"""Modelo común de la lectura de documentos y su texto con marcas.

Lo comparten el lector de Word y el de PDF: ambos devuelven una ``Lectura`` y ``a_texto``
la convierte en el formato que lee el agente, con el id de cada bloque entre corchetes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Bloque", "ErrorLectura", "Lectura", "a_texto"]


class ErrorLectura(Exception):
    """Error de lectura con un código estable; el detalle es texto de tiza."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


@dataclass
class Bloque:
    """Un trozo del documento.

    ``id``: ``p<n>`` (párrafo del cuerpo), ``t<n>`` (tabla), ``t<n>.f<i>`` (fila),
    ``t<n>.f<i>.c<j>`` (celda) y ``t<n>.f<i>.c<j>.p<k>`` (párrafo de una celda); en el PDF,
    ``g<página>.<n>``. Los índices empiezan en 1, en orden de documento.
    ``tipo``: ``titulo``, ``parrafo``, ``tabla``, ``fila`` o ``celda``. ``nivel``: 1-9 en
    los títulos. ``etiqueta``: la numeración automática ya calculada («c)», «2.») o ``""``.
    ``ancho`` y ``alto``: en las celdas, las columnas y filas que ocupan; en las tablas, sus
    columnas y filas.
    """

    id: str
    tipo: str
    texto: str = ""
    nivel: int = 0
    estilo: str = ""
    etiqueta: str = ""
    ancho: int = 1
    alto: int = 1
    hijos: list[Bloque] = field(default_factory=list)


@dataclass
class Lectura:
    fichero: str
    formato: str
    bloques: list[Bloque] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    sha256: str = ""


def _contenido(bloque: Bloque) -> str:
    texto = f"{bloque.etiqueta} {bloque.texto}".strip() if bloque.etiqueta else bloque.texto
    if bloque.tipo == "titulo":
        marca = "#" * max(2, bloque.nivel + 1)
        return f"{marca} {texto}".rstrip()
    return texto


def _escribir(bloque: Bloque, sangria: int, lineas: list[str]) -> None:
    espacio = " " * sangria
    if bloque.tipo == "tabla":
        lineas.append(f"{espacio}[{bloque.id}] tabla de {bloque.alto}×{bloque.ancho}")
        for fila in bloque.hijos:
            for celda in fila.hijos:
                lineas.append(f"{espacio}[{celda.id}]")
                for hijo in celda.hijos:
                    _escribir(hijo, sangria + 2, lineas)
        lineas.append(f"{espacio}[{bloque.id}] fin")
        return
    lineas.append(f"{espacio}[{bloque.id}] {_contenido(bloque)}".rstrip())


def a_texto(lectura: Lectura) -> str:
    """El texto que lee el agente: una línea por párrafo, con su id entre corchetes."""
    lineas: list[str] = []
    for bloque in lectura.bloques:
        _escribir(bloque, 0, lineas)
    return "\n".join(lineas) + ("\n" if lineas else "")
