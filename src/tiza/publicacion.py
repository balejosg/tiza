"""La publicación como proceso: puertas, resúmenes, confirmación y registro.

Es lo que comparten «tiza publicar» desde la terminal del docente y la sesión que
atiende al agente: recibe los documentos ya cargados y el aula ya abierta, aplica
las reglas de confianza y habla con el docente solo a través de una
:class:`Presencia`.

Lo que cambia según quién publica entra explícito, nunca por accidente:

- ``verificados``: hashes verificados en pruebas. La sesión pasa su registro en
  memoria (el agente no puede escribirlo); la terminal directa, ``None``, que lee
  ``verificados.json`` (no hay memoria de sesión entre procesos).
- ``vigente``: ¿sigue el agente esperando la petición? Solo la sesión puede
  comprobarlo; ``None`` significa que no hay nada que retirar.
- ``cupo``: tope de publicaciones en pruebas por sesión. Solo la sesión lo pasa:
  frena a un agente en bucle; la terminal del docente publica lo que pide una vez.
- ``avisar_en_pruebas``: la sesión avisa «el agente pide…»; en la terminal directa
  ya está la confirmación de destino.
- ``omitidos``: cursos que la terminal descartó antes de pedir la contraseña; no
  se vuelven a preguntar y el informe los cuenta como omitidos.
- ``sobrescribir`` y ``no_publicar`` (de ``publicar_con``, por ruta resuelta del documento): lo que
  el docente decidió sobre las actividades que retocó a mano en el aula. Solo los pone
  ``publicar_en_cursos`` tras preguntarle (``Presencia.confirmar_sobrescribir``); la petición del
  agente no puede pedir sobrescribir.
"""

from __future__ import annotations

import hashlib
import re
import sys
import traceback
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from . import calendario, contenido, estado, ficheros, informe, publicar, rutas, tipos
from .calificacion import reconciliar as rc
from .calificacion.deseado import Deseado
from .calificacion.deseado import deseado as calcular_deseado
from .calificacion.ejecutar import TIPOS_DE_BLOQUEO, Ejecucion
from .calificacion.esquema import Elemento, ErrorCalificacion, Esquema
from .config import Config
from .contenido import Documento, ErrorContenido, hash_documento
from .estado import ErrorEstado
from .estructura import Estructura, aplica_origen
from .publicar import AulaVirtual, CalificadorAula, ErrorPublicacion
from .tipos import CAMPO_RECORDATORIO, FechaActividad

if TYPE_CHECKING:  # solo para el tipo; la sesión importa este módulo
    from .sesion import CursoSesion

__all__ = [
    "AVISO_DEBUG",
    "AVISOS",
    "Aviso",
    "CAMPO_RECORDATORIO",
    "ActividadOrden",
    "CambioFecha",
    "CUPO_COPIAS",
    "CUPO_COPIAS_ACTIVIDAD",
    "CambioNombre",
    "CambioSeccion",
    "DocumentoBreve",
    "DocumentoResumen",
    "ElementoCalificador",
    "EvaluacionCerrada",
    "FicheroAislamiento",
    "MAX_PUBLICACIONES_PRUEBAS",
    "PlanCalificador",
    "Presencia",
    "ResumenAislamiento",
    "ResumenCalificador",
    "ResumenCopia",
    "ResumenOrden",
    "ResumenPublicacion",
    "ResumenSinPruebas",
    "ResumenSobrescribir",
    "SeccionOrden",
    "cambiadas_en_el_aula",
    "cambios_de_fechas",
    "cambios_de_nombre",
    "cambios_de_seccion",
    "calificador_con",
    "calificador_en_cursos",
    "cargar_calendario",
    "codigo_solo_fechas",
    "copiar_actividades",
    "copiar_curso",
    "depurar",
    "exige_oculto_sin_pruebas",
    "informe_de_cursos",
    "itinerario_de",
    "nombres_de_cursos",
    "ordenar_con",
    "ordenar_en_cursos",
    "ordenar_por_dependencias",
    "preparar_calificador",
    "publicar_con",
    "publicar_en_cursos",
    "puerta_real",
    "resumen_calificador",
    "resumen_orden",
    "resumen_solo_fechas",
]

AVISO_DEBUG = "AVISO: salida de depuración; no la compartas."
MAX_PUBLICACIONES_PRUEBAS = 50  # por sesión: frena a un agente en bucle
CUPO_COPIAS = 3  # copias del curso por sesión: frena a un agente en bucle
CUPO_COPIAS_ACTIVIDAD = 20  # copias de una sola actividad por sesión (cada actividad gasta 1)
# Moodle reescala los pesos de los hermanos al guardar uno: fijarlos converge, pero no de golpe.
# Tope de repasos de la segunda pasada del calificador (cada uno suele dividir el error por 4).
MAX_PASADAS_DE_AJUSTE = 8

# Lo que la publicación y la sesión cuentan al docente. Cada aviso tiene su
# constructor tipado en ``Aviso`` (dueño de las claves de ``datos``) y su texto
# llano en :mod:`tiza.mensajes`.
AVISOS = frozenset(
    {
        "ACTIVIDAD_EN_EVALUACION_CERRADA",
        "ACTIVIDAD_PENDIENTE",
        "AISLAMIENTO_GUARDADO",
        "AUTOPRUEBA_FALLIDA",
        "CALIFICANDO_EN_PRUEBAS",
        "CAMBIADA_DESDE_LA_PUBLICACION",
        "CAMBIADA_EN_EL_AULA",
        "CAMBIADO_A_MANO",
        "CANCELADA",
        "CARPETA_NO_AISLADA",
        "CERRANDO_SESION_ANTERIOR",
        "COMPROBACIONES_DE_AISLAMIENTO",
        "CONFIGURACION_GUARDADA",
        "COPIA_QUEDA_EN_EL_AULA",
        "CREANDO_SECCION",
        "CRITERIOS_SIN_PESO",
        "CURSOS_GUARDADOS",
        "ELEMENTO_CON_NOTAS_QUITADO",
        "ELEMENTO_SIN_ACTIVIDADES",
        "ERROR_INTERNO",
        "ESTRUCTURA_NO_LEIDA",
        "EVALUACION_CERRADA_EN_EL_AULA",
        "FALLO",
        "HUELLA_NO_GUARDADA",
        "INFORME_NO_ESCRITO",
        "MAXIMO_ALCANZADO",
        "NADA_QUE_CAMBIAR",
        "NOMBRES_NO_DISPONIBLES",
        "ORDENANDO_EN_PRUEBAS",
        "PANEL_ACTUALIZADO",
        "PANEL_NO_ACTUALIZADO",
        "PETICION_RETIRADA",
        "PRIMERA_VEZ",
        "PUBLICANDO_EN_PRUEBAS",
        "QUEDAN_MINUTOS",
        "REGISTRO_NO_GUARDADO",
        "REINICIA_EL_AGENTE",
        "RESULTADO",
        "SESION_ABIERTA",
        "SESION_ANTERIOR_CERRADA",
        "SESION_CERRADA",
        "SIGUE_FALTANDO",
        "SIGUE_LA_VERSION_ACTUAL",
        "TIZA_ACTUALIZADA",
    }
)


@dataclass(frozen=True)
class Aviso:
    """Algo que la publicación o la sesión cuentan al docente; ``codigo`` está en ``AVISOS``.

    Cada código tiene aquí su constructor con los tipos de sus datos; el
    constructor genérico queda para registros y pruebas.
    """

    codigo: str
    datos: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.codigo not in AVISOS:
            raise ValueError(f"aviso desconocido: {self.codigo}")

    @classmethod
    def actividad_en_evaluacion_cerrada(cls, ruta: str) -> Aviso:
        """``ruta``: el fichero nuevo en una evaluación cerrada, que se queda sin colocar."""
        return cls("ACTIVIDAD_EN_EVALUACION_CERRADA", {"ruta": ruta})

    @classmethod
    def actividad_pendiente(cls, ruta: str) -> Aviso:
        """``ruta``: el fichero de la carpeta que aún no está en el aula (o no se califica)."""
        return cls("ACTIVIDAD_PENDIENTE", {"ruta": ruta})

    @classmethod
    def aislamiento_guardado(cls, ruta: Path, copia: str | None) -> Aviso:
        """``ruta``: el fichero escrito; ``copia``: nombre de su copia de seguridad, si la había."""
        return cls("AISLAMIENTO_GUARDADO", {"ruta": ruta, "copia": copia})

    @classmethod
    def autoprueba_fallida(cls) -> Aviso:
        return cls("AUTOPRUEBA_FALLIDA")

    @classmethod
    def calificando_en_pruebas(cls, esquema: str) -> Aviso:
        return cls("CALIFICANDO_EN_PRUEBAS", {"esquema": esquema})

    @classmethod
    def cambiado_a_mano(cls, nombre: str) -> Aviso:
        """``nombre``: lo que el docente cambió en el aula y tiza no toca (viene del aula)."""
        return cls("CAMBIADO_A_MANO", {"nombre": nombre})

    @classmethod
    def criterios_sin_peso(cls, elemento: str) -> Aviso:
        """``elemento``: el id del esquema cuyos criterios no llevan peso."""
        return cls("CRITERIOS_SIN_PESO", {"elemento": elemento})

    @classmethod
    def elemento_con_notas_quitado(cls, nombre: str) -> Aviso:
        return cls("ELEMENTO_CON_NOTAS_QUITADO", {"nombre": nombre})

    @classmethod
    def elemento_sin_actividades(cls, elemento: str) -> Aviso:
        """``elemento``: el id del esquema (RA1…) al que no llega ninguna actividad."""
        return cls("ELEMENTO_SIN_ACTIVIDADES", {"elemento": elemento})

    @classmethod
    def evaluacion_cerrada_en_el_aula(cls, nombre: str) -> Aviso:
        return cls("EVALUACION_CERRADA_EN_EL_AULA", {"nombre": nombre})

    @classmethod
    def cambiada_en_el_aula(cls, nombre: str, cmid: int | None = None) -> Aviso:
        """``cmid``: con él, el docente aún no juntó los cambios de ``.tiza/copia/<cmid>.html``."""
        return cls("CAMBIADA_EN_EL_AULA", {"nombre": nombre, "cmid": cmid})

    @classmethod
    def cambiada_desde_la_publicacion(cls, nombre: str) -> Aviso:
        """Retocada a mano en el aula desde la última vez que tiza la publicó (sin copia de por medio)."""
        return cls("CAMBIADA_DESDE_LA_PUBLICACION", {"nombre": nombre})

    @classmethod
    def cancelada(cls) -> Aviso:
        return cls("CANCELADA")

    @classmethod
    def carpeta_no_aislada(cls) -> Aviso:
        return cls("CARPETA_NO_AISLADA")

    @classmethod
    def comprobaciones_de_aislamiento(cls, comprobaciones: Sequence[Any]) -> Aviso:
        """``comprobaciones``: las ``aislamiento.Comprobacion`` de la revisión, en orden."""
        return cls("COMPROBACIONES_DE_AISLAMIENTO", {"comprobaciones": tuple(comprobaciones)})

    @classmethod
    def configuracion_guardada(cls, ruta: Path) -> Aviso:
        return cls("CONFIGURACION_GUARDADA", {"ruta": ruta})

    @classmethod
    def cerrando_sesion_anterior(cls) -> Aviso:
        return cls("CERRANDO_SESION_ANTERIOR")

    @classmethod
    def copia_queda_en_el_aula(cls) -> Aviso:
        return cls("COPIA_QUEDA_EN_EL_AULA")

    @classmethod
    def creando_seccion(cls, nombre: str) -> Aviso:
        return cls("CREANDO_SECCION", {"nombre": nombre})

    @classmethod
    def cursos_guardados(cls, ruta: Path) -> Aviso:
        return cls("CURSOS_GUARDADOS", {"ruta": ruta})

    @classmethod
    def error_interno(cls, tipo: str) -> Aviso:
        return cls("ERROR_INTERNO", {"tipo": tipo})

    @classmethod
    def estructura_no_leida(cls) -> Aviso:
        return cls("ESTRUCTURA_NO_LEIDA")

    @classmethod
    def fallo(cls, codigo: str, detalle: str = "") -> Aviso:
        return cls("FALLO", {"codigo": codigo, "detalle": detalle})

    @classmethod
    def huella_no_guardada(cls, nombre: str) -> Aviso:
        return cls("HUELLA_NO_GUARDADA", {"nombre": nombre})

    @classmethod
    def registro_no_guardado(cls, nombre: str) -> Aviso:
        return cls("REGISTRO_NO_GUARDADO", {"nombre": nombre})

    @classmethod
    def informe_no_escrito(cls) -> Aviso:
        return cls("INFORME_NO_ESCRITO")

    @classmethod
    def maximo_alcanzado(cls, horas: int) -> Aviso:
        return cls("MAXIMO_ALCANZADO", {"horas": horas})

    @classmethod
    def nada_que_cambiar(cls) -> Aviso:
        return cls("NADA_QUE_CAMBIAR")

    @classmethod
    def panel_actualizado(cls, version: str) -> Aviso:
        """``version``: la que ha dejado instalada el actualizador del panel (``0.30.0``)."""
        return cls("PANEL_ACTUALIZADO", {"version": version})

    @classmethod
    def panel_no_actualizado(cls, actual: str, log: str) -> Aviso:
        """``actual``: la versión con la que se sigue; ``log``: dónde está el detalle."""
        return cls("PANEL_NO_ACTUALIZADO", {"actual": actual, "log": log})

    @classmethod
    def nombres_no_disponibles(cls) -> Aviso:
        return cls("NOMBRES_NO_DISPONIBLES")

    @classmethod
    def ordenando_en_pruebas(cls, documentos: tuple[DocumentoBreve, ...]) -> Aviso:
        return cls("ORDENANDO_EN_PRUEBAS", {"documentos": documentos})

    @classmethod
    def peticion_retirada(cls) -> Aviso:
        return cls("PETICION_RETIRADA")

    @classmethod
    def primera_vez(cls) -> Aviso:
        return cls("PRIMERA_VEZ")

    @classmethod
    def publicando_en_pruebas(cls, documentos: tuple[DocumentoResumen, ...]) -> Aviso:
        return cls("PUBLICANDO_EN_PRUEBAS", {"documentos": documentos})

    @classmethod
    def quedan_minutos(cls, minutos: int) -> Aviso:
        return cls("QUEDAN_MINUTOS", {"minutos": minutos})

    @classmethod
    def reinicia_el_agente(cls) -> Aviso:
        return cls("REINICIA_EL_AGENTE")

    @classmethod
    def resultado(cls, documento: dict) -> Aviso:
        return cls("RESULTADO", {"documento": documento})

    @classmethod
    def sesion_abierta(cls, caduca: datetime) -> Aviso:
        return cls("SESION_ABIERTA", {"caduca": caduca})

    @classmethod
    def sesion_anterior_cerrada(cls) -> Aviso:
        return cls("SESION_ANTERIOR_CERRADA")

    @classmethod
    def sesion_cerrada(cls, motivo: str) -> Aviso:
        return cls("SESION_CERRADA", {"motivo": motivo})

    @classmethod
    def sigue_faltando(cls, faltas: Sequence[Any]) -> Aviso:
        """``faltas``: las ``aislamiento.Comprobacion`` con estado «falta» tras aislar."""
        return cls("SIGUE_FALTANDO", {"faltas": tuple(faltas)})

    @classmethod
    def sigue_la_version_actual(cls) -> Aviso:
        return cls("SIGUE_LA_VERSION_ACTUAL")

    @classmethod
    def tiza_actualizada(cls, windows: bool) -> Aviso:
        """``windows``: la instalación sigue en otra ventana y hay que esperar a que acabe."""
        return cls("TIZA_ACTUALIZADA", {"windows": windows})


