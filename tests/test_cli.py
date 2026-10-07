"""Tests de la CLI: TTY, contraseña, informes y comandos offline."""

from __future__ import annotations

import json
import os
import time
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dobles import MoodleFalso
from tiza import (
    aislamiento,
    buzon,
    cli,
    config,
    contenido,
    informe,
    publicar,
    sesion,
    terminal,
)

PAGINA = "---\ntipo: pagina\nnombre: Repaso\nseccion: 3\n---\n\n## Repaso\n\nContenido.\n"


class SalidaFalsa:
    def __init__(self, interactiva: bool = True):
        self._interactiva = interactiva
        self.texto: list[str] = []

    def isatty(self) -> bool:
        return self._interactiva

    def write(self, texto: str) -> int:
        self.texto.append(texto)
        return len(texto)

    def flush(self) -> None:
        pass

    def readline(self) -> str:
        return "s\n"

    def contenido(self) -> str:
        return "".join(self.texto)


def simular_terminal(monkeypatch, interactiva: bool = True) -> SalidaFalsa:
    salida = SalidaFalsa(interactiva)
    monkeypatch.setattr("sys.stdin", salida)
    monkeypatch.setattr("sys.stdout", salida)
    monkeypatch.setattr(terminal.getpass, "getpass", lambda _prompt="": "secreta")
    return salida


def responder(monkeypatch, respuestas: list[str]) -> None:
    pendientes = iter(respuestas)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(pendientes))


def configurar(tmp_path, monkeypatch, cursos=None) -> None:
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
    config.guardar_global(
        "https://aula.ejemplo.org/centro",
        "profe",
        cursos or {"pruebas": 1234, "real": 5678},
    )


def escribir_pagina(tmp_path, texto: str = PAGINA) -> Path:
    ruta = tmp_path / "pagina.md"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def leer_informe(tmp_path) -> dict:
    return json.loads((tmp_path / ".tiza" / "informe.json").read_text(encoding="utf-8"))


