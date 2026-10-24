"""``tiza importar``: convierte una copia de seguridad de Moodle en ficheros de tiza editables.

Lee la copia con :mod:`tiza.copia` (offline, en memoria) y escribe, por cada página, tarea,
etiqueta, cuestionario o actividad H5P, un fichero ``.html`` o ``.md`` con su frontmatter y el
campo ``origen: {curso, cmid}``, más el resumen ``.tiza/copia.json``. Reglas que no se rompen:

- Nunca sobrescribe nada del docente: cada fichero nuevo se crea con ``x`` y, si ya está, la
  actividad queda como ``YA_IMPORTADO`` sin tocarla.
- Todo lo que se decide (nombres, estados, avisos) se calcula con textos de tiza; de la copia
  solo salen a ``copia.json`` los nombres de actividades y secciones, ya saneados.
- Los nombres de carpetas y ficheros son válidos en Windows, únicos y estables entre
  importaciones (la actividad lleva su ``cmid`` en el nombre).
- Si el curso de la copia no es uno de los cursos reales de ``tiza.toml`` no se escribe nada
  (``COPIA_DE_OTRO_CURSO``), salvo con ``como_nuevas``: entonces los ficheros salen sin
  ``origen`` y se publican como cualquier ``.md`` nuevo. Al revés, con ``como_nuevas`` una copia
  de uno de los cursos reales de este aula no se escribe (``COPIA_DEL_MISMO_CURSO``): sin
  ``origen`` perdería la protección de lo que cambió en el aula.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

import yaml

from . import config, contenido, estado, filtro, rutas, tipos
from . import copia as lector
from .copia import (
    ActividadCopia,
    Copia,
    ErrorCopia,
    FicheroCopia,
    SeccionCopia,
)
from .ficheros import fichero_en_carpeta, leer_bytes_acotado
from .importar_cuestionario import (
    ajustes_del_cuestionario,
    convertir_preguntas,
    html_como_markdown,
)
from .informe import ESTADOS_IMPORTACION, ResumenImportacion
from .lectura.modelo import ErrorLectura

__all__ = [
    "ErrorImportar",
    "ResumenImportacion",
    "importar",
    "nombre_de_recurso",
    "nombre_seguro",
]

ZONA = ZoneInfo("Europe/Madrid")
EXTENSION = {"pagina": ".html", "tarea": ".html", "etiqueta": ".html"}  # el resto, .md
MAX_NOMBRE = 50  # caracteres del nombre limpio en una carpeta o un fichero
MAX_RECURSO = 80  # caracteres del nombre limpio de un recurso (sin la extensión)
_RESERVADOS_WINDOWS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)
_NO_VALIDO_EN_WINDOWS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_REFERENCIA = re.compile(r"@@PLUGINFILE@@/([^\s\"'<>?#]+)")


class ErrorImportar(Exception):
    """Error de ``tiza importar`` con un código estable y un detalle escrito por tiza."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


# --------------------------------------------------------------------------- #
# Nombres
# --------------------------------------------------------------------------- #


def nombre_seguro(texto: str, defecto: str = "sin-nombre", largo: int = MAX_NOMBRE) -> str:
    """Un nombre de carpeta o de fichero: minúsculas, sin tildes, solo letras, cifras y «-».

    Sirve en Windows, macOS y Linux (sin símbolos, sin nombres reservados, sin punto ni
    espacio final) y da lo mismo cada vez que se importa lo mismo.
    """
    limpio = unicodedata.normalize("NFKD", texto)
    limpio = "".join(c for c in limpio if not unicodedata.combining(c)).lower()
    limpio = re.sub(r"[^a-z0-9]+", "-", limpio).strip("-")
    if len(limpio) > largo:
        limpio = limpio[:largo].rstrip("-")
    return limpio or defecto


def nombre_de_recurso(nombre: str) -> str:
    """El nombre de un fichero adjunto, conservando lo que se pueda (``foto.png`` no cambia).

    Letras (también con tilde), cifras, «.», «-» y «_»; lo demás pasa a «_». Nunca empieza por
    punto (sería oculto), ni acaba en punto o espacio, ni es un nombre reservado de Windows.
    """
    limpio = re.sub(r"[^\w.\-]", "_", unicodedata.normalize("NFC", nombre))
    limpio = re.sub(r"_+", "_", limpio)
    cuerpo, punto, extension = limpio.rpartition(".")
    if not punto:
        cuerpo, extension = limpio, ""
    cuerpo = cuerpo.strip("._-") or "recurso"
    if cuerpo.split(".")[0].lower() in _RESERVADOS_WINDOWS:
        cuerpo = f"_{cuerpo}"
    extension = extension.strip("._-")[:10]
    return cuerpo[:MAX_RECURSO] + (f".{extension}" if extension else "")


