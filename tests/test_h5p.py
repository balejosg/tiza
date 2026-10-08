"""Tests offline del paquete .h5p que genera tiza con las actividades del YAML."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from tiza.contenido import cargar
from tiza.h5p import LIBRERIAS, paquete_h5p


def documento(tmp_path, actividad: str, nombre: str = "Actividad"):
    ruta = tmp_path / "actividad.md"
    indentado = "\n".join(
        "  " + linea if linea else linea for linea in actividad.strip("\n").split("\n")
    )
    ruta.write_text(
        f"---\ntipo: h5p\nnombre: {nombre}\nseccion: 3\nactividad:\n{indentado}\n---\n\n"
        "Descripción de la actividad.\n",
        encoding="utf-8",
    )
    return cargar(ruta)


def partes(tmp_path, actividad: str, nombre: str = "Actividad"):
    paquete = paquete_h5p(documento(tmp_path, actividad, nombre))
    with zipfile.ZipFile(io.BytesIO(paquete)) as zip_:
        h5p = json.loads(zip_.read("h5p.json"))
        contenido = json.loads(zip_.read("content/content.json"))
    return h5p, contenido


RELLENAR = """
tipo: rellenar_huecos
textos:
  - "El agua hierve a [[100]] grados."
  - "La capital de Francia es [[París|Paris]]."
"""

ARRASTRAR = """
tipo: arrastrar_palabras
texto: "El [[sol]] brilla por la [[mañana]]."
distractores: [nube, lluvia]
"""

MARCAR = """
tipo: marcar_palabras
enunciado: Marca los verbos.
texto: "El niño [[come]] pan y [[bebe]] agua."
"""

TARJETAS = """
tipo: tarjetas
tarjetas:
  - {anverso: "¿Cuánto es 2 + 2?", reverso: "4"}
  - anverso: "Capital de Francia"
    reverso: "París"
"""


def test_la_tabla_de_librerias_fija_major_y_minor():
    assert LIBRERIAS == {
        "rellenar_huecos": ("H5P.Blanks", 1, 14),
        "arrastrar_palabras": ("H5P.DragText", 1, 10),
        "marcar_palabras": ("H5P.MarkTheWords", 1, 11),
        "tarjetas": ("H5P.Dialogcards", 1, 9),
    }


def test_el_paquete_es_determinista(tmp_path):
    doc = documento(tmp_path, RELLENAR)
    primero = paquete_h5p(doc)
    segundo = paquete_h5p(doc)
    assert primero == segundo
    otro = documento(tmp_path, RELLENAR, nombre="Otra")
    assert paquete_h5p(otro) != primero
    # El zip lleva exactamente h5p.json y content/content.json.
    with zipfile.ZipFile(io.BytesIO(primero)) as zip_:
        assert zip_.namelist() == ["content/content.json", "h5p.json"]


def test_h5p_json_apunta_a_la_libreria_del_tipo(tmp_path):
    h5p, _ = partes(tmp_path, RELLENAR)
    assert h5p["title"] == "Actividad"
    assert h5p["language"] == "es"
    assert h5p["mainLibrary"] == "H5P.Blanks"
    assert h5p["embedTypes"] == ["iframe"]
    assert h5p["preloadedDependencies"] == [
        {"machineName": "H5P.Blanks", "majorVersion": 1, "minorVersion": 14}
    ]


def test_rellenar_huecos_traduce_marcas_y_alternativas(tmp_path):
    _, contenido = partes(tmp_path, RELLENAR)
    assert contenido["questions"] == [
        "<p>El agua hierve a *100* grados.</p>\n",
        "<p>La capital de Francia es *París/Paris*.</p>\n",
    ]
    assert contenido["behaviour"]["caseSensitive"] is False
    assert contenido["showSolutions"] == "Mostrar solución"
    assert contenido["checkAnswer"] == "Comprobar"
    assert contenido["scoreBarLabel"] == "Has conseguido :num de un total de :total puntos"


def test_rellenar_huecos_mayusculas_y_ajustes(tmp_path):
    actividad = (
        RELLENAR + "mayusculas: true\ncalificacion: 5\nreintentar: false\nver_solucion: false\n"
    )
    _, contenido = partes(tmp_path, actividad)
    assert contenido["behaviour"]["caseSensitive"] is True
    assert contenido["behaviour"]["enableRetry"] is False
    assert contenido["behaviour"]["enableSolutionsButton"] is False


def test_el_markdown_se_renderiza_alrededor_de_las_marcas(tmp_path):
    actividad = """
