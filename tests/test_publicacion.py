"""Tests de la publicación como proceso (tiza.publicacion).

Las reglas que comparten la terminal directa y la sesión (puertas, resúmenes,
confirmaciones y registro por curso) se prueban a través de
``SesionAbierta.atender`` en test_sesion_abierta.py; aquí van las decisiones
explícitas de cada llamador: el registro de verificados, la vigencia de la
petición, el cupo, el aviso de pruebas, los cursos ya descartados y los cambios
de fechas de la confirmación.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from dobles import (
    MoodleFalso,
    PresenciaFalsa,
    aula_con_tarea,
    copia_sintetica,
    enlace_simbolico,
    estructura_de,
    fecha_en_formulario,
    tarea_en,
)
from tiza import (
    calendario,
    config,
    contenido,
    estado,
    informe,
    mensajes,
    publicacion,
    publicar,
    tipos,
)
from tiza.copia import abrir_copia
from tiza.publicar import ErrorPublicacion

PAGINA = "---\ntipo: pagina\nnombre: Repaso\nseccion: 3\n---\n\n## Repaso\n\nContenido.\n"

CFG = config.Config(
    url="https://aula.ejemplo.org/centro",
    usuario="profe",
    cursos={"pruebas": 1234},
    reales=(5678,),
)


def _carpeta(tmp_path) -> Path:
    (tmp_path / "pagina.md").write_text(PAGINA, encoding="utf-8")
    return tmp_path.resolve()


def _documentos(carpeta: Path) -> list:
    return [contenido.cargar(carpeta / "pagina.md")]


def _verificados(carpeta: Path) -> dict:
    doc = contenido.cargar(carpeta / "pagina.md")
    registro: dict = {}
    estado.anotar_verificado(registro, contenido.hash_documento(doc), "pagina.md", 100)
    return registro


def test_puerta_real_con_registro_en_memoria_ignora_el_disco(tmp_path):
    carpeta = _carpeta(tmp_path)
    doc = _documentos(carpeta)[0]
    estado.guardar_verificado(tmp_path / ".tiza", contenido.hash_documento(doc), "pagina.md", 7)
    # Sin registro en memoria (la terminal directa) se fía de verificados.json.
    assert publicacion.puerta_real(carpeta, [doc]) == []
    # Con el registro vacío en memoria (la sesión), el disco no cuenta.
    assert publicacion.puerta_real(carpeta, [doc], {}) == ["pagina.md"]


def test_el_cupo_de_pruebas_se_agota_y_sin_cupo_no_hay_tope(tmp_path):
    carpeta = _carpeta(tmp_path)
    documentos = _documentos(carpeta)
    cupo = {"pruebas": publicacion.MAX_PUBLICACIONES_PRUEBAS}
    documento = publicacion.publicar_en_cursos(
        MoodleFalso(), CFG, documentos, carpeta, PresenciaFalsa(), entorno="pruebas", cupo=cupo
    )
    assert documento["errores"] == ["LIMITE_PUBLICACIONES"]
    # Sin cupo (la terminal del docente) la misma petición se publica.
    documento = publicacion.publicar_en_cursos(
        MoodleFalso(), CFG, documentos, carpeta, PresenciaFalsa(), entorno="pruebas"
    )
    assert documento["resultado"] == "ok"


def test_las_pruebas_sin_curso_configurado_fallan(tmp_path):
    carpeta = _carpeta(tmp_path)
    cfg = config.Config(
        url="https://aula.ejemplo.org/centro", usuario="profe", cursos={}, reales=(5678,)
    )
    documento = publicacion.publicar_en_cursos(
        MoodleFalso(), cfg, _documentos(carpeta), carpeta, PresenciaFalsa(), entorno="pruebas"
    )
    assert documento["errores"] == ["SIN_CURSO_PRUEBAS"]


@pytest.mark.parametrize("avisar", [True, False])
def test_el_aviso_de_pruebas_solo_lo_pide_la_sesion(tmp_path, avisar):
    carpeta = _carpeta(tmp_path)
    presencia = PresenciaFalsa()
    documento = publicacion.publicar_en_cursos(
        MoodleFalso(),
        CFG,
        _documentos(carpeta),
        carpeta,
        presencia,
        entorno="pruebas",
        avisar_en_pruebas=avisar,
    )
    assert documento["resultado"] == "ok"
    assert ("PUBLICANDO_EN_PRUEBAS" in presencia.codigos()) is avisar


def test_sin_vigente_no_hay_peticion_que_retirar(tmp_path):
    """La terminal directa no tiene buzón: sin ``vigente`` nada se retira."""
    carpeta = _carpeta(tmp_path)
    documento = publicacion.publicar_en_cursos(
        MoodleFalso(),
        CFG,
        _documentos(carpeta),
        carpeta,
        PresenciaFalsa(real=True),
        entorno="real",
        verificados=_verificados(carpeta),
    )
    assert documento["resultado"] == "ok"


def test_con_vigente_falsa_se_retira_tras_confirmar(tmp_path):
    carpeta = _carpeta(tmp_path)
    presencia = PresenciaFalsa(real=True)
    moodle = MoodleFalso()
    documento = publicacion.publicar_en_cursos(
        moodle,
        CFG,
        _documentos(carpeta),
        carpeta,
        presencia,
        entorno="real",
        verificados=_verificados(carpeta),
        vigente=lambda: False,
    )
    assert documento["errores"] == ["PETICION_RETIRADA"]
    assert "PETICION_RETIRADA" in presencia.codigos()
    assert not any(llamada[0] == "crear" for llamada in moodle.llamadas)


def test_los_omitidos_no_se_confirman_y_salen_en_el_informe(tmp_path):
    """Los cursos que la terminal descartó antes de la contraseña no se vuelven a preguntar."""
    carpeta = _carpeta(tmp_path)
    cfg = config.Config(
        url="https://aula.ejemplo.org/centro",
        usuario="profe",
        cursos={"pruebas": 1234},
        reales=(101, 102),
    )
    presencia = PresenciaFalsa(real=True)
    documento = publicacion.publicar_en_cursos(
        MoodleFalso(),
        cfg,
        _documentos(carpeta),
        carpeta,
        presencia,
        entorno="real",
        verificados=_verificados(carpeta),
        omitidos={101},
    )
    assert [resumen.curso for resumen in presencia.resumenes] == [102]
    assert {"codigo": "CURSO_OMITIDO", "resultado": "ok", "detalle": "101"} in documento["pasos"]
    assert documento["resultado"] == "ok"


class TestCambiosDeFechas:
    def test_marca_cada_fecha_como_igual_o_cambia(self, tmp_path):
        tarea_en(tmp_path)
        doc = contenido.cargar(tmp_path / "tarea.md")
        moodle = aula_con_tarea()
        cambios = {
            c.campo: c
            for c in publicacion.cambios_de_fechas(
                moodle, estructura_de(moodle.secciones), doc, None
            )
        }
        assert cambios["apertura"].estado == "igual"
        assert cambios["entrega"].estado == "cambia"
        assert cambios["entrega"].antes == (2026, 10, 10, 23, 59)
        assert cambios["entrega"].despues == (2026, 10, 12, 23, 59)
        assert "límite" not in cambios  # ni en el fichero ni en el aula
        assert publicacion.CAMPO_RECORDATORIO not in cambios  # el aula no lo tiene puesto

    def test_ensena_que_se_quita_el_recordatorio_de_calificacion(self, tmp_path):
        # Toda publicación de una tarea desactiva «Recordarme calificar antes de»: si el
        # docente lo tenía puesto, la confirmación tiene que decírselo.
        tarea_en(tmp_path)
        doc = contenido.cargar(tmp_path / "tarea.md")
        moodle = aula_con_tarea()
        moodle.formularios[55].update(fecha_en_formulario("gradingduedate", (2026, 10, 20, 0, 0)))
        cambios = {
            c.campo: c
            for c in publicacion.cambios_de_fechas(
                moodle, estructura_de(moodle.secciones), doc, None
            )
        }
        recordatorio = cambios[publicacion.CAMPO_RECORDATORIO]
        assert recordatorio.estado == "cambia"
        assert recordatorio.antes == (2026, 10, 20, 0, 0)
        assert recordatorio.despues is None
        assert recordatorio.avisos == ()

    def test_una_actividad_nueva_no_tiene_antes(self, tmp_path):
        tarea_en(tmp_path)
        doc = contenido.cargar(tmp_path / "tarea.md")
        moodle = MoodleFalso()
        cambios = publicacion.cambios_de_fechas(moodle, estructura_de(moodle.secciones), doc, None)
        assert {c.estado for c in cambios} == {"nueva"}
        assert all(c.antes is None for c in cambios)

    def test_si_el_aula_no_se_puede_leer_se_dice_sin_abortar(self, tmp_path):
        tarea_en(tmp_path)
        doc = contenido.cargar(tmp_path / "tarea.md")

        class AulaCaida(MoodleFalso):
            def leer_modulo(self, cmid):
                raise publicar.ErrorPublicacion("ERROR_CONSULTA")

        moodle = AulaCaida()
        moodle.secciones[0]["modulos"] = [{"cmid": 55, "nombre": "Problemas", "tipo": "tarea"}]
        cambios = publicacion.cambios_de_fechas(moodle, estructura_de(moodle.secciones), doc, None)
        assert {c.estado for c in cambios} == {"desconocida"}
        assert cambios[1].despues == (2026, 10, 12, 23, 59)

    def test_los_avisos_del_calendario_van_con_su_fecha(self, tmp_path):
        tarea_en(tmp_path)  # entrega lunes 12 de octubre de 2026
        doc = contenido.cargar(tmp_path / "tarea.md")
        festivo = calendario.Calendario(festivos=((date(2026, 10, 12), date(2026, 10, 12)),))
        cambios = {
            c.campo: c for c in publicacion.cambios_de_fechas(MoodleFalso(), [], doc, festivo)
        }
        assert cambios["entrega"].avisos == ("FECHA_FESTIVA",)
        assert cambios["apertura"].avisos == ()


CON_FORMULA = (
    "---\ntipo: pagina\nnombre: Repaso\nseccion: 3\n---\n\nLa media es \\(\\frac{a}{b}\\).\n"
)


def _publicar_pruebas(tmp_path, texto, moodle):
    (tmp_path / "pagina.md").write_text(texto, encoding="utf-8")
    carpeta = tmp_path.resolve()
    return publicacion.publicar_en_cursos(
        moodle, CFG, _documentos(carpeta), carpeta, PresenciaFalsa(), entorno="pruebas"
    )


def _avisos_formulas(documento) -> list:
    return [p for p in documento["pasos"] if p["codigo"] == "FORMULAS_NO_DIBUJADAS"]


def test_avisa_si_el_aula_no_dibuja_formulas(tmp_path):
    moodle = MoodleFalso(motor_formulas=False)
    documento = _publicar_pruebas(tmp_path, CON_FORMULA, moodle)
    assert documento["errores"] == []
    assert _avisos_formulas(documento) == [
        {"codigo": "FORMULAS_NO_DIBUJADAS", "resultado": "ok", "detalle": "pagina.md"}
    ]


def test_no_avisa_si_el_aula_dibuja_formulas(tmp_path):
    documento = _publicar_pruebas(tmp_path, CON_FORMULA, MoodleFalso(motor_formulas=True))
    assert _avisos_formulas(documento) == []


def test_sin_formulas_ni_se_consulta_el_aula(tmp_path):
    moodle = MoodleFalso(motor_formulas=False)
    documento = _publicar_pruebas(tmp_path, PAGINA, moodle)
    assert _avisos_formulas(documento) == []
    assert not any(llamada[0] == "motor_de_formulas" for llamada in moodle.llamadas)


def test_se_consulta_una_sola_vez_por_curso(tmp_path):
    moodle = MoodleFalso(motor_formulas=False)
    _publicar_pruebas(tmp_path, CON_FORMULA, moodle)
    assert [llamada for llamada in moodle.llamadas if llamada[0] == "motor_de_formulas"] == [
        ("motor_de_formulas", 1234)
    ]


# --- tiza copia: la sesión hace la copia del curso ---------------------------------------


class _Reloj(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 19, 10, 30)


def _cupo() -> dict:
    return {"pruebas": 0, "copias": 0}


def _copiar(tmp_path, moodle=None, presencia=None, curso="pruebas", cupo=None, cfg=CFG, **opciones):
    moodle = moodle or MoodleFalso()
    presencia = presencia or PresenciaFalsa()
    documento = publicacion.copiar_curso(
        moodle,
        cfg,
        curso,
        tmp_path.resolve(),
        presencia,
        cupo if cupo is not None else _cupo(),
        **opciones,
    )
    informe.validar(documento)  # lo que sale hacia el agente cumple el esquema cerrado
    return moodle, presencia, documento


def _copias_guardadas(tmp_path) -> list[str]:
    carpeta = tmp_path / ".tiza" / "copias"
    return sorted(ruta.name for ruta in carpeta.iterdir()) if carpeta.exists() else []


def test_copia_pide_confirmacion(tmp_path):
    cupo = _cupo()
    moodle, presencia, documento = _copiar(
        tmp_path,
        presencia=PresenciaFalsa(copia=False),
        cupo=cupo,
        nombres={1234: "Pruebas de Mates"},
    )
    assert (documento["resultado"], documento["errores"]) == ("abortado", ["COPIA_RECHAZADA"])
    assert not any(llamada[0] == "hacer_copia" for llamada in moodle.llamadas)
    assert "copia" not in documento
    assert (presencia.resumenes_copia[0].curso, presencia.resumenes_copia[0].nombre_curso) == (
        1234,
        "Pruebas de Mates",
    )
    assert cupo["copias"] == 0  # negarse no gasta cupo
    assert _copias_guardadas(tmp_path) == []  # y no deja nada


def test_copia_con_usuarios_se_borra(tmp_path):
    moodle = MoodleFalso(copia=copia_sintetica(users=1))
    _moodle, _presencia, documento = _copiar(tmp_path, moodle)
    assert documento["errores"] == ["COPIA_CON_USUARIOS"]
    assert "copia" not in documento
    assert _copias_guardadas(tmp_path) == []  # ni la copia ni el temporal
    # Tampoco se queda, con sus datos, en la zona de copias del docente.
    assert moodle.copias_en_el_aula == []


def test_copia_queda_en_tiza_copias(tmp_path, monkeypatch):
    monkeypatch.setattr(publicacion, "datetime", _Reloj)
    moodle, presencia, documento = _copiar(tmp_path)
    assert documento["resultado"] == "ok" and documento["errores"] == []
    assert (documento["comando"], documento["entorno"], documento["curso"]) == (
        "copia",
        "pruebas",
        1234,
    )
    assert _copias_guardadas(tmp_path) == ["pruebas-20261019-1030.mbz"]
    ruta = tmp_path / ".tiza" / "copias" / "pruebas-20261019-1030.mbz"
    assert documento["copia"] == [
        {
            "curso": "pruebas",
            "fichero": ".tiza/copias/pruebas-20261019-1030.mbz",
            "bytes": ruta.stat().st_size,
            "actividades": {"assign": 1, "forum": 1, "label": 1, "page": 1},
            "borrada_del_aula": True,
            "cmid": None,
        }
    ]
    assert len(abrir_copia(ruta).actividades) == 4  # es la copia, entera y legible
    assert [p["codigo"] for p in documento["pasos"]] == ["LOGIN", "COPIAR", "BORRAR_COPIA"]
    assert moodle.borradas == [(moodle.copias_hechas[0][1], 1234)]
    assert [r.entorno for r in presencia.resumenes_copia] == ["pruebas"]


def test_copia_cupo(tmp_path):
    cupo = _cupo()
    moodle, presencia = MoodleFalso(), PresenciaFalsa()
    documentos = [_copiar(tmp_path, moodle, presencia, cupo=cupo)[2] for _ in range(4)]
    assert [d["resultado"] for d in documentos] == ["ok", "ok", "ok", "error"]
    assert documentos[3]["errores"] == ["CUPO_COPIAS"]
    assert cupo["copias"] == publicacion.CUPO_COPIAS == 3
    assert len(presencia.resumenes_copia) == 3  # a la cuarta ni se le pregunta al docente
    assert (
        len(_copias_guardadas(tmp_path)) == 3
    )  # tres copias en el mismo minuto: nombres distintos


def test_copia_se_borra_del_aula(tmp_path):
    moodle = MoodleFalso()
    _moodle, presencia, documento = _copiar(tmp_path, moodle)
    assert moodle.borradas == [(moodle.copias_hechas[0][1], 1234)]
    assert documento["copia"][0]["borrada_del_aula"] is True
    assert "COPIA_QUEDA_EN_EL_AULA" not in presencia.codigos()
    # Si no se puede borrar, la copia sigue siendo buena: se avisa y se dice en el informe.
    moodle = MoodleFalso()
    moodle.borrar_copia_falla = True
    _moodle, presencia, documento = _copiar(tmp_path, moodle)
    assert documento["resultado"] == "ok" and documento["errores"] == []
    assert documento["copia"][0]["borrada_del_aula"] is False
    assert "COPIA_QUEDA_EN_EL_AULA" in presencia.codigos()
    assert [p["resultado"] for p in documento["pasos"] if p["codigo"] == "BORRAR_COPIA"] == [
        "fallo"
    ]


def test_copia_curso_desconocido(tmp_path):
    moodle = MoodleFalso()
    for nombre in ("otro", "9999", "pruebas-1", "1234; rm"):
        _m, presencia, documento = _copiar(tmp_path, moodle, curso=nombre)
        assert documento["errores"] == ["CURSO_NO_CONFIGURADO"], nombre
        assert presencia.resumenes_copia == []
    assert not any(llamada[0] == "hacer_copia" for llamada in moodle.llamadas)


def test_copia_del_curso_real_por_nombre_o_por_id(tmp_path):
    for nombre in ("real", "5678"):
        _m, presencia, documento = _copiar(tmp_path, curso=nombre)
        assert (documento["entorno"], documento["curso"]) == ("real", 5678), nombre
        assert documento["copia"][0]["curso"] == nombre
        assert presencia.resumenes_copia[0].entorno == "real"


def test_copia_con_varios_reales_pide_el_id(tmp_path):
    cfg = config.Config(CFG.url, CFG.usuario, {"pruebas": 1234}, reales=(5678, 91))
    _m, _p, documento = _copiar(tmp_path, curso="real", cfg=cfg)
    assert documento["errores"] == ["CURSO_AMBIGUO"]
    _m, _p, documento = _copiar(tmp_path, curso="91", cfg=cfg)
    assert (documento["entorno"], documento["curso"]) == ("real", 91)


def test_copia_sin_curso_de_pruebas(tmp_path):
    cfg = config.Config(CFG.url, CFG.usuario, {}, sin_pruebas=True, reales=(5678,))
    _m, _p, documento = _copiar(tmp_path, curso="pruebas", cfg=cfg)
    assert documento["errores"] == ["SIN_CURSO_PRUEBAS"]


@pytest.mark.parametrize("codigo", ["COPIA_NO_PERMITIDA", "COPIA_FALLIDA", "SESION_CADUCADA"])
def test_copia_que_falla_en_el_aula_da_su_codigo_y_no_deja_nada(tmp_path, codigo):
    moodle = MoodleFalso()
    moodle.copia_falla = codigo
    _m, _p, documento = _copiar(tmp_path, moodle)
    assert (documento["resultado"], documento["errores"]) == ("error", [codigo])
    assert "copia" not in documento
    assert _copias_guardadas(tmp_path) == []


def test_copia_demasiado_grande_se_corta_con_el_maximo_de_abrir_copia(tmp_path, monkeypatch):
    from tiza import copia

    monkeypatch.setattr(copia, "MAX_COPIA", 100)
    _m, _p, documento = _copiar(tmp_path)
    assert documento["errores"] == ["COPIA_DEMASIADO_GRANDE"]
    assert _copias_guardadas(tmp_path) == []


def test_copia_que_no_es_una_copia_se_borra_y_da_su_codigo(tmp_path):
    moodle = MoodleFalso(copia=b"esto no es un .mbz")
    _m, _p, documento = _copiar(tmp_path, moodle)
    assert documento["errores"] == ["COPIA_NO_VALIDA"]
    assert _copias_guardadas(tmp_path) == []
    assert moodle.copias_en_el_aula == []


def test_copia_nunca_sobrescribe_un_fichero_que_ya_esta(tmp_path, monkeypatch):
    monkeypatch.setattr(publicacion, "datetime", _Reloj)
    carpeta = tmp_path / ".tiza" / "copias"
    carpeta.mkdir(parents=True)
    (carpeta / "pruebas-20261019-1030.mbz").write_bytes(b"del docente")
    _m, _p, documento = _copiar(tmp_path)
    assert documento["copia"][0]["fichero"] == ".tiza/copias/pruebas-20261019-1030-2.mbz"
    assert (carpeta / "pruebas-20261019-1030.mbz").read_bytes() == b"del docente"


def test_copia_con_tiza_enlazada_no_escribe_fuera(tmp_path):
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    enlace_simbolico(carpeta / ".tiza", fuera)
    moodle = MoodleFalso()
    _m, _p, documento = _copiar(carpeta, moodle)
    assert documento["errores"] == ["COPIA_NO_ESCRIBIBLE"]
    assert list(fuera.iterdir()) == []
    assert not any(llamada[0] == "hacer_copia" for llamada in moodle.llamadas)


def test_copia_si_el_agente_ya_no_espera_no_se_hace(tmp_path):
    cupo = _cupo()
    moodle, presencia, documento = _copiar(tmp_path, cupo=cupo, vigente=lambda: False)
    assert documento["errores"] == ["PETICION_RETIRADA"]
    assert "PETICION_RETIRADA" in presencia.codigos()
    assert not any(llamada[0] == "hacer_copia" for llamada in moodle.llamadas)
    assert cupo["copias"] == 0


def test_copia_no_deja_ningun_texto_de_moodle_en_el_informe(tmp_path):
    moodle = MoodleFalso(cursos=[{"id": 1234, "nombre": "Curso <b>secreto</b>"}])
    _m, _p, documento = _copiar(tmp_path, moodle, nombres={1234: "Curso <b>secreto</b>"})
    assert "secreto" not in str(documento)


def test_si_el_error_deja_la_copia_en_el_aula_el_informe_y_el_docente_lo_saben(tmp_path):
    moodle = MoodleFalso()
    moodle.copia_falla = "COPIA_FALLIDA"
    moodle.copia_falla_queda = True
    _m, presencia, documento = _copiar(tmp_path, moodle)
    assert documento["errores"] == ["COPIA_FALLIDA"]
    assert "COPIA_QUEDA_EN_EL_AULA" in presencia.codigos()
    pasos = {p["codigo"]: p for p in documento["pasos"]}
    assert (pasos["BORRAR_COPIA"]["resultado"], pasos["BORRAR_COPIA"]["detalle"]) == (
        "fallo",
        "COPIA_QUEDA_EN_EL_AULA",
    )
    # Si no queda, ni aviso ni paso.
    moodle = MoodleFalso()
    moodle.copia_falla = "COPIA_FALLIDA"
    _m, presencia, documento = _copiar(tmp_path, moodle)
    assert "COPIA_QUEDA_EN_EL_AULA" not in presencia.codigos()
    assert "BORRAR_COPIA" not in [p["codigo"] for p in documento["pasos"]]


def test_copia_con_usuarios_y_sin_poder_borrarla_del_aula_tambien_lo_dice(tmp_path):
    moodle = MoodleFalso(copia=copia_sintetica(users=1))
    moodle.borrar_copia_falla = True
    _m, presencia, documento = _copiar(tmp_path, moodle)
    assert documento["errores"] == ["COPIA_CON_USUARIOS"]
    assert presencia.codigos().count("COPIA_QUEDA_EN_EL_AULA") == 1
    assert ("BORRAR_COPIA", "fallo") in [(p["codigo"], p["resultado"]) for p in documento["pasos"]]
    assert _copias_guardadas(tmp_path) == []


def test_una_copia_fallida_gasta_cupo_pero_negarse_o_retirarla_no(tmp_path):
    # Fijado: el cupo se gasta al confirmar el docente, haya salido bien o no (frena un bucle).
    cupo = _cupo()
    moodle = MoodleFalso()
    moodle.copia_falla = "COPIA_FALLIDA"
    for gastadas in (1, 2, 3):
        _m, _p, documento = _copiar(tmp_path, moodle, cupo=cupo)
        assert documento["errores"] == ["COPIA_FALLIDA"]
        assert cupo["copias"] == gastadas
    _m, presencia, documento = _copiar(tmp_path, moodle, cupo=cupo)
    assert documento["errores"] == ["CUPO_COPIAS"] and len(presencia.resumenes_copia) == 0
    # Negarse no gasta (ya cubierto en test_copia_pide_confirmacion); retirarla, tampoco.
    cupo = _cupo()
    _copiar(tmp_path, cupo=cupo, presencia=PresenciaFalsa(copia=False))
    _copiar(tmp_path, cupo=cupo, vigente=lambda: False)
    assert cupo["copias"] == 0
    # Una copia que no vale (con usuarios) sí gasta.
    _copiar(tmp_path, MoodleFalso(copia=copia_sintetica(users=1)), cupo=cupo)
    assert cupo["copias"] == 1


# --- Publicar por origen: cmid, huella del aula y lotes ----------------------------------

TEXTO_DEL_AULA = "<p>SECRETO-DEL-AULA</p>"


def _aula_importada(modulo="pagina", texto=TEXTO_DEL_AULA) -> MoodleFalso:
    """El curso real 5678 con la actividad 501 «Viejo» en la sección 2, como la dejó la copia."""
    moodle = MoodleFalso(
        # El curso de pruebas (1234): sin la actividad 501, con las mismas secciones.
        secciones=[
            {"numero": 2, "nombre": "Tema 2", "id": 21, "modulos": []},
            {"numero": 3, "nombre": "Tema 3", "id": 31, "modulos": []},
        ],
        secciones_por_curso={
            5678: [
                {
                    "numero": 2,
                    "nombre": "Tema 2",
                    "id": 20,
                    "modulos": [{"cmid": 501, "nombre": "Viejo", "tipo": modulo}],
                },
                {"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []},
            ]
        },
    )
    moodle.formularios[501] = {"visible": "1", "name": "Viejo", "page[text]": texto}
    return moodle


def _fichero_importado(
    carpeta: Path, nombre="importada.md", titulo="Nuevo", cmid=501, seccion="2", extra=""
) -> None:
    (carpeta / nombre).write_text(
        f"---\ntipo: pagina\nnombre: {titulo}\nseccion: {seccion}\n"
        f"origen:\n  curso: 5678\n  cmid: {cmid}\n{extra}---\n\nTexto nuevo.\n",
        encoding="utf-8",
    )


def _fichero_normal(carpeta: Path, nombre="otra.md") -> None:
    (carpeta / nombre).write_text(
        "---\ntipo: pagina\nnombre: Otra\nseccion: 3\n---\n\nOtra página.\n", encoding="utf-8"
    )


def _escribir_copia(
    carpeta: Path, huella: str | None, curso=5678, cmid=501, huella_fichero: str | None = None
) -> None:
    """``copia.json`` con una actividad del curso ``curso``, importada con esa huella.

    ``huella_fichero``: el sha256 que se guardó del fichero al marcarla cambiada en el aula.
    """
    entrada = {
        "moodle": "https://aula.ejemplo.org/centro",
        "fecha_importacion": "2026-10-19T10:00:00+00:00",
        "secciones": [{"numero": 2, "nombre": "Tema 2", "resumen_html_presente": False}],
        "actividades": [
            {
                "cmid": cmid,
                "modulo": "page",
                "seccion": 2,
                "nombre": "Viejo",
                "fichero": "importada.md",
                "estado": "IMPORTADA",
                "detalle": None,
                "huella_aula": huella,
                "huella_fichero": huella_fichero,
            }
        ],
    }
    estado.escribir_copia(
        carpeta / ".tiza", {"version": 1, "cursos": {str(curso): entrada}, "como_nuevas": None}
    )


def _huella_del_aula(texto=TEXTO_DEL_AULA) -> str:
    return tipos.huella_aula("Viejo", texto)


def _publicar_real(carpeta: Path, moodle, ficheros, presencia=None) -> dict:
    documentos = [contenido.cargar(carpeta / f) for f in ficheros]
    registro: dict = {}
    for doc in documentos:
        estado.anotar_verificado(registro, contenido.hash_documento(doc), doc.ruta.name, 100)
    return publicacion.publicar_en_cursos(
        moodle,
        CFG,
        documentos,
        carpeta,
        presencia or PresenciaFalsa(),
        entorno="real",
        verificados=registro,
    )


def test_publicar_por_origen_actualiza_la_actividad_y_renueva_la_huella(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, _huella_del_aula())
    moodle = _aula_importada()
    documento = _publicar_real(carpeta, moodle, ["importada.md"])
    assert documento["errores"] == []
    assert [(f["nombre"], f["cmid"], f["accion"]) for f in documento["ficheros"]] == [
        ("importada.md", 501, "renombrada")  # «Viejo» pasa a «Nuevo»
    ]
    assert [c[1] for c in moodle.llamadas if c[0] == "actualizar"] == [501]
    assert not any(c[0] == "crear" for c in moodle.llamadas)
    doc = contenido.cargar(carpeta / "importada.md")
    esperada = tipos.huella_de_lo_enviado(
        tipos.obtener("pagina"), doc, contenido.html_para_moodle(doc)
    )
    guardada = estado.huellas_de_copia(carpeta / ".tiza", 5678)
    assert guardada == {501: esperada}
    # Lo que quedó en el aula da esa misma huella: la siguiente publicación no salta.
    assert tipos.huella_del_formulario(tipos.obtener("pagina"), doc, moodle.leer_modulo(501)) == (
        esperada
    )
    segunda = _publicar_real(carpeta, moodle, ["importada.md"])
    assert segunda["errores"] == [] and segunda["resultado"] == "ok"


def test_la_huella_se_renueva_solo_en_la_entrada_de_su_curso(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, _huella_del_aula())
    datos = estado.cargar_copia(carpeta / ".tiza")
    otra = {
        **datos["cursos"]["5678"],
        "actividades": [dict(datos["cursos"]["5678"]["actividades"][0])],
    }
    otra["actividades"][0]["huella_aula"] = "b" * 64
    datos["cursos"]["9999"] = otra
    estado.escribir_copia(carpeta / ".tiza", datos)
    _publicar_real(carpeta, _aula_importada(), ["importada.md"])
    ahora = estado.cargar_copia(carpeta / ".tiza")
    assert ahora["cursos"]["9999"]["actividades"][0]["huella_aula"] == "b" * 64
    assert ahora["cursos"]["5678"]["actividades"][0]["huella_aula"] != _huella_del_aula()


def test_cambiada_en_el_aula_no_publica_y_las_demas_siguen(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _fichero_normal(carpeta)
    _escribir_copia(carpeta, tipos.huella_aula("Viejo", "<p>Como estaba en la copia</p>"))
    moodle = _aula_importada()
    presencia = PresenciaFalsa()
    documento = _publicar_real(carpeta, moodle, ["importada.md", "otra.md"], presencia)
    assert documento["resultado"] == "error"
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert [f["nombre"] for f in documento["ficheros"]] == ["otra.md"]
    assert not any(c[0] in ("mover", "subir") for c in moodle.llamadas)
    assert 501 not in [c[1] for c in moodle.llamadas if c[0] == "actualizar"]
    assert moodle.formularios[501]["name"] == "Viejo"
    assert "CAMBIADA_EN_EL_AULA" in presencia.codigos()
    # La huella de la copia no se renueva: no se publicó.
    assert estado.huellas_de_copia(carpeta / ".tiza", 5678)[501] != _huella_del_aula()


def test_cambiada_no_saca_texto_del_aula(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, tipos.huella_aula("Viejo", "<p>Como estaba en la copia</p>"))
    presencia = PresenciaFalsa()
    documento = _publicar_real(carpeta, _aula_importada(), ["importada.md"], presencia)
    informe.validar(documento)
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert "SECRETO-DEL-AULA" not in json.dumps(documento, ensure_ascii=False)
    assert "SECRETO-DEL-AULA" not in repr(presencia.avisos)
    assert "SECRETO-DEL-AULA" not in "\n".join(informe.resumen(documento))


def test_el_origen_no_encontrado_solo_para_su_fichero(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta, cmid=999)
    _fichero_normal(carpeta)
    moodle = _aula_importada()
    documento = _publicar_real(carpeta, moodle, ["importada.md", "otra.md"])
    assert documento["errores"] == ["ORIGEN_NO_ENCONTRADO"]
    assert [f["nombre"] for f in documento["ficheros"]] == ["otra.md"]
    assert [c[0] for c in moodle.llamadas if c[0] == "crear"] == ["crear"]  # solo «Otra»


def test_dos_ficheros_con_el_mismo_origen_no_se_publican(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta, "uno.md", "Uno")
    _fichero_importado(carpeta, "dos.md", "Dos")
    _fichero_normal(carpeta)
    _escribir_copia(carpeta, _huella_del_aula())
    moodle = _aula_importada()
    documento = _publicar_real(carpeta, moodle, ["uno.md", "dos.md", "otra.md"])
    assert documento["errores"] == ["ORIGEN_DUPLICADO", "ORIGEN_DUPLICADO"]
    fallos = [p["detalle"] for p in documento["pasos"] if p["resultado"] == "fallo"]
    assert sorted(fallos) == ["dos.md", "uno.md"]
    assert [f["nombre"] for f in documento["ficheros"]] == ["otra.md"]
    assert 501 not in [c[1] for c in moodle.llamadas if c[0] == "actualizar"]
    assert moodle.formularios[501]["name"] == "Viejo"


def test_sin_copia_json_no_se_publica_por_origen_y_las_demas_siguen(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _fichero_normal(carpeta)
    moodle = _aula_importada()
    presencia = PresenciaFalsa()
    documento = _publicar_real(carpeta, moodle, ["importada.md", "otra.md"], presencia)
    informe.validar(documento)
    assert documento["errores"] == ["ORIGEN_SIN_HUELLA"]
    assert documento["resultado"] == "error"
    assert {"codigo": "PUBLICAR", "resultado": "fallo", "detalle": "importada.md"} in (
        documento["pasos"]
    )
    assert "ORIGEN_SIN_HUELLA" not in [p["codigo"] for p in documento["pasos"]]
    assert [f["nombre"] for f in documento["ficheros"]] == ["otra.md"]
    assert 501 not in [c[1] for c in moodle.llamadas if c[0] == "actualizar"]
    assert moodle.formularios[501]["name"] == "Viejo"
    assert not (carpeta / ".tiza" / "copia.json").exists()  # no se inventa una entrada
    # No es lo mismo que un aviso: no sale como aviso, y la confirmación no la incluye.
    assert "ORIGEN_SIN_HUELLA" not in presencia.codigos()
    assert [d.fichero for d in presencia.resumenes[0].documentos] == ["otra.md"]


def test_actividad_sin_huella_no_se_publica(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta, seccion='"Tema nuevo"')
    _escribir_copia(carpeta, None)
    moodle = _aula_importada()
    presencia = PresenciaFalsa()
    documento = _publicar_real(carpeta, moodle, ["importada.md"], presencia)
    assert documento["errores"] == ["ORIGEN_SIN_HUELLA"]
    assert not any(
        c[0] in ("actualizar", "crear", "crear_seccion", "mover") for c in moodle.llamadas
    )
    assert presencia.resumenes == []  # todo rechazado: nada que confirmar
    assert estado.huellas_de_copia(carpeta / ".tiza", 5678) == {}


def test_sin_huella_en_otro_curso_no_cuenta(tmp_path):
    # El origen es del curso 5678 y se publica en pruebas (1234): no hay nada que comparar.
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    documento = publicacion.publicar_en_cursos(
        _aula_importada(),
        CFG,
        [contenido.cargar(carpeta / "importada.md")],
        carpeta,
        PresenciaFalsa(),
        entorno="pruebas",
    )
    assert documento["errores"] == []


def _marca_del_fichero(carpeta: Path, nombre="importada.md") -> str:
    return hashlib.sha256((carpeta / nombre).read_bytes()).hexdigest()


def test_un_fichero_sin_juntar_tras_cambiada_desde_la_importacion_no_se_publica(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _fichero_normal(carpeta)
    # La copia nueva ya trae la huella del aula de ahora; el fichero sigue como se marcó.
    _escribir_copia(carpeta, _huella_del_aula(), huella_fichero=_marca_del_fichero(carpeta))
    moodle = _aula_importada()
    presencia = PresenciaFalsa()
    documento = _publicar_real(carpeta, moodle, ["importada.md", "otra.md"], presencia)
    informe.validar(documento)
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert {
        "codigo": "PUBLICAR",
        "resultado": "fallo",
        "detalle": "importada.md: junta antes los cambios de .tiza/copia/501.html",
    } in documento["pasos"]
    assert [f["nombre"] for f in documento["ficheros"]] == ["otra.md"]
    assert not any(c[0] in ("actualizar", "mover", "subir") for c in moodle.llamadas)
    assert moodle.formularios[501]["name"] == "Viejo"
    [aviso] = [a for a in presencia.avisos if a.codigo == "CAMBIADA_EN_EL_AULA"]
    [linea] = mensajes.lineas_de_aviso(aviso)
    assert "junta antes los cambios de .tiza/copia/501.html" in linea.texto
    assert [d.fichero for d in presencia.resumenes[0].documentos] == ["otra.md"]
    # La marca sigue: nada se renovó.
    assert estado.marcas_de_copia(carpeta / ".tiza", 5678) == {501: _marca_del_fichero(carpeta)}


def test_con_el_fichero_ya_juntado_se_publica_y_se_borra_la_marca(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, _huella_del_aula(), huella_fichero=_marca_del_fichero(carpeta))
    # El docente junta los cambios: el fichero ya no es el que se marcó.
    ruta = carpeta / "importada.md"
    ruta.write_text(
        ruta.read_text(encoding="utf-8") + "\nCon lo que cambió en el aula.\n", encoding="utf-8"
    )
    moodle = _aula_importada()
    documento = _publicar_real(carpeta, moodle, ["importada.md"])
    assert documento["errores"] == []
    assert [c[1] for c in moodle.llamadas if c[0] == "actualizar"] == [501]
    assert estado.marcas_de_copia(carpeta / ".tiza", 5678) == {}
    # Y después se publica con normalidad, sin tocar nada más.
    segunda = _publicar_real(carpeta, moodle, ["importada.md"])
    assert segunda["errores"] == []


def test_una_marca_ilegible_bloquea_hasta_reimportar(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, _huella_del_aula(), huella_fichero=estado.MARCA_ILEGIBLE)
    documento = _publicar_real(carpeta, _aula_importada(), ["importada.md"])
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]


def test_la_marca_de_otra_actividad_no_bloquea(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, _huella_del_aula(), huella_fichero="a" * 64)  # otro contenido
    documento = _publicar_real(carpeta, _aula_importada(), ["importada.md"])
    assert documento["errores"] == []


def test_solo_fechas_tampoco_publica_un_fichero_sin_juntar(tmp_path):
    carpeta = tmp_path.resolve()
    _tarea_importada(carpeta)
    sha = hashlib.sha256((carpeta / "tarea.md").read_bytes()).hexdigest()
    _escribir_copia(carpeta, _huella_de_la_tarea(), cmid=601, huella_fichero=sha)
    moodle = _aula_con_tarea_importada()
    presencia = PresenciaFalsa()
    documento = _solo_fechas(carpeta, moodle, presencia)
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert not any(c[0] == "actualizar" for c in moodle.llamadas)


def test_un_copia_json_invalido_para_la_publicacion_por_origen(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    (carpeta / ".tiza").mkdir()
    (carpeta / ".tiza" / "copia.json").write_text('{"version": 7}', encoding="utf-8")
    moodle = _aula_importada()
    documento = _publicar_real(carpeta, moodle, ["importada.md"])
    assert documento["errores"] == ["COPIA_INVALIDA"]
    assert not any(c[0] in ("actualizar", "crear", "mover") for c in moodle.llamadas)


def test_en_pruebas_el_origen_no_cuenta(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, tipos.huella_aula("Viejo", "<p>Otra cosa</p>"))
    moodle = _aula_importada()
    documento = publicacion.publicar_en_cursos(
        moodle,
        CFG,
        [contenido.cargar(carpeta / "importada.md")],
        carpeta,
        PresenciaFalsa(),
        entorno="pruebas",
    )
    assert documento["errores"] == [] and documento["ficheros"][0]["accion"] == "creada"
    assert documento["ficheros"][0]["cmid"] != 501
    # Y nada se renueva en copia.json: no es el curso del origen.
    assert estado.huellas_de_copia(carpeta / ".tiza", 5678)[501] == tipos.huella_aula(
        "Viejo", "<p>Otra cosa</p>"
    )


def test_el_resumen_de_real_ensena_el_cambio_de_nombre(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, _huella_del_aula())
    presencia = PresenciaFalsa()
    _publicar_real(carpeta, _aula_importada(), ["importada.md"], presencia)
    [resumen] = presencia.resumenes
    assert resumen.nombres == (publicacion.CambioNombre("importada.md", "Viejo", "Nuevo"),)
    assert resumen.movimientos == ()
    detalle = mensajes.detalle_real(resumen)
    assert any("Se cambia el nombre de «Viejo» a «Nuevo»" in linea for linea in detalle.finales)


def test_el_resumen_corto_tambien_ensena_el_cambio_de_nombre(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, _huella_del_aula())
    sin_pruebas = config.Config(
        url="https://aula.ejemplo.org/centro", usuario="profe", cursos={}, reales=(5678,)
    )
    presencia = PresenciaFalsa()
    publicacion.publicar_en_cursos(
        _aula_importada(),
        sin_pruebas,
        [contenido.cargar(carpeta / "importada.md")],
        carpeta,
        presencia,
        entorno="real",
        visible=False,
    )
    [corto] = presencia.resumenes_cortos
    assert corto.documentos[0].existe is True
    assert any(
        "Se cambia el nombre de «Viejo» a «Nuevo»" in linea
        for linea in mensajes.detalle_corto(corto).finales
    )


def test_solo_fechas_busca_por_origen_y_si_no_esta_no_cambia_nada(tmp_path):
    carpeta = tmp_path.resolve()
    (carpeta / "t.md").write_text(
        "---\ntipo: tarea\nnombre: Otro nombre\nseccion: 3\napertura: 2026-10-01\n"
        "entrega: 2026-10-12\norigen:\n  curso: 5678\n  cmid: 601\n---\n\nResuelve.\n",
        encoding="utf-8",
    )
    doc = contenido.cargar(carpeta / "t.md")
    secciones = [
        {
            "numero": 2,
            "nombre": "T2",
            "id": 20,
            "modulos": [{"cmid": 601, "nombre": "Vieja", "tipo": "tarea"}],
        }
    ]
    assert publicacion.codigo_solo_fechas(estructura_de(secciones), [doc], 5678) is None
    assert publicacion.codigo_solo_fechas(estructura_de(secciones), [doc], 1234) == "MODULO_AUSENTE"
    secciones[0]["modulos"][0]["cmid"] = 602
    assert (
        publicacion.codigo_solo_fechas(estructura_de(secciones), [doc], 5678)
        == "ORIGEN_NO_ENCONTRADO"
    )


def test_solo_fechas_busca_por_el_registro_una_actividad_con_otro_nombre(tmp_path):
    carpeta = tmp_path.resolve()
    (carpeta / ".tiza").mkdir()
    tarea_en(carpeta)  # «Problemas», sección 3
    secciones = [
        {
            "numero": 3,
            "nombre": "T3",
            "id": 30,
            "modulos": [{"cmid": 55, "nombre": "Problemas del tema", "tipo": "tarea"}],
        }
    ]
    doc = contenido.cargar(carpeta / "tarea.md", raiz=carpeta)
    assert publicacion.codigo_solo_fechas(estructura_de(secciones), [doc], 5678) == "MODULO_AUSENTE"
    estado.guardar_publicado(
        carpeta / ".tiza", 5678, "tarea.md", estado.Publicado(cmid=55, tipo="tarea")
    )
    doc = contenido.cargar(carpeta / "tarea.md", raiz=carpeta)
    assert publicacion.codigo_solo_fechas(estructura_de(secciones), [doc], 5678) is None
    assert publicacion.codigo_solo_fechas(estructura_de(secciones), [doc], 1234) == "MODULO_AUSENTE"
    # Si el nombre es ambiguo (hay otra «Problemas» en su sección), no se sabe cuál y se dice.
    secciones[0]["modulos"].append({"cmid": 56, "nombre": "Problemas", "tipo": "tarea"})
    assert (
        publicacion.codigo_solo_fechas(estructura_de(secciones), [doc], 5678) == "ACTIVIDAD_AMBIGUA"
    )


# --- Ronda de arreglos 1 ------------------------------------------------------------------


class _AulaQueFallaAlVerificar(MoodleFalso):
    """Escribe en el aula y falla una vez después: el reintento ya la encuentra escrita."""

    fallos_pendientes = 1

    def actualizar(self, cmid, payload):
        super().actualizar(cmid, payload)
        if self.fallos_pendientes:
            self.fallos_pendientes -= 1
            raise ErrorPublicacion("ERROR_ACTUALIZACION")


def _aula_que_falla(texto=TEXTO_DEL_AULA) -> _AulaQueFallaAlVerificar:
    base = _aula_importada(texto=texto)
    moodle = _AulaQueFallaAlVerificar(
        secciones=base.secciones, secciones_por_curso=base.secciones_por_curso
    )
    moodle.formularios = base.formularios
    return moodle


def test_un_reintento_tras_un_fallo_parcial_no_da_cambiada_en_el_aula(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, _huella_del_aula())
    moodle = _aula_que_falla()
    primero = _publicar_real(carpeta, moodle, ["importada.md"])
    assert primero["errores"] == ["ERROR_ACTUALIZACION"]
    assert moodle.formularios[501]["name"] == "Nuevo"  # escribió antes de fallar
    assert estado.huellas_de_copia(carpeta / ".tiza", 5678) == {501: _huella_del_aula()}
    segundo = _publicar_real(carpeta, moodle, ["importada.md"])
    assert segundo["errores"] == [] and segundo["resultado"] == "ok"
    doc = contenido.cargar(carpeta / "importada.md")
    enviada = tipos.huella_de_lo_enviado(
        tipos.obtener("pagina"), doc, contenido.html_para_moodle(doc)
    )
    assert estado.huellas_de_copia(carpeta / ".tiza", 5678) == {501: enviada}  # renovada


def test_un_cambio_del_docente_tras_el_fallo_sigue_dando_cambiada(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, _huella_del_aula())
    moodle = _aula_que_falla()
    _publicar_real(carpeta, moodle, ["importada.md"])
    moodle.formularios[501]["page[text]"] = "<p>Lo cambió el docente</p>"
    segundo = _publicar_real(carpeta, moodle, ["importada.md"])
    assert segundo["errores"] == ["CAMBIADA_EN_EL_AULA"]


# --solo-fechas con origen


def _aula_con_tarea_importada(entrega=(2026, 10, 10, 23, 59)) -> MoodleFalso:
    moodle = MoodleFalso(
        secciones_por_curso={
            5678: [
                {
                    "numero": 2,
                    "nombre": "Tema 2",
                    "id": 20,
                    "modulos": [{"cmid": 601, "nombre": "Vieja", "tipo": "tarea"}],
                }
            ]
        }
    )
    moodle.formularios[601] = {
        "visible": "1",
        "name": "Vieja",
        "introeditor[text]": "<p>Enunciado del aula</p>",
        **fecha_en_formulario("allowsubmissionsfromdate", (2026, 10, 1, 0, 0)),
        **fecha_en_formulario("duedate", entrega),
    }
    return moodle


def _tarea_importada(carpeta: Path, entrega="2026-10-12") -> None:
    (carpeta / "tarea.md").write_text(
        "---\ntipo: tarea\nnombre: Otro nombre\nseccion: 2\napertura: 2026-10-01\n"
        f"entrega: {entrega}\norigen:\n  curso: 5678\n  cmid: 601\n---\n\nResuelve.\n",
        encoding="utf-8",
    )


def _huella_de_la_tarea(entrega=(2026, 10, 10, 23, 59)) -> str:
    return tipos.huella_aula(
        "Vieja",
        "<p>Enunciado del aula</p>",
        {
            "allowsubmissionsfromdate": (2026, 10, 1, 0, 0),
            "duedate": entrega,
        },
    )


def _solo_fechas(carpeta: Path, moodle, presencia=None) -> dict:
    return publicacion.publicar_en_cursos(
        moodle,
        CFG,
        [contenido.cargar(carpeta / "tarea.md")],
        carpeta,
        presencia or PresenciaFalsa(),
        entorno="real",
        solo_fechas=True,
    )


def _copia_de_tarea(carpeta: Path, huella: str) -> None:
    _escribir_copia(carpeta, huella, cmid=601)
    datos = estado.cargar_copia(carpeta / ".tiza")
    datos["cursos"]["5678"]["actividades"][0].update(modulo="assign", fichero="tarea.md")
    estado.escribir_copia(carpeta / ".tiza", datos)


def test_solo_fechas_con_origen_cambia_las_fechas_y_renueva_la_huella(tmp_path):
    carpeta = tmp_path.resolve()
    _tarea_importada(carpeta)
    _copia_de_tarea(carpeta, _huella_de_la_tarea())
    moodle = _aula_con_tarea_importada()
    documento = _solo_fechas(carpeta, moodle)
    assert documento["errores"] == []
    assert [c[1] for c in moodle.llamadas if c[0] == "actualizar"] == [601]
    assert moodle.formularios[601]["name"] == "Vieja"  # solo las fechas
    nueva = _huella_de_la_tarea((2026, 10, 12, 23, 59))
    assert estado.huellas_de_copia(carpeta / ".tiza", 5678) == {601: nueva}
    # La siguiente publicación completa no salta.
    doc = contenido.cargar(carpeta / "tarea.md")
    registro: dict = {}
    estado.anotar_verificado(registro, contenido.hash_documento(doc), "tarea.md", 100)
    completa = publicacion.publicar_en_cursos(
        moodle, CFG, [doc], carpeta, PresenciaFalsa(), entorno="real", verificados=registro
    )
    assert completa["errores"] == [] and completa["ficheros"][0]["accion"] == "renombrada"


def test_solo_fechas_con_origen_no_pisa_unas_fechas_cambiadas_a_mano(tmp_path):
    carpeta = tmp_path.resolve()
    _tarea_importada(carpeta)
    _copia_de_tarea(carpeta, _huella_de_la_tarea())
    moodle = _aula_con_tarea_importada(entrega=(2026, 10, 20, 8, 0))  # lo cambió el docente
    presencia = PresenciaFalsa()
    documento = _solo_fechas(carpeta, moodle, presencia)
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert not any(c[0] == "actualizar" for c in moodle.llamadas)
    assert "CAMBIADA_EN_EL_AULA" in presencia.codigos()
    assert estado.huellas_de_copia(carpeta / ".tiza", 5678) == {601: _huella_de_la_tarea()}


def test_solo_fechas_con_origen_reintenta_si_las_fechas_ya_estan_puestas(tmp_path):
    carpeta = tmp_path.resolve()
    _tarea_importada(carpeta)
    _copia_de_tarea(carpeta, _huella_de_la_tarea())  # la de antes del intento que falló
    moodle = _aula_con_tarea_importada(entrega=(2026, 10, 12, 23, 59))
    documento = _solo_fechas(carpeta, moodle)
    assert documento["errores"] == []
    # Aceptada por la segunda vía: no se renueva, se deja la huella que había.
    assert estado.huellas_de_copia(carpeta / ".tiza", 5678) == {601: _huella_de_la_tarea()}


def test_solo_fechas_aceptada_por_la_segunda_via_no_bendice_un_cambio_de_texto(tmp_path):
    carpeta = tmp_path.resolve()
    _tarea_importada(carpeta)
    _copia_de_tarea(carpeta, _huella_de_la_tarea())
    moodle = _aula_con_tarea_importada(entrega=(2026, 10, 12, 23, 59))  # fechas ya puestas
    moodle.formularios[601]["introeditor[text]"] = "<p>Lo cambió el docente</p>"
    documento = _solo_fechas(carpeta, moodle)
    assert documento["errores"] == []
    assert [c[1] for c in moodle.llamadas if c[0] == "actualizar"] == [601]
    assert estado.huellas_de_copia(carpeta / ".tiza", 5678) == {601: _huella_de_la_tarea()}
    doc = contenido.cargar(carpeta / "tarea.md")
    registro: dict = {}
    estado.anotar_verificado(registro, contenido.hash_documento(doc), "tarea.md", 100)
    llamadas = len(moodle.llamadas)
    completa = publicacion.publicar_en_cursos(
        moodle, CFG, [doc], carpeta, PresenciaFalsa(), entorno="real", verificados=registro
    )
    assert completa["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert not any(c[0] == "actualizar" for c in moodle.llamadas[llamadas:])


# Lo que se rechaza por su origen no deja nada hecho ni se confirma


def test_un_fichero_rechazado_no_deja_una_seccion_creada(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta, cmid=999, seccion='"Tema nuevo"')  # su origen ya no está
    moodle = _aula_importada()
    documento = _publicar_real(carpeta, moodle, ["importada.md"])
    assert documento["errores"] == ["ORIGEN_NO_ENCONTRADO"]
    assert not any(c[0] == "crear_seccion" for c in moodle.llamadas)
    # Y con un copia.json que no vale, ni la sección ni nada.
    _fichero_importado(carpeta, seccion='"Tema nuevo"')
    (carpeta / ".tiza").mkdir(exist_ok=True)
    (carpeta / ".tiza" / "copia.json").write_text("[]", encoding="utf-8")
    documento = _publicar_real(carpeta, moodle, ["importada.md"])
    assert documento["errores"] == ["COPIA_INVALIDA"]
    assert not any(c[0] == "crear_seccion" for c in moodle.llamadas)


def test_origen_duplicado_no_deja_una_seccion_creada(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta, "uno.md", "Uno", seccion='"Tema nuevo"')
    _fichero_importado(carpeta, "dos.md", "Dos", seccion='"Tema nuevo"')
    moodle = _aula_importada()
    documento = _publicar_real(carpeta, moodle, ["uno.md", "dos.md"])
    assert documento["errores"] == ["ORIGEN_DUPLICADO", "ORIGEN_DUPLICADO"]
    assert not any(c[0] == "crear_seccion" for c in moodle.llamadas)


def test_lo_rechazado_por_su_origen_no_entra_en_la_confirmacion(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta, "uno.md", "Uno")
    _fichero_importado(carpeta, "dos.md", "Dos")  # mismo origen que uno.md
    _fichero_importado(carpeta, "huerfano.md", "Huerfano", cmid=999)
    _fichero_normal(carpeta)
    _escribir_copia(carpeta, _huella_del_aula())
    presencia = PresenciaFalsa()
    documento = _publicar_real(
        carpeta, _aula_importada(), ["uno.md", "dos.md", "huerfano.md", "otra.md"], presencia
    )
    [resumen] = presencia.resumenes
    assert [d.fichero for d in resumen.documentos] == ["otra.md"]
    assert sorted(documento["errores"]) == [
        "ORIGEN_DUPLICADO",
        "ORIGEN_DUPLICADO",
        "ORIGEN_NO_ENCONTRADO",
    ]
    assert [f["nombre"] for f in documento["ficheros"]] == ["otra.md"]


def test_si_todo_se_rechaza_no_se_pide_confirmar(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta, cmid=999)
    presencia = PresenciaFalsa()
    moodle = _aula_importada()
    documento = _publicar_real(carpeta, moodle, ["importada.md"], presencia)
    assert presencia.resumenes == []
    assert documento["errores"] == ["ORIGEN_NO_ENCONTRADO"]
    assert not any(c[0] in ("crear", "actualizar") for c in moodle.llamadas)


def test_el_resumen_corto_tampoco_presenta_lo_rechazado(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta, cmid=999)
    _fichero_normal(carpeta)
    sin_pruebas = config.Config(
        url="https://aula.ejemplo.org/centro", usuario="profe", cursos={}, reales=(5678,)
    )
    presencia = PresenciaFalsa()
    documento = publicacion.publicar_en_cursos(
        _aula_importada(),
        sin_pruebas,
        [contenido.cargar(carpeta / f) for f in ("importada.md", "otra.md")],
        carpeta,
        presencia,
        entorno="real",
        visible=False,
    )
    [corto] = presencia.resumenes_cortos
    assert [d.fichero for d in corto.documentos] == ["otra.md"]
    assert documento["errores"] == ["ORIGEN_NO_ENCONTRADO"]


def test_el_origen_repetido_no_gasta_cupo_en_pruebas(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta, "uno.md", "Uno")
    _fichero_importado(carpeta, "dos.md", "Dos")
    _fichero_normal(carpeta)
    cupo = {"pruebas": 0}
    documento = publicacion.publicar_en_cursos(
        _aula_importada(),
        CFG,
        [contenido.cargar(carpeta / f) for f in ("uno.md", "dos.md", "otra.md")],
        carpeta,
        PresenciaFalsa(),
        entorno="pruebas",
        cupo=cupo,
    )
    assert cupo["pruebas"] == 1
    assert [f["nombre"] for f in documento["ficheros"]] == ["otra.md"]


# Avisos al docente


def test_huella_no_guardada_llega_al_docente(tmp_path, monkeypatch):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, _huella_del_aula())

    def no_guarda(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(estado, "guardar_huella_de_copia", no_guarda)
    presencia = PresenciaFalsa()
    documento = _publicar_real(carpeta, _aula_importada(), ["importada.md"], presencia)
    assert documento["errores"] == []
    assert "HUELLA_NO_GUARDADA" in [p["codigo"] for p in documento["pasos"]]
    [aviso] = [a for a in presencia.avisos if a.codigo == "HUELLA_NO_GUARDADA"]
    [linea] = mensajes.lineas_de_aviso(aviso)
    assert "la próxima vez pide una copia nueva" in linea.texto and "«Nuevo»" in linea.texto


# Dependencias entre ficheros del lote


def _dependiente(carpeta: Path, nombre="siguiente.md", de="importada.md") -> None:
    (carpeta / nombre).write_text(
        f"---\ntipo: pagina\nnombre: Siguiente\nseccion: 3\nrestricciones:\n  completar: [{de}]\n"
        "---\n\nDespués.\n",
        encoding="utf-8",
    )


def test_quien_depende_de_un_fichero_cambiado_falla_solo_y_el_lote_sigue(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta, extra="finalizacion: ver\n")
    _dependiente(carpeta)
    _fichero_normal(carpeta)
    _escribir_copia(carpeta, tipos.huella_aula("Viejo", "<p>Como estaba</p>"))
    moodle = _aula_importada()
    documento = _publicar_real(carpeta, moodle, ["importada.md", "siguiente.md", "otra.md"])
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA", "DEPENDENCIA_NO_PUBLICADA"]
    assert [f["nombre"] for f in documento["ficheros"]] == ["otra.md"]


def test_quien_depende_de_un_origen_rechazado_no_se_confirma_ni_se_publica(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta, cmid=999, extra="finalizacion: ver\n")
    _dependiente(carpeta)
    _fichero_normal(carpeta)
    presencia = PresenciaFalsa()
    moodle = _aula_importada()
    documento = _publicar_real(
        carpeta, moodle, ["importada.md", "siguiente.md", "otra.md"], presencia
    )
    assert documento["errores"] == ["ORIGEN_NO_ENCONTRADO", "DEPENDENCIA_NO_PUBLICADA"]
    assert [d.fichero for d in presencia.resumenes[0].documentos] == ["otra.md"]
    assert [f["nombre"] for f in documento["ficheros"]] == ["otra.md"]


def test_una_dependencia_importada_se_resuelve_por_su_origen(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta, extra="finalizacion: ver\n")  # en el aula se llama «Viejo»
    _dependiente(carpeta)
    moodle = _aula_importada()
    documento = _publicar_real(carpeta, moodle, ["siguiente.md"])
    assert documento["errores"] == []
    [fichero] = documento["ficheros"]
    texto = moodle.formularios[fichero["cmid"]]["availabilityconditionsjson"]
    assert json.loads(texto)["c"][0]["cm"] == 501


# --- Renombrar sin duplicar: el registro de lo publicado -----------------------------------


def _pagina(carpeta: Path, nombre: str, fichero="p.md", seccion="3", extra="") -> None:
    (carpeta / fichero).write_text(
        f"---\ntipo: pagina\nnombre: {nombre}\nseccion: {seccion}\n{extra}---\n\nTexto.\n",
        encoding="utf-8",
    )


def _aula_dos_cursos() -> MoodleFalso:
    """Pruebas (1234) y el real 5678 con secciones propias, para que no se mezclen."""
    return MoodleFalso(
        secciones=[
            {"numero": 3, "nombre": "Tema 3", "id": 31, "modulos": []},
            {"numero": 4, "nombre": "Tema 4", "id": 41, "modulos": []},
        ],
        secciones_por_curso={
            5678: [
                {"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []},
                {"numero": 4, "nombre": "Tema 4", "id": 40, "modulos": []},
            ]
        },
    )


def _publicar_en(carpeta: Path, moodle, entorno, fichero="p.md", presencia=None, **opciones):
    presencia = presencia or PresenciaFalsa()
    documento = _publicar_ficheros(carpeta, moodle, entorno, [fichero], presencia, **opciones)
    return documento, presencia


def _publicar_ficheros(carpeta, moodle, entorno, ficheros, presencia, **opciones) -> dict:
    documentos = [contenido.cargar(carpeta / f, raiz=carpeta) for f in ficheros]
    registro: dict = {}
    for doc in documentos:
        estado.anotar_verificado(registro, contenido.hash_documento(doc), doc.ruta.name, 100)
    return publicacion.publicar_en_cursos(
        moodle,
        CFG,
        documentos,
        carpeta,
        presencia,
        entorno=entorno,
        verificados=registro,
        **opciones,
    )


def _modulos(moodle, curso) -> list[dict]:
    return [m for s in moodle._de(curso) for m in s["modulos"]]


def test_publicar_en_pruebas_anota_el_registro(tmp_path):
    carpeta = tmp_path.resolve()
    _pagina(carpeta, "Repaso")
    documento, _ = _publicar_en(carpeta, _aula_dos_cursos(), "pruebas")
    assert documento["errores"] == []
    cmid = documento["ficheros"][0]["cmid"]
    assert estado.cargar_publicados(carpeta / ".tiza", 1234) == {
        "p.md": estado.Publicado(cmid=cmid, tipo="pagina")
    }


def test_renombrar_actualiza_la_misma_actividad(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina(carpeta, "Repaso")
    primero, _ = _publicar_en(carpeta, moodle, "pruebas")
    _pagina(carpeta, "Repaso final")
    segundo, _ = _publicar_en(carpeta, moodle, "pruebas")
    [fichero] = segundo["ficheros"]
    assert fichero["cmid"] == primero["ficheros"][0]["cmid"]
    assert fichero["accion"] == "renombrada"
    informe.validar(segundo)
    assert [m["nombre"] for m in _modulos(moodle, 1234)] == ["Repaso final"]
    assert estado.cargar_publicados(carpeta / ".tiza", 1234)["p.md"].cmid == fichero["cmid"]


def test_renombrar_en_real_lo_ensena_y_no_duplica(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina(carpeta, "A")
    _publicar_en(carpeta, moodle, "real")
    _pagina(carpeta, "B")
    documento, presencia = _publicar_en(carpeta, moodle, "real")
    assert documento["ficheros"][0]["accion"] == "renombrada"
    assert [m["nombre"] for m in _modulos(moodle, 5678)] == ["B"]
    [resumen] = presencia.resumenes
    assert resumen.nombres == (publicacion.CambioNombre("p.md", "A", "B"),)
    assert any(
        "Se cambia el nombre de «A» a «B»" in linea
        for linea in mensajes.detalle_real(resumen).finales
    )


def test_renombrar_y_cambiar_de_seccion_mueve_y_renombra(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina(carpeta, "A")
    primero, _ = _publicar_en(carpeta, moodle, "real")
    _pagina(carpeta, "B", seccion="4")
    documento, presencia = _publicar_en(carpeta, moodle, "real")
    [fichero] = documento["ficheros"]
    assert (fichero["cmid"], fichero["accion"]) == (primero["ficheros"][0]["cmid"], "renombrada")
    seccion4 = next(s for s in moodle._de(5678) if s["numero"] == 4)
    assert [m["nombre"] for m in seccion4["modulos"]] == ["B"]
    assert len(_modulos(moodle, 5678)) == 1
    [resumen] = presencia.resumenes
    assert [c.fichero for c in resumen.movimientos] == ["p.md"]
    finales = mensajes.detalle_real(resumen).finales
    assert any("se moverá de la sección «Tema 3» a «Tema 4»" in linea for linea in finales)
    assert any("Se cambia el nombre de «A» a «B»" in linea for linea in finales)


def test_la_confirmacion_corta_ensena_el_renombrado_por_registro(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    sin_pruebas = config.Config(
        url="https://aula.ejemplo.org/centro", usuario="profe", cursos={}, reales=(5678,)
    )
    _pagina(carpeta, "A")
    publicar_corto = lambda: publicacion.publicar_en_cursos(  # noqa: E731
        moodle,
        sin_pruebas,
        [contenido.cargar(carpeta / "p.md", raiz=carpeta)],
        carpeta,
        presencia,
        entorno="real",
        visible=False,
    )
    presencia = PresenciaFalsa()
    publicar_corto()
    _pagina(carpeta, "B")
    publicar_corto()
    corto = presencia.resumenes_cortos[-1]
    assert any(
        "Se cambia el nombre de «A» a «B»" in linea
        for linea in mensajes.detalle_corto(corto).finales
    )
    assert [m["nombre"] for m in _modulos(moodle, 5678)] == ["B"]


def test_actividad_borrada_en_el_aula_se_avisa_y_se_crea_de_nuevo(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina(carpeta, "A")
    primero, _ = _publicar_en(carpeta, moodle, "real")
    viejo = primero["ficheros"][0]["cmid"]
    estado.guardar_publicado(
        carpeta / ".tiza",
        5678,
        "p.md",
        estado.Publicado(cmid=viejo, tipo="pagina", huella="a" * 64, marca="b" * 64),
    )
    for seccion in moodle._de(5678):
        seccion["modulos"] = []  # el docente la borró en el aula
    documento, presencia = _publicar_en(carpeta, moodle, "real")
    [fichero] = documento["ficheros"]
    assert fichero["accion"] == "creada" and fichero["cmid"] != viejo
    [resumen] = presencia.resumenes
    assert resumen.documentos[0].borrada is True
    assert (
        "Ya no está en el aula: se creará de nuevo."
        in mensajes.detalle_real(resumen).documentos[0].lineas
    )
    # Recreada: la huella y la marca de la anterior no valen; en real, la base es la releída.
    assert estado.cargar_publicados(carpeta / ".tiza", 5678)["p.md"] == estado.Publicado(
        cmid=fichero["cmid"],
        tipo="pagina",
        huella=_huella_del_aula_en(moodle, carpeta, fichero["cmid"]),
        marca=None,
    )


def test_en_pruebas_la_actividad_borrada_se_crea_sin_aviso(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina(carpeta, "A")
    _publicar_en(carpeta, moodle, "pruebas")
    for seccion in moodle._de(1234):
        seccion["modulos"] = []
    documento, presencia = _publicar_en(carpeta, moodle, "pruebas")
    assert documento["errores"] == [] and documento["ficheros"][0]["accion"] == "creada"
    assert presencia.resumenes == [] and presencia.resumenes_cortos == []


def test_la_confirmacion_corta_avisa_de_la_actividad_borrada(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    sin_pruebas = config.Config(
        url="https://aula.ejemplo.org/centro", usuario="profe", cursos={}, reales=(5678,)
    )
    _pagina(carpeta, "A")
    estado.guardar_publicado(
        carpeta / ".tiza", 5678, "p.md", estado.Publicado(cmid=77, tipo="pagina")
    )
    presencia = PresenciaFalsa()
    publicacion.publicar_en_cursos(
        moodle,
        sin_pruebas,
        [contenido.cargar(carpeta / "p.md", raiz=carpeta)],
        carpeta,
        presencia,
        entorno="real",
        visible=False,
    )
    [corto] = presencia.resumenes_cortos
    assert corto.documentos[0].borrada is True
    assert mensajes.detalle_corto(corto).documentos[0].lineas == (
        "Ya no está en el aula: se creará de nuevo.",
    )


def test_si_no_se_puede_guardar_el_registro_se_publica_y_se_avisa(tmp_path):
    carpeta = tmp_path.resolve()
    (carpeta / ".tiza").mkdir()
    (carpeta / ".tiza" / "publicados.json").mkdir()  # un directorio donde iría el fichero
    _pagina(carpeta, "A")
    moodle = _aula_dos_cursos()
    # Con ``raiz`` el registro dañado ya pararía al cargar; sin ella se llega a publicar.
    presencia = PresenciaFalsa()
    documento = publicacion.publicar_en_cursos(
        moodle,
        CFG,
        [contenido.cargar(carpeta / "p.md")],
        carpeta,
        presencia,
        entorno="pruebas",
    )
    assert documento["errores"] == []
    assert len(_modulos(moodle, 1234)) == 1
    [paso] = [p for p in documento["pasos"] if p["codigo"] == "REGISTRO_NO_GUARDADO"]
    assert (paso["resultado"], paso["detalle"]) == ("fallo", "p.md")
    [aviso] = [a for a in presencia.avisos if a.codigo == "REGISTRO_NO_GUARDADO"]
    [linea] = mensajes.lineas_de_aviso(aviso)
    assert "«A»" in linea.texto and linea.error


def test_un_documento_con_origen_tambien_se_registra_sin_tocar_copia_json(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, _huella_del_aula())
    antes = (carpeta / ".tiza" / "copia.json").read_text(encoding="utf-8")
    moodle = _aula_importada()
    documento = _publicar_ficheros(carpeta, moodle, "pruebas", ["importada.md"], PresenciaFalsa())
    cmid = documento["ficheros"][0]["cmid"]
    assert estado.cargar_publicados(carpeta / ".tiza", 1234)["importada.md"].cmid == cmid
    assert (carpeta / ".tiza" / "copia.json").read_text(encoding="utf-8") == antes


def test_solo_fechas_no_escribe_el_registro(tmp_path):
    carpeta = tmp_path.resolve()
    tarea_en(carpeta)
    moodle = aula_con_tarea()
    documento = _publicar_ficheros(
        carpeta, moodle, "pruebas", ["tarea.md"], PresenciaFalsa(), solo_fechas=True
    )
    assert documento["errores"] == []
    assert not (carpeta / ".tiza" / "publicados.json").exists()


def test_con_varios_cursos_reales_hay_una_entrada_por_curso(tmp_path):
    carpeta = tmp_path.resolve()
    cfg = config.Config(
        url="https://aula.ejemplo.org/centro",
        usuario="profe",
        cursos={"pruebas": 1234},
        reales=(5678, 9999),
    )
    moodle = MoodleFalso(
        secciones_por_curso={
            curso: [{"numero": 3, "nombre": "Tema 3", "id": curso, "modulos": []}]
            for curso in (1234, 5678, 9999)
        }
    )
    _pagina(carpeta, "A")
    doc = contenido.cargar(carpeta / "p.md", raiz=carpeta)
    registro: dict = {}
    estado.anotar_verificado(registro, contenido.hash_documento(doc), "p.md", 100)
    publicacion.publicar_en_cursos(
        moodle, cfg, [doc], carpeta, PresenciaFalsa(), entorno="real", verificados=registro
    )
    for curso in (5678, 9999):
        assert list(estado.cargar_publicados(carpeta / ".tiza", curso)) == ["p.md"]
    assert estado.cargar_publicados(carpeta / ".tiza", 1234) == {}


# --- Cambios a mano en el aula: detectar, preguntar y guardar la huella --------------------

CFG_DOS_REALES = config.Config(
    url="https://aula.ejemplo.org/centro",
    usuario="profe",
    cursos={"pruebas": 1234},
    reales=(5678, 9999),
)


def _pagina_texto(carpeta: Path, nombre="A", texto="Texto.", fichero="p.md") -> None:
    (carpeta / fichero).write_text(
        f"---\ntipo: pagina\nnombre: {nombre}\nseccion: 3\n---\n\n{texto}\n", encoding="utf-8"
    )


def _aula_varios_cursos() -> MoodleFalso:
    return MoodleFalso(
        secciones_por_curso={
            curso: [{"numero": 3, "nombre": "Tema 3", "id": curso + 1, "modulos": []}]
            for curso in (1234, 5678, 9999)
        }
    )


def _en(carpeta, moodle, entorno, ficheros=("p.md",), presencia=None, cfg=CFG, **opciones):
    """Publica con el registro cargado (``raiz``); devuelve (informe, presencia)."""
    presencia = presencia or PresenciaFalsa()
    documentos = [contenido.cargar(carpeta / f, raiz=carpeta) for f in ficheros]
    verificados: dict = {}
    for doc in documentos:
        estado.anotar_verificado(verificados, contenido.hash_documento(doc), doc.ruta.name, 100)
    documento = publicacion.publicar_en_cursos(
        moodle,
        cfg,
        documentos,
        carpeta,
        presencia,
        entorno=entorno,
        verificados=verificados,
        **opciones,
    )
    return documento, presencia


def _entrada(carpeta: Path, curso=5678, ruta="p.md") -> estado.Publicado:
    return estado.cargar_publicados(carpeta / ".tiza", curso)[ruta]


def _huella_del_aula_en(moodle, carpeta: Path, cmid: int, fichero="p.md") -> str:
    doc = contenido.cargar(carpeta / fichero)
    return tipos.huella_del_formulario(tipos.obtener(doc.tipo), doc, moodle.leer_modulo(cmid))


def _retocar(moodle, cmid: int, *, nombre=None, texto=None, campos=None) -> None:
    """Lo que haría el docente a mano en el formulario de la actividad."""
    formulario = moodle.formularios[cmid]
    if nombre is not None:
        formulario["name"] = nombre
        for secciones in (moodle.secciones, *moodle.secciones_por_curso.values()):
            for seccion in secciones:
                for modulo in seccion["modulos"]:
                    if modulo["cmid"] == cmid:
                        modulo["nombre"] = nombre
    if texto is not None:
        formulario["page[text]" if "page[text]" in formulario else "introeditor[text]"] = texto
    formulario.update(campos or {})


def _lecturas(moodle) -> int:
    return len([c for c in moodle.llamadas if c[0] == "leer_modulo"])


def _escrituras(moodle, cmid: int) -> list:
    return [c for c in moodle.llamadas if c[0] == "actualizar" and c[1] == cmid]


def _publicada_y_retocada(tmp_path, **retoque):
    """Una página «A» publicada en real y retocada a mano en el aula; el fichero cambia después."""
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    primero, _ = _en(carpeta, moodle, "real")
    cmid = primero["ficheros"][0]["cmid"]
    _retocar(moodle, cmid, **retoque)
    _pagina_texto(carpeta, texto="Texto de tiza, nuevo.")
    return carpeta, moodle, cmid


def test_la_primera_publicacion_en_real_guarda_la_huella_releida(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    documento, presencia = _en(carpeta, moodle, "real")
    cmid = documento["ficheros"][0]["cmid"]
    assert _entrada(carpeta) == estado.Publicado(
        cmid, "pagina", huella=_huella_del_aula_en(moodle, carpeta, cmid), marca=None
    )
    assert presencia.resumenes_sobrescribir == []


def test_en_pruebas_no_se_guarda_huella_ni_se_lee_de_mas(tmp_path):
    carpeta = tmp_path.resolve()
    _pagina_texto(carpeta)
    en_pruebas, en_real = _aula_dos_cursos(), _aula_dos_cursos()
    _en(carpeta, en_pruebas, "pruebas")
    assert _entrada(carpeta, 1234).huella is None
    _en(carpeta, en_real, "real")
    # En real se relee una vez más (la huella que se guarda); en pruebas, nada de más.
    assert _lecturas(en_real) == _lecturas(en_pruebas) + 1
    # Ni siquiera una entrada con huella hace leer más en pruebas.
    estado.guardar_publicado(
        carpeta / ".tiza",
        1234,
        "p.md",
        estado.Publicado(_entrada(carpeta, 1234).cmid, "pagina", "a" * 64),
    )
    antes = _lecturas(en_pruebas)
    _en(carpeta, en_pruebas, "pruebas")
    sin_huella = _aula_dos_cursos()
    _en(carpeta, sin_huella, "pruebas")
    assert _lecturas(en_pruebas) - antes == _lecturas(sin_huella)


def test_se_conservan_huella_y_marca_si_es_el_mismo_cmid_y_nadie_cambia_nada(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    primero, _ = _en(carpeta, moodle, "pruebas")
    cmid = primero["ficheros"][0]["cmid"]
    entrada = estado.Publicado(cmid, "pagina", huella="a" * 64, marca="b" * 64)
    estado.guardar_publicado(carpeta / ".tiza", 1234, "p.md", entrada)
    _pagina_texto(carpeta, texto="Otro texto.")
    segundo, _ = _en(carpeta, moodle, "pruebas")
    assert segundo["ficheros"][0]["cmid"] == cmid
    assert _entrada(carpeta, 1234) == entrada  # pruebas no compara ni toca la base
    # Si la actividad se recrea (otro cmid), van a None.
    for seccion in moodle._de(1234):
        seccion["modulos"] = []
    tercero, _ = _en(carpeta, moodle, "pruebas")
    assert _entrada(carpeta, 1234) == estado.Publicado(tercero["ficheros"][0]["cmid"], "pagina")


def test_republicar_sin_cambios_a_mano_no_pregunta_y_renueva_la_huella(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    primero, _ = _en(carpeta, moodle, "real")
    cmid = primero["ficheros"][0]["cmid"]
    antes = _entrada(carpeta).huella
    _pagina_texto(carpeta, texto="Texto de tiza, nuevo.")
    segundo, presencia = _en(carpeta, moodle, "real")
    assert segundo["errores"] == [] and presencia.resumenes_sobrescribir == []
    assert len(_escrituras(moodle, cmid)) == 1
    assert "CAMBIO_DEL_AULA_DESCARTADO" not in [p["codigo"] for p in segundo["pasos"]]
    ahora = _entrada(carpeta)
    assert ahora.huella != antes
    assert ahora.huella == _huella_del_aula_en(moodle, carpeta, cmid)
    # Una tercera vez, sin tocar nada, tampoco pregunta.
    tercero, presencia = _en(carpeta, moodle, "real")
    assert tercero["errores"] == [] and presencia.resumenes_sobrescribir == []


@pytest.mark.parametrize("retoque", [{"texto": "<p>A mano</p>"}, {"nombre": "Z"}])
def test_un_cambio_a_mano_y_no_a_sobrescribir_no_publica_y_el_resto_sigue(tmp_path, retoque):
    carpeta, moodle, cmid = _publicada_y_retocada(tmp_path, **retoque)
    _pagina_texto(carpeta, nombre="Otra", fichero="otra.md")
    huella = _entrada(carpeta).huella
    escrituras = len(_escrituras(moodle, cmid))
    documento, presencia = _en(carpeta, moodle, "real", ("p.md", "otra.md"))
    informe.validar(documento)
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert {"codigo": "PUBLICAR", "resultado": "fallo", "detalle": "p.md"} in documento["pasos"]
    assert [f["nombre"] for f in documento["ficheros"]] == ["otra.md"]
    assert len(_escrituras(moodle, cmid)) == escrituras  # no se tocó
    assert presencia.resumenes_sobrescribir == [
        publicacion.ResumenSobrescribir(5678, None, ("A",), 1, 1)
    ]
    [aviso] = [a for a in presencia.avisos if a.codigo == "CAMBIADA_DESDE_LA_PUBLICACION"]
    [linea] = mensajes.lineas_de_aviso(aviso)
    assert linea.texto == (
        "«A» ha cambiado en el aula desde la última vez que tiza la publicó, y no se ha tocado. "
        "Para juntar tus cambios, pide al agente que traiga la versión del aula."
    )
    assert "copia" not in linea.texto and linea.error
    assert _entrada(carpeta).huella == huella  # la base no se renueva


def test_un_cambio_a_mano_de_fecha_tambien_se_pregunta(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    tarea_en(carpeta)
    primero, _ = _en(carpeta, moodle, "real", ("tarea.md",))
    cmid = primero["ficheros"][0]["cmid"]
    _retocar(moodle, cmid, campos=fecha_en_formulario("duedate", (2026, 11, 3, 10, 0)))
    documento, presencia = _en(carpeta, moodle, "real", ("tarea.md",))
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert [r.actividades for r in presencia.resumenes_sobrescribir] == [("Problemas",)]


@pytest.mark.parametrize("retoque", [{"texto": "<p>A mano</p>"}, {"nombre": "Z"}])
def test_sobrescribir_publica_deja_el_paso_y_renueva_la_huella(tmp_path, retoque):
    carpeta, moodle, cmid = _publicada_y_retocada(tmp_path, **retoque)
    presencia = PresenciaFalsa(sobrescribir=True)
    documento, presencia = _en(carpeta, moodle, "real", presencia=presencia)
    informe.validar(documento)
    assert documento["errores"] == [] and documento["resultado"] == "ok"
    assert {"codigo": "CAMBIO_DEL_AULA_DESCARTADO", "resultado": "ok", "detalle": "p.md"} in (
        documento["pasos"]
    )
    assert moodle.formularios[cmid]["name"] == "A"
    assert "Texto de tiza, nuevo." in moodle.formularios[cmid]["page[text]"]
    assert _entrada(carpeta).huella == _huella_del_aula_en(moodle, carpeta, cmid)
    assert "CAMBIADA_EN_EL_AULA" not in presencia.codigos()


def test_la_pregunta_no_sale_si_el_docente_dice_que_no_a_la_confirmacion(tmp_path):
    carpeta, moodle, cmid = _publicada_y_retocada(tmp_path, texto="<p>A mano</p>")
    escrituras = len(_escrituras(moodle, cmid))
    presencia = PresenciaFalsa(real=False, sobrescribir=True)
    documento, presencia = _en(carpeta, moodle, "real", presencia=presencia)
    assert presencia.resumenes_sobrescribir == []
    assert len(_escrituras(moodle, cmid)) == escrituras


def test_la_pregunta_va_despues_de_la_confirmacion_normal(tmp_path):
    carpeta, moodle, _cmid = _publicada_y_retocada(tmp_path, texto="<p>A mano</p>")
    orden: list[str] = []

    class Ordenada(PresenciaFalsa):
        def confirmar_real(self, resumen):
            orden.append("real")
            return super().confirmar_real(resumen)

        def confirmar_sobrescribir(self, resumen):
            orden.append("sobrescribir")
            return super().confirmar_sobrescribir(resumen)

    _en(carpeta, moodle, "real", presencia=Ordenada())
    assert orden == ["real", "sobrescribir"]


def test_con_la_peticion_retirada_en_la_pregunta_no_se_sobrescribe(tmp_path):
    carpeta, moodle, cmid = _publicada_y_retocada(tmp_path, texto="<p>A mano</p>")
    escrituras = len(_escrituras(moodle, cmid))
    respuestas = iter([True, False])  # vigente tras la confirmación; retirada tras la pregunta
    documento, presencia = _en(
        carpeta,
        moodle,
        "real",
        presencia=PresenciaFalsa(sobrescribir=True),
        vigente=lambda: next(respuestas),
    )
    assert documento["errores"] == ["PETICION_RETIRADA"]
    assert len(_escrituras(moodle, cmid)) == escrituras
    assert "A mano" in moodle.formularios[cmid]["page[text]"]


def test_un_intento_anterior_a_medias_no_cuenta_como_cambio(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    primero, _ = _en(carpeta, moodle, "real")
    cmid = primero["ficheros"][0]["cmid"]
    _pagina_texto(carpeta, texto="Texto de tiza, nuevo.")
    # Un intento anterior ya escribió esto y falló al verificar: la base sigue siendo la vieja.
    nuevo = contenido.cargar(carpeta / "p.md")
    _retocar(moodle, cmid, texto=contenido.html_para_moodle(nuevo))
    documento, presencia = _en(carpeta, moodle, "real")
    assert documento["errores"] == [] and presencia.resumenes_sobrescribir == []


def test_una_marca_igual_al_fichero_cuenta_como_cambiada_aunque_el_aula_no_cambie(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    primero, _ = _en(carpeta, moodle, "real")
    cmid = primero["ficheros"][0]["cmid"]
    sha = hashlib.sha256((carpeta / "p.md").read_bytes()).hexdigest()
    base = _entrada(carpeta)
    estado.guardar_publicado(
        carpeta / ".tiza", 5678, "p.md", estado.Publicado(cmid, "pagina", base.huella, sha)
    )
    lecturas = _lecturas(moodle)
    documento, presencia = _en(carpeta, moodle, "real")
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert [r.actividades for r in presencia.resumenes_sobrescribir] == [("A",)]
    assert _lecturas(moodle) == lecturas  # con la marca ya se sabe: no se lee el aula
    assert _entrada(carpeta).marca == sha


def test_con_el_fichero_ya_juntado_la_marca_no_cuenta_y_tras_publicar_queda_a_none(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    primero, _ = _en(carpeta, moodle, "real")
    cmid = primero["ficheros"][0]["cmid"]
    sha = hashlib.sha256((carpeta / "p.md").read_bytes()).hexdigest()
    base = _entrada(carpeta)
    estado.guardar_publicado(
        carpeta / ".tiza", 5678, "p.md", estado.Publicado(cmid, "pagina", base.huella, sha)
    )
    _pagina_texto(carpeta, texto="Con lo que cambió en el aula.")  # el docente junta
    documento, presencia = _en(carpeta, moodle, "real")
    assert documento["errores"] == [] and presencia.resumenes_sobrescribir == []
    assert _entrada(carpeta).marca is None
    assert _entrada(carpeta).huella == _huella_del_aula_en(moodle, carpeta, cmid)


def test_un_cambio_entre_la_confirmacion_y_la_escritura_no_se_pisa(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    primero, _ = _en(carpeta, moodle, "real")
    cmid = primero["ficheros"][0]["cmid"]
    _pagina_texto(carpeta, texto="Texto de tiza, nuevo.")

    class RetocaTrasMirar(PresenciaFalsa):
        def confirmar_real(self, resumen):
            _retocar(moodle, cmid, texto="<p>A mano, justo ahora</p>")
            return super().confirmar_real(resumen)

    escrituras = len(_escrituras(moodle, cmid))
    documento, presencia = _en(carpeta, moodle, "real", presencia=RetocaTrasMirar())
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert len(_escrituras(moodle, cmid)) == escrituras
    assert "A mano, justo ahora" in moodle.formularios[cmid]["page[text]"]
    assert presencia.resumenes_sobrescribir == []  # no estaba cambiado cuando se preguntó
    assert "CAMBIADA_DESDE_LA_PUBLICACION" in presencia.codigos()


def test_con_varios_cursos_reales_se_pregunta_solo_en_el_que_cambio(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_varios_cursos()
    _pagina_texto(carpeta)
    _en(carpeta, moodle, "real", cfg=CFG_DOS_REALES, presencia=PresenciaFalsa(real=(True, True)))
    cmid = _entrada(carpeta, 5678).cmid
    _retocar(moodle, cmid, texto="<p>A mano</p>")
    _pagina_texto(carpeta, texto="Texto de tiza, nuevo.")
    presencia = PresenciaFalsa(real=(True, True), sobrescribir=(True,))
    documento, presencia = _en(carpeta, moodle, "real", cfg=CFG_DOS_REALES, presencia=presencia)
    assert documento["errores"] == []
    assert [(r.curso, r.posicion, r.total) for r in presencia.resumenes_sobrescribir] == [
        (5678, 1, 2)
    ]
    for curso in (5678, 9999):
        assert "nuevo" in moodle.formularios[_entrada(carpeta, curso).cmid]["page[text]"]


def test_con_varios_cursos_reales_la_pregunta_lleva_la_posicion_del_curso(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_varios_cursos()
    _pagina_texto(carpeta)
    _en(carpeta, moodle, "real", cfg=CFG_DOS_REALES, presencia=PresenciaFalsa(real=(True, True)))
    _retocar(moodle, _entrada(carpeta, 9999).cmid, texto="<p>A mano</p>")
    _pagina_texto(carpeta, texto="Texto de tiza, nuevo.")
    documento, presencia = _en(
        carpeta, moodle, "real", cfg=CFG_DOS_REALES, presencia=PresenciaFalsa(real=(True, True))
    )
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert [(r.curso, r.posicion, r.total) for r in presencia.resumenes_sobrescribir] == [
        (9999, 2, 2)
    ]
    # El primero, sin cambios a mano, se publicó sin preguntar.
    assert "nuevo" in moodle.formularios[_entrada(carpeta, 5678).cmid]["page[text]"]
    assert "A mano" in moodle.formularios[_entrada(carpeta, 9999).cmid]["page[text]"]


def test_un_documento_con_origen_en_su_curso_sigue_su_camino_sin_pregunta_nueva(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, _huella_del_aula())
    estado.guardar_publicado(
        carpeta / ".tiza", 5678, "importada.md", estado.Publicado(501, "pagina", "a" * 64)
    )
    moodle = _aula_importada()
    documento, presencia = _en(carpeta, moodle, "real", ("importada.md",))
    assert documento["errores"] == [] and presencia.resumenes_sobrescribir == []
    # La base del registro no se toca ni se relee: manda ``copia.json``.
    assert _entrada(carpeta, ruta="importada.md").huella == "a" * 64
    assert _lecturas(moodle) == 2  # comparar con la copia y verificar; nada más


def _tarea_publicada(tmp_path, entrega="2026-10-12"):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    tarea_en(carpeta, entrega=entrega)
    primero, _ = _en(carpeta, moodle, "real", ("tarea.md",))
    return carpeta, moodle, primero["ficheros"][0]["cmid"]


def test_solo_fechas_sin_cambio_a_mano_cambia_las_fechas_y_renueva_la_huella(tmp_path):
    carpeta, moodle, cmid = _tarea_publicada(tmp_path)
    antes = _entrada(carpeta, ruta="tarea.md").huella
    tarea_en(carpeta, entrega="2026-10-20")
    documento, presencia = _en(carpeta, moodle, "real", ("tarea.md",), solo_fechas=True)
    assert documento["errores"] == [] and presencia.resumenes_sobrescribir == []
    assert len(_escrituras(moodle, cmid)) == 1  # la creación no es un ``actualizar``
    ahora = _entrada(carpeta, ruta="tarea.md").huella
    assert ahora != antes
    assert ahora == _huella_del_aula_en(moodle, carpeta, cmid, "tarea.md")


def test_solo_fechas_con_cambio_a_mano_y_si_escribe_las_fechas_y_no_renueva(tmp_path):
    carpeta, moodle, cmid = _tarea_publicada(tmp_path)
    antes = _entrada(carpeta, ruta="tarea.md").huella
    _retocar(moodle, cmid, texto="<p>Enunciado a mano</p>")
    tarea_en(carpeta, entrega="2026-10-20")
    documento, presencia = _en(
        carpeta, moodle, "real", ("tarea.md",), PresenciaFalsa(sobrescribir=True), solo_fechas=True
    )
    assert documento["errores"] == []
    assert [r.actividades for r in presencia.resumenes_sobrescribir] == [("Problemas",)]
    assert {"codigo": "CAMBIO_DEL_AULA_DESCARTADO", "resultado": "ok", "detalle": "tarea.md"} in (
        documento["pasos"]
    )
    assert len(_escrituras(moodle, cmid)) == 1
    assert moodle.formularios[cmid]["introeditor[text]"] == "<p>Enunciado a mano</p>"
    assert _entrada(carpeta, ruta="tarea.md").huella == antes  # el texto de la aula sigue contando


def test_solo_fechas_con_cambio_a_mano_y_no_no_escribe_nada(tmp_path):
    carpeta, moodle, cmid = _tarea_publicada(tmp_path)
    _retocar(moodle, cmid, nombre="Otro nombre")
    tarea_en(carpeta, entrega="2026-10-20")
    documento, presencia = _en(carpeta, moodle, "real", ("tarea.md",), solo_fechas=True)
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert _escrituras(moodle, cmid) == []
    assert "CAMBIADA_DESDE_LA_PUBLICACION" in presencia.codigos()


def test_si_no_se_puede_leer_el_aula_al_buscar_cambios_cuenta_como_cambiada(tmp_path):
    carpeta, moodle, cmid = _publicada_y_retocada(tmp_path)
    original = moodle.leer_modulo

    def leer(cmid_pedido):
        if cmid_pedido == cmid:
            raise ErrorPublicacion("ERROR_CONSULTA")
        return original(cmid_pedido)

    moodle.leer_modulo = leer
    documento, presencia = _en(carpeta, moodle, "real")
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert [r.actividades for r in presencia.resumenes_sobrescribir] == [("A",)]


def test_si_no_se_puede_releer_tras_publicar_la_entrada_queda_sin_huella_y_se_avisa(
    tmp_path, monkeypatch
):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    primero, _ = _en(carpeta, moodle, "real")
    cmid = primero["ficheros"][0]["cmid"]
    _pagina_texto(carpeta, texto="Texto de tiza, nuevo.")
    original = moodle.leer_modulo
    registrando = []
    registrar = publicacion._registrar_publicado

    def registrar_marcando(*args, **kwargs):
        registrando.append(True)  # desde aquí se relee el formulario para guardar la huella
        return registrar(*args, **kwargs)

    def leer(cmid_pedido):
        # Buscar cambios, comprobar y verificar valen; falla la relectura del registro.
        if registrando:
            registrando.clear()  # solo falla esa relectura; la siguiente publicación va bien
            raise ErrorPublicacion("ERROR_CONSULTA")
        return original(cmid_pedido)

    monkeypatch.setattr(publicacion, "_registrar_publicado", registrar_marcando)
    moodle.leer_modulo = leer
    documento, presencia = _en(carpeta, moodle, "real")
    assert documento["ficheros"][0]["cmid"] == cmid  # la publicación quedó hecha
    assert _entrada(carpeta) == estado.Publicado(cmid, "pagina", huella=None, marca=None)
    [paso] = [p for p in documento["pasos"] if p["codigo"] == "REGISTRO_NO_GUARDADO"]
    assert (paso["resultado"], paso["detalle"]) == ("fallo", "p.md")
    assert "REGISTRO_NO_GUARDADO" in presencia.codigos()
    assert documento["errores"] == []
    # La próxima vez no se puede comparar: es como una entrada antigua.
    siguiente, presencia = _en(carpeta, moodle, "real")
    assert siguiente["errores"] == [] and presencia.resumenes_sobrescribir == []


def test_fallar_la_lectura_justo_antes_de_escribir_para_el_lote_sin_escribir_nada(tmp_path):
    carpeta, moodle, cmid = _publicada_y_retocada(tmp_path)  # sin retoque: la base vale
    _pagina_texto(carpeta, nombre="Otra", fichero="otra.md")
    escrituras = len(_escrituras(moodle, cmid))
    original = moodle.leer_modulo
    confirmada = []

    class Confirmada(PresenciaFalsa):
        def confirmar_real(self, resumen):
            confirmada.append(True)
            return super().confirmar_real(resumen)

    def leer(cmid_pedido):
        # La detección previa (antes de confirmar) lee bien; la comparación previa a escribir, no.
        if confirmada and cmid_pedido == cmid:
            raise ErrorPublicacion("ERROR_CONSULTA")
        return original(cmid_pedido)

    moodle.leer_modulo = leer
    documento, presencia = _en(carpeta, moodle, "real", ("p.md", "otra.md"), presencia=Confirmada())
    assert documento["errores"] == ["ERROR_CONSULTA"]
    assert presencia.resumenes_sobrescribir == []  # la detección no vio ningún cambio
    assert len(_escrituras(moodle, cmid)) == escrituras  # no se escribió nada
    assert [f["nombre"] for f in documento["ficheros"]] == []


def test_solo_fechas_con_las_fechas_ya_escritas_no_cuenta_como_cambio_y_no_renueva(tmp_path):
    carpeta, moodle, cmid = _tarea_publicada(tmp_path)
    antes = _entrada(carpeta, ruta="tarea.md").huella
    tarea_en(carpeta, entrega="2026-10-20")
    # Un intento anterior escribió las fechas y falló al verificar: la base sigue siendo la vieja.
    doc = contenido.cargar(carpeta / "tarea.md", raiz=carpeta)
    moodle.actualizar(cmid, publicar.payload_solo_fechas(doc))
    escrituras = len(_escrituras(moodle, cmid))
    documento, presencia = _en(carpeta, moodle, "real", ("tarea.md",), solo_fechas=True)
    assert documento["errores"] == [] and presencia.resumenes_sobrescribir == []
    assert len(_escrituras(moodle, cmid)) == escrituras + 1
    assert _entrada(carpeta, ruta="tarea.md").huella == antes  # como en ``origen``: no se renueva


def test_solo_fechas_con_otras_fechas_a_mano_distintas_de_las_pedidas_si_pregunta(tmp_path):
    carpeta, moodle, cmid = _tarea_publicada(tmp_path)
    tarea_en(carpeta, entrega="2026-10-20")
    doc = contenido.cargar(carpeta / "tarea.md", raiz=carpeta)
    moodle.actualizar(cmid, publicar.payload_solo_fechas(doc))
    _retocar(moodle, cmid, campos=fecha_en_formulario("duedate", (2026, 11, 3, 10, 0)))
    documento, presencia = _en(carpeta, moodle, "real", ("tarea.md",), solo_fechas=True)
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert [r.actividades for r in presencia.resumenes_sobrescribir] == [("Problemas",)]


def test_un_curso_no_ok_sin_errores_y_con_un_no_a_sobrescribir_corta(tmp_path, monkeypatch):
    carpeta = tmp_path.resolve()
    moodle = _aula_varios_cursos()
    _pagina_texto(carpeta)
    primero, _ = _en(carpeta, moodle, "real", cfg=CFG_DOS_REALES)
    cmid = primero["ficheros"][0]["cmid"]
    _retocar(moodle, cmid, texto="<p>A mano</p>")
    _pagina_texto(carpeta, texto="Texto de tiza, nuevo.")
    cursos = []
    publicar_con = publicacion.publicar_con

    def sin_errores(aula, entorno, curso, *args, **kwargs):
        cursos.append(curso)
        if len(cursos) == 1:  # un curso que no sale ok y no dice por qué
            return informe.crear("publicar", "abortado", [], [], [], entorno, curso)
        return publicar_con(aula, entorno, curso, *args, **kwargs)

    monkeypatch.setattr(publicacion, "publicar_con", sin_errores)
    _en(carpeta, moodle, "real", cfg=CFG_DOS_REALES)
    assert cursos == [5678]  # el siguiente curso no se toca


def test_sin_curso_de_pruebas_tambien_se_pregunta_tras_la_confirmacion_corta(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    sin_pruebas = config.Config(
        url="https://aula.ejemplo.org/centro", usuario="profe", cursos={}, reales=(5678,)
    )
    _pagina_texto(carpeta)
    _en(carpeta, moodle, "real", cfg=sin_pruebas, visible=False)
    cmid = _entrada(carpeta).cmid
    _retocar(moodle, cmid, texto="<p>A mano</p>")
    _pagina_texto(carpeta, texto="Texto de tiza, nuevo.")
    documento, presencia = _en(carpeta, moodle, "real", cfg=sin_pruebas, visible=False)
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert len(presencia.resumenes_cortos) == 1
    assert [r.actividades for r in presencia.resumenes_sobrescribir] == [("A",)]
    assert moodle.formularios[cmid]["page[text]"] == "<p>A mano</p>"


def test_un_no_a_sobrescribir_no_corta_los_cursos_siguientes(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_varios_cursos()
    _pagina_texto(carpeta)
    _en(carpeta, moodle, "real", cfg=CFG_DOS_REALES, presencia=PresenciaFalsa(real=(True, True)))
    _retocar(moodle, _entrada(carpeta, 5678).cmid, texto="<p>A mano</p>")
    _pagina_texto(carpeta, texto="Texto de tiza, nuevo.")
    documento, presencia = _en(
        carpeta, moodle, "real", cfg=CFG_DOS_REALES, presencia=PresenciaFalsa(real=(True, True))
    )
    informe.validar(documento)
    # El N es del informe (CAMBIADA_EN_EL_AULA), pero el curso siguiente se publica.
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert [(r.curso, r.posicion) for r in presencia.resumenes_sobrescribir] == [(5678, 1)]
    assert len(presencia.resumenes) == 2
    assert "A mano" in moodle.formularios[_entrada(carpeta, 5678).cmid]["page[text]"]
    assert "nuevo" in moodle.formularios[_entrada(carpeta, 9999).cmid]["page[text]"]


def test_otro_fallo_en_un_curso_sigue_cortando_los_siguientes(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_varios_cursos()
    _pagina_texto(carpeta)
    _en(carpeta, moodle, "real", cfg=CFG_DOS_REALES, presencia=PresenciaFalsa(real=(True, True)))
    cmid = _entrada(carpeta, 5678).cmid
    _retocar(moodle, cmid, texto="<p>A mano</p>")
    # Además del N, un rechazo de siempre en el mismo curso: un ``origen`` que ya no está.
    _fichero_importado(carpeta)
    _pagina_texto(carpeta, texto="Texto de tiza, nuevo.")
    documento, presencia = _en(
        carpeta,
        moodle,
        "real",
        ("p.md", "importada.md"),
        cfg=CFG_DOS_REALES,
        presencia=PresenciaFalsa(real=(True, True)),
    )
    assert "ORIGEN_NO_ENCONTRADO" in documento["errores"]
    assert len(presencia.resumenes) == 1  # el segundo curso no se llegó a confirmar


# --- Base de lo publicado en un curso real: publicados/<curso>/<cmid>/ ----------------------


def _base(carpeta: Path, curso=5678, ruta="p.md") -> Path:
    cmid = estado.cargar_publicados(carpeta / ".tiza", curso)[ruta].cmid
    return estado.ruta_base(carpeta / ".tiza", curso, cmid)


def test_publicar_en_real_guarda_la_base_fuente_y_enviado(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    documento, _ = _en(carpeta, moodle, "real")
    base = _base(carpeta)
    assert (base / "fuente").read_bytes() == (carpeta / "p.md").read_bytes()
    doc = contenido.cargar(carpeta / "p.md", raiz=carpeta)
    assert (base / "enviado.html").read_text(encoding="utf-8") == contenido.html_para_moodle(doc)
    assert "BASE_NO_GUARDADA" not in [p["codigo"] for p in documento["pasos"]]


def test_republicar_tras_editar_sustituye_la_base(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    _en(carpeta, moodle, "real")
    antes = _base(carpeta)
    _pagina_texto(carpeta, texto="Texto de tiza, nuevo.")
    _en(carpeta, moodle, "real")
    base = _base(carpeta)
    assert base == antes
    assert (base / "fuente").read_bytes() == (carpeta / "p.md").read_bytes()
    assert "nuevo" in (base / "enviado.html").read_text(encoding="utf-8")


def test_en_pruebas_no_hay_carpeta_publicados(tmp_path):
    carpeta = tmp_path.resolve()
    _pagina_texto(carpeta)
    _en(carpeta, _aula_dos_cursos(), "pruebas")
    assert not (carpeta / ".tiza" / "publicados").exists()


def test_solo_fechas_no_cambia_la_base(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    tarea_en(carpeta)
    _en(carpeta, moodle, "real", ficheros=("tarea.md",))
    base = _base(carpeta, ruta="tarea.md")
    fuente, enviado = (base / "fuente").read_bytes(), (base / "enviado.html").read_text("utf-8")
    tarea_en(carpeta, entrega="2026-10-20")  # otras fechas...
    (carpeta / "tarea.md").write_text(
        (carpeta / "tarea.md").read_text(encoding="utf-8").replace("Resuelve.", "Otro enunciado."),
        encoding="utf-8",
    )  # ...y un texto que --solo-fechas no publica: la base sigue siendo lo último publicado
    documento, _ = _en(carpeta, moodle, "real", ficheros=("tarea.md",), solo_fechas=True)
    assert documento["errores"] == []
    assert [p["codigo"] for p in documento["pasos"] if p["codigo"] == "SOLO_FECHAS"]
    assert (base / "fuente").read_bytes() == fuente
    assert (base / "enviado.html").read_text(encoding="utf-8") == enviado


def test_actividad_recreada_borra_la_base_vieja_y_escribe_la_nueva(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    primero, _ = _en(carpeta, moodle, "real")
    viejo = primero["ficheros"][0]["cmid"]
    base_vieja = estado.ruta_base(carpeta / ".tiza", 5678, viejo)
    assert (base_vieja / "fuente").exists()
    for seccion in moodle._de(5678):
        seccion["modulos"] = []  # el docente la borró en el aula
    segundo, _ = _en(carpeta, moodle, "real")
    nuevo = segundo["ficheros"][0]["cmid"]
    assert nuevo != viejo
    assert not base_vieja.exists()
    assert (_base(carpeta) / "fuente").read_bytes() == (carpeta / "p.md").read_bytes()


def test_la_base_vieja_se_borra_despues_de_guardar_la_nueva(tmp_path, monkeypatch):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    primero, _ = _en(carpeta, moodle, "real")
    viejo = primero["ficheros"][0]["cmid"]
    for seccion in moodle._de(5678):
        seccion["modulos"] = []  # el docente la borró en el aula
    orden = []
    guardar, olvidar = estado.guardar_base, estado.olvidar_base
    monkeypatch.setattr(
        estado, "guardar_base", lambda *a, **k: (orden.append("guardar"), guardar(*a, **k))[1]
    )
    monkeypatch.setattr(
        estado,
        "olvidar_base",
        lambda *a, **k: (orden.append(("olvidar", a[2])), olvidar(*a, **k))[1],
    )
    _en(carpeta, moodle, "real")
    assert orden == ["guardar", ("olvidar", viejo)]


def test_cmid_registrado_con_registro_danado_es_none_y_no_borra_nada(tmp_path):
    carpeta = tmp_path.resolve()
    _pagina_texto(carpeta)
    _en(carpeta, _aula_dos_cursos(), "real")
    dir_tiza = carpeta / ".tiza"
    antes = sorted(p.relative_to(carpeta).as_posix() for p in carpeta.rglob("*"))
    (dir_tiza / "publicados.json").write_text("no es json", encoding="utf-8")
    assert publicacion._cmid_registrado(dir_tiza, 5678, "p.md") is None
    despues = sorted(p.relative_to(carpeta).as_posix() for p in carpeta.rglob("*"))
    assert despues == antes


def test_cmid_registrado_lee_con_la_regla_de_lectura(tmp_path):
    carpeta = tmp_path.resolve()
    _pagina_texto(carpeta)
    dir_tiza = carpeta / ".tiza"
    # Una entrada con «:» ya escrita (0.29.0 en Linux) se sigue leyendo.
    registro = {
        "version": 1,
        "cursos": {
            "5678": {
                "ficheros": {"a:b.md": {"cmid": 7, "tipo": "pagina", "huella": None, "marca": None}}
            }
        },
    }
    dir_tiza.mkdir()
    (dir_tiza / "publicados.json").write_text(json.dumps(registro), encoding="utf-8")
    assert publicacion._cmid_registrado(dir_tiza, 5678, "a:b.md") == 7


@pytest.mark.skipif(sys.platform == "win32", reason="en Windows un fichero no puede llevar «:»")
def test_recrear_una_actividad_registrada_con_dos_puntos_borra_su_base_vieja(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta, fichero="a:b.md")
    dir_tiza = carpeta / ".tiza"
    dir_tiza.mkdir()
    registro = {
        "version": 1,
        "cursos": {
            "5678": {
                "ficheros": {"a:b.md": {"cmid": 7, "tipo": "pagina", "huella": None, "marca": None}}
            }
        },
    }
    (dir_tiza / "publicados.json").write_text(json.dumps(registro), encoding="utf-8")
    estado.guardar_base(dir_tiza, 5678, 7, b"viejo", "viejo")
    _en(carpeta, moodle, "real", ficheros=("a:b.md",))
    assert not estado.ruta_base(dir_tiza, 5678, 7).exists()


def test_renovar_base_de_una_entrada_con_dos_puntos_no_da_registro_no_guardado(tmp_path):
    carpeta = tmp_path.resolve()
    _pagina_texto(carpeta)
    dir_tiza = carpeta / ".tiza"
    dir_tiza.mkdir()
    registro = {"cmid": 7, "tipo": "pagina", "huella": None, "marca": None}
    datos = {"version": 1, "cursos": {"5678": {"ficheros": {"a:b.md": registro}}}}
    (dir_tiza / "publicados.json").write_text(json.dumps(datos), encoding="utf-8")
    doc = contenido.cargar(carpeta / "p.md", raiz=carpeta)
    borrador = informe.Borrador("publicar")
    presencia = PresenciaFalsa()
    huella = "a" * 64
    publicacion._renovar_base_registrada(dir_tiza, 5678, "a:b.md", doc, huella, borrador, presencia)
    assert "REGISTRO_NO_GUARDADO" not in [p.codigo for p in borrador._pasos]
    assert presencia.avisos == []
    assert estado.cargar_publicados(dir_tiza, 5678)["a:b.md"].huella == huella


def test_si_falla_guardar_la_base_no_queda_la_anterior(tmp_path, monkeypatch):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    primero, _ = _en(carpeta, moodle, "real")
    cmid = primero["ficheros"][0]["cmid"]
    assert estado.ruta_base(carpeta / ".tiza", 5678, cmid).is_dir()

    def falla(*_a, **_k):
        raise PermissionError("pasajero")

    monkeypatch.setattr(estado, "guardar_base", falla)
    _pagina_texto(carpeta, texto="Otro texto.")
    segundo, _ = _en(carpeta, moodle, "real")
    assert "BASE_NO_GUARDADA" in [p["codigo"] for p in segundo["pasos"]]
    assert not estado.ruta_base(carpeta / ".tiza", 5678, cmid).exists()


def test_base_que_no_cabe_no_para_la_publicacion(tmp_path, monkeypatch):
    carpeta = tmp_path.resolve()
    monkeypatch.setattr(estado, "MAX_BASE_BYTES", 10)
    _pagina_texto(carpeta)
    documento, _ = _en(carpeta, _aula_dos_cursos(), "real")
    assert documento["errores"] == []
    assert len(documento["ficheros"]) == 1
    [paso] = [p for p in documento["pasos"] if p["codigo"] == "BASE_NO_GUARDADA"]
    assert (paso["resultado"], paso["detalle"]) == ("fallo", "p.md")
    assert not (carpeta / ".tiza" / "publicados").exists()


def test_fichero_cambiado_tras_cargarlo_no_guarda_base(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula_dos_cursos()
    _pagina_texto(carpeta)
    doc = contenido.cargar(carpeta / "p.md", raiz=carpeta)
    registro: dict = {}
    estado.anotar_verificado(registro, contenido.hash_documento(doc), "p.md", 100)
    _pagina_texto(carpeta, texto="Cambiado después de cargarlo.")
    presencia = PresenciaFalsa()
    documento = publicacion.publicar_en_cursos(
        moodle, CFG, [doc], carpeta, presencia, entorno="real", verificados=registro
    )
    assert documento["errores"] == []
    [paso] = [p for p in documento["pasos"] if p["codigo"] == "BASE_NO_GUARDADA"]
    assert (paso["resultado"], paso["detalle"]) == ("fallo", "p.md")
    assert not (carpeta / ".tiza" / "publicados").exists()


def test_publicados_enlazado_no_guarda_base_y_no_escribe_fuera(tmp_path):
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    carpeta = (tmp_path / "asignatura").resolve()
    carpeta.mkdir()
    (carpeta / ".tiza").mkdir()
    enlace_simbolico(carpeta / ".tiza" / "publicados", fuera)
    _pagina_texto(carpeta)
    documento, _ = _en(carpeta, _aula_dos_cursos(), "real")
    assert documento["errores"] == []
    [paso] = [p for p in documento["pasos"] if p["codigo"] == "BASE_NO_GUARDADA"]
    assert (paso["resultado"], paso["detalle"]) == ("fallo", "p.md")
    assert list(fuera.iterdir()) == []


def test_dos_cursos_reales_una_base_por_curso(tmp_path):
    carpeta = tmp_path.resolve()
    _pagina_texto(carpeta)
    _en(carpeta, _aula_varios_cursos(), "real", cfg=CFG_DOS_REALES)
    for curso in (5678, 9999):
        base = _base(carpeta, curso)
        assert (base / "fuente").read_bytes() == (carpeta / "p.md").read_bytes()
    assert len(list((carpeta / ".tiza" / "publicados").iterdir())) == 2


# --- La copia de una sola actividad (``copiar_actividades``) -------------------------------

OTRA = "---\ntipo: pagina\nnombre: Otra cosa\nseccion: 3\n---\n\nTexto.\n"


def _carpeta_con_registro(tmp_path, *, publicadas=("pagina.md", "otra.md")) -> Path:
    """Dos páginas; las ``publicadas`` están en el registro (cmids 601 y 602) y en el aula."""
    carpeta = _carpeta(tmp_path)
    (carpeta / "otra.md").write_text(OTRA, encoding="utf-8")
    for cmid, nombre in ((601, "pagina.md"), (602, "otra.md")):
        if nombre in publicadas:
            estado.guardar_publicado(
                carpeta / ".tiza", 5678, nombre, estado.Publicado(cmid, "pagina", huella=None)
            )
    return carpeta


def _aula_con_paginas() -> MoodleFalso:
    moodle = MoodleFalso()
    moodle.secciones[0]["modulos"] = [
        {"cmid": 601, "nombre": "Repaso", "tipo": "pagina"},
        {"cmid": 602, "nombre": "Otra cosa", "tipo": "pagina"},
    ]
    return moodle


def _copiar_actividades(carpeta, ficheros, moodle=None, presencia=None, cupo=None, **opciones):
    moodle = moodle or _aula_con_paginas()
    presencia = presencia or PresenciaFalsa()
    cupo = cupo if cupo is not None else {"pruebas": 0, "copias": 0, "copias_actividad": 0}
    documento = publicacion.copiar_actividades(
        moodle, CFG, "real", ficheros, carpeta, presencia, cupo, **opciones
    )
    informe.validar(documento)
    return moodle, presencia, documento, cupo


def test_copiar_actividades_hace_una_copia_por_actividad_con_una_confirmacion(tmp_path):
    carpeta = _carpeta_con_registro(tmp_path)
    moodle, presencia, documento, cupo = _copiar_actividades(
        carpeta, ["pagina.md", "otra.md"], nombres={5678: "Mates"}
    )
    assert (documento["resultado"], documento["errores"]) == ("ok", [])
    assert (documento["comando"], documento["entorno"], documento["curso"]) == (
        "copia",
        "real",
        5678,
    )
    assert moodle.copias_de_actividad == [(5678, 601), (5678, 602)]
    [resumen] = presencia.resumenes_copia  # una sola confirmación
    assert resumen.actividades == ("Repaso", "Otra cosa") and resumen.curso == 5678
    assert cupo == {"pruebas": 0, "copias": 0, "copias_actividad": 2}
    assert [c["cmid"] for c in documento["copia"]] == [601, 602]
    guardadas = _copias_guardadas(carpeta)
    assert len(guardadas) == 2 and all(
        re.fullmatch(r"real-c60[12]-\d{8}-\d{4}(-2)?\.mbz", n) for n in guardadas
    )
    for copia in documento["copia"]:
        ruta = carpeta / copia["fichero"]
        assert [a.cmid for a in abrir_copia(ruta).actividades] == [copia["cmid"]]
        assert copia["actividades"] == {"page": 1} and copia["borrada_del_aula"] is True
    assert len(moodle.borradas) == 2 and moodle.copias_en_el_aula == []
    assert [p["codigo"] for p in documento["pasos"]] == [
        "LOGIN",
        "COPIAR",
        "BORRAR_COPIA",
        "COPIAR",
        "BORRAR_COPIA",
    ]


def test_copiar_actividades_por_origen(tmp_path):
    carpeta = _carpeta_con_registro(tmp_path, publicadas=())
    (carpeta / "pagina.md").write_text(
        "---\ntipo: pagina\nnombre: Repaso\nseccion: 3\norigen:\n  curso: 5678\n  cmid: 601\n---\n\nHola.\n",
        encoding="utf-8",
    )
    moodle, _p, documento, _c = _copiar_actividades(carpeta, ["pagina.md"])
    assert documento["resultado"] == "ok" and moodle.copias_de_actividad == [(5678, 601)]


def test_copiar_actividades_dos_ficheros_de_la_misma_actividad_cuentan_una(tmp_path):
    carpeta = _carpeta_con_registro(tmp_path, publicadas=("pagina.md",))
    (carpeta / "copia.md").write_text(
        "---\ntipo: pagina\nnombre: Repaso\nseccion: 3\norigen:\n  curso: 5678\n  cmid: 601\n"
        "---\n\nHola.\n",
        encoding="utf-8",
    )
    moodle, presencia, documento, cupo = _copiar_actividades(carpeta, ["pagina.md", "copia.md"])
    assert (documento["resultado"], documento["errores"]) == ("ok", [])
    assert moodle.copias_de_actividad == [(5678, 601)]
    [resumen] = presencia.resumenes_copia
    assert resumen.actividades == ("Repaso",)
    assert cupo["copias_actividad"] == 1
    repetidos = [p for p in documento["pasos"] if p["codigo"] == "ACTIVIDAD_REPETIDA"]
    assert repetidos == [{"codigo": "ACTIVIDAD_REPETIDA", "resultado": "ok", "detalle": "copia.md"}]


def test_copiar_actividades_sin_registro_no_pide_nada(tmp_path):
    carpeta = _carpeta_con_registro(tmp_path, publicadas=("pagina.md",))
    moodle, presencia, documento, cupo = _copiar_actividades(carpeta, ["pagina.md", "otra.md"])
    assert (documento["resultado"], documento["errores"]) == ("error", ["ACTIVIDAD_SIN_REGISTRO"])
    assert [f["nombre"] for f in documento["ficheros"]] == ["otra.md"]
    assert presencia.resumenes_copia == [] and moodle.copias_de_actividad == []
    assert not any(llamada[0] == "hacer_copia" for llamada in moodle.llamadas)
    assert cupo["copias_actividad"] == 0 and "copia" not in documento
    sin_registro = tmp_path / "x"
    sin_registro.mkdir()
    # Por el nombre sí está en el aula, pero eso no basta: el agente no adivina actividades.
    carpeta = _carpeta_con_registro(sin_registro, publicadas=())
    _m, presencia, documento, _c = _copiar_actividades(carpeta, ["pagina.md"])
    assert documento["errores"] == ["ACTIVIDAD_SIN_REGISTRO"] and presencia.resumenes_copia == []


def test_copiar_actividades_solo_en_cursos_reales(tmp_path):
    carpeta = _carpeta_con_registro(tmp_path)
    moodle = _aula_con_paginas()
    presencia = PresenciaFalsa()
    documento = publicacion.copiar_actividades(
        moodle, CFG, "pruebas", ["pagina.md"], carpeta, presencia, _cupo()
    )
    assert documento["errores"] == ["COPIA_DE_ACTIVIDAD_SOLO_REAL"]
    assert presencia.resumenes_copia == [] and moodle.copias_de_actividad == []


def test_copiar_actividades_cupo_propio(tmp_path):
    carpeta = _carpeta_con_registro(tmp_path)
    cupo = {"pruebas": 0, "copias": 3, "copias_actividad": publicacion.CUPO_COPIAS_ACTIVIDAD - 1}
    moodle, presencia, documento, _ = _copiar_actividades(
        carpeta, ["pagina.md", "otra.md"], cupo=cupo
    )
    assert documento["errores"] == ["CUPO_COPIAS_ACTIVIDAD"]  # el de copias de curso, aparte
    assert presencia.resumenes_copia == [] and moodle.copias_de_actividad == []
    assert cupo["copias_actividad"] == publicacion.CUPO_COPIAS_ACTIVIDAD - 1
    # Una sola sí cabe y no gasta el de los cursos.
    _m, _p, documento, _ = _copiar_actividades(carpeta, ["pagina.md"], cupo=cupo)
    assert documento["resultado"] == "ok"
    assert (cupo["copias"], cupo["copias_actividad"]) == (3, publicacion.CUPO_COPIAS_ACTIVIDAD)
    assert publicacion.CUPO_COPIAS_ACTIVIDAD == 20


def test_copiar_actividades_cupo_se_rechaza_antes_de_leer_el_aula(tmp_path):
    carpeta = _carpeta_con_registro(tmp_path)
    cupo = {"pruebas": 0, "copias": 0, "copias_actividad": publicacion.CUPO_COPIAS_ACTIVIDAD - 1}
    moodle, _p, documento, _ = _copiar_actividades(carpeta, ["pagina.md", "otra.md"], cupo=cupo)
    assert documento["errores"] == ["CUPO_COPIAS_ACTIVIDAD"]
    assert not any(llamada[0] == "estructura" for llamada in moodle.llamadas)


def test_copiar_actividades_el_docente_dice_que_no(tmp_path):
    carpeta = _carpeta_con_registro(tmp_path)
    moodle, presencia, documento, cupo = _copiar_actividades(
        carpeta, ["pagina.md"], presencia=PresenciaFalsa(copia=False)
    )
    assert (documento["resultado"], documento["errores"]) == ("abortado", ["COPIA_RECHAZADA"])
    assert len(presencia.resumenes_copia) == 1 and moodle.copias_de_actividad == []
    assert cupo["copias_actividad"] == 0 and _copias_guardadas(carpeta) == []


def test_copiar_actividades_con_otra_actividad_en_la_copia_se_borra_del_aula(tmp_path):
    from dobles import copia_sintetica_de_actividad

    carpeta = _carpeta_con_registro(tmp_path)
    moodle = _aula_con_paginas()
    moodle.copia = copia_sintetica_de_actividad(999)  # no es la 601 que se pidió
    _m, _p, documento, _c = _copiar_actividades(carpeta, ["pagina.md"], moodle)
    assert (documento["resultado"], documento["errores"]) == ("error", ["COPIA_NO_VALIDA"])
    assert "copia" not in documento and _copias_guardadas(carpeta) == []
    assert moodle.copias_en_el_aula == [] and len(moodle.borradas) == 1


def test_copiar_actividades_si_una_falla_se_para_y_las_hechas_quedan(tmp_path):
    from dobles import copia_sintetica_de_actividad

    carpeta = _carpeta_con_registro(tmp_path)

    class _SegundaMala(MoodleFalso):
        def hacer_copia(self, curso_id, destino, maximo, cmid=None):
            if cmid == 602:
                self.copia = copia_sintetica_de_actividad(999)
            return super().hacer_copia(curso_id, destino, maximo, cmid)

    moodle = _SegundaMala()
    moodle.secciones[0]["modulos"] = _aula_con_paginas().secciones[0]["modulos"]
    _m, _p, documento, cupo = _copiar_actividades(carpeta, ["pagina.md", "otra.md"], moodle)
    assert documento["errores"] == ["COPIA_NO_VALIDA"]
    assert [c["cmid"] for c in documento["copia"]] == [601]  # la primera quedó y se dice
    assert len(_copias_guardadas(carpeta)) == 1 and moodle.copias_en_el_aula == []
    assert cupo["copias_actividad"] == 2


def test_copiar_actividades_ruta_fuera_de_la_carpeta(tmp_path):
    carpeta = _carpeta_con_registro(tmp_path)
    fuera = tmp_path.parent / "fuera.md"
    fuera.write_text(PAGINA, encoding="utf-8")
    _m, presencia, documento, _c = _copiar_actividades(carpeta, ["../fuera.md"])
    assert documento["errores"] == ["RUTA_FUERA_DE_CARPETA"] and presencia.resumenes_copia == []
