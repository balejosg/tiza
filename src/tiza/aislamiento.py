"""Aislamiento del agente: comprobar y completar su configuración.

``revisar_*`` solo lee. ``fusionar_*`` solo AÑADE restricciones. Nunca se
muestra el contenido de los ficheros de ajustes: pueden tener claves de API.
Reproduce lo que explica docs/aislamiento.md.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import platformdirs

from . import config

__all__ = [
    "AVISO_GLOBAL",
    "CODEX",
    "CONFIG_OPENCODE",
    "COPILOT",
    "Comprobacion",
    "ErrorAislamiento",
    "OPENCODE",
    "configuracion_opencode",
    "contenido_opencode",
    "fusionar_claude",
    "fusionar_codex",
    "fusionar_confianza_codex",
    "leer_json",
    "reglas_webfetch",
    "revisar",
    "revisar_claude",
    "revisar_codex",
    "revisar_copilot",
    "revisar_opencode",
    "receta_copilot",
    "ruta_claude",
    "ruta_claude_proyecto",
    "ruta_codex",
    "ruta_codex_proyecto",
    "ruta_copilot",
    "rutas_tiza",
    "rutas_privadas",
    "rutas_reabiertas",
    "servidor_configurado",
]


def servidor_configurado() -> str | None:
    """El servidor del aula de la configuración global, o ``None``.

    El agente no puede leer la configuración global; con ``None``, las
    comprobaciones que dependen del servidor quedan sin hacer («no comprobado»).
    """
    try:
        datos = config.cargar_global()
    except config.ErrorConfig:
        return None
    url = (datos or {}).get("url")
    if not isinstance(url, str) or not url:
        return None
    try:
        return urlsplit(url).hostname or None
    except ValueError:
        return None


def reglas_webfetch(servidor: str) -> list[str]:
    """Reglas de Claude Code que bloquean la WebFetch hacia el servidor del aula."""
    return [f"WebFetch(domain:{servidor})"]


# Lo que un agente sin restricciones podría leer para entrar al aula con la sesión del docente o
# ver datos del alumnado: navegadores (y sus cachés), correo, descargas y almacenes de contraseñas.
_PRIVADAS = {
    "Linux": [
        "~/.config/google-chrome",
        "~/.config/chromium",
        "~/.config/microsoft-edge",
        "~/.config/BraveSoftware",
        "~/.config/vivaldi",
        "~/.config/opera",
        "~/.mozilla",
        "~/.cache/mozilla",
        "~/.cache/google-chrome",
        "~/.cache/chromium",
        "~/snap/firefox",
        "~/snap/chromium",
        "~/.var/app/org.mozilla.firefox",
        "~/.var/app/com.google.Chrome",
        "~/.var/app/org.chromium.Chromium",
        "~/.var/app/com.brave.Browser",
        "~/.var/app/com.microsoft.Edge",
        "~/.thunderbird",
        "~/.var/app/org.mozilla.Thunderbird",
        "~/Descargas",
        "~/Downloads",
        "~/.local/share/keyrings",
        "~/.password-store",
    ],
    "Darwin": [
        "~/Library/Application Support/Google/Chrome",
        "~/Library/Application Support/Firefox",
        "~/Library/Application Support/Microsoft Edge",
        "~/Library/Application Support/BraveSoftware",
        "~/Library/Application Support/Vivaldi",
        "~/Library/Application Support/com.operasoftware.Opera",
        "~/Library/Safari",
        "~/Library/Cookies",
        "~/Library/Containers/com.apple.Safari",
        "~/Library/Caches/Google/Chrome",
        "~/Library/Caches/Firefox",
        "~/Library/Caches/com.apple.Safari",
        "~/Library/Thunderbird",
        "~/Library/Mail",
        "~/Library/Keychains",
        "~/Downloads",
    ],
    "Windows": [
        "~/AppData/Local/Google/Chrome",
        "~/AppData/Roaming/Mozilla",
        "~/AppData/Local/Mozilla",
        "~/AppData/Local/Microsoft/Edge",
        "~/AppData/Local/BraveSoftware",
        "~/AppData/Local/Vivaldi",
        "~/AppData/Roaming/Opera Software",
        "~/AppData/Roaming/Thunderbird",
        "~/AppData/Local/Thunderbird",
        "~/AppData/Roaming/Microsoft/Credentials",
        "~/AppData/Local/Microsoft/Credentials",
        "~/Downloads",
    ],
}

CLAUDE = "Claude Code"

AVISO_GLOBAL = (
    "aislamiento global: afecta a todos tus proyectos; ejecuta «tiza aislar» "
    "en la carpeta de la asignatura para limitarlo a ella"
)


class ErrorAislamiento(Exception):
    """Error de aislamiento con un código estable."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


