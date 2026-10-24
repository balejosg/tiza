"""El panel de escritorio sin consola (Windows): sustituye a la terminal de ``tiza empezar``
y ``tiza sesion``. Es del docente, como ellos: ningún agente lo abre.

Piezas:

- ``estado``: el modelo (pantalla, registro, ``PresenciaPanel``, ``Puente``), sin ventana.
- ``recientes`` y ``flujo``: las carpetas recientes y el recorrido de la carpeta al cierre.
- ``sesion.html``: la página (dato del paquete), que se carga con ``html=``.
- Este módulo: la capa de ventana. Es el único del subpaquete que importa ``webview`` y solo
  dentro de ``main`` (``import tiza.panel`` no lo carga, y el CI no lo tiene instalado). Lo
  demás son funciones puras o que reciben el módulo ``webview`` como argumento.

Reglas de ventana (se comprobaron en Windows 11 con pywebview 6.2.1):

- ``destroy`` y el diálogo de carpeta se hacen siempre desde un hilo propio (``vigilar``),
  nunca dentro de un método del ``js_api``: cuelgan la ventana.
- «Siempre encima», restaurar y mostrar no usan pywebview (``on_top`` cambia ``TopMost`` sin
  ``Invoke`` y se bloquea con el sondeo del puente), sino ``SetWindowPos``/``ShowWindowAsync``
  asíncronos de Win32.
- La ventana de entrada al aula se crea en este mismo proceso, sin ``js_api``; las cookies no
  salen del proceso (nunca por disco, tubería, argumentos ni entorno).
"""

from __future__ import annotations

import importlib.resources
import importlib.util
import os
import platform
import secrets
import sys
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .. import config, publicar
from ..ventana import TIEMPO_MAXIMO, entrada, webview2
from . import flujo
from .estado import Panel, PresenciaPanel, Puente

__all__ = [
    "TITULO",
    "abrir_login",
    "acreditacion_de",
    "galletas_de",
    "main",
    "nuevo_nonce",
    "pagina",
    "que_falta",
    "redirigir_salidas",
    "ruta_del_dialogo",
    "titulo_de_login",
    "vigilar",
    "ya_dentro",
]

TITULO = "tiza"
ANCHO, ALTO, MINIMO = 820, 760, (560, 520)
ESPERA_VIGILANTE = 0.5
ESPERA_CIERRE = 15.0  # lo que se espera a que la sesión se recoja tras cerrar la ventana


# --- funciones puras --------------------------------------------------------------------


def nuevo_nonce() -> str:
    """Un nonce aleatorio por arranque para la CSP de la página."""
    return secrets.token_urlsafe(16)


def pagina(nonce: str) -> str:
    """El HTML del panel con el nonce de este arranque en su CSP, su estilo y su script."""
    texto = importlib.resources.files(__name__).joinpath("sesion.html").read_text(encoding="utf-8")
    return texto.replace("__NONCE__", nonce)


