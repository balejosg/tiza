"""La sesión del docente, sin terminal: login, cursos, puertas y buzón.

Es el lado de confianza de tiza. Habla con el docente solo a través de una
``Presencia`` (la terminal de ``tiza sesion`` o una ventana) y con el aula solo
a través de :mod:`tiza.publicar`. No escribe en la consola, salvo la traza de
``--debug``: lo que el docente ve lo decide la presencia, que además sanea los
textos ajenos (del agente o de Moodle).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import platformdirs

from . import (
    __version__,
    buzon,
    config,
    contenido,
    ficheros,
    informe,
    publicar,
    rutas,
)
from .config import Config, ErrorConfig
from .contenido import Documento, ErrorContenido, Fechas, hash_documento
from .informe import ErrorInforme
from .publicar import AulaVirtual, ErrorPublicacion

__all__ = [
    "AMPLIACION_MINUTOS",
    "AVISOS",
    "AVISO_DEBUG",
    "AVISO_MINUTOS",
    "Aviso",
    "CursoSesion",
    "DocumentoBreve",
    "DocumentoResumen",
    "ESPERA_RESPUESTA_SEGUNDOS",
    "MAX_MINUTOS",
    "MAX_PUBLICACIONES_PRUEBAS",
    "Presencia",
    "ResumenPublicacion",
    "ResumenSinPruebas",
    "SIN_PRUEBAS",
    "abrir",
    "autoprueba_con",
    "crear_dir_vistas",
    "depurar",
    "estructura_con",
    "procesar_peticion",
    "publicar_con",
    "puerta_real",
    "registrar",
]

MAX_MINUTOS = 480
AMPLIACION_MINUTOS = 30
AVISO_MINUTOS = 5
ESPERA_RESPUESTA_SEGUNDOS = 300
MAX_PUBLICACIONES_PRUEBAS = 50  # por sesión: frena a un agente en bucle
SIN_PRUEBAS = 0  # elegir_curso: el docente elige no tener curso de pruebas
VISTAS_VIEJAS_SEGUNDOS = 24 * 3600  # un directorio de vistas más viejo es de una sesión que murió
AVISO_DEBUG = "AVISO: salida de depuración; no la compartas."

# Lo que la sesión cuenta al docente. Entre paréntesis, las claves de ``datos``.
AVISOS = frozenset(
    {
        "AUTOPRUEBA_FALLIDA",  # la autoprueba falló y la sesión no se abre
        "CANCELADA",  # el docente dijo que no o no dio la contraseña
        "CREANDO_SECCION",  # (nombre) se crea una sección oculta
        "CURSOS_GUARDADOS",  # (ruta) tiza.toml de la carpeta
        "ERROR_INTERNO",  # (tipo) fallo inesperado al atender una petición
        "ESTRUCTURA_NO_LEIDA",  # no se pudo leer la estructura al abrir
        "FALLO",  # (codigo, detalle) la sesión no se pudo abrir
        "INFORME_NO_ESCRITO",  # no se pudo escribir .tiza/informe.json
        "MAXIMO_ALCANZADO",  # (horas) la sesión no se puede ampliar más
        "NOMBRES_NO_DISPONIBLES",  # no se pudo leer la lista de cursos
        "PETICION_RETIRADA",  # se confirmó cuando el agente ya no esperaba
        "PUBLICANDO_EN_PRUEBAS",  # (documentos: tuple[DocumentoResumen, ...])
        "QUEDAN_MINUTOS",  # (minutos) aviso antes del final
        "RESULTADO",  # (documento) informe de lo que acaba de pasar
        "SESION_ABIERTA",  # (caduca: datetime) sesión abierta o ampliada
        "SESION_CERRADA",  # (motivo: "aula" | "caducada" | "desactualizada" | "docente")
    }
)


@dataclass(frozen=True)
class Aviso:
    """Algo que la sesión cuenta al docente; ``codigo`` es uno de ``AVISOS``."""

    codigo: str
    datos: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.codigo not in AVISOS:
            raise ValueError(f"aviso desconocido: {self.codigo}")


@dataclass(frozen=True)
class CursoSesion:
    """Un curso de la sesión tal como se le enseña al docente."""

    entorno: str  # "pruebas" o "real"
    id: int
    nombre: str | None  # de Moodle: solo para la presencia, nunca a .tiza
    ajeno: bool  # hay lista de cursos y este id no está en ella


@dataclass(frozen=True)
class DocumentoResumen:
    """Lo que el docente necesita ver de un documento antes de publicarlo."""

    fichero: str
    tipo: str
    nombre: str
    seccion: int | str
    fechas: Fechas | None
    vista_previa: Path | None = None
    enlaces_externos: tuple[str, ...] = ()
    incrustados: tuple[str, ...] = ()  # URL de los iframes, tal como se publicarán
    recursos: tuple[str, ...] = ()  # ficheros locales que se suben, relativos a la carpeta

    @classmethod
    def de(cls, doc: Documento, base: Path, vista_previa: Path | None = None) -> DocumentoResumen:
        return cls(
            fichero=doc.ruta.name,
            tipo=doc.tipo,
            nombre=doc.nombre,
            seccion=doc.seccion,
            fechas=doc.fechas,
            vista_previa=vista_previa,
            enlaces_externos=tuple(doc.enlaces_externos),
            incrustados=tuple(doc.incrustados),
            recursos=tuple(_relativa(recurso.ruta, base) for recurso in doc.recursos),
        )


@dataclass(frozen=True)
class ResumenPublicacion:
    """Lo que se va a publicar en real: la presencia lo enseña y el docente decide."""

    curso: int
    nombre_curso: str | None
    documentos: tuple[DocumentoResumen, ...]
    secciones_nuevas: tuple[str, ...]
    visible: bool | None  # True: visible; False: oculto; None: lo que exista conserva


@dataclass(frozen=True)
class DocumentoBreve:
    """Lo mínimo de un documento para confirmar una publicación sin curso de pruebas.

    ``existe``: True si ya hay un módulo con su tipo y nombre en su sección (se
    actualizará y, al ir oculto, se ocultará si estaba visible), False si es
    nuevo y None si la estructura del aula no permitió comprobarlo.
    """

    fichero: str
    tipo: str
    nombre: str
    existe: bool | None = False


@dataclass(frozen=True)
class ResumenSinPruebas:
    """La confirmación corta cuando no hay curso de pruebas: solo se publica oculto."""

    curso: int
    nombre_curso: str | None
    documentos: tuple[DocumentoBreve, ...]
    secciones_nuevas: tuple[str, ...]


def _relativa(ruta: Path, base: Path) -> str:
    """Ruta de un recurso relativa a la carpeta (antes se comprueba que está dentro)."""
    try:
        return Path(ruta).resolve().relative_to(base).as_posix()
    except ValueError:
        return Path(ruta).name


class Presencia(Protocol):
    """Quien está delante: la terminal de «tiza sesion» o una ventana.

    Cada implementación sanea los textos ajenos al mostrarlos.
    """

    def pedir_password(self, servidor: str, usuario: str) -> str | None:
        """Contraseña del aula, tras enseñar a qué servidor va; None si cancela."""
        ...

    def elegir_curso(self, entorno: str, cursos: list[dict], excluir: int | None) -> int | None:
        """Id del curso de ``entorno`` (``cursos``: dicts con id y nombre); None si cancela.

        Para ``pruebas`` también admite ``SIN_PRUEBAS``: el docente no tiene
        curso de pruebas y en real solo se publicará oculto.
        """
        ...

    def confirmar_cursos(self, cursos: list[CursoSesion]) -> bool:
        """¿Abrir la sesión con estos cursos?"""
        ...

    def confirmar_autoprueba(self) -> bool:
        """¿Pasar ahora la autoprueba en el curso de pruebas?"""
        ...

    def confirmar_real(self, resumen: ResumenPublicacion) -> bool:
        """¿Publicar en real lo que enseña ``resumen``? Una respuesta por petición."""
        ...

    def confirmar_real_sin_pruebas(self, resumen: ResumenSinPruebas) -> bool:
        """¿Publicar oculto en real sin curso de pruebas? Una respuesta por petición."""
        ...

    def confirmar_sin_pruebas(self) -> bool:
        """¿Abrir la sesión sin curso de pruebas? (no habrá verificación previa)."""
        ...

    def ofrecer_ampliacion(self, minutos: int, plazo: float) -> bool:
        """¿Ampliar ``minutos`` más? Sin respuesta en ``plazo`` segundos, es no."""
        ...

    def informar(self, aviso: Aviso) -> None:
        """Enseña un aviso de la sesión."""
        ...


_CAMPOS_FICHERO = ("nombre", "tipo", "cmid", "accion", "oculto", "url", "seccion", "hash")


def depurar(exc: BaseException, debug: bool) -> None:
    """Traza para quien desarrolla, solo con --debug; nunca llega al agente."""
    if not debug:
        return
    print(AVISO_DEBUG, file=sys.stderr)
    traceback.print_exception(exc.__cause__ or exc)


def registrar(documento: dict, carpeta: Path, presencia: Presencia) -> dict:
    """Escribe ``.tiza/informe.json`` y se lo cuenta al docente."""
    try:
        informe.escribir(documento, Path(carpeta) / rutas.CARPETA_TRABAJO)
    except (ErrorInforme, OSError):
        presencia.informar(Aviso("INFORME_NO_ESCRITO"))
    presencia.informar(Aviso("RESULTADO", {"documento": documento}))
    return documento


def estructura_con(aula: AulaVirtual, cfg: Config, carpeta: Path, *, debug: bool = False) -> dict:
    """Con el aula ya abierta: lee y guarda la estructura de los cursos configurados."""
    comando = "estructura"
    pasos: list[dict] = [{"codigo": "LOGIN", "resultado": "ok", "detalle": None}]
    cursos: dict[str, dict] = {}
    try:
        for nombre in ("pruebas", "real"):
            curso_id = cfg.cursos.get(nombre)
            if curso_id is None:
                continue
            secciones = aula.estructura(curso_id)
            cursos[nombre] = {
                "id": curso_id,
                "secciones": [
                    {"numero": seccion["numero"], "nombre": seccion["nombre"], "id": seccion["id"]}
                    for seccion in secciones
                ],
            }
            pasos.append(
                {
                    "codigo": "ESTRUCTURA",
                    "resultado": "ok",
                    "detalle": f"{nombre}: {len(secciones)} secciones",
                }
            )
    except ErrorPublicacion as exc:
        pasos.append({"codigo": "ESTRUCTURA", "resultado": "fallo", "detalle": exc.codigo})
        depurar(exc, debug)
        return informe.crear(comando, "error", pasos, [], [exc.codigo])
    datos = {
        "version": 1,
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "cursos": cursos,
    }
    try:
        informe.validar_estructura(datos)
    except ErrorInforme:
        pasos.append(
            {"codigo": "ESTRUCTURA", "resultado": "fallo", "detalle": "ESTRUCTURA_INVALIDA"}
        )
        return informe.crear(comando, "error", pasos, [], ["ESTRUCTURA_INVALIDA"])
    publicar.escribir_estructura(Path(carpeta) / rutas.CARPETA_TRABAJO, datos)
    return informe.crear(comando, "ok", pasos, [], [])


def puerta_real(
    carpeta: Path, documentos: list[Documento], verificados: dict | None = None
) -> list[str]:
    """Nombres de los documentos sin verificación previa en pruebas.

    Con ``verificados`` (el registro en memoria de la sesión) no se fía de
    ``verificados.json``, que el agente puede escribir.
    """
    if verificados is None:
        verificados = publicar.cargar_verificados(Path(carpeta) / rutas.CARPETA_TRABAJO)
    pares = [(doc.ruta.name, hash_documento(doc)) for doc in documentos]
    return publicar.comprobar_puerta_real(verificados, pares)


def publicar_con(
    aula: AulaVirtual,
    entorno: str,
    curso: int,
    documentos: list[Documento],
    visible: bool | None,
    carpeta: Path,
    presencia: Presencia,
    *,
    debug: bool = False,
) -> dict:
    """Con el aula ya abierta: publica y verifica los documentos."""
    comando = "publicar"
    pasos: list[dict] = [{"codigo": "LOGIN", "resultado": "ok", "detalle": None}]
    try:
        secciones = aula.estructura(curso)
    except ErrorPublicacion as exc:
        pasos.append({"codigo": "ESTRUCTURA", "resultado": "fallo", "detalle": exc.codigo})
        depurar(exc, debug)
        return informe.crear(comando, "error", pasos, [], [exc.codigo], entorno, curso)
    for nombre in publicar.secciones_que_faltan(secciones, documentos):
        presencia.informar(Aviso("CREANDO_SECCION", {"nombre": nombre}))
    try:
        secciones, creadas = publicar.asegurar_secciones(aula, curso, secciones, documentos)
    except ErrorPublicacion as exc:
        pasos.append({"codigo": "CREAR_SECCION", "resultado": "fallo", "detalle": exc.codigo})
        depurar(exc, debug)
        return informe.crear(comando, "error", pasos, [], [exc.codigo], entorno, curso)
    for nombre in creadas:
        pasos.append({"codigo": "CREAR_SECCION", "resultado": "ok", "detalle": nombre})
    ficheros: list[dict] = []
    for doc in documentos:
        try:
            resultado = publicar.publicar_documento(aula, curso, secciones, doc, visible=visible)
        except ErrorPublicacion as exc:
            pasos.append({"codigo": "PUBLICAR", "resultado": "fallo", "detalle": doc.ruta.name})
            depurar(exc, debug)
            return informe.crear(comando, "error", pasos, ficheros, [exc.codigo], entorno, curso)
        if entorno == "pruebas":
            publicar.guardar_verificado(
                Path(carpeta) / rutas.CARPETA_TRABAJO,
                resultado["hash"],
                resultado["nombre"],
                resultado["cmid"],
            )
        ficheros.append({clave: resultado[clave] for clave in _CAMPOS_FICHERO})
        detalle = doc.ruta.name
        if doc.cuestionario is not None:
            detalle = f"{detalle}: {len(doc.cuestionario.preguntas)} preguntas"
        pasos.append({"codigo": "PUBLICAR", "resultado": "ok", "detalle": detalle})
        for extra in resultado.get("pasos", []):
            pasos.append(extra)
    return informe.crear(comando, "ok", pasos, ficheros, [], entorno, curso)


def crear_dir_vistas(carpeta: str | Path | None = None) -> Path:
    """Directorio privado para las vistas previas de una sesión, fuera de la carpeta de la asignatura.

    El agente escribe en la carpeta de la asignatura y podría cambiar una vista
    previa entre que tiza la escribe y el docente la abre. Este directorio está
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


