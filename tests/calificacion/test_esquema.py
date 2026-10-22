"""Esquema de calificación (calificacion.yaml): forma y validación. Offline."""

from __future__ import annotations

from pathlib import Path

import pytest

from tiza.calificacion.esquema import ErrorCalificacion, cargar_esquema

FP = """\
# esquema de FP
organizacion: elementos
elementos:
  - {id: RA1, nombre: Redes, peso: 40, codigo: RA1}
  - {id: RA2, nombre: Sistemas, peso: 30}
  - {id: RA3, nombre: Seguridad, peso: 30}
evaluaciones:
  - {nombre: Primera, secciones: [1, 2]}
  - {nombre: Segunda, secciones: [3, "Tema 4"], cerrada: true}
  - {nombre: Tercera, secciones: [5]}
final:
  de: elementos
  tope: {si_alguno_menor_que: 5, maximo: 4}
"""

ESO = """\
organizacion: evaluaciones
evaluaciones:
  - {nombre: Primera, secciones: [1], peso: 30}
  - {nombre: Segunda, secciones: [2], peso: 30}
  - {nombre: Tercera, secciones: [3], peso: 40}
final: {de: evaluaciones}
"""


def _cargar(carpeta: Path, texto: str, nombre: str = "calificacion.yaml"):
    ruta = carpeta / nombre
    ruta.write_text(texto, encoding="utf-8")
    return cargar_esquema(ruta, carpeta)


def _codigo(carpeta: Path, texto: str) -> ErrorCalificacion:
    with pytest.raises(ErrorCalificacion) as info:
        _cargar(carpeta, texto)
    return info.value


def test_esquema_fp_valido(tmp_path: Path) -> None:
    esquema = _cargar(tmp_path, FP)
    assert esquema.organizacion == "elementos"
    assert [(e.id, e.nombre, e.peso, e.codigo) for e in esquema.elementos] == [
        ("RA1", "Redes", 40.0, "RA1"),
        ("RA2", "Sistemas", 30.0, None),
        ("RA3", "Seguridad", 30.0, None),
    ]
    assert [(e.nombre, e.secciones, e.cerrada) for e in esquema.evaluaciones] == [
        ("Primera", (1, 2), False),
        ("Segunda", (3, "Tema 4"), True),
        ("Tercera", (5,), False),
    ]
    assert esquema.final.de == "elementos"
    assert esquema.final.tope is not None
    assert esquema.final.tope.si_alguno_menor_que == 5
    assert esquema.final.tope.maximo == 4


def test_esquema_eso_valido(tmp_path: Path) -> None:
    esquema = _cargar(tmp_path, ESO, "otro.yaml")
    assert esquema.organizacion == "evaluaciones"
    assert esquema.elementos == ()
    assert [e.peso for e in esquema.evaluaciones] == [30.0, 30.0, 40.0]
    assert esquema.final.de == "evaluaciones"
    assert esquema.final.tope is None


def test_pesos_no_suman(tmp_path: Path) -> None:
    texto = FP.replace(
        "peso: 30}\n  - {id: RA3, nombre: Seguridad, peso: 30",
        "peso: 30}\n  - {id: RA3, nombre: Seguridad, peso: 20",
    )
    error = _codigo(tmp_path, texto)
    assert error.codigo == "PESOS_NO_SUMAN_100"
    assert "elementos" in error.detalle
    assert "línea 3" in error.detalle


def test_pesos_de_evaluaciones_no_suman(tmp_path: Path) -> None:
    error = _codigo(tmp_path, ESO.replace("peso: 40", "peso: 50"))
    assert error.codigo == "PESOS_NO_SUMAN_100"
    assert "evaluaciones" in error.detalle


def test_peso_obligatorio_en_final_de_evaluaciones(tmp_path: Path) -> None:
    error = _codigo(tmp_path, ESO.replace(", peso: 40", ""))
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "evaluaciones[2]" in error.detalle and "peso" in error.detalle


