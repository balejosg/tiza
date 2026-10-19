"""Tests de la publicación como proceso (tiza.publicacion).

Las reglas que comparten la terminal directa y la sesión (puertas, resúmenes,
confirmaciones y registro por curso) se prueban a través de
``SesionAbierta.atender`` en test_sesion_abierta.py; aquí van las decisiones
explícitas de cada llamador: el registro de verificados, la vigencia de la
petición, el cupo, el aviso de pruebas, los cursos ya descartados y los cambios
de fechas de la confirmación.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from dobles import (
    MoodleFalso,
    PresenciaFalsa,
    aula_con_tarea,
    copia_sintetica,
    enlace_simbolico,
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
            c.campo: c for c in publicacion.cambios_de_fechas(moodle, moodle.secciones, doc, None)
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
            c.campo: c for c in publicacion.cambios_de_fechas(moodle, moodle.secciones, doc, None)
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
        cambios = publicacion.cambios_de_fechas(moodle, moodle.secciones, doc, None)
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
        cambios = publicacion.cambios_de_fechas(moodle, moodle.secciones, doc, None)
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
    assert documento["copia"] == {
        "curso": "pruebas",
        "fichero": ".tiza/copias/pruebas-20261019-1030.mbz",
        "bytes": ruta.stat().st_size,
        "actividades": {"assign": 1, "forum": 1, "label": 1, "page": 1},
        "borrada_del_aula": True,
    }
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
    assert documento["copia"]["borrada_del_aula"] is True
    assert "COPIA_QUEDA_EN_EL_AULA" not in presencia.codigos()
    # Si no se puede borrar, la copia sigue siendo buena: se avisa y se dice en el informe.
    moodle = MoodleFalso()
    moodle.borrar_copia_falla = True
    _moodle, presencia, documento = _copiar(tmp_path, moodle)
    assert documento["resultado"] == "ok" and documento["errores"] == []
    assert documento["copia"]["borrada_del_aula"] is False
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
        assert documento["copia"]["curso"] == nombre
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
    assert documento["copia"]["fichero"] == ".tiza/copias/pruebas-20261019-1030-2.mbz"
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


def _fichero_importado(carpeta: Path, nombre="importada.md", titulo="Nuevo", cmid=501) -> None:
    (carpeta / nombre).write_text(
        f"---\ntipo: pagina\nnombre: {titulo}\nseccion: 2\n"
        f"origen:\n  curso: 5678\n  cmid: {cmid}\n---\n\nTexto nuevo.\n",
        encoding="utf-8",
    )


def _fichero_normal(carpeta: Path, nombre="otra.md") -> None:
    (carpeta / nombre).write_text(
        "---\ntipo: pagina\nnombre: Otra\nseccion: 3\n---\n\nOtra página.\n", encoding="utf-8"
    )


def _escribir_copia(carpeta: Path, huella: str | None, curso=5678, cmid=501) -> None:
    """``copia.json`` con una actividad del curso ``curso``, importada con esa huella."""
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
        ("importada.md", 501, "actualizada")
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


def test_sin_copia_json_se_publica_por_origen_y_se_dice(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    moodle = _aula_importada()
    documento = _publicar_real(carpeta, moodle, ["importada.md"])
    assert documento["errores"] == []
    assert {"codigo": "ORIGEN_SIN_HUELLA", "resultado": "ok", "detalle": "importada.md"} in (
        documento["pasos"]
    )
    assert [f["cmid"] for f in documento["ficheros"]] == [501]
    assert not (carpeta / ".tiza" / "copia.json").exists()  # no se inventa una entrada


def test_actividad_sin_huella_se_publica_y_queda_protegida_despues(tmp_path):
    carpeta = tmp_path.resolve()
    _fichero_importado(carpeta)
    _escribir_copia(carpeta, None)
    moodle = _aula_importada()
    documento = _publicar_real(carpeta, moodle, ["importada.md"])
    assert documento["errores"] == []
    assert "ORIGEN_SIN_HUELLA" in [p["codigo"] for p in documento["pasos"]]
    assert 501 in estado.huellas_de_copia(carpeta / ".tiza", 5678)


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
    assert publicacion.codigo_solo_fechas(secciones, [doc], 5678) is None
    assert publicacion.codigo_solo_fechas(secciones, [doc], 1234) == "MODULO_AUSENTE"
    secciones[0]["modulos"][0]["cmid"] = 602
    assert publicacion.codigo_solo_fechas(secciones, [doc], 5678) == "ORIGEN_NO_ENCONTRADO"
