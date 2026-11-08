"""Rúbrica de una tarea a partir de filas: indicadores, descriptores y pesos propios."""

from __future__ import annotations

from pathlib import Path

import pytest

from dobles import enlace_simbolico
from tiza.calificacion.esquema import (
    Criterio,
    Elemento,
    ErrorCalificacion,
    Esquema,
    Final,
    NivelRubrica,
)
from tiza.contenido import MAX_DOCUMENTO_BYTES, ErrorContenido
from tiza.rubrica_tarea import (
    FilaRubrica,
    cargar_filas_de_tarea,
    cargar_rubrica_de_tarea,
    rubrica_de_filas,
)

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


# --- carga del fichero de rúbrica -------------------------------------------


def texto_rubrica(
    filas: str,
    *,
    nombre: str = "Rúbrica de la grúa",
    cuerpo: str = "Descripción de la rúbrica para el alumnado.\n",
    extra: str = "",
) -> str:
    return f"---\ntipo: rubrica\nnombre: {nombre}\n{extra}filas:\n{filas}---\n{cuerpo}"


def fila_yaml(
    criterio: str = "CE1",
    indicador: str = "Indicador",
    *,
    peso: float | None = None,
    niveles: dict[str, str] | None = None,
) -> str:
    lineas = [f"  - criterio: {criterio}", f"    indicador: {indicador}"]
    if peso is not None:
        lineas.append(f"    peso: {peso}")
    lineas.append("    niveles:")
    for nivel, texto in (niveles or descriptores()).items():
        lineas.append(f"      {nivel}: {texto}")
    return "\n".join(lineas) + "\n"


def escribir_rubrica(tmp_path, texto: str) -> Path:
    ruta = tmp_path / "rubricas" / "grua.md"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8", newline="\n")  # igual en Windows
    return ruta


def cargar_desde(
    tmp_path,
    texto: str,
    *,
    evalua: tuple[tuple[str, float], ...] = (("CE1", 100.0),),
):
    return cargar_rubrica_de_tarea(
        escribir_rubrica(tmp_path, texto),
        tmp_path,
        esquema_con(criterio("CE1", "1.1"), criterio("CE2", "1.2")),
        evalua,
    )


def test_carga_fichero_de_filas(tmp_path) -> None:
    cargada = cargar_desde(
        tmp_path,
        texto_rubrica(fila_yaml(peso=1) + fila_yaml("CE2", "Otro indicador", peso=2)),
        evalua=(("CE1", 100.0), ("CE2", 100.0)),
    )
    assert len(cargada.criterios) == 2
    assert [c.criterio for c in cargada.criterios] == ["CE1", "CE2"]
    assert [c.niveles[0].puntos for c in cargada.criterios] == [3.33, 6.67]
    assert cargada.nombre == "Rúbrica de la grúa"
    assert cargada.descripcion == "Descripción de la rúbrica para el alumnado.\n"
    assert "<p>Descripción de la rúbrica para el alumnado.</p>" in cargada.html


def test_fichero_libre_en_el_publico(tmp_path) -> None:
    texto = (
        "---\ntipo: rubrica\nnombre: Rúbrica\n"
        "criterios:\n  - {id: contenido, nombre: Contenido, descripcion: Algo, niveles: []}\n"
        "---\n\nDescripción.\n"
    )
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto)
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "tiza-privado" in exc.value.detalle


def test_indicaciones_en_el_publico(tmp_path) -> None:
    texto = texto_rubrica(
        fila_yaml(),
        extra="indicaciones:\n  - Penaliza menos la ortografía.\n",
    )
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto)
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "tiza-privado" in exc.value.detalle


def test_fila_fuera_de_evalua(tmp_path) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto_rubrica(fila_yaml("CE2", "Otro indicador")))
    assert exc.value.codigo == "FILA_FUERA_DE_EVALUA"
    assert "CE2" in exc.value.detalle


def test_criterio_sin_fila(tmp_path) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(
            tmp_path,
            texto_rubrica(fila_yaml("CE1")),
            evalua=(("CE1", 100.0), ("CE2", 100.0)),
        )
    assert exc.value.codigo == "CRITERIO_SIN_FILA"
    assert "CE2" in exc.value.detalle


