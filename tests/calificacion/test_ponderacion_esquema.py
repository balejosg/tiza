"""``ponderacion.yaml``: forma, líneas, ciclos, repeticiones y ficheros. Sin red ni aula."""

from __future__ import annotations

from pathlib import Path

import pytest

from tiza import agente
from tiza.calificacion.ponderacion_esquema import (
    CalificadorAula,
    CategoriaAula,
    ErrorPonderacion,
    cargar_ponderacion,
    comprobar_contra_calificador,
)

# El ejemplo del diseño (§3); la guía del calificador lo reutiliza.
EJEMPLO_PONDERACION = """\
ponderacion:
  # Nueva: tiza la crea y la reconoce por su número de ID (TZP_EXAMEN_1EV), no por el nombre.
  - id: EXAMEN_1EV
    nombre: "Examen 1.ª evaluación"
    dentro_de: "PRIMERA EVALUACIÓN"     # categoría que ya existe en el aula, por su nombre exacto
    calculo: media_ponderada
    solo_no_vacias: false
    elementos:
      - {fichero: 1eva/test-1-hardware.md, peso: 16}
      - {fichero: 1eva/test-2-procesador-textos.md, peso: 8}
      - {fichero: 1eva/test-3-maquinas-virtuales-linux.md, peso: 6}
      - {fichero: 1eva/tarea-sheets-monta-tu-pc.html, peso: 45}

  # Existente: solo se ajusta lo nombrado.
  - categoria: "PRIMERA EVALUACIÓN"
    elementos:
      - {categoria: EXAMEN_1EV, porcentaje: 30}
"""

FICHEROS_EJEMPLO = (
    "1eva/test-1-hardware.md",
    "1eva/test-2-procesador-textos.md",
    "1eva/test-3-maquinas-virtuales-linux.md",
    "1eva/tarea-sheets-monta-tu-pc.html",
)


def escribir_documento(carpeta: Path, relativa: str, tipo: str = "tarea") -> None:
    destino = carpeta / relativa
    destino.parent.mkdir(parents=True, exist_ok=True)
    extra = "apertura: 2026-10-01\nentrega: 2026-10-10\n" if tipo == "tarea" else ""
    destino.write_text(
        f"---\ntipo: {tipo}\nnombre: {destino.stem}\nseccion: 1\n{extra}---\n\nTexto.\n",
        encoding="utf-8",
    )


def preparar_ejemplo(carpeta: Path) -> None:
    for relativa in FICHEROS_EJEMPLO:
        escribir_documento(carpeta, relativa)


def esquema(carpeta: Path, texto: str):
    (carpeta / "ponderacion.yaml").write_text(texto, encoding="utf-8")
    return cargar_ponderacion(carpeta / "ponderacion.yaml", carpeta)


def fallo(carpeta: Path, texto: str) -> ErrorPonderacion:
    with pytest.raises(ErrorPonderacion) as exc:
        esquema(carpeta, texto)
    return exc.value


def nueva(elementos: str, id_: str = "A", dentro_de: str = "RAIZ", extra: str = "") -> str:
    return (
        f"  - id: {id_}\n    nombre: Nombre {id_}\n    dentro_de: {dentro_de}\n"
        f"    calculo: natural\n    solo_no_vacias: true\n{extra}    elementos:\n{elementos}"
    )


def existente(elementos: str, nombre: str = "RAIZ") -> str:
    return f"  - categoria: {nombre}\n    elementos:\n{elementos}"


