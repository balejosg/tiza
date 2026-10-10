"""Ventana de sesión de tiza: la conexión con el aula sin terminal.

Es del docente, como «tiza sesion»: ningún agente la ejecuta. La contraseña
solo se escribe aquí y solo vive en la memoria de este proceso.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

from .. import ayuda, config, sesion
from ..config import ErrorConfig
from . import pagina, webview2
from .estado import PresenciaVentana, Puente, Ventana

__all__ = ["ejecutar", "main"]


def _configurado() -> bool:
    try:
        return config.cargar_global() is not None
    except ErrorConfig:
        return False


def _configurar(ventana: Ventana) -> bool:
    """Primera vez: URL del aula y usuario (nunca la contraseña)."""
    error = ""
    while True:
        respuesta = ventana.preguntar({"tipo": "configurar", "error": error})
        if respuesta is None:
            return False
        try:
            base = config.preparar_url(respuesta["url"])
            config.guardar_global(base, respuesta["usuario"])
            return True
        except ErrorConfig as exc:
            error = ayuda.explicar(exc.codigo) or exc.codigo


def _flujo(
    ventana: Ventana,
    presencia: PresenciaVentana,
    *,
    minutos: int,
    debug: bool,
    elegir_cursos: bool = False,
) -> int:
    """Configura si hace falta, abre la sesión y ofrece reconectar al cerrarse."""
    codigo = 1
    while not ventana.cerrar.is_set():
        if not _configurado() and not _configurar(ventana):
            return 1
        ventana.motivo = ""
        codigo = sesion.abrir(
            ventana.carpeta,
            presencia,
            minutos=minutos,
            preparar=True,
            debug=debug,
            cerrar=ventana.cerrar,
            dir_vistas=ventana.dir_vistas,
            elegir_cursos=elegir_cursos,
        )
        elegir_cursos = False  # solo la primera vez: al reconectar se usan los guardados
        if ventana.cerrar.is_set():
            return codigo
        texto = ventana.motivo or "Conexión cerrada."
        if ventana.preguntar({"tipo": "cerrada", "texto": texto}) is not True:
            return codigo
    return codigo


def ejecutar(
    carpeta: str | Path, *, minutos: int = 60, debug: bool = False, elegir_cursos: bool = False
) -> int:
    """Abre la ventana de sesión para ``carpeta``; devuelve 0 o 1 como «tiza sesion»."""
    if sys.platform == "win32" and not webview2.instalado():
        webview2.avisar_que_falta()
        return 1
    import webview  # solo aquí: los tests y la CLI no necesitan pywebview

    dir_vistas = sesion.crear_dir_vistas()
    try:
        return _abrir_ventana(
            webview,
            Path(carpeta),
            dir_vistas,
            minutos=minutos,
            debug=debug,
            elegir_cursos=elegir_cursos,
        )
    finally:
        shutil.rmtree(dir_vistas, ignore_errors=True)


def _abrir_ventana(
    webview: Any,
    carpeta: Path,
    dir_vistas: Path,
    *,
    minutos: int,
    debug: bool,
    elegir_cursos: bool = False,
) -> int:
    ventana = Ventana(carpeta, dir_vistas=dir_vistas)
    presencia = PresenciaVentana(ventana)
    resultado = {"codigo": 1}
    hilos: list[threading.Thread] = []

    def cerrar() -> None:
        ventana.cerrar_todo()
        web.destroy()

    puente = Puente(ventana, al_cerrar=cerrar)
    web = webview.create_window(
        "Conexión con el aula",
        html=pagina.html(),
        js_api=puente,
        width=560,
        height=760,
        min_size=(420, 560),
        text_select=True,
        zoomable=True,
        background_color="#F6F3EE",
    )
    puente._enlazar(web.get_current_url)
    web.events.closed += ventana.cerrar_todo

    def trabajar() -> None:
        if sys.platform == "win32" and webview.renderer != "edgechromium":
            web.destroy()  # MSHTML: sin WebView2 no se sigue
            return
        resultado["codigo"] = _flujo(
            ventana, presencia, minutos=minutos, debug=debug, elegir_cursos=elegir_cursos
        )
        web.destroy()

    def arrancar() -> None:
        hilo = threading.Thread(target=trabajar, name="tiza-ventana", daemon=True)
        hilos.append(hilo)
        hilo.start()

    webview.start(arrancar, private_mode=True, debug=debug)
    ventana.cerrar_todo()
    for hilo in hilos:
        hilo.join(timeout=15)  # deja que la sesión borre sesion.json y la reserva
    return resultado["codigo"]


def _minutos(valor: str) -> int:
    if not valor.isdigit() or not 0 < int(valor) <= sesion.MAX_MINUTOS:
        raise argparse.ArgumentTypeError(
            f"los minutos deben ser un número entero entre 1 y {sesion.MAX_MINUTOS}"
        )
    return int(valor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tiza-ventana",
        description="Conexión con el aula en una ventana (del docente, nunca del agente).",
    )
    parser.add_argument("--carpeta", required=True, help="carpeta de la asignatura")
    parser.add_argument("--minutos", type=_minutos, default=60, help="minutos de conexión")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--elegir-cursos",
        action="store_true",
        help="vuelve a preguntar el curso de pruebas y los reales",
    )
    args = parser.parse_args(argv)
    return ejecutar(
        args.carpeta, minutos=args.minutos, debug=args.debug, elegir_cursos=args.elegir_cursos
    )