@pytest.mark.parametrize(
    ("cambio", "codigo", "nivel"),
    [
        ("falta", "DESCRIPTOR_FALTA", "avanzado"),
        ("sobra", "NIVEL_DESCONOCIDO", "otro"),
        ("sobra", "NIVEL_DESCONOCIDO", "Nivel6"),
    ],
)
def test_descriptor_falta_y_nivel_desconocido(tmp_path, cambio, codigo, nivel) -> None:
    niveles = descriptores()
    if cambio == "falta":
        del niveles[nivel]
    else:
        niveles[nivel] = "No existe."
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto_rubrica(fila_yaml(niveles=niveles)))
    assert exc.value.codigo == codigo
    assert "grua.md" in exc.value.detalle
    assert nivel in exc.value.detalle


def test_coma_sin_comillas(tmp_path) -> None:
    filas = (
        "  - {criterio: CE1, indicador: Hace A, "
        "niveles: {destacado: Secuencia completa, con tiempos, avanzado: Dos, "
        "adecuado: Tres, inicial: Cuatro, no_iniciado: Cinco}}\n"
    )
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto_rubrica(filas))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "comillas" in exc.value.detalle
    assert "grua.md" in exc.value.detalle


def test_criterio_que_no_es_hoja(tmp_path) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(
            tmp_path,
            texto_rubrica(fila_yaml("RA1")),
            evalua=(("RA1", 100.0),),
        )
    assert exc.value.codigo == "FILA_FUERA_DE_EVALUA"
    assert "RA1" in exc.value.detalle


def test_cuerpo_vacio(tmp_path) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto_rubrica(fila_yaml(), cuerpo=""))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "alumnado" in exc.value.detalle


def test_rubrica_fuera_de_carpeta(tmp_path) -> None:
    fuera = tmp_path / "fuera" / "grua.md"
    fuera.parent.mkdir()
    fuera.write_text(texto_rubrica(fila_yaml()), encoding="utf-8")
    dentro = tmp_path / "asig"
    dentro.mkdir()
    with pytest.raises(ErrorContenido) as exc:
        cargar_rubrica_de_tarea(
            fuera,
            dentro,
            esquema_con(criterio("CE1", "1.1")),
            (("CE1", 100.0),),
        )
    assert exc.value.codigo == "RUBRICA_FUERA_DE_CARPETA"


def test_fichero_ausente(tmp_path) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_rubrica_de_tarea(
            tmp_path / "no_existe.md",
            tmp_path,
            esquema_con(criterio("CE1", "1.1")),
            (("CE1", 100.0),),
        )
    assert exc.value.codigo == "FICHERO_AUSENTE"


def test_fichero_demasiado_grande(tmp_path) -> None:
    ruta = tmp_path / "grande.md"
    ruta.write_bytes(b"x" * (MAX_DOCUMENTO_BYTES + 1))
    with pytest.raises(ErrorContenido) as exc:
        cargar_rubrica_de_tarea(
            ruta,
            tmp_path,
            esquema_con(criterio("CE1", "1.1")),
            (("CE1", 100.0),),
        )
    assert exc.value.codigo == "FICHERO_DEMASIADO_GRANDE"


def test_codificacion_invalida(tmp_path) -> None:
    ruta = tmp_path / "mal.md"
    ruta.write_bytes(b"---\ntipo: rubrica\n---\n\xff")
    with pytest.raises(ErrorContenido) as exc:
        cargar_rubrica_de_tarea(
            ruta,
            tmp_path,
            esquema_con(criterio("CE1", "1.1")),
            (("CE1", 100.0),),
        )
    assert exc.value.codigo == "CODIFICACION_INVALIDA"


def test_enlace_a_rubrica_fuera_de_carpeta(tmp_path) -> None:
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    destino = fuera / "grua.md"
    destino.write_text(texto_rubrica(fila_yaml()), encoding="utf-8")
    dentro = tmp_path / "asig"
    enlace = dentro / "rubricas" / "grua.md"
    enlace.parent.mkdir(parents=True)
    enlace_simbolico(enlace, destino)
    with pytest.raises(ErrorContenido) as exc:
        cargar_rubrica_de_tarea(
            enlace,
            dentro,
            esquema_con(criterio("CE1", "1.1")),
            (("CE1", 100.0),),
        )
    assert exc.value.codigo == "RUBRICA_FUERA_DE_CARPETA"


