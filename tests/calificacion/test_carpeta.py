"""Avisos de la carpeta del calificador: actividades calificables sin criterios."""

from __future__ import annotations

from pathlib import Path

from tiza import agente
from tiza.calificacion.carpeta import actividades_sin_evalua
from tiza.calificacion.esquema import Elemento, Esquema, Final
from tiza.contenido import Documento

CARPETA = Path("/curso")
ESQUEMA = Esquema(
    "elementos",
    (Elemento("RA1", "Redes", 100.0),),
    (),
    Final("elementos"),
    etapa="eso",
)


def doc(nombre: str, tipo: str, evalua=None) -> Documento:
    return Documento(
        ruta=CARPETA / nombre,
        tipo=tipo,
        nombre=Path(nombre).stem,
        seccion=1,
        cuerpo="",
        html="",
        recursos=[],
        evalua=evalua,
    )


def test_sin_evalua_lista_tareas_y_cuestionarios_en_eso() -> None:
    documentos = [
        doc("tarea.md", "tarea"),
        doc("test.md", "cuestionario"),
        doc("h5p.md", "h5p"),
        doc("con_criterios.md", "tarea", (("RA1", 100),)),
    ]
    assert actividades_sin_evalua(ESQUEMA, documentos, CARPETA) == [
        "h5p.md",
        "tarea.md",
        "test.md",
    ]


def test_sin_evalua_no_lista_paginas_ni_etiquetas() -> None:
    documentos = [doc("pagina.md", "pagina"), doc("etiqueta.md", "etiqueta")]
    assert actividades_sin_evalua(ESQUEMA, documentos, CARPETA) == []


def test_actividad_sin_evalua_en_fp() -> None:
    documentos = [doc("tarea.md", "tarea")]
    fp = Esquema("elementos", ESQUEMA.elementos, (), Final("elementos"), etapa="fp")
    sin_etapa = Esquema("elementos", ESQUEMA.elementos, (), Final("elementos"))
    assert actividades_sin_evalua(fp, documentos, CARPETA) == ["tarea.md"]
    assert actividades_sin_evalua(sin_etapa, documentos, CARPETA) == ["tarea.md"]


def test_comprobar_esquema_informa_el_aviso_sin_fallar(tmp_path: Path) -> None:
    (tmp_path / "calificacion.yaml").write_text(
        "etapa: eso\norganizacion: elementos\n"
        "elementos:\n  - {id: RA1, nombre: Redes, peso: 100}\n"
        "final: {de: elementos}\n",
        encoding="utf-8",
    )
    (tmp_path / "tarea.md").write_text(
        "---\ntipo: tarea\nnombre: Problemas\nseccion: 1\n"
        "apertura: 2026-10-01\nentrega: 2026-10-10\n---\n\nResuelve.\n",
        encoding="utf-8",
    )
    resultado = agente.comprobar(tmp_path, ["calificacion.yaml"])
    assert resultado.informe["errores"] == []
    avisos = [
        paso for paso in resultado.informe["pasos"] if paso["codigo"] == "ACTIVIDAD_SIN_EVALUA"
    ]
    assert [paso["detalle"] for paso in avisos] == ["tarea.md"]


def test_comprobar_no_ignora_una_actividad_que_solo_falla_por_recupera(tmp_path: Path) -> None:
    (tmp_path / "calificacion.yaml").write_text(
        "etapa: eso\norganizacion: elementos\n"
        "elementos:\n  - {id: RA1, nombre: Redes, peso: 100}\n"
        "final: {de: elementos}\n",
        encoding="utf-8",
    )
    (tmp_path / "tarea.md").write_text(
        "---\ntipo: tarea\nnombre: Problemas\nseccion: 1\n"
        "apertura: 2026-10-01\nentrega: 2026-10-10\nrecupera: 2\n---\n\nResuelve.\n",
        encoding="utf-8",
    )
    resultado = agente.comprobar(tmp_path, ["calificacion.yaml"])
    assert resultado.informe["errores"] == ["RECUPERA_INVALIDO"]
