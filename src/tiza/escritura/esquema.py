"""Convierte un SVG del agente en un PNG para publicarlo (offline).

El SVG es dato hostil: se lee con límite, se valida contra un esquema cerrado (sin
DTD, sin entidades, sin referencias externas ni imágenes incrustadas) y solo entonces
se renderiza con resvg. El PNG lleva una marca ``tEXt`` con el SVG del que salió: así
``tiza esquema`` puede sustituir su propio PNG y nunca el del docente.

Lo que se publica es el PNG; el SVG se queda en la carpeta. Todo el módulo funciona
sin red. ``resvg_py`` se importa dentro de :func:`_renderizar` para que los demás
comandos de tiza no lo carguen.
"""

from __future__ import annotations

import math
import re
import struct
import tempfile
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tinycss2
from lxml import etree

from tiza import recursos
from tiza.escritura import ErrorEscritura

__all__ = [
    "ANCHO_MAXIMO",
    "ANCHO_MINIMO",
    "ANCHO_POR_DEFECTO",
    "CLAVE_MARCA",
    "FUENTE",
    "FUENTES",
    "MAX_ELEMENTOS",
    "MAX_PNG_BYTES",
    "MAX_SVG_BYTES",
    "convertir",
    "marca_de_png",
]

ESPACIO_SVG = "http://www.w3.org/2000/svg"
ESPACIO_XML = "http://www.w3.org/XML/1998/namespace"

MAX_SVG_BYTES = 512 * 1024
MAX_PNG_BYTES = 1024 * 1024
MAX_ELEMENTOS = 5000
ANCHO_POR_DEFECTO = 1200
ANCHO_MINIMO = 400
ANCHO_MAXIMO = 2000
PROPORCION_MINIMA = 1 / 4  # ancho / alto
PROPORCION_MAXIMA = 4.0

FUENTES = ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf")
FUENTE = "Liberation Sans"
CLAVE_MARCA = "tiza-esquema"

_FIRMA_PNG = b"\x89PNG\r\n\x1a\n"

# Lista blanca de elementos: formas, trazos, texto y las definiciones que usan.
_ELEMENTOS = frozenset(
    {
        "svg",
        "g",
        "defs",
        "symbol",
        "use",
        "title",
        "desc",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "path",
        "text",
        "tspan",
        "textPath",
        "marker",
        "linearGradient",
        "radialGradient",
        "stop",
        "clipPath",
        "mask",
        "pattern",
        "style",
    }
)

# Funciones CSS que pueden cargar una imagen: sus argumentos con forma de ruta también
# tienen que ser internos.
_FUNCIONES_CON_RECURSO = frozenset(
    {"image", "image-set", "-webkit-image-set", "cross-fade", "element"}
)

_NUMERO = re.compile(r"\A[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
_UNIDADES = {
    "": 1.0,
    "px": 1.0,
    "pt": 96 / 72,
    "pc": 16.0,
    "in": 96.0,
    "cm": 96 / 2.54,
    "mm": 96 / 25.4,
    "q": 96 / 101.6,
    "em": 16.0,  # tamaño de fuente inicial del SVG
    "ex": 8.0,
}


def _error(codigo: str, detalle: str) -> ErrorEscritura:
    return ErrorEscritura(codigo, detalle)


def _linea(nodo: Any) -> int:
    return max(1, int(nodo.sourceline or 1))


def _corto(texto: str) -> str:
    """Un nombre de elemento o propiedad, acotado para que un SVG hostil no llene el error."""
    return texto if len(texto) <= 40 else texto[:37] + "…"


def _rechazo(nodo: Any, que: str) -> ErrorEscritura:
    return _error("ESQUEMA_NO_ADMITIDO", f"línea {_linea(nodo)}: {que}.")


def _demasiado_grande(detalle: str) -> ErrorEscritura:
    return _error("ESQUEMA_DEMASIADO_GRANDE", detalle)


@dataclass(frozen=True)
class _Medidas:
    proporcion: float  # ancho / alto


def _parsear(datos: bytes) -> Any:
    """El árbol del SVG, sin DTD, sin entidades y sin red."""
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False
    )
    try:
        raiz = etree.fromstring(datos, parser)
        info = raiz.getroottree().docinfo
        if (
            info.doctype
            or info.internalDTD is not None
            or info.externalDTD is not None
            or any(True for _ in raiz.iter(etree.Entity))
        ):
            raise _error(
                "ESQUEMA_NO_ADMITIDO",
                "línea 1: no se admiten DOCTYPE ni entidades en un esquema.",
            )
    except etree.XMLSyntaxError as exc:
        linea = exc.position[0] if getattr(exc, "position", None) else 1
        raise _error(
            "ESQUEMA_NO_ADMITIDO", f"línea {max(1, int(linea))}: el SVG no está bien formado."
        ) from None
    except (ValueError, TypeError):
        raise _error("ESQUEMA_NO_ADMITIDO", "línea 1: el SVG no es XML válido.") from None
    return raiz


