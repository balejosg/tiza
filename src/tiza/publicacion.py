"""La publicación como proceso: puertas, resúmenes, confirmación y registro.

Es lo que comparten «tiza publicar» desde la terminal del docente y la sesión que
atiende al agente: recibe los documentos ya cargados y el aula ya abierta, aplica
las reglas de confianza y habla con el docente solo a través de una
:class:`Presencia`.

Lo que cambia según quién publica entra explícito, nunca por accidente:

- ``verificados``: hashes verificados en pruebas. La sesión pasa su registro en
  memoria (el agente no puede escribirlo); la terminal directa, ``None``, que lee
  ``verificados.json`` (no hay memoria de sesión entre procesos).
- ``vigente``: ¿sigue el agente esperando la petición? Solo la sesión puede
  comprobarlo; ``None`` significa que no hay nada que retirar.
- ``cupo``: tope de publicaciones en pruebas por sesión. Solo la sesión lo pasa:
  frena a un agente en bucle; la terminal del docente publica lo que pide una vez.
- ``avisar_en_pruebas``: la sesión avisa «el agente pide…»; en la terminal directa
  ya está la confirmación de destino.
- ``omitidos``: cursos que la terminal descartó antes de pedir la contraseña; no
  se vuelven a preguntar y el informe los cuenta como omitidos.
"""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from . import calendario, contenido, estado, informe, publicar, rutas, tipos
from .config import Config
from .contenido import Documento, ErrorContenido, hash_documento
from .publicar import AulaVirtual, ErrorPublicacion
from .tipos import CAMPO_RECORDATORIO, FechaActividad

if TYPE_CHECKING:  # solo para el tipo; la sesión importa este módulo
    from .sesion import CursoSesion

__all__ = [
    "AVISO_DEBUG",
    "AVISOS",
    "Aviso",
    "CAMPO_RECORDATORIO",
    "CambioFecha",
    "DocumentoBreve",
    "DocumentoResumen",
    "MAX_PUBLICACIONES_PRUEBAS",
    "Presencia",
    "ResumenPublicacion",
    "ResumenSinPruebas",
    "cambios_de_fechas",
    "cargar_calendario",
    "codigo_solo_fechas",
    "depurar",
    "exige_oculto_sin_pruebas",
    "informe_de_cursos",
    "itinerario_de",
    "nombres_de_cursos",
    "ordenar_por_dependencias",
    "publicar_con",
    "publicar_en_cursos",
    "puerta_real",
    "resumen_solo_fechas",
]

AVISO_DEBUG = "AVISO: salida de depuración; no la compartas."
MAX_PUBLICACIONES_PRUEBAS = 50  # por sesión: frena a un agente en bucle

# Lo que la publicación y la sesión cuentan al docente. Entre paréntesis, las claves de
# ``datos``.
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
    """Algo que la publicación o la sesión cuentan al docente; ``codigo`` está en ``AVISOS``."""

    codigo: str
    datos: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.codigo not in AVISOS:
            raise ValueError(f"aviso desconocido: {self.codigo}")


@dataclass(frozen=True)
class CambioFecha:
    """Una fecha de la actividad frente a la que hay en el aula. La ve solo el docente.

    ``antes`` y ``despues`` son (año, mes, día, hora, minuto), o None si no hay fecha.
    ``estado``: ``nueva`` (la actividad no existe en el aula), ``igual``, ``cambia`` o
    ``desconocida`` (no se pudo leer el aula: solo se enseña lo que se publicaría).
    """

    # «apertura», «entrega», «límite», «cierre» o CAMPO_RECORDATORIO
    campo: str
    antes: tuple[int, int, int, int, int] | None
    despues: tuple[int, int, int, int, int] | None
    estado: str
    avisos: tuple[str, ...] = ()  # FECHA_FESTIVA… según calendario.toml; nunca bloquean


