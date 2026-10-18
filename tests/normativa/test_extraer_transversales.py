"""Módulos transversales de FP (`herramientas/normativa/extraer_fp.py`, orden `transversal`).

Todo sobre fragmentos reales (`herramientas/normativa/fuentes/`): los resultados, criterios y
contenidos de Madrid de la Orden 3537/2025 (ya descifrados, tal como sale `pdftotext -layout`
del PDF arreglado) y la tabla de horas del Decreto 103/2024. Sin red ni `pdftotext`.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType

import pytest

FUENTES = Path(__file__).parents[2] / "herramientas" / "normativa" / "fuentes"
RD659 = "boe-a-2023-16889"
ORDEN = "bocm-20250827-6"
DECRETO103 = "bocm-20241115-2"

ORDEN_0179 = FUENTES / f"{ORDEN}_anexo-iii_0179.txt"
ORDEN_1665_1708 = FUENTES / f"{ORDEN}_anexos-v-vi_1665-1708.txt"
ORDEN_1709 = FUENTES / f"{ORDEN}_anexo-vii_1709.txt"
ORDEN_1710 = FUENTES / f"{ORDEN}_anexo-viii_1710.txt"
HORAS_DAM = FUENTES / f"{DECRETO103}_anexo-ii_dam.txt"
CICLO_DAM = "DESARROLLO DE APLICACIONES MULTIPLATAFORMA"


@pytest.fixture(autouse=True)
def _herramientas_en_la_ruta(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))


def herramienta(nombre: str) -> ModuleType:
    return importlib.import_module(f"herramientas.normativa.{nombre}")


def lineas(*rutas: Path):
    texto = "".join(r.read_text(encoding="utf-8") for r in rutas)
    return herramienta("comun").lineas_limpias(texto)


# --- resultados y criterios de la orden --------------------------------------------------------


def test_los_resultados_y_criterios_salen_de_la_orden_con_su_pagina():
    fp = herramienta("extraer_fp")
    m = fp.analizar_resultados_orden(lineas(ORDEN_1665_1708), "1708")
    assert [len(r["criterios"]) for r in m["resultados"]] == [6, 5, 3, 6, 9, 5]
    primero = m["resultados"][0]
    assert primero["numero"] == "1" and primero["pagina"] == 284
    assert primero["texto"] == (
        "Identifica los aspectos ambientales, sociales y de gobernanza (ASG) relativos a la "
        "sostenibilidad teniendo en cuenta el concepto de desarrollo sostenible y los marcos "
        "internacionales que contribuyen a su consecución."
    )
    assert primero["criterios"][0]["letra"] == "a"
    assert primero["criterios"][0]["texto"].startswith("Se ha descrito el concepto de sosteni")
    # los resultados y criterios que saltan de página llevan la página en que empiezan
    assert m["resultados"][1]["criterios"][1]["pagina"] == 285
    assert m["basicos"] == [] and m["orientaciones"] is None


def test_un_resultado_que_continua_en_otra_pagina_se_une_y_la_letra_pegada_es_criterio():
    fp = herramienta("extraer_fp")
    m = fp.analizar_resultados_orden(lineas(ORDEN_0179), "0179")
    assert (len(m["resultados"]), sum(len(r["criterios"]) for r in m["resultados"])) == (5, 43)
    # el resultado 1 empieza en la pág. 270 y acaba en la 271
    assert m["resultados"][0]["pagina"] == 270
    assert m["resultados"][0]["texto"].endswith(
        "interpretando con precisión el contenido del mensaje."
    )


def test_madrid_reordena_y_amplia_los_resultados_de_1709_y_1710():
    fp = herramienta("extraer_fp")
    uno = fp.analizar_resultados_orden(lineas(ORDEN_1665_1708, ORDEN_1709, ORDEN_1710), "1709")
    dos = fp.analizar_resultados_orden(lineas(ORDEN_1710), "1710")
    assert [len(r["criterios"]) for r in uno["resultados"]] == [9, 11, 3, 11, 9]
    assert [len(r["criterios"]) for r in dos["resultados"]] == [4, 7, 6, 9, 15]
    assert uno["resultados"][0]["texto"].startswith("Adquiere las competencias necesarias")
    assert dos["resultados"][4]["criterios"][-1]["letra"] == "ñ"


def test_un_criterio_fuera_de_orden_en_la_orden_es_un_error():
    fp = herramienta("extraer_fp")
    roto = ORDEN_1665_1708.read_text(encoding="utf-8").replace(
        "b) Se han identificado los asuntos", "c) Se han identificado los asuntos"
    )
    with pytest.raises(ValueError, match="1708: criterio c fuera de orden"):
        fp.analizar_resultados_orden(herramienta("comun").lineas_limpias(roto), "1708")


def test_un_modulo_sin_resultados_en_la_orden_es_un_error():
    fp = herramienta("extraer_fp")
    with pytest.raises(ValueError, match="no encuentro el módulo 1709 en la orden"):
        fp.analizar_resultados_orden(lineas(ORDEN_1710), "1709")


# --- contenidos de Madrid (Orden 3537/2025) -------------------------------------------------


def test_contenidos_de_la_orden_apartados_y_letras():
    fp = herramienta("extraer_fp")
    items = fp.analizar_contenidos_orden(lineas(ORDEN_1665_1708), "1708")
    assert [i["nivel"] for i in items].count(1) == 6
    assert [i["nivel"] for i in items].count(2) == 17
    assert items[0] == {
        "nivel": 1,
        "texto": "La sostenibilidad en el entorno actual.",
        "pagina": 286,
    }
    assert items[1]["texto"].startswith("La sostenibilidad: definición e importancia")
    # una línea justificada con huecos largos queda con espacios simples
    assert items[2]["texto"] == (
        "Objetivos para el desarrollo de la sostenibilidad y los aspectos medioambientales "
        "en los sectores empresariales."
    )
    # el módulo acaba donde empieza el siguiente anexo (que ya no es suyo)
    assert items[-1]["texto"] == "La evaluación y medidas de control."
    assert items[-1]["pagina"] == 287


def test_una_apartado_dividido_en_varias_lineas_se_une():
    fp = herramienta("extraer_fp")
    items = fp.analizar_contenidos_orden(lineas(ORDEN_1665_1708), "1665")
    assert len(items) == 30  # 6 apartados y 24 letras
    assert (
        items[6]["texto"]
        == "Tecnologías habilitadoras (THD). Características y aplicaciones de Internet de las "
        "cosas (IoT), Inteligencian artificial (IA), Big Data y tratamiento de datos, entre otras."
    )


def test_la_letra_pegada_al_texto_y_la_enie_son_apartados():
    fp = herramienta("extraer_fp")
    items = fp.analizar_contenidos_orden(lineas(ORDEN_0179), "0179")
    textos = [i["texto"] for i in items]
    # «m)Léxico…»: la letra pegada al texto
    assert any(
        t.startswith("Léxico y estructuras sintácticas que permitan desarrollar") for t in textos
    )
    assert any(t.startswith("Formación de palabras por derivación") for t in textos)  # «ñ)»
    assert (len([i for i in items if i["nivel"] == 1]), len(items)) == (6, 59)


def test_los_contenidos_acaban_antes_del_sello_del_boletin():
    fp = herramienta("extraer_fp")
    items = fp.analizar_contenidos_orden(lineas(ORDEN_1710), "1710")
    assert len(items) == 33  # 5 apartados y 28 letras
    assert items[-1]["texto"].startswith("Gestión administrativa y contable de la empresa")
    assert all("03/13.366" not in i["texto"] for i in items)


def test_un_numero_de_apartado_fuera_de_orden_es_un_error():
    fp = herramienta("extraer_fp")
    texto = ORDEN_1665_1708.read_text(encoding="utf-8").replace(
        "5. Estrategias sostenibles.", "7. Estrategias sostenibles."
    )
    with pytest.raises(ValueError, match="apartado 7 fuera de orden"):
        fp.analizar_contenidos_orden(herramienta("comun").lineas_limpias(texto), "1708")


def test_un_modulo_que_no_esta_en_la_orden_es_un_error():
    fp = herramienta("extraer_fp")
    with pytest.raises(ValueError, match="no encuentro el módulo 1709 en la orden"):
        fp.analizar_contenidos_orden(lineas(ORDEN_1710), "1709")


# --- la ficha: de punta a punta -------------------------------------------------------------


def cache_transversales(tmp_path: Path) -> Path:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"{ORDEN}.txt").write_text(
        "".join(
            r.read_text(encoding="utf-8")
            for r in (ORDEN_0179, ORDEN_1665_1708, ORDEN_1709, ORDEN_1710)
        ),
        encoding="utf-8",
    )
    (cache / f"{DECRETO103}.txt").write_text(
        HORAS_DAM.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return cache


def datos_transversales(tmp_path: Path) -> Path:
    raiz = tmp_path / "datos"
    (raiz / "normas").mkdir(parents=True)
    (raiz / "fichas").mkdir()
    for id_, (rango, numero, boletin) in {
        RD659: ("real_decreto", "659/2023", "BOE"),
        ORDEN: ("orden", "3537/2025", "BOCM"),
        DECRETO103: ("decreto", "103/2024", "BOCM"),
    }.items():
        norma = {
            "id": id_,
            "rango": rango,
            "numero": numero,
            "fecha": "2024-07-09",
            "titulo": f"Norma de prueba {numero}",
            "boletin": boletin,
            "url_pdf": "https://www.boe.es/ejemplo.pdf",
            "sha256": "0" * 64,
            "estado": "vigente",
            "revisada": "2026-10-18",
        }
        (raiz / "normas" / f"{id_}.json").write_text(json.dumps(norma), encoding="utf-8")
    return raiz


def extraer_transversal(tmp_path: Path, modulo: str, anexo_madrid: str, *extra):
    fp = herramienta("extraer_fp")
    cache = tmp_path / "cache"
    raiz = tmp_path / "datos"
    if not cache.exists():
        cache_transversales(tmp_path)
    if not raiz.exists():
        datos_transversales(tmp_path)
    argumentos = [
        "transversal",
        "--ficha",
        f"MAD.DAM.{modulo}",
        "--modulo",
        modulo,
        "--ciclo",
        CICLO_DAM,
        "--cursos-academicos",
        "2026-27",
        "--cache",
        str(cache),
        "--madrid",
        ORDEN,
        "--ubicacion-madrid",
        anexo_madrid,
        "--horas",
        DECRETO103,
        "--salida",
        str(raiz),
        *extra,
    ]
    assert fp.main(argumentos) == 0
    return json.loads((raiz / "fichas" / f"MAD.DAM.{modulo}.json").read_text(encoding="utf-8"))


def comprobar_todo(tmp_path: Path):
    from tiza.normativa import limpiar_cache

    comprobar = herramienta("comprobar")
    limpiar_cache()
    ids = [RD659, ORDEN, DECRETO103]
    documentos = comprobar.cargar_documentos(tmp_path / "cache", ids)
    return comprobar.comprobar_datos(tmp_path / "datos", documentos, {})


def test_ficha_de_un_transversal_todo_de_la_orden_de_madrid(tmp_path):
    ficha = extraer_transversal(tmp_path, "1708", "anexo VI")
    assert (ficha["codigo"], ficha["nombre"], ficha["curso"], ficha["etapa"]) == (
        "MAD.DAM.1708",
        "Sostenibilidad aplicada al sistema productivo",
        "2",
        "fp_gs",
    )
    assert ficha["normas"] == [ORDEN, DECRETO103]
    assert ficha["elementos"][0]["datos"] == {"horas": 30, "curso": "2"}
    ra = next(e for e in ficha["elementos"] if e["codigo"] == "MAD.DAM.1708.RA.3")
    # currículo propio de Madrid: cita la orden, su anexo y su página, sin `via`
    assert ra["procedencia"] == {
        "norma": ORDEN,
        "ubicacion": "anexo VI, módulo 1708, resultado de aprendizaje 3",
        "pagina": 285,
    }
    ce = next(e for e in ficha["elementos"] if e["codigo"] == "MAD.DAM.1708.RA.3.b")
    assert ce["tipo"] == "criterio_fp" and ce["padre"] == "MAD.DAM.1708.RA.3"
    co = next(e for e in ficha["elementos"] if e["codigo"] == "MAD.DAM.1708.CO.2.2")
    assert co["tipo"] == "contenido" and co["padre"] == "MAD.DAM.1708.CO.2"
    assert co["procedencia"] == {"norma": ORDEN, "ubicacion": "anexo VI", "pagina": 286}
    tipos = [e["tipo"] for e in ficha["elementos"]]
    assert tipos.count("resultado_aprendizaje") == 6
    assert tipos.count("criterio_fp") == 34
    assert tipos.count("contenido") == 23
    assert [e["orden"] for e in ficha["elementos"]] == list(range(1, len(ficha["elementos"]) + 1))
    assert comprobar_todo(tmp_path) == []


def test_el_minimo_estatal_se_cita_en_las_normas_de_la_ficha(tmp_path):
    ficha = extraer_transversal(tmp_path, "1709", "anexo VII", "--estatal", RD659)
    assert ficha["normas"] == [ORDEN, RD659, DECRETO103]
    assert ficha["curso"] == "1" and ficha["elementos"][0]["datos"] == {"horas": 100, "curso": "1"}
    tipos = [e["tipo"] for e in ficha["elementos"]]
    assert (tipos.count("resultado_aprendizaje"), tipos.count("criterio_fp")) == (5, 43)
    assert tipos.count("contenido") == 34  # el último apartado pasa de página
    assert comprobar_todo(tmp_path) == []


def test_la_comprobacion_sigue_rechazando_un_criterio_cortado(tmp_path):
    ficha_ruta = tmp_path / "datos" / "fichas" / "MAD.DAM.1708.json"
    extraer_transversal(tmp_path, "1708", "anexo VI")
    ficha = json.loads(ficha_ruta.read_text(encoding="utf-8"))
    ra = next(e for e in ficha["elementos"] if e["codigo"] == "MAD.DAM.1708.RA.3")
    ra["texto"] = "Establece la aplicación de criterios de sostenibilidad en el desempeño"
    ficha_ruta.write_text(json.dumps(ficha), encoding="utf-8")
    assert [d.tipo for d in comprobar_todo(tmp_path)] == ["TEXTO"]
