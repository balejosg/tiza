"""Manifiesto del lote (`herramientas/normativa/lote.toml`) y `regenerar.py`, sin caché ni pdftotext."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import pytest

RAIZ = Path(__file__).parents[2]
FICHAS = RAIZ / "src" / "tiza" / "normativa" / "datos" / "fichas"


@pytest.fixture(autouse=True)
def _herramientas_en_la_ruta(monkeypatch):
    monkeypatch.syspath_prepend(str(RAIZ))


def regenerar() -> ModuleType:
    return importlib.import_module("herramientas.normativa.regenerar")


def test_cada_ficha_del_paquete_tiene_una_entrada_y_viceversa():
    manifiesto = regenerar().leer_lote()
    codigos = [f.codigo for f in manifiesto.fichas]
    assert len(codigos) == len(set(codigos)), "fichas repetidas en lote.toml"
    assert set(codigos) == {p.stem for p in FICHAS.glob("*.json")}


def _escribir(tmp_path, texto):
    ruta = tmp_path / "lote.toml"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


BASE = 'revisada = "2026-10-18"\ncursos_academicos = ["2026-27"]\n'
ENTRADA = '[[ficha]]\ncodigo = "X"\nextractor = "lomloe"\nargumentos = []\n'


def test_el_manifiesto_se_lee_con_claves_cerradas(tmp_path):
    r = regenerar()
    assert [f.codigo for f in r.leer_lote(_escribir(tmp_path, BASE + ENTRADA)).fichas] == ["X"]
    for malo in (
        BASE + "otra = 1\n" + ENTRADA,
        BASE + ENTRADA + 'sobra = "x"\n',
        BASE + ENTRADA.replace("lomloe", "inventado"),
        BASE + ENTRADA.replace("argumentos = []", "argumentos = [1]"),
        BASE + ENTRADA + ENTRADA,
        'cursos_academicos = ["2026-27"]\n' + ENTRADA,
        BASE.replace("2026-10-18", "ayer") + ENTRADA,
    ):
        with pytest.raises(ValueError):
            r.leer_lote(_escribir(tmp_path, malo))


def test_regenerar_para_en_el_primer_error(tmp_path):
    r = regenerar()
    llamadas = []

    def ejecutor(modulo, argv):
        llamadas.append((modulo, argv[:3]))
        return 1 if modulo == "extraer_lomloe" else 0

    lote = r.leer_lote(_escribir(tmp_path, BASE + ENTRADA + ENTRADA.replace('"X"', '"Y"')))
    with pytest.raises(r.ErrorRegenerar):
        r.regenerar(lote, tmp_path, tmp_path / "salida", ejecutor)
    assert [m for m, _ in llamadas] == ["normas", "extraer_lomloe"]