@dataclass(frozen=True)
class DocumentoResumen:
    """Lo que el docente necesita ver de un documento antes de publicarlo."""

    fichero: str
    tipo: str
    nombre: str
    seccion: int | str
    # Las fechas que declara el documento, ya sin mirar de qué tipo es (las de una
    # tarea y las de un cuestionario se ven igual): campo llano y momento.
    fechas: tuple[FechaActividad, ...]
    vista_previa: Path | None = None
    enlaces_externos: tuple[str, ...] = ()
    incrustados: tuple[str, ...] = ()  # URL de los iframes, tal como se publicarán
    recursos: tuple[str, ...] = ()  # ficheros locales que se suben, relativos a la carpeta
    h5p: str | None = None  # actividad H5P generada («Rellenar huecos»)
    h5p_libreria: str | None = None  # librería principal de un paquete subido
    h5p_descartadas: tuple[str, ...] = ()  # librerías que tiza no sube nunca
    # None: no se ha comparado con el aula (pruebas, la confirmación corta…).
    cambios: tuple[CambioFecha, ...] | None = None
    # Finalización y restricciones que declara el .md, en lenguaje llano (solo del .md).
    itinerario: tuple[str, ...] = ()

    @classmethod
    def de(
        cls,
        doc: Documento,
        base: Path,
        vista_previa: Path | None = None,
        cambios: tuple[CambioFecha, ...] | None = None,
    ) -> DocumentoResumen:
        return cls(
            fichero=doc.ruta.name,
            tipo=doc.tipo,
            nombre=doc.nombre,
            seccion=doc.seccion,
            fechas=tuple(
                fecha for fecha in tipos.obtener(doc.tipo).fechas(doc) if fecha.momento is not None
            ),
            vista_previa=vista_previa,
            enlaces_externos=tuple(doc.enlaces_externos),
            incrustados=tuple(doc.incrustados),
            recursos=tuple(_relativa(recurso.ruta, base) for recurso in doc.recursos),
            cambios=cambios,
            itinerario=itinerario_de(doc, base),
            **tipos.obtener(doc.tipo).extras_resumen(doc),
        )


@dataclass(frozen=True)
class ResumenPublicacion:
    """Lo que se va a publicar en real: la presencia lo enseña y el docente decide."""

    curso: int
    nombre_curso: str | None
    documentos: tuple[DocumentoResumen, ...]
    secciones_nuevas: tuple[str, ...]
    visible: bool | None  # True: visible; False: oculto; None: lo que exista conserva
    solo_fechas: bool = False  # «--solo-fechas»: el contenido y la visibilidad no cambian
    aviso_calendario: str | None = None  # código si calendario.toml no se pudo usar
    posicion: int = 1  # «Curso k de n»: con varios cursos reales, una confirmación por curso
    total: int = 1


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
    itinerario: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResumenSinPruebas:
    """La confirmación corta cuando no hay curso de pruebas: solo se publica oculto."""

    curso: int
    nombre_curso: str | None
    documentos: tuple[DocumentoBreve, ...]
    secciones_nuevas: tuple[str, ...]
    posicion: int = 1
    total: int = 1


def itinerario_de(doc: Documento, base: Path) -> tuple[str, ...]:
    """El itinerario del documento en lenguaje llano, con los nombres de sus dependencias.

    Los nombres salen de los ``.md`` de la carpeta, nunca del aula.
    """
    if doc.finalizacion is None and doc.restricciones is None:
        return ()
    nombres: dict[str, str] = {}
    for fichero in doc.restricciones.completar if doc.restricciones else ():
        try:
            nombres[fichero] = contenido.cargar(base / fichero, raiz=base).nombre
        except ErrorContenido:
            continue
    return tuple(contenido.describir_itinerario(doc, nombres))


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

    def elegir_cursos_reales(self, cursos: list[dict], excluir: int | None) -> list[int] | None:
        """Ids de 1 a ``config.MAX_REALES`` cursos reales, en orden, sin ``excluir`` (el de
        pruebas); None si cancela."""
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
        """Enseña un aviso de la publicación o de la sesión."""
        ...


_CAMPOS_FICHERO = ("nombre", "tipo", "cmid", "accion", "oculto", "url", "seccion", "hash")


def depurar(exc: BaseException, debug: bool) -> None:
    """Traza para quien desarrolla, solo con --debug; nunca llega al agente."""
    if not debug:
        return
    print(AVISO_DEBUG, file=sys.stderr)
    traceback.print_exception(exc.__cause__ or exc)