def test_el_ejemplo_del_diseno_carga_con_sus_ficheros(tmp_path: Path) -> None:
    preparar_ejemplo(tmp_path)
    resultado = esquema(tmp_path, EJEMPLO_PONDERACION)
    nueva_, existente_ = resultado.entradas
    assert nueva_.nueva and nueva_.id == "EXAMEN_1EV" and nueva_.calculo == "media_ponderada"
    assert nueva_.solo_no_vacias is False and nueva_.dentro_de == "PRIMERA EVALUACIÓN"
    assert [e.peso for e in nueva_.elementos] == [16, 8, 6, 45]
    assert [e.referencia.nombre for e in nueva_.elementos] == list(FICHEROS_EJEMPLO)
    assert all(e.documento is not None and e.documento.tipo == "tarea" for e in nueva_.elementos)
    assert not existente_.nueva and existente_.categoria == "PRIMERA EVALUACIÓN"
    assert existente_.elementos[0].referencia.clase == "categoria"
    assert existente_.elementos[0].porcentaje == 30


def test_comprobar_da_cero_errores_con_el_ejemplo(tmp_path: Path) -> None:
    preparar_ejemplo(tmp_path)
    (tmp_path / "ponderacion.yaml").write_text(EJEMPLO_PONDERACION, encoding="utf-8")
    resultado = agente.comprobar(tmp_path, ["ponderacion.yaml"])
    assert resultado.informe["errores"] == []
    codigos = [paso["codigo"] for paso in resultado.informe["pasos"]]
    assert "COMPROBAR" in codigos and "CALIFICADOR_SIN_LEER" in codigos
    assert "CALIFICACION_Y_PONDERACION" not in codigos
    assert resultado.ficheros[0].codigo is None


def test_comprobar_avisa_una_sola_vez_si_hay_los_dos_esquemas(tmp_path: Path) -> None:
    preparar_ejemplo(tmp_path)
    (tmp_path / "ponderacion.yaml").write_text(EJEMPLO_PONDERACION, encoding="utf-8")
    (tmp_path / "calificacion.yaml").write_text(
        "organizacion: elementos\nelementos:\n  - {id: RA1, nombre: Redes, peso: 100}\n"
        "final: {de: elementos}\n",
        encoding="utf-8",
    )
    resultado = agente.comprobar(tmp_path, ["ponderacion.yaml", "calificacion.yaml"])
    codigos = [paso["codigo"] for paso in resultado.informe["pasos"]]
    assert resultado.informe["errores"] == []
    assert codigos.count("CALIFICACION_Y_PONDERACION") == 1
    solo = agente.comprobar(tmp_path, ["calificacion.yaml"])
    assert [p["codigo"] for p in solo.informe["pasos"]].count("CALIFICACION_Y_PONDERACION") == 1


def test_comprobar_informa_el_error_con_codigo_y_linea(tmp_path: Path) -> None:
    (tmp_path / "ponderacion.yaml").write_text("ponderacion:\n  - {raro: 1}\n", encoding="utf-8")
    resultado = agente.comprobar(tmp_path, ["ponderacion.yaml"])
    assert resultado.informe["errores"] == ["PONDERACION_INVALIDA"]
    assert "línea 2" in resultado.ficheros[0].detalle


def test_un_calificacion_yaml_sigue_su_camino(tmp_path: Path) -> None:
    (tmp_path / "calificacion.yaml").write_text("organizacion: nada\n", encoding="utf-8")
    resultado = agente.comprobar(tmp_path, ["calificacion.yaml"])
    assert resultado.informe["errores"] == ["ESQUEMA_INVALIDO"]


def test_raiz_incorrecta(tmp_path: Path) -> None:
    error = fallo(tmp_path, "otra:\n  - 1\n")
    assert error.codigo == "PONDERACION_INVALIDA"
    assert "línea 1" in error.detalle and "otra" in error.detalle


def test_clave_desconocida_en_la_raiz_y_en_la_entrada(tmp_path: Path) -> None:
    error = fallo(tmp_path, "ponderacion:\n  - {categoria: X, elementos: [], sobra: 1}\n")
    assert error.codigo == "PONDERACION_INVALIDA"
    assert "ponderacion[0].sobra" in error.detalle and "línea 2" in error.detalle
    error = fallo(tmp_path, "ponderacion:\n  - {id: A}\nextra: 1\n")
    assert error.codigo == "PONDERACION_INVALIDA" and "extra" in error.detalle