def redirigir_salidas() -> None:
    """Con ``pythonw`` (sin consola) ``sys.stdout`` y ``sys.stderr`` son None: a ``devnull``."""
    for nombre in ("stdout", "stderr"):
        if getattr(sys, nombre) is None:
            setattr(sys, nombre, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115


def que_falta(
    plataforma: str, *, hay_webview: bool, hay_webview2: Callable[[], bool]
) -> str | None:
    """Por qué no se puede abrir el panel aquí (texto para el docente), o None si se puede."""
    if plataforma != "win32":
        return (
            "El panel de tiza solo está disponible en Windows. "
            "En este sistema, abre la sesión con «tiza empezar» en la terminal."
        )
    if not hay_webview:
        return (
            "Falta pywebview, el componente de ventana de tiza. "
            "Vuelve a instalar tiza con el extra «ventana» (mira INSTALAR_CON_AGENTE.md)."
        )
    if not hay_webview2():
        return (
            "Para abrir el panel de tiza hace falta Microsoft Edge WebView2. "
            f"Descárgalo de {webview2.DESCARGA} e inténtalo de nuevo."
        )
    return None


def ya_dentro(url: str | None, base: str) -> bool:
    """¿Ha terminado el login? Sí si la ventana está en ``/my`` del aula ``base``."""
    return entrada.es_panel(url, base)


def galletas_de(jars: Iterable[Mapping[str, Any]], servidor: str) -> list[entrada.Galleta]:
    """Las cookies del aula que devuelve ``Window.get_cookies()`` (nombre, valor, dominio).

    ``jars``: lo que devuelve pywebview, una lista de ``SimpleCookie`` (nombre -> ``Morsel``).
    Es el mismo formato que ``ventana.ejecutar_hijo``: las de otros dominios se descartan.
    """
    galletas = [
        {"name": nombre, "value": morsel.value, "domain": morsel["domain"] or servidor}
        for jar in jars
        for nombre, morsel in jar.items()
    ]
    return entrada.cookies_del_aula(galletas, servidor)


def acreditacion_de(jars: Iterable[Mapping[str, Any]], servidor: str) -> publicar.Cookies | None:
    """La acreditación por cookies del login, o None si no hay ninguna cookie del aula."""
    galletas = galletas_de(jars, servidor)
    return publicar.Cookies(tuple(galletas)) if galletas else None


def titulo_de_login(url: str | None, servidor: str) -> str:
    """El título de la ventana de entrada enseña el servidor de la página que se está viendo."""
    return f"Entrar en {urlsplit(url or '').hostname or servidor}"


def ruta_del_dialogo(resultado: object) -> str | None:
    """La carpeta de lo que devuelve ``create_file_dialog`` (una secuencia de rutas o None)."""
    if isinstance(resultado, str):
        return resultado or None
    if isinstance(resultado, Sequence) and resultado and isinstance(resultado[0], str):
        return resultado[0] or None
    return None


def modo_carpeta(webview: Any) -> Any:
    """El valor de «elegir carpeta» de ``create_file_dialog`` (``FileDialog.FOLDER`` en la 6)."""
    dialogos = getattr(webview, "FileDialog", None)
    if dialogos is not None and hasattr(dialogos, "FOLDER"):
        return dialogos.FOLDER
    return webview.FOLDER_DIALOG


# --- ventana de entrada al aula -------------------------------------------------------------


def abrir_login(
    url: str,
    *,
    webview: Any,
    panel: Panel,
    tiempo_maximo: float = TIEMPO_MAXIMO,
    sondeo: float = 0.2,
) -> publicar.Acreditacion | None:
    """La ventana de entrada al aula, en este proceso y sin ``js_api``. Corre en el hilo de la sesión.

    Devuelve las cookies del aula cuando la ventana llega a ``/my`` (y la cierra), o None si
    el docente la cierra sin entrar, se cierra el panel o pasa ``tiempo_maximo``. La cookie
    no sale de aquí: solo viaja dentro de la ``publicar.Cookies`` que se devuelve.
    """
    try:
        base = config.validar_url(url).rstrip("/")
    except config.ErrorConfig:
        return None
    servidor = urlsplit(base).hostname or ""
    resultado: list[publicar.Cookies | None] = []
    cerrada = threading.Event()
    web = webview.create_window(f"Entrar en {servidor}", f"{base}/my/", width=900, height=720)

    def cargada() -> None:
        try:
            actual = web.get_current_url()
            web.set_title(titulo_de_login(actual, servidor))
            if resultado or not ya_dentro(actual, base):
                return
            resultado.append(acreditacion_de(web.get_cookies(), servidor))
            web.destroy()
        except Exception:  # noqa: BLE001 - un fallo de la ventana no debe colgar la sesión
            _intentar(web.destroy)
            cerrada.set()

    web.events.loaded += cargada
    web.events.closed += cerrada.set
    plazo = tiempo_maximo
    while not cerrada.wait(sondeo):
        plazo -= sondeo
        if panel.cerrado or plazo <= 0:
            _intentar(web.destroy)
            cerrada.wait(2.0)
            break
    return resultado[0] if resultado else None


# --- hilo de la ventana ---------------------------------------------------------------------


def _intentar(accion: Callable[[], object]) -> None:
    try:
        accion()
    except Exception:  # noqa: BLE001 - las operaciones de ventana son de mejor esfuerzo
        pass


def vigilar(
    panel: Panel,
    ventana: Any,
    *,
    cerrar: threading.Event,
    parpadear: Callable[[], object],
    elegir_carpeta: Callable[[], object],
    poner_encima: Callable[[bool], object],
    restaurar: Callable[[], object],
    mostrar: Callable[[], object],
    minimizada: Callable[[], bool] = lambda: True,
    espera: float = ESPERA_VIGILANTE,
) -> None:
    """El hilo de la ventana: todo lo que toca la ventana del panel se hace desde aquí.

    «Siempre encima», restaurar y mostrar llegan inyectados (en Windows, las llamadas
    asíncronas de Win32): ``ventana.on_top`` de pywebview cambia ``TopMost`` del formulario
    desde este hilo sin ``Invoke`` y, si a la vez el hilo de la interfaz está devolviendo el
    resultado de una llamada del puente (el sondeo, cada 300 ms), los dos se bloquean para
    siempre (visto en Windows 11 con pywebview 6.2.1). De ``ventana`` solo se usa ``destroy``,
    que sí pasa por ``Invoke``.

    - Pregunta pendiente: la ventana pasa a estar siempre encima, se restaura si estaba
      minimizada y parpadea en la barra de tareas (una vez por pregunta). Sin pregunta, deja
      de estar encima.
    - Petición del diálogo de carpeta: lo abre (``elegir_carpeta``) y el ``Panel`` valida
      lo elegido.
    - Salida pedida (``Puente.terminar``): avisa a la sesión (``cerrar``) y destruye la ventana.

    Termina cuando se cierra el panel (la X de la ventana) o tras destruirla.
    """
    numero = -1
    avisada: int | None = None  # la pregunta por la que ya parpadeó
    delante = False  # ¿está ahora siempre encima?

    def encima(valor: bool) -> None:
        nonlocal delante
        delante = valor
        _intentar(lambda: poner_encima(valor))

    while True:
        numero = panel.esperar_cambio(numero, espera)
        if panel.salida_pedida:
            cerrar.set()
            _intentar(ventana.destroy)
            return
        if panel.cerrado:
            return
        if panel.dialogo_pedido:
            if delante:
                encima(False)  # el diálogo de carpeta no debe quedar detrás del panel
            _intentar(lambda: panel.atender_dialogo(elegir_carpeta))
            continue
        if panel.pregunta_pendiente:
            if not delante:
                encima(True)
                if minimizada():
                    _intentar(restaurar)
                _intentar(mostrar)
            if avisada != numero:
                avisada = numero
                _intentar(parpadear)
        elif delante:
            avisada = None
            encima(False)


# --- Windows: la barra de tareas -----------------------------------------------------------


def _hwnd_propio(titulo: str) -> Any:
    """El HWND de la ventana de este proceso con ese título (no una ajena con el mismo)."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    encontrados: list[Any] = []

    def cada(hwnd: Any, _param: Any) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != os.getpid():
            return True
        largo = user32.GetWindowTextLengthW(hwnd)
        texto = ctypes.create_unicode_buffer(largo + 1)
        user32.GetWindowTextW(hwnd, texto, largo + 1)
        if texto.value == titulo:
            encontrados.append(hwnd)
            return False
        return True

    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(proc(cada), 0)
    return encontrados[0] if encontrados else None


def parpadear_en_la_barra(titulo: str) -> bool:
    """Hace parpadear el icono de la barra de tareas (``FlashWindowEx``). Seguro fuera de Windows."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("hwnd", wintypes.HWND),
                ("dwFlags", wintypes.DWORD),
                ("uCount", wintypes.UINT),
                ("dwTimeout", wintypes.DWORD),
            ]

        hwnd = _hwnd_propio(titulo)
        if not hwnd:
            return False
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 3 | 12, 5, 0)  # ALL | TIMERNOFG
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        return True
    except Exception:  # noqa: BLE001
        return False


