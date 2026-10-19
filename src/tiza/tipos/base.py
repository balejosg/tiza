"""Interfaz común de los tipos de actividad y lo que comparten los cinco.

Cada tipo de actividad (página, tarea, cuestionario, etiqueta y H5P) tiene su
módulo en este paquete, con lo que sabe hacer: campos del frontmatter, validación,
fechas, finalización, payload, vista previa y aportación al hash. Aquí vive solo
lo que no depende del tipo: la clase :class:`Tipo`, el modelo de fechas y los
constructores de payload genéricos.

Ningún módulo de aquí habla con el aula ni importa ``python-moodle``: los adapters
solo construyen datos y llaman a ``AulaVirtual`` a través de sus flujos, igual
que hace el resto de tiza por encima del protocolo.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:  # solo para anotar; los adapters sí importan las clases al construir
    from ..contenido import ActividadH5P, Cuestionario, Documento, Fechas, PaqueteH5P
    from ..publicar import AulaVirtual, ErrorPublicacion

# Nombre llano del «recordarme calificar antes de» de una tarea: tiza nunca lo pone y
# toda publicación de una tarea lo desactiva, así que la confirmación de real tiene que
# poder enseñar que se quita.
CAMPO_RECORDATORIO = "recordatorio de calificación"

# Casilla del formulario de finalización que marca cada modo (confirmado en Moodle 4.5).
# «ninguna» y «manual» no usan casilla: van en el campo «completion».
BANDERA_DE_MODO = {
    "ver": "completionview",
    "entregar": "completionsubmit",
    "calificar": "completionusegrade",
}


@dataclass(frozen=True)
class FechaActividad:
    """Una fecha declarada por el documento, mire donde mire el tipo donde viva.

    Las de una tarea y las de un cuestionario se construyen igual, para que el
    resto de tiza (calendario, avisos, confirmación, payload y verificación) no
    tenga que saber de qué tipo es el documento.
    """

    campo: str  # «apertura», «entrega», «límite», «cierre» o CAMPO_RECORDATORIO
    momento: datetime | None  # None: la fecha no está puesta (se desactiva en el aula)
    campo_moodle: str  # «duedate», «timeopen»…
    exige_clase: bool = False  # el calendario avisa si el día no es de clase


@dataclass(frozen=True)
class Extras:
    """Lo que la validación de un tipo añade al ``Documento``.

    Todo lo demás (ruta, nombre, sección, cuerpo, finalización, restricciones) es
    común y lo construye ``contenido``. Cada adapter solo rellena lo suyo.
    """

    fechas: Fechas | None = None  # tarea
    cuestionario: Cuestionario | None = None
    h5p: ActividadH5P | None = None
    paquete: PaqueteH5P | None = None  # .h5p ya hecho que se sube reempaquetado


@dataclass(frozen=True)
class Contexto:
    """Lo que la validación de un tipo necesita del resto de tiza.

    Lo construye ``contenido`` al validar el frontmatter: así los adapters no
    dependen de sus entresijos (fechas, render de Markdown, rutas seguras) y se
    pueden probar sin montar un documento entero.
    """

    zona: ZoneInfo
    ruta: Path
    raiz: Path | None
    fecha: Callable[[Any, time], datetime]  # (valor ISO, hora por defecto) -> datetime
    render: Callable[[str], str]  # Markdown a HTML (el que usa todo el contenido)
    paquete_h5p: Callable[[str], PaqueteH5P]  # resuelve y valida un .h5p de la carpeta


@dataclass(frozen=True)
class ContextoPublicacion:
    """Todo lo que un tipo necesita para crear o actualizar su módulo en el aula.

    Lo construye ``publicar._publicar_congelado`` con el aula ya abierta y los
    recursos ya subidos; el adapter solo arma su payload y su flujo.
    """

    moodle: AulaVirtual
    curso_id: int
    seccion: dict
    doc: Documento
    html: str  # el texto del documento, ya con @@PLUGINFILE@@
    itemid: int  # borrador del texto
    visible: bool | None  # None: lo que ya exista conserva su visibilidad
    existente: dict | None  # el módulo que se actualizaría, si ya existe
    leido: dict | None = None  # su formulario de edición, si ``publicar`` ya lo cargó


class Tipo:
    """Lo que sabe un tipo de actividad. La base solo cumple la interfaz."""

    nombre: str = ""  # «pagina»
    llano: str = ""  # «Página»
    modulo: str = ""  # nombre del módulo de Moodle («page»)
    campos: frozenset[str] = frozenset()  # campos propios del frontmatter
    finalizaciones: tuple[str, ...] = ()  # modos de finalización admitidos
    banderas: tuple[str, ...] = ()  # casillas del formulario de «cuándo se completa»
    campos_fecha: tuple[str, ...] = ()  # campos del formulario de Moodle con fecha
    # Al actualizar, el payload necesita algo del formulario de edición (``ContextoPublicacion.leido``).
    lee_formulario_al_actualizar: bool = False

    # --- Campos y validación ----------------------------------------------

    def validar(self, datos: dict[str, Any], ctx: Contexto) -> Extras:
        """Valida los campos propios (los comunes ya los validó ``contenido``)."""
        return Extras()

    # --- Fechas -----------------------------------------------------------

    def fechas(self, doc: Documento) -> tuple[FechaActividad, ...]:
        """Las fechas que declara el documento, en el orden en que se enseñan."""
        return ()

    def payload_solo_fechas(self, doc: Documento) -> dict[str, str] | None:
        """Formulario mínimo para cambiar solo las fechas, o None si no aplica."""
        return None

    # --- Payload, publicación y verificación -------------------------------

    def payload(
        self,
        doc: Documento,
        html: str,
        itemid: int,
        visible: bool | None,
        *,
        itemid_paquete: int | None = None,
    ) -> dict[str, str]:
        """Los campos del formulario de creación/actualización del módulo."""
        raise NotImplementedError

    def payload_de(self, p: ContextoPublicacion) -> dict[str, str]:
        """El payload al publicar: por defecto el de ``payload``; un tipo puede ajustarlo al aula."""
        return self.payload(p.doc, p.html, p.itemid, p.visible)

    def publicar(self, p: ContextoPublicacion) -> tuple[int, str, dict]:
        """Crea o actualiza el módulo y lo verifica; devuelve (cmid, acción, formulario)."""
        payload = self.payload_de(p)
        if p.existente is not None:
            cmid = p.existente["cmid"]
            p.moodle.actualizar(cmid, payload)
            accion = "actualizada"
        else:
            cmid = p.moodle.crear(p.curso_id, p.seccion["id"], self.nombre, payload)
            accion = "creada"
        from ..publicar import ErrorPublicacion

        try:
            info = verificar(p.moodle, self, p.doc, cmid)
        except ErrorPublicacion as exc:
            exc.cmid = cmid
            raise
        return cmid, accion, info

    def urls_pluginfile(self, base_url: str, contexto, instance, nombre: str) -> list[str]:
        """Las URL donde mirar que un recurso local quedó subido al módulo."""
        return []

    # --- Vista previa ------------------------------------------------------

    def metadatos_preview(self, doc: Documento) -> list[tuple[str, str]]:
        """Las filas propias del tipo en la cabecera de la vista previa."""
        return []

    def extra_preview(self, doc: Documento) -> str:
        """El bloque extra de la vista previa (preguntas, resumen del paquete…)."""
        return ""

    # --- Aportación al hash -------------------------------------------------

    # El orden con el que ``contenido`` llama a estos tres huecos reproduce el hash
    # de siempre, para no invalidar .tiza/verificados.json al actualizar tiza.

    def hash_fechas(self, doc: Documento, resumen: Any) -> None:
        """Añade al hash lo que va tras la cabecera (las fechas de una tarea)."""

    def hash_contenido(self, doc: Documento, resumen: Any) -> None:
        """Añade al hash lo que va tras el cuerpo (preguntas, actividad H5P)."""

    def hash_extra(self, doc: Documento, resumen: Any) -> None:
        """Añade al hash lo que va tras el itinerario (el paquete .h5p)."""

    # --- Resúmenes ----------------------------------------------------------

    def extras_resumen(self, doc: Documento) -> dict[str, Any]:
        """Datos propios que la confirmación de real enseña de este tipo."""
        return {}

    def detalle(self, doc: Documento) -> str | None:
        """Un detalle corto para el paso del informe («12 preguntas»)."""
        return None


# --------------------------------------------------------------------------- #
# Constructores genéricos de fechas (los usan todos los tipos por igual)
# --------------------------------------------------------------------------- #


def partes_fecha(momento: datetime) -> tuple[int, int, int, int, int]:
    """(año, mes, día, hora, minuto), como los lee y los escribe el formulario."""
    return (momento.year, momento.month, momento.day, momento.hour, momento.minute)


def payload_fecha(campo: str, momento: datetime) -> dict[str, str]:
    return {
        f"{campo}[enabled]": "1",
        f"{campo}[day]": str(momento.day),
        f"{campo}[month]": str(momento.month),
        f"{campo}[year]": str(momento.year),
        f"{campo}[hour]": str(momento.hour),
        f"{campo}[minute]": str(momento.minute),
    }


def fechas_payload(tipo: Tipo, doc: Documento) -> dict[str, str]:
    """Los campos de fecha del formulario; una fecha sin poner se desactiva."""
    payload: dict[str, str] = {}
    for fecha in tipo.fechas(doc):
        if fecha.momento is None:
            payload[f"{fecha.campo_moodle}[enabled]"] = "0"
        else:
            payload.update(payload_fecha(fecha.campo_moodle, fecha.momento))
    return payload


def fechas_esperadas(
    tipo: Tipo, doc: Documento
) -> dict[str, tuple[int, int, int, int, int] | None]:
    """Lo que debe mostrar el formulario de la actividad tras publicarla."""
    return {
        fecha.campo_moodle: (partes_fecha(fecha.momento) if fecha.momento is not None else None)
        for fecha in tipo.fechas(doc)
    }


# --------------------------------------------------------------------------- #
# Finalización: el payload y la lectura del formulario, genéricos por tipo
# --------------------------------------------------------------------------- #


def payload_finalizacion(
    tipo: Tipo, doc: Documento, *, solo_fecha_esperada: bool = False
) -> dict[str, str]:
    """Campos de finalización del formulario, o ``{}`` si el documento no la declara.

    Se envían todos los del tipo (los no usados a 0): la fusión conserva lo que no se
    envía, y un modo anterior dejaría su casilla marcada.
    """
    finalizacion = doc.finalizacion
    if finalizacion is None:
        return {}
    payload: dict[str, str] = {}
    esperada = finalizacion.esperada
    if esperada is None:
        payload["completionexpected[enabled]"] = "0"
    else:
        payload["completionexpected[enabled]"] = "1"
        for parte, valor in zip(
            ("year", "month", "day", "hour", "minute"), partes_fecha(esperada), strict=True
        ):
            payload[f"completionexpected[{parte}]"] = str(valor)
    if solo_fecha_esperada:
        return payload
    modo = finalizacion.modo
    payload["completion"] = {"ninguna": "0", "manual": "1"}.get(modo, "2")
    if modo in BANDERA_DE_MODO:
        elegida = BANDERA_DE_MODO[modo]
        for bandera in tipo.banderas:
            payload[bandera] = "1" if bandera == elegida else "0"
    return payload


def modo_leido(tipo: Tipo, campos: dict) -> str | None:
    """El modo de finalización que dice el formulario; None si no es uno de los de tiza."""
    completion = campos.get("completion")
    if completion == "0":
        return "ninguna"
    if completion == "1":
        return "manual"
    if completion != "2":
        return None
    marcadas = [
        modo
        for modo, bandera in BANDERA_DE_MODO.items()
        if bandera in tipo.banderas and campos.get(bandera) == "1"
    ]
    return marcadas[0] if len(marcadas) == 1 else None


# --------------------------------------------------------------------------- #
# Payload y publicación compartidos
# --------------------------------------------------------------------------- #


def campo_visible(visible: bool | None) -> dict[str, str]:
    """Sin valor, el formulario conserva la visibilidad que ya tenga el módulo."""
    return {} if visible is None else {"visible": "1" if visible else "0"}


def formato_fecha(momento: datetime) -> str:
    return momento.strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- #
# Huella de lo que hay en el aula (``CAMBIADA_EN_EL_AULA``)
# --------------------------------------------------------------------------- #

_ZONA_AULA = ZoneInfo("Europe/Madrid")
# Cada URL «…/draftfile.php/<n>/…/<f>» o «…/pluginfile.php/<n>/…/<f>» (con o sin servidor y
# con o sin «?…») es la referencia «@@PLUGINFILE@@/<f>» de la copia: el aula devuelve las
# primeras en el formulario de edición y la copia trae las segundas.
_URL_DE_FICHERO = re.compile(
    r"""/(?:draftfile|pluginfile)\.php/\d+/(?:[^\s"'<>?#]*/)?"""
    r"""([^\s"'<>?#/]+)(?:\?[^\s"'<>#]*)?"""
)
_SEPARADORES_DE_URL = "\"'<>="


def _corta_la_url(caracter: str) -> bool:
    """Lo que no puede estar en una URL: un espacio (``\\s`` de ``re``), comillas, ``<``, ``>``, ``=``."""
    return caracter.isspace() or caracter in _SEPARADORES_DE_URL


def _ficheros_del_aula(html: str) -> str:
    """Cada URL de fichero del aula como ``@@PLUGINFILE@@/<f>``, en tiempo lineal.

    Se busca la parte fija «/pluginfile.php/<n>/» y solo entonces se retrocede hasta el
    principio de la URL (sin pasar de donde acabó la anterior); un texto enorme sin espacios no
    cuesta más que su tamaño.
    """
    salida: list[str] = []
    fin_anterior = 0
    for m in _URL_DE_FICHERO.finditer(html):
        inicio = m.start()
        while inicio > fin_anterior and not _corta_la_url(html[inicio - 1]):
            inicio -= 1
        salida.append(html[fin_anterior:inicio])
        salida.append(f"@@PLUGINFILE@@/{m.group(1)}")
        fin_anterior = m.end()
    salida.append(html[fin_anterior:])
    return "".join(salida)


Momento = datetime | tuple[int, int, int, int, int] | None


def huella_aula(nombre: str, html: str, fechas: Mapping[str, Momento] | None = None) -> str:
    """El sha256 de lo que tiza sobrescribe al publicar una actividad: nombre, texto y fechas.

    Es la misma cuenta para la copia (``tiza importar``), el formulario del aula y lo que
    tiza envía, y por eso vive aquí. La normalización la fijó la espiga 5:

    - cada URL de fichero del aula pasa a ``@@PLUGINFILE@@/<f>``;
    - ``fechas`` (campo de Moodle -> momento) se guardan como (año, mes, día, hora, minuto) en
      Europe/Madrid; una fecha sin poner (``None``) es lo mismo que no estar. Un momento puede
      venir ya como esa tupla (la que lee el formulario del aula);
    - el JSON compacto de ``[nombre, html, fechas]`` (claves ordenadas) se pasa por sha256.
    """
    texto = _ficheros_del_aula(html)
    puestas: dict[str, list[int]] = {}
    for campo, momento in (fechas or {}).items():
        if momento is None:
            continue
        if isinstance(momento, tuple):
            puestas[campo] = list(momento)
            continue
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=_ZONA_AULA)
        puestas[campo] = list(partes_fecha(momento.astimezone(_ZONA_AULA)))
    serie = json.dumps(
        [nombre, texto, puestas], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serie.encode("utf-8")).hexdigest()


