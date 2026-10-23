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


@pytest.mark.parametrize("valor", [".nan", ".inf", "-.inf", "1.0e+308", "9" * 400])
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


CON_CRITERIOS = """\
organizacion: elementos
elementos:
  - id: RA1
    nombre: Redes
    peso: 60
    criterios:
      - {id: CE1_1, nombre: Configura, peso: 70, codigo: a}
      - {id: CE1_2, nombre: Documenta, peso: 30}
  - id: RA2
    nombre: Sistemas
    peso: 40
    criterios:
      - {id: CE2_1, nombre: Instala}
      - {id: CE2_2, nombre: Mantiene}
final: {de: elementos}
"""

CON_INSTRUMENTOS = """\
organizacion: elementos
elementos:
  - {id: RA1, nombre: Redes, peso: 50}
  - {id: RA2, nombre: Sistemas, peso: 50}
instrumentos:
  - {id: Examen1, nombre: Examen, seccion: 2, evalua: {RA1: 80, RA2: 20.5}}
  - {id: Oral, nombre: Exposición oral, seccion: " Tema 3 ", evalua: {RA2: 100}}
final: {de: elementos}
"""


def test_criterios_con_pesos(tmp_path: Path) -> None:
    esquema = _cargar(tmp_path, CON_CRITERIOS)
    ra1, ra2 = esquema.elementos
    assert [(c.id, c.nombre, c.peso, c.codigo) for c in ra1.criterios] == [
        ("CE1_1", "Configura", 70.0, "a"),
        ("CE1_2", "Documenta", 30.0, None),
    ]
    # sin pesos: peso None
    assert [(c.id, c.peso) for c in ra2.criterios] == [("CE2_1", None), ("CE2_2", None)]


def test_elemento_sin_criterios_los_deja_vacios(tmp_path: Path) -> None:
    assert all(e.criterios == () for e in _cargar(tmp_path, FP).elementos)
    assert _cargar(tmp_path, FP).instrumentos == ()


def test_criterios_con_y_sin_peso_mezclados(tmp_path: Path) -> None:
    error = _codigo(tmp_path, CON_CRITERIOS.replace(", peso: 30}", "}"))
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "elementos[0].criterios" in error.detalle
    assert "o todos los criterios llevan peso o ninguno" in error.detalle
    assert "línea 6" in error.detalle


def test_pesos_de_criterios_no_suman(tmp_path: Path) -> None:
    error = _codigo(tmp_path, CON_CRITERIOS.replace("peso: 30}", "peso: 20}"))
    assert error.codigo == "PESOS_NO_SUMAN_100"
    assert "elementos[0].criterios" in error.detalle


def test_criterio_con_el_id_de_un_elemento(tmp_path: Path) -> None:
    error = _codigo(tmp_path, CON_CRITERIOS.replace("id: CE1_2", "id: RA1"))
    assert error.codigo == "ID_REPETIDO"
    assert "elementos[0].criterios[1].id" in error.detalle


def test_criterio_con_el_id_de_otro_criterio(tmp_path: Path) -> None:
    error = _codigo(tmp_path, CON_CRITERIOS.replace("id: CE2_1", "id: CE1_1"))
    assert error.codigo == "ID_REPETIDO"
    assert "elementos[1].criterios[0].id" in error.detalle


def test_elemento_con_el_id_de_un_criterio_anterior(tmp_path: Path) -> None:
    error = _codigo(tmp_path, CON_CRITERIOS.replace("id: RA2", "id: CE1_1"))
    assert error.codigo == "ID_REPETIDO"
    assert "elementos[1].id" in error.detalle


def test_clave_desconocida_en_un_criterio(tmp_path: Path) -> None:
    error = _codigo(tmp_path, CON_CRITERIOS.replace("codigo: a", "color: a"))
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "elementos[0].criterios[0].color" in error.detalle


def test_criterios_vacios(tmp_path: Path) -> None:
    error = _codigo(tmp_path, FP.replace("peso: 40, codigo: RA1}", "peso: 40, criterios: []}"))
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "elementos[0].criterios" in error.detalle


def test_instrumentos_validos(tmp_path: Path) -> None:
    esquema = _cargar(tmp_path, CON_INSTRUMENTOS)
    assert [(i.id, i.nombre, i.seccion, i.evalua) for i in esquema.instrumentos] == [
        ("Examen1", "Examen", 2, (("RA1", 80), ("RA2", 20.5))),
        ("Oral", "Exposición oral", "Tema 3", (("RA2", 100),)),
    ]


