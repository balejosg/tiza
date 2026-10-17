"""Herramienta del mantenedor (`herramientas/normativa/`): análisis de texto, sin red ni pdftotext.

Los fragmentos de boletín de `herramientas/normativa/fuentes/` son texto ya extraído con
`pdftotext -layout`; las funciones de análisis trabajan sobre ese texto.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from types import ModuleType

import pytest

from tiza.normativa import Elemento, Procedencia, cargar, limpiar_cache

FUENTES = Path(__file__).parents[2] / "herramientas" / "normativa" / "fuentes"
BOCM = "bocm-20230531-18"
FRAGMENTO = FUENTES / "bocm-20230531-18_anexo-iv_ccomp-bach-1.txt"
MATERIA = "MAD.BACH.CCOMP.1"


@pytest.fixture(autouse=True)
def _herramientas_en_la_ruta(monkeypatch):
    """Solo estos tests ven el código del mantenedor (`herramientas/` no es del paquete)."""
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))


def herramienta(nombre: str) -> ModuleType:
    return importlib.import_module(f"herramientas.normativa.{nombre}")


def extraer(**cambios) -> dict:
    parametros = {
        "norma": BOCM,
        "nombre": "Ciencias de la Computación",
        "sigla": "CCOMP",
        "etapa": "bachillerato",
        "curso": "1",
        "cursos_academicos": ["2023-24", "2024-25"],
    }
    parametros.update(cambios)
    texto = FRAGMENTO.read_text(encoding="utf-8")
    return herramienta("extraer_lomloe").extraer_materia(texto, **parametros)


def elementos(ficha: dict) -> dict[str, dict]:
    return {e["codigo"]: e for e in ficha["elementos"]}


# --- extracción de la LOMLOE -------------------------------------------------


def test_lomloe_separa_enunciado_de_explicacion():
    por_codigo = elementos(extraer())
    ce1 = por_codigo[f"{MATERIA}.CE.1"]
    assert ce1["texto"].startswith("Reconocer y analizar los elementos físicos")
    assert ce1["texto"].endswith("su presencia en la actividad cotidiana.")
    assert "Los sistemas informáticos se han incorporado" not in ce1["texto"]
    assert ce1["relaciones"]["descriptores"] == [
        f"EST.BACH.DESC.{c}" for c in ("CCL3", "STEM4", "CD1", "CD2", "CD3", "CC1", "CE1")
    ]
    assert ce1["procedencia"] == {
        "norma": BOCM,
        "ubicacion": "anexo IV, competencia específica 1",
        "pagina": 115,
    }


def test_lomloe_criterios_por_competencia():
    por_codigo = elementos(extraer())
    criterios = [c for c, e in por_codigo.items() if e["tipo"] == "criterio"]
    for esperado in ("1.1", "1.2", "1.3", "2.1", "3.1", "3.2", "3.3", "4.1", "4.2", "4.3"):
        assert f"{MATERIA}.CR.{esperado}" in criterios
    assert len(criterios) == 10
    assert por_codigo[f"{MATERIA}.CR.4.2"]["padre"] == f"{MATERIA}.CE.4"
    # el criterio que cruza una página y el que empieza en la siguiente
    assert por_codigo[f"{MATERIA}.CR.3.1"]["texto"].endswith("vida académica.")
    assert por_codigo[f"{MATERIA}.CR.4.1"]["procedencia"]["pagina"] == 117
    # la lista de descriptores que acaba sin punto y con «y» entre los dos últimos
    assert por_codigo[f"{MATERIA}.CE.3"]["relaciones"]["descriptores"] == [
        f"EST.BACH.DESC.{c}"
        for c in (
            ["CCL1", "CCL3", "STEM1", "STEM4", "CD1", "CD2", "CD3"]
            + ["CPSAA4", "CPSAA5", "CC1", "CCEC4.1", "CCEC4.2"]
        )
    ]


def test_lomloe_vinetas_x_son_subcontenidos():
    por_codigo = elementos(extraer())
    padre = next(
        e
        for e in por_codigo.values()
        if e["texto"] == "Avances tecnológicos en la computación a lo largo de la historia:"
    )
    assert padre["tipo"] == "contenido"
    assert padre["padre"] == f"{MATERIA}.CO.A"
    hijo = next(e for e in por_codigo.values() if e["texto"].startswith("La válvula de vacío"))
    assert (
        hijo["texto"] == "La válvula de vacío. El primer ordenador electrónico (ENIAC 1943-1946)."
    )
    assert hijo["padre"] == padre["codigo"]
    assert hijo["codigo"] == f"{padre['codigo']}.3"
    assert not any(e["texto"].startswith(("x ", "- ")) for e in por_codigo.values())
    bloques = [e for e in por_codigo.values() if e["tipo"] == "bloque_contenidos"]
    assert [b["codigo"] for b in bloques] == [f"{MATERIA}.CO.{letra}" for letra in "ABCDE"]
    assert bloques[0]["texto"] == "Ciencias de la computación. Evolución histórica."


def escribir_datos(raiz: Path, ficha: dict) -> None:
    """Normas y descriptores mínimos más la ficha del extractor, con la disposición del paquete."""
    (raiz / "normas").mkdir()
    (raiz / "fichas").mkdir()
    for id_, numero in ((BOCM, "1736/2023"), ("boe-a-2022-4975", "243/2022")):
        norma = {
            "id": id_,
            "rango": "orden" if id_ == BOCM else "real_decreto",
            "numero": numero,
            "fecha": "2023-05-31" if id_ == BOCM else "2022-04-05",
            "titulo": f"Norma de prueba {numero}",
            "boletin": "BOCM" if id_ == BOCM else "BOE",
            "url_pdf": "https://www.bocm.es/ejemplo.pdf"
            if id_ == BOCM
            else "https://www.boe.es/ejemplo.pdf",
            "sha256": "0" * 64,
            "estado": "vigente",
            "revisada": "2026-10-17",
        }
        (raiz / "normas" / f"{id_}.json").write_text(json.dumps(norma), encoding="utf-8")
    codigos = sorted(
        {c for e in ficha["elementos"] for c in e.get("relaciones", {}).get("descriptores", [])}
    )
    descriptores = {
        "codigo": "EST.BACH.DESC",
        "nombre": "Descriptores de prueba",
        "etapa": "bachillerato",
        "curso": None,
        "cursos_academicos": ["2023-24"],
        "normas": ["boe-a-2022-4975"],
        "elementos": [
            {
                "codigo": codigo,
                "tipo": "descriptor",
                "texto": "Texto de prueba.",
                "procedencia": {"norma": "boe-a-2022-4975", "ubicacion": "anexo I", "pagina": None},
                "orden": i,
            }
            for i, codigo in enumerate(codigos, start=1)
        ],
    }
    (raiz / "fichas" / "descriptores.json").write_text(json.dumps(descriptores), "utf-8")
    herramienta("extraer_lomloe").escribir_ficha(ficha, raiz)


def test_lomloe_el_resultado_carga_con_el_cargador(tmp_path):
    ficha = extraer()
    # `unir` arregla la partición de palabras: nada de saltos ni dobles espacios en el JSON
    for e in ficha["elementos"]:
        assert "  " not in e["texto"] and "\n" not in e["texto"]
    escribir_datos(tmp_path, ficha)
    assert (tmp_path / "fichas" / f"{MATERIA}.json").is_file()

    limpiar_cache()
    cargada = cargar(raiz=tmp_path).fichas[MATERIA]
    competencias = [e for e in cargada.elementos if e.tipo == "competencia_especifica"]
    assert [e.codigo for e in competencias] == [f"{MATERIA}.CE.{n}" for n in (1, 2, 3, 4)]
    assert cargada.curso == "1" and cargada.etapa == "bachillerato"


# --- comprobación literal ----------------------------------------------------


def test_literal_normaliza_solo_espacios_y_particion():
    comprobar = herramienta("comprobar")
    assert not comprobar.aparece("componente", "el comp onente del equipo")
    assert comprobar.aparece("informático", "un sistema infor-\n   mático completo")
    assert comprobar.aparece("Alan Turing y Ada", "-   Alan  Turing\n    y   Ada Lovelace")
    # la viñeta del PDF no forma parte del texto, y un guion de verdad se conserva
    assert comprobar.aparece("La válvula de vacío.", "    x La válvula de vacío.")
    assert comprobar.aparece("pascal-meca", "la rueda de pascal-\nmeca")
    assert not comprobar.aparece("pascalmeca otro", "la rueda de pascal otro")


def elemento(texto: str, pagina: int | None = 1, norma: str = "boe-a-2022-1") -> Elemento:
    return Elemento(
        codigo="EST.BACH.DESC.CD1",
        tipo="descriptor",
        texto=texto,
        procedencia=Procedencia(norma=norma, ubicacion="anexo I", pagina=pagina),
        padre=None,
    )


def test_comprobar_informa_texto_recortado():
    comprobar = herramienta("comprobar")
    pagina = "Usa herramientas digitales de forma segura. Protege sus datos personales."
    documentos = {"boe-a-2022-1": comprobar.Documento(paginas={1: pagina})}
    assert comprobar.comprobar_elemento(elemento(pagina), documentos, {}) == []
    # falta la última frase: es un trozo literal de la página, pero la unidad no acaba ahí
    informe = comprobar.comprobar_elemento(
        elemento("Usa herramientas digitales de forma segura."), documentos, {}
    )
    assert [d.tipo for d in informe] == ["TEXTO"]
    assert str(informe[0]).startswith("TEXTO EST.BACH.DESC.CD1")
    # también si la frase que falta está en la línea siguiente
    dos_lineas = {
        "boe-a-2022-1": comprobar.Documento(paginas={1: "Usa herramientas.\nprotege datos."})
    }
    assert [
        d.tipo for d in comprobar.comprobar_elemento(elemento("Usa herramientas."), dos_lineas, {})
    ] == ["TEXTO"]


def test_comprobar_acepta_sustitucion_declarada():
    comprobar = herramienta("comprobar")
    documentos = {"boe-a-2022-1": comprobar.Documento(paginas={1: "Programa en phyton y Java."})}
    sin_declarar = comprobar.comprobar_elemento(
        elemento("Programa en Python y Java."), documentos, {"boe-a-2022-1": {}}
    )
    assert [d.tipo for d in sin_declarar] == ["TEXTO"]
    declarada = {"boe-a-2022-1": {"sustituciones": [["phyton", "Python"]]}}
    assert (
        comprobar.comprobar_elemento(elemento("Programa en Python y Java."), documentos, declarada)
        == []
    )
    # cualquier otra diferencia sigue siendo TEXTO
    otra = comprobar.comprobar_elemento(
        elemento("Programa en Python y Kotlin."), documentos, declarada
    )
    assert [d.tipo for d in otra] == ["TEXTO"]


def test_comprobar_pagina_y_fuentes_que_faltan():
    comprobar = herramienta("comprobar")
    documentos = {"boe-a-2022-1": comprobar.Documento(paginas={1: "Texto de la página uno."})}
    fuera = comprobar.comprobar_elemento(elemento("Texto.", pagina=7), documentos, {})
    assert [d.tipo for d in fuera] == ["PROCEDENCIA"]
    sin_cache = comprobar.comprobar_elemento(elemento("Texto.", norma="boe-a-2022-2"), {}, {})
    assert [d.tipo for d in sin_cache] == ["SIN_FUENTE"]


def test_comprobar_recuentos_falta_y_sobra(tmp_path):
    comprobar = herramienta("comprobar")
    escribir_datos(tmp_path, extraer())
    limpiar_cache()
    ficha = cargar(raiz=tmp_path).fichas[MATERIA]
    de_norma = {BOCM: {"recuentos": {MATERIA: {"competencias": 5, "criterios": 9, "bloques": 5}}}}
    informe = comprobar.comprobar_recuentos(ficha, de_norma)
    assert sorted((d.tipo, d.donde) for d in informe) == [
        ("FALTA", f"{MATERIA} competencias"),
        ("SOBRA", f"{MATERIA} criterios"),
    ]


def test_comprobar_contra_el_fragmento_real(tmp_path):
    """Lo que extrae el extractor aparece literal, y completo, en las páginas del fragmento."""
    comprobar = herramienta("comprobar")
    escribir_datos(tmp_path, extraer())
    limpiar_cache()
    indice = cargar(raiz=tmp_path)
    paginas = herramienta("comun").paginas_limpias(FRAGMENTO.read_text(encoding="utf-8"))
    assert sorted(paginas) == [114, 115, 116, 117, 118]
    documentos = {BOCM: comprobar.Documento(paginas=paginas)}
    informe = []
    for e in indice.fichas[MATERIA].elementos:
        informe += comprobar.comprobar_elemento(e, documentos, {})
    assert informe == []


# --- lector de fuentes.toml ---------------------------------------------------

FUENTES_TOML = """
[[norma]]
id = "bocm-20230531-18"
rango = "orden"
numero = "1736/2023"
fecha = 2023-05-31
titulo = "Orden de prueba"
boletin = "BOCM"
url_pdf = "https://www.bocm.es/boletin/ejemplo.pdf"
sha256 = "{A}"
estado = "vigente"
correcciones = ["bocm-20240101-9#anexo-iv"]
recuentos = { "MAD.BACH.CCOMP.1" = { competencias = 4, criterios = 10 } }
sustituciones = [["phyton", "Python"]]

