"""Tests del esquema cerrado del informe y de su construcción."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tiza import calendario, informe, tipos
from tiza.informe import (
    Borrador,
    ErrorInforme,
    Fichero,
    Paso,
    crear,
    escribir,
    leer,
    resumen,
    validar,
    validar_estructura,
)


def informe_valido() -> dict:
    return crear(
        "publicar",
        "ok",
        [
            Paso("LOGIN"),
            Paso("PUBLICAR", detalle="pagina.md"),
        ],
        [
            Fichero(
                nombre="pagina.md",
                tipo="pagina",
                cmid=456,
                accion="creada",
                oculto=True,
                url="https://aula.example.org/mod/page/view.php?id=456",
                seccion="Tema 3",
                hash="a" * 64,
                curso=5678,
            )
        ],
        entorno="pruebas",
        curso=1234,
    )


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


def _curso(id_: int, nombre: str = "General") -> dict:
    return {"id": id_, "secciones": [{"numero": 0, "nombre": nombre, "id": 9}]}


def test_estructura_v2_admite_una_lista_de_cursos_reales():
    datos = {
        "version": 2,
        "generado": "2026-10-03T10:00:00+00:00",
        "cursos": {"pruebas": _curso(1234), "real": [_curso(101), _curso(102, "Tema")]},
    }
    validar_estructura(datos)


def test_estructura_v1_sigue_valiendo_con_un_objeto():
    validar_estructura({**estructura_valida(), "cursos": {"real": _curso(5678)}})


@pytest.mark.parametrize(
    "datos",
    [
        {"version": 2, "cursos": {"real": _curso(101)}},  # v2: «real» es una lista
        {"version": 2, "cursos": {"real": []}},
        {"version": 2, "cursos": {"real": [_curso(n) for n in range(1, 8)]}},
        {"version": 2, "cursos": {"real": [_curso(1), "x"]}},
        {"version": 2, "cursos": {"pruebas": [_curso(1)]}},  # pruebas sigue siendo un objeto
        {"version": 1, "cursos": {"real": [_curso(101)]}},  # v1: «real» es un objeto
        {"version": 3, "cursos": {}},
        {"version": True, "cursos": {}},
    ],
)
def test_estructura_con_formas_no_validas_se_rechaza(datos):
    with pytest.raises(ErrorInforme):
        validar_estructura({"generado": "2026-10-03T10:00:00+00:00", **datos})


def test_el_maximo_de_cursos_reales_es_el_de_la_configuracion():
    from tiza import config, informe

    assert informe.MAX_CURSOS_REALES == config.MAX_REALES


def test_el_fichero_lleva_su_curso_o_nulo():
    documento = informe_valido()
    documento["ficheros"][0]["curso"] = None
    validar(documento)
    documento["ficheros"][0]["curso"] = "101"
    with pytest.raises(ErrorInforme):
        validar(documento)
    documento["ficheros"][0].pop("curso")
    with pytest.raises(ErrorInforme):
        validar(documento)


def test_el_resumen_dice_el_curso_de_cada_fichero_solo_con_varios():
    documento = informe_valido()
    linea = next(linea for linea in resumen(documento) if linea.startswith("Fichero"))
    assert "curso 5678" not in linea  # un solo curso: ya lo dice «Curso:»
    documento["curso"] = None
    linea = next(linea for linea in resumen(documento) if linea.startswith("Fichero"))
    assert "curso 5678" in linea


def test_paso_valida_al_construir():
    with pytest.raises(ErrorInforme) as exc:
        Paso("CODIGO_QUE_NO_EXISTE")
    assert exc.value.codigo == "VALOR_NO_PERMITIDO"
    with pytest.raises(ErrorInforme):
        Paso("LOGIN", "regular")
    with pytest.raises(ErrorInforme) as exc:
        Paso("LOGIN", detalle="<b>esto viene de Moodle</b>")
    assert exc.value.codigo == "TEXTO_NO_PERMITIDO"


def test_paso_como_dict():
    assert Paso("LOGIN").como_dict() == {"codigo": "LOGIN", "resultado": "ok", "detalle": None}
    assert Paso("COMPROBAR", "fallo", "a.md: SECCION_AUSENTE").resultado == "fallo"


def test_fichero_valida_al_construir():
    with pytest.raises(ErrorInforme):
        Fichero(nombre="", tipo="pagina")
    with pytest.raises(ErrorInforme) as exc:
        Fichero(nombre="a.md", tipo="encuesta")
    assert exc.value.codigo == "VALOR_NO_PERMITIDO"
    with pytest.raises(ErrorInforme):
        Fichero(nombre="a.md", tipo="pagina", url="moodle://x")
    with pytest.raises(ErrorInforme):
        Fichero(nombre="a.md", tipo="pagina", hash="no-es-un-sha256")
    Fichero(nombre="a.md", tipo="pagina")  # los demás campos, nulos


def test_fichero_como_dict():
    fichero = Fichero(nombre="a.md", tipo="pagina", cmid=7, curso=101)
    assert fichero.como_dict() == {
        "nombre": "a.md",
        "tipo": "pagina",
        "cmid": 7,
        "accion": None,
        "oculto": None,
        "url": None,
        "seccion": None,
        "hash": None,
        "curso": 101,
    }


def test_crear_acepta_los_tipos():
    documento = crear("publicar", "ok", [Paso("LOGIN")], [Fichero(nombre="a.md", tipo="pagina")])
    validar(documento)
    assert documento["pasos"] == [{"codigo": "LOGIN", "resultado": "ok", "detalle": None}]
    assert documento["ficheros"][0]["nombre"] == "a.md"


def test_crear_rechaza_la_raiz_mala_desde_el_principio():
    with pytest.raises(ErrorInforme):
        crear("borrar", "ok", [])
    with pytest.raises(ErrorInforme):
        crear("publicar", "regular", [])
    with pytest.raises(ErrorInforme):
        crear("publicar", "ok", [], entorno="otro")


def test_borrador_deriva_el_resultado():
    borrador = Borrador("comprobar")
    borrador.paso("ESTRUCTURA")
    assert borrador.errores == ()
    assert borrador.documento()["resultado"] == "ok"
    borrador.error("SIN_SESION")
    assert borrador.errores == ("SIN_SESION",)
    assert borrador.documento()["resultado"] == "error"
    assert borrador.documento("abortado")["resultado"] == "abortado"


def test_borrador_fallo_y_fichero():
    borrador = Borrador("publicar", entorno="real", curso=101)
    borrador.fallo("ESTRUCTURA", "ERROR_ESTRUCTURA")
    borrador.fichero(Fichero(nombre="a.md", tipo="pagina", curso=101))
    documento = borrador.documento()
    validar(documento)
    assert (documento["entorno"], documento["curso"]) == ("real", 101)
    assert documento["pasos"] == [
        {"codigo": "ESTRUCTURA", "resultado": "fallo", "detalle": "ERROR_ESTRUCTURA"}
    ]
    assert [f["nombre"] for f in documento["ficheros"]] == ["a.md"]


def test_borrador_agrega_otro_informe():
    previo = crear(
        "publicar",
        "ok",
        [Paso("LOGIN"), Paso("PUBLICAR", detalle="a.md")],
        [Fichero(nombre="a.md", tipo="pagina")],
    )
    borrador = Borrador("publicar", entorno="real")
    borrador.paso("CURSO", detalle="1 de 1: 101")
    borrador.agregar(previo, excluir={"LOGIN"})
    documento = borrador.documento()
    validar(documento)
    assert [p["codigo"] for p in documento["pasos"]] == ["CURSO", "PUBLICAR"]
    assert [f["nombre"] for f in documento["ficheros"]] == ["a.md"]


def test_el_esquema_rechaza_un_codigo_de_paso_desconocido():
    documento = informe_valido()
    documento["pasos"].append({"codigo": "PASO_FUTURO", "resultado": "ok", "detalle": None})
    with pytest.raises(ErrorInforme) as exc:
        validar(documento)
    assert exc.value.codigo == "VALOR_NO_PERMITIDO"


def test_el_registro_de_pasos_cubre_tipos_y_calendario():
    assert set(calendario.AVISOS) <= informe.PASOS
    for tipo in tipos.TIPOS:
        assert f"PUBLICAR_{tipo.upper()}" in informe.PASOS
        assert f"REPUBLICAR_{tipo.upper()}" in informe.PASOS


SRC = Path(__file__).resolve().parents[1] / "src" / "tiza"
_LITERAL_PASO = re.compile(r'\{\s*"codigo":\s*"')


def test_no_quedan_literales_de_paso_fuera_de_informe():
    """Los pasos se construyen con `Paso`/`Borrador`; el dict literal vive solo en el esquema."""
    culpables = [
        ruta.relative_to(SRC).as_posix()
        for ruta in SRC.rglob("*.py")
        if ruta.name != "informe.py" and _LITERAL_PASO.search(ruta.read_text(encoding="utf-8"))
    ]
    assert culpables == []


class TestOrdenar:
    """El informe de ``tiza ordenar``: comando y acciones propias, sin visibilidad."""

    @pytest.mark.parametrize("accion", ["movida", "ordenada", "sin_cambios"])
    def test_las_acciones_nuevas_valen(self, accion):
        documento = crear(
            "ordenar",
            "ok",
            [Paso("LOGIN")],
            [Fichero(nombre="a.md", tipo="pagina", cmid=7, accion=accion, seccion="Tema 1")],
            [],
            "pruebas",
            2,
        )
        validar(documento)
        assert documento["comando"] == "ordenar"
        assert documento["ficheros"][0]["oculto"] is None

    def test_una_accion_desconocida_no_vale(self):
        with pytest.raises(ErrorInforme):
            Fichero(nombre="a.md", tipo="pagina", accion="reordenada")


class TestCalificador:
    """El informe de ``tiza calificador``: sus pasos, sus acciones por actividad y sus recuentos."""

    @pytest.mark.parametrize("accion", ["colocada", "ya_estaba", "pendiente"])
    def test_las_acciones_por_actividad_valen(self, accion):
        documento = crear(
            "calificador",
            "ok",
            [Paso("LOGIN"), Paso("CALIFICADOR", detalle="12 cambios")],
            [Fichero(nombre="unidad/a.md", tipo="pagina", cmid=7, accion=accion, curso=2)],
            [],
            "pruebas",
            2,
        )
        validar(documento)
        assert documento["comando"] == "calificador"

    @pytest.mark.parametrize(
        "codigo",
        [
            "CALIFICADOR",
            "CALIFICADOR_BLOQUEAR",
            "CALIFICADOR_COLOCAR",
            "ACTIVIDAD_PENDIENTE",
            "CAMBIADO_A_MANO",
            "ELEMENTO_CON_NOTAS_QUITADO",
            "ELEMENTO_SIN_ACTIVIDADES",
            "EVALUACION_CERRADA_EN_EL_AULA",
            "TOTAL_AJENO_BLOQUEADO",
        ],
    )
    def test_los_pasos_del_calificador_estan_registrados(self, codigo):
        assert codigo in informe.PASOS
        Paso(codigo, detalle="2")

    def test_un_paso_que_no_esta_registrado_no_vale(self):
        with pytest.raises(ErrorInforme):
            Paso("CALIFICADOR_INVENTADO")

    def test_los_avisos_de_la_reconciliacion_son_los_pasos(self):
        from tiza.calificacion import reconciliar

        assert set(reconciliar.AVISOS) <= informe.PASOS


def test_resumen_lectura_esquema_cerrado():
    resumen = {
        "fichero": "prog.docx",
        "formato": "docx",
        "lectura": ".tiza/lecturas/prog.docx.txt",
        "bloques": 3,
        "tablas": 0,
        "paginas": None,
        "avisos": ["PDF_SIN_TABLAS"],
        "sha256": "a" * 64,
    }
    informe.validar_lectura(resumen)
    with pytest.raises(ErrorInforme) as exc:
        informe.validar_lectura({**resumen, "html_moodle": "x"})
    assert exc.value.codigo == "CAMPO_NO_PERMITIDO"
    with pytest.raises(ErrorInforme):
        informe.validar_lectura({**resumen, "bloques": "3"})
    with pytest.raises(ErrorInforme):
        informe.validar_lectura({**resumen, "sha256": "zz"})
    with pytest.raises(ErrorInforme):
        informe.validar_lectura({**resumen, "avisos": ["no es codigo"]})
    with pytest.raises(ErrorInforme):
        informe.validar_lectura({**resumen, "fichero": "a<b>.docx"})
    assert informe.Lectura(**resumen).a_dict() == resumen


# --- La copia que hace «tiza copia» ----------------------------------------------------


def _copia_hecha(**cambios) -> informe.CopiaHecha:
    datos = {
        "curso": "pruebas",
        "fichero": ".tiza/copias/pruebas-20261019-1030.mbz",
        "bytes": 2048,
        "actividades": {"page": 3, "assign": 1},
        "borrada_del_aula": True,
    }
    datos.update(cambios)
    return informe.CopiaHecha(**datos)


def test_el_informe_de_copia_lleva_la_copia_y_valida():
    documento = crear("copia", "ok", [Paso("COPIAR", detalle="2048 bytes")], copia=_copia_hecha())
    validar(documento)
    assert documento["copia"]["actividades"] == {"assign": 1, "page": 3}
    assert any(
        "Copia pruebas: .tiza/copias/pruebas-20261019-1030.mbz" in l for l in resumen(documento)
    )
    sin = crear("copia", "error", [], [], ["COPIA_NO_PERMITIDA"])
    assert "copia" not in sin
    validar(sin)


def test_solo_el_informe_de_copia_lleva_copia():
    with pytest.raises(ErrorInforme) as exc:
        crear("publicar", "ok", [], copia=_copia_hecha())
    assert exc.value.codigo == "CAMPO_NO_PERMITIDO"
    documento = crear("copia", "ok", [], copia=_copia_hecha())
    documento["comando"] = "publicar"
    with pytest.raises(ErrorInforme):
        validar(documento)


@pytest.mark.parametrize(
    "cambios",
    [
        {"fichero": "/etc/passwd"},
        {"fichero": "../fuera.mbz"},
        {"fichero": "a\\b.mbz"},
        {"fichero": ".tiza/copias/<b>.mbz"},
        {"curso": "pruebas<script>"},
        {"curso": ""},
        {"bytes": -1.5},
        {"bytes": None},
        {"actividades": {"Page": 1}},
        {"actividades": {"page": "3"}},
        {"actividades": {"page; rm": 1}},
        {"borrada_del_aula": "si"},
    ],
)
def test_la_copia_hecha_rechaza_valores_fuera_del_esquema(cambios):
    with pytest.raises(ErrorInforme):
        _copia_hecha(**cambios)


def test_la_copia_del_informe_es_un_esquema_cerrado():
    documento = crear("copia", "ok", [], copia=_copia_hecha())
    documento["copia"]["texto_de_moodle"] = "hola"
    with pytest.raises(ErrorInforme) as exc:
        validar(documento)
    assert exc.value.codigo == "CAMPO_NO_PERMITIDO"
    documento = crear("copia", "ok", [], copia=_copia_hecha())
    del documento["copia"]["bytes"]
    with pytest.raises(ErrorInforme) as exc:
        validar(documento)
    assert exc.value.codigo == "CAMPO_FALTANTE"


def test_el_resumen_de_rellenar_lleva_las_sustituciones():
    resumen = informe.Relleno("P.docx", "S.docx", 2, ("INDICE_SE_ACTUALIZA_AL_ABRIR",), 3)
    assert resumen.a_dict() == {
        "plantilla": "P.docx",
        "salida": "S.docx",
        "operaciones": 2,
        "sustituciones": 3,
        "avisos": ["INDICE_SE_ACTUALIZA_AL_ABRIR"],
    }
    with pytest.raises(informe.ErrorInforme):
        informe.Relleno("P.docx", "S.docx", 2, (), "3")
    with pytest.raises(informe.ErrorInforme):
        informe.validar_relleno({k: v for k, v in resumen.a_dict().items() if k != "sustituciones"})