@dataclass(frozen=True)
class CambioFecha:
    """Una fecha de la actividad frente a la que hay en el aula. La ve solo el docente.

    ``antes`` y ``despues`` son (año, mes, día, hora, minuto), o None si no hay fecha.
    ``estado``: ``nueva`` (la actividad no existe en el aula), ``igual``, ``cambia`` o
    ``desconocida`` (no se pudo leer el aula: solo se enseña lo que se publicaría).
    """

    # «apertura», «entrega», «límite», «cierre» o CAMPO_RECORDATORIO
    campo: str
    antes: tuple[int, int, int, int, int] | None
    despues: tuple[int, int, int, int, int] | None
    estado: str
    avisos: tuple[str, ...] = ()  # FECHA_FESTIVA… según calendario.toml; nunca bloquean


@dataclass(frozen=True)
class DocumentoResumen:
    """Lo que el docente necesita ver de un documento antes de publicarlo."""

    fichero: str
    tipo: str
    nombre: str
    seccion: int | str
    # Las fechas que declara el documento, ya sin mirar de qué tipo es (las de una
    # tarea y las de un cuestionario se ven igual): campo llano y momento.
    fechas: tuple[FechaActividad, ...]
    vista_previa: Path | None = None
    enlaces_externos: tuple[str, ...] = ()
    incrustados: tuple[str, ...] = ()  # URL de los iframes, tal como se publicarán
    recursos: tuple[str, ...] = ()  # ficheros locales que se suben, relativos a la carpeta
    h5p: str | None = None  # actividad H5P generada («Rellenar huecos»)
    h5p_libreria: str | None = None  # librería principal de un paquete subido
    h5p_descartadas: tuple[str, ...] = ()  # librerías que tiza no sube nunca
    imagenes_preguntas: int = 0  # imágenes locales dentro de las preguntas de un cuestionario
    # None: no se ha comparado con el aula (pruebas, la confirmación corta…).
    cambios: tuple[CambioFecha, ...] | None = None
    # Finalización y restricciones que declara el .md, en lenguaje llano (solo del .md).
    itinerario: tuple[str, ...] = ()
    # El registro la daba por publicada en este curso y ya no está en el aula: se creará de nuevo.
    borrada: bool = False

    @classmethod
    def de(
        cls,
        doc: Documento,
        base: Path,
        vista_previa: Path | None = None,
        cambios: tuple[CambioFecha, ...] | None = None,
        borrada: bool = False,
    ) -> DocumentoResumen:
        return cls(
            fichero=doc.ruta.name,
            tipo=doc.tipo,
            nombre=doc.nombre,
            seccion=doc.seccion,
            fechas=tuple(
                fecha for fecha in tipos.obtener(doc.tipo).fechas(doc) if fecha.momento is not None
            ),
            vista_previa=vista_previa,
            enlaces_externos=tuple(doc.enlaces_externos),
            incrustados=tuple(doc.incrustados),
            recursos=tuple(_relativa(recurso.ruta, base) for recurso in doc.recursos),
            cambios=cambios,
            itinerario=itinerario_de(doc, base),
            borrada=borrada,
            **tipos.obtener(doc.tipo).extras_resumen(doc),
        )


@dataclass(frozen=True)
class ResumenPublicacion:
    """Lo que se va a publicar en real: la presencia lo enseña y el docente decide."""

    curso: int
    nombre_curso: str | None
    documentos: tuple[DocumentoResumen, ...]
    secciones_nuevas: tuple[str, ...]
    visible: bool | None  # True: visible; False: oculto; None: lo que exista conserva
    solo_fechas: bool = False  # «--solo-fechas»: el contenido y la visibilidad no cambian
    aviso_calendario: str | None = None  # código si calendario.toml no se pudo usar
    posicion: int = 1  # «Curso k de n»: con varios cursos reales, una confirmación por curso
    total: int = 1
    # Actividades que cambian de sección al cambiar su ``seccion:`` (se mueven, no se duplican).
    movimientos: tuple[CambioSeccion, ...] = ()
    # Actividades que cambian de nombre al publicarse (se actualizan por su origen o su registro).
    nombres: tuple[CambioNombre, ...] = ()


@dataclass(frozen=True)
class CambioNombre:
    """Una actividad que ya está en el aula con otro nombre. La ve solo el docente."""

    fichero: str
    antes: str  # el nombre que tiene en el aula
    despues: str  # el nombre del fichero


@dataclass(frozen=True)
class CambioSeccion:
    """Una actividad que ya está en el aula y cambia de sección al publicar."""

    fichero: str
    origen: str  # nombre de la sección de la que sale (la ve solo el docente)
    destino: str


@dataclass(frozen=True)
class DocumentoBreve:
    """Lo mínimo de un documento para confirmar una publicación sin curso de pruebas.

    ``existe``: True si ya hay un módulo con su tipo y nombre en su sección (se
    actualizará y, al ir oculto, se ocultará si estaba visible), False si es
    nuevo y None si la estructura del aula no permitió comprobarlo.
    """

    fichero: str
    tipo: str
    nombre: str
    existe: bool | None = False
    itinerario: tuple[str, ...] = ()
    borrada: bool = False  # el registro la daba por publicada y ya no está: se creará de nuevo


@dataclass(frozen=True)
class ResumenSinPruebas:
    """La confirmación corta cuando no hay curso de pruebas: solo se publica oculto."""

    curso: int
    nombre_curso: str | None
    documentos: tuple[DocumentoBreve, ...]
    secciones_nuevas: tuple[str, ...]
    posicion: int = 1
    total: int = 1
    movimientos: tuple[CambioSeccion, ...] = ()
    nombres: tuple[CambioNombre, ...] = ()


@dataclass(frozen=True)
class ActividadOrden:
    """Una actividad de una sección en su orden nuevo; ``fichero`` es None si no es de tiza."""

    nombre: str
    tipo: str
    fichero: str | None = None


@dataclass(frozen=True)
class SeccionOrden:
    """Una sección cuyo orden cambia, con todas sus actividades como quedarán."""

    nombre: str
    actividades: tuple[ActividadOrden, ...]


@dataclass(frozen=True)
class ResumenOrden:
    """Lo que se va a reordenar en real: la presencia lo enseña y el docente decide."""

    curso: int
    nombre_curso: str | None
    secciones: tuple[SeccionOrden, ...]
    # (fichero que queda encima, fichero que debe completarse antes): solo un aviso.
    dependencias: tuple[tuple[str, str], ...] = ()
    posicion: int = 1
    total: int = 1


@dataclass(frozen=True)
class ElementoCalificador:
    """Un elemento del esquema (RA1…) como lo ve el docente al confirmar el calificador.

    ``peso`` es su porcentaje de la final (``None`` si la final es por evaluaciones) y
    ``actividades`` pares (nombre de la actividad, porcentaje del elemento). Todo sale de los
    ficheros de la carpeta, nunca del aula.
    """

    id: str
    peso: float | None
    actividades: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class EvaluacionCerrada:
    """Una evaluación marcada ``cerrada: true``: tiza no la toca; ``secciones`` son las del esquema.

    ``por_bloquear``: aún no está bloqueada en el aula; tiza la completa y la bloquea al terminar.
    """

    nombre: str
    secciones: tuple[int | str, ...]
    por_bloquear: bool = False


@dataclass(frozen=True)
class ResumenCalificador:
    """Lo que va a hacer ``tiza calificador`` en un curso real: la presencia lo enseña y el docente decide.

    ``mueve`` y ``ids_nuevos`` son nombres de actividades (de los ficheros); ``bloquea`` los
    nombres de los totales ajenos con notas que se bloquean (del aula: solo los ve el docente,
    saneados). ``anterior``: el curso ya tenía un calificador que no es de tiza.
    ``notas_cambian``: evaluaciones abiertas con notas dentro de lo de tiza. ``total_curso``:
    ``"porcentaje"`` o ``"nota_final"`` cuando el plan cambia el total del curso (solo sin
    calificador anterior); ``tope``: ``(umbral, máximo)`` de la regla de la final, si la hay;
    ``quita``: nombres (del aula) de lo de tiza que se borra, que no tiene notas.
    ``casillas``: nombres (del esquema) de las casillas manuales de instrumentos que se crean.
    """

    curso: int
    nombre_curso: str | None
    lineas_esquema: tuple[ElementoCalificador, ...]
    mueve: tuple[str, ...]
    bloquea: tuple[str, ...]
    ids_nuevos: tuple[str, ...]
    cerradas: tuple[EvaluacionCerrada, ...]
    avisos: tuple[Aviso, ...]
    posicion: int = 1
    total: int = 1
    anterior: bool = False
    notas_cambian: tuple[str, ...] = ()
    total_curso: str | None = None
    tope: tuple[float, float] | None = None
    quita: tuple[str, ...] = ()
    casillas: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanCalificador:
    """Lo que ``tiza calificador`` va a hacer en un curso: se calcula antes de confirmar.

    Es lo que se enseña y lo que se ejecuta: no se vuelve a calcular entre la confirmación y la
    ejecución, para no hacer algo distinto de lo que vio el docente.
    """

    curso: int
    aula_antes: CalificadorAula
    deseado: Deseado
    reconciliacion: rc.Reconciliacion
    cmids: dict[str, int]
    huellas: dict[str, str]
    documentos: tuple[Documento, ...]  # los que cuentan (los que llevan «evalua»)
    base: Path


@dataclass(frozen=True)
class ResumenCopia:
    """La copia que se pide: la presencia lo enseña y el docente decide.

    ``entorno`` es ``pruebas`` o ``real``; ``nombre_curso`` viene del aula y solo lo ve el docente.
    ``actividades`` son los nombres tal como están en el fichero (``doc.nombre``) cuando la copia
    es de actividades sueltas; vacío, la copia es del curso entero.
    """

    curso: int
    nombre_curso: str | None
    entorno: str
    actividades: tuple[str, ...] = ()  # ``doc.nombre`` de cada una; vacío = el curso entero


@dataclass(frozen=True)
class ResumenSobrescribir:
    """Las actividades de un curso real que el docente retocó a mano desde que tiza las publicó.

    Se pregunta después de la confirmación normal del curso. ``actividades`` son los nombres tal
    como están en el fichero (``doc.nombre``), nunca texto del aula.
    """

    curso: int
    nombre_curso: str | None
    actividades: tuple[str, ...]
    posicion: int = 1
    total: int = 1


@dataclass(frozen=True)
class FicheroAislamiento:
    """Un fichero que el aislamiento escribiría y qué cambia en él (sin su contenido)."""

    ruta: Path
    cambios: tuple[str, ...]


@dataclass(frozen=True)
class ResumenAislamiento:
    """Lo que el aislamiento de la carpeta (o global) hará, para que el docente lo confirme.

    ``manuales`` son frases ya redactadas: lo que tiza no edita y el docente debe cambiar a mano.
    Pueden venir sin ``ficheros``: entonces no hay nada que escribir ni que confirmar.
    """

    ficheros: tuple[FicheroAislamiento, ...]
    manuales: tuple[str, ...] = ()


def itinerario_de(doc: Documento, base: Path) -> tuple[str, ...]:
    """El itinerario del documento en lenguaje llano, con los nombres de sus dependencias.

    Los nombres salen de los ``.md`` de la carpeta, nunca del aula.
    """
    if doc.finalizacion is None and doc.restricciones is None:
        return ()
    nombres: dict[str, str] = {}
    for fichero in doc.restricciones.completar if doc.restricciones else ():
        try:
            nombres[fichero] = contenido.cargar(base / fichero, raiz=base).nombre
        except ErrorContenido:
            continue
    return tuple(contenido.describir_itinerario(doc, nombres))


def _relativa(ruta: Path, base: Path) -> str:
    """Ruta de un recurso relativa a la carpeta (antes se comprueba que está dentro)."""
    try:
        return Path(ruta).resolve().relative_to(base).as_posix()
    except ValueError:
        return Path(ruta).name


class Presencia(Protocol):
    """Quien está delante: la terminal de «tiza sesion» (la entrada al aula puede ir en una ventana).

    Cada implementación sanea los textos ajenos al mostrarlos.
    """

    def acreditar(self, url: str, usuario: str) -> publicar.Acreditacion | None:
        """Cómo entra el docente al aula ``url``: contraseña (terminal) o la sesión de la
        ventana de entrada, tras enseñar a qué servidor va; None si cancela."""
        ...

    def elegir_curso(self, entorno: str, cursos: list[dict], excluir: int | None) -> int | None:
        """Id del curso de ``entorno`` (``cursos``: dicts con id y nombre); None si cancela.

        Para ``pruebas`` también admite ``SIN_PRUEBAS``: el docente no tiene
        curso de pruebas y en real solo se publicará oculto.
        """
        ...

    def elegir_cursos_reales(self, cursos: list[dict], excluir: int | None) -> list[int] | None:
        """Ids de 1 a ``config.MAX_REALES`` cursos reales, en orden, sin ``excluir`` (el de
        pruebas); None si cancela."""
        ...

    def confirmar_cursos(self, cursos: list[CursoSesion]) -> bool:
        """¿Abrir la sesión con estos cursos?"""
        ...

    def confirmar_autoprueba(self) -> bool:
        """¿Pasar ahora la autoprueba en el curso de pruebas?"""
        ...

    def confirmar_real(self, resumen: ResumenPublicacion) -> bool:
        """¿Publicar en real lo que enseña ``resumen``? Una respuesta por petición."""
        ...

    def confirmar_real_sin_pruebas(self, resumen: ResumenSinPruebas) -> bool:
        """¿Publicar oculto en real sin curso de pruebas? Una respuesta por petición."""
        ...

    def confirmar_orden(self, resumen: ResumenOrden) -> bool:
        """¿Reordenar en real como enseña ``resumen``? Una respuesta por curso."""
        ...

    def confirmar_calificador(self, resumen: ResumenCalificador) -> bool:
        """¿Montar el calificador en real como enseña ``resumen``? Una respuesta por curso."""
        ...

    def confirmar_copia(self, resumen: ResumenCopia) -> bool:
        """¿Hacer una copia de este curso, sin datos de alumnos? Una respuesta por petición."""
        ...

    def confirmar_sobrescribir(self, resumen: ResumenSobrescribir) -> bool:
        """¿Sobrescribir las actividades que retocaste a mano en el aula y perder esos cambios?
        Una respuesta por curso; sin respuesta, es no."""
        ...

    def confirmar_sin_pruebas(self) -> bool:
        """¿Abrir la sesión sin curso de pruebas? (no habrá verificación previa)."""
        ...

    def configurar(self, validar: Callable[[str], None] | None = None) -> tuple[str, str] | None:
        """URL del aula y usuario, tal como los da el docente; None si cancela. Nunca la contraseña.

        ``validar`` lanza ``ErrorConfig`` si la URL no vale: una presencia puede llamarla en
        cuanto tiene la URL, para no pedir el usuario en balde. Quien llama valida igualmente.
        """
        ...

    def confirmar_actualizacion(self, nueva: str, actual: str) -> bool:
        """¿Actualizar ahora a la versión ``nueva`` (etiqueta, p. ej. ``v0.30.0``) teniendo la
        ``actual``? Después hay que volver a abrir."""
        ...

    def confirmar_carpeta_dudosa(self, carpeta: Path) -> bool:
        """¿Abrir la sesión en ``carpeta`` aunque no parezca la de una asignatura?"""
        ...

    def ofrecer_aislamiento(self) -> bool:
        """¿Aplicar ahora el aislamiento a esta carpeta, que no lo tiene? Si no, se pregunta
        si se sigue sin aislar. Sin respuesta, es no."""
        ...

    def confirmar_aislamiento(self, resumen: ResumenAislamiento) -> bool:
        """¿Hacer estos cambios de aislamiento? Primero enseña ``resumen.manuales``; sin
        ``resumen.ficheros`` no hay nada que preguntar y responde True."""
        ...

    def seguir_sin_aislar(self, faltas: list) -> bool:
        """¿Seguir sin aislar el agente? ``faltas``: las comprobaciones que fallan."""
        ...

    def cerrar_sesion_anterior(self, atendiendo: bool) -> bool:
        """¿Cerrar la sesión que sigue abierta en esta carpeta (quizá en una terminal que se
        cerró) y abrir esta? ``atendiendo``: está con una petición del agente."""
        ...

    def ofrecer_ampliacion(self, minutos: int, plazo: float) -> bool:
        """¿Ampliar ``minutos`` más? Sin respuesta en ``plazo`` segundos, es no."""
        ...

    def informar(self, aviso: Aviso) -> None:
        """Enseña un aviso de la publicación o de la sesión."""
        ...