[[norma]]
id = "boe-a-2022-4975"
rango = "real_decreto"
numero = "243/2022"
fecha = 2022-04-05
titulo = "Real decreto de prueba"
boletin = "BOE"
url_pdf = "https://www.boe.es/boe/dias/2022/04/06/pdfs/BOE-A-2022-4975.pdf"
url_api = "https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/BOE-A-2022-4975"
sha256 = "{B}"
estado = "vigente"
""".replace("{A}", "a" * 64).replace("{B}", "b" * 64)


def test_lector_de_fuentes_toml(tmp_path):
    comun = herramienta("comun")
    ruta = tmp_path / "fuentes.toml"
    ruta.write_text(FUENTES_TOML, encoding="utf-8")
    fuentes = comun.leer_fuentes(ruta)
    assert list(fuentes) == ["bocm-20230531-18", "boe-a-2022-4975"]
    orden = fuentes["bocm-20230531-18"]
    assert orden["fecha"] == "2023-05-31"
    assert orden["correcciones"] == ["bocm-20240101-9#anexo-iv"]
    assert orden["recuentos"] == {"MAD.BACH.CCOMP.1": {"competencias": 4, "criterios": 10}}
    assert orden["sustituciones"] == [["phyton", "Python"]]
    assert orden["url_api"] is None and orden["modifica"] == [] and orden["desde"] is None
    assert fuentes["boe-a-2022-4975"]["recuentos"] == {}
    solo_mantenedor = comun.norma_para_el_paquete(orden)
    assert "recuentos" not in solo_mantenedor and "sustituciones" not in solo_mantenedor

    for roto, motivo in (
        (
            FUENTES_TOML.replace('estado = "vigente"\ncorr', 'estado = "vigente"\nextra = 1\ncorr'),
            "extra",
        ),
        (FUENTES_TOML.replace("competencias = 4", "plantillas = 4"), "plantillas"),
        (FUENTES_TOML.replace('["phyton", "Python"]', '["phyton"]'), "sustituciones"),
        (FUENTES_TOML.replace('titulo = "Orden de prueba"\n', ""), "titulo"),
    ):
        ruta.write_text(roto, encoding="utf-8")
        with pytest.raises(ValueError, match=motivo):
            comun.leer_fuentes(ruta)


# --- descarga: sin red --------------------------------------------------------


def test_descargar_no_sobrescribe_si_el_sha256_no_coincide(tmp_path):
    descargar = herramienta("descargar")
    contenido = b"%PDF-1.7 de prueba"
    bueno = hashlib.sha256(contenido).hexdigest()
    registro = {
        "id": "bocm-20230531-18",
        "url_pdf": "https://www.bocm.es/ejemplo.pdf",
        "url_api": None,
        "sha256": bueno,
    }
    llamadas: list[str] = []

    def obtener(url: str, cabeceras: dict[str, str]) -> bytes:
        llamadas.append(url)
        return contenido

    descargar.descargar({registro["id"]: registro}, tmp_path, obtener)
    destino = tmp_path / "bocm-20230531-18.pdf"
    assert destino.read_bytes() == contenido

    # ya está y coincide: no vuelve a bajarlo
    descargar.descargar({registro["id"]: registro}, tmp_path, obtener)
    assert len(llamadas) == 1

    # la fuente cambió: se para con un error y el fichero de la caché queda como estaba
    cambiado = dict(registro, sha256="0" * 64)
    with pytest.raises(descargar.ErrorDescarga, match="sha256"):
        descargar.descargar({registro["id"]: cambiado}, tmp_path, obtener)
    assert destino.read_bytes() == contenido


# --- descriptores del BOE (XML de prueba con la estructura de la API) ----------

XML_DESCRIPTORES = """<?xml version="1.0" encoding="utf-8"?>
<texto>
<bloque id="ai" tipo="anexo"><version id_norma="BOE-A-2022-4975" fecha_vigencia="20220406">
<p class="titulo">ANEXO I</p>
<p class="parrafo">Perfil de salida del alumnado</p>
<p class="parrafo">CCL1. Se expresa de forma oral,
 escrita o signada con coherencia.</p>
