"""API de tiza para agentes embebidos: lo que la CLI ofrece al agente, sin consola.

Todo lo que devuelve pasa por el esquema cerrado
de :mod:`tiza.informe` o son textos propios de tiza; nunca texto de Moodle.
Nada aquí pide contraseñas ni se conecta al aula: lo que necesita el aula va
por el buzón a la sesión del docente.
"""

from __future__ import annotations

import textwrap
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from . import buzon, calendario, contenido, estado, informe, rutas
from .calendario import ErrorCalendario
from .calificacion.carpeta import cargar_calificacion
from .calificacion.esquema import EXTENSIONES_ESQUEMA, ErrorCalificacion
from .contenido import Documento, ErrorContenido, hash_documento
from .escritura import ErrorEscritura
from .estado import ErrorEstado, Estructura, buscar_seccion, cargar_estructura
from .ficheros import (
    FicheroNoSeguro,
    asegurar_directorio,
    escribir_texto,
    fichero_en_carpeta,
    leer_bytes_acotado,
)
from .lectura.modelo import ErrorLectura

__all__ = [
    "Comprobacion",
    "FicheroComprobado",
    "calificador",
    "comprobar",
    "copia",
    "documento",
    "estado_sesion",
    "estructura",
    "formato_documento",
    "importar",
    "leer",
    "ordenar",
    "peticion_calificador",
    "peticion_copia",
    "peticion_estructura",
    "peticion_ordenar",
    "peticion_publicar",
    "pista_worktree",
    "publicar",
]


@dataclass(frozen=True)
class FicheroComprobado:
    """Resultado de comprobar un fichero, con textos de tiza (nunca de Moodle)."""

    fichero: str
    codigo: str | None = None  # código de error; None si pasa
    detalle: str = ""  # explicación del error para quien corrige el fichero
    vista_previa: Path | None = None
    seccion_nueva: str | None = None  # sección por nombre que se creará (oculta) al publicar
    avisos: tuple[str, ...] = ()  # FECHA_FESTIVA… según calendario.toml; nunca son errores


@dataclass(frozen=True)
class Comprobacion:
    informe: dict  # esquema cerrado, como .tiza/informe.json
    ficheros: tuple[FicheroComprobado, ...]