@dataclass(frozen=True)
class Comprobacion:
    agente: str
    estado: str  # "ok" | "falta" | "aviso"
    texto: str


def rutas_privadas(sistema: str) -> list[str]:
    """Navegadores, correo, Descargas y almacenes de contraseñas que el agente no debe leer."""
    return list(_PRIVADAS.get(sistema, _PRIVADAS["Linux"]))


def rutas_tiza() -> list[str]:
    """Configuración y caché de tiza: el agente no debe leerlas ni escribirlas.

    En la configuración está la URL del aula; en la caché viven las vistas
    previas. Se niegan también de escritura: cambiar la configuración o una vista
    previa sería una forma de colarse.
    """
    return [
        str(platformdirs.user_config_dir(config.APP)),
        str(platformdirs.user_cache_dir(config.APP)),
    ]


def _expandir(ruta: str, home: Path, carpeta: Path | None) -> Path | None:
    """Ruta de unos ajustes como Path; None si es relativa y no hay carpeta.

    Si lleva comodines se queda con la parte anterior al primero: compararla es
    más estricto que el patrón completo.
    """
    for i, caracter in enumerate(ruta):
        if caracter in "*?[{":
            ruta = ruta[:i].rpartition("/")[0] or "/"
            break
    if ruta == "~" or ruta.startswith("~/"):
        return home / ruta[2:]
    if Path(ruta).is_absolute():
        return Path(ruta)
    return carpeta / ruta if carpeta is not None else None


def rutas_reabiertas(home: Path, sistema: str, carpeta: Path) -> list[str]:
    """La carpeta de la asignatura si cae dentro de una ruta privada (Descargas).

    Las rutas privadas siguen bloqueadas; solo se vuelve a permitir leer esta
    carpeta para que el agente pueda trabajar en ella.
    """
    destino = carpeta.resolve()
    for ruta in rutas_privadas(sistema):
        privada = _expandir(ruta, home, None)
        if privada is not None and destino.is_relative_to(privada.resolve()):
            return [str(destino)]
    return []


def _reabre_privada(
    entrada: object, home: Path, sistema: str, carpeta: Path | None, permitidas: list[str]
) -> bool:
    """¿Una entrada de ``allowRead`` deja leer una ruta privada fuera de lo permitido?"""
    if not isinstance(entrada, str):
        return False
    ruta = _expandir(entrada, home, carpeta)
    if ruta is None:
        return False
    ruta = ruta.resolve()
    if any(ruta.is_relative_to(Path(p)) for p in permitidas):
        return False
    for privada in rutas_privadas(sistema):
        expandida = _expandir(privada, home, None)
        if expandida is None:
            continue
        expandida = expandida.resolve()
        if ruta.is_relative_to(expandida) or expandida.is_relative_to(ruta):
            return True
    return False


def leer_json(ruta: Path) -> dict:
    if not ruta.is_file():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErrorAislamiento("AJUSTES_ILEGIBLES", ruta.name) from exc
    if not isinstance(datos, dict):
        raise ErrorAislamiento("AJUSTES_ILEGIBLES", ruta.name)
    return datos


def _comprobar(lista: list, agente: str, ok: bool, texto: str) -> None:
    lista.append(Comprobacion(agente, "ok" if ok else "falta", texto))


def _seccion(datos: dict, clave: str) -> dict:
    valor = datos.get(clave)
    return valor if isinstance(valor, dict) else {}


def _lista(datos: dict, *camino: str) -> list:
    for clave in camino[:-1]:
        datos = _seccion(datos, clave)
    valor = datos.get(camino[-1])
    return valor if isinstance(valor, list) else []


def _fusionar_ajustes(base: dict, capas: list[dict]) -> dict:
    """Configuración efectiva: las capas posteriores ganan. Las listas se unen (como hace Claude Code); en Codex solo se depende de la precedencia de los escalares."""
    resultado = copy.deepcopy(base)
    for capa in capas:
        _fusionar_en(resultado, capa)
    return resultado


def _fusionar_en(destino: dict, capa: dict) -> None:
    for clave, valor in capa.items():
        actual = destino.get(clave)
        if isinstance(valor, dict) and isinstance(actual, dict):
            _fusionar_en(actual, valor)
        elif isinstance(valor, list) and isinstance(actual, list):
            destino[clave] = actual + [elemento for elemento in valor if elemento not in actual]
        else:
            destino[clave] = copy.deepcopy(valor)


