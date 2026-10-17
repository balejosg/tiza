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
import unicodedata
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

_VINETA = re.compile(r"^(?:[-–—•·▪●]|x)\s+")
_PARTICION = re.compile(r"(?<=\w)-\n(?=\w)")
# Marca que deja el lugar de una viñeta del PDF: una línea que empieza por viñeta es
# siempre el principio de otra unidad, aunque su texto empiece en minúscula.
_MARCA = "\x01"
# Tras el final de lo guardado, la unidad debe acabar: fin de línea y que la línea
# siguiente no sea la continuación de la frase (empieza en minúscula, salvo «b)»).
_BORDE = r"[ ]*(?:\n(?!(?![a-z]\))[a-záéíóúüñ])|$)"
# Los elementos que salen de una fila de tabla (el nombre del módulo, seguido de horas y
# créditos en la misma línea) no acaban donde acaba una línea: se buscan salteando cifras.
TIPOS_DE_TABLA = frozenset({"modulo"})
_CIFRAS_DE_TABLA = r"(?:\s+(?:\d+|-))*"


@dataclass(frozen=True)
class Discrepancia:
    tipo: str
    donde: str
    detalle: str = ""

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
    for linea in unicodedata.normalize("NFC", crudo).replace("\xa0", " ").split("\n"):
        linea = " ".join(linea.split())
        linea = _MARCA + _VINETA.sub("", linea) if _VINETA.match(linea) else linea
        if linea:
            lineas.append(linea)
    unido = "\n".join(lineas)
    return _PARTICION.sub("", unido), _PARTICION.sub("-", unido)


def _patron(texto: str, tabla: bool = False) -> str:
    palabras = unicodedata.normalize("NFC", texto).replace("\xa0", " ").split()
    if not tabla:
        return rf"[\s{_MARCA}]+".join(re.escape(p) for p in palabras)
    # Fila de tabla: entre palabras, un espacio; las cifras de las otras columnas solo
    # pueden quedar en medio si el nombre salta de línea; y tras la última palabra solo
    # cifras hasta el fin de la línea.
    union = rf"(?:[ ]+|(?:[ ]+(?:\d+|-))*[ ]*\n{_MARCA}?)"
    cuerpo = union.join(re.escape(p) for p in palabras)
    return rf"(?<!\S){cuerpo}(?=(?:[ ]+(?:\d+|-))*[ ]*(?:\n|$))"


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

    def en_pdf() -> bool:
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
            hay = sum(1 for e in ficha.elementos if e.tipo == tipo and e.procedencia.norma == norma)
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
            if not elemento.codigo.startswith(
                ficha.codigo + "."
            ) and not elemento.codigo.startswith("EST."):
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


def cargar_documentos(cache: Path, ids: list[str]) -> dict[str, Documento]:
    """Lee de la caché el texto de cada norma que esté (``<id>.txt`` o ``.pdf``, y ``<id>.xml``)."""
    documentos: dict[str, Documento] = {}
    for id_ in ids:
        documento = Documento()
        try:
            documento.paginas = comun.paginas_limpias(comun.texto_de_norma(cache, id_))
        except FileNotFoundError:
            pass
        xml = cache / f"{id_}.xml"
        if xml.is_file():
            documento.xml = "\n".join(comun.parrafos_de_xml(xml.read_text(encoding="utf-8")))
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
    documentos = cargar_documentos(args.cache, list(fuentes))
    problemas = comprobar_datos(raiz, documentos, fuentes)
    for problema in problemas:
        print(problema)
    if not problemas:
        print("sin discrepancias")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