def comprobar(carpeta: str | Path, ficheros: Sequence[str]) -> Comprobacion:
    """Valida los ``.md`` o ``.html`` sin red y genera sus vistas previas en ``.tiza/preview``.

    Comprueba también la sección contra ``.tiza/estructura.json`` si existe: en el curso
    de pruebas o, si no hay, en el real.
    Devuelve el informe validado; no lo escribe en disco.
    """
    base = Path(carpeta)
    raiz = base.resolve()
    dir_tiza = base / rutas.CARPETA_TRABAJO
    borrador = informe.Borrador("comprobar")
    resultados: list[FicheroComprobado] = []
    # Un esquema de calificación (.yaml) no necesita la estructura del aula ni el calendario.
    con_documentos = any(Path(n).suffix.lower() not in EXTENSIONES_ESQUEMA for n in ficheros)
    estructura: Estructura | None = None
    cal = None
    if con_documentos:
        try:
            estructura = cargar_estructura(dir_tiza)
        except ErrorEstado as exc:
            borrador.error(exc.codigo)
            borrador.fallo("ESTRUCTURA", exc.codigo)
        else:
            borrador.paso("ESTRUCTURA")

        # El calendario es una ayuda: si no se puede leer, el error se cuenta pero los
        # documentos se comprueban igual.
        try:
            cal = calendario.cargar(base)
        except ErrorCalendario as exc:
            borrador.error(exc.codigo)
            borrador.fallo("CALENDARIO", exc.detalle)

    for nombre in ficheros:
        ruta = base / nombre
        if ruta.suffix.lower() in EXTENSIONES_ESQUEMA:
            resultados.append(_comprobar_esquema(borrador, ruta, raiz))
            continue
        try:
            doc = contenido.cargar(ruta, raiz=raiz)
            vista = contenido.previsualizar(doc, dir_tiza)
        except ErrorContenido as exc:
            borrador.error(exc.codigo)
            borrador.fallo("COMPROBAR", f"{ruta.name}: {exc.codigo}")
            resultados.append(FicheroComprobado(ruta.name, exc.codigo, exc.detalle))
            continue
        avisos_doc: list[str] = []
        for campo, dia, clase in calendario.fechas_del_documento(doc):
            for codigo in calendario.avisos(cal, dia, clase=clase):
                avisos_doc.append(codigo)
                detalle = f"{ruta.name}: {campo} {dia.isoformat()}"
                borrador.paso(codigo, detalle=detalle)
        avisos = tuple(avisos_doc)
        if _con_dolar_simple(doc):
            borrador.paso("FORMULA_DOLAR_SIMPLE", detalle=ruta.name)
        problema = revisar_dependencias(doc, raiz)
        if problema is not None:
            borrador.error(problema[0])
            borrador.fallo("COMPROBAR", f"{ruta.name}: {problema[0]}")
            resultados.append(FicheroComprobado(ruta.name, problema[0], problema[1], avisos=avisos))
            continue
        for relativa in doc.restricciones.completar if doc.restricciones else ():
            dependencia = contenido.cargar(raiz / relativa, raiz=raiz)
            if dependencia.finalizacion is None or dependencia.finalizacion.modo == "ninguna":
                # Sin finalización no hay nada que completar: se avisa, no se bloquea (el aula
                # puede tenerla puesta a mano y tiza no lee el aula al comprobar).
                borrador.paso("DEPENDENCIA_SIN_FINALIZACION", detalle=f"{ruta.name}: {relativa}")
        curso = _curso_a_comprobar(estructura)
        seccion = buscar_seccion(curso[1], doc.seccion) if curso is not None else None
        if curso is not None and seccion is None and isinstance(doc.seccion, str):
            borrador.paso("COMPROBAR", detalle=ruta.name)
            borrador.fichero(_fichero(doc, doc.seccion))
            resultados.append(
                FicheroComprobado(
                    ruta.name, vista_previa=vista, seccion_nueva=doc.seccion, avisos=avisos
                )
            )
            continue
        pista = (
            _pista_de_id(estructura, doc)
            if estructura is not None and curso is not None and seccion is None
            else None
        )
        if pista is not None:
            borrador.error("SECCION_ES_ID")
            borrador.fallo("COMPROBAR", f"{ruta.name}: SECCION_ES_ID")
            resultados.append(FicheroComprobado(ruta.name, "SECCION_ES_ID", pista, avisos=avisos))
        elif curso is not None and seccion is None:
            borrador.error("SECCION_AUSENTE")
            borrador.fallo("COMPROBAR", f"{ruta.name}: SECCION_AUSENTE")
            detalle = (
                f"no existe la sección {doc.seccion} en el curso de {curso[0]} "
                f"({rutas.CARPETA_TRABAJO}/{estado.FICHERO_ESTRUCTURA})"
            )
            resultados.append(
                FicheroComprobado(ruta.name, "SECCION_AUSENTE", detalle, avisos=avisos)
            )
        else:
            borrador.paso("COMPROBAR", detalle=ruta.name)
            if _seccion_distinta_entre_cursos(estructura, doc):
                # Texto fijo: el fichero y el número, nunca los nombres de las secciones.
                borrador.paso(
                    "SECCION_DISTINTA_ENTRE_CURSOS", detalle=f"{ruta.name}: sección {doc.seccion}"
                )
            resultados.append(FicheroComprobado(ruta.name, vista_previa=vista, avisos=avisos))
        borrador.fichero(_fichero(doc, seccion["nombre"] if seccion else None))

    return Comprobacion(borrador.documento(), tuple(resultados))


