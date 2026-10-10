"""Tests de la publicación como proceso (tiza.publicacion).

Las reglas que comparten la terminal directa y la sesión (puertas, resúmenes,
confirmaciones y registro por curso) se prueban a través de ``procesar_peticion``
en test_sesion.py; aquí van las decisiones explícitas de cada llamador: el
registro de verificados, la vigencia de la petición, el cupo, el aviso de
pruebas y los cursos ya descartados.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dobles import MoodleFalso, PresenciaFalsa
from tiza import config, contenido, publicacion, publicar

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
    return {contenido.hash_documento(doc): {"nombre": "pagina.md", "cmid": 100}}


def test_puerta_real_con_registro_en_memoria_ignora_el_disco(tmp_path):
    carpeta = _carpeta(tmp_path)
    doc = _documentos(carpeta)[0]
    publicar.guardar_verificado(tmp_path / ".tiza", contenido.hash_documento(doc), "pagina.md", 7)
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