def puerta_real(
    carpeta: Path,
    documentos: list[Documento],
    verificados: Mapping[str, estado.Verificado] | None = None,
) -> list[str]:
    """Nombres de los documentos sin verificación previa en pruebas.

    Con ``verificados`` (el registro en memoria de la sesión) no se fía de
    ``verificados.json``, que el agente puede escribir.
    """
    if verificados is None:
        verificados = estado.cargar_verificados(Path(carpeta) / rutas.CARPETA_TRABAJO)
    pares = [(doc.ruta.name, hash_documento(doc)) for doc in documentos]
    return estado.comprobar_puerta_real(verificados, pares)


def exige_oculto_sin_pruebas(cfg: Config, visible: bool | None, *, solo_fechas: bool) -> bool:
    """Regla común: sin curso de pruebas solo se publica en real oculto (o solo fechas).

    La terminal directa la usa también antes de pedir la contraseña, para no pedirla
    si va a rechazar la publicación.
    """
    return "pruebas" not in cfg.cursos and not solo_fechas and visible is not False


def nombres_de_cursos(aula: AulaVirtual, presencia: Presencia, debug: bool) -> dict[int, str]:
    """Nombres de los cursos del docente: solo para la presencia, nunca a .tiza."""
    try:
        return {curso["id"]: curso["nombre"] for curso in aula.mis_cursos()}
    except ErrorPublicacion as exc:
        presencia.informar(Aviso("NOMBRES_NO_DISPONIBLES"))
        depurar(exc, debug)
        return {}


def cargar_calendario(carpeta: Path) -> tuple[calendario.Calendario | None, str | None]:
    """El calendario de la carpeta y, si existe pero no se puede usar, su código.

    Nunca aborta: sin calendario válido, las fechas simplemente no llevan avisos.
    """
    try:
        return calendario.cargar(carpeta), None
    except calendario.ErrorCalendario as exc:
        return None, exc.codigo


# El «recordatorio de calificación» de una tarea se reexporta aquí porque la
# confirmación de real lo nombra (ver ``tipos.base.CAMPO_RECORDATORIO``).


def cambios_de_fechas(
    aula: AulaVirtual,
    secciones: list[dict],
    doc: Documento,
    cal: calendario.Calendario | None,
    *,
    debug: bool = False,
) -> tuple[CambioFecha, ...]:
    """Las fechas que se publicarían frente a las que tiene el aula, con sus avisos.

    Solo lo lee la presencia: no se guarda en ``.tiza`` ni sale hacia el agente. Las
    fechas de cada alumno (excepciones de cuestionario, prórrogas de tarea) no se
    leen nunca.
    """
    declaradas = tipos.obtener(doc.tipo).fechas(doc)
    if not declaradas:
        return ()
    esperadas = publicar.fechas_esperadas(doc)
    avisos_de = calendario.avisos_por_campo(cal, doc)
    existente = publicar.modulo_de(secciones, doc)
    actuales: dict | None = None
    if existente is not None:
        try:
            actuales = aula.leer_modulo(existente["cmid"]).get("fechas") or {}
        except ErrorPublicacion as exc:
            depurar(exc, debug)  # no aborta: se dice al docente que no se pudo leer
    cambios: list[CambioFecha] = []
    for fecha in declaradas:
        despues = esperadas.get(fecha.campo_moodle)
        avisos = avisos_de.get(fecha.campo, ())
        if existente is None or actuales is None:
            if despues is None:
                continue
            estado = "nueva" if existente is None else "desconocida"
            cambios.append(CambioFecha(fecha.campo, None, despues, estado, avisos))
            continue
        antes = actuales.get(fecha.campo_moodle)
        if antes is None and despues is None:
            continue
        estado = "igual" if antes == despues else "cambia"
        cambios.append(CambioFecha(fecha.campo, antes, despues, estado, avisos))
    return tuple(cambios)


def ordenar_por_dependencias(documentos: list[Documento], base: Path) -> list[Documento] | None:
    """Los documentos con sus dependencias de la misma petición antes (orden estable).

    ``None`` si se piden unos a otros en círculo.
    """
    claves = [_relativa(doc.ruta, base) for doc in documentos]
    pendientes = list(zip(claves, documentos, strict=True))
    hechos: set[str] = set()
    salida: list[Documento] = []
    while pendientes:
        for indice, (clave, doc) in enumerate(pendientes):
            deps = doc.restricciones.completar if doc.restricciones else ()
            if all(dep in hechos or dep not in claves for dep in deps):
                salida.append(doc)
                hechos.add(clave)
                del pendientes[indice]
                break
        else:
            return None
    return salida


