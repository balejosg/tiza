"""Publicación en el aula virtual, siempre desde la terminal del docente.

Este módulo es el único que habla con el aula. Todo lo que devuelve Moodle se
reduce a códigos y valores de nuestro propio esquema: las excepciones de
python-moodle (que pueden incluir fragmentos de ``resp.text``) nunca salen de
aquí convertidas en texto.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import html
import json
import re
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from py_moodle import auth as py_auth
from py_moodle import course as py_course
from py_moodle import draftfile as py_draftfile
from py_moodle import module as py_module
from py_moodle import section as py_section
from py_moodle.auth import LoginError
from py_moodle.course import MoodleCourseError
from py_moodle.draftfile import MoodleDraftFileError
from py_moodle.module import MoodleModuleError
from py_moodle.section import MoodleSectionError
from py_moodle.session import MoodleSessionError

from . import __version__
from .config import AdaptadorAula, DestinoNoPermitido
from .contenido import Documento, Recurso, hash_documento, html_para_moodle
from .cuestionario import preguntas_xml
from .ficheros import asegurar_directorio, escribir_json
from .h5p import LIBRERIAS as H5P_LIBRERIAS
from .h5p import paquete_h5p, reempaquetar

__all__ = [
    "AulaVirtual",
    "ErrorPublicacion",
    "Moodle",
    "autenticar",
    "asegurar_secciones",
    "autoprueba",
    "buscar_seccion",
    "cargar_estructura",
    "cargar_verificados",
    "comprobar_puerta_real",
    "escribir_estructura",
    "fechas_esperadas",
    "guardar_verificado",
    "modulo_de",
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
TIEMPO_ESPERA = 30  # segundos por petición: un aula que no responde no cuelga la sesión

MODULO_MOODLE = {
    "pagina": "page",
    "tarea": "assign",
    "cuestionario": "quiz",
    "etiqueta": "label",
    "h5p": "h5pactivity",
}
TIPO_DOCUMENTO = {
    "page": "pagina",
    "assign": "tarea",
    "quiz": "cuestionario",
    "label": "etiqueta",
    "h5pactivity": "h5p",
}

# Fechas del formulario de una tarea. En el Moodle en español: «Permitir entregas
# desde», «Fecha de entrega», «Fecha límite» (después ya no se admiten entregas)
# y «Recordarme calificar en».
CAMPOS_FECHA_TAREA = ("allowsubmissionsfromdate", "duedate", "cutoffdate", "gradingduedate")
# Fechas del formulario de un cuestionario: «Abrir el cuestionario» y «Cerrar el
# cuestionario».
CAMPOS_FECHA_CUESTIONARIO = ("timeopen", "timeclose")

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


class ErrorPublicacion(Exception):
    """Error de publicación con un código estable y sin texto de Moodle."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle
        self.cmid: int | None = None  # módulo ya creado cuando falla la verificación


# Misma clase de caracteres que terminal.texto_seguro, contenido._CONTROL e
# informe._TEXTO_PROHIBIDO (sin < y >); mantén las cuatro sincronizadas.
_NO_IMPRIMIBLE = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def nombre_de_seccion(texto: str) -> str:
    """Nombre de sección apto para el esquema cerrado: sin < > ni controles."""
    limpio = _NO_IMPRIMIBLE.sub(" ", texto).replace("<", "‹").replace(">", "›")
    return " ".join(limpio.split())[:255]


# --------------------------------------------------------------------------- #
# Adaptador del aula
# --------------------------------------------------------------------------- #


