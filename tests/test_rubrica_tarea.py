"""Rúbrica de una tarea a partir de filas: indicadores, descriptores y pesos propios."""

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
from tiza.rubrica_tarea import FilaRubrica, rubrica_de_filas

NIVELES = ("destacado", "avanzado", "adecuado", "inicial", "no_iniciado")


def esquema_de(*elementos: Elemento, niveles: tuple[NivelRubrica, ...] | None = None) -> Esquema:
    kwargs = {} if niveles is None else {"niveles_rubrica": niveles}
    return Esquema(
        organizacion="elementos",
        elementos=tuple(elementos),
        evaluaciones=(),
        final=Final("elementos"),
        **kwargs,
    )


def esquema_con(*criterios: Criterio) -> Esquema:
    return esquema_de(Elemento("RA1", "Redes", 100.0, criterios=tuple(criterios)))


def criterio(id_: str, codigo: str | None = None) -> Criterio:
    return Criterio(id_, f"Criterio {id_}", None, codigo)


def descriptores(*, prefijo: str = "Descriptor") -> dict[str, str]:
    return {nivel: f"{prefijo} {nivel}" for nivel in NIVELES}


def rubrica(
    esquema: Esquema,
    filas: tuple[FilaRubrica, ...],
    *,
    nombre: str = "Rúbrica de la grúa",
    descripcion: str = "Descripción de la rúbrica.",
    html: str = "<p>Descripción de la rúbrica.</p>\n",
):
    return rubrica_de_filas(esquema, filas, nombre, descripcion, html)


def test_puntos_por_peso_de_fila() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"), criterio("CE2", "1.2"))
    cargada = rubrica(
        esquema,
        (
            FilaRubrica("CE1", "Indicador uno", 1.0, descriptores(prefijo="Uno")),
            FilaRubrica("CE2", "Indicador dos", 2.0, descriptores(prefijo="Dos")),
        ),
    )
    assert [c.niveles[0].puntos for c in cargada.criterios] == [3.33, 6.67]
    assert [c.niveles[-1].puntos for c in cargada.criterios] == [0.0, 0.0]


def test_sin_pesos_pesan_igual() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"), criterio("CE2", "1.2"))
    cargada = rubrica(
        esquema,
        (
            FilaRubrica("CE1", "Indicador uno", None, descriptores()),
            FilaRubrica("CE2", "Indicador dos", None, descriptores()),
        ),
    )
    assert [c.niveles[0].puntos for c in cargada.criterios] == [5.0, 5.0]


def test_pesos_incompletos() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"), criterio("CE2", "1.2"))
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(
            esquema,
            (
                FilaRubrica("CE1", "Indicador uno", 1.0, descriptores()),
                FilaRubrica("CE2", "Indicador dos", None, descriptores()),
            ),
        )
    assert exc.value.codigo == "PESOS_DE_FILA_INCOMPLETOS"


def test_tres_filas_iguales_suman_10() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"), criterio("CE2", "1.2"), criterio("CE3", "1.3"))
    cargada = rubrica(
        esquema,
        (
            FilaRubrica("CE1", "Indicador uno", None, descriptores()),
            FilaRubrica("CE2", "Indicador dos", None, descriptores()),
            FilaRubrica("CE3", "Indicador tres", None, descriptores()),
        ),
    )
    assert [c.niveles[0].puntos for c in cargada.criterios] == [3.33, 3.33, 3.34]
    for posicion, nivel in enumerate(esquema.niveles_rubrica):
        suma = sum(c.niveles[posicion].puntos for c in cargada.criterios)
        assert round(suma, 2) == round(10.0 * nivel.porcentaje / 100, 2)


def test_ids_de_fila() -> None:
    esquema = esquema_con(criterio("CE3_1", "3.1"), criterio("CE2_2", "2.2"))
    cargada = rubrica(
        esquema,
        (
            FilaRubrica("CE3_1", "Primera", None, descriptores()),
            FilaRubrica("CE3_1", "Segunda", None, descriptores()),
            FilaRubrica("CE2_2", "Tercera", None, descriptores()),
        ),
    )
    assert [c.id for c in cargada.criterios] == ["ce3_1", "ce3_1_2", "ce2_2"]
    assert [c.criterio for c in cargada.criterios] == ["CE3_1", "CE3_1", "CE2_2"]


def test_nombre_y_definicion() -> None:
    esquema = esquema_con(Criterio("CE3_1", "Montaje de la grúa", None, "3.1"))
    con_descriptor = descriptores()
    con_descriptor["destacado"] = "Monta sin errores."
    cargada = rubrica(
        esquema,
        (FilaRubrica("CE3_1", "Precisión del montaje", None, con_descriptor),),
    )
    fila = cargada.criterios[0]
    assert fila.nombre == "3.1 · Precisión del montaje"
    assert fila.descripcion == "Montaje de la grúa"
    assert fila.niveles[0].descripcion == "Destacado: Monta sin errores."
    assert fila.niveles[1].puntos == 7.5
    assert fila.niveles[1].descripcion == "Avanzado: Descriptor avanzado"