def _local(clave: str) -> str:
    return etree.QName(clave).localname


def _validar(raiz: Any) -> _Medidas:
    """Valida el árbol entero y devuelve su proporción antes de renderizar nada."""
    if raiz.tag != f"{{{ESPACIO_SVG}}}svg":
        raise _error(
            "ESQUEMA_NO_ADMITIDO",
            "línea 1: la raíz tiene que ser un <svg> del espacio de nombres SVG.",
        )

    cuantos = 0
    for nodo in raiz.iter():
        if not isinstance(nodo.tag, str):
            if nodo.tag is etree.Comment:
                continue
            raise _rechazo(nodo, "no se admiten instrucciones de proceso")
        if not nodo.tag.startswith(f"{{{ESPACIO_SVG}}}"):
            raise _rechazo(nodo, "hay un elemento fuera del espacio de nombres SVG")
        nombre = nodo.tag.split("}", 1)[1]
        if nombre not in _ELEMENTOS:
            raise _rechazo(
                nodo,
                f"<{_corto(nombre)}> no está admitido en un esquema "
                "(solo formas, trazos, texto y sus definiciones)",
            )
        if nombre == "style":
            if len(nodo):
                raise _rechazo(nodo, "el <style> solo puede llevar CSS, no elementos dentro")
            _validar_hoja(nodo.text or "", nodo)
        cuantos += 1
        if cuantos > MAX_ELEMENTOS:
            raise _demasiado_grande(
                f"el esquema tiene más de {MAX_ELEMENTOS} elementos; simplifícalo."
            )
        _validar_atributos(nodo)

    return _medidas(raiz)


def _validar_atributos(nodo: Any) -> None:
    for clave, valor in nodo.attrib.items():
        local = _local(clave)
        bajo = local.casefold()
        if bajo == "href":
            if not valor.startswith("#"):
                raise _rechazo(
                    nodo,
                    f"el atributo «{_corto(local)}» solo puede apuntar dentro del esquema («#…»)",
                )
            continue
        if bajo.startswith("on"):
            raise _rechazo(nodo, "no se admiten atributos de evento")
        if clave == f"{{{ESPACIO_XML}}}base":
            raise _rechazo(nodo, "no se admite «xml:base»")
        if bajo == "style":
            try:
                declaraciones = tinycss2.parse_declaration_list(
                    valor, skip_comments=False, skip_whitespace=False
                )
            except Exception:
                raise _rechazo(nodo, "el atributo «style» no es válido") from None
            _validar_declaraciones(declaraciones, nodo, "el atributo «style»")
            continue
        if bajo in (
            "filter",
            "backdrop-filter",
            "-webkit-filter",
        ) and valor.strip().casefold() not in (
            "",
            "none",
        ):
            raise _rechazo(nodo, "no se admiten filtros")
        if "url" in valor.casefold() or "\\" in valor:
            _validar_valor(valor, nodo, f"el atributo «{_corto(local)}»")


def _parece_url_externa(valor: str) -> bool:
    texto = valor.strip().casefold()
    return texto.startswith(("http://", "https://", "file:", "data:", "ftp:", "mailto:", "//"))


def _validar_componentes(tokens: list[Any], nodo: Any, donde: str) -> None:
    for token in tokens:
        tipo = token.type
        if tipo == "url":
            if not token.value.startswith("#") or len(token.value) < 2:
                raise _rechazo(nodo, f"{donde}: solo se admiten referencias internas «url(#…)»")
        elif tipo == "function":
            nombre = token.lower_name
            if nombre == "url":
                _validar_funcion_url(token, nodo, donde)
            elif nombre in _FUNCIONES_CON_RECURSO:
                _validar_funcion_recurso(token, nodo, donde)
            _validar_componentes(token.arguments, nodo, donde)
        elif tipo in ("{} block", "[] block", "() block"):
            _validar_componentes(token.content, nodo, donde)
        elif tipo == "at-keyword":
            raise _rechazo(nodo, f"{donde}: no se admiten reglas «@»")
        elif tipo == "string" and _parece_url_externa(token.value):
            raise _rechazo(nodo, f"{donde}: no se admiten direcciones externas")
        elif tipo == "error":
            raise _rechazo(nodo, f"{donde}: el CSS no es válido")


