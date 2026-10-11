"""Tests offline del XML de preguntas de un cuestionario."""

from __future__ import annotations

import base64
import xml.etree.ElementTree as ET

import pytest

from tiza.contenido import cargar
from tiza.cuestionario import FRACCIONES, fraccion_correcta, preguntas_xml

TODOS_LOS_TIPOS = """
- tipo: opcion_multiple
  enunciado: ¿Cuánto es **2 + 2**?
  opciones:
    - {texto: "4", correcta: true, retro: ¡Bien!}
    - {texto: "5"}
  retro: Repasa las sumas.
- tipo: verdadero_falso
  enunciado: El agua hierve a 100 °C.
  respuesta: falso
- tipo: respuesta_corta
  enunciado: Capital de Francia
  aceptadas: [París, Paris]
  mayusculas: true
- tipo: numerica
  enunciado: π con dos decimales
  valor: 3.14
  tolerancia: 0.005
"""


def documento(tmp_path, preguntas: str, **campos):
    extra = "".join(f"{clave}: {valor}\n" for clave, valor in campos.items())
    ruta = tmp_path / "cuestionario.md"
    ruta.write_text(
        f"---\ntipo: cuestionario\nnombre: Q\nseccion: 1\n{extra}"
        f"preguntas:\n{preguntas}---\n\nDescripción.\n",
        encoding="utf-8",
    )
    return cargar(ruta)


def arbol(tmp_path, preguntas: str, **campos) -> ET.Element:
    return ET.fromstring(preguntas_xml(documento(tmp_path, preguntas, **campos)))


def test_fracciones_que_acepta_moodle():
    assert {k: fraccion_correcta(k) for k in range(2, 11)} == {
        2: "50",
        3: "33.33333",
        4: "25",
        5: "20",
        6: "16.66667",
        7: "14.28571",
        8: "12.5",
        9: "11.11111",
        10: "10",
    }
    assert FRACCIONES[3] == "33.33333"


def test_fraccion_fuera_de_rango_falla():
    with pytest.raises(ValueError):
        fraccion_correcta(11)


def test_ida_y_vuelta_de_los_cuatro_tipos(tmp_path):
    doc = documento(tmp_path, TODOS_LOS_TIPOS)
    xml = preguntas_xml(doc)
    assert xml.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    raiz = ET.fromstring(xml)
    assert raiz.tag == "quiz"
    preguntas = raiz.findall("question")
    assert [p.get("type") for p in preguntas] == [
        "multichoice",
        "truefalse",
        "shortanswer",
        "numerical",
    ]
    assert [p.findtext("name/text") for p in preguntas] == ["P01", "P02", "P03", "P04"]
    # El HTML que se publica es exactamente el que serializó el filtro.
    primera = doc.cuestionario.preguntas[0]
    assert preguntas[0].findtext("questiontext/text") == primera.html
    assert preguntas[0].findtext("generalfeedback/text") == primera.retro_html
    assert "Repasa las sumas." in preguntas[0].findtext("generalfeedback/text")
    assert preguntas[0].findtext("defaultgrade") == "1"
    assert preguntas[0].findtext("answer/feedback/text") == primera.opciones[0].retro_html


def test_una_sola_correcta_se_marca_single(tmp_path):
    raiz = arbol(
        tmp_path,
        """
- tipo: opcion_multiple
  enunciado: x
  opciones:
    - {texto: "a", correcta: true}
    - {texto: "b"}
    - {texto: "c"}
""",
    )
    pregunta = raiz.find("question")
    assert pregunta.findtext("single") == "true"
    assert [a.get("fraction") for a in pregunta.findall("answer")] == ["100", "0", "0"]