def depurar(exc: BaseException, debug: bool) -> None:
    """Traza para quien desarrolla, solo con --debug; nunca llega al agente."""
    if not debug:
        return
    print(AVISO_DEBUG, file=sys.stderr)
    traceback.print_exception(exc.__cause__ or exc)


def puerta_real(
    carpeta: Path,
    documentos: list[Documento],
    verificados: Mapping[str, estado.Verificado] | None = None,
) -> list[str]:
    """Nombres de los documentos sin verificación previa en pruebas.

    Con ``verificados`` (el registro en memoria de la sesión) no se fía de
    ``verificados.json``, que el agente puede escribir.
    """
    if verificados is None:
        verificados = estado.cargar_verificados(Path(carpeta) / rutas.CARPETA_TRABAJO)
    pares = [(doc.ruta.name, hash_documento(doc)) for doc in documentos]
    return estado.comprobar_puerta_real(verificados, pares)


def exige_oculto_sin_pruebas(cfg: Config, visible: bool | None, *, solo_fechas: bool) -> bool:
    """Regla común: sin curso de pruebas solo se publica en real oculto (o solo fechas).

    La terminal directa la usa también antes de pedir la contraseña, para no pedirla
    si va a rechazar la publicación.
    """
    return "pruebas" not in cfg.cursos and not solo_fechas and visible is not False


def nombres_de_cursos(aula: AulaVirtual, presencia: Presencia, debug: bool) -> dict[int, str]:
    """Nombres de los cursos del docente: solo para la presencia, nunca a .tiza."""
    try:
        return {curso["id"]: curso["nombre"] for curso in aula.mis_cursos()}
    except ErrorPublicacion as exc:
        presencia.informar(Aviso.nombres_no_disponibles())
        depurar(exc, debug)
        return {}


def cargar_calendario(carpeta: Path) -> tuple[calendario.Calendario | None, str | None]:
    """El calendario de la carpeta y, si existe pero no se puede usar, su código.

    Nunca aborta: sin calendario válido, las fechas simplemente no llevan avisos.
    """
    try:
        return calendario.cargar(carpeta), None
    except calendario.ErrorCalendario as exc:
        return None, exc.codigo


# El «recordatorio de calificación» de una tarea se reexporta aquí porque la
# confirmación de real lo nombra (ver ``tipos.base.CAMPO_RECORDATORIO``).


def cambios_de_fechas(
    aula: AulaVirtual,
    estructura: Estructura,
    doc: Documento,
    cal: calendario.Calendario | None,
    *,
    debug: bool = False,
    curso: int | None = None,
) -> tuple[CambioFecha, ...]:
    """Las fechas que se publicarían frente a las que tiene el aula, con sus avisos.

    Solo lo lee la presencia: no se guarda en ``.tiza`` ni sale hacia el agente. Las
    fechas de cada alumno (excepciones de cuestionario, prórrogas de tarea) no se
    leen nunca.
    """
    declaradas = tipos.obtener(doc.tipo).fechas(doc)
    if not declaradas:
        return ()
    esperadas = publicar.fechas_esperadas(doc)
    avisos_de = calendario.avisos_por_campo(cal, doc)
    huerfana = False  # su ``origen`` no está o el nombre es ambiguo: se negará al publicar
    loc = estructura.localizar(doc, curso)
    if loc.problema is not None:
        existente, huerfana = None, True
    else:
        existente = loc.actividad
    actuales: dict | None = None
    if existente is not None:
        try:
            actuales = aula.leer_modulo(existente.cmid).get("fechas") or {}
        except ErrorPublicacion as exc:
            depurar(exc, debug)  # no aborta: se dice al docente que no se pudo leer
    cambios: list[CambioFecha] = []
    for fecha in declaradas:
        despues = esperadas.get(fecha.campo_moodle)
        avisos = avisos_de.get(fecha.campo, ())
        if existente is None or actuales is None:
            if despues is None:
                continue
            estado = "nueva" if existente is None and not huerfana else "desconocida"
            cambios.append(CambioFecha(fecha.campo, None, despues, estado, avisos))
            continue
        antes = actuales.get(fecha.campo_moodle)
        if antes is None and despues is None:
            continue
        estado = "igual" if antes == despues else "cambia"
        cambios.append(CambioFecha(fecha.campo, antes, despues, estado, avisos))
    return tuple(cambios)


def ordenar_por_dependencias(documentos: list[Documento], base: Path) -> list[Documento] | None:
    """Los documentos con sus dependencias de la misma petición antes (orden estable).

    ``None`` si se piden unos a otros en círculo.
    """
    claves = [_relativa(doc.ruta, base) for doc in documentos]
    pendientes = list(zip(claves, documentos, strict=True))
    hechos: set[str] = set()
    salida: list[Documento] = []
    while pendientes:
        for indice, (clave, doc) in enumerate(pendientes):
            deps = doc.restricciones.completar if doc.restricciones else ()
            if all(dep in hechos or dep not in claves for dep in deps):
                salida.append(doc)
                hechos.add(clave)
                del pendientes[indice]
                break
        else:
            return None
    return salida


def _resolver_dependencias(
    base: Path,
    estructura: Estructura,
    documentos: list[Documento],
    existentes: dict[str, int],
    curso: int | None = None,
) -> tuple[str, str] | None:
    """Rellena ``existentes`` con el cmid en este curso de cada dependencia que no se pide.

    Devuelve (código, fichero) si alguna no se puede resolver: se mira antes de escribir.
    """
    pedidas = {_relativa(doc.ruta, base) for doc in documentos}
    for doc in documentos:
        for fichero in doc.restricciones.completar if doc.restricciones else ():
            if fichero in pedidas or fichero in existentes:
                continue
            try:
                dep = contenido.cargar(base / fichero, raiz=base)
            except ErrorContenido:
                return "DEPENDENCIA_INVALIDA", fichero
            modulo = estructura.localizar(dep, curso).actividad
            if modulo is None:
                return "DEPENDENCIA_NO_PUBLICADA", fichero
            existentes[fichero] = modulo.cmid
    return None


def codigo_solo_fechas(
    estructura: Estructura, documentos: list[Documento], curso: int | None = None
) -> str | None:
    """Por qué «--solo-fechas» no se puede aplicar a estos documentos, o None si sí."""
    for doc in documentos:
        if tipos.obtener(doc.tipo).payload_solo_fechas(doc) is None:
            return "SOLO_FECHAS_NO_APLICA"
        loc = estructura.localizar(doc, curso)
        if loc.problema is not None:
            return loc.problema
        if loc.actividad is None:
            return "MODULO_AUSENTE"
    return None


def resumen_solo_fechas(
    aula: AulaVirtual,
    curso: int,
    nombre_curso: str | None,
    documentos: list[Documento],
    carpeta: Path,
    estructura: Estructura,
    *,
    debug: bool = False,
    posicion: int = 1,
    total: int = 1,
) -> ResumenPublicacion:
    """Lo que se confirma en real con «--solo-fechas»: fechas antes y después, nada más."""
    cal, aviso = cargar_calendario(carpeta)
    return ResumenPublicacion(
        curso=curso,
        nombre_curso=nombre_curso,
        documentos=tuple(
            DocumentoResumen.de(
                doc,
                carpeta,
                cambios=cambios_de_fechas(aula, estructura, doc, cal, debug=debug, curso=curso),
            )
            for doc in documentos
        ),
        secciones_nuevas=(),
        visible=None,
        solo_fechas=True,
        aviso_calendario=aviso,
        posicion=posicion,
        total=total,
    )


def publicar_con(
    aula: AulaVirtual,
    entorno: str,
    curso: int,
    documentos: list[Documento],
    visible: bool | None,
    carpeta: Path,
    presencia: Presencia,
    *,
    debug: bool = False,
    solo_fechas: bool = False,
    sobrescribir: frozenset[Path] = frozenset(),
    no_publicar: frozenset[Path] = frozenset(),
) -> dict:
    """Con el aula ya abierta: publica y verifica los documentos.

    Con ``solo_fechas`` solo cambia las fechas de lo que ya existe: no crea secciones,
    no sube recursos y no registra nada como verificado en pruebas.

    En un curso real (``entorno == "real"``), lo que el docente retocó a mano en el aula desde que
    tiza lo publicó no se pisa: ``publicar.publicar_documento`` lo comprueba justo antes de
    escribir (``CAMBIADA_EN_EL_AULA``). Las decisiones del docente entran explícitas, por ruta
    resuelta del documento: ``sobrescribir`` (dijo que sí a perder ese cambio: se publica y el
    informe lleva ``CAMBIO_DEL_AULA_DESCARTADO``) y ``no_publicar`` (dijo que no: se rechaza como
    ``CAMBIADA_EN_EL_AULA``, con el resto del lote). Tras publicar en real se relee el aula y se
    guarda su huella como base de la próxima comparación. En pruebas no se compara ni se guarda.
    """
    borrador = informe.Borrador("publicar", entorno=entorno, curso=curso)
    borrador.paso("LOGIN")
    base = Path(carpeta).resolve()
    paso = "SOLO_FECHAS" if solo_fechas else "PUBLICAR"
    if not solo_fechas:
        ordenados = ordenar_por_dependencias(documentos, base)
        if ordenados is None:
            borrador.fallo("DEPENDENCIAS", "DEPENDENCIA_CIRCULAR")
            borrador.error("DEPENDENCIA_CIRCULAR")
            return borrador.documento("error")
        documentos = ordenados
    try:
        estructura = aula.estructura(curso)
    except ErrorPublicacion as exc:
        borrador.fallo("ESTRUCTURA", exc.codigo)
        borrador.error(exc.codigo)
        depurar(exc, debug)
        return borrador.documento("error")
    # Lo que se rechaza por su origen se dice ya y no deja nada hecho (ni una sección creada).
    dir_tiza = Path(carpeta) / rutas.CARPETA_TRABAJO
    try:
        huellas, marcas = _guardado_de_copia(dir_tiza, curso, documentos)
    except estado.ErrorEstado as exc:
        borrador.fallo("PREPARAR", exc.codigo)
        borrador.error(exc.codigo)
        return borrador.documento("error")
    aceptados, rechazados = _separar_rechazados(
        documentos, estructura, curso, base, solo_fechas, huellas, marcas, no_publicar
    )
    real = entorno == "real"
    for rechazado, motivo in rechazados:
        detalle = rechazado.ruta.name
        if motivo == "CAMBIADA_EN_EL_AULA" and aplica_origen(rechazado, curso):
            assert rechazado.origen is not None
            cmid = rechazado.origen.cmid
            detalle += f": junta antes los cambios de .tiza/copia/{cmid}.html"
            presencia.informar(Aviso.cambiada_en_el_aula(rechazado.nombre, cmid))
        elif motivo == "CAMBIADA_EN_EL_AULA":  # el docente retocó a mano y dijo que no
            presencia.informar(Aviso.cambiada_desde_la_publicacion(rechazado.nombre))
        borrador.fallo(paso, detalle)
        borrador.error(motivo)
    documentos = aceptados
    existentes: dict[str, int] = {}
    if not solo_fechas:
        faltante = _resolver_dependencias(base, estructura, documentos, existentes, curso)
        if faltante is not None:
            borrador.fallo("DEPENDENCIAS", faltante[1])
            borrador.error(faltante[0])
            return borrador.documento("error")
    if solo_fechas:
        # Todo o nada: si alguno de los documentos no se puede cambiar, no se cambia ninguno.
        codigo = codigo_solo_fechas(estructura, documentos, curso)
        if codigo is not None:
            borrador.fallo("SOLO_FECHAS", codigo)
            borrador.error(codigo)
            return borrador.documento("error")
    else:
        for nombre in estructura.secciones_que_faltan(documentos):
            presencia.informar(Aviso.creando_seccion(nombre))
        try:
            estructura, creadas = publicar.asegurar_secciones(aula, curso, estructura, documentos)
        except ErrorPublicacion as exc:
            borrador.fallo("CREAR_SECCION", exc.codigo)
            borrador.error(exc.codigo)
            depurar(exc, debug)
            return borrador.documento("error")
        for nombre in creadas:
            borrador.paso("CREAR_SECCION", detalle=nombre)
    cmids = dict(existentes)  # de cada fichero de la carpeta, su cmid en este curso
    motor: bool | None = None  # ¿dibuja el aula las fórmulas? Se mira una vez por curso
    for doc in documentos:
        try:
            huella = None
            huella_nueva = None  # solo --solo-fechas: la calcula publicar.py con lo que relee
            if doc.origen is not None and aplica_origen(doc, curso):
                # Sin huella no se llega aquí: ``_separar_rechazados`` ya lo dejó fuera.
                huella = huellas.get(doc.origen.cmid)
            decidido = doc.ruta.resolve() in sobrescribir
            if solo_fechas:
                resultado, huella_nueva = publicar.publicar_fechas_con_huella(
                    aula,
                    estructura,
                    doc,
                    curso,
                    huella,
                    comprobar_registro=real,
                    sobrescribir=decidido,
                )
            else:
                dependencias = {
                    fichero: cmids[fichero]
                    for fichero in (doc.restricciones.completar if doc.restricciones else ())
                    if fichero in cmids
                }
                resultado = publicar.publicar_documento(
                    aula,
                    curso,
                    estructura,
                    doc,
                    visible=visible,
                    dependencias=dependencias,
                    huella_aula=huella,
                    comprobar_registro=real,
                    sobrescribir=decidido,
                )
                assert resultado.cmid is not None  # acaba de crearla o actualizarla
                cmids[_relativa(doc.ruta, base)] = resultado.cmid
        except ErrorPublicacion as exc:
            borrador.fallo(paso, doc.ruta.name)
            depurar(exc, debug)
            borrador.error(exc.codigo)
            if exc.codigo not in ERRORES_POR_FICHERO:
                return borrador.documento("error")
            # Esta actividad no se toca; las demás del lote siguen.
            if exc.codigo == "CAMBIADA_EN_EL_AULA":
                presencia.informar(
                    Aviso.cambiada_en_el_aula(doc.nombre)
                    if aplica_origen(doc, curso)
                    else Aviso.cambiada_desde_la_publicacion(doc.nombre)
                )
            continue
        # Con --solo-fechas la huella nueva la da publicar.py; sin ella, se deja la que había.
        if aplica_origen(doc, curso) and (not solo_fechas or huella_nueva is not None):
            _renovar_huella(dir_tiza, curso, doc, borrador, presencia, huella_nueva)
        elif solo_fechas and huella_nueva is not None:
            # Sin ``origen``: la base de lo publicado, si no se pisó un cambio del docente.
            _renovar_base_registrada(
                dir_tiza, curso, _relativa(doc.ruta, base), doc, huella_nueva, borrador, presencia
            )
        if not solo_fechas:
            ruta = _relativa(doc.ruta, base)
            cmid_nuevo = cmids[ruta]  # el de arriba: acaba de crearla o actualizarla
            previo = _cmid_registrado(dir_tiza, curso, ruta)
            _registrar_publicado(
                dir_tiza,
                curso,
                ruta,
                doc,
                cmid_nuevo,
                borrador,
                presencia,
                aula=aula if real else None,
            )
            if real:
                _guardar_base(dir_tiza, curso, doc, cmid_nuevo, previo, borrador)
        if entorno == "pruebas" and not solo_fechas:
            assert resultado.cmid is not None and resultado.hash is not None
            estado.guardar_verificado(
                Path(carpeta) / rutas.CARPETA_TRABAJO,
                resultado.hash,
                resultado.nombre,
                resultado.cmid,
            )
        borrador.fichero(replace(resultado, curso=curso))
        detalle = doc.ruta.name
        if not solo_fechas:
            extra = tipos.obtener(doc.tipo).detalle(doc)
            if extra:
                detalle = f"{detalle}: {extra}"
        borrador.paso(paso, detalle=detalle)
        if decidido:
            borrador.paso("CAMBIO_DEL_AULA_DESCARTADO", detalle=doc.ruta.name)
        if not solo_fechas and contenido.tiene_formulas(doc):
            if motor is None:
                motor = publicar.aula_dibuja_formulas(aula, curso)
            if not motor:
                borrador.paso("FORMULAS_NO_DIBUJADAS", detalle=doc.ruta.name)
    return borrador.documento()


