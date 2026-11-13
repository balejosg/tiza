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

import re
import sys
import traceback
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from . import calendario, colocacion, contenido, estado, informe, publicar, recorrido, rutas, tipos
from .calificacion import ponderacion
from .calificacion import reconciliar as rc
from .calificacion.deseado import Deseado, detalle_tope, nombre_de_hoja
from .calificacion.deseado import deseado as calcular_deseado
from .calificacion.ejecutar import TIPOS_DE_BLOQUEO, Ejecucion
from .calificacion.esquema import (
    Elemento,
    ErrorCalificacion,
    Esquema,
    cargar_esquema,
)
from .calificacion.ponderacion_esquema import ErrorPonderacion, EsquemaPonderacion
from .config import Config
from .contenido import Documento, ErrorContenido, hash_documento
from .estado import ErrorEstado
from .estructura import Estructura, Seccion, aplica_origen
from .publicar import AulaVirtual, CalificadorAula, ErrorPublicacion
from .rubrica_tarea import (
    MAX_NOMBRE_ESCALA,
    FilaDeResultado,
    descripcion_de_fila,
    nombre_de_fila,
    resultados_de_tarea,
)
from .tipos import CAMPO_RECORDATORIO, FechaActividad
from .vigilancia import Anotacion, EstadoDeCambios, Rechazo, Vigilancia

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
    "PlanCalificador",
    "PlanPonderacionCurso",
    "ResumenCambioAMano",
    "ResumenPonderacion",
    "Presencia",
    "ResumenAislamiento",
    "ResumenCalificador",
    "ResumenCopia",
    "ResumenEvidencia",
    "ResumenOrden",
    "ResumenPublicacion",
    "ResumenSinPruebas",
    "ResumenSobrescribir",
    "SeccionOrden",
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
    "itinerario_de",
    "necesita_vistas",
    "nombres_de_cursos",
    "ordenar_con",
    "ordenar_en_cursos",
    "ordenar_por_dependencias",
    "preparar_calificador",
    "preparar_ponderacion",
    "ponderacion_con",
    "ponderacion_en_cursos",
    "replanificar_ponderacion",
    "publicar_con",
    "publicar_en_cursos",
    "puerta_real",
    "resumen_calificador",
    "resumen_orden",
    "resumen_solo_fechas",
]

AVISO_DEBUG = "AVISO: salida de depuración; no la compartas."
CUPO_COPIAS = 3  # copias del curso por sesión: frena a un agente en bucle
CUPO_COPIAS_ACTIVIDAD = 20  # copias de una sola actividad por sesión (cada actividad gasta 1)
# D9: la escala de logro que comparten todos los resultados de los criterios.
ESCALA_LOGRO = "Escala de logro (tiza)"
# Las fórmulas entre categorías recién creadas pueden fallar la primera vez. Los coeficientes
# de la media ponderada no se reescalan: no hacen falta repasos de pesos.
MAX_PASADAS_DE_FORMULAS = 3

