"""Estado de trabajo de la asignatura: lo que tiza guarda en ``.tiza/``.

Único dueño de los nombres de los ficheros del estado, de sus formatos y de su
validación al leer: la estructura de secciones (``estructura.json``), el registro
de lo verificado en pruebas (``verificados.json``), las vistas previas
(``preview/``), el informe (``informe.json``) y la importación de una copia de
seguridad (``copia.json``, ``copia/<cmid>.html`` y ``copias/``) y las huellas de lo que montó
tiza en el calificador (``calificador.json``) y lo que publicó en cada curso
(``publicados.json``).

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
import unicodedata
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
    "FICHERO_CALIFICADOR",
    "FICHERO_COPIA",
    "FICHERO_ESTRUCTURA",
    "FICHERO_INFORME",
    "FICHERO_PUBLICADOS",
    "FICHERO_VERIFICADOS",
    "AVISO_CAMBIADA",
    "MARCA_ILEGIBLE",
    "Publicado",
    "Verificado",
    "anotar_verificado",
    "buscar_seccion",
    "cargar_copia",
    "cargar_publicados",
    "cargar_estructura",
    "cargar_huellas",
    "cargar_verificados",
    "comprobar_puerta_real",
    "escribir_copia",
    "escribir_estructura",
    "fichero_de_cmid",
    "guardar_huella_de_copia",
    "guardar_huellas",
    "guardar_publicado",
    "guardar_verificado",
    "guardar_version_de_copia",
    "huellas_de_copia",
    "marcas_de_copia",
    "nombre_de_copia",
    "nombre_de_seccion",
    "olvidar_publicado",
    "quitar_aviso_cambiada",
    "reservar_copia",
    "ruta_lectura",
    "ruta_publicada_valida",
    "temporal_de_copia",
]

MAX_COPIA_JSON = 16 * 1024 * 1024  # copia.json, al leerlo
EDAD_MAXIMA_TEMPORAL = 24 * 60 * 60  # segundos que dura el temporal de una descarga
FICHERO_INFORME = "informe.json"
FICHERO_ESTRUCTURA = "estructura.json"
FICHERO_VERIFICADOS = "verificados.json"
FICHERO_PUBLICADOS = "publicados.json"  # lo que tiza publicó en cada curso: ruta -> actividad
MAX_PUBLICADOS_JSON = 16 * 1024 * 1024  # publicados.json, al leerlo
CARPETA_PREVIEW = "preview"  # las vistas previas clicables dentro de la carpeta de trabajo
CARPETA_LECTURAS = "lecturas"  # el texto de cada Word o PDF que lee ``tiza leer``
MARCA_ILEGIBLE = "0" * 64  # ``huella_fichero`` cuando no se pudo leer el fichero: bloquea siempre
AVISO_CAMBIADA = (
    "El nombre, el texto o las fechas cambiaron en el aula desde la importación. "
    "Tu fichero no se ha tocado; la versión nueva está en .tiza/copia/{cmid}.html."
)
_AVISO_CAMBIADA = re.compile(
    r"El nombre, el texto o las fechas cambiaron en el aula desde la importación\. "
    r"Tu fichero no se ha tocado; la versión nueva está en \.tiza/copia/\d+\.html\. ?"
)
FICHERO_CALIFICADOR = "calificador.json"  # la huella de cada nodo del calificador que montó tiza
MAX_CALIFICADOR_JSON = 16 * 1024 * 1024  # calificador.json, al leerlo
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


def huellas_de_copia(dir_tiza: str | Path, curso: int) -> dict[int, str]:
    """La ``huella_aula`` de cada actividad del ``curso`` en ``copia.json`` (cmid -> huella).

    Solo las que la tienen. Sin ``copia.json`` o sin entrada para el curso, ``{}``: no hay nada
    que comparar. Un ``copia.json`` fuera del esquema o ilegible da ``ErrorEstado``.
    """
    try:
        datos = cargar_copia(dir_tiza)
    except ErrorEstado as exc:
        if exc.codigo == "IMPORTACION_AUSENTE":
            return {}
        raise
    entrada = datos["cursos"].get(str(curso))
    if entrada is None:
        return {}
    return {
        actividad["cmid"]: actividad["huella_aula"]
        for actividad in entrada["actividades"]
        if actividad["huella_aula"] is not None
    }


def marcas_de_copia(dir_tiza: str | Path, curso: int) -> dict[int, str]:
    """El ``huella_fichero`` de cada actividad del ``curso`` que se marcó como cambiada en el aula.

    Es el sha256 del fichero del docente en el momento de marcarla ``CAMBIADA_DESDE_LA_IMPORTACION``
    (cmid -> sha256): mientras el fichero siga así, el docente no ha juntado los cambios del aula.
    Solo las que lo tienen; sin ``copia.json`` o sin entrada para el curso, ``{}``.
    """
    try:
        datos = cargar_copia(dir_tiza)
    except ErrorEstado as exc:
        if exc.codigo == "IMPORTACION_AUSENTE":
            return {}
        raise
    entrada = datos["cursos"].get(str(curso))
    if entrada is None:
        return {}
    return {
        actividad["cmid"]: actividad["huella_fichero"]
        for actividad in entrada["actividades"]
        if actividad["huella_fichero"] is not None
    }


def quitar_aviso_cambiada(detalle: str) -> str:
    """El ``detalle`` sin el aviso de «cambió en el aula» (que deja de valer al juntarlo)."""
    return _AVISO_CAMBIADA.sub("", detalle).strip()


def guardar_huella_de_copia(dir_tiza: str | Path, curso: int, cmid: int, huella: str) -> bool:
    """Renueva la ``huella_aula`` de una actividad, solo en la entrada de su curso.

    Lo que se acaba de publicar es ya la línea base: la marca del fichero (``huella_fichero``)
    se borra. Devuelve ``False`` si ``copia.json`` no existe o la actividad no está en la entrada de ese
    curso (no se inventan entradas). Lo demás de ``copia.json`` queda igual.
    """
    try:
        datos = cargar_copia(dir_tiza)
    except ErrorEstado as exc:
        if exc.codigo == "IMPORTACION_AUSENTE":
            return False
        raise
    entrada = datos["cursos"].get(str(curso))
    if entrada is None:
        return False
    hechas = [a for a in entrada["actividades"] if a["cmid"] == cmid]
    if not hechas:
        return False
    for actividad in hechas:
        actividad["huella_aula"] = huella
        actividad["huella_fichero"] = None
        actividad["estado"] = "IMPORTADA"  # ya no hay nada que juntar
        if actividad["detalle"] is not None:  # el aviso de «cambió en el aula» ya no vale
            actividad["detalle"] = quitar_aviso_cambiada(actividad["detalle"]) or None
    escribir_copia(dir_tiza, datos)
    return True


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


_HUELLA = re.compile(r"[0-9a-f]{64}")
# Las claves son números de ID de Moodle: los de tiza (``TZ_…``) y los que el docente puso a sus
# actividades. Solo un juego seguro de caracteres: nada de bidi, invisibles ni espacios. El que
# no cumpla no se guarda y su nodo se trata como sin huella.
_CLAVE_DE_NODO = re.compile(r"[A-Za-z0-9_.:-]{1,100}")
_CURSO_DE_HUELLAS = re.compile(r"[0-9]{1,18}")


def clave_de_huella_valida(clave: str) -> bool:
    """¿Puede ``clave`` (un número de ID) ser clave de una huella en ``calificador.json``?"""
    return isinstance(clave, str) and _CLAVE_DE_NODO.fullmatch(clave) is not None


def _validar_calificador(datos: Any) -> None:
    """Esquema cerrado de ``calificador.json``: ``{version: 1, cursos: {id: {nodos: {id: sha256}}}}``."""
    if not isinstance(datos, dict) or set(datos) != {"version", "cursos"}:
        raise ErrorEstado("CALIFICADOR_INVALIDO")
    if datos["version"] != 1 or isinstance(datos["version"], bool):
        raise ErrorEstado("CALIFICADOR_INVALIDO")
    cursos = datos["cursos"]
    if not isinstance(cursos, dict):
        raise ErrorEstado("CALIFICADOR_INVALIDO")
    for curso, entrada in cursos.items():
        if not isinstance(curso, str) or not _CURSO_DE_HUELLAS.fullmatch(curso):
            raise ErrorEstado("CALIFICADOR_INVALIDO")
        if not isinstance(entrada, dict) or set(entrada) != {"nodos"}:
            raise ErrorEstado("CALIFICADOR_INVALIDO")
        nodos = entrada["nodos"]
        if not isinstance(nodos, dict):
            raise ErrorEstado("CALIFICADOR_INVALIDO")
        for clave, huella in nodos.items():
            if not isinstance(clave, str) or not _CLAVE_DE_NODO.fullmatch(clave):
                raise ErrorEstado("CALIFICADOR_INVALIDO")
            if not isinstance(huella, str) or not _HUELLA.fullmatch(huella):
                raise ErrorEstado("CALIFICADOR_INVALIDO")


def _cargar_calificador(dir_tiza: str | Path) -> dict | None:
    """``calificador.json`` validado, o ``None`` si no existe; fuera del esquema es inválido."""
    ruta = Path(dir_tiza) / FICHERO_CALIFICADOR
    try:
        modo = os.lstat(ruta).st_mode
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ErrorEstado("CALIFICADOR_INVALIDO") from exc
    if not stat.S_ISREG(modo):  # un directorio, una FIFO o un enlace: no es el de tiza
        raise ErrorEstado("CALIFICADOR_INVALIDO")
    try:
        datos = json.loads(leer_bytes_acotado(ruta, MAX_CALIFICADOR_JSON).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErrorEstado("CALIFICADOR_INVALIDO") from exc
    _validar_calificador(datos)
    return datos


def cargar_huellas(dir_tiza: str | Path, curso: int) -> dict[str, str]:
    """Las huellas de los nodos del calificador que montó tiza en ``curso`` (idnumber -> sha256).

    Sin ``calificador.json`` o sin entrada para el curso, ``{}``: tiza no recuerda nada y
    adopta lo que haya. Un fichero fuera del esquema es ``CALIFICADOR_INVALIDO``.
    """
    datos = _cargar_calificador(dir_tiza)
    if datos is None:
        return {}
    entrada = datos["cursos"].get(str(curso))
    return dict(entrada["nodos"]) if entrada else {}


def guardar_huellas(dir_tiza: str | Path, curso: int, nodos: Mapping[str, str]) -> Path:
    """Guarda las huellas de ``curso`` (sustituye las anteriores) y deja intactos los demás cursos.

    Valida antes de escribir: lo que no case con el esquema no llega al disco. Las claves que no
    son un número de ID seguro (``clave_de_huella_valida``) no se guardan: ese nodo queda sin huella.
    """
    datos = _cargar_calificador(dir_tiza) or {"version": 1, "cursos": {}}
    guardables = {k: v for k, v in nodos.items() if clave_de_huella_valida(k)}
    datos["cursos"][str(int(curso))] = {"nodos": guardables}
    _validar_calificador(datos)
    asegurar_directorio(Path(dir_tiza))
    return escribir_json(Path(dir_tiza) / FICHERO_CALIFICADOR, datos)


_TIPO_PUBLICADO = re.compile(r"[a-z0-9_]{1,40}")
# Controles, invisibles y bidi (Cc, Cf) y separadores de línea y de párrafo (Zl, Zp).
_CATEGORIAS_PROHIBIDAS = frozenset({"Cc", "Cf", "Zl", "Zp"})


@dataclass(frozen=True)
class Publicado:
    """Lo que tiza publicó de un fichero de la asignatura en un curso.

    ``cmid`` y ``tipo`` dicen qué actividad es; ``huella`` y ``marca`` son sha256 en hex o None.
    """

    cmid: int
    tipo: str
    huella: str | None = None
    marca: str | None = None


def ruta_publicada_valida(ruta: str) -> bool:
    """¿Es ``ruta`` una ruta relativa POSIX segura para ser clave de ``publicados.json``?"""
    if not isinstance(ruta, str) or not 0 < len(ruta) <= 1024:
        return False
    if "\\" in ruta or ruta.startswith("/"):
        return False
    if any(unicodedata.category(c) in _CATEGORIAS_PROHIBIDAS for c in ruta):
        return False
    return all(segmento not in ("", ".", "..") for segmento in ruta.split("/"))


def _clave_curso(curso: int) -> str:
    return str(int(curso))


def _validar_publicados(datos: Any) -> None:
    """Esquema cerrado de ``publicados.json``: ``{version: 1, cursos: {id: {ficheros: {ruta: …}}}}``."""
    if not isinstance(datos, dict) or set(datos) != {"version", "cursos"}:
        raise ErrorEstado("PUBLICADOS_INVALIDO")
    if datos["version"] != 1 or isinstance(datos["version"], bool):
        raise ErrorEstado("PUBLICADOS_INVALIDO")
    cursos = datos["cursos"]
    if not isinstance(cursos, dict):
        raise ErrorEstado("PUBLICADOS_INVALIDO")
    for curso, entrada in cursos.items():
        if not isinstance(curso, str) or not _CURSO_DE_HUELLAS.fullmatch(curso):
            raise ErrorEstado("PUBLICADOS_INVALIDO")
        if not isinstance(entrada, dict) or set(entrada) != {"ficheros"}:
            raise ErrorEstado("PUBLICADOS_INVALIDO")
        ficheros = entrada["ficheros"]
        if not isinstance(ficheros, dict):
            raise ErrorEstado("PUBLICADOS_INVALIDO")
        cmids: set[int] = set()
        for ruta, valor in ficheros.items():
            if not ruta_publicada_valida(ruta) or not isinstance(valor, dict):
                raise ErrorEstado("PUBLICADOS_INVALIDO")
            if set(valor) != {"cmid", "tipo", "huella", "marca"}:
                raise ErrorEstado("PUBLICADOS_INVALIDO")
            cmid, tipo = valor["cmid"], valor["tipo"]
            if isinstance(cmid, bool) or not isinstance(cmid, int) or cmid <= 0 or cmid in cmids:
                raise ErrorEstado("PUBLICADOS_INVALIDO")
            if not isinstance(tipo, str) or not _TIPO_PUBLICADO.fullmatch(tipo):
                raise ErrorEstado("PUBLICADOS_INVALIDO")
            for huella in (valor["huella"], valor["marca"]):
                if huella is not None and (
                    not isinstance(huella, str) or not _HUELLA.fullmatch(huella)
                ):
                    raise ErrorEstado("PUBLICADOS_INVALIDO")
            cmids.add(cmid)


def _cargar_publicados_datos(dir_tiza: str | Path) -> dict | None:
    """``publicados.json`` validado, o ``None`` si no existe; fuera del esquema es inválido."""
    ruta = Path(dir_tiza) / FICHERO_PUBLICADOS
    try:
        modo = os.lstat(ruta).st_mode
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ErrorEstado("PUBLICADOS_INVALIDO") from exc
    if not stat.S_ISREG(modo):  # un directorio, una FIFO o un enlace: no es el de tiza
        raise ErrorEstado("PUBLICADOS_INVALIDO")
    try:
        datos = json.loads(leer_bytes_acotado(ruta, MAX_PUBLICADOS_JSON).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErrorEstado("PUBLICADOS_INVALIDO") from exc
    _validar_publicados(datos)
    return datos


def cargar_publicados(dir_tiza: str | Path, curso: int) -> dict[str, Publicado]:
    """Ruta -> ``Publicado`` de ``curso``. Sin fichero o sin entrada para el curso, ``{}``."""
    datos = _cargar_publicados_datos(dir_tiza)
    if datos is None:
        return {}
    entrada = datos["cursos"].get(_clave_curso(curso))
    if entrada is None:
        return {}
    return {ruta: Publicado(**valor) for ruta, valor in entrada["ficheros"].items()}


def guardar_publicado(dir_tiza: str | Path, curso: int, ruta: str, publicado: Publicado) -> Path:
    """Crea o sustituye la entrada de ``ruta`` en ``curso``; deja intactos los demás cursos.

    Quita cualquier otra ruta del mismo curso con el mismo ``cmid``: una actividad, una ruta.
    Valida antes de escribir: lo que no case con el esquema no llega al disco.
    """
    if not ruta_publicada_valida(ruta):
        raise ErrorEstado("PUBLICADOS_INVALIDO")
    datos = _cargar_publicados_datos(dir_tiza) or {"version": 1, "cursos": {}}
    clave = _clave_curso(curso)
    ficheros = datos["cursos"].get(clave, {"ficheros": {}})["ficheros"]
    nuevos = {r: v for r, v in ficheros.items() if r != ruta and v["cmid"] != publicado.cmid}
    nuevos[ruta] = dataclasses.asdict(publicado)
    datos["cursos"][clave] = {"ficheros": nuevos}
    _validar_publicados(datos)
    asegurar_directorio(Path(dir_tiza))
    return escribir_json(Path(dir_tiza) / FICHERO_PUBLICADOS, datos)


def olvidar_publicado(dir_tiza: str | Path, curso: int, ruta: str) -> bool:
    """Quita la entrada de ``ruta`` en ``curso``; ``False`` si no estaba (y no escribe nada).

    Si el curso se queda sin ficheros, se quita el curso.
    """
    datos = _cargar_publicados_datos(dir_tiza)
    if datos is None:
        return False
    clave = _clave_curso(curso)
    entrada = datos["cursos"].get(clave)
    if entrada is None or ruta not in entrada["ficheros"]:
        return False
    del entrada["ficheros"][ruta]
    if not entrada["ficheros"]:
        del datos["cursos"][clave]
    _validar_publicados(datos)
    escribir_json(Path(dir_tiza) / FICHERO_PUBLICADOS, datos)
    return True


def fichero_de_cmid(dir_tiza: str | Path, curso: int, cmid: int) -> str | None:
    """La ruta registrada para ``cmid`` en ``curso``, o ``None``."""
    for ruta, publicado in cargar_publicados(dir_tiza, curso).items():
        if publicado.cmid == cmid:
            return ruta
    return None


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
