"""La reconciliación del calificador: pura, sin aula, con un simulador de las operaciones."""

from __future__ import annotations

import dataclasses
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tiza.calificacion import reconciliar as rc
from tiza.calificacion.deseado import Deseado, deseado
from tiza.calificacion.esquema import (
    Criterio,
    Elemento,
    Esquema,
    Evaluacion,
    Final,
    Instrumento,
    Tope,
)
from tiza.calificacion.reconciliar import (
    Operacion,
    Reconciliacion,
    hay_anterior,
    huellas_de,
    pasada2,
    reconciliar,
)
from tiza.contenido import Documento
from tiza.publicar import CalificadorAula, NodoAula

CARPETA = Path("/curso")
EL = (Elemento("RA1", "Redes", 60.0), Elemento("RA2", "Sistemas", 40.0))
EL_5050 = (Elemento("RA1", "Redes", 50.0), Elemento("RA2", "Sistemas", 50.0))
EVS = (Evaluacion("Primera", (1,)), Evaluacion("Segunda", (2,)))
EVS_CERRADA = (Evaluacion("Primera", (1,), cerrada=True), Evaluacion("Segunda", (2,)))
FP = Esquema("elementos", EL, EVS, Final("elementos"))
FP_TOPE = Esquema("elementos", EL, EVS, Final("elementos", Tope(5.0, 4.0)))
FP_CERRADA = Esquema("elementos", EL_5050, EVS_CERRADA, Final("elementos"))
FP_ABIERTA_5050 = Esquema("elementos", EL_5050, EVS, Final("elementos"))
ESO = Esquema(
    "evaluaciones",
    (Elemento("RA1", "Redes", 60.0), Elemento("RA2", "Sistemas", 40.0)),
    (Evaluacion("Primera", (1,), 40.0), Evaluacion("Segunda", (2,), 60.0)),
    Final("evaluaciones"),
)
CMIDS = {"a.md": 11, "d.md": 12, "c.md": 13}


def doc(ruta: str, seccion: int, **evalua: float) -> Documento:
    return Documento(
        ruta=CARPETA / ruta,
        tipo="pagina",
        nombre=Path(ruta).stem,
        seccion=seccion,
        cuerpo="",
        html="",
        recursos=[],
        evalua=tuple(evalua.items()),
    )


def docs() -> list[Documento]:
    # RA1: a 60 + d 40; RA2: d 50 + c 50. a y d en la sección 1, c en la 2.
    return [doc("a.md", 1, RA1=60), doc("d.md", 1, RA1=40, RA2=50), doc("c.md", 2, RA2=50)]


def nodo_aula(eid: str, idnumber: str, clase: str, padre: str | None, **kw) -> NodoAula:
    base = dict(
        eid=eid,
        item_id=int(eid[2:]),
        idnumber=idnumber,
        clase=clase,
        nombre=idnumber or "sin nombre",
        padre_eid=padre,
        peso=None,
        sobrescrito=False,
        bloqueado=False,
        tiene_notas=False,
        formula=None,
        maximo=None,
        cmid=None,
    )
    base.update(kw)
    return NodoAula(**base)  # type: ignore[arg-type]


def curso() -> NodoAula:
    return nodo_aula("cg1", "", "curso", None, nombre="Curso")


def actividad(cmid: int, padre: str = "cg1", idnumber: str = "", maximo: float = 10.0, **kw):
    return nodo_aula(
        f"ig{100 + cmid}", idnumber, "actividad", padre, cmid=cmid, maximo=maximo, **kw
    )


def aula_con(*nodos: NodoAula, decimal: str = ".") -> CalificadorAula:
    return CalificadorAula(nodos=(curso(), *nodos), decimal=decimal)


def aula_inicial(cmids=CMIDS, maximo: float = 10.0) -> CalificadorAula:
    return aula_con(*(actividad(c, maximo=maximo) for c in cmids.values()))


def aplicar(aula: CalificadorAula, operaciones) -> CalificadorAula:
    """Simula lo que hace el aula con las operaciones (lo justo para que converjan)."""
    nodos = {n.eid: n for n in aula.nodos}
    siguiente = [500]

    def buscar(op: Operacion) -> NodoAula:
        if op.eid:
            return nodos[op.eid]
        if op.tipo in ("bloquear_ajeno", "bloquear_cerrada"):
            return next(n for n in nodos.values() if n.item_id == op.item_id)
        return next(n for n in nodos.values() if n.idnumber == op.idnumber)

    def padre_de(op: Operacion) -> str:
        if op.padre_eid:
            return op.padre_eid
        if op.padre:
            return next(n.eid for n in nodos.values() if n.idnumber == op.padre)
        return next(n.eid for n in nodos.values() if n.clase == "curso")

    def cambiar(op: Operacion, **kw) -> None:
        n = buscar(op)
        nodos[n.eid] = dataclasses.replace(n, **kw)

    for op in operaciones:
        t = op.tipo
        if t in ("crear_categoria", "crear_calculado"):
            siguiente[0] += 1
            k = siguiente[0]
            categoria = t == "crear_categoria"
            eid = f"{'cg' if categoria else 'ig'}{k}"
            clase = "categoria" if categoria else "calculado"
            if op.idnumber.startswith("TZ_M_"):
                clase = "manual"  # sin fórmula: así lo lee el aula
            nodos[eid] = nodo_aula(
                eid,
                op.idnumber,
                clase,
                padre_de(op),
                nombre=op.nombre or "",
                peso=op.peso,
                sobrescrito=op.peso is not None,
                maximo=op.maximo,
            )
        elif t == "colocar":
            n = buscar(op)
            cambiar(
                op,
                padre_eid=padre_de(op),
                peso=None,
                sobrescrito=False,
                idnumber=op.idnumber if op.poner_idnumber else n.idnumber,
            )
        elif t == "mover_manual":
            cambiar(op, padre_eid=padre_de(op))
        elif t == "fijar_peso":
            cambiar(op, peso=op.peso, sobrescrito=True)
        elif t == "fijar_maximo":
            cambiar(op, maximo=op.maximo)
        elif t in ("fijar_formula", "fijar_total_curso"):
            cambiar(op, formula=op.formula)
        elif t in ("bloquear_ajeno", "bloquear_cerrada"):
            cambiar(op, bloqueado=True)
        elif t == "borrar":
            del nodos[buscar(op).eid]
        for _ in range(6):  # el máximo de una categoría Natural es la suma de sus hijos
            for n in list(nodos.values()):
                if n.clase == "categoria":
                    hijos = [h for h in nodos.values() if h.padre_eid == n.eid]
                    nodos[n.eid] = dataclasses.replace(
                        n, maximo=sum(h.maximo or 0.0 for h in hijos)
                    )
    return CalificadorAula(nodos=tuple(nodos.values()), decimal=aula.decimal)


def montar(esquema=FP, documentos=None, anterior=False, aula=None, huellas=None, cmids=CMIDS):
    """Una pasada completa y la segunda: devuelve (deseado, aula final)."""
    d = deseado(esquema, documentos or docs(), anterior, CARPETA)
    aula = aula or aula_inicial(cmids)
    huellas = huellas or {}
    rec = reconciliar(d, aula, huellas, cmids)
    aula = aplicar(aula, rec.operaciones)
    ajustes = pasada2(d, aula, huellas, cmids, a_mano=rec.a_mano, por_cerrar=rec.por_cerrar)
    return d, aplicar(aula, ajustes)


def tipos(operaciones) -> list[str]:
    return [o.tipo for o in operaciones]


def por_id(aula: CalificadorAula, idnumber: str) -> NodoAula:
    return next(n for n in aula.nodos if n.idnumber == idnumber)


def subarbol(aula: CalificadorAula, raiz: str) -> tuple[set[str], set[str]]:
    """(eids, idnumbers) de un nodo y todo lo que cuelga de él."""
    nodos = {raiz_n.eid: raiz_n for raiz_n in aula.nodos}
    eids = {por_id(aula, raiz).eid}
    cambio = True
    while cambio:
        cambio = False
        for n in nodos.values():
            if n.padre_eid in eids and n.eid not in eids:
                eids.add(n.eid)
                cambio = True
    return eids, {nodos[e].idnumber for e in eids}


def toca(op: Operacion, eids: set[str], ids: set[str]) -> bool:
    return bool({op.eid, op.padre_eid} & eids or {op.idnumber, op.padre} & ids)


# --------------------------------------------------------------------------- #
# Los tests del brief
# --------------------------------------------------------------------------- #