def test_enlace_circular_da_fichero_ausente(tmp_path) -> None:
    enlace = tmp_path / "rubricas" / "grua.md"
    enlace.parent.mkdir()
    enlace_simbolico(enlace, enlace)
    with pytest.raises(ErrorContenido) as exc:
        cargar_rubrica_de_tarea(
            enlace,
            tmp_path,
            esquema_con(criterio("CE1", "1.1")),
            (("CE1", 100.0),),
        )
    assert exc.value.codigo == "FICHERO_AUSENTE"


def test_sin_raiz_carga(tmp_path) -> None:
    ruta = escribir_rubrica(tmp_path, texto_rubrica(fila_yaml()))
    cargada = cargar_rubrica_de_tarea(
        ruta,
        None,
        esquema_con(criterio("CE1", "1.1")),
        (("CE1", 100.0),),
    )
    assert len(cargada.criterios) == 1


@pytest.mark.parametrize(
    "texto",
    [
        "---\nnombre: Rúbrica\nfilas:\n" + fila_yaml() + "---\n\nDescripción.\n",
        texto_rubrica(fila_yaml()).replace("tipo: rubrica", "tipo: pagina"),
    ],
)
def test_tipo_de_fichero_invalido(tmp_path, texto) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto)
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "grua.md" in exc.value.detalle


@pytest.mark.parametrize(
    "texto",
    [
        "---\ntipo: rubrica\nnombre: Rúbrica\n---\n\nDescripción.\n",
        "---\ntipo: rubrica\nnombre: Rúbrica\nfilas: []\n---\n\nDescripción.\n",
        "---\ntipo: rubrica\nnombre: Rúbrica\nfilas: 3\n---\n\nDescripción.\n",
    ],
)
def test_filas_invalidas(tmp_path, texto) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto)
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "filas" in exc.value.detalle


def test_fila_no_es_un_mapa(tmp_path) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto_rubrica("  - solo texto\n"))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "fila 1" in exc.value.detalle


@pytest.mark.parametrize(
    ("fila", "campo", "coma"),
    [
        (
            fila_yaml().replace("    indicador:", "    color: rojo\n    indicador:"),
            "color",
            False,
        ),
        (
            "  - {criterio: CE1, indicador: Hace A, luego B, "
            "niveles: {destacado: Uno, avanzado: Dos, adecuado: Tres, "
            "inicial: Cuatro, no_iniciado: Cinco}}\n",
            "luego B",
            True,
        ),
    ],
)
def test_campo_de_fila_no_permitido(tmp_path, fila, campo, coma) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto_rubrica(fila))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert campo in exc.value.detalle
    assert ("comillas" in exc.value.detalle) is coma


@pytest.mark.parametrize("nombre", [None, '""', '"' + "x" * 256 + '"'])
def test_nombre_invalido(tmp_path, nombre) -> None:
    if nombre is None:
        texto = "---\ntipo: rubrica\nfilas:\n" + fila_yaml() + "---\n\nDescripción.\n"
    else:
        texto = (
            "---\ntipo: rubrica\nnombre: "
            + nombre
            + "\nfilas:\n"
            + fila_yaml()
            + "---\n\nDescripción.\n"
        )
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto)
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "grua.md" in exc.value.detalle
    assert "nombre" in exc.value.detalle


@pytest.mark.parametrize(
    "fila",
    [
        fila_yaml().replace("criterio: CE1\n    ", ""),
        fila_yaml().replace("criterio: CE1", 'criterio: ""'),
        fila_yaml().replace("criterio: CE1", "criterio: 3"),
    ],
)
def test_criterio_invalido(tmp_path, fila) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto_rubrica(fila))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "grua.md" in exc.value.detalle
    assert "criterio" in exc.value.detalle


@pytest.mark.parametrize(
    "fila",
    [
        "  - criterio: CE1\n    indicador: Indicador\n",
        "  - criterio: CE1\n    indicador: Indicador\n    niveles: [destacado]\n",
    ],
)
def test_niveles_invalidos(tmp_path, fila) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto_rubrica(fila))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "niveles" in exc.value.detalle