class AulaVirtual(Protocol):
    """Lo que la publicación necesita del aula.

    Lo cumplen ``Moodle`` y el doble de los tests (``tests/dobles.py``): si
    cambias un método aquí, cambia los dos.
    """

    base_url: str

    def estructura(self, curso_id: int) -> list[dict]: ...

    def mis_cursos(self) -> list[dict]: ...

    def contexto(self, curso_id: int) -> int: ...

    def subir(self, curso_id: int, contexto: int, ruta: Path, itemid: int) -> tuple[int, str]: ...

    def crear(self, curso_id: int, seccion_id: int, tipo: str, payload: dict) -> int: ...

    def actualizar(self, cmid: int, payload: dict) -> None: ...

    def leer_modulo(self, cmid: int) -> dict: ...

    def comprobar_pluginfile(self, url: str) -> bool: ...

    def borrar(self, curso_id: int, cmid: int) -> None: ...

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
            if _bloqueo_de_destino(exc):
                raise ErrorPublicacion("DESTINO_NO_PERMITIDO") from exc
            if not self.sesion_viva():
                raise ErrorPublicacion("SESION_CADUCADA") from exc
            raise ErrorPublicacion(codigo) from exc

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
                        "tipo": TIPO_DOCUMENTO.get(modname, modname),
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
        self._esperar()
        return self._reducir(
            "ERROR_SUBIDA",
            py_draftfile.upload_file_to_draft_area,
            self.sesion,
            self.base_url,
            self.sesskey,
            curso_id,
            contexto,
            str(ruta),
            itemid=itemid,
        )

    def crear(self, curso_id: int, seccion_id: int, tipo: str, payload: dict) -> int:
        nombre_modulo = MODULO_MOODLE.get(tipo)
        if nombre_modulo is None:
            raise ErrorPublicacion("TIPO_DESCONOCIDO")
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
            "fechas": {
                campo: _fecha_leida(formulario, campo)
                for campo in CAMPOS_FECHA_TAREA + CAMPOS_FECHA_CUESTIONARIO
            },
        }

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
    sesion, base_url: str, sesskey: str, curso_id: int, accion: str, ids: list[int]
) -> None:
    """Acción de edición del curso (la misma llamada AJAX que usa su página)."""
    url = f"{base_url}/lib/ajax/service.php?sesskey={sesskey}&info=core_courseformat_update_course"
    payload = [
        {
            "index": 0,
            "methodname": "core_courseformat_update_course",
            "args": {
                "action": accion,
                "courseid": str(curso_id),
                "ids": [str(item) for item in ids],
            },
        }
    ]
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


# --------------------------------------------------------------------------- #
# Payloads de módulo
# --------------------------------------------------------------------------- #


def _campo_visible(visible: bool | None) -> dict:
    """Sin valor, el formulario conserva la visibilidad que ya tenga el módulo."""
    return {} if visible is None else {"visible": "1" if visible else "0"}


def payload_pagina(doc: Documento, html: str, itemid: int, visible: bool | None) -> dict:
    payload = {
        "_qf__mod_page_mod_form": "1",
        "name": doc.nombre,
        "page[text]": html,
        "page[format]": "1",
        "page[itemid]": str(itemid),
        "submitbutton": "Save and return to course",
    }
    payload.update(_campo_visible(visible))
    return payload


def payload_etiqueta(doc: Documento, html: str, itemid: int, visible: bool | None) -> dict:
    payload = {
        "_qf__mod_label_mod_form": "1",
        "name": doc.nombre,
        "introeditor[text]": html,
        "introeditor[format]": "1",
        "introeditor[itemid]": str(itemid),
        "submitbutton2": "Save and return to course",
    }
    payload.update(_campo_visible(visible))
    return payload


def payload_tarea(doc: Documento, html: str, itemid: int, visible: bool | None) -> dict:
    """Formulario de una tarea."""
    payload: dict[str, Any] = {
        "_qf__mod_assign_mod_form": "1",
        "name": doc.nombre,
        "introeditor[text]": html,
        "introeditor[format]": "1",
        "introeditor[itemid]": str(itemid),
        "introattachments": str(itemid),
        "submitbutton": "Save and display",
    }
    payload.update(_fechas_tarea(doc))
    payload.update(_campo_visible(visible))
    return payload


def payload_cuestionario(doc: Documento, html: str, itemid: int, visible: bool | None) -> dict:
    cuestionario = doc.cuestionario
    assert cuestionario is not None
    payload: dict[str, Any] = {
        "_qf__mod_quiz_mod_form": "1",
        "name": doc.nombre,
        "introeditor[text]": html,
        "introeditor[format]": "1",
        "introeditor[itemid]": str(itemid),
        "submitbutton2": "Save and return to course",
    }
    payload.update(_fechas_cuestionario(doc))
    if cuestionario.tiempo_limite is not None:
        payload["timelimit[enabled]"] = "1"
        payload["timelimit[number]"] = str(cuestionario.tiempo_limite)
        payload["timelimit[timeunit]"] = "60"  # minutos
    else:
        payload["timelimit[enabled]"] = "0"
    # En Moodle, 0 intentos es «ilimitados».
    payload["attempts"] = "0" if cuestionario.intentos == 0 else str(cuestionario.intentos)
    payload["shuffleanswers"] = "1" if cuestionario.mezclar_respuestas else "0"
    payload.update(_campo_visible(visible))
    return payload


