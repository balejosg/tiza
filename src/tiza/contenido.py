"""Carga, valida y transforma ficheros de contenido (Markdown o HTML) con frontmatter YAML.

Todo el trabajo es offline: no hay ninguna petición de red en este módulo.
"""

from __future__ import annotations

import copy
import hashlib
import html as _html
import math
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

import yaml
from bs4 import BeautifulSoup, Tag
from markdown_it import MarkdownIt

from . import filtro, rutas, tipos
from .ficheros import FicheroNoSeguro, asegurar_directorio, escribir_texto, leer_bytes_acotado
from .filtro import CONTROL as _CONTROL
from .tipos.cuestionario import CAMPOS_CUESTIONARIO
from .tipos.h5p import CAMPOS_H5P

__all__ = [
    "EXTENSIONES",
    "MAX_DOCUMENTO_BYTES",
    "MAX_RECURSO_BYTES",
    "CAMPOS_CUESTIONARIO",
    "CAMPOS_H5P",
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
# El orden canónico de los tipos y sus campos propios lo fija el registro (tipos/).
TTIPOS = tipos.TIPOS
CAMPOS_ITINERARIO = {"finalizacion", "fecha_esperada", "restricciones"}
CAMPOS_COMUNES = {"tipo", "nombre", "seccion"} | CAMPOS_ITINERARIO
CAMPOS_RESTRICCIONES = {"desde", "hasta", "completar", "ocultar_si_no_cumple"}
MAX_DEPENDENCIAS = 10

# Actividades H5P generadas. Las etiquetas que admite cada campo de las
# librerías (semantics) limitan el Markdown en línea que se conserva.
TIPOS_H5P = ("rellenar_huecos", "arrastrar_palabras", "marcar_palabras", "tarjetas")
NOMBRES_H5P = {
    "rellenar_huecos": "Rellenar huecos",
    "arrastrar_palabras": "Arrastrar palabras",
    "marcar_palabras": "Marcar palabras",
    "tarjetas": "Tarjetas",
}
_CAMPOS_TARJETA = {"anverso", "reverso"}
_CAMPOS_H5P_POR_TIPO = {
    "rellenar_huecos": {
        "tipo",
        "textos",
        "mayusculas",
        "calificacion",
        "reintentar",
        "ver_solucion",
    },
    "arrastrar_palabras": {
        "tipo",
        "texto",
        "distractores",
        "calificacion",
        "reintentar",
        "ver_solucion",
    },
    "marcar_palabras": {"tipo", "enunciado", "texto", "calificacion", "reintentar", "ver_solucion"},
    "tarjetas": {"tipo", "tarjetas", "reintentar"},
}
# Markdown en línea que sobrevive al filtro de cada campo H5P (negrita, cursiva…).
_INLINE_HUECOS = frozenset({"strong", "em", "u", "del", "s", "code", "br"})
_INLINE_MARCAR = frozenset({"strong", "em", "u", "code", "br"})
_INLINE_TARJETA = frozenset({"strong", "em", "code", "br"})
MAX_TEXTOS_H5P = 30
MAX_TARJETAS = 100
MAX_TEXTO_H5P = 5000
MAX_RESPUESTA_H5P = 200
MAX_DISTRACTORES = 20
MAX_ALTERNATIVAS_H5P = 10
MAX_PAQUETE_H5P_BYTES = 64 * 1024 * 1024  # el .h5p subido

TIPOS_PREGUNTA = ("opcion_multiple", "verdadero_falso", "respuesta_corta", "numerica")
NOMBRES_PREGUNTA = {
    "opcion_multiple": "Opción múltiple",
    "verdadero_falso": "Verdadero o falso",
    "respuesta_corta": "Respuesta corta",
    "numerica": "Numérica",
}
_CAMPOS_PREGUNTA_BASE = {"tipo", "enunciado", "retro"}
_CAMPOS_PREGUNTA = {
    "opcion_multiple": _CAMPOS_PREGUNTA_BASE | {"opciones"},
    "verdadero_falso": _CAMPOS_PREGUNTA_BASE | {"respuesta"},
    "respuesta_corta": _CAMPOS_PREGUNTA_BASE | {"aceptadas", "mayusculas"},
    "numerica": _CAMPOS_PREGUNTA_BASE | {"valor", "tolerancia"},
}
_CAMPOS_OPCION = {"texto", "correcta", "retro"}
MAX_PREGUNTAS = 100
MAX_ENUNCIADO = 5000
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
    fechas = None
    cuestionario = None
    h5p = None
    paquete = None
    if tipo == "tarea":
        for campo in ("apertura", "entrega"):
            if datos.get(campo) is None:
                raise ErrorContenido("CAMPO_FALTANTE", f"falta el campo «{campo}»")
        apertura = _fecha(datos["apertura"], zona, time(0, 0))
        entrega = _fecha(datos["entrega"], zona, time(23, 59))
        limite = (
            _fecha(datos["limite"], zona, time(23, 59)) if datos.get("limite") is not None else None
        )
        if not (apertura < entrega and (limite is None or entrega < limite)):
            raise ErrorContenido(
                "FECHAS_INCOHERENTES",
                "debe cumplirse apertura < entrega" + (" < límite" if limite else ""),
            )
        fechas = Fechas(apertura=apertura, entrega=entrega, limite=limite)
    elif tipo == "cuestionario":
        cuestionario = _validar_cuestionario(datos, zona)
    elif tipo == "h5p":
        h5p, paquete = _validar_h5p(datos, ruta.parent, raiz)

    return Documento(
        ruta=ruta,
        tipo=tipo,
        nombre=nombre.strip(),
        seccion=seccion,
        cuerpo=cuerpo,
        html="",
        recursos=[],
        fechas=fechas,
        cuestionario=cuestionario,
        h5p=h5p,
        paquete=paquete,
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
# Validación de un cuestionario
# --------------------------------------------------------------------------- #


def _validar_cuestionario(datos: dict[str, Any], zona: ZoneInfo) -> Cuestionario:
    apertura = (
        _fecha(datos["apertura"], zona, time(0, 0)) if datos.get("apertura") is not None else None
    )
    cierre = (
        _fecha(datos["cierre"], zona, time(23, 59)) if datos.get("cierre") is not None else None
    )
    if apertura is not None and cierre is not None and not apertura < cierre:
        raise ErrorContenido("FECHAS_INCOHERENTES", "debe cumplirse apertura < cierre")

    tiempo_limite = datos.get("tiempo_limite")
    if tiempo_limite is not None and (
        isinstance(tiempo_limite, bool)
        or not isinstance(tiempo_limite, int)
        or not 1 <= tiempo_limite <= 600
    ):
        raise ErrorContenido(
            "AJUSTE_INVALIDO", "«tiempo_limite» debe ser un número entero entre 1 y 600 (minutos)"
        )

    intentos = _leer_intentos(datos.get("intentos"))
    mezclar = datos.get("mezclar_respuestas")
    if mezclar is None:
        mezclar = True
    elif not isinstance(mezclar, bool):
        raise ErrorContenido("AJUSTE_INVALIDO", "«mezclar_respuestas» debe ser true o false")

    valor_preguntas = datos.get("preguntas")
    if not isinstance(valor_preguntas, list) or not 1 <= len(valor_preguntas) <= MAX_PREGUNTAS:
        raise ErrorContenido(
            "PREGUNTAS_INVALIDAS",
            f"«preguntas» debe ser una lista de 1 a {MAX_PREGUNTAS} preguntas",
        )

    externos: list[str] = []
    incrustados: list[str] = []
    preguntas = tuple(
        _validar_pregunta(pregunta, numero, externos, incrustados)
        for numero, pregunta in enumerate(valor_preguntas, 1)
    )
    return Cuestionario(
        preguntas=preguntas,
        apertura=apertura,
        cierre=cierre,
        tiempo_limite=tiempo_limite,
        intentos=intentos,
        mezclar_respuestas=mezclar,
        externos=tuple(externos),
        incrustados=tuple(incrustados),
    )


def _leer_intentos(valor: Any) -> int:
    if valor is None:
        return 1
    if isinstance(valor, str) and valor.strip().casefold() == "ilimitados":
        return 0
    if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= 10:
        raise ErrorContenido(
            "AJUSTE_INVALIDO", "«intentos» debe ser un número entero entre 1 y 10 o «ilimitados»"
        )
    return valor


def _validar_pregunta(
    valor: Any, numero: int, externos: list[str], incrustados: list[str]
) -> Pregunta:
    donde = f"pregunta {numero}"
    if not isinstance(valor, dict):
        raise ErrorContenido("PREGUNTAS_INVALIDAS", f"{donde}: cada pregunta debe ser un mapa")

    tipo = valor.get("tipo")
    if tipo not in TIPOS_PREGUNTA:
        raise ErrorContenido(
            "TIPO_PREGUNTA_INVALIDO",
            f"{donde}: «tipo» debe ser uno de: {', '.join(TIPOS_PREGUNTA)}",
        )
    for campo in valor:
        if campo not in _CAMPOS_PREGUNTA[tipo]:
            raise ErrorContenido(
                "CAMPO_DESCONOCIDO", f"{donde}: campo «{campo}» no permitido en «{tipo}»"
            )

    enunciado = valor.get("enunciado")
    if not isinstance(enunciado, str) or not enunciado.strip() or len(enunciado) > MAX_ENUNCIADO:
        raise ErrorContenido(
            "ENUNCIADO_INVALIDO",
            f"{donde}: el enunciado debe ser texto de 1 a {MAX_ENUNCIADO} caracteres",
        )
    html = _html_de_pregunta(enunciado, donde, externos, incrustados)

    retro = _texto_opcional(valor.get("retro"), donde, "retro")
    retro_html = (
        _html_de_pregunta(retro, donde, externos, incrustados) if retro is not None else None
    )

    if tipo == "opcion_multiple":
        opciones = _validar_opciones(valor.get("opciones"), donde, externos, incrustados)
        return Pregunta(
            tipo=tipo,
            enunciado=enunciado,
            html=html,
            opciones=opciones,
            retro=retro,
            retro_html=retro_html,
        )
    if tipo == "verdadero_falso":
        respuesta = valor.get("respuesta")
        if respuesta not in ("verdadero", "falso"):
            raise ErrorContenido(
                "RESPUESTA_PREGUNTA_INVALIDA", f"{donde}: «respuesta» debe ser verdadero o falso"
            )
        return Pregunta(
            tipo=tipo,
            enunciado=enunciado,
            html=html,
            respuesta=respuesta,
            retro=retro,
            retro_html=retro_html,
        )
    if tipo == "respuesta_corta":
        aceptadas = valor.get("aceptadas")
        if (
            not isinstance(aceptadas, list)
            or not aceptadas
            or any(not isinstance(a, str) or not a.strip() for a in aceptadas)
        ):
            raise ErrorContenido(
                "RESPUESTA_PREGUNTA_INVALIDA",
                f"{donde}: «aceptadas» debe ser una lista de respuestas no vacías",
            )
        mayusculas = valor.get("mayusculas")
        if mayusculas is not None and not isinstance(mayusculas, bool):
            raise ErrorContenido(
                "RESPUESTA_PREGUNTA_INVALIDA", f"{donde}: «mayusculas» debe ser true o false"
            )
        return Pregunta(
            tipo=tipo,
            enunciado=enunciado,
            html=html,
            aceptadas=tuple(a.strip() for a in aceptadas),
            mayusculas=bool(mayusculas),
            retro=retro,
            retro_html=retro_html,
        )
    # numerica
    valor_num = valor.get("valor")
    if (
        isinstance(valor_num, bool)
        or not isinstance(valor_num, (int, float))
        or not math.isfinite(valor_num)
    ):
        raise ErrorContenido("RESPUESTA_PREGUNTA_INVALIDA", f"{donde}: «valor» debe ser un número")
    tolerancia = valor.get("tolerancia")
    if tolerancia is None:
        tolerancia = 0
    if (
        isinstance(tolerancia, bool)
        or not isinstance(tolerancia, (int, float))
        or not math.isfinite(tolerancia)
        or tolerancia < 0
    ):
        raise ErrorContenido(
            "RESPUESTA_PREGUNTA_INVALIDA",
            f"{donde}: «tolerancia» debe ser un número mayor o igual que 0",
        )
    return Pregunta(
        tipo=tipo,
        enunciado=enunciado,
        html=html,
        valor=float(valor_num),
        tolerancia=float(tolerancia),
        retro=retro,
        retro_html=retro_html,
    )


def _validar_opciones(
    valor: Any, donde: str, externos: list[str], incrustados: list[str]
) -> tuple[Opcion, ...]:
    if not isinstance(valor, list) or not 2 <= len(valor) <= 10:
        raise ErrorContenido(
            "OPCIONES_INVALIDAS", f"{donde}: «opciones» debe ser una lista de 2 a 10"
        )
    opciones: list[Opcion] = []
    for numero, opcion in enumerate(valor, 1):
        donde_opcion = f"{donde}, opción {numero}"
        if not isinstance(opcion, dict):
            raise ErrorContenido("OPCIONES_INVALIDAS", f"{donde_opcion}: debe ser un mapa")
        for campo in opcion:
            if campo not in _CAMPOS_OPCION:
                raise ErrorContenido(
                    "CAMPO_DESCONOCIDO", f"{donde_opcion}: campo «{campo}» no permitido"
                )
        texto = opcion.get("texto")
        if not isinstance(texto, str) or not texto.strip():
            raise ErrorContenido("OPCIONES_INVALIDAS", f"{donde_opcion}: falta «texto»")
        correcta = opcion.get("correcta")
        if correcta is not None and not isinstance(correcta, bool):
            raise ErrorContenido(
                "OPCIONES_INVALIDAS", f"{donde_opcion}: «correcta» debe ser true o false"
            )
        retro = _texto_opcional(opcion.get("retro"), donde_opcion, "retro")
        opciones.append(
            Opcion(
                texto=texto,
                html=_html_de_pregunta(texto, donde_opcion, externos, incrustados),
                correcta=bool(correcta),
                retro=retro,
                retro_html=(
                    _html_de_pregunta(retro, donde_opcion, externos, incrustados)
                    if retro is not None
                    else None
                ),
            )
        )
    if not any(opcion.correcta for opcion in opciones):
        raise ErrorContenido(
            "OPCIONES_INVALIDAS", f"{donde}: ninguna opción está marcada como correcta"
        )
    return tuple(opciones)


def _texto_opcional(valor: Any, donde: str, campo: str) -> str | None:
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ErrorContenido("PREGUNTAS_INVALIDAS", f"{donde}: «{campo}» debe ser texto")
    return valor


def _html_de_pregunta(texto: str, donde: str, externos: list[str], incrustados: list[str]) -> str:
    """Renderiza un campo Markdown de una pregunta y lo pasa por el filtro."""
    try:
        analisis = filtro.analizar(_render(texto))
    except filtro.HtmlPeligroso as exc:
        raise ErrorContenido("HTML_PELIGROSO", f"{donde}: {exc.detalle}") from None
    if analisis.locales:
        nombre = Path(unquote(urlsplit(analisis.locales[0]).path)).name
        detalle = f"«{nombre}»" if nombre else "una imagen o un enlace a fichero"
        raise ErrorContenido(
            "RECURSO_EN_PREGUNTA", f"{donde}: no se admiten recursos locales ({detalle})"
        )
    for url in analisis.externos:
        if url not in externos:
            externos.append(url)
    for url in analisis.incrustados:
        if url not in incrustados:
            incrustados.append(url)
    return filtro.serializar(analisis.cuerpo)


# --------------------------------------------------------------------------- #
# Validación de una actividad H5P
# --------------------------------------------------------------------------- #


def _validar_h5p(
    datos: dict[str, Any], base: Path, raiz: Path | None
) -> tuple[ActividadH5P | None, PaqueteH5P | None]:
    """Valida «actividad» (generada) o «paquete» (subido); nunca los dos."""
    actividad = datos.get("actividad")
    paquete = datos.get("paquete")
    if actividad is not None and paquete is not None:
        raise ErrorContenido(
            "CAMPOS_INCOMPATIBLES", "una actividad H5P lleva «actividad» o «paquete», no los dos"
        )
    if actividad is None and paquete is None:
        raise ErrorContenido("CAMPO_FALTANTE", "falta el campo «actividad» o «paquete»")
    if paquete is not None:
        if not isinstance(paquete, str) or not paquete.strip():
            raise ErrorContenido(
                "PAQUETE_H5P_INVALIDO", "«paquete» debe ser la ruta de un fichero .h5p"
            )
        if not paquete.strip().lower().endswith(".h5p"):
            raise ErrorContenido("PAQUETE_H5P_INVALIDO", "«paquete» debe apuntar a un fichero .h5p")
        return None, _resolver_paquete(paquete.strip(), base, raiz)
    return _leer_actividad_h5p(actividad), None


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


def _leer_actividad_h5p(valor: Any) -> ActividadH5P:
    if not isinstance(valor, dict):
        raise ErrorContenido("ACTIVIDAD_H5P_INVALIDA", "«actividad» debe ser un mapa")
    tipo = valor.get("tipo")
    if tipo not in TIPOS_H5P:
        raise ErrorContenido(
            "ACTIVIDAD_H5P_INVALIDA", f"«tipo» debe ser uno de: {', '.join(TIPOS_H5P)}"
        )
    for campo in valor:
        if campo not in _CAMPOS_H5P_POR_TIPO[tipo]:
            raise ErrorContenido(
                "CAMPO_DESCONOCIDO", f"actividad: campo «{campo}» no permitido en «{tipo}»"
            )
    reintentar = _bool_h5p(valor.get("reintentar"), "reintentar", True)
    if tipo == "rellenar_huecos":
        textos_valor = valor.get("textos")
        if not isinstance(textos_valor, list) or not 1 <= len(textos_valor) <= MAX_TEXTOS_H5P:
            raise ErrorContenido(
                "ACTIVIDAD_H5P_INVALIDA",
                f"«textos» debe ser una lista de 1 a {MAX_TEXTOS_H5P} textos",
            )
        textos = tuple(
            _texto_con_marcas(texto, f"textos {numero}", permitidas=_INLINE_HUECOS, huecos=True)
            for numero, texto in enumerate(textos_valor, 1)
        )
        return ActividadH5P(
            tipo=tipo,
            textos=textos,
            mayusculas=_bool_h5p(valor.get("mayusculas"), "mayusculas", False),
            calificacion=_calificacion_h5p(valor.get("calificacion")),
            reintentar=reintentar,
            ver_solucion=_bool_h5p(valor.get("ver_solucion"), "ver_solucion", True),
        )
    if tipo == "arrastrar_palabras":
        texto = valor.get("texto")
        distrayentes = valor.get("distractores")
        if distrayentes is None:
            distractores: tuple[str, ...] = ()
        elif (
            not isinstance(distrayentes, list)
            or len(distrayentes) > MAX_DISTRACTORES
            or any(not isinstance(item, str) or not item.strip() for item in distrayentes)
        ):
            raise ErrorContenido(
                "ACTIVIDAD_H5P_INVALIDA",
                f"«distractores» debe ser una lista de hasta {MAX_DISTRACTORES} palabras",
            )
        else:
            distractores = tuple(
                _respuesta_h5p(item, f"distractor {numero}")
                for numero, item in enumerate(distrayentes, 1)
            )
        return ActividadH5P(
            tipo=tipo,
            texto=_texto_con_marcas(
                texto, "texto", permitidas=frozenset(), huecos=True, plano=True
            ),
            distractores=distractores,
            calificacion=_calificacion_h5p(valor.get("calificacion")),
            reintentar=reintentar,
            ver_solucion=_bool_h5p(valor.get("ver_solucion"), "ver_solucion", True),
        )
    if tipo == "marcar_palabras":
        enunciado = valor.get("enunciado")
        if not isinstance(enunciado, str) or not enunciado.strip():
            raise ErrorContenido(
                "ACTIVIDAD_H5P_INVALIDA", "«enunciado» debe ser texto de 1 a 5000 caracteres"
            )
        return ActividadH5P(
            tipo=tipo,
            texto=_texto_con_marcas(
                valor.get("texto"), "texto", permitidas=_INLINE_MARCAR, huecos=True
            ),
            enunciado=enunciado,
            enunciado_html=_html_inline_h5p(enunciado, "enunciado", _INLINE_MARCAR),
            calificacion=_calificacion_h5p(valor.get("calificacion")),
            reintentar=reintentar,
            ver_solucion=_bool_h5p(valor.get("ver_solucion"), "ver_solucion", True),
        )
    # tarjetas
    tarjetas_valor = valor.get("tarjetas")
    if not isinstance(tarjetas_valor, list) or not 1 <= len(tarjetas_valor) <= MAX_TARJETAS:
        raise ErrorContenido(
            "ACTIVIDAD_H5P_INVALIDA", f"«tarjetas» debe ser una lista de 1 a {MAX_TARJETAS}"
        )
    tarjetas: list[TarjetaH5P] = []
    for numero, tarjeta in enumerate(tarjetas_valor, 1):
        donde = f"tarjeta {numero}"
        if not isinstance(tarjeta, dict):
            raise ErrorContenido("ACTIVIDAD_H5P_INVALIDA", f"{donde}: debe ser un mapa")
        for campo in tarjeta:
            if campo not in _CAMPOS_TARJETA:
                raise ErrorContenido("CAMPO_DESCONOCIDO", f"{donde}: campo «{campo}» no permitido")
        anverso = _texto_tarjeta(tarjeta.get("anverso"), donde, "anverso")
        reverso = _texto_tarjeta(tarjeta.get("reverso"), donde, "reverso")
        tarjetas.append(
            TarjetaH5P(
                anverso=anverso,
                reverso=reverso,
                anverso_html=_html_inline_h5p(anverso, f"{donde}, anverso", _INLINE_TARJETA),
                reverso_html=_html_inline_h5p(reverso, f"{donde}, reverso", _INLINE_TARJETA),
            )
        )
    return ActividadH5P(tipo=tipo, tarjetas=tuple(tarjetas), reintentar=reintentar)


def _bool_h5p(valor: Any, campo: str, por_defecto: bool) -> bool:
    if valor is None:
        return por_defecto
    if not isinstance(valor, bool):
        raise ErrorContenido("ACTIVIDAD_H5P_INVALIDA", f"«{campo}» debe ser true o false")
    return valor


def _calificacion_h5p(valor: Any) -> int:
    if valor is None:
        return 10
    if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= 100:
        raise ErrorContenido(
            "ACTIVIDAD_H5P_INVALIDA", "«calificacion» debe ser un número entero entre 1 y 100"
        )
    return valor


def _texto_tarjeta(valor: Any, donde: str, campo: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorContenido("ACTIVIDAD_H5P_INVALIDA", f"{donde}: falta «{campo}» o está vacío")
    if len(valor) > MAX_TEXTO_H5P or _CONTROL.search(valor):
        raise ErrorContenido("ACTIVIDAD_H5P_INVALIDA", f"{donde}: «{campo}» no es un texto válido")
    return valor


def _respuesta_h5p(valor: Any, donde: str) -> str:
    """Una respuesta o distractor: texto plano sin la sintaxis de H5P."""
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorContenido("ACTIVIDAD_H5P_INVALIDA", f"{donde}: no puede estar vacía")
    texto = valor.strip()
    if len(texto) > MAX_RESPUESTA_H5P or _CONTROL.search(texto):
        raise ErrorContenido("ACTIVIDAD_H5P_INVALIDA", f"{donde}: no es una respuesta válida")
    if "[[" in texto or "]]" in texto:
        raise ErrorContenido("ACTIVIDAD_H5P_INVALIDA", f"{donde}: no puede llevar marcas [[...]]")
    if "*" in texto:
        raise ErrorContenido(
            "ACTIVIDAD_H5P_INVALIDA",
            f"{donde}: no se admite «*» en una respuesta (H5P lo usa para las marcas)",
        )
    if "/" in texto or ":" in texto:
        raise ErrorContenido(
            "ACTIVIDAD_H5P_INVALIDA",
            f"{donde}: no se admiten «/» ni «:» en una respuesta (H5P les da otro significado)",
        )
    return texto


def _texto_con_marcas(
    valor: Any,
    donde: str,
    *,
    permitidas: frozenset[str],
    huecos: bool = False,
    plano: bool = False,
) -> TextoH5P:
    """Texto con ``[[respuesta]]`` o ``[[a|b]]``; devuelve sus partes y el texto H5P."""
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorContenido("ACTIVIDAD_H5P_INVALIDA", f"{donde}: debe ser un texto")
    if len(valor) > MAX_TEXTO_H5P or _CONTROL.search(valor):
        raise ErrorContenido("ACTIVIDAD_H5P_INVALIDA", f"{donde}: no es un texto válido")
    if plano and "*" in valor:
        raise ErrorContenido(
            "ACTIVIDAD_H5P_INVALIDA",
            f"{donde}: no se admite el asterisco (*) fuera de las marcas (escribe las respuestas entre [[...]])",
        )
    partes, marcas = _partir_marcas(valor, donde)
    if huecos and not marcas:
        raise ErrorContenido(
            "ACTIVIDAD_H5P_INVALIDA", f"{donde}: falta al menos un hueco [[respuesta]]"
        )
    if plano:
        return TextoH5P(partes=tuple(partes), h5p=_h5p_plano(partes), plano=True)
    h5p, partes_html = _h5p_html(partes, permitidas, donde)
    return TextoH5P(partes=tuple(partes_html), h5p=h5p)


def _partir_marcas(valor: str, donde: str) -> tuple[list[str | MarcaH5P], list[MarcaH5P]]:
    partes: list[str | MarcaH5P] = []
    marcas: list[MarcaH5P] = []
    posicion = 0
    while True:
        inicio = valor.find("[[", posicion)
        if inicio == -1:
            partes.append(valor[posicion:])
            if "]]" in valor[posicion:]:
                raise ErrorContenido(
                    "ACTIVIDAD_H5P_INVALIDA", f"{donde}: hay un «]]» sin abrir una marca"
                )
            break
        cierre = valor.find("]]", inicio + 2)
        if cierre == -1:
            raise ErrorContenido(
                "ACTIVIDAD_H5P_INVALIDA", f"{donde}: falta cerrar la marca con «]]»"
            )
        contenido = valor[inicio + 2 : cierre]
        if "[[" in contenido or "]]" in contenido:
            raise ErrorContenido(
                "ACTIVIDAD_H5P_INVALIDA", f"{donde}: las marcas no se pueden anidar"
            )
        alternativas = tuple(alternativa.strip() for alternativa in contenido.split("|"))
        if not contenido.strip():
            raise ErrorContenido("ACTIVIDAD_H5P_INVALIDA", f"{donde}: hay una marca [[...]] vacía")
        if len(alternativas) > MAX_ALTERNATIVAS_H5P or any(
            not alternativa for alternativa in alternativas
        ):
            raise ErrorContenido(
                "ACTIVIDAD_H5P_INVALIDA", f"{donde}: una respuesta [[...]] está vacía"
            )
        respuestas = tuple(
            _respuesta_h5p(alternativa, f"{donde} (respuesta)") for alternativa in alternativas
        )
        marca = MarcaH5P(respuestas=respuestas)
        partes.append(valor[posicion:inicio])
        partes.append(marca)
        marcas.append(marca)
        posicion = cierre + 2
    return partes, marcas


def _h5p_plano(partes: list[str | MarcaH5P]) -> str:
    """Texto sin HTML (campos que H5P escapa): las marcas se sustituyen tal cual."""
    salida: list[str] = []
    for parte in partes:
        if isinstance(parte, MarcaH5P):
            salida.append("*" + "/".join(parte.respuestas) + "*")
        else:
            salida.append(parte)
    return "".join(salida)


def _h5p_html(
    partes: list[str | MarcaH5P],
    permitidas: frozenset[str],
    donde: str,
) -> tuple[str, list[str | MarcaH5P]]:
    """Texto con Markdown en línea y las marcas traducidas a ``*a/b*``."""
    base = "TIZAH5P"
    extra = ""
    while f"{base}{extra}" in "".join(parte for parte in partes if isinstance(parte, str)):
        extra += "X"
    token = f"{base}{extra}"
    piezas: list[str] = []
    marcas: list[MarcaH5P] = []
    for parte in partes:
        if isinstance(parte, MarcaH5P):
            piezas.append(f"{token}:{len(marcas)}:")
            marcas.append(parte)
        else:
            piezas.append(parte)
    html = _html_inline_h5p("".join(piezas), donde, permitidas)
    if "*" in html:
        raise ErrorContenido(
            "ACTIVIDAD_H5P_INVALIDA",
            f"{donde}: no se admite el asterisco (*) fuera de las marcas (escribe las respuestas entre [[...]])",
        )
    trozos = re.split(rf"{re.escape(token)}:(\d+):", html)
    salida: list[str] = []
    partes_html: list[str | MarcaH5P] = []
    for posicion, trozo in enumerate(trozos):
        if posicion % 2 == 0:
            salida.append(trozo)
            partes_html.append(trozo)
            continue
        marca = marcas[int(trozo)]
        partes_html.append(marca)
        salida.append(
            "*" + "/".join(_html.escape(respuesta) for respuesta in marca.respuestas) + "*"
        )
    return "".join(salida), partes_html


def _html_inline_h5p(valor: str, donde: str, permitidas: frozenset[str]) -> str:
    """Markdown en línea validado por el filtro, solo con las etiquetas permitidas."""
    try:
        analisis = filtro.analizar(_render(valor))
    except filtro.HtmlPeligroso as exc:
        raise ErrorContenido("HTML_PELIGROSO", f"{donde}: {exc.detalle}") from None
    for nodo in analisis.cuerpo.descendants:
        if isinstance(nodo, Tag) and (nodo.name or "").lower() not in permitidas | {"p"}:
            raise ErrorContenido(
                "ACTIVIDAD_H5P_INVALIDA",
                f"{donde}: la etiqueta <{nodo.name}> no se admite en este campo",
            )
    return filtro.serializar(analisis.cuerpo)


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
    metadatos = [
        ("Tipo", doc.tipo),
        ("Nombre", doc.nombre),
        ("Sección", str(doc.seccion)),
    ]
    if doc.fechas is not None:
        metadatos.append(("Apertura", _formato_fecha(doc.fechas.apertura)))
        metadatos.append(("Entrega", _formato_fecha(doc.fechas.entrega)))
        if doc.fechas.limite is not None:
            metadatos.append(("Límite", _formato_fecha(doc.fechas.limite)))
    if doc.cuestionario is not None:
        cuestionario = doc.cuestionario
        if cuestionario.apertura is not None:
            metadatos.append(("Apertura", _formato_fecha(cuestionario.apertura)))
        if cuestionario.cierre is not None:
            metadatos.append(("Cierre", _formato_fecha(cuestionario.cierre)))
        if cuestionario.tiempo_limite is not None:
            metadatos.append(("Tiempo límite", f"{cuestionario.tiempo_limite} minutos"))
        metadatos.append(
            ("Intentos", "ilimitados" if cuestionario.intentos == 0 else str(cuestionario.intentos))
        )
        metadatos.append(("Mezclar respuestas", "sí" if cuestionario.mezclar_respuestas else "no"))
    if doc.h5p is not None:
        metadatos.append(("Actividad H5P", NOMBRES_H5P.get(doc.h5p.tipo, doc.h5p.tipo)))
        if doc.h5p.tipo == "tarjetas":
            metadatos.append(("Calificación", "no califica"))
        else:
            metadatos.append(("Calificación máxima", str(doc.h5p.calificacion)))
            metadatos.append(("Ver solución", "sí" if doc.h5p.ver_solucion else "no"))
        metadatos.append(("Reintentar", "sí" if doc.h5p.reintentar else "no"))
    if doc.paquete is not None:
        metadatos.append(("Paquete", doc.paquete.nombre))
    for linea in describir_itinerario(doc):
        clave, _, resto = linea.partition(": ")
        metadatos.append((clave, resto) if resto else ("Itinerario", linea))
    filas = "\n".join(
        f"<li><strong>{clave}:</strong> {_html.escape(valor)}</li>" for clave, valor in metadatos
    )
    contenido = html_para_preview(doc, dir_preview)
    preguntas = _preguntas_preview(doc)
    h5p = _h5p_preview(doc)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="es">\n<head>\n<meta charset="utf-8">\n'
        f"<title>VISTA PREVIA — {_html.escape(doc.nombre)}</title>\n"
        "</head>\n<body>\n"
        '<p style="border:2px solid #b00;padding:.5rem;font-weight:bold">'
        "VISTA PREVIA: este contenido todavía no se ha publicado.</p>\n"
        f"<h1>{_html.escape(doc.nombre)}</h1>\n<ul>{filas}</ul>\n<hr>\n"
        f"{contenido}\n{preguntas}\n{h5p}\n"
        "</body>\n</html>\n"
    )


def _preguntas_preview(doc: Documento) -> str:
    """Las preguntas del cuestionario, numeradas y con las correctas marcadas."""
    if doc.cuestionario is None:
        return ""
    partes = ["<hr>", "<h2>Preguntas del cuestionario</h2>", "<ol>"]
    for pregunta in doc.cuestionario.preguntas:
        tipo = NOMBRES_PREGUNTA.get(pregunta.tipo, pregunta.tipo)
        partes.append(f"<li><p><strong>{_html.escape(tipo)}</strong></p>")
        partes.append(f"<div>{pregunta.html}</div>")
        if pregunta.opciones:
            partes.append("<ul>")
            for opcion in pregunta.opciones:
                marca = " <strong>(correcta)</strong>" if opcion.correcta else ""
                partes.append(f"<li>{opcion.html}{marca}{_retro_preview(opcion.retro_html)}</li>")
            partes.append("</ul>")
        elif pregunta.tipo == "verdadero_falso":
            respuesta = "Verdadero" if pregunta.respuesta == "verdadero" else "Falso"
            partes.append(f"<p>Respuesta correcta: <strong>{respuesta}</strong></p>")
        elif pregunta.tipo == "respuesta_corta":
            aceptadas = ", ".join(_html.escape(a) for a in pregunta.aceptadas)
            partes.append(f"<p>Respuestas válidas: <strong>{aceptadas}</strong></p>")
        elif pregunta.tipo == "numerica" and pregunta.valor is not None:
            partes.append(
                f"<p>Valor: <strong>{_html.escape(numero_texto(pregunta.valor))}</strong>"
            )
            if pregunta.tolerancia:
                partes[-1] += f" (tolerancia ±{_html.escape(numero_texto(pregunta.tolerancia))})"
            partes[-1] += "</p>"
        partes.append(_retro_preview(pregunta.retro_html))
        partes.append("</li>")
    partes.append("</ol>")
    return "\n".join(partes)


def _retro_preview(retro_html: str | None) -> str:
    """La retroalimentación como bloque: su HTML ya trae párrafos y no cabe en un <p> ni en un <em>."""
    if retro_html is None:
        return ""
    return f"<div><p><em>Retroalimentación:</em></p>{retro_html}</div>"


def _h5p_preview(doc: Documento) -> str:
    """Actividad H5P o resumen del paquete, para que el docente lo revise."""
    if doc.paquete is not None:
        paquete = doc.paquete
        partes = ["<hr>", "<h2>Paquete H5P</h2>", "<ul>"]
        partes.append(f"<li><strong>Fichero:</strong> {_html.escape(paquete.nombre)}</li>")
        if paquete.titulo:
            partes.append(f"<li><strong>Título:</strong> {_html.escape(paquete.titulo)}</li>")
        if paquete.libreria:
            partes.append(
                f"<li><strong>Librería principal:</strong> {_html.escape(paquete.libreria)}</li>"
            )
        partes.append("</ul>")
        if paquete.ficheros:
            partes.append("<p><strong>Ficheros:</strong></p><ul>")
            for nombre in paquete.ficheros[:20]:
                partes.append(f"<li>{_html.escape(nombre)}</li>")
            if len(paquete.ficheros) > 20:
                partes.append(f"<li>… y {len(paquete.ficheros) - 20} más</li>")
            partes.append("</ul>")
        if paquete.descartadas:
            nombres = ", ".join(_html.escape(nombre) for nombre in paquete.descartadas)
            partes.append(
                f"<p><strong>Librerías descartadas:</strong> {nombres} "
                "(tiza nunca sube sus ficheros)</p>"
            )
        if paquete.externos:
            partes.append("<p><strong>Enlaces externos de la actividad:</strong></p><ul>")
            for url in paquete.externos:
                partes.append(
                    f'<li><a href="{_html.escape(url)}" target="_blank" '
                    f'rel="noopener noreferrer">{_html.escape(url)}</a></li>'
                )
            partes.append("</ul>")
        return "\n".join(partes)
    actividad = doc.h5p
    if actividad is None:
        return ""
    partes = ["<hr>", "<h2>Actividad H5P</h2>"]
    partes.append(
        "<p><strong>Tipo:</strong> "
        f"{_html.escape(NOMBRES_H5P.get(actividad.tipo, actividad.tipo))}</p>"
    )
    if actividad.tipo == "rellenar_huecos":
        partes.append("<ol>")
        for texto in actividad.textos:
            partes.append(f"<li>{_h5p_marcas_html(texto)}</li>")
        partes.append("</ol>")
    elif actividad.tipo == "arrastrar_palabras":
        assert actividad.texto is not None
        partes.append(f"<p>{_h5p_marcas_html(actividad.texto)}</p>")
        if actividad.distractores:
            distractores = ", ".join(_html.escape(d) for d in actividad.distractores)
            partes.append(f"<p><strong>Distractores:</strong> {distractores}</p>")
    elif actividad.tipo == "marcar_palabras":
        assert actividad.texto is not None
        if actividad.enunciado_html:
            partes.append(f"<p>{actividad.enunciado_html}</p>")
        partes.append(f"<p>{_h5p_marcas_html(actividad.texto)}</p>")
    else:
        partes.append("<ol>")
        for tarjeta in actividad.tarjetas:
            partes.append(
                f"<li><p><strong>Anverso:</strong></p>{tarjeta.anverso_html}"
                f"<p><strong>Reverso:</strong></p>{tarjeta.reverso_html}</li>"
            )
        partes.append("</ol>")
    return "\n".join(partes)


def _h5p_marcas_html(texto: TextoH5P) -> str:
    """El texto de la actividad con las marcas subrayadas y sus alternativas."""
    salida: list[str] = []
    for parte in texto.partes:
        if isinstance(parte, MarcaH5P):
            alternativas = " | ".join(_html.escape(respuesta) for respuesta in parte.respuestas)
            salida.append(f"<u>{alternativas}</u>")
        elif texto.plano:
            salida.append(_html.escape(parte))
        else:
            salida.append(parte)
    return "".join(salida)


def _formato_fecha(momento: datetime) -> str:
    return momento.strftime("%Y-%m-%d %H:%M")


def hash_documento(doc: Documento) -> str:
    """Hash estable del contenido y sus recursos (no depende de la ruta)."""
    resumen = hashlib.sha256()
    resumen.update(f"{doc.tipo}\n{doc.nombre}\n{doc.seccion}\n".encode())
    if doc.fechas is not None:
        resumen.update(_formato_fecha(doc.fechas.apertura).encode("utf-8"))
        resumen.update(_formato_fecha(doc.fechas.entrega).encode("utf-8"))
        if doc.fechas.limite is not None:
            resumen.update(_formato_fecha(doc.fechas.limite).encode("utf-8"))
    resumen.update(b"\n")
    resumen.update(doc.cuerpo.encode("utf-8"))
    if doc.cuestionario is not None:
        resumen.update(b"\n--cuestionario--\n")
        resumen.update(_hash_cuestionario(doc.cuestionario))
    if doc.h5p is not None:
        resumen.update(b"\n--h5p--\n")
        resumen.update(repr(doc.h5p).encode("utf-8"))
    if doc.finalizacion is not None or doc.restricciones is not None:
        resumen.update(b"\n--itinerario--\n")
        resumen.update(repr(doc.finalizacion).encode("utf-8"))
        resumen.update(repr(doc.restricciones).encode("utf-8"))
    if doc.paquete is not None:
        resumen.update(b"\n--paquete--\n")
        resumen.update(doc.paquete.nombre.encode("utf-8"))
        resumen.update(b"\n")
        with doc.paquete.ruta.open("rb") as fichero:
            while trozo := fichero.read(_TROZO_HASH):
                resumen.update(trozo)
    for recurso in sorted(doc.recursos, key=lambda item: item.nombre):
        resumen.update(b"\n--recurso--\n")
        resumen.update(recurso.nombre.encode("utf-8"))
        resumen.update(b"\n")
        with recurso.ruta.open("rb") as fichero:
            while trozo := fichero.read(_TROZO_HASH):
                resumen.update(trozo)
    return resumen.hexdigest()


def _hash_cuestionario(cuestionario: Cuestionario) -> bytes:
    """Ajustes y preguntas; el repr de los dataclass congelados es estable y completo."""
    return repr(cuestionario).encode("utf-8")
