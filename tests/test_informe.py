"""Tests del esquema cerrado del informe."""

from __future__ import annotations

import json

import pytest

from tiza.informe import ErrorInforme, escribir, leer, resumen, validar, validar_estructura


def informe_valido() -> dict:
    return {
        "version": 1,
        "comando": "publicar",
        "entorno": "pruebas",
        "curso": 1234,
        "resultado": "ok",
        "pasos": [
            {"codigo": "LOGIN", "resultado": "ok", "detalle": None},
            {"codigo": "PUBLICAR", "resultado": "ok", "detalle": "pagina.md"},
        ],
        "ficheros": [
            {
                "nombre": "pagina.md",
                "tipo": "pagina",
                "cmid": 456,
                "accion": "creada",
                "oculto": True,
                "url": "https://aula.example.org/mod/page/view.php?id=456",
                "seccion": "Tema 3",
                "hash": "a" * 64,
            }
        ],
        "errores": [],
    }


def test_informe_valido_se_escribe_y_se_lee(tmp_path):
    destino = escribir(informe_valido(), tmp_path / ".tiza")
    assert destino == tmp_path / ".tiza" / "informe.json"
    datos = json.loads(destino.read_text(encoding="utf-8"))
    assert datos["ficheros"][0]["cmid"] == 456
    assert leer(destino)["resultado"] == "ok"


def test_rechaza_campo_no_permitido_en_la_raiz(tmp_path):
    documento = informe_valido()
    documento["html_moodle"] = "<div>secreto</div>"
    with pytest.raises(ErrorInforme) as exc:
        escribir(documento, tmp_path / ".tiza")
    assert exc.value.codigo == "CAMPO_NO_PERMITIDO"


def test_rechaza_campo_no_permitido_en_un_fichero(tmp_path):
    documento = informe_valido()
    documento["ficheros"][0]["respuesta_cruda"] = "cualquier cosa"
    with pytest.raises(ErrorInforme) as exc:
        escribir(documento, tmp_path / ".tiza")
    assert exc.value.codigo == "CAMPO_NO_PERMITIDO"


def test_rechaza_tipos_incorrectos(tmp_path):
    documento = informe_valido()
    documento["ficheros"][0]["cmid"] = "456"
    with pytest.raises(ErrorInforme) as exc:
        escribir(documento, tmp_path / ".tiza")
    assert exc.value.codigo == "TIPO_INCORRECTO"


def test_rechaza_html_o_texto_con_simbolos(tmp_path):
    documento = informe_valido()
    documento["pasos"][1]["detalle"] = "<div>esto viene de Moodle</div>"
    with pytest.raises(ErrorInforme) as exc:
        validar(documento)
    assert exc.value.codigo == "TEXTO_NO_PERMITIDO"


def test_rechaza_resultado_desconocido(tmp_path):
    documento = informe_valido()
    documento["resultado"] = "regular"
    with pytest.raises(ErrorInforme) as exc:
        validar(documento)
    assert exc.value.codigo == "VALOR_NO_PERMITIDO"


def test_acepta_una_etiqueta(tmp_path):
    documento = informe_valido()
    documento["ficheros"][0]["tipo"] = "etiqueta"
    documento["ficheros"][0]["url"] = "https://aula.example.org/mod/label/view.php?id=456"
    escribir(documento, tmp_path / ".tiza")


def test_acepta_un_cuestionario(tmp_path):
    documento = informe_valido()
    documento["ficheros"][0]["tipo"] = "cuestionario"
    documento["ficheros"][0]["url"] = "https://aula.example.org/mod/quiz/view.php?id=456"
    escribir(documento, tmp_path / ".tiza")


def test_acepta_una_actividad_h5p(tmp_path):
    documento = informe_valido()
    documento["ficheros"][0]["tipo"] = "h5p"
    documento["ficheros"][0]["url"] = "https://aula.example.org/mod/h5pactivity/view.php?id=456"
    escribir(documento, tmp_path / ".tiza")


def test_rechaza_un_tipo_de_fichero_que_no_existe(tmp_path):
    documento = informe_valido()
    documento["ficheros"][0]["tipo"] = "encuesta"
    with pytest.raises(ErrorInforme):
        escribir(documento, tmp_path / ".tiza")


def test_resumen_es_lista_de_lineas(tmp_path):
    lineas = resumen(informe_valido())
    assert any("pagina.md" in linea for linea in lineas)
    assert any("456" in linea for linea in lineas)
    assert all("\n" not in linea for linea in lineas)


def test_resumen_muestra_url_del_aula():
    documento = informe_valido()
    documento["ficheros"][0]["url"] = "https://aula.example.org/c/mod/page/view.php?id=456"
    lineas = resumen(documento)
    assert "  Ver en el aula: https://aula.example.org/c/mod/page/view.php?id=456" in lineas


