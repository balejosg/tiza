"""Buzón de ficheros entre el agente y la sesión abierta por el docente.

El agente no se conecta al aula ni ve la contraseña: mientras el docente
mantiene abierto ``tiza sesion`` en la carpeta de la asignatura, deja
peticiones en ``<carpeta>/.tiza/buzon/`` y espera una respuesta con el
esquema cerrado de :mod:`tiza.informe`. El proceso ``tiza sesion``, que sí
tiene la sesión Moodle en memoria, las atiende en la terminal del docente.

Protocolo (solo biblioteca estándar, sin red ni sockets):

- ``sesion.json``: lo escribe el docente. Lleva un latido que un hilo daemon
  actualiza cada pocos segundos y una caducidad; se borra al cerrar.
- ``<id>.peticion.json``: lo escribe el agente.
- ``<id>.respuesta.json``: lo escribe el docente; es un informe ya validado.

Todas las escrituras pasan por un fichero ``.tmp`` y un ``os.replace``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import __version__, informe
from .ficheros import FicheroNoSeguro, asegurar_directorio, escribir_json, leer_bytes_acotado

__all__ = [
    "ErrorBuzon",
    "LATIDO_SEGUNDOS",
    "LATIDO_MAX",
    "ESPERA_POR_DEFECTO",
    "MAX_FICHEROS",
    "MAX_PETICION_BYTES",
    "VERSION_PROTOCOLO",
    "caducidad",
    "codigo_intacto",
    "sesion_incompatible",
    "RESERVA",
    "abrir_sesion",
    "atender",
    "borrar_sesion",
    "carpeta_buzon",
    "crear_sesion",
    "enviar",
    "huella_codigo",
    "peticion_pendiente",
    "SesionAbierta",
    "sesion_activa",
    "validar_peticion",
]

BUZON = "buzon"
SESION = "sesion.json"
RESERVA = "sesion.reserva"  # una sola sesión por carpeta
SUFIJO_PETICION = ".peticion.json"
SUFIJO_RESPUESTA = ".respuesta.json"

LATIDO_SEGUNDOS = 5.0
LATIDO_MAX = 20.0
ESPERA_POR_DEFECTO = 600.0
INTERVALO = 0.5
INTERVALO_ATENCION = 1.0
MAX_FICHEROS = 20
MAX_PETICION_BYTES = 64 * 1024  # una petición de verdad ocupa unos cientos de bytes
VERSION_PROTOCOLO = 4  # súbela si cambia el formato de las peticiones o lo que garantiza la sesión

_CAMPOS = {"version", "id", "comando", "ficheros", "entorno", "visible", "solo_fechas"}
_ID = re.compile(r"\A[0-9a-f]{32}\Z")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ABSOLUTA = re.compile(r"\A(?:[/\\]|[A-Za-z]:)")
_COMANDOS = {"publicar", "estructura"}
_ENTORNOS = {"pruebas", "real"}


class ErrorBuzon(Exception):
    """Error del buzón con un código estable."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


# --------------------------------------------------------------------------- #
# Tiempo
# --------------------------------------------------------------------------- #


def ahora_utc() -> datetime:
    return datetime.now(UTC)


def _aware(momento: datetime) -> datetime:
    if momento.tzinfo is None:
        return momento.replace(tzinfo=UTC)
    return momento


def _fecha(valor: Any) -> datetime | None:
    if not isinstance(valor, str):
        return None
    try:
        return _aware(datetime.fromisoformat(valor))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Ficheros
# --------------------------------------------------------------------------- #


def huella_codigo() -> str:
    """Huella del código de tiza en disco: todo el paquete, también los subpaquetes.

    La sesión guarda la de su arranque; si la de disco cambia con la sesión
    abierta, es que tiza se actualizó y la sesión sigue con el código antiguo.
    """
    base = Path(__file__).parent
    resumen = hashlib.sha256()
    for ruta in sorted(base.rglob("*.py")):
        resumen.update(ruta.relative_to(base).as_posix().encode())
        resumen.update(ruta.read_bytes())
    return resumen.hexdigest()


def codigo_intacto() -> bool:
    """Si el código en disco sigue siendo el que cargó esta sesión al arrancar.

    En una app empaquetada (``sys.frozen``) no hay ficheros .py y el código no
    puede cambiar con la sesión abierta.
    """
    if getattr(sys, "frozen", False):
        return True
    return huella_codigo() == _HUELLA_SESION


def carpeta_buzon(dir_tiza: str | Path) -> Path:
    return Path(dir_tiza) / BUZON


