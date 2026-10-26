"""Las carpetas de asignatura recientes del panel: hasta ``MAXIMO``, la última primero.

Viven en ``panel-recientes.json``, junto a la configuración global. Solo guardan rutas
absolutas de carpetas que existen. Es una comodidad, no un dato del que dependa nada: un
fichero roto, ajeno o ilegible se trata como vacío y un fallo al escribir se ignora.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from .. import config, ficheros, mensajes

__all__ = [
    "MAXIMO",
    "NOMBRE",
    "anotar",
    "carpeta_valida",
    "etiquetas",
    "leer",
    "nombre_visible",
    "quitar",
    "ruta",
]

MAXIMO = 8
NOMBRE = "panel-recientes.json"
MAX_FICHERO = 64 * 1024
MAX_RUTA = 1024
VERSION = 1


def ruta() -> Path:
    return config.directorio_global() / NOMBRE


def carpeta_valida(texto: object) -> Path | None:
    """La carpeta de ``texto`` si es una ruta absoluta que existe; None si no."""
    if not isinstance(texto, str) or not 0 < len(texto) <= MAX_RUTA or "\x00" in texto:
        return None
    carpeta = Path(texto)
    try:
        if not carpeta.is_absolute() or not carpeta.is_dir():
            return None
    except (OSError, ValueError):
        return None
    return carpeta


def _sin_repetir(carpetas: list[Path]) -> list[Path]:
    vistas: list[Path] = []
    for carpeta in carpetas:
        if carpeta not in vistas:
            vistas.append(carpeta)
    return vistas[:MAXIMO]


def leer() -> list[Path]:
    """Las carpetas recientes que siguen existiendo, la última usada primero."""
    try:
        datos = json.loads(ficheros.leer_bytes_acotado(ruta(), MAX_FICHERO).decode("utf-8"))
    except (OSError, ValueError, RecursionError):  # UnicodeDecodeError es un ValueError
        return []
    if not isinstance(datos, dict) or set(datos) != {"version", "carpetas"}:
        return []
    if datos["version"] != VERSION or not isinstance(datos["carpetas"], list):
        return []
    validas = (carpeta_valida(texto) for texto in datos["carpetas"])
    return _sin_repetir([c for c in validas if c is not None])


def _guardar(lista: list[Path]) -> None:
    try:
        ficheros.escribir_json(ruta(), {"version": VERSION, "carpetas": [str(c) for c in lista]})
    except OSError:
        pass


def anotar(carpeta: str | Path) -> list[Path]:
    """Pone ``carpeta`` la primera (sin repetirla) y devuelve la lista guardada.

    Una ruta que no es una carpeta absoluta existente no se anota. Si no se puede escribir
    el fichero, se devuelve la lista igualmente: las recientes no son imprescindibles.
    """
    nueva = carpeta_valida(str(carpeta))
    actuales = leer()
    if nueva is None:
        return actuales
    lista = _sin_repetir([nueva, *actuales])
    _guardar(lista)
    return lista


def quitar(carpeta: str | Path) -> list[Path]:
    """Quita ``carpeta`` de las recientes (si está) y devuelve la lista guardada."""
    if not isinstance(carpeta, (str, Path)) or "\x00" in str(carpeta):
        return leer()
    objetivo = Path(carpeta)
    actuales = leer()
    lista = [c for c in actuales if c != objetivo]
    if lista != actuales:
        _guardar(lista)
    return lista


def nombre_visible(carpeta: str | Path) -> str:
    """Cómo se enseña la carpeta: su nombre y el de su carpeta madre, ya saneados."""
    carpeta = Path(carpeta)
    nombre = carpeta.name
    if not nombre:  # la raíz de una unidad
        return mensajes.texto_seguro(str(carpeta), 80)
    padre = carpeta.parent.name
    texto = f"{padre} / {nombre}" if padre else nombre
    return mensajes.texto_seguro(texto, 80)


def _pista(carpeta: Path) -> str:
    """La carpeta madre corta, para distinguir dos recientes con el mismo nombre visible."""
    padre = carpeta.parent
    abuelo = padre.parent
    if padre.name and abuelo.name:
        texto = f"en {abuelo.name}{os.sep}{padre.name}"
    elif padre.name:
        texto = f"en {padre.name}"
    else:
        return ""
    return mensajes.texto_seguro(texto, 60)


def etiquetas(carpetas: Sequence[str | Path]) -> list[tuple[str, str]]:
    """(nombre visible, pista) de cada reciente; la pista solo si el nombre se repite."""
    rutas = [Path(c) for c in carpetas]
    nombres = [nombre_visible(c) for c in rutas]
    repetidos = {n for n in nombres if nombres.count(n) > 1}
    return [(n, _pista(c) if n in repetidos else "") for n, c in zip(nombres, rutas, strict=True)]
