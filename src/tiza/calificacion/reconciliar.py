"""La reconciliación del calificador: lo deseado frente a lo que hay en el aula. Pura.

Compara el ``Deseado`` (``deseado.py``) con el calificador leído del aula (``CalificadorAula``) y
con la huella de lo que tiza montó la última vez (``estado.cargar_huellas``), y devuelve la lista
ordenada de ``Operacion`` que hay que ejecutar. No habla con el aula ni importa ``publicar``
(que carga python-moodle): quien ejecuta las operaciones es la tarea siguiente, con los métodos
de escritura de ``Moodle``.

Qué respeta, por este orden:

* una evaluación cerrada (``TZ_V_<n>`` **bloqueada en el aula**): nada de lo que cuelga de ella
  se crea, cambia, mueve ni borra, ni ella misma; tiza nunca desbloquea. Una actividad nueva en
  una sección de una evaluación cerrada se queda sin colocar, con todas sus copias e indicadores
  (``ACTIVIDAD_EN_EVALUACION_CERRADA``). Una evaluación ``cerrada: true`` que aún no está
  bloqueada (no existe, o a medio montar) se trata como abierta —se crea, se coloca y se ajusta,
  en las dos pasadas— y se bloquea al final de la segunda («cerrar es marcar y volver a montar»):
  si el montaje falla a medias, la ejecución siguiente la completa y después la bloquea;
* lo que el docente cambió a mano en lo de tiza (D3): si el aula difiere de la huella, ese nodo no
  se toca (ni su peso ni su fórmula); sus hijos sí se gestionan;
* las notas: un nodo de tiza que ya no está en el esquema pero tiene notas se queda, y una
  actividad real que deja de contar nunca se borra (es del docente): se queda con peso 0 (D2);
* los totales ajenos con notas se bloquean antes de sacar de ellos una actividad.

El montaje va en dos pasadas (Moodle reescala pesos al añadir dentro y una fórmula entre
categorías recién creadas puede fallar la primera vez): ``reconciliar`` da la primera y, tras
ejecutarla y releer el aula, ``pasada2`` da solo los ajustes que sigan haciendo falta (quien
ejecuta la repite, con tope, mientras Moodle siga reescalando pesos).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tiza import estado
from tiza.calificacion.deseado import NOTA_FINAL, Deseado, Nodo, normalizar_pesos
from tiza.calificacion.esquema import TOLERANCIA_PESOS
from tiza.calificacion.formulas import (
    formula_copia,
    formula_indicador,
    formula_nota,
    formula_tope,
)

if TYPE_CHECKING:  # solo para los tipos: importar ``publicar`` cargaría python-moodle
    from tiza.publicar import CalificadorAula, NodoAula

__all__ = [
    "AVISOS",
    "CURSO",
    "Operacion",
    "Reconciliacion",
    "TIPOS",
    "hay_anterior",
    "huella_de_nodo",
    "huellas_de",
    "pasada2",
    "reconciliar",
]

# El orden de la lista es el orden de ejecución por tipos (``crear_*``, ``colocar`` y
# ``mover_manual`` van mezclados, padres antes que hijos).
TIPOS = (
    "bloquear_ajeno",
    "crear_categoria",
    "crear_calculado",
    "colocar",
    "mover_manual",
    "fijar_peso",
    "fijar_maximo",
    "fijar_formula",
    "fijar_total_curso",
    "bloquear_cerrada",
    "borrar",
)
AVISOS = (
    "ACTIVIDAD_EN_EVALUACION_CERRADA",
    "ACTIVIDAD_PENDIENTE",
    "CAMBIADO_A_MANO",
    "EVALUACION_CERRADA_EN_EL_AULA",
    "ELEMENTO_CON_NOTAS_QUITADO",
    "TOTAL_AJENO_BLOQUEADO",
)
CURSO = "TZ_CURSO"  # la clave de la huella del total del curso en ``calificador.json``
_PREFIJO = "TZ_"
_EVALUACION = re.compile(r"TZ_V_[0-9]+")
_CLASES_CATEGORIA = ("contenedor", "categoria", "contador")
_MAXIMO_NOTA = 10.0
_PREFIJO_MANUAL = "TZ_M_"  # las casillas manuales: el docente pone las notas a mano
_MAXIMO_SIN_DATO = 100.0


@dataclass(frozen=True)
class Operacion:
    """Una operación sobre el calificador del aula.

    Solo ``tipo`` es obligatorio; el resto depende del tipo. Lo que ya existe en el aula lleva
    su ``eid`` y su ``item_id``; lo que se crea en esta pasada solo su ``idnumber`` (y el
    ``padre`` por idnumber): quien ejecuta resuelve idnumber -> eid tras crear.

    * ``crear_categoria``: ``idnumber``, ``nombre``, ``padre`` (idnumber) y ``padre_eid`` (si el
      padre ya existe; el curso para ``TZ_TIZA``), ``peso``, ``visualizacion``.
    * ``crear_calculado``: ídem con ``maximo`` y sin visualización.
    * ``colocar``: ``cmid``, ``ruta``, ``eid``/``item_id`` de la actividad, ``padre``/``padre_eid``
      de la categoría, ``idnumber`` (el que lleva la actividad: ``TZ_A<cmid>`` o el suyo) y
      ``poner_idnumber`` (``True``: el aula no tenía ninguno y hay que escribirlo).
    * ``mover_manual``: ``eid``/``item_id`` del elemento y ``padre``/``padre_eid`` de destino.
    * ``fijar_peso``: ``eid`` (o ``idnumber`` si es nuevo) y ``peso``.
    * ``fijar_maximo``: ``item_id`` (o ``idnumber``) y ``maximo``.
    * ``fijar_formula``: ``item_id`` (o ``idnumber``) y ``formula`` en la notación interna
      (``publicar.fijar_formula`` la traduce al idioma del aula).
    * ``fijar_total_curso``: ``eid``/``item_id`` del curso y ``formula`` (``None``: la
      visualización en porcentaje y vaciar la fórmula que hubiera, la del tope quitado).
    * ``bloquear_ajeno`` y ``bloquear_cerrada``: solo ``item_id`` del total
      (nunca un ``eid``: bloquear un ``cg<id>`` bloquea en cascada) e ``idnumber``.
    * ``borrar``: ``eid`` e ``idnumber``.
    """

    tipo: str
    idnumber: str | None = None
    eid: str | None = None
    item_id: int | None = None
    padre: str | None = None
    padre_eid: str | None = None
    peso: float | None = None
    maximo: float | None = None
    nombre: str | None = None
    visualizacion: str | None = None
    cmid: int | None = None
    ruta: str | None = None
    formula: str | None = None
    poner_idnumber: bool = False


@dataclass(frozen=True)
class Reconciliacion:
    """El resultado de la primera pasada.

    ``avisos`` son pares ``(codigo, ruta_o_idnumber)``; ``TOTAL_AJENO_BLOQUEADO`` lleva el
    ``eid`` de la categoría ajena (puede no tener número de ID). ``a_mano`` son las claves
    (idnumber o ``CURSO``) cuyo estado en el aula difería de su huella: hay que pasárselas a
    ``pasada2`` para que no confunda con un cambio del docente lo que haga la propia primera pasada.
    ``por_cerrar`` son las evaluaciones ``cerrada: true`` que aún no están bloqueadas: se montan
    como las abiertas y ``pasada2`` las ajusta y las bloquea al final. ``sin_colocar`` son las rutas de las
    actividades que están en el aula pero esta pasada no coloca (evaluación cerrada o cambiadas
    a mano).
    """

    operaciones: tuple[Operacion, ...]
    avisos: tuple[tuple[str, str], ...]
    anterior: bool
    a_mano: frozenset[str] = frozenset()
    por_cerrar: frozenset[str] = frozenset()
    sin_colocar: frozenset[str] = frozenset()

    @property
    def hay_trabajo(self) -> bool:
        """Hay algo que ejecutar: operaciones de la primera pasada o evaluaciones por bloquear."""
        return bool(self.operaciones) or bool(self.por_cerrar)


# --------------------------------------------------------------------------- #
# El aula indexada, la comparación de fórmulas y las huellas
# --------------------------------------------------------------------------- #


class _Indice:
    def __init__(self, aula: CalificadorAula) -> None:
        self.por_eid = {n.eid: n for n in aula.nodos}
        self.por_id: dict[str, NodoAula] = {}
        self.por_cmid: dict[int, NodoAula] = {}
        self.hijos: dict[str, list[NodoAula]] = {}
        self.curso: NodoAula | None = None
        for n in aula.nodos:
            if n.idnumber:
                self.por_id.setdefault(n.idnumber, n)
            if n.clase == "actividad" and n.cmid is not None:
                self.por_cmid.setdefault(n.cmid, n)
            if n.clase == "curso" and self.curso is None:
                self.curso = n
            if n.padre_eid is not None:
                self.hijos.setdefault(n.padre_eid, []).append(n)

    def padre(self, nodo: NodoAula) -> NodoAula | None:
        return self.por_eid.get(nodo.padre_eid) if nodo.padre_eid else None


def hay_anterior(aula: CalificadorAula) -> bool:
    """Hay un calificador anterior si existe algún nodo sin ``TZ_`` que no sea el curso.

    No cuentan las actividades sueltas: las que cuelgan directamente del curso ni las que
    ya están dentro de una categoría de tiza (aunque tengan un número de ID propio).
    """
    indice = _Indice(aula)
    for n in aula.nodos:
        if n.clase == "curso" or n.idnumber.startswith(_PREFIJO):
            continue
        if n.clase == "actividad":
            padre = indice.padre(n)
            if padre is None or padre.clase == "curso" or padre.idnumber.startswith(_PREFIJO):
                continue
        return True
    return False


def _normalizar(formula: str | None, decimal: str) -> str:
    """La fórmula sin «=», espacios ni mayúsculas, con «.» decimal y «,» entre argumentos.

    Lo que hay dentro de ``[[...]]`` (el número de ID) se deja tal cual.
    """
    texto = (formula or "").strip()
    texto = texto[1:] if texto.startswith("=") else texto
    salida = []
    for parte in re.split(r"(\[\[.*?\]\])", texto):
        if parte.startswith("[["):
            salida.append(parte)
            continue
        parte = "".join(parte.split()).lower()
        if decimal == ",":
            parte = parte.replace(",", ".")
        salida.append(parte.replace(";", ","))
    return "".join(salida)


def _texto_peso(nodo: NodoAula) -> str:
    if nodo.peso is None or not nodo.sobrescrito:
        return "-"
    return f"{round(nodo.peso, 2):.2f}"


def _sha(partes: list[str]) -> str:
    return hashlib.sha256(json.dumps(partes, ensure_ascii=False).encode("utf-8")).hexdigest()


def _huella(nodo: NodoAula, indice: _Indice, decimal: str) -> str:
    padre = indice.padre(nodo)
    nombre = "" if nodo.clase == "actividad" else nodo.nombre
    return _sha(
        [
            nodo.clase,
            padre.idnumber if padre else "",
            _texto_peso(nodo),
            _normalizar(nodo.formula, decimal),
            nombre,
        ]
    )


def huella_de_nodo(nodo: NodoAula, aula: CalificadorAula) -> str:
    """El sha256 de (clase, padre, peso, fórmula, nombre) de un nodo tal como está en el aula.

    El padre es su ``idnumber``; el peso, solo si está sobrescrito (si no, es un cálculo de
    Moodle que cambia con los demás); y el nombre no cuenta en una actividad (el docente la
    renombra y tiza lo publica).
    """
    return _huella(nodo, _Indice(aula), aula.decimal)


def huellas_de(aula: CalificadorAula, cmids: dict[str, int]) -> dict[str, str]:
    """Las huellas que hay que guardar tras montar: una por nodo ``TZ_`` y por actividad colocada.

    Clave: el ``idnumber`` (la de las actividades con número de ID propio también). Más
    ``CURSO``: la huella de la fórmula del total del curso. Se calculan sobre el aula **releída
    tras la segunda pasada**: lo que Moodle haya dejado, no lo que se pidió. Un número de ID que
    no sea una clave segura (``estado.clave_de_huella_valida``) no deja huella: se trata como
    un nodo sin huella.
    """
    indice = _Indice(aula)
    colocadas = set(cmids.values())
    resultado: dict[str, str] = {}
    for n in aula.nodos:
        if n.clase == "curso":
            resultado[CURSO] = _sha(["curso", _normalizar(n.formula, aula.decimal)])
        elif (
            n.idnumber
            and estado.clave_de_huella_valida(n.idnumber)
            and (
                n.idnumber.startswith(_PREFIJO) or (n.clase == "actividad" and n.cmid in colocadas)
            )
        ):
            resultado[n.idnumber] = _huella(n, indice, aula.decimal)
    return resultado


def _cerca(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= TOLERANCIA_PESOS


def _peso_correcto(nodo: NodoAula, deseado: float) -> bool:
    return nodo.sobrescrito and _cerca(nodo.peso, deseado)


# --------------------------------------------------------------------------- #
# El planificador
# --------------------------------------------------------------------------- #


class _Plan:
    def __init__(
        self,
        deseado: Deseado,
        aula: CalificadorAula,
        huellas: dict[str, str],
        cmids: dict[str, int],
        a_mano: frozenset[str] | None,
        solo_ajustes: bool,
        por_cerrar: frozenset[str] | None = None,
    ) -> None:
        self.d = deseado
        self.aula = aula
        self.cmids = cmids
        self.solo_ajustes = solo_ajustes
        self.idx = _Indice(aula)
        self.dnodos = {n.idnumber: n for n in deseado.nodos}
        self.rutas = {ruta for ruta, _ in deseado.actividades}
        self.huellas = huellas
        if a_mano is None:
            actuales = huellas_de(aula, cmids)
            a_mano = frozenset(k for k, h in actuales.items() if k in huellas and huellas[k] != h)
        self.a_mano = a_mano
        evaluaciones_cerradas = {
            n.idnumber for n in aula.nodos if _EVALUACION.fullmatch(n.idnumber) and n.bloqueado
        }
        self.bloqueadas_en_aula = evaluaciones_cerradas
        if por_cerrar is None:  # primera pasada: las cerradas del esquema aún sin bloquear
            por_cerrar = frozenset(c for c in deseado.cerradas if c not in evaluaciones_cerradas)
        self.por_cerrar = por_cerrar
        self.cerradas = set(evaluaciones_cerradas)  # solo las bloqueadas en el aula son intocables
        self.sin_colocar: set[str] = set()
        self.en_cerrada: set[str] = set()  # sin colocar porque su sitio cae en una cerrada
        self.casillas_en_cerrada: set[str] = set()  # casillas nuevas con sitio en una cerrada
        self.omitidos = self._omitidos()
        self.pesos = self._pesos_sin_omitidos()
        self.avisos: dict[tuple[str, str], None] = {}
        self.ajeno: list[Operacion] = []
        self.alta: list[Operacion] = []
        self.peso: list[Operacion] = []
        self.maximo: list[Operacion] = []
        self.formula: list[Operacion] = []
        self.cierre: list[Operacion] = []
        self.borrar: list[Operacion] = []
        self._ajenas_bloqueadas: set[str] = set()
        self._salen: set[str] = set()  # eids que dejan su sitio en esta pasada

    # -- utilidades --------------------------------------------------------

    def _aviso(self, codigo: str, clave: str) -> None:
        self.avisos.setdefault((codigo, clave), None)

    def _actividad_aula(self, ruta: str) -> NodoAula | None:
        cmid = self.cmids.get(ruta)
        return self.idx.por_cmid.get(cmid) if cmid is not None else None

    def _id_efectivo(self, ruta: str) -> str:
        """El número de ID con el que se referencia una actividad en las fórmulas."""
        act = self._actividad_aula(ruta)
        assert act is not None
        return act.idnumber or f"{_PREFIJO}A{act.cmid}"

    def _referencia(self, fuente: str) -> str:
        return self._id_efectivo(fuente) if fuente in self.rutas else fuente

    def _omitidos(self) -> set[str]:
        """Las actividades que no se colocan y todo lo que cuelga de ellas.

        Son las pendientes (sin cmid o sin elemento en el aula) y las nuevas en una evaluación
        cerrada: sin número de ID ni sitio, nada puede referenciarlas.
        """
        pendientes = {r for r in sorted(self.rutas) if self._actividad_aula(r) is None}
        self.en_cerrada = self._nuevas_en_cerrada(pendientes)
        self.sin_colocar |= self.en_cerrada
        pendientes |= self.en_cerrada
        self.casillas_en_cerrada = self._casillas_nuevas_en_cerrada()
        pendientes |= self.casillas_en_cerrada
        omitidos = set(pendientes)
        for n in self.d.nodos:
            if n.clase == "copia" and n.formula_de in pendientes:
                omitidos.add(n.idnumber)
        for n in self.d.nodos:
            if n.clase == "indicador" and n.formula_de in omitidos:
                omitidos.add(n.idnumber)
        return omitidos

    def _pesos_sin_omitidos(self) -> dict[str, float]:
        """Los pesos de las hermanas de lo omitido, repartidos entre las que sí se colocan.

        Lo omitido no está en el aula y Moodle reescala a 100 las demás: contar su peso
        (``deseado`` no lo sabe) haría que cada montaje las volviera a fijar.
        """
        grupos: dict[str, list[Nodo]] = {}
        for n in self.d.nodos:
            if n.clase in ("actividad", "manual", "copia") and n.peso is not None and n.padre:
                grupos.setdefault(n.padre, []).append(n)
        resultado: dict[str, float] = {}
        for hermanas in grupos.values():
            if not any(h.idnumber in self.omitidos for h in hermanas):
                continue
            quedan = [h for h in hermanas if h.idnumber not in self.omitidos]
            pesos = normalizar_pesos([h.peso or 0.0 for h in quedan])
            resultado.update((h.idnumber, p) for h, p in zip(quedan, pesos, strict=True))
        return resultado

    def _peso(self, nodo: Nodo) -> float | None:
        return self.pesos.get(nodo.idnumber, nodo.peso)

    def _nuevas_en_cerrada(self, pendientes: set[str]) -> set[str]:
        """Las actividades del aula aún sin colocar cuyo sitio (real o copia) cae en una cerrada."""
        resultado: set[str] = set()
        for ruta, padre in self.d.actividades:
            act = self._actividad_aula(ruta)
            if ruta in pendientes or act is None:
                continue
            destino = self.idx.por_id.get(padre)
            if act.idnumber and destino is not None and act.padre_eid == destino.eid:
                continue  # ya colocada: lo de la cerrada ya estaba
            sitios = [padre, *(n.padre for n in self.d.nodos if n.formula_de == ruta)]
            if any(self._cerrado_deseado(sitio) for sitio in sitios):
                resultado.add(ruta)
        return resultado

    def _casillas_nuevas_en_cerrada(self) -> set[str]:
        """Las casillas manuales aún no creadas cuyo sitio (real o copia) cae en una cerrada."""
        resultado: set[str] = set()
        for nodo in self.d.nodos:
            if nodo.clase != "manual" or nodo.idnumber in self.idx.por_id:
                continue
            sitios = [nodo.padre, *(n.padre for n in self.d.nodos if n.formula_de == nodo.idnumber)]
            if any(self._cerrado_deseado(sitio) for sitio in sitios):
                resultado.add(nodo.idnumber)
        return resultado

    def _cerrado_deseado(self, idnumber: str | None) -> bool:
        while idnumber is not None:
            if idnumber in self.cerradas:
                return True
            nodo = self.dnodos.get(idnumber)
            idnumber = nodo.padre if nodo else None
        return False

    def _cerrado_aula(self, nodo: NodoAula | None) -> bool:
        while nodo is not None:
            if nodo.idnumber in self.cerradas:
                return True
            nodo = self.idx.padre(nodo)
        return False

    def _maximo_actividad(self, ruta: str) -> float:
        act = self._actividad_aula(ruta)
        return act.maximo if act is not None and act.maximo is not None else _MAXIMO_SIN_DATO

    def _maximo_casilla(self, idnumber: str) -> float:
        """El máximo de una casilla en el aula (el docente puede cambiarlo); 10 si aún no existe."""
        casilla = self.idx.por_id.get(idnumber)
        return (
            casilla.maximo if casilla is not None and casilla.maximo is not None else _MAXIMO_NOTA
        )

    def _maximo(self, nodo: Nodo) -> float:
        """El máximo que debe tener un calculado."""
        if nodo.clase in ("nota", "manual"):
            return _MAXIMO_NOTA
        if nodo.clase == "indicador":
            fuente = nodo.formula_de
            assert isinstance(fuente, str)
            if fuente in self.dnodos and fuente not in self.rutas:  # una copia o una casilla
                fuente = self.dnodos[fuente].formula_de or fuente  # type: ignore[assignment]
            if str(fuente).startswith(_PREFIJO_MANUAL):
                return self._maximo_casilla(str(fuente))
            return self._maximo_actividad(str(fuente))
        fuente = nodo.formula_de
        if isinstance(fuente, str) and fuente in self.rutas:
            return self._maximo_actividad(fuente)
        if isinstance(fuente, str) and fuente.startswith(_PREFIJO_MANUAL):
            return self._maximo_casilla(fuente)
        # TZ_KC_<id>: el máximo completo de TZ_E_<id>, que solo se conoce con las actividades dentro
        elemento = self.idx.por_id.get(f"{_PREFIJO}E_{nodo.idnumber[len(_PREFIJO + 'KC_') :]}")
        if elemento is not None and elemento.maximo is not None:
            return elemento.maximo
        return _MAXIMO_SIN_DATO

    def _formula(self, nodo: Nodo) -> str:
        fuente = nodo.formula_de
        if nodo.clase == "copia":
            assert isinstance(fuente, str)
            return formula_copia(self._referencia(fuente))
        if nodo.clase == "indicador":
            assert isinstance(fuente, str)
            return formula_indicador(self._referencia(fuente), self._maximo(nodo))
        assert isinstance(fuente, tuple)
        if nodo.idnumber == NOTA_FINAL and self.d.tope is not None:
            umbral, maximo, notas = self.d.tope
            return formula_tope(umbral, maximo, list(notas))
        return formula_nota(*fuente)

    # -- el recorrido ------------------------------------------------------

    def planificar(self) -> None:
        pendientes = [r for r in sorted(self.rutas) if self._actividad_aula(r) is None]
        for ruta in pendientes:
            self._aviso("ACTIVIDAD_PENDIENTE", ruta)
        for ruta in sorted(self.en_cerrada | self.casillas_en_cerrada):
            self._aviso("ACTIVIDAD_EN_EVALUACION_CERRADA", ruta)
        for n in self.aula.nodos:
            if n.idnumber in self.bloqueadas_en_aula and n.idnumber not in self.d.cerradas:
                self._aviso("EVALUACION_CERRADA_EN_EL_AULA", n.idnumber)
        for nodo in self.d.nodos:
            if nodo.idnumber in self.omitidos or self._cerrado_deseado(nodo.idnumber):
                continue
            if nodo.clase == "actividad":
                self._actividad(nodo)
            else:
                self._otro(nodo)
        self._dejan_de_contar()
        self._total_del_curso()
        self._sobrantes()
        self._cierres()

    def _actividad(self, nodo: Nodo) -> None:
        ruta = nodo.idnumber
        act = self._actividad_aula(ruta)
        assert act is not None
        destino = self.idx.por_id.get(nodo.padre) if nodo.padre else None
        en_su_sitio = destino is not None and act.padre_eid == destino.eid
        if self._cerrado_aula(act):
            if not en_su_sitio:
                self.sin_colocar.add(ruta)
            return
        clave = self._id_efectivo(ruta)
        if clave in self.a_mano:
            self._aviso("CAMBIADO_A_MANO", ruta)
            if not en_su_sitio:
                self.sin_colocar.add(ruta)
            return
        colocada = False
        if not self.solo_ajustes and (not en_su_sitio or not act.idnumber):
            if not en_su_sitio:
                self._bloquear_ajena(act)
                self._salen.add(act.eid)
            self.alta.append(
                Operacion(
                    "colocar",
                    idnumber=clave,
                    eid=act.eid,
                    item_id=act.item_id,
                    padre=nodo.padre,
                    padre_eid=destino.eid if destino else None,
                    cmid=act.cmid,
                    ruta=ruta,
                    poner_idnumber=not act.idnumber,
                )
            )
            colocada = True
        elif not en_su_sitio:
            return  # en la segunda pasada no se ajusta lo que no está donde debe
        peso = self._peso(nodo)
        if peso is not None and (colocada or not _peso_correcto(act, peso)):
            self.peso.append(
                Operacion("fijar_peso", idnumber=clave, eid=act.eid, item_id=act.item_id, peso=peso)
            )

    def _bloquear_ajena(self, act: NodoAula) -> None:
        actual = self.idx.padre(act)
        if (
            actual is not None
            and actual.clase == "categoria"
            and not actual.idnumber.startswith(_PREFIJO)
            and actual.tiene_notas
            and not actual.bloqueado
            and actual.eid not in self._ajenas_bloqueadas
        ):
            self._ajenas_bloqueadas.add(actual.eid)
            self.ajeno.append(
                Operacion(
                    "bloquear_ajeno",
                    idnumber=actual.idnumber or None,
                    item_id=actual.item_id,
                    nombre=actual.nombre,
                )
            )
            self._aviso("TOTAL_AJENO_BLOQUEADO", actual.eid)

    def _otro(self, nodo: Nodo) -> None:
        existente = self.idx.por_id.get(nodo.idnumber)
        calculado = nodo.clase not in _CLASES_CATEGORIA
        padre = self.idx.por_id.get(nodo.padre) if nodo.padre else self.idx.curso
        if existente is None:
            if self.solo_ajustes:
                return
            self._crear(nodo, calculado, padre)
            return
        if self._cerrado_aula(existente):
            return
        if nodo.idnumber in self.a_mano:
            self._aviso("CAMBIADO_A_MANO", nodo.idnumber)
            return
        movido = False
        if padre is None or existente.padre_eid != padre.eid:
            if self.solo_ajustes:
                return
            if calculado:
                self.alta.append(
                    Operacion(
                        "mover_manual",
                        idnumber=nodo.idnumber,
                        eid=existente.eid,
                        item_id=existente.item_id,
                        padre=nodo.padre,
                        padre_eid=padre.eid if padre else None,
                    )
                )
                self._salen.add(existente.eid)
                movido = True
            else:  # tiza no sabe mover categorías: se respeta donde estén y se avisa
                self._aviso("CAMBIADO_A_MANO", nodo.idnumber)
                return
        peso = self._peso(nodo)
        if peso is not None and (movido or not _peso_correcto(existente, peso)):
            self.peso.append(
                Operacion(
                    "fijar_peso",
                    idnumber=nodo.idnumber,
                    eid=existente.eid,
                    item_id=existente.item_id,
                    peso=peso,
                )
            )
        if not calculado or nodo.clase == "manual":
            return  # una casilla manual: tiza nunca toca su máximo ni le pone fórmula
        maximo = self._maximo(nodo)
        if not movido and not _cerca(existente.maximo, maximo):
            self.maximo.append(
                Operacion(
                    "fijar_maximo",
                    idnumber=nodo.idnumber,
                    eid=existente.eid,
                    item_id=existente.item_id,
                    maximo=maximo,
                )
            )
        formula = self._formula(nodo)
        if _normalizar(existente.formula, self.aula.decimal) != _normalizar(formula, "."):
            self.formula.append(
                Operacion(
                    "fijar_formula",
                    idnumber=nodo.idnumber,
                    eid=existente.eid,
                    item_id=existente.item_id,
                    formula=formula,
                )
            )

    def _crear(self, nodo: Nodo, calculado: bool, padre: NodoAula | None) -> None:
        peso = self._peso(nodo)
        if calculado:
            self.alta.append(
                Operacion(
                    "crear_calculado",
                    idnumber=nodo.idnumber,
                    nombre=nodo.nombre,
                    padre=nodo.padre,
                    padre_eid=padre.eid if padre else None,
                    peso=peso,
                    maximo=self._maximo(nodo),
                )
            )
        else:
            self.alta.append(
                Operacion(
                    "crear_categoria",
                    idnumber=nodo.idnumber,
                    nombre=nodo.nombre,
                    padre=nodo.padre,
                    padre_eid=padre.eid if padre else None,
                    peso=peso,
                    visualizacion=nodo.visualizacion,
                )
            )
        # Moodle reescala los pesos al añadir dentro: se fijan al final, con todo creado
        if peso is not None:
            self.peso.append(Operacion("fijar_peso", idnumber=nodo.idnumber, peso=peso))
        if calculado and nodo.clase != "manual":
            self.formula.append(
                Operacion("fijar_formula", idnumber=nodo.idnumber, formula=self._formula(nodo))
            )

    # -- lo que no está en el deseado -------------------------------------

    def _dejan_de_contar(self) -> None:
        """D2: una actividad real que ya no cuenta, dentro de lo de tiza, se queda con peso 0."""
        con_cmid = {self.cmids[r] for r in self.rutas if r in self.cmids}
        for n in self.aula.nodos:
            if n.clase != "actividad" or n.cmid in con_cmid:
                continue
            padre = self.idx.padre(n)
            if padre is None or not padre.idnumber.startswith(_PREFIJO) or self._cerrado_aula(n):
                continue
            clave = n.idnumber or f"{_PREFIJO}A{n.cmid}"
            if clave in self.a_mano:
                self._aviso("CAMBIADO_A_MANO", clave)
            elif not _peso_correcto(n, 0.0):
                self.peso.append(
                    Operacion("fijar_peso", idnumber=clave, eid=n.eid, item_id=n.item_id, peso=0.0)
                )

    def _total_del_curso(self) -> None:
        curso = self.idx.curso
        total = self.d.total_curso
        if total is None or curso is None or hay_anterior(self.aula):
            return
        if CURSO in self.a_mano:
            self._aviso("CAMBIADO_A_MANO", CURSO)
            return
        actual = _normalizar(curso.formula, self.aula.decimal)
        if total == NOTA_FINAL:
            esperada: str | None = formula_copia(NOTA_FINAL)
            hace_falta = actual != _normalizar(esperada, ".")
        else:  # «porcentaje»: solo la visualización, que el aula no enseña; se hace una vez
            esperada = None
            hace_falta = bool(actual) or (CURSO not in self.huellas and not self.solo_ajustes)
        if hace_falta:
            self.formula.append(
                Operacion(
                    "fijar_total_curso",
                    idnumber=CURSO,
                    eid=curso.eid,
                    item_id=curso.item_id,
                    formula=esperada,
                )
            )

    def _cierres(self) -> None:
        """Bloquea, al final de la segunda pasada, las cerradas del esquema aún sin bloquear.

        Un total bloqueado ya no admite los ajustes de pesos y fórmulas que esa pasada repite.
        """
        if not self.solo_ajustes:
            return
        for idnumber in sorted(self.por_cerrar):
            nodo = self.idx.por_id.get(idnumber)
            if nodo is not None and not nodo.bloqueado:
                self.cierre.append(
                    Operacion("bloquear_cerrada", idnumber=idnumber, item_id=nodo.item_id)
                )

    def _profundidad(self, nodo: NodoAula) -> int:
        nivel = 0
        while True:
            padre = self.idx.padre(nodo)
            if padre is None:
                return nivel
            nivel += 1
            nodo = padre

    def _de_contador(self, nodo: NodoAula) -> bool:
        padre = self.idx.padre(nodo)
        return padre is not None and padre.idnumber.startswith(f"{_PREFIJO}K_")

    def _sobrantes(self) -> None:
        """Los nodos de tiza que ya no están en el esquema.

        Se borran si no tienen notas (solo en la primera pasada); los que se quedan (con notas
        o con algo dentro que se queda) pasan a pesar 0, como una actividad que deja de contar.
        """
        candidatos = [
            n
            for n in self.aula.nodos
            if n.idnumber.startswith(_PREFIJO)
            and n.clase not in ("actividad", "curso")
            and n.idnumber not in self.dnodos
            and not self._cerrado_aula(n)
        ]
        # lo que cuelga de un contador es calculado y no guarda nada del docente: se borra siempre
        con_notas = {n.eid for n in candidatos if n.tiene_notas and not self._de_contador(n)}
        for n in candidatos:
            if n.eid in con_notas and not any(
                h.eid in con_notas for h in self.idx.hijos.get(n.eid, [])
            ):
                self._aviso("ELEMENTO_CON_NOTAS_QUITADO", n.idnumber)
        borrados: set[str] = set()
        for n in sorted(candidatos, key=self._profundidad, reverse=True):
            if n.eid in con_notas:
                continue
            if n.idnumber in self.a_mano:
                self._aviso("CAMBIADO_A_MANO", n.idnumber)
                continue
            # no se borra una categoría con algo dentro que se queda (Moodle lo subiría de nivel)
            if any(
                h.eid not in borrados and h.eid not in self._salen
                for h in self.idx.hijos.get(n.eid, [])
            ):
                continue
            borrados.add(n.eid)
            if not self.solo_ajustes:
                self.borrar.append(
                    Operacion("borrar", idnumber=n.idnumber, eid=n.eid, item_id=n.item_id)
                )
        for n in candidatos:
            if n.eid in borrados or n.idnumber in self.a_mano:
                continue
            padre = self.idx.padre(n)
            if padre is not None and padre.idnumber.startswith(f"{_PREFIJO}K_"):
                continue  # los hijos de un contador no llevan peso sobrescrito
            if not _peso_correcto(n, 0.0):
                self.peso.append(
                    Operacion(
                        "fijar_peso", idnumber=n.idnumber, eid=n.eid, item_id=n.item_id, peso=0.0
                    )
                )

    # -- el resultado ------------------------------------------------------

    def ajustes(self) -> tuple[Operacion, ...]:
        return tuple(self.peso + self.maximo + self.formula + self.cierre)

    def todo(self) -> tuple[Operacion, ...]:
        return tuple(
            self.ajeno
            + self.alta
            + self.peso
            + self.maximo
            + self.formula
            + self.cierre
            + self.borrar
        )


def reconciliar(
    deseado: Deseado,
    aula: CalificadorAula,
    huellas: dict[str, str],
    cmids: dict[str, int],
) -> Reconciliacion:
    """La primera pasada: qué operaciones llevan el aula a lo deseado sin pisar notas ni a mano.

    ``huellas`` es lo que devolvió ``estado.cargar_huellas`` (vacío si tiza no recuerda nada);
    ``cmids`` lleva, por ruta, el cmid de cada actividad en el aula (las que falten son
    pendientes). Orden: todos los ``bloquear_ajeno``; crear y colocar (padres antes que hijos);
    ``fijar_peso`` y ``fijar_maximo``; ``fijar_formula`` y ``fijar_total_curso``; y al final
    ``bloquear_cerrada`` y ``borrar`` (los hijos antes que sus padres).
    """
    plan = _Plan(deseado, aula, huellas, cmids, None, False)
    plan.planificar()
    return Reconciliacion(
        operaciones=plan.todo(),
        avisos=tuple(plan.avisos),
        anterior=hay_anterior(aula),
        a_mano=frozenset(plan.a_mano),
        por_cerrar=plan.por_cerrar,
        sin_colocar=frozenset(plan.sin_colocar),
    )


def pasada2(
    deseado: Deseado,
    aula: CalificadorAula,
    huellas: dict[str, str],
    cmids: dict[str, int],
    a_mano: frozenset[str] | None = None,
    por_cerrar: frozenset[str] = frozenset(),
) -> tuple[Operacion, ...]:
    """La segunda pasada, sobre el aula releída tras ejecutar la primera.

    Solo ``fijar_peso``, ``fijar_maximo``, ``fijar_formula`` y ``fijar_total_curso`` que sigan
    haciendo falta, y al final el ``bloquear_cerrada`` de las evaluaciones ``cerrada: true`` aún
    sin bloquear. Pásale ``a_mano=reconciliacion.a_mano`` (sin él, lo que la
    primera pasada cambió en el aula se compara con las huellas de antes y parece cosa del
    docente) y ``por_cerrar=reconciliacion.por_cerrar``.
    """
    plan = _Plan(deseado, aula, huellas, cmids, a_mano, True, por_cerrar)
    plan.planificar()
    return plan.ajustes()
