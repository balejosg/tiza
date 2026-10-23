"""Estructura deseada del calificador a partir del esquema y de las actividades. Offline y pura."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from tiza.calificacion.deseado import Deseado, Nodo, comprobar_sin_circulares, deseado
from tiza.calificacion.esquema import (
    Criterio,
    Elemento,
    ErrorCalificacion,
    Esquema,
    Evaluacion,
    Final,
    Instrumento,
    Tope,
)
from tiza.contenido import Documento

CARPETA = Path("/curso")

ELEMENTOS = (
    Elemento("RA1", "Redes", 40.0, "RA1"),
    Elemento("RA2", "Sistemas", 30.0),
    Elemento("RA3", "Seguridad", 30.0),
)
EVALUACIONES = (
    Evaluacion("Primera", (1, 2)),
    Evaluacion("Segunda", (3, "Tema 4"), cerrada=True),
    Evaluacion("Tercera", (5,)),
)
FP = Esquema("elementos", ELEMENTOS, EVALUACIONES, Final("elementos", Tope(5.0, 4.0)))
FP_SIN_TOPE = Esquema("elementos", ELEMENTOS, EVALUACIONES, Final("elementos"))
ESO = Esquema(
    "evaluaciones",
    ELEMENTOS,
    (
        Evaluacion("Primera", (1,), 30.0),
        Evaluacion("Segunda", (2,), 30.0),
        Evaluacion("Tercera", (3,), 40.0),
    ),
    Final("evaluaciones"),
)
ESO_VACIO = Esquema(
    "evaluaciones",
    (),
    (Evaluacion("Primera", (1,), 100.0),),
    Final("evaluaciones"),
)


def doc(ruta: str, seccion: int | str, **evalua: float) -> Documento:
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


def completo() -> list[Documento]:
    """Pesos que suman 100 por RA: RA1 en dos trimestres, RA2 y RA3 en uno."""
    return [
        doc("unidad1/practica1.md", 1, RA1=40),
        doc("unidad2/practica2.md", 2, RA1=20),
        doc("unidad5/examen.md", 5, RA1=40, RA2=30),
        doc("unidad3/redes.md", 3, RA2=70),
        doc("unidad5/seguridad.md", 5, RA3=100),
    ]


def nodo(d: Deseado, idnumber: str) -> Nodo:
    return next(n for n in d.nodos if n.idnumber == idnumber)


def hijos(d: Deseado, padre: str) -> list[Nodo]:
    return [n for n in d.nodos if n.padre == padre]


def de_clase(d: Deseado, clase: str) -> list[Nodo]:
    return [n for n in d.nodos if n.clase == clase]


def copia_de(d: Deseado, ruta: str, padre: str) -> Nodo:
    (copia,) = [n for n in hijos(d, padre) if n.clase == "copia" and n.formula_de == ruta]
    return copia


def test_fp_actividad_de_un_ra() -> None:
    d = deseado(FP, completo(), False, CARPETA)
    real = nodo(d, "unidad1/practica1.md")
    assert (real.clase, real.padre, real.peso) == ("actividad", "TZ_E_RA1", 40.0)
    copia = copia_de(d, "unidad1/practica1.md", "TZ_V_1_RA1")
    # en la 1.ª evaluación RA1 tiene practica1 (40) y practica2 (20): 66,67 y 33,33
    assert copia.peso == 66.67
    assert copia_de(d, "unidad2/practica2.md", "TZ_V_1_RA1").peso == 33.33
    assert copia.clase == "copia" and copia.nombre == "practica1 (copia)"
    assert dict(d.actividades)["unidad1/practica1.md"] == "TZ_E_RA1"


def test_fp_actividad_de_dos_ra() -> None:
    d = deseado(FP, completo(), False, CARPETA)
    assert nodo(d, "unidad5/examen.md").padre == "TZ_E_RA1"
    copia_ra2 = copia_de(d, "unidad5/examen.md", "TZ_E_RA2")
    assert copia_ra2.peso == 30.0
    # una copia por elemento en la vista por evaluaciones (3.ª evaluación)
    copia_v1 = copia_de(d, "unidad5/examen.md", "TZ_V_3_RA1")
    copia_v2 = copia_de(d, "unidad5/examen.md", "TZ_V_3_RA2")
    assert copia_v1.peso == 100.0 and copia_v2.peso == 100.0
    assert copia_ra2.idnumber != copia_v1.idnumber != copia_v2.idnumber


def test_pesos_explicitos_en_todos_los_hijos() -> None:
    d = deseado(FP, completo(), False, CARPETA)
    contadores = {n.idnumber for n in de_clase(d, "contador")}
    for n in d.nodos:
        if n.padre in contadores:
            assert n.peso is None, n.idnumber
        elif n.padre is not None:
            assert n.peso is not None, n.idnumber


def test_peso_cero_se_queda() -> None:
    docs = completo() + [doc("unidad1/extra.md", 1, RA1=0)]
    d = deseado(FP, docs, False, CARPETA)
    assert nodo(d, "unidad1/extra.md").peso == 0.0
    assert copia_de(d, "unidad1/extra.md", "TZ_V_1_RA1").peso == 0.0
    assert nodo(d, "unidad1/practica1.md").peso == pytest.approx(40.0)
    assert sum(n.peso or 0 for n in hijos(d, "TZ_E_RA1")) == pytest.approx(100.0)


def test_eso_por_evaluaciones() -> None:
    esquema = Esquema(
        "evaluaciones",
        ELEMENTOS,
        ESO.evaluaciones,
        Final("evaluaciones"),
    )
    docs = [
        doc("u1/a.md", 1, RA1=100),
        doc("u2/b.md", 2, RA2=100, RA1=0),
        doc("u3/c.md", 3, RA3=100),
    ]
    d = deseado(esquema, docs, False, CARPETA)
    assert nodo(d, "u1/a.md").padre == "TZ_V_1_RA1"
    assert nodo(d, "u2/b.md").padre == "TZ_V_2_RA2"
    assert copia_de(d, "u1/a.md", "TZ_E_RA1")
    assert copia_de(d, "u2/b.md", "TZ_V_2_RA1")
    assert copia_de(d, "u2/b.md", "TZ_E_RA2")
    assert nodo(d, "TZ_V_1").padre == "TZ_FINAL" and nodo(d, "TZ_V_1").peso == 30.0
    assert nodo(d, "TZ_V_3").peso == 40.0
    assert nodo(d, "TZ_VISTA").peso == 0.0
    assert nodo(d, "TZ_E_RA1").padre == "TZ_VISTA"
    assert [n.idnumber for n in hijos(d, "TZ_FINAL")] == ["TZ_V_1", "TZ_V_2", "TZ_V_3"]
    assert [n.idnumber for n in hijos(d, "TZ_TIZA")] == ["TZ_FINAL", "TZ_VISTA"]


def test_anterior_va_en_contenedor() -> None:
    d = deseado(FP, completo(), True, CARPETA)
    raiz = nodo(d, "TZ_TIZA")
    assert raiz.padre is None and raiz.peso == 0.0 and d.total_curso is None
    for n in d.nodos:
        if n is not raiz:
            assert n.padre is not None
    d = deseado(FP, completo(), False, CARPETA)
    assert d.total_curso == "TZ_NOTA_FINAL"
    d = deseado(FP_SIN_TOPE, completo(), False, CARPETA)
    assert d.total_curso == "porcentaje"
    assert nodo(d, "TZ_TIZA").peso == 100.0
    assert [n.idnumber for n in hijos(d, "TZ_TIZA")] == ["TZ_FINAL", "TZ_VISTA"]
    assert [n.peso for n in hijos(d, "TZ_TIZA")] == [100.0, 0.0]
    assert [n.idnumber for n in hijos(d, "TZ_FINAL")] == ["TZ_E_RA1", "TZ_E_RA2", "TZ_E_RA3"]
    assert [n.peso for n in hijos(d, "TZ_FINAL")] == [40.0, 30.0, 30.0]
    assert nodo(d, "TZ_FINAL").visualizacion == "porcentaje"
    assert [n.peso for n in hijos(d, "TZ_VISTA")] == [0.0, 0.0, 0.0]


def test_porcentaje_en_totales() -> None:
    d = deseado(FP, completo(), False, CARPETA)
    for n in d.nodos:
        if n.clase in ("contenedor", "categoria"):
            assert n.visualizacion == "porcentaje", n.idnumber
        else:
            assert n.visualizacion is None, n.idnumber


def test_sin_tope_sin_notas() -> None:
    d = deseado(ESO, [doc("u1/a.md", 1, RA1=100)], False, CARPETA)
    assert not [n for n in d.nodos if n.idnumber == "TZ_NOTAS"]
    assert not [n for n in d.nodos if n.clase in ("contador", "indicador", "nota")]
    assert d.tope is None and d.total_curso == "porcentaje"
    d = deseado(FP_SIN_TOPE, completo(), False, CARPETA)
    assert not [n for n in d.nodos if n.clase in ("contador", "indicador", "nota")]


def test_tope_monta_contador() -> None:
    docs = [
        doc("u1/a.md", 1, RA1=60),
        doc("u1/b.md", 1, RA2=100, RA1=40),
        doc("u1/c.md", 1, RA3=100),
    ]
    d = deseado(FP, docs, False, CARPETA)
    assert nodo(d, "TZ_NOTAS").peso == 0.0 and nodo(d, "TZ_NOTAS").padre == "TZ_TIZA"
    hijos_ra1 = hijos(d, "TZ_E_RA1")
    assert len(hijos_ra1) == 2
    indicadores = hijos(d, "TZ_K_RA1")
    assert [i.clase for i in indicadores] == ["indicador", "indicador"]
    assert sorted(str(i.formula_de) for i in indicadores) == sorted(h.idnumber for h in hijos_ra1)
    assert {"u1/a.md"} <= {str(i.formula_de) for i in indicadores}
    assert any(str(i.formula_de).startswith("TZ_C_") for i in indicadores)
    assert nodo(d, "TZ_K_RA1").clase == "contador"
    assert nodo(d, "TZ_K_RA1").peso == 0.0 and nodo(d, "TZ_K_RA1").visualizacion is None
    for i in indicadores:
        assert i.peso is None and i.idnumber.startswith("TZ_I_") and i.visualizacion is None
    notas = de_clase(d, "nota")
    assert {n.idnumber for n in notas} == {
        "TZ_NOTA_E_RA1",
        "TZ_NOTA_E_RA2",
        "TZ_NOTA_E_RA3",
        "TZ_NOTA_FINAL",
    }
    for id_ in ("RA1", "RA2", "RA3"):
        n = nodo(d, f"TZ_NOTA_E_{id_}")
        assert n.formula_de == (f"TZ_E_{id_}", f"TZ_K_{id_}")
        assert n.padre == "TZ_NOTAS" and n.peso == 0.0
    copias = hijos(d, "TZ_K_TIZA")
    assert [c.idnumber for c in copias] == ["TZ_KC_RA1", "TZ_KC_RA2", "TZ_KC_RA3"]
    assert [c.formula_de for c in copias] == ["TZ_K_RA1", "TZ_K_RA2", "TZ_K_RA3"]
    assert all(c.clase == "copia" and c.peso is None for c in copias)
    final = nodo(d, "TZ_NOTA_FINAL")
    assert final.formula_de == ("TZ_FINAL", "TZ_K_TIZA") and final.padre == "TZ_NOTAS"
    assert d.tope == (5.0, 4.0, ("TZ_NOTA_E_RA1", "TZ_NOTA_E_RA2", "TZ_NOTA_E_RA3"))
    # los idnumber son únicos
    ids = [n.idnumber for n in d.nodos]
    assert len(ids) == len(set(ids))


def test_ra_ausente_en_un_trimestre() -> None:
    docs = [
        doc("u1/a.md", 1, RA1=100),
        doc("u1/b.md", 1, RA2=100),
        doc("u5/c.md", 5, RA3=100),
    ]
    d = deseado(FP_SIN_TOPE, docs, False, CARPETA)
    assert not [n for n in d.nodos if n.idnumber == "TZ_V_1_RA3"]
    v1 = hijos(d, "TZ_V_1")
    assert [n.idnumber for n in v1] == ["TZ_V_1_RA1", "TZ_V_1_RA2"]
    assert [n.peso for n in v1] == [57.14, 42.86]
    assert sum(n.peso or 0 for n in v1) == pytest.approx(100.0)
    assert [n.peso for n in hijos(d, "TZ_V_3")] == [100.0]


def test_el_ultimo_hijo_ajusta_el_redondeo() -> None:
    esquema = Esquema("elementos", ELEMENTOS[:1], EVALUACIONES, Final("elementos"))
    docs = [doc(f"u1/a{i}.md", 1, RA1=33.33) for i in range(3)]
    # 99,99 está dentro de la tolerancia del esquema; normalizado suma exactamente 100
    d = deseado(esquema, docs, False, CARPETA)
    assert [n.peso for n in hijos(d, "TZ_E_RA1")] == [33.33, 33.33, 33.34]


def test_todos_cero_se_quedan_en_cero() -> None:
    docs = [doc("u1/a.md", 1, RA1=0), doc("u1/b.md", 1, RA1=0)]
    d = deseado(FP_SIN_TOPE, docs, False, CARPETA)
    assert [n.peso for n in hijos(d, "TZ_E_RA1")] == [0.0, 0.0]
    assert [n.peso for n in hijos(d, "TZ_V_1_RA1")] == [0.0, 0.0]


def test_elemento_desconocido() -> None:
    with pytest.raises(ErrorCalificacion) as info:
        deseado(FP, [doc("u1/a.md", 1, RA9=100)], False, CARPETA)
    assert info.value.codigo == "ELEMENTO_DESCONOCIDO"
    assert "u1/a.md" in info.value.detalle and "RA9" in info.value.detalle


def test_elemento_desconocido_sin_elementos() -> None:
    with pytest.raises(ErrorCalificacion) as info:
        deseado(ESO_VACIO, [doc("u1/a.md", 1, RA1=100)], False, CARPETA)
    assert info.value.codigo == "ELEMENTO_DESCONOCIDO"


def test_seccion_sin_evaluacion() -> None:
    with pytest.raises(ErrorCalificacion) as info:
        deseado(FP, [doc("u9/a.md", 9, RA1=100)], False, CARPETA)
    assert info.value.codigo == "SECCION_SIN_EVALUACION"
    assert "u9/a.md" in info.value.detalle


def test_seccion_de_texto_sin_distinguir_mayusculas() -> None:
    d = deseado(FP_SIN_TOPE, [doc("u4/a.md", "TEMA 4", RA1=100)], False, CARPETA)
    assert nodo(d, "u4/a.md").padre == "TZ_E_RA1"
    assert copia_de(d, "u4/a.md", "TZ_V_2_RA1")
    assert d.cerradas == ("TZ_V_2",)


def test_pesos_ra_no_suman() -> None:
    docs = [doc("u1/a.md", 1, RA1=40), doc("u1/b.md", 1, RA1=40)]
    with pytest.raises(ErrorCalificacion) as info:
        deseado(FP, docs, False, CARPETA)
    assert info.value.codigo == "PESOS_NO_SUMAN_100"
    assert "RA1" in info.value.detalle and "80" in info.value.detalle


def test_elemento_sin_actividades_es_aviso() -> None:
    d = deseado(FP, [doc("u1/a.md", 1, RA1=100)], False, CARPETA)
    assert d.avisos == (
        ("ELEMENTO_SIN_ACTIVIDADES", "RA2"),
        ("ELEMENTO_SIN_ACTIVIDADES", "RA3"),
    )
    assert nodo(d, "TZ_E_RA2")
    d = deseado(FP, completo(), False, CARPETA)
    assert d.avisos == ()


def test_documentos_sin_evalua_no_cuentan() -> None:
    sin = Documento(
        ruta=CARPETA / "u1/nada.md",
        tipo="pagina",
        nombre="nada",
        seccion=99,
        cuerpo="",
        html="",
        recursos=[],
    )
    d = deseado(FP, completo() + [sin], False, CARPETA)
    assert "u1/nada.md" not in dict(d.actividades)
    assert not [n for n in d.nodos if n.idnumber == "u1/nada.md"]


def test_copias_estables() -> None:
    docs = completo()
    d1 = deseado(FP, docs, False, CARPETA)
    d2 = deseado(FP, list(reversed(docs)), False, CARPETA)
    assert d1 == d2
    assert sorted(n.idnumber for n in d1.nodos) == sorted(n.idnumber for n in d2.nodos)


def test_cerradas() -> None:
    d = deseado(FP, completo(), False, CARPETA)
    assert d.cerradas == ("TZ_V_2",)
    assert nodo(d, "TZ_V_2").nombre == "Segunda"


def test_los_pesos_son_float() -> None:
    d = deseado(FP, completo(), False, CARPETA)
    assert all(isinstance(n.peso, float) for n in d.nodos if n.peso is not None)


def _ids(d: Deseado) -> dict[tuple[str, str | None, str | tuple[str, str] | None], str]:
    """idnumber de cada copia e indicador, por (clase, padre, a qué apunta)."""
    return {
        (n.clase, n.padre, n.formula_de): n.idnumber
        for n in d.nodos
        if n.clase in ("copia", "indicador")
    }


def test_ids_con_forma_de_huella() -> None:
    d = deseado(FP, completo(), False, CARPETA)
    for n in d.nodos:
        if n.clase == "copia" and n.formula_de in dict(d.actividades):
            assert re.fullmatch(r"TZ_C_[0-9a-f]{10}", n.idnumber)
        if n.clase == "indicador":
            assert re.fullmatch(r"TZ_I_[0-9a-f]{10}", n.idnumber)


def test_ids_estables_al_anadir_y_quitar() -> None:
    base = completo()
    antes = _ids(deseado(FP, base, False, CARPETA))
    assert len(antes) > 10
    # una actividad nueva que ordena la primera (con peso 0, no toca los pesos de nadie)
    nueva = doc("a0/primera.md", 1, RA2=0, RA1=0)
    despues = _ids(deseado(FP, [nueva] + base, False, CARPETA))
    assert len(despues) > len(antes)
    assert antes.items() <= despues.items()
    # quitar una (RA3 se queda sin actividades): las demás conservan su id
    sin_una = [d for d in base if d.ruta.name != "seguridad.md"]
    restante = _ids(deseado(FP, sin_una, False, CARPETA))
    assert 0 < len(restante) < len(antes)
    assert restante.items() <= antes.items()


def test_peso_cero_sin_indicador() -> None:
    docs = completo() + [doc("unidad1/extra.md", 1, RA1=0)]
    d = deseado(FP, docs, False, CARPETA)
    # el hijo de peso 0 está en TZ_E_RA1 pero no cuenta en el contador
    assert nodo(d, "unidad1/extra.md").peso == 0.0
    apuntados = {i.formula_de for i in hijos(d, "TZ_K_RA1")}
    assert "unidad1/extra.md" not in apuntados
    assert len(apuntados) == len([h for h in hijos(d, "TZ_E_RA1") if h.peso]) == 3
    # si todos los hijos de un elemento pesan 0, el contador se queda sin indicadores
    ceros = [doc("u1/a.md", 1, RA1=0), doc("u1/b.md", 1, RA1=0)]
    d = deseado(FP, ceros, False, CARPETA)
    assert nodo(d, "TZ_K_RA1").clase == "contador"
    assert hijos(d, "TZ_K_RA1") == []


def _antepasados(d: Deseado, idnumber: str) -> set[str]:
    por_id = {n.idnumber: n for n in d.nodos}
    resultado: set[str] = set()
    padre = por_id[idnumber].padre
    while padre is not None:
        resultado.add(padre)
        padre = por_id[padre].padre
    return resultado


def test_ningun_calculado_referencia_a_un_antepasado() -> None:
    casos = [(FP, completo()), (FP_SIN_TOPE, completo()), (ESO, [doc("u1/a.md", 1, RA1=100)])]
    for esquema, docs in casos:
        d = deseado(esquema, docs, False, CARPETA)
        for n in d.nodos:
            if n.formula_de is None:
                continue
            fuentes = n.formula_de if isinstance(n.formula_de, tuple) else (n.formula_de,)
            assert not set(fuentes) & _antepasados(d, n.idnumber), n.idnumber


def test_referencia_circular_se_rechaza() -> None:
    from tiza.calificacion.deseado import comprobar_sin_circulares

    d = deseado(FP, completo(), False, CARPETA)
    malo = Nodo("TZ_NOTA_FINAL", "nota", "x", "TZ_NOTAS", 0.0, ("TZ_TIZA", "TZ_K_TIZA"))
    nodos = tuple(malo if n.idnumber == "TZ_NOTA_FINAL" else n for n in d.nodos)
    with pytest.raises(ErrorCalificacion) as e:
        comprobar_sin_circulares(nodos)
    assert e.value.codigo == "REFERENCIA_CIRCULAR"


# ---- compatibilidad: un esquema sin criterios ni instrumentos da el árbol de siempre ----


def test_sin_criterios_ni_instrumentos_el_arbol_no_cambia() -> None:
    """Fijado a mano con la salida del código anterior a los criterios: no debe cambiar."""
    esquema = Esquema(
        "elementos",
        (Elemento("RA1", "Redes", 60.0), Elemento("RA2", "Sistemas", 40.0)),
        (Evaluacion("Primera", (1,)), Evaluacion("Segunda", (2,))),
        Final("elementos", Tope(5.0, 4.0)),
    )
    docs = [
        doc("u1/a.md", 1, RA1=60),
        doc("u1/b.md", 1, RA1=40, RA2=50),
        doc("u2/c.md", 2, RA2=50),
    ]
    d = deseado(esquema, docs, False, CARPETA)
    esperados = (
        ("TZ_TIZA", "contenedor", "Calificador de tiza", None, 100.0, None, "porcentaje"),
        ("TZ_FINAL", "categoria", "Final", "TZ_TIZA", 100.0, None, "porcentaje"),
        ("TZ_E_RA1", "categoria", "Redes", "TZ_FINAL", 60.0, None, "porcentaje"),
        ("u1/a.md", "actividad", "a", "TZ_E_RA1", 60.0, None, None),
        ("u1/b.md", "actividad", "b", "TZ_E_RA1", 40.0, None, None),
        ("TZ_E_RA2", "categoria", "Sistemas", "TZ_FINAL", 40.0, None, "porcentaje"),
        ("TZ_C_7e4917d23e", "copia", "b (copia)", "TZ_E_RA2", 50.0, "u1/b.md", None),
        ("u2/c.md", "actividad", "c", "TZ_E_RA2", 50.0, None, None),
        ("TZ_VISTA", "contenedor", "Vista por evaluaciones", "TZ_TIZA", 0.0, None, "porcentaje"),
        ("TZ_V_1", "categoria", "Primera", "TZ_VISTA", 0.0, None, "porcentaje"),
        ("TZ_V_1_RA1", "categoria", "Redes", "TZ_V_1", 60.0, None, "porcentaje"),
        ("TZ_C_23bf9b2a59", "copia", "a (copia)", "TZ_V_1_RA1", 60.0, "u1/a.md", None),
        ("TZ_C_fe18f95b1f", "copia", "b (copia)", "TZ_V_1_RA1", 40.0, "u1/b.md", None),
        ("TZ_V_1_RA2", "categoria", "Sistemas", "TZ_V_1", 40.0, None, "porcentaje"),
        ("TZ_C_7f1d95902d", "copia", "b (copia)", "TZ_V_1_RA2", 100.0, "u1/b.md", None),
        ("TZ_V_2", "categoria", "Segunda", "TZ_VISTA", 0.0, None, "porcentaje"),
        ("TZ_V_2_RA2", "categoria", "Sistemas", "TZ_V_2", 100.0, None, "porcentaje"),
        ("TZ_C_65cde091fa", "copia", "c (copia)", "TZ_V_2_RA2", 100.0, "u2/c.md", None),
        ("TZ_NOTAS", "contenedor", "Notas (sobre 10)", "TZ_TIZA", 0.0, None, "porcentaje"),
        ("TZ_K_RA1", "contador", "Contador RA1", "TZ_NOTAS", 0.0, None, None),
        ("TZ_I_d53cf958c4", "indicador", "Indicador a", "TZ_K_RA1", None, "u1/a.md", None),
        ("TZ_I_f019ebaaf5", "indicador", "Indicador b", "TZ_K_RA1", None, "u1/b.md", None),
        (
            "TZ_NOTA_E_RA1",
            "nota",
            "Redes (sobre 10)",
            "TZ_NOTAS",
            0.0,
            ("TZ_E_RA1", "TZ_K_RA1"),
            None,
        ),
        ("TZ_K_RA2", "contador", "Contador RA2", "TZ_NOTAS", 0.0, None, None),
        ("TZ_I_d99edaccfc", "indicador", "Indicador b", "TZ_K_RA2", None, "TZ_C_7e4917d23e", None),
        ("TZ_I_32ed0640fc", "indicador", "Indicador c", "TZ_K_RA2", None, "u2/c.md", None),
        (
            "TZ_NOTA_E_RA2",
            "nota",
            "Sistemas (sobre 10)",
            "TZ_NOTAS",
            0.0,
            ("TZ_E_RA2", "TZ_K_RA2"),
            None,
        ),
        ("TZ_K_TIZA", "contador", "Contador final", "TZ_NOTAS", 0.0, None, None),
        ("TZ_KC_RA1", "copia", "Contador RA1 (copia)", "TZ_K_TIZA", None, "TZ_K_RA1", None),
        ("TZ_KC_RA2", "copia", "Contador RA2 (copia)", "TZ_K_TIZA", None, "TZ_K_RA2", None),
        (
            "TZ_NOTA_FINAL",
            "nota",
            "Nota final (sobre 10)",
            "TZ_NOTAS",
            0.0,
            ("TZ_FINAL", "TZ_K_TIZA"),
            None,
        ),
    )
    assert [
        (n.idnumber, n.clase, n.nombre, n.padre, n.peso, n.formula_de, n.visualizacion)
        for n in d.nodos
    ] == list(esperados)
    assert d.total_curso == "TZ_NOTA_FINAL"
    assert d.tope == (5.0, 4.0, ("TZ_NOTA_E_RA1", "TZ_NOTA_E_RA2"))
    assert d.cerradas == ()
    assert d.actividades == (
        ("u1/a.md", "TZ_E_RA1"),
        ("u1/b.md", "TZ_E_RA1"),
        ("u2/c.md", "TZ_E_RA2"),
    )
    assert d.avisos == ()


# ---- criterios e instrumentos ----

RA1_CRITERIOS = Elemento(
    "RA1",
    "Redes",
    60.0,
    criterios=(
        Criterio("CA1", "Criterio a", 70.0, None),
        Criterio("CA2", "Criterio b", 30.0, None),
    ),
)
RA2_SIMPLE = Elemento("RA2", "Sistemas", 40.0)
DOS_EVALUACIONES = (Evaluacion("Primera", (1,)), Evaluacion("Segunda", (2,)))


def con_criterios(
    organizacion: str = "elementos",
    tope: Tope | None = None,
    elementos: tuple[Elemento, ...] = (RA1_CRITERIOS, RA2_SIMPLE),
    instrumentos: tuple[Instrumento, ...] = (),
) -> Esquema:
    evaluaciones = DOS_EVALUACIONES
    if organizacion == "evaluaciones":
        evaluaciones = (Evaluacion("Primera", (1,), 50.0), Evaluacion("Segunda", (2,), 50.0))
    return Esquema(organizacion, elementos, evaluaciones, Final(organizacion, tope), instrumentos)


def test_elemento_con_criterios_y_elemento_sin_criterios_en_las_dos_vistas() -> None:
    docs = [
        doc("u1/a.md", 1, CA1=100),
        doc("u2/b.md", 2, CA2=100),
        doc("u1/c.md", 1, RA2=100),
    ]
    d = deseado(con_criterios(), docs, False, CARPETA)
    # vista por elementos: elemento -> criterio -> actividad
    assert [(n.idnumber, n.peso) for n in hijos(d, "TZ_FINAL")] == [
        ("TZ_E_RA1", 60.0),
        ("TZ_E_RA2", 40.0),
    ]
    assert [(n.idnumber, n.peso) for n in hijos(d, "TZ_E_RA1")] == [
        ("TZ_E_CA1", 70.0),
        ("TZ_E_CA2", 30.0),
    ]
    ca1 = nodo(d, "TZ_E_CA1")
    assert (ca1.clase, ca1.nombre, ca1.visualizacion) == ("categoria", "Criterio a", "porcentaje")
    assert [(n.idnumber, n.clase, n.peso) for n in hijos(d, "TZ_E_CA1")] == [
        ("u1/a.md", "actividad", 100.0)
    ]
    assert [(n.idnumber, n.peso) for n in hijos(d, "TZ_E_CA2")] == [("u2/b.md", 100.0)]
    assert [n.idnumber for n in hijos(d, "TZ_E_RA2")] == ["u1/c.md"]
    # vista por evaluaciones: solo lo que tiene algo en cada evaluación, renormalizado
    assert [(n.idnumber, n.peso) for n in hijos(d, "TZ_V_1")] == [
        ("TZ_V_1_RA1", 60.0),
        ("TZ_V_1_RA2", 40.0),
    ]
    assert [(n.idnumber, n.peso) for n in hijos(d, "TZ_V_1_RA1")] == [("TZ_V_1_CA1", 100.0)]
    assert nodo(d, "TZ_V_1_CA1").nombre == "Criterio a"
    assert nodo(d, "TZ_V_1_CA1").visualizacion == "porcentaje"
    copia = copia_de(d, "u1/a.md", "TZ_V_1_CA1")
    assert copia.peso == 100.0
    assert [(n.idnumber, n.peso) for n in hijos(d, "TZ_V_2")] == [("TZ_V_2_RA1", 100.0)]
    assert [(n.idnumber, n.peso) for n in hijos(d, "TZ_V_2_RA1")] == [("TZ_V_2_CA2", 100.0)]
    assert not [n for n in d.nodos if n.idnumber == "TZ_V_2_CA1"]
    assert copia_de(d, "u1/c.md", "TZ_V_1_RA2").peso == 100.0
    assert d.avisos == ()


def test_criterios_sin_peso_pesan_igual_y_avisan() -> None:
    sin_peso = Elemento(
        "RA1",
        "Redes",
        60.0,
        criterios=tuple(Criterio(f"CA{i}", f"Criterio {i}", None, None) for i in (1, 2, 3)),
    )
    docs = [doc("u1/a.md", 1, CA1=100), doc("u1/b.md", 1, CA2=100), doc("u1/c.md", 1, CA3=100)]
    esquema = con_criterios(elementos=(sin_peso, RA2_SIMPLE))
    d = deseado(esquema, docs, False, CARPETA)
    assert [n.peso for n in hijos(d, "TZ_E_RA1")] == [33.33, 33.33, 33.34]
    assert [n.peso for n in hijos(d, "TZ_V_1_RA1")] == [33.33, 33.33, 33.34]
    # el aviso va antes que los de elementos sin actividades
    assert d.avisos == (("CRITERIOS_SIN_PESO", "RA1"), ("ELEMENTO_SIN_ACTIVIDADES", "RA2"))


def test_la_vista_por_evaluaciones_renormaliza_los_criterios_presentes() -> None:
    tres = Elemento(
        "RA1",
        "Redes",
        100.0,
        criterios=(
            Criterio("CA1", "Uno", 50.0, None),
            Criterio("CA2", "Dos", 30.0, None),
            Criterio("CA3", "Tres", 20.0, None),
        ),
    )
    docs = [
        doc("u1/a.md", 1, CA1=100),
        doc("u2/b.md", 2, CA2=100),
        doc("u1/c.md", 1, CA3=100),
    ]
    d = deseado(con_criterios(elementos=(tres,)), docs, False, CARPETA)
    assert [n.peso for n in hijos(d, "TZ_E_RA1")] == [50.0, 30.0, 20.0]
    # primera evaluación: solo CA1 y CA3 -> 50/70 y 20/70
    assert [(n.idnumber, n.peso) for n in hijos(d, "TZ_V_1_RA1")] == [
        ("TZ_V_1_CA1", 71.43),
        ("TZ_V_1_CA3", 28.57),
    ]
    # segunda: solo CA2 -> 100
    assert [(n.idnumber, n.peso) for n in hijos(d, "TZ_V_2_RA1")] == [("TZ_V_2_CA2", 100.0)]


def test_actividad_en_dos_criterios_de_elementos_distintos() -> None:
    ra2 = Elemento("RA2", "Sistemas", 40.0, criterios=(Criterio("CB1", "Criterio c", None, None),))
    docs = [doc("u1/x.md", 1, CA1=100, CB1=100), doc("u2/b.md", 2, CA2=100)]
    for organizacion, real, copias in (
        (
            "elementos",
            "TZ_E_CA1",
            ["TZ_E_CB1", "TZ_V_1_CA1", "TZ_V_1_CB1"],
        ),
        (
            "evaluaciones",
            "TZ_V_1_CA1",
            ["TZ_E_CA1", "TZ_E_CB1", "TZ_V_1_CB1"],
        ),
    ):
        d = deseado(
            con_criterios(organizacion, elementos=(RA1_CRITERIOS, ra2)), docs, False, CARPETA
        )
        reales = [n for n in d.nodos if n.idnumber == "u1/x.md"]
        assert [(n.clase, n.padre) for n in reales] == [("actividad", real)], organizacion
        for padre in copias:
            assert copia_de(d, "u1/x.md", padre).peso == 100.0, (organizacion, padre)
        assert len([n for n in d.nodos if n.formula_de == "u1/x.md"]) == 3
        assert dict(d.actividades)["u1/x.md"] == real
    ids = [n.idnumber for n in d.nodos]
    assert len(ids) == len(set(ids))


INSTRUMENTO = Instrumento("exposicion", "Exposición", 1, (("CA1", 50.0), ("RA2", 100.0)))


def test_instrumento_manual_real_y_copias() -> None:
    docs = [doc("u1/a.md", 1, CA1=50), doc("u2/b.md", 2, CA2=100)]
    d = deseado(con_criterios(instrumentos=(INSTRUMENTO,)), docs, False, CARPETA)
    real = nodo(d, "TZ_M_exposicion")
    assert (real.clase, real.nombre, real.padre, real.peso, real.formula_de) == (
        "manual",
        "Exposición",
        "TZ_E_CA1",
        50.0,
        None,
    )
    # primero las actividades de fichero y luego el instrumento
    assert [n.idnumber for n in hijos(d, "TZ_E_CA1")] == ["u1/a.md", "TZ_M_exposicion"]
    assert [n.peso for n in hijos(d, "TZ_E_CA1")] == [50.0, 50.0]
    copias = [n for n in d.nodos if n.formula_de == "TZ_M_exposicion"]
    assert {n.padre for n in copias} == {"TZ_V_1_CA1", "TZ_E_RA2", "TZ_V_1_RA2"}
    assert all(n.clase == "copia" and n.nombre == "Exposición (copia)" for n in copias)
    assert copia_de(d, "TZ_M_exposicion", "TZ_V_1_CA1").peso == 50.0
    # la huella es la de siempre, con TZ_M_<id> como ruta
    huella = hashlib.sha256(b"TZ_M_exposicion|RA2|E").hexdigest()[:10]
    assert copia_de(d, "TZ_M_exposicion", "TZ_E_RA2").idnumber == f"TZ_C_{huella}"
    # no es un fichero con cmid
    assert "TZ_M_exposicion" not in dict(d.actividades)
    assert not [n for n in d.nodos if n.clase == "manual" and n.idnumber != "TZ_M_exposicion"]


def test_instrumento_real_en_la_vista_por_evaluaciones() -> None:
    d = deseado(
        con_criterios("evaluaciones", instrumentos=(INSTRUMENTO,)),
        [doc("u1/a.md", 1, CA1=50)],
        False,
        CARPETA,
    )
    assert nodo(d, "TZ_M_exposicion").padre == "TZ_V_1_CA1"
    assert copia_de(d, "TZ_M_exposicion", "TZ_E_CA1")
    assert nodo(d, "TZ_M_exposicion").clase == "manual"


def test_evalua_que_nombra_un_elemento_con_criterios() -> None:
    with pytest.raises(ErrorCalificacion) as info:
        deseado(con_criterios(), [doc("u1/a.md", 1, RA1=100)], False, CARPETA)
    assert info.value.codigo == "ELEMENTO_CON_CRITERIOS"
    assert (
        info.value.detalle
        == "u1/a.md: evalua nombra «RA1», que tiene criterios: nombra sus criterios"
    )
    malo = Instrumento("exposicion", "Exposición", 1, (("RA1", 100.0),))
    with pytest.raises(ErrorCalificacion) as info:
        deseado(con_criterios(instrumentos=(malo,)), [], False, CARPETA)
    assert info.value.codigo == "ELEMENTO_CON_CRITERIOS"
    assert info.value.detalle.startswith("instrumentos[0]: ")


def test_criterio_inexistente_es_elemento_desconocido() -> None:
    with pytest.raises(ErrorCalificacion) as info:
        deseado(con_criterios(), [doc("u1/a.md", 1, CA9=100)], False, CARPETA)
    assert info.value.codigo == "ELEMENTO_DESCONOCIDO"
    assert "u1/a.md" in info.value.detalle and "CA9" in info.value.detalle
    assert "ni los criterios" in info.value.detalle
    malo = Instrumento("exposicion", "Exposición", 1, (("CA9", 100.0),))
    with pytest.raises(ErrorCalificacion) as info:
        deseado(con_criterios(instrumentos=(malo,)), [], False, CARPETA)
    assert info.value.codigo == "ELEMENTO_DESCONOCIDO"
    assert "instrumentos[0]" in info.value.detalle


def test_los_pesos_se_comprueban_por_hoja_contando_instrumentos() -> None:
    docs = [doc("u1/a.md", 1, CA1=60)]
    instrumento = Instrumento("exposicion", "Exposición", 1, (("CA1", 60.0),))
    with pytest.raises(ErrorCalificacion) as info:
        deseado(con_criterios(instrumentos=(instrumento,)), docs, False, CARPETA)
    assert info.value.codigo == "PESOS_NO_SUMAN_100"
    assert info.value.detalle.startswith("CA1: ") and "120" in info.value.detalle
    assert "u1/a.md" in info.value.detalle and "TZ_M_exposicion" in info.value.detalle
    # suman 100 con el instrumento (y CA2, RA2 sin nada: suman 0)
    ok = Instrumento("exposicion", "Exposición", 1, (("CA1", 40.0),))
    d = deseado(con_criterios(instrumentos=(ok,)), docs, False, CARPETA)
    assert [n.peso for n in hijos(d, "TZ_E_CA1")] == [60.0, 40.0]


def test_instrumento_en_seccion_sin_evaluacion() -> None:
    malo = Instrumento("exposicion", "Exposición", 9, (("CA1", 100.0),))
    with pytest.raises(ErrorCalificacion) as info:
        deseado(con_criterios(instrumentos=(malo,)), [], False, CARPETA)
    assert info.value.codigo == "SECCION_SIN_EVALUACION"
    assert "instrumentos[0]" in info.value.detalle


def test_elemento_con_criterios_cuenta_los_instrumentos_como_actividades() -> None:
    solo = Instrumento("exposicion", "Exposición", 1, (("CA2", 100.0),))
    d = deseado(con_criterios(instrumentos=(solo,)), [], False, CARPETA)
    assert d.avisos == (("ELEMENTO_SIN_ACTIVIDADES", "RA2"),)
    assert d.actividades == ()


def test_con_tope_los_indicadores_cubren_los_hijos_de_los_criterios() -> None:
    docs = [
        doc("u1/a.md", 1, CA1=100),
        doc("u1/b.md", 1, CA2=60),
        doc("u2/c.md", 2, CA2=40, RA2=100),
    ]
    instrumento = Instrumento("exposicion", "Exposición", 1, (("CA1", 0.0),))
    # el instrumento pesa 0 en CA1 (que suma 100 con a.md) y no cuenta
    d = deseado(
        con_criterios(tope=Tope(5.0, 4.0), instrumentos=(instrumento,)), docs, False, CARPETA
    )
    en_criterios = [h for c in ("TZ_E_CA1", "TZ_E_CA2") for h in hijos(d, c) if h.peso]
    indicadores = hijos(d, "TZ_K_RA1")
    assert [i.formula_de for i in indicadores] == [h.idnumber for h in en_criterios]
    assert len(indicadores) == 3
    assert "TZ_M_exposicion" not in {i.formula_de for i in indicadores}
    assert nodo(d, "TZ_NOTA_E_RA1").formula_de == ("TZ_E_RA1", "TZ_K_RA1")
    # c.md es real en CA2 (su primera hoja): en RA2 está su copia
    assert [i.formula_de for i in hijos(d, "TZ_K_RA2")] == [hijos(d, "TZ_E_RA2")[0].idnumber]
    for i in indicadores:
        assert re.fullmatch(r"TZ_I_[0-9a-f]{10}", i.idnumber)
    assert d.tope == (5.0, 4.0, ("TZ_NOTA_E_RA1", "TZ_NOTA_E_RA2"))
    ids = [n.idnumber for n in d.nodos]
    assert len(ids) == len(set(ids))


def test_el_indicador_de_una_casilla_real_apunta_a_su_idnumber() -> None:
    instrumento = Instrumento("exposicion", "Exposición", 1, (("CA1", 100.0),))
    d = deseado(con_criterios(tope=Tope(5.0, 4.0), instrumentos=(instrumento,)), [], False, CARPETA)
    assert [i.formula_de for i in hijos(d, "TZ_K_RA1")] == ["TZ_M_exposicion"]


def test_criterios_e_instrumentos_sin_referencias_circulares() -> None:
    docs = [doc("u1/a.md", 1, CA1=50), doc("u2/b.md", 2, CA2=100)]
    for organizacion in ("elementos", "evaluaciones"):
        esquema = con_criterios(organizacion, Tope(5.0, 4.0), instrumentos=(INSTRUMENTO,))
        d = deseado(esquema, docs, False, CARPETA)
        comprobar_sin_circulares(d.nodos)
        for n in d.nodos:
            if n.formula_de is None:
                continue
            fuentes = n.formula_de if isinstance(n.formula_de, tuple) else (n.formula_de,)
            assert not set(fuentes) & _antepasados(d, n.idnumber), n.idnumber
        assert d.avisos == ()