# Fallos que paran solo a su fichero: la actividad no se toca y el resto del lote sigue.
# ``DEPENDENCIA_NO_PUBLICADA`` aquí es la de un fichero del lote que se quedó sin publicar.
ERRORES_POR_FICHERO = frozenset(
    {
        "CAMBIADA_EN_EL_AULA",
        "ORIGEN_NO_ENCONTRADO",
        "ORIGEN_SIN_HUELLA",
        "DEPENDENCIA_NO_PUBLICADA",
    }
)


def _guardado_de_copia(
    dir_tiza: Path, curso: int, documentos: list[Documento]
) -> tuple[dict[int, str], dict[int, str]]:
    """De ``copia.json``, lo de este curso: (huella del aula, marca del fichero) por cmid.

    Solo se lee si algún documento viene de este curso por su ``origen``. Un ``copia.json``
    que no vale da ``ErrorEstado``.
    """
    if not any(aplica_origen(doc, curso) for doc in documentos):
        return {}, {}
    return estado.huellas_de_copia(dir_tiza, curso), estado.marcas_de_copia(dir_tiza, curso)


def _sin_origen_repetido(documentos: list[Documento]) -> tuple[list[Documento], list[Documento]]:
    """(los documentos sin otro del mismo ``origen``, los que lo comparten), en su orden."""
    cuantos = Counter((doc.origen.curso, doc.origen.cmid) for doc in documentos if doc.origen)
    repetido = [
        doc.origen is not None and cuantos[(doc.origen.curso, doc.origen.cmid)] > 1
        for doc in documentos
    ]
    return (
        [doc for doc, rep in zip(documentos, repetido, strict=True) if not rep],
        [doc for doc, rep in zip(documentos, repetido, strict=True) if rep],
    )


def _separar_rechazados(
    documentos: list[Documento],
    estructura: Estructura,
    curso: int,
    base: Path,
    solo_fechas: bool,
    huellas: Mapping[int, str],
    marcas: Mapping[int, str],
    no_publicar: Collection[Path] = (),
) -> tuple[list[Documento], list[tuple[Documento, str]]]:
    """(los que se pueden publicar, los rechazados con su código), mirando solo la estructura.

    Se rechazan antes de confirmar y de crear nada: dos ficheros del mismo ``origen``
    (``ORIGEN_DUPLICADO``), un ``origen`` que ya no está en este curso (``ORIGEN_NO_ENCONTRADO``),
    una actividad de la que ``copia.json`` no guarda la huella (``ORIGEN_SIN_HUELLA``: sin ella no
    se puede saber si cambió en el aula), una cuyo fichero sigue como cuando se marcó cambiada en
    el aula (``CAMBIADA_EN_EL_AULA``: el docente aún no juntó los cambios) y quien depende de uno
    rechazado (``DEPENDENCIA_NO_PUBLICADA``). Con ``--solo-fechas`` el origen no encontrado y las
    dependencias no cuentan: es todo o nada.

    ``no_publicar``: rutas resueltas de lo que el docente retocó a mano en el aula y no quiso
    sobrescribir (``CAMBIADA_EN_EL_AULA``, como los de ``origen``); quien depende de ellos también
    queda fuera.
    """
    base = Path(base).resolve()
    claves = [_relativa(doc.ruta, base) for doc in documentos]
    cuantos = Counter((doc.origen.curso, doc.origen.cmid) for doc in documentos if doc.origen)
    rechazados: dict[int, str] = {}
    for indice, doc in enumerate(documentos):
        if doc.origen is not None and cuantos[(doc.origen.curso, doc.origen.cmid)] > 1:
            rechazados[indice] = "ORIGEN_DUPLICADO"
    for indice, doc in enumerate(documentos):
        if indice in rechazados or doc.origen is None or not aplica_origen(doc, curso):
            continue
        if not solo_fechas:
            if estructura.localizar(doc, curso).problema is not None:
                rechazados[indice] = "ORIGEN_NO_ENCONTRADO"
                continue
        if doc.origen.cmid not in huellas:
            rechazados[indice] = "ORIGEN_SIN_HUELLA"
        elif publicar.marca_sin_juntar(marcas.get(doc.origen.cmid), doc):
            rechazados[indice] = "CAMBIADA_EN_EL_AULA"
    if no_publicar:
        for indice, doc in enumerate(documentos):
            if indice not in rechazados and doc.ruta.resolve() in no_publicar:
                rechazados[indice] = "CAMBIADA_EN_EL_AULA"
    if not solo_fechas:
        crecio = True
        while crecio:  # quien depende de un rechazado, también (de forma transitiva)
            crecio = False
            fuera = {claves[indice] for indice in rechazados}
            for indice, doc in enumerate(documentos):
                deps = doc.restricciones.completar if doc.restricciones else ()
                if indice not in rechazados and any(dep in fuera for dep in deps):
                    rechazados[indice] = "DEPENDENCIA_NO_PUBLICADA"
                    crecio = True
    return (
        [doc for indice, doc in enumerate(documentos) if indice not in rechazados],
        [(documentos[indice], rechazados[indice]) for indice in sorted(rechazados)],
    )


def _renovar_huella(
    dir_tiza: Path,
    curso: int,
    doc: Documento,
    borrador: informe.Borrador,
    presencia: Presencia,
    nueva: str | None = None,
) -> None:
    """Guarda en ``copia.json`` la huella de lo que se acaba de publicar, para el siguiente lote.

    Sin ``nueva`` se calcula con lo que tiza envió, sin releer el aula (espiga 5). Si no se puede
    guardar, la publicación sigue siendo buena; solo se avisa de que la próxima saltará.
    """
    assert doc.origen is not None
    try:
        if nueva is None:
            nueva = tipos.huella_de_lo_enviado(
                tipos.obtener(doc.tipo), doc, contenido.html_para_moodle(doc)
            )
        estado.guardar_huella_de_copia(dir_tiza, curso, doc.origen.cmid, nueva)
    except (estado.ErrorEstado, OSError):
        borrador.fallo("HUELLA_NO_GUARDADA", doc.ruta.name)
        presencia.informar(Aviso.huella_no_guardada(doc.nombre))


def _rechazos_por_el_no(
    documentos: list[Documento],
    estructura: Estructura,
    curso: int,
    base: Path,
    solo_fechas: bool,
    huellas: Mapping[int, str],
    marcas: Mapping[int, str],
    no_publicar: Collection[Path],
    de_siempre: list[tuple[Documento, str]],
) -> Counter[str]:
    """Los códigos de error que da el no del docente (y lo que arrastra), y nada más.

    Son los rechazos de ``_separar_rechazados`` con ``no_publicar`` que no estaban ya sin él
    (``de_siempre``): si el informe del curso no tiene otros errores, el curso no ha fallado.
    """
    _, con_el_no = _separar_rechazados(
        documentos, estructura, curso, base, solo_fechas, huellas, marcas, no_publicar
    )
    ya = {id(doc) for doc, _ in de_siempre}
    return Counter(motivo for doc, motivo in con_el_no if id(doc) not in ya)


def cambios_de_nombre(
    estructura: Estructura, documentos: list[Documento], curso: int
) -> tuple[CambioNombre, ...]:
    """Las actividades que se llaman distinto en el aula y en su fichero.

    Solo las que tiza halla por su ``origen`` o por el registro de lo publicado: las que halla por
    nombre se llaman igual por definición.
    """
    cambios: list[CambioNombre] = []
    for doc in documentos:
        loc = estructura.localizar(doc, curso)
        if loc.problema is not None:
            continue
        if loc.por not in ("origen", "registro") or loc.modulo is None:
            continue
        antes = loc.modulo.nombre
        if isinstance(antes, str) and antes != doc.nombre:
            cambios.append(CambioNombre(doc.ruta.name, antes, doc.nombre))
    return tuple(cambios)


def cambiadas_en_el_aula(
    aula: AulaVirtual,
    estructura: Estructura,
    documentos: list[Documento],
    curso: int,
    solo_fechas: bool = False,
) -> tuple[Documento, ...]:
    """Los documentos cuya actividad retocó el docente a mano en el aula desde que tiza la publicó.

    Solo mira los hallados por el registro y con huella en él (``publicar.cambio_a_mano``): del
    resto no lee nada. Lo que no se puede leer cuenta como cambiado, para no pisarlo a ciegas.
    Con ``solo_fechas``, lo que ya tiene las fechas del fichero no cuenta (un intento anterior las
    escribió y falló al verificar). Es solo lectura: el docente decide después
    (``Presencia.confirmar_sobrescribir``).
    """
    return tuple(
        doc
        for doc in documentos
        if publicar.cambio_a_mano(aula, estructura, doc, curso, solo_fechas)
    )


def cambios_en_el_aula(
    aula: AulaVirtual,
    estructura: Estructura,
    documentos: Sequence[Documento],
    curso: int,
    dir_tiza: Path,
) -> list[informe.Fichero]:
    """Un ``Fichero`` por documento: ``cambiada``, ``sin_cambios`` o ``sin_registro`` en ``curso``.

    Para ``tiza estructura --cambios`` (solo cursos reales; el llamador no pide el de pruebas). Con
    la regla de la publicación (``publicar.cambio_desde_la_base``); no escribe nada ni lleva texto
    del aula. ``copia.json`` solo se lee si algún documento viene de este curso por su ``origen``
    (``ErrorEstado`` si no vale).
    """
    huellas, marcas = _guardado_de_copia(dir_tiza, curso, list(documentos))
    ficheros = []
    for doc in documentos:
        cambiada, cmid = publicar.cambio_desde_la_base(
            aula, estructura, doc, curso, huellas, marcas
        )
        accion = "sin_registro" if cambiada is None else "cambiada" if cambiada else "sin_cambios"
        ficheros.append(
            informe.Fichero(doc.ruta.name, doc.tipo, cmid=cmid, accion=accion, curso=curso)
        )
    return ficheros


def _registrar_publicado(
    dir_tiza: Path,
    curso: int,
    ruta: str,
    doc: Documento,
    cmid: int,
    borrador: informe.Borrador,
    presencia: Presencia,
    *,
    aula: AulaVirtual | None = None,
) -> None:
    """Anota en ``publicados.json`` qué actividad es el fichero en este curso, para hallarla luego.

    Conserva la huella y la marca de la entrada anterior si es la misma actividad; si el cmid
    cambió (se recreó), van a None. Con ``aula`` (solo en un curso real) relee el formulario de
    lo que se acaba de publicar y guarda su huella como base de la próxima comparación, y la marca
    pasa a None; si la relectura falla, la entrada queda sin huella (como una antigua) y se avisa.
    Lo que se halla por ``origen`` no se relee: manda ``copia.json``. Si no se puede guardar, la
    publicación sigue siendo buena. Una ruta que no vale como clave no se registra ni se avisa:
    no es culpa del docente.
    """
    if not estado.ruta_publicada_valida(ruta):
        return
    no_guardado = False  # no se pudo guardar la entrada o no se pudo guardar con su huella
    try:
        anterior = estado.cargar_publicados(dir_tiza, curso).get(ruta)
        igual = anterior is not None and anterior.cmid == cmid
        huella = anterior.huella if igual and anterior else None
        marca = anterior.marca if igual and anterior else None
        if aula is not None and not aplica_origen(doc, curso):
            marca = None
            try:
                huella = tipos.huella_del_formulario(
                    tipos.obtener(doc.tipo), doc, aula.leer_modulo(cmid)
                )
            except ErrorPublicacion:
                huella, no_guardado = None, True
        estado.guardar_publicado(
            dir_tiza, curso, ruta, estado.Publicado(cmid, doc.tipo, huella=huella, marca=marca)
        )
    except (estado.ErrorEstado, OSError, ficheros.FicheroNoSeguro):
        no_guardado = True
    if no_guardado:
        borrador.fallo("REGISTRO_NO_GUARDADO", doc.ruta.name)
        presencia.informar(Aviso.registro_no_guardado(doc.nombre))


def _cmid_registrado(dir_tiza: Path, curso: int, ruta: str) -> int | None:
    """El cmid que ``publicados.json`` daba a ``ruta`` en ``curso`` antes de publicar, o ``None``.

    Un registro que no se puede leer no impide publicar: ``_registrar_publicado`` ya lo avisa.
    """
    if not estado.ruta_de_registro_valida(ruta):  # es una lectura: la regla de lectura
        return None
    try:
        anterior = estado.cargar_publicados(dir_tiza, curso).get(ruta)
    except (estado.ErrorEstado, OSError, ficheros.FicheroNoSeguro):
        return None
    return anterior.cmid if anterior is not None else None


