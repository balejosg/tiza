"""El lote real de normativa (curso 2026-27): los datos del paquete, fijados con tests.

Todo sobre los JSON de `src/tiza/normativa/datos/`, offline. Los recuentos esperados son los
que el mantenedor contó en el boletín (`herramientas/normativa/fuentes.toml`), no los del
extractor.
"""

from __future__ import annotations

import importlib
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

import pytest

from tiza.normativa import cargar, consulta

RAIZ = Path(__file__).parents[2]
NORMAS = RAIZ / "src" / "tiza" / "normativa" / "datos" / "normas"

# Horas y curso de los módulos de DAM según el Decreto 103/2024 (`comprobar` no los verifica).
HORAS_DAM = {
    "0484": (205, "1"),
    "0487": (60, "1"),
    "0373": (110, "1"),
    "0485": (270, "1"),
    "0483": (205, "1"),
    "1709": (100, "1"),
    "0486": (165, "2"),
    "0488": (150, "2"),
    "0490": (135, "2"),
    "0489": (135, "2"),
    "0491": (95, "2"),
    "0179": (50, "2"),
    "1710": (70, "2"),
    "1665": (30, "2"),
    "1708": (30, "2"),
    "0492": (50, "2"),
}


HOY = date(2026, 9, 15)  # dentro del curso 2026-27, el de los datos


@pytest.fixture(autouse=True)
def sin_reloj(monkeypatch):
    """Ningún test del lote puede leer la fecha de hoy: la suite no depende del reloj."""

    def _reloj():
        raise AssertionError("este test lee el reloj: fija `hoy` o el curso académico")

    monkeypatch.setattr(consulta, "hoy_en_madrid", _reloj)


def test_la_suite_del_lote_no_depende_del_reloj():
    # con el reloj prohibido, la consulta fijada con `hoy` (aunque sea de otro año) no lo lee
    assert consulta.buscar("ampliacion", hoy=date(2026, 9, 15)).curso_academico == "2026-27"
    with pytest.raises(AssertionError, match="reloj"):
        consulta.buscar("ampliacion")
    with pytest.raises(consulta.ErrorNormativa) as e:
        consulta.buscar("ampliacion", hoy=date(2027, 10, 1))
    assert e.value.codigo == "CURSO_SIN_DATOS"


@pytest.fixture(scope="module")
def indice():
    return cargar()


@pytest.fixture(scope="module")
def comun():
    # `herramientas/` no es del paquete: solo estos tests lo ven
    sys.path.insert(0, str(RAIZ))
    try:
        return importlib.import_module("herramientas.normativa.comun")
    finally:
        sys.path.remove(str(RAIZ))


@pytest.fixture(scope="module")
def fuentes(comun):
    return comun.leer_fuentes()


def test_lote_carga():
    cargar()


def test_recuentos_por_ficha(indice, fuentes, comun):
    sin_recuentos = []
    fallos = []
    for ficha in indice.fichas.values():
        anotado = False
        for norma, registro in fuentes.items():
            esperados = registro.get("recuentos", {}).get(ficha.codigo)
            if not esperados:
                continue
            anotado = True
            for clave, esperado in esperados.items():
                tipo = comun.RECUENTOS.get(clave, clave)
                hay = sum(
                    1 for e in ficha.elementos if e.tipo == tipo and e.procedencia.norma == norma
                )
                if hay != esperado:
                    fallos.append(f"{ficha.codigo} {clave} en {norma}: {esperado} != {hay}")
        if not anotado:
            sin_recuentos.append(ficha.codigo)
    assert not sin_recuentos, f"fichas sin recuentos en fuentes.toml: {sin_recuentos}"
    assert not fallos, fallos


def test_dam_programacion_nueve_ra(indice):
    ficha = indice.fichas["MAD.DAM.0485"]
    modulo = next(e for e in ficha.elementos if e.codigo == "MAD.DAM.0485")
    assert modulo.datos == {"horas": 270, "curso": "1"}
    assert ficha.curso == "1"
    assert sum(1 for e in ficha.elementos if e.tipo == "resultado_aprendizaje") == 9


