"""El plan puro de la ponderación: referencias, huellas, porcentajes y operaciones. Sin red ni aula."""

from __future__ import annotations

import dataclasses
import random
from pathlib import Path

import pytest

from tiza.calificacion.ponderacion import (
    ArbolPonderacion,
    NodoPonderacion,
    OperacionPonderacion,
    PlanPonderacion,
    huella_nodo,
    planificar,
    referencia_de,
)
from tiza.calificacion.ponderacion_esquema import (
    ElementoPonderacion,
    EntradaPonderacion,
    ErrorPonderacion,
    EsquemaPonderacion,
    Referencia,
)
from tiza.contenido import Documento
from tiza.estructura import Estructura

PRIMERA = "PRIMERA EVALUACIÓN"
FICHEROS = (
    ("1eva/test-1-hardware.md", "cuestionario", "Test 1", 16.0, 11),
    ("1eva/test-2-procesador-textos.md", "cuestionario", "Test 2", 8.0, 12),
    ("1eva/test-3-maquinas-virtuales-linux.md", "cuestionario", "Test 3", 6.0, 13),
    ("1eva/tarea-sheets-monta-tu-pc.html", "tarea", "Monta tu PC", 45.0, 14),
)
REF_FICHEROS = tuple(f"fichero:{ruta}" for ruta, *_ in FICHEROS)


# --- constructores sintéticos ---


def nodo(
    eid: str,
    nombre: str,
    *,
    clase: str = "manual",
    padre: str | None = "cg1",
    cmid: int | None = None,
    bloqueado: bool = False,
    tiene_notas: bool = False,
    agregacion: int | None = None,
    solo: bool | None = None,
    opciones: tuple[int, ...] | None = None,
    coeficiente: float | None = None,
    peso: float | None = 1.0,
    sobrescrito: bool = False,
    maximo: float | None = 100.0,
    idnumber: str = "",
) -> NodoPonderacion:
    return NodoPonderacion(
        eid=eid,
        item_id=int(eid[2:]),
        idnumber=idnumber,
        clase=clase,
        nombre=nombre,
        padre_eid=padre,
        cmid=cmid,
        tipo=None,
        bloqueado=bloqueado,
        tiene_notas=tiene_notas,
        agregacion=agregacion,
        solo_no_vacias=solo,
        opciones_agregacion=opciones,
        coeficiente=coeficiente,
        peso=peso,
        sobrescrito=sobrescrito,
        maximo=maximo,
        oculto=False,
    )


def raiz() -> NodoPonderacion:
    return nodo("cg1", "Curso", clase="curso", padre=None, agregacion=13, peso=None)


def categoria(eid: str, nombre: str, **campos) -> NodoPonderacion:
    campos.setdefault("agregacion", 10)
    campos.setdefault("solo", True)
    campos.setdefault("opciones", (0, 10, 11, 12, 2, 4, 6, 8, 13))
    return nodo(eid, nombre, clase="categoria", **campos)


def arbol(*nodos: NodoPonderacion) -> ArbolPonderacion:
    return ArbolPonderacion(2, (raiz(), *nodos), ",")


def estructura() -> Estructura:
    return Estructura.de_dicts(
        [
            {
                "numero": 1,
                "nombre": PRIMERA,
                "id": 10,
                "modulos": [
                    {"cmid": cmid, "nombre": nombre, "tipo": tipo}
                    for _, tipo, nombre, _, cmid in FICHEROS
                ],
            },
            {"numero": 2, "nombre": "SEGUNDA", "id": 11, "modulos": []},
        ]
    )


def fichero(ruta: str, tipo: str, nombre: str, **pesos: float) -> ElementoPonderacion:
    documento = Documento(
        ruta=Path(ruta),
        tipo=tipo,
        nombre=nombre,
        seccion=1,
        cuerpo="",
        html="",
        recursos=[],
    )
    return ElementoPonderacion(
        Referencia("fichero", ruta), pesos.get("peso"), pesos.get("porcentaje"), documento, ruta
    )


def elemento(clase: str, nombre: str, **campos) -> ElementoPonderacion:
    referencia = Referencia(clase, nombre, campos.pop("tipo", None), campos.pop("seccion", None))
    return ElementoPonderacion(referencia, campos.get("peso"), campos.get("porcentaje"), None, "x")


def examen(**cambios) -> EntradaPonderacion:
    campos = dict(
        nueva=True,
        id="EXAMEN_1EV",
        nombre="Examen 1.ª evaluación",
        dentro_de=PRIMERA,
        calculo="media_ponderada",
        solo_no_vacias=False,
        categoria=None,
        elementos=tuple(fichero(r, t, n, peso=p) for r, t, n, p, _ in FICHEROS),
        ruta="ponderacion[0]",
    )
    campos.update(cambios)
    return EntradaPonderacion(**campos)


def existente(
    nombre: str, elementos: tuple[ElementoPonderacion, ...], *, calculo=None, solo=None, n: int = 1
) -> EntradaPonderacion:
    return EntradaPonderacion(
        False, None, None, None, calculo, solo, nombre, elementos, f"ponderacion[{n}]"
    )


def sobre_examen(porcentaje: float = 30.0) -> EntradaPonderacion:
    return existente(PRIMERA, (elemento("categoria", "EXAMEN_1EV", porcentaje=porcentaje),))


def esquema_e1(porcentaje: float = 30.0) -> EsquemaPonderacion:
    return EsquemaPonderacion((examen(), sobre_examen(porcentaje)))


def aula_e1(**campos) -> ArbolPonderacion:
    """«PRIMERA EVALUACIÓN» en media ponderada con 4 notas (coef. 1) del examen y 3 ajenas."""
    notas = tuple(
        nodo(
            f"ig{cmid}", nombre, clase="actividad", padre="cg2", cmid=cmid, tiene_notas=(cmid == 11)
        )
        for _, _, nombre, _, cmid in FICHEROS
    )
    ajenas = (
        nodo("ig15", "Práctica Linux", padre="cg2"),
        nodo("ig16", "Proyecto web", padre="cg2"),
        nodo("ig17", "Actitud", padre="cg2"),
    )
    campos = {"tiene_notas": True, **campos}
    return arbol(categoria("cg2", PRIMERA, **campos), *notas, *ajenas)


def planear(esquema, a, *, huellas=None, **kw) -> PlanPonderacion:
    return planificar(esquema, estructura(), a, huellas or {}, **kw)


# --- simulación mínima de lo que hace el aula con las operaciones ---


def aplicar(a: ArbolPonderacion, plan: PlanPonderacion) -> ArbolPonderacion:
    nodos = list(a.nodos)
    reales: dict[str, str] = {}
    siguiente = 100

    def real(eid: str | None) -> str | None:
        return reales.get(eid, eid) if eid is not None else None

    def indice(eid: str) -> int:
        return next(i for i, n in enumerate(nodos) if n.eid == eid)

    def metodo_de(eid: str | None) -> int | None:
        padre = next((n for n in nodos if n.eid == eid), None)
        return padre.agregacion if padre else None

    for op in plan.operaciones:
        if op.tipo == "crear":
            eid = f"cg{siguiente}"
            siguiente += 1
            reales[str(op.eid)] = eid
            coef = op.coeficiente if op.coeficiente is not None else 0.0
            nodos.append(
                categoria(
                    eid,
                    str(op.nombre),
                    padre=real(op.padre),
                    agregacion=op.agregacion,
                    solo=op.solo_no_vacias,
                    coeficiente=coef,
                    peso=coef,
                    idnumber=str(op.idnumber),
                )
            )
        elif op.tipo == "mover":
            i = indice(str(real(op.eid)))
            destino = real(op.destino)
            nodos[i] = dataclasses.replace(
                nodos[i],
                padre_eid=destino,
                coeficiente=None,
                peso=1.0,
                sobrescrito=False,
            )
        elif op.tipo == "metodo":
            i = indice(str(real(op.eid)))
            solo = op.solo_no_vacias if op.solo_no_vacias is not None else nodos[i].solo_no_vacias
            nodos[i] = dataclasses.replace(nodos[i], agregacion=op.agregacion, solo_no_vacias=solo)
        else:
            i = indice(str(real(op.eid)))
            natural = metodo_de(nodos[i].padre_eid) == 13
            nodos[i] = dataclasses.replace(
                nodos[i], coeficiente=op.coeficiente, peso=op.coeficiente, sobrescrito=natural
            )
    return ArbolPonderacion(a.curso, tuple(nodos), a.decimal)


