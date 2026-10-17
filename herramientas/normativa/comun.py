"""Piezas comunes: páginas del boletín, unión de líneas, ``fuentes.toml`` y ``pdftotext``.

Las funciones de análisis trabajan sobre texto. La única que lanza un proceso es
:func:`convertir_pdf`, y los tests no la llaman.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

__all__ = [
    "Linea",
    "convertir_pdf",
    "leer_fuentes",
    "lineas_de",
    "lineas_limpias",
    "norma_para_el_paquete",
    "paginas_limpias",
    "parrafos_de_xml",
    "texto_de_norma",
    "unir",
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
SOLO_MANTENEDOR = ("recuentos", "sustituciones")

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
    """
    resultado: list[Linea] = []
    anterior: int | None = None
    for trozo in texto.split("\f"):
        lineas = trozo.rstrip().split("\n")  # el salto de línea antes de «\f» no es un blanco
        pagina: int | None = None
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
                resultado.append(Linea(unicodedata.normalize("NFC", linea.rstrip()), pagina))
    return resultado


def lineas_de(texto: str) -> list[Linea]:
    """Líneas de un texto cualquiera (sin cabeceras de boletín), todas sin página."""
    return [Linea(unicodedata.normalize("NFC", l.rstrip()), None) for l in texto.split("\n")]


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
    partición de palabra («infor-» «mático»): se junta sin guion. El PDF manda, así que
    el texto guardado sale de aquí y no se corrige a mano.
    """
    texto = ""
    for linea in (l.strip() for l in lineas):
        if not linea:
            continue
        if not texto:
            texto = linea
        elif re.search(r"[^\W\d_]-$", texto) and linea[:1].islower():
            texto = texto[:-1] + linea
        else:
            texto += " " + linea
    return unicodedata.normalize("NFC", " ".join(texto.replace("\xa0", " ").split()))


# --- texto de las normas en la caché ------------------------------------------------


def convertir_pdf(pdf: Path) -> str:
    """``pdftotext -layout`` de un PDF. Es la única función que lanza el programa."""
    proceso = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proceso.stdout


def texto_de_norma(cache: Path, id_: str) -> str:
    """El texto de ``pdftotext`` de una norma: ``<id>.txt`` en la caché o, si no, el del PDF."""
    txt = cache / f"{id_}.txt"
    if not txt.is_file():
        pdf = cache / f"{id_}.pdf"
        if not pdf.is_file():
            raise FileNotFoundError(f"no hay {txt.name} ni {pdf.name} en {cache}; ¿descargar.py?")
        txt.write_text(convertir_pdf(pdf), encoding="utf-8")
    return txt.read_text(encoding="utf-8")


def parrafos_de_xml(xml: str) -> list[str]:
    """Los párrafos (``<p>``) de un XML del BOE, en orden y con los espacios normalizados.

    El XML sale de la API de datos abiertos del BOE y lo lee el mantenedor, no un docente.
    """
    raiz = ET.fromstring(xml)
    parrafos = (unir(["".join(p.itertext())]) for p in raiz.iter("p"))
    return [p for p in parrafos if p]


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
    registro["recuentos"] = _leer_recuentos(id_, entrada.get("recuentos", {}))
    registro["sustituciones"] = _leer_sustituciones(id_, entrada.get("sustituciones", []))
    return registro


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
            if clave not in RECUENTOS and clave not in RECUENTOS.values():
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
