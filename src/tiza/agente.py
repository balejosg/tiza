"""API de tiza para agentes embebidos: lo que la CLI ofrece al agente, sin consola.

Todo lo que devuelve pasa por el esquema cerrado
de :mod:`tiza.informe` o son textos propios de tiza; nunca texto de Moodle.
Nada aquí pide contraseñas ni se conecta al aula: lo que necesita el aula va
por el buzón a la sesión del docente.
"""

from __future__ import annotations

import textwrap
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from . import buzon, contenido, informe, rutas
from .contenido import Documento, ErrorContenido, hash_documento
from .publicar import ErrorPublicacion, buscar_seccion, cargar_estructura

__all__ = [
    "Comprobacion",
    "FicheroComprobado",
    "comprobar",
    "estado_sesion",
    "estructura",
    "formato_documento",
    "peticion_estructura",
    "peticion_publicar",
    "pista_worktree",
    "publicar",
]


@dataclass(frozen=True)
class FicheroComprobado:
    """Resultado de comprobar un fichero, con textos de tiza (nunca de Moodle)."""

    fichero: str
    codigo: str | None = None  # código de error; None si pasa
    detalle: str = ""  # explicación del error para quien corrige el fichero
    vista_previa: Path | None = None
    seccion_nueva: str | None = None  # sección por nombre que se creará (oculta) al publicar


@dataclass(frozen=True)
class Comprobacion:
    informe: dict  # esquema cerrado, como .tiza/informe.json
    ficheros: tuple[FicheroComprobado, ...]


def comprobar(carpeta: str | Path, ficheros: Sequence[str]) -> Comprobacion:
    """Valida los ``.md`` o ``.html`` sin red y genera sus vistas previas en ``.tiza/preview``.

    Comprueba también la sección contra ``.tiza/estructura.json`` si existe: en el curso
    de pruebas o, si no hay, en el real.
    Devuelve el informe validado; no lo escribe en disco.
    """
    base = Path(carpeta)
    raiz = base.resolve()
    dir_tiza = base / rutas.CARPETA_TRABAJO
    errores: list[str] = []
    pasos: list[dict] = []
    datos: list[dict] = []
    resultados: list[FicheroComprobado] = []
    try:
        estructura = cargar_estructura(dir_tiza)
    except ErrorPublicacion as exc:
        estructura = None
        errores.append(exc.codigo)
        pasos.append({"codigo": "ESTRUCTURA", "resultado": "fallo", "detalle": exc.codigo})
    else:
        pasos.append({"codigo": "ESTRUCTURA", "resultado": "ok", "detalle": None})

    for nombre in ficheros:
        ruta = base / nombre
        try:
            doc = contenido.cargar(ruta, raiz=raiz)
            vista = contenido.previsualizar(doc, dir_tiza)
        except ErrorContenido as exc:
            errores.append(exc.codigo)
            pasos.append(_paso_fallido(ruta.name, exc.codigo))
            resultados.append(FicheroComprobado(ruta.name, exc.codigo, exc.detalle))
            continue
        curso = _curso_a_comprobar(estructura)
        seccion = buscar_seccion(curso[1], doc.seccion) if curso is not None else None
        if curso is not None and seccion is None and isinstance(doc.seccion, str):
            pasos.append({"codigo": "COMPROBAR", "resultado": "ok", "detalle": ruta.name})
            datos.append(_fichero(doc, doc.seccion))
            resultados.append(
                FicheroComprobado(ruta.name, vista_previa=vista, seccion_nueva=doc.seccion)
            )
            continue
        pista = (
            _pista_de_id(estructura, doc)
            if estructura is not None and curso is not None and seccion is None
            else None
        )
        if pista is not None:
            errores.append("SECCION_ES_ID")
            pasos.append(_paso_fallido(ruta.name, "SECCION_ES_ID"))
            resultados.append(FicheroComprobado(ruta.name, "SECCION_ES_ID", pista))
        elif curso is not None and seccion is None:
            errores.append("SECCION_AUSENTE")
            pasos.append(_paso_fallido(ruta.name, "SECCION_AUSENTE"))
            detalle = (
                f"no existe la sección {doc.seccion} en el curso de {curso[0]} "
                f"({rutas.CARPETA_TRABAJO}/estructura.json)"
            )
            resultados.append(FicheroComprobado(ruta.name, "SECCION_AUSENTE", detalle))
        else:
            pasos.append({"codigo": "COMPROBAR", "resultado": "ok", "detalle": ruta.name})
            resultados.append(FicheroComprobado(ruta.name, vista_previa=vista))
        datos.append(_fichero(doc, seccion["nombre"] if seccion else None))

    documento = informe.crear("comprobar", "error" if errores else "ok", pasos, datos, errores)
    informe.validar(documento)
    return Comprobacion(documento, tuple(resultados))


def _paso_fallido(fichero: str, codigo: str) -> dict:
    return {"codigo": "COMPROBAR", "resultado": "fallo", "detalle": f"{fichero}: {codigo}"}


def _fichero(doc: Documento, seccion: str | None) -> dict:
    return {
        "nombre": doc.ruta.name,
        "tipo": doc.tipo,
        "cmid": None,
        "accion": None,
        "oculto": None,
        "url": None,
        "seccion": seccion,
        "hash": hash_documento(doc),
    }


