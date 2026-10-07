"""La página de la ventana de sesión, con un nonce nuevo en cada arranque."""

from __future__ import annotations

import secrets
from importlib import resources

__all__ = ["html"]

_MARCA = "__NONCE__"


def html() -> str:
    plantilla = (resources.files("tiza.ventana") / "sesion.html").read_text(encoding="utf-8")
    return plantilla.replace(_MARCA, secrets.token_urlsafe(16))
