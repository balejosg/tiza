"""Contenido interactivo H5P (``mod_h5pactivity``): actividad generada o paquete subido."""

from __future__ import annotations

import html as _html
import re
from typing import Any

from bs4 import Tag

from .. import filtro
from ..contenido import (
    ActividadH5P,
    ErrorContenido,
    MarcaH5P,
    PaqueteH5P,
    TarjetaH5P,
    TextoH5P,
)
from ..filtro import CONTROL as _CONTROL
from .base import Contexto, Extras, Tipo

# Todos los campos que puede llevar el bloque del frontmatter, entre los del
# documento («actividad», «paquete») y los de la actividad generada. Lo usa
# ``test_agente`` para comprobar que la skill los enseña todos.
CAMPOS_H5P = frozenset(
    {
        "actividad",
        "paquete",
        "tipo",
        "textos",
        "texto",
        "enunciado",
        "distractores",
        "tarjetas",
        "anverso",
        "reverso",
        "mayusculas",
        "calificacion",
        "reintentar",
        "ver_solucion",
    }
)

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


class H5P(Tipo):
    nombre = "h5p"
    llano = "Contenido interactivo (H5P)"
    modulo = "h5pactivity"
    campos = frozenset({"actividad", "paquete"})
    finalizaciones = ("ninguna", "manual", "ver", "calificar")
    banderas = ("completionview", "completionusegrade")

    def validar(self, datos: dict, ctx: Contexto) -> Extras:
        h5p, paquete = _validar_h5p(datos, ctx)
        return Extras(h5p=h5p, paquete=paquete)


# --------------------------------------------------------------------------- #
# Validación de la actividad H5P generada o del paquete subido
# --------------------------------------------------------------------------- #


def _validar_h5p(
    datos: dict[str, Any], ctx: Contexto
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
        return None, ctx.paquete_h5p(paquete.strip())
    return _leer_actividad_h5p(actividad, ctx), None


def _leer_actividad_h5p(valor: Any, ctx: Contexto) -> ActividadH5P:
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
            _texto_con_marcas(
                texto, f"textos {numero}", ctx, permitidas=_INLINE_HUECOS, huecos=True
            )
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
                texto, "texto", ctx, permitidas=frozenset(), huecos=True, plano=True
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
                valor.get("texto"), "texto", ctx, permitidas=_INLINE_MARCAR, huecos=True
            ),
            enunciado=enunciado,
            enunciado_html=_html_inline(enunciado, "enunciado", _INLINE_MARCAR, ctx),
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
                anverso_html=_html_inline(anverso, f"{donde}, anverso", _INLINE_TARJETA, ctx),
                reverso_html=_html_inline(reverso, f"{donde}, reverso", _INLINE_TARJETA, ctx),
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
    ctx: Contexto,
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
    h5p, partes_html = _h5p_html(partes, permitidas, donde, ctx)
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
    ctx: Contexto,
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
    html = _html_inline("".join(piezas), donde, permitidas, ctx)
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


def _html_inline(valor: str, donde: str, permitidas: frozenset[str], ctx: Contexto) -> str:
    """Markdown en línea validado por el filtro, solo con las etiquetas permitidas."""
    try:
        analisis = filtro.analizar(ctx.render(valor))
    except filtro.HtmlPeligroso as exc:
        raise ErrorContenido("HTML_PELIGROSO", f"{donde}: {exc.detalle}") from None
    for nodo in analisis.cuerpo.descendants:
        if isinstance(nodo, Tag) and (nodo.name or "").lower() not in permitidas | {"p"}:
            raise ErrorContenido(
                "ACTIVIDAD_H5P_INVALIDA",
                f"{donde}: la etiqueta <{nodo.name}> no se admite en este campo",
            )
    return filtro.serializar(analisis.cuerpo)