def test_clave_desconocida(tmp_path: Path) -> None:
    error = _codigo(
        tmp_path, ESO.replace("final: {de: evaluaciones}", "final: {de: evaluaciones, formula: x}")
    )
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "final.formula" in error.detalle


def test_id_repetido(tmp_path: Path) -> None:
    error = _codigo(tmp_path, FP.replace("id: RA2", "id: RA1"))
    assert error.codigo == "ID_REPETIDO"
    assert "RA1" in error.detalle


def test_id_con_forma_invalida(tmp_path: Path) -> None:
    error = _codigo(tmp_path, FP.replace("id: RA2", "id: 2RA"))
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "elementos[1].id" in error.detalle


def test_seccion_repetida(tmp_path: Path) -> None:
    error = _codigo(tmp_path, FP.replace("secciones: [5]", "secciones: [2]"))
    assert error.codigo == "SECCION_REPETIDA"


def test_tope_con_evaluaciones(tmp_path: Path) -> None:
    texto = ESO.replace(
        "final: {de: evaluaciones}",
        "final: {de: evaluaciones, tope: {si_alguno_menor_que: 5, maximo: 4}}",
    )
    assert _codigo(tmp_path, texto).codigo == "TOPE_SIN_ELEMENTOS"


@pytest.mark.parametrize(
    "tope",
    [
        "{si_alguno_menor_que: 0, maximo: 4}",
        "{si_alguno_menor_que: 11, maximo: 4}",
        "{si_alguno_menor_que: 5, maximo: 10}",
        "{si_alguno_menor_que: 5, maximo: -1}",
        "{si_alguno_menor_que: 5}",
    ],
)
def test_tope_fuera_de_rango(tmp_path: Path, tope: str) -> None:
    texto = FP.replace("{si_alguno_menor_que: 5, maximo: 4}", tope)
    assert _codigo(tmp_path, texto).codigo == "ESQUEMA_INVALIDO"


def test_peso_con_tres_decimales(tmp_path: Path) -> None:
    assert _codigo(tmp_path, FP.replace("peso: 40", "peso: 40.005")).codigo == "ESQUEMA_INVALIDO"


def test_alias_yaml_rechazado(tmp_path: Path) -> None:
    texto = (
        FP.replace("evaluaciones:\n  - {nombre: Primera", "evaluaciones: &e\n  - {nombre: Primera")
        + "otra: *e\n"
    )
    error = _codigo(tmp_path, texto)
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "alias" in error.detalle


def test_clave_repetida(tmp_path: Path) -> None:
    error = _codigo(tmp_path, FP + "organizacion: elementos\n")
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "organizacion" in error.detalle


def test_fuera_de_carpeta(tmp_path: Path) -> None:
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    (tmp_path / "x.yaml").write_text(ESO, encoding="utf-8")
    with pytest.raises(ErrorCalificacion) as info:
        cargar_esquema(carpeta / ".." / "x.yaml", carpeta)
    assert info.value.codigo == "ESQUEMA_FUERA_DE_CARPETA"


def test_extension_no_yaml(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text(ESO, encoding="utf-8")
    with pytest.raises(ErrorCalificacion) as info:
        cargar_esquema(tmp_path / "x.txt", tmp_path)
    assert info.value.codigo == "FORMATO_NO_ADMITIDO"


@pytest.mark.parametrize("valor", [".nan", ".inf", "-.inf"])
@pytest.mark.parametrize(
    ("antes", "ruta"),
    [
        ("peso: 40", "elementos[0].peso"),
        ("si_alguno_menor_que: 5", "final.tope.si_alguno_menor_que"),
        ("maximo: 4", "final.tope.maximo"),
    ],
)
def test_numero_no_finito(tmp_path: Path, valor: str, antes: str, ruta: str) -> None:
    clave = antes.split(":")[0]
    sustituido = f"{clave}: {valor}"
    error = _codigo(tmp_path, FP.replace(antes, sustituido, 1))
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert ruta in error.detalle
    assert "línea" in error.detalle
