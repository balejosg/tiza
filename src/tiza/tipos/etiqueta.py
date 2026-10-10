"""Etiqueta de Moodle (``mod_label``): texto y medios dentro de la página del curso."""

from __future__ import annotations

from .base import Tipo


class Etiqueta(Tipo):
    nombre = "etiqueta"
    llano = "Área de texto y medios"
    modulo = "label"
    finalizaciones = ("ninguna", "manual")
