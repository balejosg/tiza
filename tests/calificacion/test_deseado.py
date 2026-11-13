"""Estructura deseada del calificador a partir del esquema y de las actividades. Offline y pura."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from tiza.calificacion.deseado import (
    CLASES,
    Deseado,
    Nodo,
    comprobar_sin_circulares,
    deseado,
    detalle_tope,
    evidencias_por_hoja,
    reparto_por_hoja,
)
from tiza.calificacion.esquema import (
    Agregacion,
    Criterio,
    Elemento,
    ErrorCalificacion,
    Esquema,
    Evaluacion,
    Final,
    Tope,
)
from tiza.contenido import Documento
from tiza.rubrica_tarea import FilaDeResultado, RubricaDeFilas, clave_de_fila

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
    (Elemento("CE1", "Competencia", 100.0, "CE1"),),
    (
        Evaluacion("Primera", (1,), 30.0),
        Evaluacion("Segunda", (2,), 30.0),
        Evaluacion("Tercera", (3,), 40.0),
    ),
    Final("evaluaciones"),
)

ELEMENTOS_CRITERIOS = (
    Elemento(
        "RA1",
        "Redes locales",
        60.0,
        "RA1",
        (
            Criterio("RA1_a", "Criterio a", 50.0, "a"),
            Criterio("RA1_b", "Criterio b", 50.0, "b"),
        ),
    ),
    Elemento("RA2", "Sistemas", 40.0, "RA2", regla="mas_alta"),
)
EVALUACIONES_CRITERIOS = (
    Evaluacion("Primera", (1,)),
    Evaluacion("Segunda", (2,)),
    Evaluacion("Tercera", (3,)),
)
E1 = Esquema(
    "elementos",
    ELEMENTOS_CRITERIOS,
    EVALUACIONES_CRITERIOS,
    Final("elementos", Tope(5.0, 4.0)),
    etapa="fp",
)


def doc(
    ruta: str,
    seccion: int | str,
    *,
    tipo: str = "pagina",
    evidencia: str | None = None,
    recupera: tuple[int, ...] | None = None,
    **evalua: float,
) -> Documento:
    return Documento(
        ruta=CARPETA / ruta,
        tipo=tipo,
        nombre=Path(ruta).stem,
        seccion=seccion,
        cuerpo="",
        html="",
        recursos=[],
        evalua=tuple(evalua.items()),
        evidencia=evidencia,
        recupera=recupera,
    )


def tarea(ruta: str, seccion: int | str, **evalua: float) -> Documento:
    """Una tarea con «evidencia: resultados»: el árbol pone resultados y calculados."""
    return doc(ruta, seccion, tipo="tarea", evidencia="resultados", **evalua)


def completo() -> list[Documento]:
    """Pesos que suman 100 por RA: RA1 en dos trimestres, RA2 y RA3 en uno."""
    return [
        doc("unidad1/practica1.md", 1, RA1=40),
        doc("unidad2/practica2.md", 2, RA1=20),
        doc("unidad5/examen.md", 5, RA1=40, RA2=30),
        doc("unidad3/redes.md", 3, RA2=70),
        doc("unidad5/seguridad.md", 5, RA3=100),
    ]


def documentos_e1() -> list[Documento]:
    """La prueba de EducaMadrid: RA1 con a y b, RA2 más alta y la recuperación."""
    return [
        tarea("proyecto.md", 1, RA1_a=50, RA1_b=50),
        doc("practica.md", 1, RA2=100),
        doc("recuperacion.md", 2, RA2=100, recupera=(1,)),
    ]


def nodo(d: Deseado, idnumber: str) -> Nodo:
    return next(n for n in d.nodos if n.idnumber == idnumber)


def hijos(d: Deseado, padre: str) -> list[Nodo]:
    return [n for n in d.nodos if n.padre == padre]


def de_clase(d: Deseado, clase: str) -> list[Nodo]:
    return [n for n in d.nodos if n.clase == clase]


def copias(d: Deseado, padre: str) -> list[Nodo]:
    return [n for n in hijos(d, padre) if n.clase == "copia"]


def test_clases_del_arbol() -> None:
    assert set(CLASES) == {
        "contenedor",
        "categoria",
        "actividad",
        "manual",
        "copia",
        "nota",
        "resultado",
        "resultado_calc",
    }


def test_fp_la_vista_primaria_es_la_de_evaluaciones() -> None:
    d = deseado(FP, completo(), False, CARPETA)
    assert nodo(d, "TZ_TIZA").clase == "contenedor"
    assert nodo(d, "TZ_FINAL").padre == "TZ_TIZA"
    assert nodo(d, "TZ_VISTA").padre == "TZ_TIZA"
    assert nodo(d, "TZ_VISTA").nombre == "Por evaluaciones"
    assert nodo(d, "TZ_V_1").padre == "TZ_VISTA"
    assert nodo(d, "TZ_V_1_RA1").padre == "TZ_V_1"
    real = nodo(d, "unidad1/practica1.md")
    assert (real.clase, real.padre, real.peso) == ("actividad", "TZ_V_1_RA1", 66.67)
    assert nodo(d, "unidad5/examen.md").padre == "TZ_V_3_RA1"
    assert copias(d, "TZ_V_3_RA2")[0].formula_de == "unidad5/examen.md"


def test_fp_las_copias_del_curso_llevan_q_n() -> None:
    d = deseado(FP, completo(), False, CARPETA)
    ra1 = copias(d, "TZ_E_RA1")
    assert [(c.nombre, c.peso, c.formula_de) for c in ra1] == [
        ("RA1 · 1.ª evaluación", 50.0, "TZ_V_1_RA1"),
        ("RA1 · 3.ª evaluación", 50.0, "TZ_V_3_RA1"),
    ]
    assert [c.peso for c in copias(d, "TZ_E_RA2")] == [50.0, 50.0]
    assert [c.peso for c in copias(d, "TZ_E_RA3")] == [100.0]


def test_fp_la_final_cuelga_de_los_elementos_y_la_vista_no() -> None:
    d = deseado(FP, completo(), False, CARPETA)
    assert [n.idnumber for n in hijos(d, "TZ_FINAL")] == [
        "TZ_E_RA1",
        "TZ_E_RA2",
        "TZ_E_RA3",
    ]
    assert [n.peso for n in hijos(d, "TZ_FINAL")] == [40.0, 30.0, 30.0]
    assert nodo(d, "TZ_VISTA").peso == 0.0
    assert nodo(d, "TZ_V_1").peso == 0.0


def test_eso_la_final_cuelga_de_las_evaluaciones() -> None:
    d = deseado(
        ESO,
        [doc("a.md", 1, CE1=100), doc("b.md", 2, CE1=100), doc("c.md", 3, CE1=100)],
        False,
        CARPETA,
    )
    assert nodo(d, "TZ_VISTA").nombre == "Por competencias"
    assert [n.idnumber for n in hijos(d, "TZ_FINAL")] == ["TZ_V_1", "TZ_V_2", "TZ_V_3"]
    assert [n.peso for n in hijos(d, "TZ_FINAL")] == [30.0, 30.0, 40.0]
    assert nodo(d, "TZ_VISTA").peso == 0.0


def test_evaluacion_sin_actividades_no_existe() -> None:
    d = deseado(FP, [doc("unidad1/practica1.md", 1, RA1=100)], False, CARPETA)
    assert all(n.idnumber != "TZ_V_2" for n in d.nodos)
    assert all(n.idnumber != "TZ_E_RA2" for n in d.nodos)


def test_ninguna_categoria_queda_vacia() -> None:
    for d in (
        deseado(FP, completo(), False, CARPETA),
        deseado(FP, [doc("unidad1/practica1.md", 1, RA1=100)], False, CARPETA),
        deseado(E1, documentos_e1(), False, CARPETA),
    ):
        for categoria in (n for n in d.nodos if n.clase in ("contenedor", "categoria")):
            assert hijos(d, categoria.idnumber), categoria.idnumber


def test_la_media_ponderada_es_la_agregacion_por_defecto() -> None:
    d = deseado(FP, completo(), False, CARPETA)
    for n in d.nodos:
        if n.clase in ("contenedor", "categoria") and n.idnumber not in (
            "TZ_E_RA2",
            "TZ_E_RA3",
        ):
            assert n.agregacion == 10, n.idnumber


def test_regla_mas_alta_en_los_dos_sitios() -> None:
    d = deseado(E1, documentos_e1(), False, CARPETA)
    assert nodo(d, "TZ_E_RA2").agregacion == 6
    assert nodo(d, "TZ_V_1_RA2").agregacion == 6
    assert nodo(d, "TZ_E_RA1").agregacion == 10


def test_regla_mediana_en_los_dos_sitios() -> None:
    esquema = Esquema(
        "elementos",
        (Elemento("RA1", "Redes", 100.0, regla="mediana"),),
        EVALUACIONES[:1],
        Final("elementos"),
    )
    d = deseado(esquema, [doc("a.md", 1, RA1=100)], False, CARPETA)
    assert nodo(d, "TZ_V_1_RA1").agregacion == 2
    assert nodo(d, "TZ_E_RA1").agregacion == 2


def test_lo_que_pesa_cero_sube_al_ancestro_de_media_ponderada() -> None:
    esquema = Esquema(
        "elementos",
        (
            Elemento(
                "RA1",
                "Redes",
                100.0,
                criterios=(Criterio("a", "Criterio", 100.0, regla="mas_alta"),),
            ),
        ),
        (Evaluacion("Primera", (1,)),),
        Final("elementos"),
    )
    d = deseado(
        esquema,
        [doc("nueve.md", 1, a=0), doc("cinco.md", 1, a=100)],
        False,
        CARPETA,
    )
    assert nodo(d, "nueve.md").padre == "TZ_V_1_RA1"
    assert nodo(d, "nueve.md").peso == 0.0
    assert nodo(d, "cinco.md").padre == "TZ_V_1_a"
    assert nodo(d, "cinco.md").peso is None


def test_progresiva_multiplica_los_q_n() -> None:
    esquema = Esquema(
        "elementos",
        (Elemento("RA1", "Redes", 100.0, regla="progresiva"),),
        (
            Evaluacion("Primera", (1,), 50.0),
            Evaluacion("Segunda", (2,), 50.0),
        ),
        Final("elementos"),
        agregacion=Agregacion("progresiva", (1.0, 2.0)),
    )
    d = deseado(
        esquema,
        [doc("a.md", 1, RA1=100), doc("b.md", 2, RA1=100)],
        False,
        CARPETA,
    )
    copias_ra1 = copias(d, "TZ_E_RA1")
    assert [c.peso for c in copias_ra1] == [50.0, 100.0]
    assert nodo(d, "TZ_V_1_RA1").agregacion == 10
    assert nodo(d, "TZ_E_RA1").agregacion == 10


def test_recuperacion_en_media_envuelve_la_copia() -> None:
    esquema = Esquema(
        "elementos",
        (Elemento("RA2", "Sistemas", 100.0),),
        (Evaluacion("Primera", (1,)), Evaluacion("Segunda", (2,))),
        Final("elementos"),
    )
    d = deseado(
        esquema,
        [
            doc("practica.md", 1, RA2=100),
            doc("recuperacion.md", 2, RA2=100, recupera=(1,)),
        ],
        False,
        CARPETA,
    )
    (rm,) = [n for n in hijos(d, "TZ_E_RA2") if n.idnumber.startswith("TZ_RM_")]
    assert (rm.clase, rm.agregacion, rm.peso) == ("categoria", 6, 100.0)
    assert [n.clase for n in hijos(d, rm.idnumber)] == ["copia", "actividad"]
    assert nodo(d, "recuperacion.md").padre == rm.idnumber
    assert dict(d.actividades)["recuperacion.md"] == rm.idnumber
    assert all(n.idnumber != "TZ_V_2" for n in d.nodos)


def test_recuperacion_en_mas_alta_va_suelta() -> None:
    d = deseado(E1, documentos_e1(), False, CARPETA)
    assert not any(n.idnumber.startswith("TZ_RM_") for n in d.nodos)
    assert nodo(d, "recuperacion.md").padre == "TZ_E_RA2"
    assert [n.clase for n in hijos(d, "TZ_E_RA2")] == ["copia", "actividad"]


def test_recuperacion_en_dos_trimestres() -> None:
    esquema = Esquema(
        "elementos",
        (Elemento("RA2", "Sistemas", 100.0),),
        (
            Evaluacion("Primera", (1,)),
            Evaluacion("Segunda", (2,)),
            Evaluacion("Tercera", (3,)),
        ),
        Final("elementos"),
    )
    d = deseado(
        esquema,
        [
            doc("practica1.md", 1, RA2=100),
            doc("practica2.md", 2, RA2=100),
            doc("recuperacion.md", 3, RA2=100, recupera=(1, 2)),
        ],
        False,
        CARPETA,
    )
    grupos = [n for n in hijos(d, "TZ_E_RA2") if n.idnumber.startswith("TZ_RM_")]
    assert len(grupos) == 2
    assert nodo(d, "recuperacion.md").padre == grupos[0].idnumber
    copia = next(
        n
        for n in hijos(d, grupos[1].idnumber)
        if n.clase == "copia" and n.formula_de == "recuperacion.md"
    )
    assert copia.peso is None


def test_resultados_por_criterio() -> None:
    d = deseado(E1, documentos_e1(), False, CARPETA)
    # La tarea real está en el primer criterio, con peso 0.
    assert nodo(d, "proyecto.md").padre == "TZ_V_1_RA1_a"
    assert nodo(d, "proyecto.md").peso == 0.0
    # Cada criterio lleva su resultado y su calculado; el calculado lleva el peso.
    assert len(de_clase(d, "resultado")) == 2
    assert len(de_clase(d, "resultado_calc")) == 2
    for calculado in de_clase(d, "resultado_calc"):
        assert calculado.maximo == 100.0
        assert calculado.peso == 100.0
        assert calculado.formula_de is not None
        assert nodo(d, calculado.formula_de).clase == "resultado"
    assert not any(n.idnumber.startswith("TZ_F_") for n in d.nodos)


def test_resultados_por_fila_sin_subcategoria_filas() -> None:
    esquema = Esquema(
        "elementos",
        (
            Elemento(
                "CE1",
                "Competencia",
                100.0,
                criterios=(Criterio("CE1_1", "Criterio", 100.0, "1.1"),),
            ),
        ),
        (Evaluacion("Primera", (1,)),),
        Final("elementos"),
    )
    filas = (
        FilaDeResultado(
            "CE1_1", "Planifica", 1.0, ("A", "B"), clave_de_fila("grua.md", "CE1_1", "Planifica")
        ),
        FilaDeResultado(
            "CE1_1", "Materiales", 2.0, ("A", "B"), clave_de_fila("grua.md", "CE1_1", "Materiales")
        ),
    )
    actividad = tarea("grua.md", 1, CE1_1=100)
    actividad.rubrica_filas = RubricaDeFilas("Rúbrica", filas)
    d = deseado(esquema, [actividad, doc("otra.md", 1, CE1_1=100)], False, CARPETA)
    assert not any(n.idnumber.startswith("TZ_F_") for n in d.nodos)
    calculados = de_clase(d, "resultado_calc")
    # Las filas se reparten 1/3 y 2/3 del 100 de la tarea; con la otra actividad (100) y
    # «solo no vacías», la renormalización del criterio deja 16,67 y 33,33.
    assert [c.peso for c in calculados] == [16.67, 33.33]
    assert all(n.nombre.endswith(("Planifica", "Materiales")) for n in calculados)
    assert all(c.padre == "TZ_V_1_CE1_1" for c in calculados)
    assert nodo(d, "grua.md").peso == 0.0


def test_el_tope_usa_los_totales_de_los_elementos() -> None:
    d = deseado(FP, completo(), False, CARPETA)
    assert d.tope == (5.0, 4.0, ("TZ_E_RA2",))
    assert nodo(d, "TZ_NOTA_FINAL").maximo == 100.0
    assert nodo(d, "TZ_NOTA_FINAL").padre == "TZ_TIZA"
    assert "RA2" in detalle_tope(d)


def test_sin_tope_no_hay_nota_final() -> None:
    d = deseado(FP_SIN_TOPE, completo(), False, CARPETA)
    assert d.tope is None
    assert all(n.idnumber != "TZ_NOTA_FINAL" for n in d.nodos)
    assert d.total_curso == "porcentaje"


def test_anterior_deja_la_raiz_a_cero_y_no_toca_el_curso() -> None:
    d = deseado(FP, completo(), True, CARPETA)
    assert nodo(d, "TZ_TIZA").peso == 0.0
    assert d.total_curso is None


def test_avisos_de_pesos_y_recuperacion() -> None:
    esquema = Esquema(
        "elementos",
        (Elemento("RA1", "Redes", 50.0, regla="mas_alta"), Elemento("RA2", "Sistemas", 50.0)),
        (Evaluacion("Primera", (1,), cerrada=True), Evaluacion("Segunda", (2,))),
        Final("elementos"),
    )
    d = deseado(
        esquema,
        [
            doc("a.md", 1, RA1=50),
            doc("b.md", 1, RA1=30),
            doc("ra2.md", 1, RA2=100),
            doc("c.md", 2, RA2=100, recupera=(1,)),
        ],
        False,
        CARPETA,
    )
    assert ("PESOS_SIN_EFECTO", "RA1") in d.avisos
    assert ("RECUPERACION_EN_CERRADA", "TZ_V_1") in d.avisos


def test_reparto_por_hoja_y_evidencias_siguen_siendo_las_del_esquema() -> None:
    reparto = dict(reparto_por_hoja(FP, completo(), CARPETA))
    assert reparto["RA1"] == (("practica1", 40.0), ("practica2", 20.0), ("examen", 40.0))
    hojas = {
        hoja: len(evidencias)
        for hoja, _, evidencias in evidencias_por_hoja(FP, completo(), CARPETA)
    }
    assert hojas["RA1"] == 3
    assert hojas["RA3"] == 1


def test_comprobar_sin_circulares() -> None:
    with pytest.raises(ErrorCalificacion) as info:
        comprobar_sin_circulares(
            (
                Nodo("TZ_A", "categoria", "A", None, 100.0),
                Nodo("TZ_B", "copia", "B", "TZ_A", 100.0, "TZ_A"),
            )
        )
    assert info.value.codigo == "REFERENCIA_CIRCULAR"


def test_el_escenario_de_educamadrid_cuenta_23_nodos() -> None:
    d = deseado(E1, documentos_e1(), False, CARPETA)
    assert len(d.nodos) == 23
    assert Counter(n.clase for n in d.nodos) == Counter(
        {
            "contenedor": 2,
            "categoria": 10,
            "copia": 3,
            "actividad": 3,
            "resultado": 2,
            "resultado_calc": 2,
            "nota": 1,
        }
    )
    assert [n.idnumber for n in hijos(d, "TZ_FINAL")] == ["TZ_E_RA1", "TZ_E_RA2"]
