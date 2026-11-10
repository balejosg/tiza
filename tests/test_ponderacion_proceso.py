"""El proceso de ``tiza calificador ponderacion.yaml``: el trabajo del recorrido y sus preguntas.

El aula es ``AulaPonderada`` (``test_ponderacion_ejecucion``) y la presencia, ``PresenciaFalsa``.
El plan puro está en ``calificacion/test_ponderacion.py``; la ejecución, en
``test_ponderacion_ejecucion.py``.
"""

from __future__ import annotations

import dataclasses

import pytest
from calificacion.test_ponderacion import esquema_e1
from test_calificador import carpeta_fp, nodo
from test_ponderacion_ejecucion import (
    CURSO,
    REF_FICHEROS,
    AulaPonderada,
    aula_con_e1,
    ejecutar,
    huellas,
    pasos,
    preparar,
)

from dobles import MoodleFalso, PresenciaFalsa
from tiza import config, publicacion
from tiza.calificacion.carpeta import cargar_calificacion
from tiza.publicar import CalificadorAula, ErrorPublicacion

CFG_REAL = config.Config(
    url="https://aula.ejemplo.org/centro", usuario="profe", cursos={}, reales=(CURSO,)
)
CFG_PRUEBAS = config.Config(
    url="https://aula.ejemplo.org/centro", usuario="profe", cursos={"pruebas": CURSO}, reales=(9,)
)
CFG_DOS_REALES = config.Config(
    url="https://aula.ejemplo.org/centro", usuario="profe", cursos={}, reales=(CURSO, 3)
)


def cupo() -> dict:
    return {"pruebas": 0, "copias": 0, "copias_actividad": 0}


def ponderar(aula, cfg, tmp_path, presencia, entorno, **opciones) -> dict:
    return publicacion.ponderacion_en_cursos(
        aula,
        cfg,
        esquema_e1(),
        tmp_path,
        presencia,
        entorno=entorno,
        nombre_esquema="ponderacion.yaml",
        **opciones,
    )


def codigos(presencia: PresenciaFalsa) -> list[str]:
    return [aviso.codigo for aviso in presencia.avisos]


def aula_con_cambio_a_mano(tmp_path) -> AulaPonderada:
    """E4: el aula de E1 ya ponderada, y el docente sube el peso del test 1 de 16 a 20."""
    aula = aula_con_e1()
    ejecutar(aula, esquema_e1(), tmp_path)
    aula._cambiar("ig11", coeficiente=20.0, peso=20.0)
    aula.escrituras.clear()
    return aula


# --- en pruebas ---


def test_en_pruebas_no_pregunta_gasta_cupo_y_avisa(tmp_path):
    aula = aula_con_e1()
    presencia = PresenciaFalsa()
    gastado = cupo()
    resultado = ponderar(
        aula, CFG_PRUEBAS, tmp_path, presencia, "pruebas", cupo=gastado, avisar_en_pruebas=True
    )
    assert resultado["resultado"] == "ok" and resultado["comando"] == "calificador"
    assert pasos(resultado, "PONDERACION")[0]["detalle"] == "aplicada"
    assert gastado["pruebas"] == 1
    assert presencia.resumenes_ponderacion == []
    assert presencia.resumenes_ponderacion_a_mano == []
    [aviso] = [a for a in presencia.avisos if a.codigo == "PONDERANDO_EN_PRUEBAS"]
    assert aviso.datos == {"esquema": "ponderacion.yaml"}
    assert aula.escrituras


def test_en_pruebas_la_segunda_vez_tambien_gasta_cupo(tmp_path):
    aula = aula_con_e1()
    gastado = cupo()
    for _ in range(2):
        ponderar(aula, CFG_PRUEBAS, tmp_path, PresenciaFalsa(), "pruebas", cupo=gastado)
    assert gastado["pruebas"] == 2


