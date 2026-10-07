"""Moodle XML de las preguntas de un cuestionario (offline, sin red).

Genera el XML que se importa en el banco del propio cuestionario a partir del
documento ya validado. Todo lo que sale de aquí lo construye ``ElementTree``,
que escapa el texto; el HTML de los campos es el que serializa el filtro.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .contenido import Documento, Pregunta, numero_texto

__all__ = ["FRACCIONES", "fraccion_correcta", "preguntas_xml"]

# Fracciones que acepta la importación de Moodle para cada número de respuestas
# correctas de una pregunta de opción múltiple (k de 2 a 10). La importación va
# con matchgrades=error: cualquier otro valor se rechaza en vez de redondearse.
FRACCIONES = {
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

_TIPO_XML = {
    "opcion_multiple": "multichoice",
    "verdadero_falso": "truefalse",
    "respuesta_corta": "shortanswer",
    "numerica": "numerical",
}


def fraccion_correcta(cuantas: int) -> str:
    """Fracción de cada acierto (y su negativa) cuando hay ``cuantas`` correctas."""
    try:
        return FRACCIONES[cuantas]
    except KeyError:
        raise ValueError(f"no hay fracción para {cuantas} respuestas correctas") from None


def preguntas_xml(doc: Documento) -> bytes:
    """El XML de todas las preguntas, en el orden escrito, listo para importar."""
    if doc.cuestionario is None:
        raise ValueError("el documento no es un cuestionario")
    raiz = ET.Element("quiz")
    for numero, pregunta in enumerate(doc.cuestionario.preguntas, 1):
        _anadir_pregunta(raiz, f"P{numero:02d}", pregunta)
    cuerpo = ET.tostring(raiz, encoding="unicode")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + cuerpo).encode("utf-8")


def _anadir_pregunta(raiz: ET.Element, nombre: str, pregunta: Pregunta) -> None:
    nodo = ET.SubElement(raiz, "question", type=_TIPO_XML[pregunta.tipo])
    ET.SubElement(ET.SubElement(nodo, "name"), "text").text = nombre
    _texto(nodo, "questiontext", pregunta.html)
    _texto(nodo, "generalfeedback", pregunta.retro_html or "")
    ET.SubElement(nodo, "defaultgrade").text = "1"
    penalizacion = "1" if pregunta.tipo == "verdadero_falso" else "0.3333333"
    ET.SubElement(nodo, "penalty").text = penalizacion
    ET.SubElement(nodo, "hidden").text = "0"
    if pregunta.tipo == "opcion_multiple":
        _multichoice(nodo, pregunta)
    elif pregunta.tipo == "verdadero_falso":
        _verdadero_falso(nodo, pregunta)
    elif pregunta.tipo == "respuesta_corta":
        _respuesta_corta(nodo, pregunta)
    else:
        _numerica(nodo, pregunta)


def _texto(padre: ET.Element, etiqueta: str, contenido: str) -> ET.Element:
    nodo = ET.SubElement(padre, etiqueta, format="html")
    ET.SubElement(nodo, "text").text = contenido
    return nodo


def _respuesta(
    padre: ET.Element, fraccion: str, texto: str, formato: str = "html", retro: str | None = None
) -> ET.Element:
    nodo = ET.SubElement(padre, "answer", fraction=fraccion, format=formato)
    ET.SubElement(nodo, "text").text = texto
    comentario = ET.SubElement(nodo, "feedback", format="html")
    ET.SubElement(comentario, "text").text = retro or ""
    return nodo


def _multichoice(nodo: ET.Element, pregunta: Pregunta) -> None:
    correctas = [opcion for opcion in pregunta.opciones if opcion.correcta]
    unica = len(correctas) == 1
    ET.SubElement(nodo, "single").text = "true" if unica else "false"
    ET.SubElement(nodo, "shuffleanswers").text = "true"
    ET.SubElement(nodo, "answernumbering").text = "abc"
    for opcion in pregunta.opciones:
        if unica:
            fraccion = "100" if opcion.correcta else "0"
        else:
            valor = fraccion_correcta(len(correctas))
            fraccion = valor if opcion.correcta else f"-{valor}"
        _respuesta(nodo, fraccion, opcion.html, retro=opcion.retro_html)


def _verdadero_falso(nodo: ET.Element, pregunta: Pregunta) -> None:
    respuestas = (("true", "verdadero"), ("false", "falso"))
    for texto, valor in respuestas:
        fraccion = "100" if pregunta.respuesta == valor else "0"
        _respuesta(nodo, fraccion, texto, formato="moodle_auto_format")


def _respuesta_corta(nodo: ET.Element, pregunta: Pregunta) -> None:
    ET.SubElement(nodo, "usecase").text = "1" if pregunta.mayusculas else "0"
    for aceptada in pregunta.aceptadas:
        _respuesta(nodo, "100", aceptada, formato="moodle_auto_format")


def _numerica(nodo: ET.Element, pregunta: Pregunta) -> None:
    assert pregunta.valor is not None
    respuesta = _respuesta(nodo, "100", numero_texto(pregunta.valor), formato="moodle_auto_format")
    ET.SubElement(respuesta, "tolerance").text = numero_texto(pregunta.tolerancia)