# Lo que la publicación y la sesión cuentan al docente. Cada aviso tiene su
# constructor tipado en ``Aviso`` (dueño de las claves de ``datos``) y su texto
# llano en :mod:`tiza.mensajes`.
AVISOS = frozenset(
    {
        "ACTIVIDAD_EN_EVALUACION_CERRADA",
        "ACTIVIDAD_PENDIENTE",
        "ACTIVIDAD_SIN_EVALUA",
        "AISLAMIENTO_GUARDADO",
        "AUTOPRUEBA_FALLIDA",
        "CALCULADOS_OCULTADOS",
        "CALIFICANDO_EN_PRUEBAS",
        "CAMBIADA_DESDE_LA_PUBLICACION",
        "CAMBIADA_EN_EL_AULA",
        "CAMBIADO_A_MANO",
        "CANCELADA",
        "CATEGORIA_BLOQUEADA",
        "CATEGORIA_NO_DECLARADA",
        "CARPETA_NO_AISLADA",
        "CERRANDO_SESION_ANTERIOR",
        "COMPROBACIONES_DE_AISLAMIENTO",
        "CONFIGURACION_GUARDADA",
        "COPIA_QUEDA_EN_EL_AULA",
        "CREANDO_SECCION",
        "CRITERIOS_SIN_PESO",
        "CURSOS_GUARDADOS",
        "DESCRIPTOR_PUBLICADO",
        "ELEMENTO_CON_NOTAS_QUITADO",
        "ELEMENTO_SIN_ACTIVIDADES",
        "ERROR_INTERNO",
        "ESTRUCTURA_NO_LEIDA",
        "EVIDENCIA_CAMBIADA_CON_NOTAS",
        "EVIDENCIA_COMPARTIDA",
        "EVALUACION_CERRADA_EN_EL_AULA",
        "FALLO",
        "HUELLA_NO_GUARDADA",
        "INFORME_NO_ESCRITO",
        "MAXIMO_ALCANZADO",
        "NADA_QUE_CAMBIAR",
        "NOMBRES_NO_DISPONIBLES",
        "NOTA_SIN_COLOCAR",
        "OCULTAR_FALLIDO",
        "ORDENANDO_EN_PRUEBAS",
        "PANEL_ACTUALIZADO",
        "PANEL_NO_ACTUALIZADO",
        "PESOS_CON_NOTAS",
        "PESOS_SIN_EFECTO",
        "PETICION_RETIRADA",
        "PONDERACION_NO_APLICADA",
        "PONDERANDO_EN_PRUEBAS",
        "PRIMERA_VEZ",
        "PUBLICANDO_EN_PRUEBAS",
        "QUEDAN_MINUTOS",
        "RECUPERACION_EN_CERRADA",
        "REGISTRO_NO_GUARDADO",
        "REGLA_CAMBIADA",
        "REINICIA_EL_AGENTE",
        "RESULTADO",
        "RESULTADO_CON_NOTAS_QUITADO",
        "RESULTADO_RECREADO",
        "RESULTADOS_DESACTIVADOS",
        "SANDBOX_NO_PERMITIDO",
        "SANDBOX_PERMITIDO",
        "SESION_ABIERTA",
        "SESION_ANTERIOR_CERRADA",
        "SESION_CERRADA",
        "SIGUE_FALTANDO",
        "SIGUE_LA_VERSION_ACTUAL",
        "TIZA_ACTUALIZADA",
        "TOTALES_VISIBLES",
        "PONDERACIONES_VISIBLES",
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
    def actividad_sin_evalua(cls, ruta: str) -> Aviso:
        """``ruta``: actividad calificable de ESO que aún no declara criterios (``evalua``)."""
        return cls("ACTIVIDAD_SIN_EVALUA", {"ruta": ruta})

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
    def calculados_ocultados(cls, cuantos: int) -> Aviso:
        """``cuantos``: calculados de tiza que esta pasada ha vuelto a ocultar al alumnado (R1)."""
        return cls("CALCULADOS_OCULTADOS", {"cuantos": cuantos})

    @classmethod
    def cambiado_a_mano(cls, nombre: str) -> Aviso:
        """``nombre``: lo que el docente cambió en el aula y tiza no toca (viene del aula)."""
        return cls("CAMBIADO_A_MANO", {"nombre": nombre})

    @classmethod
    def categoria_bloqueada(cls, nombre: str) -> Aviso:
        """``nombre``: la categoría bloqueada del aula, de la que tiza no cambia nada."""
        return cls("CATEGORIA_BLOQUEADA", {"nombre": nombre})

    @classmethod
    def categoria_no_declarada(cls, nombre: str) -> Aviso:
        """``nombre``: la categoría ``TZP_`` del aula que ``ponderacion.yaml`` ya no declara."""
        return cls("CATEGORIA_NO_DECLARADA", {"nombre": nombre})

    @classmethod
    def pesos_con_notas(cls, nombre: str) -> Aviso:
        """``nombre``: la categoría con notas cuyos pesos cambian (viene del aula)."""
        return cls("PESOS_CON_NOTAS", {"nombre": nombre})

    @classmethod
    def ponderacion_no_aplicada(cls, referencia: str) -> Aviso:
        """``referencia``: la clave del esquema (``fichero:…``) que el aula no refleja."""
        return cls("PONDERACION_NO_APLICADA", {"referencia": referencia})

    @classmethod
    def ponderando_en_pruebas(cls, esquema: str) -> Aviso:
        return cls("PONDERANDO_EN_PRUEBAS", {"esquema": esquema})

    @classmethod
    def criterios_sin_peso(cls, elemento: str) -> Aviso:
        """``elemento``: el id del esquema cuyos criterios no llevan peso."""
        return cls("CRITERIOS_SIN_PESO", {"elemento": elemento})

    @classmethod
    def pesos_sin_efecto(cls, hoja: str) -> Aviso:
        """``hoja``: el criterio cuya regla (mediana o más alta) ignora los pesos de ``evalua``."""
        return cls("PESOS_SIN_EFECTO", {"hoja": hoja})

    @classmethod
    def recuperacion_en_cerrada(cls, nombre: str) -> Aviso:
        """``nombre``: la evaluación cerrada en la que la recuperación no se coloca."""
        return cls("RECUPERACION_EN_CERRADA", {"nombre": nombre})

    @classmethod
    def regla_cambiada(cls, hoja: str) -> Aviso:
        """``hoja``: el criterio o elemento cuya regla de agregación cambia en el aula."""
        return cls("REGLA_CAMBIADA", {"hoja": hoja})

    @classmethod
    def elemento_con_notas_quitado(cls, nombre: str) -> Aviso:
        return cls("ELEMENTO_CON_NOTAS_QUITADO", {"nombre": nombre})

    @classmethod
    def elemento_sin_actividades(cls, elemento: str) -> Aviso:
        """``elemento``: el id del esquema (RA1…) al que no llega ninguna actividad."""
        return cls("ELEMENTO_SIN_ACTIVIDADES", {"elemento": elemento})

    @classmethod
    def evidencia_cambiada_con_notas(cls, nombre: str) -> Aviso:
        """``nombre``: la tarea con notas que no gana resultados porque el docente dijo que no."""
        return cls("EVIDENCIA_CAMBIADA_CON_NOTAS", {"nombre": nombre})

    @classmethod
    def evidencia_compartida(cls, nombre: str, tipo: str | None = None) -> Aviso:
        """``nombre``: la actividad o casilla manual con dos o más criterios, sin evidencia (D9).

        ``tipo``: el de la actividad, cuando se conoce (un cuestionario recibe un «Qué hacer»
        propio); ``None`` en las casillas manuales y en los avisos sin actividad.
        """
        datos: dict[str, Any] = {"nombre": nombre}
        if tipo is not None:
            datos["tipo"] = tipo
        return cls("EVIDENCIA_COMPARTIDA", datos)

    @classmethod
    def descriptor_publicado(cls, nombre: str, fila: str) -> Aviso:
        """``nombre``: la tarea; ``fila``: el indicador cuya escala ya estaba publicada."""
        return cls("DESCRIPTOR_PUBLICADO", {"nombre": nombre, "fila": fila})

    @classmethod
    def resultado_con_notas_quitado(cls, nombre: str) -> Aviso:
        """``nombre``: el resultado que deja de contar y se queda con peso 0 (D11)."""
        return cls("RESULTADO_CON_NOTAS_QUITADO", {"nombre": nombre})

    @classmethod
    def resultado_recreado(cls, nombre: str) -> Aviso:
        """``nombre``: el resultado que el docente borró en el aula y tiza vuelve a crear."""
        return cls("RESULTADO_RECREADO", {"nombre": nombre})

    @classmethod
    def resultados_desactivados(cls, nombre: str) -> Aviso:
        """``nombre``: la tarea que se publica sin resultados porque el sitio los tiene apagados."""
        return cls("RESULTADOS_DESACTIVADOS", {"nombre": nombre})

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
    def nota_sin_colocar(cls, nombre: str, motivo: str, categoria: str | None) -> Aviso:
        """``nombre``: la actividad publicada cuya nota no se colocó; ``motivo``: ``AMBIGUA``,
        ``SIN_PATRON``, ``CERRADA``, ``CAMBIADA`` o el código del fallo al leer o mover el
        calificador; ``categoria``: el nombre de la categoría cerrada, solo con ``CERRADA``."""
        return cls("NOTA_SIN_COLOCAR", {"nombre": nombre, "motivo": motivo, "categoria": categoria})

    @classmethod
    def ocultar_fallido(cls, cuantos: int) -> Aviso:
        """``cuantos``: calculados de tiza que siguen visibles para el alumnado (R1)."""
        return cls("OCULTAR_FALLIDO", {"cuantos": cuantos})

    @classmethod
    def totales_visibles(cls) -> Aviso:
        """El curso muestra al alumnado los totales que contienen ítems ocultos (R1-D4)."""
        return cls("TOTALES_VISIBLES")

    @classmethod
    def ponderaciones_visibles(cls) -> Aviso:
        """El informe del usuario muestra «Ponderación» o «Contribución al total del curso»."""
        return cls("PONDERACIONES_VISIBLES")

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
    def sandbox_permitido(cls) -> Aviso:
        return cls("SANDBOX_PERMITIDO")

    @classmethod
    def sandbox_no_permitido(cls, codigo: int) -> Aviso:
        """``codigo``: el de ``pkexec`` (126 canceló, 127 sin permiso; -1, sin ``pkexec``)."""
        return cls("SANDBOX_NO_PERMITIDO", {"codigo": codigo})

    @classmethod
    def tiza_actualizada(cls, aparte: bool) -> Aviso:
        """``aparte``: la instalación sigue en otro proceso (Windows o el panel) y hay que
        esperar a que acabe."""
        return cls("TIZA_ACTUALIZADA", {"aparte": aparte})


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
    # Dónde irá en el calificador la nota de lo que se crea o cambia de sección.
    notas: tuple[CambioNota, ...] = ()


@dataclass(frozen=True)
class CambioNota:
    """Dónde irá en el calificador la nota de una actividad al publicarla. La ve solo el docente.

    Con ``destino``, la nota va a esa categoría tras la actividad ``despues_de`` (nada: al
    principio); ``desde`` es la categoría de la que sale al cambiar de sección. Sin ``destino``
    no se coloca y ``motivo`` dice por qué (``AMBIGUA``, ``SIN_PATRON`` o ``CERRADA``, con el
    nombre de la categoría cerrada en ``categoria``).
    """

    fichero: str
    destino: str | None
    despues_de: str | None
    desde: str | None
    motivo: str | None
    categoria: str | None = None


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
    notas: tuple[CambioNota, ...] = ()


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
    # Notas del calificador que se reordenarán para seguir el orden final del curso.
    notas: int = 0


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
    ``ocultadas``: calculados de tiza que se ocultarán al alumnado en esta pasada (R1).
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
    ocultadas: int = 0


@dataclass(frozen=True)
class PlanCalificador:
    """Lo que ``tiza calificador`` va a hacer en un curso: se calcula antes de confirmar.

    Es lo que se enseña y lo que se ejecuta. ``preparar_calificador`` solo activa los resultados
    ya efectivos (todos sus elementos marcados); los pendientes se enseñan como tareas normales.
    Tras la confirmación, ``calificador_con`` asegura las definiciones y recalcula el árbol con
    las tareas que pasan a resultados (o las deja normales si el docente dice que no o los
    resultados están desactivados). ``resultados`` (criterio -> id en Moodle) se completa en
    ``calificador_con``; ``preparar_calificador`` no escribe y deja solo los que ya existían.
    ``resultados_pendientes`` avisa de que falta alguna definición o marca y hay que preguntar.
    """

    curso: int
    aula_antes: CalificadorAula
    deseado: Deseado
    reconciliacion: rc.Reconciliacion
    cmids: dict[str, int]
    huellas: dict[str, str]
    documentos: tuple[Documento, ...]  # los que cuentan (los que llevan «evalua»)
    base: Path
    resultados: dict[str, int] = field(default_factory=dict)
    documentos_con_resultados: frozenset[str] = frozenset()
    resultados_pendientes: bool = False
    # «Ocultar totales si contienen ítems ocultos» del curso: -1, 0, 1, 2 o None (ilegible).
    ajuste_totales: int | None = None
    # El informe del usuario muestra «Ponderación» o «Contribución al total del curso».
    ponderaciones_visibles: bool = False


@dataclass(frozen=True)
class ResumenPonderacion:
    """Lo que va a hacer ``tiza calificador ponderacion.yaml`` en un curso real: el antes/después.

    Los nombres son los del aula (solo los ve el docente, saneados). ``pesos_con_notas`` y
    ``salidas`` son nombres de categorías; ``avisos`` los que no llevan su propia línea.
    """

    curso: int
    nombre_curso: str | None
    afectadas: tuple[ponderacion.CategoriaAfectada, ...]
    cambios_a_mano: tuple[ponderacion.CambioAMano, ...]
    pesos_con_notas: tuple[str, ...]
    salidas: tuple[str, ...]
    avisos: tuple[Aviso, ...]
    posicion: int = 1
    total: int = 1


@dataclass(frozen=True)
class ResumenCambioAMano:
    """Un peso que el docente cambió a mano en el aula y que tiza solo pisa si él lo dice."""

    curso: int
    nombre_curso: str | None
    cambio: ponderacion.CambioAMano
    posicion: int = 1
    total: int = 1


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
class ResumenRubricas:
    """Las tareas que ya están en el aula y van a recibir una rúbrica por criterios.

    Se pregunta después de la confirmación normal del curso. ``tareas`` son los nombres tal
    como están en el fichero (``doc.nombre``), nunca texto del aula.
    """

    curso: int
    nombre_curso: str | None
    tareas: tuple[str, ...]
    posicion: int = 1
    total: int = 1


@dataclass(frozen=True)
class ResumenEvidencia:
    """Las tareas con notas que pasan a recoger la evidencia con resultados (D11).

    Se pregunta después de la confirmación normal del curso y antes de publicar. ``tareas`` son
    los nombres tal como están en el fichero (``doc.nombre``), nunca texto del aula.
    """

    curso: int
    nombre_curso: str | None
    tareas: tuple[str, ...]
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

    def confirmar_ponderacion(self, resumen: ResumenPonderacion) -> bool:
        """¿Aplicar en este curso la ponderación que enseña ``resumen``? Una respuesta por curso."""
        ...

    def confirmar_ponderacion_a_mano(self, resumen: ResumenCambioAMano) -> bool:
        """¿Sobrescribir lo que cambiaste a mano en el aula? Una respuesta por cambio; sin
        respuesta, es no."""
        ...

    def confirmar_copia(self, resumen: ResumenCopia) -> bool:
        """¿Hacer una copia de este curso, sin datos de alumnos? Una respuesta por petición."""
        ...

    def confirmar_sobrescribir(self, resumen: ResumenSobrescribir) -> bool:
        """¿Sobrescribir las actividades que retocaste a mano en el aula y perder esos cambios?
        Una respuesta por curso; sin respuesta, es no."""
        ...

    def confirmar_rubricas(self, resumen: ResumenRubricas) -> bool:
        """¿Ninguna de estas tareas que ya existen tiene notas? Con «no», no se toca su
        rúbrica. Una respuesta por curso; sin respuesta, es no."""
        ...

    def confirmar_evidencia(self, resumen: ResumenEvidencia) -> bool:
        """¿Estas tareas con notas ganan los resultados de sus criterios? Con «no», se publican
        sin resultados. Una respuesta por curso; sin respuesta, es no."""
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


def necesita_vistas(cfg: Config, *, solo_fechas: bool) -> bool:
    """Regla común: publicar en real hace vistas previas solo con curso de pruebas y sin solo-fechas.

    Sin curso de pruebas no hay verificación previa ni vista que enseñar: se compensa publicando
    solo en oculto y con una confirmación corta. La terminal directa la usa para crear (y borrar)
    el directorio de las vistas.
    """
    return "pruebas" in cfg.cursos and not solo_fechas


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


def niveles_de_escala(esquema: Esquema) -> tuple[str, ...]:
    """Los nombres de ``niveles_rubrica`` de menor a mayor porcentaje (D8)."""
    return tuple(
        nivel.nombre for nivel in sorted(esquema.niveles_rubrica, key=lambda n: n.porcentaje)
    )


def nombre_de_escala_de_fila(fila: FilaDeResultado) -> str:
    """El nombre estable de la escala de una fila: criterio, indicador y su clave.

    La clave lleva la tarea, el criterio y el indicador: dos tareas con la misma fila tienen
    escalas distintas y renombrar el indicador crea otra escala.
    """
    base = f"Escala · {fila.criterio} · {fila.indicador}"
    sufijo = f" · {fila.clave}"
    return (base[: MAX_NOMBRE_ESCALA - len(sufijo)] + sufijo)[:MAX_NOMBRE_ESCALA]


def _asegurar_escala_de_fila(
    aula: AulaVirtual, curso: int, fila: FilaDeResultado
) -> tuple[int, bool]:
    """(id de la escala, ¿ya estaba publicada con otros niveles?).

    Si la escala está en uso con otros niveles, Moodle no la cambia (D-F2-7): se queda como
    está, se avisa ``DESCRIPTOR_PUBLICADO`` y se sigue con el resto.
    """
    nombre = nombre_de_escala_de_fila(fila)
    try:
        return aula.asegurar_escala(curso, nombre, fila.niveles), False
    except ErrorPublicacion as exc:
        if exc.codigo != "ESCALA_EN_USO":
            raise
        escala = aula.escala_con_nombre(curso, nombre)
        if escala is None:
            raise
        return escala, True


def descripcion_de_resultado(esquema: Esquema, criterio: str) -> str:
    """La descripción de un resultado: el nombre del criterio y la lista de niveles (D9)."""
    niveles = ", ".join(
        f"{nivel.nombre} ({nivel.porcentaje:g} %)"
        for nivel in sorted(esquema.niveles_rubrica, key=lambda n: n.porcentaje)
    )
    return f"{nombre_de_hoja(esquema, criterio)}\n\nNiveles: {niveles}"


def _cargar_esquema_de_evidencia(base: Path) -> Esquema:
    """El ``calificacion.yaml`` de la carpeta, con la comprobación de D8.

    Solo se llama cuando algún documento lleva ``evidencia: resultados``. Si el fichero falta o
    no vale, se propaga ``ErrorCalificacion`` con su código (nunca texto de Moodle).
    """
    return cargar_esquema(base / "calificacion.yaml", base, resultados=True)


def _resultados_propios(aula: AulaVirtual, curso: int, doc: Documento) -> set[int]:
    """Ids de Moodle de los resultados de ``doc`` (criterios o filas) que ya existen."""
    return {
        resultado
        for clave, _criterio in resultados_de_tarea(doc)
        if (resultado := aula.resultado_por_corto(curso, f"TZ_{clave}")) is not None
    }


def _tarea_con_notas_sin_resultados(
    aula: AulaVirtual, curso: int, doc: Documento, cmid: int | None
) -> bool:
    """¿La tarea existe, tiene notas y aún no marca ninguno de sus resultados propios?

    Es la única regla de D11: ``resultados_de_la_tarea`` y las dos preguntas la usan. Un
    resultado ajeno marcado no cuenta; una definición ausente tampoco.
    """
    if cmid is None or not aula.actividad_tiene_notas(cmid):
        return False
    marcados = aula.campos_resultado_tarea(cmid)
    return not any(marcados.get(resultado) for resultado in _resultados_propios(aula, curso, doc))


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
    notas_confirmadas: Mapping[Path, str | None] | None = None,
    rubrica_confirmada: bool = False,
    evidencia_confirmada: bool = False,
) -> recorrido.Resultado:
    """Con el aula ya abierta: publica y verifica los documentos.

    Con ``solo_fechas`` solo cambia las fechas de lo que ya existe: no crea secciones,
    no sube recursos y no registra nada como verificado en pruebas.

    En un curso real (``entorno == "real"``), lo que el docente retocó a mano en el aula desde que
    tiza lo publicó no se pisa: la actividad vigilada que construye la ``Vigilancia`` lo comprueba
    justo antes de escribir (``CAMBIADA_EN_EL_AULA``). Las decisiones del docente entran explícitas,
    por ruta resuelta del documento: ``sobrescribir`` (dijo que sí a perder ese cambio: se publica y
    el informe lleva ``CAMBIO_DEL_AULA_DESCARTADO``) y ``no_publicar`` (dijo que no: se rechaza como
    ``CAMBIADA_EN_EL_AULA``, con el resto del lote). Tras publicar, la vigilancia anota la huella de
    la copia, la entrada del registro y la base; en pruebas no se compara el registro ni se guarda
    la base.

    Las notas: tras el bucle, las actividades con nota que se crearon o cambiaron de sección y no
    llevan ``evalua`` (esas las coloca ``tiza calificador``) pasan por ``publicar.colocar_notas``.
    ``notas_confirmadas`` (ruta resuelta del documento -> eid de la categoría que vio el docente en
    el resumen; ``None`` la categoría si no se iba a colocar) hace que no se mueva ninguna nota
    cuyo destino sea otro; sin ellas (``None``, en pruebas) no se compara. Que la nota no se pueda
    colocar nunca estropea la publicación: queda un paso ``NOTA_SIN_COLOCAR`` y un aviso.

    Con ``evidencia: resultados`` se asegura antes la escala de logro y los resultados de los
    criterios (D8, D9) y la tarea marca sus ``outcome_<id>``. Si el sitio tiene los resultados
    desactivados, se publica sin ellos (``RESULTADOS_DESACTIVADOS``). Si la tarea ya tiene notas y
    aún no marca ninguno, hace falta ``evidencia_confirmada`` (D11); sin él se publica sin
    resultados y queda ``EVIDENCIA_CAMBIADA_CON_NOTAS``.
    """
    borrador = informe.Borrador("publicar", entorno=entorno, curso=curso)
    borrador.paso("LOGIN")
    base = Path(carpeta).resolve()
    paso = "SOLO_FECHAS" if solo_fechas else "PUBLICAR"
    esquema_evidencia: Esquema | None = None
    if not solo_fechas and any(doc.evidencia == "resultados" for doc in documentos):
        try:
            esquema_evidencia = _cargar_esquema_de_evidencia(base)
        except (ErrorCalificacion, OSError) as exc:
            codigo = getattr(exc, "codigo", "CALIFICACION_INVALIDA")
            borrador.fallo(paso, "calificacion.yaml")
            borrador.error(codigo)
            return recorrido.Resultado.hecho(borrador.documento("error"), corta=True)
    if not solo_fechas:
        ordenados = ordenar_por_dependencias(documentos, base)
        if ordenados is None:
            borrador.fallo("DEPENDENCIAS", "DEPENDENCIA_CIRCULAR")
            borrador.error("DEPENDENCIA_CIRCULAR")
            return recorrido.Resultado.hecho(borrador.documento("error"), corta=True)
        documentos = ordenados
    try:
        estructura = aula.estructura(curso)
    except ErrorPublicacion as exc:
        borrador.fallo("ESTRUCTURA", exc.codigo)
        borrador.error(exc.codigo)
        depurar(exc, debug)
        return recorrido.Resultado.hecho(borrador.documento("error"), corta=True)
    # Lo que se rechaza por su origen se dice ya y no deja nada hecho (ni una sección creada).
    dir_tiza = Path(carpeta) / rutas.CARPETA_TRABAJO
    real = entorno == "real"
    try:
        vigilancia = Vigilancia.de(aula, dir_tiza, curso, documentos, real)
    except estado.ErrorEstado as exc:
        borrador.fallo("PREPARAR", exc.codigo)
        borrador.error(exc.codigo)
        return recorrido.Resultado.hecho(borrador.documento("error"), corta=True)
    aceptados, rechazos = _separar_rechazados(
        documentos, estructura, base, solo_fechas, vigilancia, no_publicar
    )
    for rechazo in rechazos:
        doc = rechazo.documento
        detalle = doc.ruta.name
        if rechazo.cmid_copia is not None:
            detalle += f": junta antes los cambios de .tiza/copia/{rechazo.cmid_copia}.html"
            presencia.informar(Aviso.cambiada_en_el_aula(doc.nombre, rechazo.cmid_copia))
        elif rechazo.por_decision:
            presencia.informar(Aviso.cambiada_desde_la_publicacion(doc.nombre))
        borrador.fallo(paso, detalle)
        borrador.error(rechazo.codigo)
    documentos = aceptados
    existentes: dict[str, int] = {}
    if not solo_fechas:
        faltante = _resolver_dependencias(base, estructura, documentos, existentes, curso)
        if faltante is not None:
            borrador.fallo("DEPENDENCIAS", faltante[1])
            borrador.error(faltante[0])
            return recorrido.Resultado.hecho(borrador.documento("error"), corta=True)
    if solo_fechas:
        # Todo o nada: si alguno de los documentos no se puede cambiar, no se cambia ninguno.
        codigo = codigo_solo_fechas(estructura, documentos, curso)
        if codigo is not None:
            borrador.fallo("SOLO_FECHAS", codigo)
            borrador.error(codigo)
            return recorrido.Resultado.hecho(borrador.documento("error"), corta=True)
    else:
        for nombre in estructura.secciones_que_faltan(documentos):
            presencia.informar(Aviso.creando_seccion(nombre))
        try:
            estructura, creadas = publicar.asegurar_secciones(aula, curso, estructura, documentos)
        except ErrorPublicacion as exc:
            borrador.fallo("CREAR_SECCION", exc.codigo)
            borrador.error(exc.codigo)
            depurar(exc, debug)
            return recorrido.Resultado.hecho(borrador.documento("error"), corta=True)
        for nombre in creadas:
            borrador.paso("CREAR_SECCION", detalle=nombre)
    cmids = dict(existentes)  # de cada fichero de la carpeta, su cmid en este curso
    motor: bool | None = None  # ¿dibuja el aula las fórmulas? Se mira una vez por curso
    # Las que ya están en el aula y cambian de sección (no vale «movida»: renombrar y mover a la
    # vez sale como «renombrada»); se calcula antes de que el bucle las mueva.
    cambian_de_seccion = (
        set()
        if solo_fechas
        else {
            id(doc) for doc in documentos if estructura.desde_donde_se_mueve(doc, curso) is not None
        }
    )
    con_nota: list[tuple[Documento, int]] = []
    escala_logro: int | None = None
    resultados_desactivados = False

    def resultados_de_la_tarea(doc: Documento, cmid: int | None) -> dict[str, int]:
        """Asegura la escala y los resultados de una tarea con evidencia (D8, D9, D11, D12).

        Sin resultados activos no se escribe nada y se sigue con la publicación. Si la tarea ya
        existe, tiene notas y aún no marca ningún resultado, se pide el sí que llega en
        ``evidencia_confirmada``; con un no, se publica sin resultados y queda el paso.
        """
        nonlocal escala_logro, resultados_desactivados
        if esquema_evidencia is None or doc.evidencia != "resultados" or doc.evalua is None:
            return {}
        if resultados_desactivados:
            borrador.paso("RESULTADOS_DESACTIVADOS", detalle=doc.ruta.name)
            presencia.informar(Aviso.resultados_desactivados(doc.nombre))
            return {}
        if not aula.resultados_activos(curso):
            resultados_desactivados = True
            borrador.paso("RESULTADOS_DESACTIVADOS", detalle=doc.ruta.name)
            presencia.informar(Aviso.resultados_desactivados(doc.nombre))
            return {}
        # D11: antes de crear nada, si la tarea ya tiene notas y aún no marca ningún resultado
        # propio, el «no» del docente la deja como estaba. Solo se avisa en el «no».
        if _tarea_con_notas_sin_resultados(aula, curso, doc, cmid):
            if not evidencia_confirmada:
                borrador.paso("EVIDENCIA_CAMBIADA_CON_NOTAS", detalle=doc.ruta.name)
                presencia.informar(Aviso.evidencia_cambiada_con_notas(doc.nombre))
                return {}
        resultados: dict[str, int] = {}
        if doc.rubrica_filas is not None:
            for fila in doc.rubrica_filas.filas:
                escala, publicado = _asegurar_escala_de_fila(aula, curso, fila)
                if publicado:
                    borrador.paso(
                        "DESCRIPTOR_PUBLICADO",
                        detalle=f"{doc.ruta.name}: {fila.indicador}",
                    )
                    presencia.informar(Aviso.descriptor_publicado(doc.nombre, fila.indicador))
                resultados[fila.clave] = aula.asegurar_resultado(
                    curso,
                    f"TZ_{fila.clave}",
                    nombre_de_fila(esquema_evidencia, fila),
                    descripcion_de_fila(esquema_evidencia, fila),
                    escala,
                )
            return resultados
        if escala_logro is None:
            escala_logro = aula.asegurar_escala(
                curso, ESCALA_LOGRO, niveles_de_escala(esquema_evidencia)
            )
        for criterio, _ in doc.evalua:
            resultados[criterio] = aula.asegurar_resultado(
                curso,
                f"TZ_{criterio}",
                nombre_de_hoja(esquema_evidencia, criterio),
                descripcion_de_resultado(esquema_evidencia, criterio),
                escala_logro,
            )
        return resultados

    for doc in documentos:
        vigilada = None
        pasos_del_tipo: list[informe.Paso] = []
        try:
            decidido = doc.ruta.resolve() in sobrescribir
            vigilada = vigilancia.actividad(estructura, doc, sobrescribe=decidido)
            if solo_fechas:
                resultado = publicar.publicar_fechas(
                    aula, estructura, doc, curso, vigilada=vigilada
                )
            else:
                dependencias = {
                    fichero: cmids[fichero]
                    for fichero in (doc.restricciones.completar if doc.restricciones else ())
                    if fichero in cmids
                }
                pasos_del_tipo = []
                localizada = estructura.localizar(doc, curso).modulo
                cmid_existente = (
                    vigilada.cmid
                    if vigilada is not None
                    else (localizada.cmid if localizada is not None else None)
                )
                resultados = resultados_de_la_tarea(doc, cmid_existente)
                resultado = publicar.publicar_documento(
                    aula,
                    curso,
                    estructura,
                    doc,
                    visible=visible,
                    dependencias=dependencias,
                    vigilada=vigilada,
                    rubrica_confirmada=rubrica_confirmada,
                    resultados=resultados,
                    pasos=pasos_del_tipo,
                )
                assert resultado.cmid is not None  # acaba de crearla o actualizarla
                cmids[_relativa(doc.ruta, base)] = resultado.cmid
        except ErrorPublicacion as exc:
            borrador.fallo(paso, doc.ruta.name)
            depurar(exc, debug)
            borrador.error(exc.codigo)
            if exc.codigo not in ERRORES_POR_FICHERO:
                return recorrido.Resultado.hecho(borrador.documento("error"), corta=True)
            # Esta actividad no se toca; las demás del lote siguen.
            if exc.codigo == "CAMBIADA_EN_EL_AULA":
                de_copia = vigilada.de_copia if vigilada is not None else aplica_origen(doc, curso)
                presencia.informar(
                    Aviso.cambiada_en_el_aula(doc.nombre)
                    if de_copia
                    else Aviso.cambiada_desde_la_publicacion(doc.nombre)
                )
            continue
        ruta = _relativa(doc.ruta, base)
        if solo_fechas:
            anotacion = vigilancia.anotar_fechas(doc, ruta, vigilada)
        else:
            anotacion = vigilancia.anotar_publicado(doc, ruta, cmids[ruta])
        _anotar_anotacion(anotacion, doc, borrador, presencia)
        if entorno == "pruebas" and not solo_fechas:
            assert resultado.cmid is not None and resultado.hash is not None
            estado.guardar_verificado(
                Path(carpeta) / rutas.CARPETA_TRABAJO,
                resultado.hash,
                resultado.nombre,
                resultado.cmid,
            )
        borrador.fichero(replace(resultado, curso=curso))
        if (
            not solo_fechas
            and resultado.cmid is not None
            and tipos.obtener(doc.tipo).tiene_nota(doc)
            and doc.evalua is None
            and (resultado.accion == "creada" or id(doc) in cambian_de_seccion)
        ):
            con_nota.append((doc, resultado.cmid))
        detalle = doc.ruta.name
        if not solo_fechas:
            extra = tipos.obtener(doc.tipo).detalle(doc)
            if extra:
                detalle = f"{detalle}: {extra}"
        borrador.paso(paso, detalle=detalle)
        for del_tipo in pasos_del_tipo:
            borrador.paso(del_tipo.codigo, del_tipo.resultado, del_tipo.detalle)
        if decidido:
            borrador.paso("CAMBIO_DEL_AULA_DESCARTADO", detalle=doc.ruta.name)
        if not solo_fechas and contenido.tiene_formulas(doc):
            if motor is None:
                motor = publicar.aula_dibuja_formulas(aula, curso)
            if not motor:
                borrador.paso("FORMULAS_NO_DIBUJADAS", detalle=doc.ruta.name)
    if con_nota:
        _colocar_las_notas(aula, curso, con_nota, notas_confirmadas, borrador, presencia, debug)
    documento = borrador.documento()
    return recorrido.Resultado.hecho(documento, corta=_corta(documento, rechazos, no_publicar))


def _colocar_las_notas(
    aula: AulaVirtual,
    curso: int,
    con_nota: list[tuple[Documento, int]],
    notas_confirmadas: Mapping[Path, str | None] | None,
    borrador: informe.Borrador,
    presencia: Presencia,
    debug: bool,
) -> None:
    """Coloca la nota de cada actividad de ``con_nota`` (documento, cmid) y lo cuenta.

    Relee la estructura ya con todo publicado. Un fallo del aula (también el de leer el
    calificador) no corta nada: cada actividad queda con ``NOTA_SIN_COLOCAR`` y su código.
    """
    documentos = {cmid: doc for doc, cmid in con_nota}
    esperado = (
        None
        if notas_confirmadas is None
        else {cmid: notas_confirmadas.get(doc.ruta.resolve()) for doc, cmid in con_nota}
    )
    try:
        movimientos, sin_colocar = publicar.colocar_notas(
            aula, curso, aula.estructura(curso), list(documentos), esperado
        )
    except ErrorPublicacion as exc:
        depurar(exc, debug)
        movimientos = ()
        sin_colocar = tuple(colocacion.SinColocar(cmid, exc.codigo, None) for cmid in documentos)
    for movimiento in movimientos:
        borrador.paso("NOTA_COLOCADA", detalle=documentos[movimiento.cmid].ruta.name)
    for sin in sin_colocar:
        doc = documentos[sin.cmid]
        borrador.paso("NOTA_SIN_COLOCAR", detalle=f"{doc.ruta.name}: {sin.motivo}")
        presencia.informar(Aviso.nota_sin_colocar(doc.nombre, sin.motivo, sin.categoria))


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
    base: Path,
    solo_fechas: bool,
    vigilancia: Vigilancia,
    no_publicar: Collection[Path] = (),
) -> tuple[list[Documento], list[Rechazo]]:
    """(los que se pueden publicar, los rechazados), mirando solo la estructura.

    Se rechazan antes de confirmar y de crear nada: dos ficheros del mismo ``origen``
    (``ORIGEN_DUPLICADO``), lo que rechaza la vigilancia por su ``origen``
    (``ORIGEN_NO_ENCONTRADO``, ``ORIGEN_SIN_HUELLA`` y ``CAMBIADA_EN_EL_AULA`` por la marca de
    ``copia.json``), lo que el docente decidió no sobrescribir (``CAMBIADA_EN_EL_AULA`` con
    ``por_decision``) y quien depende de uno rechazado (``DEPENDENCIA_NO_PUBLICADA``). Con
    ``--solo-fechas`` el origen no encontrado y las dependencias no cuentan: es todo o nada.
    """
    base = Path(base).resolve()
    claves = [_relativa(doc.ruta, base) for doc in documentos]
    cuantos = Counter((doc.origen.curso, doc.origen.cmid) for doc in documentos if doc.origen)
    rechazados: dict[int, Rechazo] = {}
    for indice, doc in enumerate(documentos):
        if doc.origen is not None and cuantos[(doc.origen.curso, doc.origen.cmid)] > 1:
            rechazados[indice] = Rechazo(doc, "ORIGEN_DUPLICADO")
    de_la_vigilancia = {
        id(rechazo.documento): rechazo
        for rechazo in vigilancia.rechazos(estructura, documentos, solo_fechas)
    }
    for indice, doc in enumerate(documentos):
        if indice not in rechazados and id(doc) in de_la_vigilancia:
            rechazados[indice] = de_la_vigilancia[id(doc)]
    if not solo_fechas:
        _cerrar_dependencias(documentos, claves, rechazados, por_decision=False)
    if no_publicar:
        for indice, doc in enumerate(documentos):
            if indice not in rechazados and doc.ruta.resolve() in no_publicar:
                rechazados[indice] = vigilancia.rechazo_del_no(doc)
        if not solo_fechas:
            _cerrar_dependencias(documentos, claves, rechazados, por_decision=True)
    return (
        [doc for indice, doc in enumerate(documentos) if indice not in rechazados],
        [rechazados[indice] for indice in sorted(rechazados)],
    )


