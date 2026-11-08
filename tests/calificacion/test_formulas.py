"""Fórmulas del calificador: texto puro, sin aula. Offline."""

from __future__ import annotations

import pytest

from tiza.calificacion.formulas import formula_resultado, formula_tope


def test_formula_resultado() -> None:
    assert formula_resultado("TZ_O_x", 5) == "=([[TZ_O_x]]-1)/4*10"


def test_formula_resultado_con_dos_niveles() -> None:
    assert formula_resultado("TZ_O_0123456789", 2) == "=([[TZ_O_0123456789]]-1)/1*10"


def test_formula_resultado_necesita_dos_niveles() -> None:
    for niveles in (0, 1):
        with pytest.raises(ValueError):
            formula_resultado("TZ_O_x", niveles)


def test_formula_tope_sin_notas_activas_no_lleva_min() -> None:
    assert formula_tope(5.0, 4.0, []) == "=[[TZ_FINAL]]/[[TZ_K_TIZA]]*10"
    assert formula_tope(5.0, 4.0, ["TZ_NOTA_E_RA1"]) == (
        "=min([[TZ_FINAL]]/[[TZ_K_TIZA]]*10,4+1000*floor(min([[TZ_NOTA_E_RA1]])/5))"
    )
