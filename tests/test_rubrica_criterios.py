"""Reparto de la nota de una tarea entre criterios y construcción de su rúbrica."""

from __future__ import annotations

import pytest

from tiza.calificacion.esquema import (
    Criterio,
    Elemento,
    ErrorCalificacion,
    Esquema,
    Final,
    NivelRubrica,
)
from tiza.rubrica import validar_rubrica
from tiza.rubrica_criterios import reparto, rubrica_de_criterios


def esquema_de(*elementos: Elemento, niveles: tuple[NivelRubrica, ...] | None = None) -> Esquema:
    kwargs = {} if niveles is None else {"niveles_rubrica": niveles}
    return Esquema(
        organizacion="elementos",
        elementos=tuple(elementos),
        evaluaciones=(),
        final=Final("elementos"),
        **kwargs,
    )


def criterio(id_: str, peso: float | None = None, codigo: str | None = None) -> Criterio:
    return Criterio(id_, f"Criterio {id_}", peso, codigo)


def test_reparto_proporcional() -> None:
    esquema = esquema_de(
        Elemento("RA1", "Redes", 25.0, criterios=(criterio("CE1", 20.0, "CE1"),)),
        Elemento("RA2", "Sistemas", 25.0, criterios=(criterio("CE2", 80.0, "CE2"),)),
        Elemento("RA3", "Seguridad", 50.0),
    )
    assert reparto(esquema, ("CE1", "CE2")) == (("CE1", 2.0), ("CE2", 8.0))


def test_reparto_mayor_resto_suma_exacta() -> None:
    esquema = esquema_de(
        Elemento(
            "RA1",
            "Redes",
            100.0,
            criterios=(criterio("CE1"), criterio("CE2"), criterio("CE3")),
        )
    )
    filas = reparto(esquema, ("CE1", "CE2", "CE3"))
    assert filas == (("CE1", 3.33), ("CE2", 3.33), ("CE3", 3.34))
    assert round(sum(puntos for _, puntos in filas), 2) == 10.0


def test_reparto_criterios_sin_peso_cuentan_igual_en_su_elemento() -> None:
    esquema = esquema_de(
        Elemento("RA1", "Redes", 100.0, criterios=(criterio("CE1"), criterio("CE2")))
    )
    assert reparto(esquema, ("CE1", "CE2")) == (("CE1", 5.0), ("CE2", 5.0))


def test_reparto_omite_peso_cero() -> None:
    esquema = esquema_de(
        Elemento(
            "RA1",
            "Redes",
            100.0,
            criterios=(criterio("CE1", 100.0), criterio("CE2", 0.0)),
        )
    )
    assert reparto(esquema, ("CE1", "CE2")) == (("CE1", 10.0),)


def test_reparto_todos_cero_da_rubrica_sin_pesos() -> None:
    esquema = esquema_de(Elemento("RA1", "Redes", 0.0, criterios=(criterio("CE1", 100.0),)))
    with pytest.raises(ErrorCalificacion) as exc:
        reparto(esquema, ("CE1",))
    assert exc.value.codigo == "RUBRICA_SIN_PESOS"


def test_reparto_id_desconocido_da_elemento_desconocido() -> None:
    esquema = esquema_de(Elemento("RA1", "Redes", 100.0))
    with pytest.raises(ErrorCalificacion) as exc:
        reparto(esquema, ("NO_EXISTE",))
    assert exc.value.codigo == "ELEMENTO_DESCONOCIDO"


def test_rubrica_una_fila_por_criterio_y_niveles_del_esquema() -> None:
    esquema = esquema_de(
        Elemento(
            "RA1",
            "Redes",
            100.0,
            criterios=(criterio("CE1", 50.0, "CE1"), criterio("CE2", 50.0, "CE2")),
        )
    )
    cargada = rubrica_de_criterios(esquema, ("CE1", "CE2"), "Problemas")
    assert [c.id for c in cargada.criterios] == ["ce1", "ce2"]
    assert [c.nombre for c in cargada.criterios] == [
        "CE1 · Criterio CE1",
        "CE2 · Criterio CE2",
    ]
    assert [c.descripcion for c in cargada.criterios] == ["Criterio CE1", "Criterio CE2"]
    assert [len(c.niveles) for c in cargada.criterios] == [5, 5]
    assert [n.puntos for n in cargada.criterios[0].niveles] == [5.0, 3.75, 2.5, 1.25, 0.0]
    assert "Esta tarea se califica por criterios de evaluación" in cargada.html
    assert "50 %" in cargada.html
    validar_rubrica(cargada)


def test_niveles_50_suman_exacto_con_333_y_667() -> None:
    esquema = esquema_de(
        Elemento("RA1", "Redes", 33.3),
        Elemento("RA2", "Sistemas", 66.7),
    )
    cargada = rubrica_de_criterios(esquema, ("RA1", "RA2"), "Problemas")
    assert [c.id for c in cargada.criterios] == ["ra1", "ra2"]
    filas = [(c.niveles[0].puntos, c.niveles[2].puntos) for c in cargada.criterios]
    assert filas[0][0] + filas[1][0] == 10.0
    assert filas[0][1] + filas[1][1] == 5.0
    assert filas[0] != (3.33, 1.67) or filas[1] != (6.67, 3.34)


def test_rubrica_determinista_y_hash_sensible_a_los_pesos() -> None:
    esquema = esquema_de(
        Elemento("RA1", "Redes", 40.0),
        Elemento("RA2", "Sistemas", 60.0),
    )
    primera = rubrica_de_criterios(esquema, ("RA1", "RA2"), "Problemas")
    segunda = rubrica_de_criterios(esquema, ("RA1", "RA2"), "Problemas")
    assert primera.hash() == segunda.hash()

    otro = esquema_de(
        Elemento("RA1", "Redes", 30.0),
        Elemento("RA2", "Sistemas", 70.0),
    )
    assert rubrica_de_criterios(otro, ("RA1", "RA2"), "Problemas").hash() != primera.hash()