def huellas_de(a: ArbolPonderacion, refs: dict[str, str]) -> dict[str, str]:
    return {ref: huella_nodo(a.nodo(eid), a) for ref, eid in refs.items() if a.nodo(eid)}


def eid_de(a: ArbolPonderacion, nombre: str) -> str:
    return next(n.eid for n in a.nodos if n.nombre == nombre)


def refs_e1(a: ArbolPonderacion) -> dict[str, str]:
    refs = dict(zip(REF_FICHEROS, (f"ig{c}" for *_, c in FICHEROS), strict=True))
    refs["categoria:EXAMEN_1EV"] = next(n.eid for n in a.nodos if n.idnumber == "TZP_EXAMEN_1EV")
    refs[f"categoria:{PRIMERA}"] = "cg2"
    return refs


def efectivos(
    plan: PlanPonderacion, categoria: str
) -> dict[str, tuple[float | None, float | None]]:
    afectada = next(c for c in plan.afectadas if c.nombre == categoria)
    return {h.nombre: (h.antes, h.despues) for h in afectada.hijos}


# --- referencia_de ---


def test_referencia_de_entradas_y_elementos():
    assert referencia_de(examen()) == "categoria:EXAMEN_1EV"
    assert referencia_de(sobre_examen()) == f"categoria:{PRIMERA}"
    assert referencia_de(fichero("1eva\\a.md", "tarea", "A", peso=1)) == "fichero:1eva/a.md"
    assert referencia_de(elemento("elemento", "Actitud", porcentaje=5)) == "elemento:Actitud"
    assert referencia_de(elemento("categoria", "X", porcentaje=5)) == "categoria:X"
    actividad = elemento("actividad", "Práctica 1", tipo="tarea", seccion=1, porcentaje=5)
    assert referencia_de(actividad) == "actividad:tarea:1:Práctica 1"
    otra = elemento("actividad", "Práctica 1", tipo="tarea", seccion="1.ª", porcentaje=5)
    assert referencia_de(otra) == "actividad:tarea:1.ª:Práctica 1"


def test_referencia_de_usa_la_ruta_del_documento_si_la_referencia_no_la_tiene():
    sin_ruta = ElementoPonderacion(Referencia("fichero", ""), 1.0, None, None, "x")
    documento = Documento(Path("a/b.md"), "tarea", "B", 1, "", "", [])
    assert referencia_de(sin_ruta, documento) == "fichero:a/b.md"


# --- huella_nodo ---


def test_huella_es_estable_y_depende_de_lo_que_dice():
    a = aula_e1()
    a = ArbolPonderacion(a.curso, (*a.nodos, categoria("cg3", "Sub", padre="cg2")), a.decimal)
    n = a.nodo("cg3")
    assert huella_nodo(n, a) == huella_nodo(dataclasses.replace(n), a)
    assert len(huella_nodo(n, a)) == 64
    distintos = {
        huella_nodo(dataclasses.replace(n, agregacion=13), a),
        huella_nodo(dataclasses.replace(n, solo_no_vacias=False), a),
        huella_nodo(dataclasses.replace(n, solo_no_vacias=None), a),
        huella_nodo(dataclasses.replace(n, coeficiente=2.0), a),
        huella_nodo(dataclasses.replace(n, padre_eid="cg9"), a),
        huella_nodo(n, a),
    }
    assert len(distintos) == 6


def test_huella_de_una_actividad_solo_cambia_con_su_coeficiente_o_su_padre():
    a = aula_e1()
    n = a.nodo("ig11")
    base = huella_nodo(n, a)
    for campo in (
        {"nombre": "otro"},
        {"agregacion": 13},
        {"solo_no_vacias": False},
        {"tiene_notas": False},
        {"maximo": 5.0},
    ):
        assert huella_nodo(dataclasses.replace(n, **campo), a) == base
    assert huella_nodo(dataclasses.replace(n, coeficiente=2.0), a) != base
    assert huella_nodo(dataclasses.replace(n, padre_eid="cg9"), a) != base


def test_huella_redondea_a_4_decimales_y_toma_peso_si_no_hay_coeficiente():
    a = aula_e1()
    n = a.nodo("ig11")
    assert huella_nodo(dataclasses.replace(n, coeficiente=1.28571), a) == huella_nodo(
        dataclasses.replace(n, coeficiente=1.2857, peso=9.0), a
    )
    assert huella_nodo(dataclasses.replace(n, coeficiente=None, peso=2.0), a) == huella_nodo(
        dataclasses.replace(n, coeficiente=2.0, peso=None), a
    )


def test_huella_en_natural_ignora_el_peso_que_no_esta_sobrescrito():
    a = ArbolPonderacion(
        2,
        (raiz(), categoria("cg2", "N", agregacion=13), nodo("ig5", "a", padre="cg2", peso=33.3)),
        ",",
    )
    n = a.nodo("ig5")
    assert huella_nodo(n, a) == huella_nodo(dataclasses.replace(n, peso=50.0), a)
    fijo = dataclasses.replace(n, sobrescrito=True)
    assert huella_nodo(fijo, a) != huella_nodo(dataclasses.replace(fijo, peso=50.0), a)


# --- E1: el caso del RFC ---


def test_e1_operaciones_en_orden_con_sus_valores():
    plan = planear(esquema_e1(), aula_e1())
    assert not plan.corta and not plan.sin_cambios
    assert [o.tipo for o in plan.operaciones] == ["crear", *["mover"] * 4, *["coeficiente"] * 4]
    crear = plan.operaciones[0]
    assert crear == OperacionPonderacion(
        "crear",
        "categoria:EXAMEN_1EV",
        eid="nuevo:EXAMEN_1EV",
        id="EXAMEN_1EV",
        nombre="Examen 1.ª evaluación",
        idnumber="TZP_EXAMEN_1EV",
        padre="cg2",
        agregacion=10,
        solo_no_vacias=False,
        coeficiente=1.2857,  # 30 / 70 · 3 no nombrados
        porcentaje=pytest.approx(30.0, abs=0.05),
    )
    movidos = plan.operaciones[1:5]
    assert [(o.eid, o.destino, o.despues_de) for o in movidos] == [
        ("ig11", "nuevo:EXAMEN_1EV", None),
        ("ig12", "nuevo:EXAMEN_1EV", "ig11"),
        ("ig13", "nuevo:EXAMEN_1EV", "ig12"),
        ("ig14", "nuevo:EXAMEN_1EV", "ig13"),
    ]
    assert [o.referencia for o in movidos] == list(REF_FICHEROS)
    coeficientes = plan.operaciones[5:]
    assert [(o.eid, o.coeficiente, o.metodo_del_padre) for o in coeficientes] == [
        ("ig11", 16.0, "media_ponderada"),
        ("ig12", 8.0, "media_ponderada"),
        ("ig13", 6.0, "media_ponderada"),
        ("ig14", 45.0, "media_ponderada"),
    ]