def _carpeta_propia(dir_tiza: str | Path) -> Path:
    """La carpeta del buzón, lista para que escriba el docente.

    El agente escribe en ``.tiza``: si ``.tiza`` o ``buzon`` fueran enlaces simbólicos, la
    sesión escribiría (y borraría ``*.tmp``) en otro sitio. ``DIRECTORIO_NO_SEGURO``.
    """
    try:
        asegurar_directorio(Path(dir_tiza))
        return asegurar_directorio(carpeta_buzon(dir_tiza))
    except FicheroNoSeguro as exc:
        raise ErrorBuzon(
            "DIRECTORIO_NO_SEGURO", "«.tiza» o «.tiza/buzon» es un enlace, no una carpeta"
        ) from exc


def _leer_json(ruta: Path) -> Any:
    """El JSON de un fichero del buzón, o None si no se puede leer con seguridad.

    Lo escribe el agente: no se abre una FIFO (colgaría la sesión), no se sigue un enlace
    simbólico, no se lee lo que pasa de ``MAX_PETICION_BYTES`` y un JSON anidado en exceso
    (``RecursionError``) es un fichero inválido, no un fallo de la sesión.
    """
    try:
        return json.loads(leer_bytes_acotado(ruta, MAX_PETICION_BYTES).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None


def _borrar(ruta: Path) -> None:
    try:
        ruta.unlink()
    except OSError:
        pass


def _renovar(ruta: Path) -> None:
    """El agente sigue esperando: actualiza la fecha de su petición."""
    try:
        os.utime(ruta)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Peticiones
# --------------------------------------------------------------------------- #


def validar_peticion(peticion: Any) -> None:
    """Comprueba el esquema cerrado de una petición del agente."""
    if not isinstance(peticion, dict):
        raise ErrorBuzon("PETICION_INVALIDA", "la petición debe ser un objeto")
    for campo in peticion:
        if campo not in _CAMPOS:
            raise ErrorBuzon("PETICION_INVALIDA", f"campo «{campo}» no permitido")
    for campo in _CAMPOS:
        if campo not in peticion:
            raise ErrorBuzon("PETICION_INVALIDA", f"falta el campo «{campo}»")
    if peticion["version"] != VERSION_PROTOCOLO:
        raise ErrorBuzon("PETICION_INVALIDA", f"version debe ser {VERSION_PROTOCOLO}")
    if not isinstance(peticion["id"], str) or not _ID.match(peticion["id"]):
        raise ErrorBuzon("PETICION_INVALIDA", "id no es un hexadecimal de 32 dígitos")
    if peticion["comando"] not in _COMANDOS:
        raise ErrorBuzon("PETICION_INVALIDA", "comando no permitido")
    if peticion["visible"] is not None and not isinstance(peticion["visible"], bool):
        raise ErrorBuzon("PETICION_INVALIDA", "visible debe ser booleano o nulo")
    if not isinstance(peticion["solo_fechas"], bool):
        raise ErrorBuzon("PETICION_INVALIDA", "solo_fechas debe ser booleano")
    ficheros = peticion["ficheros"]
    if not isinstance(ficheros, list):
        raise ErrorBuzon("PETICION_INVALIDA", "ficheros debe ser una lista")
    if len(ficheros) > MAX_FICHEROS:
        raise ErrorBuzon("PETICION_INVALIDA", f"como mucho {MAX_FICHEROS} ficheros")
    for nombre in ficheros:
        _validar_ruta(nombre)
    entorno = peticion["entorno"]
    if entorno is not None and entorno not in _ENTORNOS:
        raise ErrorBuzon("PETICION_INVALIDA", "entorno no permitido")
    if peticion["comando"] == "estructura":
        if ficheros:
            raise ErrorBuzon("PETICION_INVALIDA", "estructura no admite ficheros")
        if entorno is not None:
            raise ErrorBuzon("PETICION_INVALIDA", "estructura no admite entorno")
        if peticion["solo_fechas"]:
            raise ErrorBuzon("PETICION_INVALIDA", "estructura no admite solo_fechas")
    else:
        if entorno is None:
            raise ErrorBuzon("PETICION_INVALIDA", "publicar exige entorno")
        if not ficheros:
            raise ErrorBuzon("PETICION_INVALIDA", "publicar exige al menos un fichero")
        if peticion["solo_fechas"] and peticion["visible"] is not None:
            raise ErrorBuzon(
                "PETICION_INVALIDA",
                "solo_fechas no admite visible: las fechas no cambian la visibilidad",
            )


def _validar_ruta(nombre: Any) -> None:
    if not isinstance(nombre, str) or not nombre:
        raise ErrorBuzon("PETICION_INVALIDA", "las rutas deben ser texto no vacío")
    if _CONTROL.search(nombre):
        raise ErrorBuzon("PETICION_INVALIDA", "la ruta contiene caracteres de control")
    if _ABSOLUTA.match(nombre):
        raise ErrorBuzon("PETICION_INVALIDA", "las rutas deben ser relativas")
    if ".." in re.split(r"[/\\]", nombre):
        raise ErrorBuzon("PETICION_INVALIDA", "la ruta no puede salir de la carpeta")


# --------------------------------------------------------------------------- #
# Sesión del docente
# --------------------------------------------------------------------------- #


_HUELLA_SESION = huella_codigo()  # el código que este proceso cargó al arrancar


def _escribir_sesion(
    ruta: Path, caduca: datetime, pid: int | None, ahora: Callable[[], datetime] | None
) -> None:
    momento = (ahora or ahora_utc)()
    escribir_json(
        ruta,
        {
            "version": VERSION_PROTOCOLO,
            "tiza": __version__,
            "pid": os.getpid() if pid is None else pid,
            "caduca": _aware(caduca).isoformat(),
            "latido": momento.isoformat(),
            "huella": _HUELLA_SESION,
        },
    )


def crear_sesion(
    dir_tiza: str | Path,
    caduca: datetime,
    *,
    pid: int | None = None,
    ahora: Callable[[], datetime] | None = None,
) -> Path:
    """Escribe ``sesion.json`` sin hilo de latido; devuelve su ruta."""
    carpeta = _carpeta_propia(dir_tiza)
    ruta = carpeta / SESION
    _escribir_sesion(ruta, caduca, pid, ahora)
    return ruta


def borrar_sesion(dir_tiza: str | Path) -> None:
    _borrar(carpeta_buzon(dir_tiza) / SESION)


def _reservar_carpeta(dir_tiza: str | Path, *, ahora: Callable[[], datetime] | None = None) -> Path:
    """Una sola «tiza sesion» por carpeta: dos atenderían la misma petición."""
    carpeta = _carpeta_propia(dir_tiza)
    ruta = carpeta / RESERVA
    for _intento in range(2):
        try:
            descriptor = os.open(ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                antes = ruta.stat()
            except OSError:
                continue
            if not _reserva_abandonada(dir_tiza, ruta, ahora=ahora):
                break
            try:
                actual = ruta.stat()
            except OSError:
                continue
            if (actual.st_ino, actual.st_mtime_ns) != (antes.st_ino, antes.st_mtime_ns):
                continue  # otro proceso la reclamó: reintenta el open
            # Best-effort: entre este último stat y el unlink aún cabría una
            # carrera; sin bloqueos del sistema no se puede cerrar del todo.
            _borrar(ruta)
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as fichero:
            fichero.write(f"{os.getpid()}\n")
        return ruta
    raise ErrorBuzon(
        "SESION_YA_ABIERTA",
        "ya hay una «tiza sesion» abierta en esta carpeta; si acabas de cerrarla, "
        f"espera {int(LATIDO_MAX)} segundos",
    )


def _reserva_abandonada(
    dir_tiza: str | Path, ruta: Path, *, ahora: Callable[[], datetime] | None = None
) -> bool:
    """Abandonada: nadie late en sesion.json y la reserva tiene más de LATIDO_MAX s."""
    if sesion_activa(dir_tiza, ahora=ahora):
        return False
    try:
        edad = time.time() - ruta.stat().st_mtime
    except OSError:
        return True
    return edad >= LATIDO_MAX


class SesionAbierta:
    """Sesión del docente en curso; solo ella puede ampliar su caducidad."""

    def __init__(
        self, ruta: Path, caduca: datetime, ahora: Callable[[], datetime] | None = None
    ) -> None:
        self.ruta = ruta
        self.caduca = _aware(caduca)
        self._ahora = ahora
        self._cerrojo = threading.Lock()  # latido y ampliación comparten el .tmp

    def escribir(self) -> None:
        with self._cerrojo:
            _escribir_sesion(self.ruta, self.caduca, None, self._ahora)

    def ampliar(self, nueva: datetime) -> None:
        nueva = _aware(nueva)
        if nueva <= self.caduca:
            raise ValueError("la ampliación debe alargar la sesión")
        self.caduca = nueva
        try:
            self.escribir()
        except OSError:
            pass  # p. ej. Windows con el fichero abierto: lo escribe el siguiente latido


@contextmanager
def abrir_sesion(
    dir_tiza: str | Path,
    caduca: datetime,
    *,
    intervalo: float = LATIDO_SEGUNDOS,
    ahora: Callable[[], datetime] | None = None,
):
    """Abre ``sesion.json`` con un hilo daemon que late hasta salir.

    Antes reserva la carpeta: si ya hay otra sesión, lanza SESION_YA_ABIERTA.
    """
    reserva = _reservar_carpeta(dir_tiza, ahora=ahora)
    try:
        ruta = crear_sesion(dir_tiza, caduca, ahora=ahora)
        sesion = SesionAbierta(ruta, caduca, ahora)
        evento = threading.Event()

        def latir() -> None:
            while not evento.wait(intervalo):
                try:
                    sesion.escribir()
                except OSError:
                    continue  # p. ej. Windows con el fichero abierto: reintenta en el siguiente latido

        hilo = threading.Thread(target=latir, name="tiza-latido", daemon=True)
        hilo.start()
        try:
            yield sesion
        finally:
            evento.set()
            hilo.join(timeout=2)
            borrar_sesion(dir_tiza)
    finally:
        _borrar(reserva)


def _sesion_viva(datos: Any, momento: datetime, latido_max: float) -> bool:
    """Fichero de sesión con pid, caducidad futura y latido reciente (sin mirar el protocolo)."""
    if not isinstance(datos, dict):
        return False
    if isinstance(datos.get("pid"), bool) or not isinstance(datos.get("pid"), int):
        return False
    caduca = _fecha(datos.get("caduca"))
    latido = _fecha(datos.get("latido"))
    if caduca is None or latido is None or momento >= caduca:
        return False
    return (momento - latido).total_seconds() < latido_max


def sesion_activa(
    dir_tiza: str | Path,
    *,
    ahora: Callable[[], datetime] | None = None,
    latido_max: float = LATIDO_MAX,
) -> bool:
    """Hay sesión si el fichero es válido, late, no ha caducado y habla nuestro protocolo."""
    datos = _leer_json(carpeta_buzon(dir_tiza) / SESION)
    momento = (ahora or ahora_utc)()
    return _sesion_viva(datos, momento, latido_max) and datos.get("version") == VERSION_PROTOCOLO


def sesion_incompatible(
    dir_tiza: str | Path,
    *,
    ahora: Callable[[], datetime] | None = None,
    latido_max: float = LATIDO_MAX,
) -> str | None:
    """Versión de tiza de una sesión viva que habla otro protocolo; None si no la hay."""
    datos = _leer_json(carpeta_buzon(dir_tiza) / SESION)
    momento = (ahora or ahora_utc)()
    if not _sesion_viva(datos, momento, latido_max) or datos.get("version") == VERSION_PROTOCOLO:
        return None
    version = datos.get("tiza")
    return version if isinstance(version, str) and version else "desconocida"


def caducidad(
    dir_tiza: str | Path, *, ahora: Callable[[], datetime] | None = None
) -> datetime | None:
    """Hora de cierre de la sesión activa, para enseñarla; None si no hay sesión."""
    if not sesion_activa(dir_tiza, ahora=ahora):
        return None
    datos = _leer_json(carpeta_buzon(dir_tiza) / SESION)
    return _fecha(datos.get("caduca")) if isinstance(datos, dict) else None


# --------------------------------------------------------------------------- #
# Lado del agente
# --------------------------------------------------------------------------- #


def enviar(
    dir_tiza: str | Path,
    peticion: dict,
    espera: float = ESPERA_POR_DEFECTO,
    *,
    intervalo: float = INTERVALO,
    dormir: Callable[[float], None] = time.sleep,
    ahora: Callable[[], datetime] | None = None,
) -> dict:
    """Deja una petición y espera la respuesta del docente."""
    validar_peticion(peticion)
    reloj = ahora or ahora_utc
    if not sesion_activa(dir_tiza, ahora=reloj):
        raise ErrorBuzon("SESION_CERRADA", "no hay una sesión abierta del docente")
    carpeta = carpeta_buzon(dir_tiza)
    ruta_peticion = carpeta / f"{peticion['id']}{SUFIJO_PETICION}"
    ruta_respuesta = carpeta / f"{peticion['id']}{SUFIJO_RESPUESTA}"
    escribir_json(ruta_peticion, peticion)
    limite = reloj() + timedelta(seconds=espera)
    try:
        while True:
            if not sesion_activa(dir_tiza, ahora=reloj):
                raise ErrorBuzon("SESION_CERRADA", "la sesión del docente se ha cerrado")
            respuesta = _leer_json(ruta_respuesta)
            if respuesta is not None:
                try:
                    informe.validar(respuesta)
                except informe.ErrorInforme as exc:
                    raise ErrorBuzon(
                        "RESPUESTA_INVALIDA", "la respuesta no cumple el esquema"
                    ) from exc
                return respuesta
            if reloj() >= limite:
                raise ErrorBuzon("SIN_RESPUESTA", "la sesión no respondió a tiempo")
            _renovar(ruta_peticion)
            dormir(intervalo)
    finally:
        _borrar(ruta_peticion)
        _borrar(ruta_respuesta)


def peticion_pendiente(dir_tiza: str | Path, id_: str, *, latido_max: float = LATIDO_MAX) -> bool:
    """Si el agente sigue esperando: su petición existe y la renovó hace poco.

    ``enviar`` la renueva en cada vuelta y la borra al desistir. Si a su proceso
    lo matan (el timeout de la terminal del agente; en Windows no hay señal que
    avise), deja de renovarse y en LATIDO_MAX segundos se da por retirada: un
    «s» tardío del docente ya no publica.
    """
    ruta = carpeta_buzon(dir_tiza) / f"{id_}{SUFIJO_PETICION}"
    try:
        edad = time.time() - ruta.stat().st_mtime
    except OSError:
        return False
    return edad < latido_max


# --------------------------------------------------------------------------- #
# Lado del docente
# --------------------------------------------------------------------------- #


def atender(
    dir_tiza: str | Path,
    procesar: Callable[[dict], dict],
    caduca: datetime,
    *,
    intervalo: float = INTERVALO_ATENCION,
    dormir: Callable[[float], None] = time.sleep,
    ahora: Callable[[], datetime] | None = None,
    terminar: Callable[[dict], bool] | None = None,
    al_fallar: Callable[[BaseException], None] | None = None,
    al_esperar: Callable[[], None] | None = None,
    parar: Callable[[], bool] | None = None,
) -> bool:
    """Atiende peticiones, de una en una, hasta ``caduca``.

    Devuelve verdadero si para porque ``terminar(respuesta)`` lo pide (por
    ejemplo, la sesión del aula ha caducado) y falso si llega a ``caduca``.
    ``parar()`` verdadero: deja de atender y devuelve falso (el docente cerró
    la sesión).
    """
    reloj = ahora or ahora_utc
    limite = _aware(caduca)
    carpeta = _carpeta_propia(dir_tiza)
    _limpiar(carpeta)
    while reloj() < limite:
        if parar is not None and parar():
            return False
        for ruta in sorted(carpeta.glob(f"*{SUFIJO_PETICION}")):
            if reloj() >= limite or (parar is not None and parar()):
                return False
            documento = _atender_una(carpeta, ruta, procesar, al_fallar)
            if documento is not None and terminar is not None and terminar(documento):
                return True
        if al_esperar is not None:
            al_esperar()
        dormir(intervalo)
    return False


def _atender_una(
    carpeta: Path,
    ruta: Path,
    procesar: Callable[[dict], dict],
    al_fallar: Callable[[BaseException], None] | None = None,
) -> dict | None:
    peticion = _leer_json(ruta)
    if not isinstance(peticion, dict):
        _borrar(ruta)
        return None
    try:
        validar_peticion(peticion)
    except ErrorBuzon:
        _borrar(ruta)
        return None
    if not codigo_intacto():
        # tiza cambió en disco con la sesión abierta: no se publica con el código viejo.
        documento = _informe_error(peticion, "SESION_DESACTUALIZADA")
    else:
        try:
            documento = procesar(peticion)
        except Exception as exc:  # noqa: BLE001 - último cortafuegos del lado del docente
            if al_fallar is not None:
                al_fallar(exc)
            documento = _informe_error(peticion, "ERROR_INTERNO")
    try:
        informe.validar(documento)
    except informe.ErrorInforme as exc:
        if al_fallar is not None:
            al_fallar(exc)
        documento = _informe_error(peticion, "ERROR_INTERNO")
    escribir_json(carpeta / f"{peticion['id']}{SUFIJO_RESPUESTA}", documento)
    _borrar(ruta)
    return documento


def _informe_error(peticion: dict, codigo: str) -> dict:
    return informe.crear(peticion["comando"], "error", [], [], [codigo], peticion["entorno"])


def _limpiar(carpeta: Path) -> None:
    for patron in (f"*{SUFIJO_PETICION}", f"*{SUFIJO_RESPUESTA}", "*.tmp"):
        for ruta in carpeta.glob(patron):
            _borrar(ruta)
