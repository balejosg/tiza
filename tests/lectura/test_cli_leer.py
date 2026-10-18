"""CLI `tiza leer`: un JSON en stdout y la lectura en .tiza/lecturas/."""

from __future__ import annotations

import hashlib
import json
import sys

import pytest

from lectura import fabrica as f
from tiza import agente, ayuda, cli, estado


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    asignatura = tmp_path / "asignatura"
    asignatura.mkdir()
    monkeypatch.chdir(asignatura)
    return asignatura


def ejecutar(capsys, argv):
    codigo = cli.main(argv)
    return codigo, json.loads(capsys.readouterr().out)


def docx(ruta, nombre="prog.docx"):
    d = f.nuevo()
    d.add_heading("Programación", level=1)
    d.add_paragraph("Un párrafo")
    tabla = d.add_table(rows=1, cols=1)
    tabla.cell(0, 0).add_table(rows=1, cols=1)
    destino = ruta / nombre
    d.save(str(destino))
    return destino


def test_leer_escribe_en_lecturas(carpeta, capsys):
    ruta = docx(carpeta)
    codigo, resumen = ejecutar(capsys, ["leer", "prog.docx"])
    assert codigo == 0
    assert (carpeta / ".tiza" / "lecturas" / "prog.docx.txt").is_file()
    assert resumen["fichero"] == "prog.docx" and resumen["formato"] == "docx"
    assert resumen["lectura"] == ".tiza/lecturas/prog.docx.txt"
    assert resumen["bloques"] > 0
    assert resumen["tablas"] == 2  # cuenta también las anidadas
    assert resumen["paginas"] is None
    assert resumen["sha256"] == hashlib.sha256(ruta.read_bytes()).hexdigest()
    assert not (carpeta / ".tiza" / "informe.json").exists()


def test_leer_pdf_da_paginas(carpeta, capsys):
    (carpeta / "a.pdf").write_bytes(f.pdf_bytes([["Uno"], ["Dos"]]))
    codigo, resumen = ejecutar(capsys, ["leer", "a.pdf"])
    assert codigo == 0 and resumen["paginas"] == 2 and resumen["formato"] == "pdf"


def test_leer_fuera_de_la_carpeta(carpeta, capsys):
    docx(carpeta.parent, "otra.docx")
    codigo, salida = ejecutar(capsys, ["leer", "../otra.docx"])
    assert codigo == 2 and salida["error"] == "FICHERO_FUERA"


def test_leer_enlace_que_sale_de_la_carpeta(carpeta, capsys):
    destino = docx(carpeta.parent, "otra.docx")
    try:
        (carpeta / "enlace.docx").symlink_to(destino)
    except OSError:
        pytest.skip("sin enlaces simbólicos")
    codigo, salida = ejecutar(capsys, ["leer", "enlace.docx"])
    assert codigo == 2 and salida["error"] == "FICHERO_FUERA"


def test_leer_temporal_de_word(carpeta, capsys):
    docx(carpeta, "~$prog.docx")
    codigo, salida = ejecutar(capsys, ["leer", "~$prog.docx"])
    assert codigo == 2 and salida["error"] == "FICHERO_TEMPORAL"


def test_leer_oculto_y_carpetas_ocultas(carpeta, capsys):
    (carpeta / ".tiza").mkdir()
    docx(carpeta / ".tiza", "x.docx")
    docx(carpeta, ".oculto.docx")
    for ruta in (".tiza/x.docx", ".oculto.docx"):
        codigo, salida = ejecutar(capsys, ["leer", ruta])
        assert codigo == 2 and salida["error"] == "FICHERO_TEMPORAL"


def test_leer_extension_no_admitida(carpeta, capsys):
    (carpeta / "a.doc").write_bytes(b"x")
    codigo, salida = ejecutar(capsys, ["leer", "a.doc"])
    assert codigo == 2 and salida["error"] == "FORMATO_NO_ADMITIDO"


def test_leer_inexistente(carpeta, capsys):
    codigo, salida = ejecutar(capsys, ["leer", "nada.docx"])
    assert codigo == 2 and salida["error"] == "DOCUMENTO_AUSENTE"
    assert ayuda.explicar("DOCUMENTO_AUSENTE")


def test_leer_bloqueado(carpeta, capsys, monkeypatch):
    docx(carpeta)

    def bloqueado(*_args, **_kw):
        raise PermissionError

    monkeypatch.setattr("tiza.lectura.word.leer_bytes_acotado", bloqueado)
    codigo, salida = ejecutar(capsys, ["leer", "prog.docx"])
    assert codigo == 2 and salida["error"] == "FICHERO_BLOQUEADO"


