"""Escritura de documentos para el docente (hoy, un Word sencillo desde Markdown)."""

from __future__ import annotations

__all__ = ["ErrorEscritura"]


class ErrorEscritura(Exception):
    """Error de escritura con un código estable; el detalle es texto de tiza."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle
