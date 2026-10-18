"""Revisión automática de la fuente de normativa contra el texto de los boletines.

Comprueba que cada ``texto`` guardado aparece literal, y completo, en la página citada
(normalizando solo espacios, saltos de línea, guiones de partición y viñetas), que los
recuentos de cada anexo son los que el mantenedor escribió en ``fuentes.toml`` y que las
normas citadas siguen vigentes. Sale con código 1 y una línea por discrepancia, con el
vocabulario del doble chequeo:

* ``TEXTO``: lo guardado no es lo que dice la página (o falta parte, o el XML y el PDF difieren).
* ``PROCEDENCIA``: la página o la norma citada no existe.
* ``RELACION``: una relación apunta a algo que no existe.
* ``CODIGO``: un código mal formado, repetido o fuera de su ficha.
* ``VIGENCIA``: la ficha rige en un curso en el que una de sus normas ya está derogada.
* ``FALTA`` / ``SOBRA``: menos o más elementos que los esperados en el anexo.
* ``SIN_FUENTE``: no hay texto de la norma en la caché para comprobar.

Uso: ``python -m herramientas.normativa.comprobar --cache <dir>``.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import Any

from tiza.normativa import ErrorNormativa, Ficha, cargar
from tiza.normativa.modelo import Elemento

from . import comun

TIPOS_DE_DISCREPANCIA = (
    "TEXTO",
    "PROCEDENCIA",
    "RELACION",
    "CODIGO",
    "VIGENCIA",
    "FALTA",
    "SOBRA",
    "SIN_FUENTE",
)

_VINETA = re.compile(rf"^(?:[{comun.GUIONES_DE_VINETA}•·▪●\x02]|x)\s+")
_PARTICION = re.compile(r"(?<=\w)-\n(?=\w)")
# Marca que deja el lugar de una viñeta del PDF: una línea que empieza por viñeta es
# siempre el principio de otra unidad, aunque su texto empiece en minúscula.
_MARCA = "\x01"
# Tras el final de lo guardado, la unidad debe acabar: fin de línea y que la línea
# siguiente no sea la continuación de la frase (empieza en minúscula, salvo «b)» y «ii.»,
# las marcas de una letra y de un subapartado en romanos).
_BORDE = r"[ ]*»?[ ]*(?:\n(?!(?![a-zñ]\)|[ivx]+\.[ ])[a-záéíóúüñ])|$)"
# Los elementos que salen de una fila de tabla (el nombre del módulo, seguido de horas y
# créditos en la misma línea) no acaban donde acaba una línea: se buscan salteando cifras.
TIPOS_DE_TABLA = frozenset({"modulo"})


@dataclass(frozen=True)
class Discrepancia:
    tipo: str
    donde: str
    detalle: str = ""

    def __post_init__(self) -> None:
        if self.tipo not in TIPOS_DE_DISCREPANCIA:
            raise ValueError(f"tipo de discrepancia desconocido: {self.tipo}")

    def __str__(self) -> str:
        return (
            f"{self.tipo} {self.donde}: {self.detalle}"
            if self.detalle
            else f"{self.tipo} {self.donde}"
        )


@dataclass
class Documento:
    """El texto de una norma en la caché: páginas del PDF y, si la hay, el XML del BOE."""

    paginas: dict[int, str] = field(default_factory=dict)
    xml: str | None = None


# --- comparación literal ---------------------------------------------------------------


def _variantes(crudo: str) -> tuple[str, str]:
    """El texto de una página en las dos lecturas posibles del guion a final de línea.

    Las líneas conservan su salto (para saber dónde acaba una unidad) pero no su
    sangría, ni las viñetas del PDF, ni los espacios repetidos.
    """
    lineas = []
    for linea in comun.normalizar_unicode(crudo).replace("\xa0", " ").split("\n"):
        linea = " ".join(linea.split())
        linea = _MARCA + _VINETA.sub("", linea) if _VINETA.match(linea) else linea
        if linea:
            lineas.append(linea)
    unido = "\n".join(lineas)
    return _PARTICION.sub("", unido), _PARTICION.sub("-", unido)


def _patron(texto: str, tabla: bool = False) -> str:
    palabras = comun.normalizar_unicode(texto).replace("\xa0", " ").split()
    if not tabla:
        return rf"[\s{_MARCA}]+".join(re.escape(p) for p in palabras)
    # Fila de tabla: entre palabras, un espacio; las cifras de las otras columnas solo
    # pueden quedar en medio si el nombre salta de línea; y tras la última palabra solo
    # cifras hasta el fin de la línea. El encabezado de un optativo en el anexo II lo cierra
    # con sus horas y un punto («Programación en Python (90 horas).», que puede saltar de
    # línea), o con solo el punto: ese cierre también vale.
    union = rf"(?:[ ]+|(?:[ ]+(?:\d+|-))*[ ]*\n{_MARCA}?)"
    cuerpo = union.join(re.escape(p) for p in palabras)
    cierre = r"(?:(?:[ ]+\(\d+\s+horas\))?\.)?"
    return rf"(?<!\S){cuerpo}{cierre}(?=(?:[ ]+(?:\d+|-))*[ ]*(?:\n|$))"


def aparece(
    texto: str,
    pagina: str,
    siguiente: str = "",
    sustituciones: tuple[tuple[str, str], ...] = (),
    *,
    completo: bool = False,
    tabla: bool = False,
) -> bool:
    """¿Está ``texto`` literal en la página (normalizando espacios, particiones y viñetas)?

    ``siguiente`` es la página que sigue: un texto puede empezar en una y acabar en la
    otra. ``sustituciones`` son pares (incorrecto, correcto) de una corrección de errores
    declarada: se aplican a la página antes de comparar. Con ``completo``, además, lo
    guardado debe acabar donde acaba la unidad de la página (no ser un trozo). Con ``tabla``,
    el texto es una celda de una fila de tabla: tras ella solo pueden seguir las cifras de
    las otras columnas hasta el fin de la línea, y si el nombre ocupa dos líneas pueden
    quedar cifras entre ellas. Una regex no distingue un nombre cortado justo donde salta
    de línea de uno completo (la primera línea ya acaba en cifras): ese recorte no se detecta.

    Límite conocido del borde de ``completo``: una línea que empieza por un glifo de
    viñeta cuenta como principio de otra unidad, también si en el PDF era el salto de
    línea de una frase que seguía.
    """
    if not texto.strip():
        return False
    patron = re.compile(_patron(texto, tabla) + (_BORDE if completo and not tabla else ""))
    solo = _variantes(pagina)
    con_siguiente = _variantes(pagina + "\n" + siguiente) if siguiente else solo
    for propia, ampliada in zip(solo, con_siguiente, strict=True):
        for incorrecto, correcto in sustituciones:
            propia = propia.replace(incorrecto, correcto)
            ampliada = ampliada.replace(incorrecto, correcto)
        if any(m.start() < max(len(propia), 1) for m in patron.finditer(ampliada)):
            return True
    return False


# --- una ficha, un elemento ----------------------------------------------------------------


def _texto_total(documento: Documento) -> str:
    return "\n".join(documento.paginas[n] for n in sorted(documento.paginas))


def comprobar_elemento(
    elemento: Elemento,
    documentos: Mapping[str, Documento],
    fuentes: Mapping[str, Mapping[str, Any]],
) -> list[Discrepancia]:
    """Comprueba la procedencia de un elemento: el texto literal en su página (y en su vía)."""
    procedencia = elemento.procedencia
    documento = documentos.get(procedencia.norma)
    if documento is None or (not documento.paginas and documento.xml is None):
        return [
            Discrepancia(
                "SIN_FUENTE", elemento.codigo, f"no hay texto de «{procedencia.norma}» en la caché"
            )
        ]
    sustituciones = tuple(
        (par[0], par[1]) for par in fuentes.get(procedencia.norma, {}).get("sustituciones", [])
    )
    pagina = procedencia.pagina
    problemas: list[Discrepancia] = []
    if pagina is not None and not documento.paginas:
        return [
            Discrepancia(
                "SIN_FUENTE", elemento.codigo, f"«{procedencia.norma}» no tiene texto del PDF"
            )
        ]
    if pagina is not None and pagina not in documento.paginas:
        return [
            Discrepancia(
                "PROCEDENCIA",
                elemento.codigo,
                f"la página {pagina} no está en «{procedencia.norma}»",
            )
        ]

    tabla = elemento.tipo in TIPOS_DE_TABLA
    cmo = re.fullmatch(r"MAD\.CMO\.(\d{3})", elemento.codigo) if tabla else None

    def en_catalogo() -> bool:
        # el nombre de un módulo en el catálogo del anexo I se reparte en columnas
        if cmo is None or pagina is None:
            return False
        lineas = documento.paginas[pagina].split("\n")
        return comun.nombre_de_catalogo(lineas, f"CMO-{cmo[1]}") == elemento.texto

    def en_pdf() -> bool:
        if en_catalogo():
            return True
        if pagina is None:
            return aparece(
                elemento.texto,
                _texto_total(documento),
                sustituciones=sustituciones,
                completo=True,
                tabla=tabla,
            )
        return aparece(
            elemento.texto,
            documento.paginas[pagina],
            documento.paginas.get(pagina + 1, ""),
            sustituciones,
            completo=True,
            tabla=tabla,
        )

    def en_xml() -> bool:
        assert documento.xml is not None
        return aparece(elemento.texto, documento.xml, sustituciones=sustituciones, completo=True)

    doble_via = bool(procedencia.via)
    if pagina is not None:
        buscar = [("el PDF", en_pdf)]
        if doble_via and documento.xml is not None:
            buscar.append(("el XML del BOE", en_xml))
    elif documento.xml is not None:
        buscar = [("el XML del BOE", en_xml)]
        if doble_via and documento.paginas:
            buscar.append(("el PDF", en_pdf))
    else:
        buscar = [("el PDF", en_pdf)]
    for donde, busca in buscar:
        if not busca():
            lugar = f"la página {pagina}" if donde == "el PDF" and pagina else donde
            problemas.append(
                Discrepancia(
                    "TEXTO",
                    elemento.codigo,
                    f"no aparece literal ni completo en {lugar} de «{procedencia.norma}»: "
                    f"{elemento.texto[:60]}…",
                )
            )
    if procedencia.via:
        problemas = _con_via(elemento, problemas, documentos, fuentes)
    for via in procedencia.via:
        if via.norma not in documentos:
            problemas.append(
                Discrepancia("SIN_FUENTE", elemento.codigo, f"no hay texto de la vía «{via.norma}»")
            )
        elif (
            via.pagina is not None
            and documentos[via.norma].paginas
            and via.pagina not in documentos[via.norma].paginas
        ):
            problemas.append(
                Discrepancia(
                    "PROCEDENCIA",
                    elemento.codigo,
                    f"la página {via.pagina} de la vía no está en «{via.norma}»",
                )
            )
    return problemas


def _es_de(elemento: Elemento, norma: str, registro: Mapping[str, Any]) -> bool:
    """¿Es un elemento de ``norma``? También lo es el que su corrección declarada (``correccion_en``)
    cita, con ``norma`` como original en ``via``: sigue siendo uno de los suyos."""
    procedencia = elemento.procedencia
    if procedencia.norma == norma:
        return True
    correccion = registro.get("correccion_en")
    return (
        correccion is not None
        and procedencia.norma == correccion["norma"]
        and any(v.norma == norma for v in procedencia.via)
    )


def _relacionadas(a: str, b: str, fuentes: Mapping[str, Mapping[str, Any]]) -> bool:
    """¿Declara ``fuentes.toml`` que una de las dos normas corrige o modifica a la otra?"""

    def lista(id_: str, clave: str) -> set[str]:
        return {r.split("#")[0] for r in fuentes.get(id_, {}).get(clave, [])}

    claves = ("correcciones", "modifica", "modificada_por")
    return any(b in lista(a, c) or a in lista(b, c) for c in claves)


def _aparece_en(texto: str, pagina: int, documento: Documento, sustituciones, tabla: bool) -> bool:
    return aparece(
        texto,
        documento.paginas[pagina],
        documento.paginas.get(pagina + 1, ""),
        sustituciones,
        completo=True,
        tabla=tabla,
    )


def _plano(texto: str) -> str:
    return " ".join(comun.normalizar_unicode(texto).split())


def _nombre_en_anexo_ii(numero: str, texto: str) -> str | None:
    """El nombre antiguo de ``CMO-<numero>`` como lo escribe el anexo II («CMO-315 <nombre>
    (90 horas).»), o ``None`` si la página no trae ese módulo con su nombre."""
    encontrado = re.search(rf"CMO-{numero} (.+?) \(\d+ horas?\)", _plano(texto))
    return encontrado.group(1) if encontrado else None


def _con_via(
    elemento: Elemento,
    problemas: list[Discrepancia],
    documentos: Mapping[str, Documento],
    fuentes: Mapping[str, Mapping[str, Any]],
) -> list[Discrepancia]:
    """Lo propio de un elemento con ``via``: la norma que cita y la original están relacionadas.

    Un texto que no está en la página que cita (``problemas`` lo dice) vale si la corrige
    la norma que cita: tras aplicar las ``sustituciones`` que declara la norma original, es el
    de la página original, y la página de la corrección trae lo corregido.
    """
    procedencia = elemento.procedencia
    resultado = list(problemas)
    cmo = re.fullmatch(r"MAD\.CMO\.(\d{3})", elemento.codigo)
    for via in procedencia.via:
        if not _relacionadas(procedencia.norma, via.norma, fuentes):
            resultado.append(
                Discrepancia(
                    "RELACION",
                    elemento.codigo,
                    f"«{procedencia.norma}» no figura en fuentes.toml como corrección o "
                    f"modificación de «{via.norma}» (ni al revés)",
                )
            )
        # un módulo renombrado: la página de la original tiene que traer su nombre antiguo
        original = documentos.get(via.norma)
        if (
            cmo is not None
            and original is not None
            and via.pagina is not None
            and via.pagina in original.paginas
            and _nombre_en_anexo_ii(cmo[1], original.paginas[via.pagina]) is None
        ):
            resultado.append(
                Discrepancia(
                    "PROCEDENCIA",
                    elemento.codigo,
                    f"la página {via.pagina} de la vía «{via.norma}» no trae el nombre original "
                    f"de CMO-{cmo[1]}",
                )
            )
    if not any(p.tipo == "TEXTO" for p in problemas):
        return resultado
    tabla = elemento.tipo in TIPOS_DE_TABLA
    for via in procedencia.via:
        original = documentos.get(via.norma)
        if original is None or via.pagina is None or via.pagina not in original.paginas:
            continue
        registro = fuentes.get(via.norma, {})
        pares = tuple((p[0], p[1]) for p in registro.get("sustituciones", []))
        if not _aparece_en(elemento.texto, via.pagina, original, pares, tabla):
            # un texto del XML consolidado (descriptores): se lee con las formas del XML
            consolidado = registro.get("consolidado") or {}
            en_xml = elemento.texto
            for del_xml, publicada in consolidado.get("pares", []):
                en_xml = en_xml.replace(publicada, del_xml)
            if original.xml is None or not aparece(en_xml, original.xml, completo=True):
                continue
        # el texto es el original corregido: la página de la corrección tiene que traerlo
        pagina_original = _plano(original.paginas[via.pagina])
        corrige = documentos.get(procedencia.norma)
        pagina = procedencia.pagina
        aplicadas = [
            correcto
            for incorrecto, correcto in pares
            if incorrecto in pagina_original and correcto in _plano(elemento.texto)
        ]
        if (
            corrige is None
            or pagina is None
            or pagina not in corrige.paginas
            or not any(c in _plano(corrige.paginas[pagina]) for c in aplicadas)
        ):
            resultado = [p for p in resultado if p.tipo != "TEXTO"]
            resultado.append(
                Discrepancia(
                    "PROCEDENCIA",
                    elemento.codigo,
                    f"la página {pagina} de «{procedencia.norma}» no trae lo que corrige "
                    f"de «{via.norma}»",
                )
            )
            return resultado
        return [p for p in resultado if p.tipo != "TEXTO"]
    return resultado


def comprobar_recuentos(
    ficha: Ficha, fuentes: Mapping[str, Mapping[str, Any]]
) -> list[Discrepancia]:
    """Compara los elementos de la ficha con los recuentos escritos en ``fuentes.toml``."""
    problemas: list[Discrepancia] = []
    for norma, registro in fuentes.items():
        esperados = registro.get("recuentos", {}).get(ficha.codigo)
        if not esperados:
            continue
        for clave, esperado in esperados.items():
            tipo = comun.RECUENTOS.get(clave, clave)
            hay = sum(1 for e in ficha.elementos if e.tipo == tipo and _es_de(e, norma, registro))
            donde = f"{ficha.codigo} {clave}"
            if hay < esperado:
                problemas.append(
                    Discrepancia("FALTA", donde, f"«{norma}» tiene {esperado} y la ficha {hay}")
                )
            elif hay > esperado:
                problemas.append(
                    Discrepancia("SOBRA", donde, f"«{norma}» tiene {esperado} y la ficha {hay}")
                )
    return problemas


def _primer_dia(curso_academico: str) -> date:
    return date(int(curso_academico[:4]), 9, 1)


def comprobar_vigencia(
    ficha: Ficha, fuentes: Mapping[str, Mapping[str, Any]]
) -> list[Discrepancia]:
    """Una norma derogada no puede regir en un curso que empieza después de su derogación."""
    problemas = []
    for id_ in ficha.normas:
        registro = fuentes.get(id_, {})
        if registro.get("estado") != "derogada" or not registro.get("desde"):
            continue
        desde = date.fromisoformat(registro["desde"])
        tarde = [c for c in ficha.cursos_academicos if _primer_dia(c) >= desde]
        if tarde:
            problemas.append(
                Discrepancia(
                    "VIGENCIA",
                    ficha.codigo,
                    f"«{id_}» está derogada desde {desde.isoformat()} y la ficha rige en {tarde[0]}",
                )
            )
    return problemas


def comprobar_datos(
    raiz: Any,
    documentos: Mapping[str, Documento],
    fuentes: Mapping[str, Mapping[str, Any]],
) -> list[Discrepancia]:
    """Carga y valida los datos de ``raiz`` y comprueba todas las fichas."""
    try:
        indice = cargar(raiz=raiz)
    except ErrorNormativa as exc:
        return [Discrepancia(_tipo_de_error(exc.detalle), "datos", exc.detalle)]
    problemas: list[Discrepancia] = []
    for ficha in indice.fichas.values():
        for elemento in ficha.elementos:
            # el módulo es la propia ficha; los descriptores y los contenidos básicos
            # estatales tienen el prefijo EST.
            if (
                not (elemento.codigo == ficha.codigo and elemento.tipo == "modulo")
                and not elemento.codigo.startswith(ficha.codigo + ".")
                and not elemento.codigo.startswith("EST.")
            ):
                problemas.append(
                    Discrepancia("CODIGO", elemento.codigo, f"no cuelga de la ficha {ficha.codigo}")
                )
            problemas.extend(comprobar_elemento(elemento, documentos, fuentes))
        problemas.extend(comprobar_recuentos(ficha, fuentes))
        problemas.extend(comprobar_vigencia(ficha, fuentes))
    for norma, registro in fuentes.items():
        for codigo in registro.get("recuentos", {}):
            if codigo not in indice.fichas:
                problemas.append(
                    Discrepancia("FALTA", codigo, f"«{norma}» espera una ficha que no existe")
                )
    return problemas


def _tipo_de_error(detalle: str) -> str:
    if "relaciones" in detalle:
        return "RELACION"
    if ".norma" in detalle or "normas[" in detalle:
        return "PROCEDENCIA"
    return "CODIGO"


# --- caché y línea de órdenes ---------------------------------------------------------------


def cargar_documentos(
    cache: Path, ids: list[str], cifrados: Mapping[str, str | None] | None = None
) -> dict[str, Documento]:
    """Lee de la caché el texto de cada norma que esté (``<id>.txt`` o ``.pdf``, y ``<id>.xml``)."""
    documentos: dict[str, Documento] = {}
    for id_ in ids:
        documento = Documento()
        try:
            documento.paginas = comun.paginas_limpias(
                comun.texto_de_norma(cache, id_, (cifrados or {}).get(id_))
            )
        except FileNotFoundError:
            pass
        xml = cache / f"{id_}.xml"
        if xml.is_file():
            documento.xml = "\n".join(comun.textos_de_xml(xml.read_text(encoding="utf-8")))
        if documento.paginas or documento.xml is not None:
            documentos[id_] = documento
    return documentos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    ap.add_argument("--cache", type=Path, required=True, help="carpeta con los PDF y XML bajados")
    ap.add_argument(
        "--datos", type=Path, help="carpeta con normas/ y fichas/ (por defecto, el paquete)"
    )
    ap.add_argument("--fuentes", type=Path, default=comun.RUTA_FUENTES)
    args = ap.parse_args(argv)
    fuentes = comun.leer_fuentes(args.fuentes)
    raiz = args.datos or files("tiza.normativa").joinpath("datos")
    cifrados = {id_: r.get("cifrado") for id_, r in fuentes.items()}
    documentos = cargar_documentos(args.cache, list(fuentes), cifrados)
    problemas = comprobar_datos(raiz, documentos, fuentes)
    for problema in problemas:
        print(problema)
    if not problemas:
        print("sin discrepancias")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
