"""Publicación en el aula virtual, siempre desde la terminal del docente.

Este módulo es el único que habla con el aula. Todo lo que devuelve Moodle se
reduce a códigos y valores de nuestro propio esquema: las excepciones de
python-moodle (que pueden incluir fragmentos de ``resp.text``) nunca salen de
aquí convertidas en texto.
"""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import hashlib
import html
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, Protocol
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from py_moodle import auth as py_auth
from py_moodle import course as py_course
from py_moodle import draftfile as py_draftfile
from py_moodle import module as py_module
from py_moodle import section as py_section
from py_moodle.auth import LoginError
from py_moodle.compat import detect_moodle_compatibility
from py_moodle.course import MoodleCourseError
from py_moodle.draftfile import MoodleDraftFileError
from py_moodle.module import MoodleModuleError
from py_moodle.section import MoodleSectionError
from py_moodle.session import MoodleSessionError

from . import __version__, colocacion, informe, tipos
from .calificacion.formulas import (  # noqa: F401  (se reexportan: son de la API de ``publicar``)
    formula_copia,
    formula_indicador,
    formula_moodle,
    formula_nota,
    formula_tope,
)
from .calificacion.formulas import texto_numero as _texto_numero
from .config import AdaptadorAula, DestinoNoPermitido, coincide_dominio
from .contenido import Documento, Recurso, hash_documento, html_para_moodle
from .estructura import (
    Actividad,
    ErrorEstructura,
    Estructura,
    nombre_de_seccion,
)
from .rubrica import CriterioRubrica, RubricaCargada
from .tipos.cuestionario import CAMPOS_FECHA as CAMPOS_FECHA_CUESTIONARIO
from .tipos.tarea import CAMPOS_FECHA as CAMPOS_FECHA_TAREA

__all__ = [
    "AulaVirtual",
    "CopiaDescargada",
    "ErrorPublicacion",
    "Moodle",
    "autenticar",
    "asegurar_secciones",
    "colocar_notas",
    "aula_deja_copiar",
    "autoprueba",
    "aplicar_itinerario",
    "fechas_esperadas",
    "es_disponibilidad_de_tiza",
    "Movimiento",
    "ordenar_documentos",
    "ordenar_notas",
    "con_orden_final",
    "plan_de_orden",
    "payload_disponibilidad",
    "payload_finalizacion",
    "preparar_itinerario",
    "validar_disponibilidad",
    "payload_cuestionario",
    "payload_etiqueta",
    "payload_h5p",
    "payload_pagina",
    "payload_tarea",
    "publicar_documento",
    "url_modulo",
    "urls_paquete_h5p",
    "urls_pluginfile",
]

PAUSA_POR_DEFECTO = 0.4
# Esperas antes de repetir una subida que el aula frena por su límite de áreas de borrador
# (unas 50 seguidas; repone ~1 cada 5 s, espiga 6). Si no basta, AULA_PIDE_ESPERA.
ESPERAS_LIMITE_BORRADORES = (5.0, 10.0, 20.0, 40.0)
TIEMPO_ESPERA = 30  # segundos por petición: un aula que no responde no cuelga la sesión

# Copia de seguridad del curso (espiga 7, CT 130): es síncrona y rápida (42 MB en menos de
# 12 s); el tope de espera para cada etapa, para que aparezca en el área privada y para la
# descarga es de 10 minutos.
ESPERA_COPIA = 600.0
PASO_ESPERA_COPIA = 10.0  # entre dos miradas al área privada, mientras la copia no aparece
MAX_ETAPAS_COPIA = 8  # backup.php tiene 4 etapas; más es que el formulario no es el esperado
TROZO_COPIA = 1024 * 1024
# Ajustes del formulario de copia que pueden llevar datos del alumnado: siempre a 0 (espiga 7).
AJUSTES_DE_USUARIO_COPIA = frozenset(
    {
        "users",
        "anonymize",
        "role_assignments",
        "comments",
        "badges",
        "calendarevents",
        "userscompletion",
        "logs",
        "grade_histories",
        "xapistate",
        "groups",
    }
)
_AJUSTE_RAIZ = "setting_root_"
_CAMPO_NOMBRE_COPIA = "setting_root_filename"
_USERINFO = re.compile(r"\Asetting_(?:section|activity)_.+_userinfo\Z")
_ACCION_COPIA = re.compile(r"backup\.php")
_ACCION_EDICION_COPIAS = re.compile(r"backupfilesedit\.php")
_BOTONES_QUE_NO_AVANZAN = frozenset({"cancel", "previous"})

# Fechas del formulario de las actividades con fechas, para releerlas: los campos
# de una tarea y los de un cuestionario (nombres del Moodle en español, arriba).
_CAMPOS_FECHA_LEIDOS = CAMPOS_FECHA_TAREA + CAMPOS_FECHA_CUESTIONARIO

# Rúbrica nativa de una tarea (medido en el Moodle de pruebas).
METODO_SUBMISSIONS = "advancedgradingmethod_submissions"
_QF_RUBRICA = re.compile(r"\A_qf__gradingform_rubric_editrubric")
_CRITERIO_RUBRICA = re.compile(r"\Arubric\[criteria\]\[([^\]]+)\]\[(description|sortorder)\]\Z")
_NIVEL_RUBRICA = re.compile(
    r"\Arubric\[criteria\]\[([^\]]+)\]\[levels\]\[([^\]]+)\]\[(score|definition)\]\Z"
)
OPCIONES_RUBRICA = {
    "rubric[options][sortlevelsasc]": "1",
    "rubric[options][lockzeropoints]": "1",
    "rubric[options][alwaysshowdefinition]": "1",
    "rubric[options][showdescriptionteacher]": "1",
    "rubric[options][showdescriptionstudent]": "1",
    "rubric[options][showscoreteacher]": "1",
    "rubric[options][showscorestudent]": "1",
    "rubric[options][enableremarks]": "1",
    "rubric[options][showremarksstudent]": "1",
}

# Detalle de CUESTIONARIO_CON_INTENTOS: es un texto de tiza, nunca de Moodle.
DETALLE_INTENTOS = (
    "el cuestionario ya tiene intentos de alumnado y Moodle no deja cambiar sus preguntas; "
    "no se ha tocado nada. Crea otro cuestionario con otro nombre si necesitas cambiarlas."
)
DETALLE_INTENTOS_REPUBLICAR = (
    "un alumno empezó un intento durante la republicación: el cuestionario puede tener "
    "preguntas viejas y nuevas juntas. Revísalo en el aula."
)
DETALLE_H5P_INTENTOS = (
    "la actividad H5P ya tiene intentos de alumnado y cambiarla los rompería; no se ha "
    "tocado nada. Crea otra actividad con otro nombre si necesitas cambiarla."
)

ERRORES_MOODLE = (
    LoginError,
    MoodleSessionError,
    MoodleCourseError,
    MoodleDraftFileError,
    MoodleModuleError,
    MoodleSectionError,
    requests.RequestException,
    json.JSONDecodeError,
)


def _curso_sin_listado(session, base_url, sesskey, courseid, token=None) -> dict:
    """Secciones y módulos de un curso sin listar todos los cursos del usuario.

    ``add_generic_module`` llama a ``get_course_with_sections_and_modules``, que
    además ejecuta ``list_courses`` solo para obtener el nombre del curso, y esa
    llamada puede fallar si el usuario tiene algún curso no accesible. Parche
    que proponer upstream.
    """
    secciones = py_course.get_course(session, base_url, sesskey, courseid, token=token)
    return {
        "id": courseid,
        "sections": [
            {
                "id": seccion.get("id"),
                "section": seccion.get("section"),
                "name": seccion.get("name"),
                "modules": [
                    {
                        "id": modulo.get("id"),
                        "name": modulo.get("name"),
                        "modname": modulo.get("modname", modulo.get("mod", "unknown")),
                    }
                    for modulo in seccion.get("modules", seccion.get("cmlist", []))
                ],
            }
            for seccion in secciones or []
        ],
    }


py_module.get_course_with_sections_and_modules = _curso_sin_listado

USER_AGENT = f"tiza/{__version__} (+https://github.com/balejosg/tiza)"

# python-moodle reenvía la contraseña a /login/token.php para pedir un token de la
# app móvil. Aquí solo se usa la sesión web: un único envío de la contraseña.
py_auth.MoodleAuth._get_webservice_token = lambda self: None  # type: ignore[method-assign]

_init_original = py_auth.MoodleAuth.__init__


def _init_con_user_agent(self, *args, **kwargs):
    _init_original(self, *args, **kwargs)
    self.session.headers["User-Agent"] = USER_AGENT
    # Nada sale de la sesión del aula hacia otro servidor (ni la contraseña ni las cookies),
    # tampoco por una redirección: cada petición pasa por la guardia antes de enviarse.
    # El servidor queda fijado al de la URL con la que se hace el login.
    adaptador = AdaptadorAula(self.base_url)
    self.session.mount("https://", adaptador)
    self.session.mount("http://", adaptador)


py_auth.MoodleAuth.__init__ = _init_con_user_agent  # type: ignore[method-assign]


def _bloqueo_de_destino(exc: BaseException) -> bool:
    """¿Está la guardia de red detrás de este error?

    python-moodle envuelve los errores de requests en los suyos (``raise X(f"…{e}")`` dentro
    del ``except``), así que se recorre la cadena de causas y contextos.
    """
    vistos: set[int] = set()
    actual: BaseException | None = exc
    while actual is not None and id(actual) not in vistos:
        if isinstance(actual, DestinoNoPermitido):
            return True
        vistos.add(id(actual))
        actual = actual.__cause__ or actual.__context__
    return False


def _pide_espera(respuesta: Any) -> bool:
    """¿Es la respuesta del aula su límite de áreas de borrador?

    Mira el código de error de Moodle (``maxdraftitemids``), nunca el texto, que va en el
    idioma del aula. Ante cualquier duda, falso.
    """
    try:
        datos = respuesta.json()
    except Exception:  # noqa: BLE001 - sin JSON legible no es ese límite
        return False
    return isinstance(datos, dict) and datos.get("errorcode") == "maxdraftitemids"


class _SesionQueAnota:
    """La sesión del aula guardando la última respuesta de un ``post``.

    python-moodle reduce el error de la subida a su texto y tira el código de Moodle.
    """

    def __init__(self, sesion: Any) -> None:
        self._sesion = sesion
        self.ultima: Any = None

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._sesion, nombre)

    def post(self, *args, **kwargs):
        self.ultima = self._sesion.post(*args, **kwargs)
        return self.ultima


def _error_con_copia_en_el_aula(codigo: str) -> ErrorPublicacion:
    """El error de una copia que puede estar en el aula sin que tiza pueda encontrarla ni quitarla."""
    error = ErrorPublicacion(codigo)
    error.queda_en_el_aula = True
    return error


class CopiaDescargada(NamedTuple):
    """Lo que devuelve ``hacer_copia``: los bytes escritos y el nombre que tiene en el aula."""

    bytes: int
    nombre: str  # el nombre propio, en la zona de copias privadas del docente en Moodle