def _campos_de_huella(tipo: Tipo, doc: Documento) -> list[FechaActividad]:
    """Las fechas que cubre la huella: las de ``tipo.fechas`` menos el recordatorio.

    Son las mismas que lee ``tiza importar`` de la copia (tarea: apertura, entrega y límite;
    cuestionario: apertura y cierre), con los mismos nombres de campo de Moodle.
    """
    return [fecha for fecha in tipo.fechas(doc) if fecha.campo != CAMPO_RECORDATORIO]


def huella_de_lo_enviado(tipo: Tipo, doc: Documento, html: str) -> str:
    """La huella de lo que tiza escribe en el aula al publicar ``doc`` (sin releer el aula).

    ``html`` es el texto que se envía (``contenido.html_para_moodle``). La espiga 5 comprobó
    que el aula lo guarda igual tras la normalización de :func:`huella_aula`.
    """
    fechas = {fecha.campo_moodle: fecha.momento for fecha in _campos_de_huella(tipo, doc)}
    return huella_aula(doc.nombre, html, fechas)


def huella_del_formulario(tipo: Tipo, doc: Documento, leido: Mapping[str, Any]) -> str:
    """La huella de lo que hay en el aula, de ``AulaVirtual.leer_modulo`` (nombre, texto y fechas).

    Solo mira las fechas que cubre la huella de ``tipo``; el resultado nunca sale de ``publicar``.
    """
    leidas = leido.get("fechas") or {}
    fechas = {
        fecha.campo_moodle: leidas.get(fecha.campo_moodle) for fecha in _campos_de_huella(tipo, doc)
    }
    return huella_aula(leido.get("nombre") or "", leido.get("texto") or "", fechas)


