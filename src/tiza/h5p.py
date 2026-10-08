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
import re
import stat
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .contenido import (
    ActividadH5P,
    Documento,
    ErrorContenido,
    PaqueteH5P,
)

__all__ = ["LIBRERIAS", "paquete_h5p", "reempaquetar", "validar_paquete"]

# Topes del .h5p subido: el comprimido se mide en contenido._resolver_paquete;
# aquí, entradas, tamaño descomprimido, proporción y el content.json.
MAX_ENTRADAS_H5P = 2000
MAX_DESCOMPRIMIDO_H5P = 128 * 1024 * 1024
MAX_PROPORCION_H5P = 200
MAX_H5P_JSON_H5P = 1024 * 1024
MAX_CONTENT_JSON_H5P = 4 * 1024 * 1024
_MACHINENAME = re.compile(r"\A[A-Za-z][A-Za-z0-9._-]{0,127}\Z")
_EXTENSIONES_MEDIO = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".mp3",
        ".m4a",
        ".ogg",
        ".oga",
        ".wav",
        ".mp4",
        ".m4v",
        ".webm",
        ".ogv",
        ".vtt",
    }
)
_URL_HTTPS = re.compile(r"https?://[^\s\"'<>\\]+")
_PELIGROSAS = re.compile(r"javascript:|vbscript:", re.IGNORECASE)

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


# --------------------------------------------------------------------------- #
# Paquetes .h5p subidos: validación y reempaquetado
# --------------------------------------------------------------------------- #


def validar_paquete(ruta: str | Path) -> PaqueteH5P:
    """Valida un ``.h5p`` subido y devuelve su estructura, sin extraerlo a disco."""
    return _validar_paquete(ruta)[0]


def reempaquetar(ruta: str | Path) -> bytes:
    """El ``.h5p`` reconstruido: ``h5p.json`` reducido y ``content/`` sin librerías."""
    validado, h5p_limpio, contenido_json = _validar_paquete(ruta)
    ficheros: dict[str, str | bytes] = {
        "h5p.json": _json(h5p_limpio),
        "content/content.json": _json(contenido_json),
    }
    try:
        with zipfile.ZipFile(validado.ruta) as paquete:
            for nombre in validado.ficheros:
                if nombre in ficheros:
                    continue
                with paquete.open(nombre) as fuente:
                    datos = fuente.read(MAX_DESCOMPRIMIDO_H5P + 1)
                if len(datos) > MAX_DESCOMPRIMIDO_H5P:
                    raise ErrorContenido(
                        "PAQUETE_H5P_DEMASIADO_GRANDE",
                        f"«{nombre}» supera el tamaño máximo descomprimido",
                    )
                ficheros[nombre] = datos
    except ErrorContenido:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        raise ErrorContenido(
            "PAQUETE_H5P_INVALIDO", f"no se pudo releer «{validado.nombre}»"
        ) from None
    return _zip(ficheros)


