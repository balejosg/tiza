"""El registro de los tipos de actividad: un módulo por tipo, un solo dueño.

Cada tipo conoce sus campos, su validación, sus fechas, su finalización, su
payload, su publicación, su vista previa y su huella para el hash. Lo que
comparten está en :mod:`tiza.tipos.base`. El resto de tiza pregunta aquí.
"""

from __future__ import annotations

from .base import (
    BANDERA_DE_MODO,
    CAMPO_RECORDATORIO,
    FechaActividad,
    Tipo,
    fechas_esperadas,
    fechas_payload,
    modo_leido,
    partes_fecha,
    payload_fecha,
    payload_finalizacion,
)
from .cuestionario import Cuestionario
from .etiqueta import Etiqueta
from .h5p import H5P
from .pagina import Pagina
from .tarea import Tarea

__all__ = [
    "BANDERA_DE_MODO",
    "CAMPO_RECORDATORIO",
    "FechaActividad",
    "TODOS",
    "TIPOS",
    "Tipo",
    "de_modulo",
    "fechas_esperadas",
    "fechas_payload",
    "modo_leido",
    "obtener",
    "partes_fecha",
    "payload_fecha",
    "payload_finalizacion",
]

# Orden canónico: el que enseñan los mensajes de error y recorren los tests.
TODOS: tuple[Tipo, ...] = (Pagina(), Tarea(), Cuestionario(), Etiqueta(), H5P())
TIPOS = tuple(tipo.nombre for tipo in TODOS)
_POR_NOMBRE = {tipo.nombre: tipo for tipo in TODOS}
_POR_MODULO = {tipo.modulo: tipo.nombre for tipo in TODOS}


def obtener(nombre: str) -> Tipo:
    """El adapter de un tipo ya validado (los documentos siempre lo están)."""
    return _POR_NOMBRE[nombre]


def de_modulo(modulo: str) -> str | None:
    """El nombre local del tipo a partir del módulo de Moodle; None si es ajeno."""
    return _POR_MODULO.get(modulo)
