"""Escribe ``normas/<id>.json`` del paquete a partir de ``fuentes.toml``.

Cada norma de ``fuentes.toml`` pasa al paquete sin las claves del mantenedor
(``recuentos`` y ``sustituciones``) y con la fecha de su revisión. Se omiten las claves
opcionales vacías. Lo único que no sale de ``fuentes.toml`` es ``revisada``.

Uso::

    python -m herramientas.normativa.normas --revisada 2026-10-18 [--salida <datos>]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

from . import comun

# El orden de las claves en el JSON: el de las normas de ejemplo del cargador.
ORDEN = (
    "id",
    "rango",
    "numero",
    "fecha",
    "titulo",
    "boletin",
    "url_pdf",
    "url_api",
    "sha256",
    "correcciones",
    "modifica",
    "modificada_por",
    "estado",
    "derogada_por",
    "desde",
    "derogaciones_parciales",
    "citas",
    "revisada",
)


def norma_json(registro: dict[str, Any], revisada: str) -> dict[str, Any]:
    """La norma tal como va a ``normas/<id>.json``: claves en orden y sin las vacías."""
    norma = {**comun.norma_para_el_paquete(registro), "revisada": revisada}
    return {c: norma[c] for c in ORDEN if norma.get(c) not in (None, [])}


def escribir_normas(fuentes: dict[str, dict[str, Any]], revisada: str, raiz: Path) -> list[Path]:
    """Escribe una norma por registro bajo ``raiz/normas`` y devuelve las rutas."""
    carpeta = raiz / "normas"
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas = []
    for id_, registro in fuentes.items():
        ruta = carpeta / f"{id_}.json"
        texto = json.dumps(norma_json(registro, revisada), ensure_ascii=False, indent=2)
        ruta.write_text(texto + "\n", encoding="utf-8")
        rutas.append(ruta)
    return rutas


def _fecha(valor: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        raise argparse.ArgumentTypeError("debe ser una fecha ISO (AAAA-MM-DD)")
    return valor


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Escribe las normas del paquete desde fuentes.toml.")
    ap.add_argument("--revisada", required=True, type=_fecha, help="fecha de la revisión")
    ap.add_argument("--fuentes", type=Path, default=comun.RUTA_FUENTES)
    ap.add_argument("--salida", type=Path, help="carpeta de datos (por defecto, la del paquete)")
    args = ap.parse_args(argv)
    raiz = args.salida or Path(str(files("tiza.normativa").joinpath("datos")))
    rutas = escribir_normas(comun.leer_fuentes(args.fuentes), args.revisada, raiz)
    print(f"{len(rutas)} normas escritas en {raiz / 'normas'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
