"""Tests offline de la publicación: payloads, orquestación y puerta de CI."""

from __future__ import annotations

import pytest
import requests
from py_moodle.auth import LoginError
from py_moodle.draftfile import MoodleDraftFileError
from py_moodle.module import MoodleModuleError
from py_moodle.session import MoodleSessionError

from dobles import MoodleFalso
from tiza import config, contenido, publicar
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
        assert "LIMPIAR" in codigos
        assert resultado["errores"] == []
        borrados = [llamada for llamada in moodle.llamadas if llamada[0] == "borrar"]
        assert len(borrados) == 5
        assert moodle.secciones[0]["modulos"] == []

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