def _texto_seguro(texto: str, defecto: str = "") -> str:
    """Un texto de la copia apto para ``copia.json``: sin controles ni ``<`` ``>``."""
    return estado.nombre_de_seccion(texto) or defecto


# --------------------------------------------------------------------------- #
# Entradas: la copia y la carpeta de destino
# --------------------------------------------------------------------------- #


def _ruta_de_copia(raiz: Path, ruta: str | Path) -> Path:
    """La copia: un ``.mbz`` de la carpeta o uno directamente en ``.tiza/copias/``."""
    try:
        candidata = (raiz / ruta).resolve()
        copias = (raiz / rutas.CARPETA_TRABAJO / estado.CARPETA_COPIAS).resolve()
    except (OSError, RuntimeError):
        raise ErrorLectura(
            "FICHERO_FUERA", "El fichero no está en la carpeta de la asignatura."
        ) from None
    # Única excepción a las carpetas ocultas; solo si ``.tiza/copias`` no es un enlace fuera.
    if (
        copias == raiz / rutas.CARPETA_TRABAJO / estado.CARPETA_COPIAS
        and candidata.parent == copias
    ):
        destino = candidata
    else:
        try:
            destino = fichero_en_carpeta(ruta, raiz, {".mbz"})
        except ErrorLectura as error:
            if error.codigo == "FORMATO_NO_ADMITIDO":
                raise ErrorImportar(
                    "COPIA_FORMATO", "La copia de seguridad de Moodle es un fichero .mbz."
                ) from None
            raise
    if destino.suffix.lower() != ".mbz":
        raise ErrorImportar("COPIA_FORMATO", "La copia de seguridad de Moodle es un fichero .mbz.")
    if not destino.is_file():
        raise ErrorImportar("COPIA_AUSENTE", f"No existe el fichero {_texto_seguro(destino.name)}.")
    return destino


def _carpeta_destino(raiz: Path, destino: str) -> Path:
    """La carpeta donde se escribe: relativa, dentro de la asignatura, ni oculta ni rara."""
    if not isinstance(destino, str) or not destino.strip() or "\\" in destino:
        raise ErrorImportar(
            "DESTINO_NO_VALIDO", "El destino debe ser una carpeta de la asignatura."
        )
    if destino.startswith("/"):
        raise ErrorImportar(
            "DESTINO_NO_VALIDO", "El destino debe ser una carpeta de la asignatura."
        )
    partes = [p for p in destino.split("/") if p not in ("", ".")]
    if not partes or any(
        p.startswith(".")
        or p != p.strip()
        or p.endswith(".")
        or _NO_VALIDO_EN_WINDOWS.search(p)
        or p.split(".")[0].lower() in _RESERVADOS_WINDOWS
        for p in partes
    ):
        raise ErrorImportar(
            "DESTINO_NO_VALIDO", "El destino no puede ser oculto ni llevar símbolos raros."
        )
    try:
        carpeta = raiz.joinpath(*partes).resolve()
        carpeta.relative_to(raiz)
    except (ValueError, OSError, RuntimeError):
        raise ErrorImportar(
            "DESTINO_NO_VALIDO", "El destino no está dentro de la carpeta de la asignatura."
        ) from None
    if carpeta == raiz or (carpeta.exists() and not carpeta.is_dir()):
        raise ErrorImportar("DESTINO_NO_VALIDO", "El destino debe ser una carpeta nueva o vacía.")
    return carpeta


_PUERTO_POR_DEFECTO = {"https": 443, "http": 80}


def _servidor(url: str) -> tuple[str, str, int] | None:
    """(esquema, servidor, puerto) de una URL sin la ruta ni la barra final; ``None`` si no vale."""
    try:
        partes = urlsplit(url.strip())
        esquema = partes.scheme.lower()
        puerto = partes.port or _PUERTO_POR_DEFECTO.get(esquema, 0)
    except ValueError:
        return None
    if esquema not in _PUERTO_POR_DEFECTO or not partes.hostname:
        return None
    return esquema, partes.hostname.lower(), puerto


def _aula_configurada() -> str | None:
    """La URL del aula configurada (``tiza configurar``), o ``None`` si no hay ninguna."""
    try:
        global_ = config.cargar_global()
    except config.ErrorConfig:
        return None
    url = global_.get("url") if global_ else None
    return url if isinstance(url, str) and url.strip() else None


def _comprobar_como_nuevas(raiz: Path, copia: Copia) -> None:
    """Con ``como_nuevas`` la copia no puede ser de uno de los cursos reales de este aula.

    Sin ``origen`` ni huella se publicaría por nombre, sin la protección de lo que cambió en el
    aula: para ese curso se importa sin ``como_nuevas``.
    """
    if copia.curso_original not in config.reales_de_carpeta(raiz):
        return
    url = _aula_configurada()
    if url is not None and _servidor(url) != _servidor(copia.servidor):
        return
    raise ErrorImportar(
        "COPIA_DEL_MISMO_CURSO",
        "La copia es de uno de los cursos reales de tiza.toml. Impórtala sin --como-nuevas: "
        "así se publica sobre sus actividades y se avisa de lo que cambió en el aula.",
    )


