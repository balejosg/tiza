"""Tests de la ventana de entrada sin pywebview: decisiones, tubería y caída a la terminal."""

from __future__ import annotations

import http.cookies
import io
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
            # Con id explícito: pytest mete el id en una variable de entorno y Windows no admite
            # más de 32767 caracteres en ellas.
            pytest.param("x" * (entrada.MAX_TUBERIA + 1), id="mas-de-lo-permitido"),
            pytest.param("[" * 100000, id="anidado-sin-fin"),
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
        monkeypatch.setattr(ventana, "_canal_propio", lambda: None)  # no tocar los descriptores
        monkeypatch.setattr(ventana, "ejecutar_hijo", lambda url, **_: abiertas.append(url) or 0)
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


class _Evento:
    def __init__(self):
        self.funciones = []

    def __iadd__(self, funcion):
        self.funciones.append(funcion)
        return self


class _Eventos:
    def __init__(self):
        self.loaded = _Evento()


class _VentanaFalsa:
    """Doble de la ventana de pywebview: recorre las URLs que se le dan, una carga por URL."""

    def __init__(self, urls, galletas):
        self.events = _Eventos()
        self.titulos = []
        self.destruida = False
        self.cookies_borradas = False
        self._urls = list(urls)
        self._galletas = galletas
        self._actual = None

    def recorrer(self):
        for url in self._urls:
            if self.destruida:
                break
            self._actual = url
            for funcion in self.events.loaded.funciones:
                funcion()

    def get_current_url(self):
        return self._actual

    def set_title(self, titulo):
        self.titulos.append(titulo)

    def get_cookies(self):
        return self._galletas

    def clear_cookies(self):
        self.cookies_borradas = True

    def destroy(self):
        self.destruida = True


class _WebviewFalso:
    renderer = "edgechromium"

    def __init__(self, ventana):
        self.ventana = ventana
        self.creada = None
        self.arrancado = None

    def create_window(self, titulo, url, **opciones):
        self.creada = (titulo, url, opciones)
        return self.ventana

    def start(self, **opciones):
        self.arrancado = opciones
        self.ventana.recorrer()


def _jar(**valores):
    jar = http.cookies.SimpleCookie()
    for nombre, (valor, dominio) in valores.items():
        jar[nombre] = valor
        jar[nombre]["domain"] = dominio
    return jar