def test_horas_y_curso_de_dam(indice):
    hallados = {}
    for codigo, ficha in indice.fichas.items():
        if codigo.startswith("MAD.DAM.") and codigo != "MAD.DAM.json":
            modulo = next(e for e in ficha.elementos if e.codigo == codigo)
            hallados[codigo.removeprefix("MAD.DAM.")] = (
                modulo.datos.get("horas"),
                modulo.datos.get("curso"),
            )
    assert hallados == HORAS_DAM


def test_descriptores_citados_existen(indice):
    citados = 0
    for ficha in indice.fichas.values():
        if ficha.etapa not in ("eso", "bachillerato"):
            continue
        etapa = "ESO" if ficha.etapa == "eso" else "BACH"
        for e in ficha.elementos:
            for sigla in e.relaciones.get("descriptores", ()):
                citados += 1
                assert sigla in indice.elementos, (e.codigo, sigla)
                assert sigla.startswith(f"EST.{etapa}.DESC."), (e.codigo, sigla)
                assert indice.elementos[sigla][0].codigo == f"EST.{etapa}.DESC"
    assert citados > 0


def test_ampliacion_no_esta():
    assert consulta.buscar("ampliacion de programacion", hoy=HOY).resultados == ()
    assert not any(
        "ampliacion de programacion" in f.nombre.lower() for f in cargar().fichas.values()
    )


def test_decreto_27_2025_corregido():
    n = consulta.norma("Decreto 21/2025", hoy=HOY)
    assert n.numero == "27/2025"
    assert any(c.norma.id == "bocm-20250526-1" for c in n.correcciones)
    assert n.cita_pedida
    assert n.cita_correcta


def test_urls_oficiales(indice):
    for norma in indice.normas.values():
        permitidos = ["https://www.boe.es/", "https://www.bocm.es/"]
        if norma.boletin == "CM":
            permitidos.append("https://www.comunidad.madrid/")
        for url in (norma.url_pdf, norma.url_api):
            if url is not None:
                assert url.startswith(tuple(permitidos)), (norma.id, url)
    for ruta in NORMAS.glob("*.json"):
        texto = ruta.read_text(encoding="utf-8")
        assert "http://" not in texto, ruta.name


def test_requisitos_con_codigo_del_plan(indice):
    for ficha in ("MAD.ESO.PROG", "MAD.BACH.PROG", "MAD.FP.PROG"):
        codigos = [
            e.codigo for e in indice.fichas[ficha].elementos if e.tipo == "requisito_programacion"
        ]
        assert codigos
        assert all(re.fullmatch(rf"{ficha}\.\d+(\.\w+)*", c) for c in codigos), codigos
        assert not any(".REQ." in c for c in codigos)


def test_un_curso_academico(indice):
    assert {c for f in indice.fichas.values() for c in f.cursos_academicos} == {"2026-27"}
    catalogo = consulta.catalogo(hoy=HOY)
    assert catalogo.curso_academico == "2026-27"
    assert catalogo.curso_en_vigor is True
    assert len(catalogo.fichas) == len(indice.fichas)


def test_sin_caracteres_invisibles(indice):
    malos = []
    for f in indice.fichas.values():
        for texto, donde in [(f.nombre, f.codigo)] + [(e.texto, e.codigo) for e in f.elementos]:
            if any(unicodedata.category(c) in ("Cf", "Cc") for c in texto):
                malos.append(donde)
    assert not malos


def test_ningun_texto_tiene_marcas_combinantes(indice):
    # tras NFC, una marca combinante (Mn) suelta es un artefacto del PDF, no del boletín
    malos = []
    for f in indice.fichas.values():
        for texto, donde in [(f.nombre, f.codigo)] + [(e.texto, e.codigo) for e in f.elementos]:
            if any(unicodedata.category(c) == "Mn" for c in unicodedata.normalize("NFC", texto)):
                malos.append(donde)
    assert not malos
