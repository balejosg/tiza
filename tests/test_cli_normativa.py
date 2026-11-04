"""``tiza normativa`` es un paso directo a ``normativa_madrid.cli.main``: mismo stdout y mismo código."""

import importlib.util
import shlex
import shutil
import subprocess
import zipfile
from pathlib import Path

import normativa_madrid.cli as paquete
import pytest

from tiza import cli

RAIZ = Path(__file__).resolve().parent.parent

CONSULTAS = [
    "catalogo",
    "ficha MAD.ESO.TECDIG.2",
    "ficha MAD.EP.MAT --curso 3",
    "elemento MAD.EP.MAT.C2.CR.1.1",
    "elemento NOEXISTE",
    "buscar fracciones",
    "programacion fp",
    "ficha MAD.EP.MAT.C2 --formato md",
]


def _ejecutar(funcion, args, capfd):
    capfd.readouterr()
    codigo = funcion(args)
    return capfd.readouterr().out, codigo


@pytest.mark.parametrize("consulta", CONSULTAS)
def test_normativa_igual_que_el_paquete(consulta, capfd):
    args = shlex.split(consulta)
    esperado = _ejecutar(paquete.main, args, capfd)
    obtenido = _ejecutar(lambda a: cli.main(["normativa", *a]), args, capfd)
    assert esperado[0]
    assert obtenido == esperado


def test_normativa_comprobar_documento(tmp_path, capfd):
    doc = tmp_path / "unidad.md"
    doc.write_text("Trabaja MAD.EP.MAT.C2.CR.1.1 y también MAD.NOEXISTE.9.\n", encoding="utf-8")
    args = ["comprobar", str(doc)]
    esperado = _ejecutar(paquete.main, args, capfd)
    obtenido = _ejecutar(lambda a: cli.main(["normativa", *a]), args, capfd)
    assert esperado[1] == 1
    assert obtenido == esperado


def test_normativa_ayuda_es_la_del_paquete(capfd):
    with pytest.raises(SystemExit) as salida:
        cli.main(["normativa", "--help"])
    assert salida.value.code == 0
    assert "catalogo" in capfd.readouterr().out


def test_tiza_no_trae_normativa(tmp_path):
    assert importlib.util.find_spec("tiza.normativa") is None
    assert not (RAIZ / "src" / "tiza" / "normativa").exists()
    assert not (RAIZ / "herramientas" / "normativa").exists()


def test_el_wheel_no_contiene_normativa(tmp_path):
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv no está disponible")
    subprocess.run(
        [uv, "build", "--wheel", "-o", str(tmp_path)], cwd=RAIZ, check=True, capture_output=True
    )
    rueda = next(tmp_path.glob("tiza-*.whl"))
    nombres = zipfile.ZipFile(rueda).namelist()
    assert not [n for n in nombres if n.startswith("tiza/normativa/")]