def _comprobar_esquema(borrador: informe.Borrador, ruta: Path, raiz: Path) -> FicheroComprobado:
    """Un ``.yaml`` de calificación: su forma y que las actividades de la carpeta cuadren. Sin red.

    Es lo que ``tiza calificador`` comprueba antes de tocar el aula (el calificador anterior del
    curso no cambia si hay errores: solo cambia lo que se coloca, no si algo es válido).
    """
    try:
        cargar_calificacion(ruta, raiz)
    except ErrorCalificacion as exc:
        borrador.error(exc.codigo)
        borrador.fallo("COMPROBAR", f"{ruta.name}: {exc.codigo}")
        return FicheroComprobado(ruta.name, exc.codigo, exc.detalle)
    borrador.paso("COMPROBAR", detalle=ruta.name)
    return FicheroComprobado(ruta.name)


def _con_dolar_simple(doc: Documento) -> bool:
    """Un ``$x$`` en un .md: Moodle no lo dibuja (valen ``\\(…\\)``, ``\\[…\\]`` y ``$$…$$``)."""
    if doc.ruta.suffix.lower() in (".html", ".htm"):
        return False
    fuentes = [doc.cuerpo]
    if doc.cuestionario is not None:
        for pregunta in doc.cuestionario.preguntas:
            fuentes.extend([pregunta.enunciado, pregunta.retro or ""])
            for opcion in pregunta.opciones:
                fuentes.extend([opcion.texto, opcion.retro or ""])
    return any(contenido.hay_dolar_simple(fuente) for fuente in fuentes)


MAX_PROFUNDIDAD_DEPENDENCIAS = 20


def revisar_dependencias(doc: Documento, raiz: Path) -> tuple[str, str] | None:
    """Comprueba los ficheros de ``completar``: que existan, sean válidos y no formen un ciclo.

    Devuelve (código, detalle) o None. El detalle solo nombra ficheros de la carpeta.
    """
    cargados: dict[str, Documento | None] = {}

    def cargar_dep(relativa: str) -> Documento | None:
        if relativa not in cargados:
            try:
                cargados[relativa] = contenido.cargar(raiz / relativa, raiz=raiz)
            except ErrorContenido:
                cargados[relativa] = None
        return cargados[relativa]

    def visitar(actual: Documento, camino: tuple[Path, ...]) -> tuple[str, str] | None:
        if actual.restricciones is None:
            return None
        for relativa in actual.restricciones.completar:
            dep = cargar_dep(relativa)
            if dep is None:
                return "DEPENDENCIA_INVALIDA", relativa
            ruta = dep.ruta.resolve()
            if ruta in camino or len(camino) >= MAX_PROFUNDIDAD_DEPENDENCIAS:
                return "DEPENDENCIA_CIRCULAR", relativa
            problema = visitar(dep, (*camino, ruta))
            if problema is not None:
                return problema
        return None

    return visitar(doc, (doc.ruta.resolve(),))


def _fichero(doc: Documento, seccion: str | None) -> informe.Fichero:
    return informe.Fichero(
        nombre=doc.ruta.name,
        tipo=doc.tipo,
        seccion=seccion,
        hash=hash_documento(doc),
    )


def _cursos_de(estructura: Estructura | None, entorno: str) -> list[list]:
    """Las secciones de cada curso de ``entorno`` (estado ya unifica v1 y v2)."""
    if estructura is None:
        return []
    return [curso["secciones"] for curso in estructura.cursos(entorno)]


def _curso_a_comprobar(estructura: Estructura | None) -> tuple[str, list] | None:
    """El curso donde se publicará: el de pruebas o, si no hay, el primer real."""
    if estructura is None:
        return None
    for entorno in ("pruebas", "real"):
        cursos = estructura.cursos(entorno)
        if cursos:
            return entorno, cursos[0]["secciones"]
    return None


def _seccion_distinta_entre_cursos(estructura: Estructura | None, doc: Documento) -> bool:
    """¿El número de sección de ``doc`` tiene nombres distintos en los cursos reales?"""
    if not isinstance(doc.seccion, int) or isinstance(doc.seccion, bool):
        return False
    reales = _cursos_de(estructura, "real")
    if len(reales) < 2:
        return False
    nombres = set()
    for secciones in reales:
        seccion = buscar_seccion(secciones, doc.seccion)
        nombres.add(str(seccion.get("nombre")) if seccion else None)
    return len(nombres) > 1