def test_e1_antes_y_despues_exactos():
    plan = planear(esquema_e1(), aula_e1())
    assert [c.nombre for c in plan.afectadas] == ["Examen 1.ª evaluación", PRIMERA]
    nueva, existente_ = plan.afectadas
    assert (nueva.calculo_antes, nueva.calculo_despues) == (None, "media_ponderada")
    assert (nueva.solo_antes, nueva.solo_despues) == (None, False)
    assert nueva.referencia == "categoria:EXAMEN_1EV"
    assert [(h.nombre, h.referencia, h.antes, h.peso) for h in nueva.hijos] == [
        ("Test 1", REF_FICHEROS[0], None, 16.0),
        ("Test 2", REF_FICHEROS[1], None, 8.0),
        ("Test 3", REF_FICHEROS[2], None, 6.0),
        ("Monta tu PC", REF_FICHEROS[3], None, 45.0),
    ]
    assert [h.despues for h in nueva.hijos] == pytest.approx(
        [21.3333, 10.6667, 8.0, 60.0], abs=1e-3
    )

    assert (existente_.calculo_antes, existente_.calculo_despues) == (
        "media_ponderada",
        "media_ponderada",
    )
    assert (existente_.solo_antes, existente_.solo_despues) == (True, True)
    ef = efectivos(plan, PRIMERA)
    assert ef["Examen 1.ª evaluación"] == (None, pytest.approx(30.0, abs=1e-3))
    for ajena in ("Práctica Linux", "Proyecto web", "Actitud"):
        assert ef[ajena] == (pytest.approx(14.2857, abs=1e-3), pytest.approx(23.3333, abs=1e-3))
    for test in ("Test 1", "Test 2", "Test 3", "Monta tu PC"):
        assert ef[test] == (pytest.approx(14.2857, abs=1e-3), None)
    sin_referencia = [h for h in existente_.hijos if h.referencia is None]
    assert [h.nombre for h in sin_referencia] == ["Práctica Linux", "Proyecto web", "Actitud"]


def test_e1_avisos_notas_y_salidas():
    plan = planear(esquema_e1(), aula_e1())
    assert plan.pesos_con_notas == (PRIMERA,)
    assert plan.salidas == (PRIMERA,)
    assert [(a.codigo, a.nombre) for a in plan.avisos] == [("PESOS_CON_NOTAS", PRIMERA)]
    assert plan.cambios_a_mano == ()


def test_e1_sin_notas_no_hay_avisos_ni_salidas():
    a = aula_e1(tiene_notas=False)
    a = ArbolPonderacion(
        a.curso, tuple(dataclasses.replace(n, tiene_notas=False) for n in a.nodos), a.decimal
    )
    plan = planear(esquema_e1(), a)
    assert plan.avisos == () and plan.pesos_con_notas == () and plan.salidas == ()


def test_una_nota_con_notas_que_sale_de_una_categoria_sin_ellas_es_una_salida():
    a = aula_e1(tiene_notas=False)
    plan = planear(esquema_e1(), a)
    assert plan.salidas == (PRIMERA,)  # ig11 tiene notas
    assert plan.pesos_con_notas == ()


# --- E2 y E3: idempotencia y recálculo ---


def test_e2_segunda_pasada_no_hace_nada():
    a = aula_e1()
    tras = aplicar(a, planear(esquema_e1(), a))
    huellas = huellas_de(tras, refs_e1(tras))
    plan = planear(esquema_e1(), tras, huellas=huellas)
    assert plan.operaciones == ()
    assert plan.sin_cambios and not plan.corta
    assert plan.afectadas == () and plan.cambios_a_mano == ()
    assert [a.codigo for a in plan.avisos] == []


def test_e2_tambien_sin_huellas_y_con_la_categoria_del_aula_en_el_mapa_tzp():
    a = aula_e1()
    tras = aplicar(a, planear(esquema_e1(), a))
    plan = planear(
        esquema_e1(), tras, tzp={refs_e1(tras)["categoria:EXAMEN_1EV"]: "TZP_EXAMEN_1EV"}
    )
    assert plan.sin_cambios and plan.operaciones == ()


def test_e3_un_hijo_nuevo_baja_el_examen_y_se_recalcula_sin_cambiado_a_mano():
    a = aula_e1()
    tras = aplicar(a, planear(esquema_e1(), a))
    huellas = huellas_de(tras, refs_e1(tras))
    con_cuaderno = ArbolPonderacion(
        tras.curso, (*tras.nodos, nodo("ig18", "Cuaderno", padre="cg2")), tras.decimal
    )
    exam = refs_e1(tras)["categoria:EXAMEN_1EV"]
    plan = planear(esquema_e1(), con_cuaderno, huellas=huellas)
    assert plan.cambios_a_mano == ()
    assert [(o.tipo, o.eid, o.coeficiente) for o in plan.operaciones] == [
        ("coeficiente", exam, 1.7143)
    ]
    ef = efectivos(plan, PRIMERA)
    assert ef["Examen 1.ª evaluación"] == (
        pytest.approx(24.3243, abs=1e-3),
        pytest.approx(30.0, abs=1e-3),
    )
    assert ef["Cuaderno"] == (pytest.approx(18.9189, abs=1e-3), pytest.approx(17.5, abs=1e-3))
    assert plan.pesos_con_notas == (PRIMERA,)


# --- E4: cambiado a mano ---


def test_e4_un_coeficiente_cambiado_a_mano_no_se_pisa_y_se_pregunta_aparte():
    a = aula_e1()
    tras = aplicar(a, planear(esquema_e1(), a))
    huellas = huellas_de(tras, refs_e1(tras))
    a_mano = ArbolPonderacion(
        tras.curso,
        tuple(
            dataclasses.replace(n, coeficiente=20.0, peso=20.0) if n.eid == "ig11" else n
            for n in tras.nodos
        ),
        tras.decimal,
    )
    plan = planear(esquema_e1(), a_mano, huellas=huellas)
    assert plan.operaciones == () and plan.sin_cambios
    (cambio,) = plan.cambios_a_mano
    assert cambio.referencia == REF_FICHEROS[0] and cambio.nombre == "Test 1"
    assert cambio.antes == pytest.approx(25.3165, abs=1e-3)  # 20 / 79
    assert cambio.despues == pytest.approx(21.3333, abs=1e-3)  # 16 / 75
    assert [(x.codigo, x.nombre, x.referencia) for x in plan.avisos] == [
        ("CAMBIADO_A_MANO", "Test 1", REF_FICHEROS[0])
    ]

    pisado = planear(esquema_e1(), a_mano, huellas=huellas, sobrescribir=[REF_FICHEROS[0]])
    assert [(o.tipo, o.eid, o.coeficiente) for o in pisado.operaciones] == [
        ("coeficiente", "ig11", 16.0)
    ]
    assert pisado.cambios_a_mano == ()
    assert all(x.codigo != "CAMBIADO_A_MANO" for x in pisado.avisos)


def test_cambiado_a_mano_que_ya_coincide_con_lo_pedido_no_se_pregunta():
    a = aula_e1()
    tras = aplicar(a, planear(esquema_e1(), a))
    huellas = huellas_de(tras, refs_e1(tras))
    huellas[REF_FICHEROS[0]] = "0" * 64  # la huella dice otra cosa, pero el aula ya está bien
    plan = planear(esquema_e1(), tras, huellas=huellas)
    assert plan.cambios_a_mano == () and plan.avisos == ()


def test_un_elemento_movido_a_mano_a_otra_categoria_no_se_trae_de_vuelta_sin_permiso():
    a = aula_e1()
    tras = aplicar(a, planear(esquema_e1(), a))
    huellas = huellas_de(tras, refs_e1(tras))
    fuera = ArbolPonderacion(
        tras.curso,
        tuple(
            dataclasses.replace(n, padre_eid="cg2") if n.eid == "ig12" else n for n in tras.nodos
        ),
        tras.decimal,
    )
    plan = planear(esquema_e1(), fuera, huellas=huellas)
    assert plan.cambios_a_mano and plan.cambios_a_mano[0].referencia == REF_FICHEROS[1]
    assert all(o.eid != "ig12" for o in plan.operaciones)


# --- E5, E7: corte y exclusión ---


