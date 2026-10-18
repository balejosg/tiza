"""Construye los .docx sintéticos de los tests con python-docx y XML insertado."""

from __future__ import annotations

import io
import zipfile

from docx import Document
from docx.oxml import parse_xml

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def elemento(texto: str):
    """Parsea un elemento w:* suelto (declara el espacio de nombres en la raíz)."""
    raiz, resto = texto.split(">", 1)
    if raiz.endswith("/"):
        return parse_xml(f"{raiz[:-1]} {W}/>")
    return parse_xml(f"{raiz} {W}>{resto}")


def nuevo():
    return Document()


def parrafo_xml(documento, interior: str):
    """Añade un párrafo cuyo contenido es XML en bruto (w:r, w:ins, w:del…)."""
    p = documento.add_paragraph()
    for hijo in elemento(f"<w:x>{interior}</w:x>"):
        p._p.append(hijo)
    return p


def indice(documento) -> None:
    """Un índice de contenidos (w:sdt con docPartGallery) al principio del cuerpo."""
    sdt = elemento(
        '<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/>'
        "</w:docPartObj></w:sdtPr><w:sdtContent><w:p><w:r><w:t>Entrada del índice</w:t></w:r></w:p>"
        "</w:sdtContent></w:sdt>"
    )
    documento.element.body.insert(0, sdt)


def nivel(ilvl: int, fmt: str, texto: str, inicio: int = 1, estilo: str = "") -> str:
    ps = f'<w:pStyle w:val="{estilo}"/>' if estilo else ""
    return (
        f'<w:lvl w:ilvl="{ilvl}"><w:start w:val="{inicio}"/><w:numFmt w:val="{fmt}"/>'
        f'{ps}<w:lvlText w:val="{texto}"/></w:lvl>'
    )


def numeracion(
    documento, abstractos: dict[int, list[str]], nums: dict[int, tuple[int, int | None]]
):
    """Sustituye numbering.xml. ``nums``: numId -> (abstractNumId, startOverride del nivel 0)."""
    partes = [f"<w:numbering {W}>"]
    for ident, niveles in abstractos.items():
        partes.append(
            f'<w:abstractNum w:abstractNumId="{ident}">{"".join(niveles)}</w:abstractNum>'
        )
    for num, (abstracto, override) in nums.items():
        extra = (
            f'<w:lvlOverride w:ilvl="0"><w:startOverride w:val="{override}"/></w:lvlOverride>'
            if override
            else ""
        )
        partes.append(
            f'<w:num w:numId="{num}"><w:abstractNumId w:val="{abstracto}"/>{extra}</w:num>'
        )
    partes.append("</w:numbering>")
    documento.part.numbering_part._element = parse_xml("".join(partes))


def parrafo_numerado(documento, texto: str, num: int, ilvl: int = 0):
    p = documento.add_paragraph(texto)
    p._p.get_or_add_pPr().append(
        elemento(f'<w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num}"/></w:numPr>')
    )
    return p


def a_bytes(documento) -> bytes:
    memoria = io.BytesIO()
    documento.save(memoria)
    return memoria.getvalue()


def reescribir(datos: bytes, miembro: str, contenido: bytes) -> bytes:
    """Copia un zip cambiando (o añadiendo) un miembro."""
    salida = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(datos)) as origen,
        zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as destino,
    ):
        for info in origen.infolist():
            if info.filename != miembro:
                destino.writestr(info.filename, origen.read(info.filename))
        destino.writestr(miembro, contenido)
    return salida.getvalue()
