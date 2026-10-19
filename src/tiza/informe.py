"""Informe de resultados con un esquema cerrado.

Todo lo que se escribe en ``.tiza/informe.json`` o viaja en una respuesta del
buzón se construye con :func:`crear`, :class:`Paso`, :class:`Fichero` y
:class:`Borrador`, y pasa por :func:`validar` en la salida: solo admite claves,
tipos y textos conocidos. Así, ningún dato devuelto por Moodle puede colarse en
el informe que lee el agente.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import ayuda, calendario, tipos
from .estado import FICHERO_INFORME
from .ficheros import asegurar_directorio, escribir_json

__all__ = [
    "Borrador",
    "ErrorInforme",
    "Fichero",
    "ESTADOS_IMPORTACION",
    "Lectura",
    "PASOS",
    "Paso",
    "ResumenImportacion",
    "crear",
    "escribir",
    "leer",
    "resumen",
    "validar",
    "validar_copia",
    "validar_estructura",
    "validar_importacion",
    "validar_lectura",
]

COMANDOS = {
    "comprobar",
    "estructura",
    "publicar",
    "ordenar",
    "autoprueba",
    "sesion",
}
MAX_CURSOS_REALES = 6  # igual que config.MAX_REALES (este módulo no importa config)
RESULTADOS = {"ok", "error", "abortado"}
RESULTADOS_PASO = {"ok", "fallo"}
ACCIONES = {"creada", "actualizada", "borrada", "verificada", "movida", "ordenada", "sin_cambios"}
# El registro de tipos (tipos/) es el dueño de qué tipos existen.
TIPOS = set(tipos.TIPOS)
# El registro de los códigos de paso: solo estos salen en un informe. Los del
# calendario y los de la autoprueba (por tipo) salen de sus propios registros.
PASOS = (
    frozenset(
        {
            "BORRAR_SECCION",
            "CALENDARIO",
            "COMPROBAR",
            "CREAR_SECCION",
            "CURSO",
            "CURSO_OMITIDO",
            "DEPENDENCIA_SIN_FINALIZACION",
            "DEPENDENCIAS",
            "ESTRUCTURA",
            "FORMULA_DOLAR_SIMPLE",
            "FORMULAS_NO_DIBUJADAS",
            "LIMPIAR",
            "LOGIN",
            "MOVER_SECCION",
            "ORDENAR",
            "PREPARAR",
            "PUBLICAR",
            "SECCION_DISTINTA_ENTRE_CURSOS",
            "SIN_SESION",
            "SOLO_FECHAS",
            "VERIFICAR_CATEGORIA",
            "VERIFICAR_FECHAS",
        }
    )
    | set(calendario.AVISOS)
    | {f"PUBLICAR_{tipo.upper()}" for tipo in TIPOS}
    | {f"REPUBLICAR_{tipo.upper()}" for tipo in TIPOS}
)

_CAMPOS_RAIZ = {
    "version",
    "comando",
    "entorno",
    "curso",
    "resultado",
    "pasos",
    "ficheros",
    "errores",
}
_CAMPOS_PASO = {"codigo", "resultado", "detalle"}
_CAMPOS_FICHERO = {
    "nombre",
    "tipo",
    "cmid",
    "accion",
    "oculto",
    "url",
    "seccion",
    "hash",
    "curso",  # el curso donde está (nulo en «comprobar»): un .md sale una vez por curso
}

_CODIGO = re.compile(r"\A[A-Z][A-Z0-9_]{1,39}\Z")
_HASH = re.compile(r"\A[0-9a-f]{64}\Z")
_URL = re.compile(r"\Ahttps?://[^\s<>]+\Z")
# Misma clase de caracteres que mensajes.texto_seguro, contenido._CONTROL y
# publicar._NO_IMPRIMIBLE; mantén las cuatro sincronizadas.
_TEXTO_PROHIBIDO = re.compile(
    r"[<>\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069]"
)


class ErrorInforme(Exception):
    """Error del informe con un código estable."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