def _pista_de_id(estructura: Estructura, doc: Documento) -> str | None:
    """Si ``seccion`` es el id de la URL del aula, el texto que dice qué número poner."""
    for entorno in ("pruebas", "real"):
        for secciones in _cursos_de(estructura, entorno):
            for seccion in secciones:
                if isinstance(seccion, dict) and seccion.get("id") == doc.seccion:
                    return (
                        f"{doc.seccion} es el id de la sección «{seccion.get('nombre')}» del curso "
                        f"de {entorno}; escribe «seccion: {seccion.get('numero')}»."
                    )
    return None


def peticion_publicar(
    ficheros: Sequence[str],
    entorno: str,
    visible: bool | None = None,
    *,
    solo_fechas: bool = False,
) -> dict:
    """Petición de publicar para el buzón (``visible=None``: lo que exista conserva).

    ``solo_fechas`` cambia solo las fechas de tareas y cuestionarios ya publicados;
    no admite ``visible``.
    """
    return {
        "version": buzon.VERSION_PROTOCOLO,
        "id": uuid.uuid4().hex,
        "comando": "publicar",
        "ficheros": list(ficheros),
        "entorno": entorno,
        "visible": visible,
        "solo_fechas": solo_fechas,
    }


def peticion_ordenar(ficheros: Sequence[str], entorno: str) -> dict:
    """Petición de ordenar para el buzón: deja las actividades de esos ficheros en ese orden.

    No admite visibilidad ni fechas: ordenar solo cambia el orden dentro de cada sección.
    """
    return {
        "version": buzon.VERSION_PROTOCOLO,
        "id": uuid.uuid4().hex,
        "comando": "ordenar",
        "ficheros": list(ficheros),
        "entorno": entorno,
        "visible": None,
        "solo_fechas": False,
    }


def peticion_calificador(esquema: str, entorno: str) -> dict:
    """Petición de calificador para el buzón: monta el calificador del curso según ``esquema``.

    ``esquema`` es el ``.yaml`` de la carpeta; las actividades las lee la sesión de la carpeta.
    No admite visibilidad ni fechas.
    """
    return {
        "version": buzon.VERSION_PROTOCOLO,
        "id": uuid.uuid4().hex,
        "comando": "calificador",
        "ficheros": [esquema],
        "entorno": entorno,
        "visible": None,
        "solo_fechas": False,
    }


def peticion_copia(curso: str, ficheros: Sequence[str] = ()) -> dict:
    """Petición de copia para el buzón: ``curso`` es ``pruebas``, ``real`` o el id de un curso.

    Pide una copia de seguridad del curso, sin datos de usuarios, que queda en ``.tiza/copias/``.
    Con ``ficheros`` (las actividades de la carpeta, nunca sus cmids), una copia de cada una.
    """
    return {
        "version": buzon.VERSION_PROTOCOLO,
        "id": uuid.uuid4().hex,
        "comando": "copia",
        "curso": curso,
        "ficheros": list(ficheros),
        "entorno": None,
        "visible": None,
        "solo_fechas": False,
    }


def peticion_estructura() -> dict:
    return {
        "version": buzon.VERSION_PROTOCOLO,
        "id": uuid.uuid4().hex,
        "comando": "estructura",
        "ficheros": [],
        "entorno": None,
        "visible": None,
        "solo_fechas": False,
    }


def publicar(
    carpeta: str | Path,
    ficheros: Sequence[str],
    entorno: str,
    *,
    visible: bool | None = None,
    solo_fechas: bool = False,
    espera: float = buzon.ESPERA_POR_DEFECTO,
    cancelar: threading.Event | None = None,
) -> dict:
    """Pide a la sesión del docente que publique; en real, el docente confirma."""
    peticion = peticion_publicar(ficheros, entorno, visible, solo_fechas=solo_fechas)
    return _enviar(carpeta, peticion, espera, cancelar)