def _validar_funcion_url(token: Any, nodo: Any, donde: str) -> None:
    argumentos = [arg for arg in token.arguments if arg.type != "whitespace"]
    if len(argumentos) != 1 or argumentos[0].type != "string":
        raise _rechazo(nodo, f"{donde}: solo se admiten referencias internas «url(#…)»")
    valor = argumentos[0].value
    if not valor.startswith("#") or len(valor) < 2:
        raise _rechazo(nodo, f"{donde}: solo se admiten referencias internas «url(#…)»")


def _validar_funcion_recurso(token: Any, nodo: Any, donde: str) -> None:
    for argumento in token.arguments:
        if argumento.type == "string" and not argumento.value.startswith("#"):
            raise _rechazo(nodo, f"{donde}: no se admiten imágenes ni recursos externos")


def _validar_valor(valor: str, nodo: Any, donde: str) -> None:
    try:
        tokens = tinycss2.parse_component_value_list(valor)
    except Exception:
        raise _rechazo(nodo, f"{donde}: el valor no es válido") from None
    _validar_componentes(tokens, nodo, donde)


def _validar_declaraciones(declaraciones: list[Any], nodo: Any, donde: str) -> None:
    for declaracion in declaraciones:
        if declaracion.type == "error":
            raise _rechazo(nodo, f"{donde}: el CSS no es válido")
        if declaracion.type == "at-rule":
            raise _rechazo(nodo, f"{donde}: no se admiten reglas «@»")
        if declaracion.type == "declaration":
            if declaracion.lower_name in ("filter", "backdrop-filter", "-webkit-filter"):
                valor = tinycss2.serialize(declaracion.value).strip().casefold()
                if valor not in ("", "none"):
                    raise _rechazo(nodo, f"{donde}: no se admiten filtros")
            _validar_componentes(declaracion.value, nodo, f"{donde}: «{_corto(declaracion.name)}»")


def _validar_hoja(texto: str, nodo: Any) -> None:
    try:
        reglas = tinycss2.parse_stylesheet(texto, skip_comments=False, skip_whitespace=False)
    except Exception:
        raise _rechazo(nodo, "el CSS del <style> no es válido") from None
    for regla in reglas:
        if regla.type == "error":
            raise _rechazo(nodo, "el CSS del <style> no es válido")
        if regla.type == "at-rule":
            raise _rechazo(nodo, "no se admiten reglas «@» (como «@import») en el <style>")
        if regla.type != "qualified-rule":
            continue
        _validar_componentes(regla.prelude, nodo, "el selector")
        try:
            declaraciones = tinycss2.parse_declaration_list(
                regla.content, skip_comments=False, skip_whitespace=False
            )
        except Exception:
            raise _rechazo(nodo, "el CSS del <style> no es válido") from None
        _validar_declaraciones(declaraciones, nodo, "el CSS del <style>")


def _longitud(valor: str | None) -> float | None:
    """Una longitud CSS absoluta en píxeles, o None si no sirve como medida."""
    if valor is None:
        return None
    texto = valor.strip()
    if not texto:
        return None
    m = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z%]*)", texto)
    if m is None:
        return None
    numero = float(m.group(1))
    unidad = m.group(2).casefold()
    factor = _UNIDADES.get(unidad)
    if factor is None or not math.isfinite(numero):
        return None
    resultado = numero * factor
    return resultado if math.isfinite(resultado) else None


def _viewbox(valor: str | None) -> tuple[float, float, float, float] | None:
    if valor is None:
        return None
    partes = re.split(r"[\s,]+", valor.strip())
    if len(partes) != 4 or not all(_NUMERO.match(p) for p in partes):
        return None
    numeros = tuple(float(p) for p in partes)
    if not all(math.isfinite(n) for n in numeros):
        return None
    ancho, alto = numeros[2], numeros[3]
    if ancho <= 0 or alto <= 0:
        return None
    return numeros  # type: ignore[return-value]