def _nombres_de_vista(documentos: list[Documento]) -> list[str | None]:
    """Un nombre de vista previa distinto por documento.

    ``a/x.md`` y ``b/x.md`` (o ``x.md`` y ``x.html``) darían la misma vista y la segunda pisaría
    a la primera: el docente revisaría una y se publicaría la otra. Con varios documentos, la
    vista lleva delante su número de orden; con uno, el nombre de siempre (``None``).
    """
    if len(documentos) < 2:
        return [None] * len(documentos)
    return [f"{numero:02d}-{doc.ruta.stem}" for numero, doc in enumerate(documentos, 1)]


def _ruta_dentro(base: Path, nombre: str) -> Path | None:
    try:
        ruta = (base / nombre).resolve()
    except (OSError, RuntimeError):
        return None
    if not ruta.is_relative_to(base):
        return None
    return ruta


def procesar_peticion(
    peticion: dict,
    aula: AulaVirtual,
    cfg: Config,
    carpeta: Path,
    presencia: Presencia,
    *,
    verificados: dict | None = None,
    cupo: dict | None = None,
    nombres: dict[int, str] | None = None,
    dir_vistas: Path | None = None,
    debug: bool = False,
) -> dict:
    """Lado del docente: convierte una petición del buzón en un informe.

    ``cfg`` es la configuración capturada al abrir la sesión: alterar
    ``tiza.toml`` después no puede redirigir la publicación. ``dir_vistas`` es el
    directorio privado donde se escriben las vistas previas de la confirmación
    (``crear_dir_vistas``); sin él, van a ``.tiza/preview`` de la carpeta.
    """
    comando = peticion["comando"]
    base = Path(carpeta).resolve()
    if comando == "estructura":
        if "real" not in cfg.cursos:
            return informe.crear(comando, "error", [], [], ["CURSO_NO_CONFIGURADO"])
        return registrar(estructura_con(aula, cfg, base, debug=debug), base, presencia)
    entorno = peticion["entorno"]
    curso = cfg.cursos.get(entorno)
    if curso is None:
        codigo = "SIN_CURSO_PRUEBAS" if entorno == "pruebas" else "CURSO_NO_CONFIGURADO"
        return informe.crear(comando, "error", [], [], [codigo], entorno)
    documentos: list[Documento] = []
    for nombre in peticion["ficheros"]:
        ruta = _ruta_dentro(base, nombre)
        if ruta is None:
            return informe.crear(
                comando, "error", [], [], ["RUTA_FUERA_DE_CARPETA"], entorno, curso
            )
        try:
            doc = contenido.cargar(ruta, raiz=base)
        except ErrorContenido as exc:
            return informe.crear(comando, "error", [], [], [exc.codigo], entorno, curso)
        # Defensa en profundidad: ``cargar`` con ``raiz`` ya lo impide.
        if any(not recurso.ruta.resolve().is_relative_to(base) for recurso in doc.recursos):
            return informe.crear(
                comando, "error", [], [], ["RUTA_FUERA_DE_CARPETA"], entorno, curso
            )
        documentos.append(doc)
    visible = peticion["visible"]
    if entorno == "real":
        # Sin curso de pruebas no hay verificación previa ni vista que enseñar:
        # se compensa publicando solo en oculto y con una confirmación corta.
        sin_pruebas = "pruebas" not in cfg.cursos
        if sin_pruebas:
            if visible is not False:
                return informe.crear(
                    comando, "error", [], [], ["SOLO_OCULTO_SIN_PRUEBAS"], entorno, curso
                )
            visible = False
        elif puerta_real(base, documentos, verificados):
            return informe.crear(
                comando, "error", [], [], ["VERIFICACION_PENDIENTE"], entorno, curso
            )
        try:
            secciones = aula.estructura(curso)
        except ErrorPublicacion as exc:
            return informe.crear(comando, "error", [], [], [exc.codigo], entorno, curso)
        nuevas = publicar.secciones_que_faltan(secciones, documentos)
        dir_tiza = base / rutas.CARPETA_TRABAJO
        if sin_pruebas:
            corto = ResumenSinPruebas(
                curso=curso,
                nombre_curso=(nombres or {}).get(curso),
                documentos=tuple(
                    DocumentoBreve(
                        fichero=doc.ruta.name,
                        tipo=doc.tipo,
                        nombre=doc.nombre,
                        existe=publicar.ya_existe(secciones, doc),
                    )
                    for doc in documentos
                ),
                secciones_nuevas=tuple(nuevas),
            )
            confirmado = presencia.confirmar_real_sin_pruebas(corto)
        else:
            raiz_vistas = dir_vistas if dir_vistas is not None else dir_tiza
            try:
                vistas = [
                    contenido.previsualizar(doc, raiz_vistas, nombre=nombre)
                    for doc, nombre in zip(documentos, _nombres_de_vista(documentos), strict=True)
                ]
            except ErrorContenido as exc:
                return informe.crear(comando, "error", [], [], [exc.codigo], entorno, curso)
            resumen = ResumenPublicacion(
                curso=curso,
                nombre_curso=(nombres or {}).get(curso),
                documentos=tuple(
                    DocumentoResumen.de(doc, base, vista)
                    for doc, vista in zip(documentos, vistas, strict=True)
                ),
                secciones_nuevas=tuple(nuevas),
                visible=peticion["visible"],
            )
            confirmado = presencia.confirmar_real(resumen)
        if not confirmado:
            return informe.crear(comando, "abortado", [], [], ["ABORTADO"], entorno, curso)
        if not buzon.peticion_pendiente(dir_tiza, peticion["id"]):
            presencia.informar(Aviso("PETICION_RETIRADA"))
            return informe.crear(comando, "error", [], [], ["PETICION_RETIRADA"], entorno, curso)
    else:
        if cupo is not None:
            if cupo["pruebas"] + len(documentos) > MAX_PUBLICACIONES_PRUEBAS:
                return informe.crear(
                    comando, "error", [], [], ["LIMITE_PUBLICACIONES"], entorno, curso
                )
            cupo["pruebas"] += len(documentos)
        presencia.informar(
            Aviso(
                "PUBLICANDO_EN_PRUEBAS",
                {"documentos": tuple(DocumentoResumen.de(doc, base) for doc in documentos)},
            )
        )
    documento = publicar_con(
        aula, entorno, curso, documentos, visible, base, presencia, debug=debug
    )
    if verificados is not None and entorno == "pruebas" and documento["resultado"] == "ok":
        for fichero in documento["ficheros"]:
            verificados[fichero["hash"]] = {"nombre": fichero["nombre"], "cmid": fichero["cmid"]}
    return registrar(documento, base, presencia)


