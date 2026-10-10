"""Cuestionario de Moodle (``mod_quiz``): ajustes, preguntas y fechas."""

from __future__ import annotations

import math
from datetime import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .. import contenido, filtro
from ..contenido import ErrorContenido
from .base import Contexto, Extras, FechaActividad, Tipo, fechas_payload

# Campos propios del frontmatter (las preguntas van dentro) y campos de fecha del
# formulario de Moodle («Abrir el cuestionario» y «Cerrar el cuestionario»).
CAMPOS_CUESTIONARIO = frozenset(
    {"apertura", "cierre", "tiempo_limite", "intentos", "mezclar_respuestas", "preguntas"}
)
CAMPOS_FECHA = ("timeopen", "timeclose")

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


class Cuestionario(Tipo):
    nombre = "cuestionario"
    llano = "Cuestionario"
    modulo = "quiz"
    campos = CAMPOS_CUESTIONARIO
    finalizaciones = ("ninguna", "manual", "ver", "calificar")
    banderas = ("completionview", "completionusegrade")
    campos_fecha = CAMPOS_FECHA

    def validar(self, datos: dict, ctx: Contexto) -> Extras:
        return Extras(cuestionario=_validar_cuestionario(datos, ctx))

    def fechas(self, doc) -> tuple[FechaActividad, ...]:
        cuestionario = doc.cuestionario
        return (
            FechaActividad("apertura", cuestionario.apertura if cuestionario else None, "timeopen"),
            FechaActividad(
                "cierre",
                cuestionario.cierre if cuestionario else None,
                "timeclose",
                exige_clase=True,
            ),
        )

    def payload_solo_fechas(self, doc) -> dict[str, str]:
        return {
            "_qf__mod_quiz_mod_form": "1",
            "submitbutton2": "Save and return to course",
            **fechas_payload(self, doc),
        }


# --------------------------------------------------------------------------- #
# Validación del cuestionario, sus preguntas y sus opciones
# --------------------------------------------------------------------------- #


def _validar_cuestionario(datos: dict[str, Any], ctx: Contexto) -> contenido.Cuestionario:
    apertura = (
        ctx.fecha(datos["apertura"], time(0, 0)) if datos.get("apertura") is not None else None
    )
    cierre = ctx.fecha(datos["cierre"], time(23, 59)) if datos.get("cierre") is not None else None
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
        _validar_pregunta(pregunta, numero, ctx, externos, incrustados)
        for numero, pregunta in enumerate(valor_preguntas, 1)
    )
    return contenido.Cuestionario(
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
    valor: Any, numero: int, ctx: Contexto, externos: list[str], incrustados: list[str]
) -> contenido.Pregunta:
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
    html = _html_de_campo(ctx, enunciado, donde, externos, incrustados)

    retro = _texto_opcional(valor.get("retro"), donde, "retro")
    retro_html = (
        _html_de_campo(ctx, retro, donde, externos, incrustados) if retro is not None else None
    )

    if tipo == "opcion_multiple":
        opciones = _validar_opciones(valor.get("opciones"), donde, ctx, externos, incrustados)
        return contenido.Pregunta(
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
        return contenido.Pregunta(
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
        return contenido.Pregunta(
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
    return contenido.Pregunta(
        tipo=tipo,
        enunciado=enunciado,
        html=html,
        valor=float(valor_num),
        tolerancia=float(tolerancia),
        retro=retro,
        retro_html=retro_html,
    )


def _validar_opciones(
    valor: Any, donde: str, ctx: Contexto, externos: list[str], incrustados: list[str]
) -> tuple[contenido.Opcion, ...]:
    if not isinstance(valor, list) or not 2 <= len(valor) <= 10:
        raise ErrorContenido(
            "OPCIONES_INVALIDAS", f"{donde}: «opciones» debe ser una lista de 2 a 10"
        )
    opciones: list[contenido.Opcion] = []
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
            contenido.Opcion(
                texto=texto,
                html=_html_de_campo(ctx, texto, donde_opcion, externos, incrustados),
                correcta=bool(correcta),
                retro=retro,
                retro_html=(
                    _html_de_campo(ctx, retro, donde_opcion, externos, incrustados)
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


def _html_de_campo(
    ctx: Contexto, texto: str, donde: str, externos: list[str], incrustados: list[str]
) -> str:
    """Renderiza un campo Markdown de una pregunta y lo pasa por el filtro."""
    try:
        analisis = filtro.analizar(ctx.render(texto))
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