def _cerrar_dependencias(
    documentos: list[Documento],
    claves: list[str],
    rechazados: dict[int, Rechazo],
    *,
    por_decision: bool,
) -> None:
    """Añade a ``rechazados`` quien depende de un rechazado, de forma transitiva."""
    crecio = True
    while crecio:
        crecio = False
        fuera = {claves[indice] for indice in rechazados}
        for indice, doc in enumerate(documentos):
            deps = doc.restricciones.completar if doc.restricciones else ()
            if indice not in rechazados and any(dep in fuera for dep in deps):
                rechazados[indice] = Rechazo(
                    doc, "DEPENDENCIA_NO_PUBLICADA", por_decision=por_decision
                )
                crecio = True


def _corta(documento: dict, rechazos: Sequence[Rechazo], no_publicar: Collection[Path]) -> bool:
    """Si el resultado del curso corta los siguientes: un «no» del docente no corta.

    Es falso si el informe es ``ok``, o si el único motivo de sus errores es el «no» y lo que
    arrastra. Cualquier otro caso corta.
    """
    if documento["resultado"] == "ok":
        return False
    if not no_publicar or not documento["errores"]:
        return True
    por_el_no = Counter(rechazo.codigo for rechazo in rechazos if rechazo.por_decision)
    return bool(Counter(documento["errores"]) - por_el_no)


def _anotar_anotacion(
    anotacion: Anotacion,
    doc: Documento,
    borrador: informe.Borrador,
    presencia: Presencia,
) -> None:
    """Lo que no se pudo guardar al anotar, como pasos y avisos, en el orden de las escrituras.

    ``BASE_NO_GUARDADA`` no lleva aviso: el docente no nota nada. La tabla código → aviso vive
    aquí, donde viven los constructores tipados de :class:`Aviso`.
    """
    for codigo in anotacion.fallos:
        borrador.fallo(codigo, doc.ruta.name)
        aviso = _AVISO_DE_ANOTACION.get(codigo)
        if aviso is not None:
            presencia.informar(aviso(doc.nombre))