def test_sin_codigo_la_fila_se_llama_como_el_criterio() -> None:
    esquema = esquema_con(criterio("CE2_2"))
    cargada = rubrica(
        esquema,
        (FilaRubrica("CE2_2", "Un indicador", None, descriptores()),),
    )
    assert cargada.criterios[0].nombre == "CE2_2"


def test_nombre_descripcion_y_html_se_conservan() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    cargada = rubrica(
        esquema,
        (FilaRubrica("CE1", "Indicador", None, descriptores()),),
        nombre="Rúbrica de la grúa",
        descripcion="Texto llano.",
        html="<p>Texto con HTML.</p>\n",
    )
    assert cargada.nombre == "Rúbrica de la grúa"
    assert cargada.descripcion == "Texto llano."
    assert cargada.html == "<p>Texto con HTML.</p>\n"


def test_criterio_que_no_es_hoja_del_esquema() -> None:
    esquema = esquema_de(Elemento("RA1", "Redes", 100.0, criterios=(criterio("CE1", "1.1"),)))
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (FilaRubrica("RA1", "Indicador", None, descriptores()),))
    assert exc.value.codigo == "ELEMENTO_CON_CRITERIOS"

    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (FilaRubrica("NO_EXISTE", "Indicador", None, descriptores()),))
    assert exc.value.codigo == "ELEMENTO_DESCONOCIDO"


def test_mas_de_veinte_filas() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    filas = tuple(
        FilaRubrica("CE1", f"Indicador {numero}", None, descriptores()) for numero in range(1, 22)
    )
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, filas)
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"


def test_filas_repetidas() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    fila = FilaRubrica("CE1", "El mismo indicador", None, descriptores())
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (fila, fila))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"


@pytest.mark.parametrize("peso", [0, -1, 101, 1.234, True])
def test_peso_invalido(peso: float) -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (FilaRubrica("CE1", "Indicador", peso, descriptores()),))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"


def test_indicador_y_descriptor_demasiado_largos() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (FilaRubrica("CE1", "x" * 101, None, descriptores()),))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"

    largos = descriptores()
    largos["destacado"] = "x" * 1001
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (FilaRubrica("CE1", "Indicador", None, largos),))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"


def test_titulo_de_fila_demasiado_largo() -> None:
    esquema = esquema_con(Criterio("CE1", "Montaje", None, "C" * 25))
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (FilaRubrica("CE1", "x" * 100, None, descriptores()),))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "120" in exc.value.detalle


def test_descriptor_compuesto_demasiado_largo() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    largos = descriptores()
    largos["destacado"] = "x" * 1000
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (FilaRubrica("CE1", "Indicador", None, largos),))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert str(1000 - len("Destacado") - 2) in exc.value.detalle


def test_descriptor_falta() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    incompletos = descriptores()
    del incompletos["avanzado"]
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (FilaRubrica("CE1", "Indicador", None, incompletos),))
    assert exc.value.codigo == "DESCRIPTOR_FALTA"


def test_nivel_desconocido() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    sobran = descriptores()
    sobran["otro"] = "No existe."
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (FilaRubrica("CE1", "Indicador", None, sobran),))
    assert exc.value.codigo == "NIVEL_DESCONOCIDO"


def test_descriptores_no_es_un_mapa() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (FilaRubrica("CE1", "Indicador", None, ["destacado"]),))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"


def test_veinte_filas_es_el_limite() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    filas = tuple(
        FilaRubrica("CE1", f"Indicador {numero}", None, descriptores()) for numero in range(1, 21)
    )
    assert len(rubrica(esquema, filas).criterios) == 20


def test_indicador_de_cien_caracteres_se_acepta() -> None:
    esquema = esquema_con(criterio("CE1"))
    cargada = rubrica(esquema, (FilaRubrica("CE1", "x" * 100, None, descriptores()),))
    assert cargada.criterios[0].nombre == "CE1"


@pytest.mark.parametrize("peso", [0.01, 100])
def test_peso_en_los_limites(peso: float) -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    cargada = rubrica(esquema, (FilaRubrica("CE1", "Indicador", peso, descriptores()),))
    assert cargada.criterios[0].niveles[0].puntos == 10.0


def test_peso_no_numerico() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (FilaRubrica("CE1", "Indicador", "1", descriptores()),))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"


def test_peso_entero_enorme() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"))
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(esquema, (FilaRubrica("CE1", "Indicador", 10**400, descriptores()),))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"


def test_peso_relativo_demasiado_pequeno() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"), criterio("CE2", "1.2"))
    with pytest.raises(ErrorCalificacion) as exc:
        rubrica(
            esquema,
            (
                FilaRubrica("CE1", "Indicador uno", 0.01, descriptores()),
                FilaRubrica("CE2", "Indicador dos", 100, descriptores()),
            ),
        )
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "fila 1" in exc.value.detalle
    assert "peso" in exc.value.detalle


def test_rubrica_determinista() -> None:
    esquema = esquema_con(criterio("CE1", "1.1"), criterio("CE2", "1.2"))
    filas = (
        FilaRubrica("CE1", "Uno", 1.0, descriptores(prefijo="Uno")),
        FilaRubrica("CE2", "Dos", 2.0, descriptores(prefijo="Dos")),
    )
    primera = rubrica(esquema, filas)
    segunda = rubrica(esquema, filas)
    assert primera.hash() == segunda.hash()