def test_varias_correctas_reparten_la_fraccion(tmp_path):
    raiz = arbol(
        tmp_path,
        """
- tipo: opcion_multiple
  enunciado: x
  opciones:
    - {texto: "a", correcta: true}
    - {texto: "b"}
    - {texto: "c", correcta: true}
""",
    )
    pregunta = raiz.find("question")
    assert pregunta.findtext("single") == "false"
    assert [a.get("fraction") for a in pregunta.findall("answer")] == ["50", "-50", "50"]


def test_varias_correctas_usan_la_fraccion_de_moodle(tmp_path):
    raiz = arbol(
        tmp_path,
        """
- tipo: opcion_multiple
  enunciado: x
  opciones:
    - {texto: "a", correcta: true}
    - {texto: "b", correcta: true}
    - {texto: "c", correcta: true}
    - {texto: "d"}
    - {texto: "e"}
""",
    )
    fractions = [a.get("fraction") for a in raiz.findall("question/answer")]
    assert fractions == [
        "33.33333",
        "33.33333",
        "33.33333",
        "-33.33333",
        "-33.33333",
    ]


def test_verdadero_falso_marca_la_respuesta_correcta(tmp_path):
    raiz = arbol(
        tmp_path,
        """
- tipo: verdadero_falso
  enunciado: x
  respuesta: falso
""",
    )
    pregunta = raiz.find("question")
    assert [a.get("fraction") for a in pregunta.findall("answer")] == ["0", "100"]
    assert [a.findtext("text") for a in pregunta.findall("answer")] == ["true", "false"]


def test_respuesta_corta_usa_usecase_y_las_aceptadas(tmp_path):
    raiz = arbol(
        tmp_path,
        """
- tipo: respuesta_corta
  enunciado: x
  aceptadas: [París, Paris]
  mayusculas: true
""",
    )
    pregunta = raiz.find("question")
    assert pregunta.findtext("usecase") == "1"
    assert [a.findtext("text") for a in pregunta.findall("answer")] == ["París", "Paris"]
    assert [a.get("fraction") for a in pregunta.findall("answer")] == ["100", "100"]


def test_sin_mayusculas_usa_usecase_cero(tmp_path):
    raiz = arbol(
        tmp_path,
        """
- tipo: respuesta_corta
  enunciado: x
  aceptadas: [París]
""",
    )
    assert raiz.findtext("question/usecase") == "0"


def test_numerica_lleva_valor_y_tolerancia(tmp_path):
    raiz = arbol(
        tmp_path,
        """
- tipo: numerica
  enunciado: x
  valor: 3.14
  tolerancia: 0.005
""",
    )
    respuesta = raiz.find("question/answer")
    assert respuesta.findtext("text") == "3.14"
    assert respuesta.findtext("tolerance") == "0.005"


def test_numerica_entera_no_lleva_decimales(tmp_path):
    raiz = arbol(
        tmp_path,
        """
- tipo: numerica
  enunciado: x
  valor: 5
""",
    )
    respuesta = raiz.find("question/answer")
    assert respuesta.findtext("text") == "5"
    assert respuesta.findtext("tolerance") == "0"


def test_el_texto_se_escapa_y_vuelve_igual(tmp_path):
    doc = documento(
        tmp_path,
        """
- tipo: opcion_multiple
  enunciado: '2 < 3 & [enlace](https://ejemplo.org/a?x=1&y=2)'
  opciones:
    - {texto: '"comillas" & <más>', correcta: true}
    - {texto: "otra"}
""",
    )
    xml = preguntas_xml(doc)
    assert b"&amp;" in xml and b"&lt;" in xml
    assert b"<script" not in xml
    pregunta = ET.fromstring(xml).find("question")
    assert pregunta.findtext("questiontext/text") == doc.cuestionario.preguntas[0].html
    assert pregunta.findtext("answer/text") == doc.cuestionario.preguntas[0].opciones[0].html


def test_un_documento_que_no_es_cuestionario_falla(tmp_path):
    ruta = tmp_path / "pagina.md"
    ruta.write_text("---\ntipo: pagina\nnombre: P\nseccion: 1\n---\n\nx\n", encoding="utf-8")
    with pytest.raises(ValueError):
        preguntas_xml(cargar(ruta))


