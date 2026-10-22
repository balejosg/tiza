"""Tests offline de la publicación: payloads, orquestación y puerta de CI."""

from __future__ import annotations

import re
import types
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest
import requests
from py_moodle.auth import LoginError
from py_moodle.draftfile import MoodleDraftFileError
from py_moodle.module import MoodleModuleError
from py_moodle.session import MoodleSessionError

from dobles import MoodleFalso, aula_con_tarea, fecha_en_formulario, tarea_en
from tiza import config, contenido, publicar, tipos
from tiza.publicar import ErrorPublicacion


def documento(tmp_path, cuerpo="Contenido de prueba"):
    ruta = tmp_path / "pagina.md"
    ruta.write_text(
        "---\ntipo: pagina\nnombre: Repaso\nseccion: 3\n---\n\n" + cuerpo + "\n",
        encoding="utf-8",
    )
    return contenido.cargar(ruta)


def documento_con_imagen(tmp_path):
    (tmp_path / "img").mkdir(exist_ok=True)
    (tmp_path / "img" / "foto.png").write_bytes(b"png")
    ruta = tmp_path / "pagina.md"
    ruta.write_text(
        "---\ntipo: pagina\nnombre: Repaso\nseccion: 3\n---\n\n![foto](img/foto.png)\n",
        encoding="utf-8",
    )
    return contenido.cargar(ruta)


def etiqueta(tmp_path, cuerpo="Texto de la etiqueta"):
    ruta = tmp_path / "etiqueta.md"
    ruta.write_text(
        "---\ntipo: etiqueta\nnombre: Bienvenida\nseccion: 3\n---\n\n" + cuerpo + "\n",
        encoding="utf-8",
    )
    return contenido.cargar(ruta)


class TestEtiqueta:
    def test_payload_etiqueta(self, tmp_path):
        payload = publicar.payload_etiqueta(etiqueta(tmp_path), "@@PLUGINFILE@@/f.png", 7, False)
        assert payload["_qf__mod_label_mod_form"] == "1"
        assert payload["name"] == "Bienvenida"
        assert payload["introeditor[text]"] == "@@PLUGINFILE@@/f.png"
        assert payload["introeditor[itemid]"] == "7"
        assert payload["introeditor[format]"] == "1"
        assert payload["visible"] == "0"
        assert "submitbutton2" in payload

    def test_publica_una_etiqueta_nueva_oculta_y_la_verifica(self, tmp_path):
        moodle = MoodleFalso()
        resultado = publicar.publicar_documento(
            moodle, 1234, moodle.secciones, etiqueta(tmp_path), visible=None
        )
        assert (resultado.tipo, resultado.accion, resultado.oculto) == (
            "etiqueta",
            "creada",
            True,
        )
        assert resultado.url.endswith("/mod/label/view.php?id=100")
        crear = next(llamada for llamada in moodle.llamadas if llamada[0] == "crear")
        assert crear[3] == "etiqueta"

    def test_republicar_una_etiqueta_la_actualiza(self, tmp_path):
        moodle = MoodleFalso()
        doc = etiqueta(tmp_path)
        publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=None)
        repetido = publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=None)
        assert (repetido.accion, repetido.cmid) == ("actualizada", 100)

    def test_etiqueta_con_imagen_comprueba_mod_label(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "foto.png").write_bytes(b"png")
        doc = etiqueta(tmp_path, "![foto](img/foto.png)")
        moodle = MoodleFalso()
        publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=None)
        assert moodle.pluginfiles == [
            "https://aula.example.org/centro/pluginfile.php/999/mod_label/intro/foto.png"
        ]


class TestPayloads:
    def test_payload_pagina(self, tmp_path):
        doc = documento(tmp_path)
        payload = publicar.payload_pagina(doc, "@@PLUGINFILE@@/f.png", 123, False)
        assert payload["name"] == "Repaso"
        assert payload["page[text]"] == "@@PLUGINFILE@@/f.png"
        assert payload["page[itemid]"] == "123"
        assert payload["page[format]"] == "1"
        assert payload["visible"] == "0"
        assert payload["_qf__mod_page_mod_form"] == "1"

    def test_payload_pagina_visible(self, tmp_path):
        doc = documento(tmp_path)
        payload = publicar.payload_pagina(doc, "html", 1, True)
        assert payload["visible"] == "1"

    def test_payload_tarea_fechas(self, tmp_path):
        ruta = tmp_path / "tarea.md"
        ruta.write_text(
            "---\ntipo: tarea\nnombre: Problemas\nseccion: 3\n"
            "apertura: 2026-10-01\nentrega: 2026-10-10\nlimite: 2026-10-15\n---\n\nResuelve.\n",
            encoding="utf-8",
        )
        doc = contenido.cargar(ruta)
        payload = publicar.payload_tarea(doc, "@@PLUGINFILE@@/f.png", 55, False)
        assert payload["name"] == "Problemas"
        assert payload["introeditor[text]"] == "@@PLUGINFILE@@/f.png"
        assert payload["introeditor[itemid]"] == "55"
        assert payload["introattachments"] == "55"
        assert payload["allowsubmissionsfromdate[day]"] == "1"
        assert payload["duedate[month]"] == "10"
        assert payload["duedate[year]"] == "2026"
        assert payload["cutoffdate[enabled]"] == "1"
        assert payload["cutoffdate[day]"] == "15"
        assert payload["gradingduedate[enabled]"] == "0"
        assert payload["visible"] == "0"
        assert payload["_qf__mod_assign_mod_form"] == "1"

    def test_payload_tarea_sin_limite_desactiva(self, tmp_path):
        ruta = tmp_path / "tarea.md"
        ruta.write_text(
            "---\ntipo: tarea\nnombre: Problemas\nseccion: 3\n"
            "apertura: 2026-10-01\nentrega: 2026-10-10\n---\n\nResuelve.\n",
            encoding="utf-8",
        )
        doc = contenido.cargar(ruta)
        payload = publicar.payload_tarea(doc, "html", 55, False)
        assert payload["cutoffdate[enabled]"] == "0"
        assert payload["gradingduedate[enabled]"] == "0"


class TestPublicarDocumento:
    def test_crea_y_verifica(self, tmp_path):
        doc = documento_con_imagen(tmp_path)
        moodle = MoodleFalso()
        resultado = publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=False)
        assert resultado.accion == "creada"
        assert resultado.cmid == 100
        assert resultado.oculto is True
        assert resultado.seccion == "Tema 3"
        assert resultado.url.endswith("/mod/page/view.php?id=100")
        assert resultado.hash == contenido.hash_documento(doc)
        operaciones = [llamada[0] for llamada in moodle.llamadas]
        assert operaciones[:4] == [
            "contexto",
            "subir",
            "crear",
            "leer_modulo",
        ]
        assert any(
            llamada[0] == "pluginfile" and "@@PLUGINFILE@@" not in llamada[1]
            for llamada in moodle.llamadas
        )

    def test_actualiza_mismo_cmid(self, tmp_path):
        doc = documento(tmp_path)
        secciones = [
            {
                "numero": 3,
                "nombre": "Tema 3",
                "id": 30,
                "modulos": [{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}],
            }
        ]
        moodle = MoodleFalso(secciones=secciones)
        resultado = publicar.publicar_documento(moodle, 1234, secciones, doc, visible=True)
        assert resultado.accion == "actualizada"
        assert resultado.cmid == 55
        assert resultado.oculto is False
        operaciones = [llamada[0] for llamada in moodle.llamadas]
        assert "actualizar" in operaciones
        assert "crear" not in operaciones

    def test_seccion_ausente_falla(self, tmp_path):
        doc = documento(tmp_path)
        secciones = [{"numero": 1, "nombre": "General", "id": 10, "modulos": []}]
        moodle = MoodleFalso(secciones=secciones)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(moodle, 1234, secciones, doc, visible=False)
        assert exc.value.codigo == "SECCION_AUSENTE"

    def test_verificacion_sin_el_recurso_falla(self, tmp_path):
        doc = documento_con_imagen(tmp_path)
        moodle = MoodleFalso()
        moodle.leer_modulo = lambda cmid: {
            "nombre": doc.nombre,
            "texto": "<p>otra cosa</p>",
            "instance": 77,
            "visible": False,
            "contexto": 999,
        }
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=False)
        assert exc.value.codigo == "VERIFICACION_TEXTO"

    def test_pluginfile_que_no_da_200_falla(self, tmp_path):
        doc = documento_con_imagen(tmp_path)
        moodle = MoodleFalso(pluginfiles_ok=False)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=False)
        assert exc.value.codigo == "VERIFICACION_FICHERO"


class TestAutoprueba:
    def test_autoprueba_completa(self):
        moodle = MoodleFalso()
        resultado = publicar.autoprueba(moodle, 1234)
        assert resultado["resultado"] == "ok"
        codigos = [paso.codigo for paso in resultado["pasos"]]
        assert "PUBLICAR_PAGINA" in codigos
        assert "PUBLICAR_TAREA" in codigos
        assert "VERIFICAR_FECHAS" in codigos
        assert "REPUBLICAR_PAGINA" in codigos
        assert "PUBLICAR_CUESTIONARIO" in codigos
        assert "REPUBLICAR_CUESTIONARIO" in codigos
        assert "PUBLICAR_ETIQUETA" in codigos
        assert "REPUBLICAR_ETIQUETA" in codigos
        assert "PUBLICAR_H5P" in codigos
        assert "REPUBLICAR_H5P" in codigos
        assert "VERIFICAR_CATEGORIA" in codigos
        assert codigos[-4:] == ["ORDENAR", "MOVER_SECCION", "BORRAR_SECCION", "LIMPIAR"]
        assert resultado["errores"] == []
        borrados = [llamada for llamada in moodle.llamadas if llamada[0] == "borrar"]
        assert len(borrados) == 5
        assert moodle.secciones[0]["modulos"] == []

    def test_la_autoprueba_ordena_y_mueve_de_seccion_sin_duplicar_ni_dejar_nada(self):
        moodle = MoodleFalso()
        resultado = publicar.autoprueba(moodle, 1234)
        assert resultado["resultado"] == "ok"
        movimientos = [ll for ll in moodle.llamadas if ll[0] == "mover"]
        assert len(movimientos) >= 3  # intercambio, ida a la sección temporal y vuelta
        # La página no se duplicó: se crearon exactamente los cinco módulos de los ejemplos.
        assert len([ll for ll in moodle.llamadas if ll[0] == "crear"]) == 5
        assert [s["numero"] for s in moodle.secciones] == [3]  # la temporal se borró

    def test_si_mover_falla_la_autoprueba_lo_dice_y_no_deja_nada(self):
        moodle = MoodleFalso()
        moodle.mover_falla = True
        resultado = publicar.autoprueba(moodle, 1234)
        assert resultado["resultado"] == "error"
        assert resultado["errores"] == ["ERROR_MOVER"]
        codigos = [(p.codigo, p.resultado) for p in resultado["pasos"]]
        assert ("ORDENAR", "fallo") in codigos
        assert moodle.secciones[0]["modulos"] == []
        assert [s["numero"] for s in moodle.secciones] == [3]  # tampoco la sección temporal

    def test_un_aula_que_no_ordena_se_detecta(self):
        moodle = MoodleFalso()
        moodle.mover_sin_efecto = True
        resultado = publicar.autoprueba(moodle, 1234)
        assert resultado["errores"] == ["ORDEN_NO_APLICADO"]

    def test_la_autoprueba_avisa_si_el_aula_no_dibuja_formulas(self):
        resultado = publicar.autoprueba(MoodleFalso(motor_formulas=False), 1234)
        assert resultado["resultado"] == "ok"
        assert "FORMULAS_NO_DIBUJADAS" in [paso.codigo for paso in resultado["pasos"]]
        sin_aviso = publicar.autoprueba(MoodleFalso(), 1234)
        assert "FORMULAS_NO_DIBUJADAS" not in [paso.codigo for paso in sin_aviso["pasos"]]

    def test_la_autoprueba_detecta_una_categoria_que_no_es_la_del_modulo(self):
        class MoodleConOtroContexto(MoodleFalso):
            def leer_modulo(self, cmid):
                info = super().leer_modulo(cmid)
                info["contexto"] = 999  # el del curso, no el del módulo
                return info

        moodle = MoodleConOtroContexto()
        resultado = publicar.autoprueba(moodle, 1234)
        assert "VERIFICACION_PREGUNTAS" in resultado["errores"]
        assert [paso.codigo for paso in resultado["pasos"]][-2] == "VERIFICAR_CATEGORIA"
        assert moodle.secciones[0]["modulos"] == []  # limpió los cinco módulos

    def test_la_autoprueba_detecta_que_el_banco_no_tiene_las_preguntas(self):
        class MoodleConBancoVacio(MoodleFalso):
            def preguntas_en_categoria(self, cmid, categoria):
                return set()

        resultado = publicar.autoprueba(MoodleConBancoVacio(), 1234)
        assert "VERIFICACION_PREGUNTAS" in resultado["errores"]

    def test_autoprueba_limpia_tras_fallar(self):
        class MoodleQueFalla(MoodleFalso):
            def crear(self, curso_id, seccion_id, tipo, payload):
                if tipo == "tarea":
                    raise ErrorPublicacion("ERROR_CREACION")
                return super().crear(curso_id, seccion_id, tipo, payload)

        moodle = MoodleQueFalla()
        resultado = publicar.autoprueba(moodle, 1234)
        assert resultado["resultado"] == "error"
        assert "ERROR_CREACION" in resultado["errores"]
        borrados = [llamada for llamada in moodle.llamadas if llamada[0] == "borrar"]
        assert borrados and borrados[0][1] == 100
        assert moodle.secciones[0]["modulos"] == []


class TestAutenticacion:
    def test_login_fallido(self, monkeypatch):
        def falla(*args, **kwargs):
            raise LoginError("usuario o contraseña incorrectos")

        monkeypatch.setattr(publicar.py_auth, "login", falla)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.autenticar("https://aula.example.org/centro", "profe", "secreta")
        assert exc.value.codigo == "LOGIN_FALLIDO"

    def test_sesion_sin_sesskey(self, monkeypatch):
        class SesionSinSesskey:
            pass

        monkeypatch.setattr(publicar.py_auth, "login", lambda *a, **k: SesionSinSesskey())
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.autenticar("https://aula.example.org/centro", "profe", "secreta")
        assert exc.value.codigo == "SESION_SIN_SESSKEY"

    def test_sesion_no_iniciada(self, monkeypatch):
        def falla(*args, **kwargs):
            raise MoodleSessionError("sin token ni sesskey")

        monkeypatch.setattr(publicar.py_auth, "login", falla)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.autenticar("https://aula.example.org/centro", "profe", "secreta")
        assert exc.value.codigo == "SESION_NO_INICIADA"

    def test_login_una_sola_vez(self, monkeypatch):
        class SesionFalsa:
            sesskey = "clave"

        llamadas = []

        def login(*args, **kwargs):
            llamadas.append(args)
            return SesionFalsa()

        monkeypatch.setattr(publicar.py_auth, "login", login)
        publicar.autenticar("https://aula.example.org/centro", "profe", "secreta")
        assert len(llamadas) == 1

    def test_descarta_el_token(self, monkeypatch):
        class SesionFalsa:
            sesskey = "clave"
            webservice_token = "token-que-no-se-usa"

        monkeypatch.setattr(publicar.py_auth, "login", lambda *a, **k: SesionFalsa())
        moodle = publicar.autenticar("https://aula.example.org/centro", "profe", "secreta")
        assert moodle.sesion.webservice_token is None


class TestSesionSoloHaciaElAula:
    def test_la_sesion_del_aula_monta_la_guardia_en_http_y_https(self):
        from py_moodle import auth as py_auth

        sesion = py_auth.MoodleAuth("https://aula.ejemplo.org/centro", "u", "p").session
        for url in ("https://aula.ejemplo.org/", "http://aula.ejemplo.org/"):
            assert isinstance(sesion.get_adapter(url), config.AdaptadorAula)

    def test_la_guardia_de_la_sesion_fija_el_servidor_del_login(self, monkeypatch):
        from py_moodle import auth as py_auth

        enviadas: list[str] = []

        def enviar(self, request, *args, **opciones):
            enviadas.append(request.url)
            respuesta = requests.Response()
            respuesta.status_code = 200
            respuesta.url = request.url
            respuesta.request = request
            return respuesta

        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", enviar)
        sesion = py_auth.MoodleAuth("https://aula.ejemplo.org/centro", "u", "p").session
        sesion.get("https://aula.ejemplo.org/otra")
        with pytest.raises(config.DestinoNoPermitido):
            sesion.get("https://evil.example/robo")
        assert enviadas == ["https://aula.ejemplo.org/otra"]

    def test_un_bloqueo_envuelto_por_python_moodle_tambien_se_reduce(self):
        """python-moodle envuelve los errores de requests en los suyos: ``raise X(f"…{e}")``."""
        moodle = publicar.Moodle("https://aula", object(), "clave", pausa=0)

        def subir():
            try:
                raise config.DestinoNoPermitido("no")
            except requests.RequestException as e:
                raise MoodleDraftFileError(f"Failed to upload file to draft area: {e}")  # noqa: B904

        with pytest.raises(ErrorPublicacion) as exc:
            moodle._reducir("ERROR_SUBIDA", subir)
        assert exc.value.codigo == "DESTINO_NO_PERMITIDO"

    def test_autenticar_reconoce_un_bloqueo_envuelto(self, monkeypatch):
        def login(*_args, **_opciones):
            try:
                raise config.DestinoNoPermitido("no")
            except requests.RequestException as e:
                raise MoodleSessionError(f"sin sesión: {e}")  # noqa: B904

        monkeypatch.setattr(publicar.py_auth, "login", login)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.autenticar("https://aula.ejemplo.org/centro", "profe", "secreta")
        assert exc.value.codigo == "DESTINO_NO_PERMITIDO"

    def test_un_destino_ajeno_a_mitad_de_sesion_se_reduce_a_su_codigo(self):
        moodle = publicar.Moodle("https://aula", object(), "clave", pausa=0)

        def sale_fuera():
            raise config.DestinoNoPermitido("no")

        with pytest.raises(ErrorPublicacion) as exc:
            moodle._reducir("ERROR_CONSULTA", sale_fuera)
        assert exc.value.codigo == "DESTINO_NO_PERMITIDO"


class TestAdapterReduceErrores:
    def test_no_propaga_texto_de_moodle(self, monkeypatch):
        def falla(*args, **kwargs):
            raise MoodleModuleError('Fallo <div class="moodle">resp.text secreto</div>')

        monkeypatch.setattr(publicar.py_module, "add_generic_module", falla)
        moodle = publicar.Moodle("https://aula.example.org/centro", object(), "clave")
        with pytest.raises(ErrorPublicacion) as exc:
            moodle.crear(1, 2, "pagina", {"name": "x"})
        assert exc.value.codigo == "ERROR_CREACION"
        assert "moodle" not in (exc.value.detalle or "")
        assert "resp.text" not in (exc.value.detalle or "")


def test_crear_modulo_no_lista_todos_los_cursos(monkeypatch):
    from py_moodle import course as py_course
    from py_moodle import module as py_module

    def no_listar(*a, **k):
        raise AssertionError("no se deben listar todos los cursos")

    monkeypatch.setattr(py_course, "list_courses", no_listar)
    monkeypatch.setattr(
        py_course,
        "get_course",
        lambda *a, **k: [
            {
                "id": 30,
                "section": 3,
                "name": "Tema 3",
                "modules": [{"id": 7, "name": "A", "modname": "page"}],
            }
        ],
    )
    datos = py_module.get_course_with_sections_and_modules(None, "https://x", "k", 838)
    assert datos["sections"][0]["id"] == 30
    assert datos["sections"][0]["section"] == 3
    assert datos["sections"][0]["modules"][0]["id"] == 7


def test_autoprueba_borra_el_modulo_que_no_se_verifica():
    class MoodleSinFicheros(MoodleFalso):
        def comprobar_pluginfile(self, url):
            # La página se verifica; la tarea no.
            return "/mod_page/" in url

    moodle = MoodleSinFicheros()
    resultado = publicar.autoprueba(moodle, 1234)
    assert "VERIFICACION_FICHERO" in resultado["errores"]
    borrados = [llamada[1] for llamada in moodle.llamadas if llamada[0] == "borrar"]
    assert len(borrados) == 2
    assert moodle.secciones[0]["modulos"] == []


def test_urls_pluginfile_de_tarea_sin_instancia():
    urls = publicar.urls_pluginfile("https://aula", 5, "tarea", 77, "punto.png")
    assert urls == [
        "https://aula/pluginfile.php/5/mod_assign/intro/punto.png",
        "https://aula/pluginfile.php/5/mod_assign/introattachment/0/punto.png",
    ]


def test_urls_pluginfile_de_etiqueta_sin_itemid():
    urls = publicar.urls_pluginfile("https://aula", 5, "etiqueta", 77, "punto.png")
    assert urls == ["https://aula/pluginfile.php/5/mod_label/intro/punto.png"]


def test_url_de_una_etiqueta_es_su_modulo():
    assert (
        publicar.url_modulo("https://aula", "etiqueta", 9) == "https://aula/mod/label/view.php?id=9"
    )


def test_estructura_ajax_reconoce_la_etiqueta(monkeypatch):
    estado = [
        {
            "id": 30,
            "section": 1,
            "name": "Proyecto",
            "modules": [{"id": 57078, "name": "Bienvenida", "module": "label"}],
        }
    ]
    monkeypatch.setattr(publicar.py_course, "get_course", lambda *a, **k: estado)
    moodle = publicar.Moodle("https://aula", object(), "clave", pausa=0)
    assert moodle.estructura(838)[0]["modulos"] == [
        {"cmid": 57078, "nombre": "Bienvenida", "tipo": "etiqueta"}
    ]


def test_borrar_usa_ajax_con_el_curso_conocido():
    enviados = []

    class Respuesta:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"error": False, "data": "[]"}]

    class Sesion:
        def post(self, url, json=None, timeout=None):
            enviados.append((url, json))
            return Respuesta()

    moodle = publicar.Moodle("https://aula", Sesion(), "clave", pausa=0)
    moodle.borrar(838, 57073)
    url, payload = enviados[0]
    assert "core_courseformat_update_course" in url
    assert payload[0]["args"] == {"action": "cm_delete", "courseid": "838", "ids": ["57073"]}


def test_borrar_rechazado_da_codigo():
    class Respuesta:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"error": True, "exception": {"message": "x"}}]

    class Sesion:
        def post(self, url, json=None, timeout=None):
            return Respuesta()

    moodle = publicar.Moodle("https://aula", Sesion(), "clave", pausa=0)
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.borrar(838, 1)
    assert exc.value.codigo == "ERROR_BORRADO"


def test_estructura_ajax_reconoce_el_tipo_por_module(monkeypatch):
    estado = [
        {
            "id": 30,
            "section": 0,
            "name": "General",
            "modules": [{"id": 57073, "name": "Repaso", "module": "page", "modname": "Página"}],
        }
    ]
    monkeypatch.setattr(publicar.py_course, "get_course", lambda *a, **k: estado)
    moodle = publicar.Moodle("https://aula", object(), "clave", pausa=0)
    modulos = moodle.estructura(838)[0]["modulos"]
    assert modulos == [{"cmid": 57073, "nombre": "Repaso", "tipo": "pagina"}]


class _Respuesta:
    def __init__(self, status_code, location=""):
        self.status_code = status_code
        self.headers = {"Location": location}


class _SesionMuerta:
    def __init__(self, viva):
        self.viva = viva

    def get(self, url, allow_redirects=True, timeout=None):
        if self.viva:
            return _Respuesta(200)
        return _Respuesta(303, "https://aula/login/index.php")


def _falla_moodle(*a, **k):
    from py_moodle.course import MoodleCourseError

    raise MoodleCourseError("texto del aula")


def test_error_con_sesion_caducada_da_sesion_caducada(monkeypatch):
    monkeypatch.setattr(publicar.py_course, "get_course", _falla_moodle)
    moodle = publicar.Moodle("https://aula", _SesionMuerta(viva=False), "clave", pausa=0)
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.estructura(838)
    assert exc.value.codigo == "SESION_CADUCADA"


def test_error_con_sesion_viva_conserva_el_codigo(monkeypatch):
    monkeypatch.setattr(publicar.py_course, "get_course", _falla_moodle)
    moodle = publicar.Moodle("https://aula", _SesionMuerta(viva=True), "clave", pausa=0)
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.estructura(838)
    assert exc.value.codigo == "ERROR_ESTRUCTURA"


