"""Extrae los descriptores operativos del perfil de salida (anexo I) del XML del BOE.

Sirve para el RD 217/2022 (ESO) y el RD 243/2022 (Bachillerato): cada descriptor es un
párrafo que empieza por su código (``CCL1.``, ``CCEC4.1.``). Si un código sale más de una
vez (las tablas del anexo ponen a la vez los descriptores de la etapa anterior), se
queda con la aparición que se pida, por defecto la última: la de la etapa.

Uso::

    python -m herramientas.normativa.extraer_descriptores --norma boe-a-2022-4975 \\
        --etapa bachillerato --cursos-academicos 2023-24,2024-25 --cache <dir>
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

from . import comun
from .extraer_lomloe import ETAPAS, escribir_ficha

_DESCRIPTOR = re.compile(r"^([A-Z]{2,6}\d+(?:\.\d+)?)\.?\s+(\S.*)$")
NOMBRES = {"eso": "ESO", "bachillerato": "Bachillerato"}


def analizar_descriptores(xml: str, ocurrencia: int = -1) -> dict[str, str]:
    """``{código: texto}`` de los descriptores del XML, en el orden en que salen."""
    vistos: dict[str, list[str]] = {}
    for parrafo in comun.parrafos_de_xml(xml):
        if (m := _DESCRIPTOR.match(parrafo)) is not None:
            vistos.setdefault(m[1], []).append(m[2])
    return {codigo: textos[ocurrencia] for codigo, textos in vistos.items()}


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
    ap.add_argument("--ocurrencia", type=int, default=-1, help="cuál, si un código se repite")
    ap.add_argument("--salida", type=Path, help="carpeta de datos (por defecto, la del paquete)")
    args = ap.parse_args(argv)
    xml = (args.cache / f"{args.norma}.xml").read_text(encoding="utf-8")
    descriptores = analizar_descriptores(xml, args.ocurrencia)
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