def _validar_paquete(
    ruta: str | Path,
) -> tuple[PaqueteH5P, dict, Any]:
    from . import contenido as _contenido

    ruta = Path(ruta)
    try:
        tamano = ruta.stat().st_size
    except OSError:
        raise ErrorContenido("PAQUETE_H5P_INVALIDO", "no se pudo leer el paquete .h5p") from None
    if tamano > _contenido.MAX_PAQUETE_H5P_BYTES:
        raise ErrorContenido(
            "PAQUETE_H5P_DEMASIADO_GRANDE",
            f"«{ruta.name}» pesa más de {_contenido.MAX_PAQUETE_H5P_BYTES // 2**20} MB",
        )
    try:
        paquete = zipfile.ZipFile(ruta)
    except (OSError, zipfile.BadZipFile):
        raise ErrorContenido("PAQUETE_H5P_INVALIDO", "no es un paquete .h5p legible") from None
    with paquete:
        infos = _revisar_entradas(paquete.infolist())
        h5p = _leer_json(paquete, "h5p.json", MAX_H5P_JSON_H5P, "falta h5p.json o no es JSON")
        h5p_limpio, titulo, libreria = _raiz_h5p(h5p)
        contenido_json = _leer_json(
            paquete,
            "content/content.json",
            MAX_CONTENT_JSON_H5P,
            "falta content/content.json o no es JSON",
        )
        if not isinstance(contenido_json, dict):
            raise ErrorContenido("PAQUETE_H5P_INVALIDO", "content/content.json debe ser un mapa")
        externos = _externos(contenido_json)
        ficheros: list[str] = []
        descartadas: list[str] = []
        for info in infos:
            nombre = info.filename
            if _ignorada(nombre):
                continue
            if nombre == "h5p.json":
                ficheros.append(nombre)
                continue
            if nombre == "content/content.json":
                ficheros.append(nombre)
                continue
            if nombre.startswith("content/"):
                if info.is_dir():
                    continue
                extension = Path(nombre).suffix.lower()
                if extension not in _EXTENSIONES_MEDIO:
                    _invalidar(f"«{nombre}» no es un medio admitido en un paquete H5P")
                ficheros.append(nombre)
                continue
            # Una carpeta de primer nivel es una librería: se descarta siempre.
            if "/" in nombre:
                descartadas.append(nombre.split("/", 1)[0])
                continue
            _invalidar(f"el paquete lleva un fichero suelto «{nombre}»")
    return (
        PaqueteH5P(
            nombre=ruta.name,
            ruta=ruta,
            titulo=titulo,
            libreria=libreria,
            ficheros=tuple(sorted(set(ficheros))),
            externos=externos,
            descartadas=tuple(sorted(set(descartadas))),
        ),
        h5p_limpio,
        contenido_json,
    )


def _revisar_entradas(infos: list[zipfile.ZipInfo]) -> list[zipfile.ZipInfo]:
    if len(infos) > MAX_ENTRADAS_H5P:
        raise ErrorContenido(
            "PAQUETE_H5P_DEMASIADO_GRANDE",
            f"el paquete lleva más de {MAX_ENTRADAS_H5P} entradas",
        )
    nombres = [info.filename for info in infos]
    if len(nombres) != len(set(nombres)):
        _invalidar("el paquete lleva entradas repetidas")
    total = 0
    for info in infos:
        if info.flag_bits & 0x1:
            _invalidar("el paquete lleva un fichero cifrado")
        if stat.S_ISLNK(info.external_attr >> 16):
            _invalidar("el paquete lleva un enlace simbólico")
        _ruta_segura(info.filename)
        if info.compress_size > 0 and info.file_size / info.compress_size > MAX_PROPORCION_H5P:
            raise ErrorContenido(
                "PAQUETE_H5P_DEMASIADO_GRANDE",
                "el paquete comprime en exceso (posible bomba zip)",
            )
        total += info.file_size
    if total > MAX_DESCOMPRIMIDO_H5P:
        raise ErrorContenido(
            "PAQUETE_H5P_DEMASIADO_GRANDE", "el contenido descomprimido supera el máximo"
        )
    return infos


def _ruta_segura(nombre: str) -> None:
    if not nombre or nombre.startswith("/") or "\\" in nombre or re.match(r"\A[A-Za-z]:", nombre):
        _invalidar("el paquete lleva una ruta no permitida")
    limpio = nombre[:-1] if nombre.endswith("/") else nombre
    if not limpio or any(parte in ("", ".", "..") for parte in limpio.split("/")):
        _invalidar("el paquete lleva una ruta fuera de la carpeta")


def _ignorada(nombre: str) -> bool:
    return any(parte.startswith((".", "_")) for parte in nombre.split("/"))


