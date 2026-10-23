"""Ejecutar las operaciones de la reconciliación sobre el aula, en orden.

Lo que ``reconciliar`` decide son ``Operacion`` con ``idnumber`` y ``padre`` por número de ID;
aquí se traducen a las llamadas de ``Moodle`` (``AulaVirtual``). Lo que se crea en la propia
ejecución no tiene aún ``eid``: se recuerda el que devuelve ``crear_*`` y se resuelve por
``idnumber``. Si falta un dato que solo da el aula (el ``item_id`` del total de una categoría
nueva), se relee el calificador una vez. Cada operación anota lo que toca (``tocados``): las
relecturas abren solo esos formularios (``Moodle.calificador``).

Para en el primer fallo, salvo una fórmula que el aula rechaza en la primera pasada: eso lo
espera la segunda pasada (Moodle lo rechaza a veces mientras sus categorías se acaban de crear).
"""

from __future__ import annotations

from tiza.calificacion.reconciliar import Operacion
from tiza.publicar import AulaVirtual, ErrorPublicacion

__all__ = ["Ejecucion", "FORMULA_NO_VALIDA", "SIN_EFECTO", "TIPOS_DE_BLOQUEO"]

FORMULA_NO_VALIDA = "FORMULA_NO_VALIDA"
SIN_EFECTO = "BLOQUEO_SIN_EFECTO"  # detalle de BLOQUEO_FALLIDO: el aula aceptó y no bloqueó
TIPOS_DE_BLOQUEO = ("bloquear_ajeno", "bloquear_cerrada")
_TIPOS_DE_FORMULA = ("fijar_formula", "fijar_total_curso")