def test_curso_vacio_crea_todo() -> None:
    d = deseado(FP, docs(), False, CARPETA)
    aula = aula_inicial()
    rec = reconciliar(d, aula, {}, CMIDS)
    assert "bloquear_ajeno" not in tipos(rec.operaciones)
    creadas: list[str] = []
    for op in rec.operaciones:
        if op.tipo in ("crear_categoria", "crear_calculado"):
            assert op.padre is None or op.padre in creadas, op.idnumber
            creadas.append(op.idnumber)
        elif op.tipo == "colocar":
            assert op.padre in creadas
    assert creadas[0] == "TZ_TIZA"
    assert rec.operaciones[0].padre_eid == "cg1"  # el padre de TZ_TIZA es el curso
    assert {o.ruta for o in rec.operaciones if o.tipo == "colocar"} == set(CMIDS)
    assert all(o.poner_idnumber for o in rec.operaciones if o.tipo == "colocar")
    assert rec.anterior is False and rec.avisos == ()
    # nada de crear lo que ya existe: tantas creaciones como nodos que no son actividades reales
    reales = {n.idnumber for n in d.nodos if n.clase == "actividad"}
    assert len(creadas) == len([n for n in d.nodos if n.idnumber not in reales])


def trabajos(notas: bool, bloqueado: bool = False):
    t = nodo_aula(
        "cg20",
        "",
        "categoria",
        "cg1",
        nombre="Trabajos (docente)",
        tiene_notas=notas,
        bloqueado=bloqueado,
    )
    return t, actividad(11, padre="cg20", tiene_notas=notas)


def test_anterior_bloquea_antes_de_mover() -> None:
    t, a = trabajos(notas=True)
    aula = aula_con(t, a, actividad(12), actividad(13))
    assert hay_anterior(aula) is True
    d = deseado(FP, docs(), True, CARPETA)
    rec = reconciliar(d, aula, {}, CMIDS)
    assert rec.anterior is True
    tp = tipos(rec.operaciones)
    ajeno = rec.operaciones[tp.index("bloquear_ajeno")]
    assert ajeno.item_id == 20 and ajeno.eid is None
    assert tp.count("bloquear_ajeno") == 1
    colocar = next(o for o in rec.operaciones if o.tipo == "colocar" and o.cmid == 11)
    assert tp.index("bloquear_ajeno") < rec.operaciones.index(colocar)
    assert ("TOTAL_AJENO_BLOQUEADO", "cg20") in rec.avisos
    assert "fijar_total_curso" not in tp  # D1: el total del curso no se toca


def test_ajena_sin_notas_no_se_bloquea() -> None:
    t, a = trabajos(notas=False)
    aula = aula_con(t, a, actividad(12), actividad(13))
    rec = reconciliar(deseado(FP, docs(), True, CARPETA), aula, {}, CMIDS)
    assert "bloquear_ajeno" not in tipos(rec.operaciones)
    assert not [av for av in rec.avisos if av[0] == "TOTAL_AJENO_BLOQUEADO"]
    assert any(o.tipo == "colocar" and o.cmid == 11 for o in rec.operaciones)


def test_ajena_ya_bloqueada_no_se_bloquea_otra_vez() -> None:
    t, a = trabajos(notas=True, bloqueado=True)
    aula = aula_con(t, a, actividad(12), actividad(13))
    rec = reconciliar(deseado(FP, docs(), True, CARPETA), aula, {}, CMIDS)
    assert "bloquear_ajeno" not in tipos(rec.operaciones)


def test_dos_actividades_de_la_misma_ajena_la_bloquean_una_vez() -> None:
    t = nodo_aula("cg20", "", "categoria", "cg1", tiene_notas=True)
    aula = aula_con(t, actividad(11, "cg20"), actividad(12, "cg20"), actividad(13))
    rec = reconciliar(deseado(FP, docs(), True, CARPETA), aula, {}, CMIDS)
    assert tipos(rec.operaciones).count("bloquear_ajeno") == 1


def test_hay_anterior() -> None:
    assert hay_anterior(aula_con(actividad(11), actividad(12))) is False
    assert hay_anterior(aula_con()) is False
    assert hay_anterior(aula_con(nodo_aula("cg20", "", "categoria", "cg1"))) is True
    assert hay_anterior(aula_con(nodo_aula("ig50", "", "manual", "cg1"))) is True
    # una actividad suelta o con número de ID propio dentro de lo de tiza no es «anterior»
    tiza = nodo_aula("cg30", "TZ_TIZA", "categoria", "cg1")
    assert hay_anterior(aula_con(tiza, actividad(11, "cg30", idnumber="EX1"))) is False
    assert hay_anterior(aula_con(tiza, nodo_aula("ig60", "TZ_A5", "actividad", "cg30"))) is False
    assert hay_anterior(aula_con(actividad(11, idnumber="EX1"))) is False


def montaje_cerrado():
    """FP montado en 60/40, con la 1.ª evaluación bloqueada en el aula."""
    _, aula = montar(FP)
    v1 = por_id(aula, "TZ_V_1")
    nodos = tuple(
        dataclasses.replace(n, bloqueado=True) if n.eid == v1.eid else n for n in aula.nodos
    )
    return CalificadorAula(nodos=nodos, decimal="."), huellas_de(aula, CMIDS)


def test_evaluacion_cerrada_no_se_toca() -> None:
    aula, huellas = montaje_cerrado()
    d = deseado(FP_CERRADA, docs(), False, CARPETA)  # los pesos de RA cambian a 50/50
    rec = reconciliar(d, aula, huellas, CMIDS)
    eids, ids = subarbol(aula, "TZ_V_1")
    assert len(ids) > 2
    assert not [o for o in rec.operaciones if toca(o, eids, ids)]
    # no es un test vacío: lo de fuera sí cambia
    assert any(o.tipo == "fijar_peso" and o.idnumber == "TZ_E_RA1" for o in rec.operaciones)
    # y la actividad que cuenta dentro de la cerrada tampoco se mueve
    assert not any(o.tipo == "borrar" for o in rec.operaciones)


def test_cerrada_en_aula_abierta_en_esquema() -> None:
    aula, huellas = montaje_cerrado()
    d = deseado(FP_ABIERTA_5050, docs(), False, CARPETA)
    rec = reconciliar(d, aula, huellas, CMIDS)
    assert ("EVALUACION_CERRADA_EN_EL_AULA", "TZ_V_1") in rec.avisos
    eids, ids = subarbol(aula, "TZ_V_1")
    assert not [o for o in rec.operaciones if toca(o, eids, ids)]
    assert all(t in rc.TIPOS for t in tipos(rec.operaciones))
    assert not any("desbloq" in t for t in rc.TIPOS)


def test_cerrar_bloquea_total() -> None:
    _, aula = montar(FP)
    huellas = huellas_de(aula, CMIDS)
    cerrando = Esquema("elementos", EL, EVS_CERRADA, Final("elementos"))
    d = deseado(cerrando, docs(), False, CARPETA)
    rec = reconciliar(d, aula, huellas, CMIDS)
    v1 = por_id(aula, "TZ_V_1")
    # la evaluación aún no está bloqueada: se trata como abierta y se bloquea al final de la 2.ª pasada
    assert rec.por_cerrar == {"TZ_V_1"} and rec.hay_trabajo
    assert "bloquear_cerrada" not in tipos(rec.operaciones)
    cierres = pasada2(d, aula, huellas, CMIDS, a_mano=rec.a_mano, por_cerrar=rec.por_cerrar)
    assert [(o.idnumber, o.eid, o.item_id) for o in cierres] == [("TZ_V_1", None, v1.item_id)]
    assert cierres[-1].tipo == "bloquear_cerrada"
    # y ya cerrada, no se vuelve a bloquear
    cerrada = aplicar(aula, cierres)
    rec2 = reconciliar(d, cerrada, huellas_de(cerrada, CMIDS), CMIDS)
    assert rec2.operaciones == () and not rec2.hay_trabajo


