"""Configuración local de `tiza`: URL, usuario y cursos. Nunca contraseñas.

La configuración global vive en el directorio de configuración del sistema
(platformdirs). Cada carpeta de asignatura puede sobreescribir los ids de
curso con un ``tiza.toml``.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import platformdirs
import requests

from . import rutas
from .ficheros import escribir_json, escribir_texto

__all__ = [
    "AdaptadorAula",
    "Config",
    "DestinoNoPermitido",
    "ErrorConfig",
    "cargar_carpeta",
    "guardar_carpeta",
    "guardar_global",
    "inicio_de_curso",
    "necesita_autoprueba",
    "preparar_url",
    "registrar_autoprueba",
    "resolver",
    "validar_url",
]

APP = "tiza"


class ErrorConfig(Exception):
    """Error de configuración con un código estable."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


@dataclass(frozen=True)
class Config:
    url: str
    usuario: str
    cursos: dict[str, int]
    sin_pruebas: bool = False  # el docente eligió no tener curso de pruebas


def directorio_global() -> Path:
    return Path(platformdirs.user_config_dir(APP))


def ruta_global() -> Path:
    return directorio_global() / "config.json"


def cargar_global() -> dict | None:
    ruta = ruta_global()
    if not ruta.is_file():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErrorConfig("CONFIG_ILEGIBLE") from exc
    if not isinstance(datos, dict):
        raise ErrorConfig("CONFIG_ILEGIBLE")
    return datos


class DestinoNoPermitido(requests.exceptions.RequestException):
    """Una petición iba hacia un servidor que no es el del aula; no llegó a salir."""


# Solo ASCII visible y sin barras invertidas: ahí discrepan los analizadores de URL.
_CARACTERES_NO_VALIDOS = re.compile(r"[^\x21-\x7e]|\\")
_SERVIDOR = re.compile(r"\A[a-z0-9.-]+(?::[0-9]{1,5})?\Z")
_PUERTO_POR_DEFECTO = {"https": 443, "http": 80}


def _url_no_permitida() -> ErrorConfig:
    return ErrorConfig("URL_NO_PERMITIDA", "la URL debe ser https, sin usuario ni contraseña")


def validar_url(url: str) -> str:
    """Solo https: ahí es donde se envía la contraseña.

    Además de leerla como ``urlsplit``, se comprueba que ``requests`` (que es quien conecta)
    la lee igual: una barra invertida o un ``%2f`` pueden hacer que cada uno lea un servidor
    distinto. El servidor concreto se fija al configurar y lo guarda ``AdaptadorAula``.
    """
    if not isinstance(url, str) or _CARACTERES_NO_VALIDOS.search(url):
        raise _url_no_permitida()
    partes = urlsplit(url)
    if (
        partes.scheme != "https"
        or partes.username is not None
        or partes.password is not None
        or not _SERVIDOR.match(partes.netloc.lower())
    ):
        raise _url_no_permitida()
    try:
        leida_por_requests = urlsplit(requests.Request("GET", url).prepare().url)
        coincide = (leida_por_requests.hostname, leida_por_requests.port) == (
            partes.hostname,
            partes.port,
        )
    except (requests.RequestException, ValueError):
        coincide = False
    if not coincide:
        raise _url_no_permitida()
    return url


def _destino_legible(url: str | None) -> str:
    """Esquema y servidor de una URL, solo con caracteres seguros: para la traza de --debug."""
    try:
        partes = urlsplit(url or "")
        destino = f"{partes.scheme}://{partes.hostname or '?'}"
    except ValueError:
        destino = "?"
    return re.sub(r"[^a-z0-9.:/-]", "?", destino.lower())[:120]


def _servidor_de(url: str) -> tuple[str, str, int]:
    """Esquema, servidor y puerto de una URL (el puerto por defecto si no lo lleva)."""
    partes = urlsplit(url)
    esquema = partes.scheme.lower()
    return (
        esquema,
        (partes.hostname or "").lower(),
        partes.port or _PUERTO_POR_DEFECTO.get(esquema, 0),
    )


