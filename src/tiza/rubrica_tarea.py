"""Rúbrica de una tarea a partir de filas: indicadores, descriptores y pesos propios.

Todo es puro y offline. Cada fila concreta un criterio del esquema con un indicador
y un descriptor por nivel de ``niveles_rubrica``. Los puntos de la tarea (10) se
reparten por el peso de cada fila con el mayor resto, y los de cada nivel son los
de la fila por el porcentaje del nivel, también con el mayor resto, para que cada
suma sea exacta.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .calificacion.esquema import ErrorCalificacion, Esquema, NivelRubrica
from .filtro import CONTROL
from .rubrica import (
    MAX_CRITERIOS,
    MAX_NOMBRE_CRITERIO,
    MAX_TEXTO,
    CriterioRubrica,
    Nivel,
    RubricaCargada,
    validar_rubrica,
)
from .rubrica_criterios import _hoja, mayor_resto

__all__ = ["FilaRubrica", "rubrica_de_filas"]

MAX_INDICADOR = 100
MAX_PESO_FILA = 100


@dataclass(frozen=True)
class FilaRubrica:
    """Una fila de la rúbrica: un indicador concreto de un criterio y sus descriptores."""

    criterio: str
    indicador: str
    peso: float | None
    descriptores: dict[str, str]


def _error(codigo: str, detalle: str) -> ErrorCalificacion:
    return ErrorCalificacion(codigo, detalle)


def _texto(valor: Any, donde: str, maximo: int) -> str:
    if (
        not isinstance(valor, str)
        or not valor.strip()
        or len(valor) > maximo
        or CONTROL.search(valor)
    ):
        raise _error(
            "RUBRICA_NO_VALIDA",
            f"{donde}: texto de 1 a {maximo} caracteres, sin caracteres de control",
        )
    return valor


def _peso(valor: Any, donde: str) -> float:
    if (
        isinstance(valor, bool)
        or not isinstance(valor, (int, float))
        or not 0 < valor <= MAX_PESO_FILA
        or not math.isfinite(valor)
        or round(float(valor), 2) != float(valor)
    ):
        raise _error(
            "RUBRICA_NO_VALIDA",
            f"{donde}: «peso» debe ser un número mayor que 0 y hasta {MAX_PESO_FILA}, "
            "con dos decimales como mucho",
        )
    return float(valor)


def _pesos(filas: tuple[FilaRubrica, ...]) -> list[float]:
    """El peso de cada fila: el suyo o 1 si ninguna lleva peso."""
    con_peso = [fila.peso is not None for fila in filas]
    if any(con_peso) and not all(con_peso):
        raise _error(
            "PESOS_DE_FILA_INCOMPLETOS",
            "o todas las filas llevan «peso» o ninguna",
        )
    if not any(con_peso):
        return [1.0] * len(filas)
    return [_peso(fila.peso, f"fila {numero}") for numero, fila in enumerate(filas, 1)]


def _descriptores(
    niveles: tuple[NivelRubrica, ...], descriptores: Any, donde: str
) -> dict[str, str]:
    """Los descriptores de una fila, uno por nivel, validados y en el orden del esquema."""
    if not isinstance(descriptores, dict):
        raise _error(
            "RUBRICA_NO_VALIDA",
            f"{donde}: «descriptores» debe ser un mapa de nivel a texto",
        )
    ids = {nivel.id for nivel in niveles}
    for clave in descriptores:
        if clave not in ids:
            raise _error(
                "NIVEL_DESCONOCIDO",
                f"{donde}: el nivel «{clave}» no está en niveles_rubrica",
            )
    salida: dict[str, str] = {}
    for nivel in niveles:
        if nivel.id not in descriptores:
            raise _error(
                "DESCRIPTOR_FALTA",
                f"{donde}: falta el descriptor del nivel «{nivel.id}»",
            )
        texto = _texto(descriptores[nivel.id], f"{donde}, nivel «{nivel.id}»", MAX_TEXTO)
        limite = MAX_TEXTO - len(nivel.nombre) - 2
        if len(texto) > limite:
            raise _error(
                "RUBRICA_NO_VALIDA",
                f"{donde}: el descriptor del nivel «{nivel.id}» no puede pasar de "
                f"{limite} caracteres, porque «{nivel.nombre}: » ocupa el resto "
                f"de los {MAX_TEXTO} de la definición",
            )
        salida[nivel.id] = texto
    return salida


def rubrica_de_filas(
    esquema: Esquema,
    filas: tuple[FilaRubrica, ...],
    nombre: str,
    descripcion: str,
    html: str,
) -> RubricaCargada:
    """Construye la rúbrica de una tarea a partir de sus filas por criterio."""
    if not isinstance(filas, tuple) or not 1 <= len(filas) <= MAX_CRITERIOS:
        raise _error("RUBRICA_NO_VALIDA", f"«filas» debe ser una tupla de 1 a {MAX_CRITERIOS}")
    for numero, fila in enumerate(filas, 1):
        if not isinstance(fila, FilaRubrica):
            raise _error("RUBRICA_NO_VALIDA", f"fila {numero}: debe ser una FilaRubrica")

    pesos = _pesos(filas)
    total = 10.0
    puntos = mayor_resto([peso / sum(pesos) * total for peso in pesos], total)
    puntos_por_nivel = [
        mayor_resto(
            [punto * nivel.porcentaje / 100 for punto in puntos],
            total * nivel.porcentaje / 100,
        )
        for nivel in esquema.niveles_rubrica
    ]
    for indice in range(len(filas)):
        puntos_fila = [nivel[indice] for nivel in puntos_por_nivel]
        if len(set(puntos_fila)) != len(puntos_fila):
            raise _error(
                "RUBRICA_NO_VALIDA",
                f"fila {indice + 1}: el peso es demasiado pequeño frente a las demás "
                "filas y sus niveles no reparten puntos distintos",
            )

    criterios_rubrica: list[CriterioRubrica] = []
    vistas: set[tuple[str, str]] = set()
    repeticiones: dict[str, int] = {}
    for indice, fila in enumerate(filas):
        donde = f"fila {indice + 1}"
        elemento, criterio = _hoja(esquema, fila.criterio)
        indicador = _texto(fila.indicador, f"{donde} (indicador)", MAX_INDICADOR)
        clave = (fila.criterio, indicador)
        if clave in vistas:
            raise _error(
                "RUBRICA_NO_VALIDA",
                f"{donde}: el criterio «{fila.criterio}» ya tiene una fila con el "
                f"indicador «{indicador}»",
            )
        vistas.add(clave)
        descriptores = _descriptores(esquema.niveles_rubrica, fila.descriptores, donde)

        repeticion = repeticiones.get(fila.criterio, 0) + 1
        repeticiones[fila.criterio] = repeticion
        id_ = fila.criterio.lower() if repeticion == 1 else f"{fila.criterio.lower()}_{repeticion}"
        codigo = elemento.codigo if criterio is None else criterio.codigo
        nombre_fila = f"{codigo} · {indicador}" if codigo else fila.criterio
        if len(nombre_fila) > MAX_NOMBRE_CRITERIO:
            raise _error(
                "RUBRICA_NO_VALIDA",
                f"{donde}: el título de la fila no puede pasar de {MAX_NOMBRE_CRITERIO} "
                "caracteres (código e indicador)",
            )
        texto = elemento.nombre if criterio is None else criterio.nombre
        niveles = tuple(
            Nivel(
                id=nivel.id,
                puntos=puntos_por_nivel[posicion][indice],
                descripcion=f"{nivel.nombre}: {descriptores[nivel.id]}",
            )
            for posicion, nivel in enumerate(esquema.niveles_rubrica)
        )
        criterios_rubrica.append(
            CriterioRubrica(
                id=id_,
                nombre=nombre_fila,
                descripcion=texto,
                niveles=niveles,
                criterio=fila.criterio,
            )
        )

    cargada = RubricaCargada(
        nombre=nombre,
        descripcion=descripcion,
        html=html,
        criterios=tuple(criterios_rubrica),
    )
    validar_rubrica(cargada)
    return cargada