def _resolver_dependencias(
    base: Path,
    secciones: list[dict],
    documentos: list[Documento],
    existentes: dict[str, int],
) -> tuple[str, str] | None:
    """Rellena ``existentes`` con el cmid en este curso de cada dependencia que no se pide.

    Devuelve (código, fichero) si alguna no se puede resolver: se mira antes de escribir.
    """
    pedidas = {_relativa(doc.ruta, base) for doc in documentos}
    for doc in documentos:
        for fichero in doc.restricciones.completar if doc.restricciones else ():
            if fichero in pedidas or fichero in existentes:
                continue
            try:
                dep = contenido.cargar(base / fichero, raiz=base)
            except ErrorContenido:
                return "DEPENDENCIA_INVALIDA", fichero
            modulo = publicar.modulo_de(secciones, dep)
            if modulo is None:
                return "DEPENDENCIA_NO_PUBLICADA", fichero
            existentes[fichero] = modulo["cmid"]
    return None


def codigo_solo_fechas(secciones: list[dict], documentos: list[Documento]) -> str | None:
    """Por qué «--solo-fechas» no se puede aplicar a estos documentos, o None si sí."""
    for doc in documentos:
        if tipos.obtener(doc.tipo).payload_solo_fechas(doc) is None:
            return "SOLO_FECHAS_NO_APLICA"
        if publicar.modulo_de(secciones, doc) is None:
            return "MODULO_AUSENTE"
    return None


def resumen_solo_fechas(
    aula: AulaVirtual,
    curso: int,
    nombre_curso: str | None,
    documentos: list[Documento],
    carpeta: Path,
    secciones: list[dict],
    *,
    debug: bool = False,
    posicion: int = 1,
    total: int = 1,
) -> ResumenPublicacion:
    """Lo que se confirma en real con «--solo-fechas»: fechas antes y después, nada más."""
    cal, aviso = cargar_calendario(carpeta)
    return ResumenPublicacion(
        curso=curso,
        nombre_curso=nombre_curso,
        documentos=tuple(
            DocumentoResumen.de(
                doc,
                carpeta,
                cambios=cambios_de_fechas(aula, secciones, doc, cal, debug=debug),
            )
            for doc in documentos
        ),
        secciones_nuevas=(),
        visible=None,
        solo_fechas=True,
        aviso_calendario=aviso,
        posicion=posicion,
        total=total,
    )


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
    solo_fechas: bool = False,
) -> dict:
    """Con el aula ya abierta: publica y verifica los documentos.

    Con ``solo_fechas`` solo cambia las fechas de lo que ya existe: no crea secciones,
    no sube recursos y no registra nada como verificado en pruebas.
    """
    comando = "publicar"
    pasos: list[dict] = [{"codigo": "LOGIN", "resultado": "ok", "detalle": None}]
    base = Path(carpeta).resolve()
    if not solo_fechas:
        ordenados = ordenar_por_dependencias(documentos, base)
        if ordenados is None:
            pasos.append(
                {"codigo": "DEPENDENCIAS", "resultado": "fallo", "detalle": "DEPENDENCIA_CIRCULAR"}
            )
            return informe.crear(
                comando, "error", pasos, [], ["DEPENDENCIA_CIRCULAR"], entorno, curso
            )
        documentos = ordenados
    try:
        secciones = aula.estructura(curso)
    except ErrorPublicacion as exc:
        pasos.append({"codigo": "ESTRUCTURA", "resultado": "fallo", "detalle": exc.codigo})
        depurar(exc, debug)
        return informe.crear(comando, "error", pasos, [], [exc.codigo], entorno, curso)
    existentes: dict[str, int] = {}
    if not solo_fechas:
        faltante = _resolver_dependencias(base, secciones, documentos, existentes)
        if faltante is not None:
            pasos.append({"codigo": "DEPENDENCIAS", "resultado": "fallo", "detalle": faltante[1]})
            return informe.crear(comando, "error", pasos, [], [faltante[0]], entorno, curso)
    if solo_fechas:
        # Todo o nada: si alguno de los documentos no se puede cambiar, no se cambia ninguno.
        codigo = codigo_solo_fechas(secciones, documentos)
        if codigo is not None:
            pasos.append({"codigo": "SOLO_FECHAS", "resultado": "fallo", "detalle": codigo})
            return informe.crear(comando, "error", pasos, [], [codigo], entorno, curso)
    else:
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
    paso = "SOLO_FECHAS" if solo_fechas else "PUBLICAR"
    ficheros: list[dict] = []
    cmids = dict(existentes)  # de cada fichero de la carpeta, su cmid en este curso
    for doc in documentos:
        try:
            if solo_fechas:
                resultado = publicar.publicar_fechas(aula, secciones, doc)
            else:
                dependencias = {
                    fichero: cmids[fichero]
                    for fichero in (doc.restricciones.completar if doc.restricciones else ())
                    if fichero in cmids
                }
                resultado = publicar.publicar_documento(
                    aula, curso, secciones, doc, visible=visible, dependencias=dependencias
                )
                cmids[_relativa(doc.ruta, base)] = resultado["cmid"]
        except ErrorPublicacion as exc:
            pasos.append({"codigo": paso, "resultado": "fallo", "detalle": doc.ruta.name})
            depurar(exc, debug)
            return informe.crear(comando, "error", pasos, ficheros, [exc.codigo], entorno, curso)
        if entorno == "pruebas" and not solo_fechas:
            estado.guardar_verificado(
                Path(carpeta) / rutas.CARPETA_TRABAJO,
                resultado["hash"],
                resultado["nombre"],
                resultado["cmid"],
            )
        ficheros.append({**{clave: resultado[clave] for clave in _CAMPOS_FICHERO}, "curso": curso})
        detalle = doc.ruta.name
        if not solo_fechas:
            extra = tipos.obtener(doc.tipo).detalle(doc)
            if extra:
                detalle = f"{detalle}: {extra}"
        pasos.append({"codigo": paso, "resultado": "ok", "detalle": detalle})
        for extra in resultado.get("pasos", []):
            pasos.append(extra)
    return informe.crear(comando, "ok", pasos, ficheros, [], entorno, curso)


