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
import re
import shutil
import tempfile
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, NamedTuple, Protocol
from urllib.parse import urljoin, urlsplit

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

from . import __version__, informe, tipos
from .config import AdaptadorAula, DestinoNoPermitido, coincide_dominio
from .contenido import Documento, Recurso, hash_documento, html_para_moodle
from .estado import buscar_seccion, nombre_de_seccion
from .tipos.cuestionario import CAMPOS_FECHA as CAMPOS_FECHA_CUESTIONARIO
from .tipos.tarea import CAMPOS_FECHA as CAMPOS_FECHA_TAREA

__all__ = [
    "AulaVirtual",
    "ErrorPublicacion",
    "Moodle",
    "autenticar",
    "asegurar_secciones",
    "autoprueba",
    "aplicar_itinerario",
    "fechas_esperadas",
    "es_disponibilidad_de_tiza",
    "Movimiento",
    "modulo_de",
    "modulos_de",
    "modulos_fuera",
    "ordenar_documentos",
    "origen_de_movimiento",
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
    "ya_existe",
]

PAUSA_POR_DEFECTO = 0.4
# Esperas antes de repetir una subida que el aula frena por su límite de áreas de borrador
# (unas 50 seguidas; repone ~1 cada 5 s, espiga 6). Si no basta, AULA_PIDE_ESPERA.
ESPERAS_LIMITE_BORRADORES = (5.0, 10.0, 20.0, 40.0)
TIEMPO_ESPERA = 30  # segundos por petición: un aula que no responde no cuelga la sesión

# Fechas del formulario de las actividades con fechas, para releerlas: los campos
# de una tarea y los de un cuestionario (nombres del Moodle en español, arriba).
_CAMPOS_FECHA_LEIDOS = CAMPOS_FECHA_TAREA + CAMPOS_FECHA_CUESTIONARIO

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


class ErrorPublicacion(Exception):
    """Error de publicación con un código estable y sin texto de Moodle."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle
        self.cmid: int | None = None  # módulo ya creado cuando falla la verificación


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

    def estructura(self, curso_id: int) -> list[dict]: ...

    def mis_cursos(self) -> list[dict]: ...

    def contexto(self, curso_id: int) -> int: ...

    def subir(self, curso_id: int, contexto: int, ruta: Path, itemid: int) -> tuple[int, str]: ...

    def crear(self, curso_id: int, seccion_id: int, tipo: str, payload: dict) -> int: ...

    def actualizar(self, cmid: int, payload: dict) -> None: ...

    def leer_modulo(self, cmid: int) -> dict: ...

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

    def estructura(self, curso_id: int) -> list[dict]:
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
        return sorted(salida, key=lambda item: item["numero"])

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
        return {
            "nombre": _campo(formulario, "name") or "",
            "texto": _campo(formulario, "page[text]")
            or _campo(formulario, "introeditor[text]")
            or "",
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


def _tiene_campo(contenedor: Any, nombre: str) -> bool:
    """¿El formulario lleva ese campo? (los nombres pueden repetirse)."""
    return bool(contenedor.find_all(attrs={"name": nombre}))


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


def publicar_documento(
    moodle: AulaVirtual,
    curso_id: int,
    secciones: list[dict],
    doc: Documento,
    *,
    visible: bool | None,
    dependencias: dict[str, int] | None = None,
) -> informe.Fichero:
    """Crea o actualiza un documento y lo verifica releyendo el módulo.

    ``visible=None`` conserva la visibilidad de lo que ya existe; lo nuevo se crea oculto.
    Los recursos se copian una sola vez y se comprueba que siguen siendo los que
    el docente confirmó (``hash_cargado``): sustituirlos después no sirve.
    ``dependencias``: el cmid, en este curso, de cada fichero de ``restricciones.completar``.
    """
    with tempfile.TemporaryDirectory(prefix="tiza-recursos-") as temporal:
        copia = _congelar_recursos(doc, Path(temporal))
        return _publicar_congelado(
            moodle,
            curso_id,
            secciones,
            copia,
            visible=visible,
            original=doc,
            dependencias=dependencias or {},
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
    secciones: list[dict],
    doc: Documento,
    *,
    visible: bool | None,
    original: Documento,
    dependencias: dict[str, int],
) -> informe.Fichero:
    seccion = buscar_seccion(secciones, doc.seccion)
    if seccion is None:
        raise ErrorPublicacion("SECCION_AUSENTE", doc.ruta.name)
    existente = modulo_de(secciones, doc)
    movido = False
    if existente is None:
        # Sin actividad en su sección, la de otra sección es la misma: cambió ``seccion:``.
        fuera = modulos_fuera(secciones, doc)
        if len(fuera) > 1:
            raise ErrorPublicacion("ACTIVIDAD_AMBIGUA", doc.ruta.name)
        if fuera:
            existente, movido = fuera[0][1], True
    # Antes de escribir nada: una restricción ajena o una finalización bloqueada paran todo.
    envio = preparar_itinerario(moodle, doc, existente, dependencias)
    if movido and existente is not None:
        moodle.mover(curso_id, existente["cmid"], seccion["id"], None)

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
        )
    )
    aplicar_itinerario(moodle, doc, cmid, envio)
    return informe.Fichero(
        nombre=original.ruta.name,
        tipo=doc.tipo,
        cmid=cmid,
        accion="movida" if movido else accion,
        oculto=_oculto(visible, info),
        url=url_modulo(moodle.base_url, doc.tipo, cmid),
        seccion=seccion["nombre"],
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
    moodle: AulaVirtual, doc: Documento, existente: dict | None, dependencias: dict[str, int]
) -> EnvioItinerario:
    """Decide qué se enviará y, antes de escribir nada, rechaza lo que no se puede aplicar.

    Lo que el aula ya tiene se examina aquí dentro y no sale: solo se devuelve un código.
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
        actual = moodle.leer_modulo(existente["cmid"]).get("itinerario") or {}
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


