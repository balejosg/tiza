"""Ventana de entrada de tiza: el docente entra en la página de su aula y tiza recoge la sesión.

La contraseña se escribe en la página del aula, no en tiza: tiza solo ve las cookies de
sesión del servidor del aula, que el hijo devuelve por su salida estándar. Es del docente,
como ``tiza sesion``: ningún agente la ejecuta (el hijo exige una terminal delante).

El padre (``entrar``) lanza ``python -m tiza.ventana <url>``; solo el hijo importa pywebview.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from typing import Any, TextIO
from urllib.parse import urlsplit

from . import entrada, webview2

__all__ = ["ErrorVentana", "disponible", "ejecutar_hijo", "entrar", "principal"]

TIEMPO_MAXIMO = 900  # segundos que se espera a que el docente entre
SALIDA_USO = 2
SALIDA_SIN_MOTOR = 3


class ErrorVentana(Exception):
    """La ventana no se pudo abrir o no devolvió una sesión válida."""

    def __init__(self, detalle: str = "") -> None:
        super().__init__(detalle)
        self.detalle = detalle


def disponible() -> bool:
    """¿Hay ventana en este sistema? Windows (con WebView2) y macOS, con el extra instalado."""
    if sys.platform not in ("win32", "darwin"):
        return False
    if importlib.util.find_spec("webview") is None:
        return False
    return sys.platform != "win32" or webview2.instalado()


def entrar(
    url: str, *, ejecutar: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> list[entrada.Galleta] | None:
    """Abre la ventana de entrada del aula ``url``.

    Devuelve las cookies de sesión del aula, ``None`` si el docente cierra la ventana sin
    entrar, o lanza ``ErrorVentana`` si no se pudo abrir.
    """
    try:
        proceso = ejecutar(
            [sys.executable, "-m", "tiza.ventana", url],
            stdout=subprocess.PIPE,  # stdin y stderr se heredan: son la terminal del docente
            text=True,
            timeout=TIEMPO_MAXIMO,
        )
    except subprocess.TimeoutExpired:
        return None
    except OSError as exc:
        raise ErrorVentana("no se pudo lanzar la ventana") from exc
    if proceso.returncode != 0:
        raise ErrorVentana(f"la ventana terminó con el código {proceso.returncode}")
    cookies = entrada.decodificar(proceso.stdout or "")
    if cookies is None:
        raise ErrorVentana("la ventana devolvió algo que no es una sesión")
    return cookies or None


def ejecutar_hijo(url: str, *, webview: Any = None, canal: TextIO | None = None) -> int:
    """El proceso de la ventana: abre ``<aula>/my/`` y escribe las cookies en ``canal``.

    ``webview`` y ``canal`` se inyectan en los tests; por defecto, pywebview y la salida
    estándar. El título de la ventana enseña el servidor de la página que se está viendo (la
    ventana no tiene barra de direcciones): así se nota cuándo salta al proveedor de acceso.
    """
    from .. import config

    try:
        base = config.validar_url(url).rstrip("/")
    except config.ErrorConfig:
        return SALIDA_USO
    if sys.platform == "win32" and not webview2.instalado():
        return SALIDA_SIN_MOTOR
    if webview is None:
        import webview as pywebview  # solo aquí: los tests y la CLI no necesitan pywebview

        webview = pywebview

    servidor = urlsplit(base).hostname or ""
    cookies: list[entrada.Galleta] = []
    web = webview.create_window(
        f"Entrar en {servidor}",
        f"{base}/my/",
        width=900,
        height=720,
        min_size=(480, 560),
        text_select=True,
    )  # sin js_api: la página del aula no puede llamar a nada de tiza

    def cargada() -> None:
        actual = web.get_current_url()
        web.set_title(f"Entrar en {urlsplit(actual or '').hostname or servidor}")
        if not entrada.es_panel(actual, base):
            return
        galletas = [
            {"name": nombre, "value": morsel.value, "domain": morsel["domain"] or servidor}
            for jar in web.get_cookies()
            for nombre, morsel in jar.items()
        ]
        cookies.extend(entrada.cookies_del_aula(galletas, servidor))
        web.clear_cookies()  # ya no hacen falta en el motor
        web.destroy()

    web.events.loaded += cargada
    webview.start(private_mode=True)
    if sys.platform == "win32" and webview.renderer != "edgechromium":
        return SALIDA_SIN_MOTOR
    salida = canal if canal is not None else sys.stdout
    salida.write(entrada.codificar(cookies) + "\n")
    salida.flush()
    return 0


def _canal_propio() -> TextIO | None:
    """Un canal solo para el resultado: lo demás que escriba el proceso va a la terminal.

    pywebview, GTK o WebView2 pueden escribir en la salida estándar; si se mezclara con el
    JSON, tiza no lo entendería después de que el docente ya hubiera entrado. Se duplica el
    descriptor 1 (la tubería hacia tiza) y el 1 pasa a apuntar al 2 (la terminal).
    """
    try:
        sys.stdout.flush()
        canal = os.fdopen(os.dup(1), "w", encoding="utf-8")
        os.dup2(2, 1)
    except (OSError, ValueError):
        return None
    return canal


def principal(argv: list[str] | None = None) -> int:
    """Punto de entrada de ``python -m tiza.ventana <url>``: solo con una terminal delante."""
    argumentos = sys.argv[1:] if argv is None else argv
    if len(argumentos) != 1:
        print(
            "Uso: python -m tiza.ventana <url-del-aula> (lo lanza tiza, no se ejecuta a mano)",
            file=sys.stderr,
        )
        return SALIDA_USO
    # Del docente: stdin y stderr son su terminal; stdout es la tubería hacia tiza.
    if not (sys.stdin.isatty() and sys.stderr.isatty()) or sys.stdout.isatty():
        print("Esta ventana la abre tiza en la terminal del docente.", file=sys.stderr)
        return SALIDA_USO
    return ejecutar_hijo(argumentos[0], canal=_canal_propio())
