"""Piezas comunes: páginas del boletín, unión de líneas, ``fuentes.toml`` y ``pdftotext``.

Las funciones de análisis trabajan sobre texto. La única que lanza un proceso es
:func:`convertir_pdf`, y los tests no la llaman.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import tomllib
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

from tiza.normativa.modelo import TIPOS_ELEMENTO

from .cifrado import CIFRADOS, comprobar_descifrado, parchear_pdf

__all__ = [
    "GUIONES_DE_VINETA",
    "Linea",
    "convertir_pdf",
    "leer_fuentes",
    "nombre_de_catalogo",
    "procedencia_corregida",
    "lineas_de",
    "lineas_limpias",
    "norma_para_el_paquete",
    "normalizar",
    "normalizar_unicode",
    "paginas_limpias",
    "texto_de_norma",
    "textos_de_xml",
    "unir",
    "VINETA",
]

RUTA_FUENTES = Path(__file__).with_name("fuentes.toml")

# Claves de cada norma en fuentes.toml: las del paquete (como en normas/*.json, menos
# «revisada», que pone quien extrae) y las dos que solo usa el mantenedor.
_OBLIGATORIAS = (
    "id",
    "rango",
    "numero",
    "fecha",
    "titulo",
    "boletin",
    "url_pdf",
    "sha256",
    "estado",
)
_OPCIONALES_TEXTO = ("url_api", "derogada_por", "desde")
_OPCIONALES_LISTA = (
    "correcciones",
    "modifica",
    "modificada_por",
    "derogaciones_parciales",
    "citas",
)
SOLO_MANTENEDOR = ("recuentos", "sustituciones", "cifrado", "correccion_en", "consolidado")

# Los recuentos se nombran como se habla del anexo; cualquier tipo de elemento vale tal cual.
RECUENTOS = {
    "competencias": "competencia_especifica",
    "criterios": "criterio",
    "bloques": "bloque_contenidos",
    "contenidos": "contenido",
    "descriptores": "descriptor",
    "resultados": "resultado_aprendizaje",
    "criterios_fp": "criterio_fp",
    "contenidos_basicos": "contenido_basico",
}


# Las viñetas de guion del boletín: guion, raya y signo menos (U+2212). Los extractores y
# `comprobar` comparten esta definición; cada uno añade las suyas (la «x», el «•», el glifo
# de apartado) donde le hacen falta.
GUIONES_DE_VINETA = "-–—−"
VINETA = re.compile(rf"^\s*[{GUIONES_DE_VINETA}]\s+(\S.*)$")


def normalizar_unicode(texto: str) -> str:
    """NFC y sin la marca combinante que repite el acento que la letra ya lleva.

    El PDF del BOE trae a veces «í» precompuesta seguida de un U+0301 suelto (la palabra «así» con ese U+0301 de más): un
    artefacto de la extracción, no del boletín impreso. Se quita solo la marca que sigue a
    una letra cuya descomposición ya acaba en esa misma marca; cualquier otra se conserva
    (y el cargador de datos rechaza las que queden).
    """
    salida: list[str] = []
    for c in unicodedata.normalize("NFC", texto):
        if (
            salida
            and unicodedata.category(c) == "Mn"
            and unicodedata.normalize("NFD", salida[-1]).endswith(c)
        ):
            continue
        salida.append(c)
    return "".join(salida)


class Linea(NamedTuple):
    """Una línea de texto de boletín ya limpia y la página (del boletín) en la que está."""

    texto: str
    pagina: int | None


# --- páginas del boletín ---------------------------------------------------------

_CABECERA = re.compile(r"BOLET[ÍI]N OFICIAL|B\.O\.C\.M\.|\bPág\.\s*\d+|\bSec\.\s*[IVX]+\.")
_NUMERO_DE_PAGINA = re.compile(r"\bPág\.\s*(\d+)")
_SELLO = re.compile(r"^\s*(?:BOCM-\d{6,8}(?:-\d+)?|cve: BOE-\S+|Verificable en \S+.*)\s*$")


def lineas_limpias(texto: str) -> list[Linea]:
    """Las líneas del texto de ``pdftotext -layout`` sin cabeceras ni sellos, con su página.

    ``pdftotext`` pone un salto de página (``\\f``) al principio de la cabecera de cada
    página. El sello lateral del boletín (``BOCM-2023…``) cae en mitad del texto y se va
    con las líneas en blanco que lo siguen; también se van las del principio de cada
    página. Las demás líneas en blanco se conservan, una por tramo: separan de verdad un
    apartado de otro.

    Si el texto no trae ninguna cabecera de boletín («Pág. n»), las páginas son las que
    marcan los saltos de página, desde la 1, y se quita el número del pie de cada una.
    """
    resultado: list[Linea] = []
    anterior: int | None = None
    trozos = texto.split("\f")
    # Un texto sin cabeceras de boletín (una resolución de la web de la Comunidad) no trae
    # «Pág. n»: las páginas se numeran por los saltos de página y se quita el número del pie.
    sin_cabeceras = not any(_NUMERO_DE_PAGINA.search(t) for t in trozos)
    for n, trozo in enumerate(trozos, start=1):
        lineas = trozo.rstrip().split("\n")  # el salto de línea antes de «\f» no es un blanco
        if sin_cabeceras and lineas[-1].strip() == str(n):
            lineas = lineas[:-1]
        pagina: int | None = n if sin_cabeceras else None
        cabecera: set[int] = set()
        vistas = 0
        for i, linea in enumerate(lineas):
            if not linea.strip():
                continue
            vistas += 1
            if vistas > 4:
                break
            if _CABECERA.search(linea):
                cabecera.add(i)
                if (m := _NUMERO_DE_PAGINA.search(linea)) is not None:
                    pagina = int(m[1])
        if pagina is None and anterior is not None:
            pagina = anterior + 1
        anterior = pagina
        descartar_blancos = True
        for i, linea in enumerate(lineas):
            if i in cabecera or _SELLO.match(linea):
                descartar_blancos = True
            elif not linea.strip():
                if not descartar_blancos and (not resultado or resultado[-1].texto):
                    resultado.append(Linea("", pagina))
            else:
                descartar_blancos = False
                resultado.append(Linea(normalizar_unicode(linea.rstrip()), pagina))
    return resultado


def lineas_de(texto: str) -> list[Linea]:
    """Líneas de un texto cualquiera (sin cabeceras de boletín), todas sin página."""
    return [Linea(normalizar_unicode(l.rstrip()), None) for l in texto.split("\n")]


def paginas_limpias(texto: str) -> dict[int, str]:
    """El texto limpio de cada página del boletín, por número de página."""
    por_pagina: dict[int, list[str]] = {}
    for linea in lineas_limpias(texto):
        if linea.pagina is not None:
            por_pagina.setdefault(linea.pagina, []).append(linea.texto)
    return {n: "\n".join(lineas).strip("\n") for n, lineas in por_pagina.items()}


def unir(lineas: Iterable[str]) -> str:
    """Une líneas de un mismo párrafo: espacios simples, NFC y palabras partidas recompuestas.

    Si una línea acaba en letra y guion y la siguiente empieza en minúscula, es una
    partición de palabra («infor-» «mático»): se junta sin guion. Si empieza en mayúscula es
    un compuesto con guion que salta de línea («ERP-» «CRM»): se junta sin espacio y con el
    guion. El PDF manda, así que el texto guardado sale de aquí y no se corrige a mano.
    """
    texto = ""
    for linea in (l.strip() for l in lineas):
        if not linea:
            continue
        if not texto:
            texto = linea
        elif re.search(r"[^\W\d_]-$", texto) and linea[:1].islower():
            texto = texto[:-1] + linea
        elif re.search(r"[^\W\d_]-$", texto) and linea[:1].isupper():
            texto += linea
        else:
            texto += " " + linea
    return normalizar_unicode(" ".join(texto.replace("\xa0", " ").split()))


def normalizar(texto: str) -> str:
    """Un texto suelto (una celda, un párrafo del XML) como lo deja :func:`unir`."""
    return unir([texto])


# --- texto de las normas en la caché ------------------------------------------------


def convertir_pdf(pdf: Path, cifrado: str | None = None) -> str:
    """``pdftotext -layout`` de un PDF. Es la única función que lanza el programa.

    Con ``cifrado`` (el de la norma en ``fuentes.toml``), el PDF se descifra antes en una
    copia temporal (:mod:`.cifrado`) y el texto resultante se comprueba: ni un glifo sin
    tabla ni un carácter de control.
    """
    if cifrado is not None:
        with tempfile.TemporaryDirectory() as carpeta:
            copia = Path(carpeta) / "descifrado.pdf"
            copia.write_bytes(parchear_pdf(pdf.read_bytes(), cifrado))
            texto = convertir_pdf(copia)
        comprobar_descifrado(texto)
        return texto
    proceso = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proceso.stdout


def texto_de_norma(cache: Path, id_: str, cifrado: str | None = None) -> str:
    """El texto de ``pdftotext`` de una norma: ``<id>.txt`` en la caché o, si no, el del PDF.

    ``cifrado``: el de la norma en ``fuentes.toml``; el texto de la caché se comprueba igual
    (un ``.txt`` sacado sin descifrar se rechaza: bórralo para que se vuelva a sacar).
    """
    txt = cache / f"{id_}.txt"
    if not txt.is_file():
        pdf = cache / f"{id_}.pdf"
        if not pdf.is_file():
            raise FileNotFoundError(f"no hay {txt.name} ni {pdf.name} en {cache}; ¿descargar.py?")
        txt.write_text(convertir_pdf(pdf, cifrado), encoding="utf-8")
    texto = txt.read_text(encoding="utf-8")
    if cifrado is not None:
        comprobar_descifrado(texto)
    return texto


def textos_de_xml(xml: str) -> list[str]:
    """Los párrafos de un XML del BOE y las celdas de tabla sin párrafos, en orden.

    Los descriptores del perfil de salida son celdas (``<td>``) con el texto directo, sin
    ``<p>``; las celdas con ``<p>`` ya salen por sus párrafos.
    """
    raiz = ET.fromstring(xml)
    textos = (
        unir(["".join(e.itertext())])
        for e in raiz.iter()
        if e.tag == "p" or (e.tag in ("td", "th") and e.find(".//p") is None)
    )
    return [t for t in textos if t]


# --- fuentes.toml -------------------------------------------------------------------


def leer_fuentes(ruta: Path = RUTA_FUENTES) -> dict[str, dict[str, Any]]:
    """Lee ``fuentes.toml`` (una tabla ``[[norma]]`` por norma) y devuelve sus registros por id.

    Cada registro lleva todas las claves de la norma (las opcionales vacías o ``None``) y
    las dos del mantenedor: ``recuentos`` (por código de ficha, cuántos elementos de cada
    tipo hay en la norma) y ``sustituciones`` (pares «incorrecto», «correcto» de una
    corrección de errores). Una clave desconocida o mal formada es ``ValueError``.
    """
    with ruta.open("rb") as f:
        bruto = tomllib.load(f)
    normas = bruto.get("norma")
    if not isinstance(normas, list):
        raise ValueError(f"{ruta.name}: falta la lista [[norma]]")
    registros: dict[str, dict[str, Any]] = {}
    for n, entrada in enumerate(normas, start=1):
        id_ = entrada.get("id", f"#{n}") if isinstance(entrada, dict) else f"#{n}"
        if id_ in registros:
            raise ValueError(f"{id_}: norma repetida")
        registros[id_] = _leer_registro(id_, entrada)
    return registros


def _leer_registro(id_: str, entrada: Any) -> dict[str, Any]:
    if not isinstance(entrada, dict):
        raise ValueError(f"{id_}: debe ser una tabla")
    permitidas = (*_OBLIGATORIAS, *_OPCIONALES_TEXTO, *_OPCIONALES_LISTA, *SOLO_MANTENEDOR)
    for clave in entrada:
        if clave not in permitidas:
            raise ValueError(f"{id_}: clave no permitida «{clave}»")
    for clave in _OBLIGATORIAS:
        if clave not in entrada:
            raise ValueError(f"{id_}: falta «{clave}»")
    registro: dict[str, Any] = {}
    for clave in (*_OBLIGATORIAS, *_OPCIONALES_TEXTO):
        valor = entrada.get(clave)
        registro[clave] = valor if valor is None or isinstance(valor, str) else _como_texto(valor)
    for clave in _OPCIONALES_LISTA:
        valor = entrada.get(clave, [])
        if not isinstance(valor, list) or not all(isinstance(v, str) for v in valor):
            raise ValueError(f"{id_}: «{clave}» debe ser una lista de textos")
        registro[clave] = list(valor)
    if not registro["url_pdf"].startswith("https://"):
        raise ValueError(f"{id_}: «url_pdf» debe ser https")
    cifrado = entrada.get("cifrado")
    if cifrado is not None and cifrado not in CIFRADOS:
        raise ValueError(f"{id_}: cifrado desconocido «{cifrado}»")
    registro["cifrado"] = cifrado
    registro["recuentos"] = _leer_recuentos(id_, entrada.get("recuentos", {}))
    registro["sustituciones"] = _leer_sustituciones(id_, entrada.get("sustituciones", []))
    registro["correccion_en"] = _leer_correccion_en(id_, entrada, registro)
    registro["consolidado"] = _leer_consolidado(id_, entrada.get("consolidado"))
    return registro


def _leer_correccion_en(
    id_: str, entrada: dict[str, Any], registro: dict[str, Any]
) -> dict[str, Any] | None:
    """Dónde está, en la norma que corrige o modifica ésta, lo que hacen las ``sustituciones``."""
    bruto = entrada.get("correccion_en")
    if bruto is None:
        return None
    if not (
        isinstance(bruto, dict)
        and set(bruto) == {"norma", "ubicacion", "pagina"}
        and isinstance(bruto["norma"], str)
        and isinstance(bruto["ubicacion"], str)
        and bruto["ubicacion"]
        and type(bruto["pagina"]) is int
        and bruto["pagina"] > 0
    ):
        raise ValueError(f"{id_}: «correccion_en» debe tener norma, ubicacion y pagina")
    relacionadas = {
        r.split("#")[0] for r in (*registro["correcciones"], *registro["modificada_por"])
    }
    if bruto["norma"] not in relacionadas:
        raise ValueError(
            f"{id_}: «correccion_en» cita «{bruto['norma']}», que no la corrige ni la modifica"
        )
    if not entrada.get("sustituciones"):
        raise ValueError(f"{id_}: «correccion_en» sin «sustituciones» que corregir")
    return dict(bruto)


def _leer_consolidado(id_: str, bruto: Any) -> dict[str, Any] | None:
    """La lectura del XML consolidado que difiere de la corrección publicada.

    ``pares`` son (forma del consolidado, forma de la corrección publicada) y ``pagina``,
    la del PDF original donde está lo corregido.
    """
    if bruto is None:
        return None
    if not (
        isinstance(bruto, dict)
        and set(bruto) == {"pagina", "pares"}
        and type(bruto["pagina"]) is int
        and bruto["pagina"] > 0
    ):
        raise ValueError(f"{id_}: «consolidado» debe tener pagina y pares")
    return {"pagina": bruto["pagina"], "pares": _leer_sustituciones(id_, bruto["pares"])}


def _como_texto(valor: Any) -> str:
    if hasattr(valor, "isoformat"):  # las fechas de TOML sin comillas
        return str(valor.isoformat())
    raise ValueError(f"valor no válido «{valor!r}»")


def _leer_recuentos(id_: str, bruto: Any) -> dict[str, dict[str, int]]:
    if not isinstance(bruto, dict):
        raise ValueError(f"{id_}: «recuentos» debe ser una tabla por código de ficha")
    recuentos: dict[str, dict[str, int]] = {}
    for ficha, cuentas in bruto.items():
        if not isinstance(cuentas, dict):
            raise ValueError(f"{id_}: recuentos de «{ficha}» debe ser una tabla")
        for clave, valor in cuentas.items():
            if clave not in RECUENTOS and clave not in TIPOS_ELEMENTO:
                raise ValueError(f"{id_}: recuentos: «{clave}» no es un tipo de elemento")
            if type(valor) is not int or valor < 0:
                raise ValueError(f"{id_}: recuentos: «{clave}» debe ser un entero")
        recuentos[ficha] = dict(cuentas)
    return recuentos


def _leer_sustituciones(id_: str, bruto: Any) -> list[list[str]]:
    if not isinstance(bruto, list):
        raise ValueError(f"{id_}: «sustituciones» debe ser una lista de pares")
    pares: list[list[str]] = []
    for par in bruto:
        if not (
            isinstance(par, list) and len(par) == 2 and all(isinstance(t, str) and t for t in par)
        ):
            raise ValueError(f"{id_}: «sustituciones» son pares [incorrecto, correcto]")
        pares.append(list(par))
    return pares


def norma_para_el_paquete(registro: dict[str, Any]) -> dict[str, Any]:
    """El registro sin las claves del mantenedor: lo que puede ir a ``normas/<id>.json``."""
    return {c: v for c, v in registro.items() if c not in SOLO_MANTENEDOR}


def procedencia_corregida(original: dict[str, Any], registro: dict[str, Any]) -> dict[str, Any]:
    """La procedencia de un texto que una norma posterior corrige o renombra.

    ``norma`` pasa a ser la que corrige (con su ubicación y página, que declara ``fuentes.toml``
    en ``correccion_en``) y ``via``, el lugar original (``original``, sin ``via``).
    """
    correccion = registro.get("correccion_en")
    if correccion is None:
        raise ValueError(f"«{original['norma']}» no declara «correccion_en» en fuentes.toml")
    if original.get("via"):
        raise ValueError("una procedencia que ya tiene vía no se corrige otra vez")
    return {
        "norma": correccion["norma"],
        "ubicacion": correccion["ubicacion"],
        "pagina": correccion["pagina"],
        "via": [dict(original)],
    }


# --- catálogo en columnas ---------------------------------------------------------------------

_FAMILIA_INICIO = re.compile(r"Informática\s+y(?=\s)")
_FAMILIA_FIN = re.compile(r"^\s*(?:CMO-\s*\d{3}\s+[A-Z]{3}\s+)?[Cc]omunicaciones\b")
_CODIGO_DE_FILA = re.compile(r"CMO-\s*\d{3}\b")
_COLA_DE_FILA = re.compile(r"\s{3,}.*$")  # las horas y la atribución, tras un hueco ancho


def _columna_del_nombre(lineas: list[str], cerca_de: int) -> int | None:
    """Dónde empieza el nombre del módulo: pegado a la «Informática y» de la familia más cercana.

    La sangría cambia de una página a otra, así que se busca junto a la fila, no en todo el texto.
    """
    for distancia in range(0, 9):
        for i in {cerca_de - distancia, cerca_de + distancia}:
            if 0 <= i < len(lineas) and (
                m := re.search(r"Informática\s+y(\s{1,4})(?=[^\s\d])", lineas[i])
            ):
                return m.end()
    return None


def nombre_de_catalogo(lineas: list[str], codigo: str) -> str | None:
    """El nombre del módulo ``codigo`` («CMO-316») en el catálogo del anexo I, en columnas.

    La familia («Informática y» / «comunicaciones») ocupa dos líneas a ambos lados de la del
    código, y el nombre se reparte en ellas, en la columna siguiente: se lee esa columna. Un
    nombre de tres líneas desborda una línea por arriba o por abajo. ``None`` si no hay
    nombre que leer (los transversales, que no lo traen).
    """
    fila = re.compile(rf"CMO-\s*{re.escape(codigo.removeprefix('CMO-'))}\b")
    posicion = next((i for i, l in enumerate(lineas) if fila.search(l)), None)
    if posicion is None:
        return None
    columna = _columna_del_nombre(lineas, posicion)
    if columna is None:
        return None
    arriba = next(
        (
            i
            for i in range(posicion, max(posicion - 3, -1), -1)
            if _FAMILIA_INICIO.search(lineas[i])
        ),
        None,
    )
    abajo = next(
        (
            i
            for i in range(posicion, min(posicion + 3, len(lineas)))
            if _FAMILIA_FIN.match(lineas[i])
        ),
        None,
    )
    if arriba is None or abajo is None:
        return None

    def parte(i: int) -> str:
        resto = lineas[i][columna:]
        return _COLA_DE_FILA.sub("", resto).strip()

    def es_de_nombre(i: int) -> bool:
        linea = lineas[i]
        return (
            bool(linea.strip())
            and not _CODIGO_DE_FILA.search(linea)
            and not _FAMILIA_INICIO.search(linea)
            and not _FAMILIA_FIN.match(linea)
            and linea[:columna].strip() == ""
        )

    indices = list(range(arriba, abajo + 1))
    if arriba > 0 and es_de_nombre(arriba - 1) and parte(arriba - 1):
        indices.insert(0, arriba - 1)
    if abajo + 1 < len(lineas) and es_de_nombre(abajo + 1) and parte(abajo + 1):
        indices.append(abajo + 1)
    partes = [parte(i) for i in indices]
    return unir([p for p in partes if p]) or None