def test_en_pruebas_un_plan_que_corta_no_escribe_y_dice_categoria_bloqueada(tmp_path, monkeypatch):
    aula = aula_con_e1()
    original = publicacion.preparar_ponderacion

    def cortando(*args, **kwargs):
        plan_curso = original(*args, **kwargs)
        corta = dataclasses.replace(plan_curso.plan, operaciones=(), corta=True)
        return dataclasses.replace(plan_curso, plan=corta)

    monkeypatch.setattr(publicacion, "preparar_ponderacion", cortando)
    resultado = ponderar(aula, CFG_PRUEBAS, tmp_path, PresenciaFalsa(), "pruebas", cupo=cupo())
    assert resultado["resultado"] == "error"
    assert resultado["errores"] == ["CATEGORIA_BLOQUEADA"]
    assert aula.escrituras == []


def test_en_pruebas_un_error_del_curso_es_un_informe_de_error(tmp_path):
    aula = aula_con_e1()
    aula.idnumbers[CURSO] = {"cg2": "TZ_TIZA"}
    resultado = ponderar(aula, CFG_PRUEBAS, tmp_path, PresenciaFalsa(), "pruebas", cupo=cupo())
    assert resultado["resultado"] == "error"
    assert resultado["errores"] == ["PONDERACION_CON_CALIFICADOR_DE_TIZA"]
    assert aula.escrituras == []


def test_en_pruebas_sin_curso_de_pruebas(tmp_path):
    resultado = ponderar(aula_con_e1(), CFG_REAL, tmp_path, PresenciaFalsa(), "pruebas")
    assert resultado["errores"] == ["SIN_CURSO_PRUEBAS"]


def test_en_pruebas_los_cambios_a_mano_se_dejan_y_se_avisan(tmp_path):
    aula = aula_con_cambio_a_mano(tmp_path)
    presencia = PresenciaFalsa()
    resultado = ponderar(aula, CFG_PRUEBAS, tmp_path, presencia, "pruebas", cupo=cupo())
    assert resultado["resultado"] == "ok"
    assert presencia.resumenes_ponderacion_a_mano == []
    assert "CAMBIADO_A_MANO" in codigos(presencia)
    assert aula.arboles_ponderacion[CURSO].nodo("ig11").coeficiente == 20.0


# --- en real ---


def test_en_real_pregunta_una_vez_con_el_antes_despues_y_escribe(tmp_path):
    aula = aula_con_e1()
    presencia = PresenciaFalsa()
    resultado = ponderar(aula, CFG_REAL, tmp_path, presencia, "real", nombres={CURSO: "4.º ESO"})
    assert resultado["resultado"] == "ok"
    [resumen] = presencia.resumenes_ponderacion
    assert (resumen.curso, resumen.nombre_curso, resumen.posicion, resumen.total) == (
        CURSO,
        "4.º ESO",
        1,
        1,
    )
    assert [c.nombre for c in resumen.afectadas] == ["Examen 1.ª evaluación", "PRIMERA EVALUACIÓN"]
    assert resumen.pesos_con_notas == ("PRIMERA EVALUACIÓN",)
    assert pasos(resultado, "PONDERACION")[0]["detalle"] == "aplicada"
    assert presencia.resumenes_ponderacion_a_mano == []
    assert codigos(presencia) == ["PESOS_CON_NOTAS"]
    assert aula.escrituras


def test_en_real_declinar_no_escribe_y_omite_el_curso(tmp_path):
    aula = aula_con_e1()
    presencia = PresenciaFalsa(real=False)
    resultado = ponderar(aula, CFG_REAL, tmp_path, presencia, "real")
    assert resultado["resultado"] == "abortado"
    assert len(presencia.resumenes_ponderacion) == 1
    assert aula.escrituras == []
    assert codigos(presencia) == []
    assert not (tmp_path / ".tiza" / "ponderacion.json").exists()