def _nombres_de_vista(documentos: list[Documento]) -> list[str | None]:
    """Un nombre de vista previa distinto por documento.

    ``a/x.md`` y ``b/x.md`` (o ``x.md`` y ``x.html``) darían la misma vista y la segunda pisaría
    a la primera: el docente revisaría una y se publicaría la otra. Con varios documentos, la
    vista lleva delante su número de orden; con uno, el nombre de siempre (``None``).
    """
    if len(documentos) < 2:
        return [None] * len(documentos)
    return [f"{numero:02d}-{doc.ruta.stem}" for numero, doc in enumerate(documentos, 1)]


def publicar_en_cursos(
    aula: AulaVirtual,
    cfg: Config,
    documentos: list[Documento],
    base: Path,
    presencia: Presencia,
    *,
    entorno: str,
    visible: bool | None = None,
    solo_fechas: bool = False,
    verificados: Mapping[str, estado.Verificado] | None = None,
    vigente: Callable[[], bool] | None = None,
    cupo: dict | None = None,
    avisar_en_pruebas: bool = False,
    omitidos: Collection[int] = (),
    nombres: Mapping[int, str] | None = None,
    dir_vistas: Path | None = None,
    debug: bool = False,
) -> dict:
    """Publica ``documentos`` en ``entorno``; devuelve el informe del esquema cerrado.

    ``cfg`` es la configuración capturada al abrir la sesión (o al arrancar la terminal
    directa): alterar ``tiza.toml`` después no puede redirigir la publicación.

    Las diferencias entre la sesión y la terminal directa están documentadas arriba, en
    el docstring del módulo.
    """
    if entorno == "pruebas":
        return _en_pruebas(
            aula,
            cfg,
            documentos,
            base,
            presencia,
            visible=visible,
            solo_fechas=solo_fechas,
            cupo=cupo,
            avisar=avisar_en_pruebas,
            debug=debug,
        )
    return _en_real(
        aula,
        cfg,
        documentos,
        base,
        presencia,
        visible=visible,
        solo_fechas=solo_fechas,
        verificados=verificados,
        vigente=vigente,
        omitidos=omitidos,
        nombres=nombres or {},
        dir_vistas=dir_vistas,
        debug=debug,
    )