def payload_h5p(
    doc: Documento, html: str, itemid: int, itemid_paquete: int, visible: bool | None
) -> dict:
    """Formulario de una actividad H5P.

    ``itemid`` es el borrador de la descripción y ``itemid_paquete`` el del
    fichero .h5p (van separados para que no se mezclen). Las tarjetas no
    califican: seguimiento desactivado y sin nota.
    """
    actividad = doc.h5p
    califica = doc.paquete is not None or (actividad is not None and actividad.tipo != "tarjetas")
    payload: dict[str, Any] = {
        "_qf__mod_h5pactivity_mod_form": "1",
        "name": doc.nombre,
        "introeditor[text]": html,
        "introeditor[format]": "1",
        "introeditor[itemid]": str(itemid),
        "packagefile": str(itemid_paquete),
        "displayopt[export]": "0",  # sin descarga
        "displayopt[embed]": "0",  # sin código de incrustar
        "displayopt[copyright]": "0",
        "submitbutton": "Guardar cambios y regresar al curso",
    }
    if califica:
        payload["grade[modgrade_type]"] = "point"
        payload["grade[modgrade_point]"] = str(actividad.calificacion if actividad else 10)
        payload["enabletracking"] = "1"
        payload["grademethod"] = "1"  # nota más alta
        payload["reviewmode"] = "1"  # revisión al completar
    else:
        payload["grade[modgrade_type]"] = "none"
        payload["enabletracking"] = "0"
    payload.update(_campo_visible(visible))
    return payload


def _fechas_tarea(doc: Documento) -> dict:
    """Apertura, entrega y, si lo hay, el límite de entregas de una tarea."""
    payload: dict[str, Any] = {}
    if doc.fechas is not None:
        payload.update(_fechas_payload("allowsubmissionsfromdate", doc.fechas.apertura))
        payload.update(_fechas_payload("duedate", doc.fechas.entrega))
        # «limite» es la fecha límite de Moodle: después ya no se admiten entregas.
        if doc.fechas.limite is not None:
            payload.update(_fechas_payload("cutoffdate", doc.fechas.limite))
        else:
            payload["cutoffdate[enabled]"] = "0"
        payload["gradingduedate[enabled]"] = "0"
    return payload


def _fechas_cuestionario(doc: Documento) -> dict:
    """Apertura y cierre de un cuestionario; sin fecha, se desactiva en el aula."""
    cuestionario = doc.cuestionario
    assert cuestionario is not None
    payload: dict[str, Any] = {}
    if cuestionario.apertura is not None:
        payload.update(_fechas_payload("timeopen", cuestionario.apertura))
    else:
        payload["timeopen[enabled]"] = "0"
    if cuestionario.cierre is not None:
        payload.update(_fechas_payload("timeclose", cuestionario.cierre))
    else:
        payload["timeclose[enabled]"] = "0"
    return payload


def payload_solo_fechas(doc: Documento) -> dict:
    """Formulario mínimo para cambiar solo las fechas de una actividad ya publicada.

    No lleva nombre, texto, preguntas, intentos ni visibilidad: python-moodle fusiona
    el formulario con lo que ya tiene el módulo, así que esos campos no cambian.
    """
    if doc.tipo == "tarea":
        return {
            "_qf__mod_assign_mod_form": "1",
            "submitbutton": "Save and display",
            **_fechas_tarea(doc),
        }
    if doc.tipo == "cuestionario":
        return {
            "_qf__mod_quiz_mod_form": "1",
            "submitbutton2": "Save and return to course",
            **_fechas_cuestionario(doc),
        }
    raise ErrorPublicacion("SOLO_FECHAS_NO_APLICA", doc.ruta.name)


def _fechas_payload(campo: str, momento: datetime) -> dict:
    return {
        f"{campo}[enabled]": "1",
        f"{campo}[day]": str(momento.day),
        f"{campo}[month]": str(momento.month),
        f"{campo}[year]": str(momento.year),
        f"{campo}[hour]": str(momento.hour),
        f"{campo}[minute]": str(momento.minute),
    }


def fechas_esperadas(doc: Documento) -> dict[str, tuple[int, int, int, int, int] | None]:
    """Lo que debe mostrar el formulario de la actividad tras publicarla."""
    if doc.tipo == "cuestionario":
        cuestionario = doc.cuestionario
        esperadas: dict[str, tuple[int, int, int, int, int] | None] = {
            "timeopen": None,
            "timeclose": None,
        }
        if cuestionario is not None:
            if cuestionario.apertura is not None:
                esperadas["timeopen"] = _partes(cuestionario.apertura)
            if cuestionario.cierre is not None:
                esperadas["timeclose"] = _partes(cuestionario.cierre)
        return esperadas
    esperadas = dict.fromkeys(CAMPOS_FECHA_TAREA)
    if doc.fechas is not None:
        esperadas["allowsubmissionsfromdate"] = _partes(doc.fechas.apertura)
        esperadas["duedate"] = _partes(doc.fechas.entrega)
        if doc.fechas.limite is not None:
            esperadas["cutoffdate"] = _partes(doc.fechas.limite)
    return esperadas