class ErrorPublicacion(Exception):
    """Error de publicación con un código estable y sin texto de Moodle."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle
        self.cmid: int | None = None  # módulo ya creado cuando falla la verificación
        # Una copia de seguridad que Moodle ya creó y tiza no pudo quitar de la zona de copias.
        self.queda_en_el_aula = False


@dataclasses.dataclass(frozen=True)
class NodoAula:
    """Un elemento o categoría del calificador del aula. Solo estructura: jamás notas.

    ``nombre`` lo ve únicamente el docente, a través de la presencia; nunca sale a ``informe``.
    ``clase`` es ``curso``, ``categoria``, ``actividad``, ``manual`` o ``calculado``.
    """

    eid: str  # «cg<id>» (categoría o curso) o «ig<id>» (elemento)
    item_id: int  # el grade_item (el del total, en una categoría)
    idnumber: str
    clase: str
    nombre: str
    padre_eid: str | None
    peso: float | None
    sobrescrito: bool
    bloqueado: bool
    tiene_notas: bool  # solo por la presencia de ``rescalegrades``; en una categoría, por sus hijos
    formula: str | None
    maximo: float | None
    cmid: int | None
    agregacion: int | None = None  # 13 Natural, 2 Mediana, 6 Calificación más alta
    oculto: bool = False  # el alumnado no lo ve; en una categoría no se lee (tiza no las oculta)


@dataclasses.dataclass(frozen=True)
class CalificadorAula:
    """La estructura del calificador de un curso, en el orden de la página."""

    nodos: tuple[NodoAula, ...]
    decimal: str  # «,» o «.»: el separador que muestra el formulario (decide el de las fórmulas)


# --------------------------------------------------------------------------- #
# Adaptador del aula
# --------------------------------------------------------------------------- #


class AulaVirtual(Protocol):
    """Lo que la publicación necesita del aula.

    Lo cumplen ``Moodle`` y el doble de los tests (``tests/dobles.py``): si
    cambias un método aquí, cambia los dos.
    """

    base_url: str

    def cerrar(self) -> None:
        """Cierra la sesión del aula; nunca lanza."""
        ...

    def estructura(self, curso_id: int) -> Estructura: ...

    def mis_cursos(self) -> list[dict]: ...

    def contexto(self, curso_id: int) -> int: ...

    def subir(self, curso_id: int, contexto: int, ruta: Path, itemid: int) -> tuple[int, str]: ...

    def crear(self, curso_id: int, seccion_id: int, tipo: str, payload: dict) -> int: ...

    def actualizar(self, cmid: int, payload: dict) -> None: ...

    def leer_modulo(self, cmid: int) -> dict: ...

    def actividad_tiene_notas(self, cmid: int) -> bool: ...

    def leer_rubrica(self, cmid: int) -> dict: ...

    def definir_rubrica(self, cmid: int, rubrica: RubricaCargada) -> dict: ...

    def imagenes_de_pregunta(self, cmid: int, pregunta_id: int) -> tuple[int, int]: ...

    def motor_de_formulas(self, curso_id: int) -> bool: ...

    def comprobar_pluginfile(self, url: str) -> bool: ...

    def borrar(self, curso_id: int, cmid: int) -> None: ...

    def mover(self, curso_id: int, cmid: int, seccion_id: int, antes_de: int | None) -> None: ...

    def crear_seccion(self, curso_id: int, nombre: str) -> int: ...

    def borrar_seccion(self, curso_id: int, seccion_id: int) -> None: ...

    def categoria_cuestionario(self, cmid: int) -> str: ...

    def preguntas_en_categoria(self, cmid: int, categoria: str) -> set[int]: ...

    def importar_preguntas(
        self, curso_id: int, cmid: int, categoria: str, xml: bytes
    ) -> list[int]: ...

    def anadir_preguntas(self, cmid: int, ids: list[int]) -> None: ...

    def huecos(self, cmid: int) -> list[tuple[int, int | None]]: ...

    def tiene_intentos(self, cmid: int) -> bool: ...

    def quitar_hueco(self, curso_id: int, quizid: int, hueco: int) -> None: ...

    def borrar_preguntas(self, cmid: int, ids: list[int]) -> None: ...

    def comprobar_h5p(self, cmid: int) -> bool: ...

    def libreria_h5p_ausente(self, cmid: int, machine_name: str) -> bool: ...

    def h5p_tiene_intentos(self, cmid: int) -> bool: ...

    def puede_copiar(self, curso_id: int) -> bool: ...

    def hacer_copia(
        self, curso_id: int, destino: Path, maximo: int, cmid: int | None = None
    ) -> CopiaDescargada: ...

    def calificador(
        self, curso_id: int, tocados: Collection[str] | None = None
    ) -> CalificadorAula: ...

    def crear_categoria(
        self,
        curso: int,
        nombre: str,
        idnumber: str,
        padre_eid: str | None,
        peso: float | None,
        visualizacion: str | None,
        agregacion: int = 13,
    ) -> str: ...

    def crear_calculado(
        self,
        curso: int,
        nombre: str,
        idnumber: str,
        padre_eid: str | None,
        peso: float | None,
        maximo: float,
        oculto: bool = False,
    ) -> str: ...

    def fijar_maximo(self, curso: int, item_id: int, maximo: float) -> None: ...

    def fijar_peso(self, curso: int, eid: str, peso: float) -> None: ...

    def fijar_agregacion(self, curso: int, eid: str, agregacion: int) -> None: ...

    def fijar_formula(self, curso: int, item_id: int, formula: str, decimal: str) -> None: ...

    def bloquear_total(self, curso: int, item_id: int) -> None: ...

    def ocultar(self, curso: int, item_id: int) -> None: ...

    def ajuste_totales(self, curso: int) -> int | None: ...

    def colocar_actividad(
        self, curso: int, cmid: int, categoria_id: int, idnumber: str | None
    ) -> None: ...

    def mover_manual(self, curso: int, item_id: int, categoria_eid: str) -> None: ...

    def arbol_notas(self, curso: int) -> colocacion.ArbolNotas: ...

    def mover_nota(self, curso: int, eid: str, categoria: str, despues_de: str | None) -> None: ...

    def borrar_nodo(self, curso: int, eid: str) -> None: ...

    def fijar_total_curso(self, curso: int, formula: str | None, decimal: str) -> None: ...

    def resultados_activos(self, curso: int) -> bool: ...

    def asegurar_escala(self, curso: int, nombre: str, niveles: tuple[str, ...]) -> int: ...

    def escala_con_nombre(self, curso: int, nombre: str) -> int | None: ...

    def asegurar_resultado(
        self, curso: int, corto: str, nombre: str, descripcion: str, escala: int
    ) -> int: ...

    def resultado_por_corto(self, curso: int, corto: str) -> int | None: ...

    def fijar_idnumber_resultado(self, curso: int, item_id: int, idnumber: str) -> None: ...

    def campos_resultado_tarea(self, cmid: int) -> dict[int, bool]: ...

    def marcar_resultado_tarea(self, cmid: int, resultado_id: int) -> None: ...

    def borrar_copia(self, nombre: str, curso_id: int) -> None: ...


class Moodle:
    """Adaptador fino sobre python-moodle con salida reducida a códigos."""

    def __init__(
        self,
        base_url: str,
        sesion: Any,
        sesskey: str,
        pausa: float = PAUSA_POR_DEFECTO,
        dormir=time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.sesion = sesion
        self.sesskey = sesskey
        self._pausa = pausa
        self._dormir = dormir
        self._nombres_de_copia: set[str] = set()  # los que ya usó esta sesión del aula
        # Calificador: lo visto en la última lectura de cada curso, para no repetir peticiones
        # (los ``eid`` del árbol y lo leído de cada formulario). Solo lo usan las altas y las
        # relecturas con ``tocados`` dentro de una misma ejecución.
        self._arbol: dict[int, set[str]] = {}
        self._formularios: dict[int, dict[str, dict[str, Any]]] = {}
        # Nombre corto de cada resultado del curso, leído de su formulario. Se llena al
        # asegurar un resultado y se conserva mientras dure la sesión; al crear uno se
        # invalida el curso, porque la lista de ``removeoutcomes[]`` trae ids nuevos.
        self._corto_resultados: dict[int, dict[int, str]] = {}

    def _esperar(self) -> None:
        """Peticiones secuenciales con una pausa corta."""
        if self._pausa:
            self._dormir(self._pausa)

    def _reducir(self, codigo: str, funcion, *args, **kwargs):
        try:
            return funcion(*args, **kwargs)
        except ERRORES_MOODLE as exc:
            raise self._error(codigo, exc) from exc

    def _error(self, codigo: str, exc: BaseException) -> ErrorPublicacion:
        if _bloqueo_de_destino(exc):
            return ErrorPublicacion("DESTINO_NO_PERMITIDO")
        if not self.sesion_viva():
            return ErrorPublicacion("SESION_CADUCADA")
        return ErrorPublicacion(codigo)

    def cerrar(self) -> None:
        """Cierra la sesión en el aula, para que la cookie deje de valer (nunca lanza).

        Sin seguir redirecciones: con SAML o CAS el cierre de Moodle manda al proveedor de
        acceso, y tiza no sale del servidor del aula.
        """
        try:
            self.sesion.get(
                f"{self.base_url}/login/logout.php",
                params={"sesskey": self.sesskey},
                allow_redirects=False,
                timeout=15,
            )
        except Exception:  # noqa: BLE001 - cerrar es un último favor: nunca debe romper nada
            return

    def sesion_viva(self) -> bool:
        """Falso solo si el aula redirige al login (sesión caducada o cerrada).

        No depende del idioma: mira la redirección de ``/my/``, nunca el texto.
        Ante cualquier duda devuelve verdadero y se conserva el código original.
        """
        try:
            respuesta = self.sesion.get(f"{self.base_url}/my/", allow_redirects=False, timeout=15)
        except Exception:  # noqa: BLE001 - la comprobación nunca debe romper
            return True
        if getattr(respuesta, "status_code", 200) not in (301, 302, 303, 307):
            return True
        destino = (getattr(respuesta, "headers", None) or {}).get("Location", "")
        return "/login/" not in destino

    def estructura(self, curso_id: int) -> Estructura:
        self._esperar()
        secciones = self._reducir(
            "ERROR_ESTRUCTURA",
            py_course.get_course,
            self.sesion,
            self.base_url,
            self.sesskey,
            curso_id,
        )
        salida = []
        for seccion in secciones or []:
            numero = seccion.get("section")
            if numero is None:
                continue
            modulos = []
            for modulo in seccion.get("modules", []):
                # El estado AJAX trae los ids como texto ("57078"); el informe exige enteros.
                try:
                    cmid = int(modulo.get("id"))
                except (TypeError, ValueError):
                    continue
                # El estado AJAX del curso trae el tipo en "module" ("page"); allí
                # "modname" puede ser el nombre traducido ("Página").
                modname = modulo.get("module") or modulo.get("modname") or modulo.get("mod") or ""
                modulos.append(
                    {
                        "cmid": cmid,
                        "nombre": (modulo.get("name") or "").strip(),
                        "tipo": tipos.de_modulo(modname) or modname,
                    }
                )
            try:
                seccion_id = int(seccion.get("id"))
            except (TypeError, ValueError):
                continue
            salida.append(
                {
                    "numero": int(numero),
                    "nombre": nombre_de_seccion(seccion.get("name") or seccion.get("title") or ""),
                    "id": seccion_id,
                    "modulos": modulos,
                }
            )
        try:
            return Estructura.de_dicts(sorted(salida, key=lambda item: item["numero"]))
        except ErrorEstructura as exc:
            raise ErrorPublicacion("ERROR_ESTRUCTURA") from exc

    def mis_cursos(self) -> list[dict]:
        """Cursos en los que está matriculado el usuario: id y nombre."""
        self._esperar()
        return self._reducir(
            "ERROR_CURSOS", _cursos_matriculados, self.sesion, self.base_url, self.sesskey
        )

    def contexto(self, curso_id: int) -> int:
        self._esperar()
        return self._reducir(
            "ERROR_CONTEXTO",
            py_course.get_course_context_id,
            self.sesion,
            self.base_url,
            curso_id,
        )

    def subir(self, curso_id: int, contexto: int, ruta: Path, itemid: int) -> tuple[int, str]:
        """Sube un fichero a un área de borrador.

        Si el aula la frena por su límite de áreas, espera y repite (una subida rechazada
        no deja nada en el aula); si no basta, ``AULA_PIDE_ESPERA``.
        """
        for espera in (*ESPERAS_LIMITE_BORRADORES, None):
            self._esperar()
            sesion = _SesionQueAnota(self.sesion)
            try:
                return py_draftfile.upload_file_to_draft_area(
                    sesion,  # type: ignore[arg-type]  # la sesión, envuelta
                    self.base_url,
                    self.sesskey,
                    curso_id,
                    contexto,
                    str(ruta),
                    itemid=itemid,
                )
            except ERRORES_MOODLE as exc:
                if not _pide_espera(sesion.ultima):
                    raise self._error("ERROR_SUBIDA", exc) from exc
                if espera is None:
                    raise ErrorPublicacion("AULA_PIDE_ESPERA") from exc
                self._dormir(espera)
        raise AssertionError("inalcanzable")

    def crear(self, curso_id: int, seccion_id: int, tipo: str, payload: dict) -> int:
        try:
            nombre_modulo = tipos.obtener(tipo).modulo
        except KeyError:
            raise ErrorPublicacion("TIPO_DESCONOCIDO") from None
        self._esperar()
        return self._reducir(
            "ERROR_CREACION",
            py_module.add_generic_module,
            self.sesion,
            self.base_url,
            self.sesskey,
            nombre_modulo,
            curso_id,
            seccion_id,
            payload,
        )

    def actualizar(self, cmid: int, payload: dict) -> None:
        self._esperar()
        self._reducir(
            "ERROR_ACTUALIZACION",
            py_module.update_generic_module,
            self.sesion,
            self.base_url,
            cmid,
            payload,
        )

    def leer_modulo(self, cmid: int) -> dict:
        """Relee el formulario de edición del módulo (lista blanca de campos)."""
        self._esperar()
        url = f"{self.base_url}/course/modedit.php?update={cmid}"
        respuesta = self._reducir("ERROR_CONSULTA", self.sesion.get, url, timeout=TIEMPO_ESPERA)
        self._reducir("ERROR_CONSULTA", respuesta.raise_for_status)
        sopa = BeautifulSoup(respuesta.text, "html.parser")
        formulario = sopa.find("form", attrs={"action": re.compile(r"modedit\.php")}) or sopa
        instancia = _campo(formulario, "instance")
        coincidencia = re.search(r'["\']contextid["\']\s*:\s*(\d+)', respuesta.text)
        adjuntos = _campo(formulario, "introattachments")
        return {
            "nombre": _campo(formulario, "name") or "",
            "texto": _campo(formulario, "page[text]")
            or _campo(formulario, "introeditor[text]")
            or "",
            # El área de borrador de «Archivos adicionales» de una tarea (con sus ficheros).
            "adjuntos": int(adjuntos) if adjuntos and adjuntos.isdigit() else None,
            "instance": int(instancia) if instancia and instancia.isdigit() else None,
            "visible": _campo(formulario, "visible"),
            "contexto": int(coincidencia.group(1)) if coincidencia else None,
            "fechas": {campo: _fecha_leida(formulario, campo) for campo in _CAMPOS_FECHA_LEIDOS},
            # Solo para uso interno de la sesión: nunca llega a .tiza ni al agente.
            "itinerario": {
                "campos": {
                    campo: _campo(formulario, campo) for campo in CAMPOS_FINALIZACION_LEIDOS
                },
                "esperada": _fecha_leida(formulario, "completionexpected"),
                "disponibilidad": _campo(formulario, "availabilityconditionsjson") or "",
            },
        }

    def actividad_tiene_notas(self, cmid: int) -> bool:
        """¿La tarea ya tiene notas en el calificador? Solo por ``rescalegrades`` en sus ajustes.

        No abre la tabla de calificación ni la lista de participantes: no lee ninguna nota ni
        ningún nombre. Moodle muestra ese campo cuando el elemento del calificador ya tiene
        notas: una nota liberada, o una puesta sin flujo de trabajo. Una nota en borrador (con
        ``markingworkflow`` activo) no lo muestra; por eso la confirmación del docente es la
        regla principal y este campo es solo un freno. Si el formulario no se puede leer, se
        trata como si tuviera notas (D14): ante la duda, no se cambia su método ni su rúbrica.
        """
        url = f"{self.base_url}/course/modedit.php?update={cmid}"
        try:
            respuesta = self.sesion.get(url, timeout=TIEMPO_ESPERA)
            respuesta.raise_for_status()
            texto = getattr(respuesta, "text", "") or ""
        except Exception:  # noqa: BLE001 - no poder saberlo cuenta como «tiene notas»
            return True
        sopa = BeautifulSoup(texto, "html.parser")
        formulario = sopa.find("form", attrs={"action": re.compile(r"modedit\.php")})
        if formulario is None:
            # Una página de login con 200 (sesión caducada) no es el formulario de ajustes.
            return True
        return any(
            "rescalegrades" in str(campo.get("name") or "") for campo in formulario.find_all(True)
        )

    def _area_rubrica(self, cmid: int) -> int:
        contexto = self.leer_modulo(cmid).get("contexto")
        if not isinstance(contexto, int):
            raise ErrorPublicacion("RUBRICA_ILEGIBLE")
        self._esperar()
        respuesta = self._reducir(
            "RUBRICA_ILEGIBLE",
            self.sesion.get,
            f"{self.base_url}/grade/grading/manage.php",
            params={"contextid": contexto, "component": "mod_assign", "area": "submissions"},
            timeout=TIEMPO_ESPERA,
        )
        self._reducir("RUBRICA_ILEGIBLE", respuesta.raise_for_status)
        coincide = re.search(r"areaid=(\d+)", getattr(respuesta, "text", "") or "")
        if coincide is None:
            raise ErrorPublicacion("RUBRICA_ILEGIBLE")
        return int(coincide.group(1))

    def _formulario_rubrica(self, cmid: int):
        """(respuesta, formulario) del editor de rúbricas de la tarea."""
        area = self._area_rubrica(cmid)
        self._esperar()
        respuesta = self._reducir(
            "RUBRICA_ILEGIBLE",
            self.sesion.get,
            f"{self.base_url}/grade/grading/form/rubric/edit.php",
            params={"areaid": area},
            timeout=TIEMPO_ESPERA,
        )
        self._reducir("RUBRICA_ILEGIBLE", respuesta.raise_for_status)
        formulario = _formulario_en(getattr(respuesta, "text", "") or "", _QF_RUBRICA)
        if formulario is None:
            raise ErrorPublicacion("RUBRICA_ILEGIBLE")
        return respuesta, formulario

    def leer_rubrica(self, cmid: int) -> dict:
        """La rúbrica nativa de la tarea, con los ids de Moodle y las opciones del editor."""
        _respuesta, formulario = self._formulario_rubrica(cmid)
        return {
            "criterios": _definicion_rubrica(formulario),
            "lockzeropoints": _casilla_marcada(formulario, "rubric[options][lockzeropoints]"),
            "showremarksstudent": _casilla_marcada(
                formulario, "rubric[options][showremarksstudent]"
            ),
        }

    def definir_rubrica(self, cmid: int, rubrica: RubricaCargada) -> dict:
        """Define (o confirma) la rúbrica nativa de una tarea.

        Devuelve ``{"accion": "ya_definida"|"definida", "pares": …}``. Con notas puestas no
        toca nada: ``RUBRICA_EN_USO``. La señal de notas es ``actividad_tiene_notas``: nunca
        se abre la tabla de calificación ni la lista de participantes.
        """
        pares = emparejar_rubrica(self.leer_rubrica(cmid)["criterios"], rubrica)
        if pares is not None:
            return {"accion": "ya_definida", "pares": pares}
        if self.actividad_tiene_notas(cmid):
            raise ErrorPublicacion("RUBRICA_EN_USO")
        respuesta, formulario = self._formulario_rubrica(cmid)
        datos = _datos_rubrica(py_module._extract_modedit_form_data(formulario), rubrica)
        destino = urljoin(
            getattr(respuesta, "url", None) or f"{self.base_url}/grade/grading/form/rubric/",
            formulario.get("action") or "edit.php",
        )
        self._esperar()
        envio = self._reducir(
            "RUBRICA_ILEGIBLE",
            self.sesion.post,
            destino,
            data=datos,
            timeout=TIEMPO_ESPERA,
            allow_redirects=False,
        )
        if getattr(envio, "status_code", 0) not in (301, 302, 303):
            raise ErrorPublicacion("RUBRICA_ILEGIBLE")
        pares = emparejar_rubrica(self.leer_rubrica(cmid)["criterios"], rubrica)
        if pares is None:
            raise ErrorPublicacion("RUBRICA_ILEGIBLE")
        return {"accion": "definida", "pares": pares}

    def imagenes_de_pregunta(self, cmid: int, pregunta_id: int) -> tuple[int, int]:
        """(imágenes que enseña la vista previa de la pregunta, las que se sirven con HTTP 200).

        Es la vista previa del banco de preguntas, que no crea ningún intento del cuestionario
        (medido en la espiga). Solo salen números; el texto de Moodle no sale de aquí.
        """
        self._esperar()
        pagina = self._reducir(
            "ERROR_VERIFICACION_IMAGENES",
            self.sesion.get,
            f"{self.base_url}/question/bank/previewquestion/preview.php",
            params={"id": pregunta_id, "cmid": cmid},
            timeout=TIEMPO_ESPERA,
        )
        sopa = BeautifulSoup(getattr(pagina, "text", ""), "html.parser")
        urls = [
            urljoin(f"{self.base_url}/", str(img.get("src")))
            for img in sopa.select(".que img")
            if "pluginfile.php" in str(img.get("src") or "")
        ]
        servidas = sum(1 for url in urls if self.comprobar_pluginfile(url))
        return len(urls), servidas

    def motor_de_formulas(self, curso_id: int) -> bool:
        """¿Carga el aula su motor de fórmulas en la página del curso?

        Regla estructural medida en la espiga: el cargador del filtro MathJax aparece en el
        código de la página. Solo devuelve sí o no; el texto de Moodle no sale de aquí.
        """
        self._esperar()
        respuesta = self._reducir(
            "ERROR_MOTOR_FORMULAS",
            self.sesion.get,
            f"{self.base_url}/course/view.php",
            params={"id": curso_id},
            timeout=TIEMPO_ESPERA,
        )
        return getattr(respuesta, "status_code", 0) == 200 and (
            "filter_mathjaxloader" in getattr(respuesta, "text", "")
        )

    def comprobar_pluginfile(self, url: str) -> bool:
        """Solo mira la respuesta: con ``stream`` no se descarga el fichero entero."""
        self._esperar()
        respuesta = self._reducir(
            "ERROR_PLUGINFILE", self.sesion.get, url, timeout=TIEMPO_ESPERA, stream=True
        )
        try:
            return getattr(respuesta, "status_code", 0) == 200
        finally:
            cerrar = getattr(respuesta, "close", None)
            if callable(cerrar):
                cerrar()

    def borrar(self, curso_id: int, cmid: int) -> None:
        """Borra con la misma llamada AJAX que la página del curso.

        ``py_module.delete_module`` consulta antes el curso por una llamada
        que no siempre está disponible; aquí el curso ya se conoce.
        """
        self._esperar()
        self._reducir(
            "ERROR_BORRADO",
            _actualizar_curso,
            self.sesion,
            self.base_url,
            self.sesskey,
            curso_id,
            "cm_delete",
            [cmid],
        )

    def mover(self, curso_id: int, cmid: int, seccion_id: int, antes_de: int | None) -> None:
        """Mueve un módulo a ``seccion_id``: antes de ``antes_de`` o, sin él, al final.

        La misma llamada AJAX que la página del curso (``cm_move``); conserva cmid,
        visibilidad, restricciones e intentos.
        """
        self._esperar()
        self._reducir(
            "ERROR_MOVER",
            _actualizar_curso,
            self.sesion,
            self.base_url,
            self.sesskey,
            curso_id,
            "cm_move",
            [cmid],
            seccion_destino=seccion_id,
            antes_de=antes_de,
        )

    def crear_seccion(self, curso_id: int, nombre: str) -> int:
        """Crea una sección al final del curso, con nombre y oculta; devuelve su id."""
        self._esperar()
        nueva = self._reducir(
            "ERROR_SECCION",
            py_section.create_section,
            self.sesion,
            self.base_url,
            self.sesskey,
            curso_id,
        )
        try:
            seccion_id = int(nueva["fields"]["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ErrorPublicacion("ERROR_SECCION") from exc
        try:
            self._esperar()
            formato = self.formato_curso(curso_id)
            self._esperar()
            self._reducir(
                "SECCION_SIN_NOMBRE",
                _renombrar_seccion,
                self.sesion,
                self.base_url,
                self.sesskey,
                seccion_id,
                nombre,
                formato,
            )
            self._esperar()
            self._reducir(
                "ERROR_SECCION",
                _actualizar_curso,
                self.sesion,
                self.base_url,
                self.sesskey,
                curso_id,
                "section_hide",
                [seccion_id],
            )
        except ErrorPublicacion:
            # No dejar una sección a medias (sin nombre o visible).
            try:
                self.borrar_seccion(curso_id, seccion_id)
            except ErrorPublicacion:
                pass
            raise
        return seccion_id

    def formato_curso(self, curso_id: int) -> str:
        """Formato del curso («topics», «weeks», «onetopic»…), de la clase del body.

        Solo se extrae ese identificador; nada del HTML sale de aquí. Si no se
        reconoce, se asume «topics», el formato por defecto de Moodle.
        """
        self._esperar()
        respuesta = self._reducir(
            "ERROR_SECCION",
            self.sesion.get,
            f"{self.base_url}/course/view.php?id={curso_id}",
            timeout=TIEMPO_ESPERA,
        )
        return formato_de_html(getattr(respuesta, "text", "") or "")

    def borrar_seccion(self, curso_id: int, seccion_id: int) -> None:
        self._esperar()
        self._reducir(
            "ERROR_BORRADO",
            _actualizar_curso,
            self.sesion,
            self.base_url,
            self.sesskey,
            curso_id,
            "section_delete",
            [seccion_id],
        )

    # --- Cuestionarios: banco de preguntas y huecos -------------------------

    def categoria_cuestionario(self, cmid: int) -> str:
        """La opción «catid,contextid» del banco del propio cuestionario.

        El formulario de importación preselecciona la categoría del curso; hay que
        elegir la del contexto del módulo para que las preguntas vivan y se borren
        con el cuestionario.
        """
        contexto = self.leer_modulo(cmid).get("contexto")
        if not isinstance(contexto, int):
            raise ErrorPublicacion("ERROR_IMPORTACION")
        formulario, _url = self._formulario_importacion(cmid)
        for opcion in formulario.select('select[name="category"] option'):
            valor = opcion.get("value") or ""
            if _CATEGORIA.match(valor) and valor.endswith(f",{contexto}"):
                return valor
        raise ErrorPublicacion("ERROR_IMPORTACION")

    def preguntas_en_categoria(self, cmid: int, categoria: str) -> set[int]:
        """Ids de las preguntas que hay en esa categoría (las del cuestionario)."""
        self._esperar()
        respuesta = self._reducir(
            "ERROR_CONSULTA",
            self.sesion.get,
            f"{self.base_url}/question/edit.php",
            params={"cmid": cmid, "cat": categoria, "qperpage": 1000},
            timeout=TIEMPO_ESPERA,
        )
        self._reducir("ERROR_CONSULTA", respuesta.raise_for_status)
        return {
            int(identificador) for identificador in re.findall(r'name="q(\d+)"', respuesta.text)
        }

    def importar_preguntas(self, curso_id: int, cmid: int, categoria: str, xml: bytes) -> list[int]:
        """Importa el XML en la categoría del módulo y devuelve los ids nuevos.

        Los ids los asigna Moodle en orden creciente, así que el orden ascendente
        es el orden del XML.
        """
        antes = self.preguntas_en_categoria(cmid, categoria)
        formulario, url_formulario = self._formulario_importacion(cmid)
        datos = py_module._extract_modedit_form_data(formulario)
        datos["category"] = categoria
        itemid_form = str(datos.get("newfile") or "")
        itemid = int(itemid_form) if itemid_form.isdigit() else int(time.time() * 1000)

        with tempfile.TemporaryDirectory(prefix="tiza-preguntas-") as temporal:
            ruta = Path(temporal) / "preguntas.xml"
            ruta.write_bytes(xml)
            contexto = self.contexto(curso_id)
            _itemid, nombre_final = self.subir(curso_id, contexto, ruta, itemid)

        datos.update(
            {
                "format": "xml",
                "newfile": str(itemid),
                "matchgrades": "error",  # cualquier desajuste se rechaza, no se redondea
                "submitbutton": "Importar",
            }
        )
        datos.setdefault("sesskey", self.sesskey)
        url = f"{self.base_url}/question/bank/importquestions/import.php?cmid={cmid}"
        destino = urljoin(url_formulario, formulario.get("action") or url)
        self._esperar()
        respuesta = self._reducir(
            "ERROR_IMPORTACION",
            self.sesion.post,
            destino,
            data=datos,
            timeout=TIEMPO_ESPERA,
            allow_redirects=False,
        )
        if getattr(respuesta, "status_code", 0) not in (301, 302, 303) and (
            "question/edit.php" not in (getattr(respuesta, "text", "") or "")
        ):
            raise ErrorPublicacion("ERROR_IMPORTACION")
        despues = self.preguntas_en_categoria(cmid, categoria)
        return sorted(despues - antes)

    def anadir_preguntas(self, cmid: int, ids: list[int]) -> None:
        """Añade las preguntas al cuestionario en el orden dado."""
        datos: list[tuple[str, str]] = [
            ("cmid", str(cmid)),
            ("sesskey", self.sesskey),
            ("add", "1"),
            ("addonpage", "0"),
        ]
        datos += [(f"q{identificador}", "1") for identificador in ids]
        self._esperar()
        respuesta = self._reducir(
            "ERROR_ANADIR_PREGUNTAS",
            self.sesion.post,
            f"{self.base_url}/mod/quiz/edit.php",
            data=datos,
            timeout=TIEMPO_ESPERA,
            allow_redirects=False,
        )
        if getattr(respuesta, "status_code", 0) not in (301, 302, 303):
            raise ErrorPublicacion("ERROR_ANADIR_PREGUNTAS")

    def huecos(self, cmid: int) -> list[tuple[int, int | None]]:
        """Pares (hueco, pregunta) en el orden de la página; None si está vacío."""
        return _huecos_de_html(self._leer_edicion_cuestionario(cmid))

    def tiene_intentos(self, cmid: int) -> bool:
        """Falso solo si el cuestionario no tiene intentos.

        Moodle quita el menú de añadir preguntas (`data-action="addquestion"`) en
        cuanto hay un intento. No se leen cuántos ni de quién.
        """
        html = self._leer_edicion_cuestionario(cmid)
        if re.search(r'data-action=["\']addquestion["\']', html):
            return False
        if 'id="slot-' in html or "mod/quiz/edit.php" in html:
            return True
        raise ErrorPublicacion("ERROR_CONSULTA")

    def quitar_hueco(self, curso_id: int, quizid: int, hueco: int) -> None:
        self._esperar()
        respuesta = self._reducir(
            "ERROR_QUITAR_PREGUNTAS",
            self.sesion.post,
            f"{self.base_url}/mod/quiz/edit_rest.php",
            data={
                "sesskey": self.sesskey,
                "courseid": str(curso_id),
                "quizid": str(quizid),
                "class": "resource",
                "action": "DELETE",
                "id": str(hueco),
            },
            timeout=TIEMPO_ESPERA,
        )
        if getattr(respuesta, "status_code", 0) != 200:
            raise ErrorPublicacion("ERROR_QUITAR_PREGUNTAS")
        try:
            datos = respuesta.json()
        except (json.JSONDecodeError, ValueError):
            raise ErrorPublicacion("ERROR_QUITAR_PREGUNTAS") from None
        if isinstance(datos, dict) and "error" in datos:
            # Moodle se niega porque un alumno empezó un intento hace un momento.
            raise ErrorPublicacion("CUESTIONARIO_CON_INTENTOS", DETALLE_INTENTOS_REPUBLICAR)
        if not (isinstance(datos, dict) and datos.get("deleted") is True):
            raise ErrorPublicacion("ERROR_QUITAR_PREGUNTAS")

    def borrar_preguntas(self, cmid: int, ids: list[int]) -> None:
        """Borra preguntas del banco con la confirmación que pide Moodle."""
        if not ids:
            return
        base = self.base_url
        url = f"{base}/question/bank/deletequestion/delete.php"
        volver = f"/question/edit.php?cmid={cmid}"
        datos: list[tuple[str, str]] = [
            ("sesskey", self.sesskey),
            ("cmid", str(cmid)),
            ("returnurl", volver),
            ("deleteselected", "1"),
        ]
        datos += [(f"q{identificador}", "1") for identificador in ids]
        self._esperar()
        pagina = self._reducir(
            "ERROR_BORRAR_PREGUNTAS", self.sesion.post, url, data=datos, timeout=TIEMPO_ESPERA
        )
        self._reducir("ERROR_BORRAR_PREGUNTAS", pagina.raise_for_status)
        formulario = next(
            (
                formulario
                for formulario in BeautifulSoup(pagina.text, "html.parser").find_all("form")
                if "deletequestion/delete.php" in (formulario.get("action") or "")
                and formulario.find("input", attrs={"name": "confirm"})
            ),
            None,
        )
        if formulario is not None:
            campos = {
                campo.get("name"): campo.get("value", "")
                for campo in formulario.find_all("input")
                if campo.get("name") and campo.get("type") not in ("submit", "button")
            }
            campos.setdefault("sesskey", self.sesskey)
            destino = urljoin(pagina.url, formulario.get("action"))
        else:
            # Lo que haría delete.php sin formulario: confirm es el md5 de la lista.
            lista = ",".join(str(identificador) for identificador in ids)
            campos = {
                "sesskey": self.sesskey,
                "cmid": str(cmid),
                "returnurl": volver,
                "deleteselected": lista,
                "confirm": hashlib.md5(lista.encode()).hexdigest(),
            }
            destino = url
        self._esperar()
        respuesta = self._reducir(
            "ERROR_BORRAR_PREGUNTAS",
            self.sesion.post,
            destino,
            data=campos,
            timeout=TIEMPO_ESPERA,
            allow_redirects=False,
        )
        if getattr(respuesta, "status_code", 0) not in (301, 302, 303):
            raise ErrorPublicacion("ERROR_BORRAR_PREGUNTAS")

    def _formulario_importacion(self, cmid: int) -> tuple[Any, str]:
        """El formulario de importación de preguntas y la URL desde la que se cargó."""
        self._esperar()
        url = f"{self.base_url}/question/bank/importquestions/import.php?cmid={cmid}"
        pagina = self._reducir("ERROR_IMPORTACION", self.sesion.get, url, timeout=TIEMPO_ESPERA)
        self._reducir("ERROR_IMPORTACION", pagina.raise_for_status)
        sopa = BeautifulSoup(pagina.text, "html.parser")
        formulario = next(
            (
                formulario
                for formulario in sopa.find_all("form")
                if _tiene_campo(formulario, "newfile")
            ),
            None,
        )
        if formulario is None:
            raise ErrorPublicacion("ERROR_IMPORTACION")
        return formulario, str(getattr(pagina, "url", None) or url)

    def _leer_edicion_cuestionario(self, cmid: int) -> str:
        self._esperar()
        respuesta = self._reducir(
            "ERROR_CONSULTA",
            self.sesion.get,
            f"{self.base_url}/mod/quiz/edit.php",
            params={"cmid": cmid},
            timeout=TIEMPO_ESPERA,
        )
        self._reducir("ERROR_CONSULTA", respuesta.raise_for_status)
        return getattr(respuesta, "text", "") or ""

    # --- Actividades H5P: despliegue e intentos ------------------------------

    # ------------------------------------------------------------------ #
    # Calificador (solo estructura: tiza no lee nunca notas)
    # ------------------------------------------------------------------ #

    def _pagina_del_calificador(self, ruta: str, params: dict[str, int]) -> str:
        """El HTML de una página del calificador; una redirección es falta de permiso.

        Tras crear o borrar un elemento, o cambiar un máximo o un peso, Moodle devuelve primero
        la página «Recalculando calificaciones» (``div.progressbar_container``, sin el árbol):
        se repite el mismo GET. El límite son 3 lecturas de página
        (``_PETICIONES_POR_RECALCULO``) y cada una puede seguir una redirección (a su propia
        aula), así que son hasta 6 peticiones HTTP. Si sigue, lo ve quien llama.
        """
        for _ in range(_PETICIONES_POR_RECALCULO):
            html = self._leer_pagina_del_calificador(ruta, params)
            if not _es_recalculo(html):
                return html
        return html

    def _leer_pagina_del_calificador(self, ruta: str, params: dict[str, int]) -> str:
        self._esperar()
        respuesta = self._reducir(
            "ERROR_CONSULTA",
            self.sesion.get,
            f"{self.base_url}/{ruta}",
            params=params,
            allow_redirects=False,
            timeout=TIEMPO_ESPERA,
        )
        if 300 <= getattr(respuesta, "status_code", 200) < 400:
            # Justo después de escribir, Moodle puede redirigir a otra página del calificador
            # (p. ej. el recálculo): se sigue una vez. Al login, a otra aula o a un informe de
            # notas, falta de permiso (y al informe de notas ni siquiera se pide).
            destino = str((getattr(respuesta, "headers", None) or {}).get("Location", ""))
            if not destino:
                raise ErrorPublicacion("CALIFICADOR_NO_PERMITIDO")
            if not _es_del_mismo_aula(self.base_url, destino):
                raise ErrorPublicacion("CALIFICADOR_NO_PERMITIDO")  # solo a su propia aula
            if _redirige_al_login(self.base_url, destino):
                raise ErrorPublicacion("CALIFICADOR_NO_PERMITIDO")
            if _es_informe_de_notas(self.base_url, destino):
                raise ErrorPublicacion("CALIFICADOR_NO_PERMITIDO")
            resuelta = _resolver_destino(self.base_url, destino)
            self._esperar()
            respuesta = self._reducir(
                "ERROR_CONSULTA",
                self.sesion.get,
                resuelta,
                allow_redirects=False,
                timeout=TIEMPO_ESPERA,
            )
            if 300 <= getattr(respuesta, "status_code", 200) < 400:
                raise ErrorPublicacion("CALIFICADOR_NO_PERMITIDO")
        self._reducir("ERROR_CONSULTA", respuesta.raise_for_status)
        return str(getattr(respuesta, "text", ""))

    def _formula_del_elemento(self, curso_id: int, item_id: int) -> str:
        """La fórmula de un elemento calculado o categoría, o vacío si no tiene."""
        texto = BeautifulSoup(
            self._pagina_del_calificador(
                "grade/edit/tree/calculation.php", {"courseid": curso_id, "id": item_id}
            ),
            "html.parser",
        )
        calculo = _campo_con_nombre(texto, "calculation")
        if calculo is None:
            return ""
        if calculo.name == "textarea":
            return calculo.get_text().strip()
        return str(calculo.get("value") or "").strip()

    def calificador(self, curso_id: int, tocados: Collection[str] | None = None) -> CalificadorAula:
        """La estructura del calificador del curso: categorías, elementos, pesos, bloqueos y fórmulas.

        Abre el árbol y el formulario de cada elemento y categoría, nunca un informe de notas
        (``grade/report/``). Que un elemento tiene notas se sabe solo por la presencia del campo
        ``rescalegrades`` de su formulario. Lo que devuelve es dato estructural; el texto de
        Moodle no sale de aquí salvo los nombres, que solo ve el docente.

        ``tocados`` (los ``eid`` que se acaban de cambiar; ``ig<n>`` vale también para el total
        de una categoría, que es el elemento ``n``) es releer tras escribir: el árbol se lee
        entero, pero los formularios solo de lo tocado, lo nuevo, lo movido y los hermanos de
        todo eso (Moodle normaliza los pesos de una categoría), y del curso; lo demás sale de la
        lectura anterior. Si algo desapareció (un borrado), se relee todo: una fórmula podía
        apuntar a lo borrado. Sin ``tocados``, o sin lectura anterior, se lee todo.
        """
        pagina = self._pagina_del_calificador("grade/edit/tree/index.php", {"id": curso_id})
        sopa = BeautifulSoup(pagina, "html.parser")
        if sopa.find("form", id="gradetreeform") is None:
            raise ErrorPublicacion("CALIFICADOR_NO_PERMITIDO")
        filas = [
            fila
            for fila in sopa.find_all("tr")
            if ("data-category" in fila.attrs or "data-itemid" in fila.attrs)
            and "data-aggregationforcategory" not in fila.attrs
            and not _actividad_en_borrado(fila)
        ]
        previos = self._formularios.get(curso_id) if tocados is not None else None
        releer = None if previos is None else _a_releer(filas, previos, tocados or ())
        parciales: list[dict[str, Any]] = []
        for fila in filas:
            es_categoria = "data-category" in fila.attrs
            eid = str(fila["data-category"]) if es_categoria else f"ig{fila['data-itemid']}"
            item_id = int(str(fila["data-itemid"]))
            padre = fila.get("data-parent-category")
            agregacion = _numero(fila.get("data-aggregation")) if es_categoria else None
            titulo = fila.find(class_="rowtitle")
            enlace = fila.find("a", class_="gradeitemheader", href=_ENLACE_DE_ACTIVIDAD)
            coincidencia = _ENLACE_DE_ACTIVIDAD.search(str(enlace["href"])) if enlace else None
            if previos is not None and releer is not None and eid not in releer:
                anterior = dict(previos[eid])
                anterior.update(
                    item_id=item_id,
                    nombre=titulo.get_text(" ", strip=True) if titulo else "",
                    padre_eid=str(padre) if padre else None,
                    maximo=_numero(fila.get("data-grademax")),
                    cmid=int(coincidencia.group(1)) if coincidencia else None,
                    agregacion=int(agregacion) if agregacion is not None else None,
                )
                parciales.append(anterior)
                continue
            if es_categoria:
                ruta, numero = "grade/edit/tree/category.php", int(eid[2:])
            else:
                ruta, numero = "grade/edit/tree/item.php", item_id
            formulario = BeautifulSoup(
                self._pagina_del_calificador(ruta, {"courseid": curso_id, "id": numero}),
                "html.parser",
            )
            if formulario.find("form") is None:
                raise ErrorPublicacion("ERROR_CONSULTA")
            pref = "grade_item_" if es_categoria else ""
            if es_categoria or coincidencia is None:
                formula = self._formula_del_elemento(curso_id, item_id)
            else:
                formula = ""
            parciales.append(
                {
                    "eid": eid,
                    "item_id": item_id,
                    "es_categoria": es_categoria,
                    "idnumber": _valor_de_campo(formulario, pref + "idnumber"),
                    "nombre": titulo.get_text(" ", strip=True) if titulo else "",
                    "padre_eid": str(padre) if padre else None,
                    "coef": _valor_de_campo(formulario, pref + "aggregationcoef2"),
                    "grademax_formulario": _valor_de_campo(formulario, pref + "grademax"),
                    "sobrescrito": _casilla_marcada(formulario, pref + "weightoverride"),
                    "bloqueado": _casilla_marcada(formulario, pref + "locked"),
                    "oculto": not es_categoria and _casilla_marcada(formulario, "hidden"),
                    "tiene_notas": _campo_con_nombre(formulario, "rescalegrades") is not None,
                    "formula": formula or None,
                    "maximo": _numero(fila.get("data-grademax")),
                    "cmid": int(coincidencia.group(1)) if coincidencia else None,
                    "agregacion": int(agregacion) if agregacion is not None else None,
                }
            )
        self._arbol[curso_id] = {p["eid"] for p in parciales}
        self._formularios[curso_id] = {p["eid"]: p for p in parciales}
        # Una categoría tiene notas si las tiene algo de dentro.
        padre_de = {p["eid"]: p["padre_eid"] for p in parciales}
        con_notas: set[str] = set()
        for p in parciales:
            actual: str | None = p["eid"] if p["tiene_notas"] else None
            while actual is not None and actual not in con_notas:
                con_notas.add(actual)
                actual = padre_de.get(actual)
        nodos = []
        for p in parciales:
            if p["es_categoria"]:
                clase = "categoria" if p["padre_eid"] else "curso"
            elif p["cmid"] is not None:
                clase = "actividad"
            else:
                clase = "calculado" if p["formula"] else "manual"
            nodos.append(
                NodoAula(
                    eid=p["eid"],
                    item_id=p["item_id"],
                    idnumber=p["idnumber"],
                    clase=clase,
                    nombre=p["nombre"],
                    padre_eid=p["padre_eid"],
                    peso=None if clase == "curso" else _numero(p["coef"]),
                    sobrescrito=p["sobrescrito"],
                    bloqueado=p["bloqueado"],
                    tiene_notas=p["eid"] in con_notas,
                    formula=p["formula"],
                    maximo=p["maximo"],
                    cmid=p["cmid"],
                    agregacion=p["agregacion"],
                    oculto=p["oculto"],
                )
            )
        decimal = _decimal_visto(parciales)
        if not decimal:
            # Un curso limpio solo tiene enteros: el máximo por defecto del formulario de alta
            # (sin ``id``) sí lleva decimales («100,00») en el idioma del aula.
            alta = BeautifulSoup(
                self._pagina_del_calificador("grade/edit/tree/item.php", {"courseid": curso_id}),
                "html.parser",
            )
            decimal = _decimal_de(_valor_de_campo(alta, "grademax")) or "."
        return CalificadorAula(nodos=tuple(nodos), decimal=decimal)

    # --- Calificador: escribir (los envíos medidos en las espigas) --------------

    def _enviar_formulario(
        self,
        ruta: str,
        params: dict[str, int],
        cambios: dict[str, str],
        codigo: str = "ESCRITURA_CALIFICADOR",
        si_existen: dict[str, str] | None = None,
    ) -> Any:
        """GET del formulario, cambia campos y lo envía como un navegador; devuelve la respuesta.

        El texto de Moodle no sale de aquí: quien llama decide qué es un 303 (guardado) y qué
        un 200 (el formulario vuelto a mostrar, o sea, rechazado).
        """
        pagina = self._pagina_del_calificador(ruta, params)
        accion = re.compile(re.escape(ruta.rsplit("/", 1)[-1]))
        formulario = _formulario_de(pagina, accion)
        if formulario is None:
            raise ErrorPublicacion(codigo)
        cambios = dict(cambios)
        for nombre, valor in (si_existen or {}).items():
            if _campo_con_nombre(formulario, nombre) is not None:
                cambios[nombre] = valor
        pares = [(k, v) for k, v in _campos_de_formulario(formulario) if k not in cambios]
        pares += list(cambios.items())
        pares.append(("submitbutton", "Guardar cambios"))
        destino = urljoin(f"{self.base_url}/", str(formulario["action"]))
        self._esperar()
        return self._reducir(
            codigo,
            self.sesion.post,
            destino,
            data=pares,
            allow_redirects=False,
            timeout=TIEMPO_ESPERA,
        )

    @staticmethod
    def _guardado(respuesta: Any) -> bool:
        """¿Es la respuesta una redirección de guardado? Una que va al login es sesión caducada."""
        if getattr(respuesta, "status_code", 0) not in (301, 302, 303):
            return False
        destino = (getattr(respuesta, "headers", None) or {}).get("Location", "")
        if "/login/" in str(destino):
            raise ErrorPublicacion("SESION_CADUCADA")
        return True

    def _guardar(
        self,
        ruta: str,
        params: dict[str, int],
        cambios: dict[str, str],
        si_existen: dict[str, str] | None = None,
    ) -> None:
        respuesta = self._enviar_formulario(ruta, params, cambios, si_existen=si_existen)
        if not self._guardado(respuesta):
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")

    def _es_raiz(self, curso: int, eid: str) -> bool:
        """¿Es ``eid`` la categoría raíz del curso (la fila sin padre)?"""
        pagina = self._pagina_del_calificador("grade/edit/tree/index.php", {"id": curso})
        return any(
            str(f.get("data-category")) == eid and "data-parent-category" not in f.attrs
            for f in BeautifulSoup(pagina, "html.parser").find_all("tr")
        )

    def _filas_del_arbol(self, curso: int) -> dict[str, str | None]:
        """Los ``eid`` del árbol, en orden, con el ``eid`` de su categoría (``None``: la raíz)."""
        pagina = self._pagina_del_calificador("grade/edit/tree/index.php", {"id": curso})
        sopa = BeautifulSoup(pagina, "html.parser")
        filas: dict[str, str | None] = {}
        for fila in sopa.find_all("tr"):
            if "data-aggregationforcategory" in fila.attrs:
                continue
            padre = fila.get("data-parent-category")
            if "data-category" in fila.attrs:
                filas[str(fila["data-category"])] = str(padre) if padre else None
            elif "data-itemid" in fila.attrs:
                filas[f"ig{fila['data-itemid']}"] = str(padre) if padre else None
        return filas

    def _crear_y_buscar(
        self,
        curso: int,
        ruta: str,
        params: dict[str, int],
        cambios: dict[str, str],
        prefijo: str,
        padre_eid: str | None,
    ) -> str:
        """Envía el formulario de alta y devuelve el ``eid`` nuevo (el que aparece en el árbol).

        El árbol de antes es el de la última lectura (``calificador`` o el alta anterior), así
        que cada alta lee el árbol una vez, no dos. Si aparece más de uno nuevo (lo recordado
        es de antes de otra alta, p. ej. una actividad publicada), el de tiza es el que cuelga
        de la categoría pedida.
        """
        antes = self._arbol.pop(curso, None)
        if antes is None:
            antes = set(self._filas_del_arbol(curso))
        self._guardar(ruta, params, cambios)
        filas = self._filas_del_arbol(curso)
        if not filas:  # la página de recálculo, que no trae el árbol
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        self._arbol[curso] = set(filas)
        nuevos = [e for e in filas if e not in antes and e.startswith(prefijo)]
        if len(nuevos) > 1:
            raiz = next((e for e, padre in filas.items() if padre is None), None)
            nuevos = [e for e in nuevos if filas[e] == (padre_eid or raiz)]
        if len(nuevos) != 1:
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        return nuevos[0]

    def crear_categoria(
        self,
        curso: int,
        nombre: str,
        idnumber: str,
        padre_eid: str | None,
        peso: float | None,
        visualizacion: str | None,
        agregacion: int = 13,
    ) -> str:
        """Crea una categoría «solo lo calificado» y devuelve su ``eid`` (``cg<id>``).

        ``agregacion`` es la de Moodle (13 Natural, 2 Mediana, 6 Calificación más alta).
        ``peso`` no nulo la pesa en su padre; con ``None`` (hijos de un contador) no se
        sobrescribe el peso. ``visualizacion == "porcentaje"`` muestra el total en porcentaje.
        """
        cambios = {
            "fullname": nombre,
            "grade_item_idnumber": idnumber,
            "aggregation": str(agregacion),
            "aggregateonlygraded": "1",
        }
        if padre_eid is not None:
            _validar_eid(padre_eid, "cg")
            cambios["parentcategory"] = padre_eid[2:]
        if peso is not None:
            cambios["grade_item_weightoverride"] = "1"
            cambios["grade_item_aggregationcoef2"] = _texto_numero(peso)
        if visualizacion == "porcentaje":
            cambios["grade_item_display"] = "2"
        return self._crear_y_buscar(
            curso,
            "grade/edit/tree/category.php",
            {"courseid": curso, "id": 0},
            cambios,
            "cg",
            padre_eid,
        )

    def crear_calculado(
        self,
        curso: int,
        nombre: str,
        idnumber: str,
        padre_eid: str | None,
        peso: float | None,
        maximo: float,
        oculto: bool = False,
    ) -> str:
        """Crea un elemento manual con ``grademax`` y devuelve su ``eid`` (``ig<id>``).

        Sin fórmula: va después con ``fijar_formula`` (segunda pasada). Con ``oculto``, el alta
        lleva ``hidden=1`` en la misma petición: el alumnado no lo ve desde el primer momento.
        """
        cambios = {
            "itemname": nombre,
            "idnumber": idnumber,
            "grademax": _texto_numero(maximo),
            "grademin": "0",
        }
        if oculto:
            cambios["hidden"] = "1"
        if padre_eid is not None:
            _validar_eid(padre_eid, "cg")
            cambios["parentcategory"] = padre_eid[2:]
        if peso is not None:
            cambios["weightoverride"] = "1"
            cambios["aggregationcoef2"] = _texto_numero(peso)
        return self._crear_y_buscar(
            curso, "grade/edit/tree/item.php", {"courseid": curso}, cambios, "ig", padre_eid
        )

    def fijar_maximo(self, curso: int, item_id: int, maximo: float) -> None:
        """El máximo de un elemento (indicadores y copias del contador).

        Si el elemento ya tiene notas, Moodle exige elegir en ``rescalegrades``: se elige «no»
        (no recalcular), porque son elementos calculados y su fórmula redefine el valor.
        """
        self._guardar(
            "grade/edit/tree/item.php",
            {"courseid": curso, "id": item_id},
            {"grademax": _texto_numero(maximo)},
            si_existen={"rescalegrades": "no"},
        )

    def fijar_peso(self, curso: int, eid: str, peso: float) -> None:
        """Sobrescribe el peso de una categoría (``cg<id>``) o de un elemento (``ig<id>``)."""
        _validar_eid(eid)
        numero = int(eid[2:])
        if eid.startswith("cg"):
            self._guardar(
                "grade/edit/tree/category.php",
                {"courseid": curso, "id": numero},
                {
                    "grade_item_weightoverride": "1",
                    "grade_item_aggregationcoef2": _texto_numero(peso),
                },
            )
        else:
            self._guardar(
                "grade/edit/tree/item.php",
                {"courseid": curso, "id": numero},
                {"weightoverride": "1", "aggregationcoef2": _texto_numero(peso)},
            )

    def fijar_agregacion(self, curso: int, eid: str, agregacion: int) -> None:
        """Cambia la agregación de una categoría (D13); no pide confirmación aunque tenga notas."""
        _validar_eid(eid, "cg")
        self._guardar(
            "grade/edit/tree/category.php",
            {"courseid": curso, "id": int(eid[2:])},
            {"aggregation": str(agregacion), "aggregateonlygraded": "1"},
        )

    def fijar_formula(self, curso: int, item_id: int, formula: str, decimal: str) -> None:
        """Fija la fórmula de un elemento calculado.

        ``formula`` va en la notación interna (separador «,», decimal con punto) y se traduce con
        ``decimal`` (el del aula: ``calificador().decimal``). Un 200 es «Fórmula no válida»
        (referencias recién creadas: espiga 4): se reintenta una vez antes de dar el error.
        """
        traducida = formula_moodle(formula, decimal)
        for _ in range(2):
            respuesta = self._enviar_formulario(
                "grade/edit/tree/calculation.php",
                {"courseid": curso, "id": item_id},
                {"calculation": traducida},
            )
            if self._guardado(respuesta):
                return
            if getattr(respuesta, "status_code", 0) != 200:
                raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        raise ErrorPublicacion("FORMULA_NO_VALIDA")

    def _accion_del_calificador(self, ruta: str, params: dict[str, Any]) -> None:
        self._esperar()
        respuesta = self._reducir(
            "ESCRITURA_CALIFICADOR",
            self.sesion.get,
            f"{self.base_url}/{ruta}",
            params=params,
            allow_redirects=False,
            timeout=TIEMPO_ESPERA,
        )
        if not self._guardado(respuesta):
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")

    def bloquear_total(self, curso: int, item_id: int) -> None:
        """Bloquea el total con la acción del menú sobre ``ig<id>``; nunca ``cg`` (cascada).

        tiza nunca desbloquea. Que el aula acepte la orden no prueba que bloquee:
        ``Ejecucion`` relee el calificador después y exige ``bloqueado`` en cada total.
        """
        self._accion_del_calificador(
            "grade/edit/tree/action.php",
            {
                "id": curso,
                "sesskey": self.sesskey,
                "eid": f"ig{item_id}",
                "action": "lock",
                "gpr_type": "edit",
                "gpr_plugin": "tree",
                "gpr_courseid": curso,
            },
        )

    def ocultar(self, curso: int, item_id: int) -> None:
        """Oculta al alumnado un elemento con la acción del menú sobre ``ig<id>``.

        Que el aula acepte la orden no prueba que oculte: ``calificador_con`` comprueba al final
        que ningún calculado de tiza sigue visible (``OCULTAR_FALLIDO``). tiza nunca desoculta.
        """
        self._accion_del_calificador(
            "grade/edit/tree/action.php",
            {
                "id": curso,
                "sesskey": self.sesskey,
                "eid": f"ig{item_id}",
                "action": "hide",
                "gpr_type": "edit",
                "gpr_plugin": "tree",
                "gpr_courseid": curso,
            },
        )

    def ajuste_totales(self, curso: int) -> int | None:
        """El ajuste del curso «Ocultar totales si contienen ítems ocultos».

        Devuelve ``-1`` (por defecto del sitio), ``0`` (ocultar), ``1`` (mostrar incluyendo los
        ocultos) o ``2`` (mostrar excluyéndolos). Si no se puede leer, ``None``: no es un fallo
        de la publicación. La opción marcada manda; si ninguna lleva ``selected`` (el ``-1``),
        vale la primera.
        """
        try:
            pagina = self._pagina_del_calificador("grade/edit/settings/index.php", {"id": curso})
        except ErrorPublicacion:
            return None
        select = BeautifulSoup(pagina, "html.parser").find(
            "select", attrs={"name": "report_user_showtotalsifcontainhidden"}
        )
        if select is None:
            return None
        opciones = select.find_all("option")
        elegida = next((o for o in opciones if o.has_attr("selected")), None)
        if elegida is None and opciones:
            elegida = opciones[0]
        if elegida is None:
            return None
        try:
            valor = int(str(elegida.get("value") or "").strip())
        except ValueError:
            return None
        return valor if valor in (-1, 0, 1, 2) else None

    def colocar_actividad(
        self, curso: int, cmid: int, categoria_id: int, idnumber: str | None
    ) -> None:
        """Mueve la actividad a una categoría (``gradecat``) y, si hace falta, le da número de ID.

        ``actualizar`` reenvía el formulario del módulo conservando el resto de campos.
        """
        payload = {"gradecat": str(categoria_id)}
        if idnumber:
            payload["cmidnumber"] = idnumber
        self.actualizar(cmid, payload)

    def mover_manual(self, curso: int, item_id: int, categoria_eid: str) -> None:
        """Mueve un elemento manual al principio de una categoría (``first=1``; espiga 2)."""
        self.mover_nota(curso, f"ig{item_id}", categoria_eid, None)

    def mover_nota(self, curso: int, eid: str, categoria: str, despues_de: str | None) -> None:
        """Mueve un elemento a una categoría, detrás de ``despues_de`` (``None``: al principio)."""
        _validar_eid(eid)
        _validar_eid(categoria, "cg")
        if despues_de is not None:
            _validar_eid(despues_de)
        params: dict[str, Any] = {
            "id": curso,
            "action": "move",
            "eid": eid,
            "moveafter": despues_de or categoria,
        }
        if despues_de is None:
            params["first"] = 1
        params["sesskey"] = self.sesskey
        self._accion_del_calificador("grade/edit/tree/index.php", params)

    def arbol_notas(self, curso: int) -> colocacion.ArbolNotas:
        """El árbol del calificador, ligero: orden, padre, cmid, candado y marca de tiza.

        Una lectura de ``grade/edit/tree/index.php`` sin los totales; el candado se ve en la fila
        de total de cada categoría. Solo se abre el formulario de las categorías hijas de la
        raíz, para leer su número de ID: ``TZ_`` marca esa categoría y todo lo que cuelga de ella.
        """
        pagina = self._pagina_del_calificador("grade/edit/tree/index.php", {"id": curso})
        if _es_recalculo(pagina):
            raise ErrorPublicacion("ERROR_CONSULTA")
        sopa = BeautifulSoup(pagina, "html.parser")
        if sopa.find("form", id="gradetreeform") is None:
            raise ErrorPublicacion("CALIFICADOR_NO_PERMITIDO")
        candados = {
            str(fila["data-aggregationforcategory"])
            for fila in sopa.find_all("tr")
            if "data-aggregationforcategory" in fila.attrs and fila.select_one(".fa-lock")
        }
        datos: list[tuple[str, str | None, int | None, str]] = []
        for fila in sopa.find_all("tr"):
            if "data-aggregationforcategory" in fila.attrs:
                continue
            if "data-category" in fila.attrs:
                eid = str(fila["data-category"])
            elif "data-itemid" in fila.attrs:
                eid = f"ig{fila['data-itemid']}"
            else:
                continue
            padre = fila.get("data-parent-category")
            titulo = fila.find(class_="rowtitle")
            enlace = fila.find("a", class_="gradeitemheader", href=_ENLACE_DE_ACTIVIDAD)
            coincidencia = _ENLACE_DE_ACTIVIDAD.search(str(enlace["href"])) if enlace else None
            datos.append(
                (
                    eid,
                    str(padre) if padre else None,
                    int(coincidencia.group(1)) if coincidencia else None,
                    titulo.get_text(" ", strip=True) if titulo else "",
                )
            )
        raiz = next((eid for eid, padre, _, _ in datos if padre is None), None)
        if raiz is None:  # sin fila raíz no hay árbol que colocar: una lectura que no vale
            raise ErrorPublicacion("ERROR_CONSULTA")
        de_tiza: set[str] = set()
        for eid, padre, _, _ in datos:
            if padre != raiz or not eid.startswith("cg"):
                continue
            formulario = BeautifulSoup(
                self._pagina_del_calificador(
                    "grade/edit/tree/category.php", {"courseid": curso, "id": int(eid[2:])}
                ),
                "html.parser",
            )
            if _valor_de_campo(formulario, "grade_item_idnumber").startswith("TZ_"):
                de_tiza.add(eid)
        for eid, padre, _, _ in datos:  # el orden de la página pone el padre antes que el hijo
            if padre in de_tiza:
                de_tiza.add(eid)
        return colocacion.ArbolNotas(
            tuple(
                colocacion.FilaNota(
                    eid=eid,
                    padre=padre,
                    cmid=cmid,
                    nombre=nombre,
                    bloqueada=eid in candados,
                    de_tiza=eid in de_tiza,
                )
                for eid, padre, cmid, nombre in datos
            )
        )

    def borrar_nodo(self, curso: int, eid: str) -> None:
        """Borra un nodo del calificador por su ``eid``.

        Aquí solo se valida la forma del eid y que no sea la categoría raíz (el total del
        curso). Que sea una copia o una categoría ``TZ_`` sin notas lo decide quien llama
        (la reconciliación, tarea 6); este método no lo comprueba.
        """
        _validar_eid(eid)
        if eid.startswith("cg") and self._es_raiz(curso, eid):
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        self._accion_del_calificador(
            "grade/edit/tree/index.php",
            {
                "id": curso,
                "action": "delete",
                "eid": eid,
                "sesskey": self.sesskey,
                "confirm": 1,
            },
        )

    def fijar_total_curso(self, curso: int, formula: str | None, decimal: str) -> None:
        """El total del curso: con fórmula, calculado con máximo 10; sin ella, en porcentaje.

        Solo para un curso sin calificador anterior. Sin fórmula, si el total tenía una (la del
        tope que se acaba de quitar), también la vacía: si no, el curso seguiría calculándose
        con la fórmula vieja.

        Con fórmula, Moodle deja la raíz con ``aggregateonlygraded=0``: al ponerla, el formulario
        de la raíz ya no trae ``aggregation`` ni ``aggregateonlygraded`` y el reenvío del máximo
        guarda la casilla desmarcada (no tiene arreglo por POST). Es inocuo mientras haya fórmula,
        porque la agregación no se usa; si el docente la quita, debe volver a marcar «solo
        calificaciones no vacías» en el total del curso.
        """
        pagina = self._pagina_del_calificador("grade/edit/tree/index.php", {"id": curso})
        fila = next(
            (
                f
                for f in BeautifulSoup(pagina, "html.parser").find_all("tr")
                if "data-category" in f.attrs and "data-parent-category" not in f.attrs
            ),
            None,
        )
        if fila is None:
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        try:
            item_id = int(str(fila["data-itemid"]))
            categoria = int(str(fila["data-category"])[2:])
        except (KeyError, ValueError) as exc:
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR") from exc
        parametros = {"courseid": curso, "id": categoria}
        if formula is None:
            if self._formula_del_elemento(curso, item_id):
                respuesta = self._enviar_formulario(
                    "grade/edit/tree/calculation.php",
                    {"courseid": curso, "id": item_id},
                    {"calculation": ""},
                )
                if not self._guardado(respuesta):
                    raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
            self._guardar("grade/edit/tree/category.php", parametros, {"grade_item_display": "2"})
            return
        self.fijar_formula(curso, item_id, formula, decimal)
        self._guardar("grade/edit/tree/category.php", parametros, {"grade_item_grademax": "10"})

    # --- Resultados del curso y escala de logro (evidencia por criterio) -------

    def resultados_activos(self, curso: int) -> bool:
        """¿Están activos los resultados en este sitio? (D12).

        ``grade/edit/outcome/index.php`` redirige al calificador cuando está desactivado:
        se lee sin seguir la redirección y el 3xx es el no. Una redirección al login es una
        sesión caducada, no una configuración del sitio.
        """
        self._esperar()
        respuesta = self._reducir(
            "ERROR_CONSULTA",
            self.sesion.get,
            f"{self.base_url}/grade/edit/outcome/index.php",
            params={"id": curso},
            allow_redirects=False,
            timeout=TIEMPO_ESPERA,
        )
        estado = getattr(respuesta, "status_code", 200)
        if 300 <= estado < 400:
            destino = (getattr(respuesta, "headers", None) or {}).get("Location", "")
            if not destino:
                raise ErrorPublicacion("ERROR_CONSULTA")
            if not _es_del_mismo_aula(self.base_url, str(destino)):
                raise ErrorPublicacion("DESTINO_NO_PERMITIDO")
            if _redirige_al_login(self.base_url, str(destino)):
                raise ErrorPublicacion("SESION_CADUCADA")
            ruta = urlsplit(_resolver_destino(self.base_url, str(destino))).path
            if _es_informe_de_notas(self.base_url, str(destino)) or "/grade/" in ruta:
                return False  # el calificador: los resultados están desactivados (D12)
            raise ErrorPublicacion("ERROR_CONSULTA")
        self._reducir("ERROR_CONSULTA", respuesta.raise_for_status)
        return True

    def _exigir_resultados(self, curso: int) -> None:
        """Sin resultados activos no se lee ni se escribe nada de resultados (D12)."""
        if not self.resultados_activos(curso):
            raise ErrorPublicacion("RESULTADOS_DESACTIVADOS")

    def _escalas_con_nombre(self, curso: int, nombre: str) -> list[int]:
        """Los ids de las escalas del curso que se llaman ``nombre`` (lista ``scaleid``)."""
        pagina = self._pagina_del_calificador("grade/edit/outcome/edit.php", {"courseid": curso})
        sopa = BeautifulSoup(pagina, "html.parser")
        selector = sopa.find("select", attrs={"name": "scaleid"})
        if selector is None:
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        return [
            int(str(opcion["value"]))
            for opcion in selector.find_all("option")
            if str(opcion.get("value", "")).isdigit() and opcion.get_text(" ", strip=True) == nombre
        ]

    def _niveles_de_escala(self, curso: int, escala: int) -> tuple[str, ...] | None:
        """Los niveles que tiene ahora la escala, releídos de su formulario.

        Si el formulario está congelado y no trae ``scale`` (Moodle puede hacerlo con
        ``hardFreeze`` cuando la escala está en uso), se leen de la lista de escalas del
        curso, que sí los muestra en ``div.scale_options``. Si tampoco están ahí, no se
        sabe: ``None``.
        """
        pagina = self._pagina_del_calificador(
            "grade/edit/scale/edit.php", {"courseid": curso, "id": escala}
        )
        formulario = _formulario_con_campo(pagina, "scale")
        if formulario is not None:
            texto = _campo(formulario, "scale")
            if texto is not None and texto.strip():
                return _niveles_de_texto(texto)
        return self._niveles_de_escala_en_indice(curso, escala)

    def _niveles_de_escala_en_indice(self, curso: int, escala: int) -> tuple[str, ...] | None:
        """Los niveles de la escala en la lista del curso (``div.scale_options``).

        Es la fuente que sigue disponible cuando el formulario de edición está congelado.
        Solo se acepta la fila que tiene el enlace de **edición** (``edit.php``) con
        ``courseid=<curso>`` e ``id=<escala>``: el enlace de borrar de otra escala también
        puede llevar ``id=<curso>``. Si no hay enlace inequívoco o la fila no trae los
        niveles, ``None``: nunca se adivinan.
        """
        pagina = self._pagina_del_calificador("grade/edit/scale/index.php", {"id": curso})
        sopa = BeautifulSoup(pagina, "html.parser")
        for fila in sopa.find_all("tr"):
            for enlace in fila.find_all("a", href=True):
                partes = urlsplit(str(enlace.get("href") or ""))
                if partes.path.rsplit("/", 1)[-1] != "edit.php":
                    continue
                consulta = parse_qs(partes.query)
                if str(curso) not in consulta.get("courseid", []):
                    continue
                if str(escala) not in consulta.get("id", []):
                    continue
                opciones = fila.find(class_="scale_options")
                if opciones is None:
                    return None
                return _niveles_de_texto(opciones.get_text(" ", strip=True))
        return None

    def asegurar_escala(self, curso: int, nombre: str, niveles: tuple[str, ...]) -> int:
        """Crea la escala de logro o reutiliza la del mismo nombre y niveles.

        Si existe con otros niveles, se intenta actualizar. Moodle responde 303 también
        cuando la escala está en uso y deja los niveles como estaban (S1b.5): por eso se
        relee el formulario y, si no cambiaron, es ``ESCALA_EN_USO``. Nunca se detecta por
        el texto de la respuesta.
        """
        self._exigir_resultados(curso)
        deseados = tuple(niveles)
        candidatas = self._escalas_con_nombre(curso, nombre)
        ilegible = False
        for escala in candidatas:
            leidos = self._niveles_de_escala(curso, escala)
            if leidos == deseados:
                return escala
            if leidos is None:
                ilegible = True
        if ilegible:
            # No se pueden leer sus niveles en ninguna fuente disponible: no se toca ni se
            # duplica. Lo más probable es que esté en uso y Moodle no deje cambiarla.
            raise ErrorPublicacion("ESCALA_EN_USO")
        if len(candidatas) > 1:
            # Varias escalas con el mismo nombre y ninguna con estos niveles: no se elige
            # una al azar.
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        if candidatas:
            escala = candidatas[0]
            self._guardar(
                "grade/edit/scale/edit.php",
                {"courseid": curso, "id": escala},
                {"name": nombre, "scale": ",".join(deseados)},
            )
            leidos = self._niveles_de_escala(curso, escala)
            if leidos is None:
                # Moodle respondió que guardaba (303) pero no se pueden releer los niveles:
                # la escala está en uso y no se aplicó el cambio (S1b.5).
                raise ErrorPublicacion("ESCALA_EN_USO")
            if leidos != deseados:
                raise ErrorPublicacion("ESCALA_EN_USO")
            return escala
        self._guardar(
            "grade/edit/scale/edit.php",
            {"courseid": curso},
            {"name": nombre, "scale": ",".join(deseados), "standard": "0"},
        )
        nuevas = self._escalas_con_nombre(curso, nombre)
        if not nuevas:
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        return nuevas[0]

    def escala_con_nombre(self, curso: int, nombre: str) -> int | None:
        """El id de la escala del curso que se llama así, si hay exactamente una."""
        candidatas = self._escalas_con_nombre(curso, nombre)
        return candidatas[0] if len(candidatas) == 1 else None

    def _ids_de_resultados(self, curso: int) -> set[int]:
        """Los ids de los resultados usados en el curso (``removeoutcomes[]``).

        Si la página no trae el selector, no es la página que tiza sabe leer: no se puede
        deducir «no hay resultados» (sería crear un duplicado).
        """
        pagina = self._pagina_del_calificador("grade/edit/outcome/course.php", {"id": curso})
        selector = BeautifulSoup(pagina, "html.parser").find(
            "select", attrs={"name": "removeoutcomes[]"}
        )
        if selector is None:
            raise ErrorPublicacion("ERROR_CONSULTA")
        return {
            int(str(opcion["value"]))
            for opcion in selector.find_all("option")
            if str(opcion.get("value", "")).isdigit()
        }

    def _corto_de_resultado(self, curso: int, resultado: int) -> str:
        """El nombre corto del resultado, leído de su formulario y recordado por curso.

        Un formulario sin ``shortname`` no es un resultado legible: se falla en vez de
        cachear un vacío, que haría crear un duplicado.
        """
        vistos = self._corto_resultados.setdefault(curso, {})
        if resultado in vistos:
            return vistos[resultado]
        pagina = self._pagina_del_calificador(
            "grade/edit/outcome/edit.php", {"courseid": curso, "id": resultado}
        )
        formulario = _formulario_con_campo(pagina, "shortname")
        if formulario is None:
            raise ErrorPublicacion("ERROR_CONSULTA")
        corto = (_campo(formulario, "shortname") or "").strip()
        if not corto:
            raise ErrorPublicacion("ERROR_CONSULTA")
        vistos[resultado] = corto
        return corto

    def resultado_por_corto(self, curso: int, corto: str) -> int | None:
        """El id del resultado del curso con ese nombre corto, o ``None`` si no existe.

        Solo lee: la lista ``removeoutcomes[]`` y el formulario de cada resultado. Con los
        resultados desactivados devuelve ``None`` (no hay definiciones que leer).
        """
        if not self.resultados_activos(curso):
            return None
        encontrados = [
            resultado
            for resultado in self._ids_de_resultados(curso)
            if self._corto_de_resultado(curso, resultado) == corto
        ]
        if len(encontrados) != 1:
            return None
        return encontrados[0]

    def _resultado_igual(self, curso: int, resultado: int, cambios: dict[str, str]) -> bool:
        """¿El resultado ya tiene exactamente estos campos? (sin escribir nada)."""
        pagina = self._pagina_del_calificador(
            "grade/edit/outcome/edit.php", {"courseid": curso, "id": resultado}
        )
        formulario = _formulario_con_campo(pagina, "shortname")
        if formulario is None:
            return False
        escala_leida = _campo(formulario, "scaleid")
        for nombre, valor in cambios.items():
            if nombre == "scaleid" and escala_leida is None:
                # Un resultado en uso tiene el formulario congelado y no enseña la escala:
                # no se puede comparar ni cambiar; los demás campos sí se comprueban.
                continue
            if (_campo(formulario, nombre) or "").strip() != str(valor).strip():
                return False
        return True

    def asegurar_resultado(
        self,
        curso: int,
        corto: str,
        nombre: str,
        descripcion: str,
        escala: int,
    ) -> int:
        """Crea o actualiza el resultado del curso con este nombre corto y devuelve su id.

        El id sale siempre de la lista ``removeoutcomes[]`` de
        ``grade/edit/outcome/course.php``, no de la redirección del guardado. Si ya existe con
        el mismo nombre corto, nombre completo, escala y descripción, no se envía nada (el
        montaje es idempotente). Si hay más de un resultado con el mismo nombre corto (no
        debería), no se elige uno al azar.
        """
        self._exigir_resultados(curso)
        ids = self._ids_de_resultados(curso)
        encontrados = [
            resultado for resultado in ids if self._corto_de_resultado(curso, resultado) == corto
        ]
        if len(encontrados) > 1:
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        cambios = {
            "shortname": corto,
            "fullname": nombre,
            "scaleid": str(escala),
            "description_editor[text]": descripcion,
            "description_editor[format]": "0",
        }
        if encontrados:
            resultado = encontrados[0]
            if self._resultado_igual(curso, resultado, cambios):
                self._corto_resultados.setdefault(curso, {})[resultado] = corto
                return resultado
            self._guardar(
                "grade/edit/outcome/edit.php",
                {"courseid": curso, "id": resultado},
                cambios,
            )
            if not self._resultado_igual(curso, resultado, cambios):
                raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
            self._corto_resultados.setdefault(curso, {})[resultado] = corto
            return resultado
        self._guardar(
            "grade/edit/outcome/edit.php",
            {"courseid": curso},
            {**cambios, "standard": "0"},
        )
        despues = self._ids_de_resultados(curso)
        nuevos = [resultado for resultado in despues if resultado not in ids]
        if len(nuevos) != 1:
            nuevos = [
                resultado
                for resultado in despues
                if self._corto_de_resultado(curso, resultado) == corto
            ]
        if len(nuevos) != 1:
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        resultado = nuevos[0]
        if not self._resultado_igual(curso, resultado, cambios):
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        # Se añade a la caché sin releer los formularios que ya se conocían.
        self._corto_resultados.setdefault(curso, {})[resultado] = corto
        return resultado

    def fijar_idnumber_resultado(self, curso: int, item_id: int, idnumber: str) -> None:
        """El número de ID de un elemento de resultado (``outcomeitem.php``, S1b.3)."""
        self._guardar(
            "grade/edit/tree/outcomeitem.php",
            {"courseid": curso, "id": item_id},
            {"idnumber": idnumber},
        )
        pagina = self._pagina_del_calificador(
            "grade/edit/tree/outcomeitem.php", {"courseid": curso, "id": item_id}
        )
        formulario = _formulario_con_campo(pagina, "idnumber")
        if formulario is None or (_campo(formulario, "idnumber") or "").strip() != idnumber:
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")

    def campos_resultado_tarea(self, cmid: int) -> dict[int, bool]:
        """Qué resultados tiene marcados la tarea: ``outcome_<id>`` de ``course/modedit.php``.

        Solo lee los ajustes de la actividad; nunca el formulario de calificación, donde el
        índice del campo es interno (D5). Quitar un ``outcome_<id>`` no desvincula el
        resultado en Moodle (S1b.2), así que esto solo se usa para leer.
        """
        self._esperar()
        respuesta = self._reducir(
            "ERROR_CONSULTA",
            self.sesion.get,
            f"{self.base_url}/course/modedit.php",
            params={"update": cmid},
            allow_redirects=False,
            timeout=TIEMPO_ESPERA,
        )
        estado = getattr(respuesta, "status_code", 200)
        if 300 <= estado < 400:
            destino = (getattr(respuesta, "headers", None) or {}).get("Location", "")
            if not destino:
                raise ErrorPublicacion("ERROR_CONSULTA")
            if not _es_del_mismo_aula(self.base_url, str(destino)):
                raise ErrorPublicacion("DESTINO_NO_PERMITIDO")
            if _redirige_al_login(self.base_url, str(destino)):
                raise ErrorPublicacion("SESION_CADUCADA")
            raise ErrorPublicacion("ERROR_CONSULTA")
        self._reducir("ERROR_CONSULTA", respuesta.raise_for_status)
        sopa = BeautifulSoup(str(getattr(respuesta, "text", "") or ""), "html.parser")
        formulario = sopa.find("form", id="modeditform")
        if formulario is None:
            formulario = next(
                (
                    candidato
                    for candidato in sopa.find_all("form")
                    if re.search(r"(?:^|/)modedit\.php", str(candidato.get("action") or ""))
                ),
                None,
            )
        if formulario is None:
            raise ErrorPublicacion("ERROR_CONSULTA")
        patron = re.compile(r"^outcome_([0-9]+)$")
        marcados: dict[int, bool] = {}
        for campo in formulario.find_all("input", attrs={"name": patron}):
            coincidencia = patron.fullmatch(str(campo["name"]))
            if coincidencia is None:
                continue
            resultado = int(coincidencia.group(1))
            tipo = str(campo.get("type", "")).lower()
            if tipo in ("checkbox", "radio"):
                marcado = campo.has_attr("checked")
            else:
                marcado = str(campo.get("value", "")).strip() == "1"
            marcados[resultado] = marcados.get(resultado, False) or marcado
        return marcados

    def marcar_resultado_tarea(self, cmid: int, resultado_id: int) -> None:
        """Marca un resultado en los ajustes de la tarea: ``outcome_<id>=1`` (S1b.1).

        Moodle conserva las notas al actualizar el módulo y crea el elemento de resultado vacío;
        el número de ID y el sitio en el calificador los pone la reconciliación después. Actualizar
        con el resto del formulario reenviado es lo que midió la espiga: el campo que no se envía
        se conserva.
        """
        self.actualizar(
            cmid,
            {
                f"outcome_{resultado_id}": "1",
                "submitbutton": "Save and display",
            },
        )
        if not self.campos_resultado_tarea(cmid).get(resultado_id):
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")

    def comprobar_h5p(self, cmid: int) -> bool:
        """¿Arrancó H5P? El embed trae H5PIntegration con contents (espiga)."""
        html = self._leer_embed_h5p(cmid)
        return "H5PIntegration" in html and '"contents":' in html and "h5p-iframe" in html

    def libreria_h5p_ausente(self, cmid: int, machine_name: str) -> bool:
        """Si el embed nombra la librería esperada, el fallo es que falta."""
        if not machine_name:
            return False
        return bool(re.search(rf"\b{re.escape(machine_name)}\b", self._leer_embed_h5p(cmid)))

    def h5p_tiene_intentos(self, cmid: int) -> bool:
        """Hay intentos si el informe enlaza algún ``attemptid=<n>``; nada más.

        Nunca se leen nombres, notas ni cuántos intentos hay. Sin seguimiento
        (p. ej. las tarjetas) Moodle no tiene informe y responde 404: no puede
        haber intentos.
        """
        self._esperar()
        respuesta = self._reducir(
            "ERROR_CONSULTA",
            self.sesion.get,
            f"{self.base_url}/mod/h5pactivity/report.php",
            params={"id": cmid},
            timeout=TIEMPO_ESPERA,
        )
        if getattr(respuesta, "status_code", 0) == 404:
            return False
        self._reducir("ERROR_CONSULTA", respuesta.raise_for_status)
        return bool(re.search(r"attemptid=\d+", getattr(respuesta, "text", "") or ""))

    def _leer_embed_h5p(self, cmid: int) -> str:
        """El HTML del embed de la actividad; vacío si la vista no lo incrusta."""
        self._esperar()
        vista = self._reducir(
            "ERROR_CONSULTA",
            self.sesion.get,
            f"{self.base_url}/mod/h5pactivity/view.php",
            params={"id": cmid},
            timeout=TIEMPO_ESPERA,
        )
        self._reducir("ERROR_CONSULTA", vista.raise_for_status)
        sopa = BeautifulSoup(getattr(vista, "text", "") or "", "html.parser")
        iframe = sopa.find("iframe", attrs={"src": re.compile(r"/h5p/embed\.php")})
        if iframe is None:
            return ""
        src = iframe.get("src")
        if not isinstance(src, str):
            return ""
        destino = urljoin(f"{self.base_url}/mod/h5pactivity/view.php", src)
        self._esperar()
        embed = self._reducir("ERROR_CONSULTA", self.sesion.get, destino, timeout=TIEMPO_ESPERA)
        self._reducir("ERROR_CONSULTA", embed.raise_for_status)
        return getattr(embed, "text", "") or ""

    # --- Copia de seguridad del curso (sin usuarios) -------------------------

    def puede_copiar(self, curso_id: int) -> bool:
        """¿Ve el docente el formulario de copia del curso? Solo lectura (una carga de la página).

        Falso si el aula responde sin el formulario (falta el permiso de copia). Solo sale un
        sí o un no; el texto de Moodle no sale de aquí.
        """
        self._esperar()
        pagina = self._reducir(
            "ERROR_CONSULTA",
            self.sesion.get,
            f"{self.base_url}/backup/backup.php",
            params={"id": curso_id},
            timeout=TIEMPO_ESPERA,
        )
        if getattr(pagina, "status_code", 0) != 200:
            return False
        return _formulario_de(getattr(pagina, "text", "") or "", _ACCION_COPIA) is not None

    def hacer_copia(
        self, curso_id: int, destino: Path, maximo: int, cmid: int | None = None
    ) -> CopiaDescargada:
        """Hace la copia del curso sin datos de usuario y la descarga en ``destino``.

        Con ``cmid``, la copia es solo de esa actividad (``backup.php?id=<curso>&cm=<cmid>``,
        el mismo recorrido) y el nombre propio lleva ``c<cmid>``.

        Sigue las etapas de ``backup/backup.php`` como el navegador, con todos los ajustes de
        usuario forzados a 0 y un nombre propio y único para el fichero; busca la copia nueva
        en la zona de copias privadas del docente y la descarga por trozos, cortando en
        ``maximo`` bytes. Si algo falla, no deja ``destino`` a medias. ``COPIA_NO_PERMITIDA`` si
        el aula no da el formulario; ``COPIA_FALLIDA`` si la copia no aparece o la descarga no
        acaba en 10 minutos; ``COPIA_DEMASIADO_GRANDE`` si pasa de ``maximo``.
        """
        try:
            return self._hacer_copia(curso_id, destino, maximo, cmid)
        except BaseException:
            try:
                Path(destino).unlink()
            except OSError:
                pass
            raise

    def _hacer_copia(
        self, curso_id: int, destino: Path, maximo: int, cmid: int | None = None
    ) -> CopiaDescargada:
        antes = self._copias_en_el_area(curso_id)
        nombre = self._nombre_unico_de_copia(curso_id, {nombre for nombre, _ in antes}, cmid)
        self._esperar()
        pagina = self._reducir(
            "COPIA_FALLIDA",
            self.sesion.get,
            f"{self.base_url}/backup/backup.php",
            params={"id": curso_id} if cmid is None else {"id": curso_id, "cm": cmid},
            timeout=TIEMPO_ESPERA,
        )
        formulario = (
            _formulario_de(getattr(pagina, "text", "") or "", _ACCION_COPIA)
            if getattr(pagina, "status_code", 0) == 200
            else None
        )
        if formulario is None:
            if not self.sesion_viva():
                raise ErrorPublicacion("SESION_CADUCADA")
            raise ErrorPublicacion("COPIA_NO_PERMITIDA")
        enviado = False  # ¿ya se mandó el nombre propio? Desde entonces la copia puede existir
        try:
            for _ in range(MAX_ETAPAS_COPIA):
                envio = _envio_de_copia(formulario, nombre)
                if envio is None:
                    raise ErrorPublicacion("COPIA_FALLIDA")  # un formulario sin botón para seguir
                enviado = enviado or any(campo == _CAMPO_NOMBRE_COPIA for campo, _v in envio)
                self._esperar()
                pagina = self._reducir(
                    "COPIA_FALLIDA",
                    self.sesion.post,
                    f"{self.base_url}/backup/backup.php",
                    data=envio,
                    timeout=ESPERA_COPIA,
                )
                if getattr(pagina, "status_code", 200) >= 400:
                    raise ErrorPublicacion("COPIA_FALLIDA")  # una página de error del aula
                formulario = _formulario_de(getattr(pagina, "text", "") or "", _ACCION_COPIA)
                if formulario is None:
                    break  # sin más etapas: la copia está hecha
            else:
                raise ErrorPublicacion("COPIA_FALLIDA")
            if not enviado:
                # Sin nombre propio la copia lleva el de Moodle y no se podría encontrar: no se
                # espera a que aparezca (y puede haberse creado).
                raise _error_con_copia_en_el_aula("COPIA_FALLIDA")
            enlace = None
            for intento in range(int(ESPERA_COPIA / PASO_ESPERA_COPIA) + 1):
                if intento:
                    self._dormir(PASO_ESPERA_COPIA)
                enlace = next(
                    (url for n, url in self._copias_en_el_area(curso_id) if n == nombre), None
                )
                if enlace is not None:
                    break
            if enlace is None:
                raise _error_con_copia_en_el_aula("COPIA_FALLIDA")  # puede aparecer más tarde
            escritos = self._descargar_copia(enlace, Path(destino), maximo)
        except BaseException as exc:
            # Una copia que no se pudo traer (demasiado grande, cortada…) no se queda en el aula:
            # si no se puede quitar, el error lo dice (``queda_en_el_aula``).
            if enviado and not getattr(exc, "queda_en_el_aula", False):
                try:
                    self.borrar_copia(nombre, curso_id)
                except ErrorPublicacion:
                    exc.queda_en_el_aula = True  # type: ignore[attr-defined]
            raise
        return CopiaDescargada(escritos, nombre)

    def _nombre_unico_de_copia(
        self, curso_id: int, en_el_area: set[str], cmid: int | None = None
    ) -> str:
        """``tiza-<curso>-<epoch>-<aleatorio>-nu.mbz``, nuevo en el área y en esta sesión.

        Con ``cmid`` (copia de una actividad): ``tiza-<curso>-c<cmid>-<epoch>-<aleatorio>-nu.mbz``.

        Sin un nombre propio, Moodle nombra la copia con la hora y el minuto y dos copias seguidas
        se pisan (espiga 7); el sufijo aleatorio evita pisar la de otro proceso en el mismo segundo.
        """
        while True:
            parte = f"{curso_id}" if cmid is None else f"{curso_id}-c{cmid}"
            nombre = f"tiza-{parte}-{int(time.time())}-{secrets.token_hex(3)}-nu.mbz"
            if nombre not in en_el_area and nombre not in self._nombres_de_copia:
                break
        self._nombres_de_copia.add(nombre)
        return nombre

    def _copias_en_el_area(self, curso_id: int) -> list[tuple[str, str]]:
        """(nombre, enlace) de cada copia de la zona de copias privadas del docente."""
        self._esperar()
        pagina = self._reducir(
            "COPIA_FALLIDA",
            self.sesion.get,
            f"{self.base_url}/backup/restorefile.php",
            params={"contextid": self.contexto(curso_id)},
            timeout=TIEMPO_ESPERA,
        )
        sopa = BeautifulSoup(getattr(pagina, "text", "") or "", "html.parser")
        salida: list[tuple[str, str]] = []
        for enlace in sopa.find_all("a", href=True):
            href = str(enlace["href"])
            if ".mbz" in href and "pluginfile.php" in href and "/user/backup/" in href:
                nombre = unquote(href.rsplit("/", 1)[-1].split("?")[0])
                salida.append((nombre, urljoin(f"{self.base_url}/", href)))
        return salida

    def _descargar_copia(self, enlace: str, destino: Path, maximo: int) -> int:
        """Descarga por trozos; corta al pasar de ``maximo`` bytes o de ``ESPERA_COPIA`` segundos."""
        self._esperar()
        respuesta = self._reducir(
            "COPIA_FALLIDA", self.sesion.get, enlace, stream=True, timeout=TIEMPO_ESPERA
        )
        try:
            if getattr(respuesta, "status_code", 0) != 200:
                raise ErrorPublicacion("COPIA_FALLIDA")
            cabeceras = getattr(respuesta, "headers", None) or {}
            if str(cabeceras.get("Content-Type", "")).lower().startswith("text/html") or (
                "/login/" in str(getattr(respuesta, "url", ""))
            ):
                # Una página (la de entrada, o un error) donde debía venir la copia: la sesión
                # ya no vale. No se escribe nada.
                raise ErrorPublicacion("SESION_CADUCADA")
            largo = cabeceras.get("Content-Length", "")
            if str(largo).isdigit() and int(largo) > maximo:
                raise ErrorPublicacion("COPIA_DEMASIADO_GRANDE")
            limite = time.monotonic() + ESPERA_COPIA
            escritos = 0
            banderas = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
            banderas |= getattr(os, "O_BINARY", 0)
            descriptor = os.open(destino, banderas, 0o600)  # no sigue un enlace puesto en su lugar
            with os.fdopen(descriptor, "wb") as fichero:
                try:
                    for trozo in respuesta.iter_content(chunk_size=TROZO_COPIA):
                        if not trozo:
                            continue
                        escritos += len(trozo)
                        if escritos > maximo:
                            raise ErrorPublicacion("COPIA_DEMASIADO_GRANDE")
                        if time.monotonic() > limite:
                            raise ErrorPublicacion("COPIA_FALLIDA")
                        fichero.write(trozo)
                except ERRORES_MOODLE as exc:
                    raise self._error("COPIA_FALLIDA", exc) from exc
            return escritos
        finally:
            cerrar = getattr(respuesta, "close", None)
            if callable(cerrar):
                cerrar()

    def borrar_copia(self, nombre: str, curso_id: int) -> None:
        """Quita la copia ``nombre`` de la zona de copias privadas del docente (espiga 7).

        Abre ``backup/backupfilesedit.php`` (su gestor de ficheros es un área de borrador), borra
        el fichero con ``draftfiles_ajax.php?action=delete`` y guarda el formulario. Después mira
        que ya no esté: si sigue, ``ERROR_BORRADO``. Si ya no estaba, no hace nada.
        """
        presente = next(
            ((n, url) for n, url in self._copias_en_el_area(curso_id) if n == nombre), None
        )
        if presente is None:
            return
        contexto_usuario = re.search(r"pluginfile\.php/(\d+)/user/backup/", presente[1])
        if contexto_usuario is None:
            raise ErrorPublicacion("ERROR_BORRADO")
        contexto_curso = self.contexto(curso_id)
        self._esperar()
        pagina = self._reducir(
            "ERROR_BORRADO",
            self.sesion.get,
            f"{self.base_url}/backup/backupfilesedit.php",
            params={
                "currentcontext": contexto_curso,
                "contextid": contexto_usuario.group(1),
                "filearea": "backup",
                "component": "user",
                "returnurl": f"{self.base_url}/backup/restorefile.php?contextid={contexto_curso}",
            },
            timeout=TIEMPO_ESPERA,
        )
        formulario = _formulario_de(getattr(pagina, "text", "") or "", _ACCION_EDICION_COPIAS)
        if formulario is None:
            raise ErrorPublicacion("ERROR_BORRADO")
        pares = _campos_de_formulario(formulario)
        gestor = next((valor for campo, valor in pares if campo.endswith("filemanager")), None)
        if gestor is None:
            raise ErrorPublicacion("ERROR_BORRADO")
        self._esperar()
        respuesta = self._reducir(
            "ERROR_BORRADO",
            self.sesion.post,
            f"{self.base_url}/repository/draftfiles_ajax.php",
            params={"action": "delete"},
            data={"sesskey": self.sesskey, "itemid": gestor, "filepath": "/", "filename": nombre},
            timeout=TIEMPO_ESPERA,
        )
        try:
            borrado = (
                getattr(respuesta, "status_code", 0) == 200 and "error" not in respuesta.json()
            )
        except (ValueError, TypeError):
            borrado = False
        if not borrado:
            raise ErrorPublicacion("ERROR_BORRADO")
        self._esperar()
        self._reducir(
            "ERROR_BORRADO",
            self.sesion.post,
            f"{self.base_url}/backup/backupfilesedit.php",
            data=[*pares, ("submitbutton", "1")],
            timeout=TIEMPO_ESPERA,
        )
        if any(n == nombre for n, _ in self._copias_en_el_area(curso_id)):
            raise ErrorPublicacion("ERROR_BORRADO")


def _formulario_de(html: str, accion: re.Pattern[str]) -> Any:
    """El formulario de la página cuya acción cumple ``accion``, o ``None``."""
    return BeautifulSoup(html, "html.parser").find("form", attrs={"action": accion})


def _formulario_con_campo(html: str, nombre: str) -> Any:
    """El primer formulario de la página que trae un campo llamado ``nombre``, o ``None``."""
    for formulario in BeautifulSoup(html, "html.parser").find_all("form"):
        if _campo_con_nombre(formulario, nombre) is not None:
            return formulario
    return None


def _niveles_de_texto(texto: str) -> tuple[str, ...]:
    """Los niveles de una escala de Moodle: texto separado por comas."""
    if not texto.strip():
        return ()
    return tuple(nivel.strip() for nivel in texto.split(","))


_INFORME_DE_NOTAS = re.compile(r"(?:^|/)grade/report(?:/|\.php)|(?:^|/)mod/[^/]+/report\.php")


def _resolver_destino(base_url: str, destino: str) -> str:
    """La URL absoluta de una redirección del aula."""
    return urljoin(f"{base_url}/", destino)


def _es_del_mismo_aula(base_url: str, destino: str) -> bool:
    """¿La redirección se queda en el mismo servidor del aula?"""
    propia = urlsplit(base_url)
    ajena = urlsplit(_resolver_destino(base_url, destino))
    return (propia.scheme, propia.netloc) == (ajena.scheme, ajena.netloc)


def _redirige_al_login(base_url: str, destino: str) -> bool:
    """¿La redirección lleva al login del aula?"""
    return "/login/" in urlsplit(_resolver_destino(base_url, destino)).path


def _es_informe_de_notas(base_url: str, destino: str) -> bool:
    """¿La redirección lleva a un informe de notas, que tiza no lee nunca?"""
    return bool(_INFORME_DE_NOTAS.search(urlsplit(_resolver_destino(base_url, destino)).path))


_ENLACE_DE_ACTIVIDAD = re.compile(r"/mod/\w+/view\.php\?id=(\d+)")
# El icono de un elemento de actividad: ``theme/image.php/<tema>/<módulo>/<rev>/monologo``. Los
# elementos manuales y calculados llevan iconos del núcleo (``…/core/…``).
_ICONO_DE_MODULO = re.compile(r"/image\.php/[^/]+/(?!core/)[a-z][a-z0-9_]*/[0-9]+/monologo")


def _actividad_en_borrado(fila: Any) -> bool:
    """¿La fila es el elemento de una actividad que Moodle está borrando?

    Al borrar una actividad, Moodle la deja «[Borrado en progreso]» hasta que pasa su cron: el
    elemento sigue en el calificador con el icono del módulo, pero el título ya no enlaza con la
    actividad y sus páginas redirigen. tiza no la lee ni la toca; desaparece sola. Se reconoce por
    la estructura, nunca por el texto traducido.
    """
    if "data-category" in fila.attrs:
        return False
    if fila.find("a", class_="gradeitemheader", href=_ENLACE_DE_ACTIVIDAD) is not None:
        return False
    return any(
        _ICONO_DE_MODULO.search(str(img.get("src") or ""))
        for img in fila.find_all("img", class_="itemicon")
    )


def _valor_de_campo(formulario: Any, nombre: str) -> str:
    campo = _campo_con_nombre(formulario, nombre)
    return str(campo.get("value") or "").strip() if campo is not None else ""


def _campo_con_nombre(formulario: Any, nombre: str) -> Any:
    return formulario.find(attrs={"name": nombre})


def _casilla_marcada(formulario: Any, nombre: str) -> bool:
    return any(
        campo.get("type") == "checkbox" and campo.has_attr("checked")
        for campo in formulario.find_all("input", attrs={"name": nombre})
    )


def _numero(texto: Any) -> float | None:
    """«40,0» o «40.0» como número; ``None`` si no lo es (o no es finito)."""
    try:
        valor = float(str(texto).strip().replace(",", "."))
    except ValueError:
        return None
    return valor if valor == valor and abs(valor) != float("inf") else None


_EID = re.compile(
    r"(cg|ig)[0-9]+"
)  # solo cifras ASCII: ``\d`` acepta también las de otros alfabetos


def _validar_eid(eid: str, prefijo: str | None = None) -> None:
    """Un ``eid`` es ``cg<id>`` o ``ig<id>``; otra cosa es un error propio, nunca ``ValueError``."""
    if not isinstance(eid, str) or not _EID.fullmatch(eid) or (prefijo and eid[:2] != prefijo):
        raise ErrorPublicacion("ESCRITURA_CALIFICADOR")


_PETICIONES_POR_RECALCULO = 3


def _a_releer(
    filas: list[Any], previos: dict[str, dict[str, Any]], tocados: Collection[str]
) -> set[str]:
    """Los ``eid`` cuyo formulario hay que volver a abrir tras escribir (``Moodle.calificador``).

    Lo tocado, lo nuevo, lo movido o con otro máximo, todos los hijos de sus categorías (la de
    antes y la de ahora) y la raíz. Si desapareció algo, todo.
    """
    padres: dict[str, str | None] = {}
    maximos: dict[str, float | None] = {}
    por_item: dict[str, str] = {}
    for fila in filas:
        eid = (
            str(fila["data-category"])
            if "data-category" in fila.attrs
            else f"ig{fila['data-itemid']}"
        )
        padre = fila.get("data-parent-category")
        padres[eid] = str(padre) if padre else None
        maximos[eid] = _numero(fila.get("data-grademax"))
        por_item[f"ig{fila['data-itemid']}"] = eid  # el total de una categoría es su elemento
    if set(previos) - set(padres):
        return set(padres)
    cambiados = {por_item.get(t, t) for t in tocados}
    for eid, padre in padres.items():
        anterior = previos.get(eid)
        if anterior is None or anterior["padre_eid"] != padre or anterior["maximo"] != maximos[eid]:
            cambiados.add(eid)
    categorias = {padres.get(e) for e in cambiados} | {
        previos[e]["padre_eid"] for e in cambiados if e in previos
    }
    releer = cambiados | {e for e, padre in padres.items() if padre is None or padre in categorias}
    return releer & set(padres)


def _es_recalculo(html: str) -> bool:
    """¿Es la página intersticial de «Recalculando calificaciones»?"""
    if "progressbar_container" not in html:
        return False
    sopa = BeautifulSoup(html, "html.parser")
    return (
        sopa.find("div", class_="progressbar_container") is not None
        and sopa.find("form", id="gradetreeform") is None
    )


def _decimal_visto(parciales: list[dict[str, Any]]) -> str:
    """El separador decimal que enseñan los formularios (pesos primero, luego el máximo); vacío si ninguno."""
    for clave in ("coef", "grademax_formulario"):
        for p in parciales:
            visto = _decimal_de(p[clave])
            if visto:
                return visto
    return ""


def _decimal_de(texto: str) -> str:
    """«,» o «.» si el número del formulario lleva decimales; vacío si es un entero."""
    return "," if "," in texto else "." if "." in texto else ""


def _campos_de_formulario(formulario: Any) -> list[tuple[str, str]]:
    """Los campos que enviaría un navegador (sin botones), en su orden y con su valor actual."""
    pares: list[tuple[str, str]] = []
    for campo in formulario.find_all(["input", "select", "textarea"]):
        nombre = campo.get("name")
        if not nombre:
            continue
        tipo = campo.get("type", "")
        if campo.name == "select":
            opcion = campo.find("option", selected=True) or campo.find("option")
            if opcion is not None:
                pares.append((nombre, opcion.get("value", "")))
        elif tipo in ("checkbox", "radio"):
            if campo.has_attr("checked") and not campo.has_attr("disabled"):
                pares.append((nombre, campo.get("value", "1")))
        elif tipo in ("submit", "button", "reset", "image", "file"):
            continue
        elif campo.name == "textarea":
            pares.append((nombre, campo.text or ""))
        else:
            pares.append((nombre, campo.get("value", "")))
    return pares


def _es_ajuste_de_usuario(nombre: str) -> bool:
    if nombre.startswith(_AJUSTE_RAIZ):
        return nombre.removeprefix(_AJUSTE_RAIZ) in AJUSTES_DE_USUARIO_COPIA
    return bool(_USERINFO.match(nombre))


def _envio_de_copia(formulario: Any, nombre_fichero: str) -> list[tuple[str, str]] | None:
    """Lo que se envía en una etapa de la copia, o ``None`` si el formulario no avanza.

    Todos los ajustes de usuario van a 0 (también los bloqueados o ya marcados: cada uno sale
    una sola vez, con ese valor) y el nombre del fichero es el propio. El botón es el de
    ``submitbutton`` o, si no, el primero que no sea «cancelar» ni «anterior».
    """
    pares: list[tuple[str, str]] = []
    vistos: set[str] = set()
    for campo, valor in _campos_de_formulario(formulario):
        if _es_ajuste_de_usuario(campo):
            if campo not in vistos:
                pares.append((campo, "0"))
                vistos.add(campo)
        elif campo == _CAMPO_NOMBRE_COPIA:
            pares.append((campo, nombre_fichero))
        else:
            pares.append((campo, valor))
    # Un ajuste de usuario que el formulario trae solo como casilla (marcada o no) también va a 0.
    for campo in formulario.find_all("input", attrs={"type": "checkbox"}):
        nombre = campo.get("name") or ""
        if _es_ajuste_de_usuario(nombre) and nombre not in vistos:
            pares.append((nombre, "0"))
            vistos.add(nombre)
    botones = [
        boton.get("name")
        for boton in formulario.find_all("input", attrs={"type": "submit"})
        if boton.get("name") and boton.get("name") not in _BOTONES_QUE_NO_AVANZAN
    ]
    if not botones:
        return None
    pares.append(("submitbutton" if "submitbutton" in botones else botones[0], "1"))
    return pares


def _tiene_campo(contenedor: Any, nombre: str) -> bool:
    """¿El formulario lleva ese campo? (los nombres pueden repetirse)."""
    return bool(contenedor.find_all(attrs={"name": nombre}))


def _formulario_en(html: str, marca: re.Pattern[str]):
    """El formulario que lleva un campo con ese nombre, o ``None``."""
    sopa = BeautifulSoup(html, "html.parser")
    if not sopa.find(True, attrs={"name": marca}):
        return None
    return next((f for f in sopa.find_all("form") if f.find(True, attrs={"name": marca})), sopa)


def _definicion_rubrica(formulario) -> list[dict]:
    """Criterios y niveles del editor, con los ids de Moodle."""
    criterios: dict[str, dict] = {}
    for campo in formulario.find_all(["input", "textarea"]):
        nombre = campo.get("name") or ""
        if coincide := _CRITERIO_RUBRICA.match(nombre):
            criterio = criterios.setdefault(coincide.group(1), {"niveles": {}})
            if coincide.group(2) == "description":
                criterio["descripcion"] = (
                    campo.text if campo.name == "textarea" else campo.get("value")
                )
            else:
                criterio["orden"] = campo.get("value")
        elif coincide := _NIVEL_RUBRICA.match(nombre):
            criterio = criterios.setdefault(coincide.group(1), {"niveles": {}})
            nivel = criterio["niveles"].setdefault(coincide.group(2), {})
            valor = campo.text if campo.name == "textarea" else campo.get("value")
            nivel["puntos" if coincide.group(3) == "score" else "definicion"] = valor
    salida = []
    for ident, datos in criterios.items():
        niveles = []
        for nid, nivel in datos["niveles"].items():
            try:
                puntos = float(str(nivel.get("puntos", "")).replace(",", "."))
            except ValueError:
                puntos = None
            niveles.append(
                {"id": nid, "puntos": puntos, "definicion": nivel.get("definicion") or ""}
            )
        salida.append(
            {
                "id": ident,
                "orden": datos.get("orden"),
                "descripcion": datos.get("descripcion") or "",
                "niveles": niveles,
            }
        )
    return salida


def _titulo_criterio(criterio: CriterioRubrica) -> str:
    """Cómo se escribe un criterio en el editor de rúbricas de Moodle."""
    return f"{criterio.nombre}: {criterio.descripcion}"


def emparejar_rubrica(leida: list[dict], rubrica: RubricaCargada) -> dict[str, dict] | None:
    """Nuestro id de criterio → {moodle, niveles (ids por puntos)}; ``None`` si no cuadra.

    Los ids se emparejan por la descripción del criterio, los puntos de sus niveles y
    sus definiciones: un descriptor cambiado obliga a volver a escribir la rúbrica.
    """
    pares: dict[str, dict] = {}
    for criterio in rubrica.criterios:
        esperado = _titulo_criterio(criterio)
        candidato = next(
            (c for c in leida if (c.get("descripcion") or "").strip() == esperado), None
        )
        if candidato is None:
            return None
        esperados = sorted((nivel.puntos, nivel.descripcion) for nivel in criterio.niveles)
        niveles = sorted(
            candidato.get("niveles") or [],
            key=lambda nivel: (nivel.get("puntos") is None, nivel.get("puntos")),
        )
        if [(nivel.get("puntos"), nivel.get("definicion")) for nivel in niveles] != esperados:
            return None
        pares[criterio.id] = {
            "moodle": candidato.get("id"),
            "niveles": [nivel.get("id") for nivel in niveles],
        }
    return pares


def _datos_rubrica(base: dict, rubrica: RubricaCargada) -> dict:
    """Datos del editor de rúbricas con nuestra rúbrica (fuera los criterios por defecto)."""
    datos = {
        clave: valor for clave, valor in base.items() if not clave.startswith("rubric[criteria]")
    }
    datos.update(OPCIONES_RUBRICA)
    datos["name"] = rubrica.nombre
    datos["description_editor[text]"] = rubrica.html
    datos["description_editor[format]"] = "1"
    for indice, criterio in enumerate(rubrica.criterios, 1):
        prefijo = f"rubric[criteria][NEWID{indice}]"
        datos[f"{prefijo}[sortorder]"] = str(indice)
        datos[f"{prefijo}[description]"] = _titulo_criterio(criterio)
        for numero, nivel in enumerate(criterio.niveles):
            clave = f"{prefijo}[levels][NEWID{indice * 10 + numero}]"
            datos[f"{clave}[score]"] = f"{nivel.puntos:g}"
            datos[f"{clave}[definition]"] = nivel.descripcion
    for boton in [k for k in datos if k.startswith("saverubric") or k in {"cancel", "editrubric"}]:
        datos.pop(boton)
    datos["saverubric"] = "Guardar rúbrica y dejarla lista"
    return datos


_HUECO = re.compile(r'id="slot-(\d+)"')
# El enlace de edición o previsualización de la pregunta lleva su id.
_ENLACE_PREGUNTA = re.compile(
    r"(?:previewquestion/preview|editquestion/question)\.php\?[^\"']*?"
    r"(?:\?|&amp;|&)id=(\d+)|(?:previewquestion/preview|editquestion/question)\.php\?id=(\d+)"
)
_CATEGORIA = re.compile(r"\A\d+,\d+\Z")


def _huecos_de_html(html: str) -> list[tuple[int, int | None]]:
    """Pares (hueco, pregunta) en el orden de la página; ``None`` si no hay."""
    partes = _HUECO.split(html)
    salida: list[tuple[int, int | None]] = []
    vistos: set[int] = set()
    for indice in range(1, len(partes), 2):
        hueco = int(partes[indice])
        if hueco in vistos:  # el id puede repetirse en la página (plantillas)
            continue
        vistos.add(hueco)
        enlace = _ENLACE_PREGUNTA.search(partes[indice + 1])
        pregunta = int(enlace.group(1) or enlace.group(2)) if enlace else None
        salida.append((hueco, pregunta))
    return salida


def formato_de_html(html: str) -> str:
    cuerpo = re.search(r"<body\b[^>]*\bclass=[\"']([^\"']*)[\"']", html)
    if cuerpo:
        formato = re.search(r"(?:^|\s)format-([a-z0-9_]+)(?:\s|$)", cuerpo.group(1))
        if formato:
            return formato.group(1)
    return "topics"


def _renombrar_seccion(
    sesion, base_url: str, sesskey: str, seccion_id: int, nombre: str, formato: str
) -> None:
    """Pone nombre a una sección con el editor en línea del formato del curso."""
    url = f"{base_url}/lib/ajax/service.php?sesskey={sesskey}&info=core_update_inplace_editable"
    payload = [
        {
            "index": 0,
            "methodname": "core_update_inplace_editable",
            "args": {
                "component": f"format_{formato}",
                "itemtype": "sectionname",
                "itemid": str(seccion_id),
                "value": nombre,
            },
        }
    ]
    respuesta = sesion.post(url, json=payload, timeout=TIEMPO_ESPERA)
    respuesta.raise_for_status()
    datos = respuesta.json()
    if not (isinstance(datos, list) and datos and datos[0].get("error") is False):
        raise MoodleSectionError("renombrado rechazado")


def _actualizar_curso(
    sesion,
    base_url: str,
    sesskey: str,
    curso_id: int,
    accion: str,
    ids: list[int],
    *,
    seccion_destino: int | None = None,
    antes_de: int | None = None,
) -> None:
    """Acción de edición del curso (la misma llamada AJAX que usa su página).

    ``seccion_destino`` y ``antes_de`` solo los usa ``cm_move``.
    """
    url = f"{base_url}/lib/ajax/service.php?sesskey={sesskey}&info=core_courseformat_update_course"
    args = {
        "action": accion,
        "courseid": str(curso_id),
        "ids": [str(item) for item in ids],
    }
    if seccion_destino is not None:
        args["targetsectionid"] = str(seccion_destino)
    if antes_de is not None:
        args["targetcmid"] = str(antes_de)
    payload = [{"index": 0, "methodname": "core_courseformat_update_course", "args": args}]
    respuesta = sesion.post(url, json=payload, timeout=TIEMPO_ESPERA)
    respuesta.raise_for_status()
    datos = respuesta.json()
    if not (isinstance(datos, list) and datos and datos[0].get("error") is False):
        raise MoodleModuleError(f"acción {accion} rechazada")


def _cursos_matriculados(sesion, base_url: str, sesskey: str) -> list[dict]:
    """Cursos del usuario, con la misma llamada AJAX que el bloque «Mis cursos»."""
    metodo = "core_course_get_enrolled_courses_by_timeline_classification"
    url = f"{base_url}/lib/ajax/service.php?sesskey={sesskey}&info={metodo}"
    payload = [
        {
            "index": 0,
            "methodname": metodo,
            "args": {"offset": 0, "limit": 0, "classification": "all", "sort": "fullname"},
        }
    ]
    respuesta = sesion.post(url, json=payload, timeout=TIEMPO_ESPERA)
    respuesta.raise_for_status()
    datos = respuesta.json()
    if not (isinstance(datos, list) and datos and isinstance(datos[0], dict)):
        raise MoodleCourseError("respuesta de cursos inesperada")
    if datos[0].get("error") is not False:
        raise MoodleCourseError("listado de cursos rechazado")
    cuerpo = datos[0].get("data") or {}
    if not isinstance(cuerpo, dict):
        raise MoodleCourseError("respuesta de cursos sin datos")
    lista = cuerpo.get("courses") or []
    if not isinstance(lista, list):
        raise MoodleCourseError("respuesta de cursos sin lista")
    cursos = []
    for curso in lista:
        if not isinstance(curso, dict):
            continue
        identificador: Any = curso.get("id")
        if isinstance(identificador, bool):
            continue
        try:
            curso_id = int(identificador)
        except (TypeError, ValueError):
            continue
        nombre = html.unescape(str(curso.get("fullname") or curso.get("shortname") or "")).strip()
        cursos.append({"id": curso_id, "nombre": nombre or f"Curso {curso_id}"})
    return sorted(cursos, key=lambda curso: curso["nombre"].casefold())


def _campo(contenedor, nombre: str) -> str | None:
    campos = contenedor.find_all(attrs={"name": nombre})
    if not campos:
        return None
    # Una casilla puede ir precedida de un oculto con su mismo nombre (valor 0):
    # manda la casilla, y solo si está marcada.
    for campo in campos:
        if campo.name == "input" and (campo.get("type") or "").lower() == "checkbox":
            return (campo.get("value") or "1") if campo.has_attr("checked") else None
    # Un grupo de botones de opción (la finalización) vale lo que marca el elegido, no el primero.
    if all(c.name == "input" and (c.get("type") or "").lower() == "radio" for c in campos):
        marcado = next((c for c in campos if c.has_attr("checked")), None)
        return marcado.get("value") if marcado is not None else None
    campo = campos[0]
    if campo.name == "textarea":
        return campo.text
    if campo.name == "select":
        opcion = campo.find("option", selected=True) or campo.find("option")
        return opcion.get("value") if opcion else None
    return campo.get("value")


def _fecha_leida(formulario, campo: str) -> tuple[int, int, int, int, int] | None:
    """Fecha de un selector del formulario, o None si está desactivada o no está."""
    if _campo(formulario, f"{campo}[enabled]") != "1":
        return None
    valores: list[int] = []
    for parte in ("year", "month", "day", "hour", "minute"):
        valor = _campo(formulario, f"{campo}[{parte}]")
        if valor is None or not valor.isdigit():
            return None
        valores.append(int(valor))
    anio, mes, dia, hora, minuto = valores
    return (anio, mes, dia, hora, minuto)


def autenticar(base_url: str, usuario: str, password: str) -> Moodle:
    """Un único intento de login con la sesión web, sin token y sin reintentos."""
    try:
        sesion = py_auth.login(base_url, usuario, password)
    except ERRORES_MOODLE as exc:
        if _bloqueo_de_destino(exc):
            raise ErrorPublicacion("DESTINO_NO_PERMITIDO") from exc
        if isinstance(exc, LoginError):
            raise ErrorPublicacion("LOGIN_FALLIDO") from exc
        if isinstance(exc, MoodleSessionError):
            raise ErrorPublicacion("SESION_NO_INICIADA") from exc
        raise ErrorPublicacion("ERROR_LOGIN") from exc
    sesskey = getattr(sesion, "sesskey", None)
    if not sesskey:
        raise ErrorPublicacion("SESION_SIN_SESSKEY")
    # La publicación usa la sesión web: se descarta cualquier token.
    sesion.webservice_token = None  # type: ignore[attr-defined]
    return Moodle(base_url, sesion, sesskey)


def cerrar_aula(aula: Any) -> None:
    """Cierra la sesión del aula si el adaptador sabe hacerlo; nunca lanza."""
    cerrar = getattr(aula, "cerrar", None)
    if callable(cerrar):
        try:
            cerrar()
        except Exception:  # noqa: BLE001 - igual que ``Moodle.cerrar``
            return


@contextlib.contextmanager
def sesion_del_aula(aula: Any) -> Iterator[Any]:
    """Mantiene el aula abierta mientras dura el bloque y cierra su sesión al salir."""
    try:
        yield aula
    finally:
        cerrar_aula(aula)


@dataclasses.dataclass(frozen=True)
class Contrasena:
    """Acreditación por contraseña (terminal): se envía una sola vez al aula."""

    valor: str = dataclasses.field(repr=False)


@dataclasses.dataclass(frozen=True)
class Cookies:
    """Acreditación por sesión ya iniciada en la ventana de entrada: (nombre, valor, dominio)."""

    valores: Sequence[tuple[str, str, str]] = dataclasses.field(repr=False)


Acreditacion = Contrasena | Cookies


def autenticar_con(base_url: str, usuario: str, acreditacion: Acreditacion) -> Moodle:
    """Entra al aula con lo que haya aportado el docente (contraseña o cookies)."""
    if isinstance(acreditacion, Cookies):
        return autenticar_con_cookies(base_url, acreditacion.valores)
    return autenticar(base_url, usuario, acreditacion.valor)


def autenticar_con_cookies(base_url: str, cookies: Sequence[tuple[str, str, str]]) -> Moodle:
    """Sesión web a partir de las cookies de un login hecho en la ventana de entrada.

    Usa la misma sesión que ``autenticar`` (guardia de destino y User-Agent de tiza),
    sin enviar ninguna contraseña. Si el aula ya no reconoce la sesión, falla con
    ``SESION_NO_INICIADA``.
    """
    auth = py_auth.MoodleAuth(base_url, "", "")
    sesion = auth.session
    servidor = urlsplit(auth.base_url).hostname or ""
    for nombre, valor, dominio in cookies:
        # Solo las que el navegador enviaría al aula; una cookie del dominio padre
        # (``sessioncookiedomain``) conserva su dominio. Siguen viajando solo al aula:
        # el adaptador de la sesión bloquea cualquier otro servidor.
        dominio = dominio.lstrip(".").lower()
        if not coincide_dominio(servidor, dominio):
            continue
        propio = servidor if dominio == servidor.lower() else f".{dominio}"
        sesion.cookies.set(nombre, valor, domain=propio, path="/", secure=True)
    try:
        respuesta = sesion.get(f"{auth.base_url}/my/", timeout=TIEMPO_ESPERA)
        if "/login/" in str(getattr(respuesta, "url", "")):
            raise ErrorPublicacion("SESION_NO_INICIADA")
        sesskey = auth.compatibility.extract_sesskey(respuesta.text)
        if not sesskey:
            raise ErrorPublicacion("SESION_SIN_SESSKEY")
        contexto = detect_moodle_compatibility(sesion, auth.base_url, token=None)
    except ERRORES_MOODLE as exc:
        if _bloqueo_de_destino(exc):
            raise ErrorPublicacion("DESTINO_NO_PERMITIDO") from exc
        raise ErrorPublicacion("SESION_NO_INICIADA") from exc
    sesion.sesskey = sesskey  # type: ignore[attr-defined]
    sesion.webservice_token = None  # type: ignore[attr-defined]
    sesion.moodle_version = contexto.version  # type: ignore[attr-defined]
    sesion.moodle_compat = contexto.strategy  # type: ignore[attr-defined]
    return Moodle(base_url, sesion, sesskey)


# --------------------------------------------------------------------------- #
# Payloads de módulo (fachada del registro: cada formulario lo arma su adapter)
# --------------------------------------------------------------------------- #


def payload_pagina(doc: Documento, html: str, itemid: int, visible: bool | None) -> dict:
    return tipos.obtener("pagina").payload(doc, html, itemid, visible)


def payload_etiqueta(doc: Documento, html: str, itemid: int, visible: bool | None) -> dict:
    return tipos.obtener("etiqueta").payload(doc, html, itemid, visible)


def payload_tarea(doc: Documento, html: str, itemid: int, visible: bool | None) -> dict:
    """Formulario de una tarea."""
    return tipos.obtener("tarea").payload(doc, html, itemid, visible)


def payload_cuestionario(doc: Documento, html: str, itemid: int, visible: bool | None) -> dict:
    """Formulario de un cuestionario; las preguntas van aparte, por el banco."""
    return tipos.obtener("cuestionario").payload(doc, html, itemid, visible)


def payload_h5p(
    doc: Documento, html: str, itemid: int, itemid_paquete: int, visible: bool | None
) -> dict:
    """Formulario de una actividad H5P.

    ``itemid`` es el borrador de la descripción y ``itemid_paquete`` el del
    fichero .h5p (van separados para que no se mezclen).
    """
    return tipos.obtener("h5p").payload(doc, html, itemid, visible, itemid_paquete=itemid_paquete)


def payload_solo_fechas(doc: Documento) -> dict:
    """Formulario mínimo para cambiar solo las fechas de una actividad ya publicada.

    No lleva nombre, texto, preguntas, intentos ni visibilidad: python-moodle fusiona
    el formulario con lo que ya tiene el módulo, así que esos campos no cambian.
    """
    payload = tipos.obtener(doc.tipo).payload_solo_fechas(doc)
    if payload is None:
        raise ErrorPublicacion("SOLO_FECHAS_NO_APLICA", doc.ruta.name)
    return payload


def fechas_esperadas(doc: Documento) -> dict[str, tuple[int, int, int, int, int] | None]:
    """Lo que debe mostrar el formulario de la actividad tras publicarla."""
    return tipos.fechas_esperadas(tipos.obtener(doc.tipo), doc)


# --------------------------------------------------------------------------- #
# Publicación y verificación
# --------------------------------------------------------------------------- #


def _convertir(problema: tuple[str, str] | None) -> None:
    """El único sitio que convierte un problema de ``estructura`` en error de publicación."""
    if problema is not None:
        raise ErrorPublicacion(*problema)


class ActividadVigilada(Protocol):
    """Lo que ``publicar`` necesita de la actividad vigilada, sin importar ``vigilancia``."""

    cmid: int

    def comprobar(self, leer: Callable[[], dict], solo_fechas: bool) -> bool: ...

    def fechas_verificadas(self, info: dict) -> None: ...


class _LectorDeFormulario:
    """Un formulario leído una sola vez, para la comprobación y para el payload."""

    def __init__(self, moodle: AulaVirtual, cmid: int | None) -> None:
        self._moodle = moodle
        self._cmid = cmid
        self.leido: dict | None = None

    def leer(self) -> dict:
        if self.leido is None:
            assert self._cmid is not None
            self.leido = self._moodle.leer_modulo(self._cmid)
        return self.leido


def publicar_documento(
    moodle: AulaVirtual,
    curso_id: int,
    estructura: Estructura,
    doc: Documento,
    *,
    visible: bool | None,
    dependencias: dict[str, int] | None = None,
    vigilada: ActividadVigilada | None = None,
    rubrica_confirmada: bool = False,
    resultados: dict[str, int] | None = None,
    pasos: list | None = None,
) -> informe.Fichero:
    """Crea o actualiza un documento y lo verifica releyendo el módulo.

    ``visible=None`` conserva la visibilidad de lo que ya existe; lo nuevo se crea oculto.
    Los recursos se copian una sola vez y se comprueba que siguen siendo los que
    el docente confirmó (``hash_cargado``): sustituirlos después no sirve.
    ``dependencias``: el cmid, en este curso, de cada fichero de ``restricciones.completar``.

    Con ``origen`` en este curso (``curso_id``), la actividad se busca por su ``cmid`` (aunque
    haya cambiado de nombre o de sección). ``vigilada``: la actividad vigilada de este documento
    (``vigilancia.ActividadVigilada``); justo antes de escribir comprueba si el docente la retocó
    y, si es así, ``CAMBIADA_EN_EL_AULA`` y no se toca nada. Sin ella no se compara.
    ``rubrica_confirmada``: el docente confirmó que las tareas existentes que ganan rúbrica no
    tienen notas. ``pasos``: lista donde el tipo deja los pasos que añade al informe.
    """
    with tempfile.TemporaryDirectory(prefix="tiza-recursos-") as temporal:
        copia = _congelar_recursos(doc, Path(temporal))
        return _publicar_congelado(
            moodle,
            curso_id,
            estructura,
            copia,
            visible=visible,
            original=doc,
            dependencias=dependencias or {},
            vigilada=vigilada,
            rubrica_confirmada=rubrica_confirmada,
            resultados=resultados,
            pasos=pasos,
        )


def _congelar_recursos(doc: Documento, carpeta: Path) -> Documento:
    recursos = []
    for recurso in doc.recursos:
        destino = carpeta / recurso.nombre
        try:
            shutil.copyfile(recurso.ruta, destino)
        except OSError as exc:
            raise ErrorPublicacion("RECURSO_ILEGIBLE", doc.ruta.name) from exc
        recursos.append(Recurso(nombre=recurso.nombre, ruta=destino))
    copia = dataclasses.replace(doc, recursos=recursos)
    if doc.hash_cargado and hash_documento(copia) != doc.hash_cargado:
        raise ErrorPublicacion("FICHERO_MODIFICADO", doc.ruta.name)
    return copia


def _publicar_congelado(
    moodle: AulaVirtual,
    curso_id: int,
    estructura: Estructura,
    doc: Documento,
    *,
    visible: bool | None,
    original: Documento,
    dependencias: dict[str, int],
    vigilada: ActividadVigilada | None = None,
    rubrica_confirmada: bool = False,
    resultados: dict[str, int] | None = None,
    pasos: list | None = None,
) -> informe.Fichero:
    seccion = estructura.buscar_seccion(doc.seccion)
    if seccion is None:
        raise ErrorPublicacion("SECCION_AUSENTE", doc.ruta.name)
    loc = estructura.localizar(doc, curso_id)
    _convertir((loc.problema, doc.ruta.name) if loc.problema is not None else None)
    if loc.por == "otra_seccion" and loc.modulo is None:
        # Varias iguales en otras secciones y ninguna en la suya: no se sabe cuál es.
        raise ErrorPublicacion("ACTIVIDAD_AMBIGUA", doc.ruta.name)
    existente = loc.modulo
    # Hallada en otra sección (por su ``origen``, su registro o su nombre): cambió ``seccion:``.
    movido = existente is not None and (
        loc.por == "otra_seccion" or loc.seccion is None or loc.seccion.id != seccion.id
    )
    # Hallada por su ``origen`` o su registro con otro nombre en el aula: se renombra, no se duplica.
    renombrado = (
        existente is not None
        and loc.por in ("origen", "registro")
        and existente.nombre != doc.nombre
    )
    lector = _LectorDeFormulario(moodle, existente.cmid if existente is not None else None)
    if vigilada is not None:
        assert existente is not None and vigilada.cmid == existente.cmid
        if vigilada.comprobar(lector.leer, solo_fechas=False):
            raise ErrorPublicacion("CAMBIADA_EN_EL_AULA", doc.ruta.name)
    leido = lector.leido
    # Si el payload necesita algo del formulario de edición, se carga una sola vez.
    if leido is None and existente is not None:
        if tipos.obtener(doc.tipo).lee_formulario_al_actualizar:
            leido = lector.leer()
    # Antes de escribir nada: una restricción ajena o una finalización bloqueada paran todo.
    envio = preparar_itinerario(moodle, doc, existente, dependencias, leido)
    if movido and existente is not None:
        moodle.mover(curso_id, existente.cmid, seccion.id, None)

    # Sin indicación: lo nuevo nace oculto y lo que ya existe conserva su visibilidad.
    if visible is None and existente is None:
        visible = False

    # Borrador nuevo: un itemid arbitrario basta; no hace falta la consulta AJAX
    # que usa python-moodle para pedirlo (core_user_get_private_files_info).
    itemid = int(time.time() * 1000)
    html = html_para_moodle(doc)
    if doc.recursos:
        contexto = moodle.contexto(curso_id)
        for recurso in doc.recursos:
            _itemid, nombre_final = moodle.subir(curso_id, contexto, recurso.ruta, itemid)
            if nombre_final != recurso.nombre:
                html = html.replace(
                    f"@@PLUGINFILE@@/{recurso.nombre}",
                    f"@@PLUGINFILE@@/{nombre_final}",
                )
    tipo = tipos.obtener(doc.tipo)
    cmid, accion, info = tipo.publicar(
        tipos.ContextoPublicacion(
            moodle=moodle,
            curso_id=curso_id,
            seccion=seccion,
            doc=doc,
            html=html,
            itemid=itemid,
            visible=visible,
            existente=existente,
            pasos=pasos if pasos is not None else [],
            leido=leido,
            rubrica_confirmada=rubrica_confirmada,
            resultados=dict(resultados or {}),
        )
    )
    aplicar_itinerario(moodle, doc, cmid, envio)
    return informe.Fichero(
        nombre=original.ruta.name,
        tipo=doc.tipo,
        cmid=cmid,
        accion="renombrada" if renombrado else "movida" if movido else accion,
        oculto=_oculto(visible, info),
        url=url_modulo(moodle.base_url, doc.tipo, cmid),
        seccion=seccion.nombre,
        hash=hash_documento(doc),
    )


# --------------------------------------------------------------------------- #
# Itinerario: finalización y restricciones de acceso
# --------------------------------------------------------------------------- #

# Campos del formulario que se leen para decidir (uso interno; nunca salen de la sesión).
CAMPOS_FINALIZACION_LEIDOS = (
    "completion",
    "completionview",
    "completionsubmit",
    "completionusegrade",
    "completionunlocked",
)
# Lista blanca de las condiciones de acceso que tiza escribe y reconoce como suyas.
_TIPOS_DE_TIZA = frozenset({"date", "completion"})


def payload_finalizacion(doc: Documento, *, solo_fecha_esperada: bool = False) -> dict:
    """Campos de finalización del formulario, o ``{}`` si el documento no la declara.

    Se envían todos los del tipo (los no usados a 0): la fusión conserva lo que no se
    envía, y un modo anterior dejaría su casilla marcada.
    """
    return tipos.payload_finalizacion(
        tipos.obtener(doc.tipo), doc, solo_fecha_esperada=solo_fecha_esperada
    )


def modo_leido(tipo: str, campos: dict) -> str | None:
    """El modo de finalización que dice el formulario; None si no es uno de los de tiza."""
    return tipos.modo_leido(tipos.obtener(tipo), campos)


def _condiciones_de(restricciones, dependencias: dict[str, int]) -> tuple[list[dict], list[bool]]:
    condiciones: list[dict] = []
    if restricciones.desde is not None:
        condiciones.append({"type": "date", "d": ">=", "t": int(restricciones.desde.timestamp())})
    if restricciones.hasta is not None:
        condiciones.append({"type": "date", "d": "<", "t": int(restricciones.hasta.timestamp())})
    for fichero in restricciones.completar:
        condiciones.append({"type": "completion", "cm": dependencias[fichero], "e": 1})
    return condiciones, [not restricciones.ocultar] * len(condiciones)


def validar_disponibilidad(texto: str) -> None:
    """Rechaza cualquier JSON de acceso que no sea «y» de fechas y finalizaciones.

    Es el último control antes de enviar: nunca sale de tiza una condición de grupo,
    agrupamiento, perfil, nota ni nada que no sea fecha o finalización.
    """
    if texto == "":
        return
    try:
        datos = json.loads(texto)
    except ValueError:
        raise ErrorPublicacion("RESTRICCION_INVALIDA") from None
    if (
        not isinstance(datos, dict)
        or set(datos) != {"op", "c", "showc"}
        or datos["op"] != "&"
        or not isinstance(datos["c"], list)
        or not datos["c"]
        or not isinstance(datos["showc"], list)
        or len(datos["showc"]) != len(datos["c"])
        or any(not isinstance(visible, bool) for visible in datos["showc"])
    ):
        raise ErrorPublicacion("RESTRICCION_INVALIDA")
    for condicion in datos["c"]:
        if not isinstance(condicion, dict):
            raise ErrorPublicacion("RESTRICCION_INVALIDA")
        if condicion.get("type") == "date":
            valido = (
                set(condicion) == {"type", "d", "t"}
                and condicion["d"] in (">=", "<")
                and _es_entero(condicion["t"])
            )
        elif condicion.get("type") == "completion":
            valido = (
                set(condicion) == {"type", "cm", "e"}
                and _es_entero(condicion["cm"])
                and condicion["e"] == 1
            )
        else:
            valido = False
        if not valido:
            raise ErrorPublicacion("RESTRICCION_INVALIDA")


def _es_entero(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def payload_disponibilidad(doc: Documento, dependencias: dict[str, int]) -> dict:
    """``availabilityconditionsjson`` de lo que declara el documento (vacío: quitar)."""
    restricciones = doc.restricciones
    if restricciones is None:
        return {}
    condiciones, visibles = _condiciones_de(restricciones, dependencias)
    texto = (
        json.dumps({"op": "&", "c": condiciones, "showc": visibles}, separators=(",", ":"))
        if condiciones
        else ""
    )
    validar_disponibilidad(texto)
    return {"availabilityconditionsjson": texto}


def es_disponibilidad_de_tiza(texto: str) -> bool:
    """¿La restricción que ya tiene el aula usa solo clases que tiza gestiona?

    Una restricción vacía lo es. Cualquier otra cosa (grupo, perfil, nota, un «o»,
    condiciones anidadas…) es ajena: tiza no la toca ni dice de qué clase es.
    """
    if not texto or not texto.strip():
        return True
    try:
        datos = json.loads(texto)
    except ValueError:
        return False
    if not isinstance(datos, dict) or datos.get("op") != "&" or "show" in datos:
        return False
    condiciones = datos.get("c")
    if not isinstance(condiciones, list):
        return False
    return all(
        isinstance(condicion, dict) and condicion.get("type") in _TIPOS_DE_TIZA
        for condicion in condiciones
    )


def _misma_disponibilidad(leida: str, esperada: str) -> bool:
    def normal(texto: str) -> Any:
        if not texto or not texto.strip():
            return None
        try:
            datos = json.loads(texto)
        except ValueError:
            return texto
        if isinstance(datos, dict) and not datos.get("c"):
            return None  # sin condiciones es lo mismo que vacío
        return datos

    return normal(leida) == normal(esperada)


@dataclasses.dataclass(frozen=True)
class EnvioItinerario:
    """Lo que hay que enviar tras publicar el contenido; ``vacio`` si el documento no declara nada."""

    payload: dict
    finalizacion: bool  # hay que comprobar la finalización tras enviarla
    disponibilidad: str | None  # JSON esperado, o None si el documento no declara restricciones

    @property
    def vacio(self) -> bool:
        return not self.payload


def preparar_itinerario(
    moodle: AulaVirtual,
    doc: Documento,
    existente: Actividad | None,
    dependencias: dict[str, int],
    leido: dict | None = None,
) -> EnvioItinerario:
    """Decide qué se enviará y, antes de escribir nada, rechaza lo que no se puede aplicar.

    Lo que el aula ya tiene se examina aquí dentro y no sale: solo se devuelve un código.
    ``leido``: el formulario de la actividad si quien llama ya lo cargó (no se carga otra vez).
    """
    if doc.finalizacion is None and doc.restricciones is None:
        return EnvioItinerario({}, False, None)
    faltan = [
        f
        for f in (doc.restricciones.completar if doc.restricciones else ())
        if f not in dependencias
    ]
    if faltan:
        raise ErrorPublicacion("DEPENDENCIA_NO_PUBLICADA", faltan[0])
    payload: dict = {}
    disponibilidad = payload_disponibilidad(doc, dependencias)
    payload.update(disponibilidad)
    finalizacion = payload_finalizacion(doc)
    actual: dict | None = None
    if existente is not None:
        if leido is None:
            leido = moodle.leer_modulo(existente.cmid)
        actual = leido.get("itinerario") or {}
        if doc.restricciones is not None and not es_disponibilidad_de_tiza(
            actual.get("disponibilidad", "")
        ):
            raise ErrorPublicacion("RESTRICCION_AJENA", doc.ruta.name)
        if doc.finalizacion is not None:
            campos = actual.get("campos") or {}
            if campos.get("completion") is None and campos.get("completionunlocked") is None:
                raise ErrorPublicacion("FINALIZACION_DESACTIVADA", doc.ruta.name)
            if campos.get("completionunlocked") == "0":
                if modo_leido(doc.tipo, campos) != doc.finalizacion.modo:
                    raise ErrorPublicacion("FINALIZACION_BLOQUEADA", doc.ruta.name)
                # El modo ya es el pedido: solo la fecha esperada, que no está bloqueada.
                finalizacion = payload_finalizacion(doc, solo_fecha_esperada=True)
    payload.update(finalizacion)
    return EnvioItinerario(
        payload,
        doc.finalizacion is not None,
        disponibilidad["availabilityconditionsjson"] if disponibilidad else None,
    )


def aplicar_itinerario(
    moodle: AulaVirtual, doc: Documento, cmid: int, envio: EnvioItinerario
) -> None:
    """Envía la finalización y las restricciones y comprueba que el aula las guardó."""
    if envio.vacio:
        return
    moodle.actualizar(cmid, envio.payload)
    leido = moodle.leer_modulo(cmid).get("itinerario") or {}
    try:
        _verificar_itinerario(doc, leido, envio)
    except ErrorPublicacion as exc:
        exc.cmid = cmid
        raise


def _verificar_itinerario(doc: Documento, leido: dict, envio: EnvioItinerario) -> None:
    if envio.finalizacion and doc.finalizacion is not None:
        campos = leido.get("campos") or {}
        if campos.get("completion") is None:
            # El formulario no trae la finalización: el curso no la tiene activada.
            raise ErrorPublicacion("FINALIZACION_DESACTIVADA", doc.ruta.name)
        if modo_leido(doc.tipo, campos) != doc.finalizacion.modo:
            raise ErrorPublicacion("ITINERARIO_NO_APLICADO", doc.ruta.name)
        esperada = doc.finalizacion.esperada
        if leido.get("esperada") != (None if esperada is None else tipos.partes_fecha(esperada)):
            raise ErrorPublicacion("ITINERARIO_NO_APLICADO", doc.ruta.name)
    if envio.disponibilidad is not None and not _misma_disponibilidad(
        leido.get("disponibilidad", ""), envio.disponibilidad
    ):
        raise ErrorPublicacion("ITINERARIO_NO_APLICADO", doc.ruta.name)


def asegurar_secciones(
    moodle: AulaVirtual, curso_id: int, estructura: Estructura, documentos: list[Documento]
) -> tuple[Estructura, list[str]]:
    """Crea (ocultas) las secciones por nombre que falten y relee la estructura."""
    creadas = estructura.secciones_que_faltan(documentos)
    if not creadas:
        return estructura, []
    for nombre in creadas:
        moodle.crear_seccion(curso_id, nombre)
    estructura = moodle.estructura(curso_id)
    for nombre in creadas:
        if estructura.buscar_seccion(nombre) is None:
            raise ErrorPublicacion("SECCION_NO_CREADA", nombre)
    return estructura, creadas


def publicar_fechas(
    moodle: AulaVirtual,
    estructura: Estructura,
    doc: Documento,
    curso: int | None = None,
    *,
    vigilada: ActividadVigilada | None = None,
) -> informe.Fichero:
    """Cambia solo las fechas de una tarea o un cuestionario que ya está en el aula.

    No toca el contenido, los recursos, las preguntas, los intentos ni la
    visibilidad, así que no pasa por la puerta de pruebas ni sube nada. Si el
    módulo no existe, no envía nada.

    ``vigilada``: la actividad vigilada de este documento. Antes de escribir comprueba si el
    docente retocó el aula (``CAMBIADA_EN_EL_AULA`` y no se envía nada); si vale la guardada o
    las fechas ya eran las pedidas, sigue. Tras verificar, deja en ella la huella nueva (nombre y
    texto del aula, fechas nuevas), o nada si se aceptó porque las fechas ya estaban.
    """
    loc = estructura.localizar(doc, curso)
    _convertir((loc.problema, doc.ruta.name) if loc.problema is not None else None)
    existente = loc.actividad
    if existente is None:
        raise ErrorPublicacion("MODULO_AUSENTE", doc.ruta.name)
    cmid = existente.cmid
    if vigilada is not None:
        assert vigilada.cmid == cmid
        lector = _LectorDeFormulario(moodle, cmid)
        if vigilada.comprobar(lector.leer, solo_fechas=True):
            raise ErrorPublicacion("CAMBIADA_EN_EL_AULA", doc.ruta.name)
    moodle.actualizar(cmid, payload_solo_fechas(doc))
    info = _verificar_fechas(moodle, doc, cmid)
    if vigilada is not None:
        vigilada.fechas_verificadas(info)
    seccion = estructura.buscar_seccion(doc.seccion)
    return informe.Fichero(
        nombre=doc.ruta.name,
        tipo=doc.tipo,
        cmid=cmid,
        accion="actualizada",
        oculto=_oculto(None, info),
        url=url_modulo(moodle.base_url, doc.tipo, cmid),
        seccion=(seccion.nombre if seccion is not None else "") or str(doc.seccion),
        # El contenido no cambia: el hash es el que el docente ya vio al confirmar.
        hash=doc.hash_cargado or None,
    )


class Movimiento(NamedTuple):
    """Poner ``cmid`` en ``seccion_id`` antes de ``antes_de`` (o al final si es ``None``)."""

    cmid: int
    seccion_id: int
    antes_de: int | None


def orden_final(actual: list[int], deseado: list[int]) -> list[int]:
    """La sección tras repartir los huecos que ocupaban los nombrados, en el orden de ``deseado``."""
    nombrados = set(deseado)
    huecos = [indice for indice, cmid in enumerate(actual) if cmid in nombrados]
    final = list(actual)
    for indice, cmid in zip(huecos, deseado, strict=True):
        final[indice] = cmid
    return final


def plan_de_orden(
    estructura: Estructura, deseados: list[tuple[int, list[int]]]
) -> list[Movimiento]:
    """Los movimientos que dejan, en cada sección, los módulos nombrados en el orden pedido.

    Pura. ``deseados``: por sección, su id y los cmids en el orden deseado (todos de esa
    sección, sin repetir). Lo no nombrado no se mueve nunca: los nombrados se reparten los
    huecos que ya ocupaban. Se recorre el orden final de atrás hacia delante y solo se mueve
    el módulo que no está ya justo delante del que le sigue; ya ordenado, devuelve ``[]``.
    """
    movimientos: list[Movimiento] = []
    for seccion_id, cmids in deseados:
        seccion = estructura.seccion_con_id(seccion_id)
        assert seccion is not None  # el id sale de ``resolver_orden``
        actual = list(seccion.cmids)
        final = orden_final(actual, cmids)
        nombrados = set(cmids)
        for indice in range(len(final) - 1, -1, -1):
            cmid = final[indice]
            if cmid not in nombrados:
                continue
            siguiente = final[indice + 1] if indice + 1 < len(final) else None
            posicion = actual.index(cmid)
            delante = actual[posicion + 1] if posicion + 1 < len(actual) else None
            if delante == siguiente:
                continue
            actual.pop(posicion)
            actual.insert(len(actual) if siguiente is None else actual.index(siguiente), cmid)
            movimientos.append(Movimiento(cmid, seccion_id, siguiente))
    return movimientos


def colocar_notas(
    moodle: AulaVirtual,
    curso: int,
    estructura: Estructura,
    cmids: Sequence[int],
    esperado: Mapping[int, str | None] | None = None,
) -> tuple[tuple[colocacion.MovimientoNota, ...], tuple[colocacion.SinColocar, ...]]:
    """Coloca en el calificador las notas de ``cmids`` según su sección y lo comprueba.

    Lee el árbol del calificador, aplica la regla pura (:func:`tiza.colocacion.colocar`) y
    ejecuta los movimientos en orden. Con ``esperado`` (de cada cmid, la categoría que el
    docente vio en el resumen; ``None``: no se iba a colocar) no se mueve ninguna nota cuyo
    destino sea otro: sale como ``SinColocar`` con motivo ``CAMBIADA``. Un cmid que no está en
    ``esperado`` cuenta como «no se iba a colocar». Tras escribir relee el árbol y comprueba
    que cada nota quedó en su categoría y justo detrás de su precedente
    (``NOTA_NO_COLOCADA`` si no). Los errores de lectura y de escritura salen tal cual.
    """
    arbol = moodle.arbol_notas(curso)
    movimientos, sin_colocar = colocacion.colocar(estructura, arbol, cmids)
    if esperado is not None:
        validos: list[colocacion.MovimientoNota] = []
        cambiadas: list[colocacion.SinColocar] = []
        for movimiento in movimientos:
            if esperado.get(movimiento.cmid) == movimiento.categoria:
                validos.append(movimiento)
            else:
                cambiadas.append(colocacion.SinColocar(movimiento.cmid, "CAMBIADA", None))
        movimientos = tuple(validos)
        sin_colocar = (*sin_colocar, *cambiadas)
    if not movimientos:
        return (), tuple(sin_colocar)
    for movimiento in movimientos:
        moodle.mover_nota(curso, movimiento.eid, movimiento.categoria, movimiento.despues_de)
    releido = moodle.arbol_notas(curso)
    for movimiento in movimientos:
        fila = releido.fila(movimiento.eid)
        if fila is None or fila.padre != movimiento.categoria:
            raise ErrorPublicacion("NOTA_NO_COLOCADA")
        hermanas = [f.eid for f in releido.filas if f.padre == movimiento.categoria]
        indice = hermanas.index(movimiento.eid)
        anterior = hermanas[indice - 1] if indice > 0 else None
        if anterior != movimiento.despues_de:
            raise ErrorPublicacion("NOTA_NO_COLOCADA")
    return tuple(movimientos), tuple(sin_colocar)


def con_orden_final(estructura: Estructura, finales: Mapping[int, list[int]]) -> Estructura:
    """La estructura con las secciones de ``finales`` (id -> cmids) en ese orden. Pura."""
    secciones = []
    for seccion in estructura:
        final = finales.get(seccion.id)
        if final is None:
            secciones.append(seccion)
            continue
        por_cmid = {actividad.cmid: actividad for actividad in seccion.actividades}
        secciones.append(
            dataclasses.replace(seccion, actividades=tuple(por_cmid[cmid] for cmid in final))
        )
    return dataclasses.replace(estructura, secciones=tuple(secciones))


def ordenar_notas(
    moodle: AulaVirtual,
    curso: int,
    estructura: Estructura,
    cmids: Collection[int],
    esperado: int | None = None,
) -> int:
    """Deja las notas de ``cmids`` en el orden del curso dentro de su categoría; cuántas movió.

    Lee el árbol, aplica :func:`tiza.colocacion.reordenar` y ejecuta los movimientos. Tras
    escribir relee y comprueba que cada nota sigue en su categoría y que ya no queda nada por
    reordenar (``NOTA_NO_COLOCADA`` si no). Los errores de lectura y de escritura salen tal cual.
    Con ``esperado`` (cuántas notas vio mover el docente) no se escribe nada si son otras:
    ``CAMBIADA``.
    """
    movimientos = colocacion.reordenar(estructura, moodle.arbol_notas(curso), cmids)
    if esperado is not None and len(movimientos) != esperado:
        raise ErrorPublicacion("CAMBIADA")
    if not movimientos:
        return 0
    for movimiento in movimientos:
        moodle.mover_nota(curso, movimiento.eid, movimiento.categoria, movimiento.despues_de)
    releido = moodle.arbol_notas(curso)
    for movimiento in movimientos:
        fila = releido.fila(movimiento.eid)
        if fila is None or fila.padre != movimiento.categoria:
            raise ErrorPublicacion("NOTA_NO_COLOCADA")
    # Cada ``despues_de`` se dio con lo que había delante al mover y los movimientos
    # posteriores lo cambian: lo que se comprueba es que ya no queda nada por reordenar.
    if colocacion.reordenar(estructura, releido, cmids):
        raise ErrorPublicacion("NOTA_NO_COLOCADA")
    return len(movimientos)


def ordenar_documentos(
    moodle: AulaVirtual, curso_id: int, estructura: Estructura, docs: list[Documento]
) -> list[informe.Fichero]:
    """Deja las actividades de ``docs`` en el orden dado dentro de su sección y lo comprueba.

    Sin cambios no llama al aula. Si falla a medias no se deshace nada: mover no destruye y
    repetir converge.
    """
    resolucion = estructura.resolver_orden(docs, curso_id)
    _convertir(resolucion.problema)
    grupos = resolucion.grupos
    deseados = [(seccion.id, [actividad.cmid for _, actividad in par]) for seccion, par in grupos]
    movimientos = plan_de_orden(estructura, deseados)
    if movimientos:
        esperados = {
            seccion.id: orden_final(
                [actividad.cmid for actividad in seccion.actividades],
                [actividad.cmid for _, actividad in par],
            )
            for seccion, par in grupos
        }
        for movimiento in movimientos:
            moodle.mover(curso_id, *movimiento)
        releida = moodle.estructura(curso_id)
        for seccion_id, esperado in esperados.items():
            nueva = releida.seccion_con_id(seccion_id)
            if nueva is None or list(nueva.cmids) != esperado:
                raise ErrorPublicacion("ORDEN_NO_APLICADO")
    cambiadas = {movimiento.seccion_id for movimiento in movimientos}
    return [
        informe.Fichero(
            nombre=doc.ruta.name,
            tipo=doc.tipo,
            cmid=actividad.cmid,
            accion="ordenada" if seccion.id in cambiadas else "sin_cambios",
            url=url_modulo(moodle.base_url, doc.tipo, actividad.cmid),
            seccion=seccion.nombre,
            hash=hash_documento(doc),
        )
        for seccion, par in grupos
        for doc, actividad in par
    ]


def _verificar_fechas(moodle: AulaVirtual, doc: Documento, cmid: int) -> dict:
    """Relee el módulo y comprueba solo sus fechas; el resto no se mira."""
    info = moodle.leer_modulo(cmid)
    leidas = info.get("fechas") or {}
    if any(leidas.get(campo) != valor for campo, valor in fechas_esperadas(doc).items()):
        raise ErrorPublicacion("FECHAS_NO_APLICADAS", doc.ruta.name)
    return info


def _oculto(visible: bool | None, info: dict) -> bool | None:
    """Visibilidad final: la pedida o, si se conservó, la que muestra el formulario."""
    if visible is not None:
        return not visible
    return {"1": False, "0": True}.get(str(info.get("visible")))


def urls_pluginfile(base_url: str, contexto, tipo: str, instance, nombre: str) -> list[str]:
    """Fachada del registro: cada tipo sabe dónde vive su recurso (``@@PLUGINFILE@@``)."""
    return tipos.obtener(tipo).urls_pluginfile(base_url, contexto, instance, nombre)


def urls_paquete_h5p(base_url: str, contexto, instance, nombre: str) -> list[str]:
    """Las dos formas válidas de la ruta del paquete (la espiga comprobó ambas)."""
    return tipos.base.urls_paquete_h5p(base_url, contexto, instance, nombre)


def url_modulo(base_url: str, tipo: str, cmid: int) -> str:
    return f"{base_url}/mod/{tipos.obtener(tipo).modulo}/view.php?id={cmid}"


# --------------------------------------------------------------------------- #
# Autoprueba de contrato
# --------------------------------------------------------------------------- #

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def aula_dibuja_formulas(moodle: AulaVirtual, curso_id: int) -> bool:
    """Falso solo si el aula respondió y no carga el motor; si no se puede mirar, no se avisa."""
    try:
        return moodle.motor_de_formulas(curso_id)
    except ErrorPublicacion:
        return True


def aula_deja_copiar(moodle: AulaVirtual, curso_id: int) -> bool:
    """Falso solo si el aula respondió y el docente no ve el formulario de copia del curso.

    Es solo lectura; si no se puede mirar, no se avisa.
    """
    try:
        return moodle.puede_copiar(curso_id)
    except ErrorPublicacion:
        return True


DETALLE_COPIA_A_MANO = (
    "el aula no da al docente el formulario de copia del curso: «tiza copia» responderá "
    "COPIA_NO_PERMITIDA y la copia hay que hacerla a mano, sin usuarios"
)


def autoprueba(moodle: AulaVirtual, curso_id: int) -> dict:
    """Publica, republica, verifica y borra en el curso de pruebas."""
    pasos: list[informe.Paso] = []
    errores: list[str] = []
    causas: list[BaseException] = []  # solo para --debug en pantalla; nunca al informe
    cmids: list[int] = []
    seccion_temporal: int | None = None  # la de la autoprueba, mientras exista
    codigo_actual = "PREPARAR"

    def paso(codigo: str, resultado: str, detalle: str | None = None) -> None:
        pasos.append(informe.Paso(codigo, resultado, detalle))

    try:
        secciones = moodle.estructura(curso_id)
        if not secciones:
            raise ErrorPublicacion("ESTRUCTURA_VACIA")
        paso("ESTRUCTURA", "ok", f"{len(secciones)} secciones")
        if not aula_dibuja_formulas(moodle, curso_id):
            paso("FORMULAS_NO_DIBUJADAS", "ok", "el aula no carga el motor de fórmulas")
        if not aula_deja_copiar(moodle, curso_id):
            paso("COPIA_A_MANO", "ok", DETALLE_COPIA_A_MANO)
        seccion = secciones.secciones[0].numero
        with tempfile.TemporaryDirectory(prefix="tiza-autoprueba-") as temporal:
            documentos = _ejemplos(Path(temporal), seccion)
            for doc in documentos:
                codigo_actual = f"PUBLICAR_{doc.tipo.upper()}"
                resultado = publicar_documento(moodle, curso_id, secciones, doc, visible=False)
                assert resultado.cmid is not None  # acaba de crearla o actualizarla
                cmids.append(resultado.cmid)
                paso(codigo_actual, "ok", f"cmid {resultado.cmid}")
            codigo_actual = "VERIFICAR_FECHAS"
            tarea = documentos[1]
            leidas = moodle.leer_modulo(cmids[1]).get("fechas") or {}
            if any(leidas.get(campo) != valor for campo, valor in fechas_esperadas(tarea).items()):
                raise ErrorPublicacion("FECHAS_NO_APLICADAS")
            paso("VERIFICAR_FECHAS", "ok", None)
            codigo_actual = "REPUBLICAR_PAGINA"
            secciones = moodle.estructura(curso_id)
            repetido = publicar_documento(moodle, curso_id, secciones, documentos[0], visible=None)
            if cmids and repetido.cmid != cmids[0]:
                raise ErrorPublicacion("REPUBLICAR_CMID_DISTINTO")
            if repetido.oculto is not True:
                raise ErrorPublicacion("VISIBILIDAD_NO_CONSERVADA")
            paso("REPUBLICAR_PAGINA", "ok", f"cmid {repetido.cmid}")
            codigo_actual = "REPUBLICAR_CUESTIONARIO"
            secciones = moodle.estructura(curso_id)
            repetido = publicar_documento(moodle, curso_id, secciones, documentos[2], visible=None)
            if repetido.cmid != cmids[2]:
                raise ErrorPublicacion("REPUBLICAR_CMID_DISTINTO")
            if repetido.oculto is not True:
                raise ErrorPublicacion("VISIBILIDAD_NO_CONSERVADA")
            paso("REPUBLICAR_CUESTIONARIO", "ok", f"cmid {repetido.cmid}")
            codigo_actual = "REPUBLICAR_ETIQUETA"
            secciones = moodle.estructura(curso_id)
            repetido = publicar_documento(moodle, curso_id, secciones, documentos[3], visible=None)
            if repetido.cmid != cmids[3]:
                raise ErrorPublicacion("REPUBLICAR_CMID_DISTINTO")
            if repetido.oculto is not True:
                raise ErrorPublicacion("VISIBILIDAD_NO_CONSERVADA")
            paso("REPUBLICAR_ETIQUETA", "ok", f"cmid {repetido.cmid}")
            codigo_actual = "REPUBLICAR_H5P"
            secciones = moodle.estructura(curso_id)
            repetido = publicar_documento(moodle, curso_id, secciones, documentos[4], visible=None)
            if repetido.cmid != cmids[4]:
                raise ErrorPublicacion("REPUBLICAR_CMID_DISTINTO")
            if repetido.oculto is not True:
                raise ErrorPublicacion("VISIBILIDAD_NO_CONSERVADA")
            paso("REPUBLICAR_H5P", "ok", f"cmid {repetido.cmid}")
            codigo_actual = "VERIFICAR_CATEGORIA"
            cmid_quiz = cmids[2]
            categoria = moodle.categoria_cuestionario(cmid_quiz)
            contexto = moodle.leer_modulo(cmid_quiz).get("contexto")
            if not categoria.endswith(f",{contexto}"):
                raise ErrorPublicacion("VERIFICACION_PREGUNTAS")
            en_banco = moodle.preguntas_en_categoria(cmid_quiz, categoria)
            esperadas = documentos[2].cuestionario
            assert esperadas is not None
            if len(en_banco) != len(esperadas.preguntas):
                raise ErrorPublicacion("VERIFICACION_PREGUNTAS")
            paso("VERIFICAR_CATEGORIA", "ok", f"{len(en_banco)} preguntas")
            codigo_actual = "CREAR_SECCION"
            nombre_seccion = "Autoprueba tiza (seccion)"
            existente = secciones.buscar_seccion(nombre_seccion)
            if existente is not None:
                seccion_id = existente.id
            else:
                seccion_id = moodle.crear_seccion(curso_id, nombre_seccion)
            seccion_temporal = seccion_id
            secciones = moodle.estructura(curso_id)
            if secciones.buscar_seccion(nombre_seccion) is None:
                raise ErrorPublicacion("SECCION_NO_CREADA")
            paso("CREAR_SECCION", "ok", None)
            codigo_actual = "ORDENAR"
            # La tarea y la página, que acaban de crearse en este orden, se intercambian.
            pagina, tarea = documentos[0], documentos[1]
            ficheros = ordenar_documentos(moodle, curso_id, secciones, [tarea, pagina])
            if {fichero.accion for fichero in ficheros} != {"ordenada"}:
                raise ErrorPublicacion("ORDEN_NO_APLICADO")
            paso("ORDENAR", "ok", None)
            codigo_actual = "MOVER_SECCION"
            # La página pasa a la sección temporal (mismo cmid, sin duplicar) y vuelve: borrar
            # la sección temporal se la llevaría y la limpieza final fallaría.
            secciones = moodle.estructura(curso_id)
            movida = publicar_documento(
                moodle,
                curso_id,
                secciones,
                dataclasses.replace(pagina, seccion=nombre_seccion, hash_cargado=""),
                visible=None,
            )
            if movida.accion != "movida" or movida.cmid != cmids[0]:
                raise ErrorPublicacion("ERROR_MOVER")
            secciones = moodle.estructura(curso_id)
            devuelta = publicar_documento(moodle, curso_id, secciones, pagina, visible=None)
            if devuelta.accion != "movida" or devuelta.cmid != cmids[0]:
                raise ErrorPublicacion("ERROR_MOVER")
            paso("MOVER_SECCION", "ok", f"cmid {devuelta.cmid}")
            codigo_actual = "BORRAR_SECCION"
            moodle.borrar_seccion(curso_id, seccion_id)
            seccion_temporal = None
            paso("BORRAR_SECCION", "ok", None)
    except ErrorPublicacion as exc:
        errores.append(exc.codigo)
        causas.append(exc)
        paso(codigo_actual, "fallo", exc.codigo)
        if exc.cmid is not None and exc.cmid not in cmids:
            cmids.append(exc.cmid)
    finally:
        limpieza_ok = True
        for cmid in cmids:
            try:
                moodle.borrar(curso_id, cmid)
            except ErrorPublicacion as exc:
                limpieza_ok = False
                errores.append(exc.codigo)
                causas.append(exc)
        if seccion_temporal is not None:
            # Tras un fallo a medias, que la sección temporal no se quede en el curso de pruebas.
            try:
                moodle.borrar_seccion(curso_id, seccion_temporal)
            except ErrorPublicacion as exc:
                limpieza_ok = False
                errores.append(exc.codigo)
                causas.append(exc)
        paso("LIMPIAR", "ok" if limpieza_ok else "fallo")
    return {
        "resultado": "error" if errores else "ok",
        "pasos": pasos,
        "errores": errores,
        "causas": causas,
    }


def _ejemplos(carpeta: Path, seccion: int) -> list[Documento]:
    from .contenido import cargar

    (carpeta / "img").mkdir(parents=True, exist_ok=True)
    (carpeta / "img" / "punto.png").write_bytes(_PNG_1X1)
    pagina = carpeta / "pagina.md"
    pagina.write_text(
        "---\n"
        "tipo: pagina\n"
        "nombre: Autoprueba tiza (pagina)\n"
        f"seccion: {seccion}\n"
        "---\n\n"
        "![punto](img/punto.png)\n\n"
        "## Autoprueba\n\nContenido temporal de la autoprueba.\n",
        encoding="utf-8",
    )
    tarea = carpeta / "tarea.md"
    tarea.write_text(
        "---\n"
        "tipo: tarea\n"
        "nombre: Autoprueba tiza (tarea)\n"
        f"seccion: {seccion}\n"
        # Sin hora, como las escribe un docente (entrega y límite a las 23:59), y
        # antes de 2050: los desplegables de año de Moodle no llegan más allá.
        "apertura: 2049-01-01\n"
        "entrega: 2049-01-02\n"
        "limite: 2049-01-03\n"
        "---\n\n"
        "Tarea temporal de la autoprueba.\n\n"
        "![punto](img/punto.png)\n",
        encoding="utf-8",
    )
    cuestionario = carpeta / "cuestionario.md"
    cuestionario.write_text(
        "---\n"
        "tipo: cuestionario\n"
        "nombre: Autoprueba tiza (cuestionario)\n"
        f"seccion: {seccion}\n"
        "preguntas:\n"
        "  - tipo: opcion_multiple\n"
        "    enunciado: ¿Cuánto es **2 + 2**?\n"
        "    opciones:\n"
        '      - {texto: "4", correcta: true}\n'
        '      - {texto: "5"}\n'
        "  - tipo: verdadero_falso\n"
        "    enunciado: El agua hierve a 100 °C a nivel del mar.\n"
        "    respuesta: verdadero\n"
        # Un emparejamiento con una imagen dentro de una pregunta: la autoprueba comprueba que
        # el aula las importa y sirve (un cuestionario de verdad lleva ambas cosas).
        "  - tipo: emparejamiento\n"
        "    enunciado: Une cada elemento con su pareja.\n"
        "    parejas:\n"
        '      - {pregunta: "![Un punto](img/punto.png)", respuesta: A}\n'
        "      - {pregunta: B, respuesta: C}\n"
        "    distractores: [D]\n"
        "---\n\n"
        "Cuestionario temporal de la autoprueba.\n\n"
        "![punto](img/punto.png)\n",
        encoding="utf-8",
    )
    etiqueta = carpeta / "etiqueta.md"
    etiqueta.write_text(
        "---\n"
        "tipo: etiqueta\n"
        "nombre: Autoprueba tiza (etiqueta)\n"
        f"seccion: {seccion}\n"
        "---\n\n"
        "Texto temporal de la autoprueba.\n\n"
        "![punto](img/punto.png)\n",
        encoding="utf-8",
    )
    h5p = carpeta / "h5p.md"
    h5p.write_text(
        "---\n"
        "tipo: h5p\n"
        "nombre: Autoprueba tiza (h5p)\n"
        f"seccion: {seccion}\n"
        "actividad:\n"
        "  tipo: rellenar_huecos\n"
        "  textos:\n"
        '    - "El agua hierve a [[100]] grados."\n'
        "---\n\n"
        "Actividad temporal de la autoprueba.\n\n"
        "![punto](img/punto.png)\n",
        encoding="utf-8",
    )
    return [cargar(pagina), cargar(tarea), cargar(cuestionario), cargar(etiqueta), cargar(h5p)]
