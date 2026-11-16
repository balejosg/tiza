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
  (``ACTIVIDAD_EN_EVALUACION_CERRADA``); una que el esquema pasa a otra evaluación y sigue en la
  cerrada se queda donde está y avisa (``SALE_DE_EVALUACION_CERRADA``). Una evaluación
  ``cerrada: true`` que aún no está
  bloqueada (no existe, o a medio montar) se trata como abierta —se crea, se coloca y se ajusta,
  en las dos pasadas— y se bloquea al final de la segunda («cerrar es marcar y volver a montar»):
  si el montaje falla a medias, la ejecución siguiente la completa y después la bloquea;
* lo que el docente cambió a mano en lo de tiza (D3): si el aula difiere de la huella, ese nodo no
  se toca (ni su peso ni su fórmula); sus hijos sí se gestionan;
* las notas: un nodo de tiza que ya no está en el esquema pero tiene notas se queda, y una
  actividad real que deja de contar nunca se borra (es del docente): se queda con peso 0 (D2);
* los totales ajenos con notas se bloquean antes de sacar de ellos una actividad;
* una categoría con una regla de agregación distinta de la Natural se cambia en el aula y se
  avisa con ``REGLA_CAMBIADA``; sus hijos no llevan peso sobrescrito (D15).

El montaje va en dos pasadas (Moodle reescala pesos al añadir dentro y una fórmula entre
categorías recién creadas puede fallar la primera vez): ``reconciliar`` da la primera y, tras
ejecutarla y releer el aula, ``pasada2`` da solo los ajustes que sigan haciendo falta (quien
ejecuta la repite, con tope, mientras Moodle siga reescalando pesos).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tiza import estado
from tiza.calificacion.deseado import NOTA_FINAL, Deseado, Nodo, normalizar_pesos
from tiza.calificacion.esquema import TOLERANCIA_PESOS
from tiza.calificacion.formulas import (
    formula_copia,
    formula_resultado,
    formula_tope,
)

if TYPE_CHECKING:  # solo para los tipos: importar ``publicar`` cargaría python-moodle
    from tiza.publicar import CalificadorAula, NodoAula

__all__ = [
    "AVISOS",
    "CLASES_OCULTAS",
    "CURSO",
    "CambioAMano",
    "Operacion",
    "Reconciliacion",
    "Retirada",
    "TIPOS",
    "aula_tras_retirada",
    "hay_anterior",
    "huella_de_nodo",
    "huellas_de",
    "huellas_deseadas",
    "es_calculado_de_tiza",
    "es_calificador_antiguo",
    "pasada2",
    "reconciliar",
    "retirada_antiguo",
]

