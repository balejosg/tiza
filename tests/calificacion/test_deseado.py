"""Estructura deseada del calificador a partir del esquema y de las actividades. Offline y pura."""

from __future__ import annotations

from pathlib import Path

import pytest

from tiza.calificacion.deseado import Deseado, Nodo, deseado
from tiza.calificacion.esquema import (
    Elemento,
    ErrorCalificacion,
    Esquema,
    Evaluacion,
    Final,
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
    assert nodo(d, "unidad1/practica1.md").peso == 40.0
    assert sum(n.peso or 0 for n in hijos(d, "TZ_E_RA1")) == 100.0


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
    assert nodo(d, "TZ_V_1").padre == "TZ_TIZA" and nodo(d, "TZ_V_1").peso == 30.0
    assert nodo(d, "TZ_V_3").peso == 40.0
    assert nodo(d, "TZ_VISTA").peso == 0.0
    assert nodo(d, "TZ_E_RA1").padre == "TZ_VISTA"
    assert [n.idnumber for n in hijos(d, "TZ_TIZA")] == ["TZ_V_1", "TZ_V_2", "TZ_V_3", "TZ_VISTA"]


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
    assert [n.idnumber for n in hijos(d, "TZ_TIZA")] == [
        "TZ_E_RA1",
        "TZ_E_RA2",
        "TZ_E_RA3",
        "TZ_VISTA",
    ]
    assert [n.peso for n in hijos(d, "TZ_TIZA")] == [40.0, 30.0, 30.0, 0.0]
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
    assert final.formula_de == ("TZ_TIZA", "TZ_K_TIZA") and final.padre == "TZ_NOTAS"
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