_AVISO_DE_ANOTACION: dict[str, Callable[[str], Aviso]] = {
    "HUELLA_NO_GUARDADA": Aviso.huella_no_guardada,
    "REGISTRO_NO_GUARDADO": Aviso.registro_no_guardado,
}


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


_ACCION_DE_CAMBIO = {
    EstadoDeCambios.CAMBIADA: "cambiada",
    EstadoDeCambios.SIN_CAMBIOS: "sin_cambios",
    EstadoDeCambios.SIN_REGISTRO: "sin_registro",
}


def cambios_en_el_aula(
    aula: AulaVirtual,
    estructura: Estructura,
    documentos: Sequence[Documento],
    curso: int,
    dir_tiza: Path,
) -> list[informe.Fichero]:
    """Un ``Fichero`` por documento: ``cambiada``, ``sin_cambios`` o ``sin_registro`` en ``curso``.

    Para ``tiza estructura --cambios`` (solo cursos reales; el llamador no pide el de pruebas).
    Delega en la vigilancia; no escribe nada ni lleva texto del aula. ``copia.json`` solo se lee
    si algún documento viene de este curso por su ``origen`` (``ErrorEstado`` si no vale).
    """
    vigilancia = Vigilancia.de(aula, dir_tiza, curso, list(documentos), real=True)
    return [
        informe.Fichero(
            cambio.documento.ruta.name,
            cambio.documento.tipo,
            cmid=cambio.cmid,
            accion=_ACCION_DE_CAMBIO[cambio.estado],
            curso=curso,
        )
        for cambio in vigilancia.estado_por_documento(estructura, documentos)
    ]


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
    return recorrido.recorrer(
        _TrabajoPublicar(
            aula,
            cfg,
            documentos,
            base,
            presencia,
            visible=visible,
            solo_fechas=solo_fechas,
            verificados=verificados,
            dir_vistas=dir_vistas,
            debug=debug,
        ),
        cfg,
        presencia,
        entorno=entorno,
        vigente=vigente,
        cupo=cupo,
        avisar_en_pruebas=avisar_en_pruebas,
        omitidos=omitidos,
        nombres=nombres,
    )


class _TrabajoPublicar(recorrido.TrabajoBase):
    """Lo que publicar hace en un curso; el bucle y las preguntas son del recorrido."""

    comando = "publicar"

    def __init__(
        self,
        aula: AulaVirtual,
        cfg: Config,
        documentos: list[Documento],
        base: Path,
        presencia: Presencia,
        *,
        visible: bool | None,
        solo_fechas: bool,
        verificados: Mapping[str, estado.Verificado] | None,
        dir_vistas: Path | None,
        debug: bool,
    ) -> None:
        self._aula = aula
        self._cfg = cfg
        self._documentos = documentos
        self._base = base
        self._presencia = presencia
        self._visible = visible
        self._solo_fechas = solo_fechas
        self._verificados = verificados
        self._dir_vistas = dir_vistas
        self._debug = debug
        self._sin_pruebas = "pruebas" not in cfg.cursos
        self._vistas: list[Path | None] = [None] * len(documentos)
        self._cal: calendario.Calendario | None = None
        self._aviso_calendario: str | None = None

    def gasto_en_pruebas(self) -> int:
        # Los de un origen repetido no se publican: ni gastan cupo ni se anuncian.
        validos, _repetidos = _sin_origen_repetido(self._documentos)
        return len(validos)

    def comprobar_en_pruebas(self, curso: int) -> str | None:
        if not self._solo_fechas:
            return None
        # Todo o nada antes de tocar el cupo ni la presencia: si algo no se puede cambiar,
        # no se consume cupo por un cambio que no va a ocurrir.
        try:
            estructura = self._aula.estructura(curso)
        except ErrorPublicacion as exc:
            return exc.codigo
        return codigo_solo_fechas(estructura, self._documentos, curso)

    def aviso_en_pruebas(self) -> Aviso:
        validos, _repetidos = _sin_origen_repetido(self._documentos)
        return Aviso.publicando_en_pruebas(
            tuple(DocumentoResumen.de(doc, self._base) for doc in validos)
        )

    def preparar_real(self) -> str | None:
        """La puerta, las vistas y el calendario, una vez antes de los cursos reales."""
        if not self._solo_fechas:
            if self._sin_pruebas:
                if exige_oculto_sin_pruebas(
                    self._cfg, self._visible, solo_fechas=self._solo_fechas
                ):
                    return "SOLO_OCULTO_SIN_PRUEBAS"
                self._visible = False
            elif puerta_real(self._base, self._documentos, self._verificados):
                return "VERIFICACION_PENDIENTE"
        self._vistas = [None] * len(self._documentos)
        if necesita_vistas(self._cfg, solo_fechas=self._solo_fechas):
            raiz_vistas = (
                self._dir_vistas
                if self._dir_vistas is not None
                else self._base / rutas.CARPETA_TRABAJO
            )
            try:
                self._vistas = [
                    contenido.previsualizar(doc, raiz_vistas, nombre=nombre)
                    for doc, nombre in zip(
                        self._documentos, _nombres_de_vista(self._documentos), strict=True
                    )
                ]
            except ErrorContenido as exc:
                return exc.codigo
        self._cal, self._aviso_calendario = cargar_calendario(self._base)
        return None

    def en_pruebas(self, curso: int) -> dict:
        resultado = publicar_con(
            self._aula,
            "pruebas",
            curso,
            self._documentos,
            self._visible,
            self._base,
            self._presencia,
            debug=self._debug,
            solo_fechas=self._solo_fechas,
        )
        assert resultado.informe is not None
        return resultado.informe

    def en_curso(self, turno: recorrido.Turno) -> recorrido.Resultado:
        curso = turno.curso
        try:
            estructura = self._aula.estructura(curso)
        except ErrorPublicacion as exc:
            return recorrido.Resultado.fallo(exc.codigo)
        # Lo que se rechaza por su origen sale con su código y no entra en lo que se confirma.
        try:
            vigilancia = Vigilancia.de(
                self._aula,
                self._base / rutas.CARPETA_TRABAJO,
                curso,
                self._documentos,
                real=True,
            )
        except estado.ErrorEstado as exc:
            return recorrido.Resultado.fallo(exc.codigo)
        a_publicar, _ = _separar_rechazados(
            self._documentos, estructura, self._base, self._solo_fechas, vigilancia
        )
        ids = {id(doc) for doc in a_publicar}
        # Dónde irán sus notas en el calificador; lo que se enseña es lo que se confirma.
        notas: tuple[CambioNota, ...] = ()
        notas_confirmadas: dict[Path, str | None] | None = None
        if a_publicar and not self._solo_fechas:
            notas, notas_confirmadas = _notas_previstas(
                self._aula, curso, estructura, a_publicar, self._base, debug=self._debug
            )
        # Lo que el docente retocó a mano en el aula; se le pregunta tras su sí de siempre.
        cambiadas: tuple[Documento, ...] = ()
        if not a_publicar:
            confirmado = True  # nada que confirmar: publicar_con solo informa de los rechazos
        elif self._solo_fechas:
            codigo = codigo_solo_fechas(estructura, a_publicar, curso)
            if codigo is not None:
                return recorrido.Resultado.fallo(codigo)
            cambiadas = vigilancia.retoques(estructura, a_publicar, solo_fechas=True)
            resumen = resumen_solo_fechas(
                self._aula,
                curso,
                turno.nombre_curso,
                a_publicar,
                self._base,
                estructura,
                debug=self._debug,
                posicion=turno.posicion,
                total=turno.total,
            )
            confirmado = turno.preguntar(lambda presencia: presencia.confirmar_real(resumen))
        elif self._sin_pruebas:
            cambiadas = vigilancia.retoques(estructura, a_publicar)
            corto = ResumenSinPruebas(
                curso=curso,
                nombre_curso=turno.nombre_curso,
                documentos=tuple(
                    DocumentoBreve(
                        fichero=doc.ruta.name,
                        tipo=doc.tipo,
                        nombre=doc.nombre,
                        existe=estructura.ya_existe(doc, curso),
                        itinerario=itinerario_de(doc, self._base),
                        borrada=estructura.localizar(doc, curso).borrada,
                    )
                    for doc in a_publicar
                ),
                secciones_nuevas=tuple(estructura.secciones_que_faltan(a_publicar)),
                posicion=turno.posicion,
                total=turno.total,
                movimientos=cambios_de_seccion(estructura, a_publicar, curso),
                nombres=cambios_de_nombre(estructura, a_publicar, curso),
                notas=notas,
            )
            confirmado = turno.preguntar(
                lambda presencia: presencia.confirmar_real_sin_pruebas(corto)
            )
        else:
            cambiadas = vigilancia.retoques(estructura, a_publicar)
            resumen = ResumenPublicacion(
                curso=curso,
                nombre_curso=turno.nombre_curso,
                documentos=tuple(
                    DocumentoResumen.de(
                        doc,
                        self._base,
                        vista,
                        cambios=cambios_de_fechas(
                            self._aula,
                            estructura,
                            doc,
                            self._cal,
                            debug=self._debug,
                            curso=curso,
                        ),
                        borrada=estructura.localizar(doc, curso).borrada,
                    )
                    for doc, vista in zip(self._documentos, self._vistas, strict=True)
                    if id(doc) in ids
                ),
                secciones_nuevas=tuple(estructura.secciones_que_faltan(a_publicar)),
                visible=self._visible,
                aviso_calendario=self._aviso_calendario,
                posicion=turno.posicion,
                total=turno.total,
                movimientos=cambios_de_seccion(estructura, a_publicar, curso),
                nombres=cambios_de_nombre(estructura, a_publicar, curso),
                notas=notas,
            )
            confirmado = turno.preguntar(lambda presencia: presencia.confirmar_real(resumen))
        if not confirmado:
            return recorrido.Resultado.declinado()
        rubrica_confirmada = self._preguntar_rubricas(turno, estructura, a_publicar)
        evidencia_confirmada = self._preguntar_evidencia(turno, estructura, a_publicar)
        sobrescribir, no_publicar = self._preguntar_sobrescribir(turno, cambiadas)
        return publicar_con(
            self._aula,
            "real",
            curso,
            self._documentos,
            None if self._solo_fechas else self._visible,
            self._base,
            self._presencia,
            debug=self._debug,
            solo_fechas=self._solo_fechas,
            sobrescribir=sobrescribir,
            no_publicar=no_publicar,
            notas_confirmadas=notas_confirmadas,
            rubrica_confirmada=rubrica_confirmada,
            evidencia_confirmada=evidencia_confirmada,
        )

    def _preguntar_evidencia(
        self, turno: recorrido.Turno, estructura: Estructura, documentos: list[Documento]
    ) -> bool:
        """Pregunta por las tareas que ya tienen notas y ganan resultados (D11).

        Una respuesta por curso, después de la confirmación normal. Solo entran las tareas con
        ``evidencia: resultados`` que existen en el aula, tienen notas y aún no marcan ninguno de
        sus resultados; las que ya los marcan no se vuelven a preguntar. Sin tareas con evidencia
        no se consultan los resultados del aula; sin resultados activos no se pregunta: no se va
        a escribir nada de resultados.
        """
        if self._solo_fechas:
            return False
        if not any(doc.evidencia == "resultados" for doc in documentos):
            return False
        tareas: list[str] = []
        try:
            if not self._aula.resultados_activos(turno.curso):
                return False
            for doc in documentos:
                if doc.evidencia != "resultados" or doc.evalua is None:
                    continue
                modulo = estructura.localizar(doc, turno.curso).modulo
                if modulo is None:
                    continue
                if _tarea_con_notas_sin_resultados(self._aula, turno.curso, doc, modulo.cmid):
                    tareas.append(doc.nombre)
        except ErrorPublicacion as exc:
            depurar(exc, self._debug)
            return False
        if not tareas:
            return False
        resumen = ResumenEvidencia(
            curso=turno.curso,
            nombre_curso=turno.nombre_curso,
            tareas=tuple(tareas),
            posicion=turno.posicion,
            total=turno.total,
        )
        return turno.preguntar(
            lambda presencia: presencia.confirmar_evidencia(resumen), tras_no=True
        )

    def _preguntar_rubricas(
        self, turno: recorrido.Turno, estructura: Estructura, documentos: list[Documento]
    ) -> bool:
        """Pregunta por las tareas existentes que ganan rúbrica; sin tareas, no pregunta.

        La respuesta es una sola para todo el lote: con «no», todas las tareas existentes
        conservan su método y su rúbrica (``RUBRICA_NO_ACTIVADA``) y se publica el resto.
        Las tareas nuevas no entran en la lista: su rúbrica no necesita confirmación.
        """
        if self._solo_fechas:
            return False
        tareas = tuple(
            doc.nombre
            for doc in documentos
            if doc.tipo == "tarea"
            and doc.rubrica is not None
            and estructura.localizar(doc, turno.curso).modulo is not None
        )
        if not tareas:
            return False
        resumen = ResumenRubricas(
            curso=turno.curso,
            nombre_curso=turno.nombre_curso,
            tareas=tareas,
            posicion=turno.posicion,
            total=turno.total,
        )
        return turno.preguntar(
            lambda presencia: presencia.confirmar_rubricas(resumen), tras_no=True
        )

    def _preguntar_sobrescribir(
        self, turno: recorrido.Turno, cambiadas: tuple[Documento, ...]
    ) -> tuple[frozenset[Path], frozenset[Path]]:
        """(``sobrescribir``, ``no_publicar``) tras preguntar por los retoques a mano.

        Sin ``cambiadas`` no se pregunta. Con el «no» se publica el resto del lote, así que
        la vigencia se mira también tras esa respuesta (``tras_no``).
        """
        if not cambiadas:
            return frozenset(), frozenset()
        rutas_cambiadas = frozenset(doc.ruta.resolve() for doc in cambiadas)
        resumen = ResumenSobrescribir(
            curso=turno.curso,
            nombre_curso=turno.nombre_curso,
            actividades=tuple(doc.nombre for doc in cambiadas),
            posicion=turno.posicion,
            total=turno.total,
        )
        if turno.preguntar(
            lambda presencia: presencia.confirmar_sobrescribir(resumen),
            tras_no=True,
        ):
            return rutas_cambiadas, frozenset()
        return frozenset(), rutas_cambiadas