def test_resumen_sin_url_no_muestra_enlace():
    documento = informe_valido()
    documento["ficheros"][0]["url"] = None
    assert not any("Ver en el aula" in linea for linea in resumen(documento))


def test_resumen_enlace_solo_en_pantalla(tmp_path):
    documento = informe_valido()
    documento["ficheros"][0]["url"] = "https://aula.example.org/c/mod/page/view.php?id=456"
    assert "Ver en el aula" not in escribir(documento, tmp_path).read_text(encoding="utf-8")


def informe_con_errores(*codigos: str) -> dict:
    documento = informe_valido()
    documento["resultado"] = "error"
    documento["errores"] = list(codigos)
    return documento


def test_resumen_explica_que_hacer():
    lineas = resumen(informe_con_errores("SIN_SESION"))
    assert any(l.startswith("Qué hacer (SIN_SESION): ") and "tiza empezar" in l for l in lineas)


def test_resumen_no_repite_explicaciones():
    lineas = resumen(informe_con_errores("FICHERO_AUSENTE", "FICHERO_AUSENTE"))
    assert sum(l.startswith("Qué hacer (FICHERO_AUSENTE)") for l in lineas) == 1


def test_resumen_tolera_codigo_desconocido():
    lineas = resumen(informe_con_errores("CODIGO_FUTURO"))
    assert "Errores: CODIGO_FUTURO" in lineas
    assert not any(l.startswith("Qué hacer") for l in lineas)


def test_la_explicacion_no_entra_en_el_json(tmp_path):
    ruta = escribir(informe_con_errores("SIN_SESION"), tmp_path)
    assert "Qué hacer" not in ruta.read_text(encoding="utf-8")


def test_el_aviso_de_worktree_cabe_en_el_esquema():
    documento = informe_con_errores("SIN_SESION")
    documento["pasos"] = [
        {
            "codigo": "SIN_SESION",
            "resultado": "fallo",
            "detalle": (
                "estás en un worktree de git; abre la sesión del agente "
                "en la carpeta de la asignatura"
            ),
        }
    ]
    validar(documento)
    assert any(linea.startswith("Paso SIN_SESION: fallo") for linea in resumen(documento))


def test_rechaza_controles_c1_y_bidi():
    for caracter in ("\x9b", "\N{RIGHT-TO-LEFT OVERRIDE}", "\u061c"):
        documento = informe_valido()
        documento["ficheros"][0]["seccion"] = f"Tema{caracter}"
        with pytest.raises(ErrorInforme):
            validar(documento)


def test_resumen_dice_si_queda_visible():
    documento = informe_valido()
    documento["ficheros"][0]["oculto"] = False
    linea = next(linea for linea in resumen(documento) if linea.startswith("Fichero"))
    assert "visible" in linea


def estructura_valida() -> dict:
    return {
        "version": 1,
        "generado": "2026-10-03T10:00:00+00:00",
        "cursos": {
            "pruebas": {"id": 1234, "secciones": [{"numero": 0, "nombre": "General", "id": 9}]},
        },
    }


def test_estructura_valida():
    validar_estructura(estructura_valida())


def test_estructura_con_un_solo_curso():
    datos = estructura_valida()
    datos["cursos"] = {
        "real": {"id": 5678, "secciones": [{"numero": 0, "nombre": "General", "id": 9}]},
    }
    validar_estructura(datos)


@pytest.mark.parametrize("codigo", ["SIN_CURSO_PRUEBAS", "SOLO_OCULTO_SIN_PRUEBAS"])
def test_resumen_explica_los_codigos_del_modo_sin_pruebas(codigo):
    lineas = resumen(informe_con_errores(codigo))
    assert any(linea.startswith(f"Qué hacer ({codigo}):") for linea in lineas)


@pytest.mark.parametrize(
    "estropear",
    [
        lambda datos: datos.update(extra=1),
        lambda datos: datos["cursos"].update(otro={"id": 1, "secciones": []}),
        lambda datos: datos["cursos"]["pruebas"]["secciones"][0].update(nombre="<b>x</b>"),
        lambda datos: datos["cursos"]["pruebas"]["secciones"][0].pop("id"),
        lambda datos: datos["cursos"]["pruebas"].update(id="1234"),
    ],
)
def test_estructura_fuera_del_esquema(estropear):
    datos = estructura_valida()
    estropear(datos)
    with pytest.raises(ErrorInforme):
        validar_estructura(datos)


def test_crear_da_un_informe_valido():
    from tiza.informe import crear

    documento = crear("publicar", "error", [], None, ["SIN_SESION"], "pruebas", 1234)
    validar(documento)
    assert documento["ficheros"] == []
    assert documento["errores"] == ["SIN_SESION"]
    assert (documento["entorno"], documento["curso"]) == ("pruebas", 1234)
