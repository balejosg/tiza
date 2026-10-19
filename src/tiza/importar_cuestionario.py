"""Los cuestionarios de una copia de Moodle, en el formato de ``preguntas:`` de tiza.

Lo usa ``tiza importar``. Regla de fondo: lo que se importa tiene que publicarse de vuelta sin
cambiar nada en el aula. Una pregunta, o un ajuste, que tiza no escribiría igual al publicar
(otra puntuación, otro orden, retroalimentación por respuesta, unidades…) no se importa: el
cuestionario queda como ``PREGUNTAS_NO_ADMITIDAS`` o ``AJUSTES_NO_ADMITIDOS`` y el detalle dice
el motivo, con textos de tiza (nunca texto de la copia).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any

from .copia import ActividadCopia, PreguntaCopia, RespuestaCopia
from .cuestionario import fraccion_correcta

__all__ = [
    "ajustes_del_cuestionario",
    "convertir_preguntas",
    "html_como_markdown",
]

_TIPOS_PREGUNTA = ("truefalse", "multichoice", "shortanswer", "numerical")
_MAX_PREGUNTAS = 100
_MAX_ENUNCIADO = 5000
_PENALIZACION = 0.3333333  # la de tiza, salvo en verdadero/falso (1)

# --------------------------------------------------------------------------- #
# HTML de Moodle en un campo que tiza lee como Markdown
# --------------------------------------------------------------------------- #

# Etiquetas que abren en CommonMark un bloque HTML que acaba en la primera línea en blanco
# (tipo 6): dentro de él, el Markdown no se interpreta y ``2*3*4`` sigue siendo ``2*3*4``.
_ES_BLOQUE = re.compile(
    r"<(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|"
    r"details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|"
    r"h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|"
    r"optgroup|option|p|param|section|source|summary|table|tbody|td|tfoot|th|thead|title|tr|"
    r"track|ul)(?:[\s/>]|$)",
    re.IGNORECASE,
)
_ES_PRE = re.compile(r"<pre(?:[\s/>]|$)", re.IGNORECASE)
_ABRE_PRE = re.compile(r"<pre(?=[\s/>]|$)", re.IGNORECASE)
_CIERRA_PRE = re.compile(r"</pre>", re.IGNORECASE)
_LINEAS_EN_BLANCO = re.compile(r"\n[ \t]*(?:\n[ \t]*)+")


def _partes_pre(texto: str) -> list[tuple[bool, str]]:
    """El texto en tramos (¿es un ``<pre>``?, tramo), en una sola pasada.

    Sin una expresión regular de ``<pre`` a ``</pre>``: con muchos ``<pre`` sin cierre sería
    cuadrática. Un ``<pre`` sin cierre no abre nada y, como ya no hay más cierres, se acaba.
    """
    partes: list[tuple[bool, str]] = []
    pos = 0
    while True:
        abre = _ABRE_PRE.search(texto, pos)
        if abre is None:
            break
        cierra = _CIERRA_PRE.search(texto, abre.end())
        if cierra is None:
            break
        partes.append((False, texto[pos : abre.start()]))
        partes.append((True, texto[abre.start() : cierra.end()]))
        pos = cierra.end()
    partes.append((False, texto[pos:]))
    return partes


def html_como_markdown(html: str) -> str:
    """El HTML de Moodle, listo para un campo que tiza lee como Markdown, con el mismo sentido.

    tiza renderiza los textos de las preguntas y el cuerpo de un ``.md`` como Markdown con HTML
    permitido; un ``*`` o un ``_`` fuera de un bloque HTML cambiaría el texto (``2*3*4`` pasaría a
    llevar cursiva). Por eso el texto se deja como un único bloque HTML: sin líneas en blanco
    (salvo dentro de ``<pre>``, que tiza ya protege) y, si no empieza por una etiqueta de bloque,
    dentro de un ``<p>`` (o de un ``<div>`` si empieza por ``<pre>``).
    """
    texto = html.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not texto:
        return ""
    texto = "".join(
        parte if es_pre else _LINEAS_EN_BLANCO.sub("\n", parte)
        for es_pre, parte in _partes_pre(texto)
    )
    if _ES_BLOQUE.match(texto):
        return texto
    return f"<div>{texto}</div>" if _ES_PRE.match(texto) else f"<p>{texto}</p>"


# --------------------------------------------------------------------------- #
# Preguntas
# --------------------------------------------------------------------------- #


def _motivo(pregunta: PreguntaCopia, que: str = "") -> str:
    tipo = re.sub(r"[^a-z0-9_]", "", pregunta.tipo.lower())[:30] or "desconocida"
    return f"{tipo}({que})" if que else tipo


def _es(valor: float, esperado: float) -> bool:
    return math.isclose(valor, esperado, abs_tol=1e-6)


def _fracciones_de_multichoice(respuestas: Sequence[RespuestaCopia]) -> bool:
    """¿Son las que tiza generaría? Una correcta: 1 y 0. Varias (2 a 10): ±n según la tabla."""
    fracciones = [r.fraccion for r in respuestas]
    correctas = sum(1 for x in fracciones if x > 0)
    if correctas == 1:
        return all(_es(x, 1.0) or _es(x, 0.0) for x in fracciones)
    if not 2 <= correctas <= 10:
        return False
    valor = float(fraccion_correcta(correctas)) / 100
    return all(_es(x, valor) if x > 0 else _es(x, -valor) for x in fracciones)


def _validar(pregunta: PreguntaCopia) -> str | None:
    """El motivo (texto de tiza) por el que la pregunta no se puede importar, o ``None``."""
    if pregunta.tipo not in _TIPOS_PREGUNTA:
        return _motivo(pregunta)
    multi = pregunta.tipo == "multichoice"
    if not pregunta.formato_html or (
        multi and not all(r.formato_html for r in pregunta.respuestas)
    ):
        return _motivo(pregunta, "formato de texto no HTML")
    textos = [pregunta.texto, pregunta.retroalimentacion]
    textos += [r.texto for r in pregunta.respuestas]
    textos += [r.retroalimentacion for r in pregunta.respuestas]
    if any("@@PLUGINFILE@@" in t for t in textos):
        return _motivo(pregunta, "con ficheros")
    if not pregunta.texto.strip() or len(pregunta.texto) > _MAX_ENUNCIADO:
        return _motivo(pregunta, "enunciado")
    if not _es(pregunta.puntos, 1.0):
        return _motivo(pregunta, "puntos distintos de 1")
    esperada = 1.0 if pregunta.tipo == "truefalse" else _PENALIZACION
    if pregunta.penalizacion is not None and not _es(pregunta.penalizacion, esperada):
        return _motivo(pregunta, "penalización distinta")
    if pregunta.con_unidades:
        return _motivo(pregunta, "con unidades")
    respuestas = pregunta.respuestas
    if multi:
        if pregunta.opciones.get("shuffleanswers") == "0":
            return _motivo(pregunta, "sin mezclar")
        if not 2 <= len(respuestas) <= 10 or any(not r.texto.strip() for r in respuestas):
            return _motivo(pregunta, "opciones")
        if not _fracciones_de_multichoice(respuestas):
            return _motivo(pregunta, "fracciones parciales")
        correctas = sum(1 for r in respuestas if r.fraccion > 0)
        # tiza publica «una sola respuesta» solo si hay exactamente una correcta.
        esperado = "1" if correctas == 1 else "0"
        if pregunta.opciones.get("single", esperado) != esperado:
            return _motivo(pregunta, "fracciones parciales")
        return None
    if any(r.retroalimentacion.strip() for r in respuestas):
        return _motivo(pregunta, "retroalimentación por respuesta")
    if pregunta.tipo == "truefalse":  # 1 y 0 exactos, que se comprueban al convertirla
        return None
    if any(_es(r.fraccion, 0.0) for r in respuestas):
        return _motivo(pregunta, "respuesta de fracción 0")
    if not respuestas or not all(_es(r.fraccion, 1.0) for r in respuestas):
        return _motivo(pregunta, "fracciones parciales")
    return None


def _convertir(pregunta: PreguntaCopia) -> dict[str, Any] | str:
    """La pregunta en el formato de tiza, o el motivo por el que no se puede."""
    motivo = _validar(pregunta)
    if motivo is not None:
        return motivo
    enunciado = html_como_markdown(pregunta.texto)
    respuestas = pregunta.respuestas
    resultado: dict[str, Any]
    if pregunta.tipo == "truefalse":
        if len(respuestas) != 2:
            return _motivo(pregunta, "respuestas")
        verdadera, falsa = respuestas
        por_id = {r.id: r for r in respuestas if r.id}
        if (
            pregunta.opciones.get("trueanswer", "").isdigit()
            and pregunta.opciones.get("falseanswer", "").isdigit()
        ):
            verdadera = por_id.get(int(pregunta.opciones["trueanswer"]), verdadera)
            falsa = por_id.get(int(pregunta.opciones["falseanswer"]), falsa)
        if not (
            (_es(verdadera.fraccion, 1.0) and _es(falsa.fraccion, 0.0))
            or (_es(verdadera.fraccion, 0.0) and _es(falsa.fraccion, 1.0))
        ):
            return _motivo(pregunta, "respuestas")
        resultado = {
            "tipo": "verdadero_falso",
            "enunciado": enunciado,
            "respuesta": "verdadero" if _es(verdadera.fraccion, 1.0) else "falso",
        }
    elif pregunta.tipo == "multichoice":
        opciones = []
        for r in respuestas:
            opcion: dict[str, Any] = {"texto": html_como_markdown(r.texto)}
            if r.fraccion > 0:
                opcion["correcta"] = True
            if r.retroalimentacion.strip():
                opcion["retro"] = html_como_markdown(r.retroalimentacion)
            opciones.append(opcion)
        resultado = {"tipo": "opcion_multiple", "enunciado": enunciado, "opciones": opciones}
    elif pregunta.tipo == "shortanswer":
        if any(not r.texto.strip() for r in respuestas):
            return _motivo(pregunta, "respuestas")
        resultado = {
            "tipo": "respuesta_corta",
            "enunciado": enunciado,
            "aceptadas": [r.texto.strip() for r in respuestas],
        }
        if pregunta.opciones.get("usecase") == "1":
            resultado["mayusculas"] = True
    else:
        if len(respuestas) != 1:
            return _motivo(pregunta, "respuestas")
        try:
            valor = float(respuestas[0].texto.strip())
        except ValueError:
            return _motivo(pregunta, "valor")
        if not math.isfinite(valor):
            return _motivo(pregunta, "valor")
        resultado = {"tipo": "numerica", "enunciado": enunciado, "valor": valor}
        if respuestas[0].tolerancia > 0:
            resultado["tolerancia"] = respuestas[0].tolerancia
    if pregunta.retroalimentacion.strip():
        resultado["retro"] = html_como_markdown(pregunta.retroalimentacion)
    return resultado


def convertir_preguntas(actividad: ActividadCopia) -> tuple[list[dict[str, Any]], list[str]]:
    """Las preguntas convertidas y los motivos (sin repetir, en orden) de las que no se pueden."""
    convertidas: list[dict[str, Any]] = []
    motivos: list[str] = []
    for pregunta in actividad.preguntas:
        resultado = _convertir(pregunta)
        if isinstance(resultado, str):
            if resultado not in motivos:
                motivos.append(resultado)
        else:
            convertidas.append(resultado)
    if not actividad.preguntas:
        motivos.append("sin_preguntas")
    elif len(actividad.preguntas) > _MAX_PREGUNTAS:
        motivos.append(f"más_de_{_MAX_PREGUNTAS}_preguntas")
    return convertidas, motivos


# --------------------------------------------------------------------------- #
# Ajustes
# --------------------------------------------------------------------------- #


def ajustes_del_cuestionario(actividad: ActividadCopia) -> tuple[dict[str, Any], list[str]]:
    """``intentos``, ``tiempo_limite`` (minutos) y ``mezclar_respuestas`` con la semántica de tiza.

    tiza los manda siempre al publicar: sin ellos, republicar pisaría los del aula. Lo que tiza no
    puede decir (más de 10 intentos, un tiempo que no son minutos enteros de 1 a 600) no se
    aproxima, porque cambiaría el aula al republicar: se devuelven los motivos y el cuestionario
    no se importa.
    """
    ajustes: dict[str, Any] = {}
    motivos: list[str] = []
    intentos = actividad.intentos
    if intentos is not None and intentos >= 0:
        if intentos > 10:
            motivos.append("más de 10 intentos")
        ajustes["intentos"] = "ilimitados" if intentos == 0 else intentos
    segundos = actividad.tiempo_limite
    if segundos is not None:
        minutos, resto = divmod(segundos, 60)
        if resto or not 1 <= minutos <= 600:
            motivos.append("un tiempo límite que no son minutos enteros de 1 a 600")
        ajustes["tiempo_limite"] = minutos
    if actividad.mezclar_respuestas is not None:
        ajustes["mezclar_respuestas"] = actividad.mezclar_respuestas
    return ajustes, motivos