def _leer_json(paquete: zipfile.ZipFile, nombre: str, maximo: int, detalle: str) -> Any:
    try:
        info = paquete.getinfo(nombre)
    except KeyError:
        _invalidar(detalle)
    if info.file_size > maximo:
        raise ErrorContenido("PAQUETE_H5P_DEMASIADO_GRANDE", f"«{nombre}» es demasiado grande")
    try:
        with paquete.open(info) as fuente:
            datos = fuente.read(maximo + 1)
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        _invalidar(detalle)
    if len(datos) > maximo:
        raise ErrorContenido("PAQUETE_H5P_DEMASIADO_GRANDE", f"«{nombre}» es demasiado grande")
    try:
        return json.loads(datos.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _invalidar(detalle)


def _raiz_h5p(datos: Any) -> tuple[dict, str | None, str]:
    if not isinstance(datos, dict):
        _invalidar("h5p.json debe ser un mapa")
    principal = datos.get("mainLibrary")
    if not isinstance(principal, str) or not _MACHINENAME.match(principal):
        _invalidar("h5p.json: «mainLibrary» no es un nombre de librería válido")
    dependencias = datos.get("preloadedDependencies")
    if not isinstance(dependencias, list) or not dependencias:
        _invalidar("h5p.json: faltan las dependencias de la librería principal")
    limpias: list[dict] = []
    for dependencia in dependencias:
        if not isinstance(dependencia, dict):
            _invalidar("h5p.json: una dependencia no es un mapa")
        machine = dependencia.get("machineName")
        mayor = dependencia.get("majorVersion")
        menor = dependencia.get("minorVersion")
        if not isinstance(machine, str) or not _MACHINENAME.match(machine):
            _invalidar("h5p.json: una dependencia no tiene un «machineName» válido")
        if (
            isinstance(mayor, bool)
            or not isinstance(mayor, int)
            or not 0 <= mayor <= 999
            or isinstance(menor, bool)
            or not isinstance(menor, int)
            or not 0 <= menor <= 999
        ):
            _invalidar("h5p.json: una dependencia no tiene una versión válida")
        limpias.append({"machineName": machine, "majorVersion": mayor, "minorVersion": menor})
    if principal not in {dependencia["machineName"] for dependencia in limpias}:
        _invalidar("h5p.json: la librería principal no está entre las dependencias")
    principal_dep = next(
        dependencia for dependencia in limpias if dependencia["machineName"] == principal
    )
    titulo = datos.get("title")
    titulo = titulo.strip()[:255] if isinstance(titulo, str) and titulo.strip() else None
    idioma = datos.get("language")
    embed = datos.get("embedTypes")
    h5p_limpio: dict = {
        "mainLibrary": principal,
        "preloadedDependencies": limpias,
        "embedTypes": (
            [tipo for tipo in embed if tipo in ("iframe", "div")] if isinstance(embed, list) else []
        )
        or ["iframe"],
    }
    if titulo is not None:
        h5p_limpio["title"] = titulo
    if isinstance(idioma, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,9}", idioma):
        h5p_limpio["language"] = idioma
    libreria = f"{principal} {principal_dep['majorVersion']}.{principal_dep['minorVersion']}"
    return h5p_limpio, titulo, libreria


def _externos(datos: Any) -> tuple[str, ...]:
    salida: list[str] = []
    for texto in _cadenas(datos):
        if _PELIGROSAS.search(texto):
            _invalidar("content.json lleva una URL no permitida")
        for url in _URL_HTTPS.findall(texto):
            limpia = url.rstrip(".,;:!?)]}")
            if limpia and limpia not in salida:
                salida.append(limpia)
    return tuple(salida)


def _cadenas(datos: Any) -> Iterator[str]:
    if isinstance(datos, str):
        yield datos
    elif isinstance(datos, dict):
        for valor in datos.values():
            yield from _cadenas(valor)
    elif isinstance(datos, list):
        for valor in datos:
            yield from _cadenas(valor)


def _invalidar(detalle: str) -> None:
    raise ErrorContenido("PAQUETE_H5P_INVALIDO", detalle)