class TestEjecutarHijo:
    def _ejecutar(self, urls, galletas):
        ventana_falsa = _VentanaFalsa(urls, galletas)
        webview = _WebviewFalso(ventana_falsa)
        canal = io.StringIO()
        codigo = ventana.ejecutar_hijo(AULA, webview=webview, canal=canal)
        return codigo, webview, ventana_falsa, canal.getvalue()

    def test_recoge_las_cookies_del_aula_al_llegar_al_panel(self):
        galletas = [
            _jar(MoodleSession=("abc", "aula.example.org")),
            _jar(idp=("secreto", "idp.example.org")),
        ]
        codigo, webview, falsa, salida = self._ejecutar(
            [
                f"{AULA}/login/index.php",
                "https://idp.example.org/acceso",
                f"{AULA}/login/index.php",
                f"{AULA}/my/courses.php",
            ],
            galletas,
        )
        assert codigo == 0
        assert entrada.decodificar(salida) == [("MoodleSession", "abc", "aula.example.org")]
        assert salida.endswith("\n") and salida.count("\n") == 1
        assert falsa.destruida and falsa.cookies_borradas
        assert "secreto" not in salida

    def test_ventana_privada_sin_js_api_y_en_el_panel(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        _, webview, _, _ = self._ejecutar([f"{AULA}/my/"], [])
        titulo, url, opciones = webview.creada
        assert url == f"{AULA}/my/" and "aula.example.org" in titulo
        assert "js_api" not in opciones
        assert webview.arrancado == {"private_mode": True}

    def test_el_titulo_enseña_el_servidor_que_se_esta_viendo(self):
        _, _, falsa, _ = self._ejecutar(
            [f"{AULA}/login/index.php", "https://idp.example.org/acceso", f"{AULA}/my/"], []
        )
        assert falsa.titulos == [
            "Entrar en aula.example.org",
            "Entrar en idp.example.org",
            "Entrar en aula.example.org",
        ]

    def test_en_linux_sin_gtk_va_directo_a_qt(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            ventana.importlib.util, "find_spec", lambda nombre: None if nombre == "gi" else object()
        )
        _, webview, _, _ = self._ejecutar([f"{AULA}/my/"], [])
        assert webview.arrancado == {"private_mode": True, "gui": "qt"}

    def test_en_linux_con_gtk_deja_elegir_a_pywebview(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(ventana.importlib.util, "find_spec", lambda nombre: object())
        _, webview, _, _ = self._ejecutar([f"{AULA}/my/"], [])
        assert webview.arrancado == {"private_mode": True}

    def test_si_el_motor_falla_la_terminal_pide_la_contrasena(self, capsys):
        class SinMotor(_WebviewFalso):
            def start(self, **opciones):
                raise RuntimeError("GTK cannot be loaded")

        webview = SinMotor(_VentanaFalsa([], []))
        canal = io.StringIO()
        assert ventana.ejecutar_hijo(AULA, webview=webview, canal=canal) == ventana.SALIDA_SIN_MOTOR
        assert canal.getvalue() == ""
        assert "No se pudo abrir la ventana (RuntimeError)" in capsys.readouterr().err

    def test_cerrada_sin_entrar_no_devuelve_cookies(self):
        codigo, _, falsa, salida = self._ejecutar([f"{AULA}/login/index.php"], [])
        assert codigo == 0 and entrada.decodificar(salida) == []
        assert not falsa.destruida

    def test_sin_webview2_en_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(ventana.webview2, "instalado", lambda: False)
        assert ventana.ejecutar_hijo(AULA, webview=object()) == ventana.SALIDA_SIN_MOTOR

    def test_en_windows_exige_edge(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(ventana.webview2, "instalado", lambda: True)
        falso = _WebviewFalso(_VentanaFalsa([f"{AULA}/login/index.php"], []))
        falso.renderer = "mshtml"
        assert ventana.ejecutar_hijo(AULA, webview=falso, canal=io.StringIO()) == (
            ventana.SALIDA_SIN_MOTOR
        )


class TestCanalPropio:
    def test_lo_que_escriba_el_motor_no_se_mezcla_con_el_resultado(self):
        """Prueba real en un proceso aparte: el descriptor 1 apunta a la terminal (el 2)."""
        codigo = (
            "import sys; from tiza import ventana; "
            "canal = ventana._canal_propio(); "
            "print('ruido del motor'); sys.stdout.flush(); "
            "canal.write('RESULTADO'); canal.flush()"
        )
        proceso = subprocess.run(
            [sys.executable, "-c", codigo], capture_output=True, text=True, timeout=60
        )
        assert proceso.stdout == "RESULTADO"
        assert "ruido del motor" in proceso.stderr


class TestDisponible:
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

    def test_otros_sistemas_no(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "freebsd14")
        monkeypatch.setattr(ventana.importlib.util, "find_spec", lambda nombre: object())
        assert disponible_de_verdad() is False


class TestDisponibleEnLinux:
    @pytest.fixture
    def linux(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        def instalados(*nombres):
            monkeypatch.setattr(
                ventana.importlib.util,
                "find_spec",
                lambda nombre: object() if nombre in nombres else None,
            )

        return instalados

    def test_con_escritorio_y_qt(self, linux, monkeypatch):
        linux("webview", "qtpy")
        monkeypatch.setenv("DISPLAY", ":0")
        assert disponible_de_verdad() is True

    def test_con_wayland_y_gtk(self, linux, monkeypatch):
        linux("webview", "gi")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert disponible_de_verdad() is True

    def test_sin_escritorio_no_hay_ventana(self, linux):
        linux("webview", "qtpy", "gi")  # p. ej. una sesión por SSH
        assert disponible_de_verdad() is False
        assert ventana.hay_pantalla() is False

    def test_sin_motor_no_hay_ventana(self, linux, monkeypatch):
        linux("webview")
        monkeypatch.setenv("DISPLAY", ":0")
        assert disponible_de_verdad() is False

    def test_sin_el_extra_no_hay_ventana(self, linux, monkeypatch):
        linux("qtpy")
        monkeypatch.setenv("DISPLAY", ":0")
        assert disponible_de_verdad() is False


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