def _en_pruebas(
    aula: AulaVirtual,
    cfg: Config,
    documentos: list[Documento],
    base: Path,
    presencia: Presencia,
    *,
    visible: bool | None,
    solo_fechas: bool,
    cupo: dict | None,
    avisar: bool,
    debug: bool,
) -> dict:
    """El curso de pruebas: sin confirmación (la del destino es del llamador), con cupo."""
    comando, entorno = "publicar", "pruebas"
    curso = cfg.cursos.get("pruebas")
    if curso is None:
        return informe.crear(comando, "error", [], [], ["SIN_CURSO_PRUEBAS"], entorno)
    if solo_fechas:
        # Todo o nada antes de tocar el cupo ni la presencia: si algo no se puede cambiar,
        # no se consume cupo por un cambio que no va a ocurrir.
        try:
            secciones = aula.estructura(curso)
        except ErrorPublicacion as exc:
            return informe.crear(comando, "error", [], [], [exc.codigo], entorno, curso)
        codigo = codigo_solo_fechas(secciones, documentos)
        if codigo is not None:
            return informe.crear(comando, "error", [], [], [codigo], entorno, curso)
    if cupo is not None:
        if cupo["pruebas"] + len(documentos) > MAX_PUBLICACIONES_PRUEBAS:
            return informe.crear(comando, "error", [], [], ["LIMITE_PUBLICACIONES"], entorno, curso)
        cupo["pruebas"] += len(documentos)
    if avisar:
        presencia.informar(
            Aviso(
                "PUBLICANDO_EN_PRUEBAS",
                {"documentos": tuple(DocumentoResumen.de(doc, base) for doc in documentos)},
            )
        )
    return publicar_con(
        aula,
        entorno,
        curso,
        documentos,
        visible,
        base,
        presencia,
        debug=debug,
        solo_fechas=solo_fechas,
    )


def _en_real(
    aula: AulaVirtual,
    cfg: Config,
    documentos: list[Documento],
    base: Path,
    presencia: Presencia,
    *,
    visible: bool | None,
    solo_fechas: bool,
    verificados: Mapping[str, estado.Verificado] | None,
    vigente: Callable[[], bool] | None,
    omitidos: Collection[int],
    nombres: Mapping[int, str],
    dir_vistas: Path | None,
    debug: bool,
) -> dict:
    """Publica en cada curso real, en el orden de ``tiza.toml``, con una confirmación por curso.

    Si el docente dice que no a un curso, se omite y se sigue con el siguiente; si un curso
    falla, se para ahí y el informe dice qué cursos quedaron hechos. La puerta de real se
    comprueba una vez (el hash es del documento) y las vistas previas se generan una vez.
    """
    comando, entorno = "publicar", "real"
    reales = cfg.reales
    total = len(reales)
    sin_pruebas = "pruebas" not in cfg.cursos
    unico = reales[0] if total == 1 else None

    def fallo(codigo: str, curso: int | None = unico) -> dict:
        return informe.crear(comando, "error", [], [], [codigo], entorno, curso)

    if not solo_fechas:
        if sin_pruebas:
            if exige_oculto_sin_pruebas(cfg, visible, solo_fechas=solo_fechas):
                return fallo("SOLO_OCULTO_SIN_PRUEBAS")
            visible = False
        elif puerta_real(base, documentos, verificados):
            return fallo("VERIFICACION_PENDIENTE")
    vistas: list[Path | None] = [None] * len(documentos)
    if not solo_fechas and not sin_pruebas:
        # Sin curso de pruebas no hay verificación previa ni vista que enseñar:
        # se compensa publicando solo en oculto y con una confirmación corta.
        raiz_vistas = dir_vistas if dir_vistas is not None else base / rutas.CARPETA_TRABAJO
        try:
            vistas = [
                contenido.previsualizar(doc, raiz_vistas, nombre=nombre)
                for doc, nombre in zip(documentos, _nombres_de_vista(documentos), strict=True)
            ]
        except ErrorContenido as exc:
            return fallo(exc.codigo)
    cal, aviso_calendario = cargar_calendario(base)

    registro: list[tuple[int, int, dict | None]] = []  # (posición, curso, informe o None: omitido)
    for posicion, curso in enumerate(reales, 1):
        if curso in omitidos:
            registro.append((posicion, curso, None))
            continue
        if vigente is not None and posicion > 1 and not vigente():
            presencia.informar(Aviso("PETICION_RETIRADA"))
            registro.append((posicion, curso, fallo("PETICION_RETIRADA", curso)))
            break
        try:
            secciones = aula.estructura(curso)
        except ErrorPublicacion as exc:
            registro.append((posicion, curso, fallo(exc.codigo, curso)))
            break
        nombre_curso = nombres.get(curso)
        if solo_fechas:
            codigo = codigo_solo_fechas(secciones, documentos)
            if codigo is not None:
                registro.append((posicion, curso, fallo(codigo, curso)))
                break
            resumen = resumen_solo_fechas(
                aula,
                curso,
                nombre_curso,
                documentos,
                base,
                secciones,
                debug=debug,
                posicion=posicion,
                total=total,
            )
            confirmado = presencia.confirmar_real(resumen)
        elif sin_pruebas:
            corto = ResumenSinPruebas(
                curso=curso,
                nombre_curso=nombre_curso,
                documentos=tuple(
                    DocumentoBreve(
                        fichero=doc.ruta.name,
                        tipo=doc.tipo,
                        nombre=doc.nombre,
                        existe=publicar.ya_existe(secciones, doc),
                        itinerario=itinerario_de(doc, base),
                    )
                    for doc in documentos
                ),
                secciones_nuevas=tuple(publicar.secciones_que_faltan(secciones, documentos)),
                posicion=posicion,
                total=total,
            )
            confirmado = presencia.confirmar_real_sin_pruebas(corto)
        else:
            resumen = ResumenPublicacion(
                curso=curso,
                nombre_curso=nombre_curso,
                documentos=tuple(
                    DocumentoResumen.de(
                        doc,
                        base,
                        vista,
                        cambios=cambios_de_fechas(aula, secciones, doc, cal, debug=debug),
                    )
                    for doc, vista in zip(documentos, vistas, strict=True)
                ),
                secciones_nuevas=tuple(publicar.secciones_que_faltan(secciones, documentos)),
                visible=visible,
                aviso_calendario=aviso_calendario,
                posicion=posicion,
                total=total,
            )
            confirmado = presencia.confirmar_real(resumen)
        if not confirmado:
            registro.append((posicion, curso, None))
            continue
        if vigente is not None and not vigente():
            presencia.informar(Aviso("PETICION_RETIRADA"))
            registro.append((posicion, curso, fallo("PETICION_RETIRADA", curso)))
            break
        documento = publicar_con(
            aula,
            entorno,
            curso,
            documentos,
            None if solo_fechas else visible,
            base,
            presencia,
            debug=debug,
            solo_fechas=solo_fechas,
        )
        registro.append((posicion, curso, documento))
        if documento["resultado"] != "ok":
            break
    return informe_de_cursos(comando, entorno, total, unico, registro)