def ordenar(
    carpeta: str | Path,
    ficheros: Sequence[str],
    entorno: str,
    *,
    espera: float = buzon.ESPERA_POR_DEFECTO,
    cancelar: threading.Event | None = None,
) -> dict:
    """Pide a la sesión del docente que ordene las actividades de ``ficheros``; en real, confirma."""
    return _enviar(carpeta, peticion_ordenar(ficheros, entorno), espera, cancelar)


def calificador(
    carpeta: str | Path,
    esquema: str,
    entorno: str,
    *,
    espera: float = buzon.ESPERA_CALIFICADOR,
    cancelar: threading.Event | None = None,
) -> dict:
    """Pide a la sesión del docente que monte el calificador del curso según ``esquema``.

    En real, el docente confirma en su terminal, curso por curso, con lo que va a pasar. Antes
    se puede comprobar el esquema sin red con ``comprobar``. Sin sesión, ``SIN_SESION``. Espera
    hasta una hora (``buzon.ESPERA_CALIFICADOR``): montar un curso grande pasa de 10 minutos.
    """
    return _enviar(carpeta, peticion_calificador(esquema, entorno), espera, cancelar)


def copia(
    carpeta: str | Path,
    curso: str,
    ficheros: Sequence[str] = (),
    *,
    espera: float = buzon.ESPERA_POR_DEFECTO,
    cancelar: threading.Event | None = None,
) -> dict:
    """Pide a la sesión del docente una copia del curso (sin usuarios) en ``.tiza/copias/``.

    El docente confirma en su terminal. El informe lleva la lista de copias hechas (ruta y recuento
    de actividades de cada una); después se leen con ``importar``. Con ``ficheros``, una copia de
    cada actividad (solo de cursos reales y de actividades que tiza ya conoce). Sin sesión,
    ``SIN_SESION``.
    """
    return _enviar(carpeta, peticion_copia(curso, ficheros), espera, cancelar)


def estructura(
    carpeta: str | Path,
    *,
    espera: float = buzon.ESPERA_POR_DEFECTO,
    cancelar: threading.Event | None = None,
) -> dict:
    """Pide a la sesión del docente que actualice ``.tiza/estructura.json``."""
    return _enviar(carpeta, peticion_estructura(), espera, cancelar)


def estado_sesion(carpeta: str | Path) -> dict:
    """Si hay sesión del docente en la carpeta y hasta cuándo, para enseñarlo."""
    dir_tiza = Path(carpeta) / rutas.CARPETA_TRABAJO
    caduca = buzon.caducidad(dir_tiza)
    if caduca is not None:
        return {"activa": True, "caduca": caduca.isoformat(), "compatible": True}
    if buzon.sesion_incompatible(dir_tiza) is not None:
        return {"activa": True, "caduca": None, "compatible": False}
    return {"activa": False, "caduca": None, "compatible": True}


class _Cancelada(Exception):
    """El docente dejó de esperar."""


def pista_worktree(carpeta: str | Path) -> str | None:
    """Pista cuando la carpeta es un worktree enlazado de git (``.git`` es un fichero).

    En un worktree, el buzón de la asignatura no existe: el agente debe trabajar
    desde la carpeta de la asignatura, donde el docente abrió la sesión.
    """
    if (Path(carpeta) / ".git").is_file():
        return (
            "estás en un worktree de git; abre la sesión del agente en la carpeta de la asignatura"
        )
    return None


def _enviar(
    carpeta: str | Path, peticion: dict, espera: float, cancelar: threading.Event | None
) -> dict:
    dir_tiza = Path(carpeta) / rutas.CARPETA_TRABAJO
    comando, entorno = peticion["comando"], peticion["entorno"]
    if not buzon.sesion_activa(dir_tiza):
        codigo = "SESION_INCOMPATIBLE" if buzon.sesion_incompatible(dir_tiza) else "SIN_SESION"
        borrador = informe.Borrador(comando, entorno=entorno)
        borrador.error(codigo)
        if codigo == "SIN_SESION":
            pista = pista_worktree(carpeta)
            if pista is not None:
                borrador.fallo("SIN_SESION", pista)
        return borrador.documento("error")

    def dormir(segundos: float) -> None:
        if cancelar is None:
            time.sleep(segundos)
        elif cancelar.wait(segundos):
            raise _Cancelada

    try:
        return buzon.enviar(dir_tiza, peticion, espera, dormir=dormir)
    except _Cancelada:  # enviar ya ha retirado la petición del buzón
        return informe.crear(comando, "abortado", [], [], ["ABORTADO"], entorno)
    except buzon.ErrorBuzon as exc:
        return informe.crear(comando, "error", [], [], [exc.codigo], entorno)


