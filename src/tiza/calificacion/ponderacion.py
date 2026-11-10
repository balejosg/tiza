"""Ponderación simple del calificador: el modelo puro de lo que se lee del aula.

No habla con el aula ni decide nada: solo guarda lo leído de ``grade/edit/tree/index.php`` y de
los formularios de las categorías y elementos que se nombran. ``nombre`` lo ve únicamente el
docente, a través de la presencia; nunca sale a ``informe``.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING

from .ponderacion_esquema import (
    ElementoPonderacion,
    EntradaPonderacion,
    ErrorPonderacion,
    EsquemaPonderacion,
)

if TYPE_CHECKING:
    from tiza.contenido import Documento
    from tiza.estructura import Estructura

__all__ = [
    "ArbolPonderacion",
    "AvisoPonderacion",
    "CambioAMano",
    "CategoriaAfectada",
    "HijoAfectado",
    "NodoPonderacion",
    "OperacionPonderacion",
    "PlanPonderacion",
    "huella_nodo",
    "nodos_nombrados",
    "planificar",
    "porcentaje_efectivo",
    "referencia_de",
]


@dataclasses.dataclass(frozen=True)
class NodoPonderacion:
    """Un elemento o categoría del calificador con lo que hace falta para ponderar.

    ``clase`` es ``curso``, ``categoria``, ``actividad``, ``manual`` o ``calculado``.
    ``coeficiente`` son los 4 decimales del formulario (solo si se abrió); ``peso`` es el
    ``weight_<item>`` del árbol (el coeficiente en media ponderada, el porcentaje en natural).
    """

    eid: str  # «cg<id>» (categoría o curso) o «ig<id>» (elemento)
    item_id: int
    idnumber: str
    clase: str
    nombre: str
    padre_eid: str | None
    cmid: int | None
    tipo: str | None  # módulo de Moodle de la actividad (``assign``, ``quiz``…)
    bloqueado: bool
    tiene_notas: bool
    agregacion: int | None  # 13 Natural, 10 Media ponderada…; solo en categorías
    solo_no_vacias: bool | None  # ``aggregateonlygraded``; solo si se abrió el formulario
    opciones_agregacion: tuple[int, ...] | None  # las del desplegable, si se abrió
    coeficiente: float | None
    peso: float | None
    sobrescrito: bool
    maximo: float | None
    oculto: bool


@dataclasses.dataclass(frozen=True)
class ArbolPonderacion:
    """El calificador de un curso, en el orden de la página."""

    curso: int
    nodos: tuple[NodoPonderacion, ...]
    decimal: str  # «,» o «.»: el separador que muestra el aula

    def nodo(self, eid: str) -> NodoPonderacion | None:
        return next((n for n in self.nodos if n.eid == eid), None)

    def raiz(self) -> NodoPonderacion | None:
        return next((n for n in self.nodos if n.padre_eid is None), None)

    def hijos(self, eid: str) -> tuple[NodoPonderacion, ...]:
        return tuple(n for n in self.nodos if n.padre_eid == eid)

    def por_nombre(self, nombre: str) -> tuple[NodoPonderacion, ...]:
        return tuple(n for n in self.nodos if n.nombre == nombre)


# --- El plan: resolver lo que nombra el esquema, calcular los pesos y dar las operaciones ---
#
# Todo lo de abajo es puro: no habla con el aula. ``planificar`` recibe lo leído (``ArbolPonderacion``),
# la estructura de secciones, las huellas de la última pasada y devuelve el ``PlanPonderacion``.
# Los errores del curso salen como ``ErrorPonderacion``; lo que no corta va como aviso.

TOLERANCIA_EFECTIVA = 0.05  # puntos porcentuales: por debajo, el porcentaje ya es el pedido
TOLERANCIA_SUMA = 0.005  # para decir que los porcentajes nombrados suman 100
PREFIJO_IDNUMBER = "TZP_"
PREFIJO_NUEVA = "nuevo:"  # eid simbólico de una categoría que aún no existe

MEDIA_PONDERADA = 10
NATURAL = 13
_METODOS = {"media_ponderada": MEDIA_PONDERADA, "natural": NATURAL}
_NOMBRE_METODO = {MEDIA_PONDERADA: "media_ponderada", NATURAL: "natural"}
_VERSION_HUELLA = "v1"

_NOMBRADO = "nombrado"
_FIJO = "fijo"
_OMITIDO = "omitido"


@dataclasses.dataclass(frozen=True)
class OperacionPonderacion:
    """Una escritura que el plan pide al aula. ``tipo``: ``crear``, ``mover``, ``metodo`` o ``coeficiente``.

    ``eid`` (también ``padre``, ``destino`` y ``despues_de``) es un eid del aula o, para una
    categoría que aún no existe, ``nuevo:<id>``; quien ejecuta lo traduce al eid real cuando
    la crea. ``despues_de=None`` en un ``mover`` quiere decir «al principio de la categoría».
    ``metodo_del_padre`` es ``media_ponderada`` o ``natural``. ``referencia`` es la clave
    estable del esquema (``referencia_de``): nunca un id ni un nombre del aula.
    """

    tipo: str
    referencia: str
    eid: str | None = None
    id: str | None = None
    nombre: str | None = None
    idnumber: str | None = None
    padre: str | None = None
    agregacion: int | None = None
    solo_no_vacias: bool | None = None
    coeficiente: float | None = None
    # El porcentaje efectivo que debería quedar tras el cambio (para verificar sin depender
    # de la escala de los coeficientes).
    porcentaje: float | None = None
    destino: str | None = None
    despues_de: str | None = None
    metodo_del_padre: str | None = None


@dataclasses.dataclass(frozen=True)
class HijoAfectado:
    """Un hijo de una categoría afectada, con su porcentaje efectivo antes y después.

    ``antes``/``despues`` son ``None`` si no estaba o ya no está (o si el método de la categoría
    no tiene pesos por elemento). ``referencia`` solo si lo nombra el esquema. ``peso`` es el
    ``peso`` relativo que declara el esquema (nada para un ``porcentaje`` ni para lo no nombrado).
    """

    nombre: str
    referencia: str | None
    antes: float | None
    despues: float | None
    peso: float | None = None


@dataclasses.dataclass(frozen=True)
class CategoriaAfectada:
    """Una categoría cuyo contenido o reparto cambia, con todos sus hijos (nombrados o no).

    ``calculo_*`` es ``media_ponderada``, ``natural`` u ``otro``; en una categoría nueva,
    ``calculo_antes`` y ``solo_antes`` son ``None``. Los nombres son los del aula: solo los
    ve el docente.
    """

    nombre: str
    referencia: str | None
    calculo_antes: str | None
    calculo_despues: str | None
    solo_antes: bool | None
    solo_despues: bool | None
    hijos: tuple[HijoAfectado, ...]


@dataclasses.dataclass(frozen=True)
class CambioAMano:
    """Lo que el docente cambió a mano y tiza no pisa sin permiso (la pregunta aparte)."""

    referencia: str
    nombre: str
    antes: float | None  # su porcentaje efectivo hoy
    despues: float | None  # el que pondría tiza


@dataclasses.dataclass(frozen=True)
class AvisoPonderacion:
    """Un aviso del plan: un código y la categoría o elemento (nombre del aula, para el docente)."""

    codigo: str
    nombre: str
    referencia: str | None = None


@dataclasses.dataclass(frozen=True)
class PlanPonderacion:
    """Lo que hay que hacer en un curso para que el aula cumpla ``ponderacion.yaml``.

    ``corta``: no se hace nada en este curso (una categoría nueva caería dentro de una
    bloqueada). ``sin_cambios``: no hay nada que escribir (aunque haya avisos).
    ``pesos_con_notas``: nombres de las categorías afectadas que ya tienen notas. ``salidas``:
    nombres de las categorías de las que sale una nota.
    """

    curso: int
    operaciones: tuple[OperacionPonderacion, ...]
    afectadas: tuple[CategoriaAfectada, ...]
    avisos: tuple[AvisoPonderacion, ...]
    cambios_a_mano: tuple[CambioAMano, ...]
    pesos_con_notas: tuple[str, ...]
    salidas: tuple[str, ...]
    corta: bool
    sin_cambios: bool


def referencia_de(
    entrada_o_elemento: EntradaPonderacion | ElementoPonderacion,
    documento: Documento | None = None,
) -> str:
    """La clave estable de lo que nombra el esquema (la usan las huellas de ``.tiza/ponderacion.json``).

    ``fichero:<ruta>`` (relativa a la carpeta, con «/»), ``actividad:<tipo>:<sección>:<nombre>``,
    ``elemento:<nombre>`` y ``categoria:<id o nombre>`` (una entrada nueva, por su id; una
    existente, por su nombre). Nunca lleva ids de Moodle. ``documento`` solo sirve cuando la
    referencia es un fichero sin ruta propia: entonces se usa la del documento.
    """
    if isinstance(entrada_o_elemento, EntradaPonderacion):
        clave = entrada_o_elemento.id if entrada_o_elemento.nueva else entrada_o_elemento.categoria
        return f"categoria:{clave}"
    referencia = entrada_o_elemento.referencia
    if referencia.clase == "fichero":
        doc = documento or entrada_o_elemento.documento
        ruta = referencia.nombre or (doc.ruta.as_posix() if doc is not None else "")
        return f"fichero:{ruta.replace(chr(92), '/')}"
    if referencia.clase == "actividad":
        return f"actividad:{referencia.tipo}:{referencia.seccion}:{referencia.nombre}"
    return f"{referencia.clase}:{referencia.nombre}"


def _numero(valor: float | None) -> str:
    return "" if valor is None else f"{round(valor, 4) + 0.0:.4f}"


def _booleano(valor: bool | None) -> str:
    return "" if valor is None else ("1" if valor else "0")


def huella_nodo(nodo: NodoPonderacion, arbol: ArbolPonderacion) -> str:
    """El sha256 de lo que quedó en el aula de un nodo nombrado.

    Texto estable, con ``None`` como cadena vacía, los números con 4 decimales y punto, y
    los campos separados por ``|``::

        v1|categoria|agregacion=<n>|solo=<0|1>|coef=<n>|padre=<eid>
        v1|elemento|coef=<n>|padre=<eid>

    Una categoría lleva su método, «solo no vacías», su coeficiente y su padre; una actividad o
    un elemento manual, solo su coeficiente y su padre (el método de la categoría donde está
    no es suyo). El coeficiente es el del formulario o, si no se abrió, el ``peso`` del árbol;
    en una categoría natural solo cuenta el peso sobrescrito (el otro cambia solo cuando cambian
    los hermanos). **Cambiar este formato invalida ``.tiza/ponderacion.json``.**
    """
    padre = arbol.nodo(nodo.padre_eid) if nodo.padre_eid is not None else None
    valor = nodo.coeficiente if nodo.coeficiente is not None else nodo.peso
    if padre is not None and padre.agregacion == NATURAL and not nodo.sobrescrito:
        valor = None
    coef = _numero(valor)
    donde = nodo.padre_eid or ""
    if nodo.clase == "categoria":
        texto = (
            f"{_VERSION_HUELLA}|categoria|agregacion={'' if nodo.agregacion is None else nodo.agregacion}"
            f"|solo={_booleano(nodo.solo_no_vacias)}|coef={coef}|padre={donde}"
        )
    else:
        texto = f"{_VERSION_HUELLA}|elemento|coef={coef}|padre={donde}"
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


# --- Piezas internas ---


@dataclasses.dataclass(frozen=True)
class _Pieza:
    eid: str
    coef: float
    override: float | None
    maximo: float


def _coef_actual(nodo: NodoPonderacion) -> float:
    if nodo.coeficiente is not None:
        return nodo.coeficiente
    if nodo.peso is not None:
        return nodo.peso
    return 1.0


def _override_actual(nodo: NodoPonderacion) -> float | None:
    if not nodo.sobrescrito:
        return None
    return nodo.coeficiente if nodo.coeficiente is not None else nodo.peso


def _pieza_actual(nodo: NodoPonderacion) -> _Pieza:
    return _Pieza(nodo.eid, _coef_actual(nodo), _override_actual(nodo), nodo.maximo or 0.0)


def _efectivos(metodo: int | None, piezas: Sequence[_Pieza]) -> dict[str, float]:
    """El porcentaje efectivo de cada hijo en media ponderada o natural; nada en otro método."""
    if metodo == MEDIA_PONDERADA:
        total = sum(p.coef for p in piezas)
        return {p.eid: (p.coef / total * 100 if total > 0 else 0.0) for p in piezas}
    if metodo != NATURAL:
        return {}
    con = [(p, p.override) for p in piezas if p.override is not None]
    sin = [p for p in piezas if p.override is None]
    suma = sum(valor for _, valor in con)
    escala = 100 / suma if suma > 100 else 1.0  # Moodle normaliza en silencio (espiga S2)
    resto = max(0.0, 100 - suma)
    maximos = sum(p.maximo for p in sin)
    salida = {p.eid: valor * escala for p, valor in con}
    for p in sin:
        salida[p.eid] = resto * p.maximo / maximos if maximos > 0 else 0.0
    return salida


def porcentaje_efectivo(nodo: NodoPonderacion, arbol: ArbolPonderacion) -> float | None:
    """El porcentaje que representa ``nodo`` dentro de su categoría (0–100), o ``None``.

    Es la comparación que usa la verificación: no depende de la escala de los coeficientes.
    """
    padre = arbol.nodo(nodo.padre_eid) if nodo.padre_eid is not None else None
    if padre is None:
        return None
    return _efectivos(padre.agregacion, [_pieza_actual(h) for h in arbol.hijos(padre.eid)]).get(
        nodo.eid
    )


def _nombre_metodo(agregacion: int | None) -> str | None:
    if agregacion is None:
        return None
    return _NOMBRE_METODO.get(agregacion, "otro")


@dataclasses.dataclass(eq=False, repr=False)
class _Destino:
    """Una entrada del esquema ya resuelta: la categoría que se configura."""

    indice: int
    entrada: EntradaPonderacion
    ref: str
    nodo: NodoPonderacion | None  # None: hay que crearla
    metodo: int
    solo: bool | None
    nombre: str
    padre: _Destino | None = None  # solo en las nuevas: el destino de su ``dentro_de``
    elementos: list[_Elemento] = dataclasses.field(default_factory=list)
    bloqueante: NodoPonderacion | None = None

    @property
    def eid(self) -> str:
        return self.nodo.eid if self.nodo is not None else f"{PREFIJO_NUEVA}{self.entrada.id}"

    @property
    def a_crear(self) -> bool:
        return self.nodo is None


@dataclasses.dataclass(eq=False, repr=False)
class _Elemento:
    """Un elemento de una lista, ya resuelto contra el aula."""

    ref: str
    ruta: str
    eid: str
    nodo: NodoPonderacion | None  # None: una categoría nueva que hay que crear
    nombre: str
    porcentaje: float | None
    peso: float | None
    nuevo: _Destino | None
    bloqueante: NodoPonderacion | None


@dataclasses.dataclass
class _Calculo:
    operaciones: list[OperacionPonderacion]
    afectadas: list[CategoriaAfectada]
    con_notas: list[str]
    salidas: list[str]
    despues: dict[str, float]
    con_operacion: set[str]


class _Planificador:
    def __init__(
        self,
        esquema: EsquemaPonderacion,
        estructura: Estructura,
        arbol: ArbolPonderacion,
        huellas: Mapping[str, str],
        tzp: Mapping[str, str] | None,
        sobrescribir: Collection[str],
    ) -> None:
        self.esquema = esquema
        self.estructura = estructura
        self.arbol = arbol
        self.huellas = huellas
        self.sobrescribir = frozenset(sobrescribir)
        self.tzp: dict[str, str] = {
            n.eid: n.idnumber
            for n in arbol.nodos
            if n.clase == "categoria" and n.idnumber.startswith(PREFIJO_IDNUMBER)
        }
        self.tzp.update({e: i for e, i in (tzp or {}).items() if i.startswith(PREFIJO_IDNUMBER)})
        self.destinos: list[_Destino] = []
        self.nuevas: dict[str, _Destino] = {}
        self.por_eid: dict[str, _Destino] = {}
        self._antes_cache: dict[str, dict[str, float]] = {}

    # --- resolución ---

    def _error(self, codigo: str, ruta: str, motivo: str) -> ErrorPonderacion:
        return ErrorPonderacion(codigo, f"{ruta}: {motivo}" if ruta else motivo)

    def _bloqueante(self, nodo: NodoPonderacion | None) -> NodoPonderacion | None:
        vistos: set[str] = set()
        while nodo is not None and nodo.eid not in vistos:
            if nodo.bloqueado:
                return nodo
            vistos.add(nodo.eid)
            nodo = self.arbol.nodo(nodo.padre_eid) if nodo.padre_eid else None
        return None

    def _categoria_por_nombre(self, nombre: str, ruta: str) -> NodoPonderacion:
        coincidencias = [n for n in self.arbol.por_nombre(nombre) if n.clase == "categoria"]
        if not coincidencias:
            raise self._error(
                "CATEGORIA_AUSENTE", ruta, f"no hay una categoría «{nombre}» en el aula"
            )
        if len(coincidencias) > 1:
            raise self._error(
                "CATEGORIA_AMBIGUA", ruta, f"hay varias categorías «{nombre}» en el aula"
            )
        return coincidencias[0]

    def resolver_destinos(self) -> None:
        for indice, entrada in enumerate(self.esquema.entradas):
            ref = referencia_de(entrada)
            if entrada.nueva:
                id_ = str(entrada.id)
                idnumber = f"{PREFIJO_IDNUMBER}{id_}"
                existentes = [
                    self.arbol.nodo(eid)
                    for eid, valor in sorted(self.tzp.items())
                    if valor == idnumber
                ]
                nodos = [n for n in existentes if n is not None and n.clase == "categoria"]
                if len(nodos) > 1:
                    raise self._error(
                        "CATEGORIA_AMBIGUA",
                        entrada.ruta,
                        f"hay varias categorías con el número de ID {idnumber}",
                    )
                nodo = nodos[0] if nodos else None
                destino = _Destino(
                    indice,
                    entrada,
                    ref,
                    nodo,
                    _METODOS[str(entrada.calculo)],
                    entrada.solo_no_vacias,
                    str(entrada.nombre),
                )
                self.nuevas[id_] = destino
            else:
                nombre = str(entrada.categoria)
                if any(e.nueva and e.id == nombre for e in self.esquema.entradas):
                    raise self._error(
                        "PONDERACION_INVALIDA",
                        f"{entrada.ruta}.categoria",
                        f"«{nombre}» es el id de una categoría nueva: sus pesos van en su propia entrada",
                    )
                nodo = self._categoria_por_nombre(nombre, f"{entrada.ruta}.categoria")
                metodo = _METODOS[entrada.calculo] if entrada.calculo else nodo.agregacion
                destino = _Destino(
                    indice,
                    entrada,
                    ref,
                    nodo,
                    metodo if metodo is not None else -1,
                    entrada.solo_no_vacias,
                    nodo.nombre,
                )
            if destino.nodo is not None:
                if destino.nodo.eid in self.por_eid:
                    raise self._error(
                        "PONDERACION_INVALIDA",
                        entrada.ruta,
                        "dos entradas del esquema apuntan a la misma categoría del aula",
                    )
                self.por_eid[destino.nodo.eid] = destino
                destino.bloqueante = self._bloqueante(destino.nodo)
            self.destinos.append(destino)
        for destino in self.destinos:
            if destino.entrada.nueva:
                destino.padre = self._destino_de(
                    str(destino.entrada.dentro_de), f"{destino.entrada.ruta}.dentro_de"
                )

    def _destino_de(self, nombre: str, ruta: str) -> _Destino:
        if nombre in self.nuevas:
            return self.nuevas[nombre]
        nodo = self._categoria_por_nombre(nombre, ruta)
        destino = self.por_eid.get(nodo.eid)
        if destino is None:
            raise self._error(
                "PONDERACION_INVALIDA",
                ruta,
                f"«{nombre}» necesita su entrada con el elemento de esta categoría nueva",
            )
        return destino

    def resolver_elementos(self) -> None:
        for destino in self.destinos:
            for elemento in destino.entrada.elementos:
                destino.elementos.append(self._elemento(elemento))
            pesos = [e.peso is not None for e in destino.elementos]
            if any(pesos) and not all(pesos):
                raise self._error(
                    "PESOS_MEZCLADOS",
                    f"{destino.entrada.ruta}.elementos",
                    "en una misma lista no se mezclan «peso» y «porcentaje»",
                )

    def _elemento(self, elemento: ElementoPonderacion) -> _Elemento:
        referencia = elemento.referencia
        ref = referencia_de(elemento)
        ruta = elemento.ruta
        nuevo: _Destino | None = None
        if referencia.clase == "categoria" and referencia.nombre in self.nuevas:
            nuevo = self.nuevas[referencia.nombre]
            nodo = nuevo.nodo
            nombre = nuevo.nombre
        else:
            nodo = self._nodo_de(elemento)
            nombre = nodo.nombre
        return _Elemento(
            ref,
            ruta,
            nodo.eid if nodo is not None else self.nuevas[referencia.nombre].eid,
            nodo,
            nombre,
            elemento.porcentaje,
            elemento.peso,
            nuevo,
            self._bloqueante(nodo),
        )

    def _nodo_de(self, elemento: ElementoPonderacion) -> NodoPonderacion:
        referencia, ruta = elemento.referencia, elemento.ruta
        if referencia.clase == "categoria":
            return self._categoria_por_nombre(referencia.nombre, f"{ruta}.categoria")
        if referencia.clase == "elemento":
            manuales = [n for n in self.arbol.por_nombre(referencia.nombre) if n.clase == "manual"]
            if not manuales:
                raise self._error(
                    "ELEMENTO_AUSENTE", ruta, f"no hay un elemento «{referencia.nombre}» en el aula"
                )
            if len(manuales) > 1:
                raise self._error(
                    "ELEMENTO_AMBIGUO",
                    ruta,
                    f"hay varios elementos «{referencia.nombre}» en el aula",
                )
            return manuales[0]
        if referencia.clase == "fichero":
            return self._nodo_de_fichero(elemento)
        return self._nodo_de_actividad(elemento)

    def _nodo_de_fichero(self, elemento: ElementoPonderacion) -> NodoPonderacion:
        ruta = elemento.ruta
        documento = elemento.documento
        if documento is None:
            raise self._error("PONDERACION_INVALIDA", ruta, "el fichero no se cargó")
        loc = self.estructura.localizar(documento, self.arbol.curso)
        if loc.problema == "ORIGEN_NO_ENCONTRADO":
            raise self._error(
                "ACTIVIDAD_AUSENTE", ruta, "la actividad de este fichero ya no está en el aula"
            )
        if loc.problema == "ACTIVIDAD_AMBIGUA" or loc.varios:
            raise self._error(
                "ACTIVIDAD_AMBIGUA",
                ruta,
                "hay varias actividades que podrían ser la de este fichero",
            )
        if loc.modulo is None:
            raise self._error(
                "ACTIVIDAD_PENDIENTE", ruta, "este fichero aún no está publicado en el aula"
            )
        return self._nodo_de_cmid(loc.modulo.cmid, ruta)

    def _nodo_de_cmid(self, cmid: int, ruta: str) -> NodoPonderacion:
        for nodo in self.arbol.nodos:
            if nodo.cmid == cmid:
                return nodo
        raise self._error(
            "ACTIVIDAD_PENDIENTE", ruta, "la actividad aún no está en el calificador del aula"
        )

    def _nodo_de_actividad(self, elemento: ElementoPonderacion) -> NodoPonderacion:
        referencia, ruta = elemento.referencia, elemento.ruta
        seccion = (
            self.estructura.buscar_seccion(referencia.seccion)
            if referencia.seccion is not None
            else None
        )
        coincidencias = (
            [
                a
                for a in seccion.actividades
                if a.tipo == referencia.tipo and a.nombre == referencia.nombre
            ]
            if seccion is not None
            else []
        )
        if not coincidencias:
            raise self._error("ACTIVIDAD_AUSENTE", ruta, "no hay una actividad así en el aula")
        if len(coincidencias) > 1:
            raise self._error("ACTIVIDAD_AMBIGUA", ruta, "hay varias actividades así en el aula")
        return self._nodo_de_cmid(coincidencias[0].cmid, ruta)

    # --- validaciones ---

    def validar_forma(self) -> None:
        for nueva in self.nuevas.values():
            apariciones = [(d, e) for d in self.destinos for e in d.elementos if e.nuevo is nueva]
            id_ = nueva.entrada.id
            if len(apariciones) != 1:
                raise self._error(
                    "PONDERACION_INVALIDA",
                    nueva.entrada.ruta,
                    f"la categoría nueva «{id_}» debe aparecer exactamente una vez como "
                    "elemento de la lista de su «dentro_de»",
                )
            if apariciones[0][0] is not nueva.padre:
                raise self._error(
                    "PONDERACION_INVALIDA",
                    apariciones[0][1].ruta,
                    f"«{id_}» está en una lista distinta de su «dentro_de»",
                )
        vistos: dict[str, str] = {}
        for destino in self.destinos:
            for elemento in destino.elementos:
                if elemento.eid in vistos:
                    raise self._error(
                        "ELEMENTO_REPETIDO",
                        elemento.ruta,
                        f"ya está en {vistos[elemento.eid]}; un elemento solo puede estar en una lista",
                    )
                vistos[elemento.eid] = elemento.ruta
        self._sin_ciclos()

    def _sin_ciclos(self) -> None:
        padre: dict[str, str | None] = {n.eid: n.padre_eid for n in self.arbol.nodos}
        for destino in self.destinos:
            for elemento in destino.elementos:
                padre[elemento.eid] = destino.eid
        for inicio in padre:
            vistos = {inicio}
            actual = padre.get(inicio)
            while actual is not None:
                if actual in vistos:
                    raise self._error(
                        "PONDERACION_INVALIDA",
                        "ponderacion",
                        "el esquema dejaría una categoría dentro de sí misma",
                    )
                vistos.add(actual)
                actual = padre.get(actual)

    def _opciones(self, destino: _Destino) -> tuple[int, ...] | None:
        actual: _Destino | None = destino
        while actual is not None:
            if actual.nodo is not None:
                return actual.nodo.opciones_agregacion
            actual = actual.padre
        return None

    def validar_calculos(self) -> None:
        for destino in self.destinos:
            entrada, nodo = destino.entrada, destino.nodo
            con_porcentajes = any(e.porcentaje is not None for e in destino.elementos)
            if (
                not entrada.nueva
                and entrada.calculo is None
                and con_porcentajes
                and (nodo is None or nodo.agregacion not in _NOMBRE_METODO)
            ):
                raise self._error(
                    "CALCULO_SIN_PESOS",
                    entrada.ruta,
                    "la categoría no tiene pesos por elemento; declara «calculo» para cambiarlo",
                )
            if destino.metodo not in _NOMBRE_METODO:
                continue
            if nodo is not None and nodo.agregacion == destino.metodo:
                continue
            opciones = self._opciones(destino)
            if opciones is not None and destino.metodo not in opciones:
                raise self._error(
                    "CALCULO_NO_DISPONIBLE",
                    entrada.ruta,
                    f"el aula no ofrece el cálculo «{_NOMBRE_METODO[destino.metodo]}»",
                )

    def corta_por_bloqueo(self) -> list[AvisoPonderacion]:
        avisos: list[AvisoPonderacion] = []
        for destino in self.destinos:
            if not destino.a_crear:
                continue
            actual = destino.padre
            while actual is not None and actual.a_crear:
                actual = actual.padre
            bloqueante = actual.bloqueante if actual is not None else None
            if bloqueante is not None:
                aviso = AvisoPonderacion("CATEGORIA_BLOQUEADA", bloqueante.nombre)
                if aviso not in avisos:
                    avisos.append(aviso)
        return avisos

    # --- estados de los elementos ---

    def _saltado(self, destino: _Destino, congelados: frozenset[str]) -> bool:
        actual: _Destino | None = destino
        while actual is not None:
            if actual.metodo not in _NOMBRE_METODO:
                return True
            if actual.nodo is not None and (
                actual.bloqueante is not None or actual.ref in congelados
            ):
                return True
            actual = actual.padre if actual.a_crear else None
        return False

    def _estado(self, destino: _Destino, elemento: _Elemento, congelados: frozenset[str]) -> str:
        if elemento.nodo is None:
            return _NOMBRADO
        if elemento.bloqueante is None and elemento.ref not in congelados:
            return _NOMBRADO
        return _FIJO if elemento.nodo.padre_eid == destino.eid else _OMITIDO

    def _contexto(
        self, congelados: frozenset[str]
    ) -> tuple[dict[tuple[int, str], str], set[int], set[str]]:
        saltados = {d.indice for d in self.destinos if self._saltado(d, congelados)}
        estados = {
            (d.indice, e.ref): self._estado(d, e, congelados)
            for d in self.destinos
            for e in d.elementos
        }
        mueve = {
            e.eid
            for d in self.destinos
            if d.indice not in saltados
            for e in d.elementos
            if estados[(d.indice, e.ref)] == _NOMBRADO
            and e.nodo is not None
            and e.nodo.padre_eid != d.eid
        }
        return estados, saltados, mueve

    def _sin_nombrar(
        self, destino: _Destino, nombrados: Sequence[_Elemento], mueve: set[str]
    ) -> list[NodoPonderacion]:
        if destino.nodo is None:
            return []
        propios = {e.eid for e in nombrados}
        return [
            n
            for n in self.arbol.hijos(destino.nodo.eid)
            if n.eid not in propios and n.eid not in mueve
        ]

    # --- comprobaciones de porcentajes (sobre lo declarado, sin congelar nada) ---

    def _coef_sin_nombrar(self, destino: _Destino, nodo: NodoPonderacion) -> float:
        actual = destino.nodo.agregacion if destino.nodo is not None else None
        return _coef_actual(nodo) if actual == MEDIA_PONDERADA else 1.0

    def _override_sin_nombrar(self, destino: _Destino, nodo: NodoPonderacion) -> float | None:
        actual = destino.nodo.agregacion if destino.nodo is not None else None
        return _override_actual(nodo) if actual == NATURAL else None

    def comprobar_porcentajes(self) -> None:
        estados, saltados, mueve = self._contexto(frozenset())
        for destino in self.destinos:
            if destino.indice in saltados:
                continue
            nombrados = [
                e for e in destino.elementos if estados[(destino.indice, e.ref)] == _NOMBRADO
            ]
            if not nombrados:
                continue
            sin = self._sin_nombrar(destino, nombrados, mueve)
            en_pesos = all(e.peso is not None for e in nombrados)
            suma = 100.0 if en_pesos else sum(e.porcentaje or 0.0 for e in nombrados)
            ruta = f"{destino.entrada.ruta}.elementos"
            if destino.metodo == NATURAL:
                fijados = sum(
                    valor
                    for n in sin
                    if (valor := self._override_sin_nombrar(destino, n)) is not None
                )
                if suma + fijados > 100 + TOLERANCIA_SUMA:
                    raise self._error(
                        "PORCENTAJE_IMPOSIBLE",
                        ruta,
                        f"lo nombrado ({suma:g} %) más los pesos ya fijados en el aula ({fijados:g} %) pasa de 100",
                    )
            if en_pesos and destino.metodo == MEDIA_PONDERADA:
                continue
            if abs(suma - 100) > TOLERANCIA_SUMA:
                continue
            if destino.metodo == MEDIA_PONDERADA:
                queda = any(self._coef_sin_nombrar(destino, n) > 0 for n in sin)
            else:
                queda = any(
                    (valor := self._override_sin_nombrar(destino, n)) is None or valor > 0
                    for n in sin
                )
            if queda:
                raise self._error(
                    "PORCENTAJES_SIN_RESTO",
                    ruta,
                    "los porcentajes suman 100 y en la categoría quedan elementos sin nombrar",
                )

    # --- el cálculo ---

    def _objetivos(
        self,
        destino: _Destino,
        nombrados: Sequence[_Elemento],
        sin: Sequence[NodoPonderacion],
    ) -> dict[str, float]:
        """Coeficiente (media ponderada) o peso sobrescrito (natural) de cada nombrado."""
        if not nombrados:
            return {}
        if all(e.peso is not None for e in nombrados):
            pesos = {e.eid: float(e.peso or 0.0) for e in nombrados}
            if destino.metodo == MEDIA_PONDERADA:
                return {k: round(v, 4) for k, v in pesos.items()}
            total = sum(pesos.values())
            return {k: round(v / total * 100 if total > 0 else 0.0, 4) for k, v in pesos.items()}
        porcentajes = {e.eid: float(e.porcentaje or 0.0) for e in nombrados}
        if destino.metodo == MEDIA_PONDERADA:
            suma = sum(porcentajes.values())
            resto = sum(self._coef_sin_nombrar(destino, n) for n in sin)
            if resto > 0 and suma < 100 - TOLERANCIA_SUMA:
                return {k: round(v / (100 - suma) * resto, 4) for k, v in porcentajes.items()}
        return {k: round(v, 4) for k, v in porcentajes.items()}

    def _maximo_de(self, elemento: _Elemento) -> float:
        if elemento.nodo is not None:
            return elemento.nodo.maximo or 0.0
        nuevo = elemento.nuevo
        assert nuevo is not None
        if nuevo.metodo != NATURAL:
            return 100.0
        return sum(self._maximo_de(e) for e in nuevo.elementos)

    def _piezas(
        self,
        destino: _Destino,
        nombrados: Sequence[_Elemento],
        sin: Sequence[NodoPonderacion],
        objetivo: Mapping[str, float],
        aplicados: Collection[str],
    ) -> list[_Pieza]:
        metodo = destino.metodo
        piezas: list[_Pieza] = []
        for e in nombrados:
            if e.nodo is None or e.eid in aplicados:
                valor = objetivo[e.eid]
                piezas.append(
                    _Pieza(
                        e.eid,
                        valor if metodo == MEDIA_PONDERADA else 1.0,
                        valor if metodo == NATURAL else None,
                        self._maximo_de(e),
                    )
                )
            else:
                piezas.append(_pieza_actual(e.nodo))
        for n in sin:
            piezas.append(
                _Pieza(
                    n.eid,
                    self._coef_sin_nombrar(destino, n),
                    self._override_sin_nombrar(destino, n) if metodo == NATURAL else None,
                    n.maximo or 0.0,
                )
            )
        return piezas

    def _antes_del_padre(self, padre: NodoPonderacion) -> dict[str, float]:
        if padre.eid not in self._antes_cache:
            self._antes_cache[padre.eid] = _efectivos(
                padre.agregacion, [_pieza_actual(h) for h in self.arbol.hijos(padre.eid)]
            )
        return self._antes_cache[padre.eid]

    def _antes(self, nodo: NodoPonderacion) -> float | None:
        padre = self.arbol.nodo(nodo.padre_eid) if nodo.padre_eid else None
        if padre is None:
            return None
        return self._antes_del_padre(padre).get(nodo.eid)

    def calcular(self, congelados: frozenset[str]) -> _Calculo:
        estados, saltados, mueve = self._contexto(congelados)
        mover: list[OperacionPonderacion] = []
        metodo: list[OperacionPonderacion] = []
        coeficiente: list[OperacionPonderacion] = []
        coef_crear: dict[str, float] = {}
        porcentaje_crear: dict[str, float] = {}
        afectadas: list[CategoriaAfectada] = []
        con_notas: list[str] = []
        despues_global: dict[str, float] = {}
        ref_por_eid = {e.eid: e.ref for d in self.destinos for e in d.elementos}

        for destino in self.destinos:
            if destino.indice in saltados:
                continue
            nodo = destino.nodo
            nuevo_metodo = destino.metodo
            actual = nodo.agregacion if nodo is not None else None
            lista = [e for e in destino.elementos if estados[(destino.indice, e.ref)] != _OMITIDO]
            nombrados = [e for e in lista if estados[(destino.indice, e.ref)] == _NOMBRADO]
            sin = self._sin_nombrar(destino, nombrados, mueve)
            objetivo = self._objetivos(destino, nombrados, sin)
            cambia_metodo = nodo is not None and actual != nuevo_metodo
            aplicados = {
                e.eid
                for e in nombrados
                if e.nodo is None
                or e.nodo.padre_eid != destino.eid
                or cambia_metodo
                or (nuevo_metodo == NATURAL and _override_actual(e.nodo) is None)
            }
            todos = {e.eid for e in nombrados}
            deseado = _efectivos(
                nuevo_metodo, self._piezas(destino, nombrados, sin, objetivo, todos)
            )
            while True:
                efectivo = _efectivos(
                    nuevo_metodo, self._piezas(destino, nombrados, sin, objetivo, aplicados)
                )
                desvios = {
                    e.eid: abs(efectivo[e.eid] - deseado[e.eid])
                    for e in nombrados
                    if e.eid not in aplicados
                }
                peor = max(desvios, key=lambda eid: desvios[eid], default=None)
                if peor is None or desvios[peor] <= TOLERANCIA_EFECTIVA:
                    break
                aplicados.add(peor)
            despues_global.update(efectivo)

            tocada = destino.a_crear or (
                nodo is not None and any(n.eid in mueve for n in self.arbol.hijos(nodo.eid))
            )
            if nodo is not None and (
                cambia_metodo or (destino.solo is not None and nodo.solo_no_vacias != destino.solo)
            ):
                metodo.append(
                    OperacionPonderacion(
                        "metodo",
                        destino.ref,
                        eid=nodo.eid,
                        agregacion=nuevo_metodo,
                        solo_no_vacias=destino.solo,
                    )
                )
                tocada = True
            previo: str | None = None
            for posicion, e in enumerate(lista):
                if estados[(destino.indice, e.ref)] == _NOMBRADO:
                    se_mueve = (
                        e.nodo.padre_eid != destino.eid
                        if e.nodo is not None
                        else posicion < len(lista) - 1
                    )
                    if se_mueve:
                        mover.append(
                            OperacionPonderacion(
                                "mover",
                                e.ref,
                                eid=e.eid,
                                destino=destino.eid,
                                despues_de=previo,
                            )
                        )
                        tocada = True
                    if e.eid in aplicados:
                        if e.nodo is None and nuevo_metodo == MEDIA_PONDERADA:
                            assert e.nuevo is not None
                            coef_crear[str(e.nuevo.entrada.id)] = objetivo[e.eid]
                            if e.eid in deseado:
                                porcentaje_crear[str(e.nuevo.entrada.id)] = deseado[e.eid]
                        else:
                            coeficiente.append(
                                OperacionPonderacion(
                                    "coeficiente",
                                    e.ref,
                                    eid=e.eid,
                                    coeficiente=objetivo[e.eid],
                                    porcentaje=deseado.get(e.eid),
                                    metodo_del_padre=_NOMBRE_METODO[nuevo_metodo],
                                )
                            )
                        tocada = True
                    if e.nodo is None:
                        tocada = True
                previo = e.eid

            if not tocada:
                continue
            hijos: list[HijoAfectado] = []
            antes = (
                self._antes_del_padre(nodo) if nodo is not None and actual in _NOMBRE_METODO else {}
            )
            visto: set[str] = set()
            for e in lista:
                visto.add(e.eid)
                hijos.append(
                    HijoAfectado(
                        e.nombre,
                        e.ref,
                        antes.get(e.eid),
                        efectivo.get(e.eid),
                        e.peso,
                    )
                )
            if nodo is not None:
                for n in self.arbol.hijos(nodo.eid):
                    if n.eid in visto:
                        continue
                    visto.add(n.eid)
                    hijos.append(
                        HijoAfectado(
                            n.nombre,
                            ref_por_eid.get(n.eid) if n.eid in mueve else None,
                            antes.get(n.eid),
                            None if n.eid in mueve else efectivo.get(n.eid),
                        )
                    )
            solo_antes = nodo.solo_no_vacias if nodo is not None else None
            afectadas.append(
                CategoriaAfectada(
                    destino.nombre,
                    destino.ref,
                    _nombre_metodo(actual),
                    _NOMBRE_METODO[nuevo_metodo],
                    solo_antes,
                    destino.solo if destino.solo is not None else solo_antes,
                    tuple(hijos),
                )
            )
            if nodo is not None and nodo.tiene_notas:
                con_notas.append(nodo.nombre)

        procesados = {d.eid for d in self.destinos if d.indice not in saltados}
        salidas = self._salidas(mueve, procesados, afectadas, con_notas)
        operaciones = self._crear(
            crear_destinos=self._a_crear(saltados),
            coef_crear=coef_crear,
            porcentaje_crear=porcentaje_crear,
        )
        operaciones += mover + metodo + coeficiente
        return _Calculo(
            operaciones,
            afectadas,
            con_notas,
            salidas,
            despues_global,
            {o.referencia for o in operaciones if o.tipo != "crear"},
        )

    def _a_crear(self, saltados: set[int]) -> list[_Destino]:
        def profundidad(destino: _Destino) -> int:
            nivel, actual = 0, destino.padre
            while actual is not None and actual.a_crear:
                nivel, actual = nivel + 1, actual.padre
            return nivel

        a_crear = [d for d in self.destinos if d.a_crear and d.indice not in saltados]
        return sorted(a_crear, key=lambda d: (profundidad(d), d.indice))

    def _crear(
        self,
        crear_destinos: Sequence[_Destino],
        coef_crear: Mapping[str, float],
        porcentaje_crear: Mapping[str, float],
    ) -> list[OperacionPonderacion]:
        operaciones: list[OperacionPonderacion] = []
        for destino in crear_destinos:
            id_ = str(destino.entrada.id)
            padre = destino.padre
            assert padre is not None
            operaciones.append(
                OperacionPonderacion(
                    "crear",
                    destino.ref,
                    eid=destino.eid,
                    id=id_,
                    nombre=destino.nombre,
                    idnumber=f"{PREFIJO_IDNUMBER}{id_}",
                    padre=padre.eid,
                    agregacion=destino.metodo,
                    solo_no_vacias=destino.solo,
                    coeficiente=coef_crear.get(id_) if padre.metodo == MEDIA_PONDERADA else None,
                    porcentaje=porcentaje_crear.get(id_),
                )
            )
        return operaciones

    def _salidas(
        self,
        mueve: set[str],
        procesados: set[str],
        afectadas: list[CategoriaAfectada],
        con_notas: list[str],
    ) -> list[str]:
        salidas: list[str] = []
        origenes: list[str] = []
        for nodo in self.arbol.nodos:
            if nodo.eid not in mueve:
                continue
            origen = self.arbol.nodo(nodo.padre_eid) if nodo.padre_eid else None
            if origen is None:
                continue
            if origen.eid not in origenes:
                origenes.append(origen.eid)
            if (nodo.tiene_notas or origen.tiene_notas) and origen.nombre not in salidas:
                salidas.append(origen.nombre)
        for origen_eid in origenes:
            if origen_eid in procesados:
                continue
            origen = self.arbol.nodo(origen_eid)
            assert origen is not None
            quedan = [n for n in self.arbol.hijos(origen_eid) if n.eid not in mueve]
            antes = self._antes_del_padre(origen)
            despues = _efectivos(origen.agregacion, [_pieza_actual(n) for n in quedan])
            hijos = tuple(
                HijoAfectado(
                    n.nombre,
                    self._ref_de_nodo(n.eid),
                    antes.get(n.eid),
                    despues.get(n.eid) if n.eid not in mueve else None,
                )
                for n in self.arbol.hijos(origen_eid)
            )
            metodo = _nombre_metodo(origen.agregacion)
            afectadas.append(
                CategoriaAfectada(
                    origen.nombre,
                    None,
                    metodo,
                    metodo,
                    origen.solo_no_vacias,
                    origen.solo_no_vacias,
                    hijos,
                )
            )
            if origen.tiene_notas:
                con_notas.append(origen.nombre)
        return salidas

    def _ref_de_nodo(self, eid: str) -> str | None:
        for d in self.destinos:
            for e in d.elementos:
                if e.eid == eid:
                    return e.ref
        return None

    # --- manos del docente ---

    def cambiados(self, nodos: Mapping[str, NodoPonderacion]) -> set[str]:
        return {
            ref
            for ref, nodo in nodos.items()
            if ref in self.huellas
            and self.huellas[ref] != huella_nodo(nodo, self.arbol)
            and ref not in self.sobrescribir
        }

    def nodos_por_ref(self) -> dict[str, NodoPonderacion]:
        nodos: dict[str, NodoPonderacion] = {}
        for d in self.destinos:
            if d.nodo is not None:
                nodos[d.ref] = d.nodo
            for e in d.elementos:
                if e.nodo is not None:
                    nodos[e.ref] = e.nodo
        return nodos

    def planificar(self) -> PlanPonderacion:
        self.resolver_destinos()
        self.resolver_elementos()
        self.validar_forma()
        self.validar_calculos()
        bloqueo = self.corta_por_bloqueo()
        if bloqueo:
            return PlanPonderacion(
                self.arbol.curso, (), (), tuple(bloqueo), (), (), (), corta=True, sin_cambios=False
            )
        self.comprobar_porcentajes()

        nodos = self.nodos_por_ref()
        candidatos = self.cambiados(nodos)
        completo = self.calcular(frozenset())
        congelados = frozenset(candidatos & completo.con_operacion)
        resultado = self.calcular(congelados) if congelados else completo

        cambios = tuple(
            CambioAMano(
                ref,
                nodos[ref].nombre,
                self._antes(nodos[ref]),
                completo.despues.get(nodos[ref].eid),
            )
            for ref in sorted(congelados)
        )
        avisos = self._avisos_de_bloqueo()
        avisos += [AvisoPonderacion("CAMBIADO_A_MANO", c.nombre, c.referencia) for c in cambios]
        con_notas = tuple(dict.fromkeys(resultado.con_notas))
        avisos += [AvisoPonderacion("PESOS_CON_NOTAS", nombre) for nombre in con_notas]
        avisos += self._no_declaradas()
        operaciones = tuple(resultado.operaciones)
        return PlanPonderacion(
            self.arbol.curso,
            operaciones,
            tuple(resultado.afectadas),
            tuple(avisos),
            cambios,
            con_notas,
            tuple(resultado.salidas),
            corta=False,
            sin_cambios=not operaciones,
        )

    def _avisos_de_bloqueo(self) -> list[AvisoPonderacion]:
        bloqueantes: list[NodoPonderacion] = []
        for destino in self.destinos:
            if destino.bloqueante is not None:
                bloqueantes.append(destino.bloqueante)
                continue
            bloqueantes += [e.bloqueante for e in destino.elementos if e.bloqueante is not None]
        avisos: list[AvisoPonderacion] = []
        for bloqueante in bloqueantes:
            aviso = AvisoPonderacion("CATEGORIA_BLOQUEADA", bloqueante.nombre)
            if aviso not in avisos:
                avisos.append(aviso)
        return avisos

    def _no_declaradas(self) -> list[AvisoPonderacion]:
        declaradas = {e.id for e in self.esquema.entradas if e.nueva}
        avisos: list[AvisoPonderacion] = []
        for eid, idnumber in sorted(self.tzp.items()):
            id_ = idnumber[len(PREFIJO_IDNUMBER) :]
            if id_ in declaradas:
                continue
            nodo = self.arbol.nodo(eid)
            avisos.append(
                AvisoPonderacion("CATEGORIA_NO_DECLARADA", nodo.nombre if nodo else idnumber)
            )
        return avisos


def planificar(
    esquema: EsquemaPonderacion,
    estructura: Estructura,
    arbol: ArbolPonderacion,
    huellas: Mapping[str, str],
    *,
    calificador_de_tiza: bool = False,
    tzp: Mapping[str, str] | None = None,
    sobrescribir: Collection[str] = (),
) -> PlanPonderacion:
    """El plan de un curso: qué crear, mover y fijar para que el aula cumpla el esquema.

    Pura: no habla con el aula. ``huellas`` es ``referencia -> huella`` de la última pasada de
    este curso; ``tzp`` es ``eid -> número de ID`` de las categorías ``TZP_`` del aula (se suma a
    lo que ya dicen los nodos del árbol); ``sobrescribir`` son las referencias cambiadas a mano
    que el docente ya aceptó pisar. Los fallos del curso son ``ErrorPonderacion`` con su código.

    Reglas del reparto (``p`` es el porcentaje pedido, ``S`` la suma de coeficientes de lo que
    queda sin nombrar):

    * media ponderada: ``coef = p / (100 - Σp) · S`` a 4 decimales; si ``S = 0`` o no queda
      nada sin nombrar, ``coef = p`` (la escala da igual). Con ``peso`` (categoría nueva),
      ``coef = peso``;
    * natural: el peso sobrescrito es ``p`` (con ``peso``, ``p = peso / Σpeso · 100``).
    """
    if calificador_de_tiza:
        raise ErrorPonderacion(
            "PONDERACION_CON_CALIFICADOR_DE_TIZA",
            "el curso tiene el «Calificador de tiza»: no se mezcla con la ponderación",
        )
    return _Planificador(esquema, estructura, arbol, huellas, tzp, sobrescribir).planificar()


def nodos_nombrados(
    esquema: EsquemaPonderacion,
    estructura: Estructura,
    arbol: ArbolPonderacion,
    *,
    tzp: Mapping[str, str] | None = None,
) -> dict[str, NodoPonderacion]:
    """``referencia -> nodo`` de lo que el esquema nombra y existe en ``arbol``.

    Es la misma resolución que hace ``planificar`` (sin validar ni calcular nada): sirve para
    saber qué nodo del aula es cada referencia, por ejemplo al verificar y guardar las huellas.
    Un esquema que no se resuelve contra ``arbol`` es ``ErrorPonderacion``.
    """
    planificador = _Planificador(esquema, estructura, arbol, {}, tzp, ())
    planificador.resolver_destinos()
    planificador.resolver_elementos()
    return planificador.nodos_por_ref()