def _partes(momento: datetime) -> tuple[int, int, int, int, int]:
    return (momento.year, momento.month, momento.day, momento.hour, momento.minute)


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
) -> dict:
    """Crea o actualiza un documento y lo verifica releyendo el módulo.

    ``visible=None`` conserva la visibilidad de lo que ya existe; lo nuevo se crea oculto.
    Los recursos se copian una sola vez y se comprueba que siguen siendo los que
    el docente confirmó (``hash_cargado``): sustituirlos después no sirve.
    """
    with tempfile.TemporaryDirectory(prefix="tiza-recursos-") as temporal:
        copia = _congelar_recursos(doc, Path(temporal))
        return _publicar_congelado(
            moodle, curso_id, secciones, copia, visible=visible, original=doc
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
) -> dict:
    seccion = buscar_seccion(secciones, doc.seccion)
    if seccion is None:
        raise ErrorPublicacion("SECCION_AUSENTE", doc.ruta.name)
    existente = modulo_de(secciones, doc)

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
    pasos: list[dict] = []
    if doc.tipo == "cuestionario":
        cmid, accion, info = _publicar_cuestionario(
            moodle, curso_id, seccion, doc, html, itemid, visible, existente
        )
    elif doc.tipo == "h5p":
        cmid, accion, info = _publicar_h5p(
            moodle, curso_id, seccion, doc, html, itemid, visible, existente
        )
    else:
        if doc.tipo == "tarea":
            payload = payload_tarea(doc, html, itemid, visible)
        else:
            payload = {
                "pagina": payload_pagina,
                "etiqueta": payload_etiqueta,
            }[doc.tipo](doc, html, itemid, visible)
        if existente is not None:
            cmid = existente["cmid"]
            moodle.actualizar(cmid, payload)
            accion = "actualizada"
        else:
            cmid = moodle.crear(curso_id, seccion["id"], doc.tipo, payload)
            accion = "creada"
        try:
            info = _verificar(moodle, doc, cmid)
        except ErrorPublicacion as exc:
            exc.cmid = cmid
            raise
    return {
        "nombre": original.ruta.name,
        "tipo": doc.tipo,
        "cmid": cmid,
        "accion": accion,
        "oculto": _oculto(visible, info),
        "url": url_modulo(moodle.base_url, doc.tipo, cmid),
        "seccion": seccion["nombre"],
        "hash": hash_documento(doc),
        "verificado": True,
        "pasos": pasos,
    }


# --------------------------------------------------------------------------- #
# Cuestionarios: preguntas, republicación y limpieza
# --------------------------------------------------------------------------- #


def _publicar_cuestionario(
    moodle: AulaVirtual,
    curso_id: int,
    seccion: dict,
    doc: Documento,
    html: str,
    itemid: int,
    visible: bool | None,
    existente: dict | None,
) -> tuple[int, str, dict]:
    """Crea o republica un cuestionario y devuelve (cmid, acción, formulario).

    Lo nuevo se crea con sus preguntas y, si algo falla después de crear el
    módulo, se borra entero (se lleva sus preguntas). En uno existente se añade
    antes de quitar para que un fallo no lo deje vacío.
    """
    cuestionario = doc.cuestionario
    assert cuestionario is not None
    cuantas = len(cuestionario.preguntas)
    payload = payload_cuestionario(doc, html, itemid, visible)
    xml = preguntas_xml(doc)
    nuevas: list[int] = []

    if existente is None:
        cmid = moodle.crear(curso_id, seccion["id"], doc.tipo, payload)
        try:
            categoria = moodle.categoria_cuestionario(cmid)
            nuevas = _importar_preguntas(moodle, curso_id, cmid, categoria, xml, cuantas)
            moodle.anadir_preguntas(cmid, nuevas)
        except ErrorPublicacion as exc:
            _borrar_modulo_si_falla(moodle, curso_id, cmid, exc)
            raise
        accion = "creada"
    else:
        cmid = existente["cmid"]
        if moodle.tiene_intentos(cmid):
            raise ErrorPublicacion("CUESTIONARIO_CON_INTENTOS", DETALLE_INTENTOS)
        categoria = moodle.categoria_cuestionario(cmid)
        # Lo que hay ahora: sus huecos y las preguntas de su banco.
        viejos = moodle.huecos(cmid)
        viejas = moodle.preguntas_en_categoria(cmid, categoria)
        try:
            nuevas = _importar_preguntas(moodle, curso_id, cmid, categoria, xml, cuantas)
        except ErrorPublicacion:
            # La republicación no ha cambiado nada: fuera las nuevas a medias.
            _borrar_nuevas(moodle, cmid, nuevas)
            raise
        try:
            moodle.anadir_preguntas(cmid, nuevas)
        except ErrorPublicacion:
            _borrar_nuevas(moodle, cmid, nuevas)
            raise
        quizid = moodle.leer_modulo(cmid).get("instance")
        if not isinstance(quizid, int):
            raise ErrorPublicacion("ERROR_QUITAR_PREGUNTAS")
        for hueco, _pregunta in viejos:
            moodle.quitar_hueco(curso_id, quizid, hueco)
        moodle.borrar_preguntas(cmid, sorted(viejas))
        moodle.actualizar(cmid, payload)
        accion = "actualizada"

    try:
        info = _verificar(moodle, doc, cmid, preguntas=nuevas)
    except ErrorPublicacion as exc:
        if existente is None:
            _borrar_modulo_si_falla(moodle, curso_id, cmid, exc)
        else:
            exc.cmid = cmid
        raise
    return cmid, accion, info


