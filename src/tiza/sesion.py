"""La sesión del docente, sin terminal: login, cursos y ciclo de la sesión.

Es el lado de confianza de tiza. Habla con el docente solo a través de una
``Presencia`` (la terminal de ``tiza sesion``) y con el aula solo
a través de :mod:`tiza.publicar`. El estado que existe tras el login y la
atención de las peticiones del buzón viven en :mod:`tiza.sesion_abierta`; la
publicación en sí (puertas, resúmenes y confirmaciones), en
:mod:`tiza.publicacion`. No escribe en la consola, salvo la traza de ``--debug``:
lo que el docente ve lo decide la presencia, que además sanea los textos ajenos
(del agente o de Moodle).
"""

from __future__ import annotations

import json
import os
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
    "ESPERA_CIERRE_SEGUNDOS",
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
PEDIR_CIERRE = "cerrar"  # en el directorio privado de una sesión: otra de su carpeta le pide irse
ESPERA_CIERRE_SEGUNDOS = 30.0  # lo que espera «tiza empezar» a que se vaya la sesión anterior
INTERVALO_CIERRE = 0.5
PLAZO_CIERRE_AULA = 5.0  # al irse a media pregunta, lo que se espera a cerrar la sesión del aula


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

    Con ``carpeta``, el directorio guarda dentro la carpeta y el pid de su sesión
    (así otro «tiza empezar» de la carpeta puede pedirle que se cierre) y, al crear
    uno nuevo, se borran los de sesiones que ya no están vivas (restos de un cierre
    brusco).
    """
    raiz = _raiz_vistas()
    try:
        raiz.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path(tempfile.mkdtemp(prefix="tiza-vistas-"))
    _borrar_sesiones_muertas(raiz)
    nuevo = Path(tempfile.mkdtemp(prefix="sesion-", dir=raiz))
    if carpeta is not None:
        try:
            ficheros.escribir_json(
                nuevo / "sesion.json",
                {"carpeta": str(Path(carpeta).resolve()), "pid": os.getpid()},
            )
        except OSError:
            pass  # sin la marca, otro arranque lo tratará como un directorio antiguo
    return nuevo


def _raiz_vistas() -> Path:
    return Path(platformdirs.user_cache_dir(config.APP)) / "vistas"


def _marca(ruta: Path) -> dict | None:
    """La marca del directorio privado ``ruta`` (carpeta y pid de su sesión), o None."""
    try:
        marca = json.loads((ruta / "sesion.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return marca if isinstance(marca, dict) else None


def _privados_de(carpeta: Path, pid: int, propio: Path | None) -> list[Path]:
    """Los directorios privados de las sesiones de ``carpeta`` con ese ``pid``, salvo ``propio``.

    Están en la caché del usuario, que el agente no escribe: el pid de ``sesion.json``
    del buzón solo vale si coincide con el de una de estas marcas.
    """
    destino = str(Path(carpeta).resolve())
    encontrados = []
    for ruta in _raiz_vistas().glob("sesion-*"):
        if propio is not None and ruta.resolve() == Path(propio).resolve():
            continue
        marca = _marca(ruta)
        if marca is None or isinstance(marca.get("pid"), bool):
            continue
        if marca.get("carpeta") == destino and marca.get("pid") == pid:
            encontrados.append(ruta)
    return encontrados


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
            marca = _marca(ruta)
            carpeta = marca.get("carpeta") if marca is not None else None
            if isinstance(carpeta, str) and carpeta:
                # Una sesión que late, sea de la versión que sea, conserva su directorio.
                if buzon.otra_sesion(Path(carpeta) / rutas.CARPETA_TRABAJO) is None:
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
    abierta = _iniciar(cfg, base, presencia, debug, elegir_cursos, propio=dir_vistas)
    if isinstance(abierta, int):
        return abierta
    cfg, aula, nombres = abierta
    try:
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
    finally:
        publicar.cerrar_aula(aula)  # la cookie deja de valer en cuanto se acaba la sesión


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
    presencia.informar(Aviso.fallo(codigo, detalle))
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
    presencia.informar(Aviso.cancelada())
    return 1


def _cerrar_anterior(base: Path, presencia: Presencia, propio: Path | None) -> int | None:
    """Si otra sesión late en la carpeta, ofrece cerrarla; None si la carpeta queda libre.

    Pasa cuando su terminal se cerró y la sesión siguió viva sin nadie delante. Solo se
    le puede pedir a una sesión de tiza con directorio privado para esta carpeta y el pid
    de ``sesion.json``; la sesión se cierra sola (:class:`_Cierre`), tiza no mata procesos.
    """
    comando = "sesion"
    dir_tiza = base / rutas.CARPETA_TRABAJO
    otra = buzon.otra_sesion(dir_tiza)
    if otra is None:
        return None
    privados = _privados_de(base, otra.pid, propio)
    if not privados:
        return _fallo(
            comando,
            "SESION_YA_ABIERTA",
            "ya hay una «tiza sesion» abierta en esta carpeta y no se puede cerrar desde aquí",
            base,
            presencia,
        )
    if not presencia.cerrar_sesion_anterior(otra.atendiendo):
        return _fallo(
            comando,
            "SESION_YA_ABIERTA",
            "ya hay una «tiza sesion» abierta en esta carpeta",
            base,
            presencia,
        )
    for privado in privados:
        try:
            (privado / PEDIR_CIERRE).touch()
        except OSError:
            pass
    presencia.informar(Aviso.cerrando_sesion_anterior())
    limite = time.monotonic() + ESPERA_CIERRE_SEGUNDOS
    while not buzon.carpeta_libre(dir_tiza):
        if time.monotonic() >= limite:
            # La petición se queda: la sesión anterior se irá al acabar lo que publica.
            return _fallo(comando, "SESION_ANTERIOR_OCUPADA", "", base, presencia)
        time.sleep(INTERVALO_CIERRE)
    presencia.informar(Aviso.sesion_anterior_cerrada())
    return None


def _iniciar(
    cfg: Config,
    base: Path,
    presencia: Presencia,
    debug: bool,
    elegir_cursos: bool = False,
    *,
    propio: Path | None = None,
) -> tuple[Config, AulaVirtual, dict[int, str]] | int:
    """Contraseña, login y cursos; devuelve (cfg, aula, nombres) o el código de salida.

    ``propio``: el directorio privado de esta sesión, que no se confunde con el de otra.
    """
    comando = "sesion"
    salida_anterior = _cerrar_anterior(base, presencia, propio)
    if salida_anterior is not None:
        return salida_anterior
    acreditacion = presencia.acreditar(cfg.url, cfg.usuario)
    if acreditacion is None:
        return _abortado(comando, base, presencia)
    try:
        aula = publicar.autenticar_con(cfg.url, cfg.usuario, acreditacion)
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
    try:
        salida = _cursos_de_la_sesion(cfg, aula, base, presencia, debug, elegir_cursos)
    except BaseException:
        publicar.cerrar_aula(aula)
        raise
    if isinstance(salida, int):
        publicar.cerrar_aula(aula)  # se abandona tras entrar: la sesión del aula no se deja viva
        return salida
    return salida[0], aula, salida[1]


def _cursos_de_la_sesion(
    cfg: Config,
    aula: AulaVirtual,
    base: Path,
    presencia: Presencia,
    debug: bool,
    elegir_cursos: bool,
) -> tuple[Config, dict[int, str]] | int:
    """Nombres de los cursos, elección y confirmaciones; el código de salida si se abandona."""
    comando = "sesion"
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
    return completa, nombres


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
    presencia.informar(Aviso.cursos_guardados(ruta))
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
        presencia.informar(Aviso.autoprueba_fallida())
        return 1
    documento = sesion_abierta.registrar(
        sesion_abierta.estructura_con(aula, cfg, base, debug=debug), base, presencia
    )
    if "SESION_CADUCADA" in documento["errores"]:
        return 1
    if documento["resultado"] != "ok":
        presencia.informar(Aviso.estructura_no_leida())
    return None


class _Cierre:
    """Lo que hace la sesión cuando otro «tiza empezar» de su carpeta le pide irse.

    La petición es el fichero ``PEDIR_CIERRE`` de su directorio privado, que el agente
    no escribe. La mira el hilo de latido (``revisar``). Si la sesión espera al docente
    (su terminal se cerró a media pregunta: el ``input`` no volverá), se va en el acto:
    no hay nada a medias. Si no, se cierra al acabar lo que atiende y, desde entonces,
    toda pregunta es «no» (:class:`_PresenciaVigilada`).
    """

    def __init__(
        self,
        dir_tiza: Path,
        dir_vistas: Path,
        aula: AulaVirtual,
        cerrar: threading.Event,
        salir: Callable[[int], object] = os._exit,
    ) -> None:
        self.dir_tiza = dir_tiza
        self.dir_vistas = dir_vistas
        self.aula = aula
        self.cerrar = cerrar
        self.pedido = threading.Event()
        self.esperando = threading.Event()  # la presencia está preguntando al docente
        self._salir = salir

    def revisar(self) -> bool:
        """Tras cada latido; falso si la sesión se ha ido y ya no debe latir."""
        if not self.pedido.is_set():
            if not (self.dir_vistas / PEDIR_CIERRE).exists():
                return True
            self.pedido.set()
            self.cerrar.set()  # buzon.atender para en cuanto acabe lo que atiende
        if not self.esperando.is_set():
            return True
        # Sin pasar por los «finally» del hilo principal, que sigue en el ``input``.
        buzon.soltar(self.dir_tiza)
        hilo = threading.Thread(target=publicar.cerrar_aula, args=(self.aula,), daemon=True)
        hilo.start()
        hilo.join(PLAZO_CIERRE_AULA)
        shutil.rmtree(self.dir_vistas, ignore_errors=True)
        self._salir(0)
        return False


class _PresenciaVigilada:
    """La presencia de la sesión abierta, para :class:`_Cierre`.

    Anota cuándo se espera la respuesta del docente y, pedido el cierre, responde
    «no» sin preguntar (también a una respuesta que llega después de pedirlo).
    """

    def __init__(self, presencia: Presencia, cierre: _Cierre) -> None:
        self._presencia = presencia
        self._cierre = cierre

    def _preguntar(self, pregunta: Callable[[], bool]) -> bool:
        if self._cierre.pedido.is_set():
            return False
        self._cierre.esperando.set()
        try:
            respuesta = pregunta()
        finally:
            self._cierre.esperando.clear()
        return respuesta and not self._cierre.pedido.is_set()

    def acreditar(self, url: str, usuario: str) -> publicar.Acreditacion | None:
        return self._presencia.acreditar(url, usuario)

    def elegir_curso(self, entorno: str, cursos: list[dict], excluir: int | None) -> int | None:
        return self._presencia.elegir_curso(entorno, cursos, excluir)

    def elegir_cursos_reales(self, cursos: list[dict], excluir: int | None) -> list[int] | None:
        return self._presencia.elegir_cursos_reales(cursos, excluir)

    def confirmar_cursos(self, cursos: list[CursoSesion]) -> bool:
        return self._presencia.confirmar_cursos(cursos)

    def confirmar_autoprueba(self) -> bool:
        return self._presencia.confirmar_autoprueba()

    def confirmar_sin_pruebas(self) -> bool:
        return self._presencia.confirmar_sin_pruebas()

    def cerrar_sesion_anterior(self, atendiendo: bool) -> bool:
        return self._presencia.cerrar_sesion_anterior(atendiendo)

    def confirmar_real(self, resumen: publicacion.ResumenPublicacion) -> bool:
        return self._preguntar(lambda: self._presencia.confirmar_real(resumen))

    def confirmar_real_sin_pruebas(self, resumen: publicacion.ResumenSinPruebas) -> bool:
        return self._preguntar(lambda: self._presencia.confirmar_real_sin_pruebas(resumen))

    def confirmar_orden(self, resumen: publicacion.ResumenOrden) -> bool:
        return self._preguntar(lambda: self._presencia.confirmar_orden(resumen))

    def confirmar_calificador(self, resumen: publicacion.ResumenCalificador) -> bool:
        return self._preguntar(lambda: self._presencia.confirmar_calificador(resumen))

    def confirmar_copia(self, resumen: publicacion.ResumenCopia) -> bool:
        return self._preguntar(lambda: self._presencia.confirmar_copia(resumen))

    def ofrecer_ampliacion(self, minutos: int, plazo: float) -> bool:
        return self._preguntar(lambda: self._presencia.ofrecer_ampliacion(minutos, plazo))

    def informar(self, aviso: Aviso) -> None:
        self._presencia.informar(aviso)


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
    cerrar = cerrar or threading.Event()
    cierre = _Cierre(dir_tiza, dir_vistas, aula, cerrar)
    vigilada = _PresenciaVigilada(presencia, cierre)
    abierta = sesion_abierta.SesionAbierta(
        aula, cfg, base, vigilada, nombres=nombres, dir_vistas=dir_vistas, debug=debug
    )
    try:
        with buzon.abrir_sesion(dir_tiza, caduca, al_latir=cierre.revisar) as actual:
            _atender(
                dir_tiza,
                abierta.atender,
                apertura,
                actual,
                vigilada,
                debug,
                cerrar,
                otra=cierre.pedido,
            )
    except buzon.ErrorBuzon as exc:
        return _fallo("sesion", exc.codigo, exc.detalle, base, presencia)
    except KeyboardInterrupt:
        presencia.informar(Aviso.sesion_cerrada("docente"))
    return 0


def _atender(
    dir_tiza: Path,
    procesar: Callable[[dict], dict],
    apertura: datetime,
    abierta: buzon.SesionAbierta,
    presencia: Presencia,
    debug: bool,
    cerrar: threading.Event | None = None,
    *,
    otra: threading.Event | None = None,
) -> None:
    """Atiende el buzón y ofrece ampliar hasta que se cierre la sesión.

    ``otra``: la cierra otro «tiza empezar» de la carpeta, no el docente en esta terminal.
    """
    presencia.informar(Aviso.sesion_abierta(abierta.caduca))
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
            sesion=abierta,
        )
        if cerrar is not None and cerrar.is_set():
            pedida = otra is not None and otra.is_set()
            presencia.informar(Aviso.sesion_cerrada("otra" if pedida else "docente"))
            return
        if cerrada:
            presencia.informar(Aviso.sesion_cerrada(motivos[-1]))
            return
        nueva = _ofrecer_ampliacion(apertura, abierta.caduca, presencia)
        if nueva is None:
            presencia.informar(Aviso.sesion_cerrada("caducada"))
            return
        abierta.ampliar(nueva)
        presencia.informar(Aviso.sesion_abierta(nueva))


def _aviso_previo(abierta: Any, presencia: Presencia) -> Callable[[], None]:
    """Avisa una vez cuando queden AVISO_MINUTOS para el final."""
    avisado = False

    def avisar() -> None:
        nonlocal avisado
        if not avisado and abierta.caduca - buzon.ahora_utc() <= timedelta(minutes=AVISO_MINUTOS):
            avisado = True
            presencia.informar(Aviso.quedan_minutos(AVISO_MINUTOS))

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
        presencia.informar(Aviso.maximo_alcanzado(MAX_MINUTOS // 60))
        return None
    if not presencia.ofrecer_ampliacion(AMPLIACION_MINUTOS, ESPERA_RESPUESTA_SEGUNDOS):
        return None
    return min(max(reloj(), caduca) + timedelta(minutes=AMPLIACION_MINUTOS), maximo)


def _error_interno(exc: BaseException, presencia: Presencia, debug: bool) -> None:
    """El docente ve el tipo de fallo; el agente solo recibe ERROR_INTERNO."""
    presencia.informar(Aviso.error_interno(type(exc).__name__))
    if debug:
        print(AVISO_DEBUG, file=sys.stderr)
        traceback.print_exception(exc)
