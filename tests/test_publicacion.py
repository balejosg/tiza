"""Tests de la publicación como proceso (tiza.publicacion).

Las reglas que comparten la terminal directa y la sesión (puertas, resúmenes,
confirmaciones y registro por curso) se prueban a través de
``SesionAbierta.atender`` en test_sesion_abierta.py; aquí van las decisiones
explícitas de cada llamador: el registro de verificados, la vigencia de la
petición, el cupo, el aviso de pruebas, los cursos ya descartados y los cambios
de fechas de la confirmación.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from dobles import (
    MoodleFalso,
    PresenciaFalsa,
    aula_con_tarea,
    fecha_en_formulario,
    tarea_en,
)
from tiza import calendario, config, contenido, estado, publicacion, publicar

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