def test_e5_padre_bloqueado_corta_el_curso_sin_crear_nada():
    plan = planear(esquema_e1(), aula_e1(bloqueado=True))
    assert plan.corta and not plan.sin_cambios
    assert plan.operaciones == () and plan.afectadas == ()
    assert [(a.codigo, a.nombre) for a in plan.avisos] == [("CATEGORIA_BLOQUEADA", PRIMERA)]


def test_e5_un_abuelo_bloqueado_tambien_corta():
    nodos = list(aula_e1().nodos)
    a = ArbolPonderacion(
        2,
        (
            nodos[0],
            categoria("cg9", "Trimestre", bloqueado=True),
            *(dataclasses.replace(n, padre_eid="cg9") if n.eid == "cg2" else n for n in nodos[1:]),
        ),
        ",",
    )
    plan = planear(esquema_e1(), a)
    assert plan.corta and plan.operaciones == ()
    assert plan.avisos[0].nombre == "Trimestre"


def test_e5_la_cadena_de_nuevas_dentro_de_una_bloqueada_corta():
    interior = examen(
        id="INTERIOR",
        nombre="Interior",
        dentro_de="EXAMEN_1EV",
        elementos=(),
        ruta="ponderacion[2]",
    )
    esquema = EsquemaPonderacion(
        (
            examen(
                elementos=(
                    elemento("categoria", "INTERIOR", peso=1),
                    *examen().elementos,
                )
            ),
            sobre_examen(),
            interior,
        )
    )
    plan = planear(esquema, aula_e1(bloqueado=True))
    assert plan.corta and plan.operaciones == ()


def test_e7_calificador_de_tiza_es_un_error():
    with pytest.raises(ErrorPonderacion) as error:
        planear(esquema_e1(), aula_e1(), calificador_de_tiza=True)
    assert error.value.codigo == "PONDERACION_CON_CALIFICADOR_DE_TIZA"


# --- Bloqueos de nodos sueltos ---


def test_un_nodo_nombrado_dentro_de_una_bloqueada_no_sale_y_lo_demas_sigue():
    a = aula_e1()
    ajena = categoria("cg3", "Cerrada", bloqueado=True)
    a = ArbolPonderacion(
        a.curso,
        (
            *a.nodos,
            ajena,
            nodo("ig30", "Dentro", padre="cg3"),
        ),
        a.decimal,
    )
    esquema = EsquemaPonderacion(
        (
            examen(elementos=(*examen().elementos, elemento("elemento", "Dentro", peso=2))),
            sobre_examen(),
        )
    )
    plan = planear(esquema, a)
    assert not plan.corta
    assert any(x.codigo == "CATEGORIA_BLOQUEADA" and x.nombre == "Cerrada" for x in plan.avisos)
    assert all(o.eid != "ig30" for o in plan.operaciones)
    assert sum(1 for o in plan.operaciones if o.tipo == "mover") == 4


def test_una_entrada_sobre_una_categoria_bloqueada_se_omite_con_aviso():
    a = ArbolPonderacion(
        2,
        (
            raiz(),
            categoria("cg2", PRIMERA, bloqueado=True),
            nodo("ig15", "A", padre="cg2"),
            nodo("ig16", "B", padre="cg2"),
        ),
        ",",
    )
    esquema = EsquemaPonderacion(
        (
            existente(
                PRIMERA,
                (
                    elemento("elemento", "A", porcentaje=70),
                    elemento("elemento", "B", porcentaje=30),
                ),
            ),
        )
    )
    plan = planear(esquema, a)
    assert plan.operaciones == () and plan.sin_cambios
    assert [x.codigo for x in plan.avisos] == ["CATEGORIA_BLOQUEADA"]


# --- Reparto en media ponderada ---


def aula_plana(*coeficientes: float, metodo: int = 10, **extra) -> ArbolPonderacion:
    hijos = tuple(
        nodo(f"ig{20 + i}", f"E{i}", padre="cg2", peso=c, **extra)
        for i, c in enumerate(coeficientes)
    )
    return arbol(categoria("cg2", PRIMERA, agregacion=metodo), *hijos)


def pcts(**por_nombre: float) -> tuple[ElementoPonderacion, ...]:
    return tuple(elemento("elemento", n, porcentaje=p) for n, p in por_nombre.items())


def test_media_ponderada_fija_p_sobre_100_menos_suma_por_resto():
    # E0 = 2, E1 = 3: lo no nombrado (E1, E2 = 3 + 5) pesa 8 y debe quedarse con el 60 %.
    a = aula_plana(2, 3, 5)
    plan = planear(EsquemaPonderacion((existente(PRIMERA, pcts(E0=40)),)), a)
    (op,) = plan.operaciones
    assert (op.tipo, op.eid, op.coeficiente) == ("coeficiente", "ig20", pytest.approx(5.3333))
    assert op.coeficiente == round(40 / 60 * 8, 4)
    ef = efectivos(plan, PRIMERA)
    assert ef["E0"][1] == pytest.approx(40.0, abs=1e-3)
    assert ef["E1"][1] == pytest.approx(60 * 3 / 8, abs=1e-3)


def test_media_ponderada_con_resto_cero_reparte_el_100_entre_los_nombrados():
    a = aula_plana(1, 1)
    plan = planear(EsquemaPonderacion((existente(PRIMERA, pcts(E0=30, E1=20)),)), a)
    assert [(o.eid, o.coeficiente) for o in plan.operaciones] == [("ig20", 30.0), ("ig21", 20.0)]
    ef = efectivos(plan, PRIMERA)
    assert ef["E0"][1] == pytest.approx(60.0) and ef["E1"][1] == pytest.approx(40.0)


def test_media_ponderada_con_no_nombrados_de_peso_cero_cuenta_como_sin_resto():
    a = aula_plana(1, 1, 0)
    plan = planear(EsquemaPonderacion((existente(PRIMERA, pcts(E0=30, E1=20)),)), a)
    assert [(o.eid, o.coeficiente) for o in plan.operaciones] == [("ig20", 30.0), ("ig21", 20.0)]


def test_todo_nombrado_suma_100_usa_el_porcentaje_como_coeficiente():
    a = aula_plana(1, 1, 1)
    plan = planear(EsquemaPonderacion((existente(PRIMERA, pcts(E0=50, E1=30, E2=20)),)), a)
    assert [o.coeficiente for o in plan.operaciones] == [50.0, 30.0, 20.0]
    ef = efectivos(plan, PRIMERA)
    assert [ef[f"E{i}"][1] for i in range(3)] == pytest.approx([50.0, 30.0, 20.0])


def test_redondeo_a_4_decimales():
    a = aula_plana(1, 1, 1)
    plan = planear(EsquemaPonderacion((existente(PRIMERA, pcts(E0=1)),)), a)
    (op,) = plan.operaciones
    assert op.coeficiente == round(1 / 99 * 2, 4) == 0.0202
    plan = planear(EsquemaPonderacion((existente(PRIMERA, pcts(E0=30)),)), aula_plana(1, 1, 1, 1))
    assert plan.operaciones[0].coeficiente == 1.2857


def test_no_se_emite_coeficiente_si_el_porcentaje_ya_esta_en_tolerancia():
    # coef 3/7: E0 pesa 30 % de 10 → ya está; con 30,04 todavía; con 30,2 ya no
    a = aula_plana(3, 7)
    esquema = lambda p: EsquemaPonderacion((existente(PRIMERA, pcts(E0=p)),))  # noqa: E731
    assert planear(esquema(30.0), a).sin_cambios
    assert planear(esquema(30.04), a).sin_cambios
    assert not planear(esquema(30.2), a).sin_cambios


def test_idempotencia_por_escala_igual_porcentaje_no_se_toca():
    a = aula_plana(30, 70)
    assert planear(EsquemaPonderacion((existente(PRIMERA, pcts(E0=30)),)), a).sin_cambios


