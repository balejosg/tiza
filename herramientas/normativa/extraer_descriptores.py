"""Extrae los descriptores operativos del perfil de salida (anexo I) del XML del BOE.

Sirve para el RD 217/2022 (ESO) y el RD 243/2022 (Bachillerato). El anexo I pone los
descriptores en tablas de dos columnas, una por competencia clave: la primera es la etapa
anterior y la segunda la de la norma (en el RD 217/2022, «Al completar la enseñanza
básica»; en el RD 243/2022, «Al completar el Bachillerato»). Se toma la columna cuya
cabecera es la de la etapa. Cada celda trae uno o varios párrafos, y cada párrafo empieza
por su código (``CCL1.``, ``CCEC3.1``): el texto guardado es el párrafo sin el código.

Uso::

    python -m herramientas.normativa.extraer_descriptores --norma boe-a-2022-5521 \\
        --etapa bachillerato --cursos-academicos 2026-27 --cache <dir>
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

from . import comun
from .extraer_lomloe import ETAPAS, escribir_ficha

_DESCRIPTOR = re.compile(r"^([A-Z]{2,6}\d+(?:\.\d+)?)\.?\s+(\S.*)$")
NOMBRES = {"eso": "ESO", "bachillerato": "Bachillerato"}
_TABLA_DEL_PERFIL = "Al completar"  # las cabeceras de las tablas de descriptores empiezan así
# El comienzo de la cabecera de la columna de cada etapa en las tablas del anexo I.
CABECERAS = {
    "eso": "Al completar la enseñanza básica",
    "bachillerato": "Al completar el Bachillerato",
}


def _texto(elemento: ET.Element) -> str:
    return comun.normalizar("".join(elemento.itertext()))


def analizar_descriptores(xml: str, etapa: str) -> dict[str, str]:
    """``{código: texto}`` de la columna de la etapa, en el orden del anexo.

    Solo cuentan las tablas del perfil de salida (cabeceras «Al completar…»). Es
    ``ValueError`` una de ellas sin la cabecera de la etapa (o con ella repetida), un
    párrafo que no empieza por un código o un código repetido: el boletín manda y no se
    adivina nada.
    """
    cabecera = CABECERAS[etapa]
    descriptores: dict[str, str] = {}
    for tabla in ET.fromstring(xml).iter("table"):
        titulos = [_texto(th) for th in tabla.iter("th")]
        if not any(t.startswith(_TABLA_DEL_PERFIL) for t in titulos):
            continue  # otras tablas del boletín
        columnas = [i for i, t in enumerate(titulos) if t.startswith(cabecera)]
        if len(columnas) != 1:
            raise ValueError(f"la cabecera «{cabecera}» no está una vez en {titulos!r}")
        for fila in tabla.iter("tr"):
            celdas = fila.findall("td")
            if not celdas:
                continue
            celda = celdas[columnas[0]]
            parrafos = [_texto(p) for p in celda.iter("p")] or [_texto(celda)]
            for parrafo in filter(None, parrafos):
                if (m := _DESCRIPTOR.match(parrafo)) is None:
                    raise ValueError(f"no empieza por un código de descriptor: «{parrafo[:60]}»")
                if m[1] in descriptores:
                    raise ValueError(f"descriptor repetido: {m[1]}")
                descriptores[m[1]] = m[2]
    return descriptores


def ficha_descriptores(
    descriptores: dict[str, str],
    *,
    norma: str,
    etapa: str,
    cursos_academicos: Sequence[str],
    ubicacion: str = "anexo I",
) -> dict[str, Any]:
    """La ficha ``EST.<ETAPA>.DESC`` con un elemento por descriptor (procedencia sin página)."""
    abreviatura = ETAPAS[etapa]
    codigo = f"EST.{abreviatura}.DESC"
    return {
        "codigo": codigo,
        "nombre": f"Descriptores operativos del perfil de salida, {NOMBRES[etapa]}",
        "etapa": etapa,
        "curso": None,
        "cursos_academicos": list(cursos_academicos),
        "normas": [norma],
        "elementos": [
            {
                "codigo": f"{codigo}.{descriptor}",
                "tipo": "descriptor",
                "texto": texto,
                "procedencia": {"norma": norma, "ubicacion": ubicacion, "pagina": None},
                "orden": orden,
            }
            for orden, (descriptor, texto) in enumerate(descriptores.items(), start=1)
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extrae los descriptores del XML del BOE.")
    ap.add_argument("--norma", required=True, help="id de la norma, p. ej. boe-a-2022-4975")
    ap.add_argument("--etapa", required=True, choices=sorted(ETAPAS))
    ap.add_argument("--cursos-academicos", required=True, help="separados por comas")
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--salida", type=Path, help="carpeta de datos (por defecto, la del paquete)")
    args = ap.parse_args(argv)
    xml = (args.cache / f"{args.norma}.xml").read_text(encoding="utf-8")
    try:
        descriptores = analizar_descriptores(xml, args.etapa)
    except ValueError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    if not descriptores:
        print("ERROR no hay descriptores en el XML", file=sys.stderr)
        return 1
    ficha = ficha_descriptores(
        descriptores,
        norma=args.norma,
        etapa=args.etapa,
        cursos_academicos=args.cursos_academicos.split(","),
    )
    raiz = args.salida or Path(str(files("tiza.normativa").joinpath("datos")))
    print(escribir_ficha(ficha, raiz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