class TestSinTTY:
    def test_publicar_sin_tty_ni_sesion_falla_y_no_pide_password(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        simular_terminal(monkeypatch, interactiva=False)

        def no_llamar():
            raise AssertionError("no se debe pedir la contraseña sin sesión")

        monkeypatch.setattr(terminal, "pedir_password", no_llamar)
        assert cli.main(["publicar", "pagina.md", "--en", "pruebas"]) == 1
        informe = leer_informe(tmp_path)
        assert "SIN_SESION" in informe["errores"]
        assert "SIN_TTY" not in informe["errores"]

    def test_estructura_sin_tty_ni_sesion_falla(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        simular_terminal(monkeypatch, interactiva=False)
        assert cli.main(["estructura"]) == 1
        informe = leer_informe(tmp_path)
        assert "SIN_SESION" in informe["errores"]
        assert "SIN_TTY" not in informe["errores"]

    def test_sesion_sin_tty_falla(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        configurar(tmp_path, monkeypatch)
        simular_terminal(monkeypatch, interactiva=False)
        assert cli.main(["sesion"]) == 1
        assert "SIN_TTY" in leer_informe(tmp_path)["errores"]


class TestPassword:
    def test_no_acepta_password_por_argumento(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc:
            cli.main(["publicar", "pagina.md", "--en", "pruebas", "--password", "x"])
        assert exc.value.code == 2

    def test_password_solo_desde_la_terminal(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        configurar(tmp_path, monkeypatch)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        monkeypatch.setenv("TIZA_PASSWORD", "desde-el-entorno")
        monkeypatch.setattr(terminal.getpass, "getpass", lambda _prompt="": "desde-la-terminal")
        capturado: dict = {}
        monkeypatch.setattr(
            "tiza.publicar.autenticar",
            lambda url, usuario, password: (
                capturado.update(url=url, usuario=usuario, password=password),
                MoodleFalso(),
            )[1],
        )
        assert cli.main(["publicar", "pagina.md", "--en", "pruebas"]) == 0
        assert capturado["password"] == "desde-la-terminal"
        assert capturado["usuario"] == "profe"


class TestPublicar:
    def test_publica_en_pruebas_y_registra_verificado(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        configurar(tmp_path, monkeypatch)
        salida = simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        monkeypatch.setattr("tiza.publicar.autenticar", lambda *a, **k: MoodleFalso())
        assert cli.main(["publicar", "pagina.md", "--en", "pruebas"]) == 0
        informe = leer_informe(tmp_path)
        assert informe["resultado"] == "ok"
        assert informe["ficheros"][0]["cmid"] == 100
        assert informe["ficheros"][0]["oculto"] is True
        verificados = publicar.cargar_verificados(tmp_path / ".tiza")
        assert contenido.hash_documento(contenido.cargar(tmp_path / "pagina.md")) in verificados
        assert "Curso de destino: id 1234" in salida.contenido()

    def test_publicar_directo_rechaza_un_recurso_oculto_antes_de_pedir_nada(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("url = x", encoding="utf-8")
        escribir_pagina(tmp_path, PAGINA.replace("Contenido.", "[config](.git/config)"))
        configurar(tmp_path, monkeypatch)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        llamadas: list = []
        monkeypatch.setattr(
            "tiza.publicar.autenticar", lambda *a, **k: llamadas.append(a) or MoodleFalso()
        )
        assert cli.main(["publicar", "pagina.md", "--en", "pruebas"]) == 1
        assert "RECURSO_NO_PERMITIDO" in leer_informe(tmp_path)["errores"]
        assert llamadas == []

    def test_publica_en_real_sin_verificar_rechaza(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        configurar(tmp_path, monkeypatch)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        llamadas: list = []
        monkeypatch.setattr(
            "tiza.publicar.autenticar",
            lambda *a, **k: llamadas.append(a) or MoodleFalso(),
        )
        assert cli.main(["publicar", "pagina.md", "--en", "real"]) == 1
        informe = leer_informe(tmp_path)
        assert "VERIFICACION_PENDIENTE" in informe["errores"]
        assert llamadas == []

    def test_publica_en_real_con_verificado(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        configurar(tmp_path, monkeypatch)
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(
            tmp_path / ".tiza", contenido.hash_documento(doc), "pagina.md", 100
        )
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        monkeypatch.setattr("tiza.publicar.autenticar", lambda *a, **k: MoodleFalso())
        assert cli.main(["publicar", "pagina.md", "--en", "real"]) == 0
        assert leer_informe(tmp_path)["resultado"] == "ok"

    def test_error_de_moodle_no_se_filtra(self, tmp_path, monkeypatch):
        class MoodleQueFalla(MoodleFalso):
            def crear(self, curso_id, seccion_id, tipo, payload):
                raise publicar.ErrorPublicacion("ERROR_CREACION")

        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        configurar(tmp_path, monkeypatch)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        monkeypatch.setattr("tiza.publicar.autenticar", lambda *a, **k: MoodleQueFalla())
        assert cli.main(["publicar", "pagina.md", "--en", "pruebas"]) == 1
        texto = (tmp_path / ".tiza" / "informe.json").read_text(encoding="utf-8")
        assert "ERROR_CREACION" in texto
        assert "<" not in texto


class TestEstructura:
    def test_escribe_la_estructura_de_los_dos_cursos(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        configurar(tmp_path, monkeypatch)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s", "s"])
        monkeypatch.setattr("tiza.publicar.autenticar", lambda *a, **k: MoodleFalso())
        assert cli.main(["estructura"]) == 0
        datos = json.loads((tmp_path / ".tiza" / "estructura.json").read_text(encoding="utf-8"))
        assert datos["cursos"]["pruebas"]["id"] == 1234
        assert datos["cursos"]["real"]["id"] == 5678
        assert datos["cursos"]["pruebas"]["secciones"][0]["numero"] == 3


class TestComprobar:
    def test_comprobar_ok(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        publicar.escribir_estructura(
            tmp_path / ".tiza",
            {
                "version": 1,
                "cursos": {
                    "pruebas": {
                        "id": 1234,
                        "secciones": [{"numero": 3, "nombre": "Tema 3"}],
                    }
                },
            },
        )
        assert cli.main(["comprobar", "pagina.md"]) == 0
        assert (tmp_path / ".tiza" / "preview" / "pagina.html").is_file()
        informe = leer_informe(tmp_path)
        assert informe["pasos"][0]["resultado"] == "ok"
        assert informe["ficheros"][0]["seccion"] == "Tema 3"

    def test_comprobar_sin_estructura_falla(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        assert cli.main(["comprobar", "pagina.md"]) == 1
        assert "ESTRUCTURA_AUSENTE" in leer_informe(tmp_path)["errores"]

    def test_comprobar_seccion_ausente_falla(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        publicar.escribir_estructura(
            tmp_path / ".tiza",
            {
                "version": 1,
                "cursos": {
                    "pruebas": {
                        "id": 1234,
                        "secciones": [{"numero": 1, "nombre": "General"}],
                    }
                },
            },
        )
        assert cli.main(["comprobar", "pagina.md"]) == 1
        assert "SECCION_AUSENTE" in leer_informe(tmp_path)["errores"]

    def test_comprobar_id_de_seccion_indica_el_numero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path, PAGINA.replace("seccion: 3", "seccion: 12858"))
        publicar.escribir_estructura(
            tmp_path / ".tiza",
            {
                "version": 1,
                "cursos": {
                    "pruebas": {
                        "id": 1234,
                        "secciones": [{"numero": 1, "nombre": "Proyecto", "id": 12858}],
                    }
                },
            },
        )
        assert cli.main(["comprobar", "pagina.md"]) == 1
        assert "SECCION_ES_ID" in leer_informe(tmp_path)["errores"]
        assert "seccion: 1" in capsys.readouterr().err

    def test_comprobar_seccion_por_nombre_que_falta_avisa_y_pasa(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path, PAGINA.replace("seccion: 3", 'seccion: "Fracciones"'))
        publicar.escribir_estructura(
            tmp_path / ".tiza",
            {
                "version": 1,
                "cursos": {
                    "pruebas": {
                        "id": 1,
                        "secciones": [{"numero": 1, "nombre": "Proyecto", "id": 9}],
                    }
                },
            },
        )
        assert cli.main(["comprobar", "pagina.md"]) == 0
        assert "se creará oculta" in capsys.readouterr().out

    def test_comprobar_html_peligroso_falla(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path, PAGINA.replace("Contenido.", "<script>alert(1)</script>"))
        assert cli.main(["comprobar", "pagina.md"]) == 1
        assert "HTML_PELIGROSO" in leer_informe(tmp_path)["errores"]

    def test_comprobar_muestra_enlace_file(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        cli.main(["comprobar", "pagina.md"])
        salida = capsys.readouterr().out
        esperado = (tmp_path / ".tiza" / "preview" / "pagina.html").resolve().as_uri()
        assert f"Vista previa: {esperado}" in salida

    def test_comprobar_explica_cada_error_con_su_fichero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tarea.md").write_text(
            "---\ntipo: tarea\nnombre: T\nseccion: 3\n"
            "apertura: 2026-10-11\nentrega: 2026-10-10\n---\n\nx\n",
            encoding="utf-8",
        )
        (tmp_path / "sin_seccion.md").write_text(
            "---\ntipo: pagina\nnombre: P\n---\n\nx\n", encoding="utf-8"
        )
        assert cli.main(["comprobar", "tarea.md", "sin_seccion.md"]) == 1
        err = capsys.readouterr().err
        assert "tarea.md: FECHAS_INCOHERENTES: debe cumplirse apertura < entrega" in err
        assert "sin_seccion.md: CAMPO_FALTANTE: falta el campo «seccion»" in err
        detalles = [paso["detalle"] for paso in leer_informe(tmp_path)["pasos"]]
        assert "tarea.md: FECHAS_INCOHERENTES" in detalles
        assert "sin_seccion.md: CAMPO_FALTANTE" in detalles

    def test_comprobar_explica_la_seccion_ausente(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        publicar.escribir_estructura(
            tmp_path / ".tiza",
            {
                "version": 1,
                "cursos": {"pruebas": {"id": 1, "secciones": [{"numero": 1, "nombre": "General"}]}},
            },
        )
        assert cli.main(["comprobar", "pagina.md"]) == 1
        assert "pagina.md: SECCION_AUSENTE: no existe la sección 3" in capsys.readouterr().err


def test_enlace_codifica_espacios_y_acentos(tmp_path):
    ruta = tmp_path / "Matemáticas 2º" / "Tema 1.html"
    enlace = terminal.enlace(ruta)
    assert enlace.startswith("file:///")
    assert " " not in enlace and "%20" in enlace


class TestConfigurar:
    def test_guarda_url_usuario_y_cursos_sin_password(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
        simular_terminal(monkeypatch)
        responder(
            monkeypatch,
            ["https://aula.ejemplo.org", "profe", "1234", "5678", ""],
        )

        class RespuestaFalsa:
            url = "https://aula.ejemplo.org/centro/"
            status_code = 200

        monkeypatch.setattr(config.requests, "get", lambda *a, **k: RespuestaFalsa())
        assert cli.main(["configurar"]) == 0
        datos = json.loads((tmp_path / "prefs" / "config.json").read_text(encoding="utf-8"))
        assert datos["url"] == "https://aula.ejemplo.org/centro"
        assert datos["usuario"] == "profe"
        assert datos["cursos"] == {"pruebas": 1234, "real": 5678}
        assert "password" not in json.dumps(datos).lower()

    def test_url_inaccesible_explica_que_hacer(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
        monkeypatch.setattr(terminal, "exigir_tty", lambda: None)
        responder(monkeypatch, ["https://aula.ejemplo.org"])

        def sin_red(*a, **k):
            raise config.requests.ConnectionError("sin red")

        monkeypatch.setattr(config.requests, "get", sin_red)
        assert cli.main(["configurar"]) == 1
        err = capsys.readouterr().err
        assert "ERROR [URL_INACCESIBLE]" in err
        assert "Qué hacer: " in err

    def test_cursos_opcionales(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["https://aula.ejemplo.org", "profe", "", "", ""])

        class RespuestaFalsa:
            url = "https://aula.ejemplo.org/centro/"
            status_code = 200

        monkeypatch.setattr(config.requests, "get", lambda *a, **k: RespuestaFalsa())
        assert cli.main(["configurar"]) == 0
        datos = json.loads((tmp_path / "prefs" / "config.json").read_text(encoding="utf-8"))
        assert datos["cursos"] == {}

    def test_entrada_larga_reintenta_y_acepta(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
        simular_terminal(monkeypatch)
        responder(
            monkeypatch,
            ["https://aula.ejemplo.org", "profe", "9" * 5000, "1234", "5678", ""],
        )

        class RespuestaFalsa:
            url = "https://aula.ejemplo.org/centro/"
            status_code = 200

        monkeypatch.setattr(config.requests, "get", lambda *a, **k: RespuestaFalsa())
        assert cli.main(["configurar"]) == 0
        datos = json.loads((tmp_path / "prefs" / "config.json").read_text(encoding="utf-8"))
        assert datos["cursos"] == {"pruebas": 1234, "real": 5678}

    def test_no_conecta_con_urls_invalidas(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["https://evil.example\\aula.ejemplo.org/centro"])

        def no_conectar(*a, **k):
            raise AssertionError("no se debe conectar con una URL inválida")

        monkeypatch.setattr(config.requests, "get", no_conectar)
        assert cli.main(["configurar"]) == 1
        assert "URL_NO_PERMITIDA" in capsys.readouterr().err

    def test_http_se_convierte_en_https(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
        simular_terminal(monkeypatch)
        responder(
            monkeypatch,
            ["http://aula.ejemplo.org/centro", "profe", "", "", ""],
        )
        pedidas: list = []

        class RespuestaFalsa:
            url = "https://aula.ejemplo.org/centro/"
            status_code = 200

        monkeypatch.setattr(
            config.requests, "get", lambda url, **k: pedidas.append(url) or RespuestaFalsa()
        )
        assert cli.main(["configurar"]) == 0
        assert pedidas == ["https://aula.ejemplo.org/centro"]


class TestInstalarSkill:
    def test_copia_la_skill_a_los_destinos(self, tmp_path):
        destinos = cli.instalar_skill(tmp_path)
        assert len(destinos) == 4
        for destino in destinos:
            assert destino.is_file()
            assert destino.name == "SKILL.md"
            assert "tiza comprobar" in destino.read_text(encoding="utf-8")
        nombres = {destino.relative_to(tmp_path).as_posix() for destino in destinos}
        assert nombres == {
            ".claude/skills/tiza/SKILL.md",
            ".agents/skills/tiza/SKILL.md",
            ".codex/skills/tiza/SKILL.md",
            ".config/opencode/skills/tiza/SKILL.md",
        }


def informe_ok(*, comando="publicar", entorno="pruebas", curso=1234) -> dict:
    return {
        "version": 1,
        "comando": comando,
        "entorno": entorno,
        "curso": curso,
        "resultado": "ok",
        "pasos": [{"codigo": "LOGIN", "resultado": "ok", "detalle": None}],
        "ficheros": [],
        "errores": [],
    }


def peticion_publicar(ficheros=("pagina.md",), entorno="pruebas", **cambios) -> dict:
    peticion = {
        "version": 1,
        "id": "a" * 32,
        "comando": "publicar",
        "ficheros": list(ficheros),
        "entorno": entorno,
        "visible": False,
    }
    peticion.update(cambios)
    return peticion


def peticion_estructura() -> dict:
    return {
        "version": 1,
        "id": "a" * 32,
        "comando": "estructura",
        "ficheros": [],
        "entorno": None,
        "visible": False,
    }


class TestBuzonAgente:
    def test_publicar_con_sesion_usa_el_buzon_sin_tty_ni_password(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        salida = simular_terminal(monkeypatch, interactiva=False)
        monkeypatch.setattr(buzon, "sesion_activa", lambda *a, **k: True)

        def no_password():
            raise AssertionError("con sesión abierta no se pide la contraseña")

        monkeypatch.setattr(terminal, "pedir_password", no_password)
        capturado: dict = {}

        def enviar(dir_tiza, peticion, *a, **k):
            capturado["peticion"] = peticion
            return informe_ok()

        monkeypatch.setattr(buzon, "enviar", enviar)
        assert cli.main(["publicar", "pagina.md", "--en", "pruebas"]) == 0
        enviada = capturado["peticion"]
        assert enviada["comando"] == "publicar"
        assert enviada["entorno"] == "pruebas"
        assert enviada["ficheros"] == ["pagina.md"]
        assert enviada["visible"] is None
        assert len(enviada["id"]) == 32 and enviada["id"] == enviada["id"].lower()
        assert "Informe: ok" in salida.contenido()

    def test_publicar_con_sesion_devuelve_error_sin_password(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        simular_terminal(monkeypatch, interactiva=False)
        monkeypatch.setattr(buzon, "sesion_activa", lambda *a, **k: True)

        def no_password():
            raise AssertionError("con sesión abierta no se pide la contraseña")

        monkeypatch.setattr(terminal, "pedir_password", no_password)
        respuesta = informe_ok()
        respuesta["resultado"] = "error"
        respuesta["errores"] = ["ERROR_CREACION"]
        monkeypatch.setattr(buzon, "enviar", lambda *a, **k: respuesta)
        assert cli.main(["publicar", "pagina.md", "--en", "pruebas"]) == 1

    def test_publicar_con_sesion_sin_respuesta_registra_informe(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        simular_terminal(monkeypatch, interactiva=False)
        monkeypatch.setattr(buzon, "sesion_activa", lambda *a, **k: True)

        def enviar(*a, **k):
            raise buzon.ErrorBuzon("SIN_RESPUESTA", "la sesión no respondió a tiempo")

        monkeypatch.setattr(buzon, "enviar", enviar)
        assert cli.main(["publicar", "pagina.md", "--en", "pruebas"]) == 1
        assert "SIN_RESPUESTA" in leer_informe(tmp_path)["errores"]

    def test_estructura_con_sesion_usa_el_buzon(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        salida = simular_terminal(monkeypatch, interactiva=False)
        monkeypatch.setattr(buzon, "sesion_activa", lambda *a, **k: True)
        capturado: dict = {}

        def enviar(dir_tiza, peticion, *a, **k):
            capturado["peticion"] = peticion
            return informe_ok(comando="estructura", entorno=None, curso=None)

        monkeypatch.setattr(buzon, "enviar", enviar)
        assert cli.main(["estructura"]) == 0
        assert capturado["peticion"]["comando"] == "estructura"
        assert capturado["peticion"]["entorno"] is None
        assert capturado["peticion"]["ficheros"] == []
        assert "Informe: ok" in salida.contenido()


def dejar_peticion(dir_tiza: Path, peticion: dict) -> None:
    carpeta = buzon.carpeta_buzon(dir_tiza)
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{peticion['id']}{buzon.SUFIJO_PETICION}").write_text(
        json.dumps(peticion), encoding="utf-8"
    )


def procesar(peticion, moodle, cfg, base, _dir_tiza=None, **opciones):
    """Lo que hace «tiza sesion» con una petición, con la presencia de la terminal."""
    return sesion.procesar_peticion(
        peticion, moodle, cfg, base, terminal.PresenciaTerminal(), **opciones
    )


class TestProcesarPeticion:
    def preparar(self, tmp_path, monkeypatch, cursos=None) -> object:
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        configurar(tmp_path, monkeypatch, cursos)
        return config.resolver(tmp_path)

    def test_pruebas_publica_sin_confirmar_y_registra_verificado(self, tmp_path, monkeypatch):
        cfg = self.preparar(tmp_path, monkeypatch)

        def no_confirmar(*a, **k):
            raise AssertionError("las publicaciones en pruebas no piden confirmación")

        monkeypatch.setattr(terminal, "confirmar_destino", no_confirmar)
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        documento = procesar(peticion_publicar(), MoodleFalso(), cfg, base, dir_tiza)
        assert documento["resultado"] == "ok"
        assert documento["entorno"] == "pruebas"
        assert documento["ficheros"][0]["cmid"] == 100
        assert (dir_tiza / "informe.json").is_file()
        verificados = publicar.cargar_verificados(dir_tiza)
        doc = contenido.cargar(tmp_path / "pagina.md")
        assert contenido.hash_documento(doc) in verificados

    def test_real_sin_verificar_rechaza(self, tmp_path, monkeypatch):
        cfg = self.preparar(tmp_path, monkeypatch)
        llamadas: list = []
        monkeypatch.setattr(
            terminal,
            "confirmar_destino",
            lambda entorno, curso, nombre=None: llamadas.append(entorno) or True,
        )
        base = tmp_path.resolve()
        documento = procesar(
            peticion_publicar(entorno="real"),
            MoodleFalso(),
            cfg,
            base,
            base / ".tiza",
        )
        assert "VERIFICACION_PENDIENTE" in documento["errores"]
        assert llamadas == []

    def test_real_con_no_queda_abortado(self, tmp_path, monkeypatch):
        cfg = self.preparar(tmp_path, monkeypatch)
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        monkeypatch.setattr(
            terminal, "confirmar_destino", lambda entorno, curso, nombre=None: False
        )
        moodle = MoodleFalso()
        documento = procesar(peticion_publicar(entorno="real"), moodle, cfg, base, dir_tiza)
        assert documento["resultado"] == "abortado"
        assert "ABORTADO" in documento["errores"]
        assert [llamada for llamada in moodle.llamadas if llamada[0] == "crear"] == []

    def test_real_con_si_publica(self, tmp_path, monkeypatch):
        cfg = self.preparar(tmp_path, monkeypatch)
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        llamadas: list = []
        monkeypatch.setattr(
            terminal,
            "confirmar_destino",
            lambda entorno, curso, nombre=None: llamadas.append((entorno, curso)) or True,
        )
        moodle = MoodleFalso()
        peticion = peticion_publicar(entorno="real")
        dejar_peticion(dir_tiza, peticion)
        documento = procesar(peticion, moodle, cfg, base, dir_tiza)
        assert documento["resultado"] == "ok"
        assert llamadas == [("real", 5678)]
        assert any(llamada[0] == "crear" for llamada in moodle.llamadas)

    def test_real_avisa_de_las_secciones_que_creara(self, tmp_path, monkeypatch, capsys):
        cfg = self.preparar(tmp_path, monkeypatch)
        escribir_pagina(tmp_path, PAGINA.replace("seccion: 3", 'seccion: "Fracciones"'))
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        monkeypatch.setattr(
            terminal, "confirmar_destino", lambda entorno, curso, nombre=None: False
        )
        moodle = MoodleFalso()
        procesar(peticion_publicar(entorno="real"), moodle, cfg, base, dir_tiza)
        assert "Se creará la sección «Fracciones» (oculta)" in capsys.readouterr().out
        assert not any(l[0] == "crear_seccion" for l in moodle.llamadas)

    def test_real_avisa_si_sera_visible(self, tmp_path, monkeypatch, capsys):
        cfg = self.preparar(tmp_path, monkeypatch)
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        monkeypatch.setattr(
            terminal, "confirmar_destino", lambda entorno, curso, nombre=None: False
        )
        procesar(
            peticion_publicar(entorno="real", visible=True), MoodleFalso(), cfg, base, dir_tiza
        )
        salida = capsys.readouterr().out
        assert "VISIBLE" in salida
        assert "verificado en pruebas" in salida
        procesar(peticion_publicar(entorno="real"), MoodleFalso(), cfg, base, dir_tiza)
        assert "oculto" in capsys.readouterr().out

    def test_real_sin_indicar_dice_que_conserva(self, tmp_path, monkeypatch, capsys):
        cfg = self.preparar(tmp_path, monkeypatch)
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: False)
        procesar(
            peticion_publicar(entorno="real", visible=None), MoodleFalso(), cfg, base, dir_tiza
        )
        assert "conserva su visibilidad" in capsys.readouterr().out

    def test_real_describe_lo_que_se_publica(self, tmp_path, monkeypatch, capsys):
        cfg = self.preparar(tmp_path, monkeypatch)
        (tmp_path / "pagina.md").write_text(TAREA, encoding="utf-8")
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        vistos: list = []
        monkeypatch.setattr(
            terminal,
            "confirmar_destino",
            lambda entorno, curso, nombre=None: vistos.append(nombre) or False,
        )
        procesar(
            peticion_publicar(entorno="real"),
            MoodleFalso(),
            cfg,
            base,
            dir_tiza,
            nombres={5678: "Matemáticas 2ºB"},
        )
        salida = capsys.readouterr().out
        assert "Tarea «Problemas» → sección «Fracciones»" in salida
        # Una fecha sin hora es fin de día en contenido._fecha (23:59).
        assert "entrega 10/10/2026 23:59" in salida
        assert "«Matemáticas 2ºB»" in salida
        assert vistos == ["Matemáticas 2ºB"]

    def test_real_regenera_y_enlaza_la_vista_previa(self, tmp_path, monkeypatch, capsys):
        cfg = self.preparar(tmp_path, monkeypatch)
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        vista = dir_tiza / "preview" / "pagina.html"
        vista.parent.mkdir(parents=True, exist_ok=True)
        vista.write_text("vieja", encoding="utf-8")
        monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: False)
        procesar(peticion_publicar(entorno="real"), MoodleFalso(), cfg, base, dir_tiza)
        salida = capsys.readouterr().out
        assert f"vista previa: {vista.resolve().as_uri()}" in salida
        assert vista.read_text(encoding="utf-8") != "vieja"

    def test_texto_del_agente_no_inyecta_escapes(self, tmp_path, monkeypatch, capsys):
        cfg = self.preparar(tmp_path, monkeypatch)
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        monkeypatch.setattr(
            contenido, "cargar", lambda ruta, *a, **k: _con_nombre(doc, "Repaso\x1b[2K")
        )
        monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: False)
        monkeypatch.setattr(sesion, "puerta_real", lambda *a, **k: [])
        procesar(peticion_publicar(entorno="real"), MoodleFalso(), cfg, base, dir_tiza)
        assert "\x1b" not in capsys.readouterr().out

    def test_real_confirmado_tarde_no_publica(self, tmp_path, monkeypatch):
        cfg = self.preparar(tmp_path, monkeypatch)
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        monkeypatch.setattr(terminal, "confirmar_destino", lambda entorno, curso, nombre=None: True)
        moodle = MoodleFalso()
        # El agente ya desistió: no hay fichero de petición en el buzón.
        documento = procesar(peticion_publicar(entorno="real"), moodle, cfg, base, dir_tiza)
        assert "PETICION_RETIRADA" in documento["errores"]
        assert [llamada for llamada in moodle.llamadas if llamada[0] == "crear"] == []

    def test_real_con_peticion_sin_renovar_no_publica(self, tmp_path, monkeypatch):
        cfg = self.preparar(tmp_path, monkeypatch)
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: True)
        peticion = peticion_publicar(entorno="real")
        dejar_peticion(dir_tiza, peticion)
        ruta = buzon.carpeta_buzon(dir_tiza) / f"{peticion['id']}{buzon.SUFIJO_PETICION}"
        viejo = time.time() - buzon.LATIDO_MAX - 1
        os.utime(ruta, (viejo, viejo))  # al agente lo mató su herramienta sin avisar
        moodle = MoodleFalso()
        documento = procesar(peticion, moodle, cfg, base, dir_tiza)
        assert "PETICION_RETIRADA" in documento["errores"]
        assert not any(llamada[0] == "crear" for llamada in moodle.llamadas)

    def test_real_lista_los_ficheros_que_se_suben(self, tmp_path, monkeypatch, capsys):
        cfg = self.preparar(tmp_path, monkeypatch)
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "foto.png").write_bytes(b"png")
        escribir_pagina(tmp_path, PAGINA.replace("Contenido.", "![foto](img/foto.png)"))
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: False)
        procesar(peticion_publicar(entorno="real"), MoodleFalso(), cfg, base, dir_tiza)
        assert "se sube el fichero img/foto.png" in capsys.readouterr().out

    def test_minutos_tiene_limite(self):
        with pytest.raises(SystemExit):
            cli._parser().parse_args(["sesion", "--minutos", "100000"])
        assert cli._parser().parse_args(["sesion", "--minutos", "480"]).minutos == 480

    def test_tiza_toml_posterior_no_redirige_la_sesion(self, tmp_path, monkeypatch):
        cfg = self.preparar(tmp_path, monkeypatch)
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        (tmp_path / "tiza.toml").write_text("[cursos]\nreal = 2222\n", encoding="utf-8")
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        llamadas: list = []
        monkeypatch.setattr(
            terminal,
            "confirmar_destino",
            lambda entorno, curso, nombre=None: llamadas.append((entorno, curso)) or True,
        )
        documento = procesar(
            peticion_publicar(entorno="real"),
            MoodleFalso(),
            cfg,
            base,
            dir_tiza,
        )
        assert llamadas == [("real", 5678)]
        assert documento["curso"] == 5678

    def test_recurso_fuera_de_la_carpeta(self, tmp_path, monkeypatch):
        base = tmp_path / "asignatura"
        base.mkdir()
        (tmp_path / "fuera.png").write_bytes(b"png")
        (base / "pagina.md").write_text(
            "---\ntipo: pagina\nnombre: Repaso\nseccion: 3\n---\n\n![x](../fuera.png)\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(base)
        configurar(base, monkeypatch)
        cfg = config.resolver(base)
        documento = procesar(
            peticion_publicar(),
            MoodleFalso(),
            cfg,
            base.resolve(),
            base / ".tiza",
        )
        assert "RUTA_FUERA_DE_CARPETA" in documento["errores"]

    def test_error_de_moodle_no_se_filtra(self, tmp_path, monkeypatch):
        cfg = self.preparar(tmp_path, monkeypatch)

        class MoodleQueFalla(MoodleFalso):
            def crear(self, curso_id, seccion_id, tipo, payload):
                raise publicar.ErrorPublicacion("ERROR_CREACION")

        base = tmp_path.resolve()
        documento = procesar(peticion_publicar(), MoodleQueFalla(), cfg, base, base / ".tiza")
        texto = json.dumps(documento)
        assert documento["resultado"] == "error"
        assert "ERROR_CREACION" in documento["errores"]
        assert "<" not in texto

    def test_estructura_actualiza_el_fichero(self, tmp_path, monkeypatch):
        cfg = self.preparar(tmp_path, monkeypatch)
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        documento = procesar(peticion_estructura(), MoodleFalso(), cfg, base, dir_tiza)
        assert documento["resultado"] == "ok"
        datos = json.loads((dir_tiza / "estructura.json").read_text(encoding="utf-8"))
        assert datos["cursos"]["pruebas"]["id"] == 1234
        assert datos["cursos"]["real"]["id"] == 5678

    def test_real_lista_tambien_las_imagenes_externas(self, tmp_path, monkeypatch, capsys):
        cfg = self.preparar(tmp_path, monkeypatch)
        escribir_pagina(
            tmp_path, PAGINA.replace("Contenido.", "![x](https://cdn.example.org/p.png)")
        )
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: False)
        procesar(peticion_publicar(entorno="real"), MoodleFalso(), cfg, base, dir_tiza)
        assert "enlace externo: https://cdn.example.org/p.png" in capsys.readouterr().out

    def test_real_lista_los_iframes_como_incrustados(self, tmp_path, monkeypatch, capsys):
        cfg = self.preparar(tmp_path, monkeypatch)
        escribir_pagina(
            tmp_path,
            PAGINA.replace(
                "Contenido.", '<iframe src="https://www.youtube.com/embed/abc"></iframe>'
            ),
        )
        base = tmp_path.resolve()
        dir_tiza = base / ".tiza"
        doc = contenido.cargar(tmp_path / "pagina.md")
        publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "pagina.md", 100)
        monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: False)
        procesar(peticion_publicar(entorno="real"), MoodleFalso(), cfg, base, dir_tiza)
        salida = capsys.readouterr().out
        assert "incrusta: https://www.youtube-nocookie.com/embed/abc" in salida
        assert "enlace externo" not in salida

    def test_estructura_fuera_del_esquema_no_se_escribe(self, tmp_path, monkeypatch):
        cfg = self.preparar(tmp_path, monkeypatch)
        moodle = MoodleFalso(
            secciones=[{"numero": 1, "nombre": "<b>x</b>", "id": 9, "modulos": []}]
        )
        documento = sesion.estructura_con(moodle, cfg, tmp_path)
        assert documento["errores"] == ["ESTRUCTURA_INVALIDA"]
        assert not (tmp_path / ".tiza" / "estructura.json").exists()


ETIQUETAS = (
    "a1\trefs/tags/v0.4.0\nb2\trefs/tags/v0.10.0\nc3\trefs/tags/v0.5.1\nd4\trefs/tags/prueba\n"
)


class TestActualizar:
    @pytest.fixture
    def ejecutadas(self, monkeypatch):
        """Simula uv y git: ls-remote devuelve ETIQUETAS; lo demás, el código de `fallos`."""
        ejecutadas: list[list[str]] = []
        self.fallos: dict[str, int] = {}
        self.etiquetas = ETIQUETAS
        monkeypatch.delenv("TIZA_REF", raising=False)
        monkeypatch.setattr(cli, "__version__", "0.5.1")
        monkeypatch.setattr(cli.shutil, "which", lambda nombre: f"/bin/{nombre}")
        # «actualizar» es del docente: hace falta terminal y se confirma. No se sustituye
        # sys.stdout, para que capsys siga viendo la salida.
        monkeypatch.setattr(cli.terminal, "exigir_tty", lambda: None)
        monkeypatch.setattr("builtins.input", lambda _prompt="": "s")

        def run(cmd, **_k):
            ejecutadas.append(cmd)
            codigo = self.fallos.get(cmd[1], 0)
            salida = self.etiquetas if cmd[1] == "ls-remote" else ""
            return type("R", (), {"returncode": codigo, "stdout": salida})()

        monkeypatch.setattr(cli.subprocess, "run", run)
        return ejecutadas

    def test_instala_la_ultima_etiqueta_y_reinstala_la_skill(self, ejecutadas):
        assert cli.main(["actualizar"]) == 0
        assert ejecutadas[1:] == [
            ["/bin/uv", "tool", "install", "--force", f"git+{cli.REPO_GIT}@v0.10.0"],
            ["/bin/tiza", "instalar-skill"],
        ]
        assert ejecutadas[0][:2] == ["/bin/git", "ls-remote"]

    def test_sin_terminal_no_hace_nada(self, monkeypatch, capsys):
        monkeypatch.delenv("TIZA_REF", raising=False)
        ordenes: list = []
        monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: ordenes.append(a))
        simular_terminal(monkeypatch, interactiva=False)
        assert cli.main(["actualizar"]) == 1
        assert ordenes == []
        assert "SIN_TTY" in capsys.readouterr().err

    def test_pide_confirmacion_con_la_version_y_si_dice_no_no_instala(
        self, ejecutadas, monkeypatch
    ):
        preguntas: list[str] = []
        monkeypatch.setattr("builtins.input", lambda prompt="": preguntas.append(prompt) or "n")
        assert cli.main(["actualizar"]) == 1
        assert [orden[1] for orden in ejecutadas] == ["ls-remote"]  # no llegó a instalar
        assert "v0.10.0" in preguntas[0] and cli.REPO_GIT in preguntas[0]

    @pytest.mark.parametrize(
        "ref", ["-x", "a b", "a;b", "$(id)", "../x", "a/../b", "a@b", "x" * 101, "-"]
    )
    def test_tiza_ref_invalido_se_rechaza(self, ejecutadas, monkeypatch, capsys, ref):
        monkeypatch.setenv("TIZA_REF", ref)
        assert cli.main(["actualizar"]) == 1
        assert ejecutadas == []
        assert "REF_NO_VALIDA" in capsys.readouterr().err

    @pytest.mark.parametrize("ref", ["main", "v0.7.1", "feature/x-1.2", "a" * 100])
    def test_tiza_ref_valido_se_acepta(self, ejecutadas, monkeypatch, ref):
        monkeypatch.setenv("TIZA_REF", ref)
        assert cli.main(["actualizar"]) == 0
        assert ejecutadas[0][-1] == f"git+{cli.REPO_GIT}@{ref}"

    def test_con_la_ultima_version_no_reinstala_nada(self, ejecutadas, capsys):
        self.etiquetas = "a1\trefs/tags/v0.5.1\n"
        assert cli.main(["actualizar"]) == 0
        assert len(ejecutadas) == 1
        assert "Ya tienes la última versión (0.5.1)" in capsys.readouterr().out

    def test_tiza_ref_elige_la_version_sin_consultar_etiquetas(self, ejecutadas, monkeypatch):
        monkeypatch.setenv("TIZA_REF", "main")
        assert cli.main(["actualizar"]) == 0
        assert ejecutadas[0] == [
            "/bin/uv",
            "tool",
            "install",
            "--force",
            f"git+{cli.REPO_GIT}@main",
        ]

    @pytest.mark.parametrize("etiquetas", ["", "d4\trefs/tags/prueba\n"])
    def test_sin_etiquetas_falla_sin_instalar(self, ejecutadas, capsys, etiquetas):
        self.etiquetas = etiquetas
        assert cli.main(["actualizar"]) == 1
        assert len(ejecutadas) == 1
        assert "ACTUALIZACION_FALLIDA" in capsys.readouterr().err

    def test_si_git_falla_no_instala(self, ejecutadas, capsys):
        self.fallos["ls-remote"] = 128
        assert cli.main(["actualizar"]) == 1
        assert len(ejecutadas) == 1
        assert "ACTUALIZACION_FALLIDA" in capsys.readouterr().err

    def test_sin_git_falla_con_codigo_claro(self, ejecutadas, monkeypatch, capsys):
        monkeypatch.setattr(cli.shutil, "which", lambda nombre: None if nombre == "git" else "/x")
        assert cli.main(["actualizar"]) == 1
        assert ejecutadas == []
        assert "GIT_NO_ENCONTRADO" in capsys.readouterr().err

    def test_sin_uv_falla_con_codigo_claro(self, monkeypatch, capsys):
        monkeypatch.setattr(cli.terminal, "exigir_tty", lambda: None)
        monkeypatch.setattr(cli.shutil, "which", lambda nombre: None)
        assert cli.main(["actualizar"]) == 1
        assert "UV_NO_ENCONTRADO" in capsys.readouterr().err

    def test_si_uv_falla_no_toca_la_skill(self, ejecutadas, capsys):
        self.fallos["tool"] = 1
        assert cli.main(["actualizar"]) == 1
        assert len(ejecutadas) == 2
        assert "ACTUALIZACION_FALLIDA" in capsys.readouterr().err


def test_la_puerta_real_de_la_sesion_ignora_verificados_json(tmp_path):
    from tiza import contenido

    md = tmp_path / "p.md"
    md.write_text("---\ntipo: pagina\nnombre: P\nseccion: 1\n---\n\nhola\n", encoding="utf-8")
    doc = contenido.cargar(md)
    dir_tiza = tmp_path / ".tiza"
    publicar.guardar_verificado(dir_tiza, contenido.hash_documento(doc), "p.md", 7)
    assert sesion.puerta_real(tmp_path, [doc]) == []
    assert sesion.puerta_real(tmp_path, [doc], {}) == ["p.md"]


def test_el_cupo_de_pruebas_se_agota(tmp_path):
    md = tmp_path / "p.md"
    md.write_text("---\ntipo: pagina\nnombre: P\nseccion: 1\n---\n\nhola\n", encoding="utf-8")
    peticion = {
        "version": 1,
        "id": "a" * 32,
        "comando": "publicar",
        "ficheros": ["p.md"],
        "entorno": "pruebas",
        "visible": False,
    }
    cfg = config.Config(
        url="https://aula.ejemplo.org", usuario="u", cursos={"pruebas": 1, "real": 2}
    )
    cupo = {"pruebas": sesion.MAX_PUBLICACIONES_PRUEBAS}
    documento = procesar(
        peticion, MoodleFalso(), cfg, tmp_path.resolve(), tmp_path / ".tiza", cupo=cupo
    )
    assert documento["errores"] == ["LIMITE_PUBLICACIONES"]


def test_error_interno_explica_que_hacer(monkeypatch, capsys):
    def romper(_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "_despachar", romper)
    assert cli.main(["actualizar"]) == 1
    err = capsys.readouterr().err
    assert "ERROR [ERROR_INTERNO]" in err
    assert "Qué hacer: " in err


def test_avisar_error_interno_explica_que_hacer(capsys):
    sesion._error_interno(RuntimeError("boom"), terminal.PresenciaTerminal(), debug=False)
    err = capsys.readouterr().err
    assert "ERROR [ERROR_INTERNO]" in err
    assert "Qué hacer: " in err


def test_si_falla_la_escritura_del_informe_aun_explica(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".tiza").write_text("no soy un directorio", encoding="utf-8")
    cli._escribir(informe.crear("publicar", "error", [], [], ["SIN_SESION"]))
    salida = capsys.readouterr()
    assert "Qué hacer (SIN_SESION): " in salida.out
    assert "AVISO" in salida.err


TAREA = (
    '---\ntipo: tarea\nnombre: Problemas\nseccion: "Fracciones"\n'
    "apertura: 2026-10-01\nentrega: 2026-10-10\n---\n\nResuelve.\n"
)


def _con_nombre(doc, nombre):
    import dataclasses

    return dataclasses.replace(doc, nombre=nombre)


def abrir_sesion_falsa(
    tmp_path,
    monkeypatch,
    respuestas,
    moodle=None,
    cursos=None,
    ampliar=(),
    comando="sesion",
    configurado=True,
    autoprueba_ok=True,
):
    """Ejecuta un comando autenticado sin red: login falso y atención que termina al instante."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
    if configurado:
        config.guardar_global(
            "https://aula.ejemplo.org/centro",
            "profe",
            {"pruebas": 1234, "real": 5678} if cursos is None else cursos,
        )
    salida = simular_terminal(monkeypatch)
    responder(monkeypatch, respuestas)
    moodle = moodle or MoodleFalso()
    monkeypatch.setattr(publicar, "autenticar", lambda url, usuario, password: moodle)
    atendidas: list = []
    monkeypatch.setattr(buzon, "atender", lambda *a, **k: atendidas.append(a) or False)
    respuestas_ampliar = iter(ampliar)
    monkeypatch.setattr(
        terminal,
        "preguntar_con_limite",
        lambda *a, **k: next(respuestas_ampliar, False),
    )
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setattr(cli, "_home", lambda: home)
    monkeypatch.setattr(cli, "_sistema", lambda: "Linux")
    if autoprueba_ok:  # si es False, el test pone su propio doble de autoprueba
        monkeypatch.setattr(
            publicar, "autoprueba", lambda m, c: {"resultado": "ok", "pasos": [], "errores": []}
        )
    codigo = cli.main([comando])
    return codigo, salida.contenido(), atendidas


class TestSesionConNombres:
    def test_confirma_con_los_nombres(self, tmp_path, monkeypatch):
        codigo, salida, atendidas = abrir_sesion_falsa(tmp_path, monkeypatch, ["s"])
        assert codigo == 0
        assert "«Pruebas de Mates» (id 1234)" in salida
        assert "«Matemáticas 2ºB» (id 5678)" in salida
        assert len(atendidas) == 1

    def test_no_abre_si_el_docente_dice_que_no(self, tmp_path, monkeypatch):
        codigo, _salida, atendidas = abrir_sesion_falsa(tmp_path, monkeypatch, ["n"])
        assert codigo == 1
        assert atendidas == []
        assert "ABORTADO" in leer_informe(tmp_path)["errores"]

    def test_elige_cursos_que_faltan_y_los_guarda(self, tmp_path, monkeypatch):
        # pruebas: opción 2 (Pruebas de Mates); real: la lista ya no la incluye -> 1
        codigo, _salida, atendidas = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["2", "1", "s"], cursos={}
        )
        assert codigo == 0
        assert config.cargar_carpeta(tmp_path)["cursos"] == {"pruebas": 1234, "real": 5678}
        assert len(atendidas) == 1

    def test_sin_lista_de_cursos_pide_el_id(self, tmp_path, monkeypatch):
        class SinLista(MoodleFalso):
            def mis_cursos(self):
                raise publicar.ErrorPublicacion("ERROR_CURSOS")

        codigo, salida, _ = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["1234", "5678", "s"], moodle=SinLista(), cursos={}
        )
        assert codigo == 0
        assert "id 1234" in salida

    def test_avisa_si_el_curso_no_es_tuyo(self, tmp_path, monkeypatch):
        _codigo, salida, _ = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["n"], cursos={"pruebas": 1234, "real": 9999}
        )
        assert "no aparece entre tus cursos" in salida

    def test_nombre_de_curso_de_moodle_se_sanea(self, tmp_path, monkeypatch):
        moodle = MoodleFalso(
            cursos=[
                {"id": 1234, "nombre": "Prue\x1b[2Kbas"},
                {"id": 5678, "nombre": "Real\N{RIGHT-TO-LEFT OVERRIDE}"},
            ]
        )
        _codigo, salida, _ = abrir_sesion_falsa(tmp_path, monkeypatch, ["n"], moodle=moodle)
        assert "\x1b" not in salida and "\N{RIGHT-TO-LEFT OVERRIDE}" not in salida

    def test_los_nombres_de_curso_no_llegan_a_tiza(self, tmp_path, monkeypatch):
        abrir_sesion_falsa(tmp_path, monkeypatch, ["s"])
        for ruta in (tmp_path / ".tiza").rglob("*"):
            if ruta.is_file():
                texto = ruta.read_text(encoding="utf-8")
                assert "Matemáticas" not in texto and "Pruebas de Mates" not in texto


class TestAmpliarSesion:
    def test_ampliar_y_luego_cerrar(self, tmp_path, monkeypatch):
        codigo, salida, atendidas = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["s"], ampliar=[True, False]
        )
        assert codigo == 0
        assert len(atendidas) == 2
        assert "La sesión ha caducado; se cierra." in salida

    def test_sin_ampliar_cierra(self, tmp_path, monkeypatch):
        _codigo, _salida, atendidas = abrir_sesion_falsa(tmp_path, monkeypatch, ["s"])
        assert len(atendidas) == 1

    def test_ampliacion_no_supera_el_maximo(self, monkeypatch):
        apertura = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
        monkeypatch.setattr(terminal, "preguntar_con_limite", lambda *a, **k: True)
        casi = apertura + timedelta(minutes=sesion.MAX_MINUTOS - 10)
        assert sesion._ofrecer_ampliacion(
            apertura, casi, terminal.PresenciaTerminal(), ahora=lambda: casi
        ) == apertura + timedelta(minutes=sesion.MAX_MINUTOS)

    def test_ampliacion_cuenta_desde_la_caducidad(self, monkeypatch):
        apertura = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
        caduca = apertura + timedelta(minutes=60)
        monkeypatch.setattr(terminal, "preguntar_con_limite", lambda *a, **k: True)
        assert sesion._ofrecer_ampliacion(
            apertura, caduca, terminal.PresenciaTerminal(), ahora=lambda: apertura
        ) == caduca + timedelta(minutes=sesion.AMPLIACION_MINUTOS)

    def test_al_maximo_no_pregunta(self, monkeypatch, capsys):
        apertura = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)

        def no_preguntar(*a, **k):
            raise AssertionError("no debe preguntar al llegar al máximo")

        monkeypatch.setattr(terminal, "preguntar_con_limite", no_preguntar)
        fin = apertura + timedelta(minutes=sesion.MAX_MINUTOS)
        assert (
            sesion._ofrecer_ampliacion(
                apertura, fin, terminal.PresenciaTerminal(), ahora=lambda: fin
            )
            is None
        )
        assert "máximo" in capsys.readouterr().out

    def test_aviso_previo_una_sola_vez(self, monkeypatch, capsys):
        class Sesion:
            caduca = datetime.now(UTC) + timedelta(minutes=3)

        avisar = sesion._aviso_previo(Sesion(), terminal.PresenciaTerminal())
        avisar()
        avisar()
        assert capsys.readouterr().out.count("Quedan menos de") == 1

    def test_el_cupo_se_conserva_al_ampliar(self, tmp_path, monkeypatch):
        # procesar (y con él cupo_sesion y verificados_sesion) es el mismo objeto
        # en todas las vueltas, y cada vuelta caduca más tarde que la anterior.
        _codigo, _salida, atendidas = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["s"], ampliar=[True, False]
        )
        # atendidas guarda los argumentos posicionales: (dir_tiza, procesar, caduca)
        assert atendidas[0][1] is atendidas[1][1]
        assert atendidas[1][2] > atendidas[0][2]


class TestAislar:
    def preparar(self, tmp_path, monkeypatch, ajustes=None):
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        if ajustes is not None:
            (home / ".claude" / "settings.json").write_text(json.dumps(ajustes), encoding="utf-8")
        monkeypatch.setattr(cli, "_home", lambda: home)
        monkeypatch.setattr(cli, "_sistema", lambda: "Linux")
        monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
        monkeypatch.chdir(tmp_path)
        return home

    def test_revisar_falla_si_falta(self, tmp_path, monkeypatch, capsys):
        self.preparar(tmp_path, monkeypatch)
        assert cli.main(["revisar"]) == 1
        salida = capsys.readouterr().out
        assert "[FALTA] Claude Code: sandbox activado" in salida
        assert "tiza aislar" in salida

    def test_revisar_no_muestra_secretos(self, tmp_path, monkeypatch, capsys):
        self.preparar(tmp_path, monkeypatch, {"env": {"ANTHROPIC_API_KEY": "sk-secreta"}})
        cli.main(["revisar"])
        assert "sk-secreta" not in capsys.readouterr().out

    def test_aislar_sin_tty_no_toca_nada(self, tmp_path, monkeypatch):
        home = self.preparar(tmp_path, monkeypatch, {"a": 1})
        simular_terminal(monkeypatch, interactiva=False)
        assert cli.main(["aislar"]) == 1
        assert json.loads((home / ".claude" / "settings.json").read_text("utf-8")) == {"a": 1}

    def test_aislar_con_no_no_toca_nada(self, tmp_path, monkeypatch):
        home = self.preparar(tmp_path, monkeypatch, {"a": 1})
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["n"])
        assert cli.main(["aislar", "--global"]) == 1
        assert json.loads((home / ".claude" / "settings.json").read_text("utf-8")) == {"a": 1}

    def test_aislar_escribe_con_copia_y_luego_revisar_pasa(self, tmp_path, monkeypatch):
        home = self.preparar(tmp_path, monkeypatch, {"env": {"ANTHROPIC_API_KEY": "sk-secreta"}})
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar", "--global"]) == 0
        datos = json.loads((home / ".claude" / "settings.json").read_text("utf-8"))
        assert datos["env"] == {"ANTHROPIC_API_KEY": "sk-secreta"}
        assert datos["sandbox"]["enabled"] is True
        assert list((home / ".claude").glob("settings.json.antes-de-tiza-*"))
        assert cli.main(["revisar"]) == 0

    def test_aislar_sin_cambios_no_escribe(self, tmp_path, monkeypatch):
        from tiza import aislamiento

        completo, _ = aislamiento.fusionar_claude({}, "Linux")
        home = self.preparar(tmp_path, monkeypatch, completo)
        simular_terminal(monkeypatch)
        responder(monkeypatch, [])  # no debe preguntar
        assert cli.main(["aislar", "--global"]) == 0
        assert not list((home / ".claude").glob("*.antes-de-tiza-*"))

    def test_aislar_ajustes_rotos_no_los_toca(self, tmp_path, monkeypatch):
        home = self.preparar(tmp_path, monkeypatch)
        (home / ".claude" / "settings.json").write_text("{roto", encoding="utf-8")
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar", "--global"]) == 1
        assert (home / ".claude" / "settings.json").read_text("utf-8") == "{roto"

    def preparar_codex(self, tmp_path, monkeypatch, texto=""):
        home = tmp_path / "home"
        (home / ".codex").mkdir(parents=True)
        (home / ".codex" / "config.toml").write_text(texto, encoding="utf-8")
        monkeypatch.setattr(cli, "_home", lambda: home)
        monkeypatch.setattr(cli, "_sistema", lambda: "Linux")
        monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
        monkeypatch.chdir(tmp_path)
        return home

    def test_aislar_completa_codex_y_no_edita_opencode(self, tmp_path, monkeypatch):
        home = self.preparar_codex(tmp_path, monkeypatch, '# mi config\nmodel = "gpt"\n')
        carpeta = home / ".config" / "opencode"
        carpeta.mkdir(parents=True)
        original = aislamiento.contenido_opencode("Linux")
        (carpeta / "opencode.json").write_text(original, encoding="utf-8")
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar", "--global"]) == 0
        texto = (home / ".codex" / "config.toml").read_text("utf-8")
        assert 'sandbox_mode = "workspace-write"' in texto
        assert "# mi config" in texto
        assert (carpeta / "opencode.json").read_text("utf-8") == original
        assert not (carpeta / "opencode.jsonc").exists()

    def test_aislar_global_crea_opencode_si_no_existe(self, tmp_path, monkeypatch):
        home = self.preparar(tmp_path, monkeypatch)
        (home / ".config" / "opencode").mkdir(parents=True)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar", "--global"]) == 0
        assert (home / ".config" / "opencode" / "opencode.jsonc").is_file()
        assert cli.main(["revisar"]) == 0

    def test_aislar_global_avisa_si_opencode_existente_falla(self, tmp_path, monkeypatch):
        home = self.preparar(tmp_path, monkeypatch)
        carpeta = home / ".config" / "opencode"
        carpeta.mkdir(parents=True)
        existente = carpeta / "opencode.json"
        existente.write_text("{}", encoding="utf-8")
        salida = simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar", "--global"]) == 1
        assert existente.read_text("utf-8") == "{}"
        assert not (carpeta / "opencode.jsonc").exists()
        assert "añade a mano" in salida.contenido()

    def test_aislar_codex_ilegible_no_lo_toca(self, tmp_path, monkeypatch, capsys):
        home = self.preparar_codex(tmp_path, monkeypatch)
        original = b"\xff\xfe\x00roto"
        (home / ".codex" / "config.toml").write_bytes(original)
        simular_terminal(monkeypatch)
        assert cli.main(["aislar", "--global"]) == 1
        assert (home / ".codex" / "config.toml").read_bytes() == original
        assert "AJUSTES_ILEGIBLES" in capsys.readouterr().err

    def test_aislar_claude_no_regular_no_lo_toca(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        (home / ".claude" / "settings.json").mkdir(parents=True)
        monkeypatch.setattr(cli, "_home", lambda: home)
        monkeypatch.setattr(cli, "_sistema", lambda: "Linux")
        monkeypatch.chdir(tmp_path)
        simular_terminal(monkeypatch)
        assert cli.main(["aislar", "--global"]) == 1
        assert (home / ".claude" / "settings.json").is_dir()
        assert "AJUSTES_ILEGIBLES" in capsys.readouterr().err

    def preparar_proyecto(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".codex").mkdir()
        carpeta = tmp_path / "asignatura"
        carpeta.mkdir()
        (carpeta / "pagina.md").write_text(PAGINA, encoding="utf-8")
        monkeypatch.setattr(cli, "_home", lambda: home)
        monkeypatch.setattr(cli, "_sistema", lambda: "Linux")
        monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
        monkeypatch.chdir(carpeta)
        return home, carpeta

    def test_aislar_anade_el_servidor_configurado(self, tmp_path, monkeypatch):
        home = self.preparar(tmp_path, monkeypatch)
        config.guardar_global("https://aula.ejemplo.org/centro", "profe", {"real": 5678})
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar", "--global"]) == 0
        datos = json.loads((home / ".claude" / "settings.json").read_text("utf-8"))
        assert "aula.ejemplo.org" in datos["sandbox"]["network"]["deniedDomains"]
        assert "WebFetch(domain:aula.ejemplo.org)" in datos["permissions"]["deny"]
        assert cli.main(["revisar"]) == 0

    def test_aislar_por_defecto_solo_la_carpeta(self, tmp_path, monkeypatch):
        home, carpeta = self.preparar_proyecto(tmp_path, monkeypatch)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar"]) == 0
        proyecto = json.loads((carpeta / ".claude" / "settings.json").read_text("utf-8"))
        assert proyecto["sandbox"]["enabled"] is True
        codex = (carpeta / ".codex" / "config.toml").read_text("utf-8")
        assert 'sandbox_mode = "workspace-write"' in codex
        assert not (home / ".claude" / "settings.json").exists()
        global_codex = tomllib.loads((home / ".codex" / "config.toml").read_text("utf-8"))
        assert "sandbox_mode" not in global_codex
        assert global_codex["projects"][str(carpeta.resolve())]["trust_level"] == "trusted"
        assert cli.main(["revisar"]) == 0

    def test_aislar_crea_opencode_si_no_existe(self, tmp_path, monkeypatch):
        home, carpeta = self.preparar_proyecto(tmp_path, monkeypatch)
        (home / ".config" / "opencode").mkdir(parents=True)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar"]) == 0
        creada = carpeta / "opencode.jsonc"
        assert creada.is_file()
        datos = json.loads(creada.read_text("utf-8"))
        assert any(
            r.get("action") == "webfetch" and r.get("effect") == "deny"
            for r in datos["permissions"]
        )
        assert cli.main(["revisar"]) == 0

    def test_aislar_no_toca_opencode_existente(self, tmp_path, monkeypatch):
        home, carpeta = self.preparar_proyecto(tmp_path, monkeypatch)
        (home / ".config" / "opencode").mkdir(parents=True)
        existente = carpeta / "opencode.json"
        existente.write_text('{"permissions": []}', encoding="utf-8")
        salida = simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar"]) == 1
        assert existente.read_text("utf-8") == '{"permissions": []}'
        assert not (carpeta / "opencode.jsonc").exists()
        assert "añade a mano" in salida.contenido()
        assert "copia a mano las reglas" in salida.contenido()

    def test_aislar_avisa_si_opencode_ilegible(self, tmp_path, monkeypatch):
        home, carpeta = self.preparar_proyecto(tmp_path, monkeypatch)
        (home / ".config" / "opencode").mkdir(parents=True)
        existente = carpeta / "opencode.json"
        existente.write_text("{roto", encoding="utf-8")
        salida = simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar"]) == 0
        assert existente.read_text("utf-8") == "{roto"
        assert "añade a mano" in salida.contenido()

    def test_aislar_carpeta_que_no_parece_asignatura_pregunta(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        monkeypatch.setattr(cli, "_home", lambda: home)
        monkeypatch.setattr(cli, "_sistema", lambda: "Linux")
        monkeypatch.chdir(tmp_path)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["n"])
        assert cli.main(["aislar"]) == 1
        assert not (tmp_path / ".claude").exists()

    def test_revisar_avisa_si_solo_global(self, tmp_path, monkeypatch):
        self.preparar(tmp_path, monkeypatch)
        salida = simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar", "--global"]) == 0
        assert cli.main(["revisar"]) == 0
        assert "todos tus proyectos" in salida.contenido()

    def test_aislar_en_la_carpeta_personal_se_rechaza(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        monkeypatch.setattr(cli, "_home", lambda: home)
        monkeypatch.setattr(cli, "_sistema", lambda: "Linux")
        monkeypatch.chdir(home)
        simular_terminal(monkeypatch)
        responder(monkeypatch, [])
        assert cli.main(["aislar"]) == 1
        assert not (home / ".claude" / "settings.json").exists()
        assert not (home / ".codex").exists()
        assert "CARPETA_NO_VALIDA" in capsys.readouterr().err

    def test_aislar_error_no_deja_escrituras_a_medias(self, tmp_path, monkeypatch, capsys):
        _home, carpeta = self.preparar_proyecto(tmp_path, monkeypatch)
        (carpeta / ".claude").mkdir()
        (carpeta / ".claude" / "settings.json").mkdir()
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar"]) == 1
        assert not (carpeta / ".codex").exists()
        assert "AJUSTES_ILEGIBLES" in capsys.readouterr().err

    def test_aislar_proyecto_cancelado_no_escribe(self, tmp_path, monkeypatch):
        home, carpeta = self.preparar_proyecto(tmp_path, monkeypatch)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["n"])
        assert cli.main(["aislar"]) == 1
        assert not (carpeta / ".claude" / "settings.json").exists()
        assert not (carpeta / ".codex").exists()
        assert not (home / ".codex" / "config.toml").exists()

    def test_aislar_global_no_pregunta_por_la_carpeta(self, tmp_path, monkeypatch):
        self.preparar(tmp_path, monkeypatch)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli.main(["aislar", "--global"]) == 0


class TestAutopruebaRegistra:
    def test_autoprueba_ok_registra(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        configurar(tmp_path, monkeypatch)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        monkeypatch.setattr(publicar, "autenticar", lambda *a: MoodleFalso())
        monkeypatch.setattr(
            publicar,
            "autoprueba",
            lambda moodle, curso: {"resultado": "ok", "pasos": [], "errores": []},
        )
        assert cli.main(["autoprueba"]) == 0
        from datetime import date

        from tiza import __version__

        assert config.necesita_autoprueba(1234, date.today(), __version__) is False


class TestSinCursoDePruebasCli:
    def preparar_solo_real(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        configurar(tmp_path, monkeypatch, {"real": 5678})
        return simular_terminal(monkeypatch)

    def test_autoprueba_sin_curso_de_pruebas(self, tmp_path, monkeypatch):
        salida = self.preparar_solo_real(tmp_path, monkeypatch)
        assert cli.main(["autoprueba"]) == 1
        assert "SIN_CURSO_PRUEBAS" in leer_informe(tmp_path)["errores"]
        assert "Qué hacer (SIN_CURSO_PRUEBAS)" in salida.contenido()

    def test_publicar_en_pruebas_sin_curso(self, tmp_path, monkeypatch):
        salida = self.preparar_solo_real(tmp_path, monkeypatch)
        escribir_pagina(tmp_path)
        assert cli.main(["publicar", "pagina.md", "--en", "pruebas"]) == 1
        assert "SIN_CURSO_PRUEBAS" in leer_informe(tmp_path)["errores"]
        assert "Servidor" not in salida.contenido()  # ni siquiera pide la contraseña

    def test_estructura_directa_solo_con_el_curso_real(self, tmp_path, monkeypatch):
        self.preparar_solo_real(tmp_path, monkeypatch)
        responder(monkeypatch, ["s"])
        monkeypatch.setattr("tiza.publicar.autenticar", lambda *a, **k: MoodleFalso())
        assert cli.main(["estructura"]) == 0
        datos = json.loads((tmp_path / ".tiza" / "estructura.json").read_text(encoding="utf-8"))
        assert set(datos["cursos"]) == {"real"}
        assert datos["cursos"]["real"]["secciones"][0]["numero"] == 3

    @pytest.mark.parametrize("visibilidad", [[], ["--visible"]])
    def test_publicar_directo_en_real_sin_pruebas_exige_oculto(
        self, tmp_path, monkeypatch, visibilidad
    ):
        auto = self.preparar_solo_real(tmp_path, monkeypatch)
        escribir_pagina(tmp_path)
        llamadas: list = []
        monkeypatch.setattr(
            "tiza.publicar.autenticar", lambda *a, **k: llamadas.append(a) or MoodleFalso()
        )
        assert cli.main(["publicar", "pagina.md", "--en", "real", *visibilidad]) == 1
        informe = leer_informe(tmp_path)
        assert "SOLO_OCULTO_SIN_PRUEBAS" in informe["errores"]
        assert llamadas == []
        assert "Servidor" not in auto.contenido()  # no llega a pedir la contraseña

    def test_publicar_directo_en_real_sin_pruebas_oculto(self, tmp_path, monkeypatch):
        salida = self.preparar_solo_real(tmp_path, monkeypatch)
        escribir_pagina(tmp_path)
        responder(monkeypatch, ["s", "s"])  # destino y resumen corto
        monkeypatch.setattr("tiza.publicar.autenticar", lambda *a, **k: MoodleFalso())
        assert cli.main(["publicar", "pagina.md", "--en", "real", "--oculto"]) == 0
        informe = leer_informe(tmp_path)
        assert informe["resultado"] == "ok"
        assert informe["ficheros"][0]["oculto"] is True
        texto = salida.contenido()
        assert (
            "Sin curso de pruebas: se publicará solo en oculto en el curso "
            "«Matemáticas 2ºB» (id 5678)" in texto
        )
        assert "Página «Repaso»" in texto

    def test_publicar_directo_rechaza_el_destino_sin_pedir_password(self, tmp_path, monkeypatch):
        auto = self.preparar_solo_real(tmp_path, monkeypatch)
        escribir_pagina(tmp_path)
        responder(monkeypatch, ["n"])  # primer [s/N]: curso de destino

        def no_password():
            raise AssertionError("no se debe pedir la contraseña si cancela el destino")

        monkeypatch.setattr(terminal, "pedir_password", no_password)
        llamadas: list = []
        monkeypatch.setattr(
            "tiza.publicar.autenticar", lambda *a, **k: llamadas.append(a) or MoodleFalso()
        )
        assert cli.main(["publicar", "pagina.md", "--en", "real", "--oculto"]) == 1
        assert "ABORTADO" in leer_informe(tmp_path)["errores"]
        assert llamadas == []
        assert "Sin curso de pruebas: no habrá verificación previa" in auto.contenido()

    def test_publicar_directo_rechaza_el_resumen_y_no_publica(self, tmp_path, monkeypatch):
        self.preparar_solo_real(tmp_path, monkeypatch)
        escribir_pagina(tmp_path)
        responder(monkeypatch, ["s", "n"])  # destino sí, resumen corto no
        moodle = MoodleFalso()
        monkeypatch.setattr("tiza.publicar.autenticar", lambda *a, **k: moodle)
        assert cli.main(["publicar", "pagina.md", "--en", "real", "--oculto"]) == 1
        assert "ABORTADO" in leer_informe(tmp_path)["errores"]
        assert not any(llamada[0] == "crear" for llamada in moodle.llamadas)


class TestEmpezar:
    def test_abre_lee_estructura_y_atiende(self, tmp_path, monkeypatch):
        escribir_pagina(tmp_path)
        # cursos "s", autoprueba "n"
        codigo, salida, atendidas = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["s", "n"], comando="empezar"
        )
        assert codigo == 0
        assert len(atendidas) == 1
        assert (tmp_path / ".tiza" / "estructura.json").is_file()

    def test_primera_vez_configura(self, tmp_path, monkeypatch):
        escribir_pagina(tmp_path)

        class RespuestaFalsa:
            url = "https://aula.ejemplo.org/centro/"
            status_code = 200

        monkeypatch.setattr(config.requests, "get", lambda *a, **k: RespuestaFalsa())
        respuestas = [
            "https://aula.ejemplo.org",
            "profe",
            "",
            "",  # cursos
            "2",
            "1",  # elegir pruebas y real
            "s",  # confirmar cursos
            "n",  # autoprueba
        ]
        codigo, _salida, atendidas = abrir_sesion_falsa(
            tmp_path, monkeypatch, respuestas, comando="empezar", configurado=False
        )
        assert codigo == 0 and len(atendidas) == 1
        assert (tmp_path / "prefs" / "config.json").is_file()
        assert config.cargar_carpeta(tmp_path)["cursos"] == {"pruebas": 1234, "real": 5678}

    @pytest.mark.parametrize("nombre", ["tema.md", "tema.html", "tema.htm", "TEMA.HTML"])
    def test_una_carpeta_con_contenido_parece_asignatura(self, tmp_path, nombre):
        assert cli._parece_asignatura(tmp_path) is False
        (tmp_path / nombre).write_text("x", encoding="utf-8")
        assert cli._parece_asignatura(tmp_path) is True

    def test_carpeta_que_no_parece_asignatura_pregunta(self, tmp_path, monkeypatch):
        codigo, salida, atendidas = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["n"], comando="empezar"
        )
        assert codigo == 1 and atendidas == []
        assert "no parece la carpeta de una asignatura" in salida

    def test_falta_aislamiento_y_dice_que_no(self, tmp_path, monkeypatch):
        escribir_pagina(tmp_path)
        (tmp_path / "home" / ".claude").mkdir(parents=True)
        codigo, salida, atendidas = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["n", "n"], comando="empezar"
        )
        assert codigo == 1 and atendidas == []
        assert "[FALTA]" in salida and "no está aislada" in salida

    def test_empezar_ofrece_aislar_y_lo_aplica(self, tmp_path, monkeypatch):
        escribir_pagina(tmp_path)
        (tmp_path / "home" / ".claude").mkdir(parents=True)
        # aplicar: "s"; confirmar cambios: "s"; cursos: "s"; autoprueba: "n"
        codigo, _salida, atendidas = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["s", "s", "s", "n"], comando="empezar"
        )
        assert codigo == 0 and len(atendidas) == 1
        assert (tmp_path / ".claude" / "settings.json").is_file()

    def test_aislar_carpeta_en_descargas_queda_aislada(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        carpeta = home / "Descargas" / "IABach"
        carpeta.mkdir(parents=True)
        monkeypatch.setattr(cli, "_home", lambda: home)
        monkeypatch.setattr(cli, "_sistema", lambda: "Linux")
        monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        assert cli._aislar_carpeta(carpeta, "aula.ejemplo.org") is True
        ajustes = json.loads((carpeta / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert ajustes["sandbox"]["filesystem"]["allowRead"] == [str(carpeta.resolve())]

    def test_autoprueba_fallida_no_abre(self, tmp_path, monkeypatch):
        escribir_pagina(tmp_path)
        monkeypatch.setattr(
            publicar,
            "autoprueba",
            lambda m, c: {"resultado": "error", "pasos": [], "errores": ["ERROR_CREACION"]},
        )
        codigo, salida, atendidas = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["s", "s"], comando="empezar", autoprueba_ok=False
        )
        assert codigo == 1 and atendidas == []
        assert "Qué hacer (ERROR_CREACION)" in salida

    def test_autoprueba_ok_no_se_vuelve_a_ofrecer(self, tmp_path, monkeypatch):
        escribir_pagina(tmp_path)
        abrir_sesion_falsa(tmp_path, monkeypatch, ["s", "s"], comando="empezar")
        # Segunda vez: solo se confirman los cursos; si preguntara por la
        # autoprueba, responder() se quedaría sin respuestas y fallaría.
        codigo, _salida, atendidas = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["s"], comando="empezar"
        )
        assert codigo == 0 and len(atendidas) == 1

    def test_estructura_fallida_no_impide_la_sesion(self, tmp_path, monkeypatch):
        escribir_pagina(tmp_path)

        class SinEstructura(MoodleFalso):
            def estructura(self, curso_id):
                raise publicar.ErrorPublicacion("ERROR_ESTRUCTURA")

        codigo, salida, atendidas = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["s", "n"], comando="empezar", moodle=SinEstructura()
        )
        assert codigo == 0 and len(atendidas) == 1
        assert "ERROR_ESTRUCTURA" in salida

    def test_estructura_caducada_cierra(self, tmp_path, monkeypatch):
        escribir_pagina(tmp_path)

        class Caducada(MoodleFalso):
            def estructura(self, curso_id):
                raise publicar.ErrorPublicacion("SESION_CADUCADA")

        codigo, _salida, atendidas = abrir_sesion_falsa(
            tmp_path, monkeypatch, ["s", "n"], comando="empezar", moodle=Caducada()
        )
        assert codigo == 1 and atendidas == []


class TestUnaSolaSesionCli:
    def test_segunda_sesion_no_pide_la_contrasena(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        configurar(tmp_path, monkeypatch)
        simular_terminal(monkeypatch)
        buzon.crear_sesion(tmp_path / ".tiza", datetime.now(UTC) + timedelta(minutes=5))

        def no_password():
            raise AssertionError("no se debe pedir la contraseña")

        monkeypatch.setattr(terminal, "pedir_password", no_password)
        assert cli.main(["sesion"]) == 1
        assert "SESION_YA_ABIERTA" in leer_informe(tmp_path)["errores"]

    def test_reserva_ocupada_al_abrir_no_atiende(self, tmp_path, monkeypatch):
        carpeta = buzon.carpeta_buzon(tmp_path / ".tiza")
        carpeta.mkdir(parents=True)
        (carpeta / buzon.RESERVA).write_text("1\n", encoding="utf-8")
        codigo, _salida, atendidas = abrir_sesion_falsa(tmp_path, monkeypatch, ["s"])
        assert codigo == 1
        assert atendidas == []
        assert "SESION_YA_ABIERTA" in leer_informe(tmp_path)["errores"]


class TestAutopruebaConElDoble:
    def test_autoprueba_completa_desde_la_cli(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        configurar(tmp_path, monkeypatch)
        simular_terminal(monkeypatch)
        responder(monkeypatch, ["s"])
        monkeypatch.setattr(publicar, "autenticar", lambda *a: MoodleFalso())
        assert cli.main(["autoprueba"]) == 0
        codigos = [paso["codigo"] for paso in leer_informe(tmp_path)["pasos"]]
        assert codigos[0] == "LOGIN"
        assert "VERIFICAR_FECHAS" in codigos
        assert "LIMPIAR" in codigos


class TestVisibilidadCli:
    def test_oculto_y_visible_viajan_en_la_peticion(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        escribir_pagina(tmp_path)
        simular_terminal(monkeypatch, interactiva=False)
        monkeypatch.setattr(buzon, "sesion_activa", lambda *a, **k: True)
        enviadas: list = []
        monkeypatch.setattr(
            buzon,
            "enviar",
            lambda dir_tiza, peticion, *a, **k: enviadas.append(peticion) or informe_ok(),
        )
        cli.main(["publicar", "pagina.md", "--en", "pruebas", "--oculto"])
        cli.main(["publicar", "pagina.md", "--en", "pruebas", "--visible"])
        assert [peticion["visible"] for peticion in enviadas] == [False, True]

    def test_visible_y_oculto_son_incompatibles(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["publicar", "pagina.md", "--en", "pruebas", "--visible", "--oculto"])
        assert exc.value.code == 2


def test_ctrl_c_no_muestra_traza(monkeypatch, capsys):
    def interrumpir(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_despachar", interrumpir)
    assert cli.main(["comprobar", "x.md"]) == 130
    err = capsys.readouterr().err
    assert "Operación cancelada." in err
    assert "Traceback" not in err


def test_version_de_la_cli(capsys):
    from tiza import __version__

    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"tiza {__version__}"


def test_la_version_sale_de_pyproject():
    import tomllib

    from tiza import __version__

    raiz = Path(__file__).resolve().parents[1]
    datos = tomllib.loads((raiz / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == datos["project"]["version"]


def test_publicar_con_sesion_incompatible_lo_explica(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    escribir_pagina(tmp_path)
    simular_terminal(monkeypatch, interactiva=False)
    monkeypatch.setattr(buzon, "sesion_activa", lambda *a, **k: False)
    monkeypatch.setattr(buzon, "sesion_incompatible", lambda *a, **k: "9.0.0")
    assert cli.main(["publicar", "pagina.md", "--en", "pruebas"]) == 1
    assert "SESION_INCOMPATIBLE" in leer_informe(tmp_path)["errores"]
