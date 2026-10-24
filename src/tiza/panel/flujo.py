"""El recorrido del panel, de la carpeta al cierre de la sesión (sin pywebview).

Lo ejecuta el hilo del flujo que lanza ``tiza.panel.main``: pide la carpeta, hace el
arranque común (``arranque.preparar``, aquí siempre con el aislamiento exigido: el panel
no abre la sesión con el agente sin aislar), abre la sesión y deja una pantalla de reposo
con el resultado. Todo lo que habla con el docente pasa por la ``Presencia`` recibida.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from .. import aislamiento, arranque, mensajes, sesion
from ..publicacion import Aviso, Presencia
from . import recientes
from .estado import Panel

__all__ = ["MINUTOS", "ejecutar"]

MINUTOS = 60


def _sin_actualizacion() -> None:
    # Las actualizaciones desde el panel son de la fase 4: por ahora nunca hay versión nueva.
    return None


def _no_instalar(_version: str) -> bool:
    return False


def _faltas(home: Path, sistema: str, carpeta: Path, revisar: Callable) -> list:
    try:
        return [c for c in revisar(home, sistema, carpeta) if c.estado == "falta"]
    except OSError:
        return []


def _error_interno(panel: Panel, presencia: Presencia, exc: Exception) -> int:
    presencia.informar(Aviso.error_interno(type(exc).__name__))
    panel.reposo("Algo ha fallado", ["No se pudo abrir la sesión. Mira el registro."])
    return 1


def ejecutar(
    panel: Panel,
    presencia: Presencia,
    *,
    home: Path,
    sistema: str,
    cerrar: threading.Event,
    abrir_sesion: Callable[..., int] = sesion.abrir,
    preparar: Callable[..., arranque.Resultado] = arranque.preparar,
    revisar: Callable[..., list] = aislamiento.revisar,
    minutos: int = MINUTOS,
) -> int:
    """Carpeta, arranque, sesión y pantalla final. Devuelve 0 si la sesión se abrió y se cerró."""
    carpeta = panel.esperar_carpeta(recientes.leer())
    if carpeta is None:
        panel.reposo("Cancelado", ["No se ha elegido ninguna carpeta."])
        return 1
    recientes.anotar(carpeta)
    panel.fijar_carpeta(recientes.nombre_visible(carpeta))
    try:
        resultado = preparar(
            carpeta,
            presencia,
            home=home,
            sistema=sistema,
            version_nueva=_sin_actualizacion,
            instalar=_no_instalar,
            exigir_aislamiento=True,
        )
    except Exception as exc:  # noqa: BLE001 - el docente ve el tipo; el detalle no sale
        return _error_interno(panel, presencia, exc)
    if resultado.estado is arranque.Estado.ACTUALIZADA:
        panel.reposo("tiza se ha actualizado", ["Vuelve a abrir el panel."])
        return 0
    if resultado.estado is arranque.Estado.FALLO:
        lineas = mensajes.lineas_de_error(resultado.codigo, resultado.detalle)
        for linea in lineas:
            panel.anotar(linea.texto, linea.error)
        panel.reposo("No se pudo abrir la sesión", [linea.texto for linea in lineas])
        return 1
    if resultado.estado is arranque.Estado.ABORTADO:
        faltas = _faltas(home, sistema, carpeta, revisar)
        if not faltas:
            panel.reposo("Cancelado", ["No se ha abierto la sesión."])
            return 1
        panel.reposo(
            "Falta aislar al agente",
            [
                "El panel solo abre la sesión con el agente aislado. Todavía falta:",
                *[f"- {falta.agente}: {falta.texto}" for falta in faltas],
            ],
        )
        return 1
    try:
        codigo = abrir_sesion(carpeta, presencia, minutos=minutos, preparar=True, cerrar=cerrar)
    except Exception as exc:  # noqa: BLE001
        return _error_interno(panel, presencia, exc)
    if codigo == 0:
        panel.reposo("Sesión cerrada", ["Puedes cerrar el panel. Para volver a trabajar, ábrelo."])
        return 0
    panel.reposo("La sesión no se abrió", ["Mira el registro: dice qué ha pasado."])
    return 1