def _fuente_cargada(doc: Documento) -> bytes:
    """Los bytes del fichero tal como se cargaron. Si cambiaron después, ``FicheroNoSeguro``."""
    bruto = ficheros.leer_bytes_acotado(doc.ruta, estado.MAX_BASE_BYTES)
    if hashlib.sha256(bruto).hexdigest() != doc.sha256_fichero:
        raise ficheros.FicheroNoSeguro("cambiado")
    return bruto


def _guardar_base(
    dir_tiza: Path,
    curso: int,
    doc: Documento,
    cmid: int,
    previo: int | None,
    borrador: informe.Borrador,
) -> None:
    """En un curso real, guarda la base de lo publicado: el fichero fuente y el HTML enviado.

    ``previo`` distinto de ``cmid`` es una actividad recreada: su base vieja se borra después de
    guardar la nueva (si no se puede borrar, se queda: no estorba). Si algo falla, lo publicado
    queda publicado: solo se anota ``BASE_NO_GUARDADA`` (sin aviso al docente, que no nota nada).
    """
    try:
        estado.guardar_base(
            dir_tiza, curso, cmid, _fuente_cargada(doc), contenido.html_para_moodle(doc)
        )
    except (estado.ErrorEstado, OSError, ficheros.FicheroNoSeguro):
        borrador.fallo("BASE_NO_GUARDADA", doc.ruta.name)
        try:  # sin base: mejor eso que la de una publicación anterior, que se tomaría por la última
            estado.olvidar_base(dir_tiza, curso, cmid)
        except (OSError, ficheros.FicheroNoSeguro):
            pass
        return
    if previo is not None and previo != cmid:
        try:
            estado.olvidar_base(dir_tiza, curso, previo)
        except (OSError, ficheros.FicheroNoSeguro):
            pass


def _renovar_base_registrada(
    dir_tiza: Path,
    curso: int,
    ruta: str,
    doc: Documento,
    nueva: str,
    borrador: informe.Borrador,
    presencia: Presencia,
) -> None:
    """``--solo-fechas`` en real: la huella de lo releído pasa a ser la base de ``ruta``.

    La marca queda a None. Si no se puede guardar, las fechas ya están puestas; solo se avisa.
    La entrada ya existe (se lee con la regla de lectura); aquí solo se renueva, no se crea.
    """
    if not estado.ruta_de_registro_valida(ruta):
        return
    try:
        anterior = estado.cargar_publicados(dir_tiza, curso).get(ruta)
        if anterior is None:
            return
        estado.guardar_publicado(
            dir_tiza, curso, ruta, estado.Publicado(anterior.cmid, anterior.tipo, nueva, None)
        )
    except (estado.ErrorEstado, OSError, ficheros.FicheroNoSeguro):
        borrador.fallo("REGISTRO_NO_GUARDADO", doc.ruta.name)
        presencia.informar(Aviso.registro_no_guardado(doc.nombre))


def _nombres_de_vista(documentos: list[Documento]) -> list[str | None]:
    """Un nombre de vista previa distinto por documento.

    ``a/x.md`` y ``b/x.md`` (o ``x.md`` y ``x.html``) darían la misma vista y la segunda pisaría
    a la primera: el docente revisaría una y se publicaría la otra. Con varios documentos, la
    vista lleva delante su número de orden; con uno, el nombre de siempre (``None``).
    """
    if len(documentos) < 2:
        return [None] * len(documentos)
    return [f"{numero:02d}-{doc.ruta.stem}" for numero, doc in enumerate(documentos, 1)]


def publicar_en_cursos(
    aula: AulaVirtual,
    cfg: Config,
    documentos: list[Documento],
    base: Path,
    presencia: Presencia,
    *,
    entorno: str,
    visible: bool | None = None,
    solo_fechas: bool = False,
    verificados: Mapping[str, estado.Verificado] | None = None,
    vigente: Callable[[], bool] | None = None,
    cupo: dict | None = None,
    avisar_en_pruebas: bool = False,
    omitidos: Collection[int] = (),
    nombres: Mapping[int, str] | None = None,
    dir_vistas: Path | None = None,
    debug: bool = False,
) -> dict:
    """Publica ``documentos`` en ``entorno``; devuelve el informe del esquema cerrado.

    ``cfg`` es la configuración capturada al abrir la sesión (o al arrancar la terminal
    directa): alterar ``tiza.toml`` después no puede redirigir la publicación.

    Las diferencias entre la sesión y la terminal directa están documentadas arriba, en
    el docstring del módulo.
    """
    if entorno == "pruebas":
        return _en_pruebas(
            aula,
            cfg,
            documentos,
            base,
            presencia,
            visible=visible,
            solo_fechas=solo_fechas,
            cupo=cupo,
            avisar=avisar_en_pruebas,
            debug=debug,
        )
    return _en_real(
        aula,
        cfg,
        documentos,
        base,
        presencia,
        visible=visible,
        solo_fechas=solo_fechas,
        verificados=verificados,
        vigente=vigente,
        omitidos=omitidos,
        nombres=nombres or {},
        dir_vistas=dir_vistas,
        debug=debug,
    )


def _en_pruebas(
    aula: AulaVirtual,
    cfg: Config,
    documentos: list[Documento],
    base: Path,
    presencia: Presencia,
    *,
    visible: bool | None,
    solo_fechas: bool,
    cupo: dict | None,
    avisar: bool,
    debug: bool,
) -> dict:
    """El curso de pruebas: sin confirmación (la del destino es del llamador), con cupo."""
    comando, entorno = "publicar", "pruebas"
    curso = cfg.cursos.get("pruebas")
    if curso is None:
        return informe.crear(comando, "error", [], [], ["SIN_CURSO_PRUEBAS"], entorno)
    if solo_fechas:
        # Todo o nada antes de tocar el cupo ni la presencia: si algo no se puede cambiar,
        # no se consume cupo por un cambio que no va a ocurrir.
        try:
            estructura = aula.estructura(curso)
        except ErrorPublicacion as exc:
            return informe.crear(comando, "error", [], [], [exc.codigo], entorno, curso)
        codigo = codigo_solo_fechas(estructura, documentos, curso)
        if codigo is not None:
            return informe.crear(comando, "error", [], [], [codigo], entorno, curso)
    # Los de un origen repetido no se publican: ni gastan cupo ni se anuncian.
    validos, _repetidos = _sin_origen_repetido(documentos)
    if cupo is not None:
        if cupo["pruebas"] + len(validos) > MAX_PUBLICACIONES_PRUEBAS:
            return informe.crear(comando, "error", [], [], ["LIMITE_PUBLICACIONES"], entorno, curso)
        cupo["pruebas"] += len(validos)
    if avisar:
        presencia.informar(
            Aviso.publicando_en_pruebas(tuple(DocumentoResumen.de(doc, base) for doc in validos))
        )
    return publicar_con(
        aula,
        entorno,
        curso,
        documentos,
        visible,
        base,
        presencia,
        debug=debug,
        solo_fechas=solo_fechas,
    )


def _preguntar_sobrescribir(
    presencia: Presencia,
    curso: int,
    nombre_curso: str | None,
    cambiadas: tuple[Documento, ...],
    posicion: int,
    total: int,
) -> tuple[frozenset[Path], frozenset[Path]]:
    """(``sobrescribir``, ``no_publicar``) tras preguntar por lo que el docente retocó a mano.

    Solo tras el sí de siempre; sin respuesta o con la petición retirada, es no. Sin ``cambiadas``
    no se pregunta y no hay nada que sobrescribir ni que dejar sin publicar.
    """
    if not cambiadas:
        return frozenset(), frozenset()
    rutas_cambiadas = frozenset(doc.ruta.resolve() for doc in cambiadas)
    if presencia.confirmar_sobrescribir(
        ResumenSobrescribir(
            curso=curso,
            nombre_curso=nombre_curso,
            actividades=tuple(doc.nombre for doc in cambiadas),
            posicion=posicion,
            total=total,
        )
    ):
        return rutas_cambiadas, frozenset()
    return frozenset(), rutas_cambiadas


def _en_real(
    aula: AulaVirtual,
    cfg: Config,
    documentos: list[Documento],
    base: Path,
    presencia: Presencia,
    *,
    visible: bool | None,
    solo_fechas: bool,
    verificados: Mapping[str, estado.Verificado] | None,
    vigente: Callable[[], bool] | None,
    omitidos: Collection[int],
    nombres: Mapping[int, str],
    dir_vistas: Path | None,
    debug: bool,
) -> dict:
    """Publica en cada curso real, en el orden de ``tiza.toml``, con una confirmación por curso.

    Si el docente dice que no a un curso, se omite y se sigue con el siguiente; si un curso
    falla, se para ahí y el informe dice qué cursos quedaron hechos. La puerta de real se
    comprueba una vez (el hash es del documento) y las vistas previas se generan una vez.
    """
    comando, entorno = "publicar", "real"
    reales = cfg.reales
    total = len(reales)
    sin_pruebas = "pruebas" not in cfg.cursos
    unico = reales[0] if total == 1 else None

    def fallo(codigo: str, curso: int | None = unico) -> dict:
        return informe.crear(comando, "error", [], [], [codigo], entorno, curso)

    if not solo_fechas:
        if sin_pruebas:
            if exige_oculto_sin_pruebas(cfg, visible, solo_fechas=solo_fechas):
                return fallo("SOLO_OCULTO_SIN_PRUEBAS")
            visible = False
        elif puerta_real(base, documentos, verificados):
            return fallo("VERIFICACION_PENDIENTE")
    vistas: list[Path | None] = [None] * len(documentos)
    if not solo_fechas and not sin_pruebas:
        # Sin curso de pruebas no hay verificación previa ni vista que enseñar:
        # se compensa publicando solo en oculto y con una confirmación corta.
        raiz_vistas = dir_vistas if dir_vistas is not None else base / rutas.CARPETA_TRABAJO
        try:
            vistas = [
                contenido.previsualizar(doc, raiz_vistas, nombre=nombre)
                for doc, nombre in zip(documentos, _nombres_de_vista(documentos), strict=True)
            ]
        except ErrorContenido as exc:
            return fallo(exc.codigo)
    cal, aviso_calendario = cargar_calendario(base)

    registro: list[tuple[int, int, dict | None]] = []  # (posición, curso, informe o None: omitido)
    for posicion, curso in enumerate(reales, 1):
        if curso in omitidos:
            registro.append((posicion, curso, None))
            continue
        if vigente is not None and posicion > 1 and not vigente():
            presencia.informar(Aviso.peticion_retirada())
            registro.append((posicion, curso, fallo("PETICION_RETIRADA", curso)))
            break
        try:
            estructura = aula.estructura(curso)
        except ErrorPublicacion as exc:
            registro.append((posicion, curso, fallo(exc.codigo, curso)))
            break
        nombre_curso = nombres.get(curso)
        # Lo que se rechaza por su origen sale con su código y no entra en lo que se confirma.
        try:
            huellas, marcas = _guardado_de_copia(base / rutas.CARPETA_TRABAJO, curso, documentos)
        except estado.ErrorEstado as exc:
            registro.append((posicion, curso, fallo(exc.codigo, curso)))
            break
        a_publicar, rechazados_de_siempre = _separar_rechazados(
            documentos, estructura, curso, base, solo_fechas, huellas, marcas
        )
        ids = {id(doc) for doc in a_publicar}
        # Lo que el docente retocó a mano en el aula; se le pregunta tras su sí de siempre.
        cambiadas: tuple[Documento, ...] = ()
        if not a_publicar:
            confirmado = True  # nada que confirmar: publicar_con solo informa de los rechazos
        elif solo_fechas:
            codigo = codigo_solo_fechas(estructura, a_publicar, curso)
            if codigo is not None:
                registro.append((posicion, curso, fallo(codigo, curso)))
                break
            cambiadas = cambiadas_en_el_aula(aula, estructura, a_publicar, curso, solo_fechas=True)
            resumen = resumen_solo_fechas(
                aula,
                curso,
                nombre_curso,
                a_publicar,
                base,
                estructura,
                debug=debug,
                posicion=posicion,
                total=total,
            )
            confirmado = presencia.confirmar_real(resumen)
        elif sin_pruebas:
            cambiadas = cambiadas_en_el_aula(aula, estructura, a_publicar, curso)
            corto = ResumenSinPruebas(
                curso=curso,
                nombre_curso=nombre_curso,
                documentos=tuple(
                    DocumentoBreve(
                        fichero=doc.ruta.name,
                        tipo=doc.tipo,
                        nombre=doc.nombre,
                        existe=estructura.ya_existe(doc, curso),
                        itinerario=itinerario_de(doc, base),
                        borrada=estructura.localizar(doc, curso).borrada,
                    )
                    for doc in a_publicar
                ),
                secciones_nuevas=tuple(estructura.secciones_que_faltan(a_publicar)),
                posicion=posicion,
                total=total,
                movimientos=cambios_de_seccion(estructura, a_publicar, curso),
                nombres=cambios_de_nombre(estructura, a_publicar, curso),
            )
            confirmado = presencia.confirmar_real_sin_pruebas(corto)
        else:
            cambiadas = cambiadas_en_el_aula(aula, estructura, a_publicar, curso)
            resumen = ResumenPublicacion(
                curso=curso,
                nombre_curso=nombre_curso,
                documentos=tuple(
                    DocumentoResumen.de(
                        doc,
                        base,
                        vista,
                        cambios=cambios_de_fechas(
                            aula, estructura, doc, cal, debug=debug, curso=curso
                        ),
                        borrada=estructura.localizar(doc, curso).borrada,
                    )
                    for doc, vista in zip(documentos, vistas, strict=True)
                    if id(doc) in ids
                ),
                secciones_nuevas=tuple(estructura.secciones_que_faltan(a_publicar)),
                visible=visible,
                aviso_calendario=aviso_calendario,
                posicion=posicion,
                total=total,
                movimientos=cambios_de_seccion(estructura, a_publicar, curso),
                nombres=cambios_de_nombre(estructura, a_publicar, curso),
            )
            confirmado = presencia.confirmar_real(resumen)
        if not confirmado:
            registro.append((posicion, curso, None))
            continue
        if vigente is not None and not vigente():
            presencia.informar(Aviso.peticion_retirada())
            registro.append((posicion, curso, fallo("PETICION_RETIRADA", curso)))
            break
        sobrescribir, no_publicar = _preguntar_sobrescribir(
            presencia, curso, nombre_curso, cambiadas, posicion, total
        )
        if cambiadas and vigente is not None and not vigente():
            presencia.informar(Aviso.peticion_retirada())
            registro.append((posicion, curso, fallo("PETICION_RETIRADA", curso)))
            break
        documento = publicar_con(
            aula,
            entorno,
            curso,
            documentos,
            None if solo_fechas else visible,
            base,
            presencia,
            debug=debug,
            solo_fechas=solo_fechas,
            sobrescribir=sobrescribir,
            no_publicar=no_publicar,
        )
        registro.append((posicion, curso, documento))
        if documento["resultado"] != "ok":
            # Un no a sobrescribir es una decisión del docente, no un fallo: los cursos
            # siguientes se publican. Cualquier otro error corta como siempre; y también si el
            # curso no salió ok y no hay ningún error que explique que fue por el no.
            if (
                not no_publicar
                or not documento["errores"]
                or Counter(documento["errores"])
                - _rechazos_por_el_no(
                    documentos,
                    estructura,
                    curso,
                    base,
                    solo_fechas,
                    huellas,
                    marcas,
                    no_publicar,
                    rechazados_de_siempre,
                )
            ):
                break
    return informe_de_cursos(comando, entorno, total, unico, registro)