def _con_secciones_nuevas(estructura: Estructura, documentos: list[Documento]) -> Estructura:
    """La estructura con, al final, las secciones por nombre que publicar va a crear.

    Solo para prever: se numeran tras la última y llevan un id negativo que no es de ningún
    aula. Así la nota de una actividad en una sección que aún no existe también se anuncia.
    """
    faltan = estructura.secciones_que_faltan(documentos)
    ultimo = max((seccion.numero for seccion in estructura), default=0)
    return Estructura(
        (
            *estructura.secciones,
            *(
                Seccion(numero=ultimo + indice, nombre=nombre, id=-indice)
                for indice, nombre in enumerate(faltan, start=1)
            ),
        )
    )


def _notas_previstas(
    aula: AulaVirtual,
    curso: int,
    estructura: Estructura,
    documentos: list[Documento],
    base: Path,
    *,
    debug: bool = False,
) -> tuple[tuple[CambioNota, ...], dict[Path, str | None]]:
    """Dónde irán las notas de lo que ``documentos`` crea o cambia de sección.

    Devuelve lo que se enseña al docente y, por ruta resuelta del documento, el eid de la
    categoría prevista (``None``: no se coloca), que ``publicar_con`` comprueba al escribir.
    Si el calificador no se puede leer no se enseña nada (``publicar_con`` lo avisará).
    """
    ordenados = ordenar_por_dependencias(documentos, base) or documentos
    candidatos = [
        doc for doc in ordenados if tipos.obtener(doc.tipo).tiene_nota(doc) and doc.evalua is None
    ]
    prevista = _con_secciones_nuevas(estructura, documentos)
    nuevas: list[tuple[int, int, str]] = []
    movidas: list[tuple[int, int]] = []
    claves: dict[int, Documento] = {}  # clave simulada o cmid -> documento
    for doc in candidatos:
        seccion = prevista.buscar_seccion(doc.seccion)
        if seccion is None:
            continue
        if estructura.desde_donde_se_mueve(doc, curso) is not None:
            actividad = estructura.localizar(doc, curso).actividad
            if actividad is not None:
                movidas.append((actividad.cmid, seccion.id))
                claves[actividad.cmid] = doc
        elif estructura.ya_existe(doc, curso) is False:
            clave = colocacion.NUEVA - len(nuevas)
            nuevas.append((clave, seccion.id, doc.nombre))
            claves[clave] = doc
    if not claves:  # nada que crear ni mover de sección: el calificador no se toca
        return (), {}
    try:
        arbol = aula.arbol_notas(curso)
    except ErrorPublicacion as exc:
        depurar(exc, debug)
        return (), {}
    movimientos, sin_colocar = colocacion.prever(prevista, arbol, nuevas, movidas)
    nombres = {f"ig{clave}": nombre for clave, _, nombre in nuevas}

    def nombre_de(eid: str) -> str:
        fila = arbol.fila(eid)
        return nombres.get(eid) or (fila.nombre if fila is not None else "")

    por_clave: dict[int, CambioNota] = {}
    confirmadas: dict[Path, str | None] = {}
    for mov in movimientos:
        doc = claves[mov.cmid]
        por_clave[mov.cmid] = CambioNota(
            fichero=doc.ruta.name,
            destino=mov.nombre_categoria,
            despues_de=nombre_de(mov.despues_de) if mov.despues_de is not None else None,
            desde=mov.desde,
            motivo=None,
        )
        confirmadas[doc.ruta.resolve()] = mov.categoria
    for sin in sin_colocar:
        doc = claves[sin.cmid]
        por_clave[sin.cmid] = CambioNota(
            fichero=doc.ruta.name,
            destino=None,
            despues_de=None,
            desde=None,
            motivo=sin.motivo,
            categoria=sin.categoria,
        )
        confirmadas[doc.ruta.resolve()] = None
    # En el orden de los documentos, no en el del cálculo.
    cambios = tuple(por_clave[clave] for clave in claves if clave in por_clave)
    return cambios, confirmadas


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
    arbol: colocacion.ArbolNotas | None = None,
) -> ResumenOrden | None:
    """Lo que cambiaría ``ordenar`` en este curso, o ``None`` si ya está en el orden pedido.

    Con el ``arbol`` del calificador cuenta también las notas que se reordenarían sobre la
    estructura final (las de los documentos sin ``evalua``); sin él, ninguna.

    Solo lectura. Las actividades que no son de tiza salen con su nombre del aula: es la pantalla
    del docente y necesita ver dónde queda cada cosa. ``ErrorPublicacion`` si algo no se resuelve
    (``ACTIVIDAD_AUSENTE``…): se mira antes de mover nada.
    """
    resolucion = estructura.resolver_orden(documentos, curso)
    publicar._convertir(resolucion.problema)
    grupos = resolucion.grupos
    deseados = [(seccion.id, [actividad.cmid for _, actividad in par]) for seccion, par in grupos]
    cambiadas = {mov.seccion_id for mov in publicar.plan_de_orden(estructura, deseados)}
    finales: dict[int, list[int]] = {
        seccion.id: publicar.orden_final(
            list(seccion.cmids), [actividad.cmid for _, actividad in par]
        )
        for seccion, par in grupos
        if seccion.id in cambiadas
    }
    notas = 0
    if arbol is not None:
        cmids_con_nota = _cmids_con_nota(grupos)
        notas = len(
            colocacion.reordenar(
                publicar.con_orden_final(estructura, finales), arbol, list(cmids_con_nota)
            )
        )
    if not cambiadas and not notas:
        return None
    pedidos = {
        _relativa(doc.ruta, base): actividad.cmid for _, par in grupos for doc, actividad in par
    }
    ficheros_de = {actividad.cmid: doc.ruta.name for _, par in grupos for doc, actividad in par}
    vistas: list[SeccionOrden] = []
    for seccion, _ in grupos:
        if seccion.id not in cambiadas:
            continue
        final = finales[seccion.id]
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
        notas=notas,
    )


def _cmids_con_nota(
    grupos: Iterable[tuple[Any, Iterable[tuple[Documento, Any]]]],
) -> dict[int, str]:
    """Cmid y fichero de los documentos cuya nota sigue el orden del curso.

    Los que no llevan ``evalua`` (esa es del calificador de tiza); si no tienen elemento en el
    calificador, la regla pura no los encuentra y no se mueve nada.
    """
    return {
        actividad.cmid: doc.ruta.name
        for _, par in grupos
        for doc, actividad in par
        if doc.evalua is None
    }


def ordenar_con(
    aula: AulaVirtual,
    entorno: str,
    curso: int,
    documentos: list[Documento],
    *,
    debug: bool = False,
    notas_confirmadas: int | None = None,
) -> dict:
    """Con el aula ya abierta: deja las actividades de ``documentos`` en ese orden y lo verifica.

    ``notas_confirmadas`` (curso real): cuántas notas del calificador vio mover el docente en
    el resumen. Con 0 no se toca el calificador; si salen otras, no se mueve ninguna
    (``NOTA_SIN_COLOCAR`` con ``CAMBIADA``). ``None``: sin esa comprobación (curso de pruebas).
    """
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
    _ordenar_notas(aula, curso, estructura, documentos, borrador, debug, notas_confirmadas)
    return borrador.documento()


def _ordenar_notas(
    aula: AulaVirtual,
    curso: int,
    estructura: Estructura,
    documentos: list[Documento],
    borrador: informe.Borrador,
    debug: bool,
    notas_confirmadas: int | None = None,
) -> None:
    """Reordena en el calificador las notas de lo ordenado; nunca hace fallar el orden.

    Salvo los documentos con ``evalua`` (su nota es del calificador de tiza). Un error al
    leer o mover queda como ``NOTA_SIN_COLOCAR`` con su código, uno por documento.
    """
    cmids = _cmids_con_nota(estructura.resolver_orden(documentos, curso).grupos)
    if not cmids or notas_confirmadas == 0:
        return
    try:
        movidas = publicar.ordenar_notas(
            aula, curso, aula.estructura(curso), list(cmids), notas_confirmadas
        )
    except ErrorPublicacion as exc:
        depurar(exc, debug)
        for nombre in cmids.values():
            borrador.paso("NOTA_SIN_COLOCAR", detalle=f"{nombre}: {exc.codigo}")
        return
    if movidas:
        borrador.paso("NOTAS_ORDENADAS", detalle=f"{movidas} {'nota' if movidas == 1 else 'notas'}")


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
    return recorrido.recorrer(
        _TrabajoOrdenar(aula, entorno, documentos, base, debug=debug),
        cfg,
        presencia,
        entorno=entorno,
        vigente=vigente,
        cupo=cupo,
        avisar_en_pruebas=avisar_en_pruebas,
        omitidos=omitidos,
        nombres=nombres,
    )


class _TrabajoOrdenar(recorrido.TrabajoBase):
    """Lo que ordenar hace en un curso; el bucle y las preguntas son del recorrido."""

    comando = "ordenar"

    def __init__(
        self,
        aula: AulaVirtual,
        entorno: str,
        documentos: list[Documento],
        base: Path,
        *,
        debug: bool,
    ) -> None:
        self._aula = aula
        self._entorno = entorno
        self._documentos = documentos
        self._base = base
        self._debug = debug

    def aviso_en_pruebas(self) -> Aviso:
        return Aviso.ordenando_en_pruebas(
            tuple(DocumentoBreve(doc.ruta.name, doc.tipo, doc.nombre) for doc in self._documentos)
        )

    def en_pruebas(self, curso: int) -> dict:
        return ordenar_con(self._aula, self._entorno, curso, self._documentos, debug=self._debug)

    def en_curso(self, turno: recorrido.Turno) -> recorrido.Resultado:
        try:
            estructura = self._aula.estructura(turno.curso)
            try:
                arbol = self._aula.arbol_notas(turno.curso)
            except ErrorPublicacion:
                arbol = None  # sin calificador legible no se cuentan notas; ordenar sigue
            resumen = resumen_orden(
                turno.curso,
                turno.nombre_curso,
                estructura,
                self._documentos,
                self._base,
                posicion=turno.posicion,
                total=turno.total,
                arbol=arbol,
            )
        except ErrorPublicacion as exc:
            # Cada curso resuelve lo suyo antes de mover nada en él (ACTIVIDAD_AUSENTE…).
            return recorrido.Resultado.fallo(exc.codigo)
        if resumen is not None and not turno.preguntar(
            lambda presencia: presencia.confirmar_orden(resumen)
        ):
            return recorrido.Resultado.declinado()
        # Sin cambios no hay nada que confirmar: se informa de ``sin_cambios`` sin tocar el aula.
        # Solo se mueven las notas que el docente vio: ninguna si no se pudieron contar.
        vistas = resumen.notas if resumen is not None else 0
        documento = ordenar_con(
            self._aula,
            self._entorno,
            turno.curso,
            self._documentos,
            debug=self._debug,
            notas_confirmadas=vistas,
        )
        return recorrido.Resultado.hecho(documento)


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

    Se encuentran como en ``ordenar`` (``origen`` en su curso, o sección, tipo y nombre), también
    si la actividad está en otra sección con la sección del documento cambiada. ``ACTIVIDAD_AMBIGUA``
    si dos ficheros apuntan a la misma actividad o una se repite: colocar la equivocada cambiaría
    una nota sin que nadie lo viera.
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
        modulo = loc.modulo
        if modulo is None:
            continue
        cmid = modulo.cmid
        if loc.varios or cmid in vistos:
            raise ErrorPublicacion("ACTIVIDAD_AMBIGUA", ruta)
        vistos.add(cmid)
        cmids[ruta] = cmid
    return cmids


def _resultados_para_calificador(
    aula: AulaVirtual,
    curso: int,
    esquema: Esquema,
    documentos: list[Documento],
    base: Path,
    sin_resultados: Collection[str] = (),
) -> tuple[dict[str, int], bool, tuple[tuple[str, str], ...]]:
    """La escala y los resultados del curso para las tareas con evidencia (D8, D9, D12).

    Solo asegura las tareas que **no** están en ``sin_resultados`` (las que el docente declinó
    en D11). Devuelve ``(clave -> id del resultado, resultados_desactivados, descriptores ya
    publicados)``; el último son pares ``(tarea, fila)`` cuya escala no se ha tocado (D-F2-7).
    Se llama **después** de que el docente confirme el calificador: ``preparar_calificador`` no
    escribe nada. Sin resultados activos no se escribe nada y el segundo valor es verdadero
    para que el informe lo cuente (``RESULTADOS_DESACTIVADOS``); el calificador sigue montando
    el resto.
    """
    if not any(doc.evidencia == "resultados" for doc in documentos):
        return {}, False, ()
    if not aula.resultados_activos(curso):
        return {}, True, ()
    escala: int | None = None
    resultados: dict[str, int] = {}
    publicados: list[tuple[str, str]] = []
    for doc in documentos:
        if doc.evidencia != "resultados" or doc.evalua is None:
            continue
        if _ruta_de(doc, base) in sin_resultados:
            continue
        if doc.rubrica_filas is not None:
            for fila in doc.rubrica_filas.filas:
                if fila.clave in resultados:
                    continue
                escala_fila, publicado = _asegurar_escala_de_fila(aula, curso, fila)
                if publicado:
                    publicados.append((doc.nombre, fila.indicador))
                resultados[fila.clave] = aula.asegurar_resultado(
                    curso,
                    f"TZ_{fila.clave}",
                    nombre_de_fila(esquema, fila),
                    descripcion_de_fila(esquema, fila),
                    escala_fila,
                )
            continue
        if escala is None:
            escala = aula.asegurar_escala(curso, ESCALA_LOGRO, niveles_de_escala(esquema))
        for criterio, _ in doc.evalua:
            if criterio in resultados:
                continue
            resultados[criterio] = aula.asegurar_resultado(
                curso,
                f"TZ_{criterio}",
                nombre_de_hoja(esquema, criterio),
                descripcion_de_resultado(esquema, criterio),
                escala,
            )
    return resultados, False, tuple(publicados)