def test_en_real_una_pregunta_por_curso_con_su_posicion(tmp_path):
    aula = aula_con_e1()
    aula.arboles_ponderacion[3] = dataclasses.replace(aula.arboles_ponderacion[CURSO], curso=3)
    aula.arboles[3] = aula.arboles[CURSO]
    presencia = PresenciaFalsa(real=(False, False))
    ponderar(aula, CFG_DOS_REALES, tmp_path, presencia, "real")
    assert [(r.curso, r.posicion, r.total) for r in presencia.resumenes_ponderacion] == [
        (CURSO, 1, 2),
        (3, 2, 2),
    ]
    assert aula.escrituras == []


def test_en_real_sin_cambios_no_pregunta_y_anota_las_huellas(tmp_path):
    aula = aula_con_e1()
    ejecutar(aula, esquema_e1(), tmp_path)
    (tmp_path / ".tiza" / "ponderacion.json").unlink()
    aula.escrituras.clear()
    presencia = PresenciaFalsa()
    resultado = ponderar(aula, CFG_REAL, tmp_path, presencia, "real")
    assert resultado["resultado"] == "ok"
    assert pasos(resultado, "PONDERACION")[0]["detalle"] == "sin cambios"
    assert presencia.resumenes_ponderacion == []
    assert aula.escrituras == []
    assert set(huellas(tmp_path)) >= set(REF_FICHEROS)


def test_en_real_un_error_de_lectura_corta_sin_preguntar(tmp_path):
    aula = aula_con_e1()
    aula.fallos["arbol_ponderacion"] = ["LECTURA_CALIFICADOR"]
    presencia = PresenciaFalsa()
    resultado = ponderar(aula, CFG_REAL, tmp_path, presencia, "real")
    assert resultado["errores"] == ["LECTURA_CALIFICADOR"]
    assert presencia.resumenes_ponderacion == []


def test_en_real_el_calificador_de_tiza_corta_sin_preguntar(tmp_path):
    aula = aula_con_e1()
    aula.idnumbers[CURSO] = {"cg2": "TZ_TIZA"}
    presencia = PresenciaFalsa()
    resultado = ponderar(aula, CFG_REAL, tmp_path, presencia, "real")
    assert resultado["errores"] == ["PONDERACION_CON_CALIFICADOR_DE_TIZA"]
    assert presencia.resumenes_ponderacion == []


def test_en_real_un_plan_que_corta_no_pregunta(tmp_path, monkeypatch):
    aula = aula_con_e1()
    original = publicacion.preparar_ponderacion

    def cortando(*args, **kwargs):
        plan_curso = original(*args, **kwargs)
        return dataclasses.replace(
            plan_curso, plan=dataclasses.replace(plan_curso.plan, operaciones=(), corta=True)
        )

    monkeypatch.setattr(publicacion, "preparar_ponderacion", cortando)
    presencia = PresenciaFalsa()
    resultado = ponderar(aula, CFG_REAL, tmp_path, presencia, "real")
    assert resultado["errores"] == ["CATEGORIA_BLOQUEADA"]
    assert presencia.resumenes_ponderacion == []
    assert aula.escrituras == []


def test_la_peticion_retirada_tras_el_si_no_escribe(tmp_path):
    aula = aula_con_e1()
    presencia = PresenciaFalsa()
    resultado = ponderar(aula, CFG_REAL, tmp_path, presencia, "real", vigente=lambda: False)
    assert resultado["errores"] == ["PETICION_RETIRADA"]
    assert aula.escrituras == []


# --- lo cambiado a mano ---


def test_un_cambio_a_mano_se_pregunta_aparte_y_con_si_se_pisa(tmp_path):
    aula = aula_con_cambio_a_mano(tmp_path)
    presencia = PresenciaFalsa(ponderacion_a_mano=True)
    resultado = ponderar(aula, CFG_REAL, tmp_path, presencia, "real")
    assert resultado["resultado"] == "ok"
    assert len(presencia.resumenes_ponderacion) == 1  # el sí general, antes que el particular
    [pregunta] = presencia.resumenes_ponderacion_a_mano
    assert pregunta.cambio.nombre == "Test 1"
    assert pregunta.cambio.referencia == REF_FICHEROS[0]
    assert (round(pregunta.cambio.antes), round(pregunta.cambio.despues)) == (25, 21)
    assert [e for e in aula.escrituras if e[0] == "fijar_coeficiente"]
    assert aula.arboles_ponderacion[CURSO].nodo("ig11").coeficiente == 16.0
    assert preparar(aula, esquema_e1(), tmp_path).plan.sin_cambios
    assert "CAMBIADO_A_MANO" not in codigos(presencia)