def _curso_a_comprobar(estructura: dict | None) -> tuple[str, list] | None:
    """El curso donde se publicará: el de pruebas o, si no hay, el real."""
    if not estructura:
        return None
    for entorno in ("pruebas", "real"):
        try:
            secciones = estructura["cursos"][entorno]["secciones"]
        except (KeyError, TypeError):
            continue
        if isinstance(secciones, list):
            return entorno, secciones
    return None


def _pista_de_id(estructura: dict, doc: Documento) -> str | None:
    """Si ``seccion`` es el id de la URL del aula, el texto que dice qué número poner."""
    for entorno, curso in (estructura.get("cursos") or {}).items():
        for seccion in (curso or {}).get("secciones") or []:
            if isinstance(seccion, dict) and seccion.get("id") == doc.seccion:
                return (
                    f"{doc.seccion} es el id de la sección «{seccion.get('nombre')}» del curso "
                    f"de {entorno}; escribe «seccion: {seccion.get('numero')}»."
                )
    return None


def peticion_publicar(ficheros: Sequence[str], entorno: str, visible: bool | None = None) -> dict:
    """Petición de publicar para el buzón (``visible=None``: lo que exista conserva)."""
    return {
        "version": buzon.VERSION_PROTOCOLO,
        "id": uuid.uuid4().hex,
        "comando": "publicar",
        "ficheros": list(ficheros),
        "entorno": entorno,
        "visible": visible,
    }


def peticion_estructura() -> dict:
    return {
        "version": buzon.VERSION_PROTOCOLO,
        "id": uuid.uuid4().hex,
        "comando": "estructura",
        "ficheros": [],
        "entorno": None,
        "visible": None,
    }


def publicar(
    carpeta: str | Path,
    ficheros: Sequence[str],
    entorno: str,
    *,
    visible: bool | None = None,
    espera: float = buzon.ESPERA_POR_DEFECTO,
    cancelar: threading.Event | None = None,
) -> dict:
    """Pide a la sesión del docente que publique; en real, el docente confirma."""
    return _enviar(carpeta, peticion_publicar(ficheros, entorno, visible), espera, cancelar)


def estructura(
    carpeta: str | Path,
    *,
    espera: float = buzon.ESPERA_POR_DEFECTO,
    cancelar: threading.Event | None = None,
) -> dict:
    """Pide a la sesión del docente que actualice ``.tiza/estructura.json``."""
    return _enviar(carpeta, peticion_estructura(), espera, cancelar)


def estado_sesion(carpeta: str | Path) -> dict:
    """Si hay sesión del docente en la carpeta y hasta cuándo, para enseñarlo."""
    dir_tiza = Path(carpeta) / rutas.CARPETA_TRABAJO
    caduca = buzon.caducidad(dir_tiza)
    if caduca is not None:
        return {"activa": True, "caduca": caduca.isoformat(), "compatible": True}
    if buzon.sesion_incompatible(dir_tiza) is not None:
        return {"activa": True, "caduca": None, "compatible": False}
    return {"activa": False, "caduca": None, "compatible": True}


class _Cancelada(Exception):
    """El docente dejó de esperar."""


def pista_worktree(carpeta: str | Path) -> str | None:
    """Pista cuando la carpeta es un worktree enlazado de git (``.git`` es un fichero).

    En un worktree, el buzón de la asignatura no existe: el agente debe trabajar
    desde la carpeta de la asignatura, donde el docente abrió la sesión.
    """
    if (Path(carpeta) / ".git").is_file():
        return (
            "estás en un worktree de git; abre la sesión del agente en la carpeta de la asignatura"
        )
    return None


def _enviar(
    carpeta: str | Path, peticion: dict, espera: float, cancelar: threading.Event | None
) -> dict:
    dir_tiza = Path(carpeta) / rutas.CARPETA_TRABAJO
    comando, entorno = peticion["comando"], peticion["entorno"]
    if not buzon.sesion_activa(dir_tiza):
        codigo = "SESION_INCOMPATIBLE" if buzon.sesion_incompatible(dir_tiza) else "SIN_SESION"
        pasos: list[dict] = []
        if codigo == "SIN_SESION":
            pista = pista_worktree(carpeta)
            if pista is not None:
                pasos.append({"codigo": "SIN_SESION", "resultado": "fallo", "detalle": pista})
        return informe.crear(comando, "error", pasos, [], [codigo], entorno)

    def dormir(segundos: float) -> None:
        if cancelar is None:
            time.sleep(segundos)
        elif cancelar.wait(segundos):
            raise _Cancelada

    try:
        return buzon.enviar(dir_tiza, peticion, espera, dormir=dormir)
    except _Cancelada:  # enviar ya ha retirado la petición del buzón
        return informe.crear(comando, "abortado", [], [], ["ABORTADO"], entorno)
    except buzon.ErrorBuzon as exc:
        return informe.crear(comando, "error", [], [], [exc.codigo], entorno)


_INICIO_FORMATO = "<!-- formato:inicio -->"
_FIN_FORMATO = "<!-- formato:fin -->"


def formato_documento() -> str:
    """Formato de los ficheros (``.md`` o ``.html``) de tiza: frontmatter, fechas, recursos y filtro.

    Sale de la skill (``skill/tiza/SKILL.md``), que es la única fuente:
    lo leen los agentes con la skill instalada y la app con su asistente.
    """
    ruta = resources.files("tiza") / "skill" / "tiza" / "SKILL.md"
    texto = ruta.read_text(encoding="utf-8")
    inicio = texto.index(_INICIO_FORMATO) + len(_INICIO_FORMATO)
    fin = texto.index(_FIN_FORMATO, inicio)
    return textwrap.dedent(texto[inicio:fin]).strip()