def _medidas(raiz: Any) -> _Medidas:
    caja = _viewbox(raiz.get("viewBox"))
    if caja is not None:
        return _Medidas(caja[2] / caja[3])
    ancho = _longitud(raiz.get("width"))
    alto = _longitud(raiz.get("height"))
    if ancho is None or alto is None or ancho <= 0 or alto <= 0:
        raise _error(
            "ESQUEMA_NO_ADMITIDO",
            "línea 1: el SVG no dice su tamaño (width y height, o viewBox).",
        )
    return _Medidas(ancho / alto)


def _comprobar_proporcion(medidas: _Medidas, ancho: int) -> int:
    proporcion = medidas.proporcion
    if not math.isfinite(proporcion) or proporcion <= 0:
        raise _error(
            "ESQUEMA_NO_ADMITIDO",
            "el esquema no tiene una proporción válida entre su ancho y su alto.",
        )
    if proporcion < PROPORCION_MINIMA or proporcion > PROPORCION_MAXIMA:
        alto = max(1, round(ancho / proporcion))
        raise _error(
            "ESQUEMA_NO_ADMITIDO",
            f"el esquema sería de {ancho} × {alto} px; la proporción entre su ancho y su alto "
            "tiene que estar entre 1:4 y 4:1.",
        )
    return max(1, round(ancho / proporcion))


def _declaracion_fuente() -> Any:
    return tinycss2.parse_declaration_list(
        f"font-family: '{FUENTE}' !important", skip_comments=True, skip_whitespace=True
    )[0]


def _con_fuente(tokens: Any) -> list[Any]:
    """Deja la familia que trae tiza detrás de cualquier ``font`` o ``font-family``.

    No se quita ``font``: se conservarían el tamaño y el peso. La familia añadida al final
    de la misma regla gana a la del atajo y a cualquier otra declaración de esa regla.
    """
    declaraciones = tinycss2.parse_declaration_list(
        tokens, skip_comments=False, skip_whitespace=False
    )
    if any(
        declaracion.type == "declaration" and declaracion.lower_name in ("font", "font-family")
        for declaracion in declaraciones
    ):
        declaraciones.append(_declaracion_fuente())
    return declaraciones


def _con_fuente_hoja(texto: str) -> str:
    reglas = tinycss2.parse_stylesheet(texto, skip_comments=False, skip_whitespace=False)
    for regla in reglas:
        if regla.type == "qualified-rule":
            regla.content = _con_fuente(regla.content)
    return tinycss2.serialize(reglas)


def _normalizar_fuentes(raiz: Any) -> None:
    """Todas las fuentes caen en la que viaja con tiza: el PNG es igual en cada equipo."""
    for nodo in raiz.iter():
        if not isinstance(nodo.tag, str):
            continue
        for clave, valor in list(nodo.attrib.items()):
            local = _local(clave)
            if local == "font-family":
                nodo.set(clave, FUENTE)
            elif local == "font":
                del nodo.attrib[clave]
            elif local == "style":
                nodo.set(clave, tinycss2.serialize(_con_fuente(valor)))
        if nodo.tag == f"{{{ESPACIO_SVG}}}style" and nodo.text:
            nodo.text = _con_fuente_hoja(nodo.text)


@contextmanager
def _rutas_de_fuentes() -> Iterator[list[str]]:
    """Las rutas de las fuentes; en un paquete comprimido, en un temporal privado."""
    temporales: list[tempfile.TemporaryDirectory[str]] = []
    rutas: list[str] = []
    try:
        for nombre in FUENTES:
            ruta = recursos.ruta(nombre)
            if ruta is not None:
                rutas.append(str(ruta))
                continue
            temporal = tempfile.TemporaryDirectory(prefix="tiza-esquema-")
            temporales.append(temporal)
            destino = Path(temporal.name) / nombre
            try:
                destino.write_bytes(recursos.datos(nombre))
            except OSError:
                raise _error(
                    "ERROR_INTERNO", "Falta la fuente que tiza usa para los esquemas."
                ) from None
            rutas.append(str(destino))
        yield rutas
    finally:
        for temporal in temporales:
            try:
                temporal.cleanup()
            except OSError:
                pass  # Windows puede tardar en soltar el fichero; no es un fallo de tiza


