"""Requisitos de la programación (`herramientas/normativa/extraer_requisitos.py`).

Todo sobre fragmentos reales de `herramientas/normativa/fuentes/`: los artículos 66 y 67
del Decreto 27/2025 (con las cabeceras de página del BOCM), el artículo 68 del RD 83/1996
en el XML consolidado del BOE y la instrucción segunda de las instrucciones de FP 2026-27
(un texto sin cabeceras de boletín). Sin red ni `pdftotext`.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType

import pytest

FUENTES = Path(__file__).parents[2] / "herramientas" / "normativa" / "fuentes"
DECRETO = FUENTES / "bocm-20250522-1_art-66-67.txt"
REGLAMENTO = FUENTES / "boe-a-1996-3834_art-68.xml"
INSTRUCCIONES = FUENTES / "cm-instrucciones-fp-2026-27_instruccion-segunda.txt"


@pytest.fixture(autouse=True)
def _herramientas_en_la_ruta(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))


def herramienta(nombre: str) -> ModuleType:
    return importlib.import_module(f"herramientas.normativa.{nombre}")


def fuente(**kw):
    return herramienta("extraer_requisitos").Fuente(**kw)


def decreto():
    comun = herramienta("comun")
    return fuente(lineas=comun.lineas_limpias(DECRETO.read_text(encoding="utf-8")))


def reglamento():
    return fuente(xml=REGLAMENTO.read_text(encoding="utf-8"))


def instrucciones():
    comun = herramienta("comun")
    return fuente(lineas=comun.lineas_limpias(INSTRUCCIONES.read_text(encoding="utf-8")))


def entrada(**kw):
    datos = {
        "codigo": "X.PROG.1",
        "norma": "bocm-20250522-1",
        "ubicacion": "art. 67.1",
        "pagina": 46,
        "inicio": "El equipo directivo",
        "fin": "siguientes elementos:",
        "padre": None,
    }
    datos.update(kw)
    return herramienta("extraer_requisitos").Entrada(**datos)


def texto(e, f):
    return herramienta("extraer_requisitos").extraer_texto(e, f)


# --- páginas de un texto sin cabeceras de boletín ---------------------------------------


def test_un_texto_sin_cabeceras_se_numera_por_saltos_de_pagina_y_pierde_el_pie():
    comun = herramienta("comun")
    lineas = comun.lineas_limpias(INSTRUCCIONES.read_text(encoding="utf-8"))
    assert {l.pagina for l in lineas} == {1, 2}
    assert not any(l.texto.strip().isdigit() for l in lineas)  # el «1» del pie de página
    organizacion = next(l for l in lineas if l.texto.startswith("a) La organización general"))
    assert organizacion.pagina == 2


def test_si_hay_cabeceras_no_se_numera_por_saltos():
    comun = herramienta("comun")
    assert {l.pagina for l in comun.lineas_limpias(DECRETO.read_text(encoding="utf-8"))} == {
        46,
        47,
    }


# --- el texto entre dos anclas ------------------------------------------------------------


def test_la_introduccion_de_la_lista_del_articulo_67():
    assert texto(entrada(), decreto()) == (
        "El equipo directivo coordinará la elaboración de una programación didáctica para "
        "cada ciclo formativo o curso de especialización, que se realizará de forma colegiada "
        "por parte de los departamentos de las familias profesionales y departamentos "
        "didácticos que impartan enseñanzas en el ciclo formativo correspondiente en los "
        "centros públicos, o los órganos de coordinación que realicen sus funciones en los "
        "centros privados. Este documento incluirá, al menos, los siguientes elementos:"
    )


def test_una_letra_sin_su_marca():
    e = entrada(inicio="Recursos didácticos.", fin="Recursos didácticos.", ubicacion="art. 67.1.e")
    assert texto(e, decreto()) == "Recursos didácticos."


def test_una_letra_que_salta_de_linea_recompone_las_palabras_partidas():
    e = entrada(
        inicio="Características generales del proyecto intermodular",
        fin="para su desarrollo.",
    )
    assert texto(e, decreto()) == (
        "Características generales del proyecto intermodular, incluyendo propuestas para su "
        "desarrollo."
    )


def test_un_apartado_que_cruza_de_pagina_sin_las_cabeceras_en_medio():
    e = entrada(
        inicio="Las programaciones de los módulos profesionales tendrán en cuenta",
        fin="y la prevención de la violencia de género",
    )
    resultado = texto(e, decreto())
    assert resultado.startswith("Las programaciones de los módulos profesionales tendrán")
    assert (
        "especialización, desarrollarán los objetivos generales" in resultado
    )  # «especia-» «lización»
    assert "BOCM" not in resultado and "Pág." not in resultado


def test_la_pagina_siguiente_tambien_se_busca():
    # 67.4 empieza en la 47: pedida con la 46, se encuentra en la contigua
    e = entrada(
        inicio="En las programaciones didácticas se tendrán en consideración",
        fin="para todas las personas».",
        pagina=46,
    )
    assert texto(e, decreto()).endswith("«diseño universal o diseño para todas las personas».")


def test_el_xml_consolidado_busca_en_todo_el_texto_sin_pagina():
    e = entrada(
        norma="boe-a-1996-3834",
        pagina=None,
        inicio="La programación didáctica de los departamentos incluirá",
        fin="asignados al mismo o integrados en él, como consecuencia de lo establecido en "
        "los apartados 3 y 4 del artículo 48 de este Reglamento:",
    )
    resultado = texto(e, reglamento())
    assert resultado.startswith(
        "La programación didáctica de los departamentos incluirá, necesariamente"
    )
    assert resultado.endswith("apartados 3 y 4 del artículo 48 de este Reglamento:")


def test_una_letra_del_xml():
    e = entrada(
        norma="boe-a-1996-3834",
        pagina=None,
        inicio="Las medidas de atención a la diversidad",
        fin="que las precisen.",
    )
    assert texto(e, reglamento()) == (
        "Las medidas de atención a la diversidad y las adaptaciones curriculares para los "
        "alumnos que las precisen."
    )


def test_un_texto_sin_cabeceras_usa_su_pagina_numerada():
    e = entrada(
        norma="cm-instrucciones-fp-2026-27",
        pagina=2,
        inicio="La organización general de la oferta.",
        fin="del curso académico.",
    )
    resultado = texto(e, instrucciones())
    assert resultado.startswith("La organización general de la oferta. Se consignarán")
    assert resultado.endswith("o segundo cuatrimestre del curso académico.")


# --- lo que no se adivina ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("cambio", "mensaje"),
    [
        ({"inicio": "Esto no está"}, "no aparece"),
        ({"fin": "Esto tampoco"}, "no aparece"),
        ({"inicio": "programación"}, "más de una vez"),
        ({"pagina": 90}, "no tiene la página 90"),
        ({"pagina": None}, "falta la página"),
    ],
)
def test_un_ancla_que_no_encaja_es_error(cambio, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        texto(entrada(**cambio), decreto())


def test_el_fin_no_puede_estar_antes_del_inicio():
    e = entrada(inicio="Este documento incluirá", fin="El equipo directivo")
    with pytest.raises(ValueError, match="antes"):
        texto(e, decreto())


def test_un_apartado_del_xml_no_cruza_de_parrafo():
    e = entrada(
        norma="boe-a-1996-3834",
        pagina=None,
        inicio="La programación didáctica de los departamentos incluirá",
        fin="a) En el caso de la educación secundaria",
    )
    with pytest.raises(ValueError, match="más de un párrafo"):
        texto(e, reglamento())


def test_una_norma_con_xml_sin_pagina_necesita_el_xml():
    with pytest.raises(ValueError, match="XML"):
        texto(entrada(pagina=None), decreto())


# --- fichas ------------------------------------------------------------------------------


def ficha_de_ejemplo():
    return {
        "codigo": "X.PROG",
        "nombre": "Requisitos de ejemplo",
        "etapa": "fp_gs",
        "cursos_academicos": ["2026-27"],
        "requisitos": [
            {
                "codigo": "X.PROG.1",
                "norma": "bocm-20250522-1",
                "ubicacion": "art. 67.1",
                "pagina": 46,
                "inicio": "El equipo directivo",
                "fin": "siguientes elementos:",
            },
            {
                "codigo": "X.PROG.1.a",
                "padre": "X.PROG.1",
                "norma": "bocm-20250522-1",
                "ubicacion": "art. 67.1.a",
                "pagina": 46,
                "inicio": "Identificación del título",
                "fin": "familia profesional.",
            },
            {
                "codigo": "X.PROG.2",
                "norma": "boe-a-1996-3834",
                "ubicacion": "art. 68.2.e",
                "inicio": "La metodología didáctica que se va a aplicar.",
                "fin": "que se va a aplicar.",
            },
        ],
    }


def fuentes_de_ejemplo(norma):
    return {"bocm-20250522-1": decreto(), "boe-a-1996-3834": reglamento()}[norma]


def test_la_ficha_lleva_los_elementos_en_orden_con_su_procedencia_y_su_padre():
    er = herramienta("extraer_requisitos")
    ficha = er.construir_ficha(ficha_de_ejemplo(), fuentes_de_ejemplo)
    assert ficha["codigo"] == "X.PROG" and ficha["etapa"] == "fp_gs"
    assert ficha["curso"] is None and ficha["cursos_academicos"] == ["2026-27"]
    assert ficha["normas"] == ["bocm-20250522-1", "boe-a-1996-3834"]
    uno, a, dos = ficha["elementos"]
    assert [e["orden"] for e in ficha["elementos"]] == [1, 2, 3]
    assert {e["tipo"] for e in ficha["elementos"]} == {"requisito_programacion"}
    assert "padre" not in uno and a["padre"] == "X.PROG.1"
    assert a["texto"] == (
        "Identificación del título: denominación, nivel, duración y familia profesional."
    )
    assert a["procedencia"] == {
        "norma": "bocm-20250522-1",
        "ubicacion": "art. 67.1.a",
        "pagina": 46,
    }
    assert dos["procedencia"] == {
        "norma": "boe-a-1996-3834",
        "ubicacion": "art. 68.2.e",
        "pagina": None,
    }
    json.dumps(ficha)  # serializable


def test_un_padre_que_no_esta_antes_es_error():
    er = herramienta("extraer_requisitos")
    ficha = ficha_de_ejemplo()
    ficha["requisitos"][1]["padre"] = "X.PROG.9"
    with pytest.raises(ValueError, match="padre"):
        er.construir_ficha(ficha, fuentes_de_ejemplo)


def test_un_codigo_repetido_es_error():
    er = herramienta("extraer_requisitos")
    ficha = ficha_de_ejemplo()
    ficha["requisitos"][2]["codigo"] = "X.PROG.1"
    with pytest.raises(ValueError, match="repetido"):
        er.construir_ficha(ficha, fuentes_de_ejemplo)


def test_requisitos_toml_se_lee_y_sus_fichas_son_las_tres():
    er = herramienta("extraer_requisitos")
    fichas = er.leer_requisitos(er.RUTA_REQUISITOS)
    assert [f["codigo"] for f in fichas] == ["MAD.ESO.PROG", "MAD.BACH.PROG", "MAD.FP.PROG"]
    for f in fichas:
        assert f["requisitos"], f["codigo"]
        assert all(r["codigo"].startswith(f["codigo"] + ".") for r in f["requisitos"])
