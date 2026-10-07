"""Informe de resultados con un esquema cerrado.

Todo lo que se escribe en ``.tiza/informe.json`` pasa por :func:`validar`, que
solo admite claves, tipos y textos conocidos. Así, ningún dato devuelto por
Moodle puede colarse en el informe que lee el agente.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import ayuda
from .ficheros import asegurar_directorio, escribir_json

__all__ = ["ErrorInforme", "crear", "escribir", "leer", "resumen", "validar", "validar_estructura"]

COMANDOS = {
    "comprobar",
    "estructura",
    "publicar",
    "autoprueba",
    "sesion",
}
RESULTADOS = {"ok", "error", "abortado"}
RESULTADOS_PASO = {"ok", "fallo"}
ACCIONES = {"creada", "actualizada", "borrada", "verificada"}
TIPOS = {"pagina", "tarea", "cuestionario", "etiqueta"}

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
_CAMPOS_FICHERO = {"nombre", "tipo", "cmid", "accion", "oculto", "url", "seccion", "hash"}

_CODIGO = re.compile(r"\A[A-Z][A-Z0-9_]{1,39}\Z")
_HASH = re.compile(r"\A[0-9a-f]{64}\Z")
_URL = re.compile(r"\Ahttps?://[^\s<>]+\Z")
# Misma clase de caracteres que terminal.texto_seguro, contenido._CONTROL y
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


def crear(
    comando: str,
    resultado: str,
    pasos: list[dict],
    ficheros: list[dict] | None = None,
    errores: list[str] | None = None,
    entorno: str | None = None,
    curso: int | None = None,
) -> dict:
    """Documento del informe con el esquema cerrado (lo valida ``escribir``)."""
    return {
        "version": 1,
        "comando": comando,
        "entorno": entorno,
        "curso": curso,
        "resultado": resultado,
        "pasos": pasos,
        "ficheros": ficheros or [],
        "errores": errores or [],
    }


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


_CAMPOS_ESTRUCTURA = {"version", "generado", "cursos"}
_CAMPOS_CURSO = {"id", "secciones"}
_CAMPOS_SECCION = {"numero", "nombre", "id"}


def validar_estructura(datos: Any) -> None:
    """Esquema cerrado de ``.tiza/estructura.json``, que también lee el agente."""
    if not isinstance(datos, dict):
        raise ErrorInforme("TIPO_INCORRECTO", "la estructura debe ser un objeto")
    _exigir_campos(datos, _CAMPOS_ESTRUCTURA, "estructura")
    if datos["version"] != 1:
        raise ErrorInforme("VALOR_NO_PERMITIDO", "version debe ser 1")
    _exigir_texto(datos["generado"], "generado")
    if not isinstance(datos["cursos"], dict):
        raise ErrorInforme("TIPO_INCORRECTO", "cursos debe ser un objeto")
    for entorno, curso in datos["cursos"].items():
        _exigir_opcion(entorno, {"pruebas", "real"}, "entorno")
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
    return escribir_json(Path(dir_tiza) / "informe.json", documento)


def leer(ruta: str | Path) -> dict:
    """Lee un informe ya escrito."""
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def resumen(documento: dict) -> list[str]:
    """Resumen de pantalla: campos del esquema y textos fijos de :mod:`tiza.ayuda`."""
    validar(documento)
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
