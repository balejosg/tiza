"""Tests de la ventana de entrada sin pywebview: decisiones, tubería y caída a la terminal."""

from __future__ import annotations

import json
import subprocess
import sys
import types

import pytest

from tiza import cli, publicar, terminal, ventana
from tiza.ventana import entrada

AULA = "https://aula.example.org/centro"
disponible_de_verdad = ventana.disponible  # el conftest sustituye ventana.disponible en cada test


class TestEsPanel:
    def test_el_panel_del_aula_cuenta(self):
        assert entrada.es_panel(f"{AULA}/my/", AULA)
        assert entrada.es_panel(f"{AULA}/my", AULA)
        assert entrada.es_panel(f"{AULA}/my/?lang=es#x", AULA)

    def test_sin_el_panel_vuelve_a_mis_cursos(self):
        # Con el panel desactivado, Moodle manda /my/ a /my/courses.php.
        assert entrada.es_panel(f"{AULA}/my/courses.php", AULA)
        assert entrada.es_panel(f"{AULA}/my/index.php?lang=es", AULA)

    @pytest.mark.parametrize(
        "url",
        [
            None,
            "",
            f"{AULA}/login/index.php",
            f"{AULA}/admin/tool/mfa/auth.php",
            f"{AULA}/auth/oauth2/login.php",
            f"{AULA}/user/policy.php",  # se ve sin haber entrado: no vale como «dentro»
            f"{AULA}/",
            f"{AULA}/myself/",
            f"{AULA}/mycourses.php",
            "https://otro.example.org/centro/my/",
            "http://aula.example.org/centro/my/",
            "https://aula.example.org:8443/centro/my/",
            "https://aula.example.org/otro/my/",
            "https://aula.example.org.evil.example/centro/my/",
            "https://idp.example.org/login?service=https://aula.example.org/centro/my/",
        ],
    )
    def test_lo_demas_no_cuenta(self, url):
        assert not entrada.es_panel(url, AULA)


class TestCoincideDominio:
    @pytest.mark.parametrize(
        "dominio",
        [
            "aula.example.org",
            ".aula.example.org",
            "AULA.example.org",
            "example.org",
            ".example.org",
        ],
    )
    def test_el_servidor_o_un_padre(self, dominio):
        assert entrada.coincide_dominio("aula.example.org", dominio)

    @pytest.mark.parametrize(
        "dominio",
        ["", ".", "org", ".org", "xample.org", "malexample.org", "otra.example.org", "idp.org"],
    )
    def test_lo_demas_no(self, dominio):
        assert not entrada.coincide_dominio("aula.example.org", dominio)

    def test_una_ip_solo_coincide_consigo_misma(self):
        assert entrada.coincide_dominio("192.168.1.43", "192.168.1.43")
        assert not entrada.coincide_dominio("192.168.1.43", "1.43")
        assert not entrada.coincide_dominio("192.168.1.43", ".168.1.43")


class TestCookiesDelAula:
    def test_solo_lo_que_enviaria_el_navegador(self):
        galletas = [
            {"name": "MoodleSession", "value": "a", "domain": "aula.example.org"},
            {"name": "MOODLEID1_", "value": "b", "domain": ".aula.example.org"},
            {"name": "idp", "value": "c", "domain": "idp.example.org"},
            {"name": "padre", "value": "d", "domain": ".example.org"},
            {"name": "rota", "value": 3, "domain": "aula.example.org"},
            {"name": "ajena", "value": "e", "domain": "malexample.org"},
        ]
        assert entrada.cookies_del_aula(galletas, "aula.example.org") == [
            ("MoodleSession", "a", "aula.example.org"),
            ("MOODLEID1_", "b", "aula.example.org"),
            ("padre", "d", "example.org"),
        ]

    def test_una_cookie_repetida_se_queda_con_la_ultima(self):
        galletas = [
            {"name": "S", "value": "vieja", "domain": "aula.example.org"},
            {"name": "S", "value": "nueva", "domain": ".aula.example.org"},
        ]
        assert entrada.cookies_del_aula(galletas, "aula.example.org") == [
            ("S", "nueva", "aula.example.org")
        ]

    def test_limites(self):
        galletas = [
            {"name": f"c{i}", "value": "x", "domain": "aula.example.org"} for i in range(80)
        ]
        galletas.append({"name": "gorda", "value": "x" * 5000, "domain": "aula.example.org"})
        assert len(entrada.cookies_del_aula(galletas, "aula.example.org")) == entrada.MAX_COOKIES


GALLETA = ("MoodleSession", "a", "aula.example.org")


