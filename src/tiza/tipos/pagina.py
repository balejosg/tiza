"""Página de Moodle (``mod_page``): contenido con texto e imágenes."""

from __future__ import annotations

from .base import Tipo


class Pagina(Tipo):
    nombre = "pagina"
    llano = "Página"
    modulo = "page"
    finalizaciones = ("ninguna", "manual", "ver")
    banderas = ("completionview",)
