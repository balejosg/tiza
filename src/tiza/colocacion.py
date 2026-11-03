"""Dónde va la nota de una actividad en el calificador: la regla pura de «seguir a la sección».

Módulo puro: no habla con el aula ni importa python-moodle. Recibe la estructura del aula
(:class:`~tiza.estructura.Estructura`) y el árbol del calificador ya leído
(:class:`ArbolNotas`) y dice qué notas hay que mover y cuáles no se pueden colocar.

La regla, para cada actividad de ``cmids`` en el orden del curso (sección y luego posición):

* **Patrón.** Las otras actividades con nota de su sección: filas con ``cmid`` que no están en
  una categoría ``de_tiza`` y que no están en ``cmids`` (salvo las de ``cmids`` que esta misma
  llamada ya ha colocado). Si todas comparten categoría, esa es el destino. Si no hay ninguna,
  se mira la sección anterior, y así hacia atrás. Si están en varias categorías, ``AMBIGUA``.
  Si no hay ninguna en todo el curso, ``SIN_PATRON``. La raíz cuenta como una categoría más.
* **Cerradas.** Un destino bloqueado es ``CERRADA`` y no se sigue buscando; tampoco se saca una
  nota de una categoría bloqueada (``CERRADA`` con el nombre de la de origen).
* **Posición.** Detrás de la nota del destino cuya actividad va más tarde entre las que van
  antes en el orden del curso (aunque la página las tenga en otro orden), o al principio (``despues_de=None``) si no hay ninguna.
* **Sin cambios.** Si la nota ya está en su categoría y en su sitio, no sale nada.
* **De tiza.** Una nota que ya está en una categoría ``de_tiza`` no se toca: no da nada.
* **Sin nota.** Una actividad sin fila en el árbol no da movimiento ni ``SinColocar``.

Los movimientos se aplican en orden sobre un árbol simulado, para que el siguiente ``cmid``
los vea. Las notas que no están en el orden del curso (elementos manuales o calculados,
actividades que ya no están en la estructura) no cuentan para decidir la posición.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from .estructura import Estructura

AMBIGUA = "AMBIGUA"
SIN_PATRON = "SIN_PATRON"
CERRADA = "CERRADA"


@dataclass(frozen=True)
class FilaNota:
    """Una fila del calificador: una categoría o un elemento de nota."""

    eid: str  # «cg<n>» categoría, «ig<n>» elemento
    padre: str | None  # eid de su categoría; None solo en la raíz del curso
    cmid: int | None  # la actividad, si es de una
    nombre: str  # solo lo ve el docente
    bloqueada: bool = False  # categorías: su total lleva fa-lock
    de_tiza: bool = False  # categorías: TZ_ o descendiente de una TZ_


@dataclass(frozen=True)
class ArbolNotas:
    """El calificador en el orden de la página, sin las filas de total."""

    filas: tuple[FilaNota, ...]

    def raiz(self) -> str:
        """El eid de la categoría raíz del curso (la fila sin padre)."""
        for fila in self.filas:
            if fila.padre is None:
                return fila.eid
        raise ValueError("el árbol de notas no tiene raíz")

    def fila(self, eid: str) -> FilaNota | None:
        for fila in self.filas:
            if fila.eid == eid:
                return fila
        return None

    def de_cmid(self, cmid: int) -> FilaNota | None:
        for fila in self.filas:
            if fila.cmid == cmid:
                return fila
        return None


@dataclass(frozen=True)
class MovimientoNota:
    """Mover un elemento a una categoría, detrás de otra nota (o al principio)."""

    cmid: int
    eid: str  # el elemento que se mueve
    categoria: str  # eid de la categoría de destino
    despues_de: str | None  # eid de la nota tras la que va; None: al principio
    nombre_categoria: str
    desde: str | None  # nombre de la categoría de la que sale (None si la raíz)


@dataclass(frozen=True)
class SinColocar:
    """Una nota que tiza no coloca, y por qué: ``AMBIGUA``, ``SIN_PATRON`` o ``CERRADA``."""

    cmid: int
    motivo: str
    categoria: str | None  # nombre, solo con "CERRADA"


def colocar(
    estructura: Estructura, arbol: ArbolNotas, cmids: Sequence[int]
) -> tuple[tuple[MovimientoNota, ...], tuple[SinColocar, ...]]:
    """Los movimientos y los avisos para colocar las notas de ``cmids`` según su sección."""
    orden: dict[int, int] = {}
    seccion_de: dict[int, int] = {}
    for indice, seccion in enumerate(estructura):
        for cmid in seccion.cmids:
            orden.setdefault(cmid, len(orden))
            seccion_de.setdefault(cmid, indice)
    secciones = tuple(estructura)
    pedidos = set(cmids)
    pendientes = sorted((c for c in pedidos if c in orden), key=lambda c: orden[c])

    filas = list(arbol.filas)
    colocadas: set[int] = set()
    movimientos: list[MovimientoNota] = []
    sin_colocar: list[SinColocar] = []

    for cmid in pendientes:
        actual = ArbolNotas(tuple(filas))
        fila = actual.de_cmid(cmid)
        if fila is None:
            continue
        origen = actual.fila(fila.padre) if fila.padre is not None else None
        if origen is not None and origen.de_tiza:
            continue  # lo que está en una categoría de tiza no se toca
        de_atras = [secciones[i].cmids for i in range(seccion_de[cmid], -1, -1)]
        categorias = _patron(actual, cmid, de_atras, pedidos - colocadas)
        if not categorias:
            sin_colocar.append(SinColocar(cmid, SIN_PATRON, None))
            continue
        if len(categorias) > 1:
            sin_colocar.append(SinColocar(cmid, AMBIGUA, None))
            continue
        ((destino, destino_fila),) = categorias.items()
        despues = _despues_de(filas, orden, cmid, destino)
        if fila.padre == destino and _anterior(filas, orden, fila) == despues:
            colocadas.add(cmid)
            continue
        if destino_fila.bloqueada:
            sin_colocar.append(SinColocar(cmid, CERRADA, destino_fila.nombre))
            continue
        if origen is not None and origen.bloqueada:
            sin_colocar.append(SinColocar(cmid, CERRADA, origen.nombre))
            continue
        movimientos.append(
            MovimientoNota(
                cmid=cmid,
                eid=fila.eid,
                categoria=destino,
                despues_de=despues,
                nombre_categoria=destino_fila.nombre,
                desde=origen.nombre if origen is not None and origen.padre is not None else None,
            )
        )
        filas = _mover(filas, fila, destino, despues)
        colocadas.add(cmid)
    return tuple(movimientos), tuple(sin_colocar)


def _patron(
    arbol: ArbolNotas, cmid: int, secciones: Sequence[Sequence[int]], excluidos: set[int]
) -> dict[str, FilaNota]:
    """Las categorías de las otras notas de la primera sección (hacia atrás) que tenga alguna."""
    for cmids_de_la_seccion in secciones:
        categorias: dict[str, FilaNota] = {}
        for otro in cmids_de_la_seccion:
            if otro == cmid or otro in excluidos:
                continue
            fila = arbol.de_cmid(otro)
            padre = arbol.fila(fila.padre) if fila is not None and fila.padre else None
            if padre is None or padre.de_tiza:
                continue
            categorias[padre.eid] = padre
        if categorias:
            return categorias
    return {}


def _hijos_con_orden(
    filas: Sequence[FilaNota], orden: dict[int, int], categoria: str
) -> list[FilaNota]:
    """Las notas de la categoría cuya actividad está en el orden del curso, en la página."""
    return [f for f in filas if f.padre == categoria and f.cmid is not None and f.cmid in orden]


def _despues_de(
    filas: Sequence[FilaNota], orden: dict[int, int], cmid: int, categoria: str
) -> str | None:
    """La nota de la categoría cuya actividad va justo antes que ``cmid`` en el curso.

    Es la de mayor posición en el orden del curso, estén como estén en la página.
    """
    antes = [
        (orden[f.cmid], f.eid)
        for f in _hijos_con_orden(filas, orden, categoria)
        if f.cmid is not None and f.cmid != cmid and orden[f.cmid] < orden[cmid]
    ]
    return max(antes)[1] if antes else None


def _anterior(filas: Sequence[FilaNota], orden: dict[int, int], fila: FilaNota) -> str | None:
    """La nota de su categoría (en el orden del curso) que tiene justo delante en la página."""
    if fila.padre is None:
        return None
    previa: str | None = None
    for otra in _hijos_con_orden(filas, orden, fila.padre):
        if otra.eid == fila.eid:
            return previa
        previa = otra.eid
    return previa


def _mover(
    filas: Sequence[FilaNota], fila: FilaNota, categoria: str, despues: str | None
) -> list[FilaNota]:
    """El árbol tras mover ``fila`` a ``categoria``, detrás de ``despues`` (o al principio)."""
    resto = [f for f in filas if f.eid != fila.eid]
    ancla = despues if despues is not None else categoria
    posicion = next((i for i, f in enumerate(resto) if f.eid == ancla), len(resto) - 1) + 1
    resto.insert(posicion, replace(fila, padre=categoria))
    return resto
