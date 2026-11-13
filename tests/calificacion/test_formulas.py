"""Fórmulas del calificador: texto puro, sin aula. Offline."""

from __future__ import annotations

import pytest

from tiza.calificacion.formulas import formula_resultado, formula_tope


def test_formula_resultado_sobre_100() -> None:
    assert formula_resultado("TZ_O_x", 5) == "=([[TZ_O_x]]-1)/4*100"


def test_formula_resultado_con_dos_niveles() -> None:
    assert formula_resultado("TZ_O_0123456789", 2) == "=([[TZ_O_0123456789]]-1)/1*100"


def test_formula_resultado_necesita_dos_niveles() -> None:
    for niveles in (0, 1):
        with pytest.raises(ValueError):
            formula_resultado("TZ_O_x", niveles)


def test_formula_tope_sin_notas_activas_es_la_final() -> None:
    assert formula_tope(5.0, 4.0, []) == "=[[TZ_FINAL]]"


def test_formula_tope_sobre_100() -> None:
    assert formula_tope(5.0, 4.0, ["TZ_E_RA1"]) == (
        "=min([[TZ_FINAL]],40+1000*floor(min([[TZ_E_RA1]])/50))"
    )