def _comprobar_curso(raiz: Path, copia: Copia) -> None:
    """La copia tiene que ser de uno de los cursos reales y, si hay aula configurada, de ella."""
    otro = copia.curso_original not in config.reales_de_carpeta(raiz)
    url = _aula_configurada()
    if not otro and url is not None:
        otro = _servidor(url) != _servidor(copia.servidor)
    if otro:
        raise ErrorImportar(
            "COPIA_DE_OTRO_CURSO",
            "La copia no es de ninguno de los cursos reales de tiza.toml ni del aula configurada. "
            "Para realinear el aula real, pide la copia con «tiza copia real» (o con el id del "
            "curso real); --como-nuevas solo sirve para reutilizar otro curso.",
        )


# --------------------------------------------------------------------------- #
# Escritura sin sobrescribir
# --------------------------------------------------------------------------- #


def _dentro(ruta: Path, base: Path) -> None:
    """Que lo que se va a escribir sigue dentro de ``base`` (por si hay enlaces en el camino)."""
    try:
        ruta.parent.resolve().relative_to(base)
    except (ValueError, OSError, RuntimeError):
        raise ErrorImportar(
            "DESTINO_NO_VALIDO", "El destino no está dentro de la carpeta de la asignatura."
        ) from None


def _crear(ruta: Path, datos: bytes, base: Path) -> bool:
    """Crea ``ruta`` con ``datos``. ``False`` si ya existe: nunca se sobrescribe nada."""
    _dentro(ruta, base)  # antes de crear nada
    ruta.parent.mkdir(parents=True, exist_ok=True)
    _dentro(ruta, base)
    try:
        fichero = open(ruta, "xb")  # noqa: SIM115
    except FileExistsError:
        return False
    try:
        with fichero:
            fichero.write(datos)
    except BaseException:
        try:
            ruta.unlink()
        except OSError:
            pass
        raise
    return True


# --------------------------------------------------------------------------- #
# Del HTML de la copia al fichero de tiza
# --------------------------------------------------------------------------- #


@dataclass
class _Recurso:
    contenthash: str
    nombre: str  # el nombre ya saneado


def _recursos(actividad: ActividadCopia, html: str) -> tuple[str, list[_Recurso], bool]:
    """Cambia ``@@PLUGINFILE@@/<f>`` por ``recursos/<cmid>/<f limpio>`` y lista lo que extraer.

    Lo que la actividad no trae en la copia se deja sin cambiar (tercer valor ``True``): el
    docente lo verá al comprobar el fichero.
    """
    propios: dict[str, FicheroCopia] = {}
    for fichero in actividad.ficheros:
        if fichero.filearea == "package" or fichero.componente not in (
            "",
            f"mod_{actividad.modulo}",
        ):
            continue
        carpeta = fichero.ruta.strip("/")
        propios.setdefault(f"{carpeta}/{fichero.nombre}" if carpeta else fichero.nombre, fichero)
    usados: dict[str, str] = {}  # clave -> nombre con el que se escribe
    ocupados: dict[str, tuple[str, str]] = {}  # nombre sin mayúsculas -> (contenthash, nombre)
    recursos: list[_Recurso] = []
    faltan = False

    def cambiar(m: re.Match[str]) -> str:
        nonlocal faltan
        clave = unquote(m.group(1))
        fichero = propios.get(clave)
        if fichero is None:
            faltan = True
            return m.group(0)
        if clave not in usados:
            base = nombre_de_recurso(fichero.nombre)
            nombre, n = base, 1
            # Dos nombres que solo difieren en mayúsculas son el mismo fichero en Windows y macOS.
            while ocupados.get(nombre.casefold(), (fichero.contenthash, nombre))[0] != (
                fichero.contenthash
            ):
                n += 1
                cuerpo, punto, extension = base.rpartition(".")
                nombre = f"{cuerpo}-{n}.{extension}" if punto else f"{base}-{n}"
            if nombre.casefold() not in ocupados:
                ocupados[nombre.casefold()] = (fichero.contenthash, nombre)
                recursos.append(_Recurso(fichero.contenthash, nombre))
            # Mismo contenido con otras mayúsculas: se usa el nombre con el que se escribió.
            usados[clave] = ocupados[nombre.casefold()][1]
        return f"recursos/{actividad.cmid}/{usados[clave]}"

    return _REFERENCIA.sub(cambiar, html), recursos, faltan


class _Volcado(yaml.SafeDumper):
    """YAML del frontmatter: los textos de varias líneas, en bloque literal."""