@dataclass(frozen=True)
class Paso:
    """Un paso del informe, validado al construirse con el esquema cerrado."""

    codigo: str
    resultado: str = "ok"
    detalle: str | None = None

    def __post_init__(self) -> None:
        _validar_paso(self.como_dict())

    def como_dict(self) -> dict:
        return {"codigo": self.codigo, "resultado": self.resultado, "detalle": self.detalle}


@dataclass(frozen=True)
class Fichero:
    """Un fichero del informe; los campos que no apliquen quedan nulos."""

    nombre: str
    tipo: str
    cmid: int | None = None
    accion: str | None = None
    oculto: bool | None = None
    url: str | None = None
    seccion: str | None = None
    hash: str | None = None
    curso: int | None = None

    def __post_init__(self) -> None:
        _validar_fichero(self.como_dict())

    def como_dict(self) -> dict:
        return {
            "nombre": self.nombre,
            "tipo": self.tipo,
            "cmid": self.cmid,
            "accion": self.accion,
            "oculto": self.oculto,
            "url": self.url,
            "seccion": self.seccion,
            "hash": self.hash,
            "curso": self.curso,
        }


def crear(
    comando: str,
    resultado: str,
    pasos: Sequence[Paso | dict],
    ficheros: Sequence[Fichero | dict] | None = None,
    errores: Iterable[str] | None = None,
    entorno: str | None = None,
    curso: int | None = None,
) -> dict:
    """Documento del informe con el esquema cerrado, válido por construcción.

    ``Paso``/``Fichero`` son lo normal; un dict ya construido (p. ej. el informe
    de un curso que se agrega) se valida aquí. La salida hacia el agente se
    valida entera, otra vez, en :func:`escribir` y en el buzón.
    """
    _exigir_opcion(comando, COMANDOS, "comando")
    _exigir_opcion(resultado, RESULTADOS, "resultado")
    _exigir_entorno(entorno)
    _exigir_entero_o_nulo(curso, "curso")
    return {
        "version": 1,
        "comando": comando,
        "entorno": entorno,
        "curso": curso,
        "resultado": resultado,
        "pasos": [_paso_a_dict(paso) for paso in pasos],
        "ficheros": [_fichero_a_dict(fichero) for fichero in ficheros or ()],
        "errores": _errores_validos(errores or ()),
    }


def _paso_a_dict(paso: Paso | dict) -> dict:
    if isinstance(paso, Paso):
        return paso.como_dict()
    _validar_paso(paso)
    return paso


def _fichero_a_dict(fichero: Fichero | dict) -> dict:
    if isinstance(fichero, Fichero):
        return fichero.como_dict()
    _validar_fichero(fichero)
    return fichero


def _errores_validos(errores: Iterable[str]) -> list[str]:
    salida = list(errores)
    for error in salida:
        if not isinstance(error, str) or not _CODIGO.match(error):
            raise ErrorInforme("VALOR_NO_PERMITIDO", "los errores deben ser códigos")
    return salida