def test_cambia_el_metodo_y_solo_no_vacias_solo_si_difieren():
    a = aula_plana(1, 1)
    esquema = EsquemaPonderacion(
        (existente(PRIMERA, pcts(E0=50, E1=50), calculo="natural", solo=False),)
    )
    plan = planear(esquema, a)
    metodo = [o for o in plan.operaciones if o.tipo == "metodo"]
    assert [(o.eid, o.agregacion, o.solo_no_vacias) for o in metodo] == [("cg2", 13, False)]
    assert [o.tipo for o in plan.operaciones] == ["metodo", "coeficiente", "coeficiente"]
    assert {o.metodo_del_padre for o in plan.operaciones if o.tipo == "coeficiente"} == {"natural"}
    mismo = EsquemaPonderacion(
        (existente(PRIMERA, pcts(E0=50, E1=50), calculo="media_ponderada", solo=True),)
    )
    assert planear(mismo, a).sin_cambios
    solo = EsquemaPonderacion((existente(PRIMERA, pcts(E0=50, E1=50), solo=False),))
    (op,) = planear(solo, a).operaciones
    assert (op.tipo, op.agregacion, op.solo_no_vacias) == ("metodo", 10, False)


def test_solo_no_vacias_sin_declarar_se_manda_como_none_al_cambiar_el_metodo():
    a = aula_plana(1, 1)
    plan = planear(
        EsquemaPonderacion((existente(PRIMERA, pcts(E0=50, E1=50), calculo="natural"),)), a
    )
    (metodo, *_) = plan.operaciones
    assert metodo.solo_no_vacias is None


# --- Natural ---


def aula_natural(**override) -> ArbolPonderacion:
    notas = []
    for i, nombre in enumerate(("Práctica", "Proyecto", "Actitud")):
        fijo = override.get(nombre)
        notas.append(
            nodo(
                f"ig{20 + i}",
                nombre,
                padre="cg2",
                peso=fijo if fijo is not None else 33.3,
                sobrescrito=fijo is not None,
            )
        )
    del_examen = tuple(
        nodo(f"ig{cmid}", nombre, clase="actividad", padre="cg2", cmid=cmid)
        for _, _, nombre, _, cmid in FICHEROS
    )
    return arbol(categoria("cg2", PRIMERA, agregacion=13), *del_examen, *notas)


def esquema_natural(porcentaje: float = 30.0) -> EsquemaPonderacion:
    return EsquemaPonderacion(
        (
            examen(),
            existente(PRIMERA, (elemento("categoria", "EXAMEN_1EV", porcentaje=porcentaje),)),
        )
    )


def test_e9_natural_con_peso_ajeno_que_cabe():
    plan = planear(esquema_natural(), aula_natural(Actitud=50.0))
    assert [o.tipo for o in plan.operaciones] == ["crear", *["mover"] * 4, *["coeficiente"] * 5]
    exam = plan.operaciones[0]
    assert exam.coeficiente is None  # el peso de una nueva en natural va en su operación
    peso = next(
        o for o in plan.operaciones if o.eid == "nuevo:EXAMEN_1EV" and o.tipo == "coeficiente"
    )
    assert (peso.coeficiente, peso.metodo_del_padre) == (30.0, "natural")
    ef = efectivos(plan, PRIMERA)
    assert ef["Examen 1.ª evaluación"][1] == pytest.approx(30.0)
    assert ef["Actitud"] == (pytest.approx(50.0), pytest.approx(50.0))
    assert ef["Práctica"][1] == pytest.approx(10.0)
    assert ef["Proyecto"][1] == pytest.approx(10.0)


def test_e9_natural_con_peso_ajeno_que_no_cabe_es_imposible():
    with pytest.raises(ErrorPonderacion) as error:
        planear(esquema_natural(), aula_natural(Actitud=80.0))
    assert error.value.codigo == "PORCENTAJE_IMPOSIBLE"


def test_natural_con_lo_sobrescrito_justo_hasta_100_cabe():
    plan = planear(esquema_natural(), aula_natural(Actitud=70.0))
    ef = efectivos(plan, PRIMERA)
    assert ef["Práctica"][1] == pytest.approx(0.0) and ef["Proyecto"][1] == pytest.approx(0.0)


def test_natural_reparte_el_resto_segun_el_maximo():
    a = ArbolPonderacion(
        2,
        (
            raiz(),
            categoria("cg2", PRIMERA, agregacion=13),
            nodo("ig20", "N1", padre="cg2", maximo=10.0, sobrescrito=False),
            nodo("ig21", "N2", padre="cg2", maximo=10.0),
            nodo("ig22", "N3", padre="cg2", maximo=10.0),
            nodo("ig23", "N4", padre="cg2", maximo=20.0),
        ),
        ",",
    )
    plan = planear(EsquemaPonderacion((existente(PRIMERA, pcts(N1=30)),)), a)
    ef = efectivos(plan, PRIMERA)
    # Espiga S2: N1 al 30 % deja 17,5 / 17,5 / 35 al resto.
    assert [ef[n][1] for n in ("N1", "N2", "N3", "N4")] == pytest.approx([30, 17.5, 17.5, 35])
    (op,) = plan.operaciones
    assert (op.eid, op.coeficiente, op.metodo_del_padre) == ("ig20", 30.0, "natural")


def test_natural_ya_sobrescrito_en_su_sitio_no_emite_nada():
    a = ArbolPonderacion(
        2,
        (
            raiz(),
            categoria("cg2", PRIMERA, agregacion=13),
            nodo("ig20", "N1", padre="cg2", peso=30.0, sobrescrito=True),
            nodo("ig21", "N2", padre="cg2"),
        ),
        ",",
    )
    assert planear(EsquemaPonderacion((existente(PRIMERA, pcts(N1=30)),)), a).sin_cambios


def test_natural_sin_sobrescribir_fija_el_peso_aunque_el_porcentaje_ya_coincida():
    a = ArbolPonderacion(
        2,
        (
            raiz(),
            categoria("cg2", PRIMERA, agregacion=13),
            nodo("ig20", "N1", padre="cg2", peso=50.0),
            nodo("ig21", "N2", padre="cg2"),
        ),
        ",",
    )
    plan = planear(EsquemaPonderacion((existente(PRIMERA, pcts(N1=50)),)), a)
    assert [(o.tipo, o.eid) for o in plan.operaciones] == [("coeficiente", "ig20")]


def test_categoria_nueva_con_peso_relativo_en_natural_son_porcentajes():
    entrada = examen(calculo="natural")
    plan = planear(EsquemaPonderacion((entrada, sobre_examen())), aula_e1())
    pesos = [
        o.coeficiente
        for o in plan.operaciones
        if o.tipo == "coeficiente" and o.eid != "nuevo:EXAMEN_1EV"
    ]
    assert pesos == pytest.approx([21.3333, 10.6667, 8.0, 60.0])
    assert plan.operaciones[0].agregacion == 13


# --- Errores de resolución ---


def error_de(esquema: EsquemaPonderacion, a: ArbolPonderacion, **kw) -> str:
    with pytest.raises(ErrorPonderacion) as error:
        planear(esquema, a, **kw)
    return error.value.codigo


def test_elemento_ausente_y_ambiguo():
    a = aula_plana(1, 1)
    ausente = EsquemaPonderacion((existente(PRIMERA, pcts(Nada=10)),))
    assert error_de(ausente, a) == "ELEMENTO_AUSENTE"
    doble = ArbolPonderacion(a.curso, (*a.nodos, nodo("ig30", "E0", padre="cg2")), a.decimal)
    assert (
        error_de(EsquemaPonderacion((existente(PRIMERA, pcts(E0=10)),)), doble)
        == "ELEMENTO_AMBIGUO"
    )


def test_un_elemento_no_es_una_actividad_ni_una_categoria():
    a = ArbolPonderacion(
        2,
        (
            raiz(),
            categoria("cg2", PRIMERA),
            nodo("ig20", "X", clase="actividad", padre="cg2", cmid=5),
        ),
        ",",
    )
    assert error_de(EsquemaPonderacion((existente(PRIMERA, pcts(X=10)),)), a) == "ELEMENTO_AUSENTE"