def _mismo_servidor(url: str, servidor: tuple[str, str, int]) -> bool:
    """¿La URL va al esquema, servidor y puerto exactos de ``servidor``?"""
    if not url:
        return False
    try:
        partes = urlsplit(url)
        if partes.username is not None or partes.password is not None:
            return False
        return _servidor_de(url) == servidor
    except ValueError:
        return False


class AdaptadorAula(requests.adapters.HTTPAdapter):
    """Adaptador de ``requests`` que solo deja salir peticiones hacia el servidor del aula.

    Se monta en la sesión del aula con la URL guardada en la configuración global
    (esquema, servidor y puerto exactos): cada petición y **cada redirección** pasan por
    ``send``, así que ni la contraseña ni las cookies salen hacia otro servidor aunque
    python-moodle componga mal una URL o el aula redirija fuera. Lanza
    ``DestinoNoPermitido`` antes de enviar nada.
    """

    def __init__(self, servidor: str, **opciones: Any) -> None:
        self._permitido = _servidor_de(servidor)
        self._destino = f"{self._permitido[0]}://{self._permitido[1]}"
        if self._permitido[2] != _PUERTO_POR_DEFECTO.get(self._permitido[0]):
            self._destino += f":{self._permitido[2]}"
        super().__init__(**opciones)

    def send(self, request, *args, **opciones):
        if not _mismo_servidor(request.url or "", self._permitido):
            raise DestinoNoPermitido(
                f"petición bloqueada hacia {_destino_legible(request.url)}: "
                f"solo se permite {self._destino}"
            )
        return super().send(request, *args, **opciones)


_SUFIJO_LOGIN = "/login/index.php"
_REDIRECCIONES = frozenset({301, 302, 303, 307, 308})
_MAX_SALTOS = 5


def _error_redirige_fuera() -> ErrorConfig:
    return ErrorConfig(
        "URL_REDIRIGE_FUERA",
        "el aula redirige a otro servidor o puerto; escribe su dirección final.",
    )


def _reconducir(actual: str, destino: str, servidor: tuple[str, str, int]) -> str:
    """Destino de una redirección, reconducido a https si es del mismo servidor.

    Un Apache detrás de un proxy añade la barra final redirigiendo por http o por su
    puerto interno, y otros mandan a http la página de entrada; el navegador lo
    sigue sin que se note. Aquí no se sigue: se pide lo mismo por https al servidor
    del aula. Cualquier otro destino se devuelve tal cual (y se rechaza después).
    """
    try:
        partes, de_ahora = urlsplit(destino), urlsplit(actual)
        puerto = partes.port
    except ValueError:
        return destino
    if (
        partes.username is not None
        or partes.password is not None
        or (partes.hostname or "").lower() != servidor[1]
    ):
        return destino
    netloc = servidor[1] if servidor[2] == 443 else f"{servidor[1]}:{servidor[2]}"
    if partes.path == de_ahora.path + "/" and partes.query == de_ahora.query:
        return urlunsplit(("https", netloc, partes.path, partes.query, ""))
    if partes.scheme.lower() == "http" and puerto in (None, 80):
        return urlunsplit(("https", netloc, partes.path, partes.query, ""))
    return destino