def huella_con_las_fechas_de(tipo: Tipo, doc: Documento, leido: Mapping[str, Any]) -> str:
    """La huella del nombre y el texto que hay en el aula con las fechas que declara ``doc``.

    Es lo que quedaría en el aula tras cambiar solo las fechas (``--solo-fechas``).
    """
    fechas = {fecha.campo_moodle: fecha.momento for fecha in _campos_de_huella(tipo, doc)}
    return huella_aula(leido.get("nombre") or "", leido.get("texto") or "", fechas)


def verificar(
    moodle: AulaVirtual,
    tipo: Tipo,
    doc: Documento,
    cmid: int,
    *,
    preguntas: list[int] | None = None,
    paquete: str | None = None,
) -> dict:
    """Relee el módulo y comprueba nombre, fechas, recursos y lo específico del tipo."""
    from ..publicar import ErrorPublicacion

    info = moodle.leer_modulo(cmid)
    if (info.get("nombre") or "").strip() != doc.nombre:
        raise ErrorPublicacion("VERIFICACION_NOMBRE", doc.ruta.name)
    leidas = info.get("fechas") or {}
    if any(leidas.get(campo) != valor for campo, valor in fechas_esperadas(tipo, doc).items()):
        raise ErrorPublicacion("FECHAS_NO_APLICADAS", doc.ruta.name)
    texto = info.get("texto") or ""
    for recurso in doc.recursos:
        if recurso.nombre not in texto:
            raise ErrorPublicacion("VERIFICACION_TEXTO", doc.ruta.name)
        urls = tipo.urls_pluginfile(
            moodle.base_url, info.get("contexto"), info.get("instance"), recurso.nombre
        )
        if not any(moodle.comprobar_pluginfile(url) for url in urls):
            raise ErrorPublicacion("VERIFICACION_FICHERO", doc.ruta.name)
    if paquete is not None:
        urls = urls_paquete_h5p(
            moodle.base_url, info.get("contexto"), info.get("instance"), paquete
        )
        if not any(moodle.comprobar_pluginfile(url) for url in urls):
            raise ErrorPublicacion("VERIFICACION_PAQUETE", doc.ruta.name)
    if preguntas is not None:
        en_huecos = [identificador for _hueco, identificador in moodle.huecos(cmid)]
        if en_huecos != list(preguntas):
            raise ErrorPublicacion("VERIFICACION_PREGUNTAS", doc.ruta.name)
    return info


