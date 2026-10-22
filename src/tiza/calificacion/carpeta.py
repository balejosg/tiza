"""Las actividades de la carpeta de la asignatura para el calificador (offline).

``tiza calificador`` lee todos los ficheros de tiza de la carpeta, no solo los que nombra la
petición: un curso pasa de los 20 ficheros que admite una petición y el calificador necesita ver
todas las actividades que cuentan para repartir los pesos.
"""

from __future__ import annotations

import os
from pathlib import Path

from tiza import contenido
from tiza.calificacion.deseado import deseado
from tiza.calificacion.esquema import ErrorCalificacion, Esquema, cargar_esquema
from tiza.contenido import Documento, ErrorContenido
from tiza.ficheros import FicheroNoSeguro, leer_bytes_acotado

__all__ = ["MAX_FICHEROS", "cargar_calificacion", "documentos_de_la_carpeta"]

MAX_FICHEROS = 500  # ficheros .md y .html que se miran como mucho
_EXTENSIONES = {".md", ".html", ".htm"}


def _menciona_evalua(ruta: Path) -> bool:
    """Si un fichero que no carga habla de «evalua»: entonces no se puede ignorar sin más."""
    try:
        return b"evalua" in leer_bytes_acotado(ruta, contenido.MAX_DOCUMENTO_BYTES)
    except (OSError, FicheroNoSeguro):
        return False


def documentos_de_la_carpeta(base: Path) -> list[Documento]:
    """Los ficheros de tiza de la carpeta (y sus subcarpetas, salvo las ocultas), por ruta.

    Un fichero que no es de tiza (un ``README.md``, unos apuntes) se ignora. Uno que no carga pero
    menciona ``evalua`` no se ignora: dejar fuera una actividad del cálculo cambiaría la nota
    final sin avisar, así que el comando falla con el código de su error, antes de tocar el aula.
    ``CARPETA_DEMASIADO_GRANDE`` si hay más de ``MAX_FICHEROS`` candidatos.
    """
    raiz = Path(base).resolve()
    candidatos: list[Path] = []
    for directorio, subcarpetas, ficheros in os.walk(raiz, followlinks=False):
        subcarpetas[:] = sorted(s for s in subcarpetas if not s.startswith("."))
        for nombre in sorted(ficheros):
            if nombre.startswith(".") or Path(nombre).suffix.lower() not in _EXTENSIONES:
                continue
            candidatos.append(Path(directorio) / nombre)
    if len(candidatos) > MAX_FICHEROS:
        raise ErrorCalificacion(
            "CARPETA_DEMASIADO_GRANDE",
            f"hay {len(candidatos)} ficheros .md o .html y se miran {MAX_FICHEROS} como mucho",
        )
    documentos: list[Documento] = []
    for ruta in sorted(candidatos, key=lambda r: r.relative_to(raiz).as_posix()):
        try:
            documentos.append(contenido.cargar(ruta, raiz=raiz))
        except ErrorContenido as exc:
            if _menciona_evalua(ruta):
                nombre = ruta.relative_to(raiz).as_posix()
                raise ErrorCalificacion(exc.codigo, f"{nombre}: {exc.detalle}") from None
    return documentos


def cargar_calificacion(esquema: Path, base: Path) -> tuple[Esquema, list[Documento]]:
    """El esquema y las actividades de la carpeta, ya comprobados entre sí.

    Todo lo que se puede saber sin mirar el aula: la forma del esquema, los ``evalua`` de las
    actividades y que sus pesos cuadren. Lanza ``ErrorCalificacion`` con su línea o ruta.
    """
    raiz = Path(base).resolve()
    datos = cargar_esquema(Path(esquema), raiz)
    documentos = documentos_de_la_carpeta(raiz)
    deseado(
        datos, documentos, False, raiz
    )  # solo valida: si un calificador anterior cambia algo, no es un error
    return datos, documentos
