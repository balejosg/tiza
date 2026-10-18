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
DECRETO = "bocm-20220726-2"
CCOMP_ESO = FUENTES / "bocm-20220726-2_anexo-ii_ccomp-eso.txt"
DIG_ESO = FUENTES / "bocm-20220726-2_anexo-ii_dig-eso-4.txt"


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


def test_lomloe_subviñeta_tras_la_cabecera_de_un_bloque_no_cuelga_del_bloque_anterior():
    texto = FRAGMENTO.read_text(encoding="utf-8")
    cabecera = "               B. Los sistemas informáticos.\n"
    assert cabecera in texto
    huerfana = "                    x Subcontenido sin viñeta previa.\n"
    ficha = herramienta("extraer_lomloe").extraer_materia(
        texto.replace(cabecera, cabecera + huerfana),
        norma=BOCM,
        nombre="Ciencias de la Computación",
        sigla="CCOMP",
        etapa="bachillerato",
        curso="1",
        cursos_academicos=["2023-24", "2024-25"],
    )
    por_codigo = elementos(ficha)
    huerfano = next(
        e for e in por_codigo.values() if e["texto"] == "Subcontenido sin viñeta previa."
    )
    assert huerfano["codigo"] == f"{MATERIA}.CO.B.1"
    assert huerfano["padre"] == f"{MATERIA}.CO.B"
    # y el primer contenido real del bloque pasa a ser el segundo
    primero = next(
        e for e in por_codigo.values() if e["texto"].startswith("Elementos de un sistema")
    )
    assert primero["codigo"] == f"{MATERIA}.CO.B.2"
    assert primero["padre"] == f"{MATERIA}.CO.B"


# --- materias de ESO: título del boletín, curso con y sin marca, límite de la materia ----


def extraer_eso(fragmento: Path, sigla: str, curso: str, titulo: str, nombre: str, texto=None):
    """Extrae una materia de ESO del fragmento del Decreto 65/2022 (o de ``texto``)."""
    return herramienta("extraer_lomloe").extraer_materia(
        texto if texto is not None else fragmento.read_text(encoding="utf-8"),
        norma=DECRETO,
        nombre=nombre,
        titulo=titulo,
        sigla=sigla,
        etapa="eso",
        curso=curso,
        cursos_academicos=["2026-27"],
        anexo="anexo II",  # el fragmento no trae la cabecera del anexo
    )


def ccomp_eso(curso: str, texto=None) -> dict:
    return extraer_eso(
        CCOMP_ESO,
        "CCOMP",
        curso,
        "CIENCIAS DE LA COMPUTACIÓN",
        "Ciencias de la Computación",
        texto,
    )


def dig_eso(texto=None) -> dict:
    return extraer_eso(DIG_ESO, "DIG", "4", "DIGITALIZACIÓN", "Digitalización", texto)


def de_tipo(ficha: dict[str, dict], tipo: str) -> list[str]:
    return [e["texto"] for e in ficha.values() if e["tipo"] == tipo]


def test_lomloe_el_titulo_del_boletin_no_es_el_nombre_de_la_ficha():
    ficha = ccomp_eso("1")
    assert ficha["codigo"] == "MAD.ESO.CCOMP.1"
    assert ficha["nombre"] == "Ciencias de la Computación, primer curso"
    # sin título aparte se busca el nombre, que en el decreto está en mayúsculas
    texto = CCOMP_ESO.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="no encuentro la materia"):
        herramienta("extraer_lomloe").extraer_materia(
            texto,
            norma=DECRETO,
            nombre="Ciencias de la Computación",
            sigla="CCOMP",
            etapa="eso",
            curso="1",
            cursos_academicos=["2026-27"],
        )