def test_clave_de_nueva_en_una_existente(tmp_path: Path) -> None:
    texto = "ponderacion:\n  - categoria: X\n    nombre: Y\n    elementos:\n      - {categoria: Z, porcentaje: 1}\n"
    error = fallo(tmp_path, texto)
    assert error.codigo == "PONDERACION_INVALIDA"
    assert "ponderacion[0].nombre" in error.detalle and "línea 3" in error.detalle


@pytest.mark.parametrize("id_", ["1A", "con espacio", "A-B", "A" * 17])
def test_id_invalido(tmp_path: Path, id_: str) -> None:
    texto = "ponderacion:\n" + nueva("      - {categoria: X, peso: 1}\n", id_=f'"{id_}"')
    error = fallo(tmp_path, texto)
    assert error.codigo == "PONDERACION_INVALIDA"
    assert "ponderacion[0].id" in error.detalle and "línea 2" in error.detalle


def test_id_repetido(tmp_path: Path) -> None:
    texto = (
        "ponderacion:\n"
        + nueva("      - {elemento: E1, peso: 1}\n")
        + nueva("      - {elemento: E2, peso: 1}\n")
    )
    error = fallo(tmp_path, texto)
    assert error.codigo == "PONDERACION_INVALIDA" and "ponderacion[1].id" in error.detalle


def test_mas_de_veinte_entradas(tmp_path: Path) -> None:
    entradas = "".join(
        nueva("      - {elemento: E, peso: 1}\n", id_=f"A{i}", dentro_de="RAIZ") for i in range(21)
    )
    error = fallo(tmp_path, "ponderacion:\n" + entradas)
    assert error.codigo == "PONDERACION_INVALIDA" and "20" in error.detalle
    assert "línea 1" in error.detalle


def test_veinte_entradas_valen(tmp_path: Path) -> None:
    entradas = "".join(
        nueva(f"      - {{elemento: E{i}, peso: 1}}\n", id_=f"A{i}") for i in range(20)
    )
    assert len(esquema(tmp_path, "ponderacion:\n" + entradas).entradas) == 20


def test_peso_en_existente(tmp_path: Path) -> None:
    texto = "ponderacion:\n" + existente("      - {elemento: E, peso: 3}\n")
    error = fallo(tmp_path, texto)
    assert error.codigo == "PESO_EN_EXISTENTE"
    assert "ponderacion[0].elementos[0].peso" in error.detalle and "línea 4" in error.detalle


def test_pesos_mezclados(tmp_path: Path) -> None:
    texto = "ponderacion:\n" + nueva(
        "      - {elemento: E1, peso: 3}\n      - {elemento: E2, porcentaje: 10}\n"
    )
    error = fallo(tmp_path, texto)
    assert error.codigo == "PESOS_MEZCLADOS"
    assert "ponderacion[0].elementos" in error.detalle and "línea 7" in error.detalle


def test_elemento_sin_peso_ni_porcentaje_o_con_los_dos(tmp_path: Path) -> None:
    for linea in ("{elemento: E}", "{elemento: E, peso: 1, porcentaje: 5}"):
        error = fallo(tmp_path, "ponderacion:\n" + nueva(f"      - {linea}\n"))
        assert error.codigo == "PONDERACION_INVALIDA" and "línea 8" in error.detalle


def test_peso_y_porcentaje_fuera_de_rango(tmp_path: Path) -> None:
    error = fallo(tmp_path, "ponderacion:\n" + nueva("      - {elemento: E, peso: 0}\n"))
    assert error.codigo == "PONDERACION_INVALIDA" and "elementos[0].peso" in error.detalle
    error = fallo(
        tmp_path, "ponderacion:\n" + existente("      - {elemento: E, porcentaje: 101}\n")
    )
    assert error.codigo == "PONDERACION_INVALIDA" and "elementos[0].porcentaje" in error.detalle