_INICIO_FORMATO = "<!-- formato:inicio -->"
_FIN_FORMATO = "<!-- formato:fin -->"


def formato_documento() -> str:
    """Formato de los ficheros (``.md`` o ``.html``) de tiza: frontmatter, fechas, recursos y filtro.

    Sale de la skill (``skill/tiza/SKILL.md``), que es la única fuente:
    lo leen los agentes con la skill instalada y la app con su asistente.
    """
    ruta = resources.files("tiza") / "skill" / "tiza" / "SKILL.md"
    texto = ruta.read_text(encoding="utf-8")
    inicio = texto.index(_INICIO_FORMATO) + len(_INICIO_FORMATO)
    fin = texto.index(_FIN_FORMATO, inicio)
    return textwrap.dedent(texto[inicio:fin]).strip()


EXTENSIONES_LECTURA = frozenset({".docx", ".pdf"})


def _contar_tablas(bloques) -> int:
    return sum((bloque.tipo == "tabla") + _contar_tablas(bloque.hijos) for bloque in bloques)


def leer(ruta: str | Path, carpeta: str | Path) -> informe.Lectura:
    """Lee un Word o un PDF de la asignatura y guarda su texto en ``.tiza/lecturas/``.

    Offline. Devuelve el resumen validado; el agente abre después el texto. Lanza
    ``ErrorLectura`` con un código estable si el fichero no vale. Las librerías de lectura se
    importan aquí para que el resto de comandos no las carguen.
    """
    from .lectura.modelo import a_texto
    from .lectura.pdf import leer_pdf
    from .lectura.word import leer_docx

    base = Path(carpeta)
    origen = fichero_en_carpeta(ruta, base, EXTENSIONES_LECTURA)
    lector = leer_pdf if origen.suffix.lower() == ".pdf" else leer_docx
    try:
        lectura = lector(origen)
    except FileNotFoundError:
        raise ErrorLectura("DOCUMENTO_AUSENTE", f"No existe el fichero {origen.name}.") from None
    except OSError:  # permisos, bloqueo u otro fallo del sistema que el lector no mapeó
        raise ErrorLectura("FICHERO_BLOQUEADO", "El fichero no se puede abrir.") from None
    destino = estado.ruta_lectura(base, origen)
    # Primero el resumen validado: si no vale, no se deja nada escrito.
    resumen = informe.Lectura(
        fichero=origen.relative_to(base.resolve()).as_posix(),
        formato=lectura.formato,
        lectura=destino.relative_to(base).as_posix(),
        bloques=len(lectura.bloques),
        tablas=_contar_tablas(lectura.bloques),
        paginas=lectura.paginas,
        avisos=tuple(lectura.avisos),
        sha256=lectura.sha256,
    )
    try:
        asegurar_directorio(base / rutas.CARPETA_TRABAJO)
        asegurar_directorio(destino.parent)
        escribir_texto(destino, a_texto(lectura))
    except OSError:
        raise ErrorLectura(
            "LECTURA_NO_ESCRIBIBLE", f"No se pudo guardar en {rutas.CARPETA_TRABAJO}/lecturas."
        ) from None
    return resumen