def revisar_claude(
    ajustes: dict,
    sistema: str,
    proyecto: Sequence[tuple[str, dict]] = (),
    *,
    home: Path | None = None,
    carpeta: Path | None = None,
    servidor: str | None = None,
) -> list[Comprobacion]:
    """Con ``home`` revisa también ``allowRead``; con ``carpeta``, que se pueda leer.

    ``servidor`` es el del aula configurada; sin él (el agente no puede leer la
    configuración global), las comprobaciones de red quedan «no comprobadas».
    """
    lista: list[Comprobacion] = []
    efectivos = _fusionar_ajustes(ajustes, [datos for _, datos in proyecto])
    sandbox = _seccion(efectivos, "sandbox")
    permisos = _seccion(efectivos, "permissions")
    _comprobar(lista, CLAUDE, sandbox.get("enabled") is True, "sandbox activado")
    _comprobar(
        lista,
        CLAUDE,
        sandbox.get("allowUnsandboxedCommands") is False,
        "sin comandos fuera del sandbox",
    )
    if servidor is None:
        lista.append(
            Comprobacion(
                CLAUDE,
                "aviso",
                "red hacia el aula sin comprobar: no se pudo leer el servidor configurado",
            )
        )
    else:
        _comprobar(
            lista,
            CLAUDE,
            servidor in _lista(sandbox, "network", "deniedDomains"),
            f"red bloqueada hacia {servidor}",
        )
    faltan = [
        r for r in rutas_privadas(sistema) if r not in _lista(sandbox, "filesystem", "denyRead")
    ]
    _comprobar(
        lista,
        CLAUDE,
        not faltan,
        "sin lectura de navegadores ni Descargas"
        + (f" (faltan {len(faltan)} rutas)" if faltan else ""),
    )
    sin_leer_tiza = [r for r in rutas_tiza() if r not in _lista(sandbox, "filesystem", "denyRead")]
    _comprobar(
        lista,
        CLAUDE,
        not sin_leer_tiza,
        "sin lectura de la configuración ni la caché de tiza"
        + (f" (faltan {len(sin_leer_tiza)} rutas)" if sin_leer_tiza else ""),
    )
    sin_escribir_tiza = [
        r for r in rutas_tiza() if r not in _lista(sandbox, "filesystem", "denyWrite")
    ]
    _comprobar(
        lista,
        CLAUDE,
        not sin_escribir_tiza,
        "sin escritura en la configuración ni la caché de tiza"
        + (f" (faltan {len(sin_escribir_tiza)} rutas)" if sin_escribir_tiza else ""),
    )
    if home is not None:
        permitidas = rutas_reabiertas(home, sistema, carpeta) if carpeta is not None else []
        permitidos = _lista(sandbox, "filesystem", "allowRead")
        if permitidas:
            _comprobar(
                lista,
                CLAUDE,
                all(ruta in permitidos for ruta in permitidas),
                "carpeta de la asignatura legible dentro de Descargas",
            )
        reabiertas = [
            e for e in permitidos if _reabre_privada(e, home, sistema, carpeta, permitidas)
        ]
        if reabiertas:
            lista.append(
                Comprobacion(
                    CLAUDE,
                    "falta",
                    f"sandbox.filesystem.allowRead vuelve a abrir {len(reabiertas)} "
                    "rutas de navegadores o Descargas; quítalas",
                )
            )
    if servidor is None:
        lista.append(
            Comprobacion(
                CLAUDE,
                "aviso",
                "WebFetch hacia el aula sin comprobar: no se pudo leer el servidor configurado",
            )
        )
    else:
        _comprobar(
            lista,
            CLAUDE,
            all(regla in _lista(permisos, "deny") for regla in reglas_webfetch(servidor)),
            f"WebFetch bloqueado hacia {servidor}",
        )
    _comprobar(
        lista,
        CLAUDE,
        permisos.get("defaultMode") != "bypassPermissions",
        "sin modo de permisos desactivados",
    )
    for nombre, datos in proyecto:
        sandbox_p = _seccion(datos, "sandbox")
        permisos_p = _seccion(datos, "permissions")
        debilita = (
            (sandbox_p.get("enabled") is False and sandbox.get("enabled") is False)
            or (
                sandbox_p.get("allowUnsandboxedCommands") is True
                and sandbox.get("allowUnsandboxedCommands") is True
            )
            or (
                permisos_p.get("defaultMode") == "bypassPermissions"
                and permisos.get("defaultMode") == "bypassPermissions"
            )
        )
        if debilita:
            lista.append(
                Comprobacion(
                    CLAUDE,
                    "falta",
                    f"{nombre} de esta carpeta desactiva el sandbox o los permisos; quita esa línea",
                )
            )
    aporta = any(
        _seccion(datos, "sandbox") or _seccion(datos, "permissions") for _, datos in proyecto
    )
    if not aporta and not any(c.estado == "falta" for c in lista):
        lista.append(Comprobacion(CLAUDE, "aviso", AVISO_GLOBAL))
    if sistema == "Windows":
        lista.append(
            Comprobacion(
                CLAUDE,
                "aviso",
                "el sandbox de Claude Code no funciona en Windows nativo; usa WSL2 o un usuario del sistema sin acceso al aula",
            )
        )
    return lista


