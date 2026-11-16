"""La reconciliación del calificador: pura, sin aula, con un simulador de las operaciones."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from tiza import estado
from tiza.calificacion import reconciliar as rc
from tiza.calificacion.deseado import deseado
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
    hay_anterior,
    huellas_de,
    pasada2,
    reconciliar,
)
from tiza.contenido import Documento
from tiza.publicar import CalificadorAula, NodoAula

CARPETA = Path("/curso")
EL = (Elemento("RA1", "Redes", 60.0), Elemento("RA2", "Sistemas", 40.0))
EL_CRITERIOS = (
    Elemento(
        "RA1",
        "Redes",
        60.0,
        "RA1",
        (Criterio("RA1_a", "Criterio a", 50.0, "a"), Criterio("RA1_b", "Criterio b", 50.0, "b")),
    ),
    Elemento("RA2", "Sistemas", 40.0, "RA2", regla="mas_alta"),
)
EVS = (Evaluacion("Primera", (1,)), Evaluacion("Segunda", (2,)))
EVS_CERRADA = (Evaluacion("Primera", (1,), cerrada=True), Evaluacion("Segunda", (2,)))
FP = Esquema("elementos", EL, EVS, Final("elementos"))
FP_TOPE = Esquema("elementos", EL, EVS, Final("elementos", Tope(5.0, 4.0)))
FP_CERRADA = Esquema("elementos", EL_CRITERIOS, EVS_CERRADA, Final("elementos"))
E1 = Esquema("elementos", EL_CRITERIOS, EVS, Final("elementos"))
CMIDS = {"a.md": 11, "b.md": 12, "c.md": 13}


def doc(
    ruta: str, seccion: int, *, recupera: tuple[int, ...] | None = None, **evalua: float
) -> Documento:
    return Documento(
        ruta=CARPETA / ruta,
        tipo="pagina",
        nombre=Path(ruta).stem,
        seccion=seccion,
        cuerpo="",
        html="",
        recursos=[],
        evalua=tuple(evalua.items()),
        recupera=recupera,
    )


def tarea(ruta: str, seccion: int, **evalua: float) -> Documento:
    return Documento(
        ruta=CARPETA / ruta,
        tipo="tarea",
        nombre=Path(ruta).stem,
        seccion=seccion,
        cuerpo="",
        html="",
        recursos=[],
        evalua=tuple(evalua.items()),
        evidencia="resultados",
    )


def docs() -> list[Documento]:
    return [doc("a.md", 1, RA1=60), doc("b.md", 1, RA1=40, RA2=50), doc("c.md", 2, RA2=50)]


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
        oculto=clase in ("calculado", "nota"),
    )
    base.update(kw)
    return NodoAula(**base)  # type: ignore[arg-type]


def curso() -> NodoAula:
    return nodo_aula("cg1", "", "curso", None, nombre="Curso", agregacion=10)


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
    siguiente = [max((int(n.eid[2:]) for n in aula.nodos if n.eid[2:].isdigit()), default=500)]

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
                clase = "manual"
            nodos[eid] = nodo_aula(
                eid,
                op.idnumber,
                clase,
                padre_de(op),
                nombre=op.nombre or "",
                peso=op.peso,
                coeficiente=op.coeficiente,
                sobrescrito=op.peso is not None,
                maximo=op.maximo,
                agregacion=op.agregacion if categoria else None,
                oculto=op.oculto,
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
        elif t in ("mover_manual", "mover_categoria"):
            cambiar(op, padre_eid=padre_de(op))
        elif t == "marcar_resultado":
            siguiente[0] += 1
            eid = f"ig{siguiente[0]}"
            nodos[eid] = nodo_aula(
                eid,
                "",
                "actividad",
                None,
                nombre=op.nombre or "",
                cmid=op.cmid,
                maximo=None,
            )
        elif t == "fijar_idnumber_resultado":
            cambiar(op, idnumber=op.idnumber)
        elif t == "fijar_peso":
            cambiar(op, peso=op.peso, sobrescrito=True)
        elif t == "fijar_coeficiente":
            cambiar(op, coeficiente=op.coeficiente)
        elif t == "fijar_agregacion":
            cambiar(op, agregacion=op.agregacion)
        elif t == "fijar_maximo":
            cambiar(op, maximo=op.maximo)
        elif t in ("fijar_formula", "fijar_total_curso"):
            cambiar(op, formula=op.formula)
        elif t in ("bloquear_ajeno", "bloquear_cerrada"):
            cambiar(op, bloqueado=True)
        elif t == "ocultar":
            cambiar(op, oculto=True)
        elif t == "borrar":
            del nodos[buscar(op).eid]
    return CalificadorAula(nodos=tuple(nodos.values()), decimal=aula.decimal)


def montar(esquema=FP, documentos=None, anterior=False, aula=None, huellas=None, cmids=CMIDS):
    """Una pasada completa y la segunda: devuelve (deseado, aula final, reconciliación)."""
    d = deseado(esquema, docs() if documentos is None else documentos, anterior, CARPETA)
    aula = aula or aula_inicial(cmids)
    huellas = huellas or {}
    rec = reconciliar(d, aula, huellas, cmids)
    aula = aplicar(aula, rec.operaciones)
    ajustes = pasada2(d, aula, huellas, cmids, a_mano=rec.a_mano, por_cerrar=rec.por_cerrar)
    return d, aplicar(aula, ajustes), rec


def por_tipo(operaciones, tipo: str) -> list[Operacion]:
    return [op for op in operaciones if op.tipo == tipo]


def test_montaje_completo_en_media_ponderada() -> None:
    d, final, rec = montar(FP_TOPE)
    assert not por_tipo(rec.operaciones, "fijar_peso")
    categorias = [n for n in final.nodos if n.clase == "categoria"]
    assert categorias
    for categoria in categorias:
        assert categoria.agregacion in (2, 6, 10), categoria.idnumber
    assert final.nodos == tuple(final.nodos)  # inmutable
    # La actividad real está en la vista primaria; las copias, en la del curso.
    real = next(n for n in final.nodos if n.cmid == 11)
    assert real.padre_eid is not None
    assert any(n.idnumber.startswith("TZ_C_") for n in final.nodos)
    assert any(n.idnumber == "TZ_NOTA_FINAL" for n in final.nodos)


def test_la_segunda_pasada_no_hace_nada() -> None:
    d, final, _ = montar()
    assert pasada2(d, final, {}, CMIDS) == ()


def test_los_coeficientes_no_redondos_convergen() -> None:
    documentos = [doc("a.md", 1, RA1=100), doc("b.md", 1, RA1=50)]
    d, final, rec = montar(documentos=documentos)
    con_coef = [n for n in final.nodos if n.coeficiente is not None]
    assert any(abs((n.coeficiente or 0) % 1) > 0.001 for n in con_coef)
    redondeada = CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, coeficiente=round(n.coeficiente, 1))
            if n.coeficiente is not None
            else n
            for n in final.nodos
        ),
        decimal=final.decimal,
    )
    huellas = huellas_de(redondeada, CMIDS)
    assert not [
        op
        for op in reconciliar(d, redondeada, huellas, CMIDS).operaciones
        if op.tipo == "fijar_coeficiente"
    ]
    assert pasada2(d, redondeada, huellas, CMIDS) == ()


def test_categoria_de_regla_se_crea_con_su_agregacion() -> None:
    documentos = [
        doc("a.md", 1, RA1_a=50, RA1_b=50),
        doc("b.md", 1, RA2=100),
    ]
    _, final, rec = montar(E1, documentos)
    agregaciones = {
        op.idnumber: op.agregacion for op in rec.operaciones if op.tipo == "crear_categoria"
    }
    assert agregaciones["TZ_E_RA2"] == 6
    assert agregaciones["TZ_V_1_RA2"] == 6
    assert agregaciones["TZ_E_RA1"] == 10


def test_cambiar_la_agregacion_avisa_y_la_fija() -> None:
    d = deseado(E1, [doc("a.md", 1, RA2=100)], False, CARPETA)
    aula = aula_con(
        actividad(11),
        nodo_aula("cg9", "TZ_E_RA2", "categoria", "cg1", agregacion=10, coeficiente=100.0),
    )
    rec = reconciliar(d, aula, {}, CMIDS)
    assert ("REGLA_CAMBIADA", "TZ_E_RA2") in rec.avisos
    assert any(
        op.tipo == "fijar_agregacion" and op.idnumber == "TZ_E_RA2" and op.agregacion == 6
        for op in rec.operaciones
    )


def test_la_actividad_se_coloca_y_lleva_su_coeficiente() -> None:
    d, final, rec = montar()
    (colocar,) = [op for op in rec.operaciones if op.tipo == "colocar" and op.ruta == "a.md"]
    assert colocar.padre is not None
    actividad_final = next(n for n in final.nodos if n.cmid == 11)
    assert actividad_final.padre_eid is not None
    assert actividad_final.coeficiente == 60.0


def test_evaluacion_cerrada_no_se_toca() -> None:
    d = deseado(FP_CERRADA, [doc("a.md", 1, RA1_a=100), doc("c.md", 2, RA2=100)], False, CARPETA)
    aula = aula_con(
        actividad(11),
        actividad(13),
        nodo_aula("cg9", "TZ_V_1", "categoria", "cg1", agregacion=10, bloqueado=True),
    )
    rec = reconciliar(d, aula, {}, CMIDS)
    assert ("ACTIVIDAD_EN_EVALUACION_CERRADA", "a.md") in rec.avisos
    assert any(op.tipo == "colocar" and op.ruta == "c.md" for op in rec.operaciones)
    assert not any(op.tipo == "colocar" and op.ruta == "a.md" for op in rec.operaciones)


def _aula_con_a_en_la_cerrada():
    return aula_con(
        nodo_aula("cg9", "TZ_V_1", "categoria", "cg1", agregacion=10, bloqueado=True),
        actividad(11, padre="cg9"),
        actividad(13),
    )


def test_una_actividad_que_sale_de_la_cerrada_avisa_y_no_se_mueve() -> None:
    d = deseado(FP_CERRADA, [doc("a.md", 2, RA2=100), doc("c.md", 2, RA2=100)], False, CARPETA)
    rec = reconciliar(d, _aula_con_a_en_la_cerrada(), {}, CMIDS)
    assert ("SALE_DE_EVALUACION_CERRADA", "a.md") in rec.avisos
    assert "a.md" in rec.sin_colocar
    assert not any(op.tipo == "colocar" and op.ruta == "a.md" for op in rec.operaciones)


def test_una_actividad_que_sigue_en_la_cerrada_no_avisa_de_que_sale() -> None:
    d = deseado(FP_CERRADA, [doc("a.md", 1, RA1_a=100), doc("c.md", 2, RA2=100)], False, CARPETA)
    rec = reconciliar(d, _aula_con_a_en_la_cerrada(), {}, CMIDS)
    assert not any(codigo == "SALE_DE_EVALUACION_CERRADA" for codigo, _ in rec.avisos)


def test_pasar_una_seccion_entre_dos_abiertas_no_avisa_de_que_sale() -> None:
    d = deseado(E1, [doc("a.md", 2, RA2=100), doc("c.md", 2, RA2=100)], False, CARPETA)
    aula = aula_con(actividad(11), actividad(13))
    rec = reconciliar(d, aula, {}, CMIDS)
    assert not any(codigo == "SALE_DE_EVALUACION_CERRADA" for codigo, _ in rec.avisos)


def test_la_cerrada_se_bloquea_al_final_de_la_segunda_pasada() -> None:
    d = deseado(FP_CERRADA, [doc("a.md", 1, RA1_a=100)], False, CARPETA)
    aula = aula_con(actividad(11))
    rec = reconciliar(d, aula, {}, CMIDS)
    assert "TZ_V_1" in rec.por_cerrar
    final = aplicar(aula, rec.operaciones)
    ajustes = pasada2(d, final, {}, CMIDS, a_mano=rec.a_mano, por_cerrar=rec.por_cerrar)
    assert any(op.tipo == "bloquear_cerrada" and op.idnumber == "TZ_V_1" for op in ajustes)


def test_el_total_del_curso_copia_la_nota_final_dividida_por_10() -> None:
    d, _, rec = montar(FP_TOPE)
    total = por_tipo(rec.operaciones, "fijar_total_curso")
    assert total and total[0].formula == "=[[TZ_NOTA_FINAL]]/10"
    d2, _, rec2 = montar(FP)
    total2 = por_tipo(rec2.operaciones, "fijar_total_curso")
    assert total2 and total2[0].formula is None


def test_la_nota_final_se_crea_oculta_sobre_100() -> None:
    _, _, rec = montar(FP_TOPE)
    (op,) = [
        op
        for op in rec.operaciones
        if op.tipo == "crear_calculado" and op.idnumber == "TZ_NOTA_FINAL"
    ]
    assert op.maximo == 100.0 and op.oculto is True


def test_las_copias_y_calculados_nacen_ocultos() -> None:
    d = deseado(
        E1,
        [tarea("a.md", 1, RA1_a=100), tarea("b.md", 1, RA1_b=100)],
        False,
        CARPETA,
    )
    rec = reconciliar(d, aula_inicial(), {}, CMIDS, resultados={"RA1_a": 90, "RA1_b": 91})
    ocultos = {op.idnumber for op in rec.operaciones if op.tipo == "crear_calculado" and op.oculto}
    assert any(i.startswith("TZ_C_") for i in ocultos)
    assert any(i.startswith("TZ_R_") for i in ocultos)


def test_resultados_se_marcan_y_se_reconoce_su_calculo() -> None:
    d = deseado(E1, [tarea("a.md", 1, RA1_a=100), tarea("b.md", 1, RA1_b=100)], False, CARPETA)
    aula = aula_con(actividad(11), actividad(12))
    rec = reconciliar(d, aula, {}, CMIDS, resultados={"RA1_a": 91, "RA1_b": 92})
    assert len(por_tipo(rec.operaciones, "marcar_resultado")) == 2
    assert por_tipo(rec.operaciones, "marcar_resultado")[0].cmid == 11


def test_el_calculo_del_resultado_es_sobre_100() -> None:
    d = deseado(E1, [tarea("a.md", 1, RA1_a=100)], False, CARPETA)
    resultado = next(n for n in d.nodos if n.clase == "resultado")
    calculado = next(n for n in d.nodos if n.clase == "resultado_calc")
    aula = aula_con(
        actividad(11),
        nodo_aula("ig90", resultado.idnumber, "calculado", "cg1", maximo=100.0),
        nodo_aula(
            "ig91",
            calculado.idnumber,
            "calculado",
            "cg1",
            maximo=100.0,
            formula="=([[TZ_O_x]]-1)/4*10",
        ),
    )
    rec = reconciliar(d, aula, {}, CMIDS, resultados={"RA1_a": 90})
    formulas = [
        op.formula
        for op in rec.operaciones
        if op.tipo == "fijar_formula" and op.idnumber == calculado.idnumber
    ]
    assert formulas == [f"=([[{resultado.idnumber}]]-1)/4*100"]


def test_huella_incluye_el_coeficiente() -> None:
    aula = aula_con(
        actividad(11, padre="cg9"),
        nodo_aula("cg9", "TZ_V_1", "categoria", "cg1", agregacion=10, coeficiente=60.0),
    )
    huellas = huellas_de(aula, CMIDS)
    otra = aula_con(
        actividad(11, padre="cg9"),
        nodo_aula("cg9", "TZ_V_1", "categoria", "cg1", agregacion=10, coeficiente=40.0),
    )
    assert huellas["TZ_V_1"] != huellas_de(otra, CMIDS)["TZ_V_1"]


def test_lo_sobrante_con_notas_se_queda_a_coeficiente_cero() -> None:
    d = deseado(FP, [doc("a.md", 1, RA1=100)], False, CARPETA)
    aula = aula_con(
        actividad(11),
        nodo_aula(
            "cg9",
            "TZ_E_RA3",
            "categoria",
            "cg1",
            agregacion=10,
            coeficiente=100.0,
            tiene_notas=True,
        ),
    )
    rec = reconciliar(d, aula, {}, CMIDS)
    assert not any(op.tipo == "borrar" and op.idnumber == "TZ_E_RA3" for op in rec.operaciones)
    assert any(
        op.tipo == "fijar_coeficiente" and op.idnumber == "TZ_E_RA3" and op.coeficiente == 0.0
        for op in rec.operaciones
    )
    assert ("ELEMENTO_CON_NOTAS_QUITADO", "TZ_E_RA3") in rec.avisos


def test_lo_sobrante_sin_notas_se_borra() -> None:
    d = deseado(FP, [doc("a.md", 1, RA1=100)], False, CARPETA)
    aula = aula_con(
        actividad(11),
        nodo_aula("cg9", "TZ_E_RA3", "categoria", "cg1", agregacion=10, coeficiente=100.0),
    )
    rec = reconciliar(d, aula, {}, CMIDS)
    assert any(op.tipo == "borrar" and op.idnumber == "TZ_E_RA3" for op in rec.operaciones)


def test_actividad_que_deja_de_contar_se_queda_a_coeficiente_cero() -> None:
    d = deseado(FP, [doc("a.md", 1, RA1=100)], False, CARPETA)
    aula = aula_con(
        actividad(11),
        actividad(12, padre="cg9"),
        nodo_aula("cg9", "TZ_V_1_RA1", "categoria", "cg1", agregacion=10, coeficiente=100.0),
    )
    rec = reconciliar(d, aula, {}, CMIDS)
    assert any(
        op.tipo == "fijar_coeficiente" and op.idnumber == "TZ_A12" and op.coeficiente == 0.0
        for op in rec.operaciones
    ) or any(
        op.tipo == "fijar_coeficiente" and op.eid == "ig112" and op.coeficiente == 0.0
        for op in rec.operaciones
    )


def test_una_casilla_manual_se_crea_y_su_copia_tambien() -> None:
    esquema = Esquema(
        "elementos",
        (Elemento("RA1", "Redes", 100.0),),
        (Evaluacion("Primera", (1,)),),
        Final("elementos"),
        instrumentos=(Instrumento("EX", "Examen oral", 1, (("RA1", 100.0),)),),
    )
    d, final, rec = montar(esquema, [])
    assert any(op.tipo == "crear_calculado" and op.idnumber == "TZ_M_EX" for op in rec.operaciones)
    assert any(n.idnumber == "TZ_M_EX" and n.clase == "manual" for n in final.nodos)


def test_a_mano_no_se_toca() -> None:
    d, final, rec = montar()
    idnumber = "TZ_V_1_RA1"
    aula = final
    huella = huellas_de(aula, CMIDS)
    cambiada = CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, coeficiente=99.0) if n.idnumber == idnumber else n
            for n in aula.nodos
        ),
        decimal=aula.decimal,
    )
    rec2 = reconciliar(d, cambiada, huella, CMIDS)
    assert ("CAMBIADO_A_MANO", idnumber) in rec2.avisos
    assert not any(
        op.tipo == "fijar_coeficiente" and op.idnumber == idnumber for op in rec2.operaciones
    )


def test_hay_anterior() -> None:
    assert not hay_anterior(aula_con(actividad(11)))
    assert hay_anterior(
        aula_con(actividad(11), nodo_aula("cg9", "AJENA", "categoria", "cg1", agregacion=13))
    )


@pytest.mark.parametrize(
    "nodo",
    [
        nodo_aula("ig90", "TZ_NOTAS", "calculado", "cg1"),
        nodo_aula("ig91", "TZ_K_TIZA", "calculado", "cg1"),
        nodo_aula("cg9", "TZ_AG_E_RA1", "categoria", "cg1", agregacion=6),
        nodo_aula("cg10", "TZ_RP_E_1_RA1", "categoria", "cg1", agregacion=6),
        nodo_aula("ig92", "TZ_F_abc", "calculado", "cg1"),
    ],
)
def test_el_arbol_antiguo_se_detecta(nodo) -> None:
    assert rc.es_calificador_antiguo(aula_con(nodo))


def test_el_arbol_nuevo_no_se_confunde_con_el_antiguo() -> None:
    aula = aula_con(
        actividad(11, padre="cg9"),
        nodo_aula("cg9", "TZ_V_1_RA1", "categoria", "cg1", agregacion=10),
        nodo_aula("ig90", "TZ_CR_abc", "calculado", "cg9", formula="=[[TZ_A11]]"),
        nodo_aula("ig91", "TZ_C_abc", "calculado", "cg1", formula="=[[TZ_V_1_RA1]]"),
    )
    assert not rc.es_calificador_antiguo(aula)


def test_el_arbol_nuevo_con_recuperacion_en_mas_alta_no_se_confunde() -> None:
    aula = aula_con(
        actividad(11, padre="cg9"),
        nodo_aula("cg9", "TZ_V_1_RA1", "categoria", "cg1", agregacion=10),
        nodo_aula("cg10", "TZ_E_RA2", "categoria", "cg1", agregacion=6),
        actividad(12, padre="cg10"),
        nodo_aula("ig91", "TZ_C_abc", "calculado", "cg10", formula="=[[TZ_V_1_RA2]]"),
    )
    assert not rc.es_calificador_antiguo(aula)


def test_el_arbol_antiguo_con_copia_y_actividades_se_detecta() -> None:
    aula = aula_con(
        actividad(11, padre="cg9"),
        nodo_aula("cg9", "TZ_E_RA1", "categoria", "cg1", agregacion=13),
        nodo_aula("ig90", "TZ_C_abc", "calculado", "cg9", formula="=[[TZ_A11]]"),
    )
    assert rc.es_calificador_antiguo(aula)


def test_la_final_montada_se_lee_de_lo_que_cuelga_de_tz_final() -> None:
    elementos = aula_con(
        nodo_aula("cg9", "TZ_FINAL", "categoria", "cg1", agregacion=10),
        nodo_aula("cg10", "TZ_VISTA", "contenedor", "cg1", agregacion=10),
        nodo_aula("cg11", "TZ_E_RA1", "categoria", "cg9", agregacion=10),
        nodo_aula("cg12", "TZ_V_1", "categoria", "cg10", agregacion=10),
    )
    evaluaciones = aula_con(
        nodo_aula("cg9", "TZ_FINAL", "categoria", "cg1", agregacion=10),
        nodo_aula("cg10", "TZ_VISTA", "contenedor", "cg1", agregacion=10),
        nodo_aula("cg11", "TZ_V_1", "categoria", "cg9", agregacion=10),
        nodo_aula("cg12", "TZ_E_RA1", "categoria", "cg10", agregacion=10),
    )
    assert rc.final_montada(elementos) == "elementos"
    assert rc.final_montada(evaluaciones) == "evaluaciones"


def test_la_final_montada_no_se_decide_con_un_montaje_ambiguo() -> None:
    assert rc.final_montada(aula_inicial()) is None
    vacia = aula_con(nodo_aula("cg9", "TZ_FINAL", "categoria", "cg1", agregacion=10))
    assert rc.final_montada(vacia) is None
    sin_final = aula_con(nodo_aula("cg9", "TZ_V_1", "categoria", "cg1", agregacion=10))
    assert rc.final_montada(sin_final) is None
    mezclada = aula_con(
        nodo_aula("cg9", "TZ_FINAL", "categoria", "cg1", agregacion=10),
        nodo_aula("cg11", "TZ_E_RA1", "categoria", "cg9", agregacion=10),
        nodo_aula("cg12", "TZ_V_1", "categoria", "cg9", agregacion=10),
    )
    assert rc.final_montada(mezclada) is None


def test_la_final_montada_ignora_lo_que_no_es_de_tiza() -> None:
    aula = aula_con(
        nodo_aula("cg9", "TZ_FINAL", "categoria", "cg1", agregacion=10),
        nodo_aula("cg11", "", "categoria", "cg9", agregacion=10, nombre="Del docente"),
        nodo_aula("cg12", "TZ_V_1", "categoria", "cg9", agregacion=10),
    )
    assert rc.final_montada(aula) == "evaluaciones"


def test_pasada2_solo_da_ajustes() -> None:
    d, final, rec = montar()
    assert pasada2(d, final, {}, CMIDS) == ()
    cambiada = CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, coeficiente=1.0) if n.idnumber == "TZ_V_1_RA1" else n
            for n in final.nodos
        ),
        decimal=final.decimal,
    )
    ajustes = pasada2(d, cambiada, {}, CMIDS)
    assert any(op.tipo == "fijar_coeficiente" for op in ajustes)


def test_borrar_los_hijos_antes_que_los_padres() -> None:
    d = deseado(FP, [doc("a.md", 1, RA1=100)], False, CARPETA)
    aula = aula_con(
        actividad(11),
        nodo_aula("cg9", "TZ_E_RA3", "categoria", "cg1", agregacion=10),
        nodo_aula("cg10", "TZ_E_RA3_x", "categoria", "cg9", agregacion=6),
    )
    rec = reconciliar(d, aula, {}, CMIDS)
    borrados = [op.idnumber for op in rec.operaciones if op.tipo == "borrar"]
    if "TZ_E_RA3" in borrados and "TZ_E_RA3_x" in borrados:
        assert borrados.index("TZ_E_RA3_x") < borrados.index("TZ_E_RA3")


# --------------------------------------------------------------------------- #
# La retirada del árbol de la generación anterior
# --------------------------------------------------------------------------- #


def _arbol_antiguo(*, con_notas: bool = True) -> CalificadorAula:
    """El árbol de la 0.46 abreviado: una casilla tecleada, una cerrada y restos varios.

    Con ``con_notas=False`` no hay ``TZ_NOTAS`` ni ``TZ_K_TIZA``: el único delator es
    ``TZ_AG_E_RA1``.
    """
    delatores = (
        (
            nodo_aula("cg51", "TZ_NOTAS", "categoria", "cg50", agregacion=13),
            nodo_aula("cg52", "TZ_K_TIZA", "categoria", "cg51", agregacion=10),
            nodo_aula("ig54", "TZ_F_abc", "calculado", "cg51", tiene_notas=True, formula="=1"),
            nodo_aula("ig56", "TZ_M_OTRA", "manual", "cg51"),
        )
        if con_notas
        else (nodo_aula("cg60", "TZ_AG_E_RA1", "categoria", "cg50", agregacion=6),)
    )
    return aula_con(
        nodo_aula("cg50", "TZ_TIZA", "categoria", "cg1", agregacion=13),
        nodo_aula("cg53", "TZ_V_1", "categoria", "cg50", agregacion=10, bloqueado=True),
        nodo_aula("cg57", "TZ_V_1_RA1", "categoria", "cg53", agregacion=10, bloqueado=True),
        actividad(11, padre="cg53"),
        nodo_aula("ig55", "TZ_M_EXAM", "manual", "cg53", tiene_notas=True),
        nodo_aula("ig58", "TZ_O_abc", "manual", "cg53"),
        nodo_aula("ig59", "", "manual", "cg50", nombre="Del docente"),
        *delatores,
    )


def _delata(idnumber: str) -> bool:
    return idnumber in ("TZ_NOTAS", "TZ_K_TIZA") or idnumber.startswith(
        ("TZ_AG_", "TZ_RP_", "TZ_F_")
    )


def test_la_retirada_conserva_lo_tecleado() -> None:
    aula = _arbol_antiguo()
    r = rc.retirada_antiguo(aula)

    assert {op.idnumber for op in r.operaciones} == {
        "TZ_F_abc",
        "TZ_M_OTRA",
        "TZ_TIZA",
        "TZ_NOTAS",
        "TZ_K_TIZA",
        "TZ_V_1",
        "TZ_V_1_RA1",
    }
    assert all(op.tipo == "borrar" for op in r.operaciones)
    assert all(op.eid is not None and op.item_id is not None for op in r.operaciones)
    borrados = {op.eid for op in r.operaciones}
    assert borrados.isdisjoint({"ig55", "ig58", "ig59", "ig111", "cg1"})
    assert [n.idnumber for n in r.conservadas] == ["TZ_M_EXAM"]
    assert [n.idnumber for n in r.cerradas] == ["TZ_V_1"]


def test_la_retirada_borra_primero_los_elementos_y_de_entro_afuera() -> None:
    r = rc.retirada_antiguo(_arbol_antiguo())
    ids = [op.idnumber for op in r.operaciones]

    elementos = {"TZ_F_abc", "TZ_M_OTRA"}
    categorias = {"TZ_TIZA", "TZ_NOTAS", "TZ_K_TIZA", "TZ_V_1", "TZ_V_1_RA1"}
    # Dentro de cada tanda (lo que no delata y lo que delata), los elementos van antes que
    # las categorías: borrar una categoría sube sus hijos y no se quiere reordenar dos veces.
    for delator in (False, True):
        ultimo_elemento = max(
            (ids.index(idn) for idn in elementos if _delata(idn) == delator), default=-1
        )
        primera_categoria = min(
            (ids.index(idn) for idn in categorias if _delata(idn) == delator), default=len(ids)
        )
        assert ultimo_elemento < primera_categoria
    assert ids.index("TZ_V_1_RA1") < ids.index("TZ_V_1")


@pytest.mark.parametrize(
    ("con_notas", "ultima"),
    [(True, "TZ_NOTAS"), (False, "TZ_AG_E_RA1")],
)
def test_la_retirada_deja_un_delator_para_el_final(con_notas: bool, ultima: str) -> None:
    r = rc.retirada_antiguo(_arbol_antiguo(con_notas=con_notas))
    ids = [op.idnumber for op in r.operaciones]

    assert ids[-1] == ultima
    assert _delata(ids[-1])
    primera_delatora = next(i for i, idn in enumerate(ids) if _delata(idn))
    assert all(_delata(idn) for idn in ids[primera_delatora:])


def test_el_aula_tras_la_retirada_sube_lo_que_queda_al_curso() -> None:
    aula = _arbol_antiguo()
    r = rc.retirada_antiguo(aula)
    despues = rc.aula_tras_retirada(aula, r)

    borrados = {op.eid for op in r.operaciones}
    assert borrados.isdisjoint({n.eid for n in despues.nodos})
    por_idnumber = {n.idnumber: n for n in despues.nodos if n.idnumber}
    assert por_idnumber["TZ_M_EXAM"].padre_eid == "cg1"
    assert por_idnumber["TZ_O_abc"].padre_eid == "cg1"
    assert next(n for n in despues.nodos if n.eid == "ig59").padre_eid == "cg1"
    actividad_11 = next(n for n in despues.nodos if n.cmid == 11)
    assert actividad_11.padre_eid == "cg1"
    assert not rc.es_calificador_antiguo(despues)
    assert despues.decimal == aula.decimal


# --------------------------------------------------------------------------- #
# Lo conservado a mano, los huérfanos y la pregunta
# --------------------------------------------------------------------------- #


def _cambiar_nodo(aula: CalificadorAula, idnumber: str, **kw) -> CalificadorAula:
    return CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, **kw) if n.idnumber == idnumber else n for n in aula.nodos
        ),
        decimal=aula.decimal,
    )


def _con_huellas_cambiadas(d: rc.Deseado, final: CalificadorAula, idnumber: str, **kw):
    """Un aula con el nodo cambiado y las huellas de lo que montó tiza antes del cambio."""
    cambiada = _cambiar_nodo(final, idnumber, **kw)
    guardadas = huellas_de(final, CMIDS)
    conservados = {
        idnumber: estado.Conservado(
            huellas_de(cambiada, CMIDS)[idnumber], rc.huellas_deseadas(d, CMIDS)[idnumber]
        )
    }
    return cambiada, guardadas, conservados


def test_un_conservado_sin_cambios_no_avisa_ni_planifica() -> None:
    d, final, _ = montar(FP)
    cambiada, guardadas, conservados = _con_huellas_cambiadas(
        d, final, "TZ_V_1_RA1", coeficiente=70.0
    )
    rec = reconciliar(d, cambiada, guardadas, CMIDS, conservados=conservados)
    assert rec.a_mano == frozenset()
    assert rec.conservados == frozenset({"TZ_V_1_RA1"})
    assert not any(
        codigo == "CAMBIADO_A_MANO" and clave == "TZ_V_1_RA1" for codigo, clave in rec.avisos
    )
    assert not any(op.idnumber == "TZ_V_1_RA1" for op in rec.operaciones)
    assert rec.cambios_a_mano == ()


def test_un_conservado_vuelve_a_mano_si_cambia_el_yaml_de_ese_nodo() -> None:
    d, final, _ = montar(FP)
    cambiada, guardadas, conservados = _con_huellas_cambiadas(
        d, final, "TZ_V_1_RA1", coeficiente=70.0
    )
    nodos = tuple(
        dataclasses.replace(n, peso=65.0) if n.idnumber == "TZ_V_1_RA1" else n for n in d.nodos
    )
    otro = dataclasses.replace(d, nodos=nodos)
    rec = reconciliar(otro, cambiada, guardadas, CMIDS, conservados=conservados)
    assert "TZ_V_1_RA1" in rec.a_mano
    assert rec.conservados == frozenset()
    assert any(
        codigo == "CAMBIADO_A_MANO" and clave == "TZ_V_1_RA1" for codigo, clave in rec.avisos
    )
    (cambio,) = rec.cambios_a_mano
    assert cambio.tipo == "peso"
    assert cambio.antes == 70.0
    assert cambio.despues == 65.0


def test_un_conservado_vuelve_a_mano_si_el_aula_cambia_otra_vez() -> None:
    d, final, _ = montar(FP)
    _, guardadas, conservados = _con_huellas_cambiadas(d, final, "TZ_V_1_RA1", coeficiente=70.0)
    otra = _cambiar_nodo(final, "TZ_V_1_RA1", coeficiente=80.0)
    rec = reconciliar(d, otra, guardadas, CMIDS, conservados=conservados)
    assert "TZ_V_1_RA1" in rec.a_mano
    assert rec.conservados == frozenset()
    assert rec.cambios_a_mano[0].antes == 80.0
    assert rec.cambios_a_mano[0].despues == 60.0


def test_sobrescribir_saca_la_clave_de_a_mano_y_la_vuelve_a_poner() -> None:
    d, final, _ = montar(FP)
    cambiada = _cambiar_nodo(final, "TZ_V_1_RA1", coeficiente=70.0)
    guardadas = huellas_de(final, CMIDS)
    rec = reconciliar(d, cambiada, guardadas, CMIDS, sobrescribir={"TZ_V_1_RA1"})
    assert "TZ_V_1_RA1" not in rec.a_mano
    assert not any(
        codigo == "CAMBIADO_A_MANO" and clave == "TZ_V_1_RA1" for codigo, clave in rec.avisos
    )
    assert any(
        op.tipo == "fijar_coeficiente" and op.idnumber == "TZ_V_1_RA1" and op.coeficiente == 60.0
        for op in rec.operaciones
    )


def _sin_la_categoria(aula: CalificadorAula, idnumber: str) -> CalificadorAula:
    """Lo que hace Moodle al borrar una categoría: sus hijos suben a su padre."""
    borrada = next(n for n in aula.nodos if n.idnumber == idnumber)
    return CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, padre_eid=borrada.padre_eid)
            if n.padre_eid == borrada.eid and n.eid != borrada.eid
            else n
            for n in aula.nodos
            if n.eid != borrada.eid
        ),
        decimal=aula.decimal,
    )


def test_los_huerfanos_de_una_categoria_borrada_no_son_cambios_a_mano() -> None:
    documentos = [
        doc("a.md", 1, RA1_a=60),
        doc("b.md", 1, RA1_b=40, RA2=50),
        doc("c.md", 2, RA2=50),
    ]
    d, final, _ = montar(E1, documentos)
    guardadas = huellas_de(final, CMIDS)
    sin_categoria = _sin_la_categoria(final, "TZ_V_1_RA1")
    rec = reconciliar(d, sin_categoria, guardadas, CMIDS)
    assert rec.huerfanos == frozenset({"TZ_V_1_RA1_a", "TZ_V_1_RA1_b"})
    assert rec.huerfanos.isdisjoint(rec.a_mano)
    assert not any(
        codigo == "CAMBIADO_A_MANO" and clave in rec.huerfanos for codigo, clave in rec.avisos
    )


def test_un_cambio_de_verdad_de_un_hijo_de_una_categoria_borrada_sigue_a_mano() -> None:
    documentos = [
        doc("a.md", 1, RA1_a=60),
        doc("b.md", 1, RA1_b=40, RA2=50),
        doc("c.md", 2, RA2=50),
    ]
    d, final, _ = montar(E1, documentos)
    guardadas = huellas_de(final, CMIDS)
    sin_categoria = _sin_la_categoria(final, "TZ_V_1_RA1")
    sin_categoria = _cambiar_nodo(sin_categoria, "TZ_V_1_RA1_a", coeficiente=99.0)
    rec = reconciliar(d, sin_categoria, guardadas, CMIDS)
    assert "TZ_V_1_RA1_a" in rec.a_mano
    assert "TZ_V_1_RA1_a" not in rec.huerfanos
    assert any(
        codigo == "CAMBIADO_A_MANO" and clave == "TZ_V_1_RA1_a" for codigo, clave in rec.avisos
    )
    cambio = next(c for c in rec.cambios_a_mano if c.clave == "TZ_V_1_RA1_a")
    assert cambio.tipo == "peso"
    assert cambio.antes == 99.0
    assert cambio.despues == 50.0


def test_los_tipos_de_cambio_a_mano() -> None:
    d, final, _ = montar(FP)
    guardadas = huellas_de(final, CMIDS)
    # Un nombre de categoría.
    renombrada = _cambiar_nodo(final, "TZ_V_1_RA1", nombre="Otro nombre")
    rec = reconciliar(d, renombrada, guardadas, CMIDS)
    (cambio,) = rec.cambios_a_mano
    assert (cambio.tipo, cambio.nombre) == ("nombre", "Redes")
    # Una fórmula de calculado.
    calculado = next(n for n in final.nodos if n.idnumber.startswith("TZ_C_"))
    con_formula = _cambiar_nodo(final, calculado.idnumber, formula="=1")
    rec = reconciliar(d, con_formula, guardadas, CMIDS)
    cambio = next(c for c in rec.cambios_a_mano if c.clave == calculado.idnumber)
    assert cambio.tipo == "formula"
    # Una actividad movida de criterio.
    actividad = next(n for n in final.nodos if n.cmid == 11)
    destino = next(n for n in final.nodos if n.clase == "categoria" and n.idnumber == "TZ_V_1_RA2")
    movida = CalificadorAula(
        nodos=tuple(
            dataclasses.replace(n, padre_eid=destino.eid) if n.eid == actividad.eid else n
            for n in final.nodos
        ),
        decimal=final.decimal,
    )
    rec = reconciliar(d, movida, guardadas, CMIDS)
    cambio = next(c for c in rec.cambios_a_mano if c.clave == "TZ_A11")
    assert cambio.tipo == "padre"
    assert cambio.padre_antes == "TZ_V_1_RA2"
    assert cambio.padre_despues == "TZ_V_1_RA1"


def test_la_huella_deseada_coincide_con_la_del_aula_recien_montada() -> None:
    for esquema, documentos in (
        (FP, None),
        (FP_TOPE, None),
        (
            E1,
            [doc("a.md", 1, RA1_a=60), doc("b.md", 1, RA1_b=40, RA2=50), doc("c.md", 2, RA2=50)],
        ),
    ):
        d, final, _ = montar(esquema, documentos)
        curso_mp = next(n for n in final.nodos if n.clase == "curso").agregacion == 10
        deseadas = rc.huellas_deseadas(d, CMIDS, curso_mp=curso_mp)
        guardadas = huellas_de(final, CMIDS)
        assert deseadas == guardadas


def test_la_huella_deseada_de_un_resultado_coincide_con_la_del_aula() -> None:
    d = deseado(
        E1,
        [tarea("a.md", 1, RA1_a=100), tarea("b.md", 1, RA1_b=100)],
        False,
        CARPETA,
    )
    aula = aula_inicial()
    rec = reconciliar(d, aula, {}, CMIDS, resultados={"RA1_a": 90, "RA1_b": 91})
    final = aplicar(aula, rec.operaciones)
    final = aplicar(
        final,
        pasada2(d, final, {}, CMIDS, a_mano=rec.a_mano, resultados={"RA1_a": 90, "RA1_b": 91}),
    )
    curso_mp = next(n for n in final.nodos if n.clase == "curso").agregacion == 10
    assert rc.huellas_deseadas(d, CMIDS, curso_mp=curso_mp) == huellas_de(final, CMIDS)


def test_la_categoria_borrada_se_recrea_y_se_lleva_dentro_sus_huerfanos() -> None:
    documentos = [
        doc("a.md", 1, RA1_a=60),
        doc("b.md", 1, RA1_b=40, RA2=50),
        doc("c.md", 2, RA2=50),
    ]
    d, final, _ = montar(E1, documentos)
    guardadas = huellas_de(final, CMIDS)
    sin_categoria = _sin_la_categoria(final, "TZ_V_1_RA1")
    rec = reconciliar(d, sin_categoria, guardadas, CMIDS)
    assert ("CATEGORIA_RECREADA", "TZ_V_1_RA1") in rec.avisos
    assert any(
        op.tipo == "crear_categoria" and op.idnumber == "TZ_V_1_RA1" for op in rec.operaciones
    )
    movidas = {op.idnumber for op in rec.operaciones if op.tipo == "mover_categoria"}
    assert movidas == {"TZ_V_1_RA1_a", "TZ_V_1_RA1_b"}
    arreglada = aplicar(sin_categoria, rec.operaciones)
    arreglada = aplicar(
        arreglada,
        pasada2(d, arreglada, guardadas, CMIDS, a_mano=rec.a_mano, por_cerrar=rec.por_cerrar),
    )
    por_id = {n.idnumber: n for n in arreglada.nodos if n.idnumber}
    assert por_id["TZ_V_1_RA1_a"].padre_eid == por_id["TZ_V_1_RA1"].eid
    assert por_id["TZ_V_1_RA1_b"].padre_eid == por_id["TZ_V_1_RA1"].eid
    assert por_id["TZ_V_1_RA1"].padre_eid == por_id["TZ_V_1"].eid


def test_no_se_recrea_una_categoria_borrada_dentro_de_una_cerrada() -> None:
    documentos = [
        doc("a.md", 1, RA1_a=60),
        doc("b.md", 1, RA1_b=40, RA2=50),
        doc("c.md", 2, RA2=50),
    ]
    d, final, _ = montar(FP_CERRADA, documentos)
    assert next(n for n in final.nodos if n.idnumber == "TZ_V_1").bloqueado
    guardadas = huellas_de(final, CMIDS)
    sin_categoria = _sin_la_categoria(final, "TZ_V_1_RA1")
    rec = reconciliar(d, sin_categoria, guardadas, CMIDS)
    assert ("CATEGORIA_BORRADA_EN_CERRADA", "TZ_V_1_RA1") in rec.avisos
    assert not any(
        op.tipo in ("crear_categoria", "mover_categoria")
        and (op.idnumber or "").startswith("TZ_V_1_RA1")
        for op in rec.operaciones
    )
