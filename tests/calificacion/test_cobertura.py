"""Mapa de cobertura del calificador: criterios, instrumentos y avisos. Offline y puro."""

from __future__ import annotations

from pathlib import Path

from tiza.calificacion.cobertura import avisos, cobertura
from tiza.calificacion.deseado import reparto_por_hoja
from tiza.calificacion.esquema import (
    Agregacion,
    Criterio,
    Elemento,
    Esquema,
    Evaluacion,
    Final,
    Instrumento,
)
from tiza.contenido import Documento
from tiza.rubrica import CriterioRubrica, Nivel, RubricaCargada

CARPETA = Path("/curso")

ELEMENTOS = (
    Elemento(
        "CE1",
        "Competencia 1",
        100.0,
        "CE1",
        (
            Criterio("CE1_1", "Criterio 1.1", 50.0, "1.1"),
            Criterio("CE1_2", "Criterio 1.2", 50.0, "1.2"),
        ),
    ),
)
EVALUACIONES = (
    Evaluacion("Primera", (1,)),
    Evaluacion("Segunda", (2,)),
)
ESQUEMA = Esquema("elementos", ELEMENTOS, EVALUACIONES, Final("elementos"), etapa="eso")


def doc(
    ruta: str,
    seccion: int | str = 1,
    *,
    tipo: str = "tarea",
    evidencia: str | None = None,
    rubrica: RubricaCargada | None = None,
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
        evalua=tuple(evalua.items()) or None,
        evidencia=evidencia,
        rubrica=rubrica,
        recupera=recupera,
    )


def rubrica(*, filas: bool) -> RubricaCargada:
    """Una rúbrica mínima; ``criterio`` solo lo llevan las de filas, como en producción."""
    return RubricaCargada(
        nombre="Rúbrica",
        descripcion="",
        html="",
        criterios=(
            CriterioRubrica(
                id="ce1_1",
                nombre="Criterio 1.1",
                descripcion="",
                niveles=(Nivel("inicial", 0.0, "No iniciado"), Nivel("final", 10.0, "Logrado")),
                criterio="CE1_1" if filas else None,
            ),
        ),
    )


def esquema_de_hojas(*reglas: str, evaluaciones: tuple[Evaluacion, ...] = EVALUACIONES) -> Esquema:
    """Un elemento con una hoja por regla, todas sin criterios propios."""
    elementos = tuple(
        Elemento(f"RA{i}", f"Resultado {i}", 100.0 / len(reglas), regla=regla)
        for i, regla in enumerate(reglas, 1)
    )
    return Esquema(
        "elementos",
        elementos,
        evaluaciones,
        Final("elementos"),
        agregacion=Agregacion("media", ()),
    )


def mapa(esquema: Esquema, documentos: list[Documento]):
    return cobertura(esquema, documentos, CARPETA)


def hoja(m: object, id_: str):
    return next(h for h in m.hojas if h.id == id_)


def codigos(m: object, esquema: Esquema) -> list[tuple[str, str]]:
    return list(avisos(m, esquema))


def test_hoja_vacia_aparece_en_el_mapa() -> None:
    m = mapa(ESQUEMA, [doc("uno.md", CE1_1=100)])
    assert [h.id for h in m.hojas] == ["CE1_1", "CE1_2"]
    vacia = hoja(m, "CE1_2")
    assert vacia.evidencias == ()
    assert vacia.nombre == "Criterio 1.2"
    assert vacia.codigo == "1.2"
    assert vacia.elemento == "CE1"
    assert vacia.regla == "media"
    assert codigos(m, ESQUEMA) == [
        ("HOJA_CON_UNA_EVIDENCIA", "CE1_1: uno"),
        ("HOJA_SIN_EVIDENCIAS", "CE1_2"),
    ]


def test_instrumento_deducido_por_tipo() -> None:
    esquema = esquema_de_hojas("media", "media", "media", "media", "media", "media", "media")
    documentos = [
        doc("tarea.md", RA1=100),
        doc("criterios.md", RA2=100, rubrica=rubrica(filas=False)),
        doc("filas.md", RA3=100, rubrica=rubrica(filas=True)),
        doc("resultados.md", RA4=100, evidencia="resultados"),
        doc("cuestionario.md", RA5=100, tipo="cuestionario"),
        doc("h5p.md", RA6=100, tipo="h5p"),
    ]
    esquema = Esquema(
        esquema.organizacion,
        esquema.elementos,
        esquema.evaluaciones,
        esquema.final,
        (Instrumento("EXAMEN", "Examen oral", 1, (("RA7", 100.0),)),),
        agregacion=esquema.agregacion,
    )
    m = mapa(esquema, documentos)
    instrumentos = {e.ruta: e.instrumento for h in m.hojas for e in h.evidencias}
    assert instrumentos == {
        "tarea.md": "tarea",
        "criterios.md": "tarea_rubrica_criterios",
        "filas.md": "tarea_rubrica_filas",
        "resultados.md": "tarea_resultados",
        "cuestionario.md": "cuestionario",
        "h5p.md": "h5p",
        "instrumentos[0]": "casilla_manual",
    }