def test_leer_otro_error_del_sistema(carpeta, capsys, monkeypatch):
    docx(carpeta)

    def roto(*_args, **_kw):
        raise OSError("disco")

    monkeypatch.setattr("tiza.lectura.word.leer_bytes_acotado", roto)
    codigo, salida = ejecutar(capsys, ["leer", "prog.docx"])
    assert codigo == 2 and salida["error"] == "FICHERO_BLOQUEADO"


def test_ruta_lectura_sanea_el_nombre(tmp_path):
    ruta = estado.ruta_lectura(tmp_path, tmp_path / "..x" / "a b..docx")
    assert ruta.parent == tmp_path / ".tiza" / "lecturas"
    assert ruta.name == "_x__a b_docx.txt"  # ruta relativa con «__», sin «..» ni separadores
    assert estado.ruta_lectura(tmp_path, tmp_path / "prog.docx").name == "prog.docx.txt"
    fuera = estado.ruta_lectura(tmp_path / "a", tmp_path / "b" / "x.docx")
    assert fuera.name == "x.docx.txt"  # fuera de la carpeta solo cuenta el nombre


def test_leer_nombre_realista_de_docente(carpeta, capsys):
    nombre = "Programación DAM 1º (2026-27).docx"
    docx(carpeta, nombre)
    codigo, resumen = ejecutar(capsys, ["leer", nombre])
    assert codigo == 0
    assert resumen["lectura"] == f".tiza/lecturas/{nombre}.txt"
    assert (carpeta / ".tiza" / "lecturas" / f"{nombre}.txt").is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows no admite «<» en un nombre")
def test_leer_nombre_con_simbolos_no_validos(carpeta, capsys):
    docx(carpeta, "a<b>.docx")
    codigo, salida = ejecutar(capsys, ["leer", "a<b>.docx"])
    assert codigo == 2 and salida["error"] == "NOMBRE_NO_VALIDO"
    assert ayuda.explicar("NOMBRE_NO_VALIDO")
    assert not (carpeta / ".tiza").exists()  # nada escrito


def test_agente_leer_es_publica(carpeta):
    docx(carpeta)
    assert "leer" in agente.__all__
    assert agente.leer("prog.docx", carpeta).bloques > 0


def test_leer_no_sigue_un_enlace_en_lecturas(carpeta, capsys):
    docx(carpeta)
    objetivo = carpeta.parent / "fuera"
    objetivo.mkdir()
    (carpeta / ".tiza").mkdir()
    try:
        (carpeta / ".tiza" / "lecturas").symlink_to(objetivo, target_is_directory=True)
    except OSError:
        pytest.skip("sin enlaces simbólicos")
    codigo, salida = ejecutar(capsys, ["leer", "prog.docx"])
    assert codigo == 2 and not list(objetivo.iterdir())


def test_lecturas_por_ruta_relativa_no_se_pisan(carpeta, capsys):
    for curso in ("1DAM", "2DAM"):
        (carpeta / curso).mkdir()
        d = f.nuevo()
        d.add_paragraph(f"Contenido de {curso}")
        d.save(str(carpeta / curso / "Programacion.docx"))
    resumenes = []
    for curso in ("1DAM", "2DAM"):
        codigo, resumen = ejecutar(capsys, ["leer", f"{curso}/Programacion.docx"])
        assert codigo == 0
        assert resumen["fichero"] == f"{curso}/Programacion.docx"
        assert resumen["lectura"] == f".tiza/lecturas/{curso}__Programacion.docx.txt"
        resumenes.append(resumen)
    textos = [(carpeta / r["lectura"]).read_text(encoding="utf-8") for r in resumenes]
    assert "Contenido de 1DAM" in textos[0] and "Contenido de 2DAM" not in textos[0]
    assert "Contenido de 2DAM" in textos[1]


def test_error_de_leer_trae_que_hacer(carpeta, capsys):
    codigo, salida = ejecutar(capsys, ["leer", "ausente.docx"])
    assert codigo == 2 and salida["error"] == "DOCUMENTO_AUSENTE"
    assert set(salida) == {"error", "detalle", "que_hacer"}
    assert salida["que_hacer"] == ayuda.explicar("DOCUMENTO_AUSENTE")


def test_error_de_documento_trae_que_hacer(carpeta, capsys):
    (carpeta / "u.md").write_text("Hola\n\n<div>x</div>\n", encoding="utf-8")
    codigo, salida = ejecutar(capsys, ["documento", "u.md"])
    assert codigo == 2 and salida["error"] == "MARKDOWN_NO_ADMITIDO"
    assert salida["que_hacer"] == ayuda.explicar("MARKDOWN_NO_ADMITIDO")
