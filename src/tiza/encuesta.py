"""Moodle XML de las preguntas de una encuesta anónima (offline, sin red).

Genera el XML que se importa en ``mod/feedback`` a partir del documento ya validado.
Todo el texto va en ``CDATA``; un ``]]>`` se parte en dos secciones para no romper
el XML. El resultado es determinista: el mismo documento da los mismos bytes.
"""

from __future__ import annotations

from .contenido import Documento, PreguntaEncuesta, numero_texto

__all__ = ["items_xml", "opciones_xml", "presentacion", "tipo_xml"]

TIPOS_XML = {
    "escala": "multichoicerated",
    "opcion": "multichoice",
    "texto": "textarea",
    "texto_corto": "textfield",
    "numero": "numeric",
    "informacion": "label",
}


def tipo_xml(tipo: str) -> str:
    return TIPOS_XML[tipo]


def presentacion(pregunta: PreguntaEncuesta) -> str:
    """El campo ``PRESENTATION`` de Moodle para esta pregunta."""
    if pregunta.tipo == "escala":
        opciones = "|".join(
            f"{peso}####{opcion}" for peso, opcion in enumerate(pregunta.opciones, 1)
        )
        return f"r>>>>>{opciones}<<<<<1"
    if pregunta.tipo == "opcion":
        marca = "c" if pregunta.multiple else "d" if pregunta.desplegable else "r"
        return f"{marca}>>>>>{'|'.join(pregunta.opciones)}"
    if pregunta.tipo == "texto":
        return "40|4"
    if pregunta.tipo == "texto_corto":
        return "30|255"
    if pregunta.tipo == "numero":
        minimo = numero_texto(pregunta.minimo) if pregunta.minimo is not None else ""
        maximo = numero_texto(pregunta.maximo) if pregunta.maximo is not None else ""
        return f"{minimo}|{maximo}"
    return pregunta.html


def opciones_xml(pregunta: PreguntaEncuesta) -> str:
    """El campo ``OPTIONS``: ``h`` marca la escala y la opción única en horizontal."""
    if pregunta.tipo == "escala":
        return "h"
    if pregunta.tipo == "opcion" and not (pregunta.multiple or pregunta.desplegable):
        return "h"
    return ""


def _cdata(texto: str) -> str:
    return "<![CDATA[" + texto.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _item(numero: int, pregunta: PreguntaEncuesta) -> str:
    texto = "" if pregunta.tipo == "informacion" else pregunta.enunciado
    requerido = "1" if pregunta.obligatoria else "0"
    return (
        f'<ITEM TYPE="{tipo_xml(pregunta.tipo)}" REQUIRED="{requerido}">'
        f"<ITEMID>{_cdata(str(numero))}</ITEMID>"
        f"<ITEMTEXT>{_cdata(texto)}</ITEMTEXT>"
        f"<ITEMLABEL>{_cdata(f'p{numero}')}</ITEMLABEL>"
        f"<PRESENTATION>{_cdata(presentacion(pregunta))}</PRESENTATION>"
        f"<OPTIONS>{_cdata(opciones_xml(pregunta))}</OPTIONS>"
        f"<DEPENDITEM>{_cdata('0')}</DEPENDITEM>"
        f"<DEPENDVALUE>{_cdata('')}</DEPENDVALUE>"
        "</ITEM>"
    )


def items_xml(doc: Documento) -> bytes:
    """El XML de todas las preguntas, en el orden escrito, listo para importar."""
    if doc.encuesta is None:
        raise ValueError("el documento no es una encuesta")
    items = "".join(
        _item(numero, pregunta) for numero, pregunta in enumerate(doc.encuesta.preguntas, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" ?>\n'
        '<FEEDBACK VERSION="200701" COMMENT="XML-Importfile for mod/feedback">'
        f"<ITEMS>{items}</ITEMS></FEEDBACK>"
    ).encode()