def test_lomloe_la_linea_de_comandos_acepta_un_titulo_aparte(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"{DECRETO}.txt").write_text(CCOMP_ESO.read_text(encoding="utf-8"), "utf-8")
    argumentos = ["--norma", DECRETO, "--materia", "CCOMP", "--curso", "2", "--etapa", "eso"]
    argumentos += ["--nombre", "Ciencias de la Computación", "--cursos-academicos", "2026-27"]
    argumentos += ["--cache", str(cache), "--salida", str(tmp_path / "datos")]
    argumentos += ["--titulo", "CIENCIAS DE LA COMPUTACIÓN", "--anexo", "anexo II"]
    assert herramienta("extraer_lomloe").main(argumentos) == 0
    ficha = json.loads((tmp_path / "datos" / "fichas" / "MAD.ESO.CCOMP.2.json").read_text("utf-8"))
    assert ficha["nombre"] == "Ciencias de la Computación, segundo curso"


def test_lomloe_eso_cada_curso_lleva_sus_criterios_y_contenidos_y_las_competencias_comunes():
    primero = elementos(ccomp_eso("1"))
    segundo = elementos(ccomp_eso("2"))
    for ficha, curso in ((primero, "1"), (segundo, "2")):
        competencias = [c for c, e in ficha.items() if e["tipo"] == "competencia_especifica"]
        assert competencias == [f"MAD.ESO.CCOMP.{curso}.CE.{n}" for n in (1, 2, 3, 4)]
    # las competencias son las mismas y los descriptores son los de la ESO
    assert primero["MAD.ESO.CCOMP.1.CE.1"]["texto"] == segundo["MAD.ESO.CCOMP.2.CE.1"]["texto"]
    assert primero["MAD.ESO.CCOMP.1.CE.2"]["relaciones"]["descriptores"] == [
        f"EST.ESO.DESC.{c}" for c in ("CP2", "STEM1", "STEM2", "STEM3", "CD5", "CPSAA5")
    ]
    # criterios: 3+5+6+3 en 1.º y 7+4+2+2 en 2.º; sin los del otro curso
    assert len(de_tipo(primero, "criterio")) == 17 and len(de_tipo(segundo, "criterio")) == 15
    assert primero["MAD.ESO.CCOMP.1.CR.1.1"]["texto"].startswith("Comprender qué es un algoritmo")
    assert segundo["MAD.ESO.CCOMP.2.CR.1.1"]["texto"].startswith("Entender el funcionamiento")
    assert primero["MAD.ESO.CCOMP.1.CR.3.4"]["procedencia"]["ubicacion"] == (
        "anexo II, 1.º, criterio 3.4"
    )
    # el criterio que cruza una página sale entero y con la página en la que empieza
    cruza = segundo["MAD.ESO.CCOMP.2.CR.3.2"]
    assert cruza["texto"].endswith("o los servicios de almacenamiento en la nube.")
    assert cruza["procedencia"]["pagina"] == 439
    # contenidos: las viñetas «−» y «–» son contenidos y las «x», subcontenidos
    algoritmos = primero["MAD.ESO.CCOMP.1.CO.A.1"]
    assert algoritmos["texto"] == "Algoritmos:" and algoritmos["padre"] == "MAD.ESO.CCOMP.1.CO.A"
    assert primero["MAD.ESO.CCOMP.1.CO.A.1.1"]["texto"] == "Definición y ejemplos sencillos."
    assert primero["MAD.ESO.CCOMP.1.CO.A.2"]["texto"].startswith("Detección y corrección")
    bloques = de_tipo(primero, "bloque_contenidos")
    assert bloques == ["Pensamiento computacional.", "Programación.", "Computadores.", "Redes."]
    assert de_tipo(segundo, "bloque_contenidos") == bloques
    assert segundo["MAD.ESO.CCOMP.2.CO.A.1"]["texto"] == "Algoritmos de ordenación y de búsqueda."
    for ficha in (primero, segundo):
        assert not any(e["texto"].startswith(("−", "–", "x ")) for e in ficha.values())
    # el último contenido del curso es el último de la materia, no el título que sigue
    assert segundo["MAD.ESO.CCOMP.2.CO.D.2.4"]["texto"] == (
        "Software para la protección frente a ciberataques."
    )
    assert not any("CULTURA" in e["texto"] for e in segundo.values())