def test_recuperacion_marcada_y_no_cuenta_para_avisos() -> None:
    normal = doc("normal.md", 1, CE1_1=100)
    recuperacion = doc("recupera.md", 2, CE1_1=100, recupera=(1,))
    m = mapa(ESQUEMA, [normal, recuperacion])
    evidencias = hoja(m, "CE1_1").evidencias
    assert [(e.ruta, e.recupera) for e in evidencias] == [
        ("normal.md", ()),
        ("recupera.md", (1,)),
    ]
    assert codigos(m, ESQUEMA) == [
        ("HOJA_CON_UNA_EVIDENCIA", "CE1_1: normal"),
        ("HOJA_SIN_EVIDENCIAS", "CE1_2"),
    ]

    solo_recuperacion = mapa(ESQUEMA, [recuperacion])
    assert codigos(solo_recuperacion, ESQUEMA) == [
        ("HOJA_SIN_EVIDENCIAS", "CE1_1"),
        ("HOJA_SIN_EVIDENCIAS", "CE1_2"),
    ]


def test_aviso_hoja_sin_evidencias() -> None:
    m = mapa(ESQUEMA, [doc("uno.md", CE1_1=100)])
    assert ("HOJA_SIN_EVIDENCIAS", "CE1_2") in codigos(m, ESQUEMA)


def test_aviso_hoja_con_una_evidencia() -> None:
    m = mapa(ESQUEMA, [doc("Tarea maqueta.md", CE1_1=100)])
    assert ("HOJA_CON_UNA_EVIDENCIA", "CE1_1: Tarea maqueta") in codigos(m, ESQUEMA)


def test_aviso_mediana_con_dos() -> None:
    esquema = esquema_de_hojas("mediana")
    documentos = [doc("a.md", RA1=50), doc("b.md", RA1=50)]
    assert ("MEDIANA_CON_POCAS_EVIDENCIAS", "RA1: 2 evidencias") in codigos(
        mapa(esquema, documentos), esquema
    )


def test_mediana_sin_evidencias_solo_avisa_del_hueco() -> None:
    esquema = esquema_de_hojas("mediana")
    avisos = codigos(mapa(esquema, []), esquema)
    assert [c for c, _ in avisos if c.startswith("MEDIANA")] == []
    assert ("HOJA_SIN_EVIDENCIAS", "RA1") in avisos


def test_aviso_progresiva_en_una_evaluacion() -> None:
    esquema = Esquema(
        "elementos",
        (Elemento("RA1", "Resultado", 100.0, regla="progresiva"),),
        EVALUACIONES,
        Final("elementos"),
        agregacion=Agregacion("progresiva", (1.0, 2.0)),
    )
    una = mapa(esquema, [doc("a.md", 1, RA1=50), doc("b.md", 1, RA1=50)])
    assert ("PROGRESIVA_EN_UNA_EVALUACION", "RA1: evaluación 1") in codigos(una, esquema)

    dos = mapa(esquema, [doc("a.md", 1, RA1=50), doc("b.md", 2, RA1=50)])
    assert not [c for c in codigos(dos, esquema) if c[0] == "PROGRESIVA_EN_UNA_EVALUACION"]


def test_peso_normalizado_igual_que_reparto() -> None:
    documentos = [doc("a.md", CE1_1=40), doc("b.md", CE1_1=60)]
    m = mapa(ESQUEMA, documentos)
    esperado = dict(reparto_por_hoja(ESQUEMA, documentos, CARPETA))["CE1_1"]
    assert [(e.nombre, e.peso) for e in hoja(m, "CE1_1").evidencias] == list(esperado)


def test_casilla_manual_cuenta_como_evidencia() -> None:
    esquema = Esquema(
        "elementos",
        (Elemento("RA1", "Resultado", 100.0),),
        (Evaluacion("Primera", (1,)),),
        Final("elementos"),
        (Instrumento("EXAMEN", "Examen oral", 1, (("RA1", 100.0),)),),
    )
    m = mapa(esquema, [])
    [evidencia] = hoja(m, "RA1").evidencias
    assert (evidencia.ruta, evidencia.instrumento, evidencia.evaluacion) == (
        "instrumentos[0]",
        "casilla_manual",
        1,
    )
    assert codigos(m, esquema) == [("HOJA_CON_UNA_EVIDENCIA", "RA1: Examen oral")]


def test_orden_estable() -> None:
    documentos = [doc("z.md", CE1_1=50), doc("a.md", CE1_2=100), doc("m.md", CE1_1=50)]
    uno = mapa(ESQUEMA, documentos)
    otro = mapa(ESQUEMA, documentos)
    assert uno == otro
    assert [h.id for h in uno.hojas] == ["CE1_1", "CE1_2"]
    assert [e.ruta for e in hoja(uno, "CE1_1").evidencias] == ["m.md", "z.md"]