def _doc_en(tmp_path, seccion, nombre="pagina.md"):
    ruta = tmp_path / nombre
    ruta.write_text(
        f'---\ntipo: pagina\nnombre: {nombre}\nseccion: "{seccion}"\n---\n\nTexto.\n',
        encoding="utf-8",
    )
    return contenido.cargar(ruta)


class TestSeccionesPorNombre:
    def test_crea_una_vez_la_seccion_que_falta_y_publica_en_ella(self, tmp_path):
        moodle = MoodleFalso()
        docs = [_doc_en(tmp_path, "Fracciones", "a.md"), _doc_en(tmp_path, "fracciones", "b.md")]
        secciones, creadas = publicar.asegurar_secciones(
            moodle, 1234, moodle.estructura(1234), docs
        )
        assert creadas == ["Fracciones"]
        assert [l for l in moodle.llamadas if l[0] == "crear_seccion"] == [
            ("crear_seccion", 1234, "Fracciones")
        ]
        resultado = publicar.publicar_documento(moodle, 1234, secciones, docs[0], visible=False)
        assert resultado.seccion == "Fracciones"

    def test_existente_no_se_crea(self, tmp_path):
        moodle = MoodleFalso()
        _, creadas = publicar.asegurar_secciones(
            moodle, 1234, moodle.estructura(1234), [_doc_en(tmp_path, "tema 3")]
        )
        assert creadas == []

    def test_seccion_que_no_aparece_tras_crearla(self, tmp_path):
        class MoodleQueNoCrea(MoodleFalso):
            def crear_seccion(self, curso_id, nombre):
                return 1

        moodle = MoodleQueNoCrea()
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.asegurar_secciones(
                moodle, 1234, moodle.estructura(1234), [_doc_en(tmp_path, "Nueva")]
            )
        assert exc.value.codigo == "SECCION_NO_CREADA"

    def test_autoprueba_crea_y_borra_una_seccion(self):
        moodle = MoodleFalso()
        resultado = publicar.autoprueba(moodle, 1234)
        assert resultado["errores"] == []
        codigos = [paso.codigo for paso in resultado["pasos"]]
        assert "CREAR_SECCION" in codigos and "BORRAR_SECCION" in codigos
        assert [s["nombre"] for s in moodle.secciones] == ["Tema 3"]


class _SesionAjax:
    def __init__(self):
        self.acciones = []
        self.renombrado_ok = True

    def post(self, url, json=None, timeout=None):
        args = json[0]["args"]
        if json[0]["methodname"] == "core_update_inplace_editable":
            self.acciones.append(
                f"{args['component']}:{args['itemtype']}:{args['itemid']}:{args['value']}"
            )
            return _RespuestaAjax(self.renombrado_ok)
        self.acciones.append(args["action"])
        return _RespuestaAjax()


class _RespuestaAjax:
    def __init__(self, ok=True):
        self.ok = ok

    def raise_for_status(self):
        pass

    def json(self):
        return [{"error": not self.ok, "data": "[]"}]


class TestCrearSeccionReal:
    def test_crea_renombra_y_oculta(self, monkeypatch):
        sesion = _SesionAjax()
        monkeypatch.setattr(
            publicar.py_section, "create_section", lambda *a, **k: {"fields": {"id": 555}}
        )
        moodle = publicar.Moodle("https://aula", sesion, "clave", pausa=0)
        moodle.formato_curso = lambda curso_id: "onetopic"
        assert moodle.crear_seccion(838, "Fracciones") == 555
        assert sesion.acciones == ["format_onetopic:sectionname:555:Fracciones", "section_hide"]

    def test_si_no_se_puede_renombrar_la_borra(self, monkeypatch):
        sesion = _SesionAjax()
        monkeypatch.setattr(
            publicar.py_section, "create_section", lambda *a, **k: {"fields": {"id": 555}}
        )

        sesion.renombrado_ok = False
        moodle = publicar.Moodle("https://aula", sesion, "clave", pausa=0)
        moodle.formato_curso = lambda curso_id: "topics"
        moodle.sesion_viva = lambda: True
        with pytest.raises(ErrorPublicacion) as exc:
            moodle.crear_seccion(838, "Fracciones")
        assert exc.value.codigo == "SECCION_SIN_NOMBRE"
        assert sesion.acciones == ["format_topics:sectionname:555:Fracciones", "section_delete"]


def test_estructura_ajax_reconoce_el_cuestionario(monkeypatch):
    estado = [
        {
            "id": 30,
            "section": 1,
            "name": "Proyecto",
            "modules": [{"id": 57078, "name": "Repaso", "module": "quiz"}],
        }
    ]
    monkeypatch.setattr(publicar.py_course, "get_course", lambda *a, **k: estado)
    moodle = publicar.Moodle("https://aula", object(), "clave", pausa=0)
    assert moodle.estructura(838)[0]["modulos"] == [
        {"cmid": 57078, "nombre": "Repaso", "tipo": "cuestionario"}
    ]


def test_estructura_ajax_convierte_los_ids_a_entero(monkeypatch):
    estado = [
        {
            "id": "30",
            "section": 1,
            "name": "Proyecto",
            "modules": [{"id": "57078", "name": "Tarea", "module": "assign"}],
        }
    ]
    monkeypatch.setattr(publicar.py_course, "get_course", lambda *a, **k: estado)
    moodle = publicar.Moodle("https://aula", object(), "clave", pausa=0)
    seccion = moodle.estructura(838)[0]
    assert seccion["id"] == 30
    assert seccion["modulos"] == [{"cmid": 57078, "nombre": "Tarea", "tipo": "tarea"}]


def test_estructura_limpia_los_nombres_de_seccion(monkeypatch):
    estado = [
        {"id": 30, "section": 1, "name": "Tema <1>\x07  repaso", "modules": []},
        {"id": None, "section": 2, "name": "Sin id", "modules": []},
    ]
    monkeypatch.setattr(publicar.py_course, "get_course", lambda *a, **k: estado)
    moodle = publicar.Moodle("https://aula", object(), "clave", pausa=0)
    assert [seccion["nombre"] for seccion in moodle.estructura(838)] == ["Tema ‹1› repaso"]


@pytest.mark.parametrize(
    "html, formato",
    [
        (
            '<html><body id="page-course-view" class="format-onetopic path-course limitedwidth">',
            "onetopic",
        ),
        ("<body class='path-course format-weeks'>", "weeks"),
        ('<body class="path-course">', "topics"),
        ("", "topics"),
    ],
)
def test_formato_de_html(html, formato):
    assert publicar.formato_de_html(html) == formato


def test_login_no_envia_la_contrasena_a_token_php(monkeypatch):
    """El parche de publicar.py debe actuar dentro de login(), no solo existir."""
    from py_moodle import auth as py_auth

    enviados: list[tuple[str, str]] = []

    class Respuesta:
        status_code = 200
        url = "https://aula.example.org/centro/my/"
        text = ""

        def json(self):
            return {"token": "no-deberia-pedirse"}

    class Version:
        raw = "4.1"
        source = "prueba"

    class Estrategia:
        version_range = "4.x"

    class Contexto:
        strategy = Estrategia()
        version = Version()

    def peticion(self, metodo, url, *args, **kwargs):  # ninguna petición sale a la red
        enviados.append((metodo.upper(), url))
        return Respuesta()

    monkeypatch.setattr(py_auth.requests.Session, "request", peticion)
    monkeypatch.setattr(py_auth.MoodleAuth, "_standard_login", lambda self: None)
    monkeypatch.setattr(py_auth.MoodleAuth, "_get_sesskey", lambda self: "clave")
    monkeypatch.setattr(py_auth, "detect_moodle_compatibility", lambda *a, **k: Contexto())
    py_auth.login("https://aula.example.org/centro", "profe", "secreta")
    assert not any("token.php" in url for _metodo, url in enviados)


def test_el_user_agent_identifica_a_tiza():
    from py_moodle import auth as py_auth

    from tiza import __version__

    asistente = py_auth.MoodleAuth("https://aula.example.org/centro", "u", "p")
    assert asistente.session.headers["User-Agent"].startswith(f"tiza/{__version__} ")


def test_un_recurso_cambiado_tras_cargar_no_se_publica(tmp_path):
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "a.png").write_bytes(b"original")
    md = tmp_path / "p.md"
    md.write_text(
        "---\ntipo: pagina\nnombre: P\nseccion: 1\n---\n\n![a](img/a.png)\n", encoding="utf-8"
    )
    doc = contenido.cargar(md)
    (tmp_path / "img" / "a.png").write_bytes(b"sustituido")
    moodle = MoodleFalso()
    with pytest.raises(ErrorPublicacion) as exc:
        publicar.publicar_documento(
            moodle, 1, [{"numero": 1, "nombre": "T", "id": 9, "modulos": []}], doc, visible=False
        )
    assert exc.value.codigo == "FICHERO_MODIFICADO"


class _RespuestaJson:
    status_code = 200
    headers: dict = {}

    def __init__(self, datos):
        self._datos = datos

    def raise_for_status(self):
        pass

    def json(self):
        return self._datos


class _SesionCursos:
    def __init__(self, datos):
        self.datos = datos
        self.posts: list = []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return _RespuestaJson(self.datos)

    def get(self, url, allow_redirects=True, timeout=None):
        return _RespuestaJson({})  # sesion_viva(): sin redirección al login


def test_mis_cursos_reduce_y_ordena():
    sesion = _SesionCursos(
        [
            {
                "error": False,
                "data": {
                    "courses": [
                        {"id": 5678, "fullname": "Matemáticas 2ºB", "summary": "<p>x</p>"},
                        {"id": "1234", "fullname": "Ensayo &amp; pruebas"},
                        {"id": None, "fullname": "roto"},
                    ]
                },
            }
        ]
    )
    moodle = publicar.Moodle("https://aula.example.org/c", sesion, "sk", pausa=0)
    assert moodle.mis_cursos() == [
        {"id": 1234, "nombre": "Ensayo & pruebas"},
        {"id": 5678, "nombre": "Matemáticas 2ºB"},
    ]
    url, payload = sesion.posts[0]
    assert "core_course_get_enrolled_courses_by_timeline_classification" in url
    assert payload[0]["args"]["classification"] == "all"


def test_mis_cursos_rechazado_da_codigo():
    sesion = _SesionCursos([{"error": True, "exception": {"message": "<b>texto de Moodle</b>"}}])
    moodle = publicar.Moodle("https://aula.example.org/c", sesion, "sk", pausa=0)
    with pytest.raises(publicar.ErrorPublicacion) as exc:
        moodle.mis_cursos()
    assert exc.value.codigo == "ERROR_CURSOS"
    assert "Moodle" not in str(exc.value)


def _cursos_desde(datos):
    sesion = _SesionCursos(datos)
    return publicar.Moodle("https://aula.example.org/c", sesion, "sk", pausa=0)


def test_mis_cursos_usa_shortname_si_falta_fullname():
    moodle = _cursos_desde(
        [{"error": False, "data": {"courses": [{"id": 7, "shortname": "MAT2B"}]}}]
    )
    assert moodle.mis_cursos() == [{"id": 7, "nombre": "MAT2B"}]


def test_mis_cursos_sin_nombre_usa_curso_id():
    moodle = _cursos_desde([{"error": False, "data": {"courses": [{"id": 7}]}}])
    assert moodle.mis_cursos() == [{"id": 7, "nombre": "Curso 7"}]


@pytest.mark.parametrize("cuerpo", [{}, {"courses": []}])
def test_mis_cursos_sin_cursos_da_lista_vacia(cuerpo):
    assert _cursos_desde([{"error": False, "data": cuerpo}]).mis_cursos() == []


def test_mis_cursos_error_ausente_falla_cerrado():
    with pytest.raises(publicar.ErrorPublicacion) as exc:
        _cursos_desde([{"data": {"courses": []}}]).mis_cursos()
    assert exc.value.codigo == "ERROR_CURSOS"


@pytest.mark.parametrize(
    "datos",
    [
        ["x"],  # datos[0] no es diccionario
        [{"error": False, "data": "texto"}],  # data no es diccionario
        [{"error": False, "data": {"courses": 5}}],  # courses no es lista
    ],
)
def test_mis_cursos_forma_inesperada_da_codigo(datos):
    with pytest.raises(publicar.ErrorPublicacion) as exc:
        _cursos_desde(datos).mis_cursos()
    assert exc.value.codigo == "ERROR_CURSOS"
    assert "Moodle" not in str(exc.value)


def test_mis_cursos_ignora_elementos_que_no_son_diccionario():
    moodle = _cursos_desde(
        [
            {
                "error": False,
                "data": {
                    "courses": [
                        123,
                        {"id": True, "fullname": "Booleano"},
                        {"id": 1, "fullname": "Uno"},
                    ]
                },
            }
        ]
    )
    assert moodle.mis_cursos() == [{"id": 1, "nombre": "Uno"}]


FORMULARIO_TAREA = """
<html><body>
<form action="https://aula/course/modedit.php" method="post">
<input type="hidden" name="instance" value="77">
<input type="text" name="name" value="Problemas">
<textarea name="introeditor[text]">Resuelve.</textarea>
<select name="visible"><option value="1">Mostrar</option><option value="0" selected>Ocultar</option></select>
<input type="checkbox" name="duedate[enabled]" value="1" checked>
<select name="duedate[day]"><option value="1">1</option><option value="10" selected>10</option></select>
<select name="duedate[month]"><option value="10" selected>octubre</option></select>
<select name="duedate[year]"><option value="2026" selected>2026</option></select>
<select name="duedate[hour]"><option value="23" selected>23</option></select>
<select name="duedate[minute]"><option value="59" selected>59</option></select>
<input type="hidden" name="cutoffdate[enabled]" value="0">
<input type="checkbox" name="cutoffdate[enabled]" value="1">
<select name="cutoffdate[day]"><option value="15" selected>15</option></select>
<select name="cutoffdate[month]"><option value="10" selected>octubre</option></select>
<select name="cutoffdate[year]"><option value="2026" selected>2026</option></select>
<select name="cutoffdate[hour]"><option value="23" selected>23</option></select>
<select name="cutoffdate[minute]"><option value="59" selected>59</option></select>
</form>
<script>M.cfg = {"contextid": 999};</script>
</body></html>
"""


class _SesionFormulario:
    def __init__(self, texto):
        self.texto = texto

    def get(self, url, **kwargs):
        return _RespuestaFormulario(self.texto)


class _RespuestaFormulario:
    status_code = 200

    def __init__(self, texto):
        self.text = texto

    def raise_for_status(self):
        pass


def test_leer_modulo_lee_fechas_casillas_y_visibilidad():
    moodle = publicar.Moodle("https://aula", _SesionFormulario(FORMULARIO_TAREA), "clave", pausa=0)
    info = moodle.leer_modulo(5)
    assert info["nombre"] == "Problemas"
    assert info["visible"] == "0"
    assert info["contexto"] == 999
    assert info["fechas"] == {
        "allowsubmissionsfromdate": None,  # no está en el formulario
        "duedate": (2026, 10, 10, 23, 59),
        "cutoffdate": None,  # casilla sin marcar, aunque haya un oculto con su nombre
        "gradingduedate": None,
        "timeopen": None,  # campos de un cuestionario
        "timeclose": None,
    }


def test_leer_modulo_trae_el_area_de_archivos_adicionales_de_una_tarea():
    con_area = FORMULARIO_TAREA.replace(
        '<input type="hidden" name="instance" value="77">',
        '<input type="hidden" name="instance" value="77">'
        '<input type="hidden" name="introattachments" value="123456789">',
    )
    moodle = publicar.Moodle("https://aula", _SesionFormulario(con_area), "clave", pausa=0)
    assert moodle.leer_modulo(5)["adjuntos"] == 123456789
    sin_area = publicar.Moodle(
        "https://aula", _SesionFormulario(FORMULARIO_TAREA), "clave", pausa=0
    )
    assert sin_area.leer_modulo(5)["adjuntos"] is None
    raro = con_area.replace("123456789", "no-es-un-numero")
    assert (
        publicar.Moodle("https://aula", _SesionFormulario(raro), "clave", pausa=0).leer_modulo(5)[
            "adjuntos"
        ]
        is None
    )


def test_autoprueba_detecta_fechas_que_el_aula_no_aplica():
    class MoodleQueRedondea(MoodleFalso):
        def leer_modulo(self, cmid):
            info = super().leer_modulo(cmid)
            entrega = info["fechas"]["duedate"]
            if entrega is not None:  # desplegable de minutos de 5 en 5
                info["fechas"]["duedate"] = (*entrega[:4], 55)
            return info

    moodle = MoodleQueRedondea()
    resultado = publicar.autoprueba(moodle, 1234)
    assert "FECHAS_NO_APLICADAS" in resultado["errores"]
    assert moodle.secciones[0]["modulos"] == []  # limpia igualmente


def _seccion_con_repaso():
    return [
        {
            "numero": 3,
            "nombre": "Tema 3",
            "id": 30,
            "modulos": [{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}],
        }
    ]


class TestVisibilidad:
    def test_sin_indicar_el_payload_no_la_toca(self, tmp_path):
        doc = documento(tmp_path)
        assert "visible" not in publicar.payload_pagina(doc, "html", 1, None)

    def test_republicar_sin_indicar_conserva_lo_visible(self, tmp_path):
        doc = documento(tmp_path)
        secciones = _seccion_con_repaso()
        moodle = MoodleFalso(secciones=secciones)
        resultado = publicar.publicar_documento(moodle, 1234, secciones, doc, visible=None)
        payload = next(llamada[2] for llamada in moodle.llamadas if llamada[0] == "actualizar")
        assert "visible" not in payload
        assert resultado.oculto is False

    def test_crear_sin_indicar_lo_crea_oculto(self, tmp_path):
        doc = documento(tmp_path)
        moodle = MoodleFalso()
        resultado = publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=None)
        payload = next(llamada[4] for llamada in moodle.llamadas if llamada[0] == "crear")
        assert payload["visible"] == "0"
        assert resultado.oculto is True

    def test_oculto_explicito_oculta_lo_existente(self, tmp_path):
        doc = documento(tmp_path)
        secciones = _seccion_con_repaso()
        moodle = MoodleFalso(secciones=secciones)
        resultado = publicar.publicar_documento(moodle, 1234, secciones, doc, visible=False)
        assert resultado.oculto is True

    def test_autoprueba_detecta_que_no_se_conserva(self):
        class MoodleQueMuestra(MoodleFalso):
            def actualizar(self, cmid, payload):
                super().actualizar(cmid, {**payload, "visible": "1"})

        resultado = publicar.autoprueba(MoodleQueMuestra(), 1234)
        assert "VISIBILIDAD_NO_CONSERVADA" in resultado["errores"]


class _SesionQueAnota:
    def __init__(self, texto=""):
        self.texto = texto
        self.llamadas: list = []
        self.ultima = None

    def get(self, url, **kwargs):
        self.llamadas.append((url, kwargs))
        self.ultima = _RespuestaQueSeCierra(self.texto)
        return self.ultima


class _RespuestaQueSeCierra:
    status_code = 200

    def __init__(self, texto):
        self.text = texto
        self.cerrada = False

    def raise_for_status(self):
        pass

    def close(self):
        self.cerrada = True


def test_lecturas_del_aula_con_plazo_y_sin_descargar_ficheros():
    sesion = _SesionQueAnota('<form action="modedit.php"><input name="name" value="P"></form>')
    moodle = publicar.Moodle("https://aula", sesion, "clave", pausa=0)
    moodle.leer_modulo(5)
    assert moodle.comprobar_pluginfile("https://aula/pluginfile.php/1/mod_page/content/7/a.png")
    assert all(kwargs.get("timeout") == publicar.TIEMPO_ESPERA for _url, kwargs in sesion.llamadas)
    assert sesion.llamadas[-1][1].get("stream") is True
    assert sesion.ultima.cerrada is True


def test_imagenes_de_pregunta_cuenta_las_servidas_con_plazo():
    class Sesion(_SesionQueAnota):
        def get(self, url, **kwargs):
            self.llamadas.append((url, kwargs))
            if "preview.php" in url:
                return _RespuestaQueSeCierra(
                    '<div class="que"><img src="/pluginfile.php/5/question/a.png">'
                    '<img src="/pluginfile.php/5/question/b.png"><img src="/theme/icono.png"></div>'
                )
            respuesta = _RespuestaQueSeCierra("")
            respuesta.status_code = 404 if url.endswith("b.png") else 200
            return respuesta

    sesion = Sesion("")
    moodle = publicar.Moodle("https://aula", sesion, "c", pausa=0)
    assert moodle.imagenes_de_pregunta(7, 99) == (2, 1)
    assert all(kwargs.get("timeout") == publicar.TIEMPO_ESPERA for _u, kwargs in sesion.llamadas)
    assert "preview.php" in sesion.llamadas[0][0]


def test_motor_de_formulas_es_una_regla_estructural_con_plazo():
    con = publicar.Moodle(
        "https://aula",
        _SesionQueAnota("<script>filter_mathjaxloader/loader</script>"),
        "c",
        pausa=0,
    )
    sin = publicar.Moodle("https://aula", _SesionQueAnota("<p>nada</p>"), "c", pausa=0)
    assert con.motor_de_formulas(2) is True
    assert sin.motor_de_formulas(2) is False
    assert con.sesion.llamadas[-1][1]["timeout"] == publicar.TIEMPO_ESPERA