tipo: rellenar_huecos
textos:
  - "La **capital** de Francia es [[París]]."
"""
    _, contenido = partes(tmp_path, actividad)
    assert contenido["questions"] == ["<p>La <strong>capital</strong> de Francia es *París*.</p>\n"]
    assert contenido["text"] == "Rellenar con las palabras que faltan"


def test_las_respuestas_escapan_html(tmp_path):
    actividad = """
tipo: rellenar_huecos
textos:
  - "Pregunta [[a<b & c]]."
"""
    _, contenido = partes(tmp_path, actividad)
    assert "a&lt;b &amp; c" in contenido["questions"][0]


def test_arrastrar_palabras_marca_las_palabras_y_los_distractores(tmp_path):
    h5p, contenido = partes(tmp_path, ARRASTRAR)
    assert h5p["mainLibrary"] == "H5P.DragText"
    assert contenido["textField"] == "El *sol* brilla por la *mañana*."
    assert contenido["distractors"] == "*nube* *lluvia*"
    assert contenido["taskDescription"] == "Arrastra las palabras a las cajas correctas"
    assert contenido["checkAnswer"] == "Comprobar"
    assert contenido["behaviour"]["enableRetry"] is True


def test_arrastrar_palabras_sin_distractores(tmp_path):
    actividad = """
tipo: arrastrar_palabras
texto: "El [[sol]] brilla."
"""
    _, contenido = partes(tmp_path, actividad)
    assert "distractors" not in contenido or contenido["distractors"] == ""


def test_marcar_palabras_usa_el_enunciado_y_marca_las_palabras(tmp_path):
    h5p, contenido = partes(tmp_path, MARCAR)
    assert h5p["mainLibrary"] == "H5P.MarkTheWords"
    assert "Marca los verbos." in contenido["taskDescription"]
    assert contenido["textField"] == "<p>El niño *come* pan y *bebe* agua.</p>\n"
    assert contenido["checkAnswerButton"] == "Comprobar"
    assert contenido["behaviour"]["showScorePoints"] is True


def test_tarjetas_lleva_los_pares_anverso_reverso(tmp_path):
    h5p, contenido = partes(tmp_path, TARJETAS)
    assert h5p["mainLibrary"] == "H5P.Dialogcards"
    assert [dialogo["text"] for dialogo in contenido["dialogs"]] == [
        "<p>¿Cuánto es 2 + 2?</p>\n",
        "<p>Capital de Francia</p>\n",
    ]
    assert [dialogo["answer"] for dialogo in contenido["dialogs"]] == [
        "<p>4</p>\n",
        "<p>París</p>\n",
    ]
    assert contenido["mode"] == "normal"
    assert contenido["answer"] == "Voltear"
    assert contenido["behaviour"]["enableRetry"] is True


def test_tarjetas_acepta_reintentar_pero_no_calificacion(tmp_path):
    actividad = TARJETAS + "reintentar: false\n"
    _, contenido = partes(tmp_path, actividad)
    assert contenido["behaviour"]["enableRetry"] is False


def test_un_documento_que_no_es_h5p_falla(tmp_path):
    ruta = tmp_path / "pagina.md"
    ruta.write_text("---\ntipo: pagina\nnombre: P\nseccion: 1\n---\n\nx\n", encoding="utf-8")
    with pytest.raises(ValueError):
        paquete_h5p(cargar(ruta))


def test_escapar_el_titulo(tmp_path):
    h5p, _ = partes(tmp_path, RELLENAR, nombre='Comillas " y & raras')
    assert h5p["title"] == 'Comillas " y & raras'


def test_no_se_cuela_html_peligroso_en_el_paquete(tmp_path):
    actividad = """
tipo: marcar_palabras
enunciado: "<script>alert(1)</script>"
texto: "El niño [[come]] pan."
"""
    with pytest.raises(Exception) as exc:
        paquete_h5p(documento(tmp_path, actividad))
    assert getattr(exc.value, "codigo", None) == "HTML_PELIGROSO"