def test_categoria_ausente_y_ambigua():
    a = aula_e1()
    esquema = EsquemaPonderacion((existente("No existe", pcts(Actitud=10)),))
    assert error_de(esquema, a) == "CATEGORIA_AUSENTE"
    doble = ArbolPonderacion(a.curso, (*a.nodos, categoria("cg9", PRIMERA)), a.decimal)
    assert error_de(esquema_e1(), doble) == "CATEGORIA_AMBIGUA"
    assert (
        error_de(EsquemaPonderacion((examen(dentro_de="Otra"), sobre_examen())), a)
        == "CATEGORIA_AUSENTE"
    )
    en_lista = EsquemaPonderacion(
        (existente(PRIMERA, (elemento("categoria", "Nada", porcentaje=10),)),)
    )
    assert error_de(en_lista, a) == "CATEGORIA_AUSENTE"


def test_la_raiz_no_vale_como_categoria():
    a = aula_e1()
    assert (
        error_de(EsquemaPonderacion((existente("Curso", pcts(Actitud=10)),)), a)
        == "CATEGORIA_AUSENTE"
    )
    assert (
        error_de(EsquemaPonderacion((examen(dentro_de="Curso"), sobre_examen())), a)
        == "CATEGORIA_AUSENTE"
    )


def test_actividad_ausente_ambigua_y_pendiente():
    a = aula_e1()
    ficheros = lambda *e: EsquemaPonderacion((examen(elementos=e), sobre_examen()))  # noqa: E731
    pendiente = ficheros(fichero("1eva/nuevo.md", "tarea", "Todavía no", peso=1))
    assert error_de(pendiente, a) == "ACTIVIDAD_PENDIENTE"
    # Publicada en la estructura pero ausente del calificador: también pendiente.
    sin_nodo = ArbolPonderacion(a.curso, tuple(n for n in a.nodos if n.eid != "ig11"), a.decimal)
    assert error_de(esquema_e1(), sin_nodo) == "ACTIVIDAD_PENDIENTE"

    por_actividad = lambda **kw: EsquemaPonderacion(  # noqa: E731
        (
            existente(
                PRIMERA,
                (
                    elemento(
                        "actividad",
                        kw["nombre"],
                        tipo=kw["tipo"],
                        seccion=kw["seccion"],
                        porcentaje=10,
                    ),
                ),
            ),
        )
    )
    assert error_de(por_actividad(nombre="Nada", tipo="tarea", seccion=1), a) == "ACTIVIDAD_AUSENTE"
    assert (
        error_de(por_actividad(nombre="Test 1", tipo="tarea", seccion=1), a) == "ACTIVIDAD_AUSENTE"
    )
    assert (
        error_de(por_actividad(nombre="Test 1", tipo="cuestionario", seccion=2), a)
        == "ACTIVIDAD_AUSENTE"
    )
    assert (
        error_de(por_actividad(nombre="Test 1", tipo="cuestionario", seccion="Nada"), a)
        == "ACTIVIDAD_AUSENTE"
    )

    doble = Estructura.de_dicts(
        [
            {
                "numero": 1,
                "nombre": PRIMERA,
                "id": 10,
                "modulos": [
                    {"cmid": 11, "nombre": "Test 1", "tipo": "cuestionario"},
                    {"cmid": 12, "nombre": "Test 1", "tipo": "cuestionario"},
                ],
            }
        ]
    )
    with pytest.raises(ErrorPonderacion) as error:
        planificar(por_actividad(nombre="Test 1", tipo="cuestionario", seccion=1), doble, a, {})
    assert error.value.codigo == "ACTIVIDAD_AMBIGUA"
    with pytest.raises(ErrorPonderacion) as error:
        planificar(esquema_e1(), doble, a, {})
    assert error.value.codigo == "ACTIVIDAD_AMBIGUA"


def test_actividad_por_tipo_nombre_y_seccion_funciona_por_numero_o_por_nombre():
    a = aula_e1()
    for seccion in (1, PRIMERA, PRIMERA.lower()):
        esquema = EsquemaPonderacion(
            (
                existente(
                    PRIMERA,
                    (
                        elemento(
                            "actividad",
                            "Test 1",
                            tipo="cuestionario",
                            seccion=seccion,
                            porcentaje=20,
                        ),
                    ),
                ),
            )
        )
        plan = planear(esquema, a)
        assert plan.operaciones[0].eid == "ig11"
        assert plan.operaciones[0].referencia == f"actividad:cuestionario:{seccion}:Test 1"


def test_actividad_ausente_si_el_origen_ya_no_esta():
    from tiza.contenido import Origen

    a = aula_e1()
    documento = Documento(Path("x.md"), "tarea", "X", 1, "", "", [], origen=Origen(2, 999))
    elemento_ = ElementoPonderacion(Referencia("fichero", "x.md"), 1.0, None, documento, "x")
    esquema = EsquemaPonderacion((examen(elementos=(elemento_,)), sobre_examen()))
    assert error_de(esquema, a) == "ACTIVIDAD_AUSENTE"


def test_categoria_nueva_debe_estar_una_vez_en_la_lista_de_su_padre():
    a = aula_e1()
    assert error_de(EsquemaPonderacion((examen(),)), a) == "PONDERACION_INVALIDA"
    doble = existente(
        PRIMERA,
        (
            elemento("categoria", "EXAMEN_1EV", porcentaje=10),
            elemento("categoria", "EXAMEN_1EV", porcentaje=10),
        ),
    )
    assert error_de(EsquemaPonderacion((examen(), doble)), a) == "PONDERACION_INVALIDA"
    otra = categoria("cg3", "Otra")
    con_otra = ArbolPonderacion(a.curso, (*a.nodos, otra), a.decimal)
    en_otra = EsquemaPonderacion(
        (
            examen(),
            sobre_examen(),
            existente("Otra", (elemento("categoria", "EXAMEN_1EV", porcentaje=10),), n=2),
        )
    )
    assert error_de(en_otra, con_otra) == "PONDERACION_INVALIDA"


def test_nodo_nombrado_en_dos_listas_es_elemento_repetido():
    a = aula_e1()
    esquema = EsquemaPonderacion(
        (
            examen(elementos=(*examen().elementos, elemento("elemento", "Actitud", peso=1))),
            sobre_examen(),
            existente(PRIMERA, (elemento("elemento", "Actitud", porcentaje=5),), n=2),
        )
    )
    # la categoría PRIMERA tiene dos entradas: lo detecta antes
    assert error_de(esquema, a) == "PONDERACION_INVALIDA"
    dos = EsquemaPonderacion(
        (
            examen(elementos=(*examen().elementos, elemento("elemento", "Actitud", peso=1))),
            existente(
                PRIMERA,
                (
                    elemento("categoria", "EXAMEN_1EV", porcentaje=30),
                    elemento("actividad", "Test 1", tipo="cuestionario", seccion=1, porcentaje=5),
                ),
            ),
        )
    )
    assert error_de(dos, a) == "ELEMENTO_REPETIDO"


def test_una_categoria_dentro_de_si_misma_es_invalida():
    a = ArbolPonderacion(
        2,
        (raiz(), categoria("cg2", "A"), categoria("cg3", "B", padre="cg2")),
        ",",
    )
    esquema = EsquemaPonderacion((existente("B", (elemento("categoria", "A", porcentaje=10),)),))
    assert error_de(esquema, a) == "PONDERACION_INVALIDA"


# --- Comprobaciones del aula ---


def test_porcentajes_sin_resto():
    a = aula_plana(1, 1, 1)
    esquema = EsquemaPonderacion((existente(PRIMERA, pcts(E0=60, E1=40)),))
    assert error_de(esquema, a) == "PORCENTAJES_SIN_RESTO"
    casi = EsquemaPonderacion((existente(PRIMERA, pcts(E0=60, E1=40.004)),))
    assert error_de(casi, a) == "PORCENTAJES_SIN_RESTO"
    assert planear(EsquemaPonderacion((existente(PRIMERA, pcts(E0=60, E1=39.9)),)), a)


