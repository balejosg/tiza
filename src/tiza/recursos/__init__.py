"""Recursos gráficos de tiza: el logo, el icono y las fuentes de los esquemas.

Viven dentro del paquete para que la wheel los lleve: la página del panel incrusta el logo
como ``data:``, pywebview carga el ``.ico`` desde su ruta y ``tiza esquema`` renderiza con
las dos variantes de Liberation Sans (OFL 1.1). Sin red y sin ventana.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

__all__ = ["datos", "ruta"]


def ruta(nombre: str) -> Path | None:
    """La ruta real de un recurso del paquete, o None si el paquete no está en disco."""
    recurso = files(__name__).joinpath(nombre)
    if not isinstance(recurso, Path):  # paquete comprimido: pywebview necesita un fichero
        return None
    return recurso if recurso.is_file() else None


def datos(nombre: str) -> bytes:
    """Los bytes de un recurso del paquete (también dentro de un paquete comprimido)."""
    return files(__name__).joinpath(nombre).read_bytes()