def test_lomloe_materia_de_un_solo_curso_sin_marca_de_curso():
    ficha = elementos(dig_eso())
    assert ficha["MAD.ESO.DIG.4.CE.1"]["texto"].startswith(
        "Identificar y resolver problemas técnicos"
    )
    assert ficha["MAD.ESO.DIG.4.CE.1"]["relaciones"]["descriptores"] == [
        f"EST.ESO.DESC.{c}" for c in ("STEM1", "STEM2", "CD4", "CD5", "CPSAA1", "CPSAA5", "CE3")
    ]
    # los criterios llevan un punto tras el número («1.1.»)
    criterios = [c for c, e in ficha.items() if e["tipo"] == "criterio"]
    assert len(criterios) == 3 + 4 + 4 + 5
    assert ficha["MAD.ESO.DIG.4.CR.1.1"]["texto"].startswith("Conectar dispositivos y gestionar")
    assert ficha["MAD.ESO.DIG.4.CR.4.5"]["padre"] == "MAD.ESO.DIG.4.CE.4"
    assert ficha["MAD.ESO.DIG.4.CR.4.4"]["texto"].endswith(
        "accesibilidad, sostenibilidad e impacto."
    )
    # las viñetas «•» (con o sin espacio) cuelgan del contenido «–» que las precede
    edicion = ficha["MAD.ESO.DIG.4.CO.B.2"]
    assert edicion["texto"] == "Edición y creación de contenidos:"
    hijos = [e["texto"] for e in ficha.values() if e.get("padre") == edicion["codigo"]]
    assert hijos[0] == "Aplicaciones de productividad."
    assert hijos[-1] == "Realidad virtual, aumentada y mixta."
    assert len(hijos) == 4
    bloques = [e["texto"] for e in ficha.values() if e["tipo"] == "bloque_contenidos"]
    assert bloques[0] == "Dispositivos digitales, sistemas operativos y de comunicación."
    assert bloques[-1] == "Ciudadanía digital crítica."
    assert not any(e["texto"].startswith(("•", "–")) for e in ficha.values())


def test_lomloe_la_busqueda_se_queda_dentro_de_la_materia():
    ajena = (
        "    4º ESO.\n    Criterios de evaluación.\n    Competencia específica 1.\n"
        "    1.1. Criterio de otra materia.\n    Contenidos.\n    A. Bloque de otra materia.\n"
    )
    texto = DIG_ESO.read_text(encoding="utf-8")
    # la materia siguiente (ECONOMÍA Y EMPRENDIMIENTO) tiene marca de curso y la de DIG no
    ficha = elementos(dig_eso(texto + ajena))
    assert "MAD.ESO.DIG.4.CR.4.5" in ficha
    assert not any("de otra materia" in e["texto"] for e in ficha.values())
    # y un curso que la materia no tiene no se busca en la siguiente
    texto = CCOMP_ESO.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="no encuentro el apartado del curso 3"):
        ccomp_eso("3", texto + ajena.replace("4º", "3º"))


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


def _tipos(informe) -> list[str]:
    return [d.tipo for d in informe]