def _texto_yaml(volcado: yaml.SafeDumper, dato: str) -> yaml.ScalarNode:
    estilo = "|" if "\n" in dato else None
    return volcado.represent_scalar("tag:yaml.org,2002:str", dato, style=estilo)


_Volcado.add_representer(str, _texto_yaml)


def _documento(frontmatter: Mapping[str, Any], cuerpo: str) -> str:
    cabecera = yaml.dump(
        dict(frontmatter),
        Dumper=_Volcado,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1_000_000,
    )
    return f"---\n{cabecera}---\n{cuerpo.strip(chr(10))}\n"


def _fecha(momento: datetime | None) -> str | None:
    return momento.astimezone(ZONA).strftime("%Y-%m-%d %H:%M") if momento is not None else None


def _sin_vacios(datos: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in datos.items() if v is not None}


# --------------------------------------------------------------------------- #
# El plan de cada actividad
# --------------------------------------------------------------------------- #


@dataclass
class _Entrada:
    """Una actividad de ``copia.json`` mientras se importa."""

    cmid: int
    modulo: str
    seccion: int
    nombre: str
    fichero: str | None = None
    estado: str = "IMPORTADA"
    avisos: list[str] = field(default_factory=list)
    huella_aula: str | None = None
    huella_fichero: str | None = None  # sha256 del fichero al marcarla cambiada en el aula

    def a_dict(self) -> dict[str, Any]:
        return {
            "cmid": self.cmid,
            "modulo": self.modulo,
            "seccion": self.seccion,
            "nombre": self.nombre,
            "fichero": self.fichero,
            "estado": self.estado,
            "detalle": " ".join(self.avisos)[:1000] or None,
            "huella_aula": self.huella_aula,
            "huella_fichero": self.huella_fichero,
        }