_HWND_TOPMOST, _HWND_NOTOPMOST = -1, -2
# SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS: no espera al hilo de la interfaz.
_SWP_ASINCRONO = 0x0001 | 0x0002 | 0x0010 | 0x4000
_SW_SHOW, _SW_RESTORE = 5, 9


def poner_encima(titulo: str, valor: bool) -> bool:
    """«Siempre encima» con ``SetWindowPos`` asíncrono: no bloquea ni toca el GIL de .NET."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        hwnd = _hwnd_propio(titulo)
        if not hwnd:
            return False
        delante = ctypes.c_void_p(_HWND_TOPMOST if valor else _HWND_NOTOPMOST)
        return bool(ctypes.windll.user32.SetWindowPos(hwnd, delante, 0, 0, 0, 0, _SWP_ASINCRONO))
    except Exception:  # noqa: BLE001
        return False


def mostrar_ventana(titulo: str, *, restaurar: bool = False) -> bool:
    """Muestra (o restaura) la ventana con ``ShowWindowAsync``: tampoco espera a la interfaz."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        hwnd = _hwnd_propio(titulo)
        if not hwnd:
            return False
        modo = _SW_RESTORE if restaurar else _SW_SHOW
        return bool(ctypes.windll.user32.ShowWindowAsync(hwnd, modo))
    except Exception:  # noqa: BLE001
        return False