def test_comprobar_no_da_texto_en_filas_de_tabla():
    comprobar = herramienta("comprobar")
    tabla = (
        "0484     Bases de datos                                  205     12     6\n"
        "0492     Proyecto intermodular de desarrollo de aplicaciones     50     5\n"
        "         multiplataforma\n"
        "         HORAS TOTALES      2000"
    )
    documentos = {"boe-a-2022-1": comprobar.Documento(paginas={1: tabla})}

    def modulo(texto: str) -> Elemento:
        return Elemento(
            codigo="MAD.DAM.0484",
            tipo="modulo",
            texto=texto,
            procedencia=Procedencia(norma="boe-a-2022-1", ubicacion="anexo II", pagina=1),
            padre=None,
            datos={"horas": 205, "curso": "1"},
        )

    assert comprobar.comprobar_elemento(modulo("Bases de datos"), documentos, {}) == []
    # el nombre que ocupa dos líneas de la tabla, con las cifras de en medio
    largo = "Proyecto intermodular de desarrollo de aplicaciones multiplataforma"
    assert comprobar.comprobar_elemento(modulo(largo), documentos, {}) == []
    # lo que no está en la tabla sigue siendo TEXTO
    assert _tipos(comprobar.comprobar_elemento(modulo("Bases de dato"), documentos, {})) == [
        "TEXTO"
    ]
    assert _tipos(comprobar.comprobar_elemento(modulo("Bases de otros datos"), documentos, {})) == [
        "TEXTO"
    ]
    # y el borde de unidad sigue valiendo para un texto que no sale de una tabla
    assert _tipos(comprobar.comprobar_elemento(elemento("Bases de datos"), documentos, {})) == [
        "TEXTO"
    ]


def test_comprobar_detecta_nombres_truncados_en_filas_de_tabla():
    comprobar = herramienta("comprobar")
    fila = "0484     Bases de datos avanzadas     205     12     6"
    assert not comprobar.aparece("Bases de datos", fila, completo=True, tabla=True)
    assert comprobar.aparece("Bases de datos avanzadas", fila, completo=True, tabla=True)
    # cifras entre palabras de una misma línea: no es el nombre
    assert not comprobar.aparece("Bases de datos", "0484 Bases 2 de datos 205 6", tabla=True)
    # el recorte justo en el salto de línea de un nombre partido no se puede detectar
    partido = "0492 Proyecto intermodular de aplicaciones   50   5\nmultiplataforma"
    assert comprobar.aparece("Proyecto intermodular de aplicaciones", partido, tabla=True)
    assert comprobar.aparece(
        "Proyecto intermodular de aplicaciones multiplataforma", partido, tabla=True
    )


def test_comprobar_viñeta_en_minuscula_es_otra_unidad():
    comprobar = herramienta("comprobar")
    pagina = (
        "    - La válvula de vacío.\n"
        "    - el transistor y el chip.\n"
        "    x la inteligencia artificial.\n"
        "    x Los sensores.\n"
        "    continuación de una frase\n"
        "    en minúscula."
    )
    documentos = {"boe-a-2022-1": comprobar.Documento(paginas={1: pagina})}
    for texto in (
        "La válvula de vacío.",
        "el transistor y el chip.",
        "la inteligencia artificial.",
    ):
        assert comprobar.comprobar_elemento(elemento(texto), documentos, {}) == [], texto
    # una línea que sigue sin viñeta y en minúscula continúa la frase: falta parte
    assert _tipos(comprobar.comprobar_elemento(elemento("Los sensores."), documentos, {})) == [
        "TEXTO"
    ]
    # y un trozo de una viñeta sigue sin valer
    assert _tipos(comprobar.comprobar_elemento(elemento("el transistor"), documentos, {})) == [
        "TEXTO"
    ]


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


# --- descriptores del BOE (tablas de dos columnas del anexo I) ----------------

XML_ESO = FUENTES / "boe-a-2022-4975_anexo-i_descriptores-cp.xml"
XML_BACH = FUENTES / "boe-a-2022-5521_anexo-i_descriptores-cpsaa.xml"


def test_descriptores_son_los_de_la_columna_de_la_etapa():
    modulo = herramienta("extraer_descriptores")
    eso = modulo.analizar_descriptores(XML_ESO.read_text(encoding="utf-8"), "eso")
    assert list(eso) == ["CP1", "CP2", "CP3"]
    # la columna de la derecha («enseñanza básica»), no la de la Educación Primaria
    assert eso["CP1"].startswith("Usa eficazmente una o más lenguas, además de la lengua")
    assert not eso["CP1"].startswith("CP1")
    assert eso["CP2"].startswith("A partir de sus experiencias, realiza transferencias")

    # el mismo texto de «enseñanza básica» es la columna de la izquierda en Bachillerato
    bach = modulo.analizar_descriptores(XML_BACH.read_text(encoding="utf-8"), "bachillerato")
    assert not any(texto.startswith("Regula y expresa") for texto in bach.values())