def _anadir(
    raiz: dict, camino: tuple[str, ...], valores: list[str], cambios: list[str], texto: str
) -> None:
    nodo = raiz
    for clave in camino[:-1]:
        nodo = nodo.setdefault(clave, {})
        if not isinstance(nodo, dict):
            raise ErrorAislamiento("AJUSTES_INESPERADOS", clave)
    lista = nodo.setdefault(camino[-1], [])
    if not isinstance(lista, list):
        raise ErrorAislamiento("AJUSTES_INESPERADOS", camino[-1])
    for valor in valores:
        if valor not in lista:
            lista.append(valor)
            cambios.append(texto.format(valor))


def fusionar_claude(
    ajustes: dict,
    sistema: str,
    reabrir: Sequence[str] = (),
    *,
    servidor: str | None = None,
) -> tuple[dict, list[str]]:
    """``reabrir``: la carpeta de la asignatura si está en Descargas (``rutas_reabiertas``).

    ``servidor`` es el del aula configurada: con él se añade el bloqueo de red y de
    WebFetch. Sin él (no se pudo leer la configuración), no se añade nada de red.
    """
    nuevo = copy.deepcopy(ajustes)
    cambios: list[str] = []
    sandbox = nuevo.setdefault("sandbox", {})
    permisos = nuevo.setdefault("permissions", {})
    if not isinstance(sandbox, dict) or not isinstance(permisos, dict):
        raise ErrorAislamiento("AJUSTES_INESPERADOS", "sandbox/permissions")
    if sandbox.get("enabled") is not True:
        sandbox["enabled"] = True
        cambios.append("activar el sandbox")
    if sandbox.get("allowUnsandboxedCommands") is not False:
        sandbox["allowUnsandboxedCommands"] = False
        cambios.append("impedir comandos fuera del sandbox")
    if "autoAllowBashIfSandboxed" not in sandbox:
        sandbox["autoAllowBashIfSandboxed"] = True
        cambios.append("no pedir permiso para comandos que ya van dentro del sandbox")
    if servidor is not None:
        _anadir(
            sandbox,
            ("network", "deniedDomains"),
            [servidor],
            cambios,
            "bloquear la red hacia {}",
        )
    _anadir(
        sandbox, ("filesystem", "denyRead"), rutas_privadas(sistema), cambios, "impedir leer {}"
    )
    _anadir(sandbox, ("filesystem", "denyRead"), rutas_tiza(), cambios, "impedir leer {}")
    _anadir(sandbox, ("filesystem", "denyWrite"), rutas_tiza(), cambios, "impedir escribir en {}")
    if reabrir:
        _anadir(
            sandbox,
            ("filesystem", "allowRead"),
            list(reabrir),
            cambios,
            "permitir leer solo esta carpeta dentro de Descargas ({})",
        )
    if servidor is not None:
        _anadir(permisos, ("deny",), reglas_webfetch(servidor), cambios, "bloquear {}")
    modo = permisos.get("defaultMode")
    if modo == "bypassPermissions":
        permisos["defaultMode"] = "default"
        cambios.append("quitar el modo de permisos desactivados")
    elif modo is None:
        # Fija el modo de permisos para que esta capa gane a un global débil.
        permisos["defaultMode"] = "default"
    return nuevo, cambios


CODEX = "Codex"
OPENCODE = "opencode"
COPILOT = "GitHub Copilot"
CONFIG_OPENCODE = ("opencode.json", "opencode.jsonc")
_MODOS_CODEX = {"read-only", "workspace-write"}


def ruta_claude(home: Path) -> Path:
    return home / ".claude" / "settings.json"


def ruta_codex(home: Path) -> Path:
    return home / ".codex" / "config.toml"


def ruta_claude_proyecto(carpeta: Path) -> Path:
    return carpeta / ".claude" / "settings.json"


def ruta_codex_proyecto(carpeta: Path) -> Path:
    return carpeta / ".codex" / "config.toml"