def preparar_url(entrada: str) -> str:
    """URL base del aula a partir de lo que escribe el docente.

    Convierte http en https y valida el servidor **antes** de conectar; después
    sigue las redirecciones a mano: cada salto tiene que quedarse en el mismo
    servidor y puerto (si no, ``URL_REDIRIGE_FUERA``) y al final se quita
    ``/login/index.php``. La barra final o el paso a http del propio servidor se
    piden por https (``_reconducir``): nunca se conecta por http.
    """
    entrada = entrada.strip()
    if entrada.startswith("http://"):
        entrada = "https://" + entrada[len("http://") :]
    elif not entrada.startswith("https://"):
        entrada = "https://" + entrada
    validar_url(entrada)  # antes de conectar: nada sale hacia otros servidores
    servidor = _servidor_de(entrada)
    url = entrada
    for _ in range(_MAX_SALTOS + 1):
        try:
            respuesta = requests.get(url, allow_redirects=False, timeout=15)
        except requests.RequestException as exc:
            raise ErrorConfig("URL_INACCESIBLE", "no se pudo abrir la URL del aula.") from exc
        url = getattr(respuesta, "url", None) or url
        try:
            validar_url(url)
        except ErrorConfig as exc:
            raise _error_redirige_fuera() from exc
        if _servidor_de(url) != servidor:
            raise _error_redirige_fuera()
        cabeceras = getattr(respuesta, "headers", None) or {}
        destino = cabeceras.get("Location")
        if respuesta.status_code not in _REDIRECCIONES or not destino:
            break
        url = _reconducir(url, urljoin(url, destino), servidor)
        try:
            validar_url(url)
        except ErrorConfig as exc:
            raise _error_redirige_fuera() from exc
        if _servidor_de(url) != servidor:
            raise _error_redirige_fuera()
    else:
        raise ErrorConfig("URL_INVALIDA", "el aula encadena demasiadas redirecciones.")
    if respuesta.status_code >= 400:
        raise ErrorConfig("URL_INVALIDA", "la URL del aula no responde correctamente.")
    base = url.rstrip("/")
    validar_url(base)
    if base.endswith(_SUFIJO_LOGIN):
        base = base[: -len(_SUFIJO_LOGIN)].rstrip("/")
    return base


def guardar_global(url: str, usuario: str, cursos: dict[str, int]) -> Path:
    """Guarda la configuración global."""
    validar_url(url)
    _validar_curso(cursos)
    datos: dict[str, Any] = {"version": 1, "url": url, "usuario": usuario, "cursos": cursos}
    return escribir_json(directorio_global() / "config.json", datos)


def cargar_carpeta(carpeta: str | Path) -> dict:
    ruta = Path(carpeta) / rutas.FICHERO_ASIGNATURA
    if not ruta.is_file():
        return {}
    try:
        datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ErrorConfig("TIZA_TOML_INVALIDO") from exc
    if not isinstance(datos, dict):
        raise ErrorConfig("TIZA_TOML_INVALIDO")
    return datos


_CLAVE_TOML = re.compile(r"\A[A-Za-z0-9_-]+\Z")


def guardar_carpeta(
    carpeta: str | Path, cursos: dict[str, int], *, sin_pruebas: bool = False
) -> Path:
    """Fusiona ``cursos`` en ``<carpeta>/tiza.toml``.

    Solo reescribe un tiza.toml que contenga únicamente ``[cursos]`` y sin
    comentarios; si hay más, no lo toca y pide editarlo a mano. Con
    ``sin_pruebas`` guarda que el docente no quiere curso de pruebas (y quita
    cualquier id de pruebas que hubiera).
    """
    _validar_curso(cursos)
    if not isinstance(sin_pruebas, bool):
        raise ErrorConfig("CURSO_INVALIDO")
    ruta = Path(carpeta) / rutas.FICHERO_ASIGNATURA
    if ruta.is_symlink():
        # El agente escribe en la carpeta: no se escribe a través de un enlace.
        raise ErrorConfig(
            "TIZA_TOML_INVALIDO",
            f"{rutas.FICHERO_ASIGNATURA} es un enlace simbólico; edítalo a mano",
        )
    if ruta.is_file():
        try:
            contenido = ruta.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ErrorConfig("TIZA_TOML_INVALIDO") from exc
        if "#" in contenido:
            raise ErrorConfig(
                "TIZA_TOML_INVALIDO",
                f"{rutas.FICHERO_ASIGNATURA} tiene comentarios; edítalo a mano",
            )
    datos = cargar_carpeta(carpeta)
    if set(datos) - {"cursos"}:
        raise ErrorConfig(
            "TIZA_TOML_INVALIDO",
            f"{rutas.FICHERO_ASIGNATURA} tiene más datos que [cursos]; edítalo a mano",
        )
    fuente = datos.get("cursos", {})
    if not isinstance(fuente, dict):
        raise ErrorConfig("CURSO_INVALIDO")
    _validar_curso(fuente)
    actuales = {clave: valor for clave, valor in fuente.items() if clave != "sin_pruebas"}
    actuales.update(cursos)
    if sin_pruebas:
        actuales.pop("pruebas", None)
    if any(not _CLAVE_TOML.match(clave) for clave in actuales):
        raise ErrorConfig(
            "TIZA_TOML_INVALIDO",
            f"nombre de curso no válido en {rutas.FICHERO_ASIGNATURA}",
        )
    if "pruebas" in actuales and actuales.get("pruebas") == actuales.get("real"):
        raise ErrorConfig("CURSOS_IGUALES", "pruebas y real no pueden ser el mismo curso")
    lineas = ["[cursos]"] + [f"{clave} = {valor}" for clave, valor in sorted(actuales.items())]
    if sin_pruebas:
        lineas.append("sin_pruebas = true")
    escribir_texto(ruta, "\n".join(lineas) + "\n")
    return ruta