def test_cerrada_sin_bloquear_se_completa_como_una_abierta() -> None:
    # montada con los pesos 60/40 pero sin bloquear; el esquema cambia a 50/50 y la marca cerrada
    _, aula = montar(FP)
    huellas = huellas_de(aula, CMIDS)
    d = deseado(
        Esquema("elementos", EL_5050, EVS_CERRADA, Final("elementos")), docs(), False, CARPETA
    )
    rec = reconciliar(d, aula, huellas, CMIDS)
    assert {o.idnumber for o in rec.operaciones if o.tipo == "fijar_peso"} >= {
        "TZ_E_RA1",
        "TZ_E_RA2",
    }
    final = aplicar(aula, rec.operaciones)
    ajustes = pasada2(d, final, huellas, CMIDS, a_mano=rec.a_mano, por_cerrar=rec.por_cerrar)
    assert ajustes[-1].tipo == "bloquear_cerrada"
    final = aplicar(final, ajustes)
    assert por_id(final, "TZ_V_1").bloqueado is True
    assert por_id(final, "TZ_E_RA1").peso == 50.0
    # ya bloqueada, sigue sin tocarse aunque el esquema vuelva a cambiar
    otra = Esquema("elementos", EL, EVS_CERRADA, Final("elementos"))
    rec2 = reconciliar(
        deseado(otra, docs(), False, CARPETA), final, huellas_de(final, CMIDS), CMIDS
    )
    eids, ids = subarbol(final, "TZ_V_1")
    assert not [o for o in rec2.operaciones if toca(o, eids, ids)]
    assert rec2.por_cerrar == frozenset()


def test_cambiado_a_mano() -> None:  # D3
    _, aula = montar(FP)
    huellas = huellas_de(aula, CMIDS)
    ra1 = por_id(aula, "TZ_E_RA1")
    nodos = tuple(dataclasses.replace(n, peso=55.0) if n.eid == ra1.eid else n for n in aula.nodos)
    a_mano = CalificadorAula(nodos=nodos, decimal=".")
    rec = reconciliar(deseado(FP, docs(), False, CARPETA), a_mano, huellas, CMIDS)
    assert ("CAMBIADO_A_MANO", "TZ_E_RA1") in rec.avisos
    assert "TZ_E_RA1" in rec.a_mano
    assert not [o for o in rec.operaciones if o.tipo == "fijar_peso" and o.eid == ra1.eid]
    assert rec.operaciones == ()
    # sin huella, tiza no sabe que fue a mano y lo deja como lo quiere el esquema
    sin = reconciliar(deseado(FP, docs(), False, CARPETA), a_mano, {}, CMIDS)
    assert [o.idnumber for o in sin.operaciones if o.tipo == "fijar_peso"] == ["TZ_E_RA1"]


def test_cambiado_a_mano_la_formula_y_los_hijos_si_se_gestionan() -> None:
    _, aula = montar(FP_TOPE)
    huellas = huellas_de(aula, CMIDS)
    ind = next(n for n in aula.nodos if n.idnumber.startswith("TZ_I_"))
    ra1 = por_id(aula, "TZ_E_RA1")
    nodos = tuple(
        dataclasses.replace(n, formula="=[[TZ_A11]]*0+77") if n.eid == ind.eid else n
        for n in aula.nodos
    )
    a_mano = CalificadorAula(nodos=nodos, decimal=".")
    # el docente cambia a mano TZ_E_RA1 (su peso) y, además, falta una copia debajo
    nodos2 = tuple(
        dataclasses.replace(n, peso=11.0) if n.eid == ra1.eid else n for n in a_mano.nodos
    )
    sin_copia = tuple(n for n in nodos2 if n.cmid != 12)  # d.md ya no está en el aula
    rec = reconciliar(
        deseado(FP_TOPE, docs(), False, CARPETA),
        CalificadorAula(nodos=sin_copia, decimal="."),
        huellas,
        CMIDS,
    )
    assert ("CAMBIADO_A_MANO", ind.idnumber) in rec.avisos
    assert not [o for o in rec.operaciones if o.eid == ind.eid]
    assert ("CAMBIADO_A_MANO", "TZ_E_RA1") in rec.avisos
    assert ("ACTIVIDAD_PENDIENTE", "d.md") in rec.avisos


def test_pendiente() -> None:
    d = deseado(FP_TOPE, docs(), False, CARPETA)
    cmids = {"a.md": 11, "c.md": 13}  # d.md no está en el aula
    rec = reconciliar(d, aula_inicial(cmids), {}, cmids)
    assert ("ACTIVIDAD_PENDIENTE", "d.md") in rec.avisos
    assert not [o for o in rec.operaciones if o.tipo == "colocar" and o.ruta == "d.md"]
    # sus copias y sus indicadores tampoco se crean (no hay a qué apuntar)
    pendientes = {n.idnumber for n in d.nodos if n.formula_de == "d.md"}
    assert pendientes
    pendientes |= {n.idnumber for n in d.nodos if n.formula_de in pendientes}
    assert not [o for o in rec.operaciones if o.idnumber in pendientes]


def test_actividad_con_cmid_sin_elemento_en_el_aula_es_pendiente() -> None:
    d = deseado(FP, docs(), False, CARPETA)
    aula = aula_con(actividad(11), actividad(12))  # el 13 no tiene elemento calificable
    rec = reconciliar(d, aula, {}, CMIDS)
    assert ("ACTIVIDAD_PENDIENTE", "c.md") in rec.avisos


@pytest.mark.parametrize("esquema", [FP, FP_TOPE, ESO])
def test_sin_cambios_no_hace_nada(esquema) -> None:
    d, aula = montar(esquema)
    huellas = huellas_de(aula, CMIDS)
    rec = reconciliar(d, aula, huellas, CMIDS)
    assert rec.operaciones == ()
    assert rec.avisos == ()
    assert pasada2(d, aula, huellas, CMIDS) == ()


def test_montaje_completo_con_tope() -> None:
    d, aula = montar(FP_TOPE)
    nodos = {n.idnumber: n for n in aula.nodos}
    assert d.total_curso == "TZ_NOTA_FINAL"
    assert nodos["TZ_NOTA_FINAL"].formula.startswith("=min([[TZ_FINAL]]/[[TZ_K_TIZA]]*10,")
    curso_ = next(n for n in aula.nodos if n.clase == "curso")
    assert curso_.formula == "=[[TZ_NOTA_FINAL]]"
    assert nodos["TZ_NOTA_E_RA1"].formula == "=[[TZ_E_RA1]]/[[TZ_K_RA1]]*10"
    assert nodos["TZ_NOTA_E_RA1"].maximo == 10.0
    # el máximo del contador final es el del elemento, que solo se conoce tras colocar
    assert nodos["TZ_KC_RA1"].maximo == nodos["TZ_E_RA1"].maximo == 20.0
    assert nodos["TZ_KC_RA2"].formula == "=[[TZ_K_RA2]]"
    ind = next(n for n in aula.nodos if n.idnumber.startswith("TZ_I_"))
    assert ind.formula.endswith("*0+10") and ind.maximo == 10.0
    # las actividades sin número de ID reciben TZ_A<cmid>, que usan las fórmulas
    assert por_id(aula, "TZ_A11").cmid == 11
    assert any("[[TZ_A11]]" in (n.formula or "") for n in aula.nodos)


def test_un_numero_de_id_con_caracteres_raros_no_deja_huella() -> None:
    raro = "EX\u202e1"
    aula = aula_con(actividad(11, idnumber=raro), actividad(12), actividad(13))
    d, final = montar(FP, aula=aula)
    huellas = huellas_de(final, CMIDS)
    assert raro not in huellas and "TZ_TIZA" in huellas and "TZ_A12" in huellas
    # sin huella, el nodo se trata como nuevo: no es un «cambio a mano» y converge
    rec = reconciliar(d, final, huellas, CMIDS)
    assert rec.a_mano == frozenset() and rec.operaciones == ()


def test_actividad_con_numero_de_id_propio_lo_conserva() -> None:
    aula = aula_con(actividad(11, idnumber="EX1"), actividad(12), actividad(13))
    d, final = montar(FP_TOPE, aula=aula)
    assert por_id(final, "EX1").cmid == 11
    assert not any(n.idnumber == "TZ_A11" for n in final.nodos)
    assert any("[[EX1]]" in (n.formula or "") for n in final.nodos)
    colocar = [
        o
        for o in reconciliar(d, aula, {}, CMIDS).operaciones
        if o.tipo == "colocar" and o.cmid == 11
    ]
    assert colocar[0].poner_idnumber is False and colocar[0].idnumber == "EX1"
    assert huellas_de(final, CMIDS)["EX1"]