def test_descriptores_con_punto_interior_y_varios_por_celda():
    modulo = herramienta("extraer_descriptores")
    bach = modulo.analizar_descriptores(XML_BACH.read_text(encoding="utf-8"), "bachillerato")
    assert list(bach) == [
        "CPSAA1.1",
        "CPSAA1.2",
        "CPSAA2",
        "CPSAA3.1",
        "CPSAA3.2",
        "CPSAA4",
        "CPSAA5",
    ]
    assert bach["CPSAA1.1"].startswith("Fortalece el optimismo, la resiliencia")
    assert bach["CPSAA1.2"].startswith("Desarrolla una personalidad autónoma")
    assert bach["CPSAA2"].startswith("Adopta de forma autónoma un estilo de vida sostenible")


def test_descriptores_ficha_con_procedencia_del_anexo_i():
    modulo = herramienta("extraer_descriptores")
    descriptores = modulo.analizar_descriptores(
        XML_BACH.read_text(encoding="utf-8"), "bachillerato"
    )
    ficha = modulo.ficha_descriptores(
        descriptores,
        norma="boe-a-2022-5521",
        etapa="bachillerato",
        cursos_academicos=["2026-27"],
    )
    assert ficha["codigo"] == "EST.BACH.DESC"
    assert [e["codigo"] for e in ficha["elementos"]][:2] == [
        "EST.BACH.DESC.CPSAA1.1",
        "EST.BACH.DESC.CPSAA1.2",
    ]
    assert ficha["elementos"][0]["procedencia"] == {
        "norma": "boe-a-2022-5521",
        "ubicacion": "anexo I",
        "pagina": None,
    }


def test_descriptores_rechazan_lo_que_no_cuadra():
    modulo = herramienta("extraer_descriptores")
    eso = XML_ESO.read_text(encoding="utf-8")
    # una columna que no es la de la etapa
    with pytest.raises(ValueError, match="cabecera"):
        modulo.analizar_descriptores(eso, "bachillerato")
    # una celda que no empieza por un código
    estropeado = eso.replace("CP1. Usa eficazmente", "Usa eficazmente", 1)
    with pytest.raises(ValueError, match="código"):
        modulo.analizar_descriptores(estropeado, "eso")
    # un código repetido
    repetido = eso.replace(
        "CP2. A partir de sus experiencias, realiza", "CP1. A partir, realiza", 1
    )
    with pytest.raises(ValueError, match="repetido"):
        modulo.analizar_descriptores(repetido, "eso")


def test_comprobar_busca_los_descriptores_en_las_celdas_del_xml(tmp_path):
    modulo = herramienta("extraer_descriptores")
    comprobar = herramienta("comprobar")
    for norma, fragmento, etapa in (
        ("boe-a-2022-4975", XML_ESO, "eso"),
        ("boe-a-2022-5521", XML_BACH, "bachillerato"),
    ):
        xml = fragmento.read_text(encoding="utf-8")
        (tmp_path / f"{norma}.xml").write_text(xml, encoding="utf-8")
        documento = comprobar.cargar_documentos(tmp_path, [norma])[norma]
        # lo extraído de una celda sin <p> o de una con varios <p> aparece literal y completo
        for texto in modulo.analizar_descriptores(xml, etapa).values():
            assert comprobar.aparece(texto, documento.xml, completo=True)
        # y un trozo recortado no
        assert not comprobar.aparece("Usa eficazmente una o más", documento.xml, completo=True)


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
        ficha="MAD.DAM.0484",
        norma="boe-a-2010-6954",
        ubicacion="anexo I",
        orden_inicial=2,
    )
    assert [e["codigo"] for e in elementos_fp] == [
        "MAD.DAM.0484.RA.1",
        "MAD.DAM.0484.RA.1.a",
        "MAD.DAM.0484.RA.1.b",
        "MAD.DAM.0484.RA.2",
        "MAD.DAM.0484.RA.2.a",
        "MAD.DAM.0484.ORI",
    ]
    assert elementos_fp[1]["padre"] == "MAD.DAM.0484.RA.1"
    assert elementos_fp[0]["padre"] == "MAD.DAM.0484"  # la raíz es el módulo
    assert elementos_fp[0]["orden"] == 2


