"""Herramienta del mantenedor (`herramientas/normativa/`): análisis de texto, sin red ni pdftotext.

Los fragmentos de boletín de `herramientas/normativa/fuentes/` son texto ya extraído con
`pdftotext -layout`; las funciones de análisis trabajan sobre ese texto.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from tiza.normativa import Elemento, Ficha, Procedencia, cargar, limpiar_cache

SINTETICOS = Path(__file__).parent / "datos_sinteticos"

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


def extraer_eso(
    fragmento: Path, sigla: str, curso: str, titulo: str, nombre: str, texto=None, **cambios
):
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
        **cambios,
    )


def ccomp_eso(curso: str, texto=None, **cambios) -> dict:
    return extraer_eso(
        CCOMP_ESO,
        "CCOMP",
        curso,
        "CIENCIAS DE LA COMPUTACIÓN",
        "Ciencias de la Computación",
        texto,
        **cambios,
    )


def dig_eso(texto=None, **cambios) -> dict:
    cambios.setdefault("curso_unico", True)
    return extraer_eso(DIG_ESO, "DIG", "4", "DIGITALIZACIÓN", "Digitalización", texto, **cambios)


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


def test_lomloe_una_materia_sin_marcas_exige_declarar_que_es_de_un_solo_curso():
    with pytest.raises(ValueError, match="no marca el curso.*--curso-unico"):
        dig_eso(curso_unico=False)


def test_lomloe_curso_unico_no_vale_si_hay_varios_bloques_de_criterios():
    texto = DIG_ESO.read_text(encoding="utf-8")
    segundo = "    Criterios de evaluación.\n    Competencia específica 1.\n    1.1. Otro.\n\n"
    siguiente = "ECONOMÍA Y EMPRENDIMIENTO"  # el bloque cae dentro de la materia, antes del título
    antes, despues = texto.split(siguiente)[0], siguiente + texto.split(siguiente)[1]
    antes = antes[: antes.rindex("\n")]  # sin la sangría del título
    with pytest.raises(ValueError, match="varios bloques de criterios y ninguna marca de curso"):
        dig_eso(antes + "\n" + segundo + "    " + despues)
    # y tampoco con las marcas de un curso reales: o hay marcas o es de un solo curso
    with pytest.raises(ValueError, match="marca los cursos"):
        ccomp_eso("1", curso_unico=True)


def test_lomloe_el_nombre_con_ordinal_romano_no_lleva_sufijo_de_curso():
    ficha = extraer(nombre="Ciencias de la Computación I", titulo="Ciencias de la Computación")
    assert ficha["nombre"] == "Ciencias de la Computación I"
    # el sufijo depende solo del nombre, no del curso (el fragmento solo tiene el 1.º)
    ficha = extraer(nombre="Ciencias de la Computación II", titulo="Ciencias de la Computación")
    assert ficha["nombre"] == "Ciencias de la Computación II"
    # sin ordinal romano se mantiene el sufijo
    assert extraer()["nombre"] == "Ciencias de la Computación, primer curso"


def test_lomloe_una_linea_corta_en_mayusculas_no_cierra_la_materia():
    texto = DIG_ESO.read_text(encoding="utf-8")
    parada = "    Esta competencia específica se conecta"
    assert parada in texto
    # «A, B, C, D» tiene 10 caracteres pero solo 4 letras: no es el título de otra materia
    ficha = elementos(dig_eso(texto.replace(parada, "    A, B, C, D\n" + parada, 1)))
    assert "MAD.ESO.DIG.4.CR.4.5" in ficha


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


def test_comprobar_la_comilla_de_cierre_de_la_cita_no_es_parte_de_la_unidad():
    comprobar = herramienta("comprobar")
    pagina = (
        "    y) Participar de forma activa en la vida social.»\n    Seis. Se modifica el anexo."
    )
    assert comprobar.aparece("Participar de forma activa en la vida social.", pagina, completo=True)
    # pero lo que falta de la frase sigue siendo TEXTO
    assert not comprobar.aparece("Participar de forma activa.", pagina, completo=True)


def test_comprobar_la_letra_enie_abre_otra_unidad_como_cualquier_otra():
    comprobar = herramienta("comprobar")
    pagina = (
        "    n) Desarrollar aplicaciones multiproceso.\n"
        "    ñ) Desarrollar aplicaciones capaces de ofrecer servicios en red.\n"
        "    o) Participar en la implantación.\n"
    )
    assert comprobar.aparece("Desarrollar aplicaciones multiproceso.", pagina, completo=True)
    assert comprobar.aparece(
        "Desarrollar aplicaciones capaces de ofrecer servicios en red.", pagina, completo=True
    )
    # un texto cortado antes de la «ñ)» sigue sin valer
    assert not comprobar.aparece("Desarrollar aplicaciones", pagina, completo=True)


def test_comprobar_viñetas_del_boe_el_signo_menos_y_el_glifo_de_apartado():
    comprobar = herramienta("comprobar")
    # el texto guardado de un párrafo con viñetas no lleva las viñetas del boletín
    pagina = (
        "    Las líneas de actuación versarán sobre:\n"
        "    − La identificación del hardware.\n"
        "    − El análisis de los cambios.\n"
        "\x02 Declaración.\n"
    )
    guardado = "Las líneas de actuación versarán sobre: La identificación del hardware. El análisis de los cambios."
    assert comprobar.aparece(guardado, pagina.replace("\x02 Declaración.\n", ""), completo=True)
    assert comprobar.aparece("Declaración.", pagina, completo=True)


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


def test_lector_de_fuentes_los_recuentos_admiten_cualquier_tipo_de_elemento(tmp_path):
    # los del título de FP: lo que no tiene un nombre corto sale con el del tipo tal cual
    comun = herramienta("comun")
    ruta = tmp_path / "fuentes.toml"
    toml = FUENTES_TOML.replace(
        "{ competencias = 4, criterios = 10 }",
        "{ titulo = 8, competencia_general = 1, competencia_profesional = 26, "
        "objetivo_general = 26, resultados = 9, contenidos_basicos = 72 }",
    )
    ruta.write_text(toml, encoding="utf-8")
    recuentos = comun.leer_fuentes(ruta)["bocm-20230531-18"]["recuentos"]["MAD.BACH.CCOMP.1"]
    assert recuentos["competencia_profesional"] == 26 and recuentos["titulo"] == 8


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


# --- pendientes de la revisión de la tarea 5 ------------------------------------------


def test_normas_orden_cubre_las_claves_que_pasan_al_paquete():
    comun = herramienta("comun")
    normas = herramienta("normas")
    for registro in comun.leer_fuentes().values():
        assert set(normas.ORDEN) == set(comun.norma_para_el_paquete(registro)) | {"revisada"}


def test_textos_de_xml_celdas_con_y_sin_parrafo():
    comun = herramienta("comun")
    xml = (
        "<texto><table><tr>"
        "<td><p>Con párrafo.</p></td>"
        "<td>Sin   párrafo.</td>"
        "<th><p>Otro</p><p>párrafo.</p></th>"
        "</tr></table><p>Suelto.</p></texto>"
    )
    # la celda con <p> sale una sola vez, por su párrafo; la que no lo tiene, por su texto
    assert comun.textos_de_xml(xml) == [
        "Con párrafo.",
        "Sin párrafo.",
        "Otro",
        "párrafo.",
        "Suelto.",
    ]


def test_lomloe_curso_unico_sin_bloques_de_criterios_dice_que_no_los_tiene():
    texto = DIG_ESO.read_text(encoding="utf-8")
    sin = "\n".join(l for l in texto.split("\n") if "Criterios de evaluación." not in l)
    with pytest.raises(ValueError, match="no tiene «Criterios de evaluación.»"):
        dig_eso(sin)


def test_comprobar_solo_exime_del_codigo_de_la_ficha_a_los_modulos(tmp_path):
    comprobar = herramienta("comprobar")

    def codigos(raiz):
        return [d.donde for d in comprobar.comprobar_datos(raiz, {}, {}) if d.tipo == "CODIGO"]

    # los datos reales: cada módulo se llama como su ficha y no hay discrepancias
    limpiar_cache()
    assert codigos(None) == []
    # un elemento que no es un módulo y se llama como la ficha, sí
    destino = tmp_path / "datos"
    shutil.copytree(SINTETICOS, destino)
    ruta = destino / "fichas" / "materia_ccomp_1.json"
    ficha = json.loads(ruta.read_text(encoding="utf-8"))
    ficha["elementos"].append(
        {
            "codigo": ficha["codigo"],
            "tipo": "competencia_especifica",
            "texto": "Un elemento con el código de la ficha.",
            "procedencia": {"norma": "bocm-20250101-1", "ubicacion": "anexo II", "pagina": 12},
            "orden": 99,
        }
    )
    ruta.write_text(json.dumps(ficha, ensure_ascii=False), encoding="utf-8")
    limpiar_cache()
    assert codigos(destino) == [ficha["codigo"]]
    # y el mismo código como módulo vale
    ficha["elementos"][-1].update(tipo="modulo", datos={"horas": 50, "curso": "1"})
    ruta.write_text(json.dumps(ficha, ensure_ascii=False), encoding="utf-8")
    limpiar_cache()
    assert codigos(destino) == []


# --- textos corregidos o renombrados por una norma posterior (`via`) ---------------------------


def _corregido(texto: str, pagina_via: int | None = 5, norma="corrige-1", via="original-1"):
    return Elemento(
        codigo="EST.X.DESC.D1",
        tipo="descriptor",
        texto=texto,
        procedencia=Procedencia(
            norma=norma,
            ubicacion="corrección de errores",
            pagina=2,
            via=(Procedencia(norma=via, ubicacion="anexo I", pagina=pagina_via),),
        ),
        padre=None,
    )


def _mundo(original: str = "Usa símbolos.) y más.", correccion: str = "dice: símbolos…)"):
    comprobar = herramienta("comprobar")
    documentos = {
        "original-1": comprobar.Documento(paginas={5: original}),
        "corrige-1": comprobar.Documento(paginas={2: correccion}),
    }
    fuentes = {
        "original-1": {
            "sustituciones": [["símbolos.)", "símbolos…)"]],
            "correcciones": ["corrige-1"],
            "modifica": [],
            "modificada_por": [],
        },
        "corrige-1": {"correcciones": [], "modifica": [], "modificada_por": []},
    }
    return documentos, fuentes


def test_comprobar_un_texto_corregido_se_verifica_en_la_pagina_original_con_la_correccion():
    comprobar = herramienta("comprobar")
    documentos, fuentes = _mundo()
    assert (
        comprobar.comprobar_elemento(_corregido("Usa símbolos…) y más."), documentos, fuentes) == []
    )


def test_comprobar_un_texto_corregido_que_no_casa_con_la_pagina_original_es_texto():
    comprobar = herramienta("comprobar")
    documentos, fuentes = _mundo()
    informe = comprobar.comprobar_elemento(
        _corregido("Usa otra cosa…) y más."), documentos, fuentes
    )
    assert _tipos(informe) == ["TEXTO"]
    # sin la sustitución declarada en la norma original, el texto corregido tampoco casa
    fuentes["original-1"]["sustituciones"] = []
    informe = comprobar.comprobar_elemento(_corregido("Usa símbolos…) y más."), documentos, fuentes)
    assert _tipos(informe) == ["TEXTO"]


def test_comprobar_la_norma_que_corrige_tiene_que_estar_relacionada_con_la_original():
    comprobar = herramienta("comprobar")
    documentos, fuentes = _mundo()
    fuentes["original-1"]["correcciones"] = []
    informe = comprobar.comprobar_elemento(_corregido("Usa símbolos…) y más."), documentos, fuentes)
    assert _tipos(informe) == ["RELACION"]
    # vale que la relación la declare la norma que corrige («modifica»)
    fuentes["corrige-1"]["modifica"] = ["original-1"]
    assert (
        comprobar.comprobar_elemento(_corregido("Usa símbolos…) y más."), documentos, fuentes) == []
    )
    # y la fragmentada («#da-unica») cuenta
    fuentes["corrige-1"]["modifica"] = []
    fuentes["original-1"]["correcciones"] = ["corrige-1#da-unica"]
    assert (
        comprobar.comprobar_elemento(_corregido("Usa símbolos…) y más."), documentos, fuentes) == []
    )


def test_comprobar_la_pagina_de_la_correccion_tiene_que_traer_lo_corregido():
    comprobar = herramienta("comprobar")
    documentos, fuentes = _mundo(correccion="dice: otra cosa")
    informe = comprobar.comprobar_elemento(_corregido("Usa símbolos…) y más."), documentos, fuentes)
    assert _tipos(informe) == ["PROCEDENCIA"]


def test_comprobar_una_via_sin_la_pagina_original_no_vale_para_un_texto_corregido():
    comprobar = herramienta("comprobar")
    documentos, fuentes = _mundo()
    informe = comprobar.comprobar_elemento(
        _corregido("Usa símbolos…) y más.", pagina_via=None), documentos, fuentes
    )
    assert _tipos(informe) == ["TEXTO"]


def test_comprobar_un_texto_con_via_que_esta_en_su_propia_pagina_solo_pide_la_relacion():
    # un módulo renombrado en el catálogo vigente: el texto nuevo está en la página de la
    # norma que cita, y la original (con otro nombre) queda en `via`
    comprobar = herramienta("comprobar")
    documentos, fuentes = _mundo(correccion="Usa símbolos…) y más.")
    assert (
        comprobar.comprobar_elemento(_corregido("Usa símbolos…) y más."), documentos, fuentes) == []
    )
    fuentes["original-1"]["correcciones"] = []
    informe = comprobar.comprobar_elemento(_corregido("Usa símbolos…) y más."), documentos, fuentes)
    assert _tipos(informe) == ["RELACION"]


def _modulo_renombrado(via_pagina: str):
    comprobar = herramienta("comprobar")
    elemento = Elemento(
        codigo="MAD.CMO.315",
        tipo="modulo",
        texto="Arquitecturas en la nube",
        procedencia=Procedencia(
            norma="corrige-1",
            ubicacion="anexo I, módulo CMO-315",
            pagina=2,
            via=(Procedencia(norma="original-1", ubicacion="anexo II", pagina=5),),
        ),
        padre=None,
    )
    documentos = {
        "original-1": comprobar.Documento(paginas={5: via_pagina}),
        "corrige-1": comprobar.Documento(paginas={2: "CMO-315 Arquitecturas en la nube 90"}),
    }
    fuentes = {
        "original-1": {"correcciones": ["corrige-1"], "modifica": [], "modificada_por": []},
        "corrige-1": {"correcciones": [], "modifica": [], "modificada_por": []},
    }
    return comprobar, elemento, documentos, fuentes


def test_comprobar_un_modulo_renombrado_con_su_nombre_original_en_la_via():
    comprobar, elemento, documentos, fuentes = _modulo_renombrado(
        "x\nCMO-315 Arquitectura en la nube (90 horas).\ny"
    )
    assert comprobar.comprobar_elemento(elemento, documentos, fuentes) == []


def test_comprobar_un_modulo_renombrado_con_la_via_en_una_pagina_sin_el_modulo():
    comprobar, elemento, documentos, fuentes = _modulo_renombrado(
        "x\nCMO-316 Programación en Phyton (90 horas).\ny"
    )
    informe = comprobar.comprobar_elemento(elemento, documentos, fuentes)
    assert _tipos(informe) == ["PROCEDENCIA"]


def test_descriptor_corregido_cita_la_correccion_con_el_original_en_via():
    modulo = herramienta("extraer_descriptores")
    registro = {
        "consolidado": {"pagina": 46069, "pares": [["símbolos...)", "símbolos…)"]]},
        "correccion_en": {"norma": "boe-a-2022-16754", "ubicacion": "corrección", "pagina": 139703},
    }
    ficha = modulo.ficha_descriptores(
        {"STEM4": "Usa fórmulas, símbolos...) y más.", "STEM5": "Otro descriptor..."},
        norma="boe-a-2022-5521",
        etapa="bachillerato",
        cursos_academicos=["2026-27"],
        registro=registro,
    )
    stem4, stem5 = ficha["elementos"]
    assert stem4["texto"] == "Usa fórmulas, símbolos…) y más."
    assert stem4["procedencia"] == {
        "norma": "boe-a-2022-16754",
        "ubicacion": "corrección",
        "pagina": 139703,
        "via": [{"norma": "boe-a-2022-5521", "ubicacion": "anexo I", "pagina": 46069}],
    }
    assert stem5["procedencia"] == {
        "norma": "boe-a-2022-5521",
        "ubicacion": "anexo I",
        "pagina": None,
    }
    assert ficha["normas"] == ["boe-a-2022-5521", "boe-a-2022-16754"]


def test_lector_de_fuentes_correccion_en_y_consolidado(tmp_path):
    comun = herramienta("comun")
    ruta = tmp_path / "fuentes.toml"
    bueno = FUENTES_TOML.replace(
        'sustituciones = [["phyton", "Python"]]\n',
        'sustituciones = [["phyton", "Python"]]\n\n[norma.correccion_en]\n'
        'norma = "bocm-20240101-9"\nubicacion = "disposición"\npagina = 7\n',
    )
    ruta.write_text(bueno, encoding="utf-8")
    orden = comun.leer_fuentes(ruta)["bocm-20230531-18"]
    assert orden["correccion_en"] == {
        "norma": "bocm-20240101-9",
        "ubicacion": "disposición",
        "pagina": 7,
    }
    assert orden["consolidado"] is None
    assert comun.procedencia_corregida(
        {"norma": "bocm-20230531-18", "ubicacion": "anexo", "pagina": 3}, orden
    ) == {
        "norma": "bocm-20240101-9",
        "ubicacion": "disposición",
        "pagina": 7,
        "via": [{"norma": "bocm-20230531-18", "ubicacion": "anexo", "pagina": 3}],
    }
    for roto, motivo in (
        (bueno.replace('norma = "bocm-20240101-9"', 'norma = "bocm-20990101-1"'), "correccion_en"),
        (bueno.replace("pagina = 7", "pagina = 0"), "correccion_en"),
        (bueno.replace('ubicacion = "disposición"\n', ""), "correccion_en"),
    ):
        ruta.write_text(roto, encoding="utf-8")
        with pytest.raises(ValueError, match=motivo):
            comun.leer_fuentes(ruta)
    with pytest.raises(ValueError, match="correccion_en"):
        comun.procedencia_corregida({"norma": "x", "ubicacion": "a", "pagina": 1}, {})


def _mundo_con_xml(xml: str = "Usa símbolos...) y más."):
    # el original solo se verifica en el XML consolidado (sus descriptores no tienen página
    # legible en el PDF): la página del PDF solo dice dónde estaba el error
    comprobar = herramienta("comprobar")
    documentos, fuentes = _mundo(original="Otra columna. símbolos.) aparte")
    documentos["original-1"] = comprobar.Documento(
        paginas=documentos["original-1"].paginas, xml=xml
    )
    fuentes["original-1"]["consolidado"] = {"pagina": 5, "pares": [["símbolos...)", "símbolos…)"]]}
    return documentos, fuentes


def test_comprobar_un_texto_corregido_se_verifica_en_el_xml_con_la_forma_del_consolidado():
    comprobar = herramienta("comprobar")
    documentos, fuentes = _mundo_con_xml()
    bueno = _corregido("Usa símbolos…) y más.")
    assert comprobar.comprobar_elemento(bueno, documentos, fuentes) == []
    # el texto no es el del XML
    malo = _corregido("Usa otra cosa…) y más.")
    assert _tipos(comprobar.comprobar_elemento(malo, documentos, fuentes)) == ["TEXTO"]
    # la página original no trae el error que dice corregir la corrección
    documentos["original-1"].paginas[5] = "Otra columna sin el error"
    assert _tipos(comprobar.comprobar_elemento(bueno, documentos, fuentes)) == ["PROCEDENCIA"]


def test_comprobar_los_recuentos_cuentan_los_elementos_que_la_correccion_declarada_toma():
    comprobar = herramienta("comprobar")
    fuentes = {
        "original-1": {
            "recuentos": {"EST.X.DESC": {"descriptores": 1}},
            "correccion_en": {"norma": "corrige-1", "ubicacion": "c", "pagina": 2},
        },
        "corrige-1": {"recuentos": {"EST.X.DESC": {"descriptores": 0}}},
    }
    ficha = Ficha(
        codigo="EST.X.DESC",
        nombre="x",
        etapa="bachillerato",
        curso=None,
        cursos_academicos=("2026-27",),
        normas=("original-1", "corrige-1"),
        elementos=(_corregido("Usa símbolos…) y más."),),
    )
    # corregido por «corrige-1» y con «original-1» en `via`: sigue siendo uno de los de «original-1»
    assert [str(d) for d in comprobar.comprobar_recuentos(ficha, fuentes)] == [
        "SOBRA EST.X.DESC descriptores: «corrige-1» tiene 0 y la ficha 1"
    ]
