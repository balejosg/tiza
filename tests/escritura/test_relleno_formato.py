"""Formato y validación de relleno.yaml (tiza rellenar, tarea 1). Offline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tiza.escritura import ErrorEscritura
from tiza.escritura.relleno import (
    Borrar,
    DuplicarTabla,
    Filas,
    InsertarDespues,
    Reemplazar,
    cargar_relleno,
)

HASH = "a" * 64
CABECERA: dict[str, Any] = {
    "plantilla": "Plantilla.docx",
    "sha256": HASH,
    "salida": "Programacion.docx",
}


def _escribir(carpeta: Path, operaciones: list[Any] | None = None, **extra: Any) -> Path:
    datos = {**CABECERA, **extra}
    if operaciones is not None:
        datos["operaciones"] = operaciones
    ruta = carpeta / "relleno.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ruta


def _cargar(carpeta: Path, operaciones: list[Any] | None = None, **extra: Any):
    return cargar_relleno(_escribir(carpeta, operaciones, **extra), carpeta)


def _invalido(carpeta: Path, operaciones: list[Any] | None = None, **extra: Any) -> str:
    with pytest.raises(ErrorEscritura) as exc:
        _cargar(carpeta, operaciones, **extra)
    assert exc.value.codigo == "RELLENO_INVALIDO", exc.value.detalle
    return exc.value.detalle


def test_relleno_minimo_valido(tmp_path):
    relleno = _cargar(
        tmp_path,
        [{"op": "reemplazar", "id": "p3", "texto": "Hola"}],
    )
    assert relleno.plantilla == (tmp_path / "Plantilla.docx").resolve()
    assert relleno.salida == (tmp_path / "Programacion.docx").resolve()
    assert relleno.sha256 == HASH
    assert relleno.operaciones == (Reemplazar("p3", ("Hola",)),)


def test_relleno_clave_desconocida(tmp_path):
    ops = [
        {"op": "reemplazar", "id": "p1", "texto": "a"},
        {"op": "borrar", "id": "p2"},
        {"op": "reemplazar", "id": "p4", "texto": "b", "colour": "red"},
    ]
    with pytest.raises(ErrorEscritura) as exc:
        _cargar(tmp_path, ops)
    assert exc.value.codigo == "RELLENO_INVALIDO"
    assert "operaciones[2].colour" in exc.value.detalle


def test_relleno_conflicto_borrar_y_reemplazar(tmp_path):
    ops = [
        {"op": "borrar", "id": "p1"},
        {"op": "reemplazar", "id": "t3.f2.c1", "texto": "x"},
        {"op": "reemplazar", "id": "p9", "texto": "y"},
        {"op": "insertar_despues", "id": "p5", "parrafos": ["z"]},
        {"op": "borrar", "id": "t3.f2"},
    ]
    with pytest.raises(ErrorEscritura) as exc:
        _cargar(tmp_path, ops)
    assert exc.value.codigo == "OPERACIONES_EN_CONFLICTO"
    assert "operaciones[1]" in exc.value.detalle
    assert "operaciones[4]" in exc.value.detalle


def test_relleno_veces_fuera_de_rango(tmp_path):
    ops = [
        {
            "op": "duplicar_tabla",
            "tabla": "t1",
            "despues_de": "p2",
            "veces": 41,
            "celdas": [{} for _ in range(41)],
        }
    ]
    assert "veces" in _invalido(tmp_path, ops)


def test_relleno_salida_fuera_de_la_carpeta(tmp_path):
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    with pytest.raises(ErrorEscritura) as exc:
        _cargar(carpeta, [{"op": "borrar", "id": "p1"}], salida="../fuera.docx")
    assert exc.value.codigo == "FICHERO_FUERA"


def test_plantilla_igual_a_salida_no_se_permite(tmp_path):
    with pytest.raises(ErrorEscritura) as exc:
        _cargar(
            tmp_path,
            [{"op": "borrar", "id": "p1"}],
            salida="Sub/../Plantilla.docx",
        )
    assert exc.value.codigo == "DOCUMENTO_EXISTE"


def test_plantilla_debe_ser_docx(tmp_path):
    with pytest.raises(ErrorEscritura) as exc:
        _cargar(tmp_path, [{"op": "borrar", "id": "p1"}], plantilla="Plantilla.pdf")
    assert exc.value.codigo == "FORMATO_NO_ADMITIDO"


def test_conflicto_por_prefijo_de_id(tmp_path):
    # «t3» contiene a «t3.f2.c1», pero no a «t31».
    sin_choque = [
        {"op": "borrar", "id": "t3"},
        {"op": "reemplazar", "id": "t31.f1.c1", "texto": "x"},
    ]
    assert _cargar(tmp_path, sin_choque).operaciones[1] == Reemplazar("t31.f1.c1", ("x",))
    con_choque = [
        {"op": "borrar", "id": "t3"},
        {"op": "reemplazar", "id": "t3.f2.c1", "texto": "x"},
    ]
    with pytest.raises(ErrorEscritura) as exc:
        _cargar(tmp_path, con_choque)
    assert exc.value.codigo == "OPERACIONES_EN_CONFLICTO"


def test_dos_reemplazar_del_mismo_id_chocan(tmp_path):
    ops = [
        {"op": "reemplazar", "id": "p2", "texto": "a"},
        {"op": "reemplazar", "id": "p2", "texto": "b"},
    ]
    with pytest.raises(ErrorEscritura) as exc:
        _cargar(tmp_path, ops)
    assert exc.value.codigo == "OPERACIONES_EN_CONFLICTO"
    assert "operaciones[0]" in exc.value.detalle and "operaciones[1]" in exc.value.detalle


def test_dos_borrar_del_mismo_id_chocan(tmp_path):
    ops = [{"op": "borrar", "id": "p2"}, {"op": "borrar", "id": "p2"}]
    with pytest.raises(ErrorEscritura) as exc:
        _cargar(tmp_path, ops)
    assert exc.value.codigo == "OPERACIONES_EN_CONFLICTO"


def test_borrar_y_duplicar_despues_de_chocan(tmp_path):
    ops = [
        {"op": "duplicar_tabla", "tabla": "t1", "despues_de": "p5", "veces": 1, "celdas": [{}]},
        {"op": "borrar", "id": "p5"},
    ]
    with pytest.raises(ErrorEscritura) as exc:
        _cargar(tmp_path, ops)
    assert exc.value.codigo == "OPERACIONES_EN_CONFLICTO"


def test_texto_con_salto_de_linea_se_rechaza(tmp_path):
    ops = [{"op": "reemplazar", "id": "p1", "texto": "uno\ndos"}]
    detalle = _invalido(tmp_path, ops)
    assert "operaciones[0].texto" in detalle
    assert "lista de párrafos" in detalle


def test_texto_con_control_se_rechaza(tmp_path):
    ops = [{"op": "reemplazar", "id": "p1", "texto": "a" + chr(7) + "b"}]
    assert "operaciones[0].texto" in _invalido(tmp_path, ops)


def test_salto_final_se_quita_y_la_lista_de_parrafos_pasa(tmp_path):
    ops = [
        {"op": "reemplazar", "id": "p1", "texto": "fin\n"},
        {"op": "reemplazar", "id": "p2", "texto": ["uno", "dos\n"]},
    ]
    relleno = _cargar(tmp_path, ops)
    assert relleno.operaciones == (
        Reemplazar("p1", ("fin",)),
        Reemplazar("p2", ("uno", "dos")),
    )


def test_insertar_despues_con_y_sin_estilo(tmp_path):
    ops = [
        {"op": "insertar_despues", "id": "p4", "parrafos": ["a", "b"]},
        {"op": "insertar_despues", "id": "t2", "parrafos": ["c"], "estilo": "Título 2"},
    ]
    relleno = _cargar(tmp_path, ops)
    assert relleno.operaciones == (
        InsertarDespues("p4", ("a", "b"), None),
        InsertarDespues("t2", ("c",), "Título 2"),
    )


def test_insertar_despues_sin_parrafos_no_vale(tmp_path):
    assert "parrafos" in _invalido(tmp_path, [{"op": "insertar_despues", "id": "p4"}])


def test_filas_antes_de_numero_o_final(tmp_path):
    ops = [
        {
            "op": "filas",
            "tabla": "t1",
            "modelo": 2,
            "antes_de": "final",
            "contenido": [[["Celda"], "otra"]],
        },
        {
            "op": "filas",
            "tabla": "t1",
            "modelo": 2,
            "antes_de": 4,
            "contenido": [[["Celda"], "otra"]],
        },
    ]
    relleno = _cargar(tmp_path, ops)
    assert relleno.operaciones[0] == Filas("t1", 2, None, ((("Celda",), ("otra",)),))
    assert relleno.operaciones[1].antes_de == 4


@pytest.mark.parametrize("antes", [0, "primera", True])
def test_filas_antes_de_no_valido(tmp_path, antes):
    ops = [{"op": "filas", "tabla": "t1", "modelo": 2, "antes_de": antes, "contenido": [["x"]]}]
    assert "antes_de" in _invalido(tmp_path, ops)


def test_duplicar_celdas_exige_una_entrada_por_copia(tmp_path):
    base = {"op": "duplicar_tabla", "tabla": "t1", "despues_de": "p2", "veces": 2}
    assert "celdas" in _invalido(tmp_path, [{**base, "celdas": [{}]}])
    relleno = _cargar(tmp_path, [{**base, "celdas": [{}, {"f1.c1": "Nuevo"}]}])
    assert relleno.operaciones[0] == DuplicarTabla("t1", "p2", 2, ({}, {"f1.c1": ("Nuevo",)}))


def test_duplicar_celdas_solo_con_id_relativo(tmp_path):
    ops = [
        {
            "op": "duplicar_tabla",
            "tabla": "t1",
            "despues_de": "p2",
            "veces": 1,
            "celdas": [{"c1": "x"}],
        }
    ]
    assert "celdas[0]" in _invalido(tmp_path, ops)


def test_borrar_admite_parrafo_tabla_y_fila(tmp_path):
    ops = [
        {"op": "borrar", "id": "p1"},
        {"op": "borrar", "id": "t2.f3"},
        {"op": "borrar", "id": "t4"},
    ]
    assert _cargar(tmp_path, ops).operaciones == (Borrar("p1"), Borrar("t2.f3"), Borrar("t4"))


@pytest.mark.parametrize(
    "operacion",
    [
        {"op": "reemplazar", "id": "p0", "texto": "x"},
        {"op": "reemplazar", "id": "t1.f1", "texto": "x"},
        {"op": "reemplazar", "id": "x3", "texto": "x"},
        {"op": "insertar_despues", "id": "t1.f1.c1", "parrafos": ["x"]},
        {"op": "borrar", "id": "t1.f1.c1"},
        {"op": "filas", "tabla": "p1", "modelo": 1, "antes_de": "final", "contenido": [["x"]]},
        {
            "op": "duplicar_tabla",
            "tabla": "t1",
            "despues_de": "t1.f1.c1",
            "veces": 1,
            "celdas": [{}],
        },
    ],
)
def test_ids_con_forma_no_valida(tmp_path, operacion):
    assert "operaciones[0]" in _invalido(tmp_path, [operacion])


def test_operacion_desconocida(tmp_path):
    assert "operaciones[0].op" in _invalido(tmp_path, [{"op": "colorear", "id": "p1"}])


def test_numeros_no_pueden_ser_booleanos(tmp_path):
    ops = [
        {"op": "filas", "tabla": "t1", "modelo": True, "antes_de": "final", "contenido": [["x"]]}
    ]
    assert "modelo" in _invalido(tmp_path, ops)


def test_clave_de_raiz_desconocida(tmp_path):
    assert "colour" in _invalido(tmp_path, [{"op": "borrar", "id": "p1"}], colour="rojo")


def test_sha256_en_minuscula_y_64_caracteres(tmp_path):
    assert "sha256" in _invalido(tmp_path, [{"op": "borrar", "id": "p1"}], sha256="A" * 64)
    assert "sha256" in _invalido(tmp_path, [{"op": "borrar", "id": "p1"}], sha256="a" * 63)


def test_mas_de_2000_operaciones(tmp_path):
    ops = [{"op": "reemplazar", "id": f"p{i}", "texto": "x"} for i in range(1, 2002)]
    assert "operaciones" in _invalido(tmp_path, ops)


def test_yaml_con_alias_se_rechaza(tmp_path):
    ruta = tmp_path / "relleno.yaml"
    ruta.write_text(
        "plantilla: Plantilla.docx\n"
        f"sha256: {HASH}\n"
        "salida: Programacion.docx\n"
        "operaciones:\n"
        "  - &op {op: borrar, id: p1}\n"
        "  - *op\n",
        encoding="utf-8",
    )
    with pytest.raises(ErrorEscritura) as exc:
        cargar_relleno(ruta, tmp_path)
    assert exc.value.codigo == "RELLENO_INVALIDO"
    assert "alias" in exc.value.detalle


def test_yaml_no_valido_da_la_linea(tmp_path):
    ruta = tmp_path / "relleno.yaml"
    ruta.write_text("plantilla: [\n", encoding="utf-8")
    with pytest.raises(ErrorEscritura) as exc:
        cargar_relleno(ruta, tmp_path)
    assert exc.value.codigo == "RELLENO_INVALIDO"
    assert "YAML" in exc.value.detalle


def test_yaml_vacio(tmp_path):
    ruta = tmp_path / "relleno.yaml"
    ruta.write_text("", encoding="utf-8")
    with pytest.raises(ErrorEscritura) as exc:
        cargar_relleno(ruta, tmp_path)
    assert exc.value.codigo == "RELLENO_INVALIDO"


def test_yaml_mayor_de_dos_megas_se_rechaza(tmp_path):
    ruta = tmp_path / "relleno.yaml"
    ruta.write_text("x" * (2 * 1024 * 1024 + 1), encoding="utf-8")
    with pytest.raises(ErrorEscritura) as exc:
        cargar_relleno(ruta, tmp_path)
    assert exc.value.codigo == "RELLENO_INVALIDO"
    assert "2 MB" in exc.value.detalle


def test_yaml_debe_estar_en_la_carpeta(tmp_path):
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    ruta = _escribir(tmp_path, [{"op": "borrar", "id": "p1"}])
    with pytest.raises(ErrorEscritura) as exc:
        cargar_relleno(ruta, carpeta)
    assert exc.value.codigo == "FICHERO_FUERA"


def _conflictivo(carpeta: Path, operaciones: list[Any]) -> str:
    with pytest.raises(ErrorEscritura) as exc:
        _cargar(carpeta, operaciones)
    assert exc.value.codigo == "OPERACIONES_EN_CONFLICTO", exc.value.detalle
    return exc.value.detalle


def test_borrar_fila_no_choca_con_filas_insertar_ni_duplicar_de_su_tabla(tmp_path):
    # Añadir filas, insertar o copiar la tabla es normal aunque se borre una fila suya.
    ops = [
        {"op": "borrar", "id": "t3.f2"},
        {"op": "filas", "tabla": "t3", "modelo": 1, "antes_de": "final", "contenido": [["x"]]},
        {"op": "insertar_despues", "id": "t3", "parrafos": ["nota"]},
        {"op": "duplicar_tabla", "tabla": "t3", "despues_de": "p9", "veces": 1, "celdas": [{}]},
    ]
    assert len(_cargar(tmp_path, ops).operaciones) == 4


def test_borrar_fila_choca_con_filas_que_la_usan_de_modelo(tmp_path):
    ops = [
        {"op": "borrar", "id": "t3.f2"},
        {"op": "filas", "tabla": "t3", "modelo": 2, "antes_de": "final", "contenido": [["x"]]},
    ]
    detalle = _conflictivo(tmp_path, ops)
    assert "operaciones[0]" in detalle and "operaciones[1]" in detalle


def test_borrar_tabla_choca_con_reemplazar_dentro_de_ella(tmp_path):
    ops = [
        {"op": "reemplazar", "id": "t3.f2.c1", "texto": "x"},
        {"op": "borrar", "id": "t3"},
    ]
    detalle = _conflictivo(tmp_path, ops)
    assert "operaciones[0]" in detalle and "operaciones[1]" in detalle


def test_reemplazar_padre_y_borrar_hijo_chocan_en_cualquier_orden(tmp_path):
    ops_hijo_despues = [
        {"op": "reemplazar", "id": "t3.f2.c1", "texto": "x"},
        {"op": "borrar", "id": "t3.f2.c1.p1"},
    ]
    assert "operaciones[1]" in _conflictivo(tmp_path, ops_hijo_despues)
    ops_hijo_antes = [
        {"op": "borrar", "id": "t3.f2.c1.p1"},
        {"op": "reemplazar", "id": "t3.f2.c1", "texto": "x"},
    ]
    assert "operaciones[1]" in _conflictivo(tmp_path, ops_hijo_antes)


def test_borrar_de_un_hermano_no_choca(tmp_path):
    ops = [
        {"op": "reemplazar", "id": "t3.f2.c1", "texto": "x"},
        {"op": "borrar", "id": "t3.f2.c2.p1"},
        {"op": "borrar", "id": "t3.f2.c10.p1"},
    ]
    assert len(_cargar(tmp_path, ops).operaciones) == 3


def test_ids_anidados_validos(tmp_path):
    ops = [
        {"op": "reemplazar", "id": "t1.f1.c1.t1.f2.c1.p1", "texto": "x"},
        {"op": "insertar_despues", "id": "t1.f1.c1.t1", "parrafos": ["y"]},
        {"op": "filas", "tabla": "t1.f1.c1.t1", "modelo": 1, "antes_de": 2, "contenido": [["z"]]},
        {"op": "borrar", "id": "t1.f1.c1.t1.f3"},
        {"op": "borrar", "id": "t1.f1.c1.t1.f2.c1.t1.f1.c1.p2"},
        {
            "op": "duplicar_tabla",
            "tabla": "t1.f1.c1.t1",
            "despues_de": "t1.f1.c1.t1.f2.c1.p1",
            "veces": 1,
            "celdas": [{"f1.c1": "copia"}],
        },
    ]
    assert len(_cargar(tmp_path, ops).operaciones) == 6


@pytest.mark.parametrize("id_anidado", ["t1.f0.c1.t1", "t1.f1.c1.t0", "f1.c1.t1", "t1.f1.c1.t1.c1"])
def test_ids_anidados_con_forma_no_valida(tmp_path, id_anidado):
    assert "operaciones[0]" in _invalido(tmp_path, [{"op": "borrar", "id": id_anidado}])


def test_duplicar_celdas_siguen_siendo_solo_de_primer_nivel(tmp_path):
    ops = [
        {
            "op": "duplicar_tabla",
            "tabla": "t1",
            "despues_de": "p2",
            "veces": 1,
            "celdas": [{"f1.c1.t1.f1.c1": "x"}],
        }
    ]
    assert "celdas[0]" in _invalido(tmp_path, ops)


def test_clave_repetida_en_el_yaml_se_rechaza_con_su_ruta(tmp_path):
    ruta = tmp_path / "relleno.yaml"
    ruta.write_text(
        "plantilla: Plantilla.docx\n"
        f"sha256: {HASH}\n"
        "salida: Programacion.docx\n"
        "operaciones:\n"
        "  - op: reemplazar\n"
        "    id: p1\n"
        "    id: p2\n"
        "    texto: x\n",
        encoding="utf-8",
    )
    with pytest.raises(ErrorEscritura) as exc:
        cargar_relleno(ruta, tmp_path)
    assert exc.value.codigo == "RELLENO_INVALIDO"
    assert exc.value.detalle.startswith("operaciones[0].id")


def test_clave_repetida_en_la_raiz(tmp_path):
    ruta = tmp_path / "relleno.yaml"
    ruta.write_text(
        f"plantilla: A.docx\nplantilla: B.docx\nsha256: {HASH}\nsalida: S.docx\noperaciones: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ErrorEscritura) as exc:
        cargar_relleno(ruta, tmp_path)
    assert exc.value.codigo == "RELLENO_INVALIDO"
    assert exc.value.detalle.startswith("plantilla")


def test_clave_desconocida_de_una_operacion_lista_las_validas(tmp_path):
    ops = [{"op": "insertar_despues", "id": "p1", "texto": "a"}]
    detalle = _invalido(tmp_path, ops)
    assert detalle == "operaciones[0].texto: clave desconocida; válidas: id, parrafos, estilo"


def test_clave_desconocida_en_la_raiz_lista_las_validas(tmp_path):
    detalle = _invalido(tmp_path, [{"op": "borrar", "id": "p1"}], colour="red")
    assert detalle == ("colour: clave desconocida; válidas: plantilla, sha256, salida, operaciones")


@pytest.mark.parametrize(
    "contenido",
    [
        "texto: " + chr(0xFFFE) + "\n",  # carácter no imprimible para el lector de YAML
        "texto: \x07\n",
        "fecha: 2026-02-30\n",  # fecha sin comillas que no existe
    ],
)
def test_yaml_con_caracteres_o_fechas_imposibles_es_relleno_invalido(tmp_path, contenido):
    ruta = tmp_path / "relleno.yaml"
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(ErrorEscritura) as exc:
        cargar_relleno(ruta, tmp_path)
    assert exc.value.codigo == "RELLENO_INVALIDO"


def test_ids_de_encabezados_y_pies_validos(tmp_path):
    ops = [
        {"op": "reemplazar", "id": "e1.p1", "texto": "Curso 2027/28"},
        {"op": "reemplazar", "id": "pie2.t1.f1.c1", "texto": "x"},
        {"op": "insertar_despues", "id": "e1.t1", "parrafos": ["y"]},
        {"op": "filas", "tabla": "e12.t1", "modelo": 1, "antes_de": "final", "contenido": [["z"]]},
        {"op": "borrar", "id": "pie1.t1.f1.c1.t1.f2"},
        {
            "op": "duplicar_tabla",
            "tabla": "e1.t1",
            "despues_de": "e1.p1",
            "veces": 1,
            "celdas": [{"f1.c1": "copia"}],
        },
    ]
    assert len(_cargar(tmp_path, ops).operaciones) == 6


@pytest.mark.parametrize("id_", ["x1.p1", "e0.p1", "pie0.p1", "e1", "pie1", "e01.p1", "e1.e1.p1"])
def test_ids_de_encabezados_y_pies_con_forma_no_valida(tmp_path, id_):
    assert "operaciones[0]" in _invalido(tmp_path, [{"op": "reemplazar", "id": id_, "texto": "x"}])


def test_las_reglas_de_conflicto_valen_con_el_prefijo_de_parte(tmp_path):
    ops = [
        {"op": "reemplazar", "id": "e1.t1.f1.c1", "texto": "x"},
        {"op": "borrar", "id": "e1.t1.f1.c1.p1"},
    ]
    assert "operaciones[1]" in _conflictivo(tmp_path, ops)
    # Una parte y otra no se pisan, ni con el cuerpo.
    separadas = [
        {"op": "reemplazar", "id": "e1.p1", "texto": "x"},
        {"op": "borrar", "id": "pie1.p1"},
        {"op": "borrar", "id": "p1"},
    ]
    assert len(_cargar(tmp_path, separadas).operaciones) == 3
