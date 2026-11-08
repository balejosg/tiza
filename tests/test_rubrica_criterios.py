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


# --- rubrica: por_criterios en una tarea ------------------------------------

from dobles import MoodleFalso, aula_con_tarea, estructura_de  # noqa: E402
from tiza import agente, contenido, publicar, tipos  # noqa: E402
from tiza.contenido import ErrorContenido  # noqa: E402

ESQUEMA_ESO = """\
etapa: eso
organizacion: elementos
elementos:
  - {id: RA1, nombre: Redes, peso: 100}
final: {de: elementos}
"""

TAREA_CON_RUBRICA = """\
---
tipo: tarea
nombre: Problemas
seccion: 3
apertura: 2026-10-01
entrega: 2026-10-10
evalua: {CE1: 100, CE2: 100}
rubrica: por_criterios
---

Resuelve los problemas.
"""


def _carpeta(tmp_path, *, etapa: str = "etapa: eso\n", evalua: str = "{CE1: 100, CE2: 100}"):
    (tmp_path / "calificacion.yaml").write_text(
        ESQUEMA_ESO.replace("etapa: eso\n", etapa).replace(
            "{id: RA1, nombre: Redes, peso: 100}",
            "{id: RA1, nombre: Redes, peso: 100, criterios: "
            "[{id: CE1, nombre: Criterio 1, peso: 50, codigo: CE1}, "
            "{id: CE2, nombre: Criterio 2, peso: 50, codigo: CE2}]}",
        ),
        encoding="utf-8",
    )
    (tmp_path / "tarea.md").write_text(
        TAREA_CON_RUBRICA.replace("{CE1: 100, CE2: 100}", evalua), encoding="utf-8"
    )
    return tmp_path / "tarea.md"


def test_por_criterios_con_eso_carga_la_rubrica(tmp_path) -> None:
    doc = contenido.cargar(_carpeta(tmp_path), raiz=tmp_path)
    assert doc.rubrica is not None
    assert [c.id for c in doc.rubrica.criterios] == ["ce1", "ce2"]
    assert [c.niveles[0].puntos for c in doc.rubrica.criterios] == [5.0, 5.0]


def test_por_criterios_sin_evalua(tmp_path) -> None:
    ruta = _carpeta(tmp_path)
    ruta.write_text(
        TAREA_CON_RUBRICA.replace("evalua: {CE1: 100, CE2: 100}\n", ""), encoding="utf-8"
    )
    with pytest.raises(ErrorContenido) as exc:
        contenido.cargar(ruta, raiz=tmp_path)
    assert exc.value.codigo == "RUBRICA_SIN_EVALUA"


def test_por_criterios_sin_calificacion_yaml(tmp_path) -> None:
    ruta = _carpeta(tmp_path)
    (tmp_path / "calificacion.yaml").unlink()
    with pytest.raises(ErrorContenido) as exc:
        contenido.cargar(ruta, raiz=tmp_path)
    assert exc.value.codigo == "RUBRICA_SIN_ESQUEMA"


@pytest.mark.parametrize(
    "etapa", ["", "etapa: bachillerato\n", "etapa: fp\n"], ids=["sin", "bachillerato", "fp"]
)
def test_por_criterios_en_cualquier_etapa(tmp_path, etapa) -> None:
    carpeta = tmp_path / (etapa.strip().replace(":", "_") or "sin_etapa")
    carpeta.mkdir()
    ruta = _carpeta(carpeta, etapa=etapa)
    doc = contenido.cargar(ruta, raiz=carpeta)
    assert doc.rubrica is not None


def test_ruta_de_rubrica_que_no_existe(tmp_path) -> None:
    ruta = _carpeta(tmp_path)
    ruta.write_text(
        TAREA_CON_RUBRICA.replace("rubrica: por_criterios", "rubrica: rubrica.md"),
        encoding="utf-8",
    )
    with pytest.raises(ErrorContenido) as exc:
        contenido.cargar(ruta, raiz=tmp_path)
    assert exc.value.codigo == "FICHERO_AUSENTE"


def test_por_criterios_con_elemento_con_criterios(tmp_path) -> None:
    ruta = _carpeta(tmp_path, evalua="{RA1: 100}")
    with pytest.raises(ErrorContenido) as exc:
        contenido.cargar(ruta, raiz=tmp_path)
    assert exc.value.codigo == "ELEMENTO_CON_CRITERIOS"


def test_publicar_tarea_nueva_define_la_rubrica(tmp_path) -> None:
    doc = contenido.cargar(_carpeta(tmp_path), raiz=tmp_path)
    moodle = MoodleFalso()
    publicar.publicar_documento(moodle, 1234, estructura_de(moodle.secciones), doc, visible=None)
    assert any(llamada[0] == "definir_rubrica" for llamada in moodle.llamadas)
    assert moodle.formularios[100][publicar.METODO_SUBMISSIONS] == "rubric"


def test_publicar_tarea_existente_sin_confirmacion_no_define_la_rubrica(tmp_path) -> None:
    doc = contenido.cargar(_carpeta(tmp_path), raiz=tmp_path)
    moodle = aula_con_tarea()
    pasos = []
    publicar.publicar_documento(
        moodle,
        1234,
        estructura_de(moodle.secciones),
        doc,
        visible=None,
        pasos=pasos,
    )
    assert any(paso.codigo == "RUBRICA_NO_ACTIVADA" for paso in pasos)
    assert not any(llamada[0] == "definir_rubrica" for llamada in moodle.llamadas)
    assert publicar.METODO_SUBMISSIONS not in moodle.formularios[55]