def revisar_codex(
    datos: dict,
    proyecto: Sequence[tuple[str, dict]] = (),
    *,
    confianza: bool = False,
) -> list[Comprobacion]:
    lista: list[Comprobacion] = []
    efectivos = _fusionar_ajustes(datos, [capa for _, capa in proyecto])
    _comprobar(
        lista,
        CODEX,
        efectivos.get("sandbox_mode") in _MODOS_CODEX,
        "sandbox limitado a la carpeta de trabajo",
    )
    _comprobar(
        lista, CODEX, efectivos.get("approval_policy") != "never", "pide permiso antes de actuar"
    )
    _comprobar(
        lista,
        CODEX,
        _seccion(efectivos, "sandbox_workspace_write").get("network_access") is not True,
        "sin red desde el sandbox",
    )
    aporta = any(
        "sandbox_mode" in datos or "approval_policy" in datos or "sandbox_workspace_write" in datos
        for _, datos in proyecto
    )
    if aporta and not confianza:
        lista.append(
            Comprobacion(
                CODEX,
                "falta",
                "la carpeta no está marcada como de confianza para Codex: su configuración no se carga",
            )
        )
    elif not aporta and not any(c.estado == "falta" for c in lista):
        lista.append(Comprobacion(CODEX, "aviso", AVISO_GLOBAL))
    lista.append(
        Comprobacion(
            CODEX,
            "aviso",
            "Codex no limita las lecturas: la caché y la configuración de tiza (con la URL "
            "del aula) quedan accesibles. No guardes datos de alumnado en "
            "este equipo ni tengas el aula abierta en el navegador con este usuario.",
        )
    )
    return lista


def fusionar_codex(texto: str) -> tuple[str | None, list[str], list[str]]:
    try:
        datos = tomllib.loads(texto)
    except tomllib.TOMLDecodeError as exc:
        raise ErrorAislamiento("AJUSTES_ILEGIBLES", "config.toml") from exc
    cabecera: list[str] = []
    cambios: list[str] = []
    manuales: list[str] = []
    modo = datos.get("sandbox_mode")
    if modo is None:
        cabecera.append('sandbox_mode = "workspace-write"')
        cambios.append("limitar el sandbox a la carpeta de trabajo")
    elif modo not in _MODOS_CODEX:
        manuales.append('cambia sandbox_mode a "workspace-write"')
    politica = datos.get("approval_policy")
    if politica is None:
        cabecera.append('approval_policy = "on-request"')
        cambios.append("pedir permiso antes de actuar")
    elif politica == "never":
        manuales.append('cambia approval_policy a "on-request"')
    tabla = datos.get("sandbox_workspace_write")
    cola = ""
    if tabla is None:
        cola = "[sandbox_workspace_write]\nnetwork_access = false\n"
        cambios.append("cortar la red desde el sandbox")
    elif isinstance(tabla, dict) and tabla.get("network_access") is True:
        manuales.append("cambia network_access a false en [sandbox_workspace_write]")
    if not cambios:
        return None, cambios, manuales
    # Las claves de primer nivel van antes de cualquier [tabla]: al principio.
    nuevo = ("\n".join(cabecera) + "\n" if cabecera else "") + texto
    if cola:
        nuevo = nuevo.rstrip("\n") + ("\n\n" if nuevo.strip() else "") + cola
    try:
        tomllib.loads(nuevo)
    except tomllib.TOMLDecodeError as exc:
        raise ErrorAislamiento("AJUSTES_INESPERADOS", "config.toml") from exc
    return nuevo, cambios, manuales


def _registro_proyecto(proyectos: dict, carpeta: Path) -> tuple[str | None, dict]:
    """Clave y registro existentes para esta carpeta, normalizando rutas."""
    for ruta, registro in proyectos.items():
        try:
            misma = Path(ruta).resolve() == carpeta.resolve()
        except (OSError, RuntimeError):
            misma = ruta == str(carpeta)
        if misma:
            return ruta, registro if isinstance(registro, dict) else {}
    return None, {}


def _proyecto_confiable(datos: dict, carpeta: Path) -> bool:
    proyectos = datos.get("projects")
    if not isinstance(proyectos, dict):
        return False
    _, registro = _registro_proyecto(proyectos, carpeta)
    return registro.get("trust_level") == "trusted"


def fusionar_confianza_codex(texto: str, carpeta: Path) -> tuple[str | None, list[str], list[str]]:
    """Marca la carpeta como de confianza para que Codex cargue su configuración."""
    try:
        datos = tomllib.loads(texto)
    except tomllib.TOMLDecodeError as exc:
        raise ErrorAislamiento("AJUSTES_ILEGIBLES", "config.toml") from exc
    proyectos = datos.get("projects")
    if proyectos is not None and not isinstance(proyectos, dict):
        raise ErrorAislamiento("AJUSTES_INESPERADOS", "projects")
    clave = str(carpeta.resolve())
    existente, registro = _registro_proyecto(proyectos or {}, carpeta)
    if existente is not None:
        if registro.get("trust_level") == "trusted":
            return None, [], []
        return None, [], [f'cambia trust_level a "trusted" en [projects."{existente}"]']
    nuevo = texto.rstrip("\n")
    tabla = f'[projects.{json.dumps(clave, ensure_ascii=False)}]\ntrust_level = "trusted"\n'
    nuevo = (nuevo + "\n\n" if nuevo else "") + tabla
    try:
        tomllib.loads(nuevo)
    except tomllib.TOMLDecodeError as exc:
        raise ErrorAislamiento("AJUSTES_INESPERADOS", "config.toml") from exc
    return nuevo, ["marcar esta carpeta como de confianza"], []