class TestYaExiste:
    def test_documento_nuevo(self, tmp_path):
        doc = documento(tmp_path)
        secciones = [{"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []}]
        assert publicar.ya_existe(secciones, doc) is False

    def test_mismo_tipo_y_nombre_en_su_seccion(self, tmp_path):
        doc = documento(tmp_path)
        secciones = [
            {
                "numero": 3,
                "nombre": "Tema 3",
                "id": 30,
                "modulos": [{"cmid": 100, "nombre": "Repaso", "tipo": "pagina"}],
            }
        ]
        assert publicar.ya_existe(secciones, doc) is True

    def test_otro_tipo_u_otro_nombre_no_cuenta(self, tmp_path):
        doc = documento(tmp_path)
        secciones = [
            {
                "numero": 3,
                "nombre": "Tema 3",
                "id": 30,
                "modulos": [
                    {"cmid": 100, "nombre": "Repaso", "tipo": "tarea"},
                    {"cmid": 101, "nombre": "Otro", "tipo": "pagina"},
                ],
            }
        ]
        assert publicar.ya_existe(secciones, doc) is False

    def test_si_la_seccion_no_existe_es_nuevo(self, tmp_path):
        doc = documento(tmp_path)
        assert publicar.ya_existe([{"numero": 4, "nombre": "T", "id": 40}], doc) is False

    def test_estructura_incompleta_no_se_puede_saber(self, tmp_path):
        doc = documento(tmp_path)
        assert publicar.ya_existe([{"numero": 3, "nombre": "Tema 3", "id": 30}], doc) is None
        assert publicar.ya_existe(None, doc) is None


def test_el_doble_y_el_adaptador_cumplen_la_misma_interfaz():
    import inspect

    metodos = [
        nombre
        for nombre, valor in vars(publicar.AulaVirtual).items()
        if callable(valor) and not nombre.startswith("_")
    ]
    assert "leer_modulo" in metodos and "mis_cursos" in metodos
    assert "categoria_cuestionario" in metodos and "huecos" in metodos
    for nombre in metodos:
        esperado = list(inspect.signature(getattr(publicar.AulaVirtual, nombre)).parameters)
        for clase in (publicar.Moodle, MoodleFalso):
            obtenido = list(inspect.signature(getattr(clase, nombre)).parameters)
            assert obtenido == esperado, (clase.__name__, nombre)


# --------------------------------------------------------------------------- #
# Cuestionarios: adaptador real y doble
# --------------------------------------------------------------------------- #

FORMULARIO_MODEDIT_QUIZ = """
<html><body>
<form action="https://aula/centro/course/modedit.php" method="post">
<input type="hidden" name="instance" value="77">
<input type="text" name="name" value="Repaso">
<textarea name="introeditor[text]">Descripción</textarea>
</form>
<script>M.cfg = {"contextid": 444};</script>
</body></html>
"""

FORMULARIO_IMPORTACION = """
<html><body>
<form action="https://aula/centro/question/bank/importquestions/import.php?cmid=5" method="post">
<input type="hidden" name="sesskey" value="clave">
<input type="hidden" name="newfile" value="1234">
<select name="category">
<option value="1,999">Curso</option>
<option value="2,444" selected>Cuestionario</option>
</select>
<select name="format"><option value="xml">XML</option></select>
</form>
</body></html>
"""

HTML_HUECOS = """
<div id="slot-1">
<a href="https://aula/centro/question/previewquestion/preview.php?id=501">ver</a>
</div>
<div id="slot-2">
<a href="https://aula/centro/question/editquestion/question.php?cmid=5&amp;id=502">editar</a>
</div>
"""

FORMULARIO_CONFIRMAR_BORRADO = """
<html><body>
<form action="https://aula/centro/question/bank/deletequestion/delete.php" method="post">
<input type="hidden" name="sesskey" value="clave">
<input type="hidden" name="confirm" value="abc123">
<input type="hidden" name="deleteselected" value="501,502">
<input type="submit" name="submitbutton" value="Sí">
</form>
</body></html>
"""


class _Rq:
    def __init__(self, texto="", status_code=200, url="https://aula/centro/x.php", datos=None):
        self.text = texto
        self.status_code = status_code
        self.url = url
        self._datos = datos

    def raise_for_status(self):
        pass

    def json(self):
        if self._datos is None:
            raise ValueError("sin JSON")
        return self._datos


class _SesionQuiz:
    """Sesión falsa que sirve las páginas de los métodos de cuestionario."""

    def __init__(self):
        self.paginas: dict[str, object] = {}
        self.posts_guion: list[_Rq] = []
        self.banco: list[set[int]] = []
        self.gets: list[tuple] = []
        self.posts: list[tuple] = []

    def respuesta(self, clave: str, valor) -> None:
        self.paginas[clave] = valor

    def get(self, url, params=None, **kwargs):
        self.gets.append((url, params))
        if "question/edit.php" in url and self.banco:
            ids = self.banco.pop(0)
            return _Rq("".join(f'<input type="checkbox" name="q{i}">' for i in sorted(ids)))
        for clave, valor in self.paginas.items():
            if clave in url:
                return valor if isinstance(valor, _Rq) else _Rq(str(valor))
        return _Rq("")

    def post(self, url, data=None, json=None, timeout=None, allow_redirects=False):
        self.posts.append((url, data))
        if self.posts_guion:
            return self.posts_guion.pop(0)
        return _Rq("", status_code=303)


def _moodle_de_cuestionario(sesion: _SesionQuiz) -> publicar.Moodle:
    return publicar.Moodle("https://aula/centro", sesion, "clave", pausa=0)


class TestAdaptadorCuestionario:
    def test_categoria_cuestionario_elige_la_del_modulo(self):
        sesion = _SesionQuiz()
        sesion.respuesta("modedit.php", FORMULARIO_MODEDIT_QUIZ)
        sesion.respuesta("importquestions", FORMULARIO_IMPORTACION)
        assert _moodle_de_cuestionario(sesion).categoria_cuestionario(5) == "2,444"

    def test_categoria_sin_contexto_falla(self):
        sesion = _SesionQuiz()
        sesion.respuesta("modedit.php", "<form action='modedit.php'></form>")
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_cuestionario(sesion).categoria_cuestionario(5)
        assert exc.value.codigo == "ERROR_IMPORTACION"

    def test_categoria_sin_opcion_del_contexto_falla(self):
        sesion = _SesionQuiz()
        sesion.respuesta("modedit.php", FORMULARIO_MODEDIT_QUIZ)
        sesion.respuesta(
            "importquestions",
            '<form action="x"><input name="newfile" value="1">'
            '<select name="category"><option value="1,999">Curso</option></select></form>',
        )
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_cuestionario(sesion).categoria_cuestionario(5)
        assert exc.value.codigo == "ERROR_IMPORTACION"

    def test_preguntas_en_categoria_lee_los_ids(self):
        sesion = _SesionQuiz()
        sesion.banco = [{501, 502, 0}]
        assert _moodle_de_cuestionario(sesion).preguntas_en_categoria(5, "2,444") == {
            501,
            502,
            0,
        }
        url, params = sesion.gets[-1]
        assert params["cat"] == "2,444" and params["qperpage"] == 1000

    def test_importar_preguntas_sube_en_la_categoria_y_con_matchgrades(self, monkeypatch):
        sesion = _SesionQuiz()
        sesion.banco = [{500}, {500, 501}]
        sesion.respuesta("importquestions", FORMULARIO_IMPORTACION)
        monkeypatch.setattr(
            publicar.py_draftfile,
            "upload_file_to_draft_area",
            lambda *a, **k: (1234, "preguntas.xml"),
        )
        monkeypatch.setattr(publicar.py_course, "get_course_context_id", lambda *a, **k: 444)
        sesion.posts_guion = [_Rq("question/edit.php", status_code=200)]
        ids = _moodle_de_cuestionario(sesion).importar_preguntas(838, 5, "2,444", b"<quiz></quiz>")
        assert ids == [501]
        _url, datos = sesion.posts[0]
        campos = dict(datos)
        assert campos["format"] == "xml"
        assert campos["matchgrades"] == "error"
        assert campos["category"] == "2,444"
        assert campos["newfile"] == "1234"

    def test_importar_preguntas_sin_formulario_falla(self):
        sesion = _SesionQuiz()
        sesion.banco = [set()]
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_cuestionario(sesion).importar_preguntas(838, 5, "2,444", b"<quiz/>")
        assert exc.value.codigo == "ERROR_IMPORTACION"

    def test_anadir_preguntas_conserva_el_orden_dado(self):
        sesion = _SesionQuiz()
        _moodle_de_cuestionario(sesion).anadir_preguntas(5, [7, 5, 9])
        _url, datos = sesion.posts[0]
        assert [campo for campo, _valor in datos if campo.startswith("q")] == [
            "q7",
            "q5",
            "q9",
        ]
        assert dict(datos)["add"] == "1" and dict(datos)["cmid"] == "5"

    def test_anadir_preguntas_sin_redireccion_falla(self):
        sesion = _SesionQuiz()
        sesion.posts_guion = [_Rq("<html>error</html>", status_code=200)]
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_cuestionario(sesion).anadir_preguntas(5, [7])
        assert exc.value.codigo == "ERROR_ANADIR_PREGUNTAS"

    def test_huecos_lee_los_pares_en_orden(self):
        sesion = _SesionQuiz()
        sesion.respuesta("mod/quiz/edit.php", HTML_HUECOS)
        assert _moodle_de_cuestionario(sesion).huecos(5) == [(1, 501), (2, 502)]

    def test_huecos_sin_preguntas_visibles(self):
        sesion = _SesionQuiz()
        sesion.respuesta("mod/quiz/edit.php", '<div id="slot-3"></div>')
        assert _moodle_de_cuestionario(sesion).huecos(5) == [(3, None)]

    def test_tiene_intentos_por_la_falta_de_addquestion(self):
        sesion = _SesionQuiz()
        sesion.respuesta(
            "mod/quiz/edit.php", '<button data-action="addquestion"></button><div id="slot-1">'
        )
        assert _moodle_de_cuestionario(sesion).tiene_intentos(5) is False

        sesion = _SesionQuiz()
        sesion.respuesta("mod/quiz/edit.php", '<div id="slot-1"></div>')
        assert _moodle_de_cuestionario(sesion).tiene_intentos(5) is True

    def test_pagina_de_edicion_desconocida_falla(self):
        sesion = _SesionQuiz()
        sesion.respuesta("mod/quiz/edit.php", "<html><body>otra cosa</body></html>")
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_cuestionario(sesion).tiene_intentos(5)
        assert exc.value.codigo == "ERROR_CONSULTA"

    def test_quitar_hueco_envia_la_accion_de_la_papelera(self):
        sesion = _SesionQuiz()
        sesion.posts_guion = [_Rq(datos={"deleted": True})]
        _moodle_de_cuestionario(sesion).quitar_hueco(838, 77, 3)
        url, datos = sesion.posts[0]
        assert url.endswith("/mod/quiz/edit_rest.php")
        assert dict(datos) == {
            "sesskey": "clave",
            "courseid": "838",
            "quizid": "77",
            "class": "resource",
            "action": "DELETE",
            "id": "3",
        }

    def test_quitar_hueco_con_error_es_intentos(self):
        sesion = _SesionQuiz()
        sesion.posts_guion = [_Rq(datos={"error": "no se puede"})]
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_cuestionario(sesion).quitar_hueco(838, 77, 3)
        assert exc.value.codigo == "CUESTIONARIO_CON_INTENTOS"

    def test_quitar_hueco_sin_json_falla(self):
        sesion = _SesionQuiz()
        sesion.posts_guion = [_Rq("<html>error</html>", status_code=200)]
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_cuestionario(sesion).quitar_hueco(838, 77, 3)
        assert exc.value.codigo == "ERROR_QUITAR_PREGUNTAS"

    def test_borrar_preguntas_usa_la_confirmacion_del_formulario(self):
        sesion = _SesionQuiz()
        sesion.posts_guion = [
            _Rq(FORMULARIO_CONFIRMAR_BORRADO, url="https://aula/centro/delete.php"),
            _Rq("", status_code=303),
        ]
        _moodle_de_cuestionario(sesion).borrar_preguntas(5, [501, 502])
        _url, datos = sesion.posts[1]
        campos = dict(datos)
        assert campos["confirm"] == "abc123"
        assert campos["deleteselected"] == "501,502"

    def test_borrar_preguntas_sin_formulario_calcula_el_md5(self):
        sesion = _SesionQuiz()
        sesion.posts_guion = [_Rq("<html>sin formulario</html>"), _Rq("", status_code=303)]
        _moodle_de_cuestionario(sesion).borrar_preguntas(5, [501, 502])
        _url, datos = sesion.posts[1]
        import hashlib as _hashlib

        assert dict(datos)["confirm"] == _hashlib.md5(b"501,502").hexdigest()

    def test_borrar_preguntas_sin_redireccion_falla(self):
        sesion = _SesionQuiz()
        sesion.posts_guion = [
            _Rq(FORMULARIO_CONFIRMAR_BORRADO),
            _Rq("<html>error</html>", status_code=200),
        ]
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_cuestionario(sesion).borrar_preguntas(5, [501])
        assert exc.value.codigo == "ERROR_BORRAR_PREGUNTAS"

    def test_urls_pluginfile_del_cuestionario(self):
        assert publicar.urls_pluginfile("https://aula", 5, "cuestionario", 77, "punto.png") == [
            "https://aula/pluginfile.php/5/mod_quiz/intro/punto.png",
            "https://aula/pluginfile.php/5/mod_quiz/intro/0/punto.png",
        ]


class TestDobleCuestionario:
    def test_crear_registra_banco_categoria_e_instancia(self):
        moodle = MoodleFalso()
        cmid = moodle.crear(1234, 30, "cuestionario", {"name": "Repaso"})
        assert moodle.categoria_cuestionario(cmid).endswith(
            f",{moodle.leer_modulo(cmid)['contexto']}"
        )
        assert moodle.preguntas_en_categoria(cmid, moodle.categoria_cuestionario(cmid)) == set()
        assert moodle.leer_modulo(cmid)["instance"] == moodle.instancias[cmid]

    def test_importar_anadir_y_quitar(self):
        moodle = MoodleFalso()
        cmid = moodle.crear(1234, 30, "cuestionario", {"name": "Repaso"})
        categoria = moodle.categoria_cuestionario(cmid)
        xml = (
            b'<?xml version="1.0"?><quiz>'
            b"<question type='truefalse'><name><text>P01</text></name></question>"
            b"<question type='truefalse'><name><text>P02</text></name></question></quiz>"
        )
        ids = moodle.importar_preguntas(1234, cmid, categoria, xml)
        assert ids == sorted(ids) and len(ids) == 2
        assert moodle.preguntas_en_categoria(cmid, categoria) == set(ids)
        moodle.anadir_preguntas(cmid, ids)
        assert [pregunta for _hueco, pregunta in moodle.huecos(cmid)] == ids
        moodle.quitar_hueco(1234, moodle.leer_modulo(cmid)["instance"], moodle.huecos(cmid)[0][0])
        assert [pregunta for _hueco, pregunta in moodle.huecos(cmid)] == ids[1:]
        moodle.borrar_preguntas(cmid, ids)
        assert moodle.preguntas_en_categoria(cmid, categoria) == set()

    def test_con_intentos_el_doble_se_niega(self):
        moodle = MoodleFalso()
        cmid = moodle.crear(1234, 30, "cuestionario", {"name": "Repaso"})
        categoria = moodle.categoria_cuestionario(cmid)
        moodle.importar_preguntas(1234, cmid, categoria, b"<quiz/>")
        moodle.intentos[cmid] = True
        with pytest.raises(ErrorPublicacion) as exc:
            moodle.quitar_hueco(1234, moodle.leer_modulo(cmid)["instance"], 901)
        assert exc.value.codigo == "CUESTIONARIO_CON_INTENTOS"
        assert moodle.tiene_intentos(cmid) is True

    def test_borrar_el_modulo_se_lleva_sus_preguntas(self):
        moodle = MoodleFalso()
        cmid = moodle.crear(1234, 30, "cuestionario", {"name": "Repaso"})
        categoria = moodle.categoria_cuestionario(cmid)
        moodle.importar_preguntas(1234, cmid, categoria, b"<quiz/>")
        moodle.borrar(1234, cmid)
        assert categoria not in moodle.bancos


# --------------------------------------------------------------------------- #
# Publicación de un cuestionario
# --------------------------------------------------------------------------- #


PREGUNTAS_CUESTIONARIO = (
    "  - tipo: opcion_multiple\n"
    "    enunciado: ¿Cuánto es **2 + 2**?\n"
    "    opciones:\n"
    '      - {texto: "4", correcta: true}\n'
    '      - {texto: "5"}\n'
    "  - tipo: verdadero_falso\n"
    "    enunciado: El agua hierve a 100 °C.\n"
    "    respuesta: verdadero\n"
)


def documento_cuestionario(
    tmp_path, cuerpo="Descripción del cuestionario.", preguntas=PREGUNTAS_CUESTIONARIO, **ajustes
):
    extra = "".join(f"{clave}: {valor}\n" for clave, valor in ajustes.items())
    ruta = tmp_path / "cuestionario.md"
    ruta.write_text(
        "---\ntipo: cuestionario\nnombre: Repaso\nseccion: 3\n"
        + extra
        + "preguntas:\n"
        + preguntas
        + "---\n\n"
        + cuerpo
        + "\n",
        encoding="utf-8",
    )
    return contenido.cargar(ruta)


class TestPublicarCuestionario:
    def test_payload_completo(self, tmp_path):
        doc = documento_cuestionario(
            tmp_path,
            apertura="2026-10-20 08:00",
            cierre="2026-10-27 23:59",
            tiempo_limite="30",
            intentos="2",
            mezclar_respuestas="false",
        )
        payload = publicar.payload_cuestionario(doc, "html", 55, False)
        assert payload["_qf__mod_quiz_mod_form"] == "1"
        assert payload["name"] == "Repaso"
        assert payload["introeditor[text]"] == "html"
        assert payload["introeditor[itemid]"] == "55"
        assert payload["timeopen[enabled]"] == "1"
        assert (payload["timeopen[day]"], payload["timeopen[hour]"]) == ("20", "8")
        assert payload["timeclose[minute]"] == "59"
        assert payload["timelimit[enabled]"] == "1"
        assert (payload["timelimit[number]"], payload["timelimit[timeunit]"]) == ("30", "60")
        assert payload["attempts"] == "2"
        assert payload["shuffleanswers"] == "0"
        assert payload["visible"] == "0"

    def test_payload_por_defecto(self, tmp_path):
        doc = documento_cuestionario(tmp_path)
        payload = publicar.payload_cuestionario(doc, "html", 1, None)
        assert payload["timeopen[enabled]"] == "0"
        assert payload["timeclose[enabled]"] == "0"
        assert payload["timelimit[enabled]"] == "0"
        assert payload["attempts"] == "1"
        assert payload["shuffleanswers"] == "1"
        assert "visible" not in payload

    def test_payload_intentos_ilimitados(self, tmp_path):
        doc = documento_cuestionario(tmp_path, intentos="ilimitados")
        assert publicar.payload_cuestionario(doc, "html", 1, None)["attempts"] == "0"

    def test_crea_un_cuestionario_con_sus_preguntas_en_orden(self, tmp_path):
        from tiza.cuestionario import preguntas_xml

        doc = documento_cuestionario(tmp_path)
        moodle = MoodleFalso()
        resultado = publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=False)
        assert resultado.accion == "creada"
        assert resultado.oculto is True
        assert resultado.url.endswith("/mod/quiz/view.php?id=100")
        assert resultado.seccion == "Tema 3"
        cmid = resultado.cmid
        assert moodle.importados == [preguntas_xml(doc)]
        assert len(moodle.bancos[moodle.categorias[cmid]]) == 2
        assert [pregunta for _hueco, pregunta in moodle.huecos(cmid)] == sorted(
            moodle.bancos[moodle.categorias[cmid]]
        )
        operaciones = [llamada[0] for llamada in moodle.llamadas]
        assert operaciones.index("crear") < operaciones.index("categoria_cuestionario")
        assert operaciones.index("categoria_cuestionario") < operaciones.index("importar_preguntas")
        assert operaciones.index("importar_preguntas") < operaciones.index("anadir_preguntas")
        assert "huecos" in operaciones  # verificación

    def test_la_descripcion_sube_sus_recursos(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "foto.png").write_bytes(b"png")
        doc = documento_cuestionario(tmp_path, cuerpo="Mira ![foto](img/foto.png).")
        moodle = MoodleFalso()
        publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=False)
        assert moodle.pluginfiles
        assert all("mod_quiz/intro" in url for url in moodle.pluginfiles)

    def test_si_falla_la_importacion_se_borra_el_cuestionario(self, tmp_path):
        class MoodleSinImportar(MoodleFalso):
            def importar_preguntas(self, curso_id, cmid, categoria, xml):
                raise ErrorPublicacion("ERROR_IMPORTACION")

        moodle = MoodleSinImportar()
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(
                moodle, 1234, moodle.secciones, documento_cuestionario(tmp_path), visible=False
            )
        assert exc.value.codigo == "ERROR_IMPORTACION"
        assert exc.value.cmid is None  # el módulo se borró
        assert moodle.secciones[0]["modulos"] == []

    def test_si_falla_anadir_se_borra_el_cuestionario(self, tmp_path):
        class MoodleSinAnadir(MoodleFalso):
            def anadir_preguntas(self, cmid, ids):
                raise ErrorPublicacion("ERROR_ANADIR_PREGUNTAS")

        moodle = MoodleSinAnadir()
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(
                moodle, 1234, moodle.secciones, documento_cuestionario(tmp_path), visible=False
            )
        assert exc.value.codigo == "ERROR_ANADIR_PREGUNTAS"
        assert moodle.secciones[0]["modulos"] == []

    def test_si_no_se_puede_borrar_queda_el_cmid(self, tmp_path):
        class MoodleQueNoBorra(MoodleFalso):
            def importar_preguntas(self, curso_id, cmid, categoria, xml):
                raise ErrorPublicacion("ERROR_IMPORTACION")

            def borrar(self, curso_id, cmid):
                raise ErrorPublicacion("ERROR_BORRADO")

        moodle = MoodleQueNoBorra()
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(
                moodle, 1234, moodle.secciones, documento_cuestionario(tmp_path), visible=False
            )
        assert exc.value.codigo == "ERROR_IMPORTACION"
        assert exc.value.cmid == 100  # que la autoprueba lo limpie

    def _con_imagen(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "f.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 30)
        return documento_cuestionario(
            tmp_path,
            preguntas=(
                "  - tipo: verdadero_falso\n"
                "    enunciado: 'Mira ![El circuito](img/f.png)'\n"
                "    respuesta: verdadero\n"
                "    retro: 'Retro ![El circuito](img/f.png)'\n"
                "  - tipo: verdadero_falso\n"
                "    enunciado: Sin imagen.\n"
                "    respuesta: falso\n"
            ),
        )

    def test_las_imagenes_de_las_preguntas_se_verifican_en_el_aula(self, tmp_path):
        moodle = MoodleFalso()
        publicar.publicar_documento(
            moodle, 1234, moodle.secciones, self._con_imagen(tmp_path), visible=False
        )
        consultas = [llamada for llamada in moodle.llamadas if llamada[0] == "imagenes_de_pregunta"]
        assert len(consultas) == 1  # solo la pregunta que lleva imagen
        [xml] = moodle.importados
        assert b"@@PLUGINFILE@@/img-" in xml

    def test_sin_imagenes_no_se_pregunta_por_ellas(self, tmp_path):
        moodle = MoodleFalso()
        publicar.publicar_documento(
            moodle, 1234, moodle.secciones, documento_cuestionario(tmp_path), visible=False
        )
        assert not [ll for ll in moodle.llamadas if ll[0] == "imagenes_de_pregunta"]

    def test_si_el_aula_no_sirve_la_imagen_se_borra_el_cuestionario(self, tmp_path):
        moodle = MoodleFalso(imagenes_servidas=False)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(
                moodle, 1234, moodle.secciones, self._con_imagen(tmp_path), visible=False
            )
        assert exc.value.codigo == "VERIFICACION_IMAGENES"
        assert moodle.secciones[0]["modulos"] == []

    def test_si_el_aula_no_guarda_todas_las_imagenes_tambien_falla(self, tmp_path):
        class MoodleQuePierde(MoodleFalso):
            def imagenes_de_pregunta(self, cmid, pregunta_id):
                return 0, 0

        moodle = MoodleQuePierde()
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(
                moodle, 1234, moodle.secciones, self._con_imagen(tmp_path), visible=False
            )
        assert exc.value.codigo == "VERIFICACION_IMAGENES"

    def test_si_la_verificacion_desordena_se_borra_el_cuestionario(self, tmp_path):
        class MoodleQueDesordena(MoodleFalso):
            def huecos(self, cmid):
                return list(reversed(super().huecos(cmid)))

        moodle = MoodleQueDesordena()
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(
                moodle, 1234, moodle.secciones, documento_cuestionario(tmp_path), visible=False
            )
        assert exc.value.codigo == "VERIFICACION_PREGUNTAS"
        assert moodle.secciones[0]["modulos"] == []

    def test_las_fechas_del_cuestionario_se_verifican(self, tmp_path):
        class MoodleQueRedondea(MoodleFalso):
            def leer_modulo(self, cmid):
                info = super().leer_modulo(cmid)
                cierre = info["fechas"]["timeclose"]
                if cierre is not None:
                    info["fechas"]["timeclose"] = (*cierre[:4], 55)
                return info

        moodle = MoodleQueRedondea()
        doc = documento_cuestionario(tmp_path, apertura="2026-10-20", cierre="2026-10-27")
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=False)
        assert exc.value.codigo == "FECHAS_NO_APLICADAS"
        assert moodle.secciones[0]["modulos"] == []  # era nuevo: no queda nada

    def test_fechas_esperadas_de_un_cuestionario(self, tmp_path):
        doc = documento_cuestionario(tmp_path, apertura="2026-10-20 08:00", cierre="2026-10-27")
        assert publicar.fechas_esperadas(doc) == {
            "timeopen": (2026, 10, 20, 8, 0),
            "timeclose": (2026, 10, 27, 23, 59),
        }

    def test_un_cuestionario_sin_crear_siempre_oculto(self, tmp_path):
        moodle = MoodleFalso()
        resultado = publicar.publicar_documento(
            moodle, 1234, moodle.secciones, documento_cuestionario(tmp_path), visible=None
        )
        assert resultado.oculto is True


PREGUNTAS_V2 = (
    "  - tipo: respuesta_corta\n"
    "    enunciado: Capital de Francia\n"
    "    aceptadas: [París]\n"
    "  - tipo: numerica\n"
    "    enunciado: π con dos decimales\n"
    "    valor: 3.14\n"
    "    tolerancia: 0.005\n"
    "  - tipo: verdadero_falso\n"
    "    enunciado: El agua hierve a 100 °C.\n"
    "    respuesta: verdadero\n"
)


