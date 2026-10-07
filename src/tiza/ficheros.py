"""Ficheros del lado de confianza: escritura atómica y lectura sin sorpresas.

``tiza sesion`` escribe y lee en carpetas donde también escribe el agente. Lo que allí
encuentra se trata como hostil: un enlace simbólico, una FIFO o un fichero enorme no deben
llevar al docente a escribir fuera de la carpeta, a quedarse colgado ni a agotar la memoria.
"""

from __future__ import annotations

import errno
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any

__all__ = [
    "FicheroNoSeguro",
    "asegurar_directorio",
    "escribir_json",
    "escribir_texto",
    "leer_bytes_acotado",
]

_TROZO = 64 * 1024
_ENLACE = {errno.ELOOP, getattr(errno, "EMLINK", errno.ELOOP)}


class FicheroNoSeguro(OSError):
    """Lo que hay en la ruta no es lo que tiza espera.

    ``motivo``: ``enlace`` (un enlace simbólico), ``no_regular`` (una FIFO, un dispositivo…),
    ``no_directorio`` (un fichero donde debía haber un directorio) o ``grande`` (pasa del límite).
    """

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


def escribir_texto(destino: str | Path, texto: str) -> Path:
    """Escribe ``texto`` con un temporal único y ``os.replace``: quien lee ve el fichero entero.

    El temporal se crea con ``x`` (falla si ya existe) y ``os.replace`` cambia el nombre sin
    seguir un enlace simbólico que hubiera en ``destino``: lo sustituye. Así, un enlace que deje
    el agente en la carpeta no lleva a escribir en otro sitio.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(f"{destino.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporal, "x", encoding="utf-8") as fichero:
            fichero.write(texto)
        os.replace(temporal, destino)
    except OSError:
        try:
            temporal.unlink()
        except OSError:
            pass
        raise
    return destino


def escribir_json(destino: str | Path, datos: Any) -> Path:
    """Escribe ``datos`` como JSON legible con un temporal único y ``os.replace``.

    El temporal lleva un nombre aleatorio: dos escritores (el latido y una
    ampliación, o dos procesos) nunca pisan el mismo.
    """
    return escribir_texto(destino, json.dumps(datos, ensure_ascii=False, indent=2) + "\n")


def leer_bytes_acotado(ruta: str | Path, maximo: int, *, enlaces: bool = False) -> bytes:
    """Lee un fichero normal de como mucho ``maximo`` bytes, sin quedarse esperando.

    Lanza ``FicheroNoSeguro`` si es una FIFO o un dispositivo (``O_NONBLOCK`` evita que abrir
    una FIFO bloquee), si pasa de ``maximo`` bytes (también si crece mientras se lee) o, con
    ``enlaces=False``, si el último tramo de la ruta es un enlace simbólico (``O_NOFOLLOW``; en
    Windows no existe y el enlace se sigue). Los demás errores del sistema se propagan.
    """
    banderas = os.O_RDONLY
    for nombre in ("O_NONBLOCK", "O_CLOEXEC", "O_BINARY"):
        banderas |= getattr(os, nombre, 0)
    if not enlaces:
        banderas |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(ruta, banderas)
    except OSError as exc:
        if exc.errno in _ENLACE:
            raise FicheroNoSeguro("enlace") from exc
        raise
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise FicheroNoSeguro("no_regular")
        if info.st_size > maximo:
            raise FicheroNoSeguro("grande")
        trozos: list[bytes] = []
        leidos = 0
        while True:
            trozo = os.read(descriptor, min(_TROZO, maximo + 1 - leidos))
            if not trozo:
                break
            trozos.append(trozo)
            leidos += len(trozo)
            if leidos > maximo:
                raise FicheroNoSeguro("grande")
        return b"".join(trozos)
    finally:
        os.close(descriptor)


def asegurar_directorio(ruta: str | Path) -> Path:
    """Crea el directorio si falta y se niega si es un enlace simbólico o no es un directorio.

    Para las carpetas de trabajo de tiza dentro de una carpeta donde escribe el agente
    (``.tiza``, ``.tiza/buzon``): un enlace podría llevar lo que escribe el docente a otro sitio.
    Solo mira el último tramo de la ruta: quien llama comprueba cada nivel que cuelga de la
    carpeta de la asignatura (primero ``.tiza``, después ``.tiza/buzon``).
    """
    ruta = Path(ruta)
    if ruta.is_symlink():
        raise FicheroNoSeguro("enlace")
    try:
        ruta.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        raise FicheroNoSeguro("no_directorio") from None
    if ruta.is_symlink():
        raise FicheroNoSeguro("enlace")
    if not ruta.is_dir():
        raise FicheroNoSeguro("no_directorio")
    return ruta