<p class="parrafo">CCL1. Se expresa con fluidez y precisión en el Bachillerato.</p>
<table><tr><td><p class="parrafo">STEM4.</p></td></tr></table>
<p class="parrafo">CCEC4.1. Experimenta de forma creativa con diversos medios.</p>
<p class="parrafo">Otro párrafo cualquiera.</p>
</version></bloque>
</texto>
"""


def test_descriptores_desde_el_xml_del_boe():
    modulo = herramienta("extraer_descriptores")
    descriptores = modulo.analizar_descriptores(XML_DESCRIPTORES)
    assert list(descriptores) == ["CCL1", "CCEC4.1"]
    assert descriptores["CCL1"] == "Se expresa con fluidez y precisión en el Bachillerato."
    ficha = modulo.ficha_descriptores(
        descriptores,
        norma="boe-a-2022-4975",
        etapa="bachillerato",
        cursos_academicos=["2023-24"],
    )
    assert ficha["codigo"] == "EST.BACH.DESC"
    assert [e["codigo"] for e in ficha["elementos"]] == [
        "EST.BACH.DESC.CCL1",
        "EST.BACH.DESC.CCEC4.1",
    ]
    assert ficha["elementos"][0]["procedencia"] == {
        "norma": "boe-a-2022-4975",
        "ubicacion": "anexo I",
        "pagina": None,
    }


# --- formación profesional ----------------------------------------------------

TEXTO_MADRID = """\
                     Módulo profesional 01: Bases de datos (código: 0484)
                                Contenidos (duración 205 horas)
          Almacenamiento de la información:
          — Ficheros (planos, indexados y acceso directo, de marcas, entre otros).
          — Bases de Datos (BD). Conceptos, usos y tipos según el modelo de datos, la ubica-
              ción de la información.
          — Gestión de seguridad:
               Usuarios.
               Roles.
          Realización de consultas:
          — Consultas para extraer información: la sentencia SELECT.
                     Módulo profesional 02: Programación (código: 0485)
                                Contenidos (duración 270 horas)
          Otra cosa:
          — Otra.
