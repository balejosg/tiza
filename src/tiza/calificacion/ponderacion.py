"""Ponderación simple del calificador: el modelo puro de lo que se lee del aula.

No habla con el aula ni decide nada: solo guarda lo leído de ``grade/edit/tree/index.php`` y de
los formularios de las categorías y elementos que se nombran. ``nombre`` lo ve únicamente el
docente, a través de la presencia; nunca sale a ``informe``.
"""

from __future__ import annotations

import dataclasses

__all__ = ["ArbolPonderacion", "NodoPonderacion"]


@dataclasses.dataclass(frozen=True)
class NodoPonderacion:
    """Un elemento o categoría del calificador con lo que hace falta para ponderar.

    ``clase`` es ``curso``, ``categoria``, ``actividad``, ``manual`` o ``calculado``.
    ``coeficiente`` son los 4 decimales del formulario (solo si se abrió); ``peso`` es el
    ``weight_<item>`` del árbol (el coeficiente en media ponderada, el porcentaje en natural).
    """

    eid: str  # «cg<id>» (categoría o curso) o «ig<id>» (elemento)
    item_id: int
    idnumber: str
    clase: str
    nombre: str
    padre_eid: str | None
    cmid: int | None
    tipo: str | None  # módulo de Moodle de la actividad (``assign``, ``quiz``…)
    bloqueado: bool
    tiene_notas: bool
    agregacion: int | None  # 13 Natural, 10 Media ponderada…; solo en categorías
    solo_no_vacias: bool | None  # ``aggregateonlygraded``; solo si se abrió el formulario
    opciones_agregacion: tuple[int, ...] | None  # las del desplegable, si se abrió
    coeficiente: float | None
    peso: float | None
    sobrescrito: bool
    maximo: float | None
    oculto: bool


@dataclasses.dataclass(frozen=True)
class ArbolPonderacion:
    """El calificador de un curso, en el orden de la página."""

    curso: int
    nodos: tuple[NodoPonderacion, ...]
    decimal: str  # «,» o «.»: el separador que muestra el aula

    def nodo(self, eid: str) -> NodoPonderacion | None:
        return next((n for n in self.nodos if n.eid == eid), None)

    def raiz(self) -> NodoPonderacion | None:
        return next((n for n in self.nodos if n.padre_eid is None), None)

    def hijos(self, eid: str) -> tuple[NodoPonderacion, ...]:
        return tuple(n for n in self.nodos if n.padre_eid == eid)

    def por_nombre(self, nombre: str) -> tuple[NodoPonderacion, ...]:
        return tuple(n for n in self.nodos if n.nombre == nombre)