def modulos_de(secciones: list[dict], doc: Documento) -> list[dict]:
    """Los módulos de la sección de ``doc`` con su tipo y su nombre (casi siempre uno o ninguno)."""
    try:
        seccion = buscar_seccion(secciones, doc.seccion)
    except (TypeError, ValueError):
        return []
    modulos = seccion.get("modulos") if seccion is not None else None
    if not isinstance(modulos, list):
        return []
    return [
        modulo
        for modulo in modulos
        if isinstance(modulo, dict)
        and modulo.get("tipo") == doc.tipo
        and modulo.get("nombre") == doc.nombre
    ]


def modulo_de(secciones: list[dict], doc: Documento) -> dict | None:
    """El módulo del aula que actualizaría ``doc``: misma sección, tipo y nombre.

    Mismo criterio que usa ``publicar_documento``; ``None`` si no existe (o si
    la estructura no permite comprobarlo).
    """
    encontrados = modulos_de(secciones, doc)
    return encontrados[0] if encontrados else None


def modulos_fuera(secciones: list[dict], doc: Documento) -> list[tuple[dict, dict]]:
    """(sección, módulo) con el tipo y nombre de ``doc`` en las demás secciones del curso.

    Con ``doc`` publicado en otra sección, ahí es donde habría que buscarlo para moverlo.
    """
    try:
        propia = buscar_seccion(secciones, doc.seccion)
    except (TypeError, ValueError):
        propia = None
    salida: list[tuple[dict, dict]] = []
    for seccion in secciones:
        if seccion is propia or not isinstance(seccion.get("modulos"), list):
            continue
        salida += [
            (seccion, modulo)
            for modulo in seccion["modulos"]
            if isinstance(modulo, dict)
            and modulo.get("tipo") == doc.tipo
            and modulo.get("nombre") == doc.nombre
        ]
    return salida


