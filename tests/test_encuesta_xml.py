"""XML puro de las preguntas de una encuesta anónima (offline, sin red)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tiza.contenido import cargar
from tiza.encuesta import items_xml

FIXTURE = Path(__file__).parent / "encuesta-export.xml"

TODAS = """\
- tipo: informacion
  texto: "Aviso con ]]> dentro."
- tipo: escala
  enunciado: ¿Cómo te has sentido?
  opciones: [Muy mal, Mal, Normal, Bien, Muy bien]
  obligatoria: true
- tipo: opcion
  enunciado: ¿Qué has usado?
  opciones: [Apuntes, Pizarra]
- tipo: opcion
  enunciado: ¿Qué has usado además?
  opciones: [Lectura, Vídeo]
  multiple: true
- tipo: opcion
  enunciado: ¿Cuándo estudias?
  opciones: [Mañana, Tarde]
  desplegable: true
- tipo: texto
  enunciado: ¿Qué te ha gustado?
- tipo: texto_corto
  enunciado: Una palabra
- tipo: numero
  enunciado: Del 0 al 10
  minimo: 0
  maximo: 10
- tipo: numero
  enunciado: Sin límites
"""


def documento(tmp_path, preguntas: str = TODAS):
    ruta = tmp_path / "encuesta.md"
    ruta.write_text(
        "---\ntipo: encuesta\nnombre: Encuesta\nseccion: 1\n"
        f"preguntas:\n{preguntas}---\n\nDescripción.\n",
        encoding="utf-8",
        newline="\n",
    )
    return cargar(ruta, raiz=tmp_path)


def items(xml: bytes) -> list[ET.Element]:
    return ET.fromstring(xml).findall("ITEMS/ITEM")


def campo(item: ET.Element, nombre: str) -> str:
    return item.findtext(nombre) or ""


class TestFormato:
    def test_la_cabecera_y_los_items(self, tmp_path):
        xml = items_xml(documento(tmp_path))
        assert xml.startswith(
            b'<?xml version="1.0" encoding="UTF-8" ?>\n'
            b'<FEEDBACK VERSION="200701" COMMENT="XML-Importfile for mod/feedback"><ITEMS>'
        )
        assert [item.get("TYPE") for item in items(xml)] == [
            "label",
            "multichoicerated",
            "multichoice",
            "multichoice",
            "multichoice",
            "textarea",
            "textfield",
            "numeric",
            "numeric",
        ]

    def test_los_items_llevan_los_campos_de_moodle(self, tmp_path):
        [label, escala, *_resto] = items(items_xml(documento(tmp_path)))
        for item in (label, escala):
            assert [hijo.tag for hijo in item] == [
                "ITEMID",
                "ITEMTEXT",
                "ITEMLABEL",
                "PRESENTATION",
                "OPTIONS",
                "DEPENDITEM",
                "DEPENDVALUE",
            ]
        assert campo(label, "ITEMID") == "1"
        assert campo(label, "ITEMLABEL") == "p1"
        assert campo(label, "ITEMTEXT") == ""
        assert campo(label, "DEPENDITEM") == "0"
        assert escala.get("REQUIRED") == "1"

    def test_la_escala_lleva_pesos_y_es_horizontal(self, tmp_path):
        [_, escala, *_resto] = items(items_xml(documento(tmp_path)))
        assert campo(escala, "PRESENTATION") == (
            "r>>>>>1####Muy mal|2####Mal|3####Normal|4####Bien|5####Muy bien<<<<<1"
        )
        assert campo(escala, "OPTIONS") == "h"

    def test_las_tres_formas_de_opcion(self, tmp_path):
        [_, _, una, casillas, desplegable, *_resto] = items(items_xml(documento(tmp_path)))
        assert campo(una, "PRESENTATION") == "r>>>>>Apuntes|Pizarra"
        assert campo(una, "OPTIONS") == "h"
        assert campo(casillas, "PRESENTATION") == "c>>>>>Lectura|Vídeo"
        assert campo(casillas, "OPTIONS") == ""
        assert campo(desplegable, "PRESENTATION") == "d>>>>>Mañana|Tarde"
        assert campo(desplegable, "OPTIONS") == ""

    def test_los_textos_y_los_numeros(self, tmp_path):
        [_, _, _, _, _, largo, corto, numero, sin_limites] = items(items_xml(documento(tmp_path)))
        assert campo(largo, "PRESENTATION") == "40|4"
        assert campo(corto, "PRESENTATION") == "30|255"
        assert campo(numero, "PRESENTATION") == "0|10"
        assert campo(sin_limites, "PRESENTATION") == "|"

    def test_la_informacion_lleva_html_y_no_lleva_obligatoria(self, tmp_path):
        [label, *_resto] = items(items_xml(documento(tmp_path)))
        assert campo(label, "PRESENTATION") == "<p>Aviso con ]]&gt; dentro.</p>\n"
        assert label.get("REQUIRED") == "0"

    def test_un_cierre_de_cdata_no_rompe_el_xml(self):
        from tiza.encuesta import _cdata

        trozo = _cdata("Cierra ]]> sin romper.")
        assert trozo == "<![CDATA[Cierra ]]]]><![CDATA[> sin romper.]]>"
        [item] = ET.fromstring(f"<ITEMS><ITEMTEXT>{trozo}</ITEMTEXT></ITEMS>").findall("ITEMTEXT")
        assert item.text == "Cierra ]]> sin romper."

    def test_es_determinista(self, tmp_path):
        doc = documento(tmp_path)
        assert items_xml(doc) == items_xml(doc)

    def test_una_encuesta_sin_preguntas_no_llega_aqui(self, tmp_path):
        from tiza.contenido import Documento

        with pytest.raises(ValueError):
            items_xml(Documento(Path("x.md"), "encuesta", "E", 1, "", "", []))


def test_los_tipos_coinciden_con_una_exportacion_real(tmp_path):
    """El fixture es una exportación real de todos los tipos del aula (CT 130)."""
    from collections import Counter

    reales = ET.fromstring(FIXTURE.read_bytes()).findall("ITEMS/ITEM")
    nuestros = items(items_xml(documento(tmp_path)))
    assert Counter(item.get("TYPE") for item in reales) == Counter(
        {
            "label": 1,
            "multichoicerated": 1,
            "multichoice": 3,
            "textfield": 1,
            "textarea": 1,
            "numeric": 1,
        }
    )
    assert Counter(item.get("TYPE") for item in nuestros) == Counter(
        {
            "label": 1,
            "multichoicerated": 1,
            "multichoice": 3,
            "textfield": 1,
            "textarea": 1,
            "numeric": 2,
        }
    )

    def por_tipo(lista, tipo):
        return next(item for item in lista if item.get("TYPE") == tipo)

    # La escala se lee igual; en las opciones la estructura y el formato, no el texto.
    escala_real = next(item for item in reales if item.get("TYPE") == "multichoicerated")
    escala_nuestra = next(item for item in nuestros if item.get("TYPE") == "multichoicerated")
    assert (
        campo(escala_nuestra, "PRESENTATION").strip() == campo(escala_real, "PRESENTATION").strip()
    )
    assert campo(escala_nuestra, "OPTIONS").strip() == campo(escala_real, "OPTIONS").strip()
    for posicion, real in enumerate(item for item in reales if item.get("TYPE") == "multichoice"):
        nuestro = [item for item in nuestros if item.get("TYPE") == "multichoice"][posicion]
        assert (
            campo(nuestro, "PRESENTATION").split(">>>>>", 1)[0]
            == campo(real, "PRESENTATION").strip().split(">>>>>", 1)[0]
        )
        assert campo(nuestro, "OPTIONS").strip() == campo(real, "OPTIONS").strip()
    assert campo(por_tipo(nuestros, "textarea"), "PRESENTATION") == "40|4"
    assert campo(por_tipo(nuestros, "textfield"), "PRESENTATION") == "30|255"
    assert campo(por_tipo(nuestros, "numeric"), "PRESENTATION") == "0|10"