def test_un_cambio_a_mano_con_no_se_conserva_y_avisa(tmp_path):
    aula = aula_con_cambio_a_mano(tmp_path)
    presencia = PresenciaFalsa(ponderacion_a_mano=False)
    resultado = ponderar(aula, CFG_REAL, tmp_path, presencia, "real")
    assert resultado["resultado"] == "ok"
    assert len(presencia.resumenes_ponderacion_a_mano) == 1
    assert aula.arboles_ponderacion[CURSO].nodo("ig11").coeficiente == 20.0
    assert not any(e[0] == "fijar_coeficiente" and e[2] == "ig11" for e in aula.escrituras)
    avisos = [a for a in presencia.avisos if a.codigo == "CAMBIADO_A_MANO"]
    assert [a.datos["nombre"] for a in avisos] == ["Test 1"]


def test_con_solo_cambios_a_mano_no_hay_si_general_y_el_no_no_escribe(tmp_path):
    aula = aula_con_cambio_a_mano(tmp_path)
    aula._cambiar("ig12", coeficiente=3.0, peso=3.0)
    plan = preparar(aula, esquema_e1(), tmp_path).plan
    assert plan.sin_cambios and len(plan.cambios_a_mano) == 2
    presencia = PresenciaFalsa(ponderacion_a_mano=False)
    resultado = ponderar(aula, CFG_REAL, tmp_path, presencia, "real")
    assert resultado["resultado"] == "ok"
    assert presencia.resumenes_ponderacion == []
    assert len(presencia.resumenes_ponderacion_a_mano) == len(plan.cambios_a_mano)
    assert aula.escrituras == []


def test_la_vigencia_se_comprueba_tras_el_no_a_sobrescribir(tmp_path):
    aula = aula_con_cambio_a_mano(tmp_path)
    presencia = PresenciaFalsa(ponderacion_a_mano=False)
    resultado = ponderar(aula, CFG_REAL, tmp_path, presencia, "real", vigente=lambda: False)
    assert resultado["errores"] == ["PETICION_RETIRADA"]
    assert len(presencia.resumenes_ponderacion_a_mano) == 1
    assert aula.escrituras == []


# --- la exclusión inversa ---


def test_el_modo_por_elementos_se_niega_en_un_curso_con_categorias_de_ponderacion(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    esquema, documentos = cargar_calificacion(carpeta / "calificacion.yaml", carpeta)
    aula = MoodleFalso()
    aula.calificadores[CURSO] = CalificadorAula(
        nodos=(
            nodo("cg1", "", "curso", None, nombre="Curso"),
            nodo("cg2", "TZP_EXAMEN_1EV", "categoria", "cg1", nombre="Examen"),
        ),
        decimal=".",
    )
    with pytest.raises(ErrorPublicacion) as error:
        publicacion.preparar_calificador(aula, CURSO, esquema, documentos, carpeta / ".tiza")
    assert error.value.codigo == "CALIFICADOR_CON_PONDERACION"


def test_el_modo_por_elementos_sigue_con_categorias_ajenas(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    esquema, documentos = cargar_calificacion(carpeta / "calificacion.yaml", carpeta)
    aula = MoodleFalso()
    aula.calificadores[CURSO] = CalificadorAula(
        nodos=(
            nodo("cg1", "", "curso", None, nombre="Curso"),
            nodo("cg2", "MIA", "categoria", "cg1", nombre="Mía"),
        ),
        decimal=".",
    )
    plan = publicacion.preparar_calificador(aula, CURSO, esquema, documentos, carpeta / ".tiza")
    assert plan.curso == CURSO
