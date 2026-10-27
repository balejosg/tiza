"""Escritura de documentos para el docente: un Word sencillo y un SVG convertido en PNG."""

from __future__ import annotations

__all__ = ["ErrorEscritura"]


class ErrorEscritura(Exception):
    """Error de escritura con un código estable; el detalle es texto de tiza."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle
