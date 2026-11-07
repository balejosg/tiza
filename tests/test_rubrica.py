"""Tipos neutros de rúbrica: hash compatible con tiza-privado, límites e ids."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tiza.contenido import ErrorContenido
from tiza.rubrica import CriterioRubrica, Nivel, RubricaCargada, validar_rubrica


def rubrica_de_prueba() -> RubricaCargada:
    """La misma rúbrica con la que se midió el hash en tiza-privado."""
    return RubricaCargada(
        nombre="Rúbrica de prueba",
        descripcion="Rúbrica para el alumnado.",
        html="<p>Rúbrica para el alumnado.</p>\n",
        criterios=(
            CriterioRubrica(
                id="contenido",
                nombre="Contenido",
                descripcion="Ventajas e inconvenientes.",
                niveles=(
                    Nivel(id="alto", puntos=4.0, descripcion="Varias ventajas."),
                    Nivel(id="medio", puntos=2.0, descripcion="Alguna ventaja."),
                    Nivel(id="bajo", puntos=0.0, descripcion="Ninguna."),
                ),
            ),
            CriterioRubrica(
                id="forma",
                nombre="Forma",
                descripcion="Ortografía y orden.",
                niveles=(
                    Nivel(id="bien", puntos=3.0, descripcion="Sin faltas."),
                    Nivel(id="regular", puntos=1.5, descripcion="Algunas faltas."),
                    Nivel(id="mal", puntos=0.0, descripcion="Muchas faltas."),
                ),
            ),
        ),
    )


def test_hash_de_siempre() -> None:
    # Medido con RubricaCargada.hash de tiza-privado y anotado en la Tarea 1 del
    # plan de la rúbrica por criterios: no puede cambiar.
    assert rubrica_de_prueba().hash() == (
        "fc3e98b7cf3bc070e1835a259ccee0f4f51eccbfc5d2031bf49ee8b9b6f42b7a"
    )


def test_criterio_no_entra_en_el_hash() -> None:
    sin_criterio = rubrica_de_prueba()
    con_criterio = RubricaCargada(
        nombre=sin_criterio.nombre,
        descripcion=sin_criterio.descripcion,
        html=sin_criterio.html,
        criterios=tuple(replace(criterio, criterio="CE1") for criterio in sin_criterio.criterios),
    )
    assert con_criterio.criterios[0].criterio == "CE1"
    assert con_criterio.hash() == sin_criterio.hash()


def test_limites() -> None:
    valida = rubrica_de_prueba()
    with pytest.raises(ErrorContenido) as exc:
        validar_rubrica(
            RubricaCargada(
                nombre=valida.nombre,
                descripcion=valida.descripcion,
                html=valida.html,
                criterios=tuple(
                    CriterioRubrica(
                        id=f"c{numero}",
                        nombre=f"Criterio {numero}",
                        descripcion="Algo.",
                        niveles=valida.criterios[0].niveles,
                    )
                    for numero in range(1, 22)
                ),
            )
        )
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"

    with pytest.raises(ErrorContenido) as exc:
        validar_rubrica(
            RubricaCargada(
                nombre=valida.nombre,
                descripcion=valida.descripcion,
                html=valida.html,
                criterios=(
                    CriterioRubrica(
                        id="contenido",
                        nombre="Contenido",
                        descripcion="x" * 1001,
                        niveles=valida.criterios[0].niveles,
                    ),
                ),
            )
        )
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"

    with pytest.raises(ErrorContenido) as exc:
        validar_rubrica(
            RubricaCargada(
                nombre=valida.nombre,
                descripcion=valida.descripcion,
                html=valida.html,
                criterios=(
                    CriterioRubrica(
                        id="contenido",
                        nombre="Contenido",
                        descripcion="Algo.",
                        niveles=(
                            Nivel(id="alto", puntos=101.0, descripcion="Mucho."),
                            Nivel(id="bajo", puntos=0.0, descripcion="Nada."),
                        ),
                    ),
                ),
            )
        )
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"


def test_ids_invalidos() -> None:
    valida = rubrica_de_prueba()
    for id_criterio in ("1contenido", "con-tenido", "con tenido", ""):
        with pytest.raises(ErrorContenido) as exc:
            validar_rubrica(
                RubricaCargada(
                    nombre=valida.nombre,
                    descripcion=valida.descripcion,
                    html=valida.html,
                    criterios=(
                        CriterioRubrica(
                            id=id_criterio,
                            nombre="Contenido",
                            descripcion="Algo.",
                            niveles=valida.criterios[0].niveles,
                        ),
                    ),
                )
            )
        assert exc.value.codigo == "RUBRICA_NO_VALIDA"

    with pytest.raises(ErrorContenido) as exc:
        validar_rubrica(
            RubricaCargada(
                nombre=valida.nombre,
                descripcion=valida.descripcion,
                html=valida.html,
                criterios=(
                    CriterioRubrica(
                        id="contenido",
                        nombre="Contenido",
                        descripcion="Algo.",
                        niveles=(
                            Nivel(id="1alto", puntos=4.0, descripcion="Alto."),
                            Nivel(id="bajo", puntos=0.0, descripcion="Bajo."),
                        ),
                    ),
                ),
            )
        )
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"

    with pytest.raises(ErrorContenido) as exc:
        validar_rubrica(
            RubricaCargada(
                nombre=valida.nombre,
                descripcion=valida.descripcion,
                html=valida.html,
                criterios=(
                    CriterioRubrica(
                        id="contenido",
                        nombre="Contenido",
                        descripcion="Algo.",
                        niveles=(
                            Nivel(id="alto", puntos=4.0, descripcion="Alto."),
                            Nivel(id="alto", puntos=0.0, descripcion="Bajo."),
                        ),
                    ),
                ),
            )
        )
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