class TestTuberia:
    def test_ida_y_vuelta(self):
        assert entrada.decodificar(entrada.codificar([GALLETA])) == [GALLETA]
        assert entrada.decodificar(entrada.codificar([])) == []

    @pytest.mark.parametrize(
        "texto",
        [
            "",
            "no es json",
            "[]",
            '{"cookies": {}}',
            '{"cookies": [1]}',
            '{"cookies": [{"nombre": "a", "valor": "b"}]}',
            '{"cookies": [{"nombre": "a", "valor": "b", "dominio": "d", "extra": 1}]}',
            '{"cookies": [{"nombre": "a", "valor": 1, "dominio": "d"}]}',
            '{"cookies": [{"nombre": "", "valor": "b", "dominio": "d"}]}',
            '{"cookies": [{"nombre": "a", "valor": "b", "dominio": ""}]}',
            '{"cookies": [], "extra": 1}',
            json.dumps(
                {"cookies": [{"nombre": f"c{i}", "valor": "x", "dominio": "d"} for i in range(60)]}
            ),
            json.dumps({"cookies": [{"nombre": "a", "valor": "x" * 5000, "dominio": "d"}]}),
            "x" * (entrada.MAX_TUBERIA + 1),
            "[" * 100000,
        ],
    )
    def test_rechaza_lo_que_no_cumple(self, texto):
        assert entrada.decodificar(texto) is None


def proceso(codigo=0, salida=""):
    return lambda *a, **k: types.SimpleNamespace(returncode=codigo, stdout=salida, stderr="")


class TestEntrar:
    def test_devuelve_las_cookies(self):
        salida = entrada.codificar([GALLETA])
        assert ventana.entrar(AULA, ejecutar=proceso(0, salida)) == [GALLETA]

    def test_cerrada_sin_entrar_es_none(self):
        assert ventana.entrar(AULA, ejecutar=proceso(0, entrada.codificar([]))) is None

    def test_tiempo_agotado_es_none(self):
        def lenta(*a, **k):
            raise subprocess.TimeoutExpired("x", 1)

        assert ventana.entrar(AULA, ejecutar=lenta) is None

    def test_el_hijo_se_lanza_con_la_url_y_sin_pasar_secretos(self):
        vistas = []

        def ejecutar(orden, **opciones):
            vistas.append((orden, opciones))
            return types.SimpleNamespace(returncode=0, stdout=entrada.codificar([]), stderr="")

        ventana.entrar(AULA, ejecutar=ejecutar)
        orden, opciones = vistas[0]
        assert orden == [sys.executable, "-m", "tiza.ventana", AULA]
        assert "env" not in opciones and "input" not in opciones
        assert opciones["stdout"] == subprocess.PIPE
        # stdin y stderr se heredan: el hijo exige la terminal del docente (stdin y stderr).
        assert "stdin" not in opciones and "stderr" not in opciones

    @pytest.mark.parametrize("codigo,salida", [(3, ""), (2, ""), (0, "basura")])
    def test_fallos_son_error_de_ventana(self, codigo, salida):
        with pytest.raises(ventana.ErrorVentana):
            ventana.entrar(AULA, ejecutar=proceso(codigo, salida))

    def test_no_se_puede_lanzar(self):
        def falla(*a, **k):
            raise FileNotFoundError("python")

        with pytest.raises(ventana.ErrorVentana):
            ventana.entrar(AULA, ejecutar=falla)


class TestHijo:
    def test_exige_una_terminal_del_docente(self, monkeypatch):
        class Flujo:
            def __init__(self, tty):
                self._tty = tty

            def isatty(self):
                return self._tty

            def write(self, texto):
                return len(texto)

            def flush(self):
                pass

        monkeypatch.setattr(ventana, "ejecutar_hijo", lambda url: pytest.fail("no debe abrirse"))
        for stdin, stderr, stdout in [
            (False, True, False),  # un agente sin terminal
            (True, False, False),
            (True, True, True),  # a mano, con la salida en pantalla
        ]:
            monkeypatch.setattr(sys, "stdin", Flujo(stdin))
            monkeypatch.setattr(sys, "stderr", Flujo(stderr))
            monkeypatch.setattr(sys, "stdout", Flujo(stdout))
            assert ventana.principal([AULA]) == ventana.SALIDA_USO

    def test_con_lo_que_le_da_el_padre_abre_la_ventana(self, monkeypatch):
        """Contrato con ``entrar``: stdin y stderr son la terminal y stdout la tubería."""

        class Flujo:
            def __init__(self, tty):
                self._tty = tty

            def isatty(self):
                return self._tty

        abiertas = []
        monkeypatch.setattr(ventana, "ejecutar_hijo", lambda url: abiertas.append(url) or 0)
        monkeypatch.setattr(sys, "stdin", Flujo(True))
        monkeypatch.setattr(sys, "stderr", Flujo(True))
        monkeypatch.setattr(sys, "stdout", Flujo(False))
        assert ventana.principal([AULA]) == 0
        assert abiertas == [AULA]

    def test_pide_exactamente_una_url(self):
        assert ventana.principal([]) == ventana.SALIDA_USO
        assert ventana.principal(["a", "b"]) == ventana.SALIDA_USO

    def test_rechaza_urls_no_permitidas(self):
        assert ventana.ejecutar_hijo("http://aula.example.org/centro") == ventana.SALIDA_USO
        assert ventana.ejecutar_hijo("https://user:pw@aula.example.org/") == ventana.SALIDA_USO

    def test_importar_el_paquete_no_carga_pywebview(self):
        assert "webview" not in sys.modules