def test_quitado_con_notas_se_queda() -> None:
    d0 = deseado(
        Esquema("elementos", EL, EVS, Final("elementos")),
        [doc("a.md", 1, RA1=100)],
        False,
        CARPETA,
    )
    cmids = {"a.md": 11}
    aula = aplicar(aula_inicial(cmids), reconciliar(d0, aula_inicial(cmids), {}, cmids).operaciones)
    huellas = huellas_de(aula, cmids)
    assert por_id(aula, "TZ_E_RA2")  # RA2 existe, vacío
    # el esquema nuevo ya no tiene RA2
    nuevo = Esquema("elementos", (Elemento("RA1", "Redes", 100.0),), EVS, Final("elementos"))
    d1 = deseado(nuevo, [doc("a.md", 1, RA1=100)], False, CARPETA)
    sin_notas = reconciliar(d1, aula, huellas, cmids)
    borrados = [o.idnumber for o in sin_notas.operaciones if o.tipo == "borrar"]
    assert borrados == ["TZ_E_RA2"]
    ra2 = por_id(aula, "TZ_E_RA2")
    assert [o.eid for o in sin_notas.operaciones if o.tipo == "borrar"] == [ra2.eid]
    con_notas = CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, tiene_notas=True) if n.eid == ra2.eid else n for n in aula.nodos
        ),
        decimal=".",
    )
    rec = reconciliar(d1, con_notas, huellas, cmids)
    assert "borrar" not in tipos(rec.operaciones)
    assert ("ELEMENTO_CON_NOTAS_QUITADO", "TZ_E_RA2") in rec.avisos
    # D2: lo que se queda deja de contar (peso 0) en vez de seguir a 40 frente a un RA1 de 100
    ceros = [o for o in rec.operaciones if o.tipo == "fijar_peso" and o.eid == ra2.eid]
    assert [(o.idnumber, o.item_id, o.peso) for o in ceros] == [("TZ_E_RA2", ra2.item_id, 0.0)]
    final = aplicar(con_notas, rec.operaciones)
    assert por_id(final, "TZ_E_RA2").peso == 0.0 and por_id(final, "TZ_E_RA1").peso == 100.0
    otra = reconciliar(d1, final, huellas_de(final, cmids), cmids)
    assert not [o for o in otra.operaciones if o.eid == ra2.eid]
    # y si el docente tocó a mano esa categoría, no se pisa
    a_mano = CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, peso=33.0) if n.eid == ra2.eid else n for n in con_notas.nodos
        ),
        decimal=".",
    )
    sin_pisar = reconciliar(d1, a_mano, huellas, cmids)
    assert not [o for o in sin_pisar.operaciones if o.eid == ra2.eid]
    assert "TZ_E_RA2" in sin_pisar.a_mano


def test_borrar_va_el_ultimo_y_primero_los_hijos() -> None:
    d0 = deseado(FP, docs(), False, CARPETA)
    _, aula = montar(FP)
    huellas = huellas_de(aula, CMIDS)
    # c.md y d.md dejan de contar: RA2 y todo lo suyo sobra; el esquema solo tiene RA1
    nuevo = Esquema("elementos", (Elemento("RA1", "Redes", 100.0),), EVS, Final("elementos"))
    d1 = deseado(nuevo, [doc("a.md", 1, RA1=100)], False, CARPETA)
    assert d0 != d1
    rec = reconciliar(d1, aula, huellas, CMIDS)
    t = tipos(rec.operaciones)
    primero = t.index("borrar")
    assert set(t[primero:]) == {"borrar"}
    ids = [o.idnumber for o in rec.operaciones if o.tipo == "borrar"]
    assert "TZ_E_RA2" not in ids  # d.md y c.md siguen dentro de la categoría: no se borra
    # RA2 se queda con algo dentro: pesa 0 (D2)
    assert [
        o.peso for o in rec.operaciones if o.tipo == "fijar_peso" and o.idnumber == "TZ_E_RA2"
    ] == [0.0]
    # las copias que ya no hacen falta sí se borran, y antes que su categoría
    assert any(i.startswith("TZ_C_") for i in ids)
    pos = {i: k for k, i in enumerate(ids)}
    for o in rec.operaciones:
        if o.tipo == "borrar":
            hijo = por_id(aula, o.idnumber)
            padre = next((n for n in aula.nodos if n.eid == hijo.padre_eid), None)
            if padre is not None and padre.idnumber in pos:
                assert pos[o.idnumber] < pos[padre.idnumber]


def test_actividad_que_deja_de_contar_se_queda_con_peso_cero() -> None:  # D2
    _, aula = montar(FP)
    huellas = huellas_de(aula, CMIDS)
    solo = [doc("a.md", 1, RA1=100), doc("c.md", 2, RA2=100)]  # d.md ya no cuenta
    d = deseado(FP, solo, False, CARPETA)
    rec = reconciliar(d, aula, huellas, CMIDS)
    d_aula = next(n for n in aula.nodos if n.cmid == 12)
    op = next(o for o in rec.operaciones if o.tipo == "fijar_peso" and o.eid == d_aula.eid)
    assert op.peso == 0.0
    assert not any(o.tipo == "borrar" and o.eid == d_aula.eid for o in rec.operaciones)
    # una vez a 0, ya no hay nada que hacer con ella
    final = aplicar(aula, rec.operaciones)
    otra = reconciliar(d, final, huellas_de(final, CMIDS), CMIDS)
    assert not [o for o in otra.operaciones if o.eid == d_aula.eid]


def test_mover_una_copia_del_aula_a_su_sitio() -> None:
    d, aula = montar(FP)
    huellas = huellas_de(aula, CMIDS)
    copia = next(n for n in aula.nodos if n.idnumber.startswith("TZ_C_"))
    destino = next(x for x in aula.nodos if x.eid == copia.padre_eid)
    otro = next(n for n in aula.nodos if n.idnumber == "TZ_VISTA")
    # sin huella la mueve de vuelta con mover_manual; con huella igual (a mano) la respeta
    movida = CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, padre_eid=otro.eid) if n.eid == copia.eid else n
            for n in aula.nodos
        ),
        decimal=".",
    )
    sin = reconciliar(d, movida, {}, CMIDS)
    ops = [o for o in sin.operaciones if o.tipo == "mover_manual"]
    assert [(o.eid, o.item_id, o.padre_eid) for o in ops] == [
        (copia.eid, copia.item_id, destino.eid)
    ]
    con = reconciliar(d, movida, huellas, CMIDS)
    assert "mover_manual" not in tipos(con.operaciones)
    assert ("CAMBIADO_A_MANO", copia.idnumber) in con.avisos


def test_maximo_cambia_actualiza_contador() -> None:
    d, aula = montar(FP_TOPE)
    huellas = huellas_de(aula, CMIDS)
    ra1 = por_id(aula, "TZ_E_RA1")
    assert ra1.maximo == 20.0
    # 1) el máximo de TZ_E_RA1 pasa de 20 a 30 (una actividad con otro máximo, p. ej.)
    nodos = tuple(
        dataclasses.replace(n, maximo=30.0) if n.eid == ra1.eid else n for n in aula.nodos
    )
    rec = reconciliar(d, CalificadorAula(nodos=nodos, decimal="."), huellas, CMIDS)
    kc = por_id(aula, "TZ_KC_RA1")
    ops = [o for o in rec.operaciones if o.tipo == "fijar_maximo"]
    assert [(o.idnumber, o.eid, o.item_id, o.maximo) for o in ops] == [
        ("TZ_KC_RA1", kc.eid, kc.item_id, 30.0)
    ]
    # 2) una actividad de RA1 pasa de máximo 10 a 100
    a_aula = next(n for n in aula.nodos if n.cmid == 11)
    nodos = tuple(
        dataclasses.replace(n, maximo=100.0) if n.eid == a_aula.eid else n for n in aula.nodos
    )
    rec = reconciliar(d, CalificadorAula(nodos=nodos, decimal="."), huellas, CMIDS)
    indicador = next(n for n in d.nodos if n.clase == "indicador" and n.formula_de == "a.md")
    ind_aula = por_id(aula, indicador.idnumber)
    maximos = [o for o in rec.operaciones if o.tipo == "fijar_maximo" and o.eid == ind_aula.eid]
    formulas = [o for o in rec.operaciones if o.tipo == "fijar_formula" and o.eid == ind_aula.eid]
    assert [o.maximo for o in maximos] == [100.0]
    assert [o.formula for o in formulas] == ["=[[TZ_A11]]*0+100"]
    assert max(i for i, o in enumerate(rec.operaciones) if o.tipo == "fijar_maximo") < min(
        i for i, o in enumerate(rec.operaciones) if o.tipo == "fijar_formula"
    )
    # la copia de la actividad también toma el máximo nuevo
    copias = [
        o for o in rec.operaciones if o.tipo == "fijar_maximo" and o.idnumber.startswith("TZ_C_")
    ]
    assert copias and all(o.maximo == 100.0 for o in copias)