def _frontmatter(
    actividad: ActividadCopia,
    tipo: str,
    seccion: SeccionCopia,
    curso: int,
    como_nuevas: bool,
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    nombre = _texto_seguro(actividad.nombre, f"Actividad {actividad.cmid}")
    datos: dict[str, Any] = {
        "tipo": tipo,
        "nombre": nombre,
        "seccion": _texto_seguro(seccion.nombre) or seccion.numero,
    }
    if not como_nuevas:
        datos["origen"] = {"curso": curso, "cmid": actividad.cmid}
    fechas = actividad.fechas
    if tipo == "tarea":
        campos = {
            "apertura": fechas.get("allowsubmissionsfromdate"),
            "entrega": fechas.get("duedate"),
            "limite": fechas.get("cutoffdate"),
        }
    elif tipo == "cuestionario":
        campos = {"apertura": fechas.get("timeopen"), "cierre": fechas.get("timeclose")}
    else:
        campos = {}
    datos.update(_sin_vacios({k: _fecha(v) for k, v in campos.items()}))
    datos.update(extra)
    return datos


def _detalle_de_carga(ruta: Path, raiz: Path) -> tuple[str, str | None]:
    """(estado, aviso) de un fichero recién escrito, según lo que diga ``contenido.cargar``."""
    try:
        contenido.cargar(ruta, raiz=raiz)
    except contenido.ErrorContenido as error:
        if error.codigo == "HTML_PELIGROSO":
            return "HTML_NO_ADMITIDO", _texto_seguro(
                f"El filtro de tiza no admite: {error.detalle}"
            )
        texto = _texto_seguro(error.detalle)
        return "IMPORTADA", f"Al comprobarlo, tiza avisa de {error.codigo}: {texto}"[:255]
    return "IMPORTADA", None


# --------------------------------------------------------------------------- #
# copia.json: una entrada por curso
# --------------------------------------------------------------------------- #


def _leer_copia_json(dir_tiza: Path) -> dict | None:
    """El ``copia.json`` de antes, o ``None`` si no hay. Uno que no vale no se sobrescribe."""
    try:
        return estado.cargar_copia(dir_tiza)
    except estado.ErrorEstado as error:
        if error.codigo == "IMPORTACION_AUSENTE":
            return None
        raise ErrorImportar(
            "COPIA_INVALIDA",
            "No se puede leer .tiza/copia.json y no se ha sobrescrito: corrígelo o bórralo.",
        ) from None


def _previa(anterior: dict | None, curso: int, como_nuevas: bool) -> dict[int, dict]:
    """Las actividades de la importación anterior de este curso (o de «como nuevas»), por cmid."""
    if anterior is None:
        return {}
    if como_nuevas:
        entrada = anterior["como_nuevas"]
        if entrada is None or entrada["curso"] != curso:
            return {}
    else:
        entrada = anterior["cursos"].get(str(curso))
        if entrada is None:
            return {}
    return {a["cmid"]: a for a in entrada["actividades"]}


def _es_antigua(anterior: dict | None, datos: Copia, como_nuevas: bool) -> bool:
    """¿La copia es más antigua que la última importada de este curso? (solo con fechas de ambas)"""
    if anterior is None or como_nuevas or datos.fecha is None:
        return False
    ultima = anterior["cursos"].get(str(datos.curso_original))
    texto = ultima.get("fecha_copia") if ultima else None
    if texto is None:
        return False
    try:
        return datos.fecha < datetime.fromisoformat(texto)
    except ValueError:
        return False


def _fecha_de_copia(anterior: dict | None, datos: Copia, como_nuevas: bool) -> str | None:
    """La fecha de esta copia; si no la dice, se conserva la de la importación anterior."""
    if datos.fecha is not None:
        return datos.fecha.isoformat(timespec="seconds")
    if anterior is None or como_nuevas:
        return None
    ultima = anterior["cursos"].get(str(datos.curso_original))
    return ultima.get("fecha_copia") if ultima else None


def _datos_de_copia(
    anterior: dict | None,
    datos: Copia,
    entradas: list[_Entrada],
    previa: dict[int, dict],
    como_nuevas: bool,
    antigua: bool = False,
) -> dict[str, Any]:
    """``copia.json`` nuevo: solo cambia la entrada de este curso (o la de «como nuevas»).

    Dentro del curso, una actividad que ya no está en la copia conserva su entrada.
    """
    vistas = {e.cmid for e in entradas}
    actividades = [e.a_dict() for e in entradas]
    actividades += [a for cmid, a in previa.items() if cmid not in vistas]
    actividades.sort(key=lambda a: a["cmid"])
    entrada: dict[str, Any] = {
        "moodle": re.sub(r"[^0-9A-Za-z.() +-]", "", datos.moodle)[:60],
        "fecha_importacion": datetime.now(UTC).isoformat(timespec="seconds"),
        "fecha_copia": _fecha_de_copia(anterior, datos, como_nuevas),
        "secciones": [
            {
                "numero": s.numero,
                "nombre": _texto_seguro(s.nombre),
                "resumen_html_presente": bool(s.resumen_html.strip()),
            }
            for s in datos.secciones
        ],
        "actividades": actividades,
    }
    if antigua and anterior is not None:
        # Una copia más antigua no cambia lo que se sabe del aula: queda la última.
        ultima = anterior["cursos"][str(datos.curso_original)]
        entrada["moodle"] = ultima["moodle"]
        entrada["fecha_copia"] = ultima.get("fecha_copia")
        entrada["secciones"] = ultima["secciones"]
    cursos = dict(anterior["cursos"]) if anterior else {}
    nuevas = anterior["como_nuevas"] if anterior else None
    if como_nuevas:
        nuevas = {"curso": datos.curso_original, **entrada}
    else:
        cursos[str(datos.curso_original)] = entrada
    return {"version": 1, "cursos": cursos, "como_nuevas": nuevas}


# --------------------------------------------------------------------------- #
# La importación
# --------------------------------------------------------------------------- #


def importar(
    carpeta: str | Path,
    copia: str | Path,
    destino: str = "aula",
    como_nuevas: bool = False,
) -> ResumenImportacion:
    """Importa la copia ``copia`` a ficheros de tiza en ``<carpeta>/<destino>/``.

    Offline. Devuelve el resumen validado; el detalle de cada actividad queda en
    ``.tiza/copia.json``, que lleva una entrada por curso. Lanza ``ErrorImportar``,
    ``ErrorCopia`` (la copia no vale), ``ErrorLectura`` (la ruta de la copia no vale) o
    ``ErrorConfig`` (``tiza.toml`` no vale). Todo lo que se comprueba antes de escribir (copia,
    curso, destino, ``copia.json`` anterior) falla sin escribir nada.
    """
    raiz = Path(carpeta).resolve()
    ruta_copia = _ruta_de_copia(raiz, copia)
    base = _carpeta_destino(raiz, destino)
    datos = lector.abrir_copia(ruta_copia)
    if como_nuevas:
        _comprobar_como_nuevas(raiz, datos)
    else:
        _comprobar_curso(raiz, datos)
    secciones = {s.id: s for s in datos.secciones}
    for actividad in datos.actividades:
        if actividad.seccion_id not in secciones:
            raise ErrorCopia("COPIA_NO_VALIDA", "Una actividad apunta a una sección que no está.")

    dir_tiza = raiz / rutas.CARPETA_TRABAJO
    anterior = _leer_copia_json(dir_tiza)
    previa = _previa(anterior, datos.curso_original, como_nuevas)
    antigua = _es_antigua(anterior, datos, como_nuevas)
    publicados = _publicados_del_curso(dir_tiza, datos.curso_original, como_nuevas)
    entradas = []
    try:
        for actividad in datos.actividades:
            hecha = _importar_actividad(
                datos,
                actividad,
                secciones[actividad.seccion_id],
                raiz,
                base,
                dir_tiza,
                previa.get(actividad.cmid),
                como_nuevas,
                antigua,
                publicados,
            )
            if hecha is not None:
                entradas.append(hecha)
        escrito = estado.escribir_copia(
            dir_tiza,
            _datos_de_copia(anterior, datos, entradas, previa, como_nuevas, antigua),
        )
    except (OSError, estado.ErrorEstado):
        raise ErrorImportar(
            "IMPORTACION_NO_ESCRIBIBLE", "No se pudo escribir en la carpeta de la asignatura."
        ) from None
    recuento = {e: 0 for e in ESTADOS_IMPORTACION}
    for entrada in entradas:
        recuento[entrada.estado] += 1
    return ResumenImportacion(
        copia=escrito.relative_to(raiz).as_posix(),
        curso=datos.curso_original,
        como_nuevas=como_nuevas,
        actividades=len(entradas),
        estados=recuento,
    )


def _publicados_del_curso(
    dir_tiza: Path, curso: int, como_nuevas: bool
) -> dict[int, tuple[str, estado.Publicado]]:
    """cmid -> (ruta, ``Publicado``) de lo que tiza publicó en ``curso``; con ``como_nuevas``, nada.

    Un registro dañado para la importación antes de escribir nada (``PUBLICADOS_INVALIDO``).
    """
    if como_nuevas:
        return {}
    try:
        registro = estado.cargar_publicados(dir_tiza, curso)
    except estado.ErrorEstado:
        raise ErrorImportar(
            "PUBLICADOS_INVALIDO",
            "El registro de lo publicado (.tiza/publicados.json) está dañado: no se importa.",
        ) from None
    return {p.cmid: (ruta, p) for ruta, p in registro.items()}


def _publicada_por_tiza(
    datos: Copia,
    actividad: ActividadCopia,
    entrada: _Entrada,
    tipo: str,
    registrada: tuple[str, estado.Publicado],
    raiz: Path,
    dir_tiza: Path,
) -> _Entrada:
    """La actividad la publicó tiza y su fichero sigue ahí: no se crea otro, solo se compara.

    Con la huella del registro igual a la del aula, nada que hacer. Si difiere (o el registro no
    tiene huella, y no se puede saber si el docente la tocó), la versión del aula queda en
    ``.tiza/copia/<cmid>.html``, el registro toma la huella nueva y la marca del fichero actual:
    mientras siga así, al publicar en real se pregunta antes de pisar el cambio del aula.
    """
    ruta_registrada, publicado = registrada
    huella = tipos.huella_aula(actividad.nombre, actividad.html, actividad.fechas)
    entrada.fichero = ruta_registrada
    entrada.huella_aula = huella
    if publicado.huella == huella:
        entrada.estado = "PUBLICADA_POR_TIZA"
        return entrada
    ruta = raiz / ruta_registrada
    html, recursos, _faltan = _recursos(actividad, actividad.html)
    entrada.estado = "PUBLICADA_POR_TIZA_CAMBIADA"
    marca = _huella_del_fichero(ruta)
    entrada.huella_fichero = marca or estado.MARCA_ILEGIBLE
    _extraer(datos, recursos, ruta.parent, actividad.cmid, raiz)
    estado.guardar_version_de_copia(dir_tiza, actividad.cmid, html)
    estado.guardar_publicado(
        dir_tiza,
        datos.curso_original,
        ruta_registrada,
        estado.Publicado(actividad.cmid, tipo, huella=huella, marca=entrada.huella_fichero),
    )
    entrada.avisos.append(estado.AVISO_CAMBIADA.format(cmid=actividad.cmid))
    if marca is None:
        entrada.avisos.append(_AVISO_FICHERO_ILEGIBLE)
    return entrada


def _rechazar(entrada: _Entrada, estado_: str, motivo: str, previa: dict | None) -> _Entrada:
    """La actividad no se importa; si ya estaba importada, su entrada conserva fichero y huella."""
    entrada.estado = estado_
    entrada.avisos[:] = [_texto_seguro(motivo)]
    if previa is not None:
        entrada.fichero = previa["fichero"]
        entrada.huella_aula = previa["huella_aula"]
        entrada.huella_fichero = previa["huella_fichero"]
    return entrada


def _huella_del_fichero(ruta: Path) -> str | None:
    """El sha256 de los bytes del fichero del docente (los mismos que ve ``contenido.cargar``)."""
    try:
        datos = leer_bytes_acotado(ruta, contenido.MAX_DOCUMENTO_BYTES)
    except OSError:  # incluye FicheroNoSeguro
        return None
    return hashlib.sha256(datos).hexdigest()


_AVISO_FICHERO_ILEGIBLE = (
    "No se pudo leer tu fichero: no se publicará hasta que se pueda leer; "
    "pide una copia nueva e impórtala."
)
AVISO_COPIA_ANTIGUA = "Copia más antigua que la última importada: esta actividad no se ha tocado."


def _detalle_previo(previa: dict | None) -> str:
    """El ``detalle`` de la importación anterior, sin el aviso de copia antigua (no se acumula)."""
    detalle = previa["detalle"] if previa else None
    return (detalle or "").replace(AVISO_COPIA_ANTIGUA, "").strip()


def _conservar(entrada: _Entrada, previa: dict) -> _Entrada:
    """Copia más antigua que la última importada: la actividad queda como estaba."""
    entrada.estado = previa["estado"]
    entrada.fichero = previa["fichero"]
    entrada.huella_aula = previa["huella_aula"]
    entrada.huella_fichero = previa["huella_fichero"]
    entrada.avisos[:] = [AVISO_COPIA_ANTIGUA]
    if previo := _detalle_previo(previa):
        entrada.avisos.append(previo)
    return entrada


def _fichero_previo(previa: dict | None, raiz: Path, base: Path) -> Path | None:
    """El fichero de la importación anterior, si sigue ahí y está dentro del destino."""
    if previa is None or not previa["fichero"]:
        return None
    ruta = raiz / previa["fichero"]
    try:
        ruta.parent.resolve().relative_to(base)
    except (ValueError, OSError, RuntimeError):
        return None
    return ruta if os.path.lexists(ruta) else None


def _importar_actividad(
    datos: Copia,
    actividad: ActividadCopia,
    seccion: SeccionCopia,
    raiz: Path,
    base: Path,
    dir_tiza: Path,
    previa: dict | None,
    como_nuevas: bool,
    antigua: bool = False,
    publicados: Mapping[int, tuple[str, estado.Publicado]] | None = None,
) -> _Entrada | None:
    nombre = _texto_seguro(actividad.nombre, f"Actividad {actividad.cmid}")
    entrada = _Entrada(
        cmid=actividad.cmid, modulo=actividad.modulo, seccion=seccion.numero, nombre=nombre
    )
    if antigua:
        # Una copia más antigua no escribe nada nuevo: solo conserva lo que ya estaba importado.
        return _conservar(entrada, previa) if previa is not None else None
    tipo = tipos.de_modulo(actividad.modulo)
    if tipo is None:
        return _rechazar(
            entrada,
            "TIPO_NO_GESTIONADO",
            "tiza no gestiona este tipo de actividad: no se importa.",
            previa,
        )
    registrada = (publicados or {}).get(actividad.cmid)
    if registrada is not None and registrada[1].tipo == tipo:
        if os.path.lexists(raiz / registrada[0]):
            return _publicada_por_tiza(datos, actividad, entrada, tipo, registrada, raiz, dir_tiza)
    extension = EXTENSION.get(tipo, ".md")
    carpeta_seccion = base / f"{seccion.numero:02d}-{nombre_seguro(seccion.nombre)}"
    ruta = carpeta_seccion / f"{nombre_seguro(actividad.nombre)}-{actividad.cmid}{extension}"
    ruta = _fichero_previo(previa, raiz, base) or ruta
    existe = os.path.lexists(ruta)

    html, recursos, faltan = _recursos(actividad, actividad.html)
    extra: dict[str, Any] = {}
    if tipo == "cuestionario":
        preguntas, motivos = convertir_preguntas(actividad)
        if motivos:
            return _rechazar(
                entrada,
                "PREGUNTAS_NO_ADMITIDAS",
                "Preguntas que tiza no admite: " + ", ".join(motivos),
                previa,
            )
        extra, motivos = ajustes_del_cuestionario(actividad)
        if motivos:
            return _rechazar(
                entrada,
                "AJUSTES_NO_ADMITIDOS",
                "Ajustes que tiza no puede publicar sin cambiarlos: " + ", ".join(motivos),
                previa,
            )
        extra["preguntas"] = preguntas
    elif tipo == "h5p":
        paquete = next(
            (f for f in actividad.ficheros if f.contenthash == actividad.paquete_h5p), None
        )
        if paquete is None or actividad.paquete_h5p not in datos.recursos:
            return _rechazar(
                entrada,
                "TIPO_NO_GESTIONADO",
                "La actividad H5P no trae su paquete .h5p en la copia.",
                previa,
            )
        nombre_paquete = nombre_de_recurso(paquete.nombre)
        if not nombre_paquete.lower().endswith(".h5p"):
            nombre_paquete += ".h5p"
        recursos.append(_Recurso(paquete.contenthash, nombre_paquete))
        extra["paquete"] = f"recursos/{actividad.cmid}/{nombre_paquete}"

    # Lo que hay en el aula según esta copia (para detectar cambios hechos después).
    huella = None
    if not como_nuevas:
        huella = tipos.huella_aula(actividad.nombre, actividad.html, actividad.fechas)
    entrada.huella_aula = huella
    entrada.fichero = ruta.relative_to(raiz).as_posix() if existe else None
    if existe:
        entrada.estado = "YA_IMPORTADO"
        guardada = previa["huella_aula"] if previa else None
        # Una marca anterior sigue valiendo hasta que el docente toque su fichero y publique.
        entrada.huella_fichero = previa["huella_fichero"] if previa else None
        previo = _detalle_previo(previa)
        if huella is not None and guardada is not None and guardada != huella:
            entrada.estado = "CAMBIADA_DESDE_LA_IMPORTACION"
            # El fichero tal como está ahora: si al publicar sigue igual, no se juntó el cambio.
            marca = _huella_del_fichero(ruta)
            entrada.huella_fichero = marca or estado.MARCA_ILEGIBLE
            _extraer(datos, recursos, ruta.parent, actividad.cmid, raiz)
            estado.guardar_version_de_copia(dir_tiza, actividad.cmid, html)
            if previo := estado.quitar_aviso_cambiada(previo):
                entrada.avisos.append(previo)
            entrada.avisos.append(estado.AVISO_CAMBIADA.format(cmid=actividad.cmid))
            if marca is None:
                entrada.avisos.append(_AVISO_FICHERO_ILEGIBLE)
        else:
            if entrada.huella_fichero == estado.MARCA_ILEGIBLE:
                # Si ahora se puede leer, la marca pasa a ser la de verdad.
                entrada.huella_fichero = _huella_del_fichero(ruta) or estado.MARCA_ILEGIBLE
            if previo:  # el detalle de antes (p. ej. los archivos adicionales de una tarea) sigue
                entrada.avisos.append(previo)
        return entrada

    frontmatter = _frontmatter(actividad, tipo, seccion, datos.curso_original, como_nuevas, extra)
    avisos = entrada.avisos
    estado_final = "IMPORTADA"
    if not actividad.formato_html:
        estado_final = "HTML_NO_ADMITIDO"
        avisos.append("Tiene un formato de texto no HTML: tiza solo publica HTML.")
    filtrado = False
    try:
        filtro.analizar(html)
    except filtro.HtmlPeligroso as exc:
        filtrado = True
        estado_final = "HTML_NO_ADMITIDO"
        avisos.append(_texto_seguro(f"El filtro de tiza no admite: {exc.detalle}"))
    problemas = _extraer(datos, recursos, ruta.parent, actividad.cmid, base)
    entrada.fichero = ruta.relative_to(raiz).as_posix()
    cuerpo = html if extension == ".html" else html_como_markdown(html)
    if not _crear(ruta, _documento(frontmatter, cuerpo).encode("utf-8"), base):
        entrada.estado = "YA_IMPORTADO"
        avisos.clear()
        return entrada
    if not filtrado:
        resultado, aviso = _detalle_de_carga(ruta, raiz)
        if resultado == "HTML_NO_ADMITIDO":
            estado_final = resultado
        if aviso is not None:
            avisos.append(aviso)
    if faltan and "falta" not in problemas:
        problemas.append("falta")
    avisos += [_PROBLEMAS_DE_RECURSOS[p] for p in problemas]
    if nombre != " ".join(actividad.nombre.split()):
        avisos.append("El nombre tenía símbolos o era demasiado largo y se ha cambiado.")
    if tipo == "tarea" and any(f.filearea == "introattachment" for f in actividad.ficheros):
        avisos.append(
            "Tiene archivos adicionales: no están en el fichero y la tarea nueva no los tendrá."
            if como_nuevas
            else "Tiene archivos adicionales: no están en el fichero, pero se conservan en el aula."
        )
    if actividad.fecha_recordatorio is not None:
        avisos.append("Tiene activado el recordatorio de calificar: tiza lo desactiva al publicar.")
    entrada.estado = estado_final
    return entrada


_PROBLEMAS_DE_RECURSOS = {
    "falta": "Falta en la copia algún fichero que la actividad usa.",
    "existia": "Un fichero de recursos no se escribió porque ya existía otro con ese nombre.",
}


def _extraer(
    datos: Copia, recursos: list[_Recurso], carpeta: Path, cmid: int, limite: Path
) -> list[str]:
    """Escribe en ``recursos/<cmid>/`` lo que falte; un fichero que ya está no se toca.

    Devuelve los problemas (claves de ``_PROBLEMAS_DE_RECURSOS``): un recurso que no viene en la
    copia, o que no se pudo crear porque ya había un fichero con ese nombre.
    """
    problemas: list[str] = []
    for recurso in recursos:
        if recurso.contenthash not in datos.recursos:
            problemas.append("falta")
            continue
        destino = carpeta / "recursos" / str(cmid) / recurso.nombre
        if os.path.lexists(destino):
            continue
        if not _crear(destino, lector.leer_recurso(datos, recurso.contenthash), limite):
            problemas.append("existia")
    return list(dict.fromkeys(problemas))
