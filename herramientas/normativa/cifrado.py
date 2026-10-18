"""Descifrado de un PDF cuya fuente del cuerpo no trae mapa de Unicode (la Orden 3537/2025).

El PDF del BOCM compone el cuerpo con una fuente (``Arial``, subconjunto de tipo Type1C)
sin ``ToUnicode`` cuya codificación (``/Differences``) nombra cada glifo por su número en la
fuente original: ``/g3``, ``/g38``… ``pdftotext`` no conoce esos nombres y saca el carácter
U+00NN con NN el número de glifo: «competencias» sale como «FRPSHWHQFLDV». Peor: los glifos
11 y 12 (los paréntesis) son U+000B y U+000C, que Unicode tiene por espacio, y desaparecen.

El número de glifo de Arial es el del orden «Macintosh» de las fuentes TrueType: el ASCII
imprimible empieza en el glifo 3 (el espacio), así que ``glifo = carácter - 29``; las
letras acentuadas y los signos fuera del ASCII siguen en ese orden (con una plaza menos
desde las comillas, porque esta Arial no tiene el espacio duro). Solo se admiten los glifos
que se han comparado con la imagen de la página (:data:`GLIFOS_ARIAL`); un glifo de la fuente
que no esté en la tabla se pone en el área privada de Unicode y :func:`comprobar_descifrado`
lo rechaza: nunca se adivina un carácter.

El arreglo no toca el PDF original: añade al final una actualización incremental (así se
añaden objetos a un PDF sin reescribirlo) que redeclara la codificación con
``/uniXXXX``, el carácter ya descifrado, y ``pdftotext -layout`` lee el resultado como
cualquier otro PDF.
"""

from __future__ import annotations

import re

__all__ = ["CIFRADOS", "GLIFOS_ARIAL", "comprobar_descifrado", "parchear_pdf"]

# número de glifo de Arial -> carácter. El ASCII (glifos 3 a 97) por la regla de arriba; el
# resto, solo los glifos que usa la Orden 3537/2025 y se han comparado con las imágenes.
GLIFOS_ARIAL: dict[int, str] = {
    **{g: chr(g + 29) for g in range(3, 98)},
    105: "á",
    112: "é",
    116: "í",
    120: "ñ",
    121: "ó",
    126: "ú",
    129: "ü",
    157: "ª",
    169: "«",
    170: "»",
    179: "“",
    180: "”",
    200: "Á",
}

CIFRADOS: dict[str, dict[int, str]] = {"glifos-arial": GLIFOS_ARIAL}

_AREA_PRIVADA = 0xE000
# un objeto sin flujo: el cuerpo no puede cruzar un «endobj» (ni, por tanto, un flujo)
_OBJETO = re.compile(rb"(?m)^(\d+) 0 obj\s*(<<(?:(?!endobj).)*?>>)\s*endobj", re.S)
_DIFERENCIAS = re.compile(rb"/Differences\s*\[(.*?)\]", re.S)
_NOMBRE = re.compile(rb"/(\w+)")
_GLIFO = re.compile(rb"/g(\d+)\b")


def _nombre_unicode(glifo: int, tabla: dict[int, str]) -> bytes:
    caracter = tabla.get(glifo)
    codigo = ord(caracter) if caracter is not None else _AREA_PRIVADA + glifo
    return b"/uni%04X" % codigo


def _codificaciones_cifradas(pdf: bytes) -> list[tuple[int, bytes]]:
    """Los objetos de codificación cuyos nombres son todos ``/gNN``: ``(número, cuerpo)``."""
    encontrados = []
    for m in _OBJETO.finditer(pdf):
        dif = _DIFERENCIAS.search(m[2])
        if dif is None:
            continue
        nombres = _NOMBRE.findall(dif[1])
        if nombres and all(re.fullmatch(rb"g\d+", n) for n in nombres):
            encontrados.append((int(m[1]), m[2]))
    return encontrados


def parchear_pdf(pdf: bytes, cifrado: str) -> bytes:
    """El PDF con una actualización incremental que descifra los nombres de glifo.

    Los glifos de la tabla pasan a ``/uniXXXX`` con su carácter; los demás, a ``/uniE0NN``
    (área privada), para que :func:`comprobar_descifrado` los delate si salen en el texto.
    """
    tabla = CIFRADOS.get(cifrado)
    if tabla is None:
        raise ValueError(f"cifrado desconocido «{cifrado}»")
    objetos = _codificaciones_cifradas(pdf)
    if not objetos:
        raise ValueError("no hay ninguna fuente con glifos /gNN en el PDF")
    prev = re.findall(rb"startxref\s+(\d+)\s+%%EOF", pdf)
    trailer = re.findall(rb"trailer\s*<<(.*?)>>\s*startxref", pdf, re.S)
    if not prev or not trailer:
        raise ValueError("el PDF no tiene un xref clásico que ampliar")
    salida = bytearray(pdf if pdf.endswith(b"\n") else pdf + b"\n")
    desplazamientos = {}
    for numero, cuerpo in objetos:
        nuevo = _GLIFO.sub(lambda m: _nombre_unicode(int(m[1]), tabla), cuerpo)
        desplazamientos[numero] = len(salida)
        salida += b"%d 0 obj\n%s\nendobj\n" % (numero, nuevo)
    xref = len(salida)
    salida += b"xref\n"
    for numero, desplazamiento in sorted(desplazamientos.items()):
        salida += b"%d 1\n%010d 00000 n \n" % (numero, desplazamiento)
    salida += b"trailer\n<<%s/Prev %s>>\nstartxref\n%d\n%%%%EOF\n" % (trailer[-1], prev[-1], xref)
    return bytes(salida)


def comprobar_descifrado(texto: str) -> None:
    """Rechaza un texto con restos del cifrado: glifos sin tabla o controles de ``pdftotext``.

    Un carácter de control (salvo el salto de línea, el de página y el tabulador) es lo que
    deja el texto sin descifrar (el espacio cifrado es U+0003).
    """
    for m in re.finditer("[-]", texto):
        glifo = ord(m[0]) - _AREA_PRIVADA
        raise ValueError(f"glifo {glifo} de la fuente cifrada sin tabla; compáralo con la imagen")
    for m in re.finditer("[\x00-\x08\x0b\x0d-\x1f\x7f-\x9f]", texto):
        raise ValueError(
            f"carácter de control U+{ord(m[0]):04X} en el texto: ¿se leyó sin descifrar?"
        )