def test_orden_dos_fases() -> None:
    d = deseado(FP_TOPE, docs(), False, CARPETA)
    rec = reconciliar(d, aula_inicial(), {}, CMIDS)
    t = tipos(rec.operaciones)
    ultimo_alta = max(
        i for i, x in enumerate(t) if x in ("crear_categoria", "crear_calculado", "colocar")
    )
    assert min(i for i, x in enumerate(t) if x == "fijar_peso") > ultimo_alta
    assert min(i for i, x in enumerate(t) if x == "fijar_formula") > ultimo_alta
    assert min(i for i, x in enumerate(t) if x == "fijar_formula") > max(
        i for i, x in enumerate(t) if x in ("fijar_peso", "fijar_maximo")
    )
    assert t[-1] == "fijar_total_curso"
    # el orden por fases: ajeno, crear/colocar, pesos y máximos, fórmulas, cierre y borrado
    fases = {
        "bloquear_ajeno": 0,
        "crear_categoria": 1,
        "crear_calculado": 1,
        "colocar": 1,
        "mover_manual": 1,
        "fijar_peso": 2,
        "fijar_maximo": 2,
        "fijar_formula": 3,
        "fijar_total_curso": 3,
        "bloquear_cerrada": 4,
        "borrar": 4,
    }
    assert set(rc.TIPOS) == set(fases)
    assert [fases[x] for x in t] == sorted(fases[x] for x in t)
    total = [o for o in rec.operaciones if o.tipo == "fijar_total_curso"][0]
    assert total.formula == "=[[TZ_NOTA_FINAL]]"


def test_total_del_curso_sin_tope_es_solo_visualizacion() -> None:
    d = deseado(FP, docs(), False, CARPETA)
    rec = reconciliar(d, aula_inicial(), {}, CMIDS)
    (total,) = [o for o in rec.operaciones if o.tipo == "fijar_total_curso"]
    assert total.formula is None and total.eid == "cg1"


def test_quitar_el_tope_vacia_la_formula_del_total_del_curso_y_converge() -> None:
    _, con_tope = montar(FP_TOPE)
    huellas = huellas_de(con_tope, CMIDS)
    assert por_id_curso(con_tope).formula == "=[[TZ_NOTA_FINAL]]"
    d = deseado(FP, docs(), False, CARPETA)
    rec = reconciliar(d, con_tope, huellas, CMIDS)
    (total,) = [o for o in rec.operaciones if o.tipo == "fijar_total_curso"]
    assert total.formula is None  # el ejecutor la vacía y pone el porcentaje
    final = aplicar(con_tope, rec.operaciones)
    final = aplicar(final, pasada2(d, final, huellas, CMIDS, a_mano=rec.a_mano))
    assert por_id_curso(final).formula is None
    otra = reconciliar(d, final, huellas_de(final, CMIDS), CMIDS)
    assert otra.operaciones == () and otra.avisos == ()


def test_total_del_curso_en_porcentaje_solo_se_fija_una_vez() -> None:
    d = deseado(FP, docs(), False, CARPETA)
    primera = reconciliar(d, aula_inicial(), {}, CMIDS)
    assert tipos(primera.operaciones).count("fijar_total_curso") == 1
    _, montada = montar(FP)
    huellas = huellas_de(montada, CMIDS)
    # con la huella del curso (ya fijado) y sin fórmula, no hace falta nada
    assert "fijar_total_curso" not in tipos(reconciliar(d, montada, huellas, CMIDS).operaciones)
    # sin huella (nunca fijado), sí; y si hay una fórmula suelta, también
    assert "fijar_total_curso" in tipos(reconciliar(d, montada, {}, CMIDS).operaciones)


def por_id_curso(aula: CalificadorAula) -> NodoAula:
    return next(n for n in aula.nodos if n.clase == "curso")


def test_total_del_curso_cambiado_a_mano_no_se_pisa() -> None:
    d, aula = montar(FP_TOPE)
    huellas = huellas_de(aula, CMIDS)
    nodos = tuple(
        dataclasses.replace(n, formula="=[[TZ_NOTA_FINAL]]*0.9") if n.clase == "curso" else n
        for n in aula.nodos
    )
    rec = reconciliar(d, CalificadorAula(nodos=nodos, decimal="."), huellas, CMIDS)
    assert ("CAMBIADO_A_MANO", "TZ_CURSO") in rec.avisos
    assert "fijar_total_curso" not in tipos(rec.operaciones)


def test_pasada2_solo_ajustes() -> None:
    d, aula = montar(FP_TOPE)
    ra1 = por_id(aula, "TZ_E_RA1")
    ind = next(n for n in aula.nodos if n.idnumber.startswith("TZ_I_"))
    nodos = tuple(
        dataclasses.replace(n, peso=33.0)
        if n.eid == ra1.eid
        else dataclasses.replace(n, formula=None)
        if n.eid == ind.eid
        else n
        for n in aula.nodos
    )
    releida = CalificadorAula(nodos=nodos, decimal=".")
    ops = pasada2(d, releida, {}, CMIDS)
    assert [(o.tipo, o.eid) for o in ops] == [("fijar_peso", ra1.eid), ("fijar_formula", ind.eid)]
    assert ops[0].peso == 60.0 and ops[1].formula.endswith("*0+10")
    # con las huellas de antes de la primera pasada, el reescalado de Moodle no es «a mano»
    huellas = huellas_de(aula, CMIDS)
    assert pasada2(d, releida, huellas, CMIDS) == ()  # sin a_mano se confunde con un cambio
    ops = pasada2(d, releida, huellas, CMIDS, a_mano=frozenset())
    assert [(o.tipo, o.eid) for o in ops] == [("fijar_peso", ra1.eid), ("fijar_formula", ind.eid)]


def test_pasada2_tras_la_primera_solo_arregla_el_contador() -> None:
    d = deseado(FP_TOPE, docs(), False, CARPETA)
    aula = aula_inicial()
    rec = reconciliar(d, aula, {}, CMIDS)
    aula = aplicar(aula, rec.operaciones)
    ops = pasada2(d, aula, {}, CMIDS, a_mano=rec.a_mano)
    assert set(tipos(ops)) <= {"fijar_peso", "fijar_maximo", "fijar_formula", "fijar_total_curso"}
    assert {o.idnumber for o in ops if o.tipo == "fijar_maximo"} == {"TZ_KC_RA1", "TZ_KC_RA2"}


def test_pasada2_no_crea_ni_coloca() -> None:
    d = deseado(FP, docs(), False, CARPETA)
    assert pasada2(d, aula_inicial(), {}, CMIDS) == ()  # nada existe aún: no hay qué ajustar


def test_formula_con_coma_decimal_del_aula() -> None:
    d, aula = montar(FP_TOPE)
    traducidas = tuple(
        dataclasses.replace(n, formula=n.formula.replace(",", ";")) if n.formula else n
        for n in aula.nodos
    )
    coma = CalificadorAula(nodos=traducidas, decimal=",")
    huellas = huellas_de(coma, CMIDS)
    assert reconciliar(d, coma, huellas, CMIDS).operaciones == ()


def test_no_importa_python_moodle() -> None:
    codigo = (
        "import sys, tiza.calificacion.reconciliar, tiza.estado;"
        "assert not [m for m in sys.modules if m.startswith('py_moodle')]"
        " and 'tiza.publicar' not in sys.modules"
    )
    resultado = subprocess.run(
        [sys.executable, "-I", "-c", codigo], capture_output=True, text=True, check=False
    )
    assert resultado.returncode == 0, resultado.stderr


def test_las_formulas_viven_fuera_de_publicar() -> None:
    from tiza import publicar
    from tiza.calificacion import formulas

    assert publicar.formula_copia is formulas.formula_copia
    assert publicar.formula_tope is formulas.formula_tope


def test_reconciliacion_es_inmutable() -> None:
    d = deseado(FP, docs(), False, CARPETA)
    rec = reconciliar(d, aula_inicial(), {}, CMIDS)
    assert isinstance(rec, Reconciliacion) and isinstance(d, Deseado)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.anterior = True  # type: ignore[misc]
    assert isinstance(rec.operaciones, tuple) and isinstance(rec.avisos, tuple)


