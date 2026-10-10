"""Carga, valida y transforma ficheros de contenido (Markdown o HTML) con frontmatter YAML.

Todo el trabajo es offline: no hay ninguna petición de red en este módulo.
"""

from __future__ import annotations

import copy
import hashlib
import html as _html
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

import yaml
from bs4 import BeautifulSoup, Tag
from markdown_it import MarkdownIt

from . import filtro, rutas
from .ficheros import FicheroNoSeguro, asegurar_directorio, escribir_texto, leer_bytes_acotado
from .filtro import CONTROL as _CONTROL

if TYPE_CHECKING:  # el registro importa este módulo: el import va dentro de las funciones
    from . import tipos

__all__ = [
    "EXTENSIONES",
    "MAX_DOCUMENTO_BYTES",
    "MAX_RECURSO_BYTES",
    "ErrorContenido",
    "ActividadH5P",
    "Cuestionario",
    "Documento",
    "Fechas",
    "Finalizacion",
    "MarcaH5P",
    "Opcion",
    "PaqueteH5P",
    "Pregunta",
    "Recurso",
    "Restricciones",
    "TarjetaH5P",
    "TextoH5P",
    "cargar",
    "describir_itinerario",
    "hash_documento",
    "html_para_moodle",
    "html_para_preview",
    "numero_texto",
    "previsualizar",
]

EXTENSIONES = (".md", ".html", ".htm")  # en minúsculas; el resto de ficheros no es contenido
_EXTENSIONES_HTML = frozenset({".html", ".htm"})
# Orden canónico de los tipos; el dueño es ``tipos.TIPOS`` y un test comprueba que no
# se separan (aquí no se puede importar el registro: el registro importa este módulo).
TTIPOS = ("pagina", "tarea", "cuestionario", "etiqueta", "h5p")
CAMPOS_ITINERARIO = {"finalizacion", "fecha_esperada", "restricciones"}
CAMPOS_COMUNES = {"tipo", "nombre", "seccion"} | CAMPOS_ITINERARIO
CAMPOS_RESTRICCIONES = {"desde", "hasta", "completar", "ocultar_si_no_cumple"}
MAX_DEPENDENCIAS = 10
MAX_PAQUETE_H5P_BYTES = 64 * 1024 * 1024  # el .h5p subido
MAX_DOCUMENTO_BYTES = 2 * 1024 * 1024  # el .md o .html; los recursos se miden aparte
MAX_RECURSO_BYTES = 200 * 1024 * 1024
_TROZO_HASH = 1024 * 1024
_FICHEROS_DE_TIZA = frozenset({rutas.FICHERO_ASIGNATURA, rutas.FICHERO_CALENDARIO})

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL)