@pytest.mark.parametrize("quitar", ["id: Examen1, ", "nombre: Examen, ", "seccion: 2, "])
def test_instrumento_con_clave_que_falta(tmp_path: Path, quitar: str) -> None:
    error = _codigo(tmp_path, CON_INSTRUMENTOS.replace(quitar, "", 1))
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "instrumentos[0]" in error.detalle and "falta la clave" in error.detalle


def test_instrumento_con_clave_que_falta_evalua(tmp_path: Path) -> None:
    error = _codigo(tmp_path, CON_INSTRUMENTOS.replace(", evalua: {RA2: 100}", ""))
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "instrumentos[1]" in error.detalle and "evalua" in error.detalle


def test_instrumento_con_clave_que_sobra(tmp_path: Path) -> None:
    error = _codigo(tmp_path, CON_INSTRUMENTOS.replace("seccion: 2,", "seccion: 2, peso: 5,"))
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "instrumentos[0].peso" in error.detalle


@pytest.mark.parametrize(
    "evalua, ruta",
    [
        ("{}", "instrumentos[0].evalua"),
        ("[RA1]", "instrumentos[0].evalua"),
        ("{RA1: 120}", "instrumentos[0].evalua.RA1"),
        ("{RA1: -1}", "instrumentos[0].evalua.RA1"),
        ("{RA1: 10.123}", "instrumentos[0].evalua.RA1"),
        ("{RA1: true}", "instrumentos[0].evalua.RA1"),
        ('{RA1: "40"}', "instrumentos[0].evalua.RA1"),
        ('{"1RA": 10}', "instrumentos[0].evalua.1RA"),
        ("{_RA1: 10}", "instrumentos[0].evalua._RA1"),
    ],
)
def test_evalua_de_instrumento_invalido(tmp_path: Path, evalua: str, ruta: str) -> None:
    error = _codigo(
        tmp_path, CON_INSTRUMENTOS.replace("evalua: {RA1: 80, RA2: 20.5}", f"evalua: {evalua}")
    )
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert ruta in error.detalle
    assert "línea 6" in error.detalle


def test_evalua_de_instrumento_con_id_repetido(tmp_path: Path) -> None:
    # PyYAML se quedaría con el último; el cargador ya rechaza las claves repetidas
    error = _codigo(
        tmp_path, CON_INSTRUMENTOS.replace("{RA1: 80, RA2: 20.5}", "{RA1: 80, RA1: 20}")
    )
    assert error.codigo == "ESQUEMA_INVALIDO"


def test_id_de_instrumento_repetido(tmp_path: Path) -> None:
    error = _codigo(tmp_path, CON_INSTRUMENTOS.replace("id: Oral", "id: Examen1"))
    assert error.codigo == "ID_REPETIDO"
    assert "instrumentos[1].id" in error.detalle


def test_instrumento_puede_usar_el_id_de_un_elemento(tmp_path: Path) -> None:
    esquema = _cargar(tmp_path, CON_INSTRUMENTOS.replace("id: Oral", "id: RA1"))
    assert [i.id for i in esquema.instrumentos] == ["Examen1", "RA1"]


@pytest.mark.parametrize("seccion", ["-1", "true", "[1]", '""'])
def test_seccion_de_instrumento_invalida(tmp_path: Path, seccion: str) -> None:
    error = _codigo(tmp_path, CON_INSTRUMENTOS.replace("seccion: 2", f"seccion: {seccion}"))
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "instrumentos[0].seccion" in error.detalle


def test_instrumentos_vacios(tmp_path: Path) -> None:
    texto = FP + "instrumentos: []\n"
    assert _codigo(tmp_path, texto).codigo == "ESQUEMA_INVALIDO"


def test_ids_con_guion_bajo(tmp_path: Path) -> None:
    esquema = _cargar(tmp_path, FP.replace("id: RA2", "id: RA_2"))
    assert esquema.elementos[1].id == "RA_2"
    error = _codigo(tmp_path, FP.replace("id: RA2", "id: _RA2"))
    assert error.codigo == "ESQUEMA_INVALIDO"
    assert "elementos[1].id" in error.detalle
    assert "_" in error.detalle
