"""La vigilancia de lo publicado: ¿retocó el docente?, ¿hay que rechazarlo?, ¿qué cambió?

Módulo de política, no de aula: decide con la estructura tipada, el registro de lo publicado
(``publicados.json``) y ``copia.json``, y solo lee el formulario de una actividad cuando la
respuesta no se puede saber con la marca. Los dos almacenes son los dos adapters de la misma
seam interna; los formatos de disco no cambian.

Vocabulario de dominio en ``CONTEXT.md``: huella, marca, base, registro, retoque y vigilancia.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import contenido, estado, ficheros, tipos
from .contenido import Documento
from .estructura import Estructura, aplica_origen
from .publicar import ErrorPublicacion

if TYPE_CHECKING:
    from .publicar import AulaVirtual


HUELLA_NO_GUARDADA = "HUELLA_NO_GUARDADA"
REGISTRO_NO_GUARDADO = "REGISTRO_NO_GUARDADO"
BASE_NO_GUARDADA = "BASE_NO_GUARDADA"


class EstadoDeCambios(Enum):
    """Lo que ``tiza estructura --cambios`` dice de un documento."""

    CAMBIADA = "cambiada"
    SIN_CAMBIOS = "sin_cambios"
    SIN_REGISTRO = "sin_registro"


@dataclass(frozen=True)
class Rechazo:
    """Un documento que no se publica antes de confirmar, con su código.

    ``por_decision``: el rechazo se debe al «no» del docente a sobrescribir (o lo arrastra).
    ``cmid_copia``: el cmid de la copia cuando el rechazo es por la marca de ``copia.json``.
    Los dos nunca son ciertos a la vez.
    """

    documento: Documento
    codigo: str
    por_decision: bool = False
    cmid_copia: int | None = None


@dataclass(frozen=True)
class Anotacion:
    """Lo que no se pudo guardar al anotar lo publicado, en el orden de las escrituras.

    ``fallos``: códigos de paso de ``informe.PASOS`` (``HUELLA_NO_GUARDADA``,
    ``REGISTRO_NO_GUARDADO`` o ``BASE_NO_GUARDADA``), sin texto ni nombres. Vacía si todo se
    guardó.
    """

    fallos: tuple[str, ...] = ()


@dataclass(frozen=True)
class Cambio:
    """La respuesta de ``tiza estructura --cambios`` para un documento."""

    documento: Documento
    cmid: int | None
    estado: EstadoDeCambios


@dataclass
class ActividadVigilada:
    """La actividad hallada de un documento, para comprobarla justo antes y renovarla después.

    La construye :meth:`Vigilancia.actividad`; es de un solo uso y no guarda el formulario
    leído: solo decide con él y, en ``solo_fechas``, calcula la huella nueva.
    """

    cmid: int
    de_copia: bool
    _documento: Documento
    _base: str
    _marca: str | None = None
    _aceptada_por_la_segunda_via: bool = False
    _huella_nueva: str | None = None

    @property
    def huella_nueva(self) -> str | None:
        """La huella que hay que guardar tras verificar las fechas, o nada si no se renueva."""
        return self._huella_nueva

    def comprobar(self, leer: Callable[[], dict], solo_fechas: bool) -> bool:
        """Si el docente retocó la actividad: ``True`` y no se escribe nada.

        Del registro mira primero la marca y, si cuenta, no llama a ``leer``. Lo que falla al
        leer se propaga: lo ilegible al escribir no se adivina.
        """
        if not self.de_copia and _marca_sin_juntar(self._marca, self._documento):
            return True
        resultado = _comparar(self._documento, self._base, leer(), solo_fechas=solo_fechas)
        if resultado is _Cambio.IGUAL:
            return False
        if resultado is _Cambio.YA_TENIA:
            self._aceptada_por_la_segunda_via = True
            return False
        return True

    def fechas_verificadas(self, info: dict) -> None:
        """Calcula la huella nueva con el formulario que acaba de releer la verificación.

        Si la comprobación aceptó por la segunda vía (las fechas ya estaban), no hay huella
        nueva: el texto del aula puede ser un cambio ajeno y no pasa a ser la base.
        """
        if self._aceptada_por_la_segunda_via:
            return
        self._huella_nueva = tipos.huella_del_formulario(
            tipos.obtener(self._documento.tipo), self._documento, info
        )


@dataclass(frozen=True)
class Vigilancia:
    """La vigilancia de un curso en un lote; se construye una vez y se descarta.

    No escribe nada y no lee el aula al construirse. ``huellas`` y ``marcas`` son lo que
    ``copia.json`` guarda de este curso, por cmid; solo se cargan si algún documento se busca
    por su ``origen`` en él.
    """

    aula: AulaVirtual
    dir_tiza: Path
    curso: int
    real: bool
    huellas: Mapping[int, str]
    marcas: Mapping[int, str]

    @classmethod
    def de(
        cls,
        aula: AulaVirtual,
        dir_tiza: str | Path,
        curso: int,
        documentos: Sequence[Documento],
        real: bool,
    ) -> Vigilancia:
        """Construye la vigilancia del curso, cargando ``copia.json`` solo si hace falta.

        Un ``copia.json`` fuera del esquema es ``ErrorEstado`` (``COPIA_INVALIDA`` o
        ``IMPORTACION_ILEGIBLE``); que no exista es «vacío», como hoy.
        """
        huellas: dict[int, str] = {}
        marcas: dict[int, str] = {}
        if any(aplica_origen(doc, curso) for doc in documentos):
            huellas = estado.huellas_de_copia(dir_tiza, curso)
            marcas = estado.marcas_de_copia(dir_tiza, curso)
        return cls(
            aula=aula,
            dir_tiza=Path(dir_tiza),
            curso=curso,
            real=real,
            huellas=huellas,
            marcas=marcas,
        )

    def rechazos(
        self,
        estructura: Estructura,
        documentos: Sequence[Documento],
        solo_fechas: bool,
    ) -> tuple[Rechazo, ...]:
        """Los documentos que no se publican antes de confirmar, con el código de la vigilancia.

        Solo mira lo que se busca por su ``origen`` en este curso: un ``origen`` que ya no está
        (salvo con ``solo_fechas``), una copia sin huella y una marca sin juntar. La marca del
        registro no rechaza aquí: se pregunta. No lee el aula.
        """
        rechazos: list[Rechazo] = []
        for doc in documentos:
            origen = doc.origen
            if origen is None or not aplica_origen(doc, self.curso):
                continue
            if not solo_fechas and estructura.localizar(doc, self.curso).problema is not None:
                rechazos.append(Rechazo(doc, "ORIGEN_NO_ENCONTRADO"))
                continue
            if origen.cmid not in self.huellas:
                rechazos.append(Rechazo(doc, "ORIGEN_SIN_HUELLA"))
                continue
            if _marca_sin_juntar(self.marcas.get(origen.cmid), doc):
                rechazos.append(Rechazo(doc, "CAMBIADA_EN_EL_AULA", cmid_copia=origen.cmid))
        return tuple(rechazos)

    def rechazo_del_no(self, doc: Documento) -> Rechazo:
        """El rechazo de lo que el docente retocó y no quiso sobrescribir: es su decisión."""
        return Rechazo(doc, "CAMBIADA_EN_EL_AULA", por_decision=True)

    def retoques(
        self,
        estructura: Estructura,
        documentos: Sequence[Documento],
        solo_fechas: bool = False,
    ) -> tuple[Documento, ...]:
        """Los documentos cuya actividad retocó el docente a mano y hay que preguntarle.

        Solo lo hallado por el registro y con huella en él; del resto no lee nada. Con la marca
        sin juntar ya se sabe sin leer. Si no se puede leer el formulario, cuenta como retocado,
        para no pisar a ciegas. Con ``solo_fechas``, lo que ya tiene las fechas del fichero no
        cuenta. En un curso de pruebas no hay retoques ni lecturas.
        """
        if not self.real:
            return ()
        retocados: list[Documento] = []
        for doc in documentos:
            loc = estructura.localizar(doc, self.curso)
            if loc.problema is not None:
                continue
            if loc.por != "registro" or loc.modulo is None:
                continue
            entrada = doc.publicados.get(self.curso)
            if entrada is None or entrada.huella is None:
                continue
            if _marca_sin_juntar(entrada.marca, doc):
                retocados.append(doc)
                continue
            try:
                leido = self.aula.leer_modulo(loc.modulo.cmid)
            except ErrorPublicacion:
                retocados.append(doc)
                continue
            if _comparar(doc, entrada.huella, leido, solo_fechas=solo_fechas) is _Cambio.CAMBIADA:
                retocados.append(doc)
        return tuple(retocados)

    def actividad(
        self, estructura: Estructura, doc: Documento, sobrescribe: bool = False
    ) -> ActividadVigilada | None:
        """La actividad vigilada de ``doc``, o nada si no hay que comparar antes de escribir.

        La de ``copia.json`` cuando se halla por su ``origen`` y la copia guarda su huella; vale
        también en pruebas y no la silencia ``sobrescribe``. La del registro cuando se halla por
        él, su entrada tiene huella, el curso es real y el docente no dijo que sí a sobrescribir.
        """
        loc = estructura.localizar(doc, self.curso)
        if loc.problema is not None or loc.modulo is None:
            return None
        if loc.por == "origen":
            base = self.huellas.get(loc.modulo.cmid)
            if base is None:
                return None
            return ActividadVigilada(
                cmid=loc.modulo.cmid, de_copia=True, _documento=doc, _base=base
            )
        if loc.por == "registro" and self.real and not sobrescribe:
            entrada = doc.publicados.get(self.curso)
            if entrada is None or entrada.huella is None:
                return None
            return ActividadVigilada(
                cmid=loc.modulo.cmid,
                de_copia=False,
                _documento=doc,
                _base=entrada.huella,
                _marca=entrada.marca,
            )
        return None

    def anotar_publicado(self, doc: Documento, ruta: str, cmid: int) -> Anotacion:
        """Anota lo publicado entero: copia, registro y base, en el orden de las escrituras.

        Primero renueva ``copia.json`` (si el documento se halla por su ``origen`` en este
        curso); después lee el cmid previo, escribe la entrada del registro y, en un curso real,
        guarda la base. Si la actividad se recreó, la base nueva se guarda antes de olvidar la
        vieja. Lo que no se pudo guardar sale en ``Anotacion.fallos``, nunca como excepción.
        """
        fallos: list[str] = []
        nueva: str | None = None
        if aplica_origen(doc, self.curso):
            nueva = tipos.huella_de_lo_enviado(
                tipos.obtener(doc.tipo), doc, contenido.html_para_moodle(doc)
            )
            if not self._renovar_copia(doc, nueva):
                fallos.append(HUELLA_NO_GUARDADA)
        previo = self._cmid_previo(ruta)
        if not self._anotar_registro(doc, ruta, cmid, nueva=nueva):
            fallos.append(REGISTRO_NO_GUARDADO)
        if self.real and not self._guardar_base(doc, cmid, previo):
            fallos.append(BASE_NO_GUARDADA)
        return Anotacion(tuple(fallos))

    def anotar_fechas(
        self, doc: Documento, ruta: str, vigilada: ActividadVigilada | None
    ) -> Anotacion:
        """Anota lo publicado con ``--solo-fechas``: solo renueva si hay huella nueva.

        Con la actividad de la copia renueva ``copia.json``; con la del registro, su entrada.
        Sin actividad vigilada (el docente dijo que sí a sobrescribir) no se renueva nada: el
        texto del aula no se pisó y el retoque debe seguir contando.
        """
        nueva = vigilada.huella_nueva if vigilada is not None else None
        if nueva is None:
            return Anotacion()
        if vigilada is not None and vigilada.de_copia:
            return Anotacion(() if self._renovar_copia(doc, nueva) else (HUELLA_NO_GUARDADA,))
        return Anotacion(() if self._renovar_entrada(ruta, nueva) else (REGISTRO_NO_GUARDADO,))

    def _renovar_copia(self, doc: Documento, nueva: str | None = None) -> bool:
        """Renueva la huella de ``copia.json`` con lo enviado (o ``nueva``); ``False`` si falló.

        Sin ``nueva`` se calcula con lo que tiza envió, sin releer el aula. Que ``copia.json``
        no exista o no tenga la actividad no es un fallo (se conserva el silencio de siempre).
        """
        assert doc.origen is not None
        try:
            if nueva is None:
                nueva = tipos.huella_de_lo_enviado(
                    tipos.obtener(doc.tipo), doc, contenido.html_para_moodle(doc)
                )
            estado.guardar_huella_de_copia(self.dir_tiza, self.curso, doc.origen.cmid, nueva)
        except (estado.ErrorEstado, OSError):
            return False
        return True

    def _cmid_previo(self, ruta: str) -> int | None:
        """El cmid que el registro daba a ``ruta`` antes de publicar, o nada.

        Se lee con la regla de lectura (admite «:»). Un registro que no se puede leer no impide
        publicar: :meth:`_anotar_registro` ya lo avisa.
        """
        if not estado.ruta_de_registro_valida(ruta):
            return None
        try:
            anterior = estado.cargar_publicados(self.dir_tiza, self.curso).get(ruta)
        except (estado.ErrorEstado, OSError, ficheros.FicheroNoSeguro):
            return None
        return anterior.cmid if anterior is not None else None

    def _anotar_registro(self, doc: Documento, ruta: str, cmid: int, *, nueva: str | None) -> bool:
        """Escribe la entrada del registro; ``False`` si no se pudo guardar o releer.

        Una ruta que no se puede leer no es clave del registro. Una clave nueva con «:» no se
        crea (la base sí se guarda); una que ya estaba se actualiza aunque la lleve. Con
        ``nueva`` (lo hallado por su ``origen``), la entrada guarda esa misma huella y la marca
        queda vacía. Si no, conserva la huella y la marca de la entrada anterior cuando es la
        misma actividad; si el cmid cambió (se recreó), van a nada. En un curso real y sin
        ``origen``, relee el formulario para la huella y limpia la marca; si la relectura falla,
        la entrada queda sin huella y se avisa.
        """
        if not estado.ruta_de_registro_valida(ruta):
            return True
        try:
            anterior = estado.cargar_publicados(self.dir_tiza, self.curso).get(ruta)
            if anterior is None and not estado.ruta_publicada_valida(ruta):
                return True
            igual = anterior is not None and anterior.cmid == cmid
            huella = anterior.huella if igual and anterior is not None else None
            marca = anterior.marca if igual and anterior is not None else None
            no_guardado = False
            if nueva is not None:
                huella, marca = nueva, None
            elif self.real and not aplica_origen(doc, self.curso):
                marca = None
                try:
                    huella = tipos.huella_del_formulario(
                        tipos.obtener(doc.tipo), doc, self.aula.leer_modulo(cmid)
                    )
                except ErrorPublicacion:
                    huella, no_guardado = None, True
            estado.guardar_publicado(
                self.dir_tiza,
                self.curso,
                ruta,
                estado.Publicado(cmid, doc.tipo, huella=huella, marca=marca),
            )
        except (estado.ErrorEstado, OSError, ficheros.FicheroNoSeguro):
            return False
        return not no_guardado

    def _guardar_base(self, doc: Documento, cmid: int, previo: int | None) -> bool:
        """En un curso real, guarda el fichero fuente y el HTML enviado; ``False`` si falló.

        ``previo`` distinto de ``cmid`` es una actividad recreada: su base vieja se borra
        después de guardar la nueva (si no se puede borrar, se queda: no estorba). Si algo
        falla, lo publicado queda publicado; solo se anota ``BASE_NO_GUARDADA``.
        """
        try:
            estado.guardar_base(
                self.dir_tiza,
                self.curso,
                cmid,
                _fuente_cargada(doc),
                contenido.html_para_moodle(doc),
            )
        except (estado.ErrorEstado, OSError, ficheros.FicheroNoSeguro):
            try:  # sin base: mejor eso que la de una publicación anterior, que se tomaría por la última
                estado.olvidar_base(self.dir_tiza, self.curso, cmid)
            except (OSError, ficheros.FicheroNoSeguro):
                pass
            return False
        if previo is not None and previo != cmid:
            try:
                estado.olvidar_base(self.dir_tiza, self.curso, previo)
            except (OSError, ficheros.FicheroNoSeguro):
                pass
        return True

    def _renovar_entrada(self, ruta: str, nueva: str) -> bool:
        """Renueva la entrada del registro tras ``--solo-fechas``; ``False`` si no se pudo.

        Se lee con la regla de lectura (admite «:»). Si la entrada no está, no se crea.
        """
        if not estado.ruta_de_registro_valida(ruta):
            return True
        try:
            anterior = estado.cargar_publicados(self.dir_tiza, self.curso).get(ruta)
            if anterior is None:
                return True
            estado.guardar_publicado(
                self.dir_tiza,
                self.curso,
                ruta,
                estado.Publicado(anterior.cmid, anterior.tipo, nueva, None),
            )
        except (estado.ErrorEstado, OSError, ficheros.FicheroNoSeguro):
            return False
        return True

    def estado_por_documento(
        self, estructura: Estructura, documentos: Sequence[Documento]
    ) -> tuple[Cambio, ...]:
        """Un ``Cambio`` por documento, en el orden recibido: qué dice la base de cada uno.

        Sin base (no se halló por ``origen`` ni por el registro, su entrada no tiene huella o la
        localización no se puede resolver) es ``SIN_REGISTRO``. La marca sin juntar es
        ``CAMBIADA`` sin leer; una lectura fallida también cuenta como cambiada.
        """
        cambios: list[Cambio] = []
        for doc in documentos:
            loc = estructura.localizar(doc, self.curso)
            if loc.problema is not None:
                cambios.append(Cambio(doc, None, EstadoDeCambios.SIN_REGISTRO))
                continue
            cmid = loc.modulo.cmid if loc.modulo is not None else None
            base: str | None = None
            marca: str | None = None
            if loc.por == "origen" and loc.modulo is not None:
                base = self.huellas.get(loc.modulo.cmid)
                marca = self.marcas.get(loc.modulo.cmid)
            elif loc.por == "registro" and loc.modulo is not None:
                entrada = doc.publicados.get(self.curso)
                if entrada is not None and entrada.huella is not None:
                    base = entrada.huella
                    marca = entrada.marca
            if base is None or loc.modulo is None:
                cambios.append(Cambio(doc, cmid, EstadoDeCambios.SIN_REGISTRO))
                continue
            if _marca_sin_juntar(marca, doc):
                cambios.append(Cambio(doc, cmid, EstadoDeCambios.CAMBIADA))
                continue
            try:
                leido = self.aula.leer_modulo(loc.modulo.cmid)
            except ErrorPublicacion:
                cambios.append(Cambio(doc, cmid, EstadoDeCambios.CAMBIADA))
                continue
            estado_ = (
                EstadoDeCambios.CAMBIADA
                if _comparar(doc, base, leido) is _Cambio.CAMBIADA
                else EstadoDeCambios.SIN_CAMBIOS
            )
            cambios.append(Cambio(doc, cmid, estado_))
        return tuple(cambios)


class _Cambio(Enum):
    """El resultado de comparar el formulario del aula con la base y con lo que tiza enviaría."""

    IGUAL = "igual"
    YA_TENIA = "ya_tenia"
    CAMBIADA = "cambiada"


def _fuente_cargada(doc: Documento) -> bytes:
    """Los bytes del fichero tal como se cargaron. Si cambiaron después, ``FicheroNoSeguro``."""
    bruto = ficheros.leer_bytes_acotado(doc.ruta, estado.MAX_BASE_BYTES)
    if hashlib.sha256(bruto).hexdigest() != doc.sha256_fichero:
        raise ficheros.FicheroNoSeguro("cambiado")
    return bruto


def _comparar(
    doc: Documento, base: str, leido: Mapping[str, Any], *, solo_fechas: bool = False
) -> _Cambio:
    """La regla única de comparación: igual a la base, ya tenía lo de tiza o cambió.

    «Ya tenía lo de tiza» cubre un intento anterior que escribió y falló al verificar: el aula
    ya tiene lo de tiza y no hay cambio ajeno que perder. Con ``solo_fechas`` lo que tiza iba a
    enviar son solo las fechas (el nombre y el texto del aula, con las fechas del fichero).
    """
    tipo = tipos.obtener(doc.tipo)
    en_el_aula = tipos.huella_del_formulario(tipo, doc, leido)
    if en_el_aula == base:
        return _Cambio.IGUAL
    if solo_fechas:
        esperada = tipos.huella_con_las_fechas_de(tipo, doc, leido)
    else:
        esperada = tipos.huella_de_lo_enviado(tipo, doc, contenido.html_para_moodle(doc))
    return _Cambio.YA_TENIA if en_el_aula == esperada else _Cambio.CAMBIADA


def _marca_sin_juntar(marca: str | None, doc: Documento) -> bool:
    """Si la versión del aula traída en ``marca`` sigue sin juntar en el fichero del docente.

    La marca ilegible (no se pudo leer el fichero al marcarla) bloquea siempre; sin marca no
    hay nada sin juntar.
    """
    return marca is not None and marca in (doc.sha256_fichero, estado.MARCA_ILEGIBLE)