def cambios_de_seccion(
    estructura: Estructura, documentos: list[Documento], curso: int | None = None
) -> tuple[CambioSeccion, ...]:
    """Las actividades que ``publicar`` movería de sección por haber cambiado su ``seccion:``."""
    cambios: list[CambioSeccion] = []
    for doc in documentos:
        origen = estructura.desde_donde_se_mueve(doc, curso)
        if origen is None:
            continue
        destino = estructura.buscar_seccion(doc.seccion)
        nombre_destino = destino.nombre if destino is not None else str(doc.seccion)
        cambios.append(CambioSeccion(doc.ruta.name, origen, str(nombre_destino)))
    return tuple(cambios)


def _dependencias_invertidas(
    estructura: Estructura,
    documentos: list[Documento],
    base: Path,
    pedidos: dict[str, int],
    finales: dict[int, list[int]],
    curso: int | None = None,
) -> tuple[tuple[str, str], ...]:
    """Pares (fichero, dependencia) donde la actividad queda por encima de la que debe completarse antes."""
    posicion: dict[int, tuple[int, int]] = {}
    for seccion in estructura:
        orden = finales.get(seccion.id) or list(seccion.cmids)
        for indice, cmid in enumerate(orden):
            posicion[cmid] = (seccion.numero, indice)
    invertidas: list[tuple[str, str]] = []
    for doc in documentos:
        propio = pedidos.get(_relativa(doc.ruta, base))
        for fichero in doc.restricciones.completar if doc.restricciones else ():
            dependencia = pedidos.get(fichero)
            if dependencia is None:
                try:
                    cargado = contenido.cargar(base / fichero, raiz=base)
                except ErrorContenido:
                    continue
                modulo = estructura.localizar(cargado, curso).actividad
                dependencia = modulo.cmid if modulo is not None else None
            if propio in posicion and dependencia in posicion:
                assert propio is not None and dependencia is not None
                if posicion[propio] < posicion[dependencia]:
                    invertidas.append((doc.ruta.name, fichero))
    return tuple(invertidas)


def resumen_orden(
    curso: int,
    nombre_curso: str | None,
    estructura: Estructura,
    documentos: list[Documento],
    base: Path,
    *,
    posicion: int = 1,
    total: int = 1,
) -> ResumenOrden | None:
    """Lo que cambiaría ``ordenar`` en este curso, o ``None`` si ya está en el orden pedido.

    Solo lectura. Las actividades que no son de tiza salen con su nombre del aula: es la pantalla
    del docente y necesita ver dónde queda cada cosa. ``ErrorPublicacion`` si algo no se resuelve
    (``ACTIVIDAD_AUSENTE``…): se mira antes de mover nada.
    """
    resolucion = estructura.resolver_orden(documentos, curso)
    publicar._convertir(resolucion.problema)
    grupos = resolucion.grupos
    deseados = [(seccion.id, [actividad.cmid for _, actividad in par]) for seccion, par in grupos]
    cambiadas = {mov.seccion_id for mov in publicar.plan_de_orden(estructura, deseados)}
    if not cambiadas:
        return None
    pedidos = {
        _relativa(doc.ruta, base): actividad.cmid for _, par in grupos for doc, actividad in par
    }
    ficheros_de = {actividad.cmid: doc.ruta.name for _, par in grupos for doc, actividad in par}
    finales: dict[int, list[int]] = {}
    vistas: list[SeccionOrden] = []
    for seccion, par in grupos:
        if seccion.id not in cambiadas:
            continue
        actual = list(seccion.cmids)
        final = publicar.orden_final(actual, [actividad.cmid for _, actividad in par])
        finales[seccion.id] = final
        por_cmid = {actividad.cmid: actividad for actividad in seccion.actividades}
        vistas.append(
            SeccionOrden(
                nombre=str(seccion.nombre),
                actividades=tuple(
                    ActividadOrden(
                        nombre=str(por_cmid[cmid].nombre or ""),
                        tipo=str(por_cmid[cmid].tipo or ""),
                        fichero=ficheros_de.get(cmid),
                    )
                    for cmid in final
                ),
            )
        )
    return ResumenOrden(
        curso=curso,
        nombre_curso=nombre_curso,
        secciones=tuple(vistas),
        dependencias=_dependencias_invertidas(
            estructura, documentos, base, pedidos, finales, curso
        ),
        posicion=posicion,
        total=total,
    )


def ordenar_con(
    aula: AulaVirtual,
    entorno: str,
    curso: int,
    documentos: list[Documento],
    *,
    debug: bool = False,
) -> dict:
    """Con el aula ya abierta: deja las actividades de ``documentos`` en ese orden y lo verifica."""
    borrador = informe.Borrador("ordenar", entorno=entorno, curso=curso)
    borrador.paso("LOGIN")
    try:
        estructura = aula.estructura(curso)
    except ErrorPublicacion as exc:
        borrador.fallo("ESTRUCTURA", exc.codigo)
        borrador.error(exc.codigo)
        depurar(exc, debug)
        return borrador.documento("error")
    try:
        ficheros = publicar.ordenar_documentos(aula, curso, estructura, documentos)
    except ErrorPublicacion as exc:
        borrador.fallo("ORDENAR", exc.detalle or None)
        borrador.error(exc.codigo)
        depurar(exc, debug)
        return borrador.documento("error")
    for fichero in ficheros:
        borrador.fichero(replace(fichero, curso=curso))
    borrador.paso("ORDENAR", detalle=f"{len(ficheros)} ficheros")
    return borrador.documento()


def ordenar_en_cursos(
    aula: AulaVirtual,
    cfg: Config,
    documentos: list[Documento],
    base: Path,
    presencia: Presencia,
    *,
    entorno: str,
    vigente: Callable[[], bool] | None = None,
    cupo: dict | None = None,
    avisar_en_pruebas: bool = False,
    omitidos: Collection[int] = (),
    nombres: Mapping[int, str] | None = None,
    debug: bool = False,
) -> dict:
    """Ordena en ``entorno``; mismo reparto de papeles que :func:`publicar_en_cursos`.

    En pruebas gasta 1 del cupo. En real va a todos los cursos reales, con una confirmación por
    curso y parada en el primer fallo; ordenar no cambia contenido ni visibilidad, así que no
    pasa por la puerta de pruebas ni exige «oculto» sin curso de pruebas.
    """
    comando = "ordenar"
    if entorno == "pruebas":
        curso = cfg.cursos.get("pruebas")
        if curso is None:
            return informe.crear(comando, "error", [], [], ["SIN_CURSO_PRUEBAS"], entorno)
        if cupo is not None:
            if cupo["pruebas"] + 1 > MAX_PUBLICACIONES_PRUEBAS:
                return informe.crear(
                    comando, "error", [], [], ["LIMITE_PUBLICACIONES"], entorno, curso
                )
            cupo["pruebas"] += 1
        if avisar_en_pruebas:
            presencia.informar(
                Aviso.ordenando_en_pruebas(
                    tuple(DocumentoBreve(doc.ruta.name, doc.tipo, doc.nombre) for doc in documentos)
                )
            )
        return ordenar_con(aula, entorno, curso, documentos, debug=debug)

    reales = cfg.reales
    total = len(reales)
    unico = reales[0] if total == 1 else None
    nombres = nombres or {}

    def fallo(codigo: str, curso: int | None = unico) -> dict:
        return informe.crear(comando, "error", [], [], [codigo], entorno, curso)

    registro: list[tuple[int, int, dict | None]] = []
    for posicion, curso in enumerate(reales, 1):
        if curso in omitidos:
            registro.append((posicion, curso, None))
            continue
        if vigente is not None and posicion > 1 and not vigente():
            presencia.informar(Aviso.peticion_retirada())
            registro.append((posicion, curso, fallo("PETICION_RETIRADA", curso)))
            break
        try:
            estructura = aula.estructura(curso)
            resumen = resumen_orden(
                curso,
                nombres.get(curso),
                estructura,
                documentos,
                base,
                posicion=posicion,
                total=total,
            )
        except ErrorPublicacion as exc:
            # Cada curso resuelve lo suyo antes de mover nada en él (ACTIVIDAD_AUSENTE…).
            registro.append((posicion, curso, fallo(exc.codigo, curso)))
            break
        if resumen is not None:
            if not presencia.confirmar_orden(resumen):
                registro.append((posicion, curso, None))
                continue
            if vigente is not None and not vigente():
                presencia.informar(Aviso.peticion_retirada())
                registro.append((posicion, curso, fallo("PETICION_RETIRADA", curso)))
                break
        # Sin cambios no hay nada que confirmar: se informa de ``sin_cambios`` sin tocar el aula.
        documento = ordenar_con(aula, entorno, curso, documentos, debug=debug)
        registro.append((posicion, curso, documento))
        if documento["resultado"] != "ok":
            break
    return informe_de_cursos(comando, entorno, total, unico, registro)


# --------------------------------------------------------------------------- #
# El calificador: montarlo desde el esquema
# --------------------------------------------------------------------------- #


def _ruta_de(doc: Documento, base: Path) -> str:
    """La ruta del documento en la carpeta, en POSIX: la misma clave que usa ``deseado``."""
    try:
        return doc.ruta.relative_to(base).as_posix()
    except ValueError:
        return doc.ruta.as_posix()


def _cmids_de(
    estructura: Estructura, documentos: list[Documento], curso: int, base: Path
) -> dict[str, int]:
    """El cmid de cada actividad que ya está en el aula, por ruta; las que faltan no salen.

    Se encuentran como en ``ordenar`` (``origen`` en su curso, o sección, tipo y nombre).
    ``ACTIVIDAD_AMBIGUA`` si dos ficheros apuntan a la misma actividad o una se repite: colocar
    la equivocada cambiaría una nota sin que nadie lo viera.
    """
    cmids: dict[str, int] = {}
    vistos: set[int] = set()
    for doc in documentos:
        ruta = _ruta_de(doc, base)
        loc = estructura.localizar(doc, curso)
        if loc.problema == "ORIGEN_NO_ENCONTRADO":
            continue  # ya no está en el aula: es pendiente
        # ACTIVIDAD_AMBIGUA (o cualquier otro problema futuro): el registro y el nombre
        # apuntan a actividades distintas.
        publicar._convertir((loc.problema, doc.ruta.name) if loc.problema is not None else None)
        modulo = loc.actividad
        if modulo is None:
            continue
        cmid = modulo.cmid
        if loc.varios or cmid in vistos:
            raise ErrorPublicacion("ACTIVIDAD_AMBIGUA", ruta)
        vistos.add(cmid)
        cmids[ruta] = cmid
    return cmids


def preparar_calificador(
    aula: AulaVirtual,
    curso: int,
    esquema: Esquema,
    documentos: list[Documento],
    dir_tiza: Path,
) -> PlanCalificador:
    """Lee el curso y calcula qué hay que hacer en su calificador. No escribe nada en el aula.

    ``ErrorPublicacion`` si el aula no deja leer, ``ErrorCalificacion`` si las actividades no
    cuadran con el esquema y ``ErrorEstado`` si ``.tiza/calificador.json`` no vale.
    """
    base = Path(dir_tiza).parent
    huellas = estado.cargar_huellas(dir_tiza, curso)
    contados = [doc for doc in documentos if doc.evalua is not None]
    cmids = _cmids_de(aula.estructura(curso), contados, curso, base)
    actual = aula.calificador(curso)
    anterior = rc.hay_anterior(actual)
    deseado = calcular_deseado(esquema, documentos, anterior, base)
    return PlanCalificador(
        curso=curso,
        aula_antes=actual,
        deseado=deseado,
        reconciliacion=rc.reconciliar(deseado, actual, huellas, cmids),
        cmids=cmids,
        huellas=huellas,
        documentos=tuple(contados),
        base=base,
    )


def _aviso_de(codigo: str, clave: str, plan: PlanCalificador) -> Aviso | None:
    """El aviso de la reconciliación en el tipo que sabe contar la presencia (``None``: no cuenta)."""
    nombres = {n.idnumber: n.nombre for n in plan.aula_antes.nodos if n.idnumber}
    if codigo == "ACTIVIDAD_EN_EVALUACION_CERRADA" and clave.startswith("TZ_M_"):
        clave = next((n.nombre for n in plan.deseado.nodos if n.idnumber == clave), clave)
    nombre = "el total del curso" if clave == rc.CURSO else nombres.get(clave, clave)
    if codigo == "ACTIVIDAD_PENDIENTE":
        return Aviso.actividad_pendiente(clave)
    if codigo == "ACTIVIDAD_EN_EVALUACION_CERRADA":
        return Aviso.actividad_en_evaluacion_cerrada(clave)
    if codigo == "CAMBIADO_A_MANO":
        return Aviso.cambiado_a_mano(nombre)
    if codigo == "EVALUACION_CERRADA_EN_EL_AULA":
        return Aviso.evaluacion_cerrada_en_el_aula(nombre)
    if codigo == "ELEMENTO_CON_NOTAS_QUITADO":
        return Aviso.elemento_con_notas_quitado(nombre)
    if codigo == "ELEMENTO_SIN_ACTIVIDADES":
        return Aviso.elemento_sin_actividades(clave)
    if codigo == "CRITERIOS_SIN_PESO":
        return Aviso.criterios_sin_peso(clave)
    return None  # TOTAL_AJENO_BLOQUEADO ya sale en «se bloquean los totales de…»


def _actividades_de_hojas(
    elemento: Elemento, plan: PlanCalificador, esquema: Esquema
) -> tuple[tuple[str, float], ...]:
    """Las actividades (ficheros e instrumentos) de las hojas de un elemento, con su peso."""
    hojas = {c.id for c in elemento.criterios} or {elemento.id}
    ficheros = tuple(
        (doc.nombre, peso)
        for doc in plan.documentos
        for id_, peso in doc.evalua or ()
        if id_ in hojas and peso > 0
    )
    instrumentos = tuple(
        (i.nombre, peso)
        for i in esquema.instrumentos
        for id_, peso in i.evalua
        if id_ in hojas and peso > 0
    )
    return ficheros + instrumentos