def test_a_mano_de_la_primera_pasada_no_se_toca_en_la_segunda() -> None:
    _, aula = montar(FP)
    huellas = huellas_de(aula, CMIDS)
    ra1 = por_id(aula, "TZ_E_RA1")
    a_mano = CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, peso=55.0) if n.eid == ra1.eid else n for n in aula.nodos
        ),
        decimal=".",
    )
    # el esquema cambia a 50/50: RA2 sí se arregla; RA1 (a mano) no
    d = deseado(FP_ABIERTA_5050, docs(), False, CARPETA)
    rec = reconciliar(d, a_mano, huellas, CMIDS)
    assert rec.a_mano == {"TZ_E_RA1"}
    pesos = {o.idnumber for o in rec.operaciones if o.tipo == "fijar_peso"}
    assert "TZ_E_RA2" in pesos and "TZ_E_RA1" not in pesos
    tras = aplicar(a_mano, rec.operaciones)
    # RA1 sigue distinto de lo deseado, pero no se toca en la segunda pasada
    assert pasada2(d, tras, huellas, CMIDS, a_mano=rec.a_mano) == ()
    assert por_id(tras, "TZ_E_RA1").peso == 55.0
    # aunque Moodle reescale otro nodo, solo ese se ajusta
    ra2 = por_id(tras, "TZ_E_RA2")
    reescalado = CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, peso=12.0) if n.eid == ra2.eid else n for n in tras.nodos
        ),
        decimal=".",
    )
    ops = pasada2(d, reescalado, huellas, CMIDS, a_mano=rec.a_mano)
    assert [(o.tipo, o.eid, o.peso) for o in ops] == [("fijar_peso", ra2.eid, 50.0)]


def test_pasada2_y_borrar_no_tocan_una_evaluacion_cerrada() -> None:
    aula, huellas = montaje_cerrado()
    eids, ids = subarbol(aula, "TZ_V_1")
    # dentro de la cerrada pasan cosas: un peso, una fórmula y una copia que ya no hace falta
    copia = next(n for n in aula.nodos if n.eid in eids and n.idnumber.startswith("TZ_C_"))
    hijo = next(n for n in aula.nodos if n.idnumber == "TZ_V_1_RA1")
    tocada = CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, peso=1.0)
            if n.eid == hijo.eid
            else dataclasses.replace(n, formula=None)
            if n.eid == copia.eid
            else n
            for n in aula.nodos
        ),
        decimal=".",
    )
    # d.md deja de contar: sus copias de la 1.ª evaluación sobran (y están dentro de la cerrada)
    solo = [doc("a.md", 1, RA1=100), doc("c.md", 2, RA2=100)]
    d = deseado(FP_ABIERTA_5050, solo, False, CARPETA)
    sobrantes = [
        n for n in tocada.nodos if n.eid in eids and n.idnumber not in {x.idnumber for x in d.nodos}
    ]
    assert sobrantes, "el test sería vacío"
    rec = reconciliar(d, tocada, {}, CMIDS)
    assert not [o for o in rec.operaciones if toca(o, eids, ids)]
    assert not [o for o in pasada2(d, tocada, {}, CMIDS) if toca(o, eids, ids)]
    assert not [o for o in rec.operaciones if o.tipo == "borrar" and o.eid in eids]
    # fuera de la cerrada sí hay trabajo: no es un test vacío
    assert any(o.tipo == "fijar_peso" and o.idnumber == "TZ_E_RA2" for o in rec.operaciones)


# --------------------------------------------------------------------------- #
# Una actividad cuya colocación cae en una evaluación cerrada
# --------------------------------------------------------------------------- #

FP_TOPE_CERRADA = Esquema("elementos", EL, EVS_CERRADA, Final("elementos", Tope(5.0, 4.0)))
ESO_CERRADA = Esquema(
    "evaluaciones",
    (Elemento("RA1", "Redes", 60.0), Elemento("RA2", "Sistemas", 40.0)),
    (Evaluacion("Primera", (1,), 40.0, cerrada=True), Evaluacion("Segunda", (2,), 60.0)),
    Final("evaluaciones"),
)
CMIDS_E = {**CMIDS, "e.md": 14}


def referencias_rotas(aula: CalificadorAula) -> list[str]:
    """Las referencias ``[[ID]]`` de las fórmulas que no apuntan a ningún número de ID del aula."""
    ids = {n.idnumber for n in aula.nodos if n.idnumber}
    return sorted(
        {
            ref
            for n in aula.nodos
            for ref in re.findall(r"\[\[([^\]]+)\]\]", n.formula or "")
            if ref not in ids
        }
    )


def con_actividad_nueva_en_cerrada(abierto, cerrado, peso_e: float):
    """Un montaje con la 1.ª evaluación bloqueada y una actividad nueva (e.md) en su sección."""
    _, aula = montar(abierto)
    v1 = por_id(aula, "TZ_V_1")
    aula = CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, bloqueado=True) if n.eid == v1.eid else n for n in aula.nodos
        ),
        decimal=".",
    )
    huellas = huellas_de(aula, CMIDS)
    aula = CalificadorAula(nodos=(*aula.nodos, actividad(14)), decimal=".")
    resto = (100 - peso_e) / 100
    documentos = [
        doc("a.md", 1, RA1=60 * resto),
        doc("d.md", 1, RA1=40 * resto, RA2=50),
        doc("c.md", 2, RA2=50),
        doc("e.md", 1, RA1=peso_e),
    ]
    d = deseado(cerrado, documentos, False, CARPETA)
    return d, aula, huellas


@pytest.mark.parametrize(
    ("abierto", "cerrado"),
    [(FP, FP), (FP_TOPE, FP_TOPE_CERRADA), (ESO, ESO_CERRADA)],
    ids=["elementos", "elementos-con-tope", "evaluaciones"],
)
@pytest.mark.parametrize("peso_e", [0.0, 20.0])
def test_actividad_nueva_en_evaluacion_cerrada_queda_sin_colocar_con_todo_lo_suyo(
    abierto, cerrado, peso_e
) -> None:
    d, aula, huellas = con_actividad_nueva_en_cerrada(abierto, cerrado, peso_e)
    rec = reconciliar(d, aula, huellas, CMIDS_E)
    assert ("ACTIVIDAD_EN_EVALUACION_CERRADA", "e.md") in rec.avisos
    assert "e.md" in rec.sin_colocar
    suyos = {n.idnumber for n in d.nodos if n.formula_de == "e.md" or n.idnumber == "e.md"}
    suyos |= {n.idnumber for n in d.nodos if n.formula_de in suyos}
    assert len(suyos) > 1
    assert not [o for o in rec.operaciones if o.idnumber in suyos or o.ruta == "e.md"]
    assert not [o for o in rec.operaciones if o.cmid == 14]
    final = aplicar(aula, rec.operaciones)
    final = aplicar(final, pasada2(d, final, huellas, CMIDS_E, a_mano=rec.a_mano))
    assert referencias_rotas(final) == []
    otra = reconciliar(d, final, huellas_de(final, CMIDS_E), CMIDS_E)
    assert otra.operaciones == ()


def test_actividad_ya_colocada_en_su_evaluacion_cerrada_no_es_sin_colocar() -> None:
    aula, huellas = montaje_cerrado()
    rec = reconciliar(deseado(FP_CERRADA, docs(), False, CARPETA), aula, huellas, CMIDS)
    assert rec.sin_colocar == frozenset()
    assert not [av for av in rec.avisos if av[0] == "ACTIVIDAD_EN_EVALUACION_CERRADA"]


@pytest.mark.parametrize(
    "cerrado", [FP_TOPE_CERRADA, ESO_CERRADA, FP_CERRADA], ids=["tope", "evaluaciones", "50-50"]
)
def test_primer_montaje_con_evaluacion_cerrada_la_crea_y_la_bloquea_al_final(cerrado) -> None:
    d = deseado(cerrado, docs(), False, CARPETA)
    aula = aula_inicial()
    rec = reconciliar(d, aula, {}, CMIDS)
    assert rec.por_cerrar == frozenset({"TZ_V_1"})
    assert not [av for av in rec.avisos if av[0] == "ACTIVIDAD_EN_EVALUACION_CERRADA"]
    # se crea con normalidad: sus categorías y la colocación de sus actividades
    creadas = {o.idnumber for o in rec.operaciones if o.tipo == "crear_categoria"}
    assert {"TZ_V_1", "TZ_V_2"} <= creadas
    assert "TZ_V_1_RA1" in creadas
    final = aplicar(aula, rec.operaciones)
    ajustes = pasada2(d, final, {}, CMIDS, a_mano=rec.a_mano, por_cerrar=rec.por_cerrar)
    # el bloqueo va después de los ajustes de la segunda pasada, y es lo último
    assert ajustes[-1].tipo == "bloquear_cerrada" and ajustes[-1].idnumber == "TZ_V_1"
    assert ajustes[-1].item_id == por_id(final, "TZ_V_1").item_id
    final = aplicar(final, ajustes)
    assert por_id(final, "TZ_V_1").bloqueado is True
    assert por_id(final, "TZ_V_2").bloqueado is False
    assert referencias_rotas(final) == []
    # y a la vez siguiente converge: ya cerrada, no hay nada que hacer
    otra = reconciliar(d, final, huellas_de(final, CMIDS), CMIDS)
    assert otra.operaciones == () and otra.por_cerrar == frozenset()
    # mismo árbol que sin cerrar
    _, abierta = montar(
        dataclasses.replace(
            cerrado,
            evaluaciones=tuple(dataclasses.replace(e, cerrada=False) for e in cerrado.evaluaciones),
        )
    )
    assert {n.idnumber for n in final.nodos} == {n.idnumber for n in abierta.nodos}


