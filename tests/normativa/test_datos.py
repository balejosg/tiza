"""Modelo y cargador de los datos de normativa (todo offline, sobre datos de juguete)."""

from __future__ import annotations

import copy
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from tiza.normativa import (
    ErrorNormativa,
    Indice,
    Procedencia,
    cargar,
    limpiar_cache,
    normalizar_cita,
)

SINTETICOS = Path(__file__).parent / "datos_sinteticos"
MATERIA = "MAD.ESO.CCOMP.1"


@pytest.fixture
def raiz(tmp_path: Path) -> Path:
    """Copia de los datos de juguete: cada test puede estropear la suya sin tocar las demás."""
    destino = tmp_path / "datos"
    shutil.copytree(SINTETICOS, destino)
    return destino


def leer(raiz: Path, nombre: str) -> dict:
    return json.loads((raiz / nombre).read_text(encoding="utf-8"))


def escribir(raiz: Path, nombre: str, datos: dict) -> None:
    limpiar_cache()  # la caché es por ruta: tocar los ficheros la invalida
    ruta = raiz / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def modificar(raiz: Path, nombre: str, cambio) -> None:
    datos = leer(raiz, nombre)
    cambio(datos)
    escribir(raiz, nombre, datos)


def invalido(raiz: Path, *fragmentos: str) -> ErrorNormativa:
    limpiar_cache()
    with pytest.raises(ErrorNormativa) as info:
        cargar(raiz)
    assert info.value.codigo == "DATOS_INVALIDOS"
    for fragmento in fragmentos:
        assert fragmento in info.value.detalle
    return info.value


FICHA = "fichas/materia_ccomp_1.json"
NORMA = "normas/bocm-20250101-1.json"


def elemento(datos: dict, codigo: str) -> dict:
    return next(e for e in datos["elementos"] if e["codigo"] == codigo)


# --- carga correcta ---------------------------------------------------------


def test_carga_ficha_sintetica():
    indice = cargar(SINTETICOS)
    ficha = indice.fichas[MATERIA]
    competencias = [e for e in ficha.elementos if e.tipo == "competencia_especifica"]
    criterios = [e for e in ficha.elementos if e.tipo == "criterio"]
    assert [e.codigo for e in competencias] == [f"{MATERIA}.CE.1", f"{MATERIA}.CE.2"]
    assert [e.codigo for e in criterios] == [
        f"{MATERIA}.CR.1.1",
        f"{MATERIA}.CR.1.2",
        f"{MATERIA}.CR.2.1",
    ]
    assert indice.elementos[f"{MATERIA}.CR.1.2"][1].padre == f"{MATERIA}.CE.1"
    assert ficha.etapa == "eso"
    assert ficha.curso == "1"
    assert ficha.cursos_academicos == ("2025-26", "2026-27")
    assert ficha.desde == date(2026, 9, 1)


def test_elementos_apuntan_a_su_ficha_y_a_su_elemento():
    indice = cargar(SINTETICOS)
    ficha, elemento_ = indice.elementos[f"{MATERIA}.CE.1"]
    assert ficha is indice.fichas[MATERIA]
    assert elemento_.relaciones == {"descriptores": ("EST.ESO.DESC.CD1",)}
    assert elemento_.procedencia == Procedencia("bocm-20250101-1", "anexo II", 12, ())


def test_procedencia_via_nombra_la_norma_original():
    criterio = cargar(SINTETICOS).elementos[f"{MATERIA}.CR.1.2"][1]
    assert criterio.procedencia.norma == "bocm-20250201-2"
    assert criterio.procedencia.pagina is None
    assert criterio.procedencia.via == (Procedencia("bocm-20250101-1", "anexo II", 13, ()),)