class Borrador:
    """Acumula pasos, ficheros y errores y construye el informe del esquema cerrado.

    Quien informa no maneja listas paralelas: se las presta al borrador y al final
    pide :meth:`documento`.
    """

    def __init__(
        self, comando: str, *, entorno: str | None = None, curso: int | None = None
    ) -> None:
        _exigir_opcion(comando, COMANDOS, "comando")
        _exigir_entorno(entorno)
        _exigir_entero_o_nulo(curso, "curso")
        self.comando = comando
        self.entorno = entorno
        self.curso = curso
        self._pasos: list[Paso | dict] = []
        self._ficheros: list[Fichero | dict] = []
        self._errores: list[str] = []

    @property
    def errores(self) -> tuple[str, ...]:
        return tuple(self._errores)

    def paso(self, codigo: str, resultado: str = "ok", detalle: str | None = None) -> None:
        self._pasos.append(Paso(codigo, resultado, detalle))

    def fallo(self, codigo: str, detalle: str | None = None) -> None:
        self.paso(codigo, "fallo", detalle)

    def error(self, codigo: str) -> None:
        self._errores.append(codigo)

    def fichero(self, fichero: Fichero | dict) -> None:
        self._ficheros.append(fichero)

    def agregar(self, documento: Mapping[str, Any], *, excluir: Collection[str] = ()) -> None:
        """Acumula pasos, ficheros y errores de otro informe ya construido (un curso)."""
        self._pasos.extend(paso for paso in documento["pasos"] if paso["codigo"] not in excluir)
        self._ficheros.extend(documento["ficheros"])
        self._errores.extend(documento["errores"])

    def documento(self, resultado: str | None = None) -> dict:
        """El documento del esquema cerrado; sin ``resultado``, error si hubo errores."""
        if resultado is None:
            resultado = "error" if self._errores else "ok"
        return crear(
            self.comando,
            resultado,
            self._pasos,
            self._ficheros,
            self._errores,
            self.entorno,
            self.curso,
        )


def validar(documento: Any) -> None:
    """Comprueba que el documento cumple el esquema cerrado."""
    if not isinstance(documento, dict):
        raise ErrorInforme("TIPO_INCORRECTO", "el informe debe ser un objeto")
    _exigir_campos(documento, _CAMPOS_RAIZ, "raíz")
    if documento["version"] != 1:
        raise ErrorInforme("VALOR_NO_PERMITIDO", "version debe ser 1")
    _exigir_opcion(documento["comando"], COMANDOS, "comando")
    _exigir_opcion(documento["resultado"], RESULTADOS, "resultado")
    _exigir_entorno(documento["entorno"])
    _exigir_entero_o_nulo(documento["curso"], "curso")
    for paso in _exigir_lista(documento["pasos"], "pasos"):
        _validar_paso(paso)
    for fichero in _exigir_lista(documento["ficheros"], "ficheros"):
        _validar_fichero(fichero)
    for error in _exigir_lista(documento["errores"], "errores"):
        if not isinstance(error, str) or not _CODIGO.match(error):
            raise ErrorInforme("VALOR_NO_PERMITIDO", "los errores deben ser códigos")


def _validar_paso(paso: Any) -> None:
    if not isinstance(paso, dict):
        raise ErrorInforme("TIPO_INCORRECTO", "cada paso debe ser un objeto")
    _exigir_campos(paso, _CAMPOS_PASO, "paso")
    if not isinstance(paso["codigo"], str) or not _CODIGO.match(paso["codigo"]):
        raise ErrorInforme("VALOR_NO_PERMITIDO", "el código del paso no es válido")
    if paso["codigo"] not in PASOS:
        raise ErrorInforme("VALOR_NO_PERMITIDO", "el código del paso no está registrado")
    _exigir_opcion(paso["resultado"], RESULTADOS_PASO, "resultado del paso")
    _exigir_texto(paso["detalle"], "detalle del paso")


def _validar_fichero(fichero: Any) -> None:
    if not isinstance(fichero, dict):
        raise ErrorInforme("TIPO_INCORRECTO", "cada fichero debe ser un objeto")
    _exigir_campos(fichero, _CAMPOS_FICHERO, "fichero")
    if not isinstance(fichero["nombre"], str) or not fichero["nombre"]:
        raise ErrorInforme("TIPO_INCORRECTO", "nombre debe ser texto no vacío")
    _exigir_texto(fichero["nombre"], "nombre")
    _exigir_opcion(fichero["tipo"], TIPOS, "tipo de fichero")
    _exigir_entero_o_nulo(fichero["cmid"], "cmid")
    _exigir_entero_o_nulo(fichero["curso"], "curso del fichero")
    if fichero["accion"] is not None:
        _exigir_opcion(fichero["accion"], ACCIONES, "acción")
    if fichero["oculto"] is not None and not isinstance(fichero["oculto"], bool):
        raise ErrorInforme("TIPO_INCORRECTO", "oculto debe ser booleano o nulo")
    if fichero["url"] is not None:
        if not isinstance(fichero["url"], str) or not _URL.match(fichero["url"]):
            raise ErrorInforme("VALOR_NO_PERMITIDO", "url no es una URL válida")
    _exigir_texto(fichero["seccion"], "sección")
    if fichero["hash"] is not None:
        if not isinstance(fichero["hash"], str) or not _HASH.match(fichero["hash"]):
            raise ErrorInforme("VALOR_NO_PERMITIDO", "hash no es un sha256")