def resumen_calificador(
    plan: PlanCalificador,
    esquema: Esquema,
    nombre_curso: str | None,
    *,
    posicion: int = 1,
    total: int = 1,
) -> ResumenCalificador:
    """Lo que enseña la confirmación de ``tiza calificador`` en un curso real.

    Solo lectura. Los nombres de las actividades salen de los ficheros de la carpeta; los de
    totales ajenos y evaluaciones, del aula, y solo los ve el docente.
    """
    nombres = {_ruta_de(doc, plan.base): doc.nombre for doc in plan.documentos}
    operaciones = plan.reconciliacion.operaciones
    colocar = [op for op in operaciones if op.tipo == "colocar"]
    lineas = tuple(
        ElementoCalificador(
            e.id,
            e.peso if esquema.final.de == "elementos" else None,
            _actividades_de_hojas(e, plan, esquema),
        )
        for e in esquema.elementos
    )
    en_el_aula = {n.idnumber: n for n in plan.aula_antes.nodos if n.idnumber}
    notas = tuple(
        ev.nombre
        for n, ev in enumerate(esquema.evaluaciones, 1)
        if not ev.cerrada
        and (aula_ev := en_el_aula.get(f"TZ_V_{n}")) is not None
        and aula_ev.tiene_notas
        and not aula_ev.bloqueado
    )
    avisos = [
        aviso
        for codigo, clave in (*plan.reconciliacion.avisos, *plan.deseado.avisos)
        if (aviso := _aviso_de(codigo, clave, plan)) is not None
    ]

    def nombre_de(op: rc.Operacion) -> str:
        return nombres.get(op.ruta or "", op.ruta or "")

    nombre_en_el_aula = {n.eid: n.nombre or n.idnumber for n in plan.aula_antes.nodos}
    total_curso = next(
        (
            "porcentaje" if op.formula is None else "nota_final"
            for op in operaciones
            if op.tipo == "fijar_total_curso"
        ),
        None,
    )
    tope = esquema.final.tope

    return ResumenCalificador(
        curso=plan.curso,
        nombre_curso=nombre_curso,
        lineas_esquema=lineas,
        mueve=tuple(dict.fromkeys(nombre_de(op) for op in colocar)),
        bloquea=tuple(
            op.nombre or op.idnumber or "" for op in operaciones if op.tipo == "bloquear_ajeno"
        ),
        ids_nuevos=tuple(dict.fromkeys(nombre_de(op) for op in colocar if op.poner_idnumber)),
        cerradas=tuple(
            EvaluacionCerrada(
                ev.nombre, ev.secciones, f"TZ_V_{n}" in plan.reconciliacion.por_cerrar
            )
            for n, ev in enumerate(esquema.evaluaciones, 1)
            if ev.cerrada
        ),
        avisos=tuple(avisos),
        casillas=tuple(
            op.nombre or op.idnumber or ""
            for op in operaciones
            if op.tipo == "crear_calculado" and (op.idnumber or "").startswith("TZ_M_")
        ),
        posicion=posicion,
        total=total,
        anterior=plan.reconciliacion.anterior,
        notas_cambian=notas,
        total_curso=total_curso,
        tope=(tope.si_alguno_menor_que, tope.maximo) if tope is not None else None,
        quita=tuple(
            nombre_en_el_aula.get(op.eid or "", op.idnumber or "")
            for op in operaciones
            if op.tipo == "borrar"
        ),
    )


def _huellas_a_guardar(final: CalificadorAula, plan: PlanCalificador) -> dict[str, str]:
    """Las huellas de lo que quedó, salvo lo que el docente cambió a mano: eso conserva la de antes.

    Si se guardara el estado cambiado, la vez siguiente tiza lo tomaría por lo que montó y lo
    pisaría; con la huella vieja se sigue respetando (y avisando) hasta que el docente lo deje
    como estaba o lo borre del aula.
    """
    nuevas = rc.huellas_de(final, plan.cmids)
    for clave in plan.reconciliacion.a_mano:
        if clave in plan.huellas:
            nuevas[clave] = plan.huellas[clave]
    return nuevas


def _huellas_tras_fallo(
    final: CalificadorAula, plan: PlanCalificador, hechas: list[rc.Operacion]
) -> dict[str, str]:
    """Las huellas tras un fallo a medias: las de lo que tocaron las operaciones ya hechas.

    Sin ellas, la siguiente ejecución vería lo que tiza ya cambió como «cambiado a mano». Lo demás
    conserva su huella de antes, y lo que el docente cambió a mano también.
    """
    ahora = rc.huellas_de(final, plan.cmids)
    idnumber_de = {n.eid: n.idnumber for n in final.nodos if n.idnumber}
    tocadas: set[str] = set()
    for op in hechas:
        if op.tipo == "fijar_total_curso":
            tocadas.add(rc.CURSO)
        if op.idnumber:
            tocadas.add(op.idnumber)
        if op.eid and op.eid in idnumber_de:
            tocadas.add(idnumber_de[op.eid])
    nuevas = {
        k: v for k, v in plan.huellas.items() if k not in tocadas - plan.reconciliacion.a_mano
    }
    for clave in tocadas - plan.reconciliacion.a_mano:
        if clave in ahora:
            nuevas[clave] = ahora[clave]
        elif clave in plan.huellas:
            nuevas[clave] = plan.huellas[clave]
    return nuevas


def _ajustar(
    aula: AulaVirtual,
    curso: int,
    plan: PlanCalificador,
    final: CalificadorAula,
    segundas: list[Ejecucion],
) -> CalificadorAula:
    """La segunda pasada sobre el aula releída: repite los ajustes hasta que no quede ninguno.

    Moodle reescala los pesos de los hermanos al guardar cada uno, así que fijarlos de una vez
    no basta: se repite (con tope) hasta que el aula coincide con lo deseado. Los repasos no
    bloquean nada (un total bloqueado ya no admite ajustes): los cierres van al final, con todo
    estable. Cada ejecución se añade a ``segundas`` y se devuelve el aula releída.
    """
    rec = plan.reconciliacion

    def ajustes_de(leida: CalificadorAula, cierres: frozenset[str]) -> tuple[rc.Operacion, ...]:
        return rc.pasada2(
            plan.deseado,
            leida,
            plan.huellas,
            plan.cmids,
            a_mano=rec.a_mano,
            por_cerrar=cierres,
        )

    def ejecutar(leida: CalificadorAula, ajustes: tuple[rc.Operacion, ...]) -> CalificadorAula:
        segunda = Ejecucion(aula, curso, leida.decimal)
        segundas.append(segunda)
        segunda.ejecutar(ajustes, tolerar_formulas=False)
        return aula.calificador(curso, segunda.tocados)

    for _ in range(MAX_PASADAS_DE_AJUSTE):
        ajustes = ajustes_de(final, frozenset())
        if not ajustes:
            break
        final = ejecutar(final, ajustes)
    cierres = ajustes_de(final, rec.por_cerrar)
    return ejecutar(final, cierres) if cierres else final


def calificador_con(
    aula: AulaVirtual,
    entorno: str,
    curso: int,
    esquema: Esquema,
    documentos: list[Documento],
    dir_tiza: Path,
    *,
    plan: PlanCalificador | None = None,
    debug: bool = False,
) -> dict:
    """Con el aula ya abierta: monta el calificador de ``curso`` y devuelve el informe.

    Flujo: ``calificador(curso)`` → ``hay_anterior`` → ``deseado`` → ``reconciliar`` (todo eso es
    ``preparar_calificador``; con ``plan`` ya se hizo y es lo que vio el docente al confirmar) →
    las operaciones en orden → releer → ``pasada2`` (repetida, con tope, mientras haya pesos o
    fórmulas que ajustar: Moodle reescala los pesos de los hermanos al guardar cada uno) y, ya
    estable, el bloqueo de las evaluaciones cerradas → guardar las huellas. Las relecturas abren solo los formularios de lo que se tocó. Si falla un ``bloquear_ajeno`` no se ejecuta nada más en el curso
    (``BLOQUEO_FALLIDO``). Cualquier otro fallo para en seco, y se guardan las huellas de lo ya
    hecho para que repetir el comando converja sin tomarlo por cambios a mano.
    """
    borrador = informe.Borrador("calificador", entorno=entorno, curso=curso)
    borrador.paso("LOGIN")
    dir_tiza = Path(dir_tiza)
    try:
        plan = plan or preparar_calificador(aula, curso, esquema, documentos, dir_tiza)
    except (ErrorPublicacion, ErrorCalificacion, ErrorEstado) as exc:
        borrador.fallo("CALIFICADOR", exc.codigo)
        borrador.error(exc.codigo)
        depurar(exc, debug)
        return borrador.documento("error")
    rec = plan.reconciliacion
    primera = Ejecucion(aula, curso, plan.aula_antes.decimal)
    segundas: list[Ejecucion] = []
    final = plan.aula_antes
    try:
        if rec.hay_trabajo:
            primera.ejecutar(rec.operaciones, tolerar_formulas=True)
            final = aula.calificador(curso, primera.tocados)
            final = _ajustar(aula, curso, plan, final, segundas)
    except ErrorPublicacion as exc:
        hechas = len(primera.hechas) + sum(len(s.hechas) for s in segundas)
        if exc.codigo == "BLOQUEO_FALLIDO":
            borrador.fallo("CALIFICADOR_BLOQUEAR", exc.detalle or None)
        else:
            borrador.fallo("CALIFICADOR", f"{exc.codigo} tras {hechas} cambios")
        borrador.error(exc.codigo)
        depurar(exc, debug)
        hechas_antes = [*primera.hechas, *(op for s in segundas for op in s.hechas)]
        if hechas_antes:
            try:
                estado.guardar_huellas(
                    dir_tiza,
                    curso,
                    _huellas_tras_fallo(aula.calificador(curso), plan, hechas_antes),
                )
            except (ErrorPublicacion, ErrorEstado, OSError):
                borrador.fallo("HUELLA_NO_GUARDADA", "calificador")
        return borrador.documento("error")

    hechas_todas = [*primera.hechas, *(op for s in segundas for op in s.hechas)]
    borrador.paso(
        "CALIFICADOR", detalle=f"{len(hechas_todas)} cambios" if hechas_todas else "sin cambios"
    )
    bloqueos = sum(1 for op in hechas_todas if op.tipo in TIPOS_DE_BLOQUEO)
    if bloqueos:
        borrador.paso("CALIFICADOR_BLOQUEAR", detalle=str(bloqueos))
    colocadas = {op.ruta for op in hechas_todas if op.tipo == "colocar"}
    if colocadas:
        borrador.paso("CALIFICADOR_COLOCAR", detalle=str(len(colocadas)))
    avisos = [*rec.avisos, *plan.deseado.avisos]
    for codigo, cuantos in Counter(codigo for codigo, _ in avisos).items():
        borrador.paso(codigo, detalle=str(cuantos))
    pendientes = {clave for codigo, clave in rec.avisos if codigo == "ACTIVIDAD_PENDIENTE"}
    for doc in plan.documentos:
        ruta = _ruta_de(doc, plan.base)
        if ruta not in plan.cmids or ruta in pendientes:
            accion = "pendiente"
        elif ruta in colocadas:
            accion = "colocada"
        elif ruta in rec.sin_colocar:
            accion = "sin_colocar"
        else:
            accion = "ya_estaba"
        try:
            borrador.fichero(
                informe.Fichero(
                    nombre=ruta,
                    tipo=doc.tipo,
                    cmid=plan.cmids.get(ruta),
                    accion=accion,
                    curso=curso,
                )
            )
        except informe.ErrorInforme:  # un nombre de fichero que el informe no admite
            continue
    nuevas = _huellas_a_guardar(final, plan)
    if nuevas != plan.huellas:
        try:
            estado.guardar_huellas(dir_tiza, curso, nuevas)
        except (ErrorEstado, OSError):
            borrador.fallo("HUELLA_NO_GUARDADA", "calificador")
    return borrador.documento()


def calificador_en_cursos(
    aula: AulaVirtual,
    cfg: Config,
    esquema: Esquema,
    documentos: list[Documento],
    base: Path,
    presencia: Presencia,
    *,
    entorno: str,
    nombre_esquema: str,
    vigente: Callable[[], bool] | None = None,
    cupo: dict | None = None,
    avisar_en_pruebas: bool = False,
    nombres: Mapping[int, str] | None = None,
    debug: bool = False,
) -> dict:
    """Monta el calificador en ``entorno``; mismo reparto de papeles que :func:`ordenar_en_cursos`.

    En pruebas gasta 1 del cupo. En real va a todos los cursos reales, con una confirmación por
    curso (con todo lo que va a pasar en llano) y parada en el primer fallo; sin puerta de
    pruebas, como ``ordenar``. Si en un curso no hay nada que cambiar no se pregunta.
    """
    comando = "calificador"
    dir_tiza = Path(base) / rutas.CARPETA_TRABAJO
    if entorno == "pruebas":
        curso = cfg.cursos.get("pruebas")
        if curso is None:
            return informe.crear(comando, "error", [], [], ["SIN_CURSO_PRUEBAS"], entorno)
        if cupo is not None:
            if cupo["pruebas"] + 1 > MAX_PUBLICACIONES_PRUEBAS:
                return informe.crear(
                    comando, "error", [], [], ["LIMITE_PUBLICACIONES"], entorno, curso
                )
            cupo["pruebas"] += 1
        if avisar_en_pruebas:
            presencia.informar(Aviso.calificando_en_pruebas(nombre_esquema))
        return calificador_con(aula, entorno, curso, esquema, documentos, dir_tiza, debug=debug)

    reales = cfg.reales
    total = len(reales)
    unico = reales[0] if total == 1 else None
    nombres = nombres or {}

    def fallo(codigo: str, curso: int | None = unico) -> dict:
        return informe.crear(comando, "error", [], [], [codigo], entorno, curso)

    registro: list[tuple[int, int, dict | None]] = []
    for posicion, curso in enumerate(reales, 1):
        if vigente is not None and posicion > 1 and not vigente():
            presencia.informar(Aviso.peticion_retirada())
            registro.append((posicion, curso, fallo("PETICION_RETIRADA", curso)))
            break
        try:
            plan = preparar_calificador(aula, curso, esquema, documentos, dir_tiza)
        except (ErrorPublicacion, ErrorCalificacion, ErrorEstado) as exc:
            # Cada curso se lee entero antes de escribir nada en él (y antes de preguntar).
            registro.append((posicion, curso, fallo(exc.codigo, curso)))
            break
        if plan.reconciliacion.hay_trabajo:
            resumen = resumen_calificador(
                plan, esquema, nombres.get(curso), posicion=posicion, total=total
            )
            if not presencia.confirmar_calificador(resumen):
                registro.append((posicion, curso, None))
                continue
            if vigente is not None and not vigente():
                presencia.informar(Aviso.peticion_retirada())
                registro.append((posicion, curso, fallo("PETICION_RETIRADA", curso)))
                break
        # Sin operaciones no hay nada que confirmar: se informa de que no había nada que hacer.
        documento = calificador_con(
            aula, entorno, curso, esquema, documentos, dir_tiza, plan=plan, debug=debug
        )
        registro.append((posicion, curso, documento))
        if documento["resultado"] != "ok":
            break
    return informe_de_cursos(comando, entorno, total, unico, registro)


def informe_de_cursos(
    comando: str,
    entorno: str,
    total: int,
    unico: int | None,
    registro: list[tuple[int, int, dict | None]],
) -> dict:
    """Un informe con lo que pasó en cada curso real; con un solo curso, el de siempre."""
    if total == 1:
        informe_unico = registro[0][2]
        if informe_unico is None:
            return informe.crear(comando, "abortado", [], [], ["ABORTADO"], entorno, unico)
        return informe_unico
    borrador = informe.Borrador(comando, entorno=entorno)
    login = any(
        paso["codigo"] == "LOGIN"
        for _, _, doc in registro
        if doc is not None
        for paso in doc["pasos"]
    )
    if login:
        borrador.paso("LOGIN")
    publicados = 0
    for posicion, curso, doc in registro:
        if doc is None:
            borrador.paso("CURSO_OMITIDO", detalle=str(curso))
            continue
        fallido = doc["resultado"] != "ok"
        borrador.paso("CURSO", "fallo" if fallido else "ok", f"{posicion} de {total}: {curso}")
        borrador.agregar(doc, excluir={"LOGIN"})
        if fallido:
            continue
        publicados += 1
    if borrador.errores:
        return borrador.documento("error")
    if publicados == 0:
        borrador.error("ABORTADO")
        return borrador.documento("abortado")
    return borrador.documento()