def test_carga_normas():
    indice = cargar(SINTETICOS)
    decreto = indice.normas["bocm-20250101-1"]
    assert decreto.rango == "decreto"
    assert decreto.fecha == date(2025, 1, 1)
    assert decreto.revisada == date(2025, 2, 10)
    assert decreto.correcciones == ("bocm-20250201-2", "boe-a-2024-100#da-unica")
    assert decreto.derogaciones_parciales == ("Decreto 10/2020: capítulo II y art. 23",)
    derogada = indice.normas["boe-a-2020-50"]
    assert (derogada.estado, derogada.derogada_por) == ("derogada", "boe-a-2024-100")
    assert derogada.desde == date(2024, 9, 1)
    assert indice.normas["boe-a-2024-100"].url_api.startswith("https://www.boe.es/")


def test_datos_de_modulo():
    modulo = cargar(SINTETICOS).elementos["MAD.DAM.0485"][1]
    assert modulo.datos == {"horas": 160, "curso": "1"}


def test_cargar_es_idempotente_y_se_cachea():
    assert cargar(SINTETICOS) is cargar(SINTETICOS)
    assert isinstance(cargar(SINTETICOS), Indice)


def test_cargar_sin_raiz_lee_los_datos_del_paquete():
    indice = cargar()
    assert isinstance(indice, Indice)
    en_fichas = {e.codigo for f in indice.fichas.values() for e in f.elementos}
    assert set(indice.elementos) == en_fichas


# --- alias ------------------------------------------------------------------


def test_alias_de_errata():
    indice = cargar(SINTETICOS)
    assert indice.alias[normalizar_cita("Decreto 21/2025")] == "bocm-20250101-1"
    assert indice.alias[normalizar_cita("Decreto 27/2025")] == "bocm-20250101-1"


def test_alias_de_real_decreto_con_su_abreviatura():
    alias = cargar(SINTETICOS).alias
    assert alias["real decreto 1/2024"] == "boe-a-2024-100"
    assert alias["rd 1/2024"] == "boe-a-2024-100"
    assert alias[normalizar_cita("R.D. 1/2024")] == "boe-a-2024-100"


def test_normalizar_cita():
    assert normalizar_cita("  Decreto 27/2025 ") == "decreto 27/2025"
    assert normalizar_cita("Real Decreto 1/2024, de 10 de enero") == "real decreto 1/2024, 10 enero"
    assert normalizar_cita("Orden del 5/2025") == "orden 5/2025"
    assert normalizar_cita("DECRETO 27/2025") == "decreto 27/2025"
    # NFC: la forma descompuesta y la compuesta son la misma cita.
    assert normalizar_cita("Resolución 3/2025") == normalizar_cita("Resolución 3/2025")


def test_rechaza_alias_repetido_entre_normas(raiz):
    modificar(raiz, "normas/bocm-20250201-2.json", lambda d: d.update(citas=["Decreto 21/2025"]))
    modificar(raiz, "normas/boe-a-2024-100.json", lambda d: d.update(citas=["decreto 21/2025"]))
    invalido(raiz, "decreto 21/2025")


# --- claves cerradas --------------------------------------------------------


def test_rechaza_campo_desconocido(raiz):
    modificar(raiz, NORMA, lambda d: d.update(extra=1))
    invalido(raiz, "bocm-20250101-1.json", "extra")


def test_rechaza_campo_desconocido_en_ficha_elemento_y_procedencia(raiz):
    modificar(raiz, FICHA, lambda d: d.update(extra=1))
    invalido(raiz, "materia_ccomp_1.json", "extra")
    modificar(raiz, FICHA, lambda d: (d.pop("extra"), d["elementos"][0].update(otro=1)))
    invalido(raiz, "materia_ccomp_1.json", "otro")
    modificar(
        raiz,
        FICHA,
        lambda d: (d["elementos"][0].pop("otro"), d["elementos"][0]["procedencia"].update(x=1)),
    )
    invalido(raiz, "materia_ccomp_1.json", "procedencia", "x")


