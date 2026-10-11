"""¿Está instalado Microsoft Edge WebView2? (Windows)

Sin WebView2, pywebview usaría MSHTML (el motor de Internet Explorer), que no
sirve para la ventana de sesión. Se comprueba como indica Microsoft: el valor
``pv`` de la clave del runtime, por máquina o por usuario, distinto de vacío y
de 0.0.0.0.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["DESCARGA", "instalado", "texto_que_falta"]

DESCARGA = "https://developer.microsoft.com/microsoft-edge/webview2/"
_CLIENTE = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def instalado() -> bool:
    winreg: Any = importlib.import_module("winreg")
    rutas = (
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\{_CLIENTE}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\{_CLIENTE}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\{_CLIENTE}"),
    )
    for raiz, ruta in rutas:
        try:
            with winreg.OpenKey(raiz, ruta) as clave:
                version, _tipo = winreg.QueryValueEx(clave, "pv")
        except OSError:
            continue
        if isinstance(version, str) and version not in ("", "0.0.0.0"):
            return True
    return False


def texto_que_falta() -> str:
    return (
        "Para abrir la ventana de entrada hace falta Microsoft Edge WebView2. "
        f"Descárgalo de {DESCARGA} para usarla; mientras, entrarás con la contraseña en la terminal."
    )
