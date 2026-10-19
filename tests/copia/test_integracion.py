"""Importar -> publicar, de punta a punta y offline.

Une las dos mitades que los demás tests prueban por separado: ``tiza importar`` calcula la huella
del aula desde una copia sintética y ``tiza publicar`` la compara con un aula falsa cuyo
formulario devuelve lo que daría Moodle (URL ``draftfile.php`` para los ficheros, fechas en hora
de Madrid calculadas aparte con ``zoneinfo``). Si alguien cambia ``tipos.huella_aula`` y rompe
solo una mitad, falla aquí.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from copia import fabrica as f
from dobles import MoodleFalso, PresenciaFalsa, fecha_en_formulario
from tiza import agente, config, contenido, estado, publicacion, tipos

MADRID = ZoneInfo("Europe/Madrid")
PNG = b"\x89PNG\r\n\x1a\n" + b"datos de una imagen"
CURSO = 3
APERTURA = 1792447200  # segundos, en UTC
ENTREGA = 1795215540
CFG = config.Config(
    url="https://aula.example.org/centro", usuario="profe", cursos={}, reales=(CURSO,)
)
BORRADOR = "https://aula.example.org/centro/draftfile.php/5/user/draft/1792999999"


@pytest.fixture(autouse=True)
def _sin_aula_configurada(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")


# Los textos tal como los serializa tiza (atributos en orden, «/>» y un salto de línea final): es
# lo que hay en el aula cuando la actividad la publicó tiza, y entonces las tres huellas
# coinciden. Con el HTML de otro editor la de la copia y la de lo enviado difieren, y la primera
# publicación se acepta por la primera.
_HTML_DE_LA_PAGINA = '<p>Mira <img alt="foto" src="@@PLUGINFILE@@/foto.png"/></p>\n'
_HTML_DE_LA_TAREA = "<p>Haz esto</p>\n"
_HTML_DE_LA_ETIQUETA = "<p>Aviso</p>\n"


def _tupla_de_madrid(segundos: int) -> tuple[int, int, int, int, int]:
    """El instante en la hora de Madrid, calculado aparte de tiza."""
    m = datetime.fromtimestamp(segundos, MADRID)
    return (m.year, m.month, m.day, m.hour, m.minute)


def _actividades() -> list[f.ActividadFalsa]:
    return [
        f.ActividadFalsa(
            501,
            "page",
            7,
            "Una página",
            _HTML_DE_LA_PAGINA,
            ficheros=[f.FicheroFalso("foto.png", PNG)],
        ),
        f.ActividadFalsa(
            502,
            "assign",
            7,
            "Entrega",
            _HTML_DE_LA_TAREA,
            fechas={"allowsubmissionsfromdate": APERTURA, "duedate": ENTREGA, "cutoffdate": 0},
        ),
        f.ActividadFalsa(503, "label", 7, "Una etiqueta", _HTML_DE_LA_ETIQUETA),
    ]


def _aula_como_la_copia() -> MoodleFalso:
    """El curso real con las tres actividades, como las devolvería el formulario de edición."""
    moodle = MoodleFalso(
        secciones_por_curso={
            CURSO: [
                {
                    "numero": 2,
                    "nombre": "Tema 1: Intro",
                    "id": 20,
                    "modulos": [
                        {"cmid": 501, "nombre": "Una página", "tipo": "pagina"},
                        {"cmid": 502, "nombre": "Entrega", "tipo": "tarea"},
                        {"cmid": 503, "nombre": "Una etiqueta", "tipo": "etiqueta"},
                    ],
                }
            ]
        }
    )
    moodle.formularios[501] = {
        "visible": "1",
        "name": "Una página",
        "page[text]": _HTML_DE_LA_PAGINA.replace("@@PLUGINFILE@@", BORRADOR),
    }
    moodle.formularios[502] = {
        "visible": "1",
        "name": "Entrega",
        "introeditor[text]": _HTML_DE_LA_TAREA,
        **fecha_en_formulario("allowsubmissionsfromdate", _tupla_de_madrid(APERTURA)),
        **fecha_en_formulario("duedate", _tupla_de_madrid(ENTREGA)),
    }
    moodle.formularios[503] = {
        "visible": "1",
        "name": "Una etiqueta",
        "introeditor[text]": _HTML_DE_LA_ETIQUETA,
    }
    return moodle


@pytest.fixture
def carpeta(tmp_path):
    asignatura = (tmp_path / "asignatura").resolve()
    asignatura.mkdir()
    (asignatura / "tiza.toml").write_text(f"[cursos]\nreal = {CURSO}\n", encoding="utf-8")
    secciones = [f.SeccionFalsa(id=7, numero=2, nombre="Tema 1: Intro")]
    f.escribir_mbz(asignatura / "copia.mbz", secciones, _actividades(), curso=CURSO)
    agente.importar("copia.mbz", asignatura)
    return asignatura


def _ficheros(carpeta: Path) -> list[str]:
    datos = estado.cargar_copia(carpeta / ".tiza")
    actividades = datos["cursos"][str(CURSO)]["actividades"]
    return [a["fichero"] for a in sorted(actividades, key=lambda a: a["cmid"])]


def _publicar(carpeta: Path, moodle, ficheros: list[str], presencia=None) -> dict:
    documentos = [contenido.cargar(carpeta / ruta, raiz=carpeta) for ruta in ficheros]
    return publicacion.publicar_en_cursos(
        moodle,
        CFG,
        documentos,
        carpeta,
        presencia or PresenciaFalsa(),
        entorno="real",
        visible=False,
    )


def test_la_huella_es_la_misma_en_la_copia_el_formulario_y_lo_enviado(carpeta):
    moodle = _aula_como_la_copia()
    guardadas = estado.huellas_de_copia(carpeta / ".tiza", CURSO)
    assert set(guardadas) == {501, 502, 503}
    for cmid, ruta in zip((501, 502, 503), _ficheros(carpeta), strict=True):
        doc = contenido.cargar(carpeta / ruta, raiz=carpeta)
        tipo = tipos.obtener(doc.tipo)
        del_formulario = tipos.huella_del_formulario(tipo, doc, moodle.leer_modulo(cmid))
        # Lo que se envía lleva el mismo nombre del aula (el fichero no lo cambió).
        enviada = tipos.huella_de_lo_enviado(tipo, doc, contenido.html_para_moodle(doc))
        assert guardadas[cmid] == del_formulario == enviada, doc.tipo


def test_dos_pasadas_sin_cambios_no_dan_cambiada_en_el_aula(carpeta):
    moodle = _aula_como_la_copia()
    ficheros = _ficheros(carpeta)
    for _pasada in range(2):
        documento = _publicar(carpeta, moodle, ficheros)
        assert documento["errores"] == [], documento
        assert [(x["cmid"], x["accion"]) for x in documento["ficheros"]] == [
            (501, "actualizada"),
            (502, "actualizada"),
            (503, "actualizada"),
        ]
    assert not any(c[0] == "crear" for c in moodle.llamadas)


def test_un_cambio_en_el_aula_salta_solo_en_su_actividad(carpeta):
    moodle = _aula_como_la_copia()
    moodle.formularios[501]["page[text]"] = "<p>Lo cambió el docente en el aula</p>"
    presencia = PresenciaFalsa()
    documento = _publicar(carpeta, moodle, _ficheros(carpeta), presencia)
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert sorted(x["cmid"] for x in documento["ficheros"]) == [502, 503]
    assert moodle.formularios[501]["page[text]"] == "<p>Lo cambió el docente en el aula</p>"
    assert "CAMBIADA_EN_EL_AULA" in presencia.codigos()


def test_cambiar_la_entrega_en_el_aula_salta_en_la_tarea(carpeta):
    moodle = _aula_como_la_copia()
    moodle.formularios[502].update(
        fecha_en_formulario("duedate", _tupla_de_madrid(ENTREGA + 86400))
    )
    documento = _publicar(carpeta, moodle, _ficheros(carpeta))
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert sorted(x["cmid"] for x in documento["ficheros"]) == [501, 503]


def test_juntar_el_cambio_y_publicar_de_punta_a_punta(carpeta):
    """Cambio en el aula -> copia nueva -> importar -> sin juntar no se publica -> juntado, sí."""
    moodle = _aula_como_la_copia()
    ficheros = _ficheros(carpeta)
    # El docente cambia el texto de la etiqueta en el aula; llega una copia nueva.
    moodle.formularios[503]["introeditor[text]"] = "<p>Aviso nuevo</p>\n"
    actividades = _actividades()
    actividades[2].html = "<p>Aviso nuevo</p>\n"
    secciones = [f.SeccionFalsa(id=7, numero=2, nombre="Tema 1: Intro")]
    f.escribir_mbz(carpeta / "copia2.mbz", secciones, actividades, curso=CURSO)
    resumen = agente.importar("copia2.mbz", carpeta)
    assert resumen.estados["CAMBIADA_DESDE_LA_IMPORTACION"] == 1
    assert (carpeta / ".tiza" / "copia" / "503.html").read_text(encoding="utf-8") == (
        "<p>Aviso nuevo</p>\n"
    )
    # Sin juntar: se publica lo demás, no la etiqueta (el fichero sigue como se marcó).
    documento = _publicar(carpeta, moodle, ficheros)
    assert documento["errores"] == ["CAMBIADA_EN_EL_AULA"]
    assert sorted(x["cmid"] for x in documento["ficheros"]) == [501, 502]
    assert moodle.formularios[503]["introeditor[text]"] == "<p>Aviso nuevo</p>\n"
    # El docente junta los cambios en su fichero: ahora se publica con normalidad.
    ruta = carpeta / ficheros[2]
    ruta.write_text(
        ruta.read_text(encoding="utf-8").replace("Aviso", "Aviso (juntado)"), encoding="utf-8"
    )
    documento = _publicar(carpeta, moodle, ficheros)
    assert documento["errores"] == [], documento
    assert sorted(x["cmid"] for x in documento["ficheros"]) == [501, 502, 503]
    assert "Aviso (juntado)" in moodle.formularios[503]["introeditor[text]"]
    assert estado.marcas_de_copia(carpeta / ".tiza", CURSO) == {}