def _recurso_cubre_webfetch(recurso: object, host: str) -> bool:
    """¿La regla de recurso de opencode se aplica a este host?"""
    if not isinstance(recurso, str):
        return False
    if recurso == "*" or recurso == host:
        return True
    if recurso.startswith("*."):
        return host.endswith(recurso[1:])
    return False


def _opencode_deniega(datos: dict, accion: str, ruta: str) -> bool:
    """¿La última regla de opencode que cubre esa ruta deniega esa acción?"""
    objetivo = f"{Path(ruta).as_posix()}/**"
    efecto = None
    for regla in _lista(datos, "permissions"):
        if not isinstance(regla, dict) or regla.get("action") not in (accion, "*"):
            continue
        recurso = regla.get("resource", "*")
        if not isinstance(recurso, str):
            continue
        base = recurso.rstrip("*").rstrip("/")
        if recurso == "*" or recurso == objetivo or objetivo.startswith(base + "/"):
            efecto = regla.get("effect")
    return efecto == "deny"


def _opencode_bloquea_webfetch(datos: dict, servidor: str) -> bool:
    if _seccion(datos, "permission").get("webfetch") == "deny":
        return True
    # Versión 2: la última regla que coincide con el servidor decide.
    efecto = None
    for regla in _lista(datos, "permissions"):
        if (
            isinstance(regla, dict)
            and regla.get("action") in ("webfetch", "*")
            and _recurso_cubre_webfetch(regla.get("resource", "*"), servidor)
        ):
            efecto = regla.get("effect")
    return efecto == "deny"


def revisar_opencode(
    home: Path, carpeta: Path | None = None, *, servidor: str | None = None
) -> list[Comprobacion]:
    sin_sandbox = Comprobacion(
        OPENCODE,
        "aviso",
        "opencode no tiene sandbox de sistema: las reglas dependen de que confirmes cada comando",
    )
    candidatas: list[Path] = []
    if carpeta is not None:
        candidatas += [carpeta / nombre for nombre in ("opencode.json", "opencode.jsonc")]
    global_ = home / ".config" / "opencode"
    candidatas += [global_ / nombre for nombre in ("opencode.json", "opencode.jsonc")]
    ruta = next((r for r in candidatas if r.is_file()), None)
    if ruta is None:
        return [
            Comprobacion(
                OPENCODE,
                "falta",
                "no hay configuración; copia la de docs/aislamiento.md en la carpeta de la asignatura",
            ),
            sin_sandbox,
        ]
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [
            Comprobacion(
                OPENCODE,
                "aviso",
                f"{ruta.name} no se puede comprobar automáticamente; revísalo con docs/aislamiento.md",
            ),
            sin_sandbox,
        ]
    ok = isinstance(datos, dict) and (
        servidor is None or _opencode_bloquea_webfetch(datos, servidor)
    )
    if servidor is None:
        lista = [
            Comprobacion(
                OPENCODE,
                "aviso",
                "webfetch hacia el aula sin comprobar: no se pudo leer el servidor configurado",
            )
        ]
    else:
        lista = [
            Comprobacion(OPENCODE, "ok" if ok else "falta", f"webfetch bloqueado hacia {servidor}")
        ]
    faltan_tiza = [
        (accion, ruta_tiza)
        for ruta_tiza in rutas_tiza()
        for accion in ("read", "write")
        if not (isinstance(datos, dict) and _opencode_deniega(datos, accion, ruta_tiza))
    ]
    lista.append(
        Comprobacion(
            OPENCODE,
            "ok" if not faltan_tiza else "falta",
            "configuración y caché de tiza bloqueadas"
            + (f" (faltan {len(faltan_tiza)} reglas)" if faltan_tiza else ""),
        )
    )
    if ok and not faltan_tiza and (carpeta is None or ruta.parent != carpeta):
        lista.append(Comprobacion(OPENCODE, "aviso", AVISO_GLOBAL))
    lista.append(sin_sandbox)
    return lista


def ruta_copilot(home: Path) -> Path:
    """Directorio de datos de Copilot: ``COPILOT_HOME`` o ``~/.copilot``."""
    base = os.environ.get("COPILOT_HOME", "").strip()
    return Path(base) if base else home / ".copilot"


