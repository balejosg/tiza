"""Referencias entre piezas: citas «…» que se parecen al ``nombre`` de otra sin coincidir.

Offline y puro salvo la lectura de la carpeta. Las piezas se citan por su ``nombre`` exacto
entre comillas latinas («2. Comparar fracciones»). Al renombrar una, las citas que la nombraban
quedan rotas. ``tiza comprobar`` lo avisa con el paso ``REFERENCIA_ROTA``, sin bloquear: una
cita parecida puede ser a propósito.
"""

from __future__ import annotations

import os
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from tiza import contenido
from tiza.ficheros import FicheroNoSeguro, leer_bytes_acotado

__all__ = ["MAX_FICHEROS", "PARECIDO", "nombres_de_la_carpeta", "rotas"]

MAX_FICHEROS = 500  # ficheros .md y .html que se miran como mucho
PARECIDO = 0.8  # proporción de SequenceMatcher a partir de la que una cita apunta a un nombre
_EXTENSIONES = {".md", ".html", ".htm"}
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
# Lo mismo que no admite el informe (informe._TEXTO_PROHIBIDO) y saltos de línea.
_CITA = re.compile(
    r"«([^«»<>\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069]{4,120})»"
)


def _normalizar(texto: str) -> str:
    """Sin mayúsculas, tildes ni espacios repetidos, para comparar citas con nombres."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return " ".join(sin_tildes.casefold().split())


def _nombre(ruta: Path) -> str | None:
    """El ``nombre`` del frontmatter de un fichero de tiza; None si no lo es o no se lee."""
    try:
        texto = leer_bytes_acotado(ruta, contenido.MAX_DOCUMENTO_BYTES).decode("utf-8-sig")
    except (OSError, FicheroNoSeguro, UnicodeDecodeError):
        return None
    cabecera = _FRONTMATTER.match(texto)
    if cabecera is None:
        return None
    try:
        datos = yaml.safe_load(cabecera.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(datos, dict) or not isinstance(datos.get("tipo"), str):
        return None
    nombre = datos.get("nombre")
    return nombre.strip() if isinstance(nombre, str) and nombre.strip() else None


def nombres_de_la_carpeta(base: Path) -> set[str]:
    """Los ``nombre`` de los ficheros de tiza de la carpeta y sus subcarpetas no ocultas.

    Mira como mucho ``MAX_FICHEROS``: en una carpeta mayor, avisa de menos, nunca falla.
    """
    nombres: set[str] = set()
    vistos = 0
    for directorio, subcarpetas, ficheros in os.walk(Path(base), followlinks=False):
        subcarpetas[:] = sorted(s for s in subcarpetas if not s.startswith("."))
        for fichero in sorted(ficheros):
            if fichero.startswith(".") or Path(fichero).suffix.lower() not in _EXTENSIONES:
                continue
            vistos += 1
            if vistos > MAX_FICHEROS:
                return nombres
            nombre = _nombre(Path(directorio) / fichero)
            if nombre is not None:
                nombres.add(nombre)
    return nombres


def rotas(texto: str, nombres: set[str]) -> list[tuple[str, str]]:
    """Pares (cita, nombre) de las citas «…» que se parecen a un nombre sin ser ninguno.

    Una cita idéntica a un nombre está bien. Si se parece a varios, gana el más parecido.
    Cada cita sale una vez, en el orden del texto.
    """
    if not nombres:
        return []
    normalizados = [(_normalizar(nombre), nombre) for nombre in sorted(nombres)]
    resultado: list[tuple[str, str]] = []
    vistas: set[str] = set()
    for coincidencia in _CITA.finditer(texto):
        cita = coincidencia.group(1).strip()
        if cita in nombres or cita in vistas:
            continue
        vistas.add(cita)
        clave = _normalizar(cita)
        parecido, nombre = max(
            (SequenceMatcher(None, clave, normal).ratio(), original)
            for normal, original in normalizados
        )
        if parecido >= PARECIDO:
            resultado.append((cita, nombre))
    return resultado