def _importar_preguntas(
    moodle: AulaVirtual, curso_id: int, cmid: int, categoria: str, xml: bytes, cuantas: int
) -> list[int]:
    """Importa el XML y comprueba que llegaron todas las preguntas."""
    nuevas = moodle.importar_preguntas(curso_id, cmid, categoria, xml)
    if len(nuevas) != cuantas:
        raise ErrorPublicacion(
            "ERROR_IMPORTACION",
            f"se esperaban {cuantas} preguntas y el aula importó {len(nuevas)}",
        )
    return nuevas


def _borrar_nuevas(moodle: AulaVirtual, cmid: int, ids: list[int]) -> None:
    if not ids:
        return
    try:
        moodle.borrar_preguntas(cmid, ids)
    except ErrorPublicacion:
        pass  # el cuestionario sigue como estaba; las nuevas se borrarán al republicar


def _borrar_modulo_si_falla(
    moodle: AulaVirtual, curso_id: int, cmid: int, exc: ErrorPublicacion
) -> None:
    """Deshace un módulo nuevo a medias; si no puede, deja el cmid al llamador."""
    try:
        moodle.borrar(curso_id, cmid)
    except ErrorPublicacion:
        exc.cmid = cmid


# --------------------------------------------------------------------------- #
# Actividades H5P: paquete, creación y verificación
# --------------------------------------------------------------------------- #


def _paquete_de_h5p(doc: Documento) -> tuple[str, bytes, str]:
    """(librería principal, bytes del .h5p, nombre base) según el documento."""
    if doc.h5p is not None:
        machine_name = H5P_LIBRERIAS[doc.h5p.tipo][0]
        return machine_name, paquete_h5p(doc), doc.ruta.stem
    assert doc.paquete is not None
    return (
        doc.paquete.machine_name,
        reempaquetar(doc.paquete.ruta),
        Path(doc.paquete.nombre).stem,
    )


def _publicar_h5p(
    moodle: AulaVirtual,
    curso_id: int,
    seccion: dict,
    doc: Documento,
    html: str,
    itemid: int,
    visible: bool | None,
    existente: dict | None,
) -> tuple[int, str, dict]:
    """Crea o actualiza la actividad H5P y devuelve (cmid, acción, formulario)."""
    if existente is not None and moodle.h5p_tiene_intentos(existente["cmid"]):
        raise ErrorPublicacion("H5P_CON_INTENTOS", DETALLE_H5P_INTENTOS)
    machine_name, paquete, nombre_base = _paquete_de_h5p(doc)
    itemid_paquete = itemid + 1
    with tempfile.TemporaryDirectory(prefix="tiza-h5p-") as temporal:
        ruta = Path(temporal) / f"{nombre_base}.h5p"
        ruta.write_bytes(paquete)
        _itemid, nombre_final = moodle.subir(
            curso_id, moodle.contexto(curso_id), ruta, itemid_paquete
        )
    payload = payload_h5p(doc, html, itemid, itemid_paquete, visible)

    if existente is not None:
        cmid = existente["cmid"]
        moodle.actualizar(cmid, payload)
        accion = "actualizada"
    else:
        cmid = moodle.crear(curso_id, seccion["id"], doc.tipo, payload)
        accion = "creada"

    try:
        info = _verificar(moodle, doc, cmid, paquete=nombre_final)
        if not moodle.comprobar_h5p(cmid):
            if moodle.libreria_h5p_ausente(cmid, machine_name):
                raise ErrorPublicacion(
                    "H5P_LIBRERIA_AUSENTE", f"el aula no tiene la librería {machine_name}"
                )
            raise ErrorPublicacion(
                "H5P_NO_DESPLEGADO", "la actividad se creó, pero H5P no llegó a arrancar"
            )
    except ErrorPublicacion as exc:
        if existente is None:
            _borrar_modulo_si_falla(moodle, curso_id, cmid, exc)
        else:
            exc.cmid = cmid
        raise
    return cmid, accion, info