def _se_puede_leer(ruta: Path) -> bool:
    """Abre el fichero sin leerlo entero: sus claves (de API) no se muestran jamás."""
    try:
        with ruta.open("rb") as fichero:
            fichero.read(1)
    except OSError:
        return False
    return True


def _avisos_plataforma_copilot(sistema: str) -> list[Comprobacion]:
    """Requisitos del sandbox de Copilot; solo avisos: tiza no sabe si está activado."""
    if sistema == "Linux":
        faltan = [n for n in ("bwrap", "slirp4netns") if shutil.which(n) is None]
        if faltan:
            return [
                Comprobacion(
                    COPILOT,
                    "aviso",
                    "el sandbox de la app necesita "
                    + " y ".join(faltan)
                    + " en el PATH; sin ellos no funcionará",
                )
            ]
    elif sistema == "Windows":
        return [
            Comprobacion(
                COPILOT,
                "aviso",
                "en Windows el sandbox de la app exige Windows 11 25H2 o 26H1 con los parches "
                "de GitHub; si no, no funcionará",
            )
        ]
    return []


def revisar_copilot(home: Path, sistema: str, *, servidor: str | None = None) -> list[Comprobacion]:
    """Solo lectura y solo avisos: la app no permite comprobar su sandbox desde fuera.

    Si el fichero de ajustes del CLI no se puede leer, se avisa con
    ``AJUSTES_ILEGIBLES`` sin mostrar su contenido (puede tener claves de API).
    """
    ajustes = ruta_copilot(home) / "settings.json"
    if ajustes.exists() and (not ajustes.is_file() or not _se_puede_leer(ajustes)):
        return [Comprobacion(COPILOT, "falta", "AJUSTES_ILEGIBLES: settings.json")]
    lista = [
        Comprobacion(
            COPILOT,
            "aviso",
            "el sandbox se activa por proyecto (Ajustes › Proyectos › Sandbox) y tiza no puede "
            "comprobarlo; ejecuta «tiza aislar» para ver la receta",
        )
    ]
    if servidor is None:
        lista.append(
            Comprobacion(
                COPILOT,
                "aviso",
                "red hacia el aula sin comprobar: no se pudo leer el servidor configurado; "
                "deniégalo en el sandbox de la app si lo tienes configurado",
            )
        )
    else:
        lista.append(
            Comprobacion(COPILOT, "aviso", f"recuerda denegar la red hacia {servidor} en la app")
        )
    lista.append(
        Comprobacion(
            COPILOT,
            "aviso",
            "no está comprobado que el sandbox limite las lecturas internas del agente: "
            "la configuración y la caché de tiza podrían quedar legibles. No guardes datos "
            "de alumnado en este equipo ni tengas el aula abierta en el navegador con este usuario.",
        )
    )
    lista += _avisos_plataforma_copilot(sistema)
    return lista


def _ruta_de_la_receta(ruta: str, home: Path) -> str:
    expandida = _expandir(ruta, home, None)
    return str(expandida) if expandida is not None else ruta


def receta_copilot(sistema: str, home: Path, *, servidor: str | None = None) -> list[str]:
    """Receta para el sandbox de la app de Copilot: tiza no escribe su configuración.

    La app no admite comodines ni ``~``, así que las rutas van expandidas para
    este equipo; además del host del aula (si se conoce), se recuerda apagar la
    red local y las credenciales de git/gh, que vienen activadas por defecto.
    """
    leer = [_ruta_de_la_receta(ruta, home) for ruta in rutas_privadas(sistema) + rutas_tiza()]
    escribir = [_ruta_de_la_receta(ruta, home) for ruta in rutas_tiza()]
    lineas = [
        "GitHub Copilot app: activa el sandbox del proyecto (Ajustes › Proyectos › Sandbox) y añade:",
        "  - apaga «red local» y «credenciales de git/gh» (vienen activadas por defecto)",
        "  - rutas denegadas de lectura:",
        *[f"      {ruta}" for ruta in leer],
        "  - rutas denegadas de escritura:",
        *[f"      {ruta}" for ruta in escribir],
    ]
    if servidor is None:
        lineas.append(
            "  - dominio del aula: no se pudo leer el servidor configurado; deniégalo a mano"
        )
    else:
        lineas.append(f"  - dominio del aula denegado: {servidor}")
    lineas.append("  - no uses las sesiones en la nube de la app ni su «computer use»")
    return lineas