class TestDisponible:
    def test_nunca_en_linux(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert disponible_de_verdad() is False

    def test_hace_falta_el_extra(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(ventana.importlib.util, "find_spec", lambda nombre: None)
        assert disponible_de_verdad() is False
        monkeypatch.setattr(ventana.importlib.util, "find_spec", lambda nombre: object())
        assert disponible_de_verdad() is True

    def test_en_windows_hace_falta_webview2(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(ventana.importlib.util, "find_spec", lambda nombre: object())
        monkeypatch.setattr(ventana.webview2, "instalado", lambda: False)
        assert disponible_de_verdad() is False
        monkeypatch.setattr(ventana.webview2, "instalado", lambda: True)
        assert disponible_de_verdad() is True


class TestAcreditarEnLaTerminal:
    @pytest.fixture
    def con_ventana(self, monkeypatch):
        monkeypatch.setattr(ventana, "disponible", lambda: True)
        monkeypatch.setattr(
            terminal, "pedir_password", lambda: pytest.fail("no se debe pedir la contraseña")
        )

    def test_con_ventana_recoge_las_cookies(self, con_ventana, monkeypatch, capsys):
        monkeypatch.setattr(ventana, "entrar", lambda url: [GALLETA])
        assert terminal.acreditar(AULA, "profe") == publicar.Cookies([GALLETA])
        assert "tiza no verá tu contraseña" in capsys.readouterr().out

    def test_cerrar_la_ventana_cancela_sin_pedir_la_contrasena(self, con_ventana, monkeypatch):
        monkeypatch.setattr(ventana, "entrar", lambda url: None)
        assert terminal.acreditar(AULA, "profe") is None

    def test_si_no_se_puede_abrir_cae_a_la_contrasena(self, monkeypatch, capsys):
        monkeypatch.setattr(ventana, "disponible", lambda: True)

        def falla(url):
            raise ventana.ErrorVentana("x")

        monkeypatch.setattr(ventana, "entrar", falla)
        monkeypatch.setattr(terminal, "pedir_password", lambda: "secreta")
        assert terminal.acreditar(AULA, "profe") == publicar.Contrasena("secreta")
        salida = capsys.readouterr().out
        assert "No se pudo abrir la ventana" in salida
        assert "contraseña del aula de aula.example.org (usuario: profe)" in salida

    def test_sin_ventana_pide_la_contrasena(self, con_ventana, monkeypatch):
        monkeypatch.setattr(ventana, "entrar", lambda url: pytest.fail("sin ventana"))
        monkeypatch.setattr(terminal, "pedir_password", lambda: "secreta")
        assert terminal.acreditar(AULA, "profe", usar_ventana=False) == publicar.Contrasena(
            "secreta"
        )

    def test_la_presencia_respeta_usar_ventana(self, monkeypatch):
        vistas = []
        monkeypatch.setattr(
            terminal,
            "acreditar",
            lambda url, usuario, *, usar_ventana: vistas.append(usar_ventana) or None,
        )
        terminal.PresenciaTerminal(usar_ventana=False).acreditar(AULA, "profe")
        terminal.PresenciaTerminal().acreditar(AULA, "profe")
        assert vistas == [False, True]


def test_sin_ventana_es_una_opcion_de_empezar_y_sesion():
    parser = cli._parser()
    assert parser.parse_args(["empezar", "--sin-ventana"]).sin_ventana is True
    assert parser.parse_args(["sesion"]).sin_ventana is False