def test_rechaza_falta_de_campo_obligatorio(raiz):
    modificar(raiz, NORMA, lambda d: d.pop("sha256"))
    invalido(raiz, "bocm-20250101-1.json", "sha256")


def test_rechaza_json_ilegible_o_con_claves_repetidas(raiz):
    (raiz / "normas" / "roto.json").write_text("{no es json", encoding="utf-8")
    invalido(raiz, "roto.json")
    (raiz / "normas" / "roto.json").write_text('{"id": "a", "id": "b"}', encoding="utf-8")
    invalido(raiz, "roto.json", "id")


def test_rechaza_raiz_que_no_es_objeto(raiz):
    (raiz / "normas" / "lista.json").write_text("[]", encoding="utf-8")
    invalido(raiz, "lista.json")


def test_rechaza_directorio_ausente(tmp_path):
    invalido(tmp_path, "normas")


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("rango", "ley"),
        ("boletin", "BOJA"),
        ("estado", "caducada"),
        ("fecha", "10/01/2024"),
        ("fecha", "2024-13-01"),
        ("revisada", "2025-2-1"),
        ("sha256", "abc"),
        ("sha256", "G" * 64),
        ("numero", "27"),
        ("titulo", ""),
        ("id", "BOCM-20250101-1"),
        ("id", "bocm 1"),
    ],
)
def test_rechaza_valor_invalido_en_norma(raiz, campo, valor):
    modificar(raiz, NORMA, lambda d: d.update({campo: valor}))
    invalido(raiz, "bocm-20250101-1.json", campo)


def test_numero_de_una_correccion_nombra_la_norma_corregida(raiz):
    def correccion(d):
        d.update(rango="correccion", numero="del Real Decreto 217/2022")

    modificar(raiz, NORMA, correccion)
    assert cargar(raiz).normas["bocm-20250101-1"].rango == "correccion"
    for malo in ("27/2025", "Decreto 27/2025", "del Decreto 27", "del Decreto"):
        modificar(raiz, NORMA, lambda d, malo=malo: d.update(numero=malo))
        invalido(raiz, "bocm-20250101-1.json", "numero")


def test_numero_de_una_resolucion_puede_ser_un_titulo_corto(raiz):
    ruta = "normas/cm-resolucion-3-2025.json"
    modificar(raiz, ruta, lambda d: d.update(numero="de instrucciones de FP 2026-27"))
    assert cargar(raiz).normas["cm-resolucion-3-2025"].numero == "de instrucciones de FP 2026-27"
    # solo las resoluciones: un decreto sin número no es un decreto
    modificar(raiz, NORMA, lambda d: d.update(numero="de instrucciones de FP 2026-27"))
    invalido(raiz, "bocm-20250101-1.json", "numero")


def test_rechaza_estado_incoherente(raiz):
    modificar(raiz, "normas/boe-a-2020-50.json", lambda d: d.pop("derogada_por"))
    invalido(raiz, "boe-a-2020-50.json", "derogada_por")
    modificar(raiz, "normas/boe-a-2020-50.json", lambda d: d.update(derogada_por="boe-a-2024-100"))
    modificar(raiz, "normas/boe-a-2020-50.json", lambda d: d.pop("desde"))
    invalido(raiz, "boe-a-2020-50.json", "desde")
    modificar(raiz, NORMA, lambda d: d.update(desde="2025-01-01"))
    invalido(raiz, "bocm-20250101-1.json", "desde")


def test_rechaza_norma_que_apunta_a_otra_inexistente(raiz):
    modificar(raiz, NORMA, lambda d: d.update(modifica=["boe-a-1999-1"]))
    invalido(raiz, "bocm-20250101-1.json", "modifica", "boe-a-1999-1")
    modificar(raiz, NORMA, lambda d: d.update(modifica=[], correcciones=["boe-a-1999-1#da-1"]))
    invalido(raiz, "bocm-20250101-1.json", "correcciones", "boe-a-1999-1")
    modificar(raiz, NORMA, lambda d: d.update(correcciones=["bocm-20250201-2#"]))
    invalido(raiz, "bocm-20250101-1.json", "correcciones")
    modificar(raiz, "normas/boe-a-2020-50.json", lambda d: d.update(derogada_por="boe-a-1999-1"))
    modificar(raiz, NORMA, lambda d: d.update(correcciones=[]))
    invalido(raiz, "boe-a-2020-50.json", "derogada_por")