# --------------------------------------------------------------------------- #
# Las casillas manuales (instrumentos sin actividad en el aula)
# --------------------------------------------------------------------------- #

CMIDS_M = {"a.md": 11, "d.md": 12}
EXPOSICION = Instrumento("exp", "Exposición", 1, (("RA1", 50.0),))
FP_M = dataclasses.replace(FP, instrumentos=(EXPOSICION,))
FP_M_TOPE = dataclasses.replace(FP_TOPE, instrumentos=(EXPOSICION,))


def docs_m(ra1: int = 50) -> list[Documento]:
    return [doc("a.md", 1, RA1=ra1), doc("d.md", 1, RA2=100)]


def montar_m(esquema=FP_M, aula=None, huellas=None):
    return montar(esquema, docs_m(), aula=aula, huellas=huellas, cmids=CMIDS_M)


def copias_de(d: Deseado, fuente: str) -> list:
    return [n for n in d.nodos if n.clase == "copia" and n.formula_de == fuente]


def con_nodo(aula: CalificadorAula, eid: str, **kw) -> CalificadorAula:
    return CalificadorAula(
        nodos=tuple(dataclasses.replace(n, **kw) if n.eid == eid else n for n in aula.nodos),
        decimal=aula.decimal,
    )


def test_alta_de_una_casilla_manual_y_de_su_copia() -> None:
    d = deseado(FP_M, docs_m(), False, CARPETA)
    rec = reconciliar(d, aula_inicial(CMIDS_M), {}, CMIDS_M)
    real = next(n for n in d.nodos if n.idnumber == "TZ_M_exp")
    altas = [o for o in rec.operaciones if o.idnumber == "TZ_M_exp"]
    assert [o.tipo for o in altas] == ["crear_calculado", "fijar_peso"]
    assert (altas[0].maximo, altas[0].padre, altas[0].peso, altas[0].nombre) == (
        10.0,
        real.padre,
        real.peso,
        "Exposición",
    )
    assert altas[1].peso == real.peso
    for copia in copias_de(d, "TZ_M_exp"):
        ops = [o for o in rec.operaciones if o.idnumber == copia.idnumber]
        assert [o.tipo for o in ops] == ["crear_calculado", "fijar_peso", "fijar_formula"]
        assert ops[0].maximo == 10.0
        assert ops[2].formula == "=[[TZ_M_exp]]"
    assert not [o for o in rec.operaciones if o.tipo == "colocar" and o.cmid is None]
    assert ("ACTIVIDAD_PENDIENTE", "TZ_M_exp") not in rec.avisos
    assert not [a for a in rec.avisos if a[0] == "ACTIVIDAD_PENDIENTE"]


def test_la_referencia_de_una_casilla_es_su_idnumber() -> None:
    d = deseado(FP_M, docs_m(), False, CARPETA)
    plan = rc._Plan(d, aula_inicial(CMIDS_M), {}, CMIDS_M, None, False)
    assert plan._referencia("TZ_M_exp") == "TZ_M_exp"


def test_la_casilla_montada_converge_sin_operaciones() -> None:
    d, aula = montar_m()
    manual = por_id(aula, "TZ_M_exp")
    assert manual.clase == "manual" and manual.formula is None and manual.maximo == 10.0
    assert referencias_rotas(aula) == []
    huellas = huellas_de(aula, CMIDS_M)
    otra = reconciliar(d, aula, huellas, CMIDS_M)
    assert otra.operaciones == () and otra.avisos == ()
    assert pasada2(d, aula, huellas, CMIDS_M) == ()


def test_casilla_existente_con_otro_maximo_no_se_toca() -> None:
    d, aula = montar_m()
    huellas = huellas_de(aula, CMIDS_M)
    manual = por_id(aula, "TZ_M_exp")
    aula = con_nodo(aula, manual.eid, maximo=25.0)
    rec = reconciliar(d, aula, huellas, CMIDS_M)
    assert [o for o in rec.operaciones if o.eid == manual.eid] == []
    # solo se ajustan sus copias (a su máximo), nunca la casilla
    assert {o.tipo for o in rec.operaciones} == {"fijar_maximo"}
    assert {o.maximo for o in rec.operaciones} == {25.0}
    final = aplicar(aula, rec.operaciones)
    assert pasada2(d, final, huellas, CMIDS_M, a_mano=rec.a_mano) == ()


def test_casilla_en_otro_padre_se_mueve() -> None:
    d, aula = montar_m()
    huellas = huellas_de(aula, CMIDS_M)
    manual = por_id(aula, "TZ_M_exp")
    otro = por_id(aula, "TZ_E_RA2")
    rec = reconciliar(d, con_nodo(aula, manual.eid, padre_eid=otro.eid), huellas, CMIDS_M)
    # el padre difiere de la huella: es un cambio a mano y no se toca
    assert [o for o in rec.operaciones if o.eid == manual.eid] == []
    assert ("CAMBIADO_A_MANO", "TZ_M_exp") in rec.avisos
    # sin huella (tiza no recuerda nada) sí la coloca donde toca
    rec = reconciliar(d, con_nodo(aula, manual.eid, padre_eid=otro.eid), {}, CMIDS_M)
    ops = [o for o in rec.operaciones if o.eid == manual.eid]
    assert [o.tipo for o in ops] == ["mover_manual", "fijar_peso"]
    assert ops[0].padre == next(n.padre for n in d.nodos if n.idnumber == "TZ_M_exp")
    assert "fijar_maximo" not in tipos(rec.operaciones)


def test_casilla_cambiada_a_mano_no_se_toca() -> None:
    d, aula = montar_m()
    huellas = huellas_de(aula, CMIDS_M)
    manual = por_id(aula, "TZ_M_exp")
    # el docente le puso una fórmula: pasa a ser un calculado y la huella cambia
    cambiada = con_nodo(aula, manual.eid, clase="calculado", formula="=1+1", peso=7.0)
    rec = reconciliar(d, cambiada, huellas, CMIDS_M)
    assert ("CAMBIADO_A_MANO", "TZ_M_exp") in rec.avisos
    assert [o for o in rec.operaciones if o.eid == manual.eid] == []
    # y un peso cambiado a mano tampoco se pisa
    pesada = con_nodo(aula, manual.eid, peso=7.0)
    rec = reconciliar(d, pesada, huellas, CMIDS_M)
    assert ("CAMBIADO_A_MANO", "TZ_M_exp") in rec.avisos
    assert [o for o in rec.operaciones if o.eid == manual.eid] == []


def test_casilla_con_peso_distinto_se_corrige_si_no_hay_huella() -> None:
    d, aula = montar_m()
    manual = por_id(aula, "TZ_M_exp")
    rec = reconciliar(d, con_nodo(aula, manual.eid, peso=7.0), {}, CMIDS_M)
    assert [(o.tipo, o.peso) for o in rec.operaciones if o.eid == manual.eid] == [
        ("fijar_peso", 50.0)
    ]


def test_copia_de_una_casilla_en_evaluacion_cerrada_no_se_toca() -> None:
    d, aula = montar_m()
    huellas = huellas_de(aula, CMIDS_M)
    copia = next(c for c in copias_de(d, "TZ_M_exp") if c.padre == "TZ_V_1_RA1")
    en_aula = por_id(aula, copia.idnumber)
    aula = con_nodo(aula, por_id(aula, "TZ_V_1").eid, bloqueado=True)
    aula = con_nodo(aula, en_aula.eid, peso=3.0)
    rec = reconciliar(d, aula, huellas, CMIDS_M)
    assert not [o for o in rec.operaciones if o.eid == en_aula.eid]