def test_calculo_y_solo_no_vacias(tmp_path: Path) -> None:
    texto = nueva("      - {elemento: E, peso: 1}\n").replace("natural", "media")
    error = fallo(tmp_path, "ponderacion:\n" + texto)
    assert error.codigo == "PONDERACION_INVALIDA" and "ponderacion[0].calculo" in error.detalle
    texto = nueva("      - {elemento: E, peso: 1}\n").replace(
        "solo_no_vacias: true", "solo_no_vacias: 1"
    )
    error = fallo(tmp_path, "ponderacion:\n" + texto)
    assert "ponderacion[0].solo_no_vacias" in error.detalle
    texto = nueva("      - {elemento: E, peso: 1}\n").replace("    solo_no_vacias: true\n", "")
    error = fallo(tmp_path, "ponderacion:\n" + texto)
    assert error.codigo == "PONDERACION_INVALIDA" and "solo_no_vacias" in error.detalle


def test_en_una_existente_calculo_y_solo_no_vacias_son_opcionales(tmp_path: Path) -> None:
    texto = (
        "ponderacion:\n  - categoria: X\n    calculo: natural\n    solo_no_vacias: false\n"
        "    elementos:\n      - {categoria: Y, porcentaje: 10}\n"
    )
    entrada = esquema(tmp_path, texto).entradas[0]
    assert entrada.calculo == "natural" and entrada.solo_no_vacias is False


def test_referencia_con_mas_de_una_clase_o_ninguna(tmp_path: Path) -> None:
    for linea in ("{elemento: E, categoria: C, peso: 1}", "{peso: 1}"):
        error = fallo(tmp_path, "ponderacion:\n" + nueva(f"      - {linea}\n"))
        assert error.codigo == "PONDERACION_INVALIDA" and "línea 8" in error.detalle


def test_actividad_necesita_tipo_y_seccion(tmp_path: Path) -> None:
    error = fallo(
        tmp_path, "ponderacion:\n" + nueva("      - {actividad: A, tipo: tarea, peso: 1}\n")
    )
    assert error.codigo == "PONDERACION_INVALIDA" and "seccion" in error.detalle
    error = fallo(
        tmp_path, "ponderacion:\n" + nueva("      - {elemento: A, tipo: tarea, peso: 1}\n")
    )
    assert "elementos[0].tipo" in error.detalle


def test_actividad_completa_carga(tmp_path: Path) -> None:
    texto = "ponderacion:\n" + nueva(
        "      - {actividad: Práctica 1, tipo: tarea, seccion: PRIMERA, peso: 1}\n"
    )
    referencia = esquema(tmp_path, texto).entradas[0].elementos[0].referencia
    assert (referencia.clase, referencia.tipo, referencia.seccion) == (
        "actividad",
        "tarea",
        "PRIMERA",
    )


def test_actividad_de_un_tipo_sin_nota(tmp_path: Path) -> None:
    texto = "ponderacion:\n" + nueva("      - {actividad: A, tipo: pagina, seccion: 1, peso: 1}\n")
    error = fallo(tmp_path, texto)
    assert error.codigo == "NO_CALIFICABLE" and "elementos[0].tipo" in error.detalle


def test_elemento_repetido_en_dos_listas(tmp_path: Path) -> None:
    texto = (
        "ponderacion:\n"
        + nueva("      - {elemento: E, peso: 1}\n", id_="A")
        + nueva("      - {elemento: E, peso: 2}\n", id_="B")
    )
    error = fallo(tmp_path, texto)
    assert error.codigo == "ELEMENTO_REPETIDO"
    assert "ponderacion[1].elementos[0]" in error.detalle and "línea 15" in error.detalle


def test_elemento_repetido_en_la_misma_lista(tmp_path: Path) -> None:
    texto = "ponderacion:\n" + nueva(
        "      - {elemento: E, peso: 1}\n      - {elemento: E, peso: 2}\n"
    )
    error = fallo(tmp_path, texto)
    assert error.codigo == "ELEMENTO_REPETIDO" and "ponderacion[0].elementos[1]" in error.detalle