class TestRepublicarCuestionario:
    def _publicar_v2(self, moodle, tmp_path, **ajustes):
        doc = documento_cuestionario(tmp_path, preguntas=PREGUNTAS_V2, **ajustes)
        return publicar.publicar_documento(moodle, 1234, moodle.estructura(1234), doc, visible=None)

    def test_republicar_reutiliza_el_cmid_y_cambia_las_preguntas(self, tmp_path):
        moodle = MoodleFalso()
        original = documento_cuestionario(tmp_path)
        primero = publicar.publicar_documento(
            moodle, 1234, moodle.estructura(1234), original, visible=False
        )
        cmid = primero.cmid
        viejas = set(moodle.bancos[moodle.categorias[cmid]])
        segundo = self._publicar_v2(moodle, tmp_path)
        assert segundo.cmid == cmid
        assert segundo.accion == "actualizada"
        assert segundo.oculto is True  # conserva la visibilidad sin indicarla
        categoria = moodle.categorias[cmid]
        nuevas = set(moodle.bancos[categoria])
        assert len(nuevas) == 3
        assert not (nuevas & viejas)
        assert [pregunta for _hueco, pregunta in moodle.huecos(cmid)] == sorted(nuevas)
        operaciones = [llamada[0] for llamada in moodle.llamadas]
        assert operaciones.index("importar_preguntas") < operaciones.index("anadir_preguntas")
        assert operaciones.index("anadir_preguntas") < operaciones.index("quitar_hueco")
        assert operaciones.index("quitar_hueco") < operaciones.index("borrar_preguntas")
        assert operaciones.index("borrar_preguntas") < operaciones.index("actualizar")

    def test_republicar_actualiza_los_ajustes(self, tmp_path):
        moodle = MoodleFalso()
        publicar.publicar_documento(
            moodle, 1234, moodle.estructura(1234), documento_cuestionario(tmp_path), visible=False
        )
        resultado = self._publicar_v2(
            moodle, tmp_path, tiempo_limite="30", intentos="3", mezclar_respuestas="false"
        )
        formulario = moodle.formularios[resultado.cmid]
        assert formulario["attempts"] == "3"
        assert formulario["timelimit[enabled]"] == "1"
        assert formulario["timelimit[number]"] == "30"
        assert formulario["shuffleanswers"] == "0"

    def test_republicar_con_visible_lo_muestra(self, tmp_path):
        moodle = MoodleFalso()
        publicar.publicar_documento(
            moodle, 1234, moodle.estructura(1234), documento_cuestionario(tmp_path), visible=False
        )
        doc = documento_cuestionario(tmp_path, preguntas=PREGUNTAS_V2)
        resultado = publicar.publicar_documento(
            moodle, 1234, moodle.estructura(1234), doc, visible=True
        )
        assert resultado.oculto is False
        assert moodle.formularios[resultado.cmid]["visible"] == "1"

    def test_con_intentos_no_toca_nada(self, tmp_path):
        moodle = MoodleFalso()
        primero = publicar.publicar_documento(
            moodle, 1234, moodle.estructura(1234), documento_cuestionario(tmp_path), visible=False
        )
        cmid = primero.cmid
        moodle.intentos[cmid] = True
        antes_bancos = {clave: dict(banco) for clave, banco in moodle.bancos.items()}
        antes_huecos = list(moodle.huecos(cmid))
        antes_formulario = dict(moodle.formularios[cmid])
        v2 = documento_cuestionario(tmp_path, preguntas=PREGUNTAS_V2)
        secciones = moodle.estructura(1234)
        llamadas_antes = len(moodle.llamadas)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(moodle, 1234, secciones, v2, visible=None)
        assert exc.value.codigo == "CUESTIONARIO_CON_INTENTOS"
        assert "intentos" in exc.value.detalle
        nuevas_llamadas = [llamada[0] for llamada in moodle.llamadas[llamadas_antes:]]
        assert nuevas_llamadas == ["tiene_intentos"]
        assert moodle.bancos == antes_bancos
        assert moodle.huecos(cmid) == antes_huecos
        assert moodle.formularios[cmid] == antes_formulario

    def test_si_la_importacion_falla_el_cuestionario_sigue_igual(self, tmp_path):
        class MoodleQueFallaLaSegunda(MoodleFalso):
            def __init__(self):
                super().__init__()
                self.importaciones = 0

            def importar_preguntas(self, curso_id, cmid, categoria, xml):
                self.importaciones += 1
                if self.importaciones > 1:
                    raise ErrorPublicacion("ERROR_IMPORTACION")
                return super().importar_preguntas(curso_id, cmid, categoria, xml)

        moodle = MoodleQueFallaLaSegunda()
        primero = publicar.publicar_documento(
            moodle, 1234, moodle.estructura(1234), documento_cuestionario(tmp_path), visible=False
        )
        cmid = primero.cmid
        antes_bancos = {clave: dict(banco) for clave, banco in moodle.bancos.items()}
        antes_huecos = list(moodle.huecos(cmid))
        with pytest.raises(ErrorPublicacion) as exc:
            self._publicar_v2(moodle, tmp_path)
        assert exc.value.codigo == "ERROR_IMPORTACION"
        assert moodle.bancos == antes_bancos
        assert moodle.huecos(cmid) == antes_huecos
        assert "actualizar" not in [llamada[0] for llamada in moodle.llamadas]

    def test_si_anadir_falla_se_borran_las_nuevas(self, tmp_path):
        class MoodleQueFallaLaSegunda(MoodleFalso):
            def __init__(self):
                super().__init__()
                self.anadidos = 0

            def anadir_preguntas(self, cmid, ids):
                self.anadidos += 1
                if self.anadidos > 1:
                    raise ErrorPublicacion("ERROR_ANADIR_PREGUNTAS")
                super().anadir_preguntas(cmid, ids)

        moodle = MoodleQueFallaLaSegunda()
        primero = publicar.publicar_documento(
            moodle, 1234, moodle.estructura(1234), documento_cuestionario(tmp_path), visible=False
        )
        cmid = primero.cmid
        categoria = moodle.categorias[cmid]
        viejas = set(moodle.bancos[categoria])
        with pytest.raises(ErrorPublicacion) as exc:
            self._publicar_v2(moodle, tmp_path)
        assert exc.value.codigo == "ERROR_ANADIR_PREGUNTAS"
        assert set(moodle.bancos[categoria]) == viejas  # las nuevas se borraron
        assert [pregunta for _hueco, pregunta in moodle.huecos(cmid)] == sorted(viejas)

    def test_si_un_alumno_empieza_a_mitad_quedan_viejas_y_nuevas(self, tmp_path):
        class MoodleQueEmpiezaIntento(MoodleFalso):
            def __init__(self):
                super().__init__()
                self.anadidos = 0

            def anadir_preguntas(self, cmid, ids):
                super().anadir_preguntas(cmid, ids)
                self.anadidos += 1
                if self.anadidos > 1:
                    self.intentos[cmid] = True  # un alumno empieza justo después

        moodle = MoodleQueEmpiezaIntento()
        primero = publicar.publicar_documento(
            moodle, 1234, moodle.estructura(1234), documento_cuestionario(tmp_path), visible=False
        )
        cmid = primero.cmid
        categoria = moodle.categorias[cmid]
        with pytest.raises(ErrorPublicacion) as exc:
            self._publicar_v2(moodle, tmp_path)
        assert exc.value.codigo == "CUESTIONARIO_CON_INTENTOS"
        assert "viejas y nuevas" in exc.value.detalle
        assert len(moodle.bancos[categoria]) == 5  # 2 viejas + 3 nuevas, ninguna borrada
        assert len(moodle.huecos(cmid)) == 5
        assert "actualizar" not in [llamada[0] for llamada in moodle.llamadas]

    def test_las_preguntas_del_banco_del_curso_no_se_borran(self, tmp_path):
        moodle = MoodleFalso()
        primero = publicar.publicar_documento(
            moodle, 1234, moodle.estructura(1234), documento_cuestionario(tmp_path), visible=False
        )
        cmid = primero.cmid
        # La profesora añadió a mano una pregunta del banco del curso al cuestionario.
        moodle.bancos["1,999"] = {777: "Del curso"}
        moodle.huecos_quiz[cmid].append((999, 777))
        self._publicar_v2(moodle, tmp_path)
        assert moodle.bancos["1,999"] == {777: "Del curso"}
        assert 999 not in [hueco for hueco, _pregunta in moodle.huecos(cmid)]


# --------------------------------------------------------------------------- #
# Actividades H5P
# --------------------------------------------------------------------------- #

H5P_HUECOS = 'tipo: rellenar_huecos\ntextos:\n  - "El agua hierve a [[100]] grados."\n'


def documento_h5p(tmp_path, actividad=H5P_HUECOS, nombre="Repaso H5P", **campos_actividad):
    actividad = (
        actividad.rstrip("\n")
        + "\n"
        + "".join(f"{clave}: {valor}\n" for clave, valor in campos_actividad.items())
    )
    indentado = "\n".join(
        "  " + linea if linea else linea for linea in actividad.strip("\n").split("\n")
    )
    ruta = tmp_path / "actividad-h5p.md"
    ruta.write_text(
        f"---\ntipo: h5p\nnombre: {nombre}\nseccion: 3\n"
        f"actividad:\n{indentado}\n---\n\nDescripción de la actividad.\n",
        encoding="utf-8",
    )
    return contenido.cargar(ruta)


def documento_paquete_h5p(tmp_path, nombre="paquete.h5p", titulo="Paquete de prueba"):
    import io as _io
    import zipfile as _zipfile

    ruta_paquete = tmp_path / nombre
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as zip_:
        zip_.writestr(
            "h5p.json",
            '{"title":"' + titulo + '","mainLibrary":"H5P.Blanks",'
            '"preloadedDependencies":[{"machineName":"H5P.Blanks","majorVersion":1,'
            '"minorVersion":14}]}',
        )
        zip_.writestr("content/content.json", '{"questions":["El agua hierve a *100*."]}')
        zip_.writestr("H5P.Blanks-1.14/library.json", '{"machineName":"H5P.Blanks"}')
    ruta_paquete.write_bytes(buf.getvalue())
    ruta = tmp_path / "actividad-paquete.md"
    ruta.write_text(
        "---\ntipo: h5p\nnombre: Actividad con paquete\nseccion: 3\n"
        f"paquete: {nombre}\n---\n\nDescripción.\n",
        encoding="utf-8",
    )
    return contenido.cargar(ruta, raiz=tmp_path)


class TestPublicarH5P:
    def test_payload_generado(self, tmp_path):
        doc = documento_h5p(tmp_path, calificacion="7")
        payload = publicar.payload_h5p(doc, "html", 55, 56, False)
        assert payload["_qf__mod_h5pactivity_mod_form"] == "1"
        assert payload["name"] == "Repaso H5P"
        assert payload["introeditor[text]"] == "html"
        assert (payload["introeditor[itemid]"], payload["packagefile"]) == ("55", "56")
        assert payload["grade[modgrade_type]"] == "point"
        assert payload["grade[modgrade_point]"] == "7"
        assert payload["enabletracking"] == "1"
        assert payload["grademethod"] == "1"
        assert payload["reviewmode"] == "1"
        assert payload["displayopt[export]"] == "0"
        assert payload["displayopt[embed]"] == "0"
        assert payload["displayopt[copyright]"] == "0"
        assert payload["visible"] == "0"

    def test_payload_tarjetas_sin_seguimiento(self, tmp_path):
        actividad = 'tipo: tarjetas\ntarjetas:\n  - {anverso: "¿2 + 2?", reverso: "4"}\n'
        doc = documento_h5p(tmp_path, actividad=actividad)
        payload = publicar.payload_h5p(doc, "html", 1, 2, None)
        assert payload["grade[modgrade_type]"] == "none"
        assert payload["enabletracking"] == "0"
        assert "grademethod" not in payload
        assert "visible" not in payload

    def test_payload_paquete(self, tmp_path):
        doc = documento_paquete_h5p(tmp_path)
        payload = publicar.payload_h5p(doc, "html", 1, 2, None)
        assert payload["grade[modgrade_type]"] == "point"
        assert payload["grade[modgrade_point]"] == "10"
        assert payload["enabletracking"] == "1"

    def test_crea_la_actividad_y_sube_el_paquete_generado(self, tmp_path):
        from tiza.h5p import paquete_h5p

        doc = documento_h5p(tmp_path)
        moodle = MoodleFalso()
        resultado = publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=False)
        assert (resultado.tipo, resultado.accion, resultado.oculto) == (
            "h5p",
            "creada",
            True,
        )
        assert resultado.url.endswith("/mod/h5pactivity/view.php?id=100")
        subida = next(llamada for llamada in moodle.llamadas if llamada[0] == "subir")
        assert subida[1] == "actividad-h5p.h5p"
        assert moodle.subidas[-1][1] == paquete_h5p(doc)
        crear = next(llamada for llamada in moodle.llamadas if llamada[0] == "crear")
        assert crear[3] == "h5p"
        assert crear[4]["packagefile"] != crear[4]["introeditor[itemid]"]
        operaciones = [llamada[0] for llamada in moodle.llamadas]
        assert operaciones.index("subir") < operaciones.index("crear")
        assert "comprobar_h5p" in operaciones
        assert any("mod_h5pactivity/package/0/" in url for url in moodle.pluginfiles)

    def test_el_paquete_subido_se_reempaqueta(self, tmp_path):
        from tiza.h5p import reempaquetar

        doc = documento_paquete_h5p(tmp_path)
        moodle = MoodleFalso()
        publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=False)
        assert moodle.subidas[-1][1] == reempaquetar(doc.paquete.ruta)
        assert b"H5P.Blanks-1.14/library.json" not in moodle.subidas[-1][1]

    def test_los_recursos_de_la_descripcion_tambien_suben(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "foto.png").write_bytes(b"png")
        ruta = tmp_path / "actividad-h5p.md"
        ruta.write_text(
            "---\ntipo: h5p\nnombre: Repaso H5P\nseccion: 3\nactividad:\n"
            "  tipo: rellenar_huecos\n"
            "  textos:\n"
            '    - "El agua hierve a [[100]] grados."\n'
            "---\n\nMira ![foto](img/foto.png).\n",
            encoding="utf-8",
        )
        doc = contenido.cargar(ruta)
        moodle = MoodleFalso()
        publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=False)
        assert any("mod_h5pactivity/intro" in url for url in moodle.pluginfiles)

    def test_si_no_se_despliega_se_borra_la_actividad(self, tmp_path):
        class MoodleSinDesplegar(MoodleFalso):
            def comprobar_h5p(self, cmid):
                self.llamadas.append(("comprobar_h5p", cmid))
                return False

        moodle = MoodleSinDesplegar()
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(
                moodle, 1234, moodle.secciones, documento_h5p(tmp_path), visible=False
            )
        assert exc.value.codigo == "H5P_NO_DESPLEGADO"
        assert exc.value.cmid is None
        assert moodle.secciones[0]["modulos"] == []

    def test_sin_libreria_avisa_con_el_machine_name(self, tmp_path):
        class MoodleSinLibreria(MoodleFalso):
            def comprobar_h5p(self, cmid):
                self.llamadas.append(("comprobar_h5p", cmid))
                return False

            def libreria_h5p_ausente(self, cmid, machine_name):
                self.llamadas.append(("libreria_h5p_ausente", cmid, machine_name))
                return True

        moodle = MoodleSinLibreria()
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(
                moodle, 1234, moodle.secciones, documento_h5p(tmp_path), visible=False
            )
        assert exc.value.codigo == "H5P_LIBRERIA_AUSENTE"
        assert "H5P.Blanks" in exc.value.detalle
        assert moodle.secciones[0]["modulos"] == []

    def test_si_el_paquete_no_esta_en_pluginfile_se_borra(self, tmp_path):
        moodle = MoodleFalso(pluginfiles_ok=False)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(
                moodle, 1234, moodle.secciones, documento_h5p(tmp_path), visible=False
            )
        assert exc.value.codigo == "VERIFICACION_PAQUETE"
        assert moodle.secciones[0]["modulos"] == []

    def test_estructura_ajax_reconoce_la_actividad_h5p(self, monkeypatch):
        estado = [
            {
                "id": 30,
                "section": 1,
                "name": "Proyecto",
                "modules": [{"id": 57078, "name": "Repaso", "module": "h5pactivity"}],
            }
        ]
        monkeypatch.setattr(publicar.py_course, "get_course", lambda *a, **k: estado)
        moodle = publicar.Moodle("https://aula", object(), "clave", pausa=0)
        assert moodle.estructura(838)[0]["modulos"] == [
            {"cmid": 57078, "nombre": "Repaso", "tipo": "h5p"}
        ]

    def test_urls_pluginfile_y_del_paquete(self):
        assert publicar.urls_pluginfile("https://aula", 97, "h5p", 5, "paquete.h5p") == [
            "https://aula/pluginfile.php/97/mod_h5pactivity/intro/paquete.h5p",
            "https://aula/pluginfile.php/97/mod_h5pactivity/intro/0/paquete.h5p",
        ]
        assert publicar.urls_paquete_h5p("https://aula", 97, 5, "paquete.h5p") == [
            "https://aula/pluginfile.php/97/mod_h5pactivity/package/0/paquete.h5p",
            "https://aula/pluginfile.php/97/mod_h5pactivity/package/5/paquete.h5p",
        ]


class TestRepublicarH5P:
    def _publicar(self, moodle, tmp_path, **campos):
        doc = documento_h5p(tmp_path, **campos)
        return publicar.publicar_documento(moodle, 1234, moodle.estructura(1234), doc, visible=None)

    def test_republicar_reutiliza_el_cmid(self, tmp_path):
        moodle = MoodleFalso()
        primero = self._publicar(moodle, tmp_path)
        cmid = primero.cmid
        segundo = self._publicar(moodle, tmp_path, calificacion="5")
        assert (segundo.cmid, segundo.accion) == (cmid, "actualizada")
        assert segundo.oculto is True  # conserva la visibilidad
        assert moodle.formularios[cmid]["grade[modgrade_point]"] == "5"
        assert len([llamada for llamada in moodle.llamadas if llamada[0] == "subir"]) == 2

    def test_republicar_con_visible_lo_muestra(self, tmp_path):
        moodle = MoodleFalso()
        self._publicar(moodle, tmp_path)
        doc = documento_h5p(tmp_path, calificacion="3")
        resultado = publicar.publicar_documento(
            moodle, 1234, moodle.estructura(1234), doc, visible=True
        )
        assert resultado.oculto is False
        assert moodle.formularios[resultado.cmid]["visible"] == "1"

    def test_con_intentos_no_toca_nada(self, tmp_path):
        moodle = MoodleFalso()
        primero = self._publicar(moodle, tmp_path)
        cmid = primero.cmid
        moodle.intentos_h5p[cmid] = True
        antes_formulario = dict(moodle.formularios[cmid])
        antes_subidas = len(moodle.subidas)
        llamadas_antes = len(moodle.llamadas)
        with pytest.raises(ErrorPublicacion) as exc:
            self._publicar(moodle, tmp_path, calificacion="5")
        assert exc.value.codigo == "H5P_CON_INTENTOS"
        assert exc.value.cmid is None
        nuevas = [
            llamada[0] for llamada in moodle.llamadas[llamadas_antes:] if llamada[0] != "estructura"
        ]
        assert nuevas == ["h5p_tiene_intentos"]
        assert moodle.formularios[cmid] == antes_formulario
        assert len(moodle.subidas) == antes_subidas

    def test_republicar_un_paquete_actualiza_el_fichero(self, tmp_path):
        moodle = MoodleFalso()
        doc = documento_paquete_h5p(tmp_path)
        primero = publicar.publicar_documento(
            moodle, 1234, moodle.estructura(1234), doc, visible=None
        )
        segundo = publicar.publicar_documento(
            moodle, 1234, moodle.estructura(1234), doc, visible=None
        )
        assert (segundo.cmid, segundo.accion) == (primero.cmid, "actualizada")
        assert len(moodle.subidas) == 2


# --------------------------------------------------------------------------- #
# H5P: adaptador real
# --------------------------------------------------------------------------- #

VISTA_CON_EMBED = (
    '<html><body><iframe src="/h5p/embed.php?url=https%3A%2F%2Faula%2Fpluginfile.php"></iframe>'
    "</body></html>"
)

EMBED_DESPLEGADO = (
    '<html><body><script>H5PIntegration = {"contents":{"cid-1":{}},"core":{"wwwroot":"x"}};'
    '</script><div class="h5p-iframe"></div></body></html>'
)


class _SesionH5P:
    """Sesión falsa que sirve las páginas del adaptador H5P."""

    def __init__(self):
        self.paginas: dict[str, object] = {}
        self.gets: list[tuple] = []

    def respuesta(self, clave: str, valor) -> None:
        self.paginas[clave] = valor

    def get(self, url, params=None, **kwargs):
        self.gets.append((url, params))
        for clave, valor in self.paginas.items():
            if clave in url:
                return valor if isinstance(valor, _Rq) else _Rq(str(valor))
        return _Rq("")


class TestAdaptadorH5P:
    def _moodle(self, sesion: _SesionH5P) -> publicar.Moodle:
        return publicar.Moodle("https://aula/centro", sesion, "clave", pausa=0)

    def test_desplegado_cuando_el_embed_trae_integracion(self):
        sesion = _SesionH5P()
        sesion.respuesta("view.php", VISTA_CON_EMBED)
        sesion.respuesta("embed.php", EMBED_DESPLEGADO)
        assert self._moodle(sesion).comprobar_h5p(5) is True

    def test_no_desplegado_sin_integracion(self):
        sesion = _SesionH5P()
        sesion.respuesta("view.php", VISTA_CON_EMBED)
        sesion.respuesta("embed.php", "<html>sin h5p</html>")
        assert self._moodle(sesion).comprobar_h5p(5) is False

    def test_no_desplegado_sin_iframe(self):
        sesion = _SesionH5P()
        sesion.respuesta("view.php", "<html>sin iframe</html>")
        assert self._moodle(sesion).comprobar_h5p(5) is False

    def test_menciona_la_libreria_esperada(self):
        sesion = _SesionH5P()
        sesion.respuesta("view.php", VISTA_CON_EMBED)
        sesion.respuesta("embed.php", "<html>Falta H5P.Blanks 1.15</html>")
        assert self._moodle(sesion).libreria_h5p_ausente(5, "H5P.Blanks") is True
        assert self._moodle(sesion).libreria_h5p_ausente(5, "H5P.DragText") is False

    def test_intentos_por_el_enlace_del_informe(self):
        sesion = _SesionH5P()
        sesion.respuesta("report.php", '<a href="report.php?id=5&attemptid=3">ver</a>')
        assert self._moodle(sesion).h5p_tiene_intentos(5) is True

    def test_sin_intentos_no_hay_enlaces(self):
        sesion = _SesionH5P()
        sesion.respuesta("report.php", "<table><tr><th>Alumno</th></tr></table>")
        assert self._moodle(sesion).h5p_tiene_intentos(5) is False

    def test_un_informe_404_es_actividad_sin_seguimiento(self):
        sesion = _SesionH5P()
        sesion.respuesta("report.php", _Rq("", status_code=404))
        assert self._moodle(sesion).h5p_tiene_intentos(47) is False


def _fecha_en_formulario(campo: str, valor: tuple[int, int, int, int, int]) -> dict:
    anio, mes, dia, hora, minuto = valor
    return {
        f"{campo}[enabled]": "1",
        f"{campo}[year]": str(anio),
        f"{campo}[month]": str(mes),
        f"{campo}[day]": str(dia),
        f"{campo}[hour]": str(hora),
        f"{campo}[minute]": str(minuto),
    }


# Nada que cambie el contenido, las preguntas, los intentos o la visibilidad.
_ESCRITURAS_DE_CONTENIDO = {
    "crear",
    "subir",
    "borrar",
    "importar_preguntas",
    "anadir_preguntas",
    "borrar_preguntas",
    "quitar_hueco",
    "tiene_intentos",
}