def _resultados_existentes(
    aula: AulaVirtual,
    curso: int,
    documentos: list[Documento],
    cmids: dict[str, int],
    base: Path,
) -> tuple[dict[str, int], frozenset[str], bool]:
    """(criterio -> id, rutas con resultados efectivos, hay algo pendiente). Solo lee.

    Una tarea tiene resultados efectivos si está en el aula y marca **todos** sus resultados
    propios, con sus definiciones ya existentes. Si los resultados están desactivados no se lee
    nada y no se marca nada como pendiente: ``calificador_con`` dejará ``RESULTADOS_DESACTIVADOS``.
    """
    con_evidencia = [
        doc for doc in documentos if doc.evidencia == "resultados" and doc.evalua is not None
    ]
    if not con_evidencia:
        return {}, frozenset(), False
    if not aula.resultados_activos(curso):
        return {}, frozenset(), False
    resultados: dict[str, int] = {}
    vistos: set[str] = set()
    efectivas: set[str] = set()
    pendientes = False
    for doc in con_evidencia:
        propios: list[int] = []
        for clave, _criterio in resultados_de_tarea(doc):
            if clave not in vistos:
                vistos.add(clave)
                encontrado = aula.resultado_por_corto(curso, f"TZ_{clave}")
                if encontrado is not None:
                    resultados[clave] = encontrado
            if clave in resultados:
                propios.append(resultados[clave])
        ruta = _ruta_de(doc, base)
        cmid = cmids.get(ruta)
        marcados = aula.campos_resultado_tarea(cmid) if cmid is not None else {}
        if cmid is not None and propios and all(marcados.get(id_) for id_ in propios):
            efectivas.add(ruta)
        else:
            pendientes = True
    return resultados, frozenset(efectivas), pendientes