def test_el_mismo_fichero_por_dos_rutas_es_repetido(tmp_path: Path) -> None:
    escribir_documento(tmp_path, "a/t.md")
    texto = "ponderacion:\n" + nueva(
        "      - {fichero: a/t.md, peso: 1}\n      - {fichero: a/../a/t.md, peso: 2}\n"
    )
    assert fallo(tmp_path, texto).codigo == "ELEMENTO_REPETIDO"


def test_declarar_una_nueva_y_nombrarla_en_su_padre_no_es_repeticion(tmp_path: Path) -> None:
    texto = (
        "ponderacion:\n"
        + nueva("      - {elemento: E, peso: 1}\n", id_="A")
        + existente("      - {categoria: A, porcentaje: 30}\n")
    )
    assert len(esquema(tmp_path, texto).entradas) == 2


def test_ciclo_directo(tmp_path: Path) -> None:
    texto = "ponderacion:\n" + nueva("      - {elemento: E, peso: 1}\n", id_="A", dentro_de="A")
    error = fallo(tmp_path, texto)
    assert error.codigo == "CICLO_DE_CATEGORIAS"
    assert "ponderacion[0].dentro_de" in error.detalle and "línea 4" in error.detalle


def test_ciclo_con_un_paso_intermedio(tmp_path: Path) -> None:
    texto = (
        "ponderacion:\n"
        + nueva("      - {elemento: E1, peso: 1}\n", id_="A", dentro_de="B")
        + nueva("      - {elemento: E2, peso: 1}\n", id_="B", dentro_de="A")
    )
    error = fallo(tmp_path, texto)
    assert error.codigo == "CICLO_DE_CATEGORIAS" and "dentro_de" in error.detalle


def test_ciclo_por_las_listas(tmp_path: Path) -> None:
    texto = (
        "ponderacion:\n"
        + nueva("      - {categoria: B, peso: 1}\n", id_="A")
        + nueva("      - {categoria: A, peso: 1}\n", id_="B")
    )
    assert fallo(tmp_path, texto).codigo == "CICLO_DE_CATEGORIAS"


def test_anidar_sin_ciclo_vale(tmp_path: Path) -> None:
    texto = (
        "ponderacion:\n"
        + nueva("      - {elemento: E1, peso: 1}\n", id_="A", dentro_de="B")
        + nueva("      - {elemento: E2, peso: 1}\n", id_="B", dentro_de="RAIZ")
    )
    assert len(esquema(tmp_path, texto).entradas) == 2


def test_porcentajes_superan_100(tmp_path: Path) -> None:
    texto = "ponderacion:\n" + existente(
        "      - {categoria: A, porcentaje: 60}\n      - {categoria: B, porcentaje: 50}\n"
    )
    error = fallo(tmp_path, texto)
    assert error.codigo == "PORCENTAJES_SUPERAN_100"
    assert "ponderacion[0].elementos" in error.detalle and "línea 3" in error.detalle


def test_porcentajes_que_suman_justo_100_pasan_el_esquema(tmp_path: Path) -> None:
    texto = "ponderacion:\n" + existente(
        "      - {categoria: A, porcentaje: 60}\n      - {categoria: B, porcentaje: 40}\n"
    )
    assert len(esquema(tmp_path, texto).entradas[0].elementos) == 2


def test_fichero_no_calificable(tmp_path: Path) -> None:
    escribir_documento(tmp_path, "pagina.md", tipo="pagina")
    texto = "ponderacion:\n" + nueva("      - {fichero: pagina.md, peso: 1}\n")
    error = fallo(tmp_path, texto)
    assert error.codigo == "NO_CALIFICABLE"
    assert "ponderacion[0].elementos[0].fichero" in error.detalle and "línea 8" in error.detalle


def test_fichero_que_no_existe(tmp_path: Path) -> None:
    texto = "ponderacion:\n" + nueva("      - {fichero: no-esta.md, peso: 1}\n")
    error = fallo(tmp_path, texto)
    assert error.codigo == "FICHERO_AUSENTE"
    assert "elementos[0].fichero" in error.detalle and "línea 8" in error.detalle


