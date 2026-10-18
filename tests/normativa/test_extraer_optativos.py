"""Módulos optativos de FP (`herramientas/normativa/extraer_fp.py`, orden `optativo`).

Todo sobre fragmentos reales (`herramientas/normativa/fuentes/`): el currículo del anexo II
de la Orden 3536/2025 y el catálogo del anexo I en la redacción de la Orden 3822/2026, tal
como sale `pdftotext -layout`. Sin red ni `pdftotext`.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType

import pytest

FUENTES = Path(__file__).parents[2] / "herramientas" / "normativa" / "fuentes"
ORDEN = "bocm-20250827-5"
MODIFICADORA = "bocm-20260925-20"
SUSTITUCIONES = (("Phyton", "Python"), ("Phython", "Python"))
PAGINA_CATALOGO = 108

CURRICULO_A = FUENTES / f"{ORDEN}_anexo-ii_cmo-001-003.txt"
CURRICULO_IFC = FUENTES / f"{ORDEN}_anexo-ii_cmo-310-318.txt"
CATALOGO_A = FUENTES / f"{MODIFICADORA}_anexo-i_catalogo-a.txt"
CATALOGO_IFC = FUENTES / f"{MODIFICADORA}_anexo-i_catalogo-ifc.txt"


@pytest.fixture(autouse=True)
def _herramientas_en_la_ruta(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))


def herramienta(nombre: str) -> ModuleType:
    return importlib.import_module(f"herramientas.normativa.{nombre}")


def lineas(*rutas: Path):
    texto = "".join(r.read_text(encoding="utf-8") for r in rutas)
    return herramienta("comun").lineas_limpias(texto)


# --- el currículo del anexo II -------------------------------------------------------------


def test_cmo_316_con_la_correccion_de_python():
    fp = herramienta("extraer_fp")
    o = fp.analizar_optativo(lineas(CURRICULO_IFC), "CMO-316", sustituciones=SUSTITUCIONES)
    assert (o.nombre, o.horas, o.pagina) == ("Programación en Python", 90, 203)
    resultados = o.modulo["resultados"]
    assert [len(r["criterios"]) for r in resultados] == [8, 6, 2, 1, 5, 5]
    # «1.Reconoce»: el boletín no deja espacio tras el número
    assert resultados[0]["numero"] == "1" and resultados[0]["pagina"] == 203
    assert resultados[0]["texto"] == (
        "Reconoce la estructura de un programa informático, identificando y relacionando los "
        "elementos propios del lenguaje de programación utilizado."
    )
    # los criterios que pasan de página llevan la página en que empiezan
    assert [(c["letra"], c["pagina"]) for c in resultados[1]["criterios"]][-3:] == [
        ("d", 203),  # el sello del boletín cae antes, pero la página cambia después de «e)»
        ("e", 203),
        ("f", 204),
    ]
    assert [(i["nivel"]) for i in o.contenidos].count(1) == 6
    assert [(i["nivel"]) for i in o.contenidos].count(2) == 20
    assert o.contenidos[0]["texto"] == "Identificación de los elementos de un programa informático."
    assert o.contenidos[-1]["texto"] == (
        "Programación orientada a objetos. Encapsulación, herencia y polimorfismo."
    )
    assert o.contenidos[-1]["pagina"] == 205


def test_sin_la_sustitucion_el_nombre_sale_como_en_el_boletin():
    fp = herramienta("extraer_fp")
    assert fp.analizar_optativo(lineas(CURRICULO_IFC), "CMO-316").nombre == (
        "Programación en Phyton"
    )


def test_el_encabezado_que_salta_de_linea_en_las_horas():
    fp = herramienta("extraer_fp")
    o = fp.analizar_optativo(lineas(CURRICULO_IFC), "CMO-311")
    assert (o.nombre, o.horas) == ("Informática aplicada a sistemas electrónicos (Robótica)", 50)


def test_el_anexo_ii_no_siempre_repite_el_nombre_del_catalogo():
    fp = herramienta("extraer_fp")
    assert fp.analizar_optativo(lineas(CURRICULO_IFC), "CMO-315").nombre == (
        "Arquitectura en la nube"
    )


def test_un_modulo_transversal_no_declara_horas():
    fp = herramienta("extraer_fp")
    o = fp.analizar_optativo(lineas(CURRICULO_A), "CMO-003")
    assert (o.nombre, o.horas) == ("Inglés para los negocios", None)
    # acaba donde empieza el apartado B), no en el módulo siguiente
    assert o.contenidos[-1]["texto"] == (
        "Uso de estructuras gramaticales adecuadas en la elaboración de escritos "
        "relacionados con la actividad económica de la empresa."
    )


def test_los_transversales_se_separan_por_su_encabezado():
    fp = herramienta("extraer_fp")
    uno = fp.analizar_optativo(lineas(CURRICULO_A), "CMO-001")
    dos = fp.analizar_optativo(lineas(CURRICULO_A), "CMO-002")
    assert uno.nombre == "Habilidades comunicativas en lengua extranjera profesional"
    assert dos.nombre == "Ampliación de lengua extranjera profesional"
    assert uno.modulo["resultados"][0]["texto"].startswith("Reconoce y entiende")
    assert dos.modulo["resultados"][0]["texto"].startswith("Identifica y comprende")


def test_el_ultimo_modulo_del_fragmento_acaba_donde_acaba_el_texto():
    fp = herramienta("extraer_fp")
    o = fp.analizar_optativo(lineas(CURRICULO_IFC), "CMO-318")
    assert o.horas == 90 and len(o.modulo["resultados"]) >= 1 and o.contenidos


def test_el_modulo_se_busca_por_su_encabezado_no_por_la_primera_vez_que_aparece_el_codigo():
    fp = herramienta("extraer_fp")
    # en el catálogo del anexo I, CMO-003 aparece antes que su currículo
    previa = "          CMO-003                                   En cualquiera de los 011 Inglés\n"
    texto = previa + CURRICULO_A.read_text(encoding="utf-8")
    o = fp.analizar_optativo(herramienta("comun").lineas_limpias(texto), "CMO-003")
    assert o.nombre == "Inglés para los negocios" and o.modulo["resultados"]


def test_contenidos_con_titulos_sin_numerar_y_un_subapartado_en_romanos():
    fp = herramienta("extraer_fp")
    o = fp.analizar_optativo(lineas(CURRICULO_IFC), "CMO-310")
    texto = [(i["nivel"], i["texto"]) for i in o.contenidos]
    assert [t for n, t in texto if n == 1] == [
        "Almacenamiento de la información.",
        "Bases de datos relacionales.",
        "Lenguaje de definición de datos (DDL Data Definition Language).",
        "Lenguaje de manipulación de datos (DML Data Manipulation Language).",
        "Realización de consultas.",
        "Tratamiento de datos.",
        "Interpretación de diagramas entidad/relación.",
    ]
    assert [n for n, _ in texto].count(2) == 21
    # una continuación que sigue a un punto («Lógicos.» / «Aritméticos.») no es un título
    assert (
        2,
        "Operadores (combinación, precedencia): de comparación. Lógicos. Aritméticos.",
    ) in texto
    assert texto[texto.index((2, "Inserción, borrado y modificación de registros:")) + 1] == (
        3,
        "A partir de datos proporcionados por el usuario.",
    )
    # el título que abre una página sigue al título anterior: no es continuación suya
    assert (
        o.contenidos[
            [t for _, t in texto].index(
                "Lenguaje de manipulación de datos (DML Data Manipulation Language)."
            )
        ]["pagina"]
        == 185
    )


def test_subapartados_en_romanos_bajo_una_letra():
    fp = herramienta("extraer_fp")
    o = fp.analizar_optativo(lineas(CURRICULO_IFC), "CMO-314")
    texto = [(i["nivel"], i["texto"]) for i in o.contenidos]
    amenazas = texto.index((2, "Amenazas. Tipos:"))
    assert texto[amenazas + 1 : amenazas + 3] == [
        (3, "Amenazas físicas."),
        (3, "Amenazas lógicas."),
    ]


def test_una_linea_sin_marca_a_principio_de_pagina_tras_una_letra_es_un_error():
    fp = herramienta("extraer_fp")
    # sin el título que cierra la página, «Lenguaje de manipulación…» (en otra página) sigue
    # a «f) Claves ajenas.»: la sangría de una página no sirve para otra
    roto = CURRICULO_IFC.read_text(encoding="utf-8").replace(
        "            Lenguaje de definición de datos (DDL Data Definition Language).\n", "", 1
    )
    with pytest.raises(ValueError, match="CMO-310: no sé si «Lenguaje de manipulación"):
        fp.analizar_optativo(herramienta("comun").lineas_limpias(roto), "CMO-310")


def test_un_modulo_que_no_esta_es_un_error():
    fp = herramienta("extraer_fp")
    with pytest.raises(ValueError, match="no encuentro el módulo CMO-999"):
        fp.analizar_optativo(lineas(CURRICULO_IFC), "CMO-999")


def test_un_criterio_fuera_de_orden_es_un_error_no_se_interpreta():
    fp = herramienta("extraer_fp")
    roto = CURRICULO_IFC.read_text(encoding="utf-8").replace(
        "c) Se han utilizado entornos integrados", "d) Se han utilizado entornos integrados"
    )
    with pytest.raises(ValueError, match="CMO-316: criterio d fuera de orden"):
        fp.analizar_optativo(herramienta("comun").lineas_limpias(roto), "CMO-316")


def test_un_apartado_de_contenidos_fuera_de_orden_es_un_error():
    fp = herramienta("extraer_fp")
    roto = CURRICULO_IFC.read_text(encoding="utf-8").replace(
        "2. Uso de estructuras de control.", "3. Uso de estructuras de control."
    )
    with pytest.raises(ValueError, match="CMO-316: apartado 3 fuera de orden"):
        fp.analizar_optativo(herramienta("comun").lineas_limpias(roto), "CMO-316")


# --- el catálogo del anexo I ---------------------------------------------------------------


def test_horas_de_un_modulo_especifico_en_el_catalogo():
    fp = herramienta("extraer_fp")
    texto = lineas(CATALOGO_IFC)
    horas = {c: fp.analizar_catalogo(texto, c).horas for c in ("CMO-310", "CMO-314", "CMO-316")}
    assert horas == {"CMO-310": 50, "CMO-314": 90, "CMO-316": 90}
    assert fp.analizar_catalogo(texto, "CMO-316").curso is None  # el catálogo no le pone curso


def test_el_catalogo_de_los_transversales_da_el_curso_pero_no_las_horas():
    fp = herramienta("extraer_fp")
    texto = lineas(CATALOGO_A)
    cursos = {
        c: fp.analizar_catalogo(texto, c).curso
        for c in ("CMO-001F", "CMO-001A", "CMO-002F", "CMO-002I", "CMO-002A", "CMO-003")
    }
    assert cursos == {
        "CMO-001F": None,  # «En cualquiera de los dos cursos»
        "CMO-001A": None,
        "CMO-002F": "2",
        "CMO-002I": "2",
        "CMO-002A": "2",
        "CMO-003": None,
    }
    assert fp.analizar_catalogo(texto, "CMO-002I").horas is None


def test_un_codigo_que_no_esta_en_el_catalogo_es_un_error():
    fp = herramienta("extraer_fp")
    with pytest.raises(ValueError, match="CMO-999: no está en el catálogo"):
        fp.analizar_catalogo(lineas(CATALOGO_IFC), "CMO-999")


# --- la ficha: de punta a punta -------------------------------------------------------------


def cache_optativos(tmp_path: Path) -> Path:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"{ORDEN}.txt").write_text(
        "".join(r.read_text(encoding="utf-8") for r in (CURRICULO_A, CURRICULO_IFC)),
        encoding="utf-8",
    )
    (cache / f"{MODIFICADORA}.txt").write_text(
        "".join(r.read_text(encoding="utf-8") for r in (CATALOGO_A, CATALOGO_IFC)),
        encoding="utf-8",
    )
    return cache


def datos_optativos(tmp_path: Path) -> Path:
    raiz = tmp_path / "datos"
    (raiz / "normas").mkdir(parents=True)
    (raiz / "fichas").mkdir()
    for id_, numero, fecha in (
        (ORDEN, "3536/2025", "2025-08-12"),
        (MODIFICADORA, "3822/2026", "2026-09-14"),
    ):
        norma = {
            "id": id_,
            "rango": "orden",
            "numero": numero,
            "fecha": fecha,
            "titulo": f"Orden de prueba {numero}",
            "boletin": "BOCM",
            "url_pdf": "https://www.bocm.es/ejemplo.pdf",
            "sha256": "0" * 64,
            "estado": "vigente",
            "revisada": "2026-10-18",
        }
        (raiz / "normas" / f"{id_}.json").write_text(json.dumps(norma), encoding="utf-8")
    return raiz


def extraer_optativo(tmp_path: Path, modulo: str):
    fp = herramienta("extraer_fp")
    if not (tmp_path / "cache").exists():
        cache_optativos(tmp_path)
    if not (tmp_path / "datos").exists():
        datos_optativos(tmp_path)
    ficha = f"MAD.CMO.{modulo.removeprefix('CMO-')}"
    argumentos = [
        "optativo",
        "--ficha",
        ficha,
        "--modulo",
        modulo,
        "--madrid",
        ORDEN,
        "--catalogo",
        MODIFICADORA,
        "--cursos-academicos",
        "2026-27",
        "--cache",
        str(tmp_path / "cache"),
        "--salida",
        str(tmp_path / "datos"),
    ]
    assert fp.main(argumentos) == 0
    return json.loads((tmp_path / "datos" / "fichas" / f"{ficha}.json").read_text(encoding="utf-8"))


def comprobar_todo(tmp_path: Path, *, con_correccion: bool = True):
    from tiza.normativa import limpiar_cache

    comprobar = herramienta("comprobar")
    limpiar_cache()
    documentos = comprobar.cargar_documentos(tmp_path / "cache", [ORDEN, MODIFICADORA])
    fuentes = {
        ORDEN: {
            "sustituciones": [list(s) for s in SUSTITUCIONES] if con_correccion else [],
            "modificada_por": [MODIFICADORA],
        },
        MODIFICADORA: {"modifica": [ORDEN]},
    }
    return comprobar.comprobar_datos(tmp_path / "datos", documentos, fuentes)


def test_ficha_de_un_especifico_con_la_correccion_de_python(tmp_path):
    ficha = extraer_optativo(tmp_path, "CMO-316")
    assert (ficha["codigo"], ficha["nombre"], ficha["curso"], ficha["etapa"]) == (
        "MAD.CMO.316",
        "Programación en Python",
        None,
        "fp_gs",
    )
    assert ficha["normas"] == [ORDEN, MODIFICADORA]
    modulo = ficha["elementos"][0]
    assert modulo["datos"] == {"horas": 90}
    # el catálogo vigente (Orden 3822/2026, anexo I) ya da el nombre corregido: la procedencia
    # es ese catálogo y el anexo II original, con su «Phyton», queda en `via`
    assert modulo["procedencia"] == {
        "norma": MODIFICADORA,
        "ubicacion": "anexo I, módulo CMO-316",
        "pagina": PAGINA_CATALOGO,
        "via": [{"norma": ORDEN, "ubicacion": "anexo II, módulo CMO-316", "pagina": 203}],
    }
    ra = next(e for e in ficha["elementos"] if e["codigo"] == "MAD.CMO.316.RA.2")
    assert ra["procedencia"] == {
        "norma": ORDEN,
        "ubicacion": "anexo II, módulo CMO-316, resultado de aprendizaje 2",
        "pagina": 203,
    }
    ce = next(e for e in ficha["elementos"] if e["codigo"] == "MAD.CMO.316.RA.2.f")
    assert ce["tipo"] == "criterio_fp" and ce["padre"] == "MAD.CMO.316.RA.2"
    co = next(e for e in ficha["elementos"] if e["codigo"] == "MAD.CMO.316.CO.5.8")
    assert co["tipo"] == "contenido" and co["padre"] == "MAD.CMO.316.CO.5"
    assert co["procedencia"] == {
        "norma": ORDEN,
        "ubicacion": "anexo II, módulo CMO-316, contenidos",
        "pagina": 205,
    }
    tipos = [e["tipo"] for e in ficha["elementos"]]
    assert tipos.count("resultado_aprendizaje") == 6
    assert tipos.count("criterio_fp") == 27
    assert tipos.count("contenido") == 26
    assert [e["orden"] for e in ficha["elementos"]] == list(range(1, len(ficha["elementos"]) + 1))
    assert comprobar_todo(tmp_path) == []


def test_ficha_de_un_transversal_de_segundo_curso_sin_horas(tmp_path):
    ficha = extraer_optativo(tmp_path, "CMO-002I")
    assert (ficha["codigo"], ficha["nombre"], ficha["curso"]) == (
        "MAD.CMO.002I",
        "Ampliación de lengua extranjera profesional",
        "2",
    )
    assert ficha["elementos"][0]["datos"] == {"curso": "2"}
    assert any(e["codigo"] == "MAD.CMO.002I.RA.1" for e in ficha["elementos"])
    assert comprobar_todo(tmp_path) == []


def test_las_tres_lenguas_comparten_el_curriculo_y_no_tienen_curso_ni_horas(tmp_path):
    ficha = extraer_optativo(tmp_path, "CMO-001F")
    assert ficha["curso"] is None and ficha["elementos"][0]["datos"] == {}
    assert ficha["elementos"][0]["procedencia"]["ubicacion"] == "anexo II, módulo CMO-001"
    assert any(e["codigo"] == "MAD.CMO.001F.CO.1.1" for e in ficha["elementos"])
    assert comprobar_todo(tmp_path) == []


def test_las_horas_del_catalogo_y_del_anexo_ii_tienen_que_coincidir(tmp_path):
    cache = cache_optativos(tmp_path)
    ruta = cache / f"{MODIFICADORA}.txt"
    ruta.write_text(
        ruta.read_text(encoding="utf-8").replace(
            "Ciberseguridad         90", "Ciberseguridad         50", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="CMO-314"):
        extraer_optativo(tmp_path, "CMO-314")


def test_el_catalogo_renombra_cmo_315_y_el_anexo_ii_queda_en_via(tmp_path):
    ficha = extraer_optativo(tmp_path, "CMO-315")
    assert ficha["nombre"] == "Arquitecturas en la nube"
    modulo = ficha["elementos"][0]
    assert modulo["texto"] == "Arquitecturas en la nube"
    assert modulo["procedencia"]["norma"] == MODIFICADORA
    assert modulo["procedencia"]["via"] == [
        {"norma": ORDEN, "ubicacion": "anexo II, módulo CMO-315", "pagina": 197}
    ]
    # el resto del currículo no cambia de procedencia
    assert all("via" not in e["procedencia"] for e in ficha["elementos"][1:])
    assert comprobar_todo(tmp_path) == []


def test_sin_relacion_declarada_entre_las_ordenes_el_renombrado_es_discrepancia(tmp_path):
    from tiza.normativa import limpiar_cache

    extraer_optativo(tmp_path, "CMO-315")
    limpiar_cache()
    comprobar = herramienta("comprobar")
    documentos = comprobar.cargar_documentos(tmp_path / "cache", [ORDEN, MODIFICADORA])
    problemas = comprobar.comprobar_datos(tmp_path / "datos", documentos, {})
    assert [(d.tipo, d.donde) for d in problemas] == [("RELACION", "MAD.CMO.315")]


def test_un_renombrado_que_no_esta_en_el_catalogo_es_texto(tmp_path):
    extraer_optativo(tmp_path, "CMO-315")
    ruta = tmp_path / "datos" / "fichas" / "MAD.CMO.315.json"
    ficha = json.loads(ruta.read_text(encoding="utf-8"))
    ficha["elementos"][0]["texto"] = "Arquitecturas de la nube"
    ruta.write_text(json.dumps(ficha), encoding="utf-8")
    assert [(d.tipo, d.donde) for d in comprobar_todo(tmp_path)] == [("TEXTO", "MAD.CMO.315")]


def test_un_elemento_que_la_correccion_cambia_cita_la_correccion_con_el_original_en_via(tmp_path):
    cache = cache_optativos(tmp_path)
    ruta = cache / f"{ORDEN}.txt"
    ruta.write_text(
        ruta.read_text(encoding="utf-8").replace(
            "Identificación de los elementos de un programa informático.",
            "Identificación de los elementos de un programa en Phyton.",
            1,
        ),
        encoding="utf-8",
    )
    # la página de la disposición adicional única de la modificadora
    destino = cache / f"{MODIFICADORA}.txt"
    destino.write_text(
        destino.read_text(encoding="utf-8")
        + "\fPág. 194   VIERNES 25 DE SEPTIEMBRE DE 2026   B.O.C.M. Núm. 229\n"
        + "   DISPOSICIÓN ADICIONAL ÚNICA\n   se sustituye por la forma correcta: Python.\n",
        encoding="utf-8",
    )
    ficha = extraer_optativo(tmp_path, "CMO-316")
    (co,) = [
        e for e in ficha["elementos"] if "en Python." in e["texto"] and e["tipo"] == "contenido"
    ]
    assert co["texto"] == "Identificación de los elementos de un programa en Python."
    assert co["procedencia"]["norma"] == MODIFICADORA
    assert (co["procedencia"]["ubicacion"], co["procedencia"]["pagina"]) == (
        "disposición adicional única",
        194,
    )
    (via,) = co["procedencia"]["via"]
    assert (via["norma"], via["ubicacion"]) == (ORDEN, "anexo II, módulo CMO-316, contenidos")
    assert comprobar_todo(tmp_path) == []
    # sin la sustitución declarada en la orden original, la página original no casa
    assert [(d.tipo, d.donde) for d in comprobar_todo(tmp_path, con_correccion=False)] == [
        ("TEXTO", co["codigo"])
    ]


def test_el_nombre_del_catalogo_es_el_del_anexo_ii_salvo_en_cmo_315():
    fp = herramienta("extraer_fp")
    catalogo = lineas(CATALOGO_IFC)
    curricular = lineas(CURRICULO_IFC)
    diferentes = {}
    for n in range(310, 319):
        codigo = f"CMO-{n}"
        del_catalogo = fp.analizar_catalogo(catalogo, codigo).nombre
        del_anexo = fp.analizar_optativo(curricular, codigo, sustituciones=SUSTITUCIONES).nombre
        if del_catalogo != del_anexo:
            diferentes[codigo] = (del_catalogo, del_anexo)
    assert diferentes == {"CMO-315": ("Arquitecturas en la nube", "Arquitectura en la nube")}


def test_el_catalogo_de_los_transversales_no_trae_nombre():
    fp = herramienta("extraer_fp")
    assert fp.analizar_catalogo(lineas(CATALOGO_A), "CMO-002I").nombre is None


def test_un_nombre_distinto_del_encabezado_se_rechaza(tmp_path):
    extraer_optativo(tmp_path, "CMO-313")
    ruta = tmp_path / "datos" / "fichas" / "MAD.CMO.313.json"
    ficha = json.loads(ruta.read_text(encoding="utf-8"))
    ficha["elementos"][0]["texto"] = "Fundamentos de programación avanzada"
    ruta.write_text(json.dumps(ficha), encoding="utf-8")
    assert [(d.tipo, d.donde) for d in comprobar_todo(tmp_path)] == [("TEXTO", "MAD.CMO.313")]


def test_un_subapartado_en_romanos_empieza_una_unidad_nueva_no_continua_la_frase():
    aparece = herramienta("comprobar").aparece
    pagina = (
        "a) Inserción, borrado y modificación de registros:\n   i. A partir de datos del usuario."
    )
    assert aparece("Inserción, borrado y modificación de registros:", pagina, completo=True)
    # una continuación en minúscula sigue sin valer: el texto guardado sería un trozo
    cortada = "a) Inserción, borrado y modificación\n   de registros:"
    assert not aparece("Inserción, borrado y modificación", cortada, completo=True)
