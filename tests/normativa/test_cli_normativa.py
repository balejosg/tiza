"""CLI `tiza normativa`: un documento JSON por consulta, sin aula ni carpeta de trabajo."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from tiza import ayuda, cli
from tiza.normativa import ErrorNormativa, cargar, consulta, salida

SINTETICOS = Path(__file__).parent / "datos_sinteticos"
HOY = date(2026, 10, 17)
MATERIA = "MAD.ESO.CCOMP.1"
ELEMENTO = f"{MATERIA}.CE.2"  # «Diseña una solución sencilla a un problema dado.»


@pytest.fixture
def datos(monkeypatch):
    """Los datos sintéticos y el día fijo, en el punto por el que consulta los toma."""
    monkeypatch.setattr(consulta, "cargar", lambda: cargar(SINTETICOS))
    monkeypatch.setattr(consulta, "hoy_en_madrid", lambda: HOY)


def ejecutar(capsys, argv: list[str]) -> tuple[int, dict]:
    codigo = cli.main(argv)
    documento = json.loads(capsys.readouterr().out)  # exactamente un documento
    return codigo, documento


def test_cli_ficha_json_valido(datos, capsys):
    codigo, documento = ejecutar(capsys, ["normativa", "ficha", MATERIA])
    assert codigo == 0
    salida.validar(documento)
    assert documento["consulta"] == "ficha"
    assert documento["codigo"] == MATERIA


def test_cli_error_es_json(datos, capsys):
    codigo, documento = ejecutar(capsys, ["normativa", "elemento", "MAD.NO.EXISTE"])
    assert codigo == 2
    assert documento["error"] == "CODIGO_DESCONOCIDO"
    salida.validar(documento)


def test_cli_utf8_en_consola_cp1252(tmp_path, monkeypatch):
    # Los datos sintéticos no traen «º»: se copian y se añade uno al texto del elemento.
    copia = tmp_path / "datos"
    shutil.copytree(SINTETICOS, copia)
    ficha_json = copia / "fichas" / "materia_ccomp_1.json"
    original = "Diseña una solución sencilla a un problema dado."
    texto_json = ficha_json.read_text(encoding="utf-8")
    assert original in texto_json
    ficha_json.write_text(
        texto_json.replace(original, "Diseña una solución al problema 1º."), encoding="utf-8"
    )
    monkeypatch.setattr(consulta, "cargar", lambda: cargar(copia))
    monkeypatch.setattr(consulta, "hoy_en_madrid", lambda: HOY)

    flujo = io.BytesIO()
    consola = io.TextIOWrapper(flujo, encoding="cp1252", write_through=True)
    monkeypatch.setattr(sys, "stdout", consola)
    assert cli.main(["normativa", "elemento", ELEMENTO]) == 0
    texto = flujo.getvalue().decode("utf-8")
    assert json.loads(texto)["elemento"]["texto"] == "Diseña una solución al problema 1º."
    assert "º" in texto


def test_cli_curso_academico_en_todos(datos, capsys):
    pedidos = [
        (["catalogo"], "catalogo"),
        (["ficha", MATERIA], "ficha"),
        (["elemento", ELEMENTO], "elemento"),
        (["buscar", "solución", "--en", MATERIA], "buscar"),
        (["programacion", "eso"], "programacion"),
    ]
    for argumentos, consulta_esperada in pedidos:
        codigo, documento = ejecutar(
            capsys, ["normativa", *argumentos, "--curso-academico", "2026-27"]
        )
        assert codigo == 0, consulta_esperada
        assert documento["consulta"] == consulta_esperada
        assert documento["curso_academico"] == "2026-27"
        assert documento["curso_en_vigor"] is True
        salida.validar(documento)


def test_cli_norma_no_admite_curso_academico(datos):
    with pytest.raises(SystemExit) as info:
        cli.main(["normativa", "norma", "Decreto 27/2025", "--curso-academico", "2026-27"])
    assert info.value.code == 2


def test_cli_no_toca_tiza(datos, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    codigo, _ = ejecutar(capsys, ["normativa", "catalogo"])
    assert codigo == 0
    assert not (tmp_path / ".tiza").exists()
    assert not (tmp_path / "tiza.toml").exists()


def test_cli_sin_datos_da_error_json(tmp_path, monkeypatch, capsys):
    vacio = tmp_path / "datos"
    (vacio / "normas").mkdir(parents=True)
    (vacio / "fichas").mkdir()
    monkeypatch.setattr(consulta, "cargar", lambda: cargar(vacio))
    codigo, documento = ejecutar(capsys, ["normativa", "ficha", MATERIA])
    assert codigo == 2
    assert documento["error"] == "NORMATIVA_SIN_DATOS"
    assert documento["disponibles"] == []
    salida.validar(documento)
    # Con los datos reales vacíos, catalogo también falla: así lo fija la consulta (tarea 3).
    codigo, documento = ejecutar(capsys, ["normativa", "catalogo"])
    assert codigo == 2
    assert documento["error"] == "NORMATIVA_SIN_DATOS"


def test_cli_detalle_sin_caracteres_de_control(monkeypatch, capsys):
    def con_basura(*_args, **_kwargs):
        raise ErrorNormativa("CODIGO_DESCONOCIDO", "malo\x07 con\u200b ruido\n", ("x\x00y",))

    monkeypatch.setattr(consulta, "elemento", con_basura)
    codigo, documento = ejecutar(capsys, ["normativa", "elemento", "X"])
    assert codigo == 2
    assert documento == {
        "error": "CODIGO_DESCONOCIDO",
        "detalle": "malo con ruido",
        "disponibles": ["xy"],
    }


def test_cli_salida_invalida_no_da_traceback(datos, monkeypatch, capsys):
    def no_valida(_documento):
        raise salida.ErrorSalida("TIPO_INCORRECTO", "prueba")

    monkeypatch.setattr(salida, "validar", no_valida)
    codigo, documento = ejecutar(capsys, ["normativa", "catalogo"])
    assert codigo == 2
    assert documento == {"error": "SALIDA_INVALIDA", "detalle": "", "disponibles": []}


def test_normativa_no_carga_python_moodle():
    codigo = (
        "import sys\n"
        "import tiza.normativa.consulta\n"
        "assert 'py_moodle' not in sys.modules, 'python-moodle cargado'\n"
        "assert 'tiza.publicar' not in sys.modules, 'publicar cargado'\n"
    )
    subprocess.run([sys.executable, "-c", codigo], check=True)


def test_todo_codigo_de_error_tiene_ayuda():
    assert set(ayuda.MENSAJES) >= salida.CODIGOS_ERROR


def test_normativa_ayuda_en_espanol(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["normativa", "--help"])
    assert info.value.code == 0
    texto = capsys.readouterr().out
    for consulta_nombre in ("catalogo", "ficha", "elemento", "norma", "buscar", "programacion"):
        assert consulta_nombre in texto


def test_cli_norma_con_cita_valida(datos, capsys):
    codigo, documento = ejecutar(capsys, ["normativa", "norma", "Decreto 27/2025"])
    assert codigo == 0
    assert documento["consulta"] == "norma"
    salida.validar(documento)
