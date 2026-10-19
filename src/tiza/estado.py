"""Estado de trabajo de la asignatura: lo que tiza guarda en ``.tiza/``.

Único dueño de los nombres de los ficheros del estado, de sus formatos y de su
validación al leer: la estructura de secciones (``estructura.json``), el registro
de lo verificado en pruebas (``verificados.json``), las vistas previas
(``preview/``), el informe (``informe.json``) y la importación de una copia de
seguridad (``copia.json``, ``copia/<cmid>.html`` y ``copias/``).

Aquí no se habla con el aula ni se importa python-moodle: el lado del agente
(``tiza comprobar``) puede usar este módulo sin cargar nada del aula. La
estructura se valida al escribir y al leer con el esquema cerrado de
:mod:`tiza.informe`.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import stat
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import rutas
from .ficheros import (
    FicheroNoSeguro,
    asegurar_directorio,
    escribir_json,
    escribir_texto,
    leer_bytes_acotado,
)

__all__ = [
    "CARPETA_COPIA",
    "CARPETA_COPIAS",
    "CARPETA_LECTURAS",
    "CARPETA_PREVIEW",
    "ErrorEstado",
    "Estructura",
    "FICHERO_COPIA",
    "FICHERO_ESTRUCTURA",
    "FICHERO_INFORME",
    "FICHERO_VERIFICADOS",
    "Verificado",
    "anotar_verificado",
    "buscar_seccion",
    "cargar_copia",
    "cargar_estructura",
    "cargar_verificados",
    "comprobar_puerta_real",
    "escribir_copia",
    "escribir_estructura",
    "guardar_verificado",
    "guardar_version_de_copia",
    "nombre_de_copia",
    "nombre_de_seccion",
    "reservar_copia",
    "ruta_lectura",
    "temporal_de_copia",
]

MAX_COPIA_JSON = 16 * 1024 * 1024  # copia.json, al leerlo
EDAD_MAXIMA_TEMPORAL = 24 * 60 * 60  # segundos que dura el temporal de una descarga
FICHERO_INFORME = "informe.json"
FICHERO_ESTRUCTURA = "estructura.json"
FICHERO_VERIFICADOS = "verificados.json"
CARPETA_PREVIEW = "preview"  # las vistas previas clicables dentro de la carpeta de trabajo
CARPETA_LECTURAS = "lecturas"  # el texto de cada Word o PDF que lee ``tiza leer``
FICHERO_COPIA = "copia.json"  # el resumen de lo que ``tiza importar`` hizo con una copia
CARPETA_COPIA = "copia"  # ``copia/<cmid>.html``: la versión nueva de una actividad ya importada
CARPETA_COPIAS = "copias"  # donde ``tiza copia`` deja los .mbz que pide a la sesión


class ErrorEstado(Exception):
    """Error del estado de trabajo con un código estable."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


@dataclass(frozen=True)
class Estructura:
    """La estructura de secciones ya validada: la misma forma para v1 y v2.

    ``pruebas`` es el curso de pruebas o None; ``reales``, los cursos reales (en
    v1 venía un solo objeto: se normaliza a una tupla de uno). Cada curso es el
    dict del fichero: ``id`` y ``secciones`` (``numero``, ``nombre``, ``id``).
    """

    pruebas: dict | None
    reales: tuple[dict, ...]

    def cursos(self, entorno: str) -> tuple[dict, ...]:
        """Los cursos de un entorno; la versión del fichero ya no se interpreta."""
        if entorno == "pruebas":
            return (self.pruebas,) if self.pruebas is not None else ()
        if entorno == "real":
            return self.reales
        return ()


def escribir_estructura(dir_tiza: str | Path, cursos: Mapping[str, Any]) -> Path:
    """Escribe ``estructura.json`` (versión 2, validada) con la fecha de ahora.

    ``cursos``: «pruebas» (un curso) y «real» (un curso o una lista). Cada curso
    lleva «id» y sus «secciones» (cada una, «numero», «nombre» e «id»). Un «real»
    con un solo curso puede venir como objeto: se escribe como lista.
    """
    datos = {
        "version": 2,
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "cursos": _normalizar_cursos(cursos),
    }
    _validar_estructura(datos)
    asegurar_directorio(Path(dir_tiza))
    return escribir_json(Path(dir_tiza) / FICHERO_ESTRUCTURA, datos)


