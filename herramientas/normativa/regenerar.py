"""Regenera los datos del paquete desde el manifiesto del lote (``lote.toml``).

Orden: las normas, los descriptores, el resto de fichas en el orden del manifiesto y, por
último, los requisitos de la programación (los tres salen de una sola ejecución). Para en el
primer error. Después hay que ejecutar ``comprobar``.

Uso: ``uv run python -m herramientas.normativa.regenerar --cache <dir> [--salida <datos>]``.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

RUTA_LOTE = Path(__file__).with_name("lote.toml")

# extractor del manifiesto -> (módulo, subcomando, ¿lleva --ficha?)
EXTRACTORES: dict[str, tuple[str, str | None, bool]] = {
    "descriptores": ("extraer_descriptores", None, False),
    "lomloe": ("extraer_lomloe", None, False),
    "titulo": ("extraer_fp", "titulo", True),
    "modulo": ("extraer_fp", "modulo", True),
    "transversal": ("extraer_fp", "transversal", True),
    "optativo": ("extraer_fp", "optativo", True),
    "requisitos": ("extraer_requisitos", None, False),
}
_CLAVES_LOTE = {"revisada", "cursos_academicos", "ficha"}
_CLAVES_FICHA = {"codigo", "extractor", "argumentos"}

Ejecutor = Callable[[str, list[str]], int]


class ErrorRegenerar(Exception):
    pass


@dataclass(frozen=True)
class Entrada:
    codigo: str
    extractor: str
    argumentos: tuple[str, ...]


@dataclass(frozen=True)
class Lote:
    revisada: str
    cursos_academicos: tuple[str, ...]
    fichas: tuple[Entrada, ...]


def leer_lote(ruta: Path = RUTA_LOTE) -> Lote:
    """Lee el manifiesto con claves cerradas: una desconocida o mal formada es ``ValueError``."""
    with ruta.open("rb") as f:
        bruto = tomllib.load(f)
    if set(bruto) - _CLAVES_LOTE:
        raise ValueError(f"lote: claves no permitidas {sorted(set(bruto) - _CLAVES_LOTE)}")
    revisada = bruto.get("revisada")
    cursos = bruto.get("cursos_academicos")
    fichas = bruto.get("ficha")
    if not (
        isinstance(revisada, str) and len(revisada) == 10 and revisada[4] == revisada[7] == "-"
    ):
        raise ValueError("lote: «revisada» debe ser una fecha ISO entre comillas")
    if not (isinstance(cursos, list) and cursos and all(isinstance(c, str) for c in cursos)):
        raise ValueError("lote: «cursos_academicos» debe ser una lista de textos")
    if not isinstance(fichas, list) or not fichas:
        raise ValueError("lote: falta la lista [[ficha]]")
    entradas: list[Entrada] = []
    for n, f in enumerate(fichas, start=1):
        if not isinstance(f, dict) or set(f) != _CLAVES_FICHA:
            raise ValueError(f"lote: la ficha #{n} debe tener exactamente {sorted(_CLAVES_FICHA)}")
        codigo, extractor, args = f["codigo"], f["extractor"], f["argumentos"]
        if not isinstance(codigo, str) or not codigo:
            raise ValueError(f"lote: la ficha #{n} no tiene código")
        if extractor not in EXTRACTORES:
            raise ValueError(f"lote: {codigo}: extractor desconocido «{extractor}»")
        if not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
            raise ValueError(f"lote: {codigo}: «argumentos» debe ser una lista de textos")
        entradas.append(Entrada(codigo, extractor, tuple(args)))
    codigos = [e.codigo for e in entradas]
    if len(codigos) != len(set(codigos)):
        raise ValueError("lote: hay fichas repetidas")
    return Lote(revisada, tuple(cursos), tuple(entradas))


def _en_proceso(modulo: str, argv: list[str]) -> int:
    return int(importlib.import_module(f"herramientas.normativa.{modulo}").main(argv) or 0)


def regenerar(lote: Lote, cache: Path, salida: Path, ejecutor: Ejecutor = _en_proceso) -> None:
    """Ejecuta el lote entero; el primer extractor que falla lo para con ``ErrorRegenerar``."""

    def correr(modulo: str, argv: list[str], que: str) -> None:
        if ejecutor(modulo, argv) != 0:
            raise ErrorRegenerar(f"falló {que}")

    correr("normas", ["--revisada", lote.revisada, "--salida", str(salida)], "normas")
    cursos = ",".join(lote.cursos_academicos)
    comunes = ["--cache", str(cache), "--salida", str(salida)]
    orden = sorted(
        (e for e in lote.fichas if e.extractor != "requisitos"),
        key=lambda e: e.extractor != "descriptores",  # estable: descriptores primero
    )
    for e in orden:
        modulo, sub, con_ficha = EXTRACTORES[e.extractor]
        argv = [sub] if sub else []
        if con_ficha:
            argv += ["--ficha", e.codigo]
        argv += [*e.argumentos, "--cursos-academicos", cursos, *comunes]
        correr(modulo, argv, e.codigo)
        if not (salida / "fichas" / f"{e.codigo}.json").is_file():
            raise ErrorRegenerar(f"{e.codigo}: el extractor no escribió esa ficha")
    if any(e.extractor == "requisitos" for e in lote.fichas):
        correr("extraer_requisitos", comunes, "los requisitos de la programación")
        for e in lote.fichas:
            if (
                e.extractor == "requisitos"
                and not (salida / "fichas" / f"{e.codigo}.json").is_file()
            ):
                raise ErrorRegenerar(f"{e.codigo}: los requisitos no escribieron esa ficha")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Regenera los datos del paquete desde lote.toml.")
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--salida", type=Path, help="carpeta de datos (por defecto, la del paquete)")
    ap.add_argument("--lote", type=Path, default=RUTA_LOTE)
    args = ap.parse_args(argv)
    salida = args.salida or Path(str(files("tiza.normativa").joinpath("datos")))
    try:
        regenerar(leer_lote(args.lote), args.cache, salida)
    except (ErrorRegenerar, ValueError, FileNotFoundError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    print(f"datos regenerados en {salida}; ahora, `comprobar`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
