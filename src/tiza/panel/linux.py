"""La capa de ventana del panel en Linux (Qt con PySide6, a través de pywebview).

Lo que se comprobó en las espigas (Debian 12 con openbox y Ubuntu 24.04 con GNOME, en Xorg y
en Wayland, pywebview 6.2.1 y PySide6 6.12):

- Las operaciones de ventana de pywebview (``on_top``, ``restore``, ``show``) pasan por señales
  de Qt: se pueden pedir desde el hilo de la ventana sin colgar el sondeo del puente. La
  ventana minimizada se sabe por los eventos ``minimized``/``restored`` (en Wayland no llegan).
- Sin ``libxcb-cursor0`` (Ubuntu 24.04 no la trae) Qt **aborta el proceso** en Xorg, sin
  excepción que capturar. Se busca antes y, si falta, se baja con apt sin root a la carpeta
  de configuración de tiza (que el agente no puede escribir) y se carga antes que Qt.
- Con PySide6 el recolector de ciclos de Python puede liberar vistas de QtWebEngine desde
  cualquier hilo y Qt aborta («QOpenGLContext … different thread»): la recolección
  automática se apaga y se recoge con un latido en el hilo de la interfaz.
- En Wayland GNOME asocia la ventana al acceso por su nombre (``tiza.desktop``): sin
  ``setDesktopFileName`` el panel minimizado desaparece del dock.

Lo comprobable son funciones puras o con lo de fuera inyectado; lo que importa Qt solo se
llama desde ``tiza.panel.main``.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import gc
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .. import config

__all__ = [
    "LIBRERIA_CURSOR",
    "NOMBRE_ESCRITORIO",
    "PAQUETE_CURSOR",
    "Latido",
    "VentanaQt",
    "avisar",
    "bajar_libreria",
    "carpeta_librerias",
    "en_wayland",
    "preparar_qt",
    "ruta_log",
]

NOMBRE_ESCRITORIO = "tiza"  # el acceso es tiza.desktop
LIBRERIA_CURSOR = "libxcb-cursor.so.0"
PAQUETE_CURSOR = "libxcb-cursor0"
CADA_RECOGIDA = 2.0  # segundos entre recogidas de basura en el hilo de la interfaz
ESPERA_APT = 120  # segundos como mucho para bajar el paquete

_FALTA_CURSOR = (
    "Para abrir el panel de tiza falta la librería del sistema «libxcb-cursor0» y no se pudo "
    "conseguir sin permisos de administrador. Pide que la instalen (en Ubuntu: «sudo apt "
    "install libxcb-cursor0») o abre la sesión con «tiza empezar» en la terminal."
)


def ruta_log() -> Path:
    """Donde queda lo que el panel no pudo contar en pantalla (sin secretos)."""
    return config.directorio_global() / "panel.log"


def carpeta_librerias() -> Path:
    """Las librerías que el panel baja él mismo. Está en la configuración global de tiza, que
    el perfil de aislamiento prohíbe escribir al agente: lo que hay aquí se carga en el panel,
    fuera del sandbox."""
    return config.directorio_global() / "lib"


def en_wayland(entorno: Mapping[str, str]) -> bool:
    """¿Usará Qt Wayland? Sí si hay sesión de Wayland y no se fuerza X11 (``xcb``)."""
    forzada = entorno.get("QT_QPA_PLATFORM", "")
    return bool(entorno.get("WAYLAND_DISPLAY")) and not forzada.startswith("xcb")


def bajar_libreria(
    destino: Path,
    *,
    paquete: str = PAQUETE_CURSOR,
    fichero: str = LIBRERIA_CURSOR,
    ejecutar: Callable[..., Any] = subprocess.run,
    buscar: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    """Baja ``paquete`` con ``apt-get download`` (sin root, firmado por el repositorio del
    sistema), lo extrae y deja ``fichero`` en ``destino``. None si no hay apt o algo falla."""
    if buscar("apt-get") is None or buscar("dpkg-deb") is None:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="tiza-") as temporal:
            trabajo = Path(temporal)
            opciones = {"cwd": trabajo, "capture_output": True, "timeout": ESPERA_APT}
            if ejecutar(["apt-get", "download", paquete], **opciones).returncode != 0:
                return None
            debs = sorted(trabajo.glob("*.deb"))
            if not debs:
                return None
            extraido = trabajo / "x"
            if ejecutar(["dpkg-deb", "-x", str(debs[0]), str(extraido)], **opciones).returncode:
                return None
            encontrados = sorted(extraido.glob(f"usr/lib/**/{fichero}"))
            if not encontrados:
                return None
            destino.mkdir(parents=True, exist_ok=True)
            final = destino / fichero
            shutil.copyfile(encontrados[0].resolve(), final)
            return final
    except (OSError, subprocess.SubprocessError):
        return None


def preparar_qt(
    entorno: Mapping[str, str],
    *,
    carpeta: Path | None = None,
    buscar_libreria: Callable[[str], str | None] = ctypes.util.find_library,
    bajar: Callable[[Path], Path | None] = bajar_libreria,
    cargar: Callable[[str], object] = lambda ruta: ctypes.CDLL(ruta, mode=ctypes.RTLD_GLOBAL),
) -> str | None:
    """Deja Qt en condiciones de arrancar; devuelve el texto para el docente si no se puede.

    En Xorg, si el sistema no tiene ``libxcb-cursor``, se usa la copia propia de tiza (o se
    baja) y se carga antes que Qt: el cargador del sistema la reconoce por su nombre y Qt ya
    no aborta. En Wayland no hace falta.
    """
    if en_wayland(entorno) or buscar_libreria("xcb-cursor"):
        return None
    propia = (carpeta or carpeta_librerias()) / LIBRERIA_CURSOR
    if not propia.is_file() and bajar(propia.parent) is None:
        return _FALTA_CURSOR
    try:
        cargar(str(propia))
    except OSError:
        return _FALTA_CURSOR
    return None


class Latido:
    """Llama a ``emitir`` cada ``cada`` segundos en un hilo propio hasta ``parar``.

    Con Qt, ``emitir`` es una señal cuyo receptor vive en el hilo de la interfaz (y recoge la
    basura allí); el latido no toca nada de Qt.
    """

    def __init__(self, emitir: Callable[[], object], cada: float = CADA_RECOGIDA) -> None:
        self._emitir = emitir
        self._cada = cada
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._latir, name="recogida", daemon=True)

    def empezar(self) -> None:
        self._hilo.start()

    def parar(self) -> None:
        self._parar.set()

    def _latir(self) -> None:
        while not self._parar.wait(self._cada):
            try:
                self._emitir()
            except Exception:  # noqa: BLE001 - al cerrar, la señal puede haber desaparecido
                return


class VentanaQt:
    """Las operaciones de ventana del panel en Linux sobre la ``Window`` de pywebview.

    ``alertar`` marca la ventana como urgente (en Qt, ``QApplication.alert`` por una señal).
    Si no hay forma de saber si está minimizada (Wayland), se da por que no.
    """

    def __init__(self, ventana: Any, *, alertar: Callable[[], object] = lambda: None) -> None:
        self._ventana = ventana
        self._alertar = alertar
        self._minimizada = False
        ventana.events.minimized += self._al_minimizar
        ventana.events.restored += self._al_restaurar

    def _al_minimizar(self) -> None:
        self._minimizada = True

    def _al_restaurar(self) -> None:
        self._minimizada = False

    def poner_encima(self, valor: bool) -> bool:
        self._ventana.on_top = valor
        return True

    def restaurar(self) -> bool:
        self._ventana.restore()
        self._minimizada = False
        return True

    def mostrar(self) -> bool:
        self._ventana.show()
        return True

    def minimizada(self) -> bool:
        return self._minimizada

    def parpadear(self) -> object:
        return self._alertar()


def preparar_proceso(ventana_nativa: Callable[[], Any]) -> tuple[Latido, Callable[[], None]]:
    """Lo de Qt que tiene que existir en el hilo principal antes de ``webview.start``.

    Apaga la recolección automática y devuelve el latido que la hace en el hilo de la
    interfaz, y la función que marca la ventana (``ventana_nativa()``) como urgente.
    """
    from qtpy.QtCore import QObject, Signal
    from qtpy.QtGui import QGuiApplication
    from qtpy.QtWidgets import QApplication

    QGuiApplication.setDesktopFileName(NOMBRE_ESCRITORIO)

    class _Interfaz(QObject):  # creado aquí: sus señales se atienden en el hilo de la interfaz
        recoger = Signal()
        alertar = Signal()

        def __init__(self) -> None:
            super().__init__()
            self.recoger.connect(self._recoger)
            self.alertar.connect(self._alertar)

        def _recoger(self) -> None:
            gc.collect()

        def _alertar(self) -> None:
            nativa = ventana_nativa()
            if nativa is not None:
                QApplication.alert(nativa, 0)

    interfaz = _Interfaz()
    gc.disable()
    _vivos.append(interfaz)  # que no lo recoja nadie mientras viva el proceso
    return Latido(interfaz.recoger.emit), interfaz.alertar.emit


_vivos: list[Any] = []


def _anotar(texto: str) -> None:
    try:
        destino = ruta_log()
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("a", encoding="utf-8") as log:
            log.write(texto + "\n")
    except OSError:
        pass


# El cuadro de Qt va en un proceso hijo: si Qt no puede conectar con la pantalla (dentro de un
# sandbox, por ejemplo) aborta el proceso sin excepción que capturar, y el panel tiene que
# seguir para probar otro camino.
_CUADRO_QT = (
    "import sys\n"
    "from qtpy.QtWidgets import QApplication, QMessageBox\n"
    "app = QApplication(sys.argv[:1])\n"
    "QMessageBox.critical(None, 'tiza', sys.argv[1])\n"
)


def _con_qt(texto: str, ejecutar: Callable[..., Any] = subprocess.run) -> bool:
    try:
        resultado = ejecutar(
            [sys.executable, "-c", _CUADRO_QT, texto], capture_output=True, timeout=600
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return resultado.returncode == 0


def avisar(
    texto: str,
    *,
    con_qt: bool,
    ejecutar: Callable[..., Any] = subprocess.run,
    buscar: Callable[[str], str | None] = shutil.which,
    qt: Callable[[str], bool] = _con_qt,
    anotar: Callable[[str], None] = _anotar,
) -> None:
    """Dice algo al docente sin consola: con Qt si arranca; si no, ``zenity``, ``kdialog`` o
    ``notify-send``, lo que haya. Siempre queda en el log del panel."""
    anotar(texto)
    if con_qt and qt(texto):
        return
    for programa, argumentos in (
        ("zenity", ["--error", "--title=tiza", "--no-markup", f"--text={texto}"]),
        ("kdialog", ["--title", "tiza", "--error", texto]),
        ("notify-send", ["tiza", texto]),
    ):
        ruta = buscar(programa)
        if ruta is None:
            continue
        try:
            ejecutar([ruta, *argumentos], check=False, timeout=600)
            return
        except (OSError, subprocess.SubprocessError):
            continue