def test_descriptor_no_es_texto(tmp_path) -> None:
    niveles = descriptores()
    niveles["destacado"] = 3
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto_rubrica(fila_yaml(niveles=niveles)))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "destacado" in exc.value.detalle


@pytest.mark.parametrize(
    "fila",
    [
        fila_yaml().replace("    indicador: Indicador\n", ""),
        fila_yaml().replace("indicador: Indicador", 'indicador: ""'),
        fila_yaml().replace("indicador: Indicador", "indicador: " + "x" * 101),
    ],
)
def test_indicador_invalido(tmp_path, fila) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto_rubrica(fila))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "indicador" in exc.value.detalle


@pytest.mark.parametrize("peso", ["x", "0", "101"])
def test_peso_de_fila_invalido(tmp_path, peso) -> None:
    fila = fila_yaml().replace("    niveles:", f"    peso: {peso}\n    niveles:")
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(tmp_path, texto_rubrica(fila))
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "peso" in exc.value.detalle


def test_descripcion_con_imagen_local(tmp_path) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(
            tmp_path,
            texto_rubrica(fila_yaml(), cuerpo="![foto](foto.png)\n"),
        )
    assert exc.value.codigo == "RUBRICA_NO_VALIDA"
    assert "imágenes" in exc.value.detalle


def test_descripcion_con_html_peligroso(tmp_path) -> None:
    with pytest.raises(ErrorContenido) as exc:
        cargar_desde(
            tmp_path,
            texto_rubrica(fila_yaml(), cuerpo="<script>alert(1)</script>\n"),
        )
    assert exc.value.codigo == "HTML_PELIGROSO"


# --- filas para los resultados: sin rúbrica nativa y sin comas -----------------


def cargar_para_resultados(tmp_path, texto: str):
    return cargar_filas_de_tarea(
        escribir_rubrica(tmp_path, texto),
        tmp_path,
        esquema_con(criterio("CE1", "1.1"), criterio("CE2", "1.2")),
        (("CE1", 100.0), ("CE2", 100.0)),
        tarea=tmp_path / "grua.md",
        base=tmp_path,
    )


def test_filas_para_resultados_con_pesos_y_niveles_ordenados(tmp_path) -> None:
    cargada = cargar_para_resultados(
        tmp_path,
        texto_rubrica(fila_yaml(peso=1) + fila_yaml("CE2", "Otro indicador", peso=2)),
    )
    assert cargada.nombre == "Rúbrica de la grúa"
    assert [fila.criterio for fila in cargada.filas] == ["CE1", "CE2"]
    assert [fila.peso for fila in cargada.filas] == [1.0, 2.0]
    assert cargada.filas[0].niveles == (
        "No iniciado: Descriptor no_iniciado",
        "Inicial: Descriptor inicial",
        "Adecuado: Descriptor adecuado",
        "Avanzado: Descriptor avanzado",
        "Destacado: Descriptor destacado",
    )
    assert cargada.filas[0].clave != cargada.filas[1].clave
    assert cargada.filas[0].clave.startswith("CE1_")


def test_descriptor_con_coma_da_linea(tmp_path) -> None:
    niveles = descriptores()
    niveles["avanzado"] = "Dos, con coma"
    with pytest.raises(ErrorContenido) as exc:
        cargar_para_resultados(
            tmp_path, texto_rubrica(fila_yaml(niveles=niveles) + fila_yaml("CE2", "Otro"))
        )
    assert exc.value.codigo == "DESCRIPTOR_CON_COMA"
    assert "grua.md" in exc.value.detalle
    assert "fila 1" in exc.value.detalle
    assert "avanzado" in exc.value.detalle
    assert "línea 9" in exc.value.detalle


def test_la_rubrica_nativa_sigue_admitiendo_comas(tmp_path) -> None:
    niveles = descriptores()
    niveles["avanzado"] = "Dos, con coma"
    cargada = cargar_desde(tmp_path, texto_rubrica(fila_yaml(niveles=niveles)))
    nivel = next(n for n in cargada.criterios[0].niveles if n.id == "avanzado")
    assert nivel.descripcion == "Avanzado: Dos, con coma"