def test_porcentajes_sin_resto_tambien_en_natural():
    a = ArbolPonderacion(
        2,
        (
            raiz(),
            categoria("cg2", PRIMERA, agregacion=13),
            nodo("ig20", "A", padre="cg2"),
            nodo("ig21", "B", padre="cg2"),
        ),
        ",",
    )
    assert (
        error_de(EsquemaPonderacion((existente(PRIMERA, pcts(A=100)),)), a)
        == "PORCENTAJES_SIN_RESTO"
    )


def test_calculo_sin_pesos_en_una_existente():
    a = aula_plana(1, 1, metodo=0)
    esquema = EsquemaPonderacion((existente(PRIMERA, pcts(E0=50)),))
    assert error_de(esquema, a) == "CALCULO_SIN_PESOS"
    con_calculo = EsquemaPonderacion((existente(PRIMERA, pcts(E0=50), calculo="media_ponderada"),))
    assert planear(con_calculo, a).operaciones[0].tipo == "metodo"


def test_calculo_no_disponible():
    opciones = (0, 11, 12, 2, 4, 6, 8, 13)
    sin_media = aula_e1(opciones=opciones, agregacion=13)
    assert error_de(esquema_e1(), sin_media) == "CALCULO_NO_DISPONIBLE"  # E10
    a = aula_plana(1, 1, metodo=13)
    a = ArbolPonderacion(
        a.curso,
        tuple(
            dataclasses.replace(n, opciones_agregacion=opciones) if n.eid == "cg2" else n
            for n in a.nodos
        ),
        a.decimal,
    )
    esquema = EsquemaPonderacion((existente(PRIMERA, pcts(E0=50), calculo="media_ponderada"),))
    assert error_de(esquema, a) == "CALCULO_NO_DISPONIBLE"
    # Si no se conocen las opciones, se intenta.
    desconocidas = ArbolPonderacion(
        a.curso,
        tuple(
            dataclasses.replace(n, opciones_agregacion=None) if n.eid == "cg2" else n
            for n in a.nodos
        ),
        a.decimal,
    )
    assert planear(esquema, desconocidas)


def test_calculo_en_uso_no_se_comprueba_contra_las_opciones():
    a = aula_plana(1, 1)
    a = ArbolPonderacion(
        a.curso,
        tuple(
            dataclasses.replace(n, opciones_agregacion=(13,)) if n.eid == "cg2" else n
            for n in a.nodos
        ),
        a.decimal,
    )
    esquema = EsquemaPonderacion((existente(PRIMERA, pcts(E0=30), calculo="media_ponderada"),))
    plan = planear(esquema, a)
    assert [o.tipo for o in plan.operaciones] == ["coeficiente"]


# --- Categorías nuevas ---


def test_categoria_nueva_dentro_de_otra_nueva_se_crea_en_orden_de_padre_a_hijo():
    interior = examen(
        id="INTERIOR",
        nombre="Interior",
        dentro_de="EXAMEN_1EV",
        elementos=(
            fichero(*FICHEROS[0][:3], peso=1),
            fichero(*FICHEROS[1][:3], peso=3),
        ),
        ruta="ponderacion[2]",
    )
    exterior = examen(
        elementos=(
            elemento("categoria", "INTERIOR", peso=1),
            fichero(*FICHEROS[2][:3], peso=1),
            fichero(*FICHEROS[3][:3], peso=2),
        )
    )
    # El interior se declara antes que el exterior, pero se crea después.
    esquema = EsquemaPonderacion((interior, exterior, sobre_examen()))
    esquema = dataclasses.replace(
        esquema,
        entradas=(
            dataclasses.replace(interior, ruta="ponderacion[0]"),
            dataclasses.replace(exterior, ruta="ponderacion[1]"),
            dataclasses.replace(sobre_examen(), ruta="ponderacion[2]"),
        ),
    )
    plan = planear(esquema, aula_e1())
    crear = [o for o in plan.operaciones if o.tipo == "crear"]
    assert [o.id for o in crear] == ["EXAMEN_1EV", "INTERIOR"]
    assert [o.padre for o in crear] == ["cg2", "nuevo:EXAMEN_1EV"]
    # El interior pesa 1 de 4 en el exterior: coef 1 (todos nombrados, S = 0).
    assert crear[1].coeficiente == 1.0
    tipos = [o.tipo for o in plan.operaciones]
    assert tipos == sorted(tipos, key=["crear", "mover", "metodo", "coeficiente"].index)
    # El orden del YAML se conserva: el interior va primero en su padre, pero es el primero que
    # se crea... y el último en el YAML de PRIMERA, así que no se mueve.
    moves_interior = [
        o for o in plan.operaciones if o.tipo == "mover" and o.eid == "nuevo:INTERIOR"
    ]
    assert [(o.destino, o.despues_de) for o in moves_interior] == [("nuevo:EXAMEN_1EV", None)]


def test_la_nueva_no_ultima_de_su_lista_se_coloca_en_su_orden():
    sobre = existente(
        PRIMERA,
        (
            elemento("categoria", "EXAMEN_1EV", porcentaje=30),
            elemento("elemento", "Actitud", porcentaje=10),
        ),
    )
    plan = planear(EsquemaPonderacion((examen(), sobre)), aula_e1())
    moves = [
        (o.eid, o.destino, o.despues_de)
        for o in plan.operaciones
        if o.tipo == "mover" and o.destino == "cg2"
    ]
    # El examen es el primero de su lista (va al principio); Actitud ya está en PRIMERA: no se mueve.
    assert moves == [("nuevo:EXAMEN_1EV", "cg2", None)]
    sobre = existente(
        PRIMERA,
        (
            elemento("elemento", "Actitud", porcentaje=10),
            elemento("categoria", "EXAMEN_1EV", porcentaje=30),
        ),
    )
    plan = planear(EsquemaPonderacion((examen(), sobre)), aula_e1())
    assert [o for o in plan.operaciones if o.tipo == "mover" and o.destino == "cg2"] == []


def test_un_nodo_de_otra_categoria_se_mueve_con_despues_de_el_anterior_del_yaml():
    a = aula_e1()
    a = ArbolPonderacion(
        a.curso,
        (
            *a.nodos,
            categoria("cg3", "Otra"),
            nodo("ig40", "Fuera", padre="cg3"),
            nodo("ig41", "Lejos", padre="cg3"),
        ),
        a.decimal,
    )
    sobre = existente(
        PRIMERA,
        (
            elemento("elemento", "Actitud", porcentaje=10),
            elemento("elemento", "Fuera", porcentaje=10),
            elemento("elemento", "Lejos", porcentaje=10),
        ),
    )
    plan = planear(EsquemaPonderacion((sobre,)), a)
    assert [(o.eid, o.despues_de) for o in plan.operaciones if o.tipo == "mover"] == [
        ("ig40", "ig17"),
        ("ig41", "ig40"),
    ]
    assert plan.salidas == ()  # «Otra» no tiene notas
    assert [c.nombre for c in plan.afectadas] == [PRIMERA, "Otra"]
    otra = plan.afectadas[1]
    assert [(h.nombre, h.antes, h.despues) for h in otra.hijos] == [
        ("Fuera", 50.0, None),
        ("Lejos", 50.0, None),
    ]