def abrir(
    carpeta: str | Path,
    presencia: Presencia,
    *,
    minutos: int,
    preparar: bool = True,
    debug: bool = False,
    cerrar: threading.Event | None = None,
    dir_vistas: Path | None = None,
) -> int:
    """Abre la sesión del docente en ``carpeta`` y atiende el buzón hasta cerrarla.

    Devuelve 0 si la sesión se abrió (y luego se cerró por tiempo, por el aula
    o por el docente) y 1 si no llegó a abrirse. Con ``preparar`` hace además lo
    que añade «tiza empezar»: la autoprueba si toca y la estructura.

    ``dir_vistas`` es el directorio privado de las vistas previas
    (``crear_dir_vistas``). Si no se da, la sesión crea el suyo y lo borra al cerrarse.
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
    abierta = _iniciar(cfg, base, presencia, debug)
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
    pasos = [{"codigo": "LOGIN", "resultado": "ok", "detalle": None}] + resultado["pasos"]
    registrar(
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
    registrar(informe.crear(comando, "error", [], [], [codigo], entorno, curso), base, presencia)
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
    registrar(
        informe.crear(comando, "abortado", [], [], ["ABORTADO"], entorno, curso), base, presencia
    )
    presencia.informar(Aviso("CANCELADA"))
    return 1


def _iniciar(
    cfg: Config, base: Path, presencia: Presencia, debug: bool
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
        entorno = "pruebas" if "pruebas" in cfg.cursos else "real"
        return _fallo(
            comando,
            exc.codigo,
            exc.detalle,
            base,
            presencia,
            entorno=entorno,
            curso=cfg.cursos.get(entorno),
            exc=exc,
            debug=debug,
        )
    nombres = _nombres_de_cursos(aula, presencia, debug)
    try:
        completa = _completar_cursos(cfg, nombres, base, presencia)
    except ErrorConfig as exc:
        return _fallo(comando, exc.codigo, exc.detalle, base, presencia, exc=exc, debug=debug)
    if completa is None:
        return _abortado(comando, base, presencia)
    if not _confirmar_cursos(completa, nombres, presencia):
        entorno = "pruebas" if "pruebas" in completa.cursos else "real"
        return _abortado(comando, base, presencia, entorno, completa.cursos[entorno])
    if completa.sin_pruebas and not presencia.confirmar_sin_pruebas():
        return _abortado(comando, base, presencia, "real", completa.cursos.get("real"))
    return completa, aula, nombres


def _nombres_de_cursos(aula: AulaVirtual, presencia: Presencia, debug: bool) -> dict[int, str]:
    """Nombres de los cursos del docente: solo para la presencia, nunca a .tiza."""
    try:
        return {curso["id"]: curso["nombre"] for curso in aula.mis_cursos()}
    except ErrorPublicacion as exc:
        presencia.informar(Aviso("NOMBRES_NO_DISPONIBLES"))
        depurar(exc, debug)
        return {}


def _completar_cursos(
    cfg: Config, nombres: dict[int, str], base: Path, presencia: Presencia
) -> Config | None:
    """Pide los cursos que falten y los guarda en el tiza.toml de la carpeta.

    El curso real es obligatorio; el de pruebas se puede dejar sin configurar
    (``SIN_PRUEBAS``): en real solo se publicará oculto y no se vuelve a preguntar.
    """
    if "real" in cfg.cursos and ("pruebas" in cfg.cursos or cfg.sin_pruebas):
        return cfg
    lista = [{"id": curso, "nombre": nombre} for curso, nombre in nombres.items()]
    elegidos = dict(cfg.cursos)
    sin_pruebas = cfg.sin_pruebas
    for entorno, otro in (("pruebas", "real"), ("real", "pruebas")):
        if entorno in elegidos or (entorno == "pruebas" and sin_pruebas):
            continue
        curso = presencia.elegir_curso(entorno, lista, elegidos.get(otro))
        if curso is None:
            return None
        if entorno == "pruebas" and curso == SIN_PRUEBAS:
            sin_pruebas = True
            continue
        elegidos[entorno] = curso
    ruta = config.guardar_carpeta(base, elegidos, sin_pruebas=sin_pruebas)
    presencia.informar(Aviso("CURSOS_GUARDADOS", {"ruta": ruta}))
    return config.resolver(base)


def _confirmar_cursos(cfg: Config, nombres: dict[int, str], presencia: Presencia) -> bool:
    cursos = [
        CursoSesion(
            entorno=entorno,
            id=cfg.cursos[entorno],
            nombre=nombres.get(cfg.cursos[entorno]),
            ajeno=bool(nombres) and cfg.cursos[entorno] not in nombres,
        )
        for entorno in ("pruebas", "real")
        if entorno in cfg.cursos
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
    documento = registrar(estructura_con(aula, cfg, base, debug=debug), base, presencia)
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
    cupo = {"pruebas": 0}
    verificados: dict = {}  # solo lo publicado en pruebas durante esta sesión

    def procesar(peticion: dict) -> dict:
        return procesar_peticion(
            peticion,
            aula,
            cfg,
            base,
            presencia,
            verificados=verificados,
            cupo=cupo,
            nombres=nombres,
            dir_vistas=dir_vistas,
            debug=debug,
        )

    try:
        with buzon.abrir_sesion(dir_tiza, caduca) as abierta:
            _atender(dir_tiza, procesar, apertura, abierta, presencia, debug, cerrar)
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
