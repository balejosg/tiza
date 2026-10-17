"""Baja a una carpeta de caché (fuera del repositorio) los PDF y el XML de las normas.

Para cada norma de ``fuentes.toml`` baja su ``url_pdf`` a ``<caché>/<id>.pdf`` y comprueba
su ``sha256``: si no coincide, se para sin escribir nada. Si tiene ``url_api`` (BOE),
baja los bloques del texto consolidado a ``<caché>/<id>.xml``. Nunca se commitean.

Es, con :func:`obtener`, lo único de esta herramienta que sale a la red; los tests le dan
su propia función de descarga.

Uso: ``python -m herramientas.normativa.descargar --cache <dir>``.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from . import comun

CABECERAS_XML = {"Accept": "application/xml"}  # sin ella, la API del BOE responde 400
Obtener = Callable[[str, Mapping[str, str]], bytes]


class ErrorDescarga(Exception):
    """Una descarga que no se puede dar por buena."""


def obtener(url: str, cabeceras: Mapping[str, str]) -> bytes:
    """GET de una URL https; es la única función que usa la red."""
    if not url.startswith("https://"):
        raise ErrorDescarga(f"solo https: {url}")
    peticion = urllib.request.Request(url, headers={"User-Agent": "tiza-normativa", **cabeceras})
    with urllib.request.urlopen(peticion, timeout=60) as respuesta:  # noqa: S310
        return bytes(respuesta.read())


def bajar_texto_consolidado(url_api: str, obtener_url: Obtener = obtener) -> str:
    """Los bloques del texto consolidado de una norma del BOE, en un solo XML ``<texto>``.

    Pide el índice (``…/texto/indice``) y luego cada bloque (``…/texto/bloque/<id>``),
    siempre con ``Accept: application/xml``.
    """
    base = url_api.rstrip("/")
    indice = ET.fromstring(obtener_url(f"{base}/texto/indice", CABECERAS_XML))
    ids = [b.findtext("id") for b in indice.iter("bloque")]
    texto = ET.Element("texto")
    for id_ in (i for i in ids if i):
        respuesta = ET.fromstring(obtener_url(f"{base}/texto/bloque/{id_}", CABECERAS_XML))
        texto.extend(respuesta.iter("bloque"))
    return ET.tostring(texto, encoding="unicode")


def descargar(
    fuentes: Mapping[str, Mapping[str, Any]],
    cache: Path,
    obtener_url: Obtener = obtener,
    *,
    con_xml: bool = True,
) -> list[str]:
    """Baja lo que falta de cada norma y devuelve una línea por norma. Para al primer fallo."""
    cache.mkdir(parents=True, exist_ok=True)
    informe = []
    for id_, registro in fuentes.items():
        destino = cache / f"{id_}.pdf"
        if destino.is_file() and _sha256(destino.read_bytes()) == registro["sha256"]:
            estado = "ya estaba"
        else:
            contenido = obtener_url(registro["url_pdf"], {})
            if _sha256(contenido) != registro["sha256"]:
                raise ErrorDescarga(
                    f"{id_}: el sha256 del PDF bajado no coincide con fuentes.toml; no se escribe"
                )
            destino.write_bytes(contenido)
            estado = "bajado"
        if con_xml and registro.get("url_api"):
            ruta_xml = cache / f"{id_}.xml"
            if not ruta_xml.is_file():
                ruta_xml.write_text(
                    bajar_texto_consolidado(registro["url_api"], obtener_url), encoding="utf-8"
                )
        informe.append(f"{id_}: {estado}")
    return informe


def _sha256(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Baja los PDF y XML de fuentes.toml a la caché.")
    ap.add_argument("--cache", type=Path, required=True, help="carpeta fuera del repositorio")
    ap.add_argument("--fuentes", type=Path, default=comun.RUTA_FUENTES)
    args = ap.parse_args(argv)
    try:
        for linea in descargar(comun.leer_fuentes(args.fuentes), args.cache):
            print(linea)
    except ErrorDescarga as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