def documento(
    fuente: str | Path, carpeta: str | Path, salida: str | Path | None = None
) -> informe.Documento:
    """Convierte un ``.md`` de la asignatura en un Word sencillo (``.docx``) en la misma carpeta.

    Offline. Sin ``salida`` usa el nombre de la fuente con ``.docx``. Nunca sobrescribe un
    Word (``DOCUMENTO_EXISTE``) y solo escribe dentro de la carpeta. Lanza ``ErrorEscritura``
    con un código estable; las librerías del Word se importan aquí.
    """
    from .escritura.word import escribir_docx

    base = Path(carpeta)
    try:
        origen = fichero_en_carpeta(fuente, base, {".md"})
        destino = fichero_en_carpeta(
            salida if salida is not None else origen.with_suffix(".docx"), base, {".docx"}
        )
    except ErrorLectura as error:
        raise ErrorEscritura(error.codigo, error.detalle) from None
    try:
        texto = leer_bytes_acotado(origen, contenido.MAX_DOCUMENTO_BYTES).decode("utf-8-sig")
    except FileNotFoundError:
        raise ErrorEscritura("DOCUMENTO_AUSENTE", f"No existe el fichero {origen.name}.") from None
    except FicheroNoSeguro as exc:
        if exc.motivo == "grande":
            raise ErrorEscritura(
                "FICHERO_DEMASIADO_GRANDE", f"{origen.name} pesa más de 2 MB."
            ) from None
        raise ErrorEscritura("FICHERO_BLOQUEADO", f"No se puede leer {origen.name}.") from None
    except UnicodeDecodeError:
        raise ErrorEscritura("FORMATO_NO_ADMITIDO", f"{origen.name} no está en UTF-8.") from None
    except OSError:
        raise ErrorEscritura("FICHERO_BLOQUEADO", f"No se puede leer {origen.name}.") from None
    fuente_rel = origen.relative_to(base.resolve()).as_posix()
    documento_rel = destino.relative_to(base.resolve()).as_posix()
    # Se valida el resumen antes de escribir: si no vale, no queda ningún Word.
    informe.Documento(fuente=fuente_rel, documento=documento_rel, bloques=0)
    bloques = escribir_docx(texto, destino)
    return informe.Documento(fuente=fuente_rel, documento=documento_rel, bloques=bloques)


def rellenar(relleno: str | Path, carpeta: str | Path) -> informe.Relleno:
    """Aplica un ``relleno.yaml`` sobre una copia de la plantilla Word de la asignatura.

    Offline. Nunca sobrescribe un Word y solo escribe dentro de la carpeta. Lanza
    ``ErrorEscritura`` o ``ErrorLectura`` con un código estable; las librerías del Word y
    del YAML se importan aquí.
    """
    from .escritura import rellenar as aplicador
    from .escritura import relleno as lector

    base = Path(carpeta)
    origen = fichero_en_carpeta(relleno, base, {".yaml", ".yml"})
    datos = lector.cargar_relleno(origen, base)
    resultado = aplicador.rellenar(base, datos)
    raiz = base.resolve()
    return informe.Relleno(
        plantilla=datos.plantilla.resolve().relative_to(raiz).as_posix(),
        salida=resultado.salida.resolve().relative_to(raiz).as_posix(),
        operaciones=resultado.operaciones,
        avisos=resultado.avisos,
        sustituciones=resultado.sustituciones,
    )


def importar(
    copia: str | Path,
    carpeta: str | Path,
    destino: str = "aula",
    como_nuevas: bool = False,
) -> informe.ResumenImportacion:
    """Convierte una copia de seguridad de Moodle (``.mbz``) en ficheros de tiza editables.

    Offline. La copia es un ``.mbz`` de la carpeta de la asignatura o uno que ``tiza copia`` dejó
    en ``.tiza/copias/``. Escribe un fichero por actividad en ``<carpeta>/<destino>/``, con su
    ``origen``, y el resumen ``.tiza/copia.json``; nunca sobrescribe nada. Devuelve el resumen
    validado (los recuentos por estado). Lanza ``ErrorImportar``, ``ErrorCopia``,
    ``ErrorLectura`` (la ruta de la copia) o ``ErrorConfig`` (``tiza.toml``) con un código estable.
    """
    from . import importar as importador

    return importador.importar(carpeta, copia, destino, como_nuevas)