class TestSoloFechas:
    def tarea(self, tmp_path, entrega="2026-10-12"):
        ruta = tmp_path / "t.md"
        ruta.write_text(
            "---\ntipo: tarea\nnombre: Problemas\nseccion: 3\n"
            f"apertura: 2026-10-01\nentrega: {entrega}\n---\n\nResuelve.\n",
            encoding="utf-8",
        )
        return contenido.cargar(ruta)

    def cuestionario(self, tmp_path, cierre="2026-10-27"):
        extra = f"cierre: {cierre}\n" if cierre else ""
        ruta = tmp_path / "c.md"
        ruta.write_text(
            "---\ntipo: cuestionario\nnombre: Repaso\nseccion: 3\n"
            f"apertura: 2026-10-20\n{extra}intentos: 2\n"
            "preguntas:\n  - tipo: verdadero_falso\n    enunciado: x\n    respuesta: verdadero\n"
            "---\n\nDescripción.\n",
            encoding="utf-8",
        )
        return contenido.cargar(ruta)

    def aula_con(self, doc, fechas_antiguas: dict, cmid: int = 55) -> MoodleFalso:
        """Un aula con el módulo ya publicado: su contenido y sus fechas de antes."""
        moodle = MoodleFalso()
        moodle.secciones[0]["modulos"] = [{"cmid": cmid, "nombre": doc.nombre, "tipo": doc.tipo}]
        formulario = {
            "name": doc.nombre,
            "visible": "1",
            "introeditor[text]": "<p>antes</p>",
            "attempts": "2",
        }
        for campo, valor in fechas_antiguas.items():
            formulario.update(_fecha_en_formulario(campo, valor))
        moodle.formularios[cmid] = formulario
        return moodle

    def test_el_payload_de_una_tarea_solo_lleva_las_fechas(self, tmp_path):
        payload = publicar.payload_solo_fechas(self.tarea(tmp_path))
        assert not {"name", "introeditor[text]", "visible", "attempts"} & set(payload)
        assert payload["duedate[day]"] == "12"
        assert payload["cutoffdate[enabled]"] == "0"

    def test_el_payload_de_una_tarea_desactiva_el_recordatorio_de_calificacion(self, tmp_path):
        # Deliberado: Moodle rechaza una entrega posterior al recordatorio («Recordarme
        # calificar antes de»), y la confirmación de real enseña que se quita.
        payload = publicar.payload_solo_fechas(self.tarea(tmp_path))
        assert payload["gradingduedate[enabled]"] == "0"

    def test_el_payload_de_un_cuestionario_no_toca_intentos_ni_tiempo(self, tmp_path):
        payload = publicar.payload_solo_fechas(self.cuestionario(tmp_path))
        ajustes = {"attempts", "shuffleanswers", "timelimit[enabled]", "name", "visible"}
        assert not ajustes & set(payload)
        assert payload["timeclose[day]"] == "27"
        assert payload["timeopen[day]"] == "20"

    def test_una_pagina_no_admite_solo_fechas(self, tmp_path):
        ruta = tmp_path / "p.md"
        ruta.write_text("---\ntipo: pagina\nnombre: P\nseccion: 3\n---\n\nx\n", encoding="utf-8")
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.payload_solo_fechas(contenido.cargar(ruta))
        assert exc.value.codigo == "SOLO_FECHAS_NO_APLICA"

    def test_cambia_la_fecha_y_deja_el_resto_como_estaba(self, tmp_path):
        doc = self.tarea(tmp_path)
        antiguas = {"duedate": (2026, 10, 10, 23, 59)}
        moodle = self.aula_con(doc, antiguas)
        resultado = publicar.publicar_fechas(moodle, moodle.secciones, doc)
        assert (resultado.accion, resultado.cmid) == ("actualizada", 55)
        assert moodle.leer_modulo(55)["fechas"]["duedate"] == (2026, 10, 12, 23, 59)
        formulario = moodle.formularios[55]
        assert (formulario["name"], formulario["introeditor[text]"]) == (
            "Problemas",
            "<p>antes</p>",
        )
        assert formulario["attempts"] == "2"
        assert resultado.hash == doc.hash_cargado
        escrituras = {llamada[0] for llamada in moodle.llamadas} & _ESCRITURAS_DE_CONTENIDO
        assert escrituras == set()

    def test_un_cuestionario_con_intentos_cambia_solo_su_cierre(self, tmp_path):
        doc = self.cuestionario(tmp_path, cierre="2026-10-27")
        antiguas = {"timeclose": (2026, 10, 26, 23, 59)}
        moodle = self.aula_con(doc, antiguas)
        moodle.secciones[0]["modulos"] = [{"cmid": 55, "nombre": "Repaso", "tipo": "cuestionario"}]
        publicar.publicar_fechas(moodle, moodle.secciones, doc)
        assert moodle.leer_modulo(55)["fechas"]["timeclose"] == (2026, 10, 27, 23, 59)
        assert moodle.formularios[55]["attempts"] == "2"
        assert not ({llamada[0] for llamada in moodle.llamadas} & _ESCRITURAS_DE_CONTENIDO)

    def test_sin_cierre_en_el_fichero_la_fecha_del_aula_se_quita(self, tmp_path):
        doc = self.cuestionario(tmp_path, cierre=None)
        moodle = self.aula_con(doc, {"timeclose": (2026, 10, 26, 23, 59)})
        moodle.secciones[0]["modulos"] = [{"cmid": 55, "nombre": "Repaso", "tipo": "cuestionario"}]
        publicar.publicar_fechas(moodle, moodle.secciones, doc)
        assert moodle.leer_modulo(55)["fechas"]["timeclose"] is None

    def test_sin_el_modulo_no_envia_nada(self, tmp_path):
        doc = self.tarea(tmp_path)
        moodle = MoodleFalso()
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_fechas(moodle, moodle.secciones, doc)
        assert exc.value.codigo == "MODULO_AUSENTE"
        assert not any(llamada[0] == "actualizar" for llamada in moodle.llamadas)

    def test_si_el_aula_no_guarda_las_fechas_falla(self, tmp_path):
        doc = self.tarea(tmp_path)

        class AulaQueNoCambia(MoodleFalso):
            def leer_modulo(self, cmid):
                info = super().leer_modulo(cmid)
                info["fechas"]["duedate"] = (2026, 10, 10, 23, 59)
                return info

        moodle = AulaQueNoCambia()
        moodle.secciones[0]["modulos"] = [{"cmid": 55, "nombre": "Problemas", "tipo": "tarea"}]
        moodle.formularios[55] = {"name": "Problemas", "visible": "1"}
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_fechas(moodle, moodle.secciones, doc)
        assert exc.value.codigo == "FECHAS_NO_APLICADAS"

    def test_una_pagina_con_modulo_tampoco_admite_solo_fechas(self, tmp_path):
        ruta = tmp_path / "p.md"
        ruta.write_text("---\ntipo: pagina\nnombre: P\nseccion: 3\n---\n\nx\n", encoding="utf-8")
        doc = contenido.cargar(ruta)
        moodle = MoodleFalso()
        moodle.secciones[0]["modulos"] = [{"cmid": 55, "nombre": "P", "tipo": "pagina"}]
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_fechas(moodle, moodle.secciones, doc)
        assert exc.value.codigo == "SOLO_FECHAS_NO_APLICA"
        assert not any(llamada[0] == "actualizar" for llamada in moodle.llamadas)


# --- itinerario: finalización y restricciones ------------------------------ #

import json  # noqa: E402


def doc_itinerario(tmp_path, extra: str, nombre="pagina.md", tipo="pagina", titulo="Repaso"):
    for dep in ("test1.md",):
        if not (tmp_path / dep).exists():
            (tmp_path / dep).write_text(
                "---\ntipo: pagina\nnombre: Test uno\nseccion: 3\n---\n\nx\n", encoding="utf-8"
            )
    ruta = tmp_path / nombre
    ruta.write_text(
        f"---\ntipo: {tipo}\nnombre: {titulo}\nseccion: 3\n{extra}---\n\nHola\n", encoding="utf-8"
    )
    return contenido.cargar(ruta, raiz=tmp_path.resolve())


def aula_con(modulos=None, **opciones) -> MoodleFalso:
    secciones = [{"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": modulos or []}]
    return MoodleFalso(secciones=secciones, **opciones)


def publicar_itinerario(moodle, doc, dependencias=None):
    return publicar.publicar_documento(
        moodle, 1234, moodle.secciones, doc, visible=None, dependencias=dependencias
    )


class TestPayloadFinalizacion:
    @pytest.mark.parametrize(
        ("modo", "esperado"),
        [
            ("ninguna", {"completion": "0"}),
            ("manual", {"completion": "1"}),
            ("ver", {"completion": "2", "completionview": "1"}),
        ],
    )
    def test_pagina(self, tmp_path, modo, esperado):
        doc = doc_itinerario(tmp_path, f"finalizacion: {modo}\n")
        payload = publicar.payload_finalizacion(doc)
        assert {
            k: v for k, v in payload.items() if not k.startswith("completionexpected")
        } == esperado
        assert payload["completionexpected[enabled]"] == "0"

    def test_tarea_envia_todos_sus_campos_para_no_heredar_un_modo_anterior(self, tmp_path):
        extra = "apertura: 2026-10-01\nentrega: 2026-10-10\nfinalizacion: entregar\n"
        doc = doc_itinerario(tmp_path, extra, "t.md", "tarea", "Tarea")
        payload = publicar.payload_finalizacion(doc)
        assert payload["completion"] == "2"
        assert (payload["completionsubmit"], payload["completionview"]) == ("1", "0")
        assert payload["completionusegrade"] == "0"

    def test_calificar(self, tmp_path):
        extra = "apertura: 2026-10-01\nentrega: 2026-10-10\nfinalizacion: calificar\n"
        doc = doc_itinerario(tmp_path, extra, "t.md", "tarea", "Tarea")
        payload = publicar.payload_finalizacion(doc)
        assert (payload["completionusegrade"], payload["completionsubmit"]) == ("1", "0")

    def test_fecha_esperada(self, tmp_path):
        doc = doc_itinerario(tmp_path, "finalizacion: ver\nfecha_esperada: 2026-11-20\n")
        payload = publicar.payload_finalizacion(doc)
        assert payload["completionexpected[enabled]"] == "1"
        assert [payload[f"completionexpected[{p}]"] for p in ("year", "month", "day")] == [
            "2026",
            "11",
            "20",
        ]

    def test_sin_declarar_no_envia_nada(self, tmp_path):
        assert publicar.payload_finalizacion(documento(tmp_path)) == {}
        assert publicar.payload_disponibilidad(documento(tmp_path), {}) == {}


class TestPayloadDisponibilidad:
    def test_fechas_y_dependencias_compactas_con_y(self, tmp_path):
        doc = doc_itinerario(
            tmp_path,
            "restricciones:\n  desde: 2026-10-12\n  hasta: 2026-11-01\n  completar: [test1.md]\n",
        )
        texto = publicar.payload_disponibilidad(doc, {"test1.md": 64})["availabilityconditionsjson"]
        datos = json.loads(texto)
        assert datos["op"] == "&"
        assert [c["type"] for c in datos["c"]] == ["date", "date", "completion"]
        assert [c.get("d") for c in datos["c"][:2]] == [">=", "<"]
        assert datos["c"][2] == {"type": "completion", "cm": 64, "e": 1}
        assert datos["showc"] == [True, True, True]
        assert " " not in texto  # compacto, como lo guarda Moodle

    def test_ocultar_si_no_cumple(self, tmp_path):
        doc = doc_itinerario(
            tmp_path, "restricciones:\n  completar: [test1.md]\n  ocultar_si_no_cumple: true\n"
        )
        texto = publicar.payload_disponibilidad(doc, {"test1.md": 64})["availabilityconditionsjson"]
        assert json.loads(texto)["showc"] == [False]

    def test_vacias_quitan(self, tmp_path):
        doc = doc_itinerario(tmp_path, "restricciones: {}\n")
        assert publicar.payload_disponibilidad(doc, {}) == {"availabilityconditionsjson": ""}

    def test_la_fecha_es_un_instante_utc(self, tmp_path):
        doc = doc_itinerario(tmp_path, "restricciones:\n  desde: 2026-10-12\n")
        datos = json.loads(publicar.payload_disponibilidad(doc, {})["availabilityconditionsjson"])
        assert datos["c"][0]["t"] == int(doc.restricciones.desde.timestamp())  # type: ignore[union-attr]


class TestValidadorDeDisponibilidad:
    """El último control antes de enviar: aunque se construya a mano, solo fecha y finalización."""

    @pytest.mark.parametrize(
        "condicion",
        [
            {"type": "group", "id": 1},
            {"type": "group"},
            {"type": "grouping", "id": 1},
            {"type": "profile", "cf": "email", "op": "contains", "v": "x"},
            {"type": "grade", "id": 1, "min": 5},
            {"type": "otro"},
            {"type": "date", "d": ">=", "t": 1, "extra": 1},
            {"type": "date", "d": "=", "t": 1},
            {"type": "date", "d": ">=", "t": True},
            {"type": "date", "d": ">=", "t": "1"},
            {"type": "completion", "cm": 5, "e": 0},
            {"type": "completion", "cm": 5, "e": 2},
            {"type": "completion", "cm": "5", "e": 1},
            {"c": [], "op": "&", "showc": []},
            "texto",
            None,
        ],
    )
    def test_rechaza_lo_que_no_es_de_tiza(self, condicion):
        texto = json.dumps({"op": "&", "c": [condicion], "showc": [True]})
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.validar_disponibilidad(texto)
        assert exc.value.codigo == "RESTRICCION_INVALIDA"

    @pytest.mark.parametrize(
        "datos",
        [
            {"op": "|", "show": True, "c": [{"type": "date", "d": ">=", "t": 1}]},
            {"op": "&", "c": [{"type": "date", "d": ">=", "t": 1}], "showc": [True], "x": 1},
            {"op": "&", "c": [{"type": "date", "d": ">=", "t": 1}], "showc": []},
            {"op": "&", "c": [{"type": "date", "d": ">=", "t": 1}], "showc": ["si"]},
            {"op": "&", "c": [], "showc": []},
            {"op": "&", "c": [{"op": "&", "c": [], "showc": []}], "showc": [True]},
            [],
        ],
    )
    def test_rechaza_estructuras_raras(self, datos):
        with pytest.raises(ErrorPublicacion):
            publicar.validar_disponibilidad(json.dumps(datos))

    def test_rechaza_json_roto_y_acepta_vacio_y_lo_valido(self):
        with pytest.raises(ErrorPublicacion):
            publicar.validar_disponibilidad("{no")
        publicar.validar_disponibilidad("")
        publicar.validar_disponibilidad(
            json.dumps({"op": "&", "c": [{"type": "completion", "cm": 5, "e": 1}], "showc": [True]})
        )

    @pytest.mark.parametrize(
        ("texto", "es_de_tiza"),
        [
            ("", True),
            ('{"op":"&","c":[{"type":"date","d":">=","t":1}],"showc":[true]}', True),
            ('{"op":"&","c":[{"type":"completion","cm":5,"e":2}],"showc":[true]}', True),
            ('{"op":"&","c":[{"type":"group","id":1}],"showc":[true]}', False),
            (
                '{"op":"&","c":[{"type":"date","d":">=","t":1},{"type":"profile"}],"showc":[true,true]}',
                False,
            ),
            ('{"op":"|","show":true,"c":[{"type":"date","d":">=","t":1}]}', False),
            ('{"op":"&","c":[{"op":"&","c":[{"type":"date"}]}],"showc":[true]}', False),
            ("no es json", False),
            ("[]", False),
        ],
    )
    def test_reconoce_las_restricciones_ajenas(self, texto, es_de_tiza):
        assert publicar.es_disponibilidad_de_tiza(texto) is es_de_tiza