def test_indicador_de_una_casilla_con_tope_tiene_maximo_10() -> None:
    d, aula = montar_m(FP_M_TOPE)
    indicadores = [n for n in d.nodos if n.clase == "indicador"]
    reales = [n for n in indicadores if n.formula_de == "TZ_M_exp"]
    copias = {c.idnumber for c in copias_de(d, "TZ_M_exp")}
    de_copia = [n for n in indicadores if n.formula_de in copias]
    assert reales or de_copia
    for n in reales + de_copia:
        assert por_id(aula, n.idnumber).maximo == 10.0
    assert por_id(aula, "TZ_M_exp").maximo == 10.0
    assert referencias_rotas(aula) == []
    huellas = huellas_de(aula, CMIDS_M)
    assert reconciliar(d, aula, huellas, CMIDS_M).operaciones == ()
    assert pasada2(d, aula, huellas, CMIDS_M) == ()
    # un máximo distinto en el aula de un indicador de casilla se corrige a 10
    n = (reales + de_copia)[0]
    rota = con_nodo(aula, por_id(aula, n.idnumber).eid, maximo=100.0)
    rec = reconciliar(d, rota, {}, CMIDS_M)
    assert [o.maximo for o in rec.operaciones if o.tipo == "fijar_maximo"][:1] == [10.0]


def test_casilla_quitada_del_esquema_sin_notas_se_borra() -> None:
    _, aula = montar_m()
    huellas = huellas_de(aula, CMIDS_M)
    d1 = deseado(FP, docs_m(100), False, CARPETA)
    rec = reconciliar(d1, aula, huellas, CMIDS_M)
    borrados = {o.idnumber for o in rec.operaciones if o.tipo == "borrar"}
    copias = {n.idnumber for n in aula.nodos if n.formula == "=[[TZ_M_exp]]"}
    assert copias and "TZ_M_exp" in borrados
    assert copias <= borrados
    assert not [a for a in rec.avisos if a[0] == "ELEMENTO_CON_NOTAS_QUITADO"]


def test_casilla_quitada_del_esquema_con_notas_se_queda_con_peso_cero() -> None:
    _, aula = montar_m()
    huellas = huellas_de(aula, CMIDS_M)
    manual = por_id(aula, "TZ_M_exp")
    aula = con_nodo(aula, manual.eid, tiene_notas=True)
    d1 = deseado(FP, docs_m(100), False, CARPETA)
    rec = reconciliar(d1, aula, huellas, CMIDS_M)
    assert ("ELEMENTO_CON_NOTAS_QUITADO", "TZ_M_exp") in rec.avisos
    assert "TZ_M_exp" not in {o.idnumber for o in rec.operaciones if o.tipo == "borrar"}
    assert [
        (o.peso) for o in rec.operaciones if o.tipo == "fijar_peso" and o.eid == manual.eid
    ] == [0.0]


def test_casilla_nueva_con_su_sitio_en_una_evaluacion_bloqueada_no_se_crea() -> None:
    eso_m = dataclasses.replace(ESO, instrumentos=(EXPOSICION,))
    _, aula = montar(ESO, docs_m(100), cmids=CMIDS_M)
    huellas = huellas_de(aula, CMIDS_M)
    aula = con_nodo(aula, por_id(aula, "TZ_V_1").eid, bloqueado=True)
    d = deseado(eso_m, docs_m(), False, CARPETA)
    assert copias_de(d, "TZ_M_exp")  # hay copias fuera de la evaluación cerrada
    rec = reconciliar(d, aula, huellas, CMIDS_M)
    assert ("ACTIVIDAD_EN_EVALUACION_CERRADA", "TZ_M_exp") in rec.avisos
    referencias = [
        o
        for o in rec.operaciones
        if "TZ_M_exp" in (o.idnumber or "") or "TZ_M_exp" in (o.formula or "")
    ]
    assert referencias == []
    copias = {c.idnumber for c in copias_de(d, "TZ_M_exp")}
    assert not [o for o in rec.operaciones if o.idnumber in copias]
    ajustes = pasada2(d, aplicar(aula, rec.operaciones), huellas, CMIDS_M, a_mano=rec.a_mano)
    assert not [o for o in ajustes if "TZ_M_exp" in (o.idnumber or "") + (o.formula or "")]


def test_las_copias_y_los_indicadores_de_una_casilla_siguen_su_maximo_en_el_aula() -> None:
    d, aula = montar_m(FP_M_TOPE)
    huellas = huellas_de(aula, CMIDS_M)
    manual = por_id(aula, "TZ_M_exp")
    aula = con_nodo(aula, manual.eid, maximo=100.0)
    rec = reconciliar(d, aula, huellas, CMIDS_M)
    # la casilla del docente no se toca; sus copias e indicadores se ponen a su máximo
    assert [o for o in rec.operaciones if o.eid == manual.eid] == []
    derivados = {c.idnumber for c in copias_de(d, "TZ_M_exp")}
    derivados |= {
        n.idnumber for n in d.nodos if n.clase == "indicador" and n.formula_de in derivados
    }
    derivados |= {
        n.idnumber for n in d.nodos if n.clase == "indicador" and n.formula_de == "TZ_M_exp"
    }
    maximos = {o.idnumber: o.maximo for o in rec.operaciones if o.tipo == "fijar_maximo"}
    assert derivados and set(maximos) == derivados
    assert set(maximos.values()) == {100.0}
    final = aplicar(aula, rec.operaciones)
    otra = pasada2(d, final, huellas, CMIDS_M, a_mano=rec.a_mano)
    assert not [o for o in otra if o.idnumber in derivados]
    # y una casilla nueva se crea con 10 y sus copias también
    nueva = reconciliar(d, aula_inicial(CMIDS_M), {}, CMIDS_M)
    creadas = {o.idnumber: o.maximo for o in nueva.operaciones if o.tipo == "crear_calculado"}
    assert {creadas[i] for i in derivados} == {10.0}


def test_el_indicador_sobrante_de_un_contador_se_borra_aunque_tenga_notas() -> None:
    _, aula = montar(FP_TOPE)
    huellas = huellas_de(aula, CMIDS)
    esquema = dataclasses.replace(
        FP_TOPE,
        elementos=(
            Elemento(
                "RA1",
                "Redes",
                60.0,
                criterios=(Criterio("C1", "Uno", 50.0), Criterio("C2", "Dos", 50.0)),
            ),
            EL[1],
        ),
    )
    docs_c = [doc("a.md", 1, C1=100), doc("d.md", 1, RA2=100), doc("c.md", 2, C2=100)]
    d = deseado(esquema, docs_c, False, CARPETA)
    nuevos = {n.idnumber for n in d.nodos}
    antiguos = [
        n
        for n in aula.nodos
        if n.idnumber.startswith("TZ_I_")
        and n.padre_eid == por_id(aula, "TZ_K_RA1").eid
        and n.idnumber not in nuevos
    ]
    assert antiguos
    for n in antiguos:
        aula = con_nodo(aula, n.eid, tiene_notas=True)
    huellas = huellas_de(aula, CMIDS)
    rec = reconciliar(d, aula, huellas, CMIDS)
    borrados = {o.idnumber for o in rec.operaciones if o.tipo == "borrar"}
    assert {n.idnumber for n in antiguos} <= borrados
    assert not [a for a in rec.avisos if a[0] == "ELEMENTO_CON_NOTAS_QUITADO"]


def test_criterios_anidados_con_casilla_y_tope_convergen() -> None:
    esquema = Esquema(
        "elementos",
        (
            Elemento(
                "RA1",
                "Redes",
                60.0,
                criterios=(Criterio("C1", "Uno", 50.0), Criterio("C2", "Dos", 50.0)),
            ),
            EL[1],
        ),
        EVS,
        Final("elementos", Tope(5.0, 4.0)),
        instrumentos=(Instrumento("exp", "Exposición", 1, (("C2", 50.0),)),),
    )
    documentos = [doc("a.md", 1, C1=100), doc("d.md", 1, C2=50, RA2=50), doc("c.md", 2, RA2=50)]
    d = deseado(esquema, documentos, False, CARPETA)
    aula = aula_inicial(CMIDS)
    rec = reconciliar(d, aula, {}, CMIDS)
    aula = aplicar(aula, rec.operaciones)
    ajustes = pasada2(d, aula, {}, CMIDS, a_mano=rec.a_mano, por_cerrar=rec.por_cerrar)
    aula = aplicar(aula, ajustes)
    assert referencias_rotas(aula) == []
    assert por_id(aula, "TZ_M_exp").clase == "manual"
    huellas = huellas_de(aula, CMIDS)
    assert pasada2(d, aula, huellas, CMIDS) == ()
    otra = reconciliar(d, aula, huellas, CMIDS)
    assert otra.operaciones == () and otra.avisos == ()
