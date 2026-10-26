"""Tests de las carpetas recientes del panel (``tiza.panel.recientes``): offline y puros."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tiza import config, ficheros
from tiza.panel import recientes


@pytest.fixture(autouse=True)
def global_aislado(tmp_path, monkeypatch):
    """La configuración global de los tests es una carpeta temporal, nunca la del usuario."""
    carpeta = tmp_path / "global"
    monkeypatch.setattr(config, "directorio_global", lambda: carpeta)
    return carpeta


def _carpetas(tmp_path: Path, n: int) -> list[Path]:
    lista = []
    for i in range(n):
        carpeta = tmp_path / "asignaturas" / f"curso{i}"
        carpeta.mkdir(parents=True)
        lista.append(carpeta)
    return lista


def test_sin_fichero_no_hay_recientes():
    assert recientes.leer() == []


def test_anotar_pone_la_primera_y_sin_repetir(tmp_path):
    a, b, c = _carpetas(tmp_path, 3)
    recientes.anotar(a)
    recientes.anotar(b)
    recientes.anotar(c)
    assert recientes.leer() == [c, b, a]
    assert recientes.anotar(a) == [a, c, b]
    assert recientes.leer() == [a, c, b]


def test_guarda_como_mucho_ocho(tmp_path):
    todas = _carpetas(tmp_path, recientes.MAXIMO + 3)
    for carpeta in todas:
        recientes.anotar(carpeta)
    guardadas = recientes.leer()
    assert len(guardadas) == recientes.MAXIMO == 8
    assert guardadas == list(reversed(todas))[:8]


def test_solo_rutas_absolutas_de_carpetas_que_existen(tmp_path):
    (a,) = _carpetas(tmp_path, 1)
    fichero = tmp_path / "suelto.txt"
    fichero.write_text("x", encoding="utf-8")
    recientes.anotar(a)
    assert recientes.anotar(tmp_path / "no_existe") == [a]
    assert recientes.anotar(fichero) == [a]
    assert recientes.anotar("relativa/carpeta") == [a]
    assert recientes.anotar("") == [a]
    assert recientes.anotar("a\x00b") == [a]
    assert recientes.leer() == [a]


def test_lo_que_ya_no_existe_desaparece_al_leer(tmp_path):
    a, b = _carpetas(tmp_path, 2)
    recientes.anotar(a)
    recientes.anotar(b)
    b.rmdir()
    assert recientes.leer() == [a]


def _escribir(global_aislado, contenido: bytes | str) -> None:
    global_aislado.mkdir(parents=True, exist_ok=True)
    ruta = global_aislado / recientes.NOMBRE
    if isinstance(contenido, str):
        ruta.write_text(contenido, encoding="utf-8")
    else:
        ruta.write_bytes(contenido)


def test_el_fichero_vive_junto_a_la_configuracion_global(global_aislado, tmp_path):
    (a,) = _carpetas(tmp_path, 1)
    recientes.anotar(a)
    assert recientes.ruta() == global_aislado / "panel-recientes.json"
    datos = json.loads(recientes.ruta().read_text(encoding="utf-8"))
    assert datos == {"version": 1, "carpetas": [str(a)]}
    assert [p.name for p in global_aislado.iterdir()] == ["panel-recientes.json"]  # sin temporales


@pytest.mark.parametrize(
    "contenido",
    [
        b"\xff\xfe\x00 no es utf-8",
        "no es json",
        "",
        "[]",
        "null",
        '{"version": 1}',
        '{"version": 2, "carpetas": []}',
        '{"version": 1, "carpetas": "x"}',
        '{"version": 1, "carpetas": [], "otra": 1}',
        "[" * 5000,
        "x" * (recientes.MAX_FICHERO + 1),
    ],
    # Ids cortos: Windows no admite PYTEST_CURRENT_TEST de más de 32767 caracteres.
    ids=lambda contenido: f"{type(contenido).__name__}-{len(contenido)}",
)
def test_un_fichero_roto_o_raro_es_vacio(global_aislado, contenido):
    _escribir(global_aislado, contenido)
    assert recientes.leer() == []


def test_se_descartan_las_entradas_malas_y_se_sigue(global_aislado, tmp_path):
    (a,) = _carpetas(tmp_path, 1)
    entradas = [1, None, ["x"], "relativa", "x" * 2000, str(tmp_path / "no_existe"), str(a), str(a)]
    _escribir(global_aislado, json.dumps({"version": 1, "carpetas": entradas}))
    assert recientes.leer() == [a]


def test_anotar_sobre_un_fichero_roto_lo_arregla(global_aislado, tmp_path):
    (a,) = _carpetas(tmp_path, 1)
    _escribir(global_aislado, "basura")
    assert recientes.anotar(a) == [a]
    assert recientes.leer() == [a]


def test_si_no_se_puede_escribir_no_falla(tmp_path, monkeypatch):
    (a,) = _carpetas(tmp_path, 1)

    def falla(*_args, **_kwargs):
        raise PermissionError("solo lectura")

    monkeypatch.setattr(ficheros, "escribir_json", falla)
    assert recientes.anotar(a) == [a]  # lo devuelve aunque no lo guarde


def test_nombre_visible_lleva_la_carpeta_y_su_madre(tmp_path):
    carpeta = tmp_path / "Institutos" / "Matemáticas 2ºB"
    assert recientes.nombre_visible(carpeta) == "Institutos / Matemáticas 2ºB"


def test_nombre_visible_sanea_y_acota(tmp_path):
    carpeta = tmp_path / ("a\x1b[31m" + "x" * 300)
    texto = recientes.nombre_visible(carpeta)
    assert "\x1b" not in texto
    assert len(texto) <= 80


def test_nombre_visible_de_una_raiz():
    raiz = Path(Path.cwd().anchor)
    assert recientes.nombre_visible(raiz) == str(raiz)


def test_quitar_una_reciente(tmp_path):
    a, b, c = _carpetas(tmp_path, 3)
    for carpeta in (a, b, c):
        recientes.anotar(carpeta)
    assert recientes.quitar(b) == [c, a]
    assert recientes.leer() == [c, a]
    assert recientes.quitar(b) == [c, a]  # ya no estaba: no cambia nada


def test_quitar_algo_que_no_es_una_ruta_util_no_toca_el_fichero(tmp_path):
    (a,) = _carpetas(tmp_path, 1)
    recientes.anotar(a)
    assert recientes.quitar("a\x00b") == [a]
    assert recientes.quitar(tmp_path / "no_existe") == [a]


def test_etiquetas_sin_pista_si_los_nombres_no_se_repiten(tmp_path):
    a, b = _carpetas(tmp_path, 2)
    assert recientes.etiquetas([a, b]) == [
        ("asignaturas / curso0", ""),
        ("asignaturas / curso1", ""),
    ]


def test_etiquetas_con_pista_solo_si_el_nombre_visible_se_repite(tmp_path):
    uno = tmp_path / "A" / "2026" / "mates"
    otro = tmp_path / "B" / "2026" / "mates"
    tercero = tmp_path / "C" / "lengua"
    for carpeta in (uno, otro, tercero):
        carpeta.mkdir(parents=True)
    etiquetas = dict(enumerate(recientes.etiquetas([uno, otro, tercero])))
    assert etiquetas[0] == ("2026 / mates", f"en A{os.sep}2026")
    assert etiquetas[1] == ("2026 / mates", f"en B{os.sep}2026")
    assert etiquetas[2] == ("C / lengua", "")


def test_la_pista_sanea_y_acota(tmp_path):
    carpeta = tmp_path / ("a\x1b[31m" * 40) / ("b\x1b[31m" * 40) / "mates"
    texto = recientes.etiquetas([carpeta])[0][1]
    assert texto == ""  # sin repetir el nombre, no hay pista
    otra = tmp_path / ("a\x1b[31m" * 40) / ("b\x1b[31m" * 40) / "mates"
    texto = recientes.etiquetas([carpeta, otra])[0][1]
    assert "\x1b" not in texto
    assert len(texto) <= 60