EMPAREJAMIENTO_YAML = """- tipo: emparejamiento
  enunciado: Une cada país con su capital.
  parejas:
    - {pregunta: Francia, respuesta: París}
    - {pregunta: "**Italia**", respuesta: Roma}
    - {pregunta: Portugal, respuesta: "Lisboa & Oporto"}
  distractores: [Madrid]
  retro: Repasa.
"""


def test_emparejamiento_en_el_xml(tmp_path):
    [pregunta] = arbol(tmp_path, EMPAREJAMIENTO_YAML).findall("question")
    assert pregunta.get("type") == "matching"
    assert pregunta.findtext("shuffleanswers") == "true"
    assert pregunta.findtext("defaultgrade") == "1"
    assert pregunta.findtext("generalfeedback/text") == "<p>Repasa.</p>\n"
    subs = pregunta.findall("subquestion")
    assert [s.findtext("answer/text") for s in subs] == [
        "París",
        "Roma",
        "Lisboa & Oporto",
        "Madrid",
    ]
    assert [s.get("format") for s in subs] == ["html"] * 4
    assert subs[0].findtext("text") == "<p>Francia</p>\n"
    assert "<strong>Italia</strong>" in subs[1].findtext("text")
    assert subs[3].findtext("text") == ""  # el distractor no tiene pregunta


def test_el_xml_del_emparejamiento_es_determinista_y_escapa(tmp_path):
    doc = documento(tmp_path, EMPAREJAMIENTO_YAML)
    assert preguntas_xml(doc) == preguntas_xml(doc)
    assert b"Lisboa &amp; Oporto" in preguntas_xml(doc)


_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

CON_IMAGENES = """- tipo: opcion_multiple
  enunciado: "Enunciado ![fig](img/f.png)"
  retro: "Retro ![fig](img/f.png)"
  opciones:
    - {texto: "A ![fig](img/f.png)", correcta: true, retro: "Bien ![fig](img/f.png)"}
    - {texto: B}
- tipo: emparejamiento
  enunciado: Une.
  parejas:
    - {pregunta: "![fig](img/f.png)", respuesta: X}
    - {pregunta: Q, respuesta: Y}
  distractores: [Z]
"""


def test_las_imagenes_viajan_adjuntas_a_cada_campo(tmp_path):
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "f.png").write_bytes(_PNG)
    doc = documento(tmp_path, CON_IMAGENES)
    nombre = doc.cuestionario.imagenes[0].nombre
    multiple, matching = ET.fromstring(preguntas_xml(doc)).findall("question")
    esperado = base64.b64encode(_PNG).decode("ascii")

    def adjuntos(nodo):
        return [
            (f.get("name"), f.get("path"), f.get("encoding"), f.text) for f in nodo.findall("file")
        ]

    entero = (nombre, "/", "base64", esperado)
    for campo in ("questiontext", "generalfeedback"):
        assert adjuntos(multiple.find(campo)) == [entero]
        assert f"@@PLUGINFILE@@/{nombre}" in multiple.findtext(f"{campo}/text")
    primera = multiple.findall("answer")[0]
    assert adjuntos(primera) == [entero] and adjuntos(primera.find("feedback")) == [entero]
    assert multiple.findall("answer")[1].findall("file") == []
    sub = matching.findall("subquestion")
    assert adjuntos(sub[0]) == [entero]
    assert sub[1].findall("file") == [] and sub[2].findall("file") == []
    assert "tiza-imagen:" not in preguntas_xml(doc).decode()


def test_el_xml_con_imagenes_es_determinista(tmp_path):
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "f.png").write_bytes(_PNG)
    assert preguntas_xml(documento(tmp_path, CON_IMAGENES)) == preguntas_xml(
        documento(tmp_path, CON_IMAGENES)
    )
