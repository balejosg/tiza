"""Fórmulas del calificador: texto puro, sin aula. Offline."""

from __future__ import annotations

import pytest

from tiza.calificacion.formulas import formula_resultado


def test_formula_resultado() -> None:
    assert formula_resultado("TZ_O_x", 5) == "=([[TZ_O_x]]-1)/4*10"


def test_formula_resultado_con_dos_niveles() -> None:
    assert formula_resultado("TZ_O_0123456789", 2) == "=([[TZ_O_0123456789]]-1)/1*10"


def test_formula_resultado_necesita_dos_niveles() -> None:
    for niveles in (0, 1):
        with pytest.raises(ValueError):
            formula_resultado("TZ_O_x", niveles)
