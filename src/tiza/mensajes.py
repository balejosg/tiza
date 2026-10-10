"""Todo el texto llano que ve el docente, venga de la terminal o de la ventana.

Convierte los avisos y los resúmenes de :mod:`tiza.publicacion` en líneas y
piezas ya saneadas; las presencias (``terminal.PresenciaTerminal`` y
``ventana.PresenciaVentana``) solo adaptan ese texto a su medio: stdout/stderr
en la terminal, pantalla y registro en la ventana. Nada aquí pregunta ni
escribe en la consola.

Las claves de ``Aviso.datos`` las fija cada constructor de ``publicacion.Aviso``
y solo se leen aquí; las presencias no miran ``datos``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import ayuda, estado, informe, rutas, tipos
from .informe import ErrorInforme
from .publicacion import (
    CAMPO_RECORDATORIO,
    Aviso,
    DocumentoBreve,
    DocumentoResumen,
    ResumenPublicacion,
    ResumenSinPruebas,
)

__all__ = [
    "AUTOPRUEBA_TEXTO",
    "AVISO_AJENO",
    "DetalleCorto",
    "DetalleReal",
    "DocumentoCorto",
    "DocumentoReal",
    "EXCEPCIONES_TEXTO",
    "Linea",
    "PARA_QUE",
    "SIN_PRUEBAS_AVISO",
    "SOLO_FECHAS_TEXTO",
    "VISIBILIDAD",
    "cambian_fechas",
    "describir_cambios",
    "describir_curso",
    "describir_documento",
    "detalle_corto",
    "detalle_real",
    "lineas_de_aviso",
    "lineas_de_error",
    "nombre_llano",
    "texto_cierre",
    "texto_seguro",
]

# Controles C0/C1 (incluido ESC y CSI) y controles bidireccionales (incluido
# U+061C, ARABIC LETTER MARK): con ellos un texto ajeno podría borrar o
# reescribir lo que el docente lee antes de confirmar. Misma clase de caracteres
# que informe._TEXTO_PROHIBIDO, contenido._CONTROL y publicar._NO_IMPRIMIBLE;
# mantén las cuatro sincronizadas.
_NO_IMPRIMIBLE = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def texto_seguro(texto: object, maximo: int = 120) -> str:
    """Texto del agente o de Moodle apto para enseñar al docente."""
    if maximo < 1:
        return ""
    limpio = _NO_IMPRIMIBLE.sub("", str(texto))
    if len(limpio) > maximo:
        limpio = limpio[: maximo - 1] + "…"
    return limpio


PARA_QUE = {
    "pruebas": "Donde se publica primero; el alumnado no lo ve.",
    "real": "El que usa tu alumnado.",
}

VISIBILIDAD: dict[bool | None, str] = {
    True: "ATENCIÓN: se publicará VISIBLE para el alumnado.",
    False: "Se publicará oculto (también lo que ya fuera visible).",
    None: "Lo que ya exista conserva su visibilidad; lo nuevo se crea oculto.",
}

AUTOPRUEBA_TEXTO = (
    "Conviene pasar la autoprueba: crea y borra contenido temporal en el curso de "
    "pruebas para comprobar que todo funciona (1-2 minutos)."
)
SIN_PRUEBAS_AVISO = (
    "Sin curso de pruebas: no habrá verificación previa y en real solo se publicará oculto."
)
AVISO_AJENO = "No aparece entre tus cursos: comprueba el id."
EXCEPCIONES_TEXTO = (
    "Las excepciones de fecha de alumnos concretos no cambian: revísalas en el aula si las hay."
)
SOLO_FECHAS_TEXTO = (
    "Solo cambian las fechas: el contenido, las preguntas, los intentos y la "
    "visibilidad no cambian."
)

_CIERRE = {
    "aula": (
        "El aula ha cerrado la sesión (caducó, o entraste con este usuario "
        "desde otro sitio, como el navegador). Vuelve a abrirla."
    ),
    "caducada": "La sesión ha caducado; se cierra.",
    "desactualizada": (
        "tiza ha cambiado mientras la sesión estaba abierta; se cierra. Vuelve a abrirla."
    ),
    "docente": "Sesión cerrada.",
}


def texto_cierre(motivo: str) -> str:
    """Por qué se cierra la sesión, en lenguaje llano."""
    return _CIERRE[motivo]


# El nombre llano de cada tipo lo fija su módulo; si el tipo es ajeno (un módulo del
# aula que no es de tiza), se enseña su nombre crudo.
_TIPOS = {tipo.nombre: tipo.llano for tipo in tipos.TODOS}


def nombre_llano(tipo: str) -> str:
    """Nombre para enseñar del tipo de actividad; crudo si es de fuera de tiza."""
    return _TIPOS.get(tipo, tipo)


def describir_curso(curso: int, nombre: str | None) -> str:
    """El curso para enseñarlo: «nombre» (id N), o solo el id si no hay nombre."""
    if nombre:
        return f"«{texto_seguro(nombre, 80)}» (id {curso})"
    return f"id {curso}"


def _fecha_llana(momento: datetime) -> str:
    return momento.strftime("%d/%m/%Y %H:%M")


_AVISOS_LLANOS = {
    "FECHA_FUERA_DE_CURSO": "fuera del curso escolar",
    "FECHA_FESTIVA": "festivo",
    "FECHA_FIN_DE_SEMANA": "fin de semana",
    "FECHA_SIN_CLASE": "no es día de clase",
}


def _fecha_o_sin(valor: tuple[int, int, int, int, int] | None) -> str:
    return "sin fecha" if valor is None else _fecha_llana(datetime(*valor))


def describir_cambios(doc: DocumentoResumen) -> list[str]:
    """Una línea por fecha: lo que hay en el aula y lo que se publicaría, con sus avisos."""
    lineas: list[str] = []
    for cambio in doc.cambios or ():
        if cambio.estado == "nueva":
            linea = f"{cambio.campo} {_fecha_o_sin(cambio.despues)} (la actividad es nueva)"
        elif cambio.estado == "igual":
            linea = f"{cambio.campo} {_fecha_o_sin(cambio.despues)} (sin cambios)"
        elif cambio.estado == "cambia":
            linea = (
                f"{cambio.campo} antes {_fecha_o_sin(cambio.antes)} "
                f"→ ahora {_fecha_o_sin(cambio.despues)}"
            )
        else:
            linea = (
                f"{cambio.campo}: no se pudieron leer las fechas actuales del aula; "
                f"se publicaría {_fecha_o_sin(cambio.despues)}"
            )
        avisos = [_AVISOS_LLANOS.get(codigo, codigo) for codigo in cambio.avisos]
        if avisos:
            linea += " — " + ", ".join(avisos)
        lineas.append(linea)
    return lineas


def cambian_fechas(resumen: ResumenPublicacion) -> bool:
    """Si alguna fecha cambia, o no se pudo comparar con el aula: toca recordar las excepciones.

    El recordatorio de calificación es del docente, no del alumnado: por sí solo no cuenta.
    """
    return any(
        cambio.estado in ("cambia", "desconocida") and cambio.campo != CAMPO_RECORDATORIO
        for doc in resumen.documentos
        for cambio in doc.cambios or ()
    )


def describir_documento(doc: DocumentoResumen) -> str:
    """Qué se va a publicar, en lenguaje llano y saneado.

    Con ``cambios`` (la confirmación de real), las fechas van en sus propias líneas.
    """
    if isinstance(doc.seccion, str):
        seccion = f"sección «{texto_seguro(doc.seccion)}»"
    else:
        seccion = f"sección {doc.seccion}"
    texto = f"{nombre_llano(doc.tipo)} «{texto_seguro(doc.nombre)}» → {seccion}"
    if doc.fechas and doc.cambios is None:
        texto += "; " + ", ".join(
            f"{fecha.campo} {_fecha_llana(fecha.momento)}"
            for fecha in doc.fechas
            if fecha.momento is not None
        )
    return texto


@dataclass(frozen=True)
class DocumentoReal:
    """Un documento de la confirmación de real, ya en texto llano."""

    titulo: str
    lineas: tuple[str, ...]
    vista_previa: Path | None


@dataclass(frozen=True)
class DetalleReal:
    """La confirmación de real: lo que la presencia enseña antes de preguntar."""

    curso: str
    posicion: int
    total: int
    solo_fechas: bool
    encabezado: str
    documentos: tuple[DocumentoReal, ...]
    finales: tuple[str, ...]
    aviso_calendario: str | None = None


def detalle_real(resumen: ResumenPublicacion) -> DetalleReal:
    """El resumen de una publicación en real convertido en piezas llano.

    La terminal las imprime y la ventana las pinta: el mismo texto, una sola vez.
    """
    solo = resumen.solo_fechas
    curso = describir_curso(resumen.curso, resumen.nombre_curso)
    if solo:
        encabezado = f"Se van a cambiar solo las fechas en el curso REAL {curso}:"
    else:
        encabezado = f"Se va a publicar en el curso REAL {curso}:"
    finales: list[str] = []
    if cambian_fechas(resumen):
        finales.append(EXCEPCIONES_TEXTO)
    finales += [
        f"Se creará la sección «{texto_seguro(nombre)}» (oculta)."
        for nombre in resumen.secciones_nuevas
    ]
    finales.append(SOLO_FECHAS_TEXTO if solo else VISIBILIDAD[resumen.visible])
    aviso = None
    if resumen.aviso_calendario is not None:
        aviso = "AVISO: calendario.toml no se puede usar. " + (
            ayuda.explicar(resumen.aviso_calendario) or ""
        )
    return DetalleReal(
        curso=curso,
        posicion=resumen.posicion,
        total=resumen.total,
        solo_fechas=solo,
        encabezado=encabezado,
        documentos=tuple(_documento_real(doc, solo) for doc in resumen.documentos),
        finales=tuple(finales),
        aviso_calendario=aviso,
    )


def _documento_real(doc: DocumentoResumen, solo: bool) -> DocumentoReal:
    lineas = [f"fichero {texto_seguro(doc.fichero)}" + ("" if solo else ", verificado en pruebas")]
    lineas += describir_cambios(doc)
    if not solo:
        lineas += [texto_seguro(linea) for linea in doc.itinerario]
        if doc.h5p is not None:
            lineas.append(f"actividad H5P: {texto_seguro(doc.h5p)}")
        if doc.h5p_libreria:
            lineas.append(f"paquete H5P: {texto_seguro(doc.h5p_libreria)}")
        for libreria in doc.h5p_descartadas:
            lineas.append(f"no se sube la librería {texto_seguro(libreria)}")
        for url in doc.enlaces_externos:
            lineas.append(f"enlace externo: {texto_seguro(url)}")
        for url in doc.incrustados:
            lineas.append(f"incrusta: {texto_seguro(url)}")
        for ruta in doc.recursos:
            lineas.append(f"se sube el fichero {texto_seguro(ruta)}")
    return DocumentoReal(
        titulo=describir_documento(doc), lineas=tuple(lineas), vista_previa=doc.vista_previa
    )


@dataclass(frozen=True)
class DocumentoCorto:
    """Un documento de la confirmación sin pruebas, ya en texto llano."""

    titulo: str
    lineas: tuple[str, ...]


@dataclass(frozen=True)
class DetalleCorto:
    """La confirmación sin curso de pruebas: solo se publica oculto."""

    curso: str
    posicion: int
    total: int
    aviso: str
    encabezado: str
    documentos: tuple[DocumentoCorto, ...]
    finales: tuple[str, ...]


def detalle_corto(resumen: ResumenSinPruebas) -> DetalleCorto:
    """El resumen sin pruebas convertido en piezas llano."""
    return DetalleCorto(
        curso=describir_curso(resumen.curso, resumen.nombre_curso),
        posicion=resumen.posicion,
        total=resumen.total,
        aviso="Sin curso de pruebas: se publicará solo en oculto.",
        encabezado="Se va a publicar en el curso REAL, sin verificación previa:",
        documentos=tuple(_documento_corto(doc) for doc in resumen.documentos),
        finales=tuple(
            f"Se creará la sección «{texto_seguro(nombre)}» (oculta)."
            for nombre in resumen.secciones_nuevas
        ),
    )


def _documento_corto(doc: DocumentoBreve) -> DocumentoCorto:
    lineas: list[str] = []
    if doc.existe is True:
        lineas.append("Ya existe en el aula: se ocultará si estaba visible.")
    elif doc.existe is None:
        lineas.append("Puede que ya exista en el aula: se ocultará si estaba visible.")
    lineas += [texto_seguro(linea) for linea in doc.itinerario]
    return DocumentoCorto(
        titulo=(
            f"{nombre_llano(doc.tipo)} «{texto_seguro(doc.nombre)}» "
            f"(fichero {texto_seguro(doc.fichero)})"
        ),
        lineas=tuple(lineas),
    )


@dataclass(frozen=True)
class Linea:
    """Una línea para el docente; ``error`` la manda a stderr en la terminal."""

    texto: str
    error: bool = False


def lineas_de_error(codigo: str, detalle: str = "") -> tuple[Linea, ...]:
    """Las líneas de un error con código: «ERROR [X]» y su «Qué hacer», si lo hay."""
    texto = f"ERROR [{codigo}]"
    if detalle:
        texto += f": {detalle}"
    lineas = [Linea(texto, error=True)]
    que_hacer = ayuda.explicar(codigo)
    if que_hacer is not None:
        lineas.append(Linea(f"Qué hacer: {que_hacer}", error=True))
    return tuple(lineas)


def _autoprueba_fallida(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("No se abre la sesión porque la autoprueba ha fallado.", error=True),)


def _cancelada(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("Operación cancelada.", error=True),)


def _creando_seccion(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea(f"Creando la sección «{texto_seguro(datos['nombre'])}» (oculta)..."),)


def _cursos_guardados(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea(f"Cursos guardados en {datos['ruta']}."),)


def _error_interno(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    detalle = f"fallo inesperado al atender una petición ({texto_seguro(datos['tipo'])})."
    return lineas_de_error("ERROR_INTERNO", detalle)


def _estructura_no_leida(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("No se pudo leer la estructura; el agente podrá pedirla con «tiza estructura»."),)


def _fallo(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return lineas_de_error(str(datos["codigo"]), str(datos.get("detalle") or ""))


def _informe_no_escrito(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    ruta = f"{rutas.CARPETA_TRABAJO}/{estado.FICHERO_INFORME}"
    return (Linea(f"AVISO: no se pudo escribir {ruta}.", error=True),)


def _maximo_alcanzado(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(
            f"La sesión ha llegado al máximo de {datos['horas']} horas. "
            "Abre otra cuando la necesites."
        ),
    )


def _nombres_no_disponibles(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("No se pudo leer la lista de tus cursos; se mostrarán solo los ids."),)


def _peticion_retirada(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("El agente ya no espera esta petición; no se publica."),)


def _publicando_en_pruebas(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    lineas = [Linea("El agente pide publicar en pruebas:")]
    lineas += [Linea(f"- {describir_documento(doc)}") for doc in datos["documentos"]]
    return tuple(lineas)


def _quedan_minutos(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(
            f"Quedan menos de {datos['minutos']} minutos de sesión. "
            "Al llegar la hora podrás ampliarla aquí."
        ),
    )


def _resultado(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    try:
        lineas = informe.resumen(datos["documento"])
    except ErrorInforme:
        return ()
    return tuple(Linea(linea) for linea in lineas)


def _sesion_abierta(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    hora = datos["caduca"].astimezone().strftime("%d/%m/%Y %H:%M")
    return (
        Linea(
            f"Sesión abierta hasta el {hora}. Deja la sesión abierta mientras trabajas; "
            "se cerrará al llegar la hora o cuando la cierres."
        ),
    )


def _sesion_cerrada(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea(texto_cierre(datos["motivo"])),)


_CONVERSIONES: dict[str, Callable[[Mapping[str, Any]], tuple[Linea, ...]]] = {
    "AUTOPRUEBA_FALLIDA": _autoprueba_fallida,
    "CANCELADA": _cancelada,
    "CREANDO_SECCION": _creando_seccion,
    "CURSOS_GUARDADOS": _cursos_guardados,
    "ERROR_INTERNO": _error_interno,
    "ESTRUCTURA_NO_LEIDA": _estructura_no_leida,
    "FALLO": _fallo,
    "INFORME_NO_ESCRITO": _informe_no_escrito,
    "MAXIMO_ALCANZADO": _maximo_alcanzado,
    "NOMBRES_NO_DISPONIBLES": _nombres_no_disponibles,
    "PETICION_RETIRADA": _peticion_retirada,
    "PUBLICANDO_EN_PRUEBAS": _publicando_en_pruebas,
    "QUEDAN_MINUTOS": _quedan_minutos,
    "RESULTADO": _resultado,
    "SESION_ABIERTA": _sesion_abierta,
    "SESION_CERRADA": _sesion_cerrada,
}


def lineas_de_aviso(aviso: Aviso) -> tuple[Linea, ...]:
    """El aviso en texto llano para el docente."""
    return _CONVERSIONES[aviso.codigo](aviso.datos)
