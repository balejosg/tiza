"""Rúbrica por criterios de evaluación: reparto de puntos y construcción para Moodle.

Todo es puro y offline. Los pesos salen de ``calificacion.yaml``: el peso del
elemento y, si lo hay, el del criterio. Una tarea tiene una sola nota; la
rúbrica reparte sus 10 puntos entre los criterios que trabaja, en proporción a
esos pesos fijos. El redondeo es el del mayor resto, tanto en las filas como en
cada nivel, para que cada suma sea exacta.
"""

from __future__ import annotations

import html as _html
import math

from . import filtro
from .calificacion.esquema import Criterio, Elemento, ErrorCalificacion, Esquema
from .contenido import numero_texto
from .rubrica import CriterioRubrica, Nivel, RubricaCargada, validar_rubrica

__all__ = ["reparto", "rubrica_de_criterios"]

_NOMBRE_TAREA_MAX = 255


def _centimos(valor: float) -> int:
    return int(round(valor * 100))


def _mayor_resto(exactos: list[float], total: float) -> list[float]:
    """Reparte ``total`` en céntimos según ``exactos``, con el método del mayor resto.

    Los empates se resuelven a favor del último, como el ajuste final de
    ``normalizar_pesos``: así tres criterios iguales dan 3,33 / 3,33 / 3,34.
    """
    if not exactos:
        return []
    objetivo = _centimos(total)
    en_centimos = [valor * 100 for valor in exactos]
    bases = [int(math.floor(valor + 1e-9)) for valor in en_centimos]
    while sum(bases) < objetivo:
        indice = max(range(len(bases)), key=lambda i: (en_centimos[i] - bases[i], i))
        bases[indice] += 1
    while sum(bases) > objetivo:
        indice = min(range(len(bases)), key=lambda i: (en_centimos[i] - bases[i], -i))
        bases[indice] -= 1
    return [base / 100 for base in bases]


def _hoja(esquema: Esquema, id_: str) -> tuple[Elemento, Criterio | None]:
    for elemento in esquema.elementos:
        if elemento.criterios:
            for criterio in elemento.criterios:
                if criterio.id == id_:
                    return elemento, criterio
            if elemento.id == id_:
                raise ErrorCalificacion(
                    "ELEMENTO_CON_CRITERIOS",
                    f"«{id_}» tiene criterios: nombra sus criterios, no el elemento",
                )
        elif elemento.id == id_:
            return elemento, None
    raise ErrorCalificacion(
        "ELEMENTO_DESCONOCIDO",
        f"«{id_}» no está entre los elementos ni los criterios de calificacion.yaml",
    )


def _peso_absoluto(elemento: Elemento, criterio: Criterio | None) -> float:
    """Peso absoluto de una hoja: elemento y criterio, cada uno sobre 100."""
    if criterio is None:
        return elemento.peso / 100
    peso_criterio = 1 / len(elemento.criterios) if criterio.peso is None else criterio.peso / 100
    return (elemento.peso / 100) * peso_criterio


def reparto(
    esquema: Esquema, criterios: tuple[str, ...], total: float = 10.0
) -> tuple[tuple[str, float], ...]:
    """Los puntos de cada criterio, en el orden pedido, sumando exactamente ``total``.

    Un criterio con peso absoluto 0 no genera fila. Si todos pesan 0,
    ``RUBRICA_SIN_PESOS``. Un id que no es una hoja del esquema da
    ``ELEMENTO_DESCONOCIDO`` o ``ELEMENTO_CON_CRITERIOS``.
    """
    pesos: list[tuple[str, float]] = []
    for id_ in criterios:
        elemento, criterio = _hoja(esquema, id_)
        peso = _peso_absoluto(elemento, criterio)
        if peso > 0:
            pesos.append((id_, peso))
    if not pesos:
        raise ErrorCalificacion(
            "RUBRICA_SIN_PESOS",
            "ningún criterio de la tarea tiene peso en calificacion.yaml",
        )
    suma = sum(peso for _, peso in pesos)
    puntos = _mayor_resto([peso / suma * total for _, peso in pesos], total)
    filas = tuple((id_, valor) for (id_, _), valor in zip(pesos, puntos, strict=True) if valor > 0)
    if not filas:
        raise ErrorCalificacion(
            "RUBRICA_SIN_PESOS",
            "ningún criterio de la tarea tiene peso suficiente para una fila",
        )
    return filas


def _porcentaje(valor: float) -> str:
    return numero_texto(valor).replace(".", ",")


def _texto_criterio(elemento: Elemento, criterio: Criterio | None) -> str:
    if criterio is None:
        nombre = elemento.nombre
        codigo = elemento.codigo
    else:
        nombre = criterio.nombre
        codigo = criterio.codigo
    return f"{codigo} · {nombre}" if codigo else nombre


def _descripcion_criterio(elemento: Elemento, criterio: Criterio | None) -> str:
    return elemento.nombre if criterio is None else criterio.nombre


def rubrica_de_criterios(
    esquema: Esquema, criterios: tuple[str, ...], nombre_tarea: str
) -> RubricaCargada:
    """La rúbrica de una tarea: una fila por criterio y los niveles del esquema."""
    filas = reparto(esquema, criterios)
    total = 10.0
    puntos_por_nivel: list[list[float]] = [
        _mayor_resto(
            [puntos * nivel.porcentaje / 100 for _, puntos in filas],
            total * nivel.porcentaje / 100,
        )
        for nivel in esquema.niveles_rubrica
    ]

    criterios_rubrica: list[CriterioRubrica] = []
    lineas: list[str] = []
    for indice, (id_, puntos) in enumerate(filas):
        elemento, criterio = _hoja(esquema, id_)
        nombre = _texto_criterio(elemento, criterio)
        descripcion = _descripcion_criterio(elemento, criterio)
        niveles = tuple(
            Nivel(
                id=nivel.id,
                puntos=puntos_por_nivel[posicion][indice],
                descripcion=nivel.nombre,
            )
            for posicion, nivel in enumerate(esquema.niveles_rubrica)
        )
        criterios_rubrica.append(
            CriterioRubrica(
                id=id_.lower(),
                nombre=nombre,
                descripcion=descripcion,
                niveles=niveles,
            )
        )
        lineas.append(f"- {nombre}: {_porcentaje(puntos / total * 100)} %")

    descripcion = "\n".join(["Esta tarea se califica por criterios de evaluación:", *lineas])
    cuerpo_html = (
        "<p>Esta tarea se califica por criterios de evaluación:</p><ul>"
        + "".join(f"<li>{_html.escape(linea[2:])}</li>" for linea in lineas)
        + "</ul>"
    )
    try:
        html = filtro.serializar(filtro.analizar(cuerpo_html).cuerpo)
    except filtro.HtmlPeligroso as exc:  # el texto se escapa: no debería ocurrir
        raise ErrorCalificacion("RUBRICA_NO_VALIDA", f"HTML de la rúbrica: {exc.detalle}") from None
    cargada = RubricaCargada(
        nombre=f"Rúbrica de {nombre_tarea.strip()}"[:_NOMBRE_TAREA_MAX],
        descripcion=descripcion,
        html=html,
        criterios=tuple(criterios_rubrica),
    )
    validar_rubrica(cargada)
    return cargada
