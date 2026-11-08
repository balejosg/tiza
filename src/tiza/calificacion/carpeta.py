"""Las actividades de la carpeta de la asignatura para el calificador (offline).

``tiza calificador`` lee todos los ficheros de tiza de la carpeta, no solo los que nombra la
petición: un curso pasa de los 20 ficheros que admite una petición y el calificador necesita ver
todas las actividades que cuentan para repartir los pesos.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from tiza import contenido, tipos
from tiza.calificacion.deseado import deseado
from tiza.calificacion.esquema import ErrorCalificacion, Esquema, cargar_esquema
from tiza.contenido import Documento, ErrorContenido
from tiza.ficheros import FicheroNoSeguro, leer_bytes_acotado

__all__ = [
    "MAX_FICHEROS",
    "actividades_sin_evalua",
    "cargar_calificacion",
    "documentos_de_la_carpeta",
]

MAX_FICHEROS = 500  # ficheros .md y .html que se miran como mucho
_EXTENSIONES = {".md", ".html", ".htm"}


_CAMPOS_DE_CALIFICACION = re.compile(r"^(?:evalua|evidencia|rubrica|recupera)\s*:", re.MULTILINE)
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


def _menciona_calificacion(ruta: Path) -> bool:
    """Si el frontmatter de un fichero que no carga lo hace del calificador.

    ``evalua``, ``evidencia``, ``rubrica`` y ``recupera`` cambian la nota o el calificador: si el
    fichero no carga, no se puede ignorar sin más. Se mira solo la cabecera, no el cuerpo del
    documento.
    """
    try:
        texto = leer_bytes_acotado(ruta, contenido.MAX_DOCUMENTO_BYTES).decode("utf-8-sig")
    except (OSError, FicheroNoSeguro, UnicodeDecodeError):
        return False
    coincidencia = _FRONTMATTER.match(texto)
    return bool(coincidencia and _CAMPOS_DE_CALIFICACION.search(coincidencia.group(1)))


def documentos_de_la_carpeta(base: Path) -> list[Documento]:
    """Los ficheros de tiza de la carpeta (y sus subcarpetas, salvo las ocultas), por ruta.

    Un fichero que no es de tiza (un ``README.md``, unos apuntes) se ignora. Uno que no carga pero
    cuyo frontmatter menciona ``evalua``, ``evidencia``, ``rubrica`` o ``recupera`` no se ignora:
    dejar fuera una actividad del cálculo cambiaría la nota final sin avisar, así que el comando
    falla con el código de su error, antes de tocar el aula. ``CARPETA_DEMASIADO_GRANDE`` si hay
    más de ``MAX_FICHEROS`` candidatos.
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
            if _menciona_calificacion(ruta):
                nombre = ruta.relative_to(raiz).as_posix()
                raise ErrorCalificacion(exc.codigo, f"{nombre}: {exc.detalle}") from None
    return documentos


def cargar_calificacion(esquema: Path, base: Path) -> tuple[Esquema, list[Documento]]:
    """El esquema y las actividades de la carpeta, ya comprobados entre sí.

    Todo lo que se puede saber sin mirar el aula: la forma del esquema, los ``evalua`` y
    ``recupera`` de las actividades y que todo cuadre con el esquema. Lanza
    ``ErrorCalificacion`` con su línea o ruta.
    """
    raiz = Path(base).resolve()
    datos = cargar_esquema(Path(esquema), raiz)
    documentos = documentos_de_la_carpeta(raiz)
    if any(documento.evidencia == "resultados" for documento in documentos):
        # La escala de los resultados solo importa cuando alguna tarea los pide.
        datos = cargar_esquema(Path(esquema), raiz, resultados=True)
    deseado(
        datos, documentos, False, raiz
    )  # solo valida: si un calificador anterior cambia algo, no es un error
    return datos, documentos


def actividades_sin_evalua(
    esquema: Esquema, documentos: list[Documento], carpeta: Path
) -> list[str]:
    """Rutas relativas de las actividades calificables sin ``evalua``, solo en ESO.

    Son las tareas, los cuestionarios y los H5P que aún no cuentan en el calificador. Las
    páginas y las etiquetas no tienen nota y no salen. El resultado va ordenado.
    """
    if esquema.etapa != "eso":
        return []
    raiz = Path(carpeta).resolve()
    rutas: list[str] = []
    for documento in documentos:
        if documento.evalua is not None or not tipos.obtener(documento.tipo).calificable:
            continue
        try:
            relativa = documento.ruta.resolve().relative_to(raiz)
        except (ValueError, OSError):
            relativa = documento.ruta
        rutas.append(relativa.as_posix())
    return sorted(rutas)