def preparar_calificador(
    aula: AulaVirtual,
    curso: int,
    esquema: Esquema,
    documentos: list[Documento],
    dir_tiza: Path,
) -> PlanCalificador:
    """Lee el curso y calcula qué hay que hacer en su calificador. No escribe nada en el aula.

    Con tareas de ``evidencia: resultados`` lee (sin crear) el id de cada resultado
    ``TZ_<criterio>`` y lo pasa a la reconciliación: si la definición existe pero su elemento del
    calificador se borró, el plan ya incluye ``marcar_resultado`` y el docente lo confirma. Si
    falta alguna definición, ``resultados_pendientes`` hace que se pregunte igualmente; la
    asegura ``calificador_con`` después del «sí».

    ``ErrorPublicacion`` si el aula no deja leer, ``ErrorCalificacion`` si las actividades no
    cuadran con el esquema y ``ErrorEstado`` si ``.tiza/calificador.json`` no vale.
    """
    base = Path(dir_tiza).parent
    huellas = estado.cargar_huellas(dir_tiza, curso)
    contados = [doc for doc in documentos if doc.evalua is not None]
    cmids = _cmids_de(aula.estructura(curso), contados, curso, base)
    actual = aula.calificador(curso)
    if any(nodo.idnumber.startswith(ponderacion.PREFIJO_IDNUMBER) for nodo in actual.nodos):
        raise ErrorPublicacion("CALIFICADOR_CON_PONDERACION")
    opciones = next(
        (
            nodo.opciones_agregacion
            for nodo in actual.nodos
            if nodo.clase in ("curso", "categoria") and nodo.opciones_agregacion
        ),
        None,
    )
    if opciones is not None and 10 not in opciones:
        raise ErrorPublicacion("CALCULO_NO_DISPONIBLE")
    if rc.es_calificador_antiguo(actual):
        raise ErrorPublicacion("CALIFICADOR_ANTIGUO")
    if estado.version_de_calificador(dir_tiza) == 1 and huellas:
        # El docente borró a mano el árbol viejo: su huella ya no describe nada. Si aún
        # estuviera, ``es_calificador_antiguo`` habría cortado antes.
        estado.olvidar_huellas(dir_tiza, curso)
        huellas = {}
    anterior = rc.hay_anterior(actual)
    resultados, efectivas, pendientes = _resultados_existentes(aula, curso, documentos, cmids, base)
    deseado = calcular_deseado(esquema, documentos, anterior, base, resultados=efectivas)
    return PlanCalificador(
        curso=curso,
        aula_antes=actual,
        deseado=deseado,
        reconciliacion=rc.reconciliar(deseado, actual, huellas, cmids, resultados=resultados),
        cmids=cmids,
        huellas=huellas,
        documentos=tuple(contados),
        base=base,
        resultados=resultados,
        documentos_con_resultados=efectivas,
        resultados_pendientes=pendientes,
        ajuste_totales=aula.ajuste_totales(curso),
        ponderaciones_visibles=aula.ponderaciones_visibles(curso),
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
    if codigo == "PESOS_SIN_EFECTO":
        return Aviso.pesos_sin_efecto(clave)
    if codigo == "RECUPERACION_EN_CERRADA":
        de_la_carpeta = next((n.nombre for n in plan.deseado.nodos if n.idnumber == clave), None)
        return Aviso.recuperacion_en_cerrada(de_la_carpeta or nombres.get(clave, clave))
    if codigo == "REGLA_CAMBIADA":
        return Aviso.regla_cambiada(clave)
    if codigo == "EVIDENCIA_COMPARTIDA":
        documento = next((d for d in plan.documentos if d.nombre == clave), None)
        return Aviso.evidencia_compartida(clave, tipo=documento.tipo if documento else None)
    if codigo in ("RESULTADO_CON_NOTAS_QUITADO", "RESULTADO_RECREADO"):
        de_la_carpeta = next((n.nombre for n in plan.deseado.nodos if n.idnumber == clave), None)
        texto = de_la_carpeta or nombres.get(clave, clave)
        if codigo == "RESULTADO_CON_NOTAS_QUITADO":
            return Aviso.resultado_con_notas_quitado(texto)
        return Aviso.resultado_recreado(texto)
    return None  # TOTAL_AJENO_BLOQUEADO ya sale en «se bloquean los totales de…»; CALCULADOS_OCULTADOS, en su recuento


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
    if plan.ajuste_totales in (1, 2):
        avisos.append(Aviso.totales_visibles())
    if plan.ponderaciones_visibles:
        avisos.append(Aviso.ponderaciones_visibles())

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
        ocultadas=sum(1 for op in operaciones if op.tipo == "ocultar"),
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
    """La segunda pasada sobre el aula releída: los ajustes que falten y, al final, los cierres.

    La media ponderada no reescala los coeficientes al añadir hermanos, así que una sola pasada
    de ajustes basta. Solo se repite si Moodle rechazó una fórmula entre categorías recién
    creadas (``formulas_pendientes``), con un tope pequeño. Los repasos no bloquean nada: los
    cierres van al final, con todo estable. Cada ejecución se añade a ``segundas``.
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
            resultados=plan.resultados,
        )

    def ejecutar(
        leida: CalificadorAula, ajustes: tuple[rc.Operacion, ...], *, tolerar: bool
    ) -> CalificadorAula:
        segunda = Ejecucion(aula, curso, leida.decimal)
        segundas.append(segunda)
        segunda.ejecutar(ajustes, tolerar_formulas=tolerar)
        return aula.calificador(curso, segunda.tocados)

    for _ in range(MAX_PASADAS_DE_FORMULAS):
        ajustes = ajustes_de(final, frozenset())
        if not ajustes:
            break
        final = ejecutar(final, ajustes, tolerar=True)
        if not segundas[-1].formulas_pendientes:
            break
    cierres = ajustes_de(final, rec.por_cerrar)
    return ejecutar(final, cierres, tolerar=False) if cierres else final


MAX_IDS_POR_TIPO = 4  # en el desglose de los cambios: los primeros números de ID de cada tipo


def desglose_de_cambios(operaciones: list[rc.Operacion]) -> str:
    """Los cambios del calificador por tipo, con los primeros números de ID de tiza de cada uno.

    Sirve para ver qué se repite cuando un montaje no converge. Solo lleva el tipo de operación y
    números de ID ``TZ_…``, que pone tiza: nunca nombres ni textos del aula.
    """
    cuantos: dict[str, int] = {}
    ids: dict[str, list[str]] = {}
    for op in operaciones:
        cuantos[op.tipo] = cuantos.get(op.tipo, 0) + 1
        idnumber = op.idnumber or ""
        lista = ids.setdefault(op.tipo, [])
        if idnumber.startswith("TZ_") and idnumber not in lista:
            lista.append(idnumber)
    partes = []
    for tipo in sorted(cuantos):
        texto = f"{tipo}: {cuantos[tipo]}"
        lista = ids[tipo]
        if lista:
            resto = ", …" if len(lista) > MAX_IDS_POR_TIPO else ""
            texto += f" ({', '.join(lista[:MAX_IDS_POR_TIPO])}{resto})"
        partes.append(texto)
    return "; ".join(partes)


def calificador_con(
    aula: AulaVirtual,
    entorno: str,
    curso: int,
    esquema: Esquema,
    documentos: list[Documento],
    dir_tiza: Path,
    *,
    plan: PlanCalificador | None = None,
    presencia: Presencia | None = None,
    evidencia_confirmada: bool = False,
    sin_resultados: Collection[str] = (),
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

    ``preparar_calificador`` no escribe. Por defecto **no se activan** resultados nuevos
    (``evidencia_confirmada=False``): las tareas pendientes se montan como normales. Con el sí
    explícito se aseguran la escala y los resultados de las tareas que no estén en
    ``sin_resultados`` (las declinadas en D11) y se recalcula el árbol con esas rutas. Si el sitio
    tiene los resultados desactivados, no se escribe nada de resultados, el árbol es normal y
    queda ``RESULTADOS_DESACTIVADOS`` (D12).
    """
    borrador = informe.Borrador("calificador", entorno=entorno, curso=curso)
    borrador.paso("LOGIN")
    dir_tiza = Path(dir_tiza)
    try:
        plan = plan or preparar_calificador(aula, curso, esquema, documentos, dir_tiza)
        declinadas = frozenset(sin_resultados)
        resultados: dict[str, int]
        efectivas: frozenset[str]
        desactivados: bool
        descriptores_publicados: tuple[tuple[str, str], ...] = ()
        if not any(doc.evidencia == "resultados" for doc in documentos):
            # Sin tareas con evidencia no se toca nada de resultados: ni se consulta el aula.
            resultados, efectivas, desactivados = {}, frozenset(), False
        elif not aula.resultados_activos(curso):
            resultados, efectivas, desactivados = {}, frozenset(), True
        elif not evidencia_confirmada:
            resultados = dict(plan.resultados)
            efectivas = plan.documentos_con_resultados - declinadas
            desactivados = False
        else:
            resultados, desactivados, descriptores_publicados = _resultados_para_calificador(
                aula, curso, esquema, documentos, plan.base, declinadas
            )
            efectivas = (
                frozenset(
                    ruta
                    for doc in documentos
                    if doc.evidencia == "resultados"
                    and doc.evalua is not None
                    and (ruta := _ruta_de(doc, plan.base)) not in declinadas
                )
                if not desactivados
                else frozenset()
            )
        deseado = calcular_deseado(
            esquema, documentos, plan.reconciliacion.anterior, plan.base, resultados=efectivas
        )
        plan = replace(
            plan,
            deseado=deseado,
            reconciliacion=rc.reconciliar(
                deseado,
                plan.aula_antes,
                plan.huellas,
                plan.cmids,
                resultados=resultados,
            ),
            resultados=resultados,
            documentos_con_resultados=efectivas,
        )
    except (ErrorPublicacion, ErrorCalificacion, ErrorEstado) as exc:
        borrador.fallo("CALIFICADOR", exc.codigo)
        borrador.error(exc.codigo)
        depurar(exc, debug)
        return borrador.documento("error")
    if desactivados:
        borrador.paso("RESULTADOS_DESACTIVADOS")
        if presencia is not None:
            for doc in documentos:
                if doc.evidencia == "resultados":
                    presencia.informar(Aviso.resultados_desactivados(doc.nombre))
    if descriptores_publicados:
        borrador.paso("DESCRIPTOR_PUBLICADO", detalle=str(len(descriptores_publicados)))
        if presencia is not None:
            for nombre, fila in descriptores_publicados:
                presencia.informar(Aviso.descriptor_publicado(nombre, fila))
    if esquema.final.tope is not None:
        borrador.paso("TOPE", detalle=detalle_tope(plan.deseado))
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
            borrador.paso("CALIFICADOR_CAMBIOS", detalle=desglose_de_cambios(hechas_antes))
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
    if hechas_todas:
        borrador.paso("CALIFICADOR_CAMBIOS", detalle=desglose_de_cambios(hechas_todas))
    bloqueos = sum(1 for op in hechas_todas if op.tipo in TIPOS_DE_BLOQUEO)
    if bloqueos:
        borrador.paso("CALIFICADOR_BLOQUEAR", detalle=str(bloqueos))
    colocadas = {op.ruta for op in hechas_todas if op.tipo == "colocar"}
    if colocadas:
        borrador.paso("CALIFICADOR_COLOCAR", detalle=str(len(colocadas)))
    if plan.ajuste_totales in (1, 2):
        borrador.paso("TOTALES_VISIBLES")
        if presencia is not None:
            presencia.informar(Aviso.totales_visibles())
    if plan.ponderaciones_visibles:
        borrador.paso("PONDERACIONES_VISIBLES")
        if presencia is not None:
            presencia.informar(Aviso.ponderaciones_visibles())
    ocultados = sum(1 for op in hechas_todas if op.tipo == "ocultar")
    avisos = [*rec.avisos, *plan.deseado.avisos]
    for codigo, cuantos in Counter(codigo for codigo, _ in avisos).items():
        if codigo == "CALCULADOS_OCULTADOS":  # un solo aviso, con el número de calculados
            if not ocultados:
                continue  # el aula los rechazó todos: lo cuenta OCULTAR_FALLIDO
            cuantos = ocultados
            if presencia is not None:
                presencia.informar(Aviso.calculados_ocultados(ocultados))
        borrador.paso(codigo, detalle=str(cuantos))
    # R1: privacidad. Lo que sigue visible en el aula final (un ocultado que no surtió efecto o
    # un alta que Moodle no guardó oculta) se avisa sin cortar el curso y sin reintentar.
    visibles = [n for n in final.nodos if rc.es_calculado_de_tiza(n) and not n.oculto]
    if visibles:
        borrador.fallo("OCULTAR_FALLIDO", str(len(visibles)))
        if presencia is not None:
            presencia.informar(Aviso.ocultar_fallido(len(visibles)))
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


@dataclass(frozen=True)
class PlanPonderacionCurso:
    """Lo leído del aula y el plan de ``ponderacion.yaml`` para un curso. No escribe nada.

    ``nombres`` son los nombres exactos con los que se relee el árbol de ponderación; ``tzp``
    es ``eid -> número de ID`` de las categorías ``TZP_`` que ya había en el aula.
    """

    curso: int
    esquema: EsquemaPonderacion
    estructura: Estructura
    arbol: ponderacion.ArbolPonderacion
    plan: ponderacion.PlanPonderacion
    huellas: dict[str, str]
    nombres: tuple[str, ...]
    tzp: dict[str, str]


MAX_PASADAS_DE_PESOS = 8  # repasos de los pesos en natural (Moodle reescala a los hermanos)
_TIPOS_DE_PONDERACION = ("crear", "mover", "metodo", "coeficiente")


def _nombres_de_ponderacion(esquema: EsquemaPonderacion) -> tuple[str, ...]:
    """Los nombres exactos que hay que abrir en el aula para planificar este esquema."""
    nuevas = {e.id for e in esquema.entradas if e.nueva}
    nombres: dict[str, None] = {}
    for entrada in esquema.entradas:
        if entrada.nueva:
            nombres[str(entrada.nombre)] = None
            if entrada.dentro_de not in nuevas:
                nombres[str(entrada.dentro_de)] = None
        else:
            nombres[str(entrada.categoria)] = None
        for elemento in entrada.elementos:
            referencia = elemento.referencia
            if referencia.clase == "fichero":
                if elemento.documento is not None:
                    nombres[elemento.documento.nombre] = None
            elif referencia.clase == "categoria" and referencia.nombre in nuevas:
                continue
            else:
                nombres[referencia.nombre] = None
    return tuple(nombres)


def _referencias_de_ponderacion(esquema: EsquemaPonderacion) -> frozenset[str]:
    return frozenset(
        [ponderacion.referencia_de(e) for e in esquema.entradas]
        + [ponderacion.referencia_de(el) for e in esquema.entradas for el in e.elementos]
    )


def preparar_ponderacion(
    aula: AulaVirtual,
    curso: int,
    esquema: EsquemaPonderacion,
    dir_tiza: Path,
) -> PlanPonderacionCurso:
    """Lee el curso y calcula qué hay que hacer para que cumpla ``esquema``. No escribe nada.

    ``ErrorPublicacion`` si el aula no deja leer, ``ErrorPonderacion`` si el esquema no cuadra con
    el aula (o el curso tiene el «Calificador de tiza») y ``ErrorEstado`` si
    ``.tiza/ponderacion.json`` no vale. Si el plan corta (``plan.corta``) no se debe ejecutar.
    """
    estructura = aula.estructura(curso)
    categorias = [fila.eid for fila in aula.arbol_notas(curso).filas if fila.eid.startswith("cg")]
    ids = aula.idnumbers_de(curso, categorias)
    tzp = {eid: valor for eid, valor in ids.items() if valor.startswith("TZP_")}
    nombres = _nombres_de_ponderacion(esquema)
    arbol = aula.arbol_ponderacion(curso, nombres)
    huellas = estado.cargar_huellas_ponderacion(dir_tiza, curso)
    plan = ponderacion.planificar(
        esquema,
        estructura,
        arbol,
        huellas,
        calificador_de_tiza=any(valor == "TZ_TIZA" for valor in ids.values()),
        tzp=tzp,
    )
    return PlanPonderacionCurso(curso, esquema, estructura, arbol, plan, huellas, nombres, tzp)


def _desglose_ponderacion(operaciones: Sequence[ponderacion.OperacionPonderacion]) -> str:
    """Los cambios por tipo (``crear: 1; mover: 4``): nunca nombres ni ids del aula."""
    cuantos = Counter(op.tipo for op in operaciones)
    return "; ".join(f"{tipo}: {cuantos[tipo]}" for tipo in _TIPOS_DE_PONDERACION if cuantos[tipo])


class _EjecucionPonderacion:
    """Las escrituras de un curso, con la traducción de ``nuevo:<id>`` al eid que dio el aula."""

    def __init__(self, aula: AulaVirtual, curso: int) -> None:
        self.aula = aula
        self.curso = curso
        self.reales: dict[str, str] = {}
        self.hechas: list[ponderacion.OperacionPonderacion] = []

    def real(self, eid: str | None) -> str | None:
        return self.reales.get(eid, eid) if eid is not None else None

    def ejecutar(self, operaciones: Iterable[ponderacion.OperacionPonderacion]) -> None:
        for op in operaciones:
            self._una(op)
            self.hechas.append(op)

    def _una(self, op: ponderacion.OperacionPonderacion) -> None:
        aula, curso = self.aula, self.curso
        if op.tipo == "crear":
            eid = aula.crear_categoria(
                curso,
                str(op.nombre),
                str(op.idnumber),
                self.real(op.padre),
                None,
                None,
                agregacion=int(op.agregacion if op.agregacion is not None else 13),
                solo_no_vacias=True if op.solo_no_vacias is None else op.solo_no_vacias,
                coeficiente=op.coeficiente,
            )
            self.reales[str(op.eid)] = eid
            # El aula ignora el coeficiente en el alta de una categoría (S1: nace a 0), así que
            # se fija justo después. Se anota como operación para verificarlo y dejar su huella.
            if op.coeficiente is not None:
                aula.fijar_coeficiente(curso, eid, op.coeficiente, "media_ponderada")
                self.hechas.append(
                    ponderacion.OperacionPonderacion(
                        "coeficiente",
                        op.referencia,
                        eid=eid,
                        coeficiente=op.coeficiente,
                        porcentaje=op.porcentaje,
                        metodo_del_padre="media_ponderada",
                    )
                )
        elif op.tipo == "mover":
            aula.mover_nota(
                curso, str(self.real(op.eid)), str(self.real(op.destino)), self.real(op.despues_de)
            )
        elif op.tipo == "metodo":
            aula.fijar_agregacion(
                curso, str(self.real(op.eid)), int(op.agregacion or 0), op.solo_no_vacias
            )
        else:
            aula.fijar_coeficiente(
                curso,
                str(self.real(op.eid)),
                float(op.coeficiente or 0.0),
                str(op.metodo_del_padre),
            )


def _pesos_en_natural(plan: ponderacion.PlanPonderacion) -> bool:
    return any(
        op.tipo == "coeficiente" and op.metodo_del_padre == "natural" for op in plan.operaciones
    )


def _repetir_pesos(
    aula: AulaVirtual,
    plan_curso: PlanPonderacionCurso,
    ejecucion: _EjecucionPonderacion,
) -> bool:
    """Repite los coeficientes hasta que el aula coincide con el plan; ``False`` si no converge.

    En natural Moodle reescala a los hermanos al guardar un peso, así que fijarlos de una vez no
    basta: se relee, se replanifica (con todo lo del esquema como «ya aceptado», para no tomar el
    reescalado por un cambio a mano) y se ejecutan solo los coeficientes que queden.
    """
    sobrescribir = _referencias_de_ponderacion(plan_curso.esquema) | set(plan_curso.huellas)
    for pasada in range(MAX_PASADAS_DE_PESOS + 1):
        arbol = aula.arbol_ponderacion(plan_curso.curso, plan_curso.nombres)
        tzp = dict(plan_curso.tzp)
        tzp.update(
            {
                real: f"TZP_{eid[len(ponderacion.PREFIJO_NUEVA) :]}"
                for eid, real in ejecucion.reales.items()
            }
        )
        try:
            nuevo = ponderacion.planificar(
                plan_curso.esquema,
                plan_curso.estructura,
                arbol,
                plan_curso.huellas,
                tzp=tzp,
                sobrescribir=sobrescribir,
            )
        except ErrorPonderacion:
            return False
        quedan = [op for op in nuevo.operaciones if op.tipo == "coeficiente"]
        if not quedan:
            return True
        if pasada == MAX_PASADAS_DE_PESOS:
            return False
        ejecucion.ejecutar(quedan)
    return False


def _nodo_final(
    arbol: ponderacion.ArbolPonderacion, eid: str | None
) -> ponderacion.NodoPonderacion | None:
    if eid is None:
        return None
    if eid.startswith(ponderacion.PREFIJO_NUEVA):
        idnumber = f"{ponderacion.PREFIJO_IDNUMBER}{eid[len(ponderacion.PREFIJO_NUEVA) :]}"
        return next((n for n in arbol.nodos if n.idnumber == idnumber), None)
    return arbol.nodo(eid)


def _eid_final(arbol: ponderacion.ArbolPonderacion, eid: str | None) -> str | None:
    nodo = _nodo_final(arbol, eid)
    return nodo.eid if nodo is not None else eid


def _aplicada(op: ponderacion.OperacionPonderacion, arbol: ponderacion.ArbolPonderacion) -> bool:
    """¿Lo que pidió la operación está en el aula releída?"""
    nodo = _nodo_final(arbol, op.eid)
    if nodo is None:
        return False
    if op.tipo == "crear":
        if nodo.padre_eid != _eid_final(arbol, op.padre):
            return False
    if op.tipo == "mover":
        return nodo.padre_eid == _eid_final(arbol, op.destino)
    if op.tipo in ("crear", "metodo"):
        if nodo.agregacion != op.agregacion:
            return False
        if op.solo_no_vacias is not None and nodo.solo_no_vacias != op.solo_no_vacias:
            return False
        if op.tipo == "metodo" or op.porcentaje is None:
            return True
    if op.porcentaje is None:
        return True
    efectivo = ponderacion.porcentaje_efectivo(nodo, arbol)
    return efectivo is not None and abs(efectivo - op.porcentaje) < ponderacion.TOLERANCIA_EFECTIVA


def _verificadas(
    hechas: Sequence[ponderacion.OperacionPonderacion], arbol: ponderacion.ArbolPonderacion
) -> list[str]:
    """Las referencias de las operaciones hechas que el aula no refleja, sin repetir."""
    ultimas: dict[tuple[str, str | None], ponderacion.OperacionPonderacion] = {}
    for op in hechas:
        ultimas[(op.tipo, op.eid)] = op  # de varias pasadas de pesos, cuenta la última
    fallidas: dict[str, None] = {}
    for op in ultimas.values():
        if not _aplicada(op, arbol):
            fallidas[op.referencia] = None
    return list(fallidas)


def _huellas_de_ponderacion(
    plan_curso: PlanPonderacionCurso,
    arbol: ponderacion.ArbolPonderacion,
    ejecucion: _EjecucionPonderacion,
    fallidas: Collection[str],
) -> dict[str, str]:
    """Las huellas de lo que el aula tiene ahora y está verificado; lo demás conserva la de antes."""
    plan = plan_curso.plan
    tzp = dict(plan_curso.tzp)
    tzp.update({n.eid: n.idnumber for n in arbol.nodos if n.idnumber.startswith("TZP_")})
    nodos = ponderacion.nodos_nombrados(plan_curso.esquema, plan_curso.estructura, arbol, tzp=tzp)
    pendientes = {op.referencia for op in plan.operaciones if op not in ejecucion.hechas}
    con_operacion = {op.referencia for op in plan.operaciones}
    a_mano = {c.referencia for c in plan.cambios_a_mano}
    nuevas: dict[str, str] = {}
    for referencia, nodo in nodos.items():
        antes = plan_curso.huellas.get(referencia)
        if referencia in fallidas or referencia in a_mano:
            verificada = False
        elif referencia in con_operacion:
            verificada = referencia not in pendientes
        else:
            verificada = _en_orden(nodo, arbol)
        if verificada:
            nuevas[referencia] = ponderacion.huella_nodo(nodo, arbol)
        elif antes is not None:
            nuevas[referencia] = antes
    return nuevas


def _en_orden(nodo: ponderacion.NodoPonderacion, arbol: ponderacion.ArbolPonderacion) -> bool:
    """Lo que el plan no toca solo cuenta como hecho si no está bloqueado ni sin método de pesos."""
    actual: ponderacion.NodoPonderacion | None = nodo
    while actual is not None:
        if actual.bloqueado:
            return False
        actual = arbol.nodo(actual.padre_eid) if actual.padre_eid else None
    padre = arbol.nodo(nodo.padre_eid) if nodo.padre_eid else None
    return padre is not None and padre.agregacion in (
        ponderacion.MEDIA_PONDERADA,
        ponderacion.NATURAL,
    )


def _guardar_huellas_ponderacion(
    dir_tiza: Path, plan_curso: PlanPonderacionCurso, nuevas: dict[str, str]
) -> None:
    if nuevas != plan_curso.huellas:
        estado.guardar_huellas_ponderacion(dir_tiza, plan_curso.curso, nuevas)


def ponderacion_con(
    aula: AulaVirtual,
    entorno: str,
    curso: int,
    plan_curso: PlanPonderacionCurso,
    dir_tiza: Path,
    *,
    presencia: Presencia | None = None,
    debug: bool = False,
) -> dict:
    """Con el aula ya abierta: aplica el plan de ponderación de ``curso`` y devuelve el informe.

    Las operaciones van en el orden del plan (crear, mover, método, coeficientes) y paran en seco
    ante el primer ``ErrorPublicacion`` (no se deshace nada: la pasada siguiente completa). Si
    algún reparto es natural, los coeficientes se repiten (con tope) porque Moodle reescala a los
    hermanos. Después se relee lo tocado, se comprueba operación por operación (lo que el aula
    no refleja es un ``PONDERACION_NO_APLICADA`` por su referencia, sin cortar) y solo lo
    verificado guarda su huella en ``.tiza/ponderacion.json``.

    No pregunta ni avisa: la confirmación y los avisos son del trabajo que lo llama.
    """
    borrador = informe.Borrador("calificador", entorno=entorno, curso=curso)
    borrador.paso("LOGIN")
    dir_tiza = Path(dir_tiza)
    plan = plan_curso.plan
    if plan.corta:
        borrador.error("CATEGORIA_BLOQUEADA")
        borrador.fallo("PONDERACION", "CATEGORIA_BLOQUEADA")
        return borrador.documento("error")
    ejecucion = _EjecucionPonderacion(aula, curso)
    corte: ErrorPublicacion | None = None
    inestable = False
    try:
        ejecucion.ejecutar(plan.operaciones)
        if _pesos_en_natural(plan):
            inestable = not _repetir_pesos(aula, plan_curso, ejecucion)
    except ErrorPublicacion as exc:
        corte = exc
        depurar(exc, debug)
        borrador.error(exc.codigo)
    hechas = ejecucion.hechas
    if corte is not None:
        borrador.fallo("PONDERACION", f"{corte.codigo} tras {len(hechas)} cambios")
    if hechas:
        borrador.paso("PONDERACION_CAMBIOS", detalle=_desglose_ponderacion(hechas))
    final = plan_curso.arbol
    if hechas:
        try:
            final = aula.arbol_ponderacion(curso, plan_curso.nombres)
        except ErrorPublicacion as exc:
            depurar(exc, debug)
            if corte is None:
                borrador.error(exc.codigo)
                borrador.fallo("PONDERACION", f"{exc.codigo} tras {len(hechas)} cambios")
            return borrador.documento("error")
    fallidas = _verificadas(hechas, final)
    for referencia in fallidas:
        borrador.fallo("PONDERACION_NO_APLICADA", referencia)
    if inestable:
        borrador.fallo("PONDERACION_NO_APLICADA", "pesos inestables")
    if corte is None:
        if not hechas:
            borrador.paso("PONDERACION", detalle="sin cambios")
        else:
            parcial = bool(fallidas) or inestable
            borrador.paso("PONDERACION", detalle="parcial" if parcial else "aplicada")
    try:
        nuevas = _huellas_de_ponderacion(plan_curso, final, ejecucion, fallidas)
        _guardar_huellas_ponderacion(dir_tiza, plan_curso, nuevas)
    except (ErrorPonderacion, ErrorEstado, OSError):
        borrador.fallo("HUELLA_NO_GUARDADA", "ponderacion")
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
    omitidos: Collection[int] = (),
    nombres: Mapping[int, str] | None = None,
    debug: bool = False,
) -> dict:
    """Monta el calificador en ``entorno``; mismo reparto de papeles que :func:`ordenar_en_cursos`.

    En pruebas gasta 1 del cupo. En real va a todos los cursos reales, con una confirmación por
    curso (con todo lo que va a pasar en llano) y parada en el primer fallo; sin puerta de
    pruebas, como ``ordenar``. Si en un curso no hay nada que cambiar no se pregunta.
    """
    return recorrido.recorrer(
        _TrabajoCalificador(
            aula,
            entorno,
            esquema,
            documentos,
            base,
            nombre_esquema,
            presencia,
            debug=debug,
        ),
        cfg,
        presencia,
        entorno=entorno,
        vigente=vigente,
        cupo=cupo,
        avisar_en_pruebas=avisar_en_pruebas,
        omitidos=omitidos,
        nombres=nombres,
    )