def urls_paquete_h5p(base_url: str, contexto, instance, nombre: str) -> list[str]:
    """Las dos formas válidas de la ruta del paquete (la espiga comprobó ambas)."""
    raiz = f"{base_url}/pluginfile.php/{contexto}/mod_h5pactivity/package"
    return [f"{raiz}/0/{nombre}", f"{raiz}/{instance}/{nombre}"]


def importar_preguntas(
    moodle: AulaVirtual, curso_id: int, cmid: int, categoria: str, xml: bytes, cuantas: int
) -> list[int]:
    """Importa el XML y comprueba que llegaron todas las preguntas."""
    from ..publicar import ErrorPublicacion

    nuevas = moodle.importar_preguntas(curso_id, cmid, categoria, xml)
    if len(nuevas) != cuantas:
        raise ErrorPublicacion(
            "ERROR_IMPORTACION",
            f"se esperaban {cuantas} preguntas y el aula importó {len(nuevas)}",
        )
    return nuevas


def borrar_nuevas(moodle: AulaVirtual, cmid: int, ids: list[int]) -> None:
    """Deshace una importación a medias; si no puede, se borrarán al republicar."""
    from ..publicar import ErrorPublicacion

    if not ids:
        return
    try:
        moodle.borrar_preguntas(cmid, ids)
    except ErrorPublicacion:
        pass  # el cuestionario sigue como estaba; las nuevas se borrarán al republicar


def deshacer_modulo(moodle: AulaVirtual, curso_id: int, cmid: int, exc: ErrorPublicacion) -> None:
    """Borra un módulo nuevo a medias; si no puede, deja el cmid al llamador."""
    from ..publicar import ErrorPublicacion

    try:
        moodle.borrar(curso_id, cmid)
    except ErrorPublicacion:
        exc.cmid = cmid
