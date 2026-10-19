"""CLI `tiza rellenar`: un JSON en stdout, el Word nuevo y la marca de actualizar campos."""

from __future__ import annotations

import hashlib
import json
import zipfile

import pytest
import yaml
from lectura import fabrica as f

from tiza import ayuda, cli


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    asignatura = tmp_path / "asignatura"
    asignatura.mkdir()
    monkeypatch.chdir(asignatura)
    return asignatura


def ejecutar(capsys, argv):
    codigo = cli.main(argv)
    return codigo, json.loads(capsys.readouterr().out)


def preparar(carpeta, con_indice=False, sha=None):
    d = f.nuevo()
    if con_indice:
        f.indice(d)
    d.add_paragraph("Texto viejo")
    plantilla = carpeta / "Plantilla.docx"
    d.save(str(plantilla))
    datos = {
        "plantilla": "Plantilla.docx",
        "sha256": sha or hashlib.sha256(plantilla.read_bytes()).hexdigest(),
        "salida": "Salida.docx",
        "operaciones": [{"op": "reemplazar", "id": "p1", "texto": "Texto nuevo"}],
    }
    (carpeta / "relleno.yaml").write_text(
        yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def test_cli_rellenar_resumen(carpeta, capsys):
    preparar(carpeta)
    codigo, resumen = ejecutar(capsys, ["rellenar", "relleno.yaml"])
    assert codigo == 0
    assert resumen == {
        "plantilla": "Plantilla.docx",
        "salida": "Salida.docx",
        "operaciones": 1,
        "avisos": [],
    }
    assert (carpeta / "Salida.docx").is_file()
    assert not (carpeta / ".tiza" / "informe.json").exists()


def test_cli_rellenar_marca_update_fields(carpeta, capsys):
    preparar(carpeta)
    assert ejecutar(capsys, ["rellenar", "relleno.yaml"])[0] == 0
    with zipfile.ZipFile(carpeta / "Salida.docx") as z:
        ajustes = z.read("word/settings.xml").decode("utf-8")
    assert "<w:updateFields" in ajustes and 'w:val="true"' in ajustes.split("<w:updateFields")[1]


def test_cli_rellenar_aviso_de_indice(carpeta, capsys):
    preparar(carpeta, con_indice=True)
    codigo, resumen = ejecutar(capsys, ["rellenar", "relleno.yaml"])
    assert codigo == 0 and resumen["avisos"] == ["INDICE_SE_ACTUALIZA_AL_ABRIR"]
    assert ayuda.explicar("INDICE_SE_ACTUALIZA_AL_ABRIR")


def test_cli_rellenar_error_es_codigo(carpeta, capsys):
    preparar(carpeta, sha="0" * 64)
    codigo, resultado = ejecutar(capsys, ["rellenar", "relleno.yaml"])
    assert codigo == 2
    assert resultado["error"] == "PLANTILLA_CAMBIADA"
    assert resultado["que_hacer"] == ayuda.explicar("PLANTILLA_CAMBIADA")
    assert not (carpeta / "Salida.docx").exists()