def test_publicar_tarea_existente_confirmada_define_la_rubrica(tmp_path) -> None:
    doc = contenido.cargar(_carpeta(tmp_path), raiz=tmp_path)
    moodle = aula_con_tarea()
    pasos = []
    publicar.publicar_documento(
        moodle,
        1234,
        estructura_de(moodle.secciones),
        doc,
        visible=None,
        rubrica_confirmada=True,
        pasos=pasos,
    )
    assert not any(paso.codigo == "RUBRICA_NO_ACTIVADA" for paso in pasos)
    assert any(llamada[0] == "definir_rubrica" for llamada in moodle.llamadas)
    assert moodle.formularios[55][publicar.METODO_SUBMISSIONS] == "rubric"


def test_publicar_tarea_con_notas_da_rubrica_no_activada(tmp_path) -> None:
    doc = contenido.cargar(_carpeta(tmp_path), raiz=tmp_path)
    moodle = aula_con_tarea()
    moodle.tareas_con_notas.add(55)
    pasos = []
    publicar.publicar_documento(
        moodle,
        1234,
        estructura_de(moodle.secciones),
        doc,
        visible=None,
        rubrica_confirmada=True,
        pasos=pasos,
    )
    assert any(paso.codigo == "RUBRICA_NO_ACTIVADA" for paso in pasos)
    assert not any(llamada[0] == "definir_rubrica" for llamada in moodle.llamadas)
    assert publicar.METODO_SUBMISSIONS not in moodle.formularios[55]


def test_vista_previa_muestra_porcentajes(tmp_path) -> None:
    doc = contenido.cargar(_carpeta(tmp_path), raiz=tmp_path)
    vista = tipos.obtener("tarea").extra_preview(doc)
    assert "Rúbrica" in vista
    assert "50 %" in vista
    assert "CE1 · Criterio 1" in vista


def test_tarea_sin_rubrica_mantiene_su_hash(tmp_path) -> None:
    (tmp_path / "tarea.md").write_text(
        "---\ntipo: tarea\nnombre: Problemas\nseccion: 3\n"
        "apertura: 2026-10-01\nentrega: 2026-10-10\n---\nResuelve los problemas.\n",
        encoding="utf-8",
    )
    doc = contenido.cargar(tmp_path / "tarea.md")
    assert doc.hash_cargado == "c354d075fa17e1bd5796e07fb8642f175bcbeb62485b58381b491d58b366af69"


def test_comprobar_da_los_errores_offline(tmp_path) -> None:
    ruta = _carpeta(tmp_path, evalua="{RA1: 100}")
    resultado = agente.comprobar(tmp_path, [ruta.name])
    assert resultado.ficheros[0].codigo == "ELEMENTO_CON_CRITERIOS"
    assert "ELEMENTO_CON_CRITERIOS" in resultado.informe["errores"]


# --- Tarea importada del aula (retrofit) ------------------------------------


def _carpeta_importada(tmp_path):
    _carpeta(tmp_path)
    ruta = tmp_path / "tarea.md"
    texto = ruta.read_text(encoding="utf-8").replace(
        "rubrica: por_criterios\n",
        "rubrica: por_criterios\norigen: {curso: 1234, cmid: 55}\n",
    )
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def test_importada_sin_notas_recibe_la_rubrica_al_publicar(tmp_path) -> None:
    doc = contenido.cargar(_carpeta_importada(tmp_path), raiz=tmp_path)
    moodle = aula_con_tarea()
    resultado = publicar.publicar_documento(
        moodle,
        1234,
        estructura_de(moodle.secciones),
        doc,
        visible=None,
        rubrica_confirmada=True,
    )
    assert resultado.cmid == 55
    assert any(llamada[0] == "definir_rubrica" for llamada in moodle.llamadas)
    assert moodle.formularios[55][publicar.METODO_SUBMISSIONS] == "rubric"


def test_importada_con_notas_conserva_su_metodo(tmp_path) -> None:
    doc = contenido.cargar(_carpeta_importada(tmp_path), raiz=tmp_path)
    moodle = aula_con_tarea()
    moodle.tareas_con_notas.add(55)
    pasos: list = []
    publicar.publicar_documento(
        moodle,
        1234,
        estructura_de(moodle.secciones),
        doc,
        visible=None,
        rubrica_confirmada=True,
        pasos=pasos,
    )
    assert [paso.codigo for paso in pasos] == ["RUBRICA_NO_ACTIVADA"]
    assert not any(llamada[0] == "definir_rubrica" for llamada in moodle.llamadas)
    assert publicar.METODO_SUBMISSIONS not in moodle.formularios[55]


def test_importada_sin_cambios_salvo_la_rubrica_mantiene_la_descripcion(tmp_path) -> None:
    doc = contenido.cargar(_carpeta_importada(tmp_path), raiz=tmp_path)
    moodle = aula_con_tarea()
    moodle.formularios[55]["introeditor[text]"] = doc.html
    publicar.publicar_documento(
        moodle,
        1234,
        estructura_de(moodle.secciones),
        doc,
        visible=None,
        rubrica_confirmada=True,
    )
    actualizar = next(llamada for llamada in moodle.llamadas if llamada[0] == "actualizar")
    assert actualizar[2]["introeditor[text]"] == doc.html