def contenido_opencode(sistema: str, reabrir: Sequence[str] = ()) -> str:
    """Configuración de opencode (v2) que ``revisar_opencode`` acepta como aislada.

    ``reabrir`` va al final porque en opencode gana la última regla que coincide.
    """
    permisos: list[dict[str, str]] = [
        {"action": "*", "resource": "*", "effect": "allow"},
        {"action": "external_directory", "resource": "*", "effect": "ask"},
        {"action": "shell", "resource": "*", "effect": "ask"},
        {"action": "webfetch", "resource": "*", "effect": "deny"},
        {"action": "websearch", "resource": "*", "effect": "deny"},
    ]
    permisos += [
        {"action": "read", "resource": f"{ruta}/**", "effect": "deny"}
        for ruta in rutas_privadas(sistema)
    ]
    permisos += [
        {"action": accion, "resource": f"{Path(ruta).as_posix()}/**", "effect": "deny"}
        for ruta in rutas_tiza()
        for accion in ("read", "write")
    ]
    permisos += [
        {"action": "read", "resource": f"{Path(ruta).as_posix()}/**", "effect": "allow"}
        for ruta in reabrir
    ]
    datos = {"$schema": "https://opencode.ai/config.json", "permissions": permisos}
    return json.dumps(datos, ensure_ascii=False, indent=2) + "\n"


def _declara_reglas_opencode(ruta: Path) -> bool:
    """¿La configuración de opencode trae reglas propias? Lo ilegible cuenta como sí."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return True
    return not isinstance(datos, dict) or "permissions" in datos or "permission" in datos


def configuracion_opencode(
    carpeta: Path, home: Path, sistema: str
) -> tuple[Path, str, list[str]] | None:
    """Propuesta para crear opencode.jsonc, o None si no se debe tocar nada.

    No toca una configuración que ya exista en la carpeta (puede tener
    comentarios o reglas propias) ni crea una nueva si el usuario ya tiene
    reglas en la global: la última regla que coincide gana, así que el
    ``allow`` general de la configuración de tiza debilitaría sus denegaciones.
    """
    if any((carpeta / nombre).exists() for nombre in CONFIG_OPENCODE):
        return None
    global_ = home / ".config" / "opencode"
    if any(
        (global_ / nombre).is_file() and _declara_reglas_opencode(global_ / nombre)
        for nombre in CONFIG_OPENCODE
    ):
        return None
    return (
        carpeta / "opencode.jsonc",
        contenido_opencode(sistema, rutas_reabiertas(home, sistema, carpeta)),
        ["crear opencode.jsonc con webfetch, websearch y perfiles de navegador bloqueados"],
    )


def revisar(home: Path, sistema: str, carpeta: Path) -> list[Comprobacion]:
    """Revisión completa, de solo lectura, de los agentes instalados.

    El servidor del aula sale de la configuración global; si no se puede leer
    (el agente no debería poder), las comprobaciones de red quedan «no
    comprobadas» y no se marca como falta.
    """
    lista: list[Comprobacion] = []
    servidor = servidor_configurado()
    if (home / ".claude").is_dir():
        try:
            proyecto = [
                (f".claude/{nombre}", leer_json(carpeta / ".claude" / nombre))
                for nombre in ("settings.json", "settings.local.json")
                if (carpeta / ".claude" / nombre).is_file()
            ]
            lista += revisar_claude(
                leer_json(ruta_claude(home)),
                sistema,
                proyecto,
                home=home,
                carpeta=carpeta,
                servidor=servidor,
            )
        except ErrorAislamiento as exc:
            lista.append(Comprobacion(CLAUDE, "falta", f"{exc.codigo}: {exc.detalle}"))
    if (home / ".codex").is_dir():
        ruta = ruta_codex(home)
        try:
            datos = tomllib.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {}
            ruta_proyecto = ruta_codex_proyecto(carpeta)
            proyecto = []
            if ruta_proyecto.is_file():
                proyecto = [
                    (str(ruta_proyecto), tomllib.loads(ruta_proyecto.read_text(encoding="utf-8")))
                ]
            lista += revisar_codex(datos, proyecto, confianza=_proyecto_confiable(datos, carpeta))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            lista.append(Comprobacion(CODEX, "falta", "AJUSTES_ILEGIBLES: config.toml"))
    if (home / ".config" / "opencode").is_dir() or any(
        (carpeta / nombre).is_file() for nombre in ("opencode.json", "opencode.jsonc")
    ):
        lista += revisar_opencode(home, carpeta, servidor=servidor)
    if ruta_copilot(home).is_dir():
        lista += revisar_copilot(home, sistema, servidor=servidor)
    if not lista:
        lista.append(
            Comprobacion(
                "—",
                "aviso",
                "no se ha encontrado Claude Code, Codex, opencode ni GitHub Copilot; "
                "configura tu agente con docs/aislamiento.md",
            )
        )
    return lista