_CAMPOS_LECTURA = {
    "fichero",
    "formato",
    "lectura",
    "bloques",
    "tablas",
    "paginas",
    "avisos",
    "sha256",
}


@dataclass(frozen=True)
class Lectura:
    """El resumen que imprime ``tiza leer``: dónde quedó la lectura y qué tiene.

    ``tablas`` cuenta todas las tablas, también las anidadas; ``paginas`` es el número de
    páginas de un PDF y ``None`` en un Word. Se valida al construirlo: nunca sale uno inválido.
    """

    fichero: str
    formato: str
    lectura: str
    bloques: int
    tablas: int
    paginas: int | None
    avisos: Sequence[str]
    sha256: str

    def __post_init__(self) -> None:
        validar_lectura(self.a_dict())

    def a_dict(self) -> dict:
        return {
            "fichero": self.fichero,
            "formato": self.formato,
            "lectura": self.lectura,
            "bloques": self.bloques,
            "tablas": self.tablas,
            "paginas": self.paginas,
            "avisos": list(self.avisos),
            "sha256": self.sha256,
        }


def validar_lectura(datos: Any) -> None:
    """Esquema cerrado del resumen de ``tiza leer``."""
    if not isinstance(datos, dict):
        raise ErrorInforme("TIPO_INCORRECTO", "la lectura debe ser un objeto")
    _exigir_campos(datos, _CAMPOS_LECTURA, "lectura")
    _exigir_opcion(datos["formato"], {"docx", "pdf"}, "formato")
    for campo in ("fichero", "lectura"):
        if not isinstance(datos[campo], str) or not datos[campo]:
            raise ErrorInforme("TIPO_INCORRECTO", f"{campo} debe ser texto")
        _exigir_texto(datos[campo], campo)
    _exigir_entero(datos["bloques"], "bloques")
    _exigir_entero(datos["tablas"], "tablas")
    _exigir_entero_o_nulo(datos["paginas"], "paginas")
    for aviso in _exigir_lista(datos["avisos"], "avisos"):
        if not isinstance(aviso, str) or not _CODIGO.match(aviso):
            raise ErrorInforme("VALOR_NO_PERMITIDO", "los avisos deben ser códigos")
    if not isinstance(datos["sha256"], str) or not _HASH.match(datos["sha256"]):
        raise ErrorInforme("VALOR_NO_PERMITIDO", "sha256 no es un hash válido")


_CAMPOS_DOCUMENTO = {"fuente", "documento", "bloques"}


@dataclass(frozen=True)
class Documento:
    """El resumen que imprime ``tiza documento``: de qué ``.md`` sale qué ``.docx``.

    Las rutas son relativas a la carpeta de la asignatura. Se valida al construirlo.
    """

    fuente: str
    documento: str
    bloques: int

    def __post_init__(self) -> None:
        validar_documento(self.a_dict())

    def a_dict(self) -> dict:
        return {"fuente": self.fuente, "documento": self.documento, "bloques": self.bloques}


def validar_documento(datos: Any) -> None:
    """Esquema cerrado del resumen de ``tiza documento``."""
    if not isinstance(datos, dict):
        raise ErrorInforme("TIPO_INCORRECTO", "el documento debe ser un objeto")
    _exigir_campos(datos, _CAMPOS_DOCUMENTO, "documento")
    for campo in ("fuente", "documento"):
        if not isinstance(datos[campo], str) or not datos[campo]:
            raise ErrorInforme("TIPO_INCORRECTO", f"{campo} debe ser texto")
        _exigir_texto(datos[campo], campo)
    _exigir_entero(datos["bloques"], "bloques")


