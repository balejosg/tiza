"""Entrada al aula en una ventana: lo que se decide sin pywebview.

La ventana (un proceso hijo, ver ``__init__``) enseña la página de login del aula y,
cuando el aula sirve el panel ``/my/``, devuelve las cookies de sesión del servidor del
aula. Aquí viven las decisiones que se prueban sin ventana: cuándo se está dentro, qué
cookies se aceptan y qué formato y límites tiene lo que cruza la tubería.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit

from ..config import coincide_dominio

__all__ = [
    "MAX_COOKIES",
    "MAX_TUBERIA",
    "Galleta",
    "codificar",
    "coincide_dominio",
    "cookies_del_aula",
    "decodificar",
    "es_panel",
]

MAX_COOKIES = 50
MAX_NOMBRE = 100
MAX_VALOR = 4096
MAX_DOMINIO = 255
MAX_TUBERIA = 64 * 1024

Galleta = tuple[str, str, str]  # nombre, valor, dominio


def es_panel(url: str | None, base: str) -> bool:
    """¿Está ``url`` dentro de ``/my`` del aula ``base``? El aula solo lo sirve con sesión.

    La ventana se abre en ``/my/``, así que al acabar el login Moodle vuelve ahí: al panel o,
    con el panel desactivado, a ``/my/courses.php``. Otras páginas del aula que enlaza la
    página de login (política de cookies, portada) no cuentan: se puede ver sin haber entrado.
    """
    if not url:
        return False
    actual, aula = urlsplit(url), urlsplit(base)
    if actual.scheme != "https" or (actual.hostname, actual.port) != (aula.hostname, aula.port):
        return False
    panel = f"{aula.path.rstrip('/')}/my"
    return actual.path == panel or actual.path.startswith(f"{panel}/")


def cookies_del_aula(galletas: Iterable[Mapping[str, object]], servidor: str) -> list[Galleta]:
    """(nombre, valor, dominio) de las cookies que el navegador enviaría al aula ``servidor``.

    ``galletas``: diccionarios con ``name``, ``value`` y ``domain``. Las de otros dominios
    (un proveedor de identidad, por ejemplo) se descartan.
    """
    resultado: dict[tuple[str, str], Galleta] = {}
    for galleta in galletas:
        nombre, valor, dominio = galleta.get("name"), galleta.get("value"), galleta.get("domain")
        if (
            not isinstance(nombre, str)
            or not isinstance(valor, str)
            or not isinstance(dominio, str)
        ):
            continue
        if not nombre or len(nombre) > MAX_NOMBRE or len(valor) > MAX_VALOR:
            continue
        if len(dominio) > MAX_DOMINIO or not coincide_dominio(servidor, dominio):
            continue
        resultado[(nombre, dominio.lstrip(".").lower())] = (
            nombre,
            valor,
            dominio.lstrip(".").lower(),
        )
        if len(resultado) >= MAX_COOKIES:
            break
    return list(resultado.values())


def codificar(cookies: Iterable[Galleta]) -> str:
    return json.dumps(
        {"cookies": [{"nombre": n, "valor": v, "dominio": d} for n, v, d in cookies]},
        ensure_ascii=True,
    )


def decodificar(texto: str) -> list[Galleta] | None:
    """Las cookies de lo que escribió el hijo; None si no cumple el esquema o los límites."""
    if len(texto) > MAX_TUBERIA:
        return None
    try:
        datos = json.loads(texto)
    except (ValueError, RecursionError):
        return None
    if not isinstance(datos, dict) or set(datos) != {"cookies"}:
        return None
    cookies = datos["cookies"]
    if not isinstance(cookies, list) or len(cookies) > MAX_COOKIES:
        return None
    resultado: list[Galleta] = []
    for galleta in cookies:
        if not isinstance(galleta, dict) or set(galleta) != {"nombre", "valor", "dominio"}:
            return None
        nombre, valor, dominio = galleta["nombre"], galleta["valor"], galleta["dominio"]
        if not all(isinstance(campo, str) for campo in (nombre, valor, dominio)):
            return None
        if not 0 < len(nombre) <= MAX_NOMBRE or len(valor) > MAX_VALOR:
            return None
        if not 0 < len(dominio) <= MAX_DOMINIO:
            return None
        resultado.append((nombre, valor, dominio))
    return resultado