def buscar_seccion(secciones: list[dict], clave: int | str) -> dict | None:
    """Sección por número (entero) o por nombre (texto, sin distinguir mayúsculas)."""
    for seccion in secciones:
        if not isinstance(seccion, dict):
            continue
        if isinstance(clave, int):
            if seccion.get("numero") == clave:
                return seccion
        # El nombre ya se saneó al construir la estructura (nombre_de_seccion);
        # aquí se aplica la misma normalización para que la comparación coincida.
        elif (
            nombre_de_seccion(seccion.get("nombre") or "").casefold()
            == nombre_de_seccion(clave).casefold()
        ):
            return seccion
    return None


def modulo_de(secciones: list[dict], doc: Documento) -> dict | None:
    """El módulo del aula que actualizaría ``doc``: misma sección, tipo y nombre.

    Mismo criterio que usa ``publicar_documento``; ``None`` si no existe (o si
    la estructura no permite comprobarlo).
    """
    try:
        seccion = buscar_seccion(secciones, doc.seccion)
    except (TypeError, ValueError):
        return None
    if seccion is None:
        return None
    modulos = seccion.get("modulos")
    if not isinstance(modulos, list):
        return None
    for modulo in modulos:
        if isinstance(modulo, dict) and modulo.get("tipo") == doc.tipo:
            if modulo.get("nombre") == doc.nombre:
                return modulo
    return None


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


def _verificar(
    moodle: AulaVirtual,
    doc: Documento,
    cmid: int,
    preguntas: list[int] | None = None,
    paquete: str | None = None,
) -> dict:
    info = moodle.leer_modulo(cmid)
    if (info.get("nombre") or "").strip() != doc.nombre:
        raise ErrorPublicacion("VERIFICACION_NOMBRE", doc.ruta.name)
    leidas = info.get("fechas") or {}
    if any(leidas.get(campo) != valor for campo, valor in fechas_esperadas(doc).items()):
        raise ErrorPublicacion("FECHAS_NO_APLICADAS", doc.ruta.name)
    texto = info.get("texto") or ""
    for recurso in doc.recursos:
        if recurso.nombre not in texto:
            raise ErrorPublicacion("VERIFICACION_TEXTO", doc.ruta.name)
        urls = urls_pluginfile(
            moodle.base_url, info.get("contexto"), doc.tipo, info.get("instance"), recurso.nombre
        )
        if not any(moodle.comprobar_pluginfile(url) for url in urls):
            raise ErrorPublicacion("VERIFICACION_FICHERO", doc.ruta.name)
    if paquete is not None:
        urls = urls_paquete_h5p(
            moodle.base_url, info.get("contexto"), info.get("instance"), paquete
        )
        if not any(moodle.comprobar_pluginfile(url) for url in urls):
            raise ErrorPublicacion("VERIFICACION_PAQUETE", doc.ruta.name)
    if preguntas is not None:
        en_huecos = [identificador for _hueco, identificador in moodle.huecos(cmid)]
        if en_huecos != list(preguntas):
            raise ErrorPublicacion("VERIFICACION_PREGUNTAS", doc.ruta.name)
    return info