# El orden de la lista es el orden de ejecución por tipos (``crear_*``, ``colocar`` y
# ``mover_manual`` van mezclados, padres antes que hijos).
TIPOS = (
    "bloquear_ajeno",
    "crear_categoria",
    "crear_calculado",
    "colocar",
    "mover_manual",
    "marcar_resultado",
    "fijar_idnumber_resultado",
    "fijar_agregacion",
    "fijar_coeficiente",
    "fijar_peso",
    "fijar_maximo",
    "fijar_formula",
    "fijar_total_curso",
    "ocultar",
    "bloquear_cerrada",
    "borrar",
)
AVISOS = (
    "ACTIVIDAD_EN_EVALUACION_CERRADA",
    "ACTIVIDAD_PENDIENTE",
    "CALCULADOS_OCULTADOS",
    "CAMBIADO_A_MANO",
    "EVALUACION_CERRADA_EN_EL_AULA",
    "ELEMENTO_CON_NOTAS_QUITADO",
    "REGLA_CAMBIADA",
    "SALE_DE_EVALUACION_CERRADA",
    "RESULTADO_CON_NOTAS_QUITADO",
    "RESULTADO_RECREADO",
    "TOTAL_AJENO_BLOQUEADO",
)
CURSO = "TZ_CURSO"  # la clave de la huella del total del curso en ``calificador.json``
# R1-D1: las clases calculadas que crea tiza y que el alumnado no ve. No se ocultan las
# actividades, las casillas manuales (el instrumento) ni los elementos de resultado.
CLASES_OCULTAS = ("copia", "nota", "resultado_calc")
_PREFIJO = "TZ_"
_PREFIJO_RESULTADO = "TZ_O_"
_PREFIJO_CALCULADO_RESULTADO = "TZ_R_"
_EVALUACION = re.compile(r"TZ_V_[0-9]+")
_CLASES_CATEGORIA = ("contenedor", "categoria")
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
    * ``crear_calculado``: ídem con ``maximo``, sin visualización y con ``oculto`` (R1).
    * ``colocar``: ``cmid``, ``ruta``, ``eid``/``item_id`` de la actividad, ``padre``/``padre_eid``
      de la categoría, ``idnumber`` (el que lleva la actividad: ``TZ_A<cmid>`` o el suyo) y
      ``poner_idnumber`` (``True``: el aula no tenía ninguno y hay que escribirlo).
    * ``mover_manual``: ``eid``/``item_id`` del elemento y ``padre``/``padre_eid`` de destino.
    * ``marcar_resultado``: ``cmid`` de la tarea y ``resultado`` (id del resultado de Moodle);
      Moodle vuelve a crear su elemento de resultado. La segunda pasada lo coloca y le pone su
      número de ID.
    * ``fijar_idnumber_resultado``: ``item_id`` del elemento de resultado y ``idnumber``.
    * ``fijar_agregacion``: ``eid`` (o ``idnumber`` si es nuevo) y ``agregacion`` de Moodle.
    * ``fijar_coeficiente``: ``eid`` (o ``idnumber`` si es nuevo) y ``coeficiente`` de la media
      ponderada (4 decimales). ``fijar_peso`` sigue para la ponderación de siempre.
    * ``fijar_peso``: ``eid`` (o ``idnumber`` si es nuevo) y ``peso``.
    * ``fijar_maximo``: ``item_id`` (o ``idnumber``) y ``maximo``.
    * ``fijar_formula``: ``item_id`` (o ``idnumber``) y ``formula`` en la notación interna
      (``publicar.fijar_formula`` la traduce al idioma del aula).
    * ``fijar_total_curso``: ``eid``/``item_id`` del curso y ``formula`` (``None``: la
      visualización en porcentaje y vaciar la fórmula que hubiera, la del tope quitado).
    * ``bloquear_ajeno`` y ``bloquear_cerrada``: solo ``item_id`` del total
      (nunca un ``eid``: bloquear un ``cg<id>`` bloquea en cascada) e ``idnumber``.
    * ``ocultar``: ``eid``, ``item_id`` e ``idnumber`` de un calculado de tiza que el alumnado
      sigue viendo (R1). No toca categorías, actividades ni casillas manuales.
    * ``borrar``: ``eid`` e ``idnumber``.
    """

    tipo: str
    idnumber: str | None = None
    eid: str | None = None
    item_id: int | None = None
    padre: str | None = None
    padre_eid: str | None = None
    peso: float | None = None
    coeficiente: float | None = None
    maximo: float | None = None
    nombre: str | None = None
    visualizacion: str | None = None
    cmid: int | None = None
    ruta: str | None = None
    formula: str | None = None
    resultado: int | None = None
    agregacion: int | None = None
    poner_idnumber: bool = False
    oculto: bool = False  # ``crear_calculado``: el alta ya lo oculta al alumnado (R1)


@dataclass(frozen=True)
class CambioAMano:
    """Un nodo de lo que montó tiza que el docente cambió en el aula.

    ``tipo`` es ``peso``, ``padre``, ``formula``, ``nombre`` u ``otro``. En ``peso``, ``antes``
    es el valor del aula y ``despues`` el que pondría tiza (coeficiente o peso, sin porcentaje).
    En ``padre``, ``padre_antes`` es el número de ID del padre en el aula y ``padre_despues`` el
    del YAML. ``nombre`` es el nombre de la carpeta (nunca el del aula).
    """

    clave: str
    tipo: str
    nombre: str
    antes: float | None = None
    despues: float | None = None
    padre_antes: str | None = None
    padre_despues: str | None = None


@dataclass(frozen=True)
class Reconciliacion:
    """El resultado de la primera pasada.

    ``avisos`` son pares ``(codigo, ruta_o_idnumber)``; ``TOTAL_AJENO_BLOQUEADO`` lleva el
    ``eid`` de la categoría ajena (puede no tener número de ID). ``a_mano`` son las claves
    (idnumber o ``CURSO``) cuyo estado en el aula difería de su huella: hay que pasárselas a
    ``pasada2`` para que no confunda con un cambio del docente lo que haga la propia primera pasada.
    ``por_cerrar`` son las evaluaciones ``cerrada: true``: ``pasada2`` bloquea su total y las
    categorías de dentro que sigan abiertas. ``sin_colocar`` son las rutas de las
    actividades que están en el aula pero esta pasada no coloca (evaluación cerrada o cambiadas
    a mano).
    """

    operaciones: tuple[Operacion, ...]
    avisos: tuple[tuple[str, str], ...]
    anterior: bool
    a_mano: frozenset[str] = frozenset()
    por_cerrar: frozenset[str] = frozenset()
    sin_colocar: frozenset[str] = frozenset()
    cerradas: frozenset[str] = frozenset()
    conservados: frozenset[str] = frozenset()
    huerfanos: frozenset[str] = frozenset()
    cambios_a_mano: tuple[CambioAMano, ...] = ()

    @property
    def hay_trabajo(self) -> bool:
        """Hay algo que ejecutar: operaciones, evaluaciones por bloquear o categorías que congelar."""
        return bool(self.operaciones) or bool(self.por_cerrar) or bool(self.cerradas)


@dataclass(frozen=True)
class Retirada:
    """Lo que hay que quitar del árbol de la generación anterior para montar el nuevo.

    ``operaciones`` son todas ``borrar`` (con ``eid``, ``idnumber`` e ``item_id``), en el orden
    seguro: lo que no delata primero y los delatores al final, para que un corte a medias siga
    viéndose antiguo. ``conservadas`` son las casillas manuales con notas (lo que tecleó el
    docente) y ``cerradas`` las evaluaciones ``TZ_V_<n>`` bloqueadas que hay que avisar que se
    recalculan. Las actividades y los resultados también se conservan, pero no se listan: no
    hay nada que hacer con ellos salvo dejarlos subir al curso.
    """

    operaciones: tuple[Operacion, ...]
    conservadas: tuple[NodoAula, ...]
    cerradas: tuple[NodoAula, ...]


# --------------------------------------------------------------------------- #
# El aula indexada, la comparación de fórmulas y las huellas
# --------------------------------------------------------------------------- #


class _Indice:
    def __init__(self, aula: CalificadorAula) -> None:
        self.por_eid = {n.eid: n for n in aula.nodos}
        self.por_id: dict[str, NodoAula] = {}
        self.por_cmid: dict[int, NodoAula] = {}
        # Un cmid puede tener varios elementos: la actividad real y cada elemento de resultado
        # que Moodle crea al marcarla (también sale como ``actividad`` y con el mismo cmid).
        self.por_cmid_todos: dict[int, list[NodoAula]] = {}
        self.hijos: dict[str, list[NodoAula]] = {}
        self.curso: NodoAula | None = None
        for n in aula.nodos:
            if n.idnumber:
                self.por_id.setdefault(n.idnumber, n)
            if n.clase == "actividad" and n.cmid is not None:
                self.por_cmid_todos.setdefault(n.cmid, []).append(n)
                self.por_cmid.setdefault(n.cmid, n)
            if n.clase == "curso" and self.curso is None:
                self.curso = n
            if n.padre_eid is not None:
                self.hijos.setdefault(n.padre_eid, []).append(n)

    def padre(self, nodo: NodoAula) -> NodoAula | None:
        return self.por_eid.get(nodo.padre_eid) if nodo.padre_eid else None


def _delata(idnumber: str) -> bool:
    """¿Este número de ID hace que el árbol se vea de la generación anterior?

    Los delatores se borran los últimos: si la retirada se corta a medias, la pasada
    siguiente sigue reconociendo el árbol antiguo y vuelve a retirar en vez de montar el
    nuevo encima de los restos.
    """
    return idnumber in ("TZ_NOTAS", "TZ_K_TIZA") or idnumber.startswith(
        ("TZ_AG_", "TZ_RP_", "TZ_F_")
    )


def es_calificador_antiguo(aula: CalificadorAula) -> bool:
    """¿El aula tiene un árbol de la generación anterior, que hay que borrar a mano?

    Lo delatan los nodos de la 0.43 (``TZ_NOTAS``, ``TZ_K_TIZA``, ``TZ_AG_*``, ``TZ_RP_*``,
    ``TZ_F_*``) o una copia ``TZ_C_`` dentro de una vista ``TZ_V_*``/``TZ_E_*`` que contiene
    actividades. La vista del curso nueva tiene copias ``TZ_C_`` pero **no** actividades dentro
    (las actividades reales están en la vista primaria); la copia de una actividad en la vista
    primaria es ``TZ_CR_``, así que no se confunde.
    """
    indice = _Indice(aula)
    for nodo in aula.nodos:
        if not nodo.idnumber.startswith(_PREFIJO):
            continue
        if _delata(nodo.idnumber):
            return True
        if not nodo.idnumber.startswith("TZ_C_"):
            continue
        # La copia del curso nueva referencia el total del trimestre (TZ_V_…); la antigua
        # copiaba una actividad. Solo la antigua delata el árbol anterior.
        referencias = re.findall(r"\[\[(.*?)\]\]", nodo.formula or "")
        if referencias and all(
            referencia.startswith(("TZ_V_", "TZ_E_")) for referencia in referencias
        ):
            continue
        padre = indice.padre(nodo)
        if padre is None or not padre.idnumber.startswith(("TZ_V_", "TZ_E_")):
            continue
        pendientes = [padre]
        while pendientes:
            actual = pendientes.pop()
            if actual.clase == "actividad":
                return True
            pendientes.extend(indice.hijos.get(actual.eid, []))
    return False


def final_montada(aula: CalificadorAula) -> str | None:
    """De qué sale la nota final de lo que tiza tiene montado: ``elementos``, ``evaluaciones`` o ``None``.

    La señal es lo que cuelga directamente de ``TZ_FINAL``: sus hijos ``TZ_E_*`` (los elementos o
    RA) o ``TZ_V_*`` (las evaluaciones). ``deseado`` pone en ``TZ_FINAL`` una sola de las dos
    vistas (la otra va a ``TZ_VISTA``), así que, si solo hay una clase, es inequívoca. Sin
    ``TZ_FINAL``, sin hijos de tiza o con las dos clases mezcladas (un montaje a medias o
    tocado a mano) no se decide: ``None``. Lo que no es de tiza (sin ``TZ_``) no cuenta.
    ``organizacion`` no se deduce: no cambia el árbol (solo ``final.de`` lo hace).
    """
    indice = _Indice(aula)
    final = indice.por_id.get("TZ_FINAL")
    if final is None:
        return None
    clases = {
        "elementos" if hijo.idnumber.startswith("TZ_E_") else "evaluaciones"
        for hijo in indice.hijos.get(final.eid, [])
        if hijo.idnumber.startswith(("TZ_E_", "TZ_V_"))
    }
    return next(iter(clases)) if len(clases) == 1 else None


def _se_borra(nodo: NodoAula) -> bool:
    """La regla de la retirada, por clase de nodo (nunca por ``tiene_notas`` a secas)."""
    if not nodo.idnumber.startswith(_PREFIJO) or nodo.clase == "curso":
        return False
    if nodo.clase == "actividad" or nodo.idnumber.startswith(_PREFIJO_RESULTADO):
        return False
    if nodo.clase == "manual":
        return not nodo.tiene_notas
    return True  # categorías y calculados (tengan o no notas)


def _profundidad(nodo: NodoAula, indice: _Indice) -> int:
    nivel = 0
    padre = indice.padre(nodo)
    while padre is not None:
        nivel += 1
        nodo = padre
        padre = indice.padre(nodo)
    return nivel


def _en_orden_de_retirada(nodos: list[NodoAula], indice: _Indice) -> list[NodoAula]:
    """No delatores primero y delatores al final; dentro de cada tanda, elementos y luego
    categorías de la más profunda a la más externa (estable dentro de la misma profundidad)."""
    orden: list[NodoAula] = []
    for delata in (False, True):
        tanda = [n for n in nodos if _delata(n.idnumber) is delata]
        orden.extend(n for n in tanda if n.clase != "categoria")
        orden.extend(
            sorted(
                (n for n in tanda if n.clase == "categoria"),
                key=lambda n: _profundidad(n, indice),
                reverse=True,
            )
        )
    return orden


def retirada_antiguo(aula: CalificadorAula) -> Retirada:
    """Qué se borra del árbol de la generación anterior, en el orden que no pierde nada.

    Se conservan las actividades, los ``TZ_O_``, las casillas manuales con notas y todo lo que
    no empiece por ``TZ_``. Los calculados se borran siempre (tengan o no notas): ``tiene_notas``
    también sale en los calculados con valor y no distingue lo tecleado de lo calculado.
    """
    indice = _Indice(aula)
    conservadas = tuple(
        n
        for n in aula.nodos
        if n.idnumber.startswith(_PREFIJO) and n.clase == "manual" and n.tiene_notas
    )
    cerradas = tuple(
        n
        for n in aula.nodos
        if n.clase == "categoria" and n.bloqueado and _EVALUACION.fullmatch(n.idnumber) is not None
    )
    borrar = _en_orden_de_retirada(
        [n for n in aula.nodos if _se_borra(n)],
        indice,
    )
    return Retirada(
        operaciones=tuple(
            Operacion("borrar", idnumber=n.idnumber, eid=n.eid, item_id=n.item_id) for n in borrar
        ),
        conservadas=conservadas,
        cerradas=cerradas,
    )


def aula_tras_retirada(aula: CalificadorAula, retirada: Retirada) -> CalificadorAula:
    """El aula simulada tras la retirada: sin lo borrado, con lo que queda colgando del curso.

    Al borrar una categoría, Moodle sube a su padre lo que había dentro; cada nodo que queda
    pasa a colgar de su ancestro más cercano que no se borra. El curso nunca se borra.
    """
    indice = _Indice(aula)
    borrados = {op.eid for op in retirada.operaciones if op.eid is not None}

    def padre_que_queda(nodo: NodoAula) -> str | None:
        padre = indice.padre(nodo)
        while padre is not None and padre.eid in borrados:
            padre = indice.padre(padre)
        return padre.eid if padre is not None else None

    quedan = tuple(
        dataclasses.replace(n, padre_eid=padre_que_queda(n))
        for n in aula.nodos
        if n.eid not in borrados
    )
    return dataclasses.replace(aula, nodos=quedan)


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


def _texto_coeficiente(nodo: NodoAula, indice: _Indice) -> str:
    """El coeficiente si el padre es de media ponderada; si no, el peso de siempre."""
    padre = indice.padre(nodo)
    if padre is not None and padre.agregacion == 10:
        return "-" if nodo.coeficiente is None else f"{nodo.coeficiente:.4f}"
    return _texto_peso(nodo)


def _sha(partes: list[str]) -> str:
    return hashlib.sha256(json.dumps(partes, ensure_ascii=False).encode("utf-8")).hexdigest()


def _huella(nodo: NodoAula, indice: _Indice, decimal: str) -> str:
    padre = indice.padre(nodo)
    nombre = "" if nodo.clase == "actividad" else nodo.nombre
    return _sha(
        [
            nodo.clase,
            padre.idnumber if padre else "",
            _texto_coeficiente(nodo, indice),
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


def _huella_con_padre(nodo: NodoAula, padre: str, padre_mp: bool, decimal: str) -> str:
    """La huella del nodo tal como está, pero con el padre que tenía en el YAML.

    Sirve para reconocer los huérfanos de una categoría borrada: Moodle los sube al padre y su
    huella cambia solo por eso; si el resto coincide con la guardada, no es un cambio a mano.
    """
    if padre_mp:
        peso = "-" if nodo.coeficiente is None else f"{nodo.coeficiente:.4f}"
    else:
        peso = _texto_peso(nodo)
    nombre = "" if nodo.clase == "actividad" else nodo.nombre
    return _sha([nodo.clase, padre, peso, _normalizar(nodo.formula, decimal), nombre])


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


def _texto_peso_deseado(nodo: Nodo, *, padre_mp: bool, en_el_curso: bool) -> str:
    """El peso de un nodo del deseado como lo escribiría la huella del aula."""
    if nodo.clase == "resultado":  # tiza no le pone peso: Moodle lo deja en 0 sin sobrescribir
        return "-"
    if nodo.peso is None:
        return "-"
    if padre_mp:
        return f"{nodo.peso:.4f}"
    if en_el_curso:  # ``fijar_peso``: el peso natural de lo que cuelga del curso
        return f"{round(nodo.peso, 2):.2f}"
    return "-"  # en una categoría que no es de media ponderada tiza no sobrescribe peso


# La clase que el aula da a cada clase del deseado (``calificador()`` no distingue contenedor,
# copia, nota ni resultado_calc: todo lo que no es una actividad con cmid es ``calculado``).
_CLASE_EN_EL_AULA = {
    "contenedor": "categoria",
    "categoria": "categoria",
    "actividad": "actividad",
    "manual": "manual",
    "copia": "calculado",
    "nota": "calculado",
    "resultado": "actividad",
    "resultado_calc": "calculado",
}


def _clase_en_el_aula(nodo: Nodo) -> str:
    return _CLASE_EN_EL_AULA.get(nodo.clase, nodo.clase)


def _formula_deseada(nodo: Nodo, deseado: Deseado, referencia: str | None) -> str | None:
    """La fórmula que tiza pondría en un nodo; ``None`` si no se puede resolver (se omite)."""
    if nodo.clase == "copia":
        return None if referencia is None else formula_copia(referencia)
    if nodo.clase == "resultado_calc":
        assert isinstance(nodo.formula_de, str)
        return formula_resultado(nodo.formula_de, deseado.niveles)
    if nodo.clase == "nota" and nodo.idnumber == NOTA_FINAL:
        if deseado.tope is None:
            return formula_copia("TZ_FINAL")
        umbral, maximo, notas = deseado.tope
        return formula_tope(umbral, maximo, list(notas))
    return ""


def huellas_deseadas(
    deseado: Deseado,
    cmids: Mapping[str, int],
    claves: Mapping[str, str] | None = None,
    *,
    curso_mp: bool = False,
) -> dict[str, str]:
    """La huella de lo que tiza pondría en cada nodo: clase, padre, peso, fórmula y nombre.

    Se calcula desde el ``Deseado``, no desde el aula, con el mismo formato que
    :func:`huellas_de`, para saber si lo conservado a mano sigue igual por los dos lados.
    ``claves`` permite dar el número de ID efectivo de cada actividad (``TZ_A<cmid>`` o el
    que tenga); sin él se usa ``TZ_A<cmid>``. ``curso_mp`` dice si el total del curso es de
    media ponderada (decide cómo se lee el peso de ``TZ_TIZA``). Las copias de una actividad
    pendiente se omiten: esa pasada no las monta.
    """
    dnodos = {n.idnumber: n for n in deseado.nodos}
    rutas = {ruta for ruta, _ in deseado.actividades}
    efectivas = dict(claves or {})

    def clave_de(ruta: str) -> str | None:
        if ruta in efectivas:
            return efectivas[ruta]
        cmid = cmids.get(ruta)
        return f"{_PREFIJO}A{cmid}" if cmid is not None else None

    def referencia(fuente: str) -> str | None:
        return clave_de(fuente) if fuente in rutas else fuente

    resultado: dict[str, str] = {}
    for n in deseado.nodos:
        if n.clase == "actividad":
            clave = clave_de(n.idnumber)
            if clave is None:
                continue
        else:
            clave = n.idnumber
        padre = dnodos.get(n.padre) if n.padre else None
        padre_mp = (
            curso_mp
            if padre is None
            else (padre.clase in ("contenedor", "categoria") and padre.agregacion == 10)
        )
        fuente = n.formula_de
        formula = _formula_deseada(
            n, deseado, referencia(fuente) if isinstance(fuente, str) else None
        )
        if formula is None:
            continue
        resultado[clave] = _sha(
            [
                _clase_en_el_aula(n),
                n.padre or "",
                _texto_peso_deseado(n, padre_mp=padre_mp, en_el_curso=n.padre is None),
                _normalizar(formula, "."),
                "" if _clase_en_el_aula(n) == "actividad" else n.nombre,
            ]
        )
    if deseado.total_curso is not None:
        esperada = f"{formula_copia(NOTA_FINAL)}/10" if deseado.total_curso == NOTA_FINAL else ""
        resultado[CURSO] = _sha(["curso", _normalizar(esperada, ".")])
    return resultado


# Medio decimal: el aula redondea a un decimal el peso que devuelve (más un margen de coma flotante).
_TOLERANCIA_PESO_AULA = 0.05 + 1e-9


def _cerca(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= TOLERANCIA_PESOS


def es_calculado_de_tiza(nodo: NodoAula) -> bool:
    """¿Es un calculado que crea tiza? La clase del aula ``calculado`` y prefijo ``TZ_``.

    Las casillas manuales, las actividades y los elementos de resultado no lo son. Tampoco lo
    son los calculados del docente (sin ``TZ_``): tiza no los oculta ni los toca.
    """
    return nodo.clase == "calculado" and nodo.idnumber.startswith(_PREFIJO)


def _coeficiente_correcto(nodo: NodoAula, deseado: float) -> bool:
    """El coeficiente de media ponderada del aula vale si coincide con el deseado.

    Se compara a medio decimal, como los pesos de siempre: el formulario de Moodle muestra el
    coeficiente con cuatro decimales, pero puede redondear la última cifra.
    """
    return nodo.coeficiente is not None and abs(nodo.coeficiente - deseado) <= _TOLERANCIA_PESO_AULA


def _peso_correcto(nodo: NodoAula, deseado: float) -> bool:
    """El peso natural (``TZ_TIZA`` en el total del curso) vale si coincide con el deseado."""
    return (
        nodo.sobrescrito
        and nodo.peso is not None
        and abs(nodo.peso - deseado) <= _TOLERANCIA_PESO_AULA
    )


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
        resultados: Mapping[str, int] | None = None,
        conservados: Mapping[str, estado.Conservado] | None = None,
        sobrescribir: Collection[str] = (),
    ) -> None:
        self.d = deseado
        self.aula = aula
        self.cmids = cmids
        self.solo_ajustes = solo_ajustes
        self.idx = _Indice(aula)
        self.dnodos = {n.idnumber: n for n in deseado.nodos}
        self.rutas = {ruta for ruta, _ in deseado.actividades}
        # (ruta, clave) -> TZ_O_… y su vuelta; y clave -> id del resultado en Moodle.
        self.resultados_de = {
            (ruta, clave): idnumber for ruta, clave, idnumber in deseado.resultados
        }
        self.resultado_de_id = {
            idnumber: (ruta, clave) for ruta, clave, idnumber in deseado.resultados
        }
        self.resultados_moodle = dict(resultados or {})
        self.nombres_resultado = frozenset(
            self.dnodos[id_].nombre for _, _, id_ in deseado.resultados if id_ in self.dnodos
        )
        self.huellas = huellas
        self.claves = {
            ruta: self._id_efectivo(ruta)
            for ruta in self.rutas
            if self._actividad_aula(ruta) is not None
        }
        self.por_clave: dict[str, NodoAula] = dict(self.idx.por_id)
        for ruta, clave in self.claves.items():
            actividad = self._actividad_aula(ruta)
            if actividad is not None:
                self.por_clave[clave] = actividad
        self.deseadas = huellas_deseadas(
            deseado,
            cmids,
            self.claves,
            curso_mp=self.idx.curso is not None and self.idx.curso.agregacion == 10,
        )
        self.conservados = dict(conservados or {})
        self.sobrescribir = frozenset(sobrescribir)
        self.conservados_vigentes: set[str] = set()
        self.huerfanos: set[str] = set()
        if a_mano is None:
            actuales = huellas_de(aula, cmids)
            rotas = self._de_casillas_nuevas()
            self.huerfanos = self._huerfanos(actuales, rotas)
            self.conservados_vigentes = self._conservados_vigentes(actuales)
            a_mano = frozenset(
                k
                for k, h in actuales.items()
                if k in huellas
                and huellas[k] != h
                and k not in rotas
                and k not in self.huerfanos
                and k not in self.conservados_vigentes
                and k not in self.sobrescribir
            )
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
        self.reparacion: list[Operacion] = []
        self.agregacion: list[Operacion] = []
        self.peso: list[Operacion] = []
        self.maximo: list[Operacion] = []
        self.formula: list[Operacion] = []
        self.ocultar: list[Operacion] = []
        self.cierre: list[Operacion] = []
        self.borrar: list[Operacion] = []
        self._ajenas_bloqueadas: set[str] = set()
        self._salen: set[str] = set()  # eids que dejan su sitio en esta pasada

    # -- utilidades --------------------------------------------------------

    def _aviso(self, codigo: str, clave: str) -> None:
        self.avisos.setdefault((codigo, clave), None)

    def _deseado_de_clave(self, clave: str) -> Nodo | None:
        """El nodo del deseado de una clave del aula (``TZ_A<cmid>`` para una actividad)."""
        if clave in self.dnodos:
            return self.dnodos[clave]
        for ruta, efectiva in self.claves.items():
            if efectiva == clave:
                return self.dnodos.get(ruta)
        return None

    def _conservados_vigentes(self, actuales: Mapping[str, str]) -> set[str]:
        """Lo conservado que sigue igual por los dos lados: ni el aula ni el YAML lo tocaron."""
        return {
            clave
            for clave, conservado in self.conservados.items()
            if clave in actuales
            and actuales[clave] == conservado.aula
            and self.deseadas.get(clave) == conservado.deseado
        }

    def _huerfanos(self, actuales: Mapping[str, str], rotas: Collection[str]) -> set[str]:
        """Los hijos de una categoría ``TZ_`` que el docente borró a mano.

        Moodle los sube al padre, así que su huella cambia solo por el padre. Si al recalcularla
        con el padre que tenían en el YAML coincide con la guardada, no son un cambio a mano:
        tiza recrea la categoría y los vuelve a meter dentro.
        """
        huerfanos: set[str] = set()
        for clave, huella in actuales.items():
            if clave in rotas or clave not in self.huellas or self.huellas[clave] == huella:
                continue
            nodo = self._deseado_de_clave(clave)
            if nodo is None or not nodo.padre or not nodo.padre.startswith(_PREFIJO):
                continue
            if nodo.padre in self.idx.por_id:  # el padre sigue en el aula: no es un huérfano
                continue
            actual = self.por_clave.get(clave)
            padre = self.dnodos.get(nodo.padre)
            if actual is None or padre is None:
                continue
            padre_mp = padre.clase in ("contenedor", "categoria") and padre.agregacion == 10
            if (
                _huella_con_padre(actual, nodo.padre, padre_mp, self.aula.decimal)
                == self.huellas[clave]
            ):
                huerfanos.add(clave)
        return huerfanos

    def _valor_peso_aula(self, nodo: NodoAula) -> float | None:
        """El peso del aula en la misma escala que el deseado: coeficiente en MP, peso si no."""
        padre = self.idx.padre(nodo)
        if padre is not None and padre.agregacion == 10:
            return nodo.coeficiente
        return nodo.peso if nodo.sobrescrito else None

    def cambios_a_mano(self) -> tuple[CambioAMano, ...]:
        """El tipo de cambio de cada clave que hay que preguntar, y sus valores si es de peso.

        Compara el nodo del aula con lo que pide el YAML; no con la huella, que es un sha. Si no
        sabe decir qué cambió, el tipo es ``otro``.
        """
        cambios: list[CambioAMano] = []
        for clave in sorted(self.a_mano):
            if clave == CURSO:
                actual = self.idx.curso
                formula = (
                    _normalizar(actual.formula, self.aula.decimal) if actual is not None else ""
                )
                if self.d.total_curso == NOTA_FINAL:
                    esperada = f"{formula_copia(NOTA_FINAL)}/10"
                elif self.d.total_curso == "porcentaje":
                    esperada = ""
                else:
                    cambios.append(CambioAMano(clave, "otro", "total del curso"))
                    continue
                if actual is not None and formula != _normalizar(esperada, "."):
                    cambios.append(CambioAMano(clave, "formula", "total del curso"))
                    continue
                cambios.append(CambioAMano(clave, "otro", "total del curso"))
                continue
            actual = self.por_clave.get(clave)
            deseado = self._deseado_de_clave(clave)
            if actual is None or deseado is None:
                cambios.append(CambioAMano(clave, "otro", clave))
                continue
            padre = self.idx.padre(actual)
            padre_antes = padre.idnumber if padre is not None and padre.idnumber else None
            padre_despues = deseado.padre
            padre_cambiado = (padre_antes or "") != (padre_despues or "")
            padre_borrado = (
                padre_cambiado
                and padre_despues is not None
                and padre_despues.startswith(_PREFIJO)
                and padre_despues not in self.idx.por_id
            )
            if padre_cambiado and not padre_borrado:
                cambios.append(
                    CambioAMano(
                        clave,
                        "padre",
                        deseado.nombre,
                        padre_antes=padre_antes,
                        padre_despues=padre_despues,
                    )
                )
                continue
            antes = self._valor_peso_aula(actual)
            despues = self._peso(deseado)
            if (antes is None) != (despues is None) or (
                antes is not None
                and despues is not None
                and abs(antes - despues) > _TOLERANCIA_PESO_AULA
            ):
                cambios.append(
                    CambioAMano(clave, "peso", deseado.nombre, antes=antes, despues=despues)
                )
                continue
            if deseado.clase in ("copia", "resultado_calc", "nota"):
                if _normalizar(actual.formula, self.aula.decimal) != _normalizar(
                    self._formula(deseado), "."
                ):
                    cambios.append(CambioAMano(clave, "formula", deseado.nombre))
                    continue
            if deseado.clase != "actividad" and actual.nombre != deseado.nombre:
                cambios.append(CambioAMano(clave, "nombre", deseado.nombre))
                continue
            if padre_cambiado:
                cambios.append(
                    CambioAMano(
                        clave,
                        "padre",
                        deseado.nombre,
                        padre_antes=padre_antes,
                        padre_despues=padre_despues,
                    )
                )
                continue
            cambios.append(CambioAMano(clave, "otro", deseado.nombre))
        return tuple(cambios)

    def _actividad_aula(self, ruta: str) -> NodoAula | None:
        cmid = self.cmids.get(ruta)
        if cmid is None:
            return None
        candidatos = self.idx.por_cmid_todos.get(cmid, [])
        if not candidatos:
            return None
        if len(candidatos) == 1:
            return candidatos[0]
        # Varios elementos con el cmid: la actividad real y los resultados que Moodle crea al
        # marcarla. Se descartan los que llevan el nombre de un resultado; si aun así hay
        # ambigüedad, no se elige uno al azar.
        sin_resultados = [n for n in candidatos if n.nombre not in self.nombres_resultado]
        if len(sin_resultados) == 1:
            return sin_resultados[0]
        deseado = self.dnodos.get(ruta)
        if deseado is not None:
            exactos = [n for n in sin_resultados if n.nombre == deseado.nombre]
            if len(exactos) == 1:
                return exactos[0]
        return None

    def _id_efectivo(self, ruta: str) -> str:
        """El número de ID con el que se referencia una actividad en las fórmulas."""
        act = self._actividad_aula(ruta)
        assert act is not None
        return act.idnumber or f"{_PREFIJO}A{act.cmid}"

    def _referencia(self, fuente: str) -> str:
        return self._id_efectivo(fuente) if fuente in self.rutas else fuente

    def _resultado_aula(self, nodo: Nodo) -> NodoAula | None:
        """El elemento de resultado del aula de un nodo ``resultado``, si ya existe.

        Primero por su número de ID (``TZ_O_…``); si aún no lo tiene, por el cmid de la tarea y
        el nombre completo del criterio (D9), que es lo único que Moodle guarda al crearlo.
        """
        existente = self.idx.por_id.get(nodo.idnumber)
        if existente is not None:
            return existente
        datos = self.resultado_de_id.get(nodo.idnumber)
        if datos is None:
            return None
        ruta, _criterio = datos
        cmid = self.cmids.get(ruta)
        if cmid is None:
            return None
        return next(
            (n for n in self.idx.por_cmid_todos.get(cmid, []) if n.nombre == nodo.nombre),
            None,
        )

    def _omitidos(self) -> set[str]:
        """Las actividades que no se colocan y todo lo que cuelga de ellas.

        Son las pendientes (sin cmid o sin elemento en el aula) y las nuevas en una evaluación
        cerrada: sin número de ID ni sitio, nada puede referenciarlas. Un resultado del aula que
        no está y que no se puede recrear (tarea pendiente o resultados desactivados) se omite con
        su calculado: es lo más seguro, porque una fórmula a un número de ID que no existe dejaría
        el calificador a medias.
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
            if n.clase == "resultado":
                datos = self.resultado_de_id.get(n.idnumber)
                if datos is None:
                    continue
                ruta, clave = datos
                if (
                    self.cmids.get(ruta) is None
                    or ruta in pendientes
                    or (self._resultado_aula(n) is None and clave not in self.resultados_moodle)
                ):
                    omitidos.add(n.idnumber)
        for n in self.d.nodos:
            if n.clase == "resultado_calc" and n.formula_de in omitidos:
                omitidos.add(n.idnumber)
        for n in self.d.nodos:
            if n.clase == "indicador" and n.formula_de in omitidos:
                omitidos.add(n.idnumber)
        return omitidos

    def _de_casillas_nuevas(self) -> set[str]:
        """Las copias e indicadores de una casilla manual que tiza va a crear (otra vez).

        Si el docente borró la casilla, Moodle les dejó la fórmula apuntando al elemento que ya no
        existe: no es un cambio a mano, y al crear la casilla se vuelve a fijar su fórmula.
        """
        nuevas = {
            n.idnumber
            for n in self.d.nodos
            if n.clase == "manual" and n.idnumber not in self.idx.por_id
        }
        dependientes: set[str] = set()
        for clase in ("copia", "indicador"):
            for n in self.d.nodos:
                if n.clase == clase and n.formula_de in nuevas | dependientes:
                    dependientes.add(n.idnumber)
        return dependientes

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

    def _padre_mp(self, padre: str | None) -> bool:
        """¿El padre es de media ponderada? (El curso, para ``TZ_TIZA``, puede no serlo)."""
        if padre is None or padre == "":
            return self.idx.curso is not None and self.idx.curso.agregacion == 10
        deseado = self.dnodos.get(padre)
        if deseado is not None:
            return deseado.clase in ("contenedor", "categoria") and deseado.agregacion == 10
        aula = self.idx.por_id.get(padre)
        return aula is not None and aula.agregacion == 10

    def _ajuste_peso(self, nodo: Nodo) -> tuple[str | None, float | None]:
        """Cómo se fija el peso de un nodo: coeficiente en MP, peso natural en el curso, o nada."""
        valor = self._peso(nodo)
        if self._padre_mp(nodo.padre):
            return "fijar_coeficiente", valor
        if nodo.padre is None:
            return "fijar_peso", valor
        return None, None

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
        if nodo.clase in ("resultado_calc", "nota"):
            return nodo.maximo if nodo.maximo is not None else _MAXIMO_SIN_DATO
        if nodo.clase == "manual":
            return _MAXIMO_NOTA
        if nodo.clase == "copia":
            if nodo.maximo is not None:
                return nodo.maximo
            fuente = nodo.formula_de
            if isinstance(fuente, str) and fuente in self.rutas:
                return self._maximo_actividad(fuente)
            if isinstance(fuente, str) and fuente.startswith(_PREFIJO_MANUAL):
                return self._maximo_casilla(fuente)
            return _MAXIMO_SIN_DATO
        return _MAXIMO_SIN_DATO

    def _formula(self, nodo: Nodo) -> str:
        fuente = nodo.formula_de
        if nodo.clase == "copia":
            assert isinstance(fuente, str)
            return formula_copia(self._referencia(fuente))
        if nodo.clase == "resultado_calc":
            assert isinstance(fuente, str)
            return formula_resultado(fuente, self.d.niveles)
        if nodo.clase == "nota" and nodo.idnumber == NOTA_FINAL:
            if self.d.tope is None:
                return formula_copia("TZ_FINAL")
            umbral, maximo, notas = self.d.tope
            return formula_tope(umbral, maximo, list(notas))
        raise AssertionError(f"sin fórmula para {nodo.idnumber}")

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
            if nodo.idnumber in self.omitidos:
                continue
            if nodo.clase == "actividad":
                self._avisar_si_sale_de_cerrada(nodo)
            if self._cerrado_deseado(nodo.idnumber):
                continue
            if nodo.clase == "actividad":
                self._actividad(nodo)
            else:
                self._otro(nodo)
        self._dejan_de_contar()
        self._total_del_curso()
        self._sobrantes()
        self._ocultar_calculados()
        self._cierres()

    def _evaluacion_deseada(self, idnumber: str | None) -> str | None:
        while idnumber is not None:
            if _EVALUACION.fullmatch(idnumber):
                return idnumber
            nodo = self.dnodos.get(idnumber)
            idnumber = nodo.padre if nodo else None
        return None

    def _evaluacion_cerrada_del_aula(self, nodo: NodoAula | None) -> str | None:
        while nodo is not None:
            if nodo.idnumber in self.cerradas and _EVALUACION.fullmatch(nodo.idnumber):
                return nodo.idnumber
            nodo = self.idx.padre(nodo)
        return None

    def _avisar_si_sale_de_cerrada(self, nodo: Nodo) -> None:
        """Avisa de la actividad que el esquema pone en otra evaluación y sigue en una cerrada."""
        act = self._actividad_aula(nodo.idnumber)
        hoy = self._evaluacion_cerrada_del_aula(act)
        if hoy is not None and hoy != self._evaluacion_deseada(nodo.padre):
            self._aviso("SALE_DE_EVALUACION_CERRADA", nodo.idnumber)
            self.sin_colocar.add(nodo.idnumber)

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
        if clave in self.conservados_vigentes:
            return
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
        tipo, valor = self._ajuste_peso(nodo)
        if valor is not None:
            if tipo == "fijar_coeficiente" and (colocada or not _coeficiente_correcto(act, valor)):
                self.peso.append(
                    Operacion(
                        "fijar_coeficiente",
                        idnumber=clave,
                        eid=act.eid,
                        item_id=act.item_id,
                        coeficiente=valor,
                    )
                )
            elif tipo == "fijar_peso" and (colocada or not _peso_correcto(act, valor)):
                self.peso.append(
                    Operacion(
                        "fijar_peso",
                        idnumber=clave,
                        eid=act.eid,
                        item_id=act.item_id,
                        peso=valor,
                    )
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

    def _resultado(self, nodo: Nodo) -> None:
        """Un elemento de resultado del aula: se le pone el número de ID y su sitio (peso 0).

        No se crea por el alta normal del calificador: lo crea Moodle al marcar la tarea. Si el
        docente lo borró a mano, ``marcar_resultado`` lo vuelve a crear y la segunda pasada lo
        coloca y le pone el número de ID (``RESULTADO_RECREADO``).
        """
        existente = self._resultado_aula(nodo)
        padre = self.idx.por_id.get(nodo.padre) if nodo.padre else self.idx.curso
        if existente is None:
            if self.solo_ajustes:
                return
            datos = self.resultado_de_id.get(nodo.idnumber)
            if datos is None:
                return
            ruta, clave = datos
            cmid = self.cmids.get(ruta)
            resultado = self.resultados_moodle.get(clave)
            if cmid is None or resultado is None:
                return
            self.alta.append(
                Operacion(
                    "marcar_resultado",
                    cmid=cmid,
                    resultado=resultado,
                    nombre=nodo.nombre,
                )
            )
            self._aviso("RESULTADO_RECREADO", nodo.idnumber)
            return
        if self._cerrado_aula(existente):
            return
        if nodo.idnumber in self.conservados_vigentes:
            return
        con_id = bool(existente.idnumber)
        if con_id and nodo.idnumber in self.a_mano:
            self._aviso("CAMBIADO_A_MANO", nodo.idnumber)
            return
        if padre is None or existente.padre_eid != padre.eid:
            self.reparacion.append(
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
        if not con_id:
            self.reparacion.append(
                Operacion(
                    "fijar_idnumber_resultado",
                    idnumber=nodo.idnumber,
                    eid=existente.eid,
                    item_id=existente.item_id,
                )
            )
        # Sin ``aggregateoutcomes`` el resultado del aula ya pesa 0 (D6); no se le sobrescribe
        # un peso: el formulario del elemento de resultado no es el del elemento normal.

    def _otro(self, nodo: Nodo) -> None:
        if nodo.clase == "resultado":
            self._resultado(nodo)
            return
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
        if nodo.idnumber in self.conservados_vigentes:
            return
        if nodo.idnumber in self.a_mano:
            self._aviso("CAMBIADO_A_MANO", nodo.idnumber)
            return
        if (
            nodo.clase == "categoria"
            and existente.agregacion is not None
            and existente.agregacion != nodo.agregacion
        ):
            self._aviso("REGLA_CAMBIADA", nodo.idnumber)
            self.agregacion.append(
                Operacion(
                    "fijar_agregacion",
                    idnumber=nodo.idnumber,
                    eid=existente.eid,
                    item_id=existente.item_id,
                    agregacion=nodo.agregacion,
                )
            )
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
                if nodo.idnumber in self.huerfanos:
                    return
                self._aviso("CAMBIADO_A_MANO", nodo.idnumber)
                return
        tipo, valor = self._ajuste_peso(nodo)
        if valor is not None:
            if tipo == "fijar_coeficiente" and (
                movido or not _coeficiente_correcto(existente, valor)
            ):
                self.peso.append(
                    Operacion(
                        "fijar_coeficiente",
                        idnumber=nodo.idnumber,
                        eid=existente.eid,
                        item_id=existente.item_id,
                        coeficiente=valor,
                    )
                )
            elif tipo == "fijar_peso" and (movido or not _peso_correcto(existente, valor)):
                self.peso.append(
                    Operacion(
                        "fijar_peso",
                        idnumber=nodo.idnumber,
                        eid=existente.eid,
                        item_id=existente.item_id,
                        peso=valor,
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
        tipo, valor = self._ajuste_peso(nodo)
        coeficiente = valor if tipo == "fijar_coeficiente" else None
        peso = valor if tipo == "fijar_peso" else None
        if calculado:
            self.alta.append(
                Operacion(
                    "crear_calculado",
                    idnumber=nodo.idnumber,
                    nombre=nodo.nombre,
                    padre=nodo.padre,
                    padre_eid=padre.eid if padre else None,
                    peso=peso,
                    coeficiente=coeficiente,
                    maximo=self._maximo(nodo),
                    oculto=nodo.clase in CLASES_OCULTAS,
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
                    coeficiente=coeficiente,
                    visualizacion=nodo.visualizacion,
                    agregacion=nodo.agregacion,
                )
            )
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
            if n.idnumber.startswith(_PREFIJO_RESULTADO):
                continue  # un resultado del aula no es la actividad: ya pesa 0 (D6)
            padre = self.idx.padre(n)
            if padre is None or not padre.idnumber.startswith(_PREFIJO) or self._cerrado_aula(n):
                continue
            if not self._padre_mp(padre.idnumber or None):
                continue
            clave = n.idnumber or f"{_PREFIJO}A{n.cmid}"
            if clave in self.conservados_vigentes:
                continue
            if clave in self.a_mano:
                self._aviso("CAMBIADO_A_MANO", clave)
            elif not _coeficiente_correcto(n, 0.0):
                self.peso.append(
                    Operacion(
                        "fijar_coeficiente",
                        idnumber=clave,
                        eid=n.eid,
                        item_id=n.item_id,
                        coeficiente=0.0,
                    )
                )

    def _total_del_curso(self) -> None:
        curso = self.idx.curso
        total = self.d.total_curso
        if total is None or curso is None or hay_anterior(self.aula):
            return
        if CURSO in self.conservados_vigentes:
            return
        if CURSO in self.a_mano:
            self._aviso("CAMBIADO_A_MANO", CURSO)
            return
        actual = _normalizar(curso.formula, self.aula.decimal)
        if total == NOTA_FINAL:
            # La nota final es 0–100 (oculta); el total del curso se muestra sobre 10.
            esperada: str | None = f"{formula_copia(NOTA_FINAL)}/10"
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

    def _ocultar_calculados(self) -> None:
        """R1: deja ocultos al alumnado los calculados de tiza que sigan visibles.

        Va sobre los nodos del aula, no del deseado: incluye lo que cuelga de una evaluación
        cerrada (``planificar`` salta ``_cerrado_deseado``) y los sobrantes que se conservan
        (``TZ_R_`` y copias con notas). Excluye lo que esta misma pasada va a borrar y nunca
        toca categorías, actividades ni casillas manuales. Solo la primera pasada: las 8 pasadas
        de ``_ajustar`` no repiten un ocultado que falló (``OCULTAR_FALLIDO`` lo comprueba
        ``calificador_con`` sobre el aula final).
        """
        if self.solo_ajustes:
            return
        borrados = {op.eid for op in self.borrar}
        for n in self.aula.nodos:
            if not es_calculado_de_tiza(n) or n.oculto or n.eid in borrados:
                continue
            self.ocultar.append(
                Operacion("ocultar", idnumber=n.idnumber, eid=n.eid, item_id=n.item_id)
            )
        if self.ocultar:
            self._aviso("CALCULADOS_OCULTADOS", str(len(self.ocultar)))

    def _cierres(self) -> None:
        """Bloquea, al final de la segunda pasada, las cerradas del esquema aún sin bloquear.

        Un total bloqueado ya no admite los ajustes de pesos y fórmulas que esa pasada repite.
        """
        if not self.solo_ajustes:
            return
        for idnumber in sorted(set(self.por_cerrar) | set(self.d.cerradas)):
            nodo = self.idx.por_id.get(idnumber)
            if nodo is None:
                continue
            # La copia del curso lee el total de la hoja, no el de la evaluación: hay que
            # bloquear también las categorías de dentro para que una nota tardía no la mueva.
            pendientes = [nodo]
            vistos: set[str] = set()
            while pendientes:
                actual = pendientes.pop()
                if actual.eid in vistos:
                    continue
                vistos.add(actual.eid)
                if (
                    actual.clase == "categoria"
                    and not actual.bloqueado
                    and actual.idnumber.startswith(_PREFIJO)
                ):
                    self.cierre.append(
                        Operacion(
                            "bloquear_cerrada",
                            idnumber=actual.idnumber,
                            item_id=actual.item_id,
                        )
                    )
                pendientes.extend(self.idx.hijos.get(actual.eid, []))

    def _profundidad(self, nodo: NodoAula) -> int:
        nivel = 0
        while True:
            padre = self.idx.padre(nodo)
            if padre is None:
                return nivel
            nivel += 1
            nodo = padre

    def _sobrantes(self) -> None:
        """Los nodos de tiza que ya no están en el esquema.

        Se borran si no tienen notas (solo en la primera pasada); los que se quedan (con notas
        o con algo dentro que se queda) pasan a coeficiente 0 si su padre es de media ponderada,
        como una actividad que deja de contar. Los resultados del aula (``TZ_O_``) y sus
        calculados (``TZ_R_``) nunca se borran: al quitar ``evidencia`` se quedan con peso 0 y,
        si el resultado tiene niveles, se avisa (D11).
        """
        candidatos = [
            n
            for n in self.aula.nodos
            if n.idnumber.startswith(_PREFIJO)
            and n.clase not in ("actividad", "curso")
            and n.idnumber not in self.dnodos
            and not self._cerrado_aula(n)
            and not n.idnumber.startswith((_PREFIJO_RESULTADO, _PREFIJO_CALCULADO_RESULTADO))
        ]
        con_notas = {n.eid for n in candidatos if n.tiene_notas}
        for n in candidatos:
            if n.eid in con_notas and not any(
                h.eid in con_notas for h in self.idx.hijos.get(n.eid, [])
            ):
                self._aviso("ELEMENTO_CON_NOTAS_QUITADO", n.idnumber)
        resultados_que_quedan = [
            n
            for n in self.aula.nodos
            if n.idnumber.startswith((_PREFIJO_RESULTADO, _PREFIJO_CALCULADO_RESULTADO))
            and n.idnumber not in self.dnodos
            and not self._cerrado_aula(n)
        ]
        for n in resultados_que_quedan:
            if n.idnumber.startswith(_PREFIJO_RESULTADO) and n.tiene_notas:
                self._aviso("RESULTADO_CON_NOTAS_QUITADO", n.idnumber)
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
            if not self._padre_mp(padre.idnumber if padre else None):
                continue
            if not _coeficiente_correcto(n, 0.0):
                self.peso.append(
                    Operacion(
                        "fijar_coeficiente",
                        idnumber=n.idnumber,
                        eid=n.eid,
                        item_id=n.item_id,
                        coeficiente=0.0,
                    )
                )
        for n in resultados_que_quedan:
            if n.idnumber in self.a_mano:
                self._aviso("CAMBIADO_A_MANO", n.idnumber)
                continue
            if n.idnumber.startswith(_PREFIJO_RESULTADO):
                continue  # el formulario del resultado no lleva coeficiente
            padre = self.idx.padre(n)
            if not self._padre_mp(padre.idnumber if padre else None):
                continue
            if not _coeficiente_correcto(n, 0.0):
                self.peso.append(
                    Operacion(
                        "fijar_coeficiente",
                        idnumber=n.idnumber,
                        eid=n.eid,
                        item_id=n.item_id,
                        coeficiente=0.0,
                    )
                )

    # -- el resultado ------------------------------------------------------

    def ajustes(self) -> tuple[Operacion, ...]:
        return tuple(
            self.reparacion + self.agregacion + self.peso + self.maximo + self.formula + self.cierre
        )

    def todo(self) -> tuple[Operacion, ...]:
        return tuple(
            self.ajeno
            + self.alta
            + self.reparacion
            + self.agregacion
            + self.peso
            + self.maximo
            + self.formula
            + self.ocultar
            + self.cierre
            + self.borrar
        )


def es_evaluacion(idnumber: str) -> bool:
    return _EVALUACION.fullmatch(idnumber) is not None


def reconciliar(
    deseado: Deseado,
    aula: CalificadorAula,
    huellas: dict[str, str],
    cmids: dict[str, int],
    resultados: Mapping[str, int] | None = None,
    *,
    conservados: Mapping[str, estado.Conservado] | None = None,
    sobrescribir: Collection[str] = (),
) -> Reconciliacion:
    """La primera pasada: qué operaciones llevan el aula a lo deseado sin pisar notas ni a mano.

    ``huellas`` es lo que devolvió ``estado.cargar_huellas`` (vacío si tiza no recuerda nada);
    ``cmids`` lleva, por ruta, el cmid de cada actividad en el aula (las que falten son
    pendientes). ``conservados`` son los nodos que el docente decidió conservar a mano: si su
    huella del aula y la de lo deseado no han cambiado, se saltan en silencio; si cambia
    cualquiera de las dos, vuelven a ``a_mano``. ``sobrescribir`` son las claves que el docente
    ya aceptó pisar en esta pasada: salen de ``a_mano``. Orden: todos los ``bloquear_ajeno``;
    crear y colocar (padres antes que hijos); ``fijar_peso`` y ``fijar_maximo``;
    ``fijar_formula`` y ``fijar_total_curso``; y al final ``bloquear_cerrada`` y ``borrar`` (los
    hijos antes que sus padres).
    """
    plan = _Plan(
        deseado,
        aula,
        huellas,
        cmids,
        None,
        False,
        resultados=resultados,
        conservados=conservados,
        sobrescribir=sobrescribir,
    )
    plan.planificar()
    return Reconciliacion(
        operaciones=plan.todo(),
        avisos=tuple(plan.avisos),
        anterior=hay_anterior(aula),
        a_mano=frozenset(plan.a_mano),
        por_cerrar=plan.por_cerrar,
        sin_colocar=frozenset(plan.sin_colocar),
        cerradas=frozenset(deseado.cerradas),
        conservados=frozenset(plan.conservados_vigentes),
        huerfanos=frozenset(plan.huerfanos),
        cambios_a_mano=plan.cambios_a_mano(),
    )


def pasada2(
    deseado: Deseado,
    aula: CalificadorAula,
    huellas: dict[str, str],
    cmids: dict[str, int],
    a_mano: frozenset[str] | None = None,
    por_cerrar: frozenset[str] = frozenset(),
    resultados: Mapping[str, int] | None = None,
) -> tuple[Operacion, ...]:
    """La segunda pasada, sobre el aula releída tras ejecutar la primera.

    Solo ``mover_manual`` y ``fijar_idnumber_resultado`` de un resultado recreado,
    ``fijar_peso``, ``fijar_maximo``, ``fijar_formula`` y ``fijar_total_curso`` que sigan
    haciendo falta, y al final el ``bloquear_cerrada`` de las evaluaciones ``cerrada: true`` aún
    sin bloquear. Pásale ``a_mano=reconciliacion.a_mano`` (sin él, lo que la
    primera pasada cambió en el aula se compara con las huellas de antes y parece cosa del
    docente), ``por_cerrar=reconciliacion.por_cerrar`` y ``resultados`` (criterio -> id del
    resultado en Moodle) cuando la publicación los haya asegurado.
    """
    plan = _Plan(deseado, aula, huellas, cmids, a_mano, True, por_cerrar, resultados=resultados)
    plan.planificar()
    return plan.ajustes()