def _normas_fp(raiz: Path) -> None:
    (raiz / "normas").mkdir()
    (raiz / "fichas").mkdir()
    for id_, numero, boletin, url in (
        ("boe-a-2010-6954", "450/2010", "BOE", "https://www.boe.es/ejemplo.pdf"),
        ("bocm-20110113-3", "3/2011", "BOCM", "https://www.bocm.es/ejemplo.pdf"),
        ("bocm-20240904-103", "103/2024", "BOCM", "https://www.bocm.es/otro.pdf"),
    ):
        norma = {
            "id": id_,
            "rango": "real_decreto" if boletin == "BOE" else "decreto",
            "numero": numero,
            "fecha": "2011-01-13",
            "titulo": f"Norma de prueba {numero}",
            "boletin": boletin,
            "url_pdf": url,
            "sha256": "0" * 64,
            "estado": "vigente",
            "revisada": "2026-10-17",
        }
        (raiz / "normas" / f"{id_}.json").write_text(json.dumps(norma), encoding="utf-8")


def test_fp_codigos_segun_el_plan_y_el_cargador_los_acepta(tmp_path):
    fp = herramienta("extraer_fp")
    comun = herramienta("comun")
    ficha = "MAD.DAM.0484"
    modulo = fp.analizar_modulo_boe(PARRAFOS_BOE, "0484")
    contenidos = fp.analizar_contenidos_madrid(comun.lineas_de(TEXTO_MADRID), "0484")
    elementos_ficha = [
        fp.elemento_modulo(
            "Bases de datos",
            205,
            "1",
            ficha=ficha,
            norma="bocm-20240904-103",
            ubicacion="anexo II",
            pagina=3,
        )
    ]
    elementos_ficha += fp.elementos_del_boe(
        modulo,
        ficha=ficha,
        norma="boe-a-2010-6954",
        ubicacion="anexo I",
        orden_inicial=2,
    )
    elementos_ficha += fp.elementos_de_contenidos(
        contenidos,
        ficha=ficha,
        norma="bocm-20110113-3",
        ubicacion="anexo I",
        orden_inicial=len(elementos_ficha) + 1,
    )
    assert elementos_ficha[0]["codigo"] == ficha and elementos_ficha[0]["tipo"] == "modulo"
    contenidos_madrid = [e for e in elementos_ficha if e["tipo"] == "contenido"]
    assert [e["codigo"] for e in contenidos_madrid][:4] == [
        f"{ficha}.CO.1",
        f"{ficha}.CO.1.1",
        f"{ficha}.CO.1.2",
        f"{ficha}.CO.1.3",
    ]
    assert contenidos_madrid[0]["padre"] == ficha
    assert contenidos_madrid[1]["padre"] == f"{ficha}.CO.1"
    assert not any(e["tipo"] == "contenido_basico" for e in elementos_ficha)
    assert [e["tipo"] for e in elementos_ficha if e["codigo"].endswith(".RA.1.a")] == [
        "criterio_fp"
    ]

    _normas_fp(tmp_path)
    fichero = {
        "codigo": ficha,
        "nombre": "Bases de datos",
        "etapa": "fp_gs",
        "curso": None,
        "cursos_academicos": ["2026-27"],
        "normas": ["boe-a-2010-6954", "bocm-20110113-3", "bocm-20240904-103"],
        "elementos": elementos_ficha,
    }
    herramienta("extraer_lomloe").escribir_ficha(fichero, tmp_path)
    limpiar_cache()
    cargada = cargar(raiz=tmp_path).fichas[ficha]
    assert len(cargada.elementos) == len(elementos_ficha)

    # los contenidos de Madrid y los básicos estatales se cuentan por separado
    comprobar = herramienta("comprobar")
    hay = len(contenidos_madrid)
    esperado = {
        "bocm-20110113-3": {"recuentos": {ficha: {"contenidos": hay, "contenidos_basicos": 0}}}
    }
    assert comprobar.comprobar_recuentos(cargada, esperado) == []
    esperado = {"bocm-20110113-3": {"recuentos": {ficha: {"contenidos_basicos": hay}}}}
    assert _tipos(comprobar.comprobar_recuentos(cargada, esperado)) == ["FALTA"]


