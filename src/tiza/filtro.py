"""Política de HTML de tiza: una lista blanca sobre el árbol que construye un navegador.

El HTML se analiza con html5lib, que sigue el algoritmo del estándar: el árbol
que se valida es el mismo que verá el navegador del alumnado. Todo lo que no
está en las listas de este módulo se rechaza con ``HtmlPeligroso``; nada se
limpia en silencio. Todo es offline.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import tinycss2
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString, PreformattedString

__all__ = [
    "CONTROL",
    "ETIQUETAS_PERMITIDAS",
    "SANDBOX_INCRUSTADOS",
    "Analisis",
    "HtmlPeligroso",
    "analizar",
    "serializar",
]

# Lista blanca: lo que genera el Markdown (CommonMark con tablas) y unas pocas
# etiquetas de texto. Todo lo demás (svg, meta, base, style, link, form, script,
# audio, video…) se rechaza, igual que cualquier atributo no listado.
ETIQUETAS_PERMITIDAS = frozenset(
    {
        "a",
        "abbr",
        "article",
        "aside",
        "b",
        "blockquote",
        "br",
        "caption",
        "code",
        "col",
        "colgroup",
        "dd",
        "del",
        "details",
        "div",
        "dl",
        "dt",
        "em",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "i",
        "iframe",
        "img",
        "ins",
        "kbd",
        "li",
        "mark",
        "ol",
        "p",
        "pre",
        "q",
        "s",
        "samp",
        "section",
        "small",
        "span",
        "strong",
        "sub",
        "summary",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
)
ATRIBUTOS_GLOBALES = frozenset({"title", "lang", "class", "style"})
ATRIBUTOS_POR_ETIQUETA = {
    "a": frozenset({"href", "target", "rel"}),
    "img": frozenset({"src", "alt", "width", "height"}),
    "ol": frozenset({"start"}),
    "td": frozenset({"colspan", "rowspan"}),
    "th": frozenset({"colspan", "rowspan", "scope"}),
    "col": frozenset({"span"}),
    "colgroup": frozenset({"span"}),
    "details": frozenset({"open"}),
    "iframe": frozenset(
        {
            "src",
            "width",
            "height",
            "allow",
            "allowfullscreen",
            "sandbox",
            "frameborder",
            "scrolling",
            "loading",
            "referrerpolicy",
        }
    ),
}
_ENTERO = re.compile(r"\A\d{1,6}\Z")
_MEDIDA = re.compile(r"\A(?:\d{1,3}|1\d{3}|2000)(?:%|px)?\Z")  # hasta 2000, como en el CSS
_VALORES = {
    "start": _ENTERO,
    "colspan": _ENTERO,
    "rowspan": _ENTERO,
    "span": _ENTERO,
    "width": _MEDIDA,
    "height": _MEDIDA,
    "scope": re.compile(r"\A(?:col|row|colgroup|rowgroup)\Z"),
    "lang": re.compile(r"\A[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*\Z"),
    "target": re.compile(r"\A_blank\Z"),
    "allowfullscreen": re.compile(r"\A(?:|allowfullscreen)\Z"),
    "frameborder": re.compile(r"\A[01]\Z"),
    "scrolling": re.compile(r"\A(?:yes|no|auto)\Z"),
    "loading": re.compile(r"\A(?:lazy|eager)\Z"),
    "referrerpolicy": re.compile(
        r"\A(?:no-referrer|no-referrer-when-downgrade|origin|origin-when-cross-origin"
        r"|same-origin|strict-origin|strict-origin-when-cross-origin)\Z"
    ),
    "rel": re.compile(
        r"\A(?:noopener|noreferrer|nofollow)(?:\s+(?:noopener|noreferrer|nofollow))*\Z"
    ),
}

# Clases: una lista cerrada de Bootstrap (formas de la 4 y de la 5 donde cambian).
# Quedan fuera las que colocan o superponen (position-*, fixed-*, sticky-*,
# stretched-link, modal…), las que ocultan (d-none, collapse) y los espaciados
# negativos (m*-n*).
_COLORES = "primary|secondary|success|danger|warning|info|light|dark"
_CLASES_EXACTAS = frozenset(
    {
        "alert",
        "badge",
        "card",
        "card-body",
        "card-header",
        "card-footer",
        "card-title",
        "card-text",
        "col",
        "d-block",
        "d-flex",
        "d-inline",
        "d-inline-block",
        "font-italic",
        "font-weight-bold",
        "font-weight-normal",
        "img-fluid",
        "lead",
        "list-unstyled",
        "row",
        "small",
        "table",
        "table-bordered",
        "table-hover",
        "table-responsive",
        "table-sm",
        "table-striped",
        "text-muted",
        "text-white",
    }
)
_PATRON_CLASE = re.compile(
    r"\A(?:"
    rf"(?:alert|badge|text|bg|text-bg|border)-(?:{_COLORES})"
    r"|col-(?:[1-9]|1[0-2])"
    r"|col-(?:sm|md|lg|xl|xxl)-(?:[1-9]|1[0-2])"
    r"|[mp][tblrxyse]?-[0-5]"
    r"|m[tblrxyse]?-auto"
    r"|justify-content-(?:start|end|center|between|around|evenly)"
    r"|align-items-(?:start|end|center|baseline|stretch)"
    r"|flex-(?:row|column|wrap|nowrap|row-reverse|column-reverse|fill|grow-[01]|shrink-[01])"
    r"|fw-(?:bold|bolder|normal|light|lighter)"
    r"|fst-(?:italic|normal)"
    r"|text-(?:start|center|end|left|right|justify)"
    r"|shadow(?:-sm|-lg)?"
    r"|border(?:-top|-bottom|-start|-end|-left|-right|-0)?"
    r"|rounded(?:-circle|-pill|-0|-sm|-lg)?"
    r")\Z"
)
# Solo en enlaces: el aspecto de botón.
_PATRON_CLASE_BOTON = re.compile(rf"\Abtn(?:-sm|-lg|-(?:outline-)?(?:{_COLORES}))?\Z")
# Solo en <code>: la que pone el Markdown en los bloques de código.
_PATRON_CLASE_LENGUAJE = re.compile(r"\Alanguage-[A-Za-z0-9_+#.-]{1,40}\Z")
_ATRIBUTO_URL = {"a": "href", "img": "src"}
_DATA_IMAGEN = re.compile(r"\Adata:image/(?:png|jpeg|gif|webp)[;,]", re.IGNORECASE)
_ESPACIO_DE_NOMBRES_HTML = (None, "http://www.w3.org/1999/xhtml")

# Misma clase de caracteres que terminal.texto_seguro, informe._TEXTO_PROHIBIDO y
# publicar._NO_IMPRIMIBLE; mantén las cuatro sincronizadas.
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


class HtmlPeligroso(Exception):
    """El HTML lleva algo que la lista blanca no admite; ``detalle`` dice qué."""

    def __init__(self, detalle: str) -> None:
        super().__init__(detalle)
        self.detalle = detalle


@dataclass
class Analisis:
    """Resultado de validar un HTML.

    ``cuerpo`` es el ``<body>`` ya validado y es lo que se publica; ``locales``
    son los valores de URL que apuntan a ficheros locales (tal como los escribió
    el autor, sin repetir), ``externos`` los enlaces ``http(s)`` y ``//…`` e
    ``incrustados`` las URL de los ``<iframe>``, tal como se publicarán.
    """

    cuerpo: Tag
    locales: list[str] = field(default_factory=list)
    externos: list[str] = field(default_factory=list)
    incrustados: list[str] = field(default_factory=list)  # URL de los iframes, ya normalizadas


def analizar(html: str) -> Analisis:
    """Valida ``html`` (un fragmento o un documento) y devuelve su ``<body>``.

    Raises:
        HtmlPeligroso: con qué etiqueta, atributo o valor no está permitido.
    """
    sopa = BeautifulSoup(html, "html5lib")
    cuerpo = _estructura(sopa)
    locales: list[str] = []
    externos: list[str] = []
    incrustados: list[str] = []
    iframes: list[Tag] = []
    for nodo in cuerpo.descendants:
        if isinstance(nodo, PreformattedString):
            raise HtmlPeligroso(_describir_nodo(nodo))
        if not isinstance(nodo, Tag):
            continue
        nombre = (nodo.name or "").lower()
        if nombre not in ETIQUETAS_PERMITIDAS or nodo.namespace not in _ESPACIO_DE_NOMBRES_HTML:
            raise HtmlPeligroso(f"etiqueta <{nombre}> no permitida")
        _validar_atributos(nombre, nodo.attrs)
        if nombre == "iframe":
            url = _normalizar_iframe(nodo)
            iframes.append(nodo)
            if url not in incrustados:
                incrustados.append(url)
            continue
        atributo = _ATRIBUTO_URL.get(nombre)
        valor = nodo.get(atributo) if atributo else None
        if not isinstance(valor, str) or not valor.strip():
            continue
        clase = _clasificar_url(nombre, valor)
        if clase == "externa":
            if valor.strip() not in externos:
                externos.append(valor.strip())
        elif clase == "local" and valor not in locales:
            locales.append(valor)
    for etiqueta in iframes:  # fuera del recorrido, para no tocar el árbol mientras se lee
        etiqueta.clear()
    return Analisis(cuerpo=cuerpo, locales=locales, externos=externos, incrustados=incrustados)


def serializar(cuerpo: Tag) -> str:
    """El HTML del ``<body>``, con el texto escapado.

    No uses ``str()`` sobre los nodos: el de un texto suelto devuelve la cadena sin
    escapar, y ``&lt;script&gt;`` se publicaría como un ``<script>`` de verdad.
    """
    copia = copy.copy(cuerpo)
    # El navegador descarta el primer salto de línea de un <pre>; para que el resultado
    # se lea igual que el árbol (como manda el estándar) hay que escribir uno de más.
    for bloque in copia.find_all("pre"):
        primero = bloque.contents[0] if bloque.contents else None
        if (
            isinstance(primero, NavigableString)
            and not isinstance(primero, PreformattedString)
            and primero.startswith("\n")
        ):
            primero.replace_with("\n" + primero)
    return copia.decode_contents()


def _describir_nodo(nodo: PreformattedString) -> str:
    return {
        "Comment": "comentario HTML no permitido",
        "CData": "sección CDATA no permitida",
        "Declaration": "declaración no permitida",
        "Doctype": "declaración <!DOCTYPE> no permitida aquí",
        "ProcessingInstruction": "instrucción de proceso no permitida",
    }.get(type(nodo).__name__, "contenido no permitido")


def _estructura(sopa: BeautifulSoup) -> Tag:
    """Comprueba lo que rodea al ``<body>`` y lo devuelve.

    html5lib siempre construye ``html``, ``head`` y ``body``. De la cabecera solo
    se toleran ``<meta charset>`` y ``<title>`` (se ignoran); el ``<body>`` no
    puede llevar atributos.
    """
    raiz = sopa.find("html")
    cuerpo = sopa.find("body")
    if not isinstance(raiz, Tag) or not isinstance(cuerpo, Tag):  # no ocurre con html5lib
        raise HtmlPeligroso("el documento no tiene cuerpo")
    for nodo in sopa.contents:
        if nodo is raiz:
            continue
        if isinstance(nodo, PreformattedString) and type(nodo).__name__ == "Doctype":
            continue
        raise HtmlPeligroso(
            _describir_nodo(nodo)
            if isinstance(nodo, PreformattedString)
            else "texto fuera del cuerpo"
        )
    _atributos_de_estructura("html", raiz, {"lang"})
    _atributos_de_estructura("body", cuerpo, set())
    for hijo in raiz.contents:
        if hijo is cuerpo:
            continue
        if isinstance(hijo, Tag) and hijo.name == "head":
            _revisar_cabecera(hijo)
        elif isinstance(hijo, PreformattedString):
            raise HtmlPeligroso(_describir_nodo(hijo))
    return cuerpo


def _atributos_de_estructura(nombre: str, etiqueta: Tag, permitidos: set[str]) -> None:
    for clave in etiqueta.attrs:
        if clave.lower() not in permitidos:
            raise HtmlPeligroso(f"atributo «{clave.lower()}» no permitido en <{nombre}>")


def _revisar_cabecera(cabecera: Tag) -> None:
    for nodo in cabecera.descendants:
        if isinstance(nodo, PreformattedString):
            raise HtmlPeligroso(_describir_nodo(nodo))
        if not isinstance(nodo, Tag):
            continue
        nombre = (nodo.name or "").lower()
        if nodo.parent is not cabecera or nombre not in {"meta", "title"}:
            raise HtmlPeligroso(f"etiqueta <{nombre}> no permitida")
        if nombre == "meta" and set(nodo.attrs) != {"charset"}:
            claves = ", ".join(sorted(f"«{clave.lower()}»" for clave in nodo.attrs)) or "ninguno"
            raise HtmlPeligroso(f"<meta> solo admite «charset» (lleva {claves})")


def _validar_atributos(etiqueta: str, atributos: dict) -> None:
    permitidos = ATRIBUTOS_GLOBALES | ATRIBUTOS_POR_ETIQUETA.get(etiqueta, frozenset())
    for clave, valor in list(atributos.items()):
        atributo = clave.lower()
        if atributo not in permitidos:
            raise HtmlPeligroso(f"atributo «{atributo}» no permitido en <{etiqueta}>")
        texto = " ".join(valor) if isinstance(valor, list) else str(valor)
        if atributo == "class":
            _validar_clases(etiqueta, texto.split())
            continue
        if atributo == "allow":
            atributos[clave] = _validar_allow(etiqueta, texto)
            continue
        if atributo == "sandbox":
            # Solo el valor fijo que añade tiza (así lo publicado se puede volver a analizar).
            if texto.strip() != SANDBOX_INCRUSTADOS:
                raise HtmlPeligroso(f"valor no permitido en «sandbox» de <{etiqueta}>")
            continue
        if atributo == "style":
            # Lo que se publica es el CSS reescrito desde los tokens ya validados.
            css = _validar_estilo(etiqueta, texto)
            if css:
                atributos[clave] = css
            else:
                del atributos[clave]
            continue
        patron = _VALORES.get(atributo)
        if patron is not None and not patron.match(texto.strip()):
            raise HtmlPeligroso(f"valor no permitido en «{atributo}» de <{etiqueta}>")
        if atributo == "allowfullscreen":
            atributos[clave] = ""


# --------------------------------------------------------------------------- #
# CSS de los atributos style
# --------------------------------------------------------------------------- #

# Solo lo que maqueta. Fuera todo lo que coloca o superpone (position, top/left…,
# z-index, transform), oculta (visibility, opacity, display:none) o añade
# contenido (content): con eso se podría tapar la interfaz de Moodle con un botón
# o un inicio de sesión falsos.
_PROPIEDAD_CSS = re.compile(
    r"\A(?:"
    r"color|font-family|font-size|font-style|font-weight|line-height|letter-spacing"
    r"|text-align|text-decoration|text-transform|text-indent|vertical-align|white-space"
    r"|list-style-type"
    r"|background|background-color"
    r"|margin(?:-top|-right|-bottom|-left)?"
    r"|padding(?:-top|-right|-bottom|-left)?"
    r"|border(?:-top|-right|-bottom|-left)?(?:-width|-style|-color)?"
    r"|border-radius|border-(?:top|bottom)-(?:left|right)-radius|border-collapse"
    r"|box-shadow|box-sizing"
    r"|(?:min-|max-)?(?:width|height)|aspect-ratio"
    r"|display|float|clear|overflow(?:-x|-y)?"
    r"|flex(?:-direction|-wrap|-flow|-grow|-shrink|-basis)?"
    r"|justify-content|align-(?:items|content|self)|gap|row-gap|column-gap"
    r"|grid-template-columns|grid-column"
    r")\Z"
)
_DISPLAY = frozenset(
    {"block", "inline", "inline-block", "flex", "inline-flex", "grid", "table", "table-row"}
    | {"table-cell"}
)
_FUNCIONES_CSS = frozenset(
    {"rgb", "rgba", "hsl", "hsla", "linear-gradient", "radial-gradient", "repeat", "minmax"}
)
_UNIDADES_CSS = frozenset({"px", "em", "rem", "pt", "ch", "fr", "deg"})
_IDENTIFICADOR_CSS = re.compile(r"\A[A-Za-z][A-Za-z0-9-]*\Z")
_COLOR_HEX = re.compile(r"\A(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})\Z")
_NOMBRE_DE_FUENTE = re.compile(r"\A[\w .-]{1,60}\Z")
_LITERALES_CSS = frozenset({",", "/"})
_LARGO_MAXIMO_STYLE = 4000
# Topes en píxeles (las demás unidades se convierten): una caja, un relleno o una sombra
# gigantes taparían lo que hay alrededor, y el fondo de un relleno se pinta aunque el
# elemento sea de línea y no mueva nada.
_NUMERO_MAXIMO = 2000
_NUMERO_MAXIMO_PINTADO = 64  # padding* y box-shadow
_PIXELES_POR_UNIDAD = {"px": 1, "em": 16, "rem": 16, "pt": 4 / 3, "ch": 8, "fr": 1, "deg": 1}
_PROFUNDIDAD_MAXIMA = 4


def _validar_estilo(etiqueta: str, texto: str) -> str:
    """Valida un atributo style y devuelve el CSS reescrito desde sus tokens."""
    if len(texto) > _LARGO_MAXIMO_STYLE:
        raise HtmlPeligroso(f"el atributo style de <{etiqueta}> es demasiado largo")
    declaraciones: list[str] = []
    nodos = tinycss2.parse_blocks_contents(texto, skip_comments=False, skip_whitespace=True)
    for nodo in nodos:
        if nodo.type == "comment":
            raise HtmlPeligroso(f"comentario CSS no permitido en <{etiqueta}>")
        if nodo.type == "error":
            raise HtmlPeligroso(f"CSS mal formado en el style de <{etiqueta}>")
        if nodo.type != "declaration":
            raise HtmlPeligroso(f"regla CSS no permitida en el style de <{etiqueta}>")
        propiedad = nodo.lower_name
        if not _PROPIEDAD_CSS.match(propiedad):
            raise HtmlPeligroso(f"propiedad CSS «{propiedad}» no permitida en <{etiqueta}>")
        if nodo.important:
            raise HtmlPeligroso(f"«!important» no permitido en «{propiedad}» de <{etiqueta}>")
        pintado = propiedad == "box-shadow" or propiedad.startswith("padding")
        tope = _NUMERO_MAXIMO_PINTADO if pintado else _NUMERO_MAXIMO
        try:
            _revisar_valor(propiedad, nodo.value, tope, 0)
        except _ValorCss as exc:
            raise HtmlPeligroso(
                f"valor CSS no permitido en «{propiedad}» de <{etiqueta}>: {exc}"
            ) from None
        valor = re.sub(r"\s+", " ", tinycss2.serialize(nodo.value)).strip()
        if not valor:
            raise HtmlPeligroso(f"valor CSS vacío en «{propiedad}» de <{etiqueta}>")
        declaraciones.append(f"{propiedad}:{valor}")
    return ";".join(declaraciones)


class _ValorCss(Exception):
    """Motivo por el que un valor de CSS no se admite (se envuelve en HtmlPeligroso)."""


def _revisar_valor(propiedad: str, tokens, tope: float, profundidad: int) -> None:
    if profundidad > _PROFUNDIDAD_MAXIMA:
        raise _ValorCss("funciones anidadas en exceso")
    for token in tokens:
        tipo = token.type
        if tipo == "whitespace":
            continue
        if tipo == "ident":
            if not _IDENTIFICADOR_CSS.match(token.value):
                raise _ValorCss("identificador no permitido")
            if propiedad == "display" and token.lower_value not in _DISPLAY:
                raise _ValorCss(f"display «{token.lower_value}» no permitido")
        elif tipo in {"number", "percentage"}:
            _revisar_numero(token.value, tope)
        elif tipo == "dimension":
            if token.lower_unit not in _UNIDADES_CSS:
                raise _ValorCss(f"unidad «{token.lower_unit}» no permitida")
            _revisar_numero(token.value * _PIXELES_POR_UNIDAD[token.lower_unit], tope)
        elif tipo == "hash":
            if not _COLOR_HEX.match(token.value):
                raise _ValorCss("color hexadecimal no válido")
        elif tipo == "string":
            if propiedad != "font-family" or not _NOMBRE_DE_FUENTE.match(token.value):
                raise _ValorCss("texto entre comillas no permitido")
        elif tipo == "literal":
            if token.value not in _LITERALES_CSS:
                raise _ValorCss(f"símbolo «{token.value}» no permitido")
        elif tipo == "function":
            if token.lower_name not in _FUNCIONES_CSS:
                raise _ValorCss(f"función «{token.lower_name}()» no permitida")
            _revisar_valor(propiedad, token.arguments, tope, profundidad + 1)
        elif tipo == "url":
            raise _ValorCss("función «url()» no permitida")
        elif tipo == "comment":
            raise _ValorCss("comentario no permitido")
        elif tipo in {"error", "bad-url", "bad-string"}:
            raise _ValorCss("CSS mal formado")
        else:
            raise _ValorCss(f"bloque o elemento «{tipo}» no permitido")


def _revisar_numero(valor: float, tope: float) -> None:
    if valor < 0:
        raise _ValorCss("los valores negativos no están permitidos")
    if not valor <= tope:
        raise _ValorCss(f"número demasiado grande (el máximo es {tope:g})")


# --------------------------------------------------------------------------- #
# Iframes
# --------------------------------------------------------------------------- #

# Solo https y solo estos servidores exactos (sin usuario, puerto ni subdominios
# distintos). El valor es el prefijo de ruta obligatorio, si lo hay.
_SERVIDORES_INCRUSTABLES: dict[str, str] = {
    # Vídeo
    "www.youtube.com": "/embed/",
    "youtube.com": "/embed/",
    "www.youtube-nocookie.com": "/embed/",
    "player.vimeo.com": "",
    # Presentaciones
    "view.genially.com": "",
    "view.genial.ly": "",
    "www.canva.com": "",
    # Actividades
    "wordwall.net": "",
    "www.tizaplay.com": "",
    "es.tizaplay.com": "",
    "learningapps.org": "",
    # Ciencias y mates
    "www.geogebra.org": "",
    "phet.colorado.edu": "",
}
_YOUTUBE = frozenset({"www.youtube.com", "youtube.com"})
_YOUTUBE_SIN_COOKIES = "www.youtube-nocookie.com"
_URL_INCRUSTADA = re.compile(
    r"\Ahttps://(?P<servidor>[A-Za-z0-9.-]+)(?P<resto>(?:[/?#][^\s\\<>\"'`]*)?)\Z"
)
# Lo único que el iframe puede pedirle al navegador. Fuera: camera, microphone,
# geolocation, payment, usb…
_PERMISOS_INCRUSTADOS = frozenset(
    {
        "accelerometer",
        "autoplay",
        "clipboard-write",
        "encrypted-media",
        "fullscreen",
        "gyroscope",
        "picture-in-picture",
        "web-share",
    }
)
# Sin allow-top-navigation: lo incrustado no puede sustituir la página de Moodle.
SANDBOX_INCRUSTADOS = (
    "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox "
    "allow-forms allow-presentation"
)


def _normalizar_iframe(iframe: Tag) -> str:
    """Valida el iframe, lo deja como se publicará y devuelve su URL."""
    valor = iframe.get("src")
    if not isinstance(valor, str) or not valor.strip():
        raise HtmlPeligroso("<iframe> sin «src»")
    original = valor.strip()
    if CONTROL.search(original):
        raise HtmlPeligroso("la URL del <iframe> contiene caracteres de control")
    coincidencia = _URL_INCRUSTADA.match(original)
    if coincidencia is None:
        raise HtmlPeligroso("el «src» de <iframe> debe ser una URL https sin usuario ni puerto")
    servidor = coincidencia.group("servidor").lower()
    resto = coincidencia.group("resto")
    prefijo = _SERVIDORES_INCRUSTABLES.get(servidor)
    if prefijo is None:
        raise HtmlPeligroso(f"servidor «{servidor}» no permitido en <iframe>")
    if prefijo and not re.split(r"[?#]", resto, maxsplit=1)[0].startswith(prefijo):
        raise HtmlPeligroso(f"en «{servidor}» solo se admiten direcciones {prefijo}… en <iframe>")
    if servidor in _YOUTUBE:
        servidor = _YOUTUBE_SIN_COOKIES
    url = f"https://{servidor}{resto}"
    if any(not isinstance(hijo, str) or hijo.strip() for hijo in iframe.contents):
        raise HtmlPeligroso("el <iframe> debe estar vacío")
    iframe["src"] = url
    iframe["sandbox"] = SANDBOX_INCRUSTADOS
    return url


def _validar_allow(etiqueta: str, texto: str) -> str:
    permisos = [permiso.strip() for permiso in texto.split(";") if permiso.strip()]
    for permiso in permisos:
        if permiso not in _PERMISOS_INCRUSTADOS:
            raise HtmlPeligroso(f"permiso «{permiso}» no permitido en «allow» de <{etiqueta}>")
    return "; ".join(permisos)


def _validar_clases(etiqueta: str, clases: list[str]) -> None:
    for clase in clases:
        if (
            clase in _CLASES_EXACTAS
            or _PATRON_CLASE.match(clase)
            or (etiqueta == "a" and _PATRON_CLASE_BOTON.match(clase))
            or (etiqueta == "code" and _PATRON_CLASE_LENGUAJE.match(clase))
        ):
            continue
        raise HtmlPeligroso(f"clase «{clase}» no permitida en <{etiqueta}>")


def _clasificar_url(etiqueta: str, valor: str) -> str:
    """«externa», «local» o «interna» (#ancla, mailto:, imagen data:); si no, rechaza."""
    if CONTROL.search(valor):
        raise HtmlPeligroso("la URL contiene caracteres de control")
    limpio = valor.strip()
    if limpio.startswith("#"):
        return "interna"
    if limpio.startswith("//"):
        return "externa"
    if re.match(r"[\\/]{2}", limpio):  # \\servidor (red de Windows) o /\host
        raise HtmlPeligroso("la URL no puede empezar por barras invertidas")
    try:
        esquema = urlsplit(limpio).scheme.lower()
    except ValueError:
        raise HtmlPeligroso("URL mal formada") from None
    if not esquema or len(esquema) == 1:  # ruta relativa, o C:\… de Windows
        return "local"
    if esquema in {"http", "https"}:
        return "externa"
    if etiqueta == "a" and esquema == "mailto":
        return "interna"
    if etiqueta == "img" and _DATA_IMAGEN.match(limpio):
        return "interna"
    raise HtmlPeligroso(f"URL «{esquema}:» no permitida en <{etiqueta}>")
