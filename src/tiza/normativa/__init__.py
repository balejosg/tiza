"""Fuente de normativa: el modelo y el cargador de los datos que viajan con tiza."""

from __future__ import annotations

from . import consulta, salida
from .datos import ErrorNormativa, Indice, cargar, limpiar_cache, normalizar_cita
from .modelo import Elemento, Ficha, Norma, Procedencia

__all__ = [
    "Elemento",
    "ErrorNormativa",
    "Ficha",
    "Indice",
    "Norma",
    "Procedencia",
    "cargar",
    "consulta",
    "limpiar_cache",
    "normalizar_cita",
    "salida",
]