def test_rechaza_id_de_norma_repetido(raiz):
    shutil.copy(raiz / NORMA, raiz / "normas" / "copia.json")
    invalido(raiz, "bocm-20250101-1")


# --- dominios de las URL ----------------------------------------------------


def test_rechaza_url_fuera_de_dominios(raiz):
    modificar(raiz, NORMA, lambda d: d.update(url_pdf="https://example.org/x"))
    invalido(raiz, "bocm-20250101-1.json", "url_pdf")
    # El portal de la comunidad solo vale para las normas cuyo boletín es CM.
    modificar(raiz, NORMA, lambda d: d.update(url_pdf="https://www.comunidad.madrid/x"))
    invalido(raiz, "bocm-20250101-1.json", "url_pdf")
    modificar(raiz, NORMA, lambda d: d.update(url_pdf="http://www.bocm.es/x"))
    invalido(raiz, "bocm-20250101-1.json", "url_pdf")
    modificar(raiz, NORMA, lambda d: d.update(url_pdf="https://www.bocm.es.example.org/x"))
    invalido(raiz, "bocm-20250101-1.json", "url_pdf")
    modificar(raiz, NORMA, lambda d: d.update(url_pdf="https://usuario@www.bocm.es/x"))
    invalido(raiz, "bocm-20250101-1.json", "url_pdf")


def test_acepta_urls_de_boletines(raiz):
    modificar(raiz, NORMA, lambda d: d.update(url_pdf="https://www.bocm.es/x"))
    assert cargar(raiz).normas["bocm-20250101-1"].url_pdf == "https://www.bocm.es/x"
    modificar(raiz, NORMA, lambda d: d.update(url_pdf="https://www.boe.es/x"))
    assert cargar(raiz).normas["bocm-20250101-1"].url_pdf == "https://www.boe.es/x"


def test_url_api_solo_para_el_boe_y_en_sus_dominios(raiz):
    modificar(raiz, NORMA, lambda d: d.update(url_api="https://www.boe.es/api"))
    invalido(raiz, "bocm-20250101-1.json", "url_api")
    modificar(
        raiz,
        "normas/boe-a-2024-100.json",
        lambda d: d.update(url_api="https://example.org/api"),
    )
    modificar(raiz, NORMA, lambda d: d.update(url_api=None))
    invalido(raiz, "boe-a-2024-100.json", "url_api")


# --- fichas y elementos -----------------------------------------------------


def test_rechaza_codigo_duplicado(raiz):
    def duplicar(d):
        d["elementos"][1]["codigo"] = d["elementos"][0]["codigo"]

    modificar(raiz, FICHA, duplicar)
    invalido(raiz, "MAD.ESO.CCOMP.1.CE.2")


def test_un_codigo_puede_llevar_la_enie_de_una_lista_de_letras(raiz):
    # la competencia «ñ» del título (art. 5 del RD 450/2010): MAD.DAM.CP.ñ
    modificar(
        raiz,
        "fichas/modulo_0485.json",
        lambda d: elemento(d, "MAD.DAM.0485.RA.1").update(codigo="MAD.DAM.0485.RA.1.ñ"),
    )
    limpiar_cache()
    assert "MAD.DAM.0485.RA.1.ñ" in cargar(raiz).elementos
    # y una letra cualquiera fuera del alfabeto de las listas, no
    modificar(
        raiz,
        "fichas/modulo_0485.json",
        lambda d: elemento(d, "MAD.DAM.0485.RA.1.ñ").update(codigo="MAD.DAM.0485.RA.1.ç"),
    )
    invalido(raiz, "MAD.DAM.0485.RA.1.ç", "formato no válido")