class TestPublicarConItinerario:
    def test_pagina_nueva_con_finalizacion_y_restriccion(self, tmp_path):
        doc = doc_itinerario(tmp_path, "finalizacion: ver\nrestricciones:\n  desde: 2026-10-12\n")
        moodle = aula_con()
        resultado = publicar_itinerario(moodle, doc)
        assert resultado.accion == "creada"
        formulario = moodle.formularios[resultado.cmid]
        assert formulario["completion"] == "2" and formulario["completionview"] == "1"
        assert json.loads(formulario["availabilityconditionsjson"])["c"][0]["type"] == "date"

    def test_sin_declarar_no_toca_lo_que_hay(self, tmp_path):
        moodle = aula_con([{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}])
        moodle.formularios[55] = {
            "name": "Repaso",
            "visible": "1",
            "completion": "2",
            "completionview": "1",
            "availabilityconditionsjson": '{"op":"&","c":[{"type":"group","id":1}],"showc":[true]}',
        }
        antes = dict(moodle.formularios[55])
        publicar_itinerario(moodle, documento(tmp_path))
        for campo in ("completion", "completionview", "availabilityconditionsjson"):
            assert moodle.formularios[55][campo] == antes[campo]

    def test_restricciones_vacias_quitan_las_de_tiza(self, tmp_path):
        moodle = aula_con([{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}])
        moodle.formularios[55] = {
            "name": "Repaso",
            "availabilityconditionsjson": '{"op":"&","c":[{"type":"date","d":">=","t":1}],"showc":[true]}',
        }
        publicar_itinerario(moodle, doc_itinerario(tmp_path, "restricciones: {}\n"))
        assert moodle.formularios[55]["availabilityconditionsjson"] == ""

    def test_finalizacion_ninguna_desactiva(self, tmp_path):
        moodle = aula_con([{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}])
        moodle.formularios[55] = {"name": "Repaso", "completion": "2", "completionview": "1"}
        publicar_itinerario(moodle, doc_itinerario(tmp_path, "finalizacion: ninguna\n"))
        assert moodle.formularios[55]["completion"] == "0"

    def test_restriccion_ajena_no_envia_nada(self, tmp_path):
        moodle = aula_con([{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}])
        ajena = '{"op":"&","c":[{"type":"group","id":1}],"showc":[true]}'
        moodle.formularios[55] = {"name": "Repaso", "availabilityconditionsjson": ajena}
        doc = doc_itinerario(tmp_path, "restricciones:\n  desde: 2026-10-12\n")
        with pytest.raises(ErrorPublicacion) as exc:
            publicar_itinerario(moodle, doc)
        assert exc.value.codigo == "RESTRICCION_AJENA"
        assert moodle.formularios[55]["availabilityconditionsjson"] == ajena
        assert not any(ll[0] == "actualizar" for ll in moodle.llamadas)  # ni el contenido
        assert "group" not in str(exc.value.detalle)

    def test_finalizacion_sin_restricciones_no_mira_la_ajena(self, tmp_path):
        moodle = aula_con([{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}])
        ajena = '{"op":"&","c":[{"type":"group","id":1}],"showc":[true]}'
        moodle.formularios[55] = {"name": "Repaso", "availabilityconditionsjson": ajena}
        publicar_itinerario(moodle, doc_itinerario(tmp_path, "finalizacion: manual\n"))
        assert moodle.formularios[55]["availabilityconditionsjson"] == ajena
        assert moodle.formularios[55]["completion"] == "1"

    def test_finalizacion_bloqueada_no_toca_nada(self, tmp_path):
        moodle = aula_con([{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}])
        moodle.formularios[55] = {"name": "Repaso", "completion": "2", "completionview": "1"}
        moodle.bloqueadas.add(55)
        doc = doc_itinerario(tmp_path, "finalizacion: manual\n")
        with pytest.raises(ErrorPublicacion) as exc:
            publicar_itinerario(moodle, doc)
        assert exc.value.codigo == "FINALIZACION_BLOQUEADA"
        assert not any(ll[0] == "actualizar" for ll in moodle.llamadas)
        assert moodle.formularios[55]["completion"] == "2"

    def test_bloqueada_pero_igual_a_lo_pedido_sigue_adelante(self, tmp_path):
        moodle = aula_con([{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}])
        moodle.formularios[55] = {"name": "Repaso", "completion": "2", "completionview": "1"}
        moodle.bloqueadas.add(55)
        doc = doc_itinerario(tmp_path, "finalizacion: ver\nrestricciones:\n  desde: 2026-10-12\n")
        publicar_itinerario(moodle, doc)
        assert json.loads(moodle.formularios[55]["availabilityconditionsjson"])["c"]

    def test_nunca_se_envia_el_desbloqueo(self, tmp_path):
        moodle = aula_con()
        publicar_itinerario(moodle, doc_itinerario(tmp_path, "finalizacion: ver\n"))
        enviados = [ll[2] for ll in moodle.llamadas if ll[0] in ("crear", "actualizar")]
        assert all("completionunlocked" not in str(p) for p in enviados)

    def test_curso_sin_finalizacion_en_una_actividad_nueva(self, tmp_path):
        moodle = aula_con(sin_finalizacion=True)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar_itinerario(moodle, doc_itinerario(tmp_path, "finalizacion: ver\n"))
        assert exc.value.codigo == "FINALIZACION_DESACTIVADA"
        assert exc.value.cmid is not None  # el contenido ya está: el informe lo cuenta

    def test_curso_sin_finalizacion_en_una_actividad_existente_no_escribe(self, tmp_path):
        moodle = aula_con(
            [{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}], sin_finalizacion=True
        )
        moodle.formularios[55] = {"name": "Repaso"}
        with pytest.raises(ErrorPublicacion) as exc:
            publicar_itinerario(moodle, doc_itinerario(tmp_path, "finalizacion: ver\n"))
        assert exc.value.codigo == "FINALIZACION_DESACTIVADA"
        assert not any(ll[0] == "actualizar" for ll in moodle.llamadas)

    def test_restricciones_sin_finalizacion_funcionan_en_un_curso_sin_ella(self, tmp_path):
        moodle = aula_con(sin_finalizacion=True)
        resultado = publicar_itinerario(
            moodle, doc_itinerario(tmp_path, "restricciones:\n  desde: 2026-10-12\n")
        )
        assert json.loads(moodle.formularios[resultado.cmid]["availabilityconditionsjson"])

    def test_verificacion_si_el_aula_no_guarda_la_restriccion(self, tmp_path):
        class AulaQueIgnora(MoodleFalso):
            def _admitido(self, cmid, payload):
                return {k: v for k, v in payload.items() if k != "availabilityconditionsjson"}

        moodle = AulaQueIgnora(
            secciones=[{"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []}]
        )
        with pytest.raises(ErrorPublicacion) as exc:
            publicar_itinerario(
                moodle, doc_itinerario(tmp_path, "restricciones:\n  desde: 2026-10-12\n")
            )
        assert exc.value.codigo == "ITINERARIO_NO_APLICADO"

    def test_dependencia_sin_cmid(self, tmp_path):
        doc = doc_itinerario(tmp_path, "restricciones:\n  completar: [test1.md]\n")
        with pytest.raises(ErrorPublicacion) as exc:
            publicar_itinerario(aula_con(), doc, {})
        assert exc.value.codigo == "DEPENDENCIA_NO_PUBLICADA"
        assert exc.value.detalle == "test1.md"

    def test_la_restriccion_lleva_el_cmid_de_la_dependencia(self, tmp_path):
        doc = doc_itinerario(tmp_path, "restricciones:\n  completar: [test1.md]\n")
        moodle = aula_con()
        resultado = publicar_itinerario(moodle, doc, {"test1.md": 64})
        texto = moodle.formularios[resultado.cmid]["availabilityconditionsjson"]
        assert json.loads(texto)["c"] == [{"type": "completion", "cm": 64, "e": 1}]

    def test_lo_leido_del_aula_no_sale_en_el_resultado(self, tmp_path):
        moodle = aula_con([{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}])
        moodle.formularios[55] = {"name": "Repaso", "availabilityconditionsjson": ""}
        resultado = publicar_itinerario(moodle, doc_itinerario(tmp_path, "finalizacion: ver\n"))
        assert "itinerario" not in str(resultado) and "completion" not in str(resultado)


def test_campo_de_un_grupo_de_botones_de_opcion_es_el_marcado():
    from bs4 import BeautifulSoup

    html = (
        '<input type="radio" name="completion" value="0">'
        '<input type="radio" name="completion" value="1">'
        '<input type="radio" name="completion" value="2" checked>'
    )
    assert publicar._campo(BeautifulSoup(html, "html.parser"), "completion") == "2"
    sin_marcar = html.replace(" checked", "")
    assert publicar._campo(BeautifulSoup(sin_marcar, "html.parser"), "completion") is None


class _RespuestaFalsa:
    def __init__(self, url, texto="", estado=200):
        self.url = url
        self.text = texto
        self.status_code = estado
        self.headers = {}


class _SesionDeCookies:
    def __init__(self, url_final, texto):
        self.cookies = requests.cookies.RequestsCookieJar()
        self.pedidas = []
        self._url_final = url_final
        self._texto = texto

    def get(self, url, **opciones):
        self.pedidas.append(url)
        return _RespuestaFalsa(self._url_final or url, self._texto)


def _auth_con_sesion(monkeypatch, sesion):
    class Compat:
        def extract_sesskey(self, texto):
            return "clave" if "sesskey" in texto else None

    class AuthFalsa:
        def __init__(self, base_url, usuario, password, **_):
            self.base_url = base_url.rstrip("/")
            self.session = sesion
            self.compatibility = Compat()
            self.visto = (usuario, password)

    monkeypatch.setattr(publicar.py_auth, "MoodleAuth", AuthFalsa)
    monkeypatch.setattr(
        publicar,
        "detect_moodle_compatibility",
        lambda *a, **k: types.SimpleNamespace(version="4.5", strategy="estrategia"),
    )


class TestAutenticacionConCookies:
    URL = "https://aula.example.org/centro"

    def test_entra_con_las_cookies_y_sin_contrasena(self, monkeypatch):
        sesion = _SesionDeCookies(None, "sesskey")
        _auth_con_sesion(monkeypatch, sesion)
        aula = publicar.autenticar_con_cookies(
            self.URL, [("MoodleSession", "abc", "aula.example.org")]
        )
        assert aula.sesskey == "clave"
        assert sesion.pedidas == [f"{self.URL}/my/"]
        galleta = next(iter(sesion.cookies))
        assert (galleta.name, galleta.domain, galleta.secure) == (
            "MoodleSession",
            "aula.example.org",
            True,
        )
        assert sesion.webservice_token is None and sesion.sesskey == "clave"

    def test_la_cookie_del_dominio_padre_llega_al_aula_y_a_nadie_mas(self, monkeypatch):
        sesion = _SesionDeCookies(None, "sesskey")
        _auth_con_sesion(monkeypatch, sesion)
        publicar.autenticar_con_cookies(
            self.URL,
            [
                ("MoodleSession", "abc", "example.org"),
                ("afinidad", "x", "aula.example.org"),
                ("idp", "y", "idp.example.org"),
                ("ajena", "z", "malexample.org"),
            ],
        )
        enviadas = {}
        for destino in ("https://aula.example.org/centro/", "https://otra.example.org/"):
            peticion = urllib.request.Request(destino)
            sesion.cookies.add_cookie_header(peticion)
            enviadas[destino] = peticion.get_header("Cookie", "")
        assert sorted(enviadas["https://aula.example.org/centro/"].split("; ")) == [
            "MoodleSession=abc",
            "afinidad=x",
        ]
        assert enviadas["https://otra.example.org/"] == "MoodleSession=abc"  # el dominio padre
        assert "idp" not in str(enviadas) and "ajena" not in str(enviadas)

    def test_si_el_aula_redirige_al_login_no_hay_sesion(self, monkeypatch):
        sesion = _SesionDeCookies(f"{self.URL}/login/index.php", "sesskey")
        _auth_con_sesion(monkeypatch, sesion)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.autenticar_con_cookies(
                self.URL, [("MoodleSession", "caducada", "aula.example.org")]
            )
        assert exc.value.codigo == "SESION_NO_INICIADA"

    def test_sin_sesskey(self, monkeypatch):
        _auth_con_sesion(monkeypatch, _SesionDeCookies(None, "nada"))
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.autenticar_con_cookies(
                self.URL, [("MoodleSession", "abc", "aula.example.org")]
            )
        assert exc.value.codigo == "SESION_SIN_SESSKEY"

    def test_la_guardia_de_destino_sigue_montada(self, monkeypatch):
        # Sin parchear MoodleAuth: la sesión real lleva el adaptador que fija el servidor.
        sesion = publicar.py_auth.MoodleAuth(self.URL, "", "").session
        adaptador = sesion.get_adapter("https://aula.example.org/")
        assert isinstance(adaptador, publicar.AdaptadorAula)
        assert sesion.headers["User-Agent"] == publicar.USER_AGENT

    def test_destino_no_permitido(self, monkeypatch):
        class Sesion(_SesionDeCookies):
            def get(self, url, **opciones):
                raise publicar.DestinoNoPermitido("otro servidor")

        _auth_con_sesion(monkeypatch, Sesion(None, ""))
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.autenticar_con_cookies(
                self.URL, [("MoodleSession", "abc", "aula.example.org")]
            )
        assert exc.value.codigo == "DESTINO_NO_PERMITIDO"


class TestAutenticarCon:
    def test_contrasena_va_por_el_login_normal(self, monkeypatch):
        vistas = []
        monkeypatch.setattr(
            publicar, "autenticar", lambda url, usuario, password: vistas.append(password) or "m"
        )
        monkeypatch.setattr(
            publicar, "autenticar_con_cookies", lambda *a: pytest.fail("no son cookies")
        )
        assert publicar.autenticar_con("https://a", "u", publicar.Contrasena("secreta")) == "m"
        assert vistas == ["secreta"]

    def test_cookies_van_por_la_sesion_ya_iniciada(self, monkeypatch):
        monkeypatch.setattr(publicar, "autenticar", lambda *a: pytest.fail("no es contraseña"))
        monkeypatch.setattr(publicar, "autenticar_con_cookies", lambda url, c: ("m", list(c)))
        resultado = publicar.autenticar_con("https://a", "u", publicar.Cookies([("S", "x", "a")]))
        assert resultado == ("m", [("S", "x", "a")])

    def test_las_acreditaciones_no_se_ven_en_el_repr(self):
        assert "secreta" not in repr(publicar.Contrasena("secreta"))
        assert "valor" not in repr(publicar.Cookies([("MoodleSession", "valor", "a")]))


class _SesionQueAnotaElCierre:
    def __init__(self, falla=False):
        self.peticiones = []
        self._falla = falla

    def get(self, url, **opciones):
        self.peticiones.append((url, opciones))
        if self._falla:
            raise requests.ConnectionError("sin red")
        return _Respuesta(303, "https://idp.example.org/logout")


class TestCerrarLaSesionDelAula:
    def test_pide_el_cierre_con_la_sesskey_y_sin_seguir_redirecciones(self):
        sesion = _SesionQueAnotaElCierre()
        publicar.Moodle("https://aula.example.org/centro", sesion, "clave", pausa=0).cerrar()
        [(url, opciones)] = sesion.peticiones
        assert url == "https://aula.example.org/centro/login/logout.php"
        assert opciones["params"] == {"sesskey": "clave"}
        assert opciones["allow_redirects"] is False  # con SAML/CAS no se sale del aula

    def test_nunca_lanza(self):
        sesion = _SesionQueAnotaElCierre(falla=True)
        publicar.Moodle("https://aula.example.org", sesion, "clave", pausa=0).cerrar()
        assert len(sesion.peticiones) == 1

    def test_cerrar_aula_tolera_un_adaptador_sin_cierre_o_que_falla(self):
        publicar.cerrar_aula(object())

        class Rompe:
            def cerrar(self):
                raise RuntimeError("no")

        publicar.cerrar_aula(Rompe())

    def test_sesion_del_aula_cierra_al_salir_y_con_error(self):
        class Aula:
            cerradas = 0

            def cerrar(self):
                self.cerradas += 1

        aula = Aula()
        with publicar.sesion_del_aula(aula) as dentro:
            assert dentro is aula
        assert aula.cerradas == 1
        with pytest.raises(ValueError), publicar.sesion_del_aula(aula):
            raise ValueError("fallo")
        assert aula.cerradas == 2


class _SesionSubidas:
    """Responde a cada subida con la siguiente respuesta de la lista."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.subidas = 0

    def post(self, *a, **k):
        self.subidas += 1
        return _RespuestaJson(self.respuestas.pop(0))

    def get(self, url, allow_redirects=True, timeout=None):
        return _Respuesta(200)


_LIMITE = {"error": "Ha alcanzado el límite… espere", "errorcode": "maxdraftitemids"}


class TestLimiteDeBorradores:
    """Espiga 6: el aula frena las subidas cuando se agotan sus áreas de borrador."""

    def _subir(self, monkeypatch, tmp_path, respuestas):
        monkeypatch.setattr(publicar.py_draftfile, "detect_upload_repo", lambda *a: 5)
        fichero = tmp_path / "foto.png"
        fichero.write_bytes(b"png")
        sesion = _SesionSubidas(respuestas)
        dormidas: list[float] = []
        moodle = publicar.Moodle("https://aula", sesion, "clave", pausa=0, dormir=dormidas.append)
        try:
            return moodle.subir(1, 2, fichero, 77), sesion, dormidas
        except ErrorPublicacion as exc:
            return exc, sesion, dormidas

    def test_espera_y_repite_la_subida(self, monkeypatch, tmp_path):
        resultado, sesion, dormidas = self._subir(
            monkeypatch, tmp_path, [_LIMITE, _LIMITE, {"id": 77, "filename": "foto.png"}]
        )
        assert resultado == (77, "foto.png")
        assert sesion.subidas == 3
        assert dormidas == [5.0, 10.0]

    def test_si_no_basta_pide_esperar_al_docente(self, monkeypatch, tmp_path):
        resultado, sesion, dormidas = self._subir(monkeypatch, tmp_path, [_LIMITE] * 5)
        assert isinstance(resultado, ErrorPublicacion)
        assert resultado.codigo == "AULA_PIDE_ESPERA"
        assert resultado.detalle == ""
        assert sesion.subidas == 5
        assert dormidas == list(publicar.ESPERAS_LIMITE_BORRADORES)

    def test_otro_error_no_espera(self, monkeypatch, tmp_path):
        otro = {"error": "límite del área", "errorcode": "maxareabytes"}
        resultado, sesion, dormidas = self._subir(monkeypatch, tmp_path, [otro])
        assert isinstance(resultado, ErrorPublicacion)
        assert resultado.codigo == "ERROR_SUBIDA"
        assert sesion.subidas == 1
        assert dormidas == []

    def test_reconoce_el_codigo_y_no_el_texto(self):
        assert publicar._pide_espera(_RespuestaJson(_LIMITE))
        assert not publicar._pide_espera(_RespuestaJson({"error": "limit, wait"}))
        assert not publicar._pide_espera(_RespuestaJson(["maxdraftitemids"]))
        assert not publicar._pide_espera(None)


# --- Copia de seguridad del curso: las etapas de backup.php contra una sesión falsa ---------

AJUSTES_DE_USUARIO = (
    "users",
    "anonymize",
    "role_assignments",
    "comments",
    "badges",
    "calendarevents",
    "userscompletion",
    "logs",
    "grade_histories",
    "xapistate",
    "groups",
)
URL_AULA = "https://aula.example.org/centro"


class _RespuestaCopia:
    def __init__(self, texto="", status=200, cuerpo=b"", cabeceras=None, datos=None):
        self.text = texto
        self.status_code = status
        self.headers = cabeceras or {}
        self._cuerpo = cuerpo
        self._datos = datos if datos is not None else {}
        self.cerrada = False

    def iter_content(self, chunk_size=1):
        for inicio in range(0, len(self._cuerpo), chunk_size):
            yield self._cuerpo[inicio : inicio + chunk_size]

    def json(self):
        return self._datos

    def close(self):
        self.cerrada = True


def _pagina_con(formulario: str) -> str:
    return f"<html><body>{formulario}</body></html>"


def _etapa(extras: str, accion: str = f"{URL_AULA}/backup/backup.php") -> str:
    return _pagina_con(
        f'<form action="{accion}" method="post">'
        '<input type="hidden" name="sesskey" value="clave">'
        '<input type="hidden" name="backup" value="1">'
        f"{extras}"
        '<input type="submit" name="cancel" value="Cancelar">'
        '<input type="submit" name="submitbutton" value="Siguiente"></form>'
    )


def _ajustes_marcados(bloqueados=()) -> str:
    """Cada ajuste de usuario como lo trae mform: un hidden a 0 y la casilla, marcada."""
    html = ""
    for ajuste in (*AJUSTES_DE_USUARIO, "activities", "files"):
        bloqueo = " disabled" if ajuste in bloqueados else ""
        html += (
            f'<input type="hidden" name="setting_root_{ajuste}" value="0">'
            f'<input type="checkbox" name="setting_root_{ajuste}" value="1" checked{bloqueo}>'
        )
    html += (
        '<input type="hidden" name="setting_section_section_7_userinfo" value="0">'
        '<input type="checkbox" name="setting_section_section_7_userinfo" value="1" checked>'
        '<input type="checkbox" name="setting_activity_page_501_userinfo" value="1" checked>'
    )
    return html


class _SesionCopia:
    """El aula: backup.php en tres etapas, la zona de copias del docente y su gestor de ficheros."""

    def __init__(
        self,
        cuerpo=b"MBZ" * 10,
        sin_formulario=False,
        no_aparece=False,
        cabeceras=None,
        al_borrar_queda=False,
        sin_filename=False,
    ):
        self.cuerpo = cuerpo
        self.sin_formulario = sin_formulario
        self.no_aparece = no_aparece
        self.cabeceras = cabeceras
        self.al_borrar_queda = al_borrar_queda
        self.sin_filename = sin_filename
        self.posts: list[tuple[str, list[tuple[str, str]]]] = []
        self.borrados_ajax: list[dict] = []
        self.guardado_edicion: list[tuple[str, str]] | None = None
        self.nombres_en_el_area: list[str] = []
        self.descargas: list[_RespuestaCopia] = []
        self._etapa = 0

    def get(self, url, params=None, timeout=None, stream=False, allow_redirects=True):
        if url.endswith("/backup/backup.php"):
            if self.sin_formulario:
                return _RespuestaCopia("<html><body>Sin permiso</body></html>")
            self._etapa = 1
            return _RespuestaCopia(_etapa(_ajustes_marcados(bloqueados=("users",))))
        if url.endswith("/backup/restorefile.php"):
            enlaces = "".join(
                f'<a href="{URL_AULA}/pluginfile.php/55/user/backup/0/{nombre}?forcedownload=1">'
                f"{nombre}</a>"
                for nombre in self.nombres_en_el_area
            )
            enlaces += '<a href="/pluginfile.php/55/course/backup/0/ajena.mbz">ajena</a>'
            return _RespuestaCopia(_pagina_con(enlaces))
        if "/user/backup/" in url:
            respuesta = _RespuestaCopia(cuerpo=self.cuerpo, cabeceras=self.cabeceras)
            self.descargas.append(respuesta)
            return respuesta
        if url.endswith("/backup/backupfilesedit.php"):
            return _RespuestaCopia(
                _pagina_con(
                    f'<form action="{URL_AULA}/backup/backupfilesedit.php" method="post">'
                    '<input type="hidden" name="sesskey" value="clave">'
                    '<input type="hidden" name="files_filemanager" value="7777">'
                    '<input type="submit" name="submitbutton" value="Guardar"></form>'
                )
            )
        return _RespuestaCopia("<html></html>")  # /my/ y lo demás: la sesión sigue viva

    def post(self, url, data=None, params=None, timeout=None):
        if url.endswith("/backup/backup.php"):
            pares = list(data)
            self.posts.append((url, pares))
            self._etapa += 1
            if self._etapa == 2:
                return _RespuestaCopia(_etapa(_ajustes_marcados()))
            if self._etapa == 3:
                return _RespuestaCopia(
                    _etapa(
                        '<input type="hidden" name="setting_root_users" value="1">'
                        + (
                            ""
                            if self.sin_filename
                            else '<input type="text" name="setting_root_filename" value="c.mbz">'
                        )
                    )
                )
            nombre = dict(pares).get("setting_root_filename", "")
            if not self.no_aparece:
                self.nombres_en_el_area.append(nombre)
            return _RespuestaCopia(
                _pagina_con(f'<form action="{URL_AULA}/backup/restorefile.php"></form>')
            )
        if url.endswith("/repository/draftfiles_ajax.php"):
            self.borrados_ajax.append({"params": params, **data})
            return _RespuestaCopia(datos={"filepath": "/"})
        if url.endswith("/backup/backupfilesedit.php"):
            self.guardado_edicion = list(data)
            if not self.al_borrar_queda:
                borrados = {b["filename"] for b in self.borrados_ajax}
                self.nombres_en_el_area = [n for n in self.nombres_en_el_area if n not in borrados]
            return _RespuestaCopia()
        raise AssertionError(url)


def _moodle_de_copia(sesion, monkeypatch=None, epoch=1792000000):
    moodle = publicar.Moodle(URL_AULA, sesion, "clave", pausa=0, dormir=lambda _s: None)
    moodle.contexto = lambda curso_id: 999
    if monkeypatch is not None:
        reloj = types.SimpleNamespace(time=lambda: float(epoch), monotonic=publicar.time.monotonic)
        monkeypatch.setattr(publicar, "time", reloj)
    return moodle


class TestHacerCopia:
    def test_copia_fuerza_sin_usuarios(self, tmp_path, monkeypatch):
        sesion = _SesionCopia()
        moodle = _moodle_de_copia(sesion, monkeypatch)
        destino = tmp_path / "descarga.tmp"
        hecha = moodle.hacer_copia(2, destino, 1000)
        assert (hecha.bytes, destino.read_bytes()) == (30, b"MBZ" * 10)
        assert len(sesion.posts) == 3  # tres etapas
        for _url, pares in sesion.posts:
            enviado = [valor for nombre, valor in pares]
            nombres = [nombre for nombre, _valor in pares]
            for ajuste in AJUSTES_DE_USUARIO:
                # Una sola vez y a 0, aunque el formulario la traiga marcada, bloqueada o a 1.
                assert nombres.count(f"setting_root_{ajuste}") <= 1, ajuste
                if f"setting_root_{ajuste}" in nombres:
                    assert dict(pares)[f"setting_root_{ajuste}"] == "0", ajuste
            assert dict(pares).get("setting_section_section_7_userinfo", "0") == "0"
            assert dict(pares).get("setting_activity_page_501_userinfo", "0") == "0"
            assert "cancel" not in nombres and enviado[-1] == "1"
        primera = dict(sesion.posts[0][1])
        assert primera["setting_root_users"] == "0"  # la bloqueada también
        assert primera["setting_root_activities"] == "1"  # lo demás sigue como venía
        ultima = dict(sesion.posts[-1][1])
        assert ultima["setting_root_users"] == "0"  # el hidden a 1 de la última etapa, forzado

    def test_copia_nombre_unico(self, tmp_path, monkeypatch):
        sesion = _SesionCopia()
        moodle = _moodle_de_copia(sesion, monkeypatch)
        # Mismo segundo y, por casualidad, el mismo sufijo aleatorio: el nombre no se repite.
        sufijos = iter(["aaaaaa", "aaaaaa", "bbbbbb", "aaaaaa", "cccccc"])
        monkeypatch.setattr(
            publicar, "secrets", types.SimpleNamespace(token_hex=lambda n: next(sufijos))
        )
        primera = moodle.hacer_copia(2, tmp_path / "a.tmp", 1000)
        sesion._etapa = 0
        segunda = moodle.hacer_copia(2, tmp_path / "b.tmp", 1000)
        assert primera.nombre == "tiza-2-1792000000-aaaaaa-nu.mbz"
        assert segunda.nombre == "tiza-2-1792000000-bbbbbb-nu.mbz"
        ultimas = [dict(pares)["setting_root_filename"] for _u, pares in sesion.posts[2::3]]
        assert ultimas == [primera.nombre, segunda.nombre]
        # Aunque la primera ya no esté en el aula, esta sesión no repite su nombre.
        sesion.nombres_en_el_area.clear()
        sesion._etapa = 0
        assert moodle.hacer_copia(2, tmp_path / "c.tmp", 1000).nombre.endswith("-cccccc-nu.mbz")

    def test_el_nombre_propio_tiene_el_patron_con_un_sufijo_aleatorio(self, tmp_path, monkeypatch):
        sesion = _SesionCopia()
        moodle = _moodle_de_copia(sesion, monkeypatch)
        nombres = {moodle.hacer_copia(2, tmp_path / "x.tmp", 1000).nombre}
        sesion._etapa = 0
        nombres.add(moodle.hacer_copia(2, tmp_path / "y.tmp", 1000).nombre)
        assert len(nombres) == 2
        for nombre in nombres:
            assert re.fullmatch(r"tiza-2-1792000000-[0-9a-f]{6}-nu\.mbz", nombre)

    def test_sin_formulario_no_hay_permiso(self, tmp_path):
        moodle = _moodle_de_copia(_SesionCopia(sin_formulario=True))
        with pytest.raises(ErrorPublicacion) as exc:
            moodle.hacer_copia(2, tmp_path / "d.tmp", 1000)
        assert exc.value.codigo == "COPIA_NO_PERMITIDA"
        assert not (tmp_path / "d.tmp").exists()

    def test_si_la_sesion_caduco_no_es_falta_de_permiso(self, tmp_path):
        sesion = _SesionCopia(sin_formulario=True)
        original = sesion.get

        def get(url, **opciones):
            if url.endswith("/my/"):
                return types.SimpleNamespace(
                    status_code=303, headers={"Location": f"{URL_AULA}/login/index.php"}
                )
            return original(url, **opciones)

        sesion.get = get
        moodle = _moodle_de_copia(sesion)
        with pytest.raises(ErrorPublicacion) as exc:
            moodle.hacer_copia(2, tmp_path / "d.tmp", 1000)
        assert exc.value.codigo == "SESION_CADUCADA"

    def test_una_etapa_que_responde_con_error_no_espera_diez_minutos(self, tmp_path):
        sesion = _SesionCopia()
        original = sesion.post

        def post(url, **opciones):
            respuesta = original(url, **opciones)
            if len(sesion.posts) == 2:
                respuesta.status_code = 500
            return respuesta

        sesion.post = post
        esperas: list[float] = []
        moodle = _moodle_de_copia(sesion)
        moodle._dormir = esperas.append
        with pytest.raises(ErrorPublicacion) as exc:
            moodle.hacer_copia(2, tmp_path / "j.tmp", 1000)
        assert exc.value.codigo == "COPIA_FALLIDA"
        assert esperas == [] and len(sesion.posts) == 2

    def test_un_formulario_que_no_avanza_es_fallido(self, tmp_path):
        sesion = _SesionCopia()
        original = sesion.get

        def get(url, **opciones):
            if url.endswith("/backup/backup.php"):
                return _RespuestaCopia(
                    _pagina_con(
                        f'<form action="{URL_AULA}/backup/backup.php">'
                        '<input type="submit" name="cancel" value="Cancelar"></form>'
                    )
                )
            return original(url, **opciones)

        sesion.get = get
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_copia(sesion).hacer_copia(2, tmp_path / "k.tmp", 1000)
        assert exc.value.codigo == "COPIA_FALLIDA"
        assert sesion.posts == []  # nunca se pulsa «cancelar» por error

    def test_sin_nombre_propio_falla_en_el_momento_sin_esperar(self, tmp_path):
        sesion = _SesionCopia(sin_filename=True)
        esperas: list[float] = []
        moodle = _moodle_de_copia(sesion)
        moodle._dormir = esperas.append
        with pytest.raises(ErrorPublicacion) as exc:
            moodle.hacer_copia(2, tmp_path / "l.tmp", 1000)
        assert exc.value.codigo == "COPIA_FALLIDA"
        assert esperas == []  # ni diez minutos ni una sola mirada al área
        assert exc.value.queda_en_el_aula is True  # con el nombre de Moodle, no se puede quitar

    def test_una_descarga_que_es_html_es_sesion_caducada_y_no_se_escribe(self, tmp_path):
        cabeceras = {"Content-Type": "text/html; charset=utf-8"}
        sesion = _SesionCopia(cuerpo=b"<html>entrada</html>", cabeceras=cabeceras)
        destino = tmp_path / "m.tmp"
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_copia(sesion).hacer_copia(2, destino, 1000)
        assert exc.value.codigo == "SESION_CADUCADA"
        assert not destino.exists()
        assert sesion.nombres_en_el_area == []  # y la copia no se queda en el aula

    def test_una_descarga_que_acaba_en_la_pagina_de_entrada_es_sesion_caducada(self, tmp_path):
        sesion = _SesionCopia()
        original = sesion.get

        def get(url, **opciones):
            respuesta = original(url, **opciones)
            if "/user/backup/" in url:
                respuesta.url = f"{URL_AULA}/login/index.php"
            return respuesta

        sesion.get = get
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_copia(sesion).hacer_copia(2, tmp_path / "n.tmp", 1000)
        assert exc.value.codigo == "SESION_CADUCADA"
        assert not (tmp_path / "n.tmp").exists()

    def test_el_error_dice_si_la_copia_queda_en_el_aula(self, tmp_path):
        # Demasiado grande y se pudo quitar: no queda.
        grande = _SesionCopia(cuerpo=b"x" * 5000)
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_copia(grande).hacer_copia(2, tmp_path / "o.tmp", 1000)
        assert (exc.value.codigo, exc.value.queda_en_el_aula) == ("COPIA_DEMASIADO_GRANDE", False)
        # Demasiado grande y el borrado no surte efecto: queda.
        rebelde = _SesionCopia(cuerpo=b"x" * 5000, al_borrar_queda=True)
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_copia(rebelde).hacer_copia(2, tmp_path / "p.tmp", 1000)
        assert (exc.value.codigo, exc.value.queda_en_el_aula) == ("COPIA_DEMASIADO_GRANDE", True)
        # No aparece nunca en el área: no se puede quitar, y puede estar.
        ausente = _SesionCopia(no_aparece=True)
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_copia(ausente).hacer_copia(2, tmp_path / "q.tmp", 1000)
        assert (exc.value.codigo, exc.value.queda_en_el_aula) == ("COPIA_FALLIDA", True)
        # Falla antes de mandar el nombre: no hay copia.
        sin_permiso = _SesionCopia(sin_formulario=True)
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_copia(sin_permiso).hacer_copia(2, tmp_path / "r.tmp", 1000)
        assert exc.value.queda_en_el_aula is False

    def test_corta_al_pasar_del_maximo_y_no_deja_nada(self, tmp_path):
        sesion = _SesionCopia(cuerpo=b"x" * 5000)
        moodle = _moodle_de_copia(sesion)
        destino = tmp_path / "e.tmp"
        with pytest.raises(ErrorPublicacion) as exc:
            moodle.hacer_copia(2, destino, 1000)
        assert exc.value.codigo == "COPIA_DEMASIADO_GRANDE"
        assert not destino.exists()
        assert sesion.descargas[0].cerrada
        assert sesion.nombres_en_el_area == []  # la copia que no se pudo traer se borró del aula

    def test_la_cabecera_de_tamano_corta_sin_descargar(self, tmp_path):
        sesion = _SesionCopia(cabeceras={"Content-Length": "999999"})
        with pytest.raises(ErrorPublicacion) as exc:
            _moodle_de_copia(sesion).hacer_copia(2, tmp_path / "f.tmp", 1000)
        assert exc.value.codigo == "COPIA_DEMASIADO_GRANDE"

    def test_si_la_copia_no_aparece_es_fallida_tras_la_espera(self, tmp_path):
        esperas: list[float] = []
        sesion = _SesionCopia(no_aparece=True)
        moodle = _moodle_de_copia(sesion)
        moodle._dormir = esperas.append
        with pytest.raises(ErrorPublicacion) as exc:
            moodle.hacer_copia(2, tmp_path / "g.tmp", 1000)
        assert exc.value.codigo == "COPIA_FALLIDA"
        assert sum(esperas) == publicar.ESPERA_COPIA  # diez minutos, no más

    def test_una_descarga_que_pasa_de_diez_minutos_es_fallida(self, tmp_path, monkeypatch):
        sesion = _SesionCopia()
        moodle = _moodle_de_copia(sesion)
        instantes = iter([0.0, publicar.ESPERA_COPIA + 1.0, publicar.ESPERA_COPIA + 2.0])
        monkeypatch.setattr(
            publicar,
            "time",
            types.SimpleNamespace(time=lambda: 1.0, monotonic=lambda: next(instantes)),
        )
        destino = tmp_path / "h.tmp"
        with pytest.raises(ErrorPublicacion) as exc:
            moodle.hacer_copia(2, destino, 1000)
        assert exc.value.codigo == "COPIA_FALLIDA"
        assert not destino.exists()

    def test_un_enlace_puesto_en_el_destino_no_se_sigue(self, tmp_path):
        from dobles import enlace_simbolico

        ajeno = tmp_path / "ajeno.txt"
        ajeno.write_text("mio", encoding="utf-8")
        destino = tmp_path / "i.tmp"
        enlace_simbolico(destino, ajeno)
        if not hasattr(publicar.os, "O_NOFOLLOW"):
            pytest.skip("este sistema no tiene O_NOFOLLOW")
        with pytest.raises(OSError):
            _moodle_de_copia(_SesionCopia()).hacer_copia(2, destino, 1000)
        assert ajeno.read_text(encoding="utf-8") == "mio"

    def test_puede_copiar_mira_el_formulario(self):
        assert _moodle_de_copia(_SesionCopia()).puede_copiar(2) is True
        assert _moodle_de_copia(_SesionCopia(sin_formulario=True)).puede_copiar(2) is False


class TestBorrarCopia:
    def _con_una_copia(self, tmp_path, **opciones):
        sesion = _SesionCopia(**opciones)
        moodle = _moodle_de_copia(sesion)
        hecha = moodle.hacer_copia(2, tmp_path / "x.tmp", 1000)
        return sesion, moodle, hecha.nombre

    def test_borra_del_gestor_y_guarda(self, tmp_path):
        sesion, moodle, nombre = self._con_una_copia(tmp_path)
        moodle.borrar_copia(nombre, 2)
        [borrado] = sesion.borrados_ajax
        assert (borrado["filename"], borrado["itemid"], borrado["filepath"]) == (
            nombre,
            "7777",
            "/",
        )
        assert borrado["params"] == {"action": "delete"} and borrado["sesskey"] == "clave"
        assert ("submitbutton", "1") in (sesion.guardado_edicion or [])
        assert sesion.nombres_en_el_area == []

    def test_si_sigue_en_el_area_es_error(self, tmp_path):
        _sesion, moodle, nombre = self._con_una_copia(tmp_path, al_borrar_queda=True)
        with pytest.raises(ErrorPublicacion) as exc:
            moodle.borrar_copia(nombre, 2)
        assert exc.value.codigo == "ERROR_BORRADO"

    def test_si_ya_no_esta_no_hace_nada(self, tmp_path):
        sesion, moodle, nombre = self._con_una_copia(tmp_path)
        sesion.nombres_en_el_area.clear()
        moodle.borrar_copia(nombre, 2)
        assert sesion.borrados_ajax == [] and sesion.guardado_edicion is None


class TestAutopruebaYCopia:
    def test_la_autoprueba_avisa_si_el_aula_no_deja_copiar(self):
        moodle = MoodleFalso(copia_permitida=False)
        resultado = publicar.autoprueba(moodle, 1234)
        assert resultado["resultado"] == "ok"  # sigue: es un aviso, no un fallo
        [paso] = [p for p in resultado["pasos"] if p.codigo == "COPIA_A_MANO"]
        assert "COPIA_NO_PERMITIDA" in paso.detalle
        sin_aviso = publicar.autoprueba(MoodleFalso(), 1234)
        assert "COPIA_A_MANO" not in [p.codigo for p in sin_aviso["pasos"]]


# --------------------------------------------------------------------------- #
# Publicar por origen: una actividad importada se actualiza por su cmid
# --------------------------------------------------------------------------- #


def _aula_con_origen(modulo="pagina", seccion_del_modulo=2):
    """Un aula de 'curso 3' con la actividad 501 «Viejo» (en la sección 2 o en la 3)."""
    secciones = [
        {"numero": 2, "nombre": "Tema 2", "id": 20, "modulos": []},
        {"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []},
    ]
    destino = next(s for s in secciones if s["numero"] == seccion_del_modulo)
    destino["modulos"].append({"cmid": 501, "nombre": "Viejo", "tipo": modulo})
    moodle = MoodleFalso(secciones=secciones)
    moodle.formularios[501] = {
        "visible": "1",
        "name": "Viejo",
        "page[text]": "<p>Texto del aula</p>",
    }
    return moodle


def _documento_con_origen(tmp_path, nombre="Nuevo", seccion="2", curso=3, cmid=501):
    ruta = tmp_path / "importada.md"
    ruta.write_text(
        f"---\ntipo: pagina\nnombre: {nombre}\nseccion: {seccion}\n"
        f"origen:\n  curso: {curso}\n  cmid: {cmid}\n---\n\nTexto nuevo.\n",
        encoding="utf-8",
    )
    return contenido.cargar(ruta)


def _llamadas(moodle, *nombres):
    return [llamada for llamada in moodle.llamadas if llamada[0] in nombres]


class TestPublicarPorOrigen:
    def test_origen_actualiza_por_cmid_con_otro_nombre(self, tmp_path):
        moodle = _aula_con_origen()
        doc = _documento_con_origen(tmp_path)
        resultado = publicar.publicar_documento(moodle, 3, moodle.estructura(3), doc, visible=None)
        assert (resultado.accion, resultado.cmid) == ("actualizada", 501)
        assert [llamada[1] for llamada in _llamadas(moodle, "actualizar")] == [501]
        assert _llamadas(moodle, "crear", "mover") == []
        assert moodle.formularios[501]["name"] == "Nuevo"

    def test_origen_mueve_de_seccion(self, tmp_path):
        moodle = _aula_con_origen(seccion_del_modulo=3)
        doc = _documento_con_origen(tmp_path, seccion='"Tema 2"')
        resultado = publicar.publicar_documento(moodle, 3, moodle.estructura(3), doc, visible=None)
        assert (resultado.accion, resultado.cmid) == ("movida", 501)
        assert _llamadas(moodle, "mover") == [("mover", 3, 501, 20, None)]
        assert _llamadas(moodle, "crear") == []
        assert [m["cmid"] for m in moodle.secciones[0]["modulos"]] == [501]
        assert moodle.secciones[1]["modulos"] == []

    def test_origen_inexistente(self, tmp_path):
        moodle = _aula_con_origen()
        doc = _documento_con_origen(tmp_path, cmid=999)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(moodle, 3, moodle.estructura(3), doc, visible=None)
        assert exc.value.codigo == "ORIGEN_NO_ENCONTRADO"
        assert _llamadas(moodle, "crear", "actualizar", "mover") == []

    def test_origen_de_otro_tipo(self, tmp_path):
        moodle = _aula_con_origen(modulo="foro")
        doc = _documento_con_origen(tmp_path)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(moodle, 3, moodle.estructura(3), doc, visible=None)
        assert exc.value.codigo == "ORIGEN_NO_ENCONTRADO"
        assert _llamadas(moodle, "crear", "actualizar", "mover") == []

    def test_origen_en_pruebas_busca_por_nombre(self, tmp_path):
        # El curso de pruebas (2) no es el del origen (3): sección, tipo y nombre, como hoy.
        moodle = _aula_con_origen()
        doc = _documento_con_origen(tmp_path)
        resultado = publicar.publicar_documento(moodle, 2, moodle.estructura(2), doc, visible=None)
        assert resultado.accion == "creada" and resultado.cmid != 501
        assert [llamada[0] for llamada in _llamadas(moodle, "crear", "mover")] == ["crear"]
        # Y si ya hay una con ese nombre en su sección, la actualiza por nombre.
        otra = publicar.publicar_documento(moodle, 2, moodle.estructura(2), doc, visible=None)
        assert (otra.accion, otra.cmid) == ("actualizada", resultado.cmid)

    def test_modulo_de_y_ya_existe_siguen_el_curso_del_origen(self, tmp_path):
        moodle = _aula_con_origen()
        doc = _documento_con_origen(tmp_path)
        assert publicar.modulo_de(moodle.secciones, doc, 3)["cmid"] == 501
        assert publicar.modulo_de(moodle.secciones, doc, 2) is None  # otro curso: por nombre
        assert publicar.ya_existe(moodle.secciones, doc, 3) is True
        assert publicar.ya_existe(moodle.secciones, doc, 2) is False
        assert (
            publicar.ya_existe(moodle.secciones, _documento_con_origen(tmp_path, cmid=9), 3) is None
        )
        with pytest.raises(ErrorPublicacion):
            publicar.modulo_de(moodle.secciones, _documento_con_origen(tmp_path, cmid=9), 3)

    def test_cambiada_en_el_aula_no_toca_la_actividad(self, tmp_path):
        moodle = _aula_con_origen()
        doc = _documento_con_origen(tmp_path, seccion='"Tema 3"')
        huella_de_la_copia = tipos.huella_aula("Viejo", "<p>Otro texto</p>")
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(
                moodle, 3, moodle.estructura(3), doc, visible=None, huella_aula=huella_de_la_copia
            )
        assert exc.value.codigo == "CAMBIADA_EN_EL_AULA"
        assert _llamadas(moodle, "crear", "actualizar", "mover", "subir") == []

    def test_con_la_huella_de_la_copia_se_actualiza(self, tmp_path):
        moodle = _aula_con_origen()
        doc = _documento_con_origen(tmp_path)
        igual = tipos.huella_aula("Viejo", "<p>Texto del aula</p>")
        resultado = publicar.publicar_documento(
            moodle, 3, moodle.estructura(3), doc, visible=None, huella_aula=igual
        )
        assert resultado.accion == "actualizada"
        # El formulario se carga una sola vez antes de escribir: la huella lo aprovecha.
        antes = [i for i, llamada in enumerate(moodle.llamadas) if llamada[0] == "leer_modulo"]
        assert antes[0] < next(
            i for i, llamada in enumerate(moodle.llamadas) if llamada[0] == "actualizar"
        )

    def test_huella_aula_normaliza_urls(self):
        base = '<p>Mira <img src="{}"> esto</p>'
        borrador = base.format("https://x/draftfile.php/5/user/draft/123/punto.png")
        copia = base.format("@@PLUGINFILE@@/punto.png")
        pluginfile = base.format(
            "https://x/pluginfile.php/8/mod_page/content/0/punto.png?forcedownload=1"
        )
        assert tipos.huella_aula("N", borrador) == tipos.huella_aula("N", copia)
        assert tipos.huella_aula("N", pluginfile) == tipos.huella_aula("N", copia)
        assert tipos.huella_aula("N", copia.replace("esto", "esta")) != tipos.huella_aula(
            "N", copia
        )
        assert tipos.huella_aula("M", copia) != tipos.huella_aula("N", copia)
        fecha = {"duedate": datetime(2026, 10, 12, 23, 59)}
        otra = {"duedate": datetime(2026, 10, 13, 0, 0)}
        un_minuto = {"duedate": datetime(2026, 10, 12, 23, 58)}
        assert tipos.huella_aula("N", copia, fecha) != tipos.huella_aula("N", copia)
        assert tipos.huella_aula("N", copia, fecha) != tipos.huella_aula("N", copia, otra)
        assert tipos.huella_aula("N", copia, fecha) != tipos.huella_aula("N", copia, un_minuto)

    def test_la_huella_de_lo_enviado_es_la_del_formulario_que_deja_el_aula(self, tmp_path):
        # Lo que tiza envía y lo que el formulario del aula devuelve dan la misma huella, en
        # una tarea (con fechas) y con el recordatorio sin poner.
        ruta = tmp_path / "tarea.md"
        ruta.write_text(
            "---\ntipo: tarea\nnombre: Problemas\nseccion: 3\napertura: 2026-10-01\n"
            "entrega: 2026-10-12\n---\n\nResuelve.\n",
            encoding="utf-8",
        )
        doc = contenido.cargar(ruta)
        moodle = MoodleFalso()
        resultado = publicar.publicar_documento(moodle, 3, moodle.estructura(3), doc, visible=None)
        tipo = tipos.obtener("tarea")
        enviada = tipos.huella_de_lo_enviado(tipo, doc, contenido.html_para_moodle(doc))
        assert tipos.huella_del_formulario(tipo, doc, moodle.leer_modulo(resultado.cmid)) == enviada
        # Cambiar un minuto de la entrega en el aula la cambia.
        moodle.formularios[resultado.cmid].update(
            fecha_en_formulario("duedate", (2026, 10, 12, 23, 58))
        )
        assert tipos.huella_del_formulario(tipo, doc, moodle.leer_modulo(resultado.cmid)) != enviada

    def test_cuestionario_con_intentos_sigue_protegido(self, tmp_path):
        moodle = MoodleFalso()
        primero = publicar.publicar_documento(
            moodle, 3, moodle.estructura(3), documento_cuestionario(tmp_path), visible=False
        )
        cmid = primero.cmid
        moodle.intentos[cmid] = True
        antes = (
            {clave: dict(banco) for clave, banco in moodle.bancos.items()},
            list(moodle.huecos(cmid)),
            dict(moodle.formularios[cmid]),
        )
        doc = documento_cuestionario(
            tmp_path,
            preguntas=PREGUNTAS_V2,
            origen=f"{{curso: 3, cmid: {cmid}}}",
        )
        huella = tipos.huella_del_formulario(
            tipos.obtener("cuestionario"), doc, moodle.leer_modulo(cmid)
        )
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(
                moodle, 3, moodle.estructura(3), doc, visible=None, huella_aula=huella
            )
        assert exc.value.codigo == "CUESTIONARIO_CON_INTENTOS"
        assert (
            {clave: dict(banco) for clave, banco in moodle.bancos.items()},
            list(moodle.huecos(cmid)),
            dict(moodle.formularios[cmid]),
        ) == antes


class TestAdjuntosDeUnaTarea:
    """Actualizar una tarea no borra sus «Archivos adicionales» (fallo medido en el CT)."""

    def _publicar(self, tmp_path, moodle):
        tarea_en(tmp_path, "2026-10-12")
        doc = contenido.cargar(tmp_path / "tarea.md")
        return publicar.publicar_documento(moodle, 5678, moodle.estructura(5678), doc, visible=None)

    def _aula(self, adjuntos="4242"):
        moodle = aula_con_tarea()
        moodle.secciones_por_curso[5678] = moodle.secciones
        if adjuntos is not None:
            moodle.formularios[55]["introattachments"] = adjuntos
        return moodle

    def test_al_actualizar_se_reenvia_el_area_del_formulario(self, tmp_path):
        moodle = self._aula("4242")
        resultado = self._publicar(tmp_path, moodle)
        assert resultado.accion == "actualizada" and resultado.cmid == 55
        (actualizar,) = [c for c in moodle.llamadas if c[0] == "actualizar"]
        assert actualizar[2]["introattachments"] == "4242"
        # No es el borrador del texto, que es uno nuevo.
        assert actualizar[2]["introeditor[itemid]"] != "4242"

    def test_el_formulario_se_carga_una_sola_vez_antes_de_escribir(self, tmp_path):
        moodle = self._aula()
        self._publicar(tmp_path, moodle)
        nombres = [c[0] for c in moodle.llamadas]
        assert nombres.count("leer_modulo") >= 1
        assert nombres.index("leer_modulo") < nombres.index("actualizar")

    def test_sin_esa_area_en_el_formulario_no_se_envia_la_clave(self, tmp_path):
        moodle = self._aula(adjuntos=None)
        self._publicar(tmp_path, moodle)
        (actualizar,) = [c for c in moodle.llamadas if c[0] == "actualizar"]
        assert "introattachments" not in actualizar[2]

    def test_una_tarea_nueva_sigue_como_siempre(self, tmp_path):
        moodle = MoodleFalso()
        tarea_en(tmp_path, "2026-10-12")
        doc = contenido.cargar(tmp_path / "tarea.md")
        resultado = publicar.publicar_documento(
            moodle, 5678, moodle.estructura(5678), doc, visible=None
        )
        assert resultado.accion == "creada"
        (crear,) = [c for c in moodle.llamadas if c[0] == "crear"]
        payload = crear[4]
        assert payload["introattachments"] == payload["introeditor[itemid]"]
        assert not any(c[0] == "leer_modulo" and c[1] != resultado.cmid for c in moodle.llamadas)

    def test_otros_tipos_no_cargan_el_formulario_para_el_payload(self, tmp_path):
        moodle = MoodleFalso()
        moodle.secciones[0]["modulos"] = [{"cmid": 60, "nombre": "Repaso", "tipo": "pagina"}]
        moodle.formularios[60] = {"name": "Repaso", "visible": "1", "page[text]": "<p>x</p>"}
        doc = documento(tmp_path)
        publicar.publicar_documento(moodle, 5678, moodle.estructura(5678), doc, visible=None)
        antes_de_escribir = moodle.llamadas[: [c[0] for c in moodle.llamadas].index("actualizar")]
        assert not any(c[0] == "leer_modulo" for c in antes_de_escribir)


# --------------------------------------------------------------------------- #
# Calificador: leer la estructura sin leer notas
# --------------------------------------------------------------------------- #

FIXTURES_CALIFICADOR = Path(__file__).parent / "fixtures" / "calificador"


def _fixture_calificador(nombre: str) -> str:
    return (FIXTURES_CALIFICADOR / nombre).read_text(encoding="utf-8")


def _formulario_item(*, locked=False, rescale=False, peso="0,0", sobrescrito=False, idnumber=""):
    html = _fixture_calificador("item.html")
    html = html.replace(
        'name="idnumber" type="text" value=""', f'name="idnumber" type="text" value="{idnumber}"'
    )
    html = html.replace(
        'name="aggregationcoef2" type="text" value="0,0"',
        f'name="aggregationcoef2" type="text" value="{peso}"',
    )
    if locked:
        html = html.replace(
            'id="id_locked" name="locked" type="checkbox"',
            'id="id_locked" name="locked" type="checkbox" checked=""',
        )
    if sobrescrito:
        html = html.replace(
            'id="id_weightoverride" name="weightoverride" type="checkbox"',
            'id="id_weightoverride" name="weightoverride" type="checkbox" checked=""',
        )
    if rescale:
        html = html.replace(
            "</form>",
            '<select name="rescalegrades"><option value="" selected></option></select></form>',
        )
    return html


class _RespuestaHttp:
    def __init__(self, texto="", status=200, destino=""):
        self.text = texto
        self.status_code = status
        self.headers = {"Location": destino} if destino else {}
        self.url = "https://aula/grade/edit/tree/index.php"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("fallo")


class _SesionCalificador:
    """Aula falsa del calificador: devuelve la página del árbol y los formularios por elemento."""

    def __init__(
        self, arbol=None, items=None, categorias=None, calculos=None, respuesta_arbol=None
    ):
        self.arbol = _fixture_calificador("setup-lleno.html") if arbol is None else arbol
        self.items = items or {}
        self.categorias = categorias or {}
        self.calculos = calculos or {}
        self.respuesta_arbol = respuesta_arbol
        self.urls: list[str] = []
        # Escritura: cada GET (url, params) y cada POST (url, campos); respuestas de POST en cola.
        self.gets: list[tuple[str, dict]] = []
        self.posts: list[tuple[str, list[tuple[str, str]]]] = []
        self.respuestas_post: list[_RespuestaHttp] = []
        self.arbol_despues: str | None = None  # el árbol que se ve tras el primer POST

    def post(self, url, data=None, allow_redirects=True, timeout=None):
        self.posts.append((url, list(data)))
        if self.arbol_despues is not None:
            self.arbol = self.arbol_despues
        if self.respuestas_post:
            return self.respuestas_post.pop(0)
        return _RespuestaHttp("", status=303, destino="https://aula/grade/edit/tree/index.php")

    def get(self, url, params=None, allow_redirects=True, timeout=None):
        self.urls.append(url if not params else f"{url}?{sorted(params.items())}")
        self.gets.append((url, dict(params or {})))
        if url.endswith("/grade/edit/tree/index.php") and (params or {}).get("action"):
            return _RespuestaHttp("", status=303, destino="https://aula/grade/edit/tree/index.php")
        if url.endswith("/grade/edit/tree/action.php"):
            return _RespuestaHttp("", status=303, destino="https://aula/grade/edit/tree/index.php")
        if url.endswith("/grade/edit/tree/index.php"):
            return self.respuesta_arbol or _RespuestaHttp(self.arbol)
        ident = int(params.get("id", 0))
        if url.endswith("/grade/edit/tree/item.php"):
            return _RespuestaHttp(self.items.get(ident) or _formulario_item())
        if url.endswith("/grade/edit/tree/category.php"):
            return _RespuestaHttp(
                self.categorias.get(ident) or _fixture_calificador("category.html")
            )
        if url.endswith("/grade/edit/tree/calculation.php"):
            formula = self.calculos.get(ident, "")
            return _RespuestaHttp(
                f'<form action="/grade/edit/tree/calculation.php"><textarea name="calculation">{formula}</textarea></form>'
            )
        raise AssertionError(f"petición inesperada: {url}")


def _calificador(**kwargs):
    sesion = _SesionCalificador(**kwargs)
    moodle = publicar.Moodle("https://aula", sesion, "clave", pausa=0)
    return moodle.calificador(2), sesion


def _nodo(calificador, eid):
    return next(n for n in calificador.nodos if n.eid == eid)


def test_calificador_arbol():
    cal, _ = _calificador()
    assert _nodo(cal, "cg1").clase == "curso"
    assert _nodo(cal, "cg1").padre_eid is None
    categorias = [n for n in cal.nodos if n.clase == "categoria"]
    assert [n.eid for n in categorias] == ["cg3", "cg4", "cg5"]
    assert all(n.padre_eid == "cg1" for n in categorias)
    assert _nodo(cal, "cg3").item_id == 162
    assert _nodo(cal, "cg3").nombre == "Espiga RA1"
    assert _nodo(cal, "cg3").maximo == 20.0
    hijos = [n.eid for n in cal.nodos if n.padre_eid == "cg3"]
    assert hijos == ["ig165", "ig166", "ig171"]
    assert _nodo(cal, "ig165").maximo == 10.0
    assert _nodo(cal, "ig165").clase == "manual"
    assert _nodo(cal, "ig171").clase == "actividad"
    assert _nodo(cal, "ig171").cmid == 258
    assert _nodo(cal, "ig165").cmid is None
    # Las filas de «total» de cada categoría no son nodos.
    assert "ig162" not in {n.eid for n in cal.nodos}


def test_calificador_lee_los_campos_de_cada_elemento():
    cal, _ = _calificador(
        items={165: _formulario_item(idnumber="TZ_A1", peso="40,0", sobrescrito=True)},
        calculos={169: "=[[TZ_A1]]*1"},
    )
    nodo = _nodo(cal, "ig165")
    assert nodo.idnumber == "TZ_A1"
    assert nodo.peso == 40.0
    assert nodo.sobrescrito is True
    assert _nodo(cal, "ig166").sobrescrito is False
    assert _nodo(cal, "ig169").clase == "calculado"
    assert _nodo(cal, "ig169").formula == "=[[TZ_A1]]*1"
    assert _nodo(cal, "ig165").formula is None


def test_calificador_flags():
    cal, _ = _calificador(
        items={
            165: _formulario_item(rescale=True),
            166: _formulario_item(locked=True),
        },
    )
    assert _nodo(cal, "ig165").tiene_notas is True
    assert _nodo(cal, "ig165").bloqueado is False
    assert _nodo(cal, "ig166").tiene_notas is False
    assert _nodo(cal, "ig166").bloqueado is True
    # Una categoría tiene notas si las tiene algún elemento de dentro.
    assert _nodo(cal, "cg3").tiene_notas is True
    assert _nodo(cal, "cg4").tiene_notas is False
    assert _nodo(cal, "cg1").tiene_notas is True


def test_calificador_bloqueo_de_categoria():
    html = _fixture_calificador("category.html").replace(
        'name="grade_item_locked" type="checkbox"',
        'name="grade_item_locked" type="checkbox" checked=""',
    )
    cal, _ = _calificador(categorias={3: html})
    assert _nodo(cal, "cg3").bloqueado is True
    assert _nodo(cal, "cg4").bloqueado is False


def test_decimal_coma():
    cal, _ = _calificador(items={165: _formulario_item(peso="40,0")})
    assert cal.decimal == ","


def test_decimal_punto():
    cal, _ = _calificador(items={165: _formulario_item(peso="40.0")})
    assert cal.decimal == "."


def test_sin_permiso():
    redireccion = _RespuestaHttp("", status=303, destino="https://aula/login/index.php")
    sesion = _SesionCalificador(respuesta_arbol=redireccion)
    moodle = publicar.Moodle("https://aula", sesion, "clave", pausa=0)
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.calificador(2)
    assert exc.value.codigo == "CALIFICADOR_NO_PERMITIDO"


class _SesionConRedireccion(_SesionCalificador):
    """La primera lectura del árbol es una redirección (p. ej. Moodle recalculando)."""

    def __init__(self, destino, veces=1, **kwargs):
        super().__init__(**kwargs)
        self.destino = destino
        self.veces = veces

    def get(self, url, params=None, allow_redirects=True, timeout=None):
        if url.endswith("/grade/edit/tree/index.php") and self.veces > 0:
            self.veces -= 1
            self.gets.append((url, dict(params or {})))
            return _RespuestaHttp("", status=303, destino=self.destino)
        return super().get(url, params, allow_redirects, timeout)


def test_redireccion_que_no_va_al_login_se_sigue_una_vez():
    sesion = _SesionConRedireccion("https://aula/grade/edit/tree/index.php")
    moodle = publicar.Moodle("https://aula", sesion, "clave", pausa=0)
    assert moodle.calificador(2).nodos
    assert sesion.gets[1][0] == "https://aula/grade/edit/tree/index.php"


def test_dos_redirecciones_seguidas_son_falta_de_permiso():
    sesion = _SesionConRedireccion("https://aula/grade/edit/tree/index.php", veces=2)
    moodle = publicar.Moodle("https://aula", sesion, "clave", pausa=0)
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.calificador(2)
    assert exc.value.codigo == "CALIFICADOR_NO_PERMITIDO"


class _SesionDeEnteros(_SesionCalificador):
    """Un curso limpio: ningún formulario existente muestra decimales; el alta sí (100,00)."""

    def get(self, url, params=None, allow_redirects=True, timeout=None):
        if url.endswith("/grade/edit/tree/item.php"):
            self.gets.append((url, dict(params or {})))
            if "id" not in (params or {}):
                return _RespuestaHttp(_fixture_calificador("item.html"))
            html = _fixture_calificador("item.html")
            html = html.replace(
                'name="grademax" type="text" value="100,00"',
                'name="grademax" type="text" value="100"',
            )
            return _RespuestaHttp(html.replace('value="0,0"', 'value="0"'))
        return super().get(url, params, allow_redirects, timeout)


def test_decimal_de_un_curso_limpio_sale_del_formulario_de_alta():
    sesion = _SesionDeEnteros()
    cal = publicar.Moodle("https://aula", sesion, "clave", pausa=0).calificador(2)
    assert cal.decimal == ","
    assert ("https://aula/grade/edit/tree/item.php", {"courseid": 2}) in sesion.gets


def test_sin_formulario_del_arbol_no_hay_permiso():
    sesion = _SesionCalificador(arbol="<html><body>Sin permiso</body></html>")
    moodle = publicar.Moodle("https://aula", sesion, "clave", pausa=0)
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.calificador(2)
    assert exc.value.codigo == "CALIFICADOR_NO_PERMITIDO"


def test_error_de_red_es_error_de_consulta():
    class Sesion:
        def get(self, *a, **k):
            raise requests.ConnectionError("caído")

    moodle = publicar.Moodle("https://aula", Sesion(), "clave", pausa=0)
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.calificador(2)
    assert exc.value.codigo in ("ERROR_CONSULTA", "SESION_CADUCADA")


def test_no_lee_notas():
    _, sesion = _calificador()
    assert sesion.urls
    assert not any("grade/report" in url for url in sesion.urls)
    assert not any("grade/export" in url or "grade/import" in url for url in sesion.urls)


def test_calificador_espera_entre_peticiones():
    pausas: list[float] = []
    sesion = _SesionCalificador()
    moodle = publicar.Moodle("https://aula", sesion, "clave", pausa=0.5, dormir=pausas.append)
    moodle.calificador(2)
    # Una pausa por petición (árbol, 3+1+1+1 formularios...): al menos una por cada GET.
    assert len(pausas) == len(sesion.urls)


def test_el_doble_devuelve_un_calificador_configurable():
    aula = MoodleFalso()
    assert aula.calificador(2) == publicar.CalificadorAula(nodos=(), decimal=".")
    esperado = publicar.CalificadorAula(nodos=(), decimal=",")
    aula.calificadores[2] = esperado
    assert aula.calificador(2) is esperado
    assert ("calificador", 2) in aula.llamadas


# --------------------------------------------------------------------------- #
# Calificador: escribir (crear, pesar, bloquear, colocar)
# --------------------------------------------------------------------------- #


def _campos(sesion, indice=-1):
    url, pares = sesion.posts[indice]
    return url, dict(pares)


def _moodle_calificador(**kwargs):
    sesion = _SesionCalificador(**kwargs)
    return publicar.Moodle("https://aula", sesion, "clave", pausa=0), sesion


def _arbol_con_nueva_categoria():
    html = _fixture_calificador("setup-lleno.html")
    fila = (
        '<tr class="category cg1" data-category="cg9" data-parent-category="cg1" '
        'data-aggregation="13" data-grademax="0" data-aggregationcoef="0" data-itemid="900" '
        'data-hidden="false" id="grade-item-cg9">'
    )
    return html.replace("</table>", fila + "</tr></table>", 1)


def test_formula_moodle_coma():
    plantilla = "=min([[A]],[[B]])+0.5"
    assert publicar.formula_moodle(plantilla, ",") == "=min([[A]];[[B]])+0.5"


def test_formula_moodle_punto():
    plantilla = "=min([[A]],[[B]])+0.5"
    assert publicar.formula_moodle(plantilla, ".") == plantilla


def test_formula_tope():
    notas = ["TZ_NOTA_E_RA1", "TZ_NOTA_E_RA2", "TZ_NOTA_E_RA3"]
    f = publicar.formula_tope(5, 4, notas)
    esperado = (
        "=min([[TZ_FINAL]]/[[TZ_K_TIZA]]*10;4+1000*floor(min("
        "[[TZ_NOTA_E_RA1]];[[TZ_NOTA_E_RA2]];[[TZ_NOTA_E_RA3]])/5))"
    )
    assert publicar.formula_moodle(f, ",") == esperado
    assert publicar.formula_moodle(f, ".") == esperado.replace(";", ",")


def test_formula_tope_con_decimales():
    f = publicar.formula_tope(4.5, 7.5, ["TZ_N1"])
    assert "7.5+1000*floor(min([[TZ_N1]])/4.5)" in f


def test_formula_nota():
    assert publicar.formula_nota("TZ_E_RA1", "TZ_K_RA1") == "=[[TZ_E_RA1]]/[[TZ_K_RA1]]*10"


def test_formula_indicador():
    assert publicar.formula_indicador("TZ_A258", 100) == "=[[TZ_A258]]*0+100"
    assert publicar.formula_indicador("TZ_A258", 2.5) == "=[[TZ_A258]]*0+2.5"
    assert publicar.formula_indicador("X", 1 / 3) == "=[[X]]*0+0.33333"


def test_formula_copia():
    assert publicar.formula_copia("TZ_I_1") == "=[[TZ_I_1]]"


def test_crear_categoria_envia():
    moodle, sesion = _moodle_calificador()
    sesion.arbol_despues = _arbol_con_nueva_categoria()
    eid = moodle.crear_categoria(2, "RA1", "TZ_E_RA1", "cg1", 40, "porcentaje")
    assert eid == "cg9"
    url, campos = _campos(sesion)
    assert url == "https://aula/grade/edit/tree/category.php"
    assert campos["fullname"] == "RA1"
    assert campos["grade_item_idnumber"] == "TZ_E_RA1"
    assert campos["aggregation"] == "13"
    assert campos["aggregateonlygraded"] == "1"
    assert campos["parentcategory"] == "1"
    assert campos["grade_item_weightoverride"] == "1"
    assert campos["grade_item_aggregationcoef2"] == "40"
    assert campos["courseid"] == "2"
    assert ("category.php", {"courseid": 2, "id": 0}) in [
        (u.rsplit("/", 1)[1], p) for u, p in sesion.gets
    ]


def test_crear_categoria_porcentaje():
    moodle, sesion = _moodle_calificador()
    sesion.arbol_despues = _arbol_con_nueva_categoria()
    moodle.crear_categoria(2, "RA1", "TZ_E_RA1", "cg1", 40, "porcentaje")
    assert _campos(sesion)[1]["grade_item_display"] == "2"
    moodle2, sesion2 = _moodle_calificador()
    sesion2.arbol_despues = _arbol_con_nueva_categoria()
    moodle2.crear_categoria(2, "RA1", "TZ_E_RA1", "cg1", 40, None)
    assert "grade_item_display" not in _campos(sesion2)[1]


def test_crear_categoria_sin_peso():
    moodle, sesion = _moodle_calificador()
    sesion.arbol_despues = _arbol_con_nueva_categoria()
    moodle.crear_categoria(2, "K", "TZ_K", "cg1", None, "porcentaje")
    campos = _campos(sesion)[1]
    assert campos["grade_item_weightoverride"] == "0"
    assert campos["grade_item_aggregationcoef2"] == "0"


def test_crear_sin_aparecer_en_el_arbol_es_error():
    moodle, _ = _moodle_calificador()
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.crear_categoria(2, "RA1", "TZ_E_RA1", "cg1", 40, "porcentaje")
    assert exc.value.codigo == "ESCRITURA_CALIFICADOR"


def test_crear_calculado_envia():
    moodle, sesion = _moodle_calificador()
    nueva = '<tr class="item cg1" data-itemid="901" data-parent-category="cg1" id="grade-item-ig901"></tr>'
    sesion.arbol_despues = _fixture_calificador("setup-lleno.html").replace(
        "</table>", nueva + "</table>", 1
    )
    eid = moodle.crear_calculado(2, "Nota", "TZ_NOTA_E_1", "cg3", 25, 10)
    assert eid == "ig901"
    url, campos = _campos(sesion)
    assert url == "https://aula/grade/edit/tree/item.php"
    assert campos["itemname"] == "Nota"
    assert campos["idnumber"] == "TZ_NOTA_E_1"
    assert campos["grademax"] == "10"
    assert campos["parentcategory"] == "3"
    assert campos["weightoverride"] == "1"
    assert campos["aggregationcoef2"] == "25"
    assert "calculation" not in campos


def test_crear_calculado_sin_peso():
    moodle, sesion = _moodle_calificador()
    nueva = '<tr class="item cg1" data-itemid="901" data-parent-category="cg1" id="grade-item-ig901"></tr>'
    sesion.arbol_despues = _fixture_calificador("setup-lleno.html").replace(
        "</table>", nueva + "</table>", 1
    )
    moodle.crear_calculado(2, "I", "TZ_I_1", "cg3", None, 7.5)
    campos = _campos(sesion)[1]
    assert campos["weightoverride"] == "0"
    assert campos["grademax"] == "7.5"


def test_fijar_maximo_y_peso():
    moodle, sesion = _moodle_calificador()
    moodle.fijar_maximo(2, 165, 30)
    assert sesion.gets[-1] == ("https://aula/grade/edit/tree/item.php", {"courseid": 2, "id": 165})
    assert _campos(sesion)[1]["grademax"] == "30"
    moodle.fijar_peso(2, "ig165", 60)
    assert _campos(sesion)[1]["weightoverride"] == "1"
    assert _campos(sesion)[1]["aggregationcoef2"] == "60"
    moodle.fijar_peso(2, "cg3", 0)
    url, campos = _campos(sesion)
    assert url.endswith("/category.php")
    assert sesion.gets[-1][1] == {"courseid": 2, "id": 3}
    assert campos["grade_item_weightoverride"] == "1"
    assert campos["grade_item_aggregationcoef2"] == "0"


def test_fijar_maximo_elige_no_recalcular_si_hay_notas():
    moodle, sesion = _moodle_calificador(items={165: _formulario_item(rescale=True)})
    moodle.fijar_maximo(2, 165, 220)
    campos = _campos(sesion)[1]
    assert campos["grademax"] == "220"
    assert campos["rescalegrades"] == "no"


def test_fijar_maximo_sin_notas_no_envia_rescalegrades():
    moodle, sesion = _moodle_calificador()
    moodle.fijar_maximo(2, 165, 30)
    assert "rescalegrades" not in _campos(sesion)[1]


def test_escritura_rechazada_es_error_propio():
    moodle, sesion = _moodle_calificador()
    sesion.respuestas_post = [_RespuestaHttp("<p>Texto secreto de Moodle</p>", status=200)]
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.fijar_peso(2, "ig165", 60)
    assert exc.value.codigo == "ESCRITURA_CALIFICADOR"
    assert "secreto" not in str(exc.value) + exc.value.detalle


def test_fijar_formula_traduce_con_el_decimal():
    moodle, sesion = _moodle_calificador()
    moodle.fijar_formula(2, 169, "=min([[A]],[[B]])", decimal=",")
    url, campos = _campos(sesion)
    assert url == "https://aula/grade/edit/tree/calculation.php"
    assert campos["calculation"] == "=min([[A]];[[B]])"
    moodle.fijar_formula(2, 169, "=min([[A]],[[B]])", decimal=".")
    assert _campos(sesion)[1]["calculation"] == "=min([[A]],[[B]])"


def test_formula_reintenta():
    moodle, sesion = _moodle_calificador()
    sesion.respuestas_post = [
        _RespuestaHttp("<div class='error'>Fórmula no válida</div>", status=200),
        _RespuestaHttp("", status=303, destino="x"),
    ]
    moodle.fijar_formula(2, 169, "=[[A]]", ".")
    assert len(sesion.posts) == 2


def test_formula_no_valida():
    moodle, sesion = _moodle_calificador()
    sesion.respuestas_post = [
        _RespuestaHttp("<div>Fórmula no válida: texto de Moodle</div>", status=200),
        _RespuestaHttp("<div>Fórmula no válida: texto de Moodle</div>", status=200),
    ]
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.fijar_formula(2, 169, "=[[A]]", ".")
    assert exc.value.codigo == "FORMULA_NO_VALIDA"
    assert len(sesion.posts) == 2
    assert "texto de Moodle" not in str(exc.value) + exc.value.detalle


def test_bloquear_es_ig():
    moodle, sesion = _moodle_calificador()
    moodle.bloquear_total(2, 162)
    url, params = sesion.gets[-1]
    assert url == "https://aula/grade/edit/tree/action.php"
    assert params["eid"] == "ig162"
    assert params["action"] == "lock"
    assert params["sesskey"] == "clave"
    assert not any(str(v).startswith("cg") for v in params.values())


def test_bloquear_rechazado():
    class Sesion(_SesionCalificador):
        def get(self, url, params=None, **kw):
            if url.endswith("action.php"):
                return _RespuestaHttp("<p>no</p>", status=200)
            return super().get(url, params, **kw)

    moodle = publicar.Moodle("https://aula", Sesion(), "clave", pausa=0)
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.bloquear_total(2, 162)
    assert exc.value.codigo == "ESCRITURA_CALIFICADOR"


def test_mover_manual_first():
    moodle, sesion = _moodle_calificador()
    moodle.mover_manual(2, 165, "cg5")
    url, params = sesion.gets[-1]
    assert url == "https://aula/grade/edit/tree/index.php"
    assert params["action"] == "move"
    assert params["eid"] == "ig165"
    assert params["moveafter"] == "cg5"
    assert params["first"] == 1


def test_borrar_nodo():
    moodle, sesion = _moodle_calificador()
    moodle.borrar_nodo(2, "cg5")
    url, params = sesion.gets[-1]
    assert params["action"] == "delete"
    assert params["eid"] == "cg5"
    assert params["confirm"] == 1


def test_colocar_actividad():
    moodle, _ = _moodle_calificador()
    llamadas = []
    moodle.actualizar = lambda cmid, payload: llamadas.append((cmid, payload))
    moodle.colocar_actividad(2, 258, 5, "TZ_A258")
    moodle.colocar_actividad(2, 259, 5, None)
    assert llamadas == [
        (258, {"gradecat": "5", "cmidnumber": "TZ_A258"}),
        (259, {"gradecat": "5"}),
    ]


def test_fijar_total_curso_con_formula():
    sesion = _SesionCalificador()
    moodle = publicar.Moodle("https://aula", sesion, "clave", pausa=0)
    moodle.fijar_total_curso(2, "=[[TZ_NOTA_FINAL]]", ".")
    assert [u.rsplit("/", 1)[1] for u, _ in sesion.posts] == ["calculation.php", "category.php"]
    assert dict(sesion.posts[0][1])["calculation"] == "=[[TZ_NOTA_FINAL]]"
    assert dict(sesion.posts[1][1])["grade_item_grademax"] == "10"
    assert {"courseid": 2, "id": 1} in [p for u, p in sesion.gets if u.endswith("calculation.php")]


def test_fijar_total_curso_sin_formula_solo_porcentaje():
    sesion = _SesionCalificador()
    moodle = publicar.Moodle("https://aula", sesion, "clave", pausa=0)
    moodle.fijar_total_curso(2, None, ".")
    assert len(sesion.posts) == 1
    url, campos = _campos(sesion)
    assert url.endswith("/category.php")
    assert campos["grade_item_display"] == "2"


def test_el_doble_registra_las_escrituras_y_simula_fallos():
    aula = MoodleFalso()
    eid = aula.crear_categoria(2, "RA1", "TZ_E_RA1", "cg1", 40, "porcentaje")
    assert eid.startswith("cg")
    aula.bloquear_total(2, 162)
    assert aula.escrituras[0][0] == "crear_categoria"
    assert aula.escrituras[1] == ("bloquear_total", 2, 162)
    aula.fallos["fijar_formula"] = ["FORMULA_NO_VALIDA"]
    with pytest.raises(ErrorPublicacion) as exc:
        aula.fijar_formula(2, 169, "=[[A]]", ",")
    assert exc.value.codigo == "FORMULA_NO_VALIDA"
    aula.fijar_formula(2, 169, "=[[A]]", ",")  # el fallo se gasta
    assert aula.escrituras[-1][0] == "fijar_formula"


# --- Ronda de arreglo 1 ---


def test_decimal_es_obligatorio():
    import inspect

    for clase in (publicar.AulaVirtual, publicar.Moodle, MoodleFalso):
        for nombre in ("fijar_formula", "fijar_total_curso"):
            parametro = inspect.signature(getattr(clase, nombre)).parameters["decimal"]
            assert parametro.default is inspect.Parameter.empty, (clase, nombre)


def test_el_doble_registra_el_decimal():
    aula = MoodleFalso()
    aula.fijar_formula(2, 169, "=[[A]]", ",")
    aula.fijar_total_curso(2, None, ".")
    assert aula.escrituras == [
        ("fijar_formula", 2, 169, "=[[A]]", ","),
        ("fijar_total_curso", 2, None, "."),
    ]


@pytest.mark.parametrize("eid", ["", "x", "cg", "ig1x", "cg-1", "CG1", "cg1 ", "1", "cg1\n"])
def test_eid_mal_formado_es_error_propio(eid):
    moodle, sesion = _moodle_calificador()
    for llamada in (
        lambda: moodle.borrar_nodo(2, eid),
        lambda: moodle.fijar_peso(2, eid, 10),
        lambda: moodle.mover_manual(2, 165, eid),
        lambda: moodle.crear_categoria(2, "n", "TZ_X", eid, None, None),
        lambda: moodle.crear_calculado(2, "n", "TZ_X", eid, None, 10),
    ):
        with pytest.raises(ErrorPublicacion) as exc:
            llamada()
        assert exc.value.codigo == "ESCRITURA_CALIFICADOR"
    assert sesion.posts == []
    assert not any(p.get("action") == "delete" for _, p in sesion.gets)


def test_borrar_nodo_rechaza_la_raiz_del_curso():
    moodle, sesion = _moodle_calificador()
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.borrar_nodo(2, "cg1")
    assert exc.value.codigo == "ESCRITURA_CALIFICADOR"
    assert not any(p.get("action") == "delete" for _, p in sesion.gets)
    moodle.borrar_nodo(2, "cg3")  # una categoría normal sí
    assert sesion.gets[-1][1]["eid"] == "cg3"


def test_fijar_total_curso_sin_itemid_es_error_propio():
    arbol = (
        "<html><body><form id='gradetreeform'><table>"
        '<tr data-category="cg1" data-aggregation="13"></tr></table></form></body></html>'
    )
    moodle, sesion = _moodle_calificador(arbol=arbol)
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.fijar_total_curso(2, "=[[A]]", ".")
    assert exc.value.codigo == "ESCRITURA_CALIFICADOR"
    assert sesion.posts == []


def test_redireccion_al_login_es_sesion_caducada():
    login = _RespuestaHttp("", status=303, destino="https://aula/login/index.php")
    moodle, sesion = _moodle_calificador()
    sesion.respuestas_post = [login]
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.fijar_peso(2, "ig165", 60)
    assert exc.value.codigo == "SESION_CADUCADA"
    moodle, sesion = _moodle_calificador()
    sesion.respuestas_post = [login]
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.fijar_formula(2, 169, "=[[A]]", ".")
    assert exc.value.codigo == "SESION_CADUCADA"


def test_accion_con_redireccion_al_login_es_sesion_caducada():
    class Sesion(_SesionCalificador):
        def get(self, url, params=None, **kw):
            if url.endswith("action.php"):
                return _RespuestaHttp("", status=302, destino="https://aula/login/index.php")
            return super().get(url, params, **kw)

    moodle = publicar.Moodle("https://aula", Sesion(), "clave", pausa=0)
    with pytest.raises(ErrorPublicacion) as exc:
        moodle.bloquear_total(2, 162)
    assert exc.value.codigo == "SESION_CADUCADA"


def test_formula_moodle_no_toca_las_comas_de_un_numero_de_id():
    assert publicar.formula_moodle("=min([[A,B]],[[C]])", ",") == "=min([[A,B]];[[C]])"