def _renderizar(svg: str, ancho: int, alto: int) -> bytes:
    """El PNG de resvg; la librería se importa aquí para no cargarla en otros comandos."""
    import resvg_py  # import diferido: solo lo necesita «tiza esquema»

    with _rutas_de_fuentes() as fuentes:
        try:
            png = resvg_py.svg_to_bytes(
                svg_string=svg,
                width=ancho,
                height=alto,
                background="#ffffff",
                skip_system_fonts=True,
                font_files=fuentes,
                font_family=FUENTE,
            )
        except (Exception, MemoryError):
            raise _error(
                "ESQUEMA_NO_ADMITIDO",
                "no se pudo dibujar el esquema; revisa las referencias «use» y los degradados.",
            ) from None
    if not isinstance(png, bytes):
        png = bytes(png)
    if not png.startswith(_FIRMA_PNG):
        raise _error("ERROR_INTERNO", "resvg no devolvió un PNG.")
    return png


def _recorrer_chunks(png: bytes) -> Iterator[tuple[bytes, bytes]]:
    if not png.startswith(_FIRMA_PNG):
        return
    posicion = len(_FIRMA_PNG)
    while posicion + 12 <= len(png):
        (longitud,) = struct.unpack(">I", png[posicion : posicion + 4])
        tipo = png[posicion + 4 : posicion + 8]
        inicio = posicion + 8
        fin = inicio + longitud
        if fin + 4 > len(png):
            return
        yield tipo, png[inicio:fin]
        if tipo == b"IEND":
            return
        posicion = fin + 4


def _inicio_de_iend(png: bytes) -> int | None:
    posicion = len(_FIRMA_PNG)
    while posicion + 12 <= len(png):
        (longitud,) = struct.unpack(">I", png[posicion : posicion + 4])
        tipo = png[posicion + 4 : posicion + 8]
        fin = posicion + 8 + longitud
        if fin + 4 > len(png):
            return None
        if tipo == b"IEND":
            return posicion
        posicion = fin + 4
    return None


def marca_de_png(png: bytes) -> str | None:
    """El SVG de origen que ``tiza esquema`` dejó escrito en el PNG, o None."""
    for tipo, datos in _recorrer_chunks(png):
        if tipo != b"tEXt":
            continue
        clave, separador, texto = datos.partition(b"\x00")
        if not separador or clave != CLAVE_MARCA.encode("ascii"):
            continue
        try:
            return texto.decode("utf-8")
        except UnicodeDecodeError:
            return texto.decode("latin-1", "replace")
    return None


def _con_marca(png: bytes, origen: str) -> bytes:
    """Inserta el trozo ``tEXt`` antes de IEND; no toca los píxeles."""
    posicion = _inicio_de_iend(png)
    if posicion is None:
        raise _error("ERROR_INTERNO", "el PNG de resvg no tiene IEND.")
    datos = CLAVE_MARCA.encode("ascii") + b"\x00" + origen.encode("utf-8")
    crc = zlib.crc32(b"tEXt" + datos) & 0xFFFFFFFF
    trozo = struct.pack(">I", len(datos)) + b"tEXt" + datos + struct.pack(">I", crc)
    return png[:posicion] + trozo + png[posicion:]


def convertir(datos: bytes, origen: str, ancho: int = ANCHO_POR_DEFECTO) -> tuple[bytes, int, int]:
    """Valida el SVG de ``datos`` y devuelve ``(png, ancho, alto)``.

    ``origen`` es la ruta relativa del SVG, que queda escrita en el PNG para poder
    sustituirlo después. Lanza ``ErrorEscritura`` con un código estable.
    """
    if isinstance(ancho, bool) or not isinstance(ancho, int):
        raise _demasiado_grande("el ancho tiene que ser un número entero.")
    if ancho < ANCHO_MINIMO or ancho > ANCHO_MAXIMO:
        raise _demasiado_grande(
            f"el ancho tiene que estar entre {ANCHO_MINIMO} y {ANCHO_MAXIMO} px."
        )
    try:
        raiz = _parsear(datos)
        medidas = _validar(raiz)
        alto = _comprobar_proporcion(medidas, ancho)
        _normalizar_fuentes(raiz)
        svg = etree.tostring(raiz, encoding="unicode", xml_declaration=False)
    except RecursionError:
        raise _error("ESQUEMA_NO_ADMITIDO", "el SVG está anidado demasiado profundo.") from None
    png = _con_marca(_renderizar(svg, ancho, alto), origen)
    if len(png) > MAX_PNG_BYTES:
        raise _demasiado_grande(
            f"el PNG pasa de {MAX_PNG_BYTES // 2**20} MB; simplifica el esquema "
            "o usa un ancho menor."
        )
    return png, ancho, alto