def test_rechaza_codigo_duplicado_entre_fichas(raiz):
    modificar(
        raiz,
        "fichas/modulo_0485.json",
        lambda d: elemento(d, "MAD.DAM.0485.RA.1").update(codigo=f"{MATERIA}.CE.1"),
    )
    invalido(raiz, f"{MATERIA}.CE.1", "modulo_0485.json")


def test_rechaza_ficha_repetida(raiz):
    shutil.copy(raiz / FICHA, raiz / "fichas" / "copia.json")
    invalido(raiz, MATERIA)


def test_rechaza_padre_inexistente(raiz):
    modificar(raiz, FICHA, lambda d: elemento(d, f"{MATERIA}.CR.1.1").update(padre="NO.EXISTE"))
    invalido(raiz, "NO.EXISTE", "padre")


def test_rechaza_padre_de_otra_ficha(raiz):
    modificar(
        raiz, FICHA, lambda d: elemento(d, f"{MATERIA}.CR.1.1").update(padre="EST.ESO.DESC.CD1")
    )
    invalido(raiz, "EST.ESO.DESC.CD1", "padre")


def test_rechaza_ciclo_de_padres(raiz):
    def ciclo(d):
        elemento(d, f"{MATERIA}.CE.1").update(padre=f"{MATERIA}.CR.1.1")

    modificar(raiz, FICHA, ciclo)
    invalido(raiz, "padre")


def test_rechaza_relacion_a_codigo_inexistente(raiz):
    modificar(
        raiz,
        FICHA,
        lambda d: elemento(d, f"{MATERIA}.CE.1").update(
            relaciones={"descriptores": ["EST.ESO.DESC.CD9"]}
        ),
    )
    invalido(raiz, "EST.ESO.DESC.CD9", "descriptores")


def test_rechaza_relacion_mal_formada(raiz):
    modificar(
        raiz,
        FICHA,
        lambda d: elemento(d, f"{MATERIA}.CE.1").update(
            relaciones={"descriptores": "EST.ESO.DESC.CD1"}
        ),
    )
    invalido(raiz, "descriptores")
    modificar(
        raiz,
        FICHA,
        lambda d: elemento(d, f"{MATERIA}.CE.1").update(
            relaciones={"Descriptores": ["EST.ESO.DESC.CD1"]}
        ),
    )
    invalido(raiz, "Descriptores")


def test_rechaza_norma_inexistente_en_procedencia(raiz):
    modificar(
        raiz,
        FICHA,
        lambda d: elemento(d, f"{MATERIA}.CE.1")["procedencia"].update(norma="boe-a-1999-1"),
    )
    invalido(raiz, "boe-a-1999-1", "procedencia")


def test_rechaza_norma_inexistente_en_via(raiz):
    modificar(
        raiz,
        FICHA,
        lambda d: elemento(d, f"{MATERIA}.CR.1.2")["procedencia"]["via"][0].update(
            norma="boe-a-1999-1"
        ),
    )
    invalido(raiz, "boe-a-1999-1", "via")


def test_rechaza_norma_inexistente_en_la_ficha(raiz):
    modificar(raiz, FICHA, lambda d: d["normas"].append("boe-a-1999-1"))
    invalido(raiz, "boe-a-1999-1", "normas")


def test_rechaza_pagina_invalida(raiz):
    for pagina in (0, -1, "3", True):
        modificar(
            raiz,
            FICHA,
            lambda d, p=pagina: elemento(d, f"{MATERIA}.CE.1")["procedencia"].update(pagina=p),
        )
        invalido(raiz, "pagina")