def informe_de_cursos(
    comando: str,
    entorno: str,
    total: int,
    unico: int | None,
    registro: list[tuple[int, int, dict | None]],
) -> dict:
    """Un informe con lo que pasó en cada curso real; con un solo curso, el de siempre."""
    if total == 1:
        informe_unico = registro[0][2]
        if informe_unico is None:
            return informe.crear(comando, "abortado", [], [], ["ABORTADO"], entorno, unico)
        return informe_unico
    pasos: list[dict] = []
    ficheros: list[dict] = []
    errores: list[str] = []
    login = any(
        paso["codigo"] == "LOGIN"
        for _, _, doc in registro
        if doc is not None
        for paso in doc["pasos"]
    )
    if login:
        pasos.append({"codigo": "LOGIN", "resultado": "ok", "detalle": None})
    publicados = 0
    for posicion, curso, doc in registro:
        if doc is None:
            pasos.append({"codigo": "CURSO_OMITIDO", "resultado": "ok", "detalle": str(curso)})
            continue
        fallido = doc["resultado"] != "ok"
        pasos.append(
            {
                "codigo": "CURSO",
                "resultado": "fallo" if fallido else "ok",
                "detalle": f"{posicion} de {total}: {curso}",
            }
        )
        pasos.extend(paso for paso in doc["pasos"] if paso["codigo"] != "LOGIN")
        ficheros.extend(doc["ficheros"])
        if fallido:
            errores.extend(doc["errores"])
        else:
            publicados += 1
    if errores:
        resultado = "error"
    elif publicados == 0:
        resultado, errores = "abortado", ["ABORTADO"]
    else:
        resultado = "ok"
    return informe.crear(comando, resultado, pasos, ficheros, errores, entorno, None)
