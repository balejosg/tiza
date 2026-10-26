"""Todo el texto llano que ve el docente en la terminal.

Convierte los avisos y los resúmenes de :mod:`tiza.publicacion` en líneas y
piezas ya saneadas; la presencia (``terminal.PresenciaTerminal``) solo adapta ese texto a su medio:
stdout/stderr en la terminal. Nada aquí pregunta ni
escribe en la consola.

Las claves de ``Aviso.datos`` las fija cada constructor de ``publicacion.Aviso``
y solo se leen aquí; las presencias no miran ``datos``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import ayuda, estado, informe, rutas, tipos
from .informe import ErrorInforme
from .publicacion import (
    CAMPO_RECORDATORIO,
    Aviso,
    CambioNombre,
    CambioSeccion,
    DocumentoBreve,
    DocumentoResumen,
    ResumenAislamiento,
    ResumenCalificador,
    ResumenCopia,
    ResumenOrden,
    ResumenPublicacion,
    ResumenSinPruebas,
    ResumenSobrescribir,
)

if TYPE_CHECKING:
    from .sesion import CursoSesion

__all__ = [
    "ACTUALIZANDO_TEXTO",
    "ACTUALIZANDO_TITULO",
    "AUTOPRUEBA_TEXTO",
    "NO_SE_ENTRO_QUE_HACER",
    "NO_SE_ENTRO_TEXTO",
    "NO_SE_ENTRO_TITULO",
    "PREGUNTA_ACTUALIZAR",
    "PREGUNTA_AISLAMIENTO",
    "PREGUNTA_AISLAR_AQUI",
    "PREGUNTA_AUTOPRUEBA",
    "PREGUNTA_CARPETA_DUDOSA",
    "PREGUNTA_CURSOS",
    "PREGUNTA_DESTINO",
    "PREGUNTA_SEGUIR_SIN_AISLAR",
    "PREGUNTA_SESION_ANTERIOR",
    "PREGUNTA_SIN_PRUEBAS",
    "AVISO_AJENO",
    "SEPARADOR_NUEVA_SESION",
    "SESION_ANTERIOR_ATENDIENDO",
    "SESION_ANTERIOR_TEXTO",
    "DetalleCalificador",
    "DetalleCopia",
    "DetalleCorto",
    "DetalleOrden",
    "DetalleReal",
    "DetalleSobrescribir",
    "DocumentoCorto",
    "DocumentoReal",
    "EXCEPCIONES_TEXTO",
    "Linea",
    "MARCAS_DE_COMPROBACION",
    "PARA_QUE",
    "SIN_CURSO_PRUEBAS_OPCION",
    "SIN_PRUEBAS_AVISO",
    "SOLO_FECHAS_TEXTO",
    "VISIBILIDAD",
    "VOLVER_A_EMPEZAR",
    "cabecera_de_curso",
    "cambian_fechas",
    "describir_cambios",
    "describir_curso",
    "describir_documento",
    "detalle_calificador",
    "detalle_copia",
    "detalle_corto",
    "detalle_orden",
    "detalle_real",
    "detalle_sobrescribir",
    "linea_de_copia",
    "linea_destino",
    "lineas_de_aislamiento",
    "lineas_de_aviso",
    "lineas_de_cursos",
    "lineas_de_error",
    "nombre_llano",
    "pregunta_ampliacion",
    "rotulos",
    "rotulos_ampliacion",
    "texto_actualizacion",
    "texto_carpeta_dudosa",
    "texto_cierre",
    "texto_seguro",
]

# Controles C0/C1 (incluido ESC y CSI) y controles bidireccionales (incluido
# U+061C, ARABIC LETTER MARK): con ellos un texto ajeno podría borrar o
# reescribir lo que el docente lee antes de confirmar. Misma clase de caracteres
# que informe._TEXTO_PROHIBIDO, contenido._CONTROL y estructura._NO_IMPRIMIBLE;
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
SESION_ANTERIOR_TEXTO = (
    "Ya hay una sesión de tiza abierta en esta carpeta (quizá en una terminal que se cerró)."
)
SESION_ANTERIOR_ATENDIENDO = (
    "Está con una petición del agente: si espera tu respuesta, no se publicará; "
    "si ya está publicando, terminará antes de cerrarse."
)
EXCEPCIONES_TEXTO = (
    "Las excepciones de fecha de alumnos concretos no cambian: revísalas en el aula si las hay."
)
SOLO_FECHAS_TEXTO = (
    "Solo cambian las fechas: el contenido, las preguntas, los intentos y la "
    "visibilidad no cambian."
)

BORRADA_TEXTO = "Ya no está en el aula: se creará de nuevo."

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
    "otra": "Se ha abierto otra sesión en esta carpeta; esta se cierra.",
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
    finales += _lineas_de_movimientos(resumen.movimientos)
    finales += _lineas_de_nombres(resumen.nombres)
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
    if doc.borrada and not solo:
        lineas.append(BORRADA_TEXTO)
    if not solo:
        lineas += [texto_seguro(linea) for linea in doc.itinerario]
        if doc.h5p is not None:
            lineas.append(f"actividad H5P: {texto_seguro(doc.h5p)}")
        if doc.h5p_libreria:
            lineas.append(f"paquete H5P: {texto_seguro(doc.h5p_libreria)}")
        if doc.imagenes_preguntas:
            plural = "imagen" if doc.imagenes_preguntas == 1 else "imágenes"
            lineas.append(f"{doc.imagenes_preguntas} {plural} dentro de las preguntas")
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
        )
        + tuple(_lineas_de_movimientos(resumen.movimientos))
        + tuple(_lineas_de_nombres(resumen.nombres)),
    )


def _lineas_de_movimientos(movimientos: tuple[CambioSeccion, ...]) -> list[str]:
    """Una línea por actividad que cambia de sección: se mueve, no se duplica."""
    return [
        f"«{texto_seguro(cambio.fichero)}»: se moverá de la sección «{texto_seguro(cambio.origen)}» "
        f"a «{texto_seguro(cambio.destino)}» (no se duplica)."
        for cambio in movimientos
    ]


def _lineas_de_nombres(cambios: tuple[CambioNombre, ...]) -> list[str]:
    """Una línea por actividad que se llama distinto en el aula: se actualiza, no se duplica."""
    return [
        f"Se cambia el nombre de «{texto_seguro(cambio.antes)}» a «{texto_seguro(cambio.despues)}» "
        f"(fichero {texto_seguro(cambio.fichero)})."
        for cambio in cambios
    ]


def _documento_corto(doc: DocumentoBreve) -> DocumentoCorto:
    lineas: list[str] = []
    if doc.borrada:
        lineas.append(BORRADA_TEXTO)
    elif doc.existe is True:
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
class DetalleOrden:
    """La confirmación de real de ``tiza ordenar``: cada sección con su orden nuevo."""

    curso: str
    posicion: int
    total: int
    encabezado: str
    secciones: tuple[tuple[str, tuple[str, ...]], ...]  # (título, una línea por actividad)
    finales: tuple[str, ...]


def detalle_orden(resumen: ResumenOrden) -> DetalleOrden:
    """El orden nuevo de cada sección, con los nombres que tienen las actividades en el aula.

    Es la pantalla del docente: las que no son de tiza salen por su nombre, saneado. Esos
    nombres no se escriben en ``.tiza``.
    """
    secciones = []
    for seccion in resumen.secciones:
        lineas = []
        for numero, actividad in enumerate(seccion.actividades, 1):
            marca = (
                f" (fichero {texto_seguro(actividad.fichero)})"
                if actividad.fichero is not None
                else ""
            )
            lineas.append(
                f"{numero}. {nombre_llano(actividad.tipo)} «{texto_seguro(actividad.nombre)}»{marca}"
            )
        secciones.append((f"Sección «{texto_seguro(seccion.nombre)}»:", tuple(lineas)))
    finales = [
        f"AVISO: «{texto_seguro(fichero)}» quedará por encima de «{texto_seguro(dependencia)}», "
        "que debe completarse antes. El orden en pantalla no cambia las restricciones."
        for fichero, dependencia in resumen.dependencias
    ]
    finales.append("Solo cambia el orden: el contenido, la visibilidad y los intentos no cambian.")
    return DetalleOrden(
        curso=describir_curso(resumen.curso, resumen.nombre_curso),
        posicion=resumen.posicion,
        total=resumen.total,
        encabezado=f"Se va a reordenar en el curso REAL {describir_curso(resumen.curso, resumen.nombre_curso)}:",
        secciones=tuple(secciones),
        finales=tuple(finales),
    )


@dataclass(frozen=True)
class DetalleCalificador:
    """La confirmación de ``tiza calificador`` en un curso real: qué cambia, en líneas llanas."""

    curso: str
    posicion: int
    total: int
    encabezado: str
    lineas: tuple[str, ...]


def _porcentaje(valor: float) -> str:
    return f"{valor:g} %".replace(".", ",")


def _unidades(secciones: tuple[int | str, ...]) -> str:
    """Las secciones de una evaluación en llano: «1-4», «1, 3» o «1-2, «Tema 5»»."""
    rangos: list[list[int]] = []
    for numero in sorted({s for s in secciones if isinstance(s, int)}):
        if rangos and numero == rangos[-1][1] + 1:
            rangos[-1][1] = numero
        else:
            rangos.append([numero, numero])
    tramos = [str(desde) if desde == hasta else f"{desde}-{hasta}" for desde, hasta in rangos]
    tramos += [f"«{texto_seguro(s, 60)}»" for s in secciones if isinstance(s, str)]
    return ", ".join(tramos)


def _lista(nombres: tuple[str, ...]) -> str:
    return ", ".join(texto_seguro(nombre, 80) for nombre in nombres)


def _lista_corta(nombres: tuple[str, ...], maximo: int = 8) -> str:
    """Los primeros nombres y cuántos más: una lista de copias puede ser muy larga."""
    if len(nombres) <= maximo:
        return _lista(nombres)
    return f"{_lista(nombres[:maximo])} y {len(nombres) - maximo} más"


def _numero(valor: float) -> str:
    return f"{valor:g}".replace(".", ",")


def detalle_calificador(resumen: ResumenCalificador) -> DetalleCalificador:
    """Lo que hará ``tiza calificador`` en el curso, con consecuencias, en lenguaje llano.

    Los nombres de actividades salen de los ficheros; los de totales ajenos y los avisos, del
    aula, y se sanean aquí. Es la pantalla del docente: no se escribe en ``.tiza``.
    """
    lineas: list[str] = []
    for elemento in resumen.lineas_esquema:
        de_la_final = (
            f" ({_porcentaje(elemento.peso)} de la final)" if elemento.peso is not None else ""
        )
        actividades = (
            ", ".join(
                f"{texto_seguro(nombre, 80)} {_porcentaje(peso)}"
                for nombre, peso in elemento.actividades
            )
            or "todavía sin actividades"
        )
        lineas.append(f"{texto_seguro(elemento.id, 40)}{de_la_final}: {actividades}")
    if resumen.tope is not None:
        umbral, maximo = resumen.tope
        lineas.append(
            f"Regla de la final: si algún elemento queda por debajo de {_numero(umbral)}, la final "
            f"no pasa de {_numero(maximo)}. Mientras un RA no tenga ninguna nota, cuenta como 0 "
            "en esa regla: la final puede salir topada a mitad de curso"
        )
    for cerrada in resumen.cerradas:
        estado = (
            "cerrada: se completa y se bloquea al terminar, y ya no cambia"
            if cerrada.por_bloquear
            else "cerrada, no cambia"
        )
        lineas.append(
            f"{texto_seguro(cerrada.nombre, 80)}: unidades {_unidades(cerrada.secciones)} "
            f"({estado})"
        )
    if resumen.bloquea:
        lineas.append(f"Se bloquean los totales de: {_lista(resumen.bloquea)} (tienen notas)")
    if resumen.mueve:
        lineas.append(f"Pasan al calificador de tiza: {_lista(resumen.mueve)}")
    if resumen.casillas:
        lineas.append(
            "Se crean casillas de calificación manual, que rellenas tú en el aula: "
            f"{_lista(resumen.casillas)}"
        )
    if resumen.ids_nuevos:
        lineas.append(f"Se añade número de ID a: {_lista(resumen.ids_nuevos)}")
    if resumen.quita:
        lineas.append(
            f"Se quitan del calificador de tiza (no tienen notas): {_lista_corta(resumen.quita)}"
        )
    if resumen.anterior:
        lineas.append(
            "Lo de tiza es informativo: el total del curso sigue siendo el tuyo, y las "
            "actividades que pasan a tiza dejan de sumar en él"
        )
    elif resumen.total_curso is not None:
        como = (
            "la nota final sobre 10"
            if resumen.total_curso == "nota_final"
            else "el porcentaje del calificador"
        )
        lineas.append(
            f"El total del curso pasa a ser el de tiza ({como}), también para quien ya tenga notas"
        )
    for nombre in resumen.notas_cambian:
        lineas.append(
            f"La nota de la {texto_seguro(nombre, 80)} puede cambiar para quien ya tenga notas"
        )
    for aviso in resumen.avisos:
        lineas.extend(linea.texto for linea in lineas_de_aviso(aviso))
    curso = describir_curso(resumen.curso, resumen.nombre_curso)
    return DetalleCalificador(
        curso=curso,
        posicion=resumen.posicion,
        total=resumen.total,
        encabezado=f"Se va a montar el calificador en el curso REAL {curso}:",
        lineas=tuple(lineas),
    )


@dataclass(frozen=True)
class DetalleCopia:
    """La confirmación de ``tiza copia``: de qué curso y la pregunta al docente."""

    curso: str
    entorno: str
    pregunta: str
    actividades: tuple[str, ...] = ()  # una por línea; vacío = la copia es del curso entero


def detalle_copia(resumen: ResumenCopia) -> DetalleCopia:
    """La pregunta de la copia del curso, con el nombre del curso saneado (viene del aula).

    Con ``actividades`` (nombres tal como están en el fichero), la copia es de esas actividades.
    """
    nombre = texto_seguro(resumen.nombre_curso, 80) if resumen.nombre_curso else None
    if resumen.actividades:
        return DetalleCopia(
            curso=describir_curso(resumen.curso, resumen.nombre_curso),
            entorno=resumen.entorno,
            pregunta=(
                "¿Hacer una copia de seguridad de estas actividades, sin datos de alumnos, "
                "para juntar tus cambios?"
            ),
            actividades=tuple(texto_seguro(a, 80) for a in resumen.actividades),
        )
    return DetalleCopia(
        curso=describir_curso(resumen.curso, resumen.nombre_curso),
        entorno=resumen.entorno,
        pregunta=(
            f"¿Hago una copia del curso «{nombre or 'id ' + str(resumen.curso)}», sin datos de "
            "alumnos, para que el agente la lea? Se guarda en esta carpeta."
        ),
    )


@dataclass(frozen=True)
class DetalleSobrescribir:
    """La pregunta de real sobre lo que el docente retocó a mano en el aula."""

    curso: str
    posicion: int
    total: int
    encabezado: str
    lineas: tuple[str, ...]  # una por actividad, con su viñeta
    pregunta: str


def detalle_sobrescribir(resumen: ResumenSobrescribir) -> DetalleSobrescribir:
    """Qué actividades cambiaron en el aula desde que tiza las publicó, y si se sobrescriben.

    Los nombres son los de los ficheros del docente, saneados como todo lo que se enseña.
    """
    return DetalleSobrescribir(
        curso=describir_curso(resumen.curso, resumen.nombre_curso),
        posicion=resumen.posicion,
        total=resumen.total,
        encabezado="Estas actividades han cambiado en el aula desde que tiza las publicó:",
        lineas=tuple(f"  · {texto_seguro(nombre)}" for nombre in resumen.actividades),
        pregunta="¿Sobrescribirlas y perder esos cambios?",
    )


SIN_CURSO_PRUEBAS_OPCION = "No tengo curso de pruebas (en real se publicará solo oculto)"
PREGUNTA_DESTINO = "¿Continuar con este curso?"
PREGUNTA_CURSOS = "¿Abrir la sesión con estos cursos?"
PREGUNTA_SIN_PRUEBAS = "¿Abrir la sesión sin curso de pruebas?"
PREGUNTA_AUTOPRUEBA = "¿Pasarla ahora?"
PREGUNTA_ACTUALIZAR = "¿Actualizar ahora? Después tendrás que volver a abrir la sesión."
PREGUNTA_CARPETA_DUDOSA = "¿Abrir la sesión aquí de todos modos?"
PREGUNTA_AISLAR_AQUI = "¿Aplicar ahora el aislamiento a esta carpeta?"
PREGUNTA_AISLAMIENTO = "¿Aplicarlos?"
PREGUNTA_SEGUIR_SIN_AISLAR = "¿Seguir sin aislar el agente?"
PREGUNTA_SESION_ANTERIOR = "¿Cerrarla y abrir esta?"

# Rótulos de los botones de cada confirmación del panel: (sí, no, riesgo). El riesgo vacío
# deja el «sí» como botón principal; «real» lo pinta en coral y «peligro» pone delante el
# «no» como principal y el «sí» en rojo. La terminal no los usa: sigue con [s/N].
_ROTULOS: dict[str, tuple[str, str, str]] = {
    "confirmar_real": ("Publicar en este curso", "Saltar este curso", "real"),
    "confirmar_real_sin_pruebas": ("Publicar en este curso", "Saltar este curso", "real"),
    "confirmar_orden": ("Ordenar este curso", "Saltar este curso", "real"),
    "confirmar_calificador": ("Cambiar el calificador", "Saltar este curso", "real"),
    "confirmar_sobrescribir": (
        "Sobrescribir y perder sus cambios",
        "Conservar los cambios del aula",
        "peligro",
    ),
    "confirmar_copia": ("Hacer la copia", "No hacerla", ""),
    "confirmar_cursos": ("Abrir la sesión", "Cancelar", ""),
    "confirmar_sin_pruebas": ("Abrir sin curso de pruebas", "Cancelar", "real"),
    "confirmar_autoprueba": ("Pasarla ahora", "Ahora no", ""),
    "confirmar_actualizacion": ("Actualizar ahora", "Ahora no", ""),
    "confirmar_carpeta_dudosa": ("Abrir aquí de todos modos", "No abrir", "peligro"),
    "ofrecer_aislamiento": ("Aplicar el aislamiento", "No aplicarlo", ""),
    "confirmar_aislamiento": ("Aplicar el aislamiento", "No aplicarlo", ""),
    "seguir_sin_aislar": ("Seguir sin aislar", "No seguir", "peligro"),
    "cerrar_sesion_anterior": (
        "Cerrar la anterior y abrir esta",
        "Dejar la anterior",
        "",
    ),
}


def rotulos(confirmacion: str) -> dict[str, str]:
    """Los rótulos de una confirmación del panel, con los valores por defecto si no tiene."""
    texto_si, texto_no, riesgo = _ROTULOS.get(confirmacion, ("", "", ""))
    return {"texto_si": texto_si, "texto_no": texto_no, "riesgo": riesgo}


def rotulos_ampliacion(minutos: int) -> dict[str, str]:
    """Los rótulos de la pregunta de ampliación, con sus minutos."""
    return {
        "texto_si": f"Ampliar {minutos} minutos",
        "texto_no": "Cerrar la sesión",
        "riesgo": "",
    }


def linea_destino(entorno: str, curso: int, nombre: str | None = None) -> str:
    """El destino de una confirmación: «Curso de destino: … (entorno: real)»."""
    return f"Curso de destino: {describir_curso(curso, nombre)} (entorno: {entorno})"


def cabecera_de_curso(posicion: int, total: int, curso: str) -> str | None:
    """Con varios cursos reales, cada confirmación dice cuál es: «Curso 2 de 3: …»."""
    return f"Curso {posicion} de {total}: {curso}" if total > 1 else None


def lineas_de_cursos(cursos: Sequence[CursoSesion]) -> tuple[str, ...]:
    """Los cursos de la sesión que se va a abrir, y el aviso si no hay curso de pruebas."""
    lineas = ["Cursos de esta sesión:"]
    for curso in cursos:
        linea = f"  {curso.entorno + ':':8} {describir_curso(curso.id, curso.nombre)}"
        if curso.ajeno:
            linea += f" — {AVISO_AJENO}"
        if curso.entorno == "real":
            linea += " — cada publicación en real se confirmará aquí"
        lineas.append(linea)
    if not any(curso.entorno == "pruebas" for curso in cursos):
        lineas.append(f"AVISO: {SIN_PRUEBAS_AVISO}")
    return tuple(lineas)


# Lo que el panel cuenta al docente cuando no se llegó a entrar en el aula y cuando se actualiza.
NO_SE_ENTRO_TITULO = "No se entró en el aula"
NO_SE_ENTRO_TEXTO = "La ventana de entrada se cerró o pasó el tiempo."
NO_SE_ENTRO_QUE_HACER = "Vuelve a abrir tiza para intentarlo."
SEPARADOR_NUEVA_SESION = "— Nueva sesión —"
VOLVER_A_EMPEZAR = "Volver a empezar"
ACTUALIZANDO_TITULO = "Se está actualizando"
ACTUALIZANDO_TEXTO = "Se está actualizando; el panel se abrirá solo en un minuto o dos."


def texto_actualizacion(nueva: str, actual: str) -> str:
    """La versión nueva de tiza (``nueva`` es la etiqueta, p. ej. ``v0.30.0``) y la que se tiene."""
    return f"Hay una versión nueva de tiza: {nueva[1:]} (tienes la {actual})."


def texto_carpeta_dudosa(carpeta: Path) -> str:
    """Por qué la carpeta no parece la de una asignatura."""
    return (
        f"{carpeta} no parece la carpeta de una asignatura "
        f"(no hay ficheros .md o .html ni {rutas.FICHERO_ASIGNATURA})."
    )


def lineas_de_aislamiento(resumen: ResumenAislamiento) -> tuple[str, ...]:
    """Lo que tiza no edita (a mano) y los cambios que haría en cada fichero."""
    lineas = list(resumen.manuales)
    if resumen.ficheros:
        lineas.append("Se van a hacer estos cambios:")
        for fichero in resumen.ficheros:
            lineas.append(f"  En {fichero.ruta}:")
            lineas.extend(f"    - {cambio}" for cambio in fichero.cambios)
    return tuple(lineas)


def pregunta_ampliacion(minutos: int) -> str:
    """La pregunta al acabarse el tiempo de la sesión."""
    return f"Se ha acabado el tiempo de la sesión. ¿Ampliar {minutos} minutos más?"


def linea_de_copia(detalle: DetalleCopia) -> str:
    """De qué curso es la copia que se pide."""
    return f"Curso de la copia: {detalle.curso} (entorno: {detalle.entorno})"


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


def _actividad_en_evaluacion_cerrada(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(
            "Es nueva en una evaluación cerrada: no se coloca en el calificador, ni sus copias "
            f"(la evaluación no se toca): {texto_seguro(datos['ruta'], 200)}"
        ),
    )


def _actividad_pendiente(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(f"Aún no está en el aula, no cuenta todavía: {texto_seguro(datos['ruta'], 200)}"),
    )


def _calificando_en_pruebas(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(
            "El agente pide montar el calificador en pruebas con "
            f"«{texto_seguro(datos['esquema'], 200)}»."
        ),
    )


def _cambiado_a_mano(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(f"Lo cambiaste a mano en el aula y tiza no lo toca: {texto_seguro(datos['nombre'])}"),
    )


def _elemento_con_notas_quitado(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(
            "Ya no está en el esquema pero tiene notas: se queda en el aula con peso 0: "
            f"{texto_seguro(datos['nombre'])}"
        ),
    )


def _criterios_sin_peso(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(
            f"Los criterios de {texto_seguro(datos['elemento'], 40)} no llevan peso: "
            "tiza los pesa igual."
        ),
    )


def _elemento_sin_actividades(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea(f"Ninguna actividad cuenta para {texto_seguro(datos['elemento'], 40)} todavía."),)


def _evaluacion_cerrada_en_el_aula(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(f"Ya está bloqueada en el aula y tiza no la toca: {texto_seguro(datos['nombre'])}"),
    )


MARCAS_DE_COMPROBACION = {"ok": "[ok]", "falta": "[FALTA]", "aviso": "[aviso]"}


def _aislamiento_guardado(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    copia = f" (copia: {datos['copia']})" if datos.get("copia") else ""
    return (Linea(f"Guardado {datos['ruta']}{copia}"),)


def _carpeta_no_aislada(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("Esta carpeta no está aislada del aula."),)


def _comprobaciones_de_aislamiento(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return tuple(
        Linea(f"{MARCAS_DE_COMPROBACION[c.estado]} {c.agente}: {c.texto}")
        for c in datos["comprobaciones"]
    )


def _configuracion_guardada(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(f"Configuración guardada en {datos['ruta']}. No se ha guardado ninguna contraseña."),
        Linea(
            "Los cursos son de cada asignatura: se eligen por nombre al abrir la sesión "
            f"en su carpeta («tiza empezar») y se guardan en su {rutas.FICHERO_ASIGNATURA}."
        ),
    )


def _nada_que_cambiar(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("No hay nada que cambiar."),)


def _primera_vez(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("Es la primera vez: vamos a configurar tiza (no se pide la contraseña)."),)


def _reinicia_el_agente(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("Reinicia tu agente para que lea la configuración nueva."),)


def _sigue_faltando(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("Sigue faltando:"),) + tuple(
        Linea(f"  - {c.agente}: {c.texto}") for c in datos["faltas"]
    )


def _sigue_la_version_actual(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("Se sigue con la versión que tienes."),)


def _tiza_actualizada(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    if datos["windows"]:
        return (
            Linea(
                "Vuelve a abrir la sesión cuando la otra ventana diga que tiza está actualizada."
            ),
        )
    return (Linea("tiza está actualizada. Vuelve a abrir la sesión para usar la versión nueva."),)


def _autoprueba_fallida(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("No se abre la sesión porque la autoprueba ha fallado.", error=True),)


def _cambiada_desde_la_publicacion(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(
            f"«{texto_seguro(datos['nombre'])}» ha cambiado en el aula desde la última vez que "
            "tiza la publicó, y no se ha tocado. Para juntar tus cambios, pide al agente que "
            "traiga la versión del aula.",
            error=True,
        ),
    )


def _cambiada_en_el_aula(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    if datos.get("cmid") is not None:
        return (
            Linea(
                f"«{texto_seguro(datos['nombre'])}» cambió en el aula y tu fichero sigue como "
                "cuando se importó. No la publico para no perder ese cambio: junta antes los "
                f"cambios de .tiza/copia/{int(datos['cmid'])}.html en tu fichero.",
                error=True,
            ),
        )
    return (
        Linea(
            f"Ha cambiado «{texto_seguro(datos['nombre'])}» en el aula desde la copia. "
            "No la publico para no perder ese cambio. "
            "Pide al agente una copia nueva del curso.",
            error=True,
        ),
    )


def _huella_no_guardada(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(
            f"No he podido guardar lo que acabo de publicar de «{texto_seguro(datos['nombre'])}» "
            "para comprobar sus cambios después; la próxima vez pide una copia nueva.",
            error=True,
        ),
    )


def _registro_no_guardado(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(
            f"«{texto_seguro(datos['nombre'])}» se ha publicado, pero no he podido anotar qué "
            "actividad es ni cómo ha quedado; si le cambias el nombre al fichero, tiza podría "
            "crear otra en vez de actualizar esta, y no te avisará si la retocas a mano en el aula.",
            error=True,
        ),
    )


def _cancelada(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("Operación cancelada.", error=True),)


def _cerrando_sesion_anterior(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("Cerrando la sesión anterior..."),)


def _copia_queda_en_el_aula(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(
            "La copia también queda en tu zona de copias de Moodle "
            "(«Restaurar»): puedes borrarla allí"
        ),
    )


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


def _panel_actualizado(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea(f"tiza se ha actualizado a la versión {texto_seguro(datos['version'])}."),)


def _panel_no_actualizado(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (
        Linea(
            f"No se pudo actualizar; sigues con la versión {texto_seguro(datos['actual'])} "
            f"(detalle en {texto_seguro(datos['log'], 300)}).",
            error=True,
        ),
    )


def _nombres_no_disponibles(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("No se pudo leer la lista de tus cursos; se mostrarán solo los ids."),)


def _ordenando_en_pruebas(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    lineas = [Linea("El agente pide ordenar en pruebas:")]
    lineas += [
        Linea(
            f"- {nombre_llano(doc.tipo)} «{texto_seguro(doc.nombre)}» (fichero {texto_seguro(doc.fichero)})"
        )
        for doc in datos["documentos"]
    ]
    return tuple(lineas)


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


def _sesion_anterior_cerrada(_datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea("La sesión anterior se ha cerrado."),)


def _sesion_cerrada(datos: Mapping[str, Any]) -> tuple[Linea, ...]:
    return (Linea(texto_cierre(datos["motivo"])),)


_CONVERSIONES: dict[str, Callable[[Mapping[str, Any]], tuple[Linea, ...]]] = {
    "ACTIVIDAD_EN_EVALUACION_CERRADA": _actividad_en_evaluacion_cerrada,
    "ACTIVIDAD_PENDIENTE": _actividad_pendiente,
    "AISLAMIENTO_GUARDADO": _aislamiento_guardado,
    "AUTOPRUEBA_FALLIDA": _autoprueba_fallida,
    "CALIFICANDO_EN_PRUEBAS": _calificando_en_pruebas,
    "CAMBIADA_DESDE_LA_PUBLICACION": _cambiada_desde_la_publicacion,
    "CAMBIADA_EN_EL_AULA": _cambiada_en_el_aula,
    "CAMBIADO_A_MANO": _cambiado_a_mano,
    "CANCELADA": _cancelada,
    "CARPETA_NO_AISLADA": _carpeta_no_aislada,
    "CERRANDO_SESION_ANTERIOR": _cerrando_sesion_anterior,
    "COMPROBACIONES_DE_AISLAMIENTO": _comprobaciones_de_aislamiento,
    "CONFIGURACION_GUARDADA": _configuracion_guardada,
    "COPIA_QUEDA_EN_EL_AULA": _copia_queda_en_el_aula,
    "CREANDO_SECCION": _creando_seccion,
    "CRITERIOS_SIN_PESO": _criterios_sin_peso,
    "CURSOS_GUARDADOS": _cursos_guardados,
    "ELEMENTO_CON_NOTAS_QUITADO": _elemento_con_notas_quitado,
    "ELEMENTO_SIN_ACTIVIDADES": _elemento_sin_actividades,
    "ERROR_INTERNO": _error_interno,
    "ESTRUCTURA_NO_LEIDA": _estructura_no_leida,
    "EVALUACION_CERRADA_EN_EL_AULA": _evaluacion_cerrada_en_el_aula,
    "FALLO": _fallo,
    "HUELLA_NO_GUARDADA": _huella_no_guardada,
    "INFORME_NO_ESCRITO": _informe_no_escrito,
    "MAXIMO_ALCANZADO": _maximo_alcanzado,
    "NADA_QUE_CAMBIAR": _nada_que_cambiar,
    "NOMBRES_NO_DISPONIBLES": _nombres_no_disponibles,
    "ORDENANDO_EN_PRUEBAS": _ordenando_en_pruebas,
    "PANEL_ACTUALIZADO": _panel_actualizado,
    "PANEL_NO_ACTUALIZADO": _panel_no_actualizado,
    "PETICION_RETIRADA": _peticion_retirada,
    "PRIMERA_VEZ": _primera_vez,
    "PUBLICANDO_EN_PRUEBAS": _publicando_en_pruebas,
    "QUEDAN_MINUTOS": _quedan_minutos,
    "REGISTRO_NO_GUARDADO": _registro_no_guardado,
    "REINICIA_EL_AGENTE": _reinicia_el_agente,
    "RESULTADO": _resultado,
    "SESION_ABIERTA": _sesion_abierta,
    "SESION_ANTERIOR_CERRADA": _sesion_anterior_cerrada,
    "SESION_CERRADA": _sesion_cerrada,
    "SIGUE_FALTANDO": _sigue_faltando,
    "SIGUE_LA_VERSION_ACTUAL": _sigue_la_version_actual,
    "TIZA_ACTUALIZADA": _tiza_actualizada,
}


def lineas_de_aviso(aviso: Aviso) -> tuple[Linea, ...]:
    """El aviso en texto llano para el docente."""
    return _CONVERSIONES[aviso.codigo](aviso.datos)