"""

TEXTO_HORAS = """\
            Ciclo Formativo: DESARROLLO DE APLICACIONES MULTIPLATAFORMA
                                                                                Duración del   Equivalencias    Curso 1º        Curso 2º
            Código                            Denominación                         (horas)        ECTS         semanales)   semanales)
            0484     Bases de datos                                                 205             12             6
            0485     Programación                                                   270             15             8
            0486     Acceso a datos                                                 165             10                             5
                     HORAS TOTALES                                                 2000                           30             30
"""


def test_fp_contenidos_de_madrid_y_horas():
    fp = herramienta("extraer_fp")
    comun = herramienta("comun")
    contenidos = fp.analizar_contenidos_madrid(comun.lineas_de(TEXTO_MADRID), "0484")
    assert [(c["nivel"], c["texto"]) for c in contenidos] == [
        (1, "Almacenamiento de la información:"),
        (2, "Ficheros (planos, indexados y acceso directo, de marcas, entre otros)."),
        (
            2,
            "Bases de Datos (BD). Conceptos, usos y tipos según el modelo de datos, "
            "la ubicación de la información.",
        ),
        (2, "Gestión de seguridad:"),
        (3, "Usuarios."),
        (3, "Roles."),
        (1, "Realización de consultas:"),
        (2, "Consultas para extraer información: la sentencia SELECT."),
    ]
    lineas = comun.lineas_de(TEXTO_HORAS)
    ciclo = "DESARROLLO DE APLICACIONES MULTIPLATAFORMA"
    assert fp.analizar_horas_curso(lineas, ciclo=ciclo, codigo_modulo="0485")[:2] == (270, "1")
    assert fp.analizar_horas_curso(lineas, ciclo=ciclo, codigo_modulo="0486")[:2] == (165, "2")


PARRAFOS_BOE = [
    "Módulo Profesional: Bases de datos.",
    "Código: 0484",
    "Resultados de aprendizaje y criterios de evaluación.",
    "1. Reconoce los elementos de las bases de datos.",
    "Criterios de evaluación:",
    "a) Se ha analizado el papel de los sistemas gestores.",
    "b) Se han clasificado según el modelo de datos.",
    "2. Crea bases de datos.",
    "a) Se ha creado una base de datos.",
    "Duración: 205 horas.",
    "Contenidos básicos:",
    "Almacenamiento de la información.",
    "Orientaciones pedagógicas.",
    "Este módulo contiene la formación necesaria.",
    "Se relaciona con otros módulos.",
    "Módulo Profesional: Programación.",
    "Código: 0485",
]


def test_fp_resultados_criterios_y_orientaciones_del_boe():
    fp = herramienta("extraer_fp")
    modulo = fp.analizar_modulo_boe(PARRAFOS_BOE, "0484")
    assert modulo["nombre"] == "Bases de datos"
    assert [(r["numero"], r["texto"]) for r in modulo["resultados"]] == [
        ("1", "Reconoce los elementos de las bases de datos."),
        ("2", "Crea bases de datos."),
    ]
    assert [c["letra"] for c in modulo["resultados"][0]["criterios"]] == ["a", "b"]
    assert modulo["orientaciones"] == (
        "Este módulo contiene la formación necesaria. Se relaciona con otros módulos."
    )
    elementos_fp = fp.elementos_del_boe(
        modulo,
        ficha="MAD.FPGS.DAM.0484",
        norma="boe-a-2010-6954",
        ubicacion="anexo I",
        orden_inicial=2,
    )
    assert [e["codigo"] for e in elementos_fp] == [
        "MAD.FPGS.DAM.0484.RA.1",
        "MAD.FPGS.DAM.0484.RA.1.CE.a",
        "MAD.FPGS.DAM.0484.RA.1.CE.b",
        "MAD.FPGS.DAM.0484.RA.2",
        "MAD.FPGS.DAM.0484.RA.2.CE.a",
        "MAD.FPGS.DAM.0484.ORI",
    ]
    assert elementos_fp[1]["padre"] == "MAD.FPGS.DAM.0484.RA.1"
    assert elementos_fp[0]["orden"] == 2