def replanificar_ponderacion(
    plan_curso: PlanPonderacionCurso, *, sobrescribir: Collection[str] = ()
) -> PlanPonderacionCurso:
    """El mismo curso leído, replanificado dando por aceptado pisar las ``sobrescribir`` (referencias)."""
    plan = ponderacion.planificar(
        plan_curso.esquema,
        plan_curso.estructura,
        plan_curso.arbol,
        plan_curso.huellas,
        tzp=plan_curso.tzp,
        sobrescribir=sobrescribir,
    )
    return replace(plan_curso, plan=plan)


_AVISOS_DE_PONDERACION: dict[str, Callable[[str], Aviso]] = {
    "CAMBIADO_A_MANO": Aviso.cambiado_a_mano,
    "CATEGORIA_BLOQUEADA": Aviso.categoria_bloqueada,
    "CATEGORIA_NO_DECLARADA": Aviso.categoria_no_declarada,
    "PESOS_CON_NOTAS": Aviso.pesos_con_notas,
}


def _avisos_del_plan(
    plan: ponderacion.PlanPonderacion, *, codigos: Collection[str]
) -> tuple[Aviso, ...]:
    """Los avisos del plan de esos ``codigos`` en el tipo de la presencia, sin repetir."""
    avisos: dict[tuple[str, str], Aviso] = {}
    for aviso in plan.avisos:
        if aviso.codigo in codigos and aviso.codigo in _AVISOS_DE_PONDERACION:
            avisos.setdefault(
                (aviso.codigo, aviso.nombre), _AVISOS_DE_PONDERACION[aviso.codigo](aviso.nombre)
            )
    return tuple(avisos.values())


def ponderacion_en_cursos(
    aula: AulaVirtual,
    cfg: Config,
    esquema: EsquemaPonderacion,
    base: Path,
    presencia: Presencia,
    *,
    entorno: str,
    nombre_esquema: str,
    vigente: Callable[[], bool] | None = None,
    cupo: dict | None = None,
    avisar_en_pruebas: bool = False,
    omitidos: Collection[int] = (),
    nombres: Mapping[int, str] | None = None,
    debug: bool = False,
) -> dict:
    """Aplica ``ponderacion.yaml`` en ``entorno``; gemela de :func:`calificador_en_cursos`.

    En pruebas gasta 1 del cupo y no pregunta. En real va a todos los cursos reales con una
    confirmación por curso (el antes/después), preguntas aparte por lo cambiado a mano y parada
    en el primer fallo. Si en un curso no hay nada que cambiar no se pregunta.
    """
    return recorrido.recorrer(
        _TrabajoPonderacion(aula, entorno, esquema, base, nombre_esquema, presencia, debug=debug),
        cfg,
        presencia,
        entorno=entorno,
        vigente=vigente,
        cupo=cupo,
        avisar_en_pruebas=avisar_en_pruebas,
        omitidos=omitidos,
        nombres=nombres,
    )


def _a_mano(resumen: ResumenCambioAMano) -> Callable[[Presencia], bool]:
    return lambda presencia: presencia.confirmar_ponderacion_a_mano(resumen)


class _TrabajoPonderacion(recorrido.TrabajoBase):
    """Lo que la ponderación hace en un curso; el bucle y las preguntas son del recorrido."""

    comando = "calificador"

    def __init__(
        self,
        aula: AulaVirtual,
        entorno: str,
        esquema: EsquemaPonderacion,
        base: Path,
        nombre_esquema: str,
        presencia: Presencia,
        *,
        debug: bool,
    ) -> None:
        self._aula = aula
        self._entorno = entorno
        self._esquema = esquema
        self._dir_tiza = Path(base) / rutas.CARPETA_TRABAJO
        self._nombre_esquema = nombre_esquema
        self._presencia = presencia
        self._debug = debug

    def aviso_en_pruebas(self) -> Aviso:
        return Aviso.ponderando_en_pruebas(self._nombre_esquema)

    def en_pruebas(self, curso: int) -> dict:
        try:
            plan_curso = preparar_ponderacion(self._aula, curso, self._esquema, self._dir_tiza)
        except (ErrorPublicacion, ErrorPonderacion, ErrorEstado) as exc:
            borrador = informe.Borrador("calificador", entorno=self._entorno, curso=curso)
            borrador.paso("LOGIN")
            borrador.fallo("PONDERACION", exc.codigo)
            borrador.error(exc.codigo)
            depurar(exc, self._debug)
            return borrador.documento("error")
        # Con el plan cortado ``ponderacion_con`` no escribe: da CATEGORIA_BLOQUEADA.
        if not plan_curso.plan.corta:
            for aviso in _avisos_del_plan(
                plan_curso.plan,
                codigos=("CAMBIADO_A_MANO", "CATEGORIA_BLOQUEADA", "CATEGORIA_NO_DECLARADA"),
            ):
                self._presencia.informar(aviso)
        return ponderacion_con(
            self._aula,
            self._entorno,
            curso,
            plan_curso,
            self._dir_tiza,
            presencia=self._presencia,
            debug=self._debug,
        )

    def _ejecutar(
        self, turno: recorrido.Turno, plan_curso: PlanPonderacionCurso
    ) -> recorrido.Resultado:
        documento = ponderacion_con(
            self._aula,
            self._entorno,
            turno.curso,
            plan_curso,
            self._dir_tiza,
            presencia=self._presencia,
            debug=self._debug,
        )
        return recorrido.Resultado.hecho(documento)

    def _resumen(
        self, plan_curso: PlanPonderacionCurso, turno: recorrido.Turno
    ) -> ResumenPonderacion:
        plan = plan_curso.plan
        return ResumenPonderacion(
            curso=turno.curso,
            nombre_curso=turno.nombre_curso,
            afectadas=plan.afectadas,
            cambios_a_mano=plan.cambios_a_mano,
            pesos_con_notas=plan.pesos_con_notas,
            salidas=plan.salidas,
            avisos=_avisos_del_plan(plan, codigos=("CATEGORIA_BLOQUEADA", "CAMBIADO_A_MANO")),
            posicion=turno.posicion,
            total=turno.total,
        )

    def en_curso(self, turno: recorrido.Turno) -> recorrido.Resultado:
        try:
            plan_curso = preparar_ponderacion(
                self._aula, turno.curso, self._esquema, self._dir_tiza
            )
        except (ErrorPublicacion, ErrorPonderacion, ErrorEstado) as exc:
            # Cada curso se lee entero antes de escribir nada en él (y antes de preguntar).
            return recorrido.Resultado.fallo(exc.codigo)
        plan = plan_curso.plan
        if plan.corta:
            return recorrido.Resultado.fallo("CATEGORIA_BLOQUEADA")
        confirmado = False
        if not plan.sin_cambios:
            resumen = self._resumen(plan_curso, turno)
            if not turno.preguntar(lambda presencia: presencia.confirmar_ponderacion(resumen)):
                return recorrido.Resultado.declinado()
            confirmado = True
        for aviso in _avisos_del_plan(plan, codigos=("PESOS_CON_NOTAS", "CATEGORIA_NO_DECLARADA")):
            self._presencia.informar(aviso)
        sobrescribir: list[str] = []
        for cambio in plan.cambios_a_mano:
            pregunta = ResumenCambioAMano(
                turno.curso, turno.nombre_curso, cambio, turno.posicion, turno.total
            )
            if turno.preguntar(_a_mano(pregunta), tras_no=True):
                sobrescribir.append(cambio.referencia)
            else:
                self._presencia.informar(Aviso.cambiado_a_mano(cambio.nombre))
        if sobrescribir:
            try:
                plan_curso = replanificar_ponderacion(plan_curso, sobrescribir=sobrescribir)
            except ErrorPonderacion as exc:
                return recorrido.Resultado.fallo(exc.codigo)
            if plan_curso.plan.corta:
                return recorrido.Resultado.fallo("CATEGORIA_BLOQUEADA")
            if not confirmado and not plan_curso.plan.sin_cambios:
                resumen = self._resumen(plan_curso, turno)
                if not turno.preguntar(lambda presencia: presencia.confirmar_ponderacion(resumen)):
                    return recorrido.Resultado.declinado()
        return self._ejecutar(turno, plan_curso)


class _TrabajoCalificador(recorrido.TrabajoBase):
    """Lo que el calificador hace en un curso; el bucle y las preguntas son del recorrido."""

    comando = "calificador"

    def __init__(
        self,
        aula: AulaVirtual,
        entorno: str,
        esquema: Esquema,
        documentos: list[Documento],
        base: Path,
        nombre_esquema: str,
        presencia: Presencia,
        *,
        debug: bool,
    ) -> None:
        self._aula = aula
        self._entorno = entorno
        self._esquema = esquema
        self._documentos = documentos
        self._dir_tiza = Path(base) / rutas.CARPETA_TRABAJO
        self._nombre_esquema = nombre_esquema
        self._presencia = presencia
        self._debug = debug

    def aviso_en_pruebas(self) -> Aviso:
        return Aviso.calificando_en_pruebas(self._nombre_esquema)

    def en_pruebas(self, curso: int) -> dict:
        return calificador_con(
            self._aula,
            self._entorno,
            curso,
            self._esquema,
            self._documentos,
            self._dir_tiza,
            presencia=self._presencia,
            evidencia_confirmada=True,
            debug=self._debug,
        )

    def en_curso(self, turno: recorrido.Turno) -> recorrido.Resultado:
        try:
            plan = preparar_calificador(
                self._aula, turno.curso, self._esquema, self._documentos, self._dir_tiza
            )
        except (ErrorPublicacion, ErrorCalificacion, ErrorEstado) as exc:
            # Cada curso se lee entero antes de escribir nada en él (y antes de preguntar).
            return recorrido.Resultado.fallo(exc.codigo)
        if plan.reconciliacion.hay_trabajo or plan.resultados_pendientes:
            resumen = resumen_calificador(
                plan,
                self._esquema,
                turno.nombre_curso,
                posicion=turno.posicion,
                total=turno.total,
            )
            if not turno.preguntar(lambda presencia: presencia.confirmar_calificador(resumen)):
                return recorrido.Resultado.declinado()
        evidencia_declinada = self._preguntar_evidencia(plan, turno)
        # Sin operaciones no hay nada que confirmar: se informa de que no había nada que hacer.
        documento = calificador_con(
            self._aula,
            self._entorno,
            turno.curso,
            self._esquema,
            self._documentos,
            self._dir_tiza,
            plan=plan,
            presencia=self._presencia,
            evidencia_confirmada=True,
            sin_resultados=evidencia_declinada,
            debug=self._debug,
        )
        return recorrido.Resultado.hecho(documento)

    def _preguntar_evidencia(self, plan: PlanCalificador, turno: recorrido.Turno) -> frozenset[str]:
        """D11 en el calificador: pregunta solo por tareas pendientes que ya tienen notas.

        Devuelve las rutas que el docente declinó. Si no hay tareas pendientes con notas, no se
        pregunta y se devuelve vacío (las pendientes sin notas se pueden activar: no hay riesgo).
        """
        if not plan.resultados_pendientes:
            return frozenset()
        try:
            estructura = self._aula.estructura(turno.curso)
        except ErrorPublicacion:
            # Sin la estructura no se puede saber cuáles tienen notas: no se activa ninguna.
            return frozenset(
                _ruta_de(doc, plan.base)
                for doc in self._documentos
                if doc.evidencia == "resultados"
            )
        pendientes: list[tuple[str, str]] = []
        for doc in self._documentos:
            if doc.evidencia != "resultados" or doc.evalua is None:
                continue
            ruta = _ruta_de(doc, plan.base)
            if ruta in plan.documentos_con_resultados:
                continue
            modulo = estructura.localizar(doc, turno.curso).modulo
            if modulo is not None and _tarea_con_notas_sin_resultados(
                self._aula, turno.curso, doc, modulo.cmid
            ):
                pendientes.append((ruta, doc.nombre))
        if not pendientes:
            return frozenset()
        resumen = ResumenEvidencia(
            curso=turno.curso,
            nombre_curso=turno.nombre_curso,
            tareas=tuple(nombre for _, nombre in pendientes),
            posicion=turno.posicion,
            total=turno.total,
        )
        if turno.preguntar(lambda presencia: presencia.confirmar_evidencia(resumen), tras_no=True):
            return frozenset()
        return frozenset(ruta for ruta, _ in pendientes)


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