def _curso_de_copia(cfg: Config, nombre: str) -> tuple[str, int]:
    """(entorno, id) del curso que pide el agente: ``pruebas``, ``real`` o el id de uno de tiza.toml.

    ``real`` solo vale si hay un único curso real; con varios, hay que decir cuál por su id.
    """
    pruebas = cfg.cursos.get("pruebas")
    if nombre == "pruebas":
        if pruebas is None:
            raise ErrorPublicacion("SIN_CURSO_PRUEBAS")
        return "pruebas", pruebas
    if nombre == "real":
        if not cfg.reales:
            raise ErrorPublicacion("CURSO_NO_CONFIGURADO")
        if len(cfg.reales) > 1:
            raise ErrorPublicacion("CURSO_AMBIGUO")
        return "real", cfg.reales[0]
    if re.fullmatch(r"[1-9][0-9]{0,17}", nombre):
        curso = int(nombre)
        if curso == pruebas:
            return "pruebas", curso
        if curso in cfg.reales:
            return "real", curso
    raise ErrorPublicacion("CURSO_NO_CONFIGURADO")


def _quitar(ruta: Path) -> None:
    try:
        ruta.unlink()
    except OSError:
        pass


def _borrar_del_aula(
    aula: AulaVirtual, nombre: str, curso: int, presencia: Presencia, debug: bool
) -> bool:
    """Quita la copia de la zona de copias del docente; si no puede, se lo dice y devuelve falso."""
    try:
        aula.borrar_copia(nombre, curso)
    except ErrorPublicacion as exc:
        depurar(exc, debug)
        presencia.informar(Aviso.copia_queda_en_el_aula())
        return False
    return True


class _FalloDeCopia(Exception):
    """Una copia que no salió: el código, la causa (para depurar) y si quedó en el aula."""

    def __init__(self, codigo: str, causa: BaseException | None, queda_en_el_aula: bool) -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.causa = causa
        self.queda_en_el_aula = queda_en_el_aula


def _traer_copia(
    aula: AulaVirtual,
    curso_id: int,
    curso: str,
    dir_tiza: Path,
    temporal: Path,
    presencia: Presencia,
    debug: bool,
    cmid: int | None = None,
) -> tuple[informe.CopiaHecha, int]:
    """Hace una copia (del curso, o de la actividad ``cmid``), la guarda y la quita del aula.

    Lo común de ``tiza copia``: descarga a ``temporal``, la abre con :func:`tiza.copia.abrir_copia`
    (una con usuarios, o que no vale, se borra del aula y da su código), la deja en
    ``.tiza/copias/`` sin sobrescribir nada y la borra de la zona de copias del docente (si no
    puede, avisa y ``borrada_del_aula`` va a falso). Con ``cmid`` exige que traiga exactamente esa
    actividad (``COPIA_NO_VALIDA`` si no). Devuelve la copia hecha y los bytes descargados; si
    falla, ``_FalloDeCopia`` (la copia ya no está en el aula, o ``queda_en_el_aula``). Quita
    ``temporal`` siempre.
    """
    from .copia import MAX_COPIA, ErrorCopia, abrir_copia  # carga diferida: lxml

    nombre_en_el_aula: str | None = None

    def fallo(codigo: str, causa: BaseException | None = None) -> _FalloDeCopia:
        nonlocal nombre_en_el_aula
        queda = bool(getattr(causa, "queda_en_el_aula", False))
        if nombre_en_el_aula is not None:
            # La copia ya estaba en el aula y no se queda: tampoco con sus datos en la zona del docente.
            queda = not _borrar_del_aula(aula, nombre_en_el_aula, curso_id, presencia, debug)
            nombre_en_el_aula = None
        elif queda:
            presencia.informar(Aviso.copia_queda_en_el_aula())
        return _FalloDeCopia(codigo, causa, queda)

    try:
        try:
            if cmid is None:
                hecha = aula.hacer_copia(curso_id, temporal, MAX_COPIA)
            else:
                hecha = aula.hacer_copia(curso_id, temporal, MAX_COPIA, cmid)
        except ErrorPublicacion as exc:
            raise fallo(exc.codigo, exc) from None
        except OSError as exc:
            raise fallo("COPIA_NO_ESCRIBIBLE", exc) from None
        nombre_en_el_aula = hecha.nombre
        try:
            contenido_de_la_copia = abrir_copia(temporal)
        except ErrorCopia as exc:
            raise fallo(exc.codigo, exc) from None
        if cmid is not None and [a.cmid for a in contenido_de_la_copia.actividades] != [cmid]:
            raise fallo("COPIA_NO_VALIDA")  # no trae exactamente la actividad pedida
        try:
            destino = estado.reservar_copia(dir_tiza, curso, datetime.now(), temporal, cmid)
        except OSError as exc:
            raise fallo("COPIA_NO_ESCRIBIBLE", exc) from None
        borrada = _borrar_del_aula(aula, hecha.nombre, curso_id, presencia, debug)
        nombre_en_el_aula = None
        return (
            informe.CopiaHecha(
                curso=curso,
                fichero=f"{rutas.CARPETA_TRABAJO}/{estado.CARPETA_COPIAS}/{destino.name}",
                bytes=hecha.bytes,
                actividades=Counter(a.modulo[:30] for a in contenido_de_la_copia.actividades),
                borrada_del_aula=borrada,
                cmid=cmid,
            ),
            hecha.bytes,
        )
    finally:
        _quitar(temporal)  # tras renombrarla ya no existe; si algo falló, no queda a medias
        if nombre_en_el_aula is not None:
            # Un fallo inesperado: que la copia no se quede en la zona del docente.
            _borrar_del_aula(aula, nombre_en_el_aula, curso_id, presencia, debug)


def _anotar_copia(borrador: informe.Borrador, hecha: informe.CopiaHecha, bytes_: int) -> None:
    """Los pasos y la copia de una copia hecha (los comparten la del curso y las de actividad)."""
    borrador.paso("COPIAR", detalle=f"{bytes_} bytes")
    if hecha.borrada_del_aula:
        borrador.paso("BORRAR_COPIA")
    else:
        borrador.fallo("BORRAR_COPIA", "COPIA_QUEDA_EN_EL_AULA")
    borrador.copia(hecha)


def _anotar_fallo_de_copia(borrador: informe.Borrador, fallo: _FalloDeCopia, debug: bool) -> dict:
    borrador.fallo("COPIAR", fallo.codigo)
    if fallo.queda_en_el_aula:
        borrador.fallo("BORRAR_COPIA", "COPIA_QUEDA_EN_EL_AULA")
    borrador.error(fallo.codigo)
    if fallo.causa is not None:
        depurar(fallo.causa, debug)
    return borrador.documento("error")


def copiar_curso(
    aula: AulaVirtual,
    cfg: Config,
    curso: str,
    base: Path,
    presencia: Presencia,
    cupo: dict,
    *,
    nombres: Mapping[int, str] | None = None,
    vigente: Callable[[], bool] | None = None,
    debug: bool = False,
) -> dict:
    """``tiza copia``: la sesión hace una copia del curso sin datos de usuario y la deja en
    ``.tiza/copias/``.

    ``curso``: ``pruebas``, ``real`` o el id de un curso de ``cfg``. Pide al docente una
    confirmación por petición; con un no, ``COPIA_RECHAZADA`` y no se toca nada. Gasta 1 del
    cupo de copias (``CUPO_COPIAS`` por sesión). La copia se descarga a un temporal, se abre
    con :func:`tiza.copia.abrir_copia` (una copia con usuarios, o que no vale, se borra y da
    su código) y solo entonces recibe su nombre ``<curso>-<AAAAMMDD-HHMM>.mbz``, sin
    sobrescribir nada. Después se borra de la zona de copias del docente en Moodle; si no se
    puede, se avisa y ``borrada_del_aula`` va a falso. El informe lleva solo códigos y números.
    """
    comando = "copia"
    try:
        entorno, curso_id = _curso_de_copia(cfg, curso)
    except ErrorPublicacion as exc:
        return informe.crear(comando, "error", [], [], [exc.codigo])

    def fallo(codigo: str, resultado: str = "error") -> dict:
        return informe.crear(comando, resultado, [], [], [codigo], entorno, curso_id)

    if cupo.setdefault("copias", 0) >= CUPO_COPIAS:
        return fallo("CUPO_COPIAS")
    resumen = ResumenCopia(curso_id, (nombres or {}).get(curso_id), entorno)
    if not presencia.confirmar_copia(resumen):
        return fallo("COPIA_RECHAZADA", "abortado")
    if vigente is not None and not vigente():
        presencia.informar(Aviso.peticion_retirada())
        return fallo("PETICION_RETIRADA")
    cupo["copias"] += 1
    dir_tiza = Path(base) / rutas.CARPETA_TRABAJO
    try:
        temporal = estado.temporal_de_copia(dir_tiza)
    except OSError:
        return fallo("COPIA_NO_ESCRIBIBLE")

    borrador = informe.Borrador(comando, entorno=entorno, curso=curso_id)
    borrador.paso("LOGIN")
    try:
        hecha, bytes_ = _traer_copia(aula, curso_id, curso, dir_tiza, temporal, presencia, debug)
    except _FalloDeCopia as exc:
        return _anotar_fallo_de_copia(borrador, exc, debug)
    _anotar_copia(borrador, hecha, bytes_)
    return borrador.documento()


def copiar_actividades(
    aula: AulaVirtual,
    cfg: Config,
    curso: str,
    ficheros: Sequence[str],
    base: Path,
    presencia: Presencia,
    cupo: dict,
    *,
    nombres: Mapping[int, str] | None = None,
    vigente: Callable[[], bool] | None = None,
    debug: bool = False,
) -> dict:
    """``tiza copia <curso> --actividad <fichero>…``: una copia por actividad, para juntar cambios.

    Solo cursos reales (``COPIA_DE_ACTIVIDAD_SOLO_REAL``). Cada fichero (dentro de ``base``) se
    localiza en el curso por el registro de lo publicado o por su ``origen``
    (:func:`estructura.localizar`); el agente nunca da cmids. Todo o nada antes de confirmar: si un
    fichero no se halla así (``ACTIVIDAD_SIN_REGISTRO``) o no caben todas en el cupo propio
    (``CUPO_COPIAS_ACTIVIDAD`` por sesión, 1 por actividad), no se pide nada. Una confirmación
    por petición con los nombres; con un no, ``COPIA_RECHAZADA``. Luego, una copia por actividad
    (en orden): si una falla se para ahí y las ya hechas quedan y salen en el informe.
    """
    comando = "copia"
    try:
        entorno, curso_id = _curso_de_copia(cfg, curso)
    except ErrorPublicacion as exc:
        return informe.crear(comando, "error", [], [], [exc.codigo])

    def fallo(codigo: str, resultado: str = "error", ficheros: Sequence = ()) -> dict:
        return informe.crear(comando, resultado, [], ficheros, [codigo], entorno, curso_id)

    if entorno != "real":
        return fallo("COPIA_DE_ACTIVIDAD_SOLO_REAL")
    if not ficheros:
        return fallo("PETICION_INVALIDA")
    # Sin repetir la ruta; dos ficheros de la misma actividad (mismo cmid) se cuentan abajo.
    pedidos = list(dict.fromkeys(ficheros))
    # Cota superior barata, antes de leer el aula: cada ruta distinta gasta como mucho 1.
    if cupo.setdefault("copias_actividad", 0) + len(pedidos) > CUPO_COPIAS_ACTIVIDAD:
        return fallo("CUPO_COPIAS_ACTIVIDAD")

    raiz = Path(base).resolve()
    documentos: list[Documento] = []
    for nombre in pedidos:
        try:
            ruta = (raiz / nombre).resolve()
            if not ruta.is_relative_to(raiz):
                return fallo("RUTA_FUERA_DE_CARPETA")
            documentos.append(contenido.cargar(ruta, raiz=raiz))
        except (OSError, RuntimeError):
            return fallo("RUTA_FUERA_DE_CARPETA")
        except ErrorContenido as exc:
            return fallo(exc.codigo)
    try:
        estructura = aula.estructura(curso_id)
    except ErrorPublicacion as exc:
        depurar(exc, debug)
        return fallo(exc.codigo)
    cmids: dict[int, Documento] = {}
    repetidos: list[str] = []  # los ficheros que sobran: apuntan a una actividad ya pedida
    sin_registro: list[informe.Fichero] = []
    for doc in documentos:
        donde = estructura.localizar(doc, curso_id)
        if donde.problema is not None:
            return fallo(donde.problema, ficheros=[informe.Fichero(doc.ruta.name, doc.tipo)])
        if donde.por in ("registro", "origen") and donde.modulo is not None:
            cmid = int(donde.modulo.cmid)
            if cmid in cmids:
                repetidos.append(doc.ruta.name)
            else:
                cmids[cmid] = doc
        else:
            sin_registro.append(informe.Fichero(doc.ruta.name, doc.tipo))
    if sin_registro:
        return fallo("ACTIVIDAD_SIN_REGISTRO", ficheros=sin_registro)
    # El cupo se gasta por actividad (cmid distinto), no por fichero.
    if cupo.setdefault("copias_actividad", 0) + len(cmids) > CUPO_COPIAS_ACTIVIDAD:
        return fallo("CUPO_COPIAS_ACTIVIDAD")

    resumen = ResumenCopia(
        curso_id,
        (nombres or {}).get(curso_id),
        entorno,
        tuple(doc.nombre for doc in cmids.values()),
    )
    if not presencia.confirmar_copia(resumen):
        return fallo("COPIA_RECHAZADA", "abortado")
    if vigente is not None and not vigente():
        presencia.informar(Aviso.peticion_retirada())
        return fallo("PETICION_RETIRADA")
    cupo["copias_actividad"] += len(cmids)
    dir_tiza = raiz / rutas.CARPETA_TRABAJO

    borrador = informe.Borrador(comando, entorno=entorno, curso=curso_id)
    borrador.paso("LOGIN")
    for nombre in repetidos:
        borrador.paso("ACTIVIDAD_REPETIDA", detalle=nombre)
    for cmid in cmids:
        try:
            temporal = estado.temporal_de_copia(dir_tiza)
        except OSError:
            return _anotar_fallo_de_copia(
                borrador, _FalloDeCopia("COPIA_NO_ESCRIBIBLE", None, False), debug
            )
        try:
            hecha, bytes_ = _traer_copia(
                aula, curso_id, curso, dir_tiza, temporal, presencia, debug, cmid
            )
        except _FalloDeCopia as exc:
            return _anotar_fallo_de_copia(borrador, exc, debug)
        _anotar_copia(borrador, hecha, bytes_)
    return borrador.documento()
