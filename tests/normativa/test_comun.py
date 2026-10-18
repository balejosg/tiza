"""Limpieza de texto y viñetas compartidas (`herramientas/normativa/comun.py`)."""

from __future__ import annotations

import importlib
import unicodedata
from pathlib import Path
from types import ModuleType

import pytest

FUENTES = Path(__file__).parents[2] / "herramientas" / "normativa" / "fuentes"
MADRID_0373_0485 = FUENTES / "bocm-20110131-3_anexo-i_0373-0485.txt"

# El caso real de MAD.DAM.0489.ORI: el PDF del BOE trae «í» (U+00ED) y, detrás, un U+0301 suelto.
ASI_COMO_PDF = "as\u00ed\u0301 como su puesta a punto"
ASI_COMO = "as\u00ed como su puesta a punto"


@pytest.fixture(autouse=True)
def _herramientas_en_la_ruta(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))


def herramienta(nombre: str) -> ModuleType:
    return importlib.import_module(f"herramientas.normativa.{nombre}")


def test_unir_quita_la_marca_que_repite_el_acento_de_la_letra():
    assert herramienta("comun").unir([ASI_COMO_PDF]) == ASI_COMO


def test_las_lineas_limpias_tambien_la_quitan():
    comun = herramienta("comun")
    assert [l.texto for l in comun.lineas_limpias(ASI_COMO_PDF)] == [ASI_COMO]
    assert [l.texto for l in comun.lineas_de(ASI_COMO_PDF)] == [ASI_COMO]


def test_una_marca_distinta_del_acento_de_la_letra_se_conserva():
    comun = herramienta("comun")
    # «í» más una diéresis suelta no es el mismo acento: no es un duplicado
    texto = comun.unir(["as\u00ed\u0308"])
    assert unicodedata.normalize("NFD", texto) == "asi\u0301\u0308"


def test_la_marca_suelta_tras_una_letra_sin_acento_se_compone():
    assert herramienta("comun").unir(["asi\u0301 como"]) == "as\u00ed como"


def test_comprobar_acepta_el_texto_limpio_frente_a_la_pagina_con_la_marca():
    comprobar = herramienta("comprobar")
    pagina = f"   Motores de juegos, {ASI_COMO_PDF}.\n"
    assert comprobar.aparece(f"Motores de juegos, {ASI_COMO}.", pagina, completo=True)
    # y a la inversa: la comparación no depende de qué lado trae la marca
    assert comprobar.aparece(f"Motores de juegos, {ASI_COMO_PDF}.", pagina, completo=True)


def test_la_vineta_comun_reconoce_guion_raya_y_signo_menos():
    comun = herramienta("comun")
    for signo in ("-", "\u2013", "\u2014", "\u2212"):
        m = comun.VINETA.match(f"    {signo} Texto de la viñeta")
        assert m is not None and m[1] == "Texto de la viñeta", signo
    assert comun.VINETA.match("    -Sin espacio") is None
    assert comun.VINETA.match("    Texto - con guion") is None


def test_los_extractores_y_comprobar_usan_la_misma_definicion_de_vineta():
    comun = herramienta("comun")
    for nombre in ("extraer_fp", "extraer_lomloe"):
        modulo = herramienta(nombre)
        assert not hasattr(modulo, "_VINETA"), nombre
        assert not hasattr(modulo, "_VINETA_BOE"), nombre
    # `comprobar` añade a los guiones comunes los glifos propios de los PDF
    comprobar = herramienta("comprobar")
    for signo in comun.GUIONES_DE_VINETA:
        assert comprobar._VINETA.match(f"{signo} texto")
    with pytest.raises(ValueError, match="desconocido"):
        comprobar.Discrepancia("INVENTADO", "x")


def test_el_parser_de_contenidos_de_madrid_reconoce_el_signo_menos():
    fp = herramienta("extraer_fp")
    comun = herramienta("comun")
    texto = MADRID_0373_0485.read_text(encoding="utf-8")
    con_menos = texto.replace("\u2014 ", "\u2212 ")
    assert con_menos != texto
    a = fp.analizar_contenidos_madrid(comun.lineas_limpias(texto), "0373")
    b = fp.analizar_contenidos_madrid(comun.lineas_limpias(con_menos), "0373")
    assert a == b
