"""Construye copias de seguridad ``.mbz`` sintéticas (tar.gz y zip) con la estructura medida.

La estructura es la de la copia real que hizo el profesor en el Moodle de pruebas (espiga 4):
``moodle_backup.xml`` con ``information`` y ``settings``, ``sections/section_<id>/section.xml``,
``activities/<módulo>_<cmid>/module.xml`` y ``<módulo>.xml``, ``files.xml`` con
``files/<xx>/<hash>`` y ``questions.xml``. Todo se genera en memoria: ninguna copia real entra
en el repositorio.

Uso típico::

    datos = construir_mbz(
        [SeccionFalsa(id=7, numero=1, nombre="Tema 1")],
        [ActividadFalsa(cmid=501, modulo="page", seccion_id=7, nombre="Intro", html="<p>Hola</p>")],
    )
    ruta = escribir_mbz(tmp_path / "copia.mbz", secciones, actividades, formato="zip")

``DATOS_DE_USUARIO`` son los valores que la fábrica pone en ``author``, ``userid``, ``createdby``
y ``modifiedby``: ningún objeto leído de la copia debe contenerlos.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

AUTOR = "Autora Secreta Zubiri"
USUARIO = "987654"
DATOS_DE_USUARIO = (AUTOR, USUARIO)

CABECERA = '<?xml version="1.0" encoding="UTF-8"?>\n'


@dataclass
class SeccionFalsa:
    id: int
    numero: int
    nombre: str = ""
    resumen: str = ""
    visible: bool = True


@dataclass
class FicheroFalso:
    nombre: str
    contenido: bytes
    filearea: str = "content"
    componente: str = ""  # por defecto, mod_<módulo>


@dataclass
class PreguntaFalsa:
    """Una pregunta del banco; ``versiones``: (número, texto[, estado]) de cada versión."""

    entrada: int
    nombre: str = "P01"
    versiones: Sequence[tuple[int, str] | tuple[int, str, str]] = ((1, "Uno es uno"),)
    tipo: str = "truefalse"
    respuestas: Sequence[tuple[str, float]] = (("Verdadero", 1.0), ("Falso", 0.0))
    fijada: int | None = None  # versión que fija el cuestionario (None = la última)
    estado: str = "ready"  # estado de todas sus versiones
    modo: str = "normal"  # "aleatoria": hueco aleatorio; "ausente": no está en questions.xml
    ajustes: Mapping[str, str] | None = None  # ajustes del tipo (por defecto, single=1)
    tolerancia: float | None = None  # numérica: tolerancia de cada respuesta (numerical_answers)


@dataclass
class ActividadFalsa:
    cmid: int
    modulo: str
    seccion_id: int
    nombre: str
    html: str = ""
    visible: bool = True
    fechas: Mapping[str, int] = field(default_factory=dict)  # nombre del campo -> segundos
    ficheros: Sequence[FicheroFalso] = ()
    preguntas: Sequence[PreguntaFalsa] = ()
    module_id: int | None = None  # para forzar un module.xml que no coincide
    xml_propio: bytes | None = None  # sustituye a <módulo>.xml entero
    ajustes: Mapping[str, object] = field(default_factory=dict)  # attempts_number, timelimit…


def _e(texto: object) -> str:
    return escape(str(texto))


def _hash(contenido: bytes) -> str:
    return hashlib.sha1(contenido).hexdigest()


def _contexto(actividad: ActividadFalsa) -> int:
    return 1000 + actividad.cmid


def _moodle_backup(
    secciones: Sequence[SeccionFalsa],
    actividades: Sequence[ActividadFalsa],
    users: int,
    curso: int,
    servidor: str,
) -> bytes:
    acts = "".join(
        f"<activity><moduleid>{a.cmid}</moduleid><sectionid>{a.seccion_id}</sectionid>"
        f"<modulename>{_e(a.modulo)}</modulename><title>{_e(a.nombre)}</title>"
        f"<directory>activities/{_e(a.modulo)}_{a.cmid}</directory>"
        "<insubsection></insubsection></activity>"
        for a in actividades
    )
    secs = "".join(
        f"<section><sectionid>{s.id}</sectionid><title>{s.numero}</title>"
        f"<directory>sections/section_{s.id}</directory></section>"
        for s in secciones
    )
    return (
        f"{CABECERA}<moodle_backup><information>"
        "<name>copia.mbz</name><moodle_version>2024100715</moodle_version>"
        "<moodle_release>4.5.15 (Build: 20261005)</moodle_release>"
        f"<original_wwwroot>{_e(servidor)}</original_wwwroot>"
        f"<original_course_id>{curso}</original_course_id>"
        f"<contents><activities>{acts}</activities><sections>{secs}</sections>"
        "<course><courseid>2</courseid><title>pruebas</title><directory>course</directory>"
        "</course></contents>"
        "<settings>"
        f"<setting><level>root</level><name>users</name><value>{users}</value></setting>"
        "<setting><level>root</level><name>activities</name><value>1</value></setting>"
        "<setting><level>activity</level><activity>page_1</activity>"
        "<name>page_1_userinfo</name><value>0</value></setting>"
        "</settings></information></moodle_backup>"
    ).encode()


def _seccion(seccion: SeccionFalsa, actividades: Sequence[ActividadFalsa]) -> bytes:
    secuencia = ",".join(str(a.cmid) for a in actividades if a.seccion_id == seccion.id)
    nombre = _e(seccion.nombre) if seccion.nombre else "$@NULL@$"
    return (
        f'{CABECERA}<section id="{seccion.id}"><number>{seccion.numero}</number>'
        f"<name>{nombre}</name><summary>{_e(seccion.resumen)}</summary>"
        f"<summaryformat>1</summaryformat><sequence>{secuencia}</sequence>"
        f"<visible>{int(seccion.visible)}</visible>"
        f"<timemodified>1792250619</timemodified></section>"
    ).encode()


def _module(actividad: ActividadFalsa) -> bytes:
    identificador = actividad.module_id if actividad.module_id is not None else actividad.cmid
    return (
        f'{CABECERA}<module id="{identificador}" version="2024100700">'
        f"<modulename>{_e(actividad.modulo)}</modulename>"
        f"<sectionid>{actividad.seccion_id}</sectionid><sectionnumber>1</sectionnumber>"
        f"<added>1792250621</added><visible>{int(actividad.visible)}</visible>"
        "<tags></tags></module>"
    ).encode()


def _instancias(actividad: ActividadFalsa) -> str:
    partes = []
    for hueco, pregunta in enumerate(actividad.preguntas, start=1):
        if pregunta.modo == "aleatoria":
            partes.append(
                f'<question_instance id="{hueco}"><slot>{hueco}</slot><page>1</page>'
                "<maxmark>1.0000000</maxmark>"
                f'<question_set_reference id="{hueco}"><component>mod_quiz</component>'
                "<filtercondition>{}</filtercondition></question_set_reference>"
                "</question_instance>"
            )
            continue
        version = "$@NULL@$" if pregunta.fijada is None else str(pregunta.fijada)
        partes.append(
            f'<question_instance id="{hueco}"><slot>{hueco}</slot><page>1</page>'
            "<maxmark>2.0000000</maxmark>"
            f'<question_reference id="{hueco}"><component>mod_quiz</component>'
            f"<questionbankentryid>{pregunta.entrada}</questionbankentryid>"
            f"<version>{version}</version></question_reference></question_instance>"
        )
    return f"<question_instances>{''.join(partes)}</question_instances>"


def _principal(actividad: ActividadFalsa) -> bytes:
    if actividad.xml_propio is not None:
        return actividad.xml_propio
    if actividad.modulo == "page":
        cuerpo = f"<intro></intro><content>{_e(actividad.html)}</content>"
    else:
        cuerpo = f"<intro>{_e(actividad.html)}</intro>"
    cuerpo += f"<createdby>{USUARIO}</createdby><author>{AUTOR}</author>"
    cuerpo += "".join(f"<{k}>{v}</{k}>" for k, v in actividad.fechas.items())
    if actividad.modulo == "assign":
        cuerpo += "<userflags></userflags><submissions></submissions><grades></grades>"
    if actividad.modulo == "quiz":
        cuerpo += "".join(f"<{k}>{_e(v)}</{k}>" for k, v in actividad.ajustes.items())
        cuerpo += _instancias(actividad)
    return (
        f'{CABECERA}<activity id="9" moduleid="{actividad.cmid}" '
        f'modulename="{_e(actividad.modulo)}" contextid="{_contexto(actividad)}">'
        f'<{actividad.modulo} id="9"><name>{_e(actividad.nombre)}</name>{cuerpo}'
        f"</{actividad.modulo}></activity>"
    ).encode()


def _files_xml(actividades: Sequence[ActividadFalsa]) -> bytes:
    partes = []
    identificador = 2000
    for actividad in actividades:
        componente_base = f"mod_{actividad.modulo}"
        for fichero in actividad.ficheros:
            componente = fichero.componente or componente_base
            for nombre, contenido in ((fichero.nombre, fichero.contenido), (".", b"")):
                identificador += 1
                partes.append(
                    f'<file id="{identificador}"><contenthash>{_hash(contenido)}</contenthash>'
                    f"<contextid>{_contexto(actividad)}</contextid>"
                    f"<component>{_e(componente)}</component>"
                    f"<filearea>{_e(fichero.filearea)}</filearea><itemid>0</itemid>"
                    f"<filepath>/</filepath><filename>{_e(nombre)}</filename>"
                    f"<userid>{USUARIO}</userid><filesize>{len(contenido)}</filesize>"
                    f"<author>{AUTOR}</author><license>unknown</license></file>"
                )
    return f"{CABECERA}<files>{''.join(partes)}</files>".encode()


def _ajustes(pregunta: PreguntaFalsa) -> str:
    ajustes = pregunta.ajustes if pregunta.ajustes is not None else {"single": "1"}
    return "".join(f"<{k}>{_e(v)}</{k}>" for k, v in ajustes.items())


def _numericas(pregunta: PreguntaFalsa) -> str:
    if pregunta.tolerancia is None:
        return ""
    partes = "".join(
        f'<numerical_answer id="{n}"><answer>{n}</answer>'
        f"<tolerance>{pregunta.tolerancia}</tolerance></numerical_answer>"
        for n, _ in enumerate(pregunta.respuestas, start=1)
    )
    return f"<numerical_answers>{partes}</numerical_answers>"


def _questions_xml(actividades: Sequence[ActividadFalsa]) -> bytes:
    entradas = []
    identificador = 100
    for actividad in actividades:
        for pregunta in actividad.preguntas:
            if pregunta.modo != "normal":
                continue
            versiones = []
            for numero, texto, *resto in pregunta.versiones:
                estado = resto[0] if resto else pregunta.estado
                identificador += 1
                respuestas = "".join(
                    f"<answer id='{n}'><answertext>{_e(t)}</answertext>"
                    f"<fraction>{f}</fraction><feedback></feedback></answer>"
                    for n, (t, f) in enumerate(pregunta.respuestas, start=1)
                )
                versiones.append(
                    f'<question_versions id="{identificador}"><version>{numero}</version>'
                    f'<status>{estado}</status><questions><question id="{identificador}">'
                    f"<name>{_e(pregunta.nombre)}</name><questiontext>{_e(texto)}</questiontext>"
                    "<generalfeedback></generalfeedback><defaultmark>1.0000000</defaultmark>"
                    f"<qtype>{_e(pregunta.tipo)}</qtype>"
                    f"<createdby>{USUARIO}</createdby><modifiedby>{USUARIO}</modifiedby>"
                    f"<plugin_qtype_{pregunta.tipo}_question><answers>{respuestas}</answers>"
                    f"{_numericas(pregunta)}"
                    f'<{pregunta.tipo} id="1">{_ajustes(pregunta)}</{pregunta.tipo}>'
                    f"</plugin_qtype_{pregunta.tipo}_question>"
                    "</question></questions></question_versions>"
                )
            entradas.append(
                f'<question_bank_entry id="{pregunta.entrada}"><ownerid>{USUARIO}</ownerid>'
                f"<question_version>{''.join(versiones)}</question_version></question_bank_entry>"
            )
    return (
        f'{CABECERA}<question_categories><question_category id="52"><name>Por defecto</name>'
        f"<question_bank_entries>{''.join(entradas)}</question_bank_entries>"
        "</question_category></question_categories>"
    ).encode()


def entradas_de_copia(
    secciones: Sequence[SeccionFalsa],
    actividades: Sequence[ActividadFalsa],
    *,
    users: int = 0,
    curso: int = 2,
    servidor: str = "https://aula.example.org",
) -> dict[str, bytes]:
    """Los ficheros de la copia (nombre en el archivo -> contenido), sin empaquetar."""
    entradas: dict[str, bytes] = {
        "moodle_backup.xml": _moodle_backup(secciones, actividades, users, curso, servidor),
        "files.xml": _files_xml(actividades),
        "questions.xml": _questions_xml(actividades),
    }
    if users:
        entradas["users.xml"] = (
            f"{CABECERA}<users><user><username>{AUTOR}</username></user></users>".encode()
        )
    for seccion in secciones:
        entradas[f"sections/section_{seccion.id}/section.xml"] = _seccion(seccion, actividades)
    for actividad in actividades:
        base = f"activities/{actividad.modulo}_{actividad.cmid}"
        entradas[f"{base}/module.xml"] = _module(actividad)
        entradas[f"{base}/{actividad.modulo}.xml"] = _principal(actividad)
        for fichero in actividad.ficheros:
            entradas[f"files/{_hash(fichero.contenido)[:2]}/{_hash(fichero.contenido)}"] = (
                fichero.contenido
            )
    return entradas


def empaquetar(
    entradas: Mapping[str, bytes] | Sequence[tuple[str, bytes]], formato: str = "tar.gz"
) -> bytes:
    """Empaqueta ``entradas`` (nombre -> bytes, o pares si hay repetidos) en tar.gz o zip.

    Los nombres se escriben tal cual, también los peligrosos (``../x``, rutas absolutas).
    """
    pares = list(entradas.items()) if isinstance(entradas, Mapping) else list(entradas)
    salida = io.BytesIO()
    if formato == "zip":
        with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as archivo:
            for nombre, datos in pares:
                archivo.writestr(nombre, datos)
    elif formato == "tar.gz":
        with tarfile.open(fileobj=salida, mode="w:gz") as tar:
            for nombre, datos in pares:
                info = tarfile.TarInfo(nombre)
                info.size = len(datos)
                tar.addfile(info, io.BytesIO(datos))
    else:
        raise ValueError(f"formato desconocido: {formato}")
    return salida.getvalue()


def construir_mbz(
    secciones: Sequence[SeccionFalsa],
    actividades: Sequence[ActividadFalsa],
    *,
    formato: str = "tar.gz",
    users: int = 0,
    curso: int = 2,
    servidor: str = "https://aula.example.org",
    extras: Mapping[str, bytes] | Sequence[tuple[str, bytes]] = (),
) -> bytes:
    """Los bytes de un ``.mbz`` con esas secciones y actividades (más las ``extras`` crudas)."""
    entradas = entradas_de_copia(
        secciones, actividades, users=users, curso=curso, servidor=servidor
    )
    pares = list(entradas.items())
    pares += list(extras.items()) if isinstance(extras, Mapping) else list(extras)
    return empaquetar(pares, formato)


def escribir_mbz(
    ruta: Path,
    secciones: Sequence[SeccionFalsa],
    actividades: Sequence[ActividadFalsa],
    **opciones: object,
) -> Path:
    """Escribe la copia en ``ruta`` y la devuelve (acepta las opciones de ``construir_mbz``)."""
    ruta.write_bytes(construir_mbz(secciones, actividades, **opciones))  # type: ignore[arg-type]
    return ruta


def copia_basica() -> tuple[list[SeccionFalsa], list[ActividadFalsa]]:
    """Una sección con una página (501), una tarea (502), una etiqueta (503) y un foro (504)."""
    secciones = [SeccionFalsa(id=7, numero=1, nombre="Tema 1", resumen="<p>Resumen</p>")]
    actividades = [
        ActividadFalsa(501, "page", 7, "Una página", "<p>Hola</p>"),
        ActividadFalsa(
            502,
            "assign",
            7,
            "Una tarea",
            "<p>Entrega</p>",
            visible=False,
            fechas={"allowsubmissionsfromdate": 1792447200, "duedate": 1795215540, "cutoffdate": 0},
        ),
        ActividadFalsa(503, "label", 7, "Una etiqueta", "<p>Aviso</p>"),
        ActividadFalsa(504, "forum", 7, "Un foro", "<p>Foro</p>"),
    ]
    return secciones, actividades
