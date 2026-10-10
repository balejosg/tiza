"""Garantías de privacidad de las fechas: tiza no toca excepciones por alumno ni grupos."""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "tiza"

# Excepciones de fecha por alumno (prórrogas, overrides) y agrupamientos: revelan
# adaptaciones y datos del alumnado. Ningún módulo de tiza debe nombrarlos.
PROHIBIDO = (
    "overrides.php",
    "grantextension",
    "mod/quiz/override",
    "mod/assign/override",
    "groupings",
)


def test_ningun_modulo_de_tiza_toca_excepciones_de_fecha_ni_agrupamientos():
    for ruta in SRC.rglob("*.py"):
        texto = ruta.read_text(encoding="utf-8")
        for termino in PROHIBIDO:
            assert termino not in texto, f"{ruta.name} menciona «{termino}»"