def esta_minimizada(titulo: str) -> bool:
    """¿Está minimizada la ventana? Si no se puede saber, True (restaurar no estorba)."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        hwnd = _hwnd_propio(titulo)
        return True if not hwnd else bool(ctypes.windll.user32.IsIconic(hwnd))
    except Exception:  # noqa: BLE001
        return True


def avisar(texto: str) -> None:
    """Dice algo al docente sin consola: un cuadro de Windows o, fuera de Windows, stderr."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, texto, TITULO, 0x10)  # MB_ICONERROR
            return
        except Exception:  # noqa: BLE001
            pass
    print(texto, file=sys.stderr)


# --- punto de entrada -----------------------------------------------------------------------


def main() -> int:
    """``tiza-panel``: abre el panel. Es del docente: no se lanza desde un agente."""
    redirigir_salidas()
    falta = que_falta(
        sys.platform,
        hay_webview=importlib.util.find_spec("webview") is not None,
        hay_webview2=webview2.instalado,
    )
    if falta is not None:
        avisar(falta)
        return 1

    import webview  # solo aquí: ni los tests ni la CLI necesitan pywebview

    panel = Panel()
    cerrar = threading.Event()  # lo activa la ventana al cerrarse: la sesión se recoge sola
    presencia = PresenciaPanel(
        panel, abrir_login=lambda url: abrir_login(url, webview=webview, panel=panel)
    )
    puente = Puente(panel)
    ventana = webview.create_window(
        TITULO,
        html=pagina(nuevo_nonce()),
        js_api=puente,
        width=ANCHO,
        height=ALTO,
        min_size=MINIMO,
        text_select=True,
    )

    def cerrada() -> None:
        panel.cerrar()
        cerrar.set()

    ventana.events.closed += cerrada
    modo = modo_carpeta(webview)
    home, sistema = Path.home(), platform.system()
    flujo_hilo = threading.Thread(
        target=lambda: flujo.ejecutar(panel, presencia, home=home, sistema=sistema, cerrar=cerrar),
        name="flujo",
        daemon=True,
    )

    def arrancar() -> None:
        vigilante = threading.Thread(
            target=vigilar,
            args=(panel, ventana),
            kwargs={
                "cerrar": cerrar,
                "parpadear": lambda: parpadear_en_la_barra(TITULO),
                "elegir_carpeta": lambda: ruta_del_dialogo(ventana.create_file_dialog(modo)),
                "poner_encima": lambda valor: poner_encima(TITULO, valor),
                "restaurar": lambda: mostrar_ventana(TITULO, restaurar=True),
                "mostrar": lambda: mostrar_ventana(TITULO),
                "minimizada": lambda: esta_minimizada(TITULO),
            },
            name="ventana",
            daemon=True,
        )
        vigilante.start()
        flujo_hilo.start()

    try:
        webview.start(arrancar, private_mode=True)
    except Exception as exc:  # noqa: BLE001 - sin motor de ventanas: se dice, no se calla
        avisar(f"No se pudo abrir la ventana del panel ({type(exc).__name__}).")
        return 1
    # La ventana ya se cerró: la sesión tiene su tiempo para borrar ``sesion.json`` y la reserva.
    if flujo_hilo.is_alive():
        flujo_hilo.join(ESPERA_CIERRE)
    return 0
