"""El recorrido del panel, de la carpeta al cierre de la sesión (sin pywebview).

Lo ejecuta el hilo del flujo que lanza ``tiza.panel.main``: pide la carpeta, hace el
arranque común (``arranque.preparar``, aquí siempre con el aislamiento exigido: el panel
no abre la sesión con el agente sin aislar), abre la sesión y deja una pantalla de reposo
con el resultado. Todo lo que habla con el docente pasa por la ``Presencia`` recibida.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .. import __version__, actualizacion, aislamiento, arranque, mensajes, sesion
from ..publicacion import Aviso, Presencia
from . import recientes
from .estado import Panel

__all__ = ["MINUTOS", "contar_actualizacion", "ejecutar", "instalar_con_actualizador"]

MINUTOS = 60
PAUSA_ACTUALIZACION = 3.0  # lo que se deja leer «Se está actualizando» antes de cerrar


def instalar_con_actualizador(
    nueva: str,
    *,
    lanzar: Callable[..., bool] = actualizacion.lanzar_panel_oculto,
    buscar_uv: Callable[[str], str | None] = shutil.which,
) -> bool:
    """Lanza el actualizador oculto de Windows (espera a que este proceso termine); True si salió."""
    uv = buscar_uv("uv")
    return uv is not None and lanzar(uv, nueva)


def contar_actualizacion(presencia: Presencia, entorno: Mapping[str, str] | None = None) -> None:
    """Si el actualizador acaba de reabrir el panel, lo cuenta en el registro (una vez)."""
    if entorno is None:
        entorno = dict(os.environ)
        os.environ.pop(actualizacion.VARIABLE_RESULTADO, None)  # que no pase a procesos hijos
    resultado = actualizacion.resultado_del_entorno(entorno)
    if resultado is None:
        return
    se_actualizo, version = resultado
    if se_actualizo:
        presencia.informar(Aviso.panel_actualizado(version))
    else:
        presencia.informar(Aviso.panel_no_actualizado(__version__, str(actualizacion.ruta_log())))


def presencia_sin_entrar(presencia: Presencia) -> bool:
    """¿Se pidió entrar en el aula y no se entró? (solo la presencia del panel lo recuerda)."""
    return getattr(presencia, "sin_entrar", False) is True


def _faltas(home: Path, sistema: str, carpeta: Path, revisar: Callable) -> list:
    try:
        return [c for c in revisar(home, sistema, carpeta) if c.estado == "falta"]
    except OSError:
        return []


@dataclass(frozen=True)
class _Vuelta:
    """Lo que deja una vuelta: su código y la pantalla con la que termina."""

    codigo: int
    titulo: str
    lineas: tuple[str, ...]
    volver: bool = True
    salir: bool = False


def _error_interno(presencia: Presencia, exc: Exception) -> None:
    presencia.informar(Aviso.error_interno(type(exc).__name__))


def _olvidar_presencia(presencia: Presencia) -> None:
    """Entre vueltas, el «no se entró» de la anterior no vale para la siguiente."""
    if hasattr(presencia, "sin_entrar"):
        presencia.sin_entrar = False  # type: ignore[attr-defined]


def _una_vuelta(
    panel: Panel,
    presencia: Presencia,
    *,
    home: Path,
    sistema: str,
    cerrar: threading.Event,
    abrir_sesion: Callable[..., int],
    preparar: Callable[..., arranque.Resultado],
    revisar: Callable[..., list],
    minutos: int,
    version_nueva: Callable[[], str | None],
    instalar: Callable[[str], bool],
) -> _Vuelta:
    """De la carpeta al final de la sesión; no pregunta si se vuelve a empezar."""
    panel.fijar_paso("carpeta")
    carpeta = panel.esperar_carpeta(recientes.leer())
    if carpeta is None:
        return _Vuelta(1, "Cancelado", ("No se ha elegido ninguna carpeta.",))
    recientes.anotar(carpeta)
    panel.fijar_carpeta(recientes.nombre_visible(carpeta))
    try:
        resultado = preparar(
            carpeta,
            presencia,
            home=home,
            sistema=sistema,
            version_nueva=version_nueva,
            instalar=instalar,
            exigir_aislamiento=True,
        )
    except Exception as exc:  # noqa: BLE001 - el docente ve el tipo; el detalle no sale
        _error_interno(presencia, exc)
        return _Vuelta(1, "Algo ha fallado", ("No se pudo abrir la sesión. Mira el registro.",))
    if resultado.estado is arranque.Estado.ACTUALIZADA:
        return _Vuelta(
            0,
            mensajes.ACTUALIZANDO_TITULO,
            (mensajes.ACTUALIZANDO_TEXTO,),
            volver=False,
            salir=True,
        )
    if resultado.estado is arranque.Estado.FALLO:
        lineas = mensajes.lineas_de_error(resultado.codigo, resultado.detalle)
        for linea in lineas:
            panel.anotar(linea.texto, linea.error)
        return _Vuelta(1, "No se pudo abrir la sesión", tuple(linea.texto for linea in lineas))
    if resultado.estado is arranque.Estado.ABORTADO:
        faltas = _faltas(home, sistema, carpeta, revisar)
        if not faltas:
            return _Vuelta(1, "Cancelado", ("No se ha abierto la sesión.",))
        return _Vuelta(
            1,
            "Falta aislar al agente",
            (
                "El panel solo abre la sesión con el agente aislado. Todavía falta:",
                *[f"- {falta.agente}: {falta.texto}" for falta in faltas],
            ),
        )
    try:
        codigo = abrir_sesion(carpeta, presencia, minutos=minutos, preparar=True, cerrar=cerrar)
    except Exception as exc:  # noqa: BLE001
        _error_interno(presencia, exc)
        return _Vuelta(1, "Algo ha fallado", ("No se pudo abrir la sesión. Mira el registro.",))
    if codigo != 0 and presencia_sin_entrar(presencia):
        return _Vuelta(
            1,
            mensajes.NO_SE_ENTRO_TITULO,
            (mensajes.NO_SE_ENTRO_TEXTO, mensajes.NO_SE_ENTRO_QUE_HACER),
        )
    if codigo == 0:
        return _Vuelta(
            0, "Sesión cerrada", ("Puedes cerrar el panel. Para volver a trabajar, ábrelo.",)
        )
    return _Vuelta(1, "La sesión no se abrió", ("Mira el registro: dice qué ha pasado.",))


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
    version_nueva: Callable[[], str | None] = actualizacion.version_nueva,
    instalar: Callable[[str], bool] = instalar_con_actualizador,
    pausa: float = PAUSA_ACTUALIZACION,
) -> int:
    """Carpeta, arranque, sesión y pantalla final. Devuelve 0 si la sesión se abrió y se cerró.

    Si el docente pide volver a empezar, la vuelta siguiente empieza en la carpeta, en la
    misma ventana. Con una versión nueva el arranque ofrece actualizar: ``instalar`` lanza el
    actualizador, el panel deja una pantalla de reposo y se cierra para que el actualizador siga.
    """
    while True:
        vuelta = _una_vuelta(
            panel,
            presencia,
            home=home,
            sistema=sistema,
            cerrar=cerrar,
            abrir_sesion=abrir_sesion,
            preparar=preparar,
            revisar=revisar,
            minutos=minutos,
            version_nueva=version_nueva,
            instalar=instalar,
        )
        panel.reposo(vuelta.titulo, vuelta.lineas)
        if vuelta.salir:
            time.sleep(pausa)  # que el docente llegue a leerlo antes de que se cierre el panel
            panel.salir()
            return vuelta.codigo
        if not vuelta.volver or not panel.preguntar_final():
            return vuelta.codigo
        panel.nueva_vuelta()
        _olvidar_presencia(presencia)