def test_fichero_con_extension_no_admitida(tmp_path: Path) -> None:
    (tmp_path / "notas.txt").write_text("x", encoding="utf-8")
    texto = "ponderacion:\n" + nueva("      - {fichero: notas.txt, peso: 1}\n")
    assert fallo(tmp_path, texto).codigo == "FORMATO_NO_ADMITIDO"


def test_fichero_fuera_de_la_carpeta_no_se_lee(tmp_path: Path) -> None:
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    escribir_documento(tmp_path, "fuera.md")
    texto = "ponderacion:\n" + nueva("      - {fichero: ../fuera.md, peso: 1}\n")
    error = fallo(carpeta, texto)
    assert error.codigo == "FICHERO_FUERA"
    assert "línea 8" in error.detalle


def test_fichero_oculto_no_se_lee(tmp_path: Path) -> None:
    escribir_documento(tmp_path, ".tiza/oculto.md")
    texto = "ponderacion:\n" + nueva("      - {fichero: .tiza/oculto.md, peso: 1}\n")
    assert fallo(tmp_path, texto).codigo == "FICHERO_TEMPORAL"


def test_el_yaml_fuera_de_la_carpeta(tmp_path: Path) -> None:
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    (tmp_path / "ponderacion.yaml").write_text("ponderacion: []\n", encoding="utf-8")
    with pytest.raises(ErrorPonderacion) as exc:
        cargar_ponderacion(tmp_path / "ponderacion.yaml", carpeta)
    assert exc.value.codigo == "ESQUEMA_FUERA_DE_CARPETA"


def test_comprobar_no_lee_un_yaml_de_fuera_para_despachar(tmp_path: Path) -> None:
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    (tmp_path / "ponderacion.yaml").write_text("ponderacion: []\n", encoding="utf-8")
    resultado = agente.comprobar(carpeta, ["../ponderacion.yaml"])
    assert resultado.informe["errores"] == ["ESQUEMA_FUERA_DE_CARPETA"]


def test_yaml_roto_o_con_alias(tmp_path: Path) -> None:
    assert fallo(tmp_path, "ponderacion: [\n").codigo == "PONDERACION_INVALIDA"
    assert fallo(tmp_path, "ponderacion:\n  - &a {categoria: X}\n").codigo == "PONDERACION_INVALIDA"


# --- Comprobación contra el calificador (la conectará T8 al fichero de estado) ---

AULA = CalificadorAula(
    (
        CategoriaAula(
            "PRIMERA",
            "media_ponderada",
            actividades=(("tarea", "Práctica", "PRIMERA"), ("tarea", "Práctica", "PRIMERA")),
            elementos=("Actitud", "Doble", "Doble"),
            subcategorias=("Sub",),
        ),
        CategoriaAula("Sub", "otro"),
        CategoriaAula("Repetida", "natural"),
        CategoriaAula("Repetida", "natural"),
    )
)


def codigos(texto: str, tmp_path: Path) -> list[str]:
    return [h.codigo for h in comprobar_contra_calificador(esquema(tmp_path, texto), AULA)]


def test_contra_el_calificador_categorias(tmp_path: Path) -> None:
    assert codigos(
        "ponderacion:\n" + existente("      - {categoria: Sub, porcentaje: 10}\n"), tmp_path
    ) == ["CATEGORIA_AUSENTE"]
    texto = "ponderacion:\n" + existente("      - {categoria: Sub, porcentaje: 10}\n", "Repetida")
    assert codigos(texto, tmp_path) == ["CATEGORIA_AMBIGUA"]
    texto = "ponderacion:\n" + nueva("      - {elemento: Actitud, peso: 1}\n", dentro_de="PRIMERA")
    assert codigos(texto, tmp_path) == []


