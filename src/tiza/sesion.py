"""La sesión del docente, sin terminal: login, cursos y ciclo de la sesión.

Es el lado de confianza de tiza. Habla con el docente solo a través de una
``Presencia`` (la terminal de ``tiza sesion`` o una ventana) y con el aula solo
a través de :mod:`tiza.publicar`. El estado que existe tras el login y la
atención de las peticiones del buzón viven en :mod:`tiza.sesion_abierta`; la
publicación en sí (puertas, resúmenes y confirmaciones), en
:mod:`tiza.publicacion`. No escribe en la consola, salvo la traza de ``--debug``:
lo que el docente ve lo decide la presencia, que además sanea los textos ajenos
(del agente o de Moodle).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import platformdirs

from . import (
    __version__,
    buzon,
    config,
    ficheros,
    informe,
    publicacion,
    publicar,
    rutas,
    sesion_abierta,
)
from .config import Config, ErrorConfig
from .publicacion import AVISO_DEBUG, Aviso, Presencia, depurar
from .publicar import AulaVirtual, ErrorPublicacion

__all__ = [
    "AMPLIACION_MINUTOS",
    "AVISO_MINUTOS",
    "CursoSesion",
    "ESPERA_RESPUESTA_SEGUNDOS",
    "MAX_MINUTOS",
    "SIN_PRUEBAS",
    "abrir",
    "autoprueba_con",
    "crear_dir_vistas",
]

MAX_MINUTOS = 480
AMPLIACION_MINUTOS = 30
AVISO_MINUTOS = 5
ESPERA_RESPUESTA_SEGUNDOS = 300
SIN_PRUEBAS = 0  # elegir_curso: el docente elige no tener curso de pruebas
VISTAS_VIEJAS_SEGUNDOS = 24 * 3600  # un directorio de vistas más viejo es de una sesión que murió


@dataclass(frozen=True)
class CursoSesion:
    """Un curso de la sesión tal como se le enseña al docente."""

    entorno: str  # "pruebas" o "real"
    id: int
    nombre: str | None  # de Moodle: solo para la presencia, nunca a .tiza
    ajeno: bool  # hay lista de cursos y este id no está en ella


def crear_dir_vistas(carpeta: str | Path | None = None) -> Path:
    """Directorio privado para las vistas previas, fuera de la carpeta de la asignatura.

    Lo usan la sesión y la publicación directa en real: el agente escribe en la
    carpeta de la asignatura y podría cambiar una vista previa entre que tiza la escribe y el docente la abre. Este directorio está
    en la caché del usuario, con nombre aleatorio y permisos 0700: un agente en
    un sandbox no llega a escribir en él. Si la caché no se puede usar, cae al
    directorio temporal del sistema (también 0700, pero ahí un sandbox que deje
    escribir en el temporal sí llegaría: es el último recurso).

    Con ``carpeta``, el directorio guarda dentro la carpeta de su sesión y, al
    crear uno nuevo, se borran los de sesiones que ya no están vivas (restos de
    un cierre brusco).
    """
    raiz = Path(platformdirs.user_cache_dir(config.APP)) / "vistas"
    try:
        raiz.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path(tempfile.mkdtemp(prefix="tiza-vistas-"))
    _borrar_sesiones_muertas(raiz)
    nuevo = Path(tempfile.mkdtemp(prefix="sesion-", dir=raiz))
    if carpeta is not None:
        try:
            ficheros.escribir_json(nuevo / "sesion.json", {"carpeta": str(Path(carpeta).resolve())})
        except OSError:
            pass  # sin la marca, otro arranque lo tratará como un directorio antiguo
    return nuevo


def _borrar_sesiones_muertas(raiz: Path) -> None:
    """Quita los directorios de sesiones que ya no están vivas (cierre brusco).

    Cada directorio guarda la carpeta de su sesión; si esa carpeta ya no tiene
    una sesión latiendo, el directorio entero (las vistas previas) se
    borra sin esperar 24 horas. Un directorio sin marca (versión antigua) solo
    se borra cuando es muy viejo, para no llevarse por delante una sesión viva.
    """
    limite = time.time() - VISTAS_VIEJAS_SEGUNDOS
    for ruta in raiz.glob("sesion-*"):
        try:
            try:
                marca = json.loads((ruta / "sesion.json").read_text(encoding="utf-8"))
                carpeta = marca.get("carpeta") if isinstance(marca, dict) else None
            except (OSError, json.JSONDecodeError):
                carpeta = None
            if isinstance(carpeta, str) and carpeta:
                if not buzon.sesion_activa(Path(carpeta) / rutas.CARPETA_TRABAJO):
                    shutil.rmtree(ruta, ignore_errors=True)
            elif ruta.stat().st_mtime < limite:
                shutil.rmtree(ruta, ignore_errors=True)
        except OSError:
            continue


def abrir(
    carpeta: str | Path,
    presencia: Presencia,
    *,
    minutos: int,
    preparar: bool = True,
    debug: bool = False,
    cerrar: threading.Event | None = None,
    dir_vistas: Path | None = None,
    elegir_cursos: bool = False,
) -> int:
    """Abre la sesión del docente en ``carpeta`` y atiende el buzón hasta cerrarla.

    Devuelve 0 si la sesión se abrió (y luego se cerró por tiempo, por el aula
    o por el docente) y 1 si no llegó a abrirse. Con ``preparar`` hace además lo
    que añade «tiza empezar»: la autoprueba si toca y la estructura.

    ``dir_vistas`` es el directorio privado de las vistas previas
    (``crear_dir_vistas``). Si no se da, la sesión crea el suyo y lo borra al cerrarse.
    Con ``elegir_cursos`` se vuelve a preguntar el curso de pruebas y los reales.
    """
    if dir_vistas is not None:
        return _abrir(
            carpeta,
            presencia,
            minutos=minutos,
            preparar=preparar,
            debug=debug,
            cerrar=cerrar,
            dir_vistas=dir_vistas,
            elegir_cursos=elegir_cursos,
        )
    propio = crear_dir_vistas(carpeta)
    try:
        return _abrir(
            carpeta,
            presencia,
            minutos=minutos,
            preparar=preparar,
            debug=debug,
            cerrar=cerrar,
            dir_vistas=propio,
            elegir_cursos=elegir_cursos,
        )
    finally:
        shutil.rmtree(propio, ignore_errors=True)


def _abrir(
    carpeta: str | Path,
    presencia: Presencia,
    *,
    minutos: int,
    preparar: bool,
    debug: bool,
    cerrar: threading.Event | None,
    dir_vistas: Path,
    elegir_cursos: bool,
) -> int:
    base = Path(carpeta).resolve()
    try:
        cfg = config.resolver(base)
    except ErrorConfig as exc:
        return _fallo("sesion", exc.codigo, exc.detalle, base, presencia, exc=exc, debug=debug)
    try:
        ficheros.asegurar_directorio(base / rutas.CARPETA_TRABAJO)
    except ficheros.FicheroNoSeguro as exc:
        detalle = f"«{rutas.CARPETA_TRABAJO}» es un enlace simbólico, no una carpeta"
        return _fallo(
            "sesion", "DIRECTORIO_NO_SEGURO", detalle, base, presencia, exc=exc, debug=debug
        )
    abierta = _iniciar(cfg, base, presencia, debug, elegir_cursos)
    if isinstance(abierta, int):
        return abierta
    cfg, aula, nombres = abierta
    if preparar:
        salida = _preparar(aula, cfg, base, presencia, debug)
        if salida is not None:
            return salida
    return _servir(
        aula,
        cfg,
        nombres,
        base,
        presencia,
        minutos=minutos,
        debug=debug,
        cerrar=cerrar,
        dir_vistas=dir_vistas,
    )


def autoprueba_con(
    aula: AulaVirtual, curso: int, carpeta: Path, presencia: Presencia, *, debug: bool = False
) -> bool:
    """Autoprueba con el aula ya abierta; si pasa, la registra para este curso escolar."""
    resultado = publicar.autoprueba(aula, curso)
    for causa in resultado.get("causas", []):
        depurar(causa, debug)
    pasos: list[informe.Paso] = [informe.Paso("LOGIN"), *resultado["pasos"]]
    sesion_abierta.registrar(
        informe.crear(
            "autoprueba", resultado["resultado"], pasos, [], resultado["errores"], "pruebas", curso
        ),
        carpeta,
        presencia,
    )
    if resultado["errores"]:
        return False
    config.registrar_autoprueba(curso, date.today(), __version__)
    return True


def _fallo(
    comando: str,
    codigo: str,
    detalle: str,
    base: Path,
    presencia: Presencia,
    *,
    entorno: str | None = None,
    curso: int | None = None,
    exc: BaseException | None = None,
    debug: bool = False,
) -> int:
    """La sesión no se pudo abrir: informe para el agente y explicación para el docente."""
    sesion_abierta.registrar(
        informe.crear(comando, "error", [], [], [codigo], entorno, curso), base, presencia
    )
    presencia.informar(Aviso("FALLO", {"codigo": codigo, "detalle": detalle}))
    if exc is not None:
        depurar(exc, debug)
    return 1


def _abortado(
    comando: str,
    base: Path,
    presencia: Presencia,
    entorno: str | None = None,
    curso: int | None = None,
) -> int:
    sesion_abierta.registrar(
        informe.crear(comando, "abortado", [], [], ["ABORTADO"], entorno, curso), base, presencia
    )
    presencia.informar(Aviso("CANCELADA"))
    return 1


def _iniciar(
    cfg: Config, base: Path, presencia: Presencia, debug: bool, elegir_cursos: bool = False
) -> tuple[Config, AulaVirtual, dict[int, str]] | int:
    """Contraseña, login y cursos; devuelve (cfg, aula, nombres) o el código de salida."""
    comando = "sesion"
    if buzon.sesion_activa(base / rutas.CARPETA_TRABAJO):
        return _fallo(
            comando,
            "SESION_YA_ABIERTA",
            "ya hay una «tiza sesion» abierta en esta carpeta",
            base,
            presencia,
        )
    password = presencia.pedir_password(urlsplit(cfg.url).hostname or cfg.url, cfg.usuario)
    if password is None:
        return _abortado(comando, base, presencia)
    try:
        aula = publicar.autenticar(cfg.url, cfg.usuario, password)
    except ErrorPublicacion as exc:
        entorno, curso = _entorno_del_informe(cfg)
        return _fallo(
            comando,
            exc.codigo,
            exc.detalle,
            base,
            presencia,
            entorno=entorno,
            curso=curso,
            exc=exc,
            debug=debug,
        )
    nombres = publicacion.nombres_de_cursos(aula, presencia, debug)
    try:
        completa = _completar_cursos(cfg, nombres, base, presencia, elegir=elegir_cursos)
    except ErrorConfig as exc:
        return _fallo(comando, exc.codigo, exc.detalle, base, presencia, exc=exc, debug=debug)
    if completa is None:
        return _abortado(comando, base, presencia)
    if not _confirmar_cursos(completa, nombres, presencia):
        entorno, curso = _entorno_del_informe(completa)
        return _abortado(comando, base, presencia, entorno, curso)
    if completa.sin_pruebas and not presencia.confirmar_sin_pruebas():
        return _abortado(
            comando,
            base,
            presencia,
            "real",
            completa.reales[0] if len(completa.reales) == 1 else None,
        )
    return completa, aula, nombres


def _entorno_del_informe(cfg: Config) -> tuple[str, int | None]:
    """Entorno y curso con que se informa de un fallo general (el curso, solo si es uno)."""
    if "pruebas" in cfg.cursos:
        return "pruebas", cfg.cursos["pruebas"]
    return "real", cfg.reales[0] if len(cfg.reales) == 1 else None


def _completar_cursos(
    cfg: Config,
    nombres: dict[int, str],
    base: Path,
    presencia: Presencia,
    *,
    elegir: bool = False,
) -> Config | None:
    """Pide los cursos que falten y los guarda en el tiza.toml de la carpeta.

    Hace falta al menos un curso real; el de pruebas se puede dejar sin configurar
    (``SIN_PRUEBAS``): en real solo se publicará oculto y no se vuelve a preguntar.
    Con ``elegir`` se vuelve a preguntar todo, aunque ya esté configurado.
    """
    if not elegir and cfg.reales and ("pruebas" in cfg.cursos or cfg.sin_pruebas):
        return cfg
    lista = [{"id": curso, "nombre": nombre} for curso, nombre in nombres.items()]
    pruebas = None if elegir else cfg.cursos.get("pruebas")
    reales = () if elegir else cfg.reales
    sin_pruebas = False if elegir else cfg.sin_pruebas
    if pruebas is None and not sin_pruebas:
        curso = presencia.elegir_curso("pruebas", lista, reales[0] if reales else None)
        if curso is None:
            return None
        if curso == SIN_PRUEBAS:
            sin_pruebas = True
        else:
            pruebas = curso
    if not reales:
        elegidos = presencia.elegir_cursos_reales(lista, pruebas)
        if not elegidos:
            return None
        reales = tuple(elegidos)
    cursos: dict[str, Any] = {"real": list(reales)}
    if pruebas is not None:
        cursos["pruebas"] = pruebas
    ruta = config.guardar_carpeta(base, cursos, sin_pruebas=sin_pruebas)
    presencia.informar(Aviso("CURSOS_GUARDADOS", {"ruta": ruta}))
    return config.resolver(base)


def _confirmar_cursos(cfg: Config, nombres: dict[int, str], presencia: Presencia) -> bool:
    ids = [("pruebas", cfg.cursos["pruebas"])] if "pruebas" in cfg.cursos else []
    ids += [("real", curso) for curso in cfg.reales]
    cursos = [
        CursoSesion(
            entorno=entorno,
            id=curso,
            nombre=nombres.get(curso),
            ajeno=bool(nombres) and curso not in nombres,
        )
        for entorno, curso in ids
    ]
    return presencia.confirmar_cursos(cursos)


def _preparar(
    aula: AulaVirtual, cfg: Config, base: Path, presencia: Presencia, debug: bool
) -> int | None:
    """Lo que añade «tiza empezar»: autoprueba si toca y estructura; None si se sigue."""
    pruebas = cfg.cursos.get("pruebas")
    if (
        pruebas is not None
        and config.necesita_autoprueba(pruebas, date.today(), __version__)
        and presencia.confirmar_autoprueba()
        and not autoprueba_con(aula, pruebas, base, presencia, debug=debug)
    ):
        presencia.informar(Aviso("AUTOPRUEBA_FALLIDA"))
        return 1
    documento = sesion_abierta.registrar(
        sesion_abierta.estructura_con(aula, cfg, base, debug=debug), base, presencia
    )
    if "SESION_CADUCADA" in documento["errores"]:
        return 1
    if documento["resultado"] != "ok":
        presencia.informar(Aviso("ESTRUCTURA_NO_LEIDA"))
    return None


def _servir(
    aula: AulaVirtual,
    cfg: Config,
    nombres: dict[int, str],
    base: Path,
    presencia: Presencia,
    *,
    minutos: int,
    debug: bool,
    cerrar: threading.Event | None,
    dir_vistas: Path,
) -> int:
    """Tras el login: atiende el buzón hasta que se cierre la sesión."""
    dir_tiza = base / rutas.CARPETA_TRABAJO
    apertura = datetime.now(UTC)
    caduca = apertura + timedelta(minutes=minutos)
    abierta = sesion_abierta.SesionAbierta(
        aula, cfg, base, presencia, nombres=nombres, dir_vistas=dir_vistas, debug=debug
    )
    try:
        with buzon.abrir_sesion(dir_tiza, caduca) as actual:
            _atender(dir_tiza, abierta.atender, apertura, actual, presencia, debug, cerrar)
    except buzon.ErrorBuzon as exc:
        return _fallo("sesion", exc.codigo, exc.detalle, base, presencia)
    except KeyboardInterrupt:
        presencia.informar(Aviso("SESION_CERRADA", {"motivo": "docente"}))
    return 0


def _atender(
    dir_tiza: Path,
    procesar: Callable[[dict], dict],
    apertura: datetime,
    abierta: buzon.SesionAbierta,
    presencia: Presencia,
    debug: bool,
    cerrar: threading.Event | None = None,
) -> None:
    """Atiende el buzón y ofrece ampliar hasta que se cierre la sesión."""
    presencia.informar(Aviso("SESION_ABIERTA", {"caduca": abierta.caduca}))
    motivos: list[str] = []

    def terminar(documento: dict) -> bool:
        if "SESION_DESACTUALIZADA" in documento["errores"]:
            motivos.append("desactualizada")
        elif "SESION_CADUCADA" in documento["errores"]:
            motivos.append("aula")
        return bool(motivos)

    while True:
        cerrada = buzon.atender(
            dir_tiza,
            procesar,
            abierta.caduca,
            terminar=terminar,
            al_fallar=lambda exc: _error_interno(exc, presencia, debug),
            al_esperar=_aviso_previo(abierta, presencia),
            parar=cerrar.is_set if cerrar is not None else None,
        )
        if cerrar is not None and cerrar.is_set():
            presencia.informar(Aviso("SESION_CERRADA", {"motivo": "docente"}))
            return
        if cerrada:
            presencia.informar(Aviso("SESION_CERRADA", {"motivo": motivos[-1]}))
            return
        nueva = _ofrecer_ampliacion(apertura, abierta.caduca, presencia)
        if nueva is None:
            presencia.informar(Aviso("SESION_CERRADA", {"motivo": "caducada"}))
            return
        abierta.ampliar(nueva)
        presencia.informar(Aviso("SESION_ABIERTA", {"caduca": nueva}))


def _aviso_previo(abierta: Any, presencia: Presencia) -> Callable[[], None]:
    """Avisa una vez cuando queden AVISO_MINUTOS para el final."""
    avisado = False

    def avisar() -> None:
        nonlocal avisado
        if not avisado and abierta.caduca - buzon.ahora_utc() <= timedelta(minutes=AVISO_MINUTOS):
            avisado = True
            presencia.informar(Aviso("QUEDAN_MINUTOS", {"minutos": AVISO_MINUTOS}))

    return avisar


def _ofrecer_ampliacion(
    apertura: datetime,
    caduca: datetime,
    presencia: Presencia,
    ahora: Callable[[], datetime] | None = None,
) -> datetime | None:
    """Nueva caducidad si el docente amplía; None si no responde o dice que no."""
    reloj = ahora or buzon.ahora_utc
    maximo = apertura + timedelta(minutes=MAX_MINUTOS)
    if max(reloj(), caduca) >= maximo - timedelta(minutes=1):
        presencia.informar(Aviso("MAXIMO_ALCANZADO", {"horas": MAX_MINUTOS // 60}))
        return None
    if not presencia.ofrecer_ampliacion(AMPLIACION_MINUTOS, ESPERA_RESPUESTA_SEGUNDOS):
        return None
    return min(max(reloj(), caduca) + timedelta(minutes=AMPLIACION_MINUTOS), maximo)


def _error_interno(exc: BaseException, presencia: Presencia, debug: bool) -> None:
    """El docente ve el tipo de fallo; el agente solo recibe ERROR_INTERNO."""
    presencia.informar(Aviso("ERROR_INTERNO", {"tipo": type(exc).__name__}))
    if debug:
        print(AVISO_DEBUG, file=sys.stderr)
        traceback.print_exception(exc)
