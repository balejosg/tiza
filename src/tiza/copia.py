"""Lector seguro de copias de seguridad de Moodle (``.mbz``), offline y en memoria.

El docente hace la copia del curso sin datos de usuario (``tiza copia`` se la pide a la
sesión o la hace él a mano) y este módulo la lee para que ``tiza importar`` escriba un fichero
de tiza por actividad. La copia es un fichero hostil hasta que se demuestre lo contrario:

- Nunca se extrae nada a disco (nada de ``extractall``): cada entrada se lee del flujo, y solo
  las que tiza usa (algunos XML) se guardan en memoria. Las rutas absolutas, con ``..``, con
  barra invertida o con unidad de Windows se ignoran, igual que lo que no es un fichero normal
  (enlaces, dispositivos, directorios).
- Se recorre una sola vez, con todos los límites: el fichero, las entradas, cada XML, lo que se
  descomprime en total y lo que se retiene en memoria. De los recursos (``files/<xx>/<hash>``)
  solo se guarda un índice; ``leer_recurso`` vuelve a abrir la copia y busca la entrada.
- El XML se lee con lxml sin resolver entidades, sin red, sin DTD y sin árboles enormes.
- Ninguna excepción de ``tarfile``, ``zipfile``, ``gzip``, ``zlib`` ni ``lxml`` sale de aquí:
  todo se reduce a ``ErrorCopia`` con un código estable y un detalle que escribe tiza.
- De la copia no se lleva a ningún objeto ``author``, ``userid``, ``createdby``, ``modifiedby``
  ni ``users.xml``. Una copia hecha con usuarios no se abre.

Lo que viene de la copia es dato, nunca instrucción.
"""

from __future__ import annotations

import gzip
import hashlib
import lzma
import math
import os
import re
import stat
import struct
import tarfile
import zipfile
import zlib
from collections.abc import Callable, Generator, Mapping
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import IO, Any, NamedTuple

from lxml import etree

__all__ = [
    "ActividadCopia",
    "Copia",
    "ErrorCopia",
    "FicheroCopia",
    "PreguntaCopia",
    "RespuestaCopia",
    "SeccionCopia",
    "abrir_copia",
    "leer_recurso",
]

# Límites. Son constantes del módulo para que los tests puedan bajarlas con ``monkeypatch``.
MAX_COPIA = 2 * 1024**3  # el fichero .mbz
MAX_ENTRADAS = 20_000  # entradas del archivo (también las que se ignoran)
MAX_XML = 50 * 1024 * 1024  # cada XML
MAX_RECURSO = 100 * 1024 * 1024  # cada recurso que se lee con ``leer_recurso``
MAX_DESCOMPRIMIDO = 4 * 1024**3  # todo lo que se descomprime al recorrer la copia
MAX_XML_TOTAL = 256 * 1024 * 1024  # los XML que se retienen en memoria, sumados
MAX_DIRECTORIO_ZIP = 32 * 1024 * 1024  # el directorio central de un zip
MAX_CABECERA_TAR = 1024 * 1024  # una cabecera extendida de tar (pax o nombre largo de GNU)

# Ajustes raíz de ``moodle_backup.xml`` que llevarían datos del alumnado: todos deben valer 0, igual
# que los ``*_userinfo`` de secciones y actividades. No están ``badges``, ``calendarevents`` ni
# ``groups``: el formulario los trae marcados por defecto y, sin ``users``, no llevan personas
# (la copia que hace el docente a mano con los valores por defecto los tiene a 1).
AJUSTES_CON_DATOS_DE_USUARIO = frozenset(
    {
        "users",
        "anonymize",
        "role_assignments",
        "comments",
        "userscompletion",
        "logs",
        "grade_histories",
        "xapistate",
    }
)

_NULO = "$@NULL@$"  # cómo escribe Moodle un valor nulo en sus XML
_TROZO = 64 * 1024
_HASH = re.compile(r"[0-9a-f]{40}")
_RECURSO = re.compile(r"files/([0-9a-f]{2})/([0-9a-f]{40})")
_SECCION = re.compile(r"sections/section_([1-9][0-9]{0,17})/section\.xml")
_ACTIVIDAD = re.compile(r"activities/([a-z][a-z0-9]*)_([1-9][0-9]{0,17})/([A-Za-z0-9_]+)\.xml")
_UNIDAD = re.compile(r"[A-Za-z]:")
_ENTERO = re.compile(r"-?[0-9]{1,18}")

# Ajustes de ``plugin_qtype_*_question`` que se llevan a ``PreguntaCopia.opciones``.
_OPCIONES_ADMITIDAS = frozenset(
    {
        "single",
        "shuffleanswers",
        "answernumbering",
        "showstandardinstruction",
        "usecase",
        "trueanswer",
        "falseanswer",
    }
)

_ERRORES_DE_LIBRERIA = (
    tarfile.TarError,
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    gzip.BadGzipFile,
    zlib.error,
    lzma.LZMAError,
    EOFError,
    OSError,
    ValueError,
    NotImplementedError,
    RuntimeError,
    OverflowError,
    struct.error,
    etree.LxmlError,
)