def origen_de_movimiento(secciones: list[dict], doc: Documento) -> str | None:
    """Nombre de la sección de la que se movería ``doc`` al publicarlo, o None si no se mueve.

    Solo se mueve si no existe en su sección y hay exactamente uno en otra; solo lectura.
    """
    if modulos_de(secciones, doc):
        return None
    fuera = modulos_fuera(secciones, doc)
    if len(fuera) != 1:
        return None
    return str(fuera[0][0].get("nombre") or "")


def ya_existe(secciones: list[dict], doc: Documento) -> bool | None:
    """Si al publicar ``doc`` se actualizaría un módulo que ya existe.

    Solo lectura, con el mismo criterio que ``publicar_documento`` (misma
    sección, tipo y nombre). ``None`` si la estructura del aula no permite
    comprobarlo: quien lo muestre debe avisar de que puede existir, sin abortar.
    """
    try:
        seccion = buscar_seccion(secciones, doc.seccion)
    except (TypeError, ValueError):
        return None
    if seccion is None:
        return False
    if not isinstance(seccion.get("modulos"), list):
        return None
    return modulo_de(secciones, doc) is not None


def secciones_que_faltan(secciones: list[dict], documentos: list[Documento]) -> list[str]:
    """Nombres de sección pedidos por los documentos que aún no existen."""
    faltan: list[str] = []
    for doc in documentos:
        if isinstance(doc.seccion, str) and buscar_seccion(secciones, doc.seccion) is None:
            if doc.seccion.casefold() not in {nombre.casefold() for nombre in faltan}:
                faltan.append(doc.seccion)
    return faltan


def asegurar_secciones(
    moodle: AulaVirtual, curso_id: int, secciones: list[dict], documentos: list[Documento]
) -> tuple[list[dict], list[str]]:
    """Crea (ocultas) las secciones por nombre que falten y relee la estructura."""
    creadas = secciones_que_faltan(secciones, documentos)
    if not creadas:
        return secciones, []
    for nombre in creadas:
        moodle.crear_seccion(curso_id, nombre)
    secciones = moodle.estructura(curso_id)
    for nombre in creadas:
        if buscar_seccion(secciones, nombre) is None:
            raise ErrorPublicacion("SECCION_NO_CREADA", nombre)
    return secciones, creadas