def resolver(carpeta: str | Path) -> Config:
    global_ = cargar_global()
    if global_ is None:
        raise ErrorConfig("SIN_CONFIGURAR")
    datos_carpeta = cargar_carpeta(carpeta)
    url = global_.get("url")
    usuario = global_.get("usuario")
    if not isinstance(url, str) or not url or not isinstance(usuario, str) or not usuario:
        raise ErrorConfig("CONFIG_INCOMPLETA")
    cursos: dict[str, int] = {}
    sin_pruebas = False
    for fuente in (global_.get("cursos", {}), datos_carpeta.get("cursos", {})):
        if not isinstance(fuente, dict):
            raise ErrorConfig("CURSO_INVALIDO")
        _validar_curso(fuente)
        if isinstance(fuente.get("sin_pruebas"), bool):
            sin_pruebas = fuente["sin_pruebas"]
        cursos.update({clave: valor for clave, valor in fuente.items() if clave != "sin_pruebas"})
    # Un curso de pruebas explícito de la carpeta manda sobre la marca de «sin pruebas».
    if isinstance(datos_carpeta.get("cursos"), dict) and "pruebas" in datos_carpeta["cursos"]:
        sin_pruebas = False
    if sin_pruebas:
        cursos.pop("pruebas", None)
    validar_url(url)
    if "pruebas" in cursos and cursos.get("pruebas") == cursos.get("real"):
        raise ErrorConfig("CURSOS_IGUALES", "pruebas y real no pueden ser el mismo curso")
    return Config(
        url=url.rstrip("/"),
        usuario=usuario,
        cursos=cursos,
        sin_pruebas=sin_pruebas,
    )


def _validar_curso(cursos: dict) -> None:
    if not isinstance(cursos, dict):
        raise ErrorConfig("CURSO_INVALIDO")
    for clave, valor in cursos.items():
        if not isinstance(clave, str):
            raise ErrorConfig("CURSO_INVALIDO")
        if clave == "sin_pruebas":
            if not isinstance(valor, bool):
                raise ErrorConfig("CURSO_INVALIDO")
            continue
        if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
            raise ErrorConfig("CURSO_INVALIDO")


# --------------------------------------------------------------------------- #
# Estado: última autoprueba correcta por curso de pruebas
# --------------------------------------------------------------------------- #


def _ruta_estado() -> Path:
    return directorio_global() / "estado.json"


def _leer_estado() -> dict:
    """Estado local; si falta o está dañado, como si no hubiera nada."""
    try:
        datos = json.loads(_ruta_estado().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return datos if isinstance(datos, dict) else {}


def inicio_de_curso(hoy: date) -> date:
    return date(hoy.year if hoy.month >= 9 else hoy.year - 1, 9, 1)


def necesita_autoprueba(curso: int, hoy: date, version: str) -> bool:
    registros = _leer_estado().get("autoprueba")
    registro = registros.get(str(curso)) if isinstance(registros, dict) else None
    if not isinstance(registro, dict) or registro.get("version") != version:
        return True
    try:
        fecha = date.fromisoformat(registro.get("fecha"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True
    return fecha < inicio_de_curso(hoy)


def registrar_autoprueba(curso: int, hoy: date, version: str) -> Path:
    datos = _leer_estado()
    registros = datos.get("autoprueba")
    if not isinstance(registros, dict):
        registros = {}
    registros[str(curso)] = {"fecha": hoy.isoformat(), "version": version}
    datos["autoprueba"] = registros
    return escribir_json(_ruta_estado(), datos)