def cargar_estructura(dir_tiza: str | Path) -> Estructura:
    """Lee ``estructura.json`` y lo devuelve validado; v1 y v2 quedan iguales.

    Un fichero que no cumple el esquema no se interpreta a medias:
    ``ESTRUCTURA_INVALIDA``.
    """
    ruta = Path(dir_tiza) / FICHERO_ESTRUCTURA
    if not ruta.is_file():
        raise ErrorEstado("ESTRUCTURA_AUSENTE")
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErrorEstado("ESTRUCTURA_ILEGIBLE") from exc
    _validar_estructura(datos)
    cursos = datos["cursos"]
    real = cursos.get("real")
    return Estructura(
        pruebas=cursos.get("pruebas"),
        reales=(real,) if isinstance(real, dict) else tuple(real or ()),
    )


def escribir_copia(dir_tiza: str | Path, datos: Mapping[str, Any]) -> Path:
    """Valida y escribe ``copia.json`` (versión 1); lo reescribe en cada importación."""
    _validar_copia(datos)
    asegurar_directorio(Path(dir_tiza))
    return escribir_json(Path(dir_tiza) / FICHERO_COPIA, datos)


def cargar_copia(dir_tiza: str | Path) -> dict:
    """Lee ``copia.json`` validado; un fichero fuera del esquema es ``COPIA_INVALIDA``.

    ``IMPORTACION_AUSENTE`` si no existe (no hay importación), ``COPIA_INVALIDA`` si existe y no es
    un fichero normal (directorio, FIFO, enlace) e ``IMPORTACION_ILEGIBLE`` si no se puede leer.
    """
    ruta = Path(dir_tiza) / FICHERO_COPIA
    try:
        modo = os.lstat(ruta).st_mode
    except FileNotFoundError:
        raise ErrorEstado("IMPORTACION_AUSENTE") from None
    except OSError as exc:
        raise ErrorEstado("IMPORTACION_ILEGIBLE") from exc
    if not stat.S_ISREG(modo):  # un directorio, una FIFO o un enlace: no es el de tiza
        raise ErrorEstado("COPIA_INVALIDA")
    try:
        datos = json.loads(leer_bytes_acotado(ruta, MAX_COPIA_JSON).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErrorEstado("IMPORTACION_ILEGIBLE") from exc
    _validar_copia(datos)
    return datos


def guardar_version_de_copia(dir_tiza: str | Path, cmid: int, html: str) -> Path:
    """Deja la versión de la copia nueva de una actividad como dato en ``copia/<cmid>.html``."""
    if isinstance(cmid, bool) or not isinstance(cmid, int) or cmid <= 0:
        raise ErrorEstado("COPIA_INVALIDA")
    directorio = asegurar_directorio(Path(dir_tiza))
    carpeta = asegurar_directorio(directorio / CARPETA_COPIA)
    return escribir_texto(carpeta / f"{cmid}.html", html)


def nombre_de_copia(curso: str, momento: datetime, repeticion: int = 0) -> str:
    """Nombre de una copia que deja ``tiza copia``: ``<curso>-<AAAAMMDD-HHMM>.mbz``.

    ``repeticion`` > 0 añade el sufijo ``-2``, ``-3``…: nunca se sobrescribe una copia.
    """
    base = f"{curso}-{momento:%Y%m%d-%H%M}"
    return f"{base}.mbz" if repeticion == 0 else f"{base}-{repeticion + 1}.mbz"


def _carpeta_de_copias(dir_tiza: str | Path) -> Path:
    """``.tiza/copias``, creada si falta; se niega si ``.tiza`` o ella son enlaces (FicheroNoSeguro)."""
    directorio = asegurar_directorio(Path(dir_tiza))
    return asegurar_directorio(directorio / CARPETA_COPIAS)


def _quitar_temporales_viejos(carpeta: Path) -> None:
    """Borra los ``.descarga-*.tmp`` de hace más de un día (una descarga que murió a medias)."""
    limite = time.time() - EDAD_MAXIMA_TEMPORAL
    for ruta in carpeta.glob(".descarga-*.tmp"):
        try:
            info = ruta.lstat()
            if stat.S_ISREG(info.st_mode) and info.st_mtime < limite:
                ruta.unlink()
        except OSError:
            pass


def temporal_de_copia(dir_tiza: str | Path) -> Path:
    """Un fichero temporal nuevo (``x``: nunca uno que ya exista) donde descargar la copia.

    Antes borra los temporales de descargas que murieron hace más de un día.
    """
    carpeta = _carpeta_de_copias(dir_tiza)
    _quitar_temporales_viejos(carpeta)
    temporal = carpeta / f".descarga-{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporal, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    return temporal


def reservar_copia(dir_tiza: str | Path, curso: str, momento: datetime, temporal: Path) -> Path:
    """Da a ``temporal`` su nombre definitivo sin sobrescribir nada y devuelve la ruta.

    Reserva el nombre con un fichero vacío creado con ``x`` y lo sustituye por la copia; si ya
    hay uno con ese nombre (una copia anterior, o un fichero del docente), prueba el siguiente
    sufijo. ``FicheroNoSeguro`` si no hay sitio entre cien nombres.
    """
    carpeta = _carpeta_de_copias(dir_tiza)
    for repeticion in range(100):
        destino = carpeta / nombre_de_copia(curso, momento, repeticion)
        try:
            descriptor = os.open(destino, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        os.close(descriptor)
        try:
            os.replace(temporal, destino)
        except OSError:
            try:
                destino.unlink()
            except OSError:
                pass
            raise
        return destino
    raise FicheroNoSeguro("no_regular")


def _validar_copia(datos: Any) -> None:
    # Import diferido: informe importa este módulo por el nombre de su fichero.
    from .informe import ErrorInforme, validar_copia

    try:
        validar_copia(datos)
    except ErrorInforme as exc:
        raise ErrorEstado("COPIA_INVALIDA") from exc


def _normalizar_cursos(cursos: Mapping[str, Any]) -> dict:
    normalizados = dict(cursos)
    if isinstance(normalizados.get("real"), dict):
        normalizados["real"] = [normalizados["real"]]
    return normalizados


def _validar_estructura(datos: Any) -> None:
    # Import diferido: informe importa este módulo por el nombre de su fichero.
    from .informe import ErrorInforme, validar_estructura

    try:
        validar_estructura(datos)
    except ErrorInforme as exc:
        raise ErrorEstado("ESTRUCTURA_INVALIDA") from exc


@dataclass(frozen=True)
class Verificado:
    """Un documento verificado en pruebas: su nombre y cmid en el aula, y cuándo.

    Fecha en ISO 8601 UTC; el disco siempre la lleva y el registro en memoria usa
    la misma dataclass. Al leer un fichero antiguo o a mano puede faltar (None).
    """

    nombre: str
    cmid: int
    fecha: str | None = None


def cargar_verificados(dir_tiza: str | Path) -> dict[str, Verificado]:
    """Mapa de hashes verificados; un fichero corrupto es un mapa vacío.

    Una entrada que no encaja (nombre o cmid con otra forma) no cuenta como
    verificada: la puerta de real vuelve a pedir el paso por pruebas, que es el
    lado seguro.
    """
    ruta = Path(dir_tiza) / FICHERO_VERIFICADOS
    if not ruta.is_file():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        ficheros = datos.get("ficheros")
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    if not isinstance(ficheros, dict):
        return {}
    registro: dict[str, Verificado] = {}
    for hash_doc, entrada in ficheros.items():
        verificado = _verificado_de(entrada)
        if verificado is not None:
            registro[hash_doc] = verificado
    return registro


def _verificado_de(entrada: Any) -> Verificado | None:
    if not isinstance(entrada, dict):
        return None
    nombre, cmid, fecha = entrada.get("nombre"), entrada.get("cmid"), entrada.get("fecha")
    if not isinstance(nombre, str) or isinstance(cmid, bool) or not isinstance(cmid, int):
        return None
    if fecha is not None and not isinstance(fecha, str):
        return None
    return Verificado(nombre=nombre, cmid=cmid, fecha=fecha)


def anotar_verificado(
    registro: dict[str, Verificado], hash_doc: str, nombre: str, cmid: int
) -> None:
    """Añade al registro en memoria un documento verificado en pruebas.

    Usa la misma dataclass que el disco; la fecha la pone aquí.
    """
    registro[hash_doc] = Verificado(nombre, cmid, datetime.now(UTC).isoformat(timespec="seconds"))


def guardar_verificado(dir_tiza: str | Path, hash_doc: str, nombre: str, cmid: int) -> Path:
    directorio = asegurar_directorio(Path(dir_tiza))
    registro = cargar_verificados(directorio)
    anotar_verificado(registro, hash_doc, nombre, cmid)
    return escribir_json(
        directorio / FICHERO_VERIFICADOS,
        {
            "version": 1,
            "ficheros": {clave: dataclasses.asdict(item) for clave, item in registro.items()},
        },
    )


def comprobar_puerta_real(
    verificados: Mapping[str, Verificado], pares: list[tuple[str, str]]
) -> list[str]:
    """Nombres de los ficheros sin verificación previa en pruebas."""
    return [nombre for nombre, hash_doc in pares if hash_doc not in verificados]


# Misma clase de caracteres que mensajes.texto_seguro, contenido._CONTROL e
# informe._TEXTO_PROHIBIDO; mantén las cuatro sincronizadas.
_NO_IMPRIMIBLE = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def nombre_de_seccion(texto: str) -> str:
    """Nombre de sección apto para el esquema cerrado: sin < > ni controles."""
    limpio = _NO_IMPRIMIBLE.sub(" ", texto).replace("<", "‹").replace(">", "›")
    return " ".join(limpio.split())[:255]


def buscar_seccion(secciones: list[dict], clave: int | str) -> dict | None:
    """Sección por número (entero) o por nombre (texto, sin distinguir mayúsculas)."""
    for seccion in secciones:
        if not isinstance(seccion, dict):
            continue
        if isinstance(clave, int):
            if seccion.get("numero") == clave:
                return seccion
        # El nombre ya se saneó al construir la estructura (nombre_de_seccion);
        # aquí se aplica la misma normalización para que la comparación coincida.
        elif (
            nombre_de_seccion(seccion.get("nombre") or "").casefold()
            == nombre_de_seccion(clave).casefold()
        ):
            return seccion
    return None


def ruta_lectura(carpeta: str | Path, fichero: str | Path) -> Path:
    """Dónde queda la lectura de ``fichero``: ``.tiza/lecturas/<ruta-saneada>.txt``.

    Se nombra con la ruta del fichero relativa a ``carpeta``, con los separadores cambiados
    por ``__`` (``1DAM/Prog.docx`` da ``1DAM__Prog.docx.txt``); un fichero en la raíz
    conserva su nombre. La extensión cuenta (``a.docx`` y ``a.pdf`` no se pisan) y se quitan
    caracteres de control y ``..``. Un fichero fuera de ``carpeta`` solo aporta su nombre.
    """
    ruta = Path(str(fichero).replace("\\", "/"))
    try:
        partes = ruta.resolve().relative_to(Path(carpeta).resolve()).parts
    except (ValueError, OSError, RuntimeError):
        partes = ()
    if not partes:
        partes = (ruta.name,)

    def sanear(parte: str) -> str:
        parte = "".join(c for c in parte if c.isprintable() and c not in '<>:"/\\|?*')
        return parte.replace("..", "_").strip(". ")

    nombre = "__".join(p for p in map(sanear, partes) if p) or "lectura"
    return Path(carpeta) / rutas.CARPETA_TRABAJO / CARPETA_LECTURAS / f"{nombre}.txt"