def test_rechaza_tipo_de_elemento_desconocido(raiz):
    modificar(raiz, FICHA, lambda d: elemento(d, f"{MATERIA}.CE.1").update(tipo="inventado"))
    invalido(raiz, "CE.1].tipo")


def test_rechaza_orden_invalido_o_repetido(raiz):
    modificar(raiz, FICHA, lambda d: elemento(d, f"{MATERIA}.CE.1").update(orden="1"))
    invalido(raiz, "orden")
    modificar(raiz, FICHA, lambda d: elemento(d, f"{MATERIA}.CE.1").update(orden=2))
    invalido(raiz, "orden")


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("etapa", "primaria"),
        ("curso", "uno"),
        ("cursos_academicos", ["2026"]),
        ("cursos_academicos", ["2026-29"]),
        ("cursos_academicos", []),
        ("desde", "septiembre"),
        ("codigo", "mad.eso"),
    ],
)
def test_rechaza_valor_invalido_en_ficha(raiz, campo, valor):
    modificar(raiz, FICHA, lambda d: d.update({campo: valor}))
    invalido(raiz, "materia_ccomp_1.json", campo)


def test_ficha_sin_desde_lo_deja_en_none(raiz):
    modificar(raiz, FICHA, lambda d: d.pop("desde"))
    assert cargar(raiz).fichas[MATERIA].desde is None
    modificar(raiz, FICHA, lambda d: d.update(desde=None))
    assert cargar(raiz).fichas[MATERIA].desde is None


# --- datos cerrados por tipo ------------------------------------------------


def test_rechaza_dato_desconocido_en_un_tipo(raiz):
    modificar(
        raiz,
        "fichas/modulo_0485.json",
        lambda d: elemento(d, "MAD.DAM.0485")["datos"].update(extra=1),
    )
    invalido(raiz, "modulo_0485.json", "extra")
    modificar(raiz, FICHA, lambda d: elemento(d, f"{MATERIA}.CE.1").update(datos={"horas": 3}))
    invalido(raiz, "datos", "horas")


def test_rechaza_dato_con_tipo_de_valor_incorrecto(raiz):
    for datos in (
        {"horas": "160", "curso": "1"},
        {"horas": 0, "curso": "1"},
        {"horas": 160, "curso": 1},
        {"horas": True, "curso": "1"},
    ):
        modificar(
            raiz,
            "fichas/modulo_0485.json",
            lambda d, x=datos: elemento(d, "MAD.DAM.0485").update(datos=x),
        )
        invalido(raiz, "datos")


# --- textos -----------------------------------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        "Dos  espacios en medio.",
        "Espacio al final. ",
        " Espacio al principio.",
        "Salto\nde línea.",
        "Tabulador\taquí.",
        "Espacio duro.",
        "",
        "Café descompuesto.",
    ],
)
def test_rechaza_texto_con_espacios_sin_normalizar(raiz, texto):
    modificar(raiz, FICHA, lambda d: elemento(d, f"{MATERIA}.CE.1").update(texto=texto))
    invalido(raiz, "texto", f"{MATERIA}.CE.1")


def test_rechaza_titulo_con_espacios_sin_normalizar(raiz):
    modificar(raiz, NORMA, lambda d: d.update(titulo="Título  con doble espacio"))
    invalido(raiz, "bocm-20250101-1.json", "titulo")


# --- aislamiento de la caché -----------------------------------------------


def test_un_fallo_no_se_cachea_ni_contamina_otras_cargas(raiz, tmp_path):
    modificar(raiz, NORMA, lambda d: d.update(extra=1))
    invalido(raiz)
    modificar(raiz, NORMA, lambda d: d.pop("extra"))
    assert "bocm-20250101-1" in cargar(raiz).normas
    assert "bocm-20250101-1" in cargar(SINTETICOS).normas


def test_no_modifica_los_datos_de_entrada(raiz):
    antes = copy.deepcopy(leer(raiz, FICHA))
    cargar(raiz)
    assert leer(raiz, FICHA) == antes