_CAMPOS_RELLENO = {"plantilla", "salida", "operaciones", "avisos"}


@dataclass(frozen=True)
class Relleno:
    """El resumen que imprime ``tiza rellenar``: qué plantilla, qué Word nuevo y cuántas operaciones.

    Las rutas son relativas a la carpeta de la asignatura y los avisos, códigos estables.
    Se valida al construirlo.
    """

    plantilla: str
    salida: str
    operaciones: int
    avisos: Sequence[str]

    def __post_init__(self) -> None:
        validar_relleno(self.a_dict())

    def a_dict(self) -> dict:
        return {
            "plantilla": self.plantilla,
            "salida": self.salida,
            "operaciones": self.operaciones,
            "avisos": list(self.avisos),
        }


def validar_relleno(datos: Any) -> None:
    """Esquema cerrado del resumen de ``tiza rellenar``."""
    if not isinstance(datos, dict):
        raise ErrorInforme("TIPO_INCORRECTO", "el relleno debe ser un objeto")
    _exigir_campos(datos, _CAMPOS_RELLENO, "relleno")
    for campo in ("plantilla", "salida"):
        if not isinstance(datos[campo], str) or not datos[campo]:
            raise ErrorInforme("TIPO_INCORRECTO", f"{campo} debe ser texto")
        _exigir_texto(datos[campo], campo)
    _exigir_entero(datos["operaciones"], "operaciones")
    for aviso in _exigir_lista(datos["avisos"], "avisos"):
        if not isinstance(aviso, str) or not _CODIGO.match(aviso):
            raise ErrorInforme("VALOR_NO_PERMITIDO", "los avisos deben ser códigos")


# Cómo queda cada actividad de una copia que importa ``tiza importar``.
ESTADOS_IMPORTACION = (
    "IMPORTADA",
    "YA_IMPORTADO",
    "CAMBIADA_DESDE_LA_IMPORTACION",
    "HTML_NO_ADMITIDO",
    "PREGUNTAS_NO_ADMITIDAS",
    "TIPO_NO_GESTIONADO",
)
_CAMPOS_IMPORTACION = {"copia", "curso", "como_nuevas", "actividades", "estados"}
_CAMPOS_COPIA = {
    "version",
    "curso",
    "moodle",
    "fecha_importacion",
    "como_nuevas",
    "secciones",
    "actividades",
}
_CAMPOS_SECCION_COPIA = {"numero", "nombre", "resumen_html_presente"}
_CAMPOS_ACTIVIDAD_COPIA = {
    "cmid",
    "modulo",
    "seccion",
    "nombre",
    "fichero",
    "estado",
    "detalle",
    "huella_aula",
}
_MODULO = re.compile(r"\A[a-z][a-z0-9]{0,29}\Z")


@dataclass(frozen=True)
class ResumenImportacion:
    """El resumen que imprime ``tiza importar``: dónde quedó ``copia.json`` y los recuentos.

    ``copia`` es una ruta relativa a la carpeta de la asignatura y ``estados`` lleva un
    recuento por cada estado de :data:`ESTADOS_IMPORTACION` (también los que valen 0).
    Se valida al construirlo: nunca sale uno inválido.
    """

    copia: str
    curso: int
    como_nuevas: bool
    actividades: int
    estados: Mapping[str, int]

    def __post_init__(self) -> None:
        validar_importacion(self.a_dict())

    def a_dict(self) -> dict:
        return {
            "copia": self.copia,
            "curso": self.curso,
            "como_nuevas": self.como_nuevas,
            "actividades": self.actividades,
            "estados": {estado: self.estados.get(estado, 0) for estado in ESTADOS_IMPORTACION},
        }