def test_contra_el_calificador_actividades_y_elementos(tmp_path: Path) -> None:
    texto = "ponderacion:\n" + nueva(
        "      - {actividad: Práctica, tipo: tarea, seccion: PRIMERA, peso: 1}\n"
        "      - {actividad: Otra, tipo: tarea, seccion: PRIMERA, peso: 1}\n"
        "      - {elemento: Doble, peso: 1}\n"
        "      - {elemento: Nada, peso: 1}\n",
        dentro_de="PRIMERA",
    )
    assert codigos(texto, tmp_path) == [
        "ACTIVIDAD_AMBIGUA",
        "ACTIVIDAD_AUSENTE",
        "ELEMENTO_AMBIGUO",
        "ELEMENTO_AUSENTE",
    ]


def test_contra_el_calificador_fichero_sin_publicar_es_aviso(tmp_path: Path) -> None:
    escribir_documento(tmp_path, "t.md")
    texto = "ponderacion:\n" + nueva("      - {fichero: t.md, peso: 1}\n", dentro_de="PRIMERA")
    (hallazgo,) = comprobar_contra_calificador(esquema(tmp_path, texto), AULA)
    assert hallazgo.codigo == "ACTIVIDAD_PENDIENTE" and not hallazgo.error


def test_contra_el_calificador_porcentajes_sin_resto(tmp_path: Path) -> None:
    texto = "ponderacion:\n" + existente("      - {categoria: Sub, porcentaje: 100}\n", "PRIMERA")
    assert codigos(texto, tmp_path) == ["PORCENTAJES_SIN_RESTO"]
    todo = (
        "      - {actividad: Práctica, tipo: tarea, seccion: PRIMERA, porcentaje: 25}\n"
        "      - {elemento: Actitud, porcentaje: 25}\n"
        "      - {elemento: Doble, porcentaje: 25}\n"
        "      - {categoria: Sub, porcentaje: 25}\n"
    )
    resultado = codigos("ponderacion:\n" + existente(todo, "PRIMERA"), tmp_path)
    assert "PORCENTAJES_SIN_RESTO" not in resultado


def test_contra_el_calificador_calculo_sin_pesos(tmp_path: Path) -> None:
    texto = "ponderacion:\n" + existente("      - {elemento: Actitud, porcentaje: 10}\n", "Sub")
    assert codigos(texto, tmp_path) == ["CALCULO_SIN_PESOS"]
    texto = (
        "ponderacion:\n  - categoria: Sub\n    calculo: natural\n    elementos:\n"
        "      - {categoria: Repetida, porcentaje: 10}\n"
    )
    assert "CALCULO_SIN_PESOS" not in codigos(texto, tmp_path)


def test_comprobar_usa_el_calificador_de_estructura_v3(tmp_path: Path) -> None:
    from tiza import estado

    preparar_ejemplo(tmp_path)
    (tmp_path / "ponderacion.yaml").write_text(EJEMPLO_PONDERACION, encoding="utf-8")
    actividades = [
        {
            "tipo": "actividad",
            "actividad": "tarea",
            "nombre": Path(relativa).stem,
            "seccion": "1",
            "porcentaje": 25.0,
        }
        for relativa in FICHEROS_EJEMPLO
    ]
    calificador = {
        "categorias": [
            {
                "nombre": "PRIMERA EVALUACIÓN",
                "calculo": "media_ponderada",
                "solo_no_vacias": False,
                "bloqueada": False,
                "tiene_notas": True,
                "porcentaje": None,
                "hijos": actividades,
            }
        ]
    }
    estado.escribir_estructura(
        tmp_path / ".tiza",
        {
            "pruebas": {
                "id": 1234,
                "secciones": [{"numero": 1, "nombre": "Tema 1", "id": 11}],
                "calificador": calificador,
            }
        },
        version=3,
    )
    resultado = agente.comprobar(tmp_path, ["ponderacion.yaml"])
    codigos = [paso["codigo"] for paso in resultado.informe["pasos"]]
    assert resultado.informe["errores"] == []
    assert "CALIFICADOR_SIN_LEER" not in codigos
