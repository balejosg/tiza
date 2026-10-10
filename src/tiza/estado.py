"""Estado de trabajo de la asignatura: lo que tiza guarda en ``.tiza/``.

Único dueño de los nombres de los ficheros del estado, de sus formatos y de su
validación al leer: la estructura de secciones (``estructura.json``), el registro
de lo verificado en pruebas (``verificados.json``), las vistas previas
(``preview/``) y el informe (``informe.json``).

Aquí no se habla con el aula ni se importa python-moodle: el lado del agente
(``tiza comprobar``) puede usar este módulo sin cargar nada del aula. La
estructura se valida al escribir y al leer con el esquema cerrado de
:mod:`tiza.informe`.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ficheros import asegurar_directorio, escribir_json

__all__ = [
    "CARPETA_PREVIEW",
    "ErrorEstado",
    "Estructura",
    "FICHERO_ESTRUCTURA",
    "FICHERO_INFORME",
    "FICHERO_VERIFICADOS",
    "Verificado",
    "anotar_verificado",
    "buscar_seccion",
    "cargar_estructura",
    "cargar_verificados",
    "comprobar_puerta_real",
    "escribir_estructura",
    "guardar_verificado",
    "nombre_de_seccion",
]

FICHERO_INFORME = "informe.json"
FICHERO_ESTRUCTURA = "estructura.json"
FICHERO_VERIFICADOS = "verificados.json"
CARPETA_PREVIEW = "preview"  # las vistas previas clicables dentro de la carpeta de trabajo


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