def publicar_fechas(moodle: AulaVirtual, secciones: list[dict], doc: Documento) -> dict:
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
    return {
        "nombre": doc.ruta.name,
        "tipo": doc.tipo,
        "cmid": cmid,
        "accion": "actualizada",
        "oculto": _oculto(None, info),
        "url": url_modulo(moodle.base_url, doc.tipo, cmid),
        "seccion": seccion.get("nombre") or str(doc.seccion),
        # El contenido no cambia: el hash es el que el docente ya vio al confirmar.
        "hash": doc.hash_cargado or None,
        "verificado": True,
        "pasos": [],
    }


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
    raiz = f"{base_url}/pluginfile.php/{contexto}/mod_{MODULO_MOODLE[tipo]}"
    if tipo == "pagina":
        return [f"{raiz}/content/{instance}/{nombre}"]
    if tipo == "cuestionario":
        # La descripción de un cuestionario va en mod_quiz/intro (sin itemid).
        return [f"{raiz}/intro/{nombre}", f"{raiz}/intro/0/{nombre}"]
    if tipo == "etiqueta":
        # El texto de una etiqueta va en mod_label/intro (sin itemid).
        return [f"{raiz}/intro/{nombre}"]
    if tipo == "h5p":
        # La descripción va en mod_h5pactivity/intro; el paquete va aparte.
        return [f"{raiz}/intro/{nombre}", f"{raiz}/intro/0/{nombre}"]
    # En una tarea, intro no lleva itemid e introattachment usa el 0.
    return [f"{raiz}/intro/{nombre}", f"{raiz}/introattachment/0/{nombre}"]


def urls_paquete_h5p(base_url: str, contexto, instance, nombre: str) -> list[str]:
    """Las dos formas válidas de la ruta del paquete (la espiga comprobó ambas)."""
    raiz = f"{base_url}/pluginfile.php/{contexto}/mod_h5pactivity/package"
    return [f"{raiz}/0/{nombre}", f"{raiz}/{instance}/{nombre}"]


def url_modulo(base_url: str, tipo: str, cmid: int) -> str:
    return f"{base_url}/mod/{MODULO_MOODLE[tipo]}/view.php?id={cmid}"


# --------------------------------------------------------------------------- #
# Estado en .tiza
# --------------------------------------------------------------------------- #


def escribir_estructura(dir_tiza: str | Path, datos: dict) -> Path:
    asegurar_directorio(Path(dir_tiza))
    return escribir_json(Path(dir_tiza) / "estructura.json", datos)


def cargar_estructura(dir_tiza: str | Path) -> dict:
    ruta = Path(dir_tiza) / "estructura.json"
    if not ruta.is_file():
        raise ErrorPublicacion("ESTRUCTURA_AUSENTE")
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErrorPublicacion("ESTRUCTURA_ILEGIBLE") from exc