def validar_importacion(datos: Any) -> None:
    """Esquema cerrado del resumen de ``tiza importar``."""
    if not isinstance(datos, dict):
        raise ErrorInforme("TIPO_INCORRECTO", "la importación debe ser un objeto")
    _exigir_campos(datos, _CAMPOS_IMPORTACION, "importación")
    _exigir_ruta_relativa(datos["copia"], "copia")
    _exigir_entero(datos["curso"], "curso")
    _exigir_bool(datos["como_nuevas"], "como_nuevas")
    _exigir_entero(datos["actividades"], "actividades")
    estados = datos["estados"]
    if not isinstance(estados, dict):
        raise ErrorInforme("TIPO_INCORRECTO", "estados debe ser un objeto")
    _exigir_campos(estados, set(ESTADOS_IMPORTACION), "estados")
    for estado, cuantas in estados.items():
        _exigir_entero(cuantas, f"estado {estado}")


def validar_copia(datos: Any) -> None:
    """Esquema cerrado de ``.tiza/copia.json``, que también lee el agente."""
    if not isinstance(datos, dict):
        raise ErrorInforme("TIPO_INCORRECTO", "la copia debe ser un objeto")
    _exigir_campos(datos, _CAMPOS_COPIA, "copia")
    if datos["version"] != 1 or isinstance(datos["version"], bool):
        raise ErrorInforme("VALOR_NO_PERMITIDO", "version debe ser 1")
    _exigir_entero(datos["curso"], "curso")
    for campo in ("moodle", "fecha_importacion"):
        if not isinstance(datos[campo], str):
            raise ErrorInforme("TIPO_INCORRECTO", f"{campo} debe ser texto")
        _exigir_texto(datos[campo], campo)
    _exigir_bool(datos["como_nuevas"], "como_nuevas")
    for seccion in _exigir_lista(datos["secciones"], "secciones"):
        if not isinstance(seccion, dict):
            raise ErrorInforme("TIPO_INCORRECTO", "cada sección debe ser un objeto")
        _exigir_campos(seccion, _CAMPOS_SECCION_COPIA, "sección")
        _exigir_entero(seccion["numero"], "número de sección")
        if not isinstance(seccion["nombre"], str):
            raise ErrorInforme("TIPO_INCORRECTO", "el nombre de la sección debe ser texto")
        _exigir_texto(seccion["nombre"], "nombre de sección")
        _exigir_bool(seccion["resumen_html_presente"], "resumen_html_presente")
    for actividad in _exigir_lista(datos["actividades"], "actividades"):
        if not isinstance(actividad, dict):
            raise ErrorInforme("TIPO_INCORRECTO", "cada actividad debe ser un objeto")
        _exigir_campos(actividad, _CAMPOS_ACTIVIDAD_COPIA, "actividad")
        _exigir_entero(actividad["cmid"], "cmid")
        _exigir_entero(actividad["seccion"], "sección de la actividad")
        if not isinstance(actividad["modulo"], str) or not _MODULO.match(actividad["modulo"]):
            raise ErrorInforme("VALOR_NO_PERMITIDO", "módulo no permitido")
        if not isinstance(actividad["nombre"], str):
            raise ErrorInforme("TIPO_INCORRECTO", "el nombre de la actividad debe ser texto")
        _exigir_texto(actividad["nombre"], "nombre de la actividad")
        if actividad["fichero"] is not None:
            _exigir_ruta_relativa(actividad["fichero"], "fichero")
        _exigir_opcion(actividad["estado"], set(ESTADOS_IMPORTACION), "estado")
        if actividad["detalle"] is not None and not isinstance(actividad["detalle"], str):
            raise ErrorInforme("TIPO_INCORRECTO", "el detalle debe ser texto o nulo")
        _exigir_texto(actividad["detalle"], "detalle")
        huella = actividad["huella_aula"]
        if huella is not None and (not isinstance(huella, str) or not _HASH.match(huella)):
            raise ErrorInforme("VALOR_NO_PERMITIDO", "huella_aula no es un sha256")


def _exigir_bool(valor: Any, nombre: str) -> None:
    if not isinstance(valor, bool):
        raise ErrorInforme("TIPO_INCORRECTO", f"{nombre} debe ser verdadero o falso")