def test_categoria_de_origen_afectada_con_notas_sale_en_pesos_y_salidas():
    a = aula_e1()
    a = ArbolPonderacion(
        a.curso,
        (
            *a.nodos,
            categoria("cg3", "Otra", tiene_notas=True),
            nodo("ig40", "Fuera", padre="cg3"),
            nodo("ig41", "Queda", padre="cg3"),
        ),
        a.decimal,
    )
    sobre = existente(PRIMERA, (elemento("elemento", "Fuera", porcentaje=10),))
    plan = planear(EsquemaPonderacion((sobre,)), a)
    assert plan.salidas == ("Otra",)
    assert "Otra" in plan.pesos_con_notas
    otra = next(c for c in plan.afectadas if c.nombre == "Otra")
    assert [(h.nombre, h.antes, h.despues) for h in otra.hijos] == [
        ("Fuera", 50.0, None),
        ("Queda", 50.0, 100.0),
    ]
    # La categoría de la que sale algo no se toca: sin metodo ni coeficiente sobre ella.
    assert all(o.eid != "cg3" for o in plan.operaciones)


def test_categoria_tzp_del_aula_con_otro_id_es_no_declarada():
    a = aula_e1()
    a = ArbolPonderacion(
        a.curso, (*a.nodos, categoria("cg9", "Vieja", idnumber="TZP_VIEJA")), a.decimal
    )
    plan = planear(EsquemaPonderacion((existente(PRIMERA, pcts(Actitud=10)),)), a)
    assert ("CATEGORIA_NO_DECLARADA", "Vieja") in [(x.codigo, x.nombre) for x in plan.avisos]
    plan = planear(
        EsquemaPonderacion((existente(PRIMERA, pcts(Actitud=10)),)),
        aula_e1(),
        tzp={"cg77": "TZP_OTRA", "cg78": "otra"},
    )
    assert [(x.codigo, x.nombre) for x in plan.avisos if x.codigo != "PESOS_CON_NOTAS"] == [
        ("CATEGORIA_NO_DECLARADA", "TZP_OTRA")
    ]


def test_dos_categorias_del_aula_con_el_mismo_tzp_es_ambiguo():
    a = aula_e1()
    a = ArbolPonderacion(
        a.curso,
        (
            *a.nodos,
            categoria("cg8", "X1", idnumber="TZP_EXAMEN_1EV"),
            categoria("cg9", "X2", idnumber="TZP_EXAMEN_1EV"),
        ),
        a.decimal,
    )
    assert error_de(esquema_e1(), a) == "CATEGORIA_AMBIGUA"


def test_la_categoria_adoptada_por_su_tzp_se_mueve_a_su_padre_y_ajusta_el_metodo():
    a = aula_e1()
    tras = aplicar(a, planear(esquema_e1(), a))
    exam = refs_e1(tras)["categoria:EXAMEN_1EV"]
    # Alguien la sacó a la raíz y cambió su método y «solo no vacías».
    cambiada = ArbolPonderacion(
        tras.curso,
        tuple(
            dataclasses.replace(n, padre_eid="cg1", agregacion=13, solo_no_vacias=True)
            if n.eid == exam
            else n
            for n in tras.nodos
        ),
        tras.decimal,
    )
    plan = planear(esquema_e1(), cambiada)
    tipos = [(o.tipo, o.eid) for o in plan.operaciones]
    assert ("mover", exam) in tipos and ("metodo", exam) in tipos
    metodo = next(o for o in plan.operaciones if o.tipo == "metodo")
    assert (metodo.agregacion, metodo.solo_no_vacias) == (10, False)


# --- El invariante de no tocar ---


def comprobar_invariante(
    esquema: EsquemaPonderacion, a: ArbolPonderacion, nombrados: set[str]
) -> None:
    plan = planificar(esquema, estructura(), a, {})
    nuevos = {f"nuevo:{e.id}" for e in esquema.entradas if e.nueva}
    permitidos = nombrados | nuevos
    for op in plan.operaciones:
        if op.tipo in ("mover", "metodo", "coeficiente"):
            assert op.eid in permitidos, (op, permitidos)
    orden = [["crear", "mover", "metodo", "coeficiente"].index(o.tipo) for o in plan.operaciones]
    assert orden == sorted(orden)


@pytest.mark.parametrize("semilla", range(60))
def test_invariante_de_no_tocar_con_arboles_al_azar(semilla):
    azar = random.Random(semilla)
    metodo = azar.choice([10, 13])
    n_hijos = azar.randint(1, 6)
    hijos = []
    for i in range(n_hijos):
        fijo = metodo == 13 and azar.random() < 0.3
        hijos.append(
            nodo(
                f"ig{20 + i}",
                f"H{i}",
                padre="cg2",
                peso=azar.choice([1.0, 2.0, 0.0, 3.5])
                if metodo == 10
                else (azar.randint(1, 30) * 1.0 if fijo else 33.3),
                sobrescrito=fijo,
                maximo=azar.choice([10.0, 20.0, 100.0]),
                bloqueado=azar.random() < 0.1,
                tiene_notas=azar.random() < 0.3,
            )
        )
    ajenas = [
        nodo(f"ig{60 + i}", f"A{i}", padre="cg3", maximo=azar.choice([10.0, 100.0]))
        for i in range(azar.randint(0, 3))
    ]
    nodos = [
        categoria("cg2", "P", agregacion=metodo, bloqueado=azar.random() < 0.1),
        categoria("cg3", "Q", agregacion=azar.choice([10, 13, 0])),
        *hijos,
        *ajenas,
    ]
    a = arbol(*nodos)
    todos = [h.nombre for h in hijos] + [x.nombre for x in ajenas]
    nombrados = azar.sample(todos, k=azar.randint(1, len(todos)))
    hay_nueva = azar.random() < 0.5
    por_nombre = {n.nombre: n.eid for n in a.nodos}
    if hay_nueva:
        propios = nombrados[: max(1, len(nombrados) // 2)]
        resto = nombrados[len(propios) :]
        entradas = [
            EntradaPonderacion(
                True,
                "NUEVA",
                "Nueva",
                "P",
                azar.choice(["media_ponderada", "natural"]),
                azar.choice([True, False]),
                None,
                tuple(elemento("elemento", n, peso=azar.randint(1, 5)) for n in propios),
                "ponderacion[0]",
            ),
            existente(
                "P",
                (
                    elemento("categoria", "NUEVA", porcentaje=azar.choice([10.0, 30.0, 50.0])),
                    *(elemento("elemento", n, porcentaje=azar.choice([5.0, 10.0])) for n in resto),
                ),
            ),
        ]
    else:
        entradas = [
            existente(
                "P",
                tuple(
                    elemento("elemento", n, porcentaje=azar.choice([5.0, 10.0, 20.0]))
                    for n in nombrados
                ),
            )
        ]
    esquema = EsquemaPonderacion(tuple(entradas))
    nombrados_eids = {por_nombre[n] for n in nombrados} | {"cg2"}
    try:
        comprobar_invariante(esquema, a, nombrados_eids)
    except ErrorPonderacion as error:
        assert error.codigo in {
            "PORCENTAJE_IMPOSIBLE",
            "PORCENTAJES_SIN_RESTO",
            "ELEMENTO_AMBIGUO",
            "PONDERACION_INVALIDA",
        }


def test_invariante_de_no_tocar_en_e1_y_con_cambios_a_mano():
    a = aula_e1()
    nombrados = {"cg2", "ig11", "ig12", "ig13", "ig14"}
    comprobar_invariante(esquema_e1(), a, nombrados)
    tras = aplicar(a, planear(esquema_e1(), a))
    con_cuaderno = ArbolPonderacion(
        tras.curso, (*tras.nodos, nodo("ig18", "Cuaderno", padre="cg2")), tras.decimal
    )
    exam = refs_e1(tras)["categoria:EXAMEN_1EV"]
    comprobar_invariante(esquema_e1(), con_cuaderno, nombrados | {exam})


def test_los_no_nombrados_no_reciben_ninguna_operacion_en_media_ponderada_ni_natural():
    for a, esquema in (
        (aula_e1(), esquema_e1()),
        (aula_natural(Actitud=40.0), esquema_natural()),
    ):
        plan = planear(esquema, a)
        tocados = {o.eid for o in plan.operaciones if o.tipo != "crear"}
        assert not tocados & {"ig15", "ig16", "ig17", "ig20", "ig21", "ig22"}