# --- normas del paquete desde fuentes.toml --------------------------------------

FUENTES_MINIMAS = """\
[[norma]]
id = "bocm-20250101-1"
rango = "decreto"
numero = "27/2025"
fecha = 2025-01-01
titulo = "Decreto de prueba"
boletin = "BOCM"
url_pdf = "https://www.bocm.es/boletin/ejemplo.pdf"
sha256 = "1111111111111111111111111111111111111111111111111111111111111111"
correcciones = ["bocm-20250201-2"]
estado = "vigente"
citas = ["Decreto 21/2025"]
sustituciones = [["Phyton", "Python"]]

[norma.recuentos."MAD.X"]
criterios = 3

[[norma]]
id = "bocm-20250201-2"
rango = "correccion"
numero = "del Decreto 27/2025"
fecha = "2025-02-01"
titulo = "Corrección de errores del Decreto de prueba"
boletin = "BOCM"
url_pdf = "https://www.bocm.es/boletin/ejemplo-correccion.pdf"
sha256 = "2222222222222222222222222222222222222222222222222222222222222222"
estado = "vigente"
"""


def test_normas_del_paquete_desde_fuentes(tmp_path):
    normas = herramienta("normas")
    fuentes = tmp_path / "fuentes.toml"
    fuentes.write_text(FUENTES_MINIMAS, encoding="utf-8")
    salida = tmp_path / "datos"

    argumentos = ["--revisada", "2026-10-18", "--fuentes", str(fuentes), "--salida", str(salida)]
    assert normas.main(argumentos) == 0

    ficheros = sorted(p.name for p in (salida / "normas").iterdir())
    assert ficheros == ["bocm-20250101-1.json", "bocm-20250201-2.json"]
    texto = (salida / "normas" / "bocm-20250101-1.json").read_text(encoding="utf-8")
    assert texto.endswith("}\n")
    norma = json.loads(texto)
    # lo que es solo del mantenedor no llega al paquete; sí la fecha de la revisión
    assert "recuentos" not in norma and "sustituciones" not in norma
    assert norma["revisada"] == "2026-10-18"
    assert norma["fecha"] == "2025-01-01"
    assert norma["citas"] == ["Decreto 21/2025"]
    assert "url_api" not in norma and "derogada_por" not in norma
    assert list(norma)[:4] == ["id", "rango", "numero", "fecha"]
    # el cargador del paquete los acepta tal cual (sin fichas, pero con su carpeta)
    (salida / "fichas").mkdir()
    limpiar_cache()
    indice = cargar(salida)
    assert indice.normas["bocm-20250201-2"].rango == "correccion"
    assert indice.normas["bocm-20250101-1"].correcciones == ("bocm-20250201-2",)


def test_normas_exigen_una_fecha_de_revision_valida(tmp_path):
    normas = herramienta("normas")
    fuentes = tmp_path / "fuentes.toml"
    fuentes.write_text(FUENTES_MINIMAS, encoding="utf-8")
    argumentos = ["--revisada", "18/10/2026", "--fuentes", str(fuentes), "--salida", str(tmp_path)]
    with pytest.raises(SystemExit):
        normas.main(argumentos)