def _exigir_ruta_relativa(valor: Any, nombre: str) -> None:
    """Una ruta con «/» dentro de la carpeta de la asignatura: sin «..», sin unidad ni barra inicial."""
    if not isinstance(valor, str) or not valor:
        raise ErrorInforme("TIPO_INCORRECTO", f"{nombre} debe ser una ruta")
    _exigir_texto(valor, nombre)
    partes = valor.split("/")
    if (
        "\\" in valor
        or valor.startswith("/")
        or any(p in ("", ".", "..") for p in partes)
        or re.match(r"[A-Za-z]:", partes[0])
    ):
        raise ErrorInforme("VALOR_NO_PERMITIDO", f"{nombre} no es una ruta relativa")


_CAMPOS_ESTRUCTURA = {"version", "generado", "cursos"}
_CAMPOS_CURSO = {"id", "secciones"}
_CAMPOS_SECCION = {"numero", "nombre", "id"}


def validar_estructura(datos: Any) -> None:
    """Esquema cerrado de ``.tiza/estructura.json``, que también lee el agente."""
    if not isinstance(datos, dict):
        raise ErrorInforme("TIPO_INCORRECTO", "la estructura debe ser un objeto")
    _exigir_campos(datos, _CAMPOS_ESTRUCTURA, "estructura")
    # v1: «real» es un curso; v2: «real» es una lista de cursos (uno por curso real).
    if datos["version"] not in (1, 2) or isinstance(datos["version"], bool):
        raise ErrorInforme("VALOR_NO_PERMITIDO", "version debe ser 1 o 2")
    _exigir_texto(datos["generado"], "generado")
    if not isinstance(datos["cursos"], dict):
        raise ErrorInforme("TIPO_INCORRECTO", "cursos debe ser un objeto")
    for entorno, curso in datos["cursos"].items():
        _exigir_opcion(entorno, {"pruebas", "real"}, "entorno")
        if datos["version"] == 2 and entorno == "real":
            lista = _exigir_lista(curso, "cursos reales")
            if not 1 <= len(lista) <= MAX_CURSOS_REALES:
                raise ErrorInforme("VALOR_NO_PERMITIDO", "número de cursos reales no permitido")
            for uno in lista:
                _validar_curso_estructura(uno)
        else:
            _validar_curso_estructura(curso)


def _validar_curso_estructura(curso: Any) -> None:
    if not isinstance(curso, dict):
        raise ErrorInforme("TIPO_INCORRECTO", "cada curso debe ser un objeto")
    _exigir_campos(curso, _CAMPOS_CURSO, "curso")
    _exigir_entero(curso["id"], "id del curso")
    for seccion in _exigir_lista(curso["secciones"], "secciones"):
        if not isinstance(seccion, dict):
            raise ErrorInforme("TIPO_INCORRECTO", "cada sección debe ser un objeto")
        _exigir_campos(seccion, _CAMPOS_SECCION, "sección")
        _exigir_entero(seccion["numero"], "número de sección")
        _exigir_entero(seccion["id"], "id de sección")
        if not isinstance(seccion["nombre"], str):
            raise ErrorInforme("TIPO_INCORRECTO", "el nombre de la sección debe ser texto")
        _exigir_texto(seccion["nombre"], "nombre de sección")


def _exigir_entero(valor: Any, nombre: str) -> None:
    if valor is None:
        raise ErrorInforme("TIPO_INCORRECTO", f"{nombre} debe ser un número entero")
    _exigir_entero_o_nulo(valor, nombre)


def _exigir_campos(documento: dict, permitidos: set[str], donde: str) -> None:
    for campo in documento:
        if campo not in permitidos:
            raise ErrorInforme("CAMPO_NO_PERMITIDO", f"campo «{campo}» no permitido en {donde}")
    for campo in permitidos:
        if campo not in documento:
            raise ErrorInforme("CAMPO_FALTANTE", f"falta el campo «{campo}» en {donde}")


