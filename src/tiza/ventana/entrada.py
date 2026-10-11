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

__all__ = ["MAX_COOKIES", "MAX_TUBERIA", "codificar", "cookies_del_aula", "decodificar", "es_panel"]

MAX_COOKIES = 50
MAX_VALOR = 4096
MAX_TUBERIA = 64 * 1024


def es_panel(url: str | None, base: str) -> bool:
    """¿Es ``url`` el panel ``/my/`` del aula ``base``? El aula solo lo sirve con sesión."""
    if not url:
        return False
    actual, aula = urlsplit(url), urlsplit(base)
    if actual.scheme != "https" or (actual.hostname, actual.port) != (aula.hostname, aula.port):
        return False
    return actual.path.rstrip("/") == f"{aula.path.rstrip('/')}/my"


def cookies_del_aula(galletas: Iterable[Mapping[str, object]], servidor: str) -> dict[str, str]:
    """Nombre → valor de las cookies cuyo dominio es exactamente el servidor del aula.

    ``galletas``: diccionarios con ``name``, ``value`` y ``domain``. Las de otros
    dominios (un proveedor de identidad, por ejemplo) se descartan.
    """
    resultado: dict[str, str] = {}
    for galleta in galletas:
        nombre, valor, dominio = galleta.get("name"), galleta.get("value"), galleta.get("domain")
        if (
            not isinstance(nombre, str)
            or not isinstance(valor, str)
            or not isinstance(dominio, str)
        ):
            continue
        if dominio.lstrip(".").lower() != servidor.lower():
            continue
        if not nombre or len(nombre) > 100 or len(valor) > MAX_VALOR:
            continue
        resultado[nombre] = valor
        if len(resultado) >= MAX_COOKIES:
            break
    return resultado


def codificar(cookies: Mapping[str, str]) -> str:
    return json.dumps({"cookies": dict(cookies)}, ensure_ascii=True)


def decodificar(texto: str) -> dict[str, str] | None:
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
    if not isinstance(cookies, dict) or len(cookies) > MAX_COOKIES:
        return None
    for nombre, valor in cookies.items():
        if not isinstance(nombre, str) or not isinstance(valor, str):
            return None
        if not 0 < len(nombre) <= 100 or len(valor) > MAX_VALOR:
            return None
    return dict(cookies)