def cargar_verificados(dir_tiza: str | Path) -> dict:
    """Devuelve el mapa de hashes verificados; un fichero corrupto es un mapa vacío."""
    ruta = Path(dir_tiza) / "verificados.json"
    if not ruta.is_file():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        ficheros = datos.get("ficheros")
        return ficheros if isinstance(ficheros, dict) else {}
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def guardar_verificado(dir_tiza: str | Path, hash_doc: str, nombre: str, cmid: int) -> Path:
    directorio = asegurar_directorio(Path(dir_tiza))
    registro: dict[str, dict] = cargar_verificados(directorio)
    registro[hash_doc] = {
        "nombre": nombre,
        "cmid": cmid,
        "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    return escribir_json(directorio / "verificados.json", {"version": 1, "ficheros": registro})


def comprobar_puerta_real(verificados: dict, pares: list[tuple[str, str]]) -> list[str]:
    """Devuelve los nombres de los ficheros sin verificación previa en pruebas."""
    return [nombre for nombre, hash_doc in pares if hash_doc not in verificados]


# --------------------------------------------------------------------------- #
# Autoprueba de contrato
# --------------------------------------------------------------------------- #

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def autoprueba(moodle: AulaVirtual, curso_id: int) -> dict:
    """Publica, republica, verifica y borra en el curso de pruebas."""
    pasos: list[dict] = []
    errores: list[str] = []
    causas: list[BaseException] = []  # solo para --debug en pantalla; nunca al informe
    cmids: list[int] = []
    codigo_actual = "PREPARAR"

    def paso(codigo: str, resultado: str, detalle: str | None = None) -> None:
        pasos.append({"codigo": codigo, "resultado": resultado, "detalle": detalle})

    try:
        secciones = moodle.estructura(curso_id)
        if not secciones:
            raise ErrorPublicacion("ESTRUCTURA_VACIA")
        paso("ESTRUCTURA", "ok", f"{len(secciones)} secciones")
        seccion = secciones[0]["numero"]
        with tempfile.TemporaryDirectory(prefix="tiza-autoprueba-") as temporal:
            documentos = _ejemplos(Path(temporal), seccion)
            for doc in documentos:
                codigo_actual = {
                    "pagina": "PUBLICAR_PAGINA",
                    "tarea": "PUBLICAR_TAREA",
                    "cuestionario": "PUBLICAR_CUESTIONARIO",
                    "etiqueta": "PUBLICAR_ETIQUETA",
                    "h5p": "PUBLICAR_H5P",
                }[doc.tipo]
                resultado = publicar_documento(moodle, curso_id, secciones, doc, visible=False)
                cmids.append(resultado["cmid"])
                paso(codigo_actual, "ok", f"cmid {resultado['cmid']}")
            codigo_actual = "VERIFICAR_FECHAS"
            tarea = documentos[1]
            leidas = moodle.leer_modulo(cmids[1]).get("fechas") or {}
            if any(leidas.get(campo) != valor for campo, valor in fechas_esperadas(tarea).items()):
                raise ErrorPublicacion("FECHAS_NO_APLICADAS")
            paso("VERIFICAR_FECHAS", "ok", None)
            codigo_actual = "REPUBLICAR_PAGINA"
            secciones = moodle.estructura(curso_id)
            repetido = publicar_documento(moodle, curso_id, secciones, documentos[0], visible=None)
            if cmids and repetido["cmid"] != cmids[0]:
                raise ErrorPublicacion("REPUBLICAR_CMID_DISTINTO")
            if repetido["oculto"] is not True:
                raise ErrorPublicacion("VISIBILIDAD_NO_CONSERVADA")
            paso("REPUBLICAR_PAGINA", "ok", f"cmid {repetido['cmid']}")
            codigo_actual = "REPUBLICAR_CUESTIONARIO"
            secciones = moodle.estructura(curso_id)
            repetido = publicar_documento(moodle, curso_id, secciones, documentos[2], visible=None)
            if repetido["cmid"] != cmids[2]:
                raise ErrorPublicacion("REPUBLICAR_CMID_DISTINTO")
            if repetido["oculto"] is not True:
                raise ErrorPublicacion("VISIBILIDAD_NO_CONSERVADA")
            paso("REPUBLICAR_CUESTIONARIO", "ok", f"cmid {repetido['cmid']}")
            codigo_actual = "REPUBLICAR_ETIQUETA"
            secciones = moodle.estructura(curso_id)
            repetido = publicar_documento(moodle, curso_id, secciones, documentos[3], visible=None)
            if repetido["cmid"] != cmids[3]:
                raise ErrorPublicacion("REPUBLICAR_CMID_DISTINTO")
            if repetido["oculto"] is not True:
                raise ErrorPublicacion("VISIBILIDAD_NO_CONSERVADA")
            paso("REPUBLICAR_ETIQUETA", "ok", f"cmid {repetido['cmid']}")
            codigo_actual = "REPUBLICAR_H5P"
            secciones = moodle.estructura(curso_id)
            repetido = publicar_documento(moodle, curso_id, secciones, documentos[4], visible=None)
            if repetido["cmid"] != cmids[4]:
                raise ErrorPublicacion("REPUBLICAR_CMID_DISTINTO")
            if repetido["oculto"] is not True:
                raise ErrorPublicacion("VISIBILIDAD_NO_CONSERVADA")
            paso("REPUBLICAR_H5P", "ok", f"cmid {repetido['cmid']}")
            codigo_actual = "VERIFICAR_CATEGORIA"
            cmid_quiz = cmids[2]
            categoria = moodle.categoria_cuestionario(cmid_quiz)
            contexto = moodle.leer_modulo(cmid_quiz).get("contexto")
            if not categoria.endswith(f",{contexto}"):
                raise ErrorPublicacion("VERIFICACION_PREGUNTAS")
            en_banco = moodle.preguntas_en_categoria(cmid_quiz, categoria)
            if len(en_banco) != 2:
                raise ErrorPublicacion("VERIFICACION_PREGUNTAS")
            paso("VERIFICAR_CATEGORIA", "ok", f"{len(en_banco)} preguntas")
            codigo_actual = "CREAR_SECCION"
            nombre_seccion = "Autoprueba tiza (seccion)"
            existente = buscar_seccion(secciones, nombre_seccion)
            if existente is not None:
                seccion_id = existente["id"]
            else:
                seccion_id = moodle.crear_seccion(curso_id, nombre_seccion)
            secciones = moodle.estructura(curso_id)
            if buscar_seccion(secciones, nombre_seccion) is None:
                raise ErrorPublicacion("SECCION_NO_CREADA")
            paso("CREAR_SECCION", "ok", None)
            codigo_actual = "BORRAR_SECCION"
            moodle.borrar_seccion(curso_id, seccion_id)
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
