"""Tests de la capa de ventana (``tiza.panel``) sin pywebview: lo puro y el hilo de ventana."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace

import pytest

import tiza
import tiza.panel as panel_pkg
from tiza import publicar
from tiza.panel.estado import RETARDO_RESPUESTA, Panel, PresenciaPanel, Puente
from tiza.ventana import webview2

AULA = "https://aula.ejemplo.org/centro"


def _galletas(**dominios: str) -> list[SimpleCookie]:
    jar = SimpleCookie()
    for nombre, dominio in dominios.items():
        jar[nombre] = f"valor-de-{nombre}"
        jar[nombre]["domain"] = dominio
    return [jar]


# --- funciones puras ----------------------------------------------------------------------


def test_que_falta_fuera_de_windows():
    texto = panel_pkg.que_falta("linux", hay_webview=True, hay_webview2=lambda: pytest.fail("no"))
    assert texto is not None and "solo está disponible en Windows" in texto
    assert "tiza empezar" in texto


def test_que_falta_sin_pywebview():
    texto = panel_pkg.que_falta("win32", hay_webview=False, hay_webview2=lambda: pytest.fail("no"))
    assert texto is not None and "pywebview" in texto


def test_que_falta_sin_webview2():
    texto = panel_pkg.que_falta("win32", hay_webview=True, hay_webview2=lambda: False)
    assert texto is not None and webview2.DESCARGA in texto
    assert "terminal" not in texto  # el panel no tiene terminal a la que caer


def test_que_falta_no_falta_nada():
    assert panel_pkg.que_falta("win32", hay_webview=True, hay_webview2=lambda: True) is None


def test_redirigir_salidas_con_pythonw(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    panel_pkg.redirigir_salidas()
    try:
        print("no falla")
        print("tampoco", file=sys.stderr)
    finally:
        for flujo in (sys.stdout, sys.stderr):
            flujo.close()


def test_redirigir_salidas_no_toca_lo_que_ya_hay(monkeypatch, capsys):
    antes = (sys.stdout, sys.stderr)
    panel_pkg.redirigir_salidas()
    assert (sys.stdout, sys.stderr) == antes


@pytest.mark.parametrize(
    ("resultado", "esperado"),
    [
        (("/a/b", "/c"), "/a/b"),
        (["/a/b"], "/a/b"),
        ("/a/b", "/a/b"),
        (None, None),
        ((), None),
        ("", None),
        (("",), None),
        ([5], None),
        (5, None),
        ({"a": 1}, None),
    ],
)
def test_ruta_del_dialogo(resultado, esperado):
    assert panel_pkg.ruta_del_dialogo(resultado) == esperado


def test_modo_carpeta_usa_filedialog_y_si_no_la_constante_antigua():
    nuevo = SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=20), FOLDER_DIALOG=20)
    assert panel_pkg.modo_carpeta(nuevo) == 20
    viejo = SimpleNamespace(FOLDER_DIALOG=20)
    assert panel_pkg.modo_carpeta(viejo) == 20
    assert panel_pkg.modo_carpeta(SimpleNamespace(FileDialog=object(), FOLDER_DIALOG=7)) == 7


def test_galletas_de_solo_las_del_aula():
    jars = _galletas(MoodleSession="aula.ejemplo.org", otra=".aula.ejemplo.org", ajena="evil.org")
    assert panel_pkg.galletas_de(jars, "aula.ejemplo.org") == [
        ("MoodleSession", "valor-de-MoodleSession", "aula.ejemplo.org"),
        ("otra", "valor-de-otra", "aula.ejemplo.org"),
    ]


def test_galletas_sin_dominio_se_asignan_al_servidor():
    assert panel_pkg.galletas_de(_galletas(MoodleSession=""), "aula.ejemplo.org") == [
        ("MoodleSession", "valor-de-MoodleSession", "aula.ejemplo.org")
    ]


def test_acreditacion_de_es_cookies_o_none():
    jars = _galletas(MoodleSession="aula.ejemplo.org")
    acreditacion = panel_pkg.acreditacion_de(jars, "aula.ejemplo.org")
    assert isinstance(acreditacion, publicar.Cookies)
    assert acreditacion.valores == (
        ("MoodleSession", "valor-de-MoodleSession", "aula.ejemplo.org"),
    )
    assert "valor-de" not in repr(acreditacion)
    assert panel_pkg.acreditacion_de(_galletas(x="evil.org"), "aula.ejemplo.org") is None
    assert panel_pkg.acreditacion_de([], "aula.ejemplo.org") is None


@pytest.mark.parametrize(
    ("url", "dentro"),
    [
        (f"{AULA}/my/", True),
        (f"{AULA}/my/courses.php", True),
        (f"{AULA}/login/index.php", False),
        (f"{AULA}/", False),
        ("https://otro.org/centro/my/", False),
        ("http://aula.ejemplo.org/centro/my/", False),
        (None, False),
        ("", False),
    ],
)
def test_ya_dentro(url, dentro):
    assert panel_pkg.ya_dentro(url, AULA) is dentro


def test_titulo_de_login_enseña_el_servidor_visto():
    assert panel_pkg.titulo_de_login("https://sso.otro.org/x?y=1", "aula.ejemplo.org") == (
        "Entrar en sso.otro.org"
    )
    assert panel_pkg.titulo_de_login(None, "aula.ejemplo.org") == "Entrar en aula.ejemplo.org"


def test_las_funciones_de_windows_no_hacen_nada_en_otro_sistema(capsys):
    if sys.platform == "win32":
        pytest.skip("comprueba el comportamiento fuera de Windows")
    assert panel_pkg.parpadear_en_la_barra("tiza") is False
    assert panel_pkg.esta_minimizada("tiza") is True
    panel_pkg.avisar("hola docente")
    assert "hola docente" in capsys.readouterr().err


def test_main_sin_lo_necesario_avisa_y_sale(monkeypatch):
    avisos: list[str] = []
    monkeypatch.setattr(panel_pkg, "avisar", avisos.append)
    monkeypatch.setattr(panel_pkg.importlib.util, "find_spec", lambda nombre: None)
    assert panel_pkg.main() == 1
    assert len(avisos) == 1 and avisos[0]


# --- pywebview no se importa ------------------------------------------------------------------


def test_importar_el_panel_no_importa_webview():
    codigo = (
        "import sys, tiza.panel, tiza.panel.estado, tiza.panel.flujo, tiza.panel.recientes\n"
        "assert 'webview' not in sys.modules, 'se importó webview'\n"
    )
    resultado = subprocess.run(
        [sys.executable, "-I", "-c", codigo], capture_output=True, text=True, timeout=60
    )
    assert resultado.returncode == 0, resultado.stderr


def test_solo_el_init_importa_webview_y_solo_dentro_de_una_funcion():
    carpeta = Path(tiza.__file__).parent / "panel"
    for fuente in sorted(carpeta.glob("*.py")):
        lineas = [
            linea
            for linea in fuente.read_text(encoding="utf-8").splitlines()
            if linea.strip().startswith(("import webview", "from webview"))
        ]
        if fuente.name == "__init__.py":
            assert lineas and all(linea.startswith(" ") for linea in lineas)
        else:
            assert not lineas, fuente.name


# --- ventana de entrada al aula -------------------------------------------------------------


class Evento:
    def __init__(self) -> None:
        self.funciones: list = []

    def __iadd__(self, funcion):
        self.funciones.append(funcion)
        return self

    def lanzar(self) -> None:
        for funcion in list(self.funciones):
            funcion()


class WebFalsa:
    def __init__(self, jars=()) -> None:
        self.events = SimpleNamespace(loaded=Evento(), closed=Evento())
        self.url: str | None = None
        self.titulo: str | None = None
        self.jars = list(jars)
        self.destruida = 0

    def get_current_url(self):
        return self.url

    def set_title(self, titulo: str) -> None:
        self.titulo = titulo

    def get_cookies(self):
        return self.jars

    def destroy(self) -> None:
        self.destruida += 1
        self.events.closed.lanzar()

    def navegar(self, url: str) -> None:
        self.url = url
        self.events.loaded.lanzar()


class WebviewFalso:
    def __init__(self, jars=()) -> None:
        self.web = WebFalsa(jars)
        self.ventanas: list[tuple] = []

    def create_window(self, *args, **kwargs):
        self.ventanas.append((args, kwargs))
        return self.web


def _login(webview, panel=None, **opciones):
    """Lanza abrir_login en un hilo (como la sesión); devuelve cómo leer lo que devuelve."""
    resultado: dict = {}

    def correr() -> None:
        resultado["valor"] = panel_pkg.abrir_login(
            AULA, webview=webview, panel=panel or Panel(), sondeo=0.01, **opciones
        )

    hilo = threading.Thread(target=correr, daemon=True)
    hilo.start()
    limite = time.monotonic() + 5
    while not webview.ventanas and time.monotonic() < limite:
        time.sleep(0.005)
    assert webview.ventanas, "no se creó la ventana"

    def leer():
        hilo.join(5)
        assert not hilo.is_alive(), "abrir_login sigue esperando"
        return resultado["valor"]

    return leer


def test_el_login_se_crea_sin_js_api_en_la_pagina_del_panel_del_aula():
    webview = WebviewFalso()
    leer = _login(webview)
    (args, kwargs) = webview.ventanas[0]
    assert args == ("Entrar en aula.ejemplo.org", f"{AULA}/my/")
    assert kwargs == {"width": 900, "height": 720}
    assert "js_api" not in kwargs
    webview.web.destroy()
    assert leer() is None


def test_el_login_devuelve_las_cookies_al_llegar_al_panel_y_cierra_la_ventana():
    webview = WebviewFalso(_galletas(MoodleSession="aula.ejemplo.org", ajena="evil.org"))
    leer = _login(webview)
    web = webview.web
    web.navegar(f"{AULA}/login/index.php")
    assert web.titulo == "Entrar en aula.ejemplo.org" and web.destruida == 0
    web.navegar("https://sso.otro.org/entrar")
    assert web.titulo == "Entrar en sso.otro.org" and web.destruida == 0
    web.navegar(f"{AULA}/my/")
    acreditacion = leer()
    assert isinstance(acreditacion, publicar.Cookies)
    assert acreditacion.valores == (
        ("MoodleSession", "valor-de-MoodleSession", "aula.ejemplo.org"),
    )
    assert web.destruida == 1


def test_el_login_no_toma_dos_veces_las_cookies():
    webview = WebviewFalso(_galletas(MoodleSession="aula.ejemplo.org"))
    leer = _login(webview)
    webview.web.navegar(f"{AULA}/my/")
    leer()
    webview.web.navegar(f"{AULA}/my/")  # otro «loaded» tras destruirla
    assert webview.web.destruida == 1


def test_en_el_panel_sin_cookies_del_aula_no_hay_acreditacion():
    webview = WebviewFalso(_galletas(ajena="evil.org"))
    leer = _login(webview)
    webview.web.navegar(f"{AULA}/my/")
    assert leer() is None


def test_cerrar_la_ventana_sin_entrar_es_none():
    webview = WebviewFalso(_galletas(MoodleSession="aula.ejemplo.org"))
    leer = _login(webview)
    webview.web.navegar(f"{AULA}/login/index.php")
    webview.web.destroy()  # el docente cierra con la X
    assert leer() is None


def test_si_se_cierra_el_panel_se_cierra_el_login():
    panel = Panel()
    webview = WebviewFalso()
    leer = _login(webview, panel)
    panel.cerrar()
    assert leer() is None
    assert webview.web.destruida == 1


def test_el_login_tiene_un_tiempo_maximo():
    webview = WebviewFalso()
    leer = _login(webview, tiempo_maximo=0.05)
    assert leer() is None
    assert webview.web.destruida == 1


def test_una_url_que_no_vale_no_abre_ventana():
    webview = WebviewFalso()
    assert (
        panel_pkg.abrir_login("http://aula.ejemplo.org/x", webview=webview, panel=Panel()) is None
    )
    assert webview.ventanas == []


def test_un_fallo_de_la_ventana_no_cuelga_la_sesion():
    class Rota(WebFalsa):
        def get_current_url(self):
            raise RuntimeError("motor caído")

    webview = WebviewFalso()
    webview.web = Rota()
    leer = _login(webview)
    webview.web.navegar(f"{AULA}/my/")
    assert leer() is None
    assert webview.web.destruida == 1


def test_el_login_de_la_presencia_nunca_pasa_por_el_puente():
    cookies = publicar.Cookies((("MoodleSession", "secreto", "aula.ejemplo.org"),))
    panel = Panel()
    presencia = PresenciaPanel(panel, abrir_login=lambda url: cookies)
    assert presencia.acreditar(AULA, "ana") is cookies
    assert "secreto" not in str(Puente(panel).estado())


# --- hilo de la ventana -------------------------------------------------------------------


class Reloj:
    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora


class VentanaFalsa:
    def __init__(self) -> None:
        self.cambios: list[tuple] = []
        self._on_top = False
        self.falla_on_top = False

    @property
    def on_top(self) -> bool:
        return self._on_top

    @on_top.setter
    def on_top(self, valor: bool) -> None:
        if self.falla_on_top:
            raise RuntimeError("sin ventana")
        self._on_top = valor
        self.cambios.append(("on_top", valor))

    def restore(self) -> None:
        self.cambios.append(("restore",))

    def show(self) -> None:
        self.cambios.append(("show",))

    def destroy(self) -> None:
        self.cambios.append(("destroy",))


class Vigilancia:
    """Un Panel de reloj falso, una ventana falsa y el hilo de ventana corriendo de verdad."""

    def __init__(self, *, minimizada: bool = True, elegir=lambda: None, parpadear=None) -> None:
        self.reloj = Reloj()
        self.panel = Panel(reloj=self.reloj)
        self.presencia = PresenciaPanel(self.panel, reloj=self.reloj)
        self.ventana = VentanaFalsa()
        self.cerrar = threading.Event()
        self.parpadeos = 0
        self.hilos: list[threading.Thread] = []

        def parpadeo() -> bool:
            self.parpadeos += 1
            return True

        self.vigilante = threading.Thread(
            target=panel_pkg.vigilar,
            args=(self.panel, self.ventana),
            kwargs={
                "cerrar": self.cerrar,
                "parpadear": parpadear or parpadeo,
                "elegir_carpeta": elegir,
                "poner_encima": lambda valor: setattr(self.ventana, "on_top", valor),
                "restaurar": self.ventana.restore,
                "mostrar": self.ventana.show,
                "minimizada": lambda: minimizada,
                "espera": 0.01,
            },
            daemon=True,
        )
        self.vigilante.start()

    def preguntar(self, funcion, *args):
        resultado: dict = {}

        def correr() -> None:
            resultado["valor"] = funcion(*args)

        hilo = threading.Thread(target=correr, daemon=True)
        hilo.start()
        self.hilos.append(hilo)
        return hilo, resultado

    def pantalla(self, tipo: str | None = None) -> dict:
        limite = time.monotonic() + 5
        while time.monotonic() < limite:
            actual = self.panel.estado()["pantalla"]
            if actual["tipo"] != "reposo" and tipo in (None, actual["tipo"]):
                self.reloj.ahora += RETARDO_RESPUESTA + 0.1
                return actual
            time.sleep(0.005)
        raise AssertionError("no llegó la pantalla")

    def esperar(self, condicion) -> None:
        limite = time.monotonic() + 5
        while not condicion() and time.monotonic() < limite:
            time.sleep(0.005)
        assert condicion()

    def terminar(self) -> None:
        self.panel.cerrar()
        self.vigilante.join(5)
        assert not self.vigilante.is_alive()
        for hilo in self.hilos:
            hilo.join(5)


@pytest.fixture
def vigilancia():
    creadas: list[Vigilancia] = []

    def crear(**opciones) -> Vigilancia:
        v = Vigilancia(**opciones)
        creadas.append(v)
        return v

    yield crear
    for v in creadas:
        v.terminar()


def test_con_una_pregunta_la_ventana_se_pone_delante_y_parpadea(vigilancia):
    v = vigilancia()
    hilo, resultado = v.preguntar(v.presencia.confirmar_autoprueba)
    p = v.pantalla()
    v.esperar(lambda: v.parpadeos == 1)
    assert v.ventana.cambios[:3] == [("on_top", True), ("restore",), ("show",)]
    assert v.panel.responder(p["numero"], True)
    hilo.join(5)
    assert resultado["valor"] is True
    v.esperar(lambda: v.ventana.on_top is False)
    assert v.parpadeos == 1


def test_sin_minimizar_no_se_restaura(vigilancia):
    v = vigilancia(minimizada=False)
    v.preguntar(v.presencia.confirmar_autoprueba)
    v.pantalla()
    v.esperar(lambda: ("show",) in v.ventana.cambios)
    assert ("restore",) not in v.ventana.cambios


def test_cada_pregunta_nueva_parpadea_una_vez(vigilancia):
    v = vigilancia()
    for esperado in (1, 2):
        hilo, resultado = v.preguntar(v.presencia.confirmar_autoprueba)
        p = v.pantalla()
        v.esperar(lambda esperado=esperado: v.parpadeos == esperado)
        time.sleep(0.05)  # varias vueltas del hilo: no repite el parpadeo
        assert v.parpadeos == esperado
        v.panel.responder(p["numero"], True)
        hilo.join(5)


def test_los_fallos_de_la_ventana_no_matan_el_hilo(vigilancia):
    def falla():
        raise RuntimeError("sin barra de tareas")

    v = vigilancia(parpadear=falla)
    v.ventana.falla_on_top = True
    hilo, resultado = v.preguntar(v.presencia.confirmar_autoprueba)
    p = v.pantalla()
    v.esperar(lambda: ("show",) in v.ventana.cambios)
    assert v.vigilante.is_alive()
    assert v.panel.responder(p["numero"], False)
    hilo.join(5)


def test_el_dialogo_de_carpeta_lo_abre_el_hilo_de_ventana_y_el_panel_valida(vigilancia, tmp_path):
    elegida = tmp_path / "asignatura"
    elegida.mkdir()
    hilos_del_dialogo: list[str] = []

    def elegir():
        hilos_del_dialogo.append(threading.current_thread().name)
        return str(elegida)

    v = vigilancia(elegir=elegir)
    hilo, resultado = v.preguntar(v.panel.esperar_carpeta)
    p = v.pantalla("carpeta")
    v.esperar(lambda: v.ventana.on_top is True)
    assert Puente(v.panel).buscar_carpeta(p["numero"]) is True
    hilo.join(5)
    assert resultado["valor"] == elegida
    assert hilos_del_dialogo and hilos_del_dialogo[0] != threading.current_thread().name
    # Mientras el diálogo está abierto la ventana deja de estar encima.
    assert ("on_top", False) in v.ventana.cambios


def test_un_dialogo_cancelado_deja_la_pregunta_y_vuelve_a_poner_la_ventana_delante(vigilancia):
    v = vigilancia(elegir=lambda: None)
    hilo, resultado = v.preguntar(v.panel.esperar_carpeta)
    p = v.pantalla("carpeta")
    v.esperar(lambda: v.ventana.on_top is True)
    Puente(v.panel).buscar_carpeta(p["numero"])
    v.esperar(lambda: v.ventana.cambios.count(("on_top", True)) == 2)
    assert v.panel.pregunta_pendiente
    assert v.parpadeos == 1  # no vuelve a parpadear por la misma pregunta
    v.panel.cerrar()
    hilo.join(5)
    assert resultado["valor"] is None


def test_terminar_avisa_a_la_sesion_y_destruye_la_ventana_desde_el_hilo(vigilancia):
    v = vigilancia()
    hilo, resultado = v.preguntar(v.presencia.confirmar_autoprueba)
    p = v.pantalla()
    assert Puente(v.panel).terminar(p["numero"]) is True
    v.vigilante.join(5)
    assert not v.vigilante.is_alive()
    assert v.cerrar.is_set()
    assert ("destroy",) in v.ventana.cambios
    hilo.join(5)
    assert resultado["valor"] is False


def test_si_el_docente_cierra_la_ventana_el_hilo_termina_sin_destruirla(vigilancia):
    v = vigilancia()
    v.panel.cerrar()  # lo que hace events.closed
    v.vigilante.join(5)
    assert not v.vigilante.is_alive()
    assert ("destroy",) not in v.ventana.cambios


def test_vigilar_no_toca_on_top_restore_ni_show_de_pywebview():
    # Cambiar ``on_top`` de pywebview desde este hilo bloquea la ventana para siempre si el
    # hilo de la interfaz está devolviendo a la vez una llamada del puente (Windows 11): todo
    # eso va por las funciones inyectadas, nunca por la ventana.
    class VentanaQueNoSeToca:
        def __getattr__(self, nombre):
            if nombre == "destroy":
                return lambda: None
            raise AssertionError(f"vigilar tocó ventana.{nombre}")

        def __setattr__(self, nombre, valor):
            raise AssertionError(f"vigilar cambió ventana.{nombre}")

    reloj = Reloj()
    panel = Panel(reloj=reloj)
    presencia = PresenciaPanel(panel, reloj=reloj)
    vistos: list = []
    cerrar = threading.Event()
    hilo = threading.Thread(
        target=panel_pkg.vigilar,
        args=(panel, VentanaQueNoSeToca()),
        kwargs={
            "cerrar": cerrar,
            "parpadear": lambda: vistos.append("parpadeo"),
            "elegir_carpeta": lambda: None,
            "poner_encima": lambda valor: vistos.append(("encima", valor)),
            "restaurar": lambda: vistos.append("restaurar"),
            "mostrar": lambda: vistos.append("mostrar"),
            "minimizada": lambda: True,
            "espera": 0.01,
        },
        daemon=True,
    )
    hilo.start()
    pregunta = threading.Thread(target=presencia.confirmar_autoprueba, daemon=True)
    pregunta.start()
    limite = time.monotonic() + 5
    while "mostrar" not in vistos and time.monotonic() < limite:
        time.sleep(0.01)
    assert vistos[:3] == [("encima", True), "restaurar", "mostrar"]
    panel.cerrar()
    hilo.join(5)
    pregunta.join(5)
    assert not hilo.is_alive()


def test_operaciones_win32_no_hacen_nada_fuera_de_windows(monkeypatch):
    monkeypatch.setattr(panel_pkg.sys, "platform", "linux")
    assert panel_pkg.poner_encima("tiza", True) is False
    assert panel_pkg.mostrar_ventana("tiza") is False
    assert panel_pkg.mostrar_ventana("tiza", restaurar=True) is False