class ErrorCopia(Exception):
    """Error de lectura de la copia con un código estable; el detalle es texto de tiza."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


@dataclass(frozen=True, slots=True)
class FicheroCopia:
    """Un fichero de una actividad según ``files.xml`` (sin autor ni usuario)."""

    nombre: str
    filearea: str
    contenthash: str
    componente: str = ""
    ruta: str = "/"
    tamano: int = 0


@dataclass(frozen=True, slots=True)
class RespuestaCopia:
    """Una respuesta de una pregunta; ``id`` es el de ``question_answers`` (0 si no se conoce)
    y ``tolerancia`` la de una respuesta numérica (``numerical_records``; 0 si no la tiene)."""

    texto: str
    fraccion: float
    retroalimentacion: str = ""
    id: int = 0
    tolerancia: float = 0.0
    formato_html: bool = True  # el texto y su retroalimentación están en HTML (formato 1)


@dataclass(frozen=True, slots=True)
class PreguntaCopia:
    """Una pregunta (un hueco) de un cuestionario.

    Versión: la que fija el cuestionario (``question_reference/version``) si la hay; si no, la
    última en estado ``ready``, como lo resuelve Moodle.

    ``tipo``: el ``qtype`` de la pregunta, salvo en dos casos que la tarea 3 no puede importar y
    marcará como no admitidos: ``random`` (hueco de pregunta aleatoria,
    ``question_set_reference``) y ``desconocida`` (la pregunta no está en ``questions.xml`` o no
    tiene una versión elegible). En ambos, ``entrada`` y ``version`` valen 0 si no se conocen y
    los textos van vacíos; el hueco y los puntos sí se conservan.

    ``opciones``: los ajustes sencillos del tipo de pregunta que tiza usa (lista blanca
    ``_OPCIONES_ADMITIDAS``, por ejemplo ``single`` o ``shuffleanswers`` de una de opciones).

    ``formato_html``: el enunciado y la retroalimentación general están en HTML (formato 1; un
    formato que la copia no dice cuenta como HTML). ``penalizacion``: la ``penalty`` de la
    pregunta, o ``None`` si la copia no la trae. ``con_unidades``: una numérica con unidades.
    """

    entrada: int
    version: int
    hueco: int
    nombre: str
    tipo: str
    texto: str
    retroalimentacion: str
    puntos: float
    respuestas: tuple[RespuestaCopia, ...] = ()
    opciones: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    formato_html: bool = True
    penalizacion: float | None = None
    con_unidades: bool = False


@dataclass(frozen=True, slots=True)
class SeccionCopia:
    id: int
    numero: int
    nombre: str
    resumen_html: str
    orden_actividades: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ActividadCopia:
    """Una actividad de la copia.

    ``fechas``: tarea (``allowsubmissionsfromdate``, ``duedate``, ``cutoffdate``) o
    cuestionario (``timeopen``, ``timeclose``), cada una un ``datetime`` en UTC o ``None``
    si es 0; vacío en las demás. ``html``: el ``content`` de una página; el ``intro`` del resto.

    Solo en un cuestionario (``None`` en los demás o si la copia no lo dice): ``intentos``
    (``attempts_number``; 0 son ilimitados, como en tiza), ``tiempo_limite`` (``timelimit``, en
    segundos; ``None`` si no tiene) y ``mezclar_respuestas`` (``shuffleanswers``).

    ``formato_html``: el texto (``content`` de una página, ``intro`` del resto) está en HTML
    (formato 1; si la copia no dice el formato, cuenta como HTML). ``fecha_recordatorio``: el
    «recordarme calificar antes de» de una tarea (``gradingduedate``), que tiza nunca pone.
    """

    cmid: int
    modulo: str
    seccion_id: int
    nombre: str
    visible: bool
    html: str
    fechas: Mapping[str, datetime | None] = field(default_factory=lambda: MappingProxyType({}))
    ficheros: tuple[FicheroCopia, ...] = ()
    preguntas: tuple[PreguntaCopia, ...] = ()
    paquete_h5p: str | None = None
    intentos: int | None = None
    tiempo_limite: int | None = None
    mezclar_respuestas: bool | None = None
    formato_html: bool = True
    fecha_recordatorio: datetime | None = None


@dataclass(frozen=True, slots=True)
class Copia:
    """La copia leída: lo que tiza usa y el índice para ``leer_recurso``.

    ``servidor`` es ``original_wwwroot``. ``ruta`` y ``recursos`` (``contenthash`` -> nombre de
    la entrada y tamaño) son internos de ``leer_recurso``.
    """

    curso_original: int
    moodle: str
    secciones: tuple[SeccionCopia, ...]
    actividades: tuple[ActividadCopia, ...]
    servidor: str = ""
    ruta: Path = field(default=Path(), repr=False, compare=False)
    recursos: Mapping[str, tuple[str, int]] = field(
        default_factory=lambda: MappingProxyType({}), repr=False, compare=False
    )


# --- Recorrido del archivo -------------------------------------------------------------


class _Entrada(NamedTuple):
    nombre: str
    tamano: int
    abrir: Callable[[], IO[bytes]]  # válido solo hasta pedir la siguiente entrada


class _Acotado:
    """Cuenta lo que se descomprime y corta al pasar del límite (bombas de compresión)."""

    def __init__(self, origen: Any) -> None:
        self._origen = origen
        self._restante = MAX_DESCOMPRIMIDO

    def read(self, n: int = -1) -> bytes:
        n = _TROZO if n is None or n < 0 else min(n, _TROZO)
        datos = self._origen.read(n)
        self._restante -= len(datos)
        if self._restante < 0:
            raise _demasiado_grande("La copia ocupa demasiado al descomprimirla.")
        return datos


def _demasiado_grande(detalle: str) -> ErrorCopia:
    return ErrorCopia("COPIA_DEMASIADO_GRANDE", detalle)


def _no_valida(detalle: str) -> ErrorCopia:
    return ErrorCopia("COPIA_NO_VALIDA", detalle)


def _ruta_segura(nombre: str) -> str | None:
    """La ruta limpia de una entrada, o ``None`` si es absoluta, sube con ``..`` o es rara."""
    if not nombre or "\x00" in nombre or "\\" in nombre or nombre.startswith("/"):
        return None
    partes = nombre.split("/")
    while partes and partes[0] == ".":
        partes.pop(0)
    if partes and partes[-1] == "":
        partes.pop()  # barra final de un directorio
    if not partes or any(p in ("", ".", "..") for p in partes):
        return None
    if _UNIDAD.match(partes[0]):
        return None
    return "/".join(partes)


def _nombre_para_mensaje(nombre: str) -> str:
    """El nombre de una entrada, apto para un detalle: sin nada que no sea ruta llana."""
    limpio = re.sub(r"[^A-Za-z0-9_./-]", "?", nombre)
    return limpio if len(limpio) <= 80 else limpio[:77] + "..."


def _abrir_fichero(ruta: Path) -> IO[bytes]:
    """Abre la copia: un fichero normal (no un enlace ni una FIFO) de tamaño aceptable."""
    banderas = os.O_RDONLY
    for nombre in ("O_NONBLOCK", "O_CLOEXEC", "O_BINARY", "O_NOFOLLOW"):
        banderas |= getattr(os, nombre, 0)
    if Path(ruta).is_symlink():
        raise _no_valida("La copia no puede ser un enlace simbólico.")
    try:
        descriptor = os.open(ruta, banderas)
    except OSError:
        raise _no_valida("No se pudo abrir el fichero de la copia.") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise _no_valida("La copia debe ser un fichero normal.")
        if info.st_size > MAX_COPIA:
            raise _demasiado_grande("El fichero de la copia pasa de 2 GB.")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _comprobar_directorio_zip(fichero: IO[bytes]) -> None:
    """Rechaza un zip cuyo directorio central sea enorme, antes de que ``zipfile`` lo cargue."""
    fichero.seek(0, os.SEEK_END)
    fin = fichero.tell()
    cola = min(fin, 22 + 65535)
    fichero.seek(fin - cola)
    datos = fichero.read(cola)
    fichero.seek(0)
    pos = datos.rfind(b"PK\x05\x06")
    if pos < 0 or len(datos) < pos + 22:
        raise _no_valida("El zip de la copia está dañado.")
    # Un .mbz de Moodle no necesita zip64; con su localizador, ``zipfile`` ignoraría el EOCD
    # clásico que se mira aquí, así que se rechaza.
    if pos >= 20 and datos[pos - 20 : pos - 16] == b"PK\x06\x07":
        raise _no_valida("El zip de la copia usa un formato que tiza no admite.")
    entradas = struct.unpack("<H", datos[pos + 10 : pos + 12])[0]
    tamano_directorio = struct.unpack("<L", datos[pos + 12 : pos + 16])[0]
    if entradas > MAX_ENTRADAS or tamano_directorio > MAX_DIRECTORIO_ZIP:
        raise _demasiado_grande("La copia tiene demasiadas entradas.")


def _entradas(ruta: Path) -> Generator[_Entrada, None, None]:
    """Las entradas que son ficheros normales con ruta segura, una a una y sin extraer."""
    with _abrir_fichero(ruta) as fichero:
        firma = fichero.read(2)
        fichero.seek(0)
        if firma == b"\x1f\x8b":
            yield from _entradas_tar(fichero)
        elif firma == b"PK":
            yield from _entradas_zip(fichero)
        else:
            raise _no_valida("El fichero no es una copia de Moodle (ni tar.gz ni zip).")


_CABECERAS_EXTENDIDAS = frozenset(
    {
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.SOLARIS_XHDTYPE,
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
    }
)


class _TarInfoAcotado(tarfile.TarInfo):
    """``TarInfo`` que no deja a ``tarfile`` leer en memoria una cabecera extendida enorme.

    ``tarfile`` lee la cabecera pax o de nombre largo entera antes de que nada pueda cortarla, y
    su tamaño lo declara el propio fichero. Se apoya en ``_proc_member``, que es API privada de
    ``tarfile`` (estable desde Python 3.8): ``test_la_api_privada_de_tarfile_sigue_ahi`` falla si
    cambia.
    """

    def _proc_member(self, tarfile: Any) -> Any:
        if self.type in _CABECERAS_EXTENDIDAS and self.size > MAX_CABECERA_TAR:
            raise _no_valida("La copia tiene una cabecera de archivo demasiado grande.")
        return super()._proc_member(tarfile)  # type: ignore[misc]


def _entradas_tar(fichero: IO[bytes]) -> Generator[_Entrada, None, None]:
    cuenta = 0
    with gzip.GzipFile(fileobj=fichero, mode="rb") as plano:
        flujo: Any = _Acotado(plano)
        with tarfile.open(fileobj=flujo, mode="r|", tarinfo=_TarInfoAcotado) as tar:
            for miembro in tar:
                cuenta += 1
                if cuenta > MAX_ENTRADAS:
                    raise _demasiado_grande("La copia tiene demasiadas entradas.")
                if not miembro.isreg():
                    continue
                nombre = _ruta_segura(miembro.name)
                if nombre is None:
                    continue

                def abrir(m: tarfile.TarInfo = miembro) -> IO[bytes]:
                    lector = tar.extractfile(m)
                    if lector is None:
                        raise _no_valida("No se pudo leer una entrada de la copia.")
                    return lector

                yield _Entrada(nombre, miembro.size, abrir)


def _entradas_zip(fichero: IO[bytes]) -> Generator[_Entrada, None, None]:
    _comprobar_directorio_zip(fichero)
    with zipfile.ZipFile(fichero) as archivo:
        infos = archivo.infolist()
        if len(infos) > MAX_ENTRADAS:
            raise _demasiado_grande("La copia tiene demasiadas entradas.")
        total = 0
        for info in infos:
            if info.is_dir():
                continue
            modo = stat.S_IFMT(info.external_attr >> 16)
            if modo not in (0, stat.S_IFREG):
                continue  # enlace simbólico, dispositivo...
            nombre = _ruta_segura(info.filename)
            if nombre is None:
                continue
            total += info.file_size
            if total > MAX_DESCOMPRIMIDO:
                raise _demasiado_grande("La copia ocupa demasiado al descomprimirla.")

            def abrir(i: zipfile.ZipInfo = info) -> IO[bytes]:
                return archivo.open(i)

            yield _Entrada(nombre, info.file_size, abrir)


def _leer_acotado(lector: IO[bytes], maximo: int, que: str) -> bytes:
    """Lee como mucho ``maximo`` bytes; si hay más, ``COPIA_DEMASIADO_GRANDE``."""
    trozos: list[bytes] = []
    leidos = 0
    while leidos <= maximo:
        trozo = lector.read(min(_TROZO, maximo + 1 - leidos))
        if not trozo:
            break
        trozos.append(trozo)
        leidos += len(trozo)
    if leidos > maximo:
        raise _demasiado_grande(f"{que} es demasiado grande.")
    return b"".join(trozos)


def _leer_entrada(entrada: _Entrada, maximo: int, que: str) -> bytes:
    """Lee la entrada entera (con límite) y cierra su lector."""
    with closing(entrada.abrir()) as lector:
        return _leer_acotado(lector, maximo, que)


def _es_xml_usado(nombre: str) -> bool:
    return (
        nombre in ("moodle_backup.xml", "files.xml", "questions.xml")
        or _SECCION.fullmatch(nombre) is not None
        or _actividad_de(nombre) is not None
    )


def _actividad_de(nombre: str) -> tuple[str, int] | None:
    """(módulo, cmid) si es ``module.xml`` o ``<módulo>.xml`` de una actividad."""
    m = _ACTIVIDAD.fullmatch(nombre)
    if m is None or m.group(3) not in ("module", m.group(1)):
        return None
    return m.group(1), int(m.group(2))


# --- XML -------------------------------------------------------------------------------


def _parsear(datos: bytes, nombre: str) -> Any:
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False
    )
    invalido = _no_valida(f"El XML «{_nombre_para_mensaje(nombre)}» de la copia no es válido.")
    try:
        raiz = etree.fromstring(datos, parser)
        info = raiz.getroottree().docinfo
        # Moodle nunca escribe un DOCTYPE ni entidades: se rechaza antes de usar el árbol.
        if (
            info.doctype
            or info.internalDTD is not None
            or info.externalDTD is not None
            or any(True for _ in raiz.iter(etree.Entity))
        ):
            raise invalido
    except (etree.LxmlError, ValueError):
        raise invalido from None
    return raiz


def _texto(elem: Any, etiqueta: str, defecto: str = "") -> str:
    hijo = elem.find(etiqueta) if elem is not None else None
    if hijo is None or hijo.text is None or hijo.text == _NULO:
        return defecto
    return str(hijo.text)


def _entero(texto: str, que: str) -> int:
    texto = texto.strip()
    if not _ENTERO.fullmatch(texto):
        raise _no_valida(f"La copia tiene un número que no es válido ({que}).")
    return int(texto)


def _entero_de(elem: Any, etiqueta: str, que: str, defecto: int | None = None) -> int:
    valor = _texto(elem, etiqueta)
    if not valor.strip() and defecto is not None:
        return defecto
    return _entero(valor, que)


def _decimal(texto: str, defecto: float = 0.0) -> float:
    try:
        valor = float(texto.strip()) if texto.strip() else defecto
    except ValueError:
        raise _no_valida("La copia tiene un número que no es válido.") from None
    if not math.isfinite(valor):
        raise _no_valida("La copia tiene un número que no es válido.")
    return valor


def _fecha(elem: Any, etiqueta: str) -> datetime | None:
    segundos = _entero_de(elem, etiqueta, etiqueta, 0)
    if segundos == 0:
        return None
    try:
        return datetime.fromtimestamp(segundos, tz=UTC)
    except (OverflowError, OSError, ValueError):
        raise _no_valida(f"La copia tiene una fecha que no es válida ({etiqueta}).") from None


# --- Construcción ----------------------------------------------------------------------


def abrir_copia(ruta: Path) -> Copia:
    """Lee la copia ``ruta`` (tar.gz o zip) y devuelve lo que tiza usa, en memoria."""
    ruta = Path(ruta)
    try:
        xmls: dict[str, bytes] = {}
        recursos: dict[str, tuple[str, int]] = {}
        con_usuarios = False
        retenido = 0
        with closing(_entradas(ruta)) as entradas:
            for entrada in entradas:
                nombre = entrada.nombre
                if nombre == "users.xml":
                    con_usuarios = True
                elif _es_xml_usado(nombre):
                    if nombre in xmls:
                        continue
                    if entrada.tamano > MAX_XML:
                        raise _demasiado_grande(
                            f"El XML «{_nombre_para_mensaje(nombre)}» pasa de 50 MB."
                        )
                    retenido += entrada.tamano
                    if retenido > MAX_XML_TOTAL:
                        raise _demasiado_grande("Los XML de la copia ocupan demasiado.")
                    xmls[nombre] = _leer_entrada(entrada, MAX_XML, "Un XML de la copia")
                else:
                    m = _RECURSO.fullmatch(nombre)
                    if m and m.group(2).startswith(m.group(1)):
                        recursos.setdefault(m.group(2), (nombre, entrada.tamano))
        return _construir(xmls, recursos, con_usuarios, ruta)
    except ErrorCopia:
        raise
    except _ERRORES_DE_LIBRERIA:
        raise _no_valida("La copia está dañada o no es una copia de Moodle.") from None


def _construir(
    xmls: dict[str, bytes],
    recursos: dict[str, tuple[str, int]],
    con_usuarios: bool,
    ruta: Path,
) -> Copia:
    if "moodle_backup.xml" not in xmls:
        raise _no_valida("Falta moodle_backup.xml: no es una copia de seguridad de Moodle.")
    raiz = _parsear(xmls["moodle_backup.xml"], "moodle_backup.xml")
    informacion = raiz.find("information")
    if raiz.tag != "moodle_backup" or informacion is None:
        raise _no_valida("moodle_backup.xml no tiene la forma de una copia de Moodle.")
    usuarios = None
    con_datos = False
    for ajuste in informacion.findall("settings/setting"):
        nombre, valor = _texto(ajuste, "name"), _texto(ajuste, "value").strip()
        if _texto(ajuste, "level") == "root" and nombre == "users":
            usuarios = valor
        # Cualquier ajuste de datos de usuario presente que no valga 0 es una copia con personas.
        if (
            _texto(ajuste, "level") == "root" and nombre in AJUSTES_CON_DATOS_DE_USUARIO
        ) or nombre.endswith("_userinfo"):
            con_datos = con_datos or valor != "0"
    if usuarios is None:
        raise _no_valida("La copia no dice si lleva usuarios, así que no se puede abrir.")
    if usuarios != "0" or con_usuarios or con_datos:
        raise ErrorCopia("COPIA_CON_USUARIOS", "La copia incluye datos de usuarios.")

    curso = _entero_de(informacion, "original_course_id", "curso de la copia")
    titulos: dict[str, str] = {}
    for actividad in informacion.findall("contents/activities/activity"):
        titulos[_texto(actividad, "moduleid").strip()] = _texto(actividad, "title")

    ficheros = _leer_ficheros(xmls.get("files.xml"))
    versiones = _leer_preguntas(xmls.get("questions.xml"))
    secciones = _leer_secciones(xmls)
    actividades = _leer_actividades(xmls, titulos, ficheros, versiones)
    return Copia(
        curso_original=curso,
        moodle=_texto(informacion, "moodle_release"),
        secciones=secciones,
        actividades=actividades,
        servidor=_texto(informacion, "original_wwwroot"),
        ruta=ruta,
        recursos=MappingProxyType(dict(recursos)),
    )


def _leer_ficheros(datos: bytes | None) -> dict[int, list[FicheroCopia]]:
    """Los ficheros de ``files.xml`` por contexto; sin carpetas, sin vacíos y sin personas."""
    por_contexto: dict[int, list[FicheroCopia]] = {}
    if datos is None:
        return por_contexto
    for fichero in _parsear(datos, "files.xml").findall("file"):
        nombre = _texto(fichero, "filename")
        contenthash = _texto(fichero, "contenthash").strip()
        if nombre in ("", ".") or not _HASH.fullmatch(contenthash):
            continue
        contexto = _entero_de(fichero, "contextid", "contexto de un fichero")
        por_contexto.setdefault(contexto, []).append(
            FicheroCopia(
                nombre=nombre,
                filearea=_texto(fichero, "filearea"),
                contenthash=contenthash,
                componente=_texto(fichero, "component"),
                ruta=_texto(fichero, "filepath", "/"),
                tamano=_entero_de(fichero, "filesize", "tamaño de un fichero", 0),
            )
        )
    for lista in por_contexto.values():
        lista.sort(key=lambda f: (f.filearea, f.ruta, f.nombre, f.contenthash))
    return por_contexto


def _opciones_de(pregunta: Any) -> Mapping[str, str]:
    """Los ajustes de ``plugin_qtype_*_question`` que están en la lista blanca."""
    opciones: dict[str, str] = {}
    for plugin in pregunta:
        etiqueta = plugin.tag
        if not (
            isinstance(etiqueta, str)
            and etiqueta.startswith("plugin_qtype_")
            and etiqueta.endswith("_question")
        ):
            continue
        for elemento in plugin.iter():
            if elemento is plugin or not isinstance(elemento.tag, str) or len(elemento) > 0:
                continue
            if elemento.tag not in _OPCIONES_ADMITIDAS:
                continue
            if any(a.tag == "answers" for a in elemento.iterancestors()):
                continue
            valor = "" if elemento.text in (None, _NULO) else str(elemento.text)
            opciones.setdefault(elemento.tag, valor)
    return MappingProxyType(opciones)


def _leer_preguntas(datos: bytes | None) -> dict[int, dict[int, tuple[str, Any]]]:
    """Por entrada del banco: versión -> (estado, elemento ``question``)."""
    entradas: dict[int, dict[int, tuple[str, Any]]] = {}
    if datos is None:
        return entradas
    for entrada in _parsear(datos, "questions.xml").iter("question_bank_entry"):
        identificador = _entero(entrada.get("id", ""), "pregunta del banco")
        versiones = entradas.setdefault(identificador, {})
        for version in entrada.iter("question_versions"):
            pregunta = version.find("questions/question")
            if pregunta is None:
                continue
            numero = _entero_de(version, "version", "versión de una pregunta")
            versiones.setdefault(numero, (_texto(version, "status", "ready"), pregunta))
    return entradas


def _elegir_version(versiones: dict[int, tuple[str, Any]], fijada: int | None) -> int | None:
    """La versión fijada por el cuestionario si la hay; si no, la última ``ready``.

    ``None`` si la fijada no existe o no hay ninguna ``ready`` (no se cae a otra versión).
    """
    if fijada is not None:
        return fijada if fijada in versiones else None
    listas = [n for n, (estado, _) in versiones.items() if estado == "ready"]
    return max(listas) if listas else None


def _hueco_sin_pregunta(tipo: str, hueco: int, maximo: str) -> PreguntaCopia:
    """Un hueco que tiza no puede importar: aleatorio o con una pregunta que no se resuelve."""
    return PreguntaCopia(
        entrada=0,
        version=0,
        hueco=hueco,
        nombre="",
        tipo=tipo,
        texto="",
        retroalimentacion="",
        puntos=_decimal(maximo, 1.0),
    )


def _es_html(formato: str) -> bool:
    """El formato de texto de Moodle (1 es HTML); si la copia no lo dice, se da por bueno."""
    return formato.strip() in ("", "1")


def _con_unidades(elemento: Any) -> bool:
    return any(
        _texto(unidad, "unit").strip()
        for plugin in elemento
        if isinstance(plugin.tag, str) and plugin.tag.startswith("plugin_qtype_")
        for unidad in plugin.findall("numerical_units/numerical_unit")
    )


def _respuestas_de(elemento: Any) -> tuple[RespuestaCopia, ...]:
    """Las respuestas de ``plugin_qtype_*_question/answers/answer``, con su tolerancia numérica.

    Solo esas: otros elementos ``answer`` (el de ``numerical_record``, que es un id) no cuentan.
    """
    respuestas = []
    for plugin in elemento:
        etiqueta = plugin.tag
        if not (
            isinstance(etiqueta, str)
            and etiqueta.startswith("plugin_qtype_")
            and etiqueta.endswith("_question")
        ):
            continue
        tolerancias: dict[int, float] = {}
        # Moodle 4.5 guarda la tolerancia en ``numerical_records/numerical_record`` (medido en la
        # copia real); ``numerical_answers`` es el nombre de versiones anteriores.
        for numerica in (
            *plugin.findall("numerical_records/numerical_record"),
            *plugin.findall("numerical_answers/numerical_answer"),
        ):
            referencia = _texto(numerica, "answer").strip()
            if _ENTERO.fullmatch(referencia):
                tolerancias[int(referencia)] = _decimal(_texto(numerica, "tolerance", "0"))
        for r in plugin.findall("answers/answer"):
            identificador = (r.get("id") or "").strip()
            numero = int(identificador) if _ENTERO.fullmatch(identificador) else 0
            respuestas.append(
                RespuestaCopia(
                    texto=_texto(r, "answertext"),
                    fraccion=_decimal(_texto(r, "fraction", "0")),
                    retroalimentacion=_texto(r, "feedback"),
                    id=numero,
                    tolerancia=tolerancias.get(numero, 0.0),
                    formato_html=_es_html(_texto(r, "answerformat"))
                    and (
                        not _texto(r, "feedback").strip() or _es_html(_texto(r, "feedbackformat"))
                    ),
                )
            )
    return tuple(respuestas)


def _pregunta(entrada: int, version: int, hueco: int, maximo: str, elemento: Any) -> PreguntaCopia:
    return PreguntaCopia(
        entrada=entrada,
        version=version,
        hueco=hueco,
        nombre=_texto(elemento, "name"),
        tipo=_texto(elemento, "qtype"),
        texto=_texto(elemento, "questiontext"),
        retroalimentacion=_texto(elemento, "generalfeedback"),
        puntos=_decimal(maximo, _decimal(_texto(elemento, "defaultmark", "1"), 1.0)),
        respuestas=_respuestas_de(elemento),
        opciones=_opciones_de(elemento),
        formato_html=_es_html(_texto(elemento, "questiontextformat"))
        and (
            not _texto(elemento, "generalfeedback").strip()
            or _es_html(_texto(elemento, "generalfeedbackformat"))
        ),
        penalizacion=(
            _decimal(_texto(elemento, "penalty")) if _texto(elemento, "penalty").strip() else None
        ),
        con_unidades=_con_unidades(elemento),
    )


def _preguntas_del_cuestionario(
    cuestionario: Any, versiones: dict[int, dict[int, tuple[str, Any]]]
) -> tuple[PreguntaCopia, ...]:
    preguntas = []
    for instancia in cuestionario.findall("question_instances/question_instance"):
        hueco = _entero_de(instancia, "slot", "hueco del cuestionario", 0)
        maximo = _texto(instancia, "maxmark")
        referencia = instancia.find("question_reference")
        if referencia is None:
            tipo = (
                "random" if instancia.find("question_set_reference") is not None else "desconocida"
            )
            preguntas.append(_hueco_sin_pregunta(tipo, hueco, maximo))
            continue
        entrada = _entero_de(referencia, "questionbankentryid", "pregunta del cuestionario")
        fijada_texto = _texto(referencia, "version").strip()
        fijada = _entero(fijada_texto, "versión fijada") if fijada_texto else None
        disponibles = versiones.get(entrada)
        numero = _elegir_version(disponibles, fijada) if disponibles else None
        if disponibles is None or numero is None:
            preguntas.append(_hueco_sin_pregunta("desconocida", hueco, maximo))
            continue
        preguntas.append(_pregunta(entrada, numero, hueco, maximo, disponibles[numero][1]))
    preguntas.sort(key=lambda p: p.hueco)
    return tuple(preguntas)


def _leer_secciones(xmls: dict[str, bytes]) -> tuple[SeccionCopia, ...]:
    secciones = []
    for nombre in sorted(n for n in xmls if _SECCION.fullmatch(n)):
        raiz = _parsear(xmls[nombre], nombre)
        en_nombre = _SECCION.fullmatch(nombre)
        identificador = _entero(raiz.get("id", ""), "sección")
        if en_nombre is None or identificador != int(en_nombre.group(1)):
            raise _no_valida(f"La sección «{_nombre_para_mensaje(nombre)}» no coincide con su id.")
        orden = []
        for parte in _texto(raiz, "sequence").split(","):
            if parte.strip():
                orden.append(_entero(parte, "orden de la sección"))
        secciones.append(
            SeccionCopia(
                id=identificador,
                numero=_entero_de(raiz, "number", "número de sección"),
                nombre=_texto(raiz, "name"),
                resumen_html=_texto(raiz, "summary"),
                orden_actividades=tuple(orden),
            )
        )
    secciones.sort(key=lambda s: (s.numero, s.id))
    return tuple(secciones)


_FECHAS = {
    "assign": ("allowsubmissionsfromdate", "duedate", "cutoffdate"),
    "quiz": ("timeopen", "timeclose"),
}


def _ajustes_del_cuestionario(contenido: Any) -> dict[str, Any]:
    """``intentos``, ``tiempo_limite`` (segundos) y ``mezclar_respuestas`` de ``quiz.xml``."""
    if contenido is None:
        return {}
    ajustes: dict[str, Any] = {}
    intentos = _texto(contenido, "attempts_number").strip()
    if intentos:
        ajustes["intentos"] = _entero(intentos, "intentos del cuestionario")
    limite = _texto(contenido, "timelimit").strip()
    if limite:
        segundos = _entero(limite, "tiempo límite del cuestionario")
        ajustes["tiempo_limite"] = segundos if segundos > 0 else None
    mezclar = _texto(contenido, "shuffleanswers").strip()
    if mezclar:
        ajustes["mezclar_respuestas"] = mezclar == "1"
    return ajustes


def _leer_actividades(
    xmls: dict[str, bytes],
    titulos: dict[str, str],
    ficheros: dict[int, list[FicheroCopia]],
    versiones: dict[int, dict[int, tuple[str, Any]]],
) -> tuple[ActividadCopia, ...]:
    actividades = []
    vistos: set[int] = set()
    for nombre in sorted(xmls):
        identidad = _actividad_de(nombre)
        if identidad is None or not nombre.endswith("/module.xml"):
            continue
        modulo, cmid = identidad
        if cmid in vistos:
            raise _no_valida(f"La copia repite la actividad {cmid} en dos carpetas.")
        vistos.add(cmid)
        directorio = nombre.rsplit("/", 1)[0]
        modulo_xml = _parsear(xmls[nombre], nombre)
        if _entero(modulo_xml.get("id", ""), "actividad") != cmid:
            raise _no_valida(
                f"La actividad «{_nombre_para_mensaje(directorio)}» no coincide con su module.xml."
            )
        if _texto(modulo_xml, "modulename") != modulo:
            raise _no_valida(
                f"La actividad «{_nombre_para_mensaje(directorio)}» no es del tipo de su carpeta."
            )
        raiz = None
        datos = xmls.get(f"{directorio}/{modulo}.xml")
        if datos is not None:
            raiz = _parsear(datos, f"{directorio}/{modulo}.xml")
            moduleid = raiz.get("moduleid")
            if moduleid is not None and _entero(moduleid, "actividad") != cmid:
                raise _no_valida(
                    f"La actividad «{_nombre_para_mensaje(directorio)}» no coincide con su XML."
                )
        contenido = raiz.find(modulo) if raiz is not None else None
        contexto = _entero(raiz.get("contextid", ""), "contexto") if raiz is not None else None
        propios = ficheros.get(contexto, []) if contexto is not None else []
        campo = "content" if modulo == "page" else "intro"
        fechas = (
            {c: _fecha(contenido, c) for c in _FECHAS.get(modulo, ())}
            if contenido is not None
            else {}
        )
        paquete = next((f.contenthash for f in propios if f.filearea == "package"), None)
        ajustes = _ajustes_del_cuestionario(contenido) if modulo == "quiz" else {}
        formato = _texto(contenido, "contentformat" if modulo == "page" else "introformat")
        actividades.append(
            ActividadCopia(
                cmid=cmid,
                modulo=modulo,
                seccion_id=_entero_de(modulo_xml, "sectionid", "sección de una actividad"),
                nombre=_texto(contenido, "name", titulos.get(str(cmid), "")),
                visible=_texto(modulo_xml, "visible").strip() == "1",
                html=_texto(contenido, campo),
                fechas=MappingProxyType(fechas),
                ficheros=tuple(propios),
                preguntas=(
                    _preguntas_del_cuestionario(contenido, versiones)
                    if modulo == "quiz" and contenido is not None
                    else ()
                ),
                paquete_h5p=paquete if modulo == "h5pactivity" else None,
                formato_html=_es_html(formato),
                fecha_recordatorio=(
                    _fecha(contenido, "gradingduedate")
                    if modulo == "assign" and contenido is not None
                    else None
                ),
                **ajustes,
            )
        )
    actividades.sort(key=lambda a: a.cmid)
    return tuple(actividades)


def leer_recurso(copia: Copia, contenthash: str) -> bytes:
    """El contenido de ``files/<xx>/<contenthash>``, con el límite de 100 MB.

    Comprueba que el sha1 del contenido es el ``contenthash`` (si no, ``COPIA_NO_VALIDA``).

    Vuelve a abrir la copia y busca la entrada: leer un recurso de un tar.gz relee el flujo
    hasta él (se leen pocos), pero la copia nunca está entera en memoria.
    """
    if not _HASH.fullmatch(contenthash) or contenthash not in copia.recursos:
        raise _no_valida("La copia no trae ese fichero.")
    nombre, tamano = copia.recursos[contenthash]
    if tamano > MAX_RECURSO:
        raise _demasiado_grande("Un fichero de la copia pasa de 100 MB.")
    try:
        with closing(_entradas(copia.ruta)) as entradas:
            for entrada in entradas:
                if entrada.nombre == nombre:
                    datos = _leer_entrada(entrada, MAX_RECURSO, "Un fichero de la copia")
                    if hashlib.sha1(datos).hexdigest() != contenthash:
                        raise _no_valida("Un fichero de la copia no coincide con su huella.")
                    return datos
        raise _no_valida("La copia ha cambiado desde que se abrió.")
    except ErrorCopia:
        raise
    except _ERRORES_DE_LIBRERIA:
        raise _no_valida("La copia está dañada o no es una copia de Moodle.") from None