def publicar_fechas(moodle: AulaVirtual, secciones: list[dict], doc: Documento) -> informe.Fichero:
    """Cambia solo las fechas de una tarea o un cuestionario que ya está en el aula.

    No toca el contenido, los recursos, las preguntas, los intentos ni la
    visibilidad, así que no pasa por la puerta de pruebas ni sube nada. Si el
    módulo no existe, no envía nada.
    """
    existente = modulo_de(secciones, doc)
    if existente is None:
        raise ErrorPublicacion("MODULO_AUSENTE", doc.ruta.name)
    cmid = existente["cmid"]
    moodle.actualizar(cmid, payload_solo_fechas(doc))
    info = _verificar_fechas(moodle, doc, cmid)
    seccion = buscar_seccion(secciones, doc.seccion) or {}
    return informe.Fichero(
        nombre=doc.ruta.name,
        tipo=doc.tipo,
        cmid=cmid,
        accion="actualizada",
        oculto=_oculto(None, info),
        url=url_modulo(moodle.base_url, doc.tipo, cmid),
        seccion=seccion.get("nombre") or str(doc.seccion),
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


def plan_de_orden(secciones: list[dict], deseados: list[tuple[int, list[int]]]) -> list[Movimiento]:
    """Los movimientos que dejan, en cada sección, los módulos nombrados en el orden pedido.

    Pura. ``deseados``: por sección, su id y los cmids en el orden deseado (todos de esa
    sección, sin repetir). Lo no nombrado no se mueve nunca: los nombrados se reparten los
    huecos que ya ocupaban. Se recorre el orden final de atrás hacia delante y solo se mueve
    el módulo que no está ya justo delante del que le sigue; ya ordenado, devuelve ``[]``.
    """
    movimientos: list[Movimiento] = []
    for seccion_id, cmids in deseados:
        seccion = next(s for s in secciones if s["id"] == seccion_id)
        actual = [modulo["cmid"] for modulo in seccion["modulos"]]
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


def resolver_orden(
    secciones: list[dict], docs: list[Documento]
) -> list[tuple[dict, list[tuple[Documento, dict]]]]:
    """Cada sección con sus documentos en el orden pedido y el módulo del aula de cada uno.

    ``FICHERO_REPETIDO``, ``ACTIVIDAD_AUSENTE`` y ``ACTIVIDAD_AMBIGUA`` se dan antes de mover nada.
    """
    vistos: set[Path] = set()
    cmids: set[int] = set()
    grupos: dict[int, tuple[dict, list[tuple[Documento, dict]]]] = {}
    for doc in docs:
        ruta = doc.ruta.resolve()
        if ruta in vistos:
            raise ErrorPublicacion("FICHERO_REPETIDO", doc.ruta.name)
        vistos.add(ruta)
        encontrados = modulos_de(secciones, doc)
        if not encontrados:
            raise ErrorPublicacion("ACTIVIDAD_AUSENTE", doc.ruta.name)
        modulo = encontrados[0]
        # Dos ficheros que apuntan a la misma actividad: no hay orden entre ellos.
        if len(encontrados) > 1 or modulo["cmid"] in cmids:
            raise ErrorPublicacion("ACTIVIDAD_AMBIGUA", doc.ruta.name)
        cmids.add(modulo["cmid"])
        seccion = buscar_seccion(secciones, doc.seccion)
        assert seccion is not None  # ``modulos_de`` la encontró
        grupos.setdefault(seccion["id"], (seccion, []))[1].append((doc, modulo))
    return list(grupos.values())


def ordenar_documentos(
    moodle: AulaVirtual, curso_id: int, secciones: list[dict], docs: list[Documento]
) -> list[informe.Fichero]:
    """Deja las actividades de ``docs`` en el orden dado dentro de su sección y lo comprueba.

    Sin cambios no llama al aula. Si falla a medias no se deshace nada: mover no destruye y
    repetir converge.
    """
    grupos = resolver_orden(secciones, docs)
    deseados = [(seccion["id"], [modulo["cmid"] for _, modulo in par]) for seccion, par in grupos]
    movimientos = plan_de_orden(secciones, deseados)
    if movimientos:
        esperados = {
            seccion["id"]: orden_final(
                [modulo["cmid"] for modulo in seccion["modulos"]],
                [modulo["cmid"] for _, modulo in par],
            )
            for seccion, par in grupos
        }
        for movimiento in movimientos:
            moodle.mover(curso_id, *movimiento)
        releida = moodle.estructura(curso_id)
        for seccion_id, esperado in esperados.items():
            nueva = next((s for s in releida if s["id"] == seccion_id), None)
            if nueva is None or [m["cmid"] for m in nueva["modulos"]] != esperado:
                raise ErrorPublicacion("ORDEN_NO_APLICADO")
    cambiadas = {movimiento.seccion_id for movimiento in movimientos}
    return [
        informe.Fichero(
            nombre=doc.ruta.name,
            tipo=doc.tipo,
            cmid=modulo["cmid"],
            accion="ordenada" if seccion["id"] in cambiadas else "sin_cambios",
            url=url_modulo(moodle.base_url, doc.tipo, modulo["cmid"]),
            seccion=seccion["nombre"],
            hash=hash_documento(doc),
        )
        for seccion, par in grupos
        for doc, modulo in par
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
        seccion = secciones[0]["numero"]
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
            existente = buscar_seccion(secciones, nombre_seccion)
            if existente is not None:
                seccion_id = existente["id"]
            else:
                seccion_id = moodle.crear_seccion(curso_id, nombre_seccion)
            seccion_temporal = seccion_id
            secciones = moodle.estructura(curso_id)
            if buscar_seccion(secciones, nombre_seccion) is None:
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