class Ejecucion:
    """Las operaciones de un curso, una tras otra, sobre el aula ya abierta."""

    def __init__(self, aula: AulaVirtual, curso: int, decimal: str) -> None:
        self.aula = aula
        self.curso = curso
        self.decimal = decimal
        self.eids: dict[str, str] = {}  # idnumber -> eid de lo creado en esta ejecución
        self.hechas: list[Operacion] = []
        self.formulas_pendientes = 0  # rechazadas y toleradas: la segunda pasada las repite
        self.tocados: set[str] = (
            set()
        )  # eids cambiados («ig<n>»: también el total de una categoría)
        self._releida: dict[str, tuple[str, int]] | None = None

    # -- resolución --------------------------------------------------------

    def _relectura(self) -> dict[str, tuple[str, int]]:
        if self._releida is None:
            self._releida = {
                n.idnumber: (n.eid, n.item_id)
                for n in self.aula.calificador(self.curso, self.tocados).nodos
                if n.idnumber
            }
        return self._releida

    def _eid_de(self, idnumber: str | None) -> str:
        if idnumber is None:
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR", "operación sin destino")
        if idnumber in self.eids:
            return self.eids[idnumber]
        if idnumber in self._relectura():
            return self._relectura()[idnumber][0]
        raise ErrorPublicacion("ESCRITURA_CALIFICADOR", "el destino de una operación no existe")

    def _padre(self, op: Operacion) -> str | None:
        if op.padre_eid is not None:
            return op.padre_eid
        if op.padre is not None:
            return self._eid_de(op.padre)
        return None

    def _eid(self, op: Operacion) -> str:
        return op.eid if op.eid is not None else self._eid_de(op.idnumber)

    def _item(self, op: Operacion) -> int:
        if op.item_id is not None:
            return op.item_id
        eid = self.eids.get(op.idnumber or "")
        if eid is not None and eid.startswith("ig"):
            return int(eid[2:])  # el elemento calculado es su propio grade_item
        if op.idnumber in self._relectura():
            return self._relectura()[op.idnumber][1]
        raise ErrorPublicacion("ESCRITURA_CALIFICADOR", "el destino de una operación no existe")

    # -- ejecución ---------------------------------------------------------

    def ejecutar(self, operaciones: tuple[Operacion, ...], *, tolerar_formulas: bool) -> None:
        """Ejecuta en orden; un ``ErrorPublicacion`` para en seco (``self.hechas`` dice hasta dónde).

        Un ``bloquear_ajeno`` fallido es ``BLOQUEO_FALLIDO`` (``detalle`` lleva el código del
        aula): si no se pudo proteger un total con notas, no se mueve nada más en ese curso. Que
        el aula acepte la orden no basta: al acabar cada tanda de bloqueos (los ajenos, antes de
        mover nada; los cierres, antes de borrar) se relee el calificador y cada total debe
        estar bloqueado; si no, también es ``BLOQUEO_FALLIDO``.
        """
        tanda: list[Operacion] = []
        for op in operaciones:
            if tanda and op.tipo != tanda[0].tipo:
                self._verificar_bloqueos(tanda)
                tanda = []
            try:
                self._una(op)
            except ErrorPublicacion as exc:
                if op.tipo == "bloquear_ajeno":
                    raise ErrorPublicacion("BLOQUEO_FALLIDO", exc.codigo) from None
                if (
                    tolerar_formulas
                    and op.tipo in _TIPOS_DE_FORMULA
                    and exc.codigo == FORMULA_NO_VALIDA
                ):
                    self.formulas_pendientes += 1
                    continue
                raise
            self.hechas.append(op)
            if op.tipo in TIPOS_DE_BLOQUEO:
                tanda.append(op)
        self._verificar_bloqueos(tanda)

    def _verificar_bloqueos(self, bloqueos: list[Operacion]) -> None:
        """Relee el calificador y exige ``bloqueado`` en cada total que se acaba de bloquear."""
        if not bloqueos:
            return
        self._releida = None  # lo cacheado es anterior al bloqueo
        bloqueados = {
            n.item_id for n in self.aula.calificador(self.curso, self.tocados).nodos if n.bloqueado
        }
        if any(op.item_id not in bloqueados for op in bloqueos):
            raise ErrorPublicacion("BLOQUEO_FALLIDO", SIN_EFECTO)

    def _una(self, op: Operacion) -> None:
        aula, curso = self.aula, self.curso
        tipo = op.tipo
        if tipo in TIPOS_DE_BLOQUEO:
            assert op.item_id is not None
            self.tocados.add(f"ig{op.item_id}")
            aula.bloquear_total(curso, op.item_id)
        elif tipo == "crear_categoria":
            assert op.idnumber is not None and op.nombre is not None
            self.eids[op.idnumber] = aula.crear_categoria(
                curso, op.nombre, op.idnumber, self._padre(op), op.peso, op.visualizacion
            )
        elif tipo == "crear_calculado":
            assert op.idnumber is not None and op.nombre is not None and op.maximo is not None
            self.eids[op.idnumber] = aula.crear_calculado(
                curso, op.nombre, op.idnumber, self._padre(op), op.peso, op.maximo
            )
        elif tipo == "colocar":
            assert op.cmid is not None
            padre = self._padre(op)
            if padre is None or not padre.startswith("cg"):
                raise ErrorPublicacion("ESCRITURA_CALIFICADOR", "la categoría de destino no existe")
            if op.eid is not None:
                self.tocados.add(op.eid)
            if op.item_id is not None:
                self.tocados.add(f"ig{op.item_id}")
            aula.colocar_actividad(
                curso, op.cmid, int(padre[2:]), op.idnumber if op.poner_idnumber else None
            )
        elif tipo == "mover_manual":
            padre = self._padre(op)
            if padre is None:
                raise ErrorPublicacion("ESCRITURA_CALIFICADOR", "la categoría de destino no existe")
            self.tocados.add(f"ig{self._item(op)}")
            aula.mover_manual(curso, self._item(op), padre)
        elif tipo == "fijar_peso":
            assert op.peso is not None
            self.tocados.add(self._eid(op))
            aula.fijar_peso(curso, self._eid(op), op.peso)
        elif tipo == "fijar_maximo":
            assert op.maximo is not None
            self.tocados.add(f"ig{self._item(op)}")
            aula.fijar_maximo(curso, self._item(op), op.maximo)
        elif tipo == "fijar_formula":
            assert op.formula is not None
            self.tocados.add(f"ig{self._item(op)}")
            aula.fijar_formula(curso, self._item(op), op.formula, self.decimal)
        elif tipo == "fijar_total_curso":  # la raíz se relee siempre
            aula.fijar_total_curso(curso, op.formula, self.decimal)
        elif tipo == "borrar":
            assert op.eid is not None
            self.tocados.add(op.eid)
            aula.borrar_nodo(curso, op.eid)
        else:  # pragma: no cover - ``reconciliar.TIPOS`` es la lista cerrada
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR", "operación desconocida")
