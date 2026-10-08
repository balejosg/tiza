"""Paquete ``.h5p`` de las actividades generadas por tiza (offline, sin red).

Construye un paquete **solo contenido** (``h5p.json`` y ``content/content.json``)
a partir del documento ya validado: nunca lleva librerías ni JavaScript. Las
cadenas de interfaz van en español, tomadas del ``language/es.json`` de cada
librería; sin ellas H5P saldría en inglés. El paquete es determinista: el mismo
documento produce exactamente los mismos bytes, para que el hash y la puerta
de real sigan valiendo.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from .contenido import (
    ActividadH5P,
    Documento,
)

__all__ = ["LIBRERIAS", "paquete_h5p", "resumen_paquete"]

# Versiones mayor.menor confirmadas en la espiga (Moodle 4.5.15, CT 130). H5P
# acepta también un minor anterior con el minor instalado; una actualización del
# aula dentro del mismo mayor sigue sirviendo. La autoprueba detecta si faltan.
LIBRERIAS: dict[str, tuple[str, int, int]] = {
    "rellenar_huecos": ("H5P.Blanks", 1, 14),
    "arrastrar_palabras": ("H5P.DragText", 1, 10),
    "marcar_palabras": ("H5P.MarkTheWords", 1, 11),
    "tarjetas": ("H5P.Dialogcards", 1, 9),
}

_ES_BLANKS = {
    "text": "Rellenar con las palabras que faltan",
    "showSolutions": "Mostrar solución",
    "tryAgain": "Intentar de nuevo",
    "checkAnswer": "Comprobar",
    "submitAnswer": "Enviar",
    "notFilledOut": "Por favor, completa todos los huecos para poder ver la solución",
    "answerIsCorrect": "':ans' es correcta",
    "answerIsWrong": "':ans' es incorrecta",
    "answeredCorrectly": "Contestado correctamente",
    "answeredIncorrectly": "Contestado incorrectamente",
    "solutionLabel": "Respuesta correcta:",
    "inputLabel": "Hueco @num de @total",
    "inputHasTipLabel": "Pista disponible",
    "tipLabel": "Pista",
    "scoreBarLabel": "Has conseguido :num de un total de :total puntos",
    "a11yCheck": (
        "Comprobar las respuestas. Las respuestas serán marcadas como correcta, "
        "incorrectas o sin contestar."
    ),
    "a11yShowSolution": "Mostrar la solución. La tarea se marcará con su solución correcta.",
    "a11yRetry": "Vuelve a intentar la tarea. Borra todas tus respuestas y empieza de nuevo.",
    "a11yCheckingModeHeader": "Modo de Comprobación",
    "confirmCheck": {
        "header": "¿ Terminar ?",
        "body": "¿Está seguro que desea terminar ?",
        "cancelLabel": "Cancelar",
        "confirmLabel": "Terminar",
    },
    "confirmRetry": {
        "header": "¿Intentar de nuevo?",
        "body": "¿Seguro que quieres volver a intentarlo?",
        "cancelLabel": "Cancelar",
        "confirmLabel": "Confirmar",
    },
}

_ES_DRAGTEXT = {
    "taskDescription": "Arrastra las palabras a las cajas correctas",
    "checkAnswer": "Comprobar",
    "submitAnswer": "Enviar",
    "tryAgain": "Reintentar",
    "showSolution": "Mostrar solución",
    "dropZoneIndex": "Zona de colocación @index.",
    "empty": "La zona de Colocación @index está vacía.",
    "contains": "la zona de Colocación @index contiene elemento @draggable.",
    "ariaDraggableIndex": "@index de @count elementos que se pueden colocar.",
    "tipLabel": "Mostrar pista",
    "correctText": "¡Correcto!",
    "incorrectText": "¡Incorrecto!",
    "resetDropTitle": "Restablecer colocación",
    "resetDropDescription": "¿Seguro que quieres restablecer esta zona de colocación?",
    "grabbed": "Has cogido el elemento a arrastrar.",
    "cancelledDragging": "Arrastre cancelado.",
    "correctAnswer": "Respuesta correcta:",
    "feedbackHeader": "Retroalimentación",
    "scoreBarLabel": "Has obtenido :num de un total de :total puntos",
    "a11yCheck": (
        "Comprueba las respuestas. Las respuestas se marcarán como correctas, "
        "incorrectas o sin respuesta."
    ),
    "a11yShowSolution": "Mostrar la solución. El trabajo será calificado con su solución correcta.",
    "a11yRetry": "Vuelve a intentar la tarea. Borra todas tus respuestas y empieza de nuevo.",
}

_ES_MARKTHEWORDS = {
    "checkAnswerButton": "Comprobar",
    "submitAnswerButton": "Enviar",
    "tryAgainButton": "Intentar de nuevo",
    "showSolutionButton": "Mostrar solución",
    "correctAnswer": "¡Correcto!",
    "incorrectAnswer": "¡Incorrecto!",
    "missedAnswer": "¡Respuesta no encontrada!",
    "displaySolutionDescription": "La tarea se ha actualizado con la solución.",
    "scoreBarLabel": "Has obtenido :num de un total de :total puntos",
    "a11yFullTextLabel": "Texto completo legible",
    "a11yClickableTextLabel": "Texto completo donde se pueden marcar las palabras",
    "a11ySolutionModeHeader": "Modo Solución",
    "a11yCheckingHeader": "Modo de Comprobación",
    "a11yCheck": (
        "Revisa tus respuestas. Las respuestas se marcarán como correcta, "
        "incorrecta o sin contestar."
    ),
    "a11yShowSolution": "Mostrar la solución. La tarea se calificará con su solución correcta.",
    "a11yRetry": "Vuelve a intentar la tarea. Borra todas tus respuestas y empieza de nuevo.",
}

_ES_DIALOGCARDS = {
    "answer": "Voltear",
    "next": "Siguiente",
    "prev": "Anterior",
    "retry": "Reintentar",
    "correctAnswer": "¡La tuve buena!",
    "incorrectAnswer": "La tuve mala",
    "round": "Ronda @round",
    "cardsLeft": "Cartas restantes: @number",
    "nextRound": "Avanzar a ronda @round",
    "startOver": "Comenzar de nuevo",
    "showSummary": "Siguiente",
    "summary": "Resumen",
    "summaryCardsRight": "Cartas que tuvo correctas:",
    "summaryCardsWrong": "Cartas que tuvo incorrectas:",
    "summaryCardsNotShown": "Cartas en el mazo no mostradas:",
    "summaryOverallScore": "Puntaje Global",
    "summaryCardsCompleted": "Cartas que ha completado el aprendizaje:",
    "summaryCompletedRounds": "Rondas completadas:",
    "summaryAllDone": (
        "¡Bien Hecho! ¡Usted tuvo todas las @cards cartas correctas @max veces seguidas!"
    ),
    "progressText": "Carta @card de @total",
    "cardFrontLabel": "Frente de la Carta",
    "cardBackLabel": "Revés de la Carta",
    "tipButtonLabel": "Mostrar pista",
    "audioNotSupported": "Su navegador no soporta este audio",
    "confirmStartingOver": {
        "header": "¿Comenzar de nuevo?",
        "body": "Se perderá todo el progreso. ¿Está seguro de querer comenzar de nuevo?",
        "cancelLabel": "Cancelar",
        "confirmLabel": "Comenzar de nuevo",
    },
}


def _json(datos: object) -> str:
    return json.dumps(datos, ensure_ascii=False, indent=2)


def _zip(ficheros: dict[str, str | bytes]) -> bytes:
    """Zip determinista: nombres ordenados y fecha fija."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as paquete:
        for nombre in sorted(ficheros):
            datos = ficheros[nombre]
            if isinstance(datos, str):
                datos = datos.encode("utf-8")
            info = zipfile.ZipInfo(nombre, date_time=(2024, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            paquete.writestr(info, datos)
    return buf.getvalue()


def _h5p_json(doc: Documento, tipo: str) -> dict:
    machine_name, major, minor = LIBRERIAS[tipo]
    return {
        "title": doc.nombre,
        "language": "es",
        "mainLibrary": machine_name,
        "embedTypes": ["iframe"],
        "preloadedDependencies": [
            {"machineName": machine_name, "majorVersion": major, "minorVersion": minor}
        ],
    }


def _rellenar_huecos(actividad: ActividadH5P) -> dict:
    return {
        "media": {},
        "questions": [texto.h5p for texto in actividad.textos],
        "overallFeedback": [],
        **_ES_BLANKS,
        "behaviour": {
            "enableRetry": actividad.reintentar,
            "enableSolutionsButton": actividad.ver_solucion,
            "enableCheckButton": True,
            "autoCheck": False,
            "caseSensitive": actividad.mayusculas,
            "showSolutionsRequiresInput": True,
            "separateLines": False,
            "confirmCheckDialog": False,
            "confirmRetryDialog": False,
            "acceptSpellingErrors": False,
        },
    }


def _arrastrar_palabras(actividad: ActividadH5P) -> dict:
    assert actividad.texto is not None
    return {
        "media": {},
        "textField": actividad.texto.h5p,
        "distractors": " ".join(f"*{distractor}*" for distractor in actividad.distractores),
        "overallFeedback": [],
        **_ES_DRAGTEXT,
        "behaviour": {
            "enableRetry": actividad.reintentar,
            "enableSolutionsButton": actividad.ver_solucion,
            "enableCheckButton": True,
            "instantFeedback": False,
        },
    }


def _marcar_palabras(actividad: ActividadH5P) -> dict:
    assert actividad.texto is not None
    return {
        "media": {},
        "taskDescription": actividad.enunciado_html or "",
        "textField": actividad.texto.h5p,
        "overallFeedback": [],
        **_ES_MARKTHEWORDS,
        "behaviour": {
            "enableRetry": actividad.reintentar,
            "enableSolutionsButton": actividad.ver_solucion,
            "enableCheckButton": True,
            "showScorePoints": True,
        },
    }


def _tarjetas(actividad: ActividadH5P) -> dict:
    return {
        "title": "",
        "mode": "normal",
        "description": "",
        "dialogs": [
            {"text": tarjeta.anverso_html, "answer": tarjeta.reverso_html}
            for tarjeta in actividad.tarjetas
        ],
        **_ES_DIALOGCARDS,
        "behaviour": {
            "enableRetry": actividad.reintentar,
            "disableBackwardsNavigation": False,
            "scaleTextNotCard": False,
            "randomCards": False,
            "maxProficiency": 5,
            "quickProgression": False,
        },
    }


_CONTENIDO = {
    "rellenar_huecos": _rellenar_huecos,
    "arrastrar_palabras": _arrastrar_palabras,
    "marcar_palabras": _marcar_palabras,
    "tarjetas": _tarjetas,
}


def paquete_h5p(doc: Documento) -> bytes:
    """El ``.h5p`` (solo contenido) de una actividad generada, listo para subir."""
    if doc.h5p is None:
        raise ValueError("el documento no es una actividad H5P generada")
    return _zip(
        {
            "h5p.json": _json(_h5p_json(doc, doc.h5p.tipo)),
            "content/content.json": _json(_CONTENIDO[doc.h5p.tipo](doc.h5p)),
        }
    )


def resumen_paquete(ruta: str | Path) -> dict:
    """Título, librería principal y ficheros de un ``.h5p``, sin extraerlo.

    Es una lectura de solo estructura para la vista previa: un fichero que no
    sea un zip legible devuelve los campos vacíos (la validación completa llega
    con ``validar_paquete``).
    """
    ruta = Path(ruta)
    try:
        with zipfile.ZipFile(ruta) as paquete:
            nombres = paquete.namelist()
            datos = json.loads(paquete.read("h5p.json")) if "h5p.json" in nombres else {}
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError):
        return {"titulo": None, "libreria": None, "ficheros": []}
    if not isinstance(datos, dict):
        return {"titulo": None, "libreria": None, "ficheros": sorted(nombres)}
    principal = datos.get("mainLibrary")
    libreria = None
    for dependencia in datos.get("preloadedDependencies") or []:
        if isinstance(dependencia, dict) and dependencia.get("machineName") == principal:
            libreria = (
                f"{principal} {dependencia.get('majorVersion')}.{dependencia.get('minorVersion')}"
            )
            break
    titulo = datos.get("title")
    return {
        "titulo": titulo if isinstance(titulo, str) else None,
        "libreria": libreria,
        "ficheros": sorted(nombres),
    }
