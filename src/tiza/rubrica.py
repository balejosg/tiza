"""Tipos neutros de una rúbrica de Moodle, sin corrector ni carga de ficheros.

Los usan la publicación pública (rúbricas generadas por criterios) y, en
``tiza-privado``, el corrector con IA. El hash es exactamente el de siempre en
``tiza-privado``: cambiarlo invalidaría sus ``verificados.json``.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

from .contenido import ErrorContenido
from .filtro import CONTROL

__all__ = [
    "MAX_CRITERIOS",
    "MAX_PUNTOS",
    "MAX_TEXTO",
    "CriterioRubrica",
    "Nivel",
    "RubricaCargada",
    "validar_rubrica",
]

MAX_CRITERIOS = 20
MAX_TEXTO = 1000  # descripción de un criterio o de un nivel
MAX_PUNTOS = 100
MAX_NIVELES = 6
MAX_NOMBRE_CRITERIO = 120
MAX_NOMBRE_RUBRICA = 255
_ID = re.compile(r"\A[A-Za-z][A-Za-z0-9_]{0,39}\Z")


@dataclass(frozen=True)
class Nivel:
    """Un nivel de un criterio: su id, sus puntos y cómo se describe."""

    id: str
    puntos: float
    descripcion: str


@dataclass(frozen=True)
class CriterioRubrica:
    """Una fila de la rúbrica, con sus niveles."""

    id: str
    nombre: str  # cómo lo lee el alumnado: «Contenido»
    descripcion: str
    niveles: tuple[Nivel, ...]
    criterio: str | None = None  # id del criterio del esquema; no entra en el hash

    @property
    def minimo(self) -> float:
        return min(nivel.puntos for nivel in self.niveles)

    @property
    def maximo(self) -> float:
        return max(nivel.puntos for nivel in self.niveles)


@dataclass(frozen=True)
class RubricaCargada:
    """Una rúbrica ya construida: lo que se publica y lo que corrige el privado."""

    nombre: str
    descripcion: str  # el cuerpo original (Markdown o HTML)
    html: str  # la descripción validada, como se enseña en la vista previa
    criterios: tuple[CriterioRubrica, ...]

    def hash(self) -> str:
        """Hash de lo que se publica en Moodle, con el mismo formato que en el privado."""
        resumen = hashlib.sha256()
        resumen.update(f"{self.nombre}\n{self.html}\n".encode())
        for criterio in self.criterios:
            resumen.update(f"--{criterio.id}\n{criterio.nombre}\n{criterio.descripcion}\n".encode())
            for nivel in criterio.niveles:
                resumen.update(f"{nivel.id}\n{nivel.puntos!r}\n{nivel.descripcion}\n".encode())
        return resumen.hexdigest()


def _error(detalle: str) -> ErrorContenido:
    return ErrorContenido("RUBRICA_NO_VALIDA", detalle)


def _texto(valor: Any, donde: str, maximo: int) -> str:
    if not isinstance(valor, str):
        raise _error(f"{donde}: debe ser texto")
    if not valor.strip() or len(valor) > maximo or CONTROL.search(valor):
        raise _error(f"{donde}: texto de 1 a {maximo} caracteres, sin caracteres de control")
    return valor


def _identificador(valor: Any, donde: str) -> str:
    if not isinstance(valor, str) or not _ID.match(valor):
        raise _error(
            f"{donde}: el id debe empezar por letra y usar solo letras, números o «_» (máximo 40)"
        )
    return valor


def _puntos(valor: Any, donde: str) -> float:
    if (
        isinstance(valor, bool)
        or not isinstance(valor, (int, float))
        or not math.isfinite(valor)
        or not 0 <= valor <= MAX_PUNTOS
        or round(float(valor), 2) != float(valor)
    ):
        raise _error(
            f"{donde}: «puntos» debe ser un número entre 0 y {MAX_PUNTOS}, "
            "con dos decimales como mucho"
        )
    return float(valor)


def _niveles(niveles: Any, donde: str) -> None:
    if not isinstance(niveles, tuple) or not 2 <= len(niveles) <= MAX_NIVELES:
        raise _error(f"{donde}: «niveles» debe ser una tupla de 2 a {MAX_NIVELES}")
    vistos: set[str] = set()
    puntos: list[float] = []
    for numero, nivel in enumerate(niveles, 1):
        etiqueta = f"{donde}, nivel {numero}"
        if not isinstance(nivel, Nivel):
            raise _error(f"{etiqueta}: debe ser un Nivel")
        ident = _identificador(nivel.id, etiqueta)
        if ident in vistos:
            raise _error(f"{etiqueta}: el id «{ident}» está repetido")
        vistos.add(ident)
        puntos.append(_puntos(nivel.puntos, etiqueta))
        _texto(nivel.descripcion, f"{etiqueta} (descripcion)", MAX_TEXTO)
    if min(puntos) != 0:
        raise _error(f"{donde}: el nivel más bajo debe valer 0")
    if len(set(puntos)) != len(puntos):
        raise _error(f"{donde}: los niveles no pueden repetir puntos")


def validar_rubrica(rubrica: RubricaCargada) -> None:
    """Comprueba los límites y los ids de una rúbrica ya construida."""
    if not isinstance(rubrica, RubricaCargada):
        raise _error("la rúbrica no es un objeto RubricaCargada")
    _texto(rubrica.nombre, "nombre", MAX_NOMBRE_RUBRICA)
    criterios = rubrica.criterios
    if not isinstance(criterios, tuple) or not 1 <= len(criterios) <= MAX_CRITERIOS:
        raise _error(f"«criterios» debe ser una tupla de 1 a {MAX_CRITERIOS}")
    vistos: set[str] = set()
    for numero, criterio in enumerate(criterios, 1):
        donde = f"criterio {numero}"
        if not isinstance(criterio, CriterioRubrica):
            raise _error(f"{donde}: debe ser un CriterioRubrica")
        ident = _identificador(criterio.id, donde)
        if ident in vistos:
            raise _error(f"{donde}: el id «{ident}» está repetido")
        vistos.add(ident)
        _texto(criterio.nombre, f"{donde} (nombre)", MAX_NOMBRE_CRITERIO)
        _texto(criterio.descripcion, f"{donde} (descripcion)", MAX_TEXTO)
        _niveles(criterio.niveles, donde)