class ErrorContenido(Exception):
    """Error de contenido con un código estable (sin texto de Moodle)."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


@dataclass(frozen=True)
class Recurso:
    """Fichero local referenciado desde el Markdown."""

    nombre: str
    ruta: Path


@dataclass(frozen=True)
class PaqueteH5P:
    """``.h5p`` subido, ya validado y listo para reempaquetar."""

    nombre: str
    ruta: Path
    machine_name: str = ""
    titulo: str | None = None
    libreria: str | None = None  # «H5P.Blanks 1.14»
    ficheros: tuple[str, ...] = ()  # entradas que se conservan
    externos: tuple[str, ...] = ()  # URL https de content.json, para el docente
    descartadas: tuple[str, ...] = ()  # carpetas de librerías que se tiran siempre


@dataclass(frozen=True)
class Fechas:
    """Fechas de una tarea, ya convertidas a la zona del aula."""

    apertura: datetime
    entrega: datetime
    limite: datetime | None


@dataclass(frozen=True)
class Finalizacion:
    """Cuándo cuenta una actividad como completada (``ninguna`` la desactiva)."""

    modo: str
    esperada: datetime | None = None  # «completar antes de»: solo informativa en Moodle


@dataclass(frozen=True)
class Restricciones:
    """Cuándo está disponible: por fecha y por haber completado otras actividades de tiza.

    Todo vacío es «quitar las restricciones de tiza». Solo se admiten estas dos clases de
    condición, siempre unidas con «y»; nunca grupos, perfiles ni datos del alumnado.
    """

    desde: datetime | None = None
    hasta: datetime | None = None
    completar: tuple[str, ...] = ()  # ficheros .md de la carpeta, normalizados (con «/»)
    ocultar: bool = False  # sin cumplirse: oculta (por defecto, en gris con la condición)


@dataclass(frozen=True)
class Opcion:
    """Opción de una pregunta de opción múltiple, ya validada."""

    texto: str  # lo que se escribió (Markdown)
    html: str  # el texto renderizado, tal como se publica
    correcta: bool
    retro: str | None = None  # retroalimentación de esta opción (Markdown)
    retro_html: str | None = None


@dataclass(frozen=True)
class Pregunta:
    """Pregunta de un cuestionario, ya validada."""

    tipo: str
    enunciado: str  # lo que se escribió (Markdown)
    html: str  # el enunciado renderizado, tal como se publica
    opciones: tuple[Opcion, ...] = ()
    respuesta: str | None = None  # «verdadero» o «falso»
    aceptadas: tuple[str, ...] = ()  # respuestas válidas de una pregunta corta
    mayusculas: bool = False  # distinguir mayúsculas en la respuesta corta
    valor: float | None = None  # valor exacto de una pregunta numérica
    tolerancia: float = 0.0  # margen de la pregunta numérica, >= 0
    retro: str | None = None  # retroalimentación general (Markdown)
    retro_html: str | None = None


@dataclass(frozen=True)
class Cuestionario:
    """Ajustes y preguntas de un cuestionario, ya validados."""

    preguntas: tuple[Pregunta, ...]
    apertura: datetime | None = None
    cierre: datetime | None = None
    tiempo_limite: int | None = None  # minutos, 1..600
    intentos: int = 1  # 0 significa ilimitados
    mezclar_respuestas: bool = True
    externos: tuple[str, ...] = ()  # enlaces externos de las preguntas
    incrustados: tuple[str, ...] = ()  # iframes de las preguntas, ya normalizados


@dataclass(frozen=True)
class MarcaH5P:
    """Un hueco o palabra marcada con ``[[...]]`` y sus alternativas."""

    respuestas: tuple[str, ...]


@dataclass(frozen=True)
class TextoH5P:
    """Texto con marcas ya traducido a la sintaxis de H5P.

    ``partes`` son los tramos ya renderizados (HTML validado) o el texto tal
    cual si el campo de H5P no admite etiquetas (``plano=True``).
    """

    partes: tuple[str | MarcaH5P, ...]
    h5p: str  # el texto tal como va en content.json
    plano: bool = False


@dataclass(frozen=True)
class TarjetaH5P:
    """Par anverso/reverso de una actividad de tarjetas."""

    anverso: str  # lo que se escribió (Markdown)
    reverso: str
    anverso_html: str
    reverso_html: str


@dataclass(frozen=True)
class ActividadH5P:
    """Actividad H5P generada a partir del YAML, ya validada."""

    tipo: str
    textos: tuple[TextoH5P, ...] = ()  # rellenar_huecos
    texto: TextoH5P | None = None  # arrastrar_palabras / marcar_palabras
    enunciado: str | None = None  # marcar_palabras (tarea)
    enunciado_html: str | None = None
    distractores: tuple[str, ...] = ()
    tarjetas: tuple[TarjetaH5P, ...] = ()
    mayusculas: bool = False  # distinguir mayúsculas en rellenar_huecos
    calificacion: int = 10  # calificación máxima, 1..100
    reintentar: bool = True
    ver_solucion: bool = True


@dataclass
class Documento:
    """Documento cargado y validado."""

    ruta: Path
    tipo: str
    nombre: str
    seccion: int | str  # número de sección o nombre (se crea si no existe)
    cuerpo: str  # lo que escribió el docente (Markdown o HTML), sin el frontmatter
    html: str  # el cuerpo ya validado, tal como se publica
    recursos: list[Recurso]
    fechas: Fechas | None = None
    cuestionario: Cuestionario | None = None
    h5p: ActividadH5P | None = None
    paquete: PaqueteH5P | None = None  # .h5p ya hecho que se sube reempaquetado
    # None: el .md no lo declara y lo que haya en el aula se conserva.
    finalizacion: Finalizacion | None = None
    restricciones: Restricciones | None = None
    hash_cargado: str = ""  # hash al cargar; si cambia un recurso después, no se publica
    enlaces_externos: list[str] = field(default_factory=list)  # los ve el docente antes de real
    incrustados: list[str] = field(default_factory=list)  # URL de los iframes, también las ve
    _mapa_recursos: dict[str, Recurso] = field(default_factory=dict, repr=False)
    _arbol: Tag | None = field(default=None, repr=False)  # el <body> validado


def cargar(
    ruta: str | Path, zona: str | ZoneInfo = "Europe/Madrid", *, raiz: Path | None = None
) -> Documento:
    """Carga un fichero .md o .html, valida su frontmatter y devuelve el documento.

    ``raiz`` es la carpeta de la asignatura (ya resuelta). Con ella, un recurso local
    tiene que estar dentro, no puede ser un fichero oculto ni ``tiza.toml`` y se comprueba
    antes de mirar si existe, para que quien pide la subida no averigüe qué hay fuera.
    Sin ella no se aplican esas reglas.

    Raises:
        ErrorContenido: con un código estable cuando el fichero no es válido.
    """
    zona = ZoneInfo(zona) if isinstance(zona, str) else zona
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ErrorContenido("FICHERO_AUSENTE", f"no existe el fichero {ruta.name}")
    try:
        texto = leer_bytes_acotado(ruta, MAX_DOCUMENTO_BYTES, enlaces=True).decode("utf-8")
    except FicheroNoSeguro as exc:
        if exc.motivo == "grande":
            raise ErrorContenido(
                "FICHERO_DEMASIADO_GRANDE",
                f"«{ruta.name}» pesa más de {MAX_DOCUMENTO_BYTES // 2**20} MB",
            ) from None
        raise ErrorContenido("FICHERO_AUSENTE", f"no existe el fichero {ruta.name}") from None
    except OSError:
        raise ErrorContenido("FICHERO_AUSENTE", f"no se pudo leer {ruta.name}") from None
    except UnicodeDecodeError:
        raise ErrorContenido("CODIFICACION_INVALIDA", "el fichero no es UTF-8") from None

    datos, cuerpo = _separar_frontmatter(texto)
    doc = _validar(datos, cuerpo, ruta, zona, raiz)
    try:
        analisis = filtro.analizar(_a_html(ruta, cuerpo))
    except filtro.HtmlPeligroso as exc:
        raise ErrorContenido("HTML_PELIGROSO", exc.detalle) from None
    doc._arbol = analisis.cuerpo
    doc.html = filtro.serializar(analisis.cuerpo)
    doc.recursos, doc._mapa_recursos = _recursos_locales(analisis.locales, ruta.parent, raiz)
    if doc.paquete is not None and any(
        recurso.nombre == doc.paquete.nombre for recurso in doc.recursos
    ):
        raise ErrorContenido(
            "RECURSO_DUPLICADO",
            f"el nombre «{doc.paquete.nombre}» se usa para el paquete y para un recurso",
        )
    doc.enlaces_externos = _sin_repetir(analisis.externos, doc.cuestionario)
    if doc.paquete is not None:
        for url in doc.paquete.externos:
            if url not in doc.enlaces_externos:
                doc.enlaces_externos.append(url)
    doc.incrustados = _sin_repetir(analisis.incrustados, doc.cuestionario, externos=False)
    doc.hash_cargado = hash_documento(doc)
    return doc


def _sin_repetir(
    urls: list[str], cuestionario: Cuestionario | None, *, externos: bool = True
) -> list[str]:
    """Los enlaces del cuerpo y los de las preguntas, sin repetir y en orden."""
    salida = list(urls)
    if cuestionario is not None:
        otros = cuestionario.externos if externos else cuestionario.incrustados
        for url in otros:
            if url not in salida:
                salida.append(url)
    return salida


# --------------------------------------------------------------------------- #
# Frontmatter y validación
# --------------------------------------------------------------------------- #


def _separar_frontmatter(texto: str) -> tuple[Any, str]:
    texto = texto.lstrip("\ufeff")
    coincidencia = _FRONTMATTER.match(texto)
    if not coincidencia:
        raise ErrorContenido("FRONTMATTER_INVALIDO", "falta el bloque YAML entre ---")
    try:
        datos = yaml.safe_load(coincidencia.group(1))
    except yaml.YAMLError:
        raise ErrorContenido("FRONTMATTER_INVALIDO", "el bloque YAML no se puede leer") from None
    if not isinstance(datos, dict):
        raise ErrorContenido("FRONTMATTER_INVALIDO", "el bloque YAML debe ser un mapa")
    return datos, coincidencia.group(2)


def _validar(
    datos: dict[str, Any], cuerpo: str, ruta: Path, zona: ZoneInfo, raiz: Path | None = None
) -> Documento:
    for campo in ("tipo", "nombre", "seccion"):
        if campo not in datos or datos[campo] is None:
            raise ErrorContenido("CAMPO_FALTANTE", f"falta el campo «{campo}»")

    tipo = datos["tipo"]
    if tipo not in TTIPOS:
        raise ErrorContenido(
            "TIPO_INVALIDO", "tipo debe ser pagina, tarea, cuestionario, etiqueta o h5p"
        )
    from . import tipos  # diferido: el registro importa este módulo al cargarse

    adapter = tipos.obtener(tipo)

    permitidos = CAMPOS_COMUNES | adapter.campos
    for campo in datos:
        if campo not in permitidos:
            raise ErrorContenido("CAMPO_DESCONOCIDO", f"campo «{campo}» no permitido")

    nombre = datos["nombre"]
    if (
        not isinstance(nombre, str)
        or not nombre.strip()
        or len(nombre) > 255
        or _CONTROL.search(nombre)
    ):
        raise ErrorContenido("NOMBRE_INVALIDO", "el nombre debe ser texto de 1 a 255 caracteres")

    seccion = datos["seccion"]
    if isinstance(seccion, str):
        seccion = seccion.strip()
        if (
            not seccion
            or len(seccion) > 255
            or re.search(r"[<>]", seccion)
            or _CONTROL.search(seccion)
        ):
            raise ErrorContenido(
                "SECCION_INVALIDA",
                "el nombre de la sección debe ser texto de 1 a 255 caracteres, sin < ni >",
            )
    elif isinstance(seccion, bool) or not isinstance(seccion, int) or seccion < 0:
        raise ErrorContenido(
            "SECCION_INVALIDA", "la sección debe ser un número entero >= 0 o un nombre"
        )

    finalizacion = _validar_finalizacion(datos, adapter, zona)
    restricciones = _validar_restricciones(datos, ruta, zona, raiz)
    ctx = tipos.Contexto(
        zona=zona,
        ruta=ruta,
        raiz=raiz,
        fecha=lambda valor, hora: _fecha(valor, zona, hora),
        render=_render,
        paquete_h5p=lambda valor: _resolver_paquete(valor, ruta.parent, raiz),
    )
    extras = adapter.validar(datos, ctx)

    return Documento(
        ruta=ruta,
        tipo=tipo,
        nombre=nombre.strip(),
        seccion=seccion,
        cuerpo=cuerpo,
        html="",
        recursos=[],
        fechas=extras.fechas,
        cuestionario=extras.cuestionario,
        h5p=extras.h5p,
        paquete=extras.paquete,
        finalizacion=finalizacion,
        restricciones=restricciones,
    )


# --------------------------------------------------------------------------- #
# Finalización y restricciones
# --------------------------------------------------------------------------- #


def _validar_finalizacion(
    datos: dict[str, Any], adapter: tipos.Tipo, zona: ZoneInfo
) -> Finalizacion | None:
    if "finalizacion" not in datos:
        if "fecha_esperada" in datos:
            raise ErrorContenido(
                "FINALIZACION_NO_ADMITIDA", "fecha_esperada necesita «finalizacion»"
            )
        return None
    modo = datos["finalizacion"]
    admitidos = adapter.finalizaciones
    if not isinstance(modo, str) or modo not in admitidos:
        raise ErrorContenido(
            "FINALIZACION_NO_ADMITIDA",
            f"en {adapter.nombre}, finalizacion debe ser " + ", ".join(admitidos),
        )
    esperada = None
    if "fecha_esperada" in datos:
        if modo == "ninguna":
            raise ErrorContenido(
                "FINALIZACION_NO_ADMITIDA", "fecha_esperada no vale con «finalizacion: ninguna»"
            )
        if datos["fecha_esperada"] is None:
            raise ErrorContenido("FECHA_INVALIDA", "fecha_esperada no puede estar vacía")
        esperada = _fecha(datos["fecha_esperada"], zona, time(23, 59))
    return Finalizacion(modo=modo, esperada=esperada)


def _validar_restricciones(
    datos: dict[str, Any], ruta: Path, zona: ZoneInfo, raiz: Path | None
) -> Restricciones | None:
    if "restricciones" not in datos:
        return None
    valor = datos["restricciones"]
    if not isinstance(valor, dict):
        raise ErrorContenido("RESTRICCION_INVALIDA", "restricciones debe ser un mapa")
    for campo in valor:
        if campo not in CAMPOS_RESTRICCIONES:
            raise ErrorContenido(
                "CAMPO_DESCONOCIDO", f"campo «{campo}» no permitido en restricciones"
            )
    desde = _fecha(valor["desde"], zona, time(0, 0)) if valor.get("desde") is not None else None
    hasta = _fecha(valor["hasta"], zona, time(23, 59)) if valor.get("hasta") is not None else None
    if desde is not None and hasta is not None and not desde < hasta:
        raise ErrorContenido("FECHAS_INCOHERENTES", "debe cumplirse desde < hasta")
    ocultar = valor.get("ocultar_si_no_cumple", False)
    if not isinstance(ocultar, bool):
        raise ErrorContenido("RESTRICCION_INVALIDA", "ocultar_si_no_cumple debe ser true o false")
    completar = _validar_dependencias(valor.get("completar", []), ruta, raiz)
    return Restricciones(desde=desde, hasta=hasta, completar=completar, ocultar=ocultar)


def _validar_dependencias(valor: Any, ruta: Path, raiz: Path | None) -> tuple[str, ...]:
    """Las rutas de ``completar``, relativas a la carpeta, dentro de ella y sin repetir."""
    if not isinstance(valor, list):
        raise ErrorContenido("RESTRICCION_INVALIDA", "completar debe ser una lista de ficheros")
    if len(valor) > MAX_DEPENDENCIAS:
        raise ErrorContenido(
            "RESTRICCION_INVALIDA", f"completar admite como mucho {MAX_DEPENDENCIAS} ficheros"
        )
    carpeta = raiz if raiz is not None else ruta.parent.resolve()
    propia = ruta.resolve()
    salida: list[str] = []
    for item in valor:
        if not isinstance(item, str) or not item.strip() or _CONTROL.search(item):
            raise ErrorContenido("RESTRICCION_INVALIDA", "cada fichero de completar debe ser texto")
        destino = _resolver_local(ruta.parent, item.strip())
        if raiz is not None:
            _exigir_permitido(destino, raiz)  # antes de mirar si existe
        elif not destino.is_relative_to(carpeta):
            raise ErrorContenido(
                "RUTA_FUERA_DE_CARPETA", "un fichero de completar está fuera de la carpeta"
            )
        if destino.suffix.lower() not in EXTENSIONES:
            raise ErrorContenido(
                "RESTRICCION_INVALIDA", f"«{destino.name}» no es un fichero de contenido"
            )
        if destino == propia:
            raise ErrorContenido(
                "DEPENDENCIA_CIRCULAR", "un documento no puede depender de sí mismo"
            )
        relativa = destino.relative_to(carpeta).as_posix()
        if relativa in salida:
            raise ErrorContenido("RESTRICCION_INVALIDA", f"«{destino.name}» está repetido")
        salida.append(relativa)
    return tuple(salida)


_MODOS_LLANOS = {
    "ninguna": "no se marca como completada",
    "manual": "marcarla el alumno como hecha",
    "ver": "verla",
    "entregar": "entregarla",
    "calificar": "tener nota",
}


def _formato_fecha(momento: datetime) -> str:
    # Formato del docente para el itinerario; los adapters formatean con
    # ``tipos.base.formato_fecha``, que produce exactamente el mismo texto.
    return momento.strftime("%Y-%m-%d %H:%M")


def describir_itinerario(doc: Documento, nombres: dict[str, str] | None = None) -> list[str]:
    """El itinerario en lenguaje llano, solo con lo que dice el ``.md``.

    ``nombres``: nombre de cada fichero de ``completar``, tal como está en su ``.md``.
    """
    lineas: list[str] = []
    if doc.finalizacion is not None:
        modo = doc.finalizacion.modo
        lineas.append(
            "No se marca como completada"
            if modo == "ninguna"
            else f"Se completa al: {_MODOS_LLANOS[modo]}"
        )
        if doc.finalizacion.esperada is not None:
            lineas.append(f"Fecha esperada: {_formato_fecha(doc.finalizacion.esperada)}")
    restricciones = doc.restricciones
    if restricciones is not None:
        condiciones: list[str] = []
        if restricciones.desde is not None:
            condiciones.append(f"desde {_formato_fecha(restricciones.desde)}")
        if restricciones.hasta is not None:
            condiciones.append(f"hasta {_formato_fecha(restricciones.hasta)}")
        for fichero in restricciones.completar:
            nombre = (nombres or {}).get(fichero)
            etiqueta = f"«{nombre}» ({fichero})" if nombre else fichero
            condiciones.append(f"cuando completen {etiqueta}")
        if not condiciones:
            lineas.append("Se quitan las restricciones de tiza")
        else:
            lineas.append("Disponible: " + " · ".join(condiciones))
            lineas.append(
                "Si no se cumple: se oculta"
                if restricciones.ocultar
                else "Si no se cumple: se ve en gris"
            )
    return lineas


# --------------------------------------------------------------------------- #
# Paquete .h5p subido
# --------------------------------------------------------------------------- #


def _resolver_paquete(valor: str, base: Path, raiz: Path | None) -> PaqueteH5P:
    """El ``.h5p`` como paquete validado: dentro de la carpeta y con un tope de tamaño."""
    ruta = _resolver_local(base, valor)
    if raiz is not None:
        _exigir_permitido(ruta, raiz)  # antes de mirar si existe
    if not ruta.is_file():
        raise ErrorContenido(
            "RECURSO_AUSENTE", f"no existe el paquete «{Path(unquote(valor)).name}»"
        )
    try:
        leer_bytes_acotado(ruta, MAX_PAQUETE_H5P_BYTES, enlaces=True)
    except FicheroNoSeguro as exc:
        if exc.motivo == "grande":
            raise ErrorContenido(
                "PAQUETE_H5P_DEMASIADO_GRANDE",
                f"«{ruta.name}» pesa más de {MAX_PAQUETE_H5P_BYTES // 2**20} MB",
            ) from None
        raise ErrorContenido(
            "RECURSO_AUSENTE", f"no se pudo leer el paquete «{ruta.name}»"
        ) from None
    except OSError:
        raise ErrorContenido(
            "RECURSO_AUSENTE", f"no se pudo leer el paquete «{ruta.name}»"
        ) from None
    from .h5p import validar_paquete  # import diferido: h5p importa contenido

    return validar_paquete(ruta)


def numero_texto(valor: float | int) -> str:
    """Un número como lo escribe el docente: sin decimales de más ni notación científica."""
    numero = float(valor)
    if numero == int(numero) and abs(numero) < 1e15:
        return str(int(numero))
    return repr(numero)


def _fecha(valor: Any, zona: ZoneInfo, hora_por_defecto: time) -> datetime:
    if isinstance(valor, datetime):
        momento = valor
    elif isinstance(valor, date):
        momento = datetime.combine(valor, hora_por_defecto)
    elif isinstance(valor, str):
        limpio = valor.strip()
        candidato = limpio.replace(" ", "T")
        try:
            momento = datetime.fromisoformat(candidato)
        except ValueError:
            raise ErrorContenido("FECHA_INVALIDA", f"«{limpio}» no es una fecha válida") from None
        if len(limpio) == 10:
            momento = datetime.combine(momento.date(), hora_por_defecto)
    else:
        raise ErrorContenido("FECHA_INVALIDA", "la fecha debe ser texto ISO")
    if momento.tzinfo is None:
        return momento.replace(tzinfo=zona)
    return momento.astimezone(zona)


# --------------------------------------------------------------------------- #
# Render y filtro de seguridad
# --------------------------------------------------------------------------- #


def _a_html(ruta: Path, cuerpo: str) -> str:
    """Un .html se usa tal cual (sin Markdown); cualquier otro fichero es Markdown."""
    return cuerpo if ruta.suffix.lower() in _EXTENSIONES_HTML else _render(cuerpo)


def _render(cuerpo: str) -> str:
    # Sin bloques de código por sangría: el HTML sangrado tras una línea en blanco
    # se publicaba escapado dentro de <pre><code>. El código va entre ```.
    markdown = MarkdownIt("commonmark", {"html": True}).enable("table").disable("code")
    # Un bloque HTML que empieza por <div> termina en la primera línea en blanco, y lo
    # que queda de un <pre> se leería como Markdown. Dentro de <pre> las líneas en
    # blanco se sustituyen por una marca y se restauran tras el render.
    cuerpo = _PRE.sub(lambda m: _BLANCO.sub(_MARCA, m.group(0)), cuerpo)
    cuerpo, formulas = _apartar_formulas(cuerpo)
    salida = markdown.render(cuerpo).replace(_MARCA, "")
    return _FORMULA_MARCADA.sub(lambda m: formulas[int(m.group(1))], salida)


# Fórmulas LaTeX: se apartan antes del Markdown y vuelven como texto, con sus
# delimitadores, para que ``*`` y ``_`` no se lean como cursiva ni se pierdan las barras.
_FORMULA_INICIO = "\ue001"
_FORMULA_FIN = "\ue002"
_FORMULA_MARCADA = re.compile(f"{_FORMULA_INICIO}(\\d+){_FORMULA_FIN}")
_MAX_FORMULA = 2000
_MAX_FORMULAS = 500
_TEXTO_O_FORMULA = re.compile(
    r"(?P<codigo>```.*?```|~~~.*?~~~|`[^`\n]*`|<pre\b.*?</pre>)"
    r"|(?P<formula>\$\$.*?\$\$|\\\(.*?\\\)|\\\[.*?\\\])"
    r"|(?P<abierta>\$\$|\\\(|\\\[)",
    re.DOTALL | re.IGNORECASE,
)


def _apartar_formulas(cuerpo: str) -> tuple[str, list[str]]:
    formulas: list[str] = []

    def apartar(m: re.Match[str]) -> str:
        if m.group("codigo") is not None:
            return m.group(0)
        if m.group("abierta") is not None:
            raise ErrorContenido(
                "FORMULA_SIN_CERRAR",
                f"la fórmula que empieza por «{m.group('abierta')}» no se cierra",
            )
        formula = m.group("formula")
        if len(formula) > _MAX_FORMULA or len(formulas) >= _MAX_FORMULAS:
            raise ErrorContenido(
                "FORMULA_INVALIDA",
                f"una fórmula supera {_MAX_FORMULA} caracteres o hay más de {_MAX_FORMULAS}",
            )
        formulas.append(_html.escape(formula, quote=False))
        return f"{_FORMULA_INICIO}{len(formulas) - 1}{_FORMULA_FIN}"

    return _TEXTO_O_FORMULA.sub(apartar, cuerpo), formulas


_MARCA = "\ue000"  # carácter de uso privado: no aparece en texto real
_PRE = re.compile(r"<pre\b.*?</pre>", re.DOTALL | re.IGNORECASE)
_BLANCO = re.compile(r"^[ \t]*$", re.MULTILINE)


# --------------------------------------------------------------------------- #
# Recursos locales
# --------------------------------------------------------------------------- #


def _resolver_local(base: Path, valor: str) -> Path:
    limpio = urlsplit(valor).path
    return (base / unquote(limpio)).resolve()


def _exigir_permitido(ruta: Path, raiz: Path) -> None:
    """Un recurso va dentro de la carpeta de la asignatura y no es oculto ni de tiza."""
    try:
        relativa = ruta.relative_to(raiz)
    except ValueError:
        raise ErrorContenido(
            "RUTA_FUERA_DE_CARPETA", "un recurso está fuera de la carpeta de la asignatura"
        ) from None
    if relativa.name in _FICHEROS_DE_TIZA or any(parte.startswith(".") for parte in relativa.parts):
        raise ErrorContenido(
            "RECURSO_NO_PERMITIDO", f"«{relativa.name}» es un fichero oculto o de configuración"
        )


def _recursos_locales(
    locales: list[str], base: Path, raiz: Path | None = None
) -> tuple[list[Recurso], dict[str, Recurso]]:
    """Los ficheros que hay que subir y el mapa «URL escrita en el documento → recurso»."""
    recursos: list[Recurso] = []
    mapa: dict[str, Recurso] = {}
    por_nombre: dict[str, Path] = {}
    for valor in locales:
        ruta = _resolver_local(base, valor)
        if raiz is not None:
            _exigir_permitido(ruta, raiz)  # antes de mirar si existe
        if not ruta.is_file():
            raise ErrorContenido(
                "RECURSO_AUSENTE", f"no existe el recurso «{Path(unquote(valor)).name}»"
            )
        if ruta.stat().st_size > MAX_RECURSO_BYTES:
            raise ErrorContenido(
                "RECURSO_DEMASIADO_GRANDE",
                f"«{ruta.name}» pesa más de {MAX_RECURSO_BYTES // 2**20} MB",
            )
        anterior = por_nombre.get(ruta.name)
        if anterior is not None and anterior != ruta:
            raise ErrorContenido(
                "RECURSO_DUPLICADO",
                f"el nombre «{ruta.name}» se usa para dos ficheros distintos",
            )
        recurso = Recurso(nombre=ruta.name, ruta=ruta)
        if anterior is None:
            recursos.append(recurso)
            por_nombre[ruta.name] = ruta
        mapa[valor] = recurso
    return recursos, mapa


def _sustituir(doc: Documento, reemplazo) -> Tag:
    """Copia del árbol validado con las URL de los recursos locales reemplazadas."""
    assert doc._arbol is not None
    copia = copy.copy(doc._arbol)
    for etiqueta in copia.find_all(["img", "a"]):
        atributo = "src" if etiqueta.name == "img" else "href"
        valor = etiqueta.get(atributo)
        if isinstance(valor, str) and valor in doc._mapa_recursos:
            etiqueta[atributo] = reemplazo(valor, doc._mapa_recursos[valor])
    return copia


def html_para_moodle(doc: Documento) -> str:
    """HTML con los recursos locales sustituidos por referencias @@PLUGINFILE@@."""

    def reemplazo(_valor: str, recurso: Recurso) -> str:
        return f"@@PLUGINFILE@@/{recurso.nombre}"

    return filtro.serializar(_sustituir(doc, reemplazo))


def html_para_preview(doc: Documento, dir_preview: Path) -> str:
    """HTML con los recursos locales apuntando, de forma relativa, al original."""

    def reemplazo(_valor: str, recurso: Recurso) -> str:
        try:
            relativa = os.path.relpath(recurso.ruta, dir_preview)
        except ValueError:  # Windows: el recurso y la vista previa están en unidades distintas
            return Path(recurso.ruta).resolve().as_uri()
        return relativa.replace(os.sep, "/")

    copia = _sustituir(doc, reemplazo)
    # La vista previa no carga nada de fuera: cada iframe se sustituye por un recuadro.
    for iframe in copia.find_all("iframe"):
        # Dentro de un enlace no se puede anidar otro.
        enlazable = iframe.find_parent("a") is None
        iframe.replace_with(_marcador_incrustado(str(iframe.get("src")), enlazable))
    return filtro.serializar(copia)


def _marcador_incrustado(url: str, enlazable: bool = True) -> Tag:
    # Un <span> de bloque y no un <p>: el iframe puede estar dentro de un párrafo.
    sopa = BeautifulSoup("", "html.parser")
    caja = sopa.new_tag(
        "span", style="display:block;border:2px dashed #666;padding:.75rem;background:#f4f4f4"
    )
    servidor = sopa.new_tag("strong")
    servidor.string = urlsplit(url).netloc
    enlace = sopa.new_tag("a", href=url, target="_blank", rel="noopener noreferrer")
    enlace.string = "abrir en otra pestaña"
    partes: list[Tag | str] = ["Aquí irá contenido incrustado de ", servidor]
    if enlazable:
        partes += [": ", enlace]
    for parte in partes:
        caja.append(parte)
    return caja


# --------------------------------------------------------------------------- #
# Vista previa y hash
# --------------------------------------------------------------------------- #


def previsualizar(doc: Documento, dir_tiza: str | Path, *, nombre: str | None = None) -> Path:
    """Escribe .tiza/preview/<nombre>.html y devuelve su ruta.

    ``nombre`` es el del fichero de la vista, sin extensión; por defecto, el del documento.
    El agente escribe en esa carpeta y puede dejar allí un enlace simbólico. La escritura es
    atómica (sustituye el enlace en vez de escribir a través de él) y ni ``.tiza`` ni
    ``preview`` pueden ser enlaces: ``DIRECTORIO_NO_SEGURO``.
    """
    raiz = Path(dir_tiza)
    try:
        asegurar_directorio(raiz)
        dir_preview = asegurar_directorio(raiz / "preview")
    except FicheroNoSeguro:
        raise ErrorContenido(
            "DIRECTORIO_NO_SEGURO",
            f"«{rutas.CARPETA_TRABAJO}» o «{rutas.CARPETA_TRABAJO}/preview» es un enlace, no una carpeta",
        ) from None
    destino = dir_preview / f"{nombre or doc.ruta.stem}.html"
    escribir_texto(destino, _plantilla(doc, dir_preview))
    return destino


def _plantilla(doc: Documento, dir_preview: Path) -> str:
    from . import tipos  # diferido: el registro importa este módulo

    tipo = tipos.obtener(doc.tipo)
    metadatos = [
        ("Tipo", doc.tipo),
        ("Nombre", doc.nombre),
        ("Sección", str(doc.seccion)),
    ]
    metadatos.extend(tipo.metadatos_preview(doc))
    for linea in describir_itinerario(doc):
        clave, _, resto = linea.partition(": ")
        metadatos.append((clave, resto) if resto else ("Itinerario", linea))
    filas = "\n".join(
        f"<li><strong>{clave}:</strong> {_html.escape(valor)}</li>" for clave, valor in metadatos
    )
    contenido = html_para_preview(doc, dir_preview)
    extra = tipo.extra_preview(doc)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="es">\n<head>\n<meta charset="utf-8">\n'
        f"<title>VISTA PREVIA — {_html.escape(doc.nombre)}</title>\n"
        "</head>\n<body>\n"
        '<p style="border:2px solid #b00;padding:.5rem;font-weight:bold">'
        "VISTA PREVIA: este contenido todavía no se ha publicado.</p>\n"
        f"<h1>{_html.escape(doc.nombre)}</h1>\n<ul>{filas}</ul>\n<hr>\n"
        f"{contenido}\n{extra}\n"
        "</body>\n</html>\n"
    )


def hash_documento(doc: Documento) -> str:
    """Hash estable del contenido y sus recursos (no depende de la ruta).

    Cada tipo aporta sus bytes por los tres huecos del adapter (fechas, contenido
    específico y extra) en el orden de siempre, para no invalidar los hashes ya
    verificados en pruebas.
    """
    from . import tipos  # diferido: el registro importa este módulo

    tipo = tipos.obtener(doc.tipo)
    resumen = hashlib.sha256()
    resumen.update(f"{doc.tipo}\n{doc.nombre}\n{doc.seccion}\n".encode())
    tipo.hash_fechas(doc, resumen)
    resumen.update(b"\n")
    resumen.update(doc.cuerpo.encode("utf-8"))
    tipo.hash_contenido(doc, resumen)
    if doc.finalizacion is not None or doc.restricciones is not None:
        resumen.update(b"\n--itinerario--\n")
        resumen.update(repr(doc.finalizacion).encode("utf-8"))
        resumen.update(repr(doc.restricciones).encode("utf-8"))
    tipo.hash_extra(doc, resumen)
    for recurso in sorted(doc.recursos, key=lambda item: item.nombre):
        resumen.update(b"\n--recurso--\n")
        resumen.update(recurso.nombre.encode("utf-8"))
        resumen.update(b"\n")
        with recurso.ruta.open("rb") as fichero:
            while trozo := fichero.read(_TROZO_HASH):
                resumen.update(trozo)
    return resumen.hexdigest()