def _exigir_opcion(valor: Any, opciones: set[str], nombre: str) -> None:
    if not isinstance(valor, str):
        raise ErrorInforme("TIPO_INCORRECTO", f"{nombre} debe ser texto")
    if valor not in opciones:
        raise ErrorInforme("VALOR_NO_PERMITIDO", f"{nombre} no es un valor permitido")
    _exigir_texto(valor, nombre)


def _exigir_entorno(valor: Any) -> None:
    if valor is None:
        return
    _exigir_opcion(valor, {"pruebas", "real"}, "entorno")


def _exigir_entero_o_nulo(valor: Any, nombre: str) -> None:
    if valor is None:
        return
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErrorInforme("TIPO_INCORRECTO", f"{nombre} debe ser un número entero o nulo")


def _exigir_lista(valor: Any, nombre: str) -> list:
    if not isinstance(valor, list):
        raise ErrorInforme("TIPO_INCORRECTO", f"{nombre} debe ser una lista")
    return valor


def _exigir_texto(valor: Any, nombre: str) -> None:
    if valor is None:
        return
    if not isinstance(valor, str):
        raise ErrorInforme("TIPO_INCORRECTO", f"{nombre} debe ser texto o nulo")
    if _TEXTO_PROHIBIDO.search(valor):
        raise ErrorInforme("TEXTO_NO_PERMITIDO", f"{nombre} contiene símbolos no permitidos")


def escribir(documento: dict, dir_tiza: str | Path) -> Path:
    """Valida y escribe ``.tiza/informe.json``; devuelve su ruta.

    Si ``.tiza`` es un enlace simbólico no escribe nada (``FicheroNoSeguro``).
    """
    validar(documento)
    asegurar_directorio(Path(dir_tiza))
    return escribir_json(Path(dir_tiza) / FICHERO_INFORME, documento)


def leer(ruta: str | Path) -> dict:
    """Lee un informe ya escrito."""
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def resumen(documento: dict) -> list[str]:
    """Resumen de pantalla: campos del esquema y textos fijos de :mod:`tiza.ayuda`.

    No valida: solo pinta. La validación del esquema es de las salidas hacia el
    agente (``escribir`` y el buzón), y la construcción ya comprueba cada campo.
    """
    lineas = [f"Informe: {documento['resultado']} ({documento['comando']})"]
    if documento["entorno"] is not None:
        lineas.append(f"Entorno: {documento['entorno']}")
    if documento["curso"] is not None:
        lineas.append(f"Curso: {documento['curso']}")
    for paso in documento["pasos"]:
        detalle = f" — {paso['detalle']}" if paso["detalle"] else ""
        lineas.append(f"Paso {paso['codigo']}: {paso['resultado']}{detalle}")
    for fichero in documento["ficheros"]:
        partes = [f"Fichero {fichero['nombre']}: {fichero['tipo']}"]
        if fichero["cmid"] is not None:
            partes.append(f"cmid {fichero['cmid']}")
        if fichero["accion"] is not None:
            partes.append(fichero["accion"])
        if fichero["oculto"] is True:
            partes.append("oculto")
        elif fichero["oculto"] is False:
            partes.append("visible")
        if fichero["seccion"]:
            partes.append(f"sección {fichero['seccion']}")
        if fichero["curso"] is not None and documento["curso"] is None:
            partes.append(f"curso {fichero['curso']}")  # varios cursos: de cuál es
        lineas.append(" — ".join(partes))
        if fichero["url"]:
            lineas.append(f"  Ver en el aula: {fichero['url']}")
    if documento["errores"]:
        lineas.append("Errores: " + ", ".join(documento["errores"]))
        # Texto fijo de tiza, elegido por el código; nunca viene de Moodle.
        for codigo in dict.fromkeys(documento["errores"]):
            texto = ayuda.explicar(codigo)
            if texto is not None:
                lineas.append(f"Qué hacer ({codigo}): {texto}")
    return lineas
