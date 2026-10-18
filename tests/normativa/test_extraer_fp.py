"""Extractor de la formación profesional (`herramientas/normativa/extraer_fp.py`).

Todo sobre fragmentos reales de boletín (`herramientas/normativa/fuentes/`), ya extraídos con
`pdftotext -layout`: el RD 405/2023 (artículo segundo: la redacción vigente del RD 450/2010,
que no tiene texto consolidado), el Decreto 3/2011 (contenidos de Madrid) y el Decreto 103/2024
(horas). Sin red ni `pdftotext`.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import pytest

FUENTES = Path(__file__).parents[2] / "herramientas" / "normativa" / "fuentes"
RD405 = "boe-a-2023-13221"
RD450 = "boe-a-2010-8067"
RD500 = "boe-a-2024-10685"
DECRETO3 = "bocm-20110131-3"
DECRETO103 = "bocm-20241115-2"

TITULO = FUENTES / f"{RD405}_art-segundo_titulo.txt"
MOD_0485 = FUENTES / f"{RD405}_anexo-i_0485.txt"
MOD_0487 = FUENTES / f"{RD405}_anexo-i_0487.txt"
MOD_0492 = FUENTES / f"{RD405}_anexo-i_0492.txt"
NIVEL_500 = FUENTES / f"{RD500}_art-segundo_nivel.txt"
GENERAL_450 = FUENTES / f"{RD450}_art-4_competencia-general.txt"
MADRID_0373_0485 = FUENTES / f"{DECRETO3}_anexo-i_0373-0485.txt"
MADRID_0489_0491 = FUENTES / f"{DECRETO3}_anexo-i_0489-0491.txt"
HORAS_DAM = FUENTES / f"{DECRETO103}_anexo-ii_dam.txt"


@pytest.fixture(autouse=True)
def _herramientas_en_la_ruta(monkeypatch):
    """Solo estos tests ven el código del mantenedor (`herramientas/` no es del paquete)."""
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))


def herramienta(nombre: str) -> ModuleType:
    return importlib.import_module(f"herramientas.normativa.{nombre}")


def lineas(ruta: Path):
    return herramienta("comun").lineas_limpias(ruta.read_text(encoding="utf-8"))


def modulo(ruta: Path, codigo: str) -> dict:
    return herramienta("extraer_fp").analizar_modulo(lineas(ruta), codigo)


# --- el artículo segundo del RD 405/2023 ----------------------------------------------------


def test_el_articulo_se_recorta_entre_su_encabezado_y_el_siguiente():
    fp = herramienta("extraer_fp")
    # los dos fragmentos juntos: el artículo segundo empieza en uno y acaba, en el otro,
    # justo antes de «Artículo tercero» (que repite módulos para otro título)
    juntas = lineas(TITULO) + lineas(MOD_0492)
    articulo = fp.recortar_articulo(juntas, "segundo")
    assert articulo[0].texto.strip().startswith("Artículo segundo. Actualización del Real Decreto")
    assert articulo[0].pagina == 79002
    assert articulo[-1].texto.strip().endswith("El uso de las TIC.»")
    assert not any(l.texto.strip().startswith("Artículo tercero") for l in articulo)
    # el que no está es un error, no un trozo vacío
    with pytest.raises(ValueError, match="no encuentro el Artículo cuarto"):
        fp.recortar_articulo(juntas, "cuarto")


# --- un módulo del anexo I: resultados, criterios, contenidos básicos y orientaciones -----


def test_modulo_resultados_y_criterios():
    m = modulo(MOD_0485, "0485")
    resultados = m["resultados"]
    assert [r["numero"] for r in resultados] == list("123456789")
    assert [len(r["criterios"]) for r in resultados] == [9, 9, 9, 9, 8, 10, 10, 8, 7]
    primero = resultados[0]
    assert primero["texto"] == (
        "Reconoce la estructura de un programa informático, identificando y relacionando "
        "los elementos propios del lenguaje de programación utilizado."
    )
    assert primero["pagina"] == 79015
    d = primero["criterios"][3]
    assert (d["letra"], d["pagina"]) == ("d", 79015)
    assert d["texto"] == (
        "Se han identificado los distintos tipos de variables y la utilidad específica de cada uno."
    )
    # el criterio h) ya está en la página siguiente
    assert (primero["criterios"][7]["letra"], primero["criterios"][7]["pagina"]) == ("h", 79016)
    # los espacios de justificación del PDF no se guardan
    séptimo = resultados[6]
    assert séptimo["texto"] == (
        "Desarrolla programas aplicando características avanzadas de los lenguajes "
        "orientados a objetos y del entorno de programación."
    )
    # un criterio cuyo texto salta de línea y de página
    assert resultados[6]["criterios"][9]["pagina"] == 79018
    assert resultados[8]["criterios"][-1]["texto"] == (
        "Se han creado aplicaciones para gestionar la información presente en bases de datos."
    )


def test_modulo_contenidos_basicos_con_encabezados_y_viñetas():
    m = modulo(MOD_0485, "0485")
    basicos = m["basicos"]
    assert [b["nivel"] for b in basicos].count(1) == 9
    assert [b["nivel"] for b in basicos].count(2) == 63
    assert (basicos[0]["nivel"], basicos[0]["texto"]) == (
        1,
        "Identificación de los elementos de un programa informático:",
    )
    assert (basicos[1]["nivel"], basicos[1]["texto"]) == (2, "Estructura y bloques fundamentales.")
    # una viñeta que ocupa tres líneas, con el signo menos del boletín
    assert (
        "Apertura y cierre de ficheros. Modos de acceso. Escritura y lectura de información en ficheros."
        in [b["texto"] for b in basicos]
    )
    assert basicos[-1]["texto"] == (
        "Almacenamiento, recuperación, actualización y eliminación de información en "
        "bases de datos."
    )
    # un encabezado que abre una página
    objetos = next(b for b in basicos if b["texto"] == "Utilización de objetos:")
    assert objetos["pagina"] == 79019


def test_modulo_orientaciones_son_un_solo_texto_sin_viñetas_ni_el_modulo_siguiente():
    ori = modulo(MOD_0485, "0485")["orientaciones"]
    assert ori["pagina"] == 79020
    texto = ori["texto"]
    assert texto.startswith(
        "Este módulo profesional contiene parte de la formación necesaria para desempeñar"
    )
    assert (
        "La formación del módulo contribuye a alcanzar los objetivos generales e), j), q) y w)"
        in texto
    )
    assert texto.endswith(
        "La prueba, depuración y documentación de las aplicaciones desarrolladas."
    )
    # la viñeta es del boletín, no del texto; y el aviso del módulo siguiente no es suyo
    assert "–" not in texto and "−" not in texto
    assert "queda redactado" not in texto and "0373" not in texto


def test_modulo_encabezado_de_contenidos_que_abre_una_pagina():
    # «Repositorio. Herramientas de control de versiones…» abre la página 79028 tras una
    # viñeta que acaba en punto: es un encabezado (acaba en «:»), no su continuación
    basicos = modulo(MOD_0487, "0487")["basicos"]
    textos = [b["texto"] for b in basicos]
    i = textos.index(
        "Repositorio. Herramientas de control de versiones. Uso integrado en el entorno "
        "de desarrollo:"
    )
    assert basicos[i]["nivel"] == 1 and basicos[i]["pagina"] == 79028
    assert (
        textos[i - 1]
        == "Control de versiones. Estructura de las herramientas de control de versiones."
    )
    assert textos[i + 1] == "Repositorios remotos."


def test_modulo_sin_contenidos_basicos_y_con_la_comilla_de_cierre():
    # el proyecto no tiene contenidos básicos, y su último párrafo cierra la cita con «»»
    m = modulo(MOD_0492, "0492")
    assert [len(r["criterios"]) for r in m["resultados"]] == [9, 9, 8, 7]
    assert m["basicos"] == []
    assert m["orientaciones"]["texto"].endswith("El uso de las TIC.")


def test_modulo_que_no_esta_o_esta_repetido_es_un_error():
    fp = herramienta("extraer_fp")
    with pytest.raises(ValueError, match="no encuentro el módulo 0999"):
        fp.analizar_modulo(lineas(MOD_0485), "0999")
    with pytest.raises(ValueError, match="aparece más de una vez"):
        fp.analizar_modulo(lineas(MOD_0485) + lineas(MOD_0485), "0485")


def test_modulo_un_criterio_fuera_de_orden_es_un_error_y_no_se_pierde_en_silencio():
    fp = herramienta("extraer_fp")
    comun = herramienta("comun")
    texto = (
        "Código: 0999.\n"
        "Resultados de aprendizaje y criterios de evaluación.\n"
        "1. Hace algo.\n"
        "Criterios de evaluación:\n"
        "a) Se ha hecho.\n"
        "c) Se ha saltado el b.\n"
    )
    with pytest.raises(ValueError, match="0999.*criterio c"):
        fp.analizar_modulo(comun.lineas_de(texto), "0999")


def test_modulo_una_linea_que_no_es_de_ningun_tipo_es_un_error():
    fp = herramienta("extraer_fp")
    comun = herramienta("comun")
    texto = (
        "Código: 0999.\n"
        "Resultados de aprendizaje y criterios de evaluación.\n"
        "\n"
        "Una línea suelta que no es un resultado.\n"
    )
    with pytest.raises(ValueError, match="0999.*Una línea suelta"):
        fp.analizar_modulo(comun.lineas_de(texto), "0999")


# --- los elementos del módulo: códigos, padres y procedencia con vía --------------------------


def elementos_0485() -> list[dict]:
    fp = herramienta("extraer_fp")
    return fp.elementos_del_modulo(
        modulo(MOD_0485, "0485"),
        ficha="MAD.DAM.0485",
        norma=RD405,
        ubicacion="artículo segundo, apartado Seis (anexo I)",
        via={"norma": RD450, "ubicacion": "anexo I"},
        orden_inicial=2,
    )


def test_elementos_del_modulo_codigos_padres_y_orden():
    elementos = elementos_0485()
    por_codigo = {e["codigo"]: e for e in elementos}
    assert len(por_codigo) == len(elementos)
    tipos = [e["tipo"] for e in elementos]
    assert tipos.count("resultado_aprendizaje") == 9
    assert tipos.count("criterio_fp") == 79
    assert tipos.count("contenido_basico") == 72
    assert tipos.count("orientaciones") == 1
    # el módulo es la ficha, y de él cuelgan los resultados, los contenidos y las orientaciones
    assert por_codigo["MAD.DAM.0485.RA.3"]["padre"] == "MAD.DAM.0485"
    assert por_codigo["MAD.DAM.0485.RA.3.a"]["padre"] == "MAD.DAM.0485.RA.3"
    assert por_codigo["MAD.DAM.0485.ORI"]["padre"] == "MAD.DAM.0485"
    # los contenidos básicos son estatales: EST. y no MAD.
    assert por_codigo["EST.DAM.0485.CB.1"]["padre"] == "MAD.DAM.0485"
    assert por_codigo["EST.DAM.0485.CB.1.1"]["padre"] == "EST.DAM.0485.CB.1"
    assert por_codigo["EST.DAM.0485.CB.2"]["tipo"] == "contenido_basico"
    assert [e["orden"] for e in elementos] == list(range(2, 2 + len(elementos)))
    # en el orden del anexo: resultados, contenidos básicos y orientaciones
    assert elementos[0]["codigo"] == "MAD.DAM.0485.RA.1"
    assert elementos[-1]["codigo"] == "MAD.DAM.0485.ORI"


def test_elementos_del_modulo_la_procedencia_es_la_modificacion_con_via_al_original():
    por_codigo = {e["codigo"]: e for e in elementos_0485()}
    assert por_codigo["MAD.DAM.0485.RA.1.h"]["procedencia"] == {
        "norma": RD405,
        "ubicacion": (
            "artículo segundo, apartado Seis (anexo I), módulo 0485, "
            "resultado de aprendizaje 1, criterio h"
        ),
        "pagina": 79016,
        "via": [
            {
                "norma": RD450,
                "ubicacion": "anexo I, módulo 0485, resultado de aprendizaje 1, criterio h",
                "pagina": None,
            }
        ],
    }
    ori = por_codigo["MAD.DAM.0485.ORI"]["procedencia"]
    assert ori["ubicacion"].endswith("módulo 0485, orientaciones pedagógicas")
    assert ori["via"][0]["ubicacion"] == "anexo I, módulo 0485, orientaciones pedagógicas"
    basico = por_codigo["EST.DAM.0485.CB.2.1"]["procedencia"]
    assert basico["ubicacion"].endswith("módulo 0485, contenidos básicos")
    assert basico["pagina"] == 79019


def test_elementos_del_modulo_sin_via_es_la_procedencia_de_siempre():
    fp = herramienta("extraer_fp")
    elementos = fp.elementos_del_modulo(
        modulo(MOD_0492, "0492"), ficha="MAD.DAM.0492", norma=RD405, ubicacion="anexo I"
    )
    assert all("via" not in e["procedencia"] for e in elementos)
    assert not any(e["tipo"] == "contenido_basico" for e in elementos)
    assert elementos[0]["orden"] == 1


# --- contenidos de Madrid (Decreto 3/2011) ---------------------------------------------------


def madrid(ruta: Path, codigo: str) -> list[dict]:
    return herramienta("extraer_fp").analizar_contenidos_madrid(lineas(ruta), codigo)


def niveles(items: list[dict]) -> dict[int, int]:
    return {n: sum(1 for i in items if i["nivel"] == n) for n in (1, 2, 3)}


def test_madrid_la_cabecera_del_modulo_puede_ocupar_dos_lineas():
    # «Módulo profesional 04: Lenguajes de marcas… información / (código: 0373)»
    items = madrid(MADRID_0373_0485, "0373")
    assert items[0] == {
        "nivel": 1,
        "texto": "Reconocimiento de las características de lenguajes de marcas:",
        "pagina": 73,
    }
    assert items[-1]["texto"] == (
        "Gestores de relaciones con clientes CRM (Customer Relationship Management)."
    )
    assert items[-1]["pagina"] == 75
    # ni el módulo anterior (FOL) ni el siguiente
    textos = [i["texto"] for i in items]
    assert not any("Datos, algoritmos" in t or "Primeros auxilios" in t for t in textos)
    # 8 encabezados, 62 viñetas «—» y 8 apartados, contados en el boletín
    assert niveles(items) == {1: 8, 2: 62, 3: 8}
    # los apartados que cuelgan de una viñeta que acaba en «:»
    i = textos.index("Utilización de herramientas de procesamiento:")
    assert [(x["nivel"], x["texto"]) for x in items[i : i + 3]] == [
        (2, "Utilización de herramientas de procesamiento:"),
        (3, "DOM."),
        (3, "SAX (Simple Application programming interface for XML)."),
    ]


def test_madrid_niveles_y_sangrias_que_cambian_de_pagina():
    items = madrid(MADRID_0373_0485, "0485")
    textos = [i["texto"] for i in items]
    assert items[0] == {"nivel": 1, "texto": "Introducción a la programación:", "pagina": 75}
    assert niveles(items) == {1: 13, 2: 83, 3: 27}
    # la página 76 empieza con otra sangría: «— Estructuras de repetición.» sigue siendo una viñeta
    assert items[textos.index("Estructuras de repetición.")] == {
        "nivel": 2,
        "texto": "Estructuras de repetición.",
        "pagina": 76,
    }
    # apartados sin viñeta y sin punto final: cada uno el suyo, y «Inicialización» no se pega
    i = textos.index("Arrays unidimensionales y multidimensionales:")
    assert [(x["nivel"], x["texto"]) for x in items[i : i + 7]] == [
        (2, "Arrays unidimensionales y multidimensionales:"),
        (3, "Declaración."),
        (3, "Creación de arrays unidimensionales y multidimensionales."),
        (3, "Inicialización"),
        (3, "Acceso a elementos."),
        (3, "Recorridos, búsquedas y ordenaciones."),
        (2, "Cadenas de caracteres:"),
    ]
    # un apartado que ocupa dos líneas, con la palabra partida
    assert (
        3,
        "Polimorfismo en tiempo de compilación (sobrecarga) y polimorfismo en tiempo de "
        "ejecución (ligadura dinámica).",
    ) in [(x["nivel"], x["texto"]) for x in items]
    # una viñeta que ocupa dos líneas
    assert (
        2,
        "Interfaces gráficos de usuario simples. Concepto de evento. Creación de "
        "controladores de eventos.",
    ) in [(x["nivel"], x["texto"]) for x in items]
    assert items[-1]["texto"] == "Tipos de datos colección."


def test_madrid_el_ultimo_modulo_acaba_en_el_anexo_siguiente_y_el_horario_lleva_dos_puntos():
    # «Contenidos (duración: 80 horas)» con dos puntos, y la raya suelta de «— destruido.»,
    # que el boletín imprime como una viñeta más
    items = madrid(MADRID_0489_0491, "0489")
    assert items[0]["texto"] == "Análisis de tecnologías para aplicaciones en dispositivos móviles:"
    # esta viñeta acaba en «:» y sigue en la línea de abajo, sin glifo de apartado: es suya
    assert items[1] == {
        "nivel": 2,
        "texto": "Limitaciones que plantea la ejecución de aplicaciones en los dispositivos "
        "móviles: desconexión, seguridad, memoria, consumo batería, almacenamiento.",
        "pagina": 87,
    }
    assert items[2]["texto"] == "Tecnologías disponibles."
    assert "destruido." in [i["texto"] for i in items]
    ultimo = madrid(MADRID_0489_0491, "0491")
    assert ultimo[0]["pagina"] == 88
    # acaba donde empieza el anexo II (módulo 10, «INGLÉS TÉCNICO…», con su código en mayúsculas)
    assert not any(
        "INGLÉS" in i["texto"] or "Resultados de aprendizaje" in i["texto"] for i in ultimo
    )


def test_madrid_un_modulo_que_no_esta_es_un_error_y_uno_sin_contenidos_tambien():
    fp = herramienta("extraer_fp")
    with pytest.raises(ValueError, match="no encuentro el módulo 0492 en los contenidos de Madrid"):
        fp.analizar_contenidos_madrid(lineas(MADRID_0373_0485), "0492")


# --- horas y curso (Decreto 103/2024, anexo II) ----------------------------------------------

CICLO_DAM = "DESARROLLO DE APLICACIONES MULTIPLATAFORMA"


def horas(codigo: str):
    return herramienta("extraer_fp").analizar_horas_curso(
        lineas(HORAS_DAM), ciclo=CICLO_DAM, codigo_modulo=codigo
    )


def test_horas_y_curso_de_los_modulos_tecnicos_de_dam():
    esperado = {
        "0484": ("Bases de datos", 205, "1"),
        "0487": ("Entornos de desarrollo", 60, "1"),
        "0373": ("Lenguajes de marcas y sistemas de gestión de información", 110, "1"),
        "0485": ("Programación", 270, "1"),
        "0483": ("Sistemas informáticos", 205, "1"),
        "0486": ("Acceso a datos", 165, "2"),
        "0488": ("Desarrollo de interfaces", 150, "2"),
        "0490": ("Programación de servicios y procesos", 135, "2"),
        "0489": ("Programación multimedia y dispositivos móviles", 135, "2"),
        "0491": ("Sistemas de gestión empresarial", 95, "2"),
    }
    for codigo, (nombre, h, curso) in esperado.items():
        fila = horas(codigo)
        assert (fila.nombre, fila.horas, fila.curso, fila.pagina) == (nombre, h, curso, 120)


def test_horas_el_proyecto_ocupa_dos_lineas_y_la_tabla_no_le_pone_curso():
    fila = horas("0492")
    assert fila.nombre == "Proyecto intermodular de desarrollo de aplicaciones multiplataforma"
    assert (fila.horas, fila.curso, fila.pagina) == (50, None, 120)


def test_horas_un_modulo_o_un_ciclo_que_no_estan_son_un_error():
    fp = herramienta("extraer_fp")
    with pytest.raises(ValueError, match="no encuentro el módulo 0999"):
        horas("0999")
    with pytest.raises(ValueError, match="no encuentro el ciclo «OTRO CICLO»"):
        fp.analizar_horas_curso(lineas(HORAS_DAM), ciclo="OTRO CICLO", codigo_modulo="0485")


# --- el título: identificación, competencias y objetivos --------------------------------------


def articulo_titulo() -> list:
    return herramienta("extraer_fp").recortar_articulo(lineas(TITULO), "segundo")


def test_unir_junta_un_guion_de_compuesto_seguido_de_mayuscula_sin_espacio():
    comun = herramienta("comun")
    assert comun.unir(["en sistemas ERP-", "CRM."]) == "en sistemas ERP-CRM."
    # la palabra partida sigue perdiendo el guion
    assert comun.unir(["un sistema infor-", "mático"]) == "un sistema informático"


def test_titulo_identificacion_un_elemento_por_dato():
    fp = herramienta("extraer_fp")
    apartado, cuerpo = fp.articulo_reescrito(articulo_titulo(), 2)
    assert apartado == "Uno"
    items = fp.partir_identificacion(cuerpo)
    assert [i["lugar"] for i in items] == [
        "Denominación",
        "Nivel",
        "Duración",
        "Equivalencia en créditos ECTS",
        "Familia profesional",
        "Ramas de conocimiento",
        "Referente en la Clasificación Internacional Normalizada de la Educación",
        "Nivel del Marco Español de Cualificaciones para la Educación Superior",
    ]
    assert items[0]["texto"] == "Denominación: Desarrollo de Aplicaciones Multiplataforma."
    assert items[0]["pagina"] == 79002
    assert items[5]["texto"] == "Ramas de conocimiento: Ciencias. Ingeniería y Arquitectura."
    # el valor en la línea de abajo, y el último dato sin la comilla que cierra la cita
    assert items[6]["texto"] == (
        "Referente en la Clasificación Internacional Normalizada de la Educación: P-5.5.4."
    )
    assert items[7]["texto"] == (
        "Nivel del Marco Español de Cualificaciones para la Educación Superior: "
        "Nivel 1 Técnico Superior."
    )


def test_titulo_competencias_y_objetivos_veintiseis_letras_con_la_enie():
    fp = herramienta("extraer_fp")
    esperadas = list("abcdefghijklmn") + ["ñ"] + list("opqrstuvwxy")
    apartado, cuerpo = fp.articulo_reescrito(articulo_titulo(), 5)
    assert apartado == "Dos"
    competencias = fp.partir_letras(cuerpo)
    assert [c["lugar"] for c in competencias] == [f"letra {x}" for x in esperadas]
    assert [c["clave"] for c in competencias] == esperadas
    por_letra = {c["clave"]: c for c in competencias}
    assert por_letra["f"]["texto"] == (
        "Desarrollar aplicaciones implementando un sistema completo de formularios e informes "
        "que permitan gestionar de forma integral la información almacenada."
    )
    assert (por_letra["g"]["pagina"], por_letra["h"]["pagina"]) == (79002, 79003)
    assert por_letra["ñ"]["texto"] == (
        "Desarrollar aplicaciones capaces de ofrecer servicios en red empleando "
        "mecanismos de comunicación."
    )
    assert por_letra["y"]["texto"].endswith("con una actitud crítica y responsable.")

    apartado, cuerpo = fp.articulo_reescrito(articulo_titulo(), 9)
    assert apartado == "Cinco"
    objetivos = {o["clave"]: o for o in fp.partir_letras(cuerpo)}
    assert list(objetivos) == esperadas
    # «ERP-» + «CRM» son un compuesto con guion que salta de línea
    assert objetivos["q"]["texto"].endswith(
        "desarrollar componentes personalizados en sistemas ERP-CRM."
    )
    assert objetivos["y"]["texto"].endswith("para participar como ciudadano democrático.")


def test_titulo_un_articulo_que_no_esta_reescrito_es_un_error():
    fp = herramienta("extraer_fp")
    with pytest.raises(ValueError, match="no encuentro el apartado que reescribe el artículo 7"):
        fp.articulo_reescrito(articulo_titulo(), 7)


def test_titulo_una_lista_de_letras_con_un_hueco_es_un_error():
    fp = herramienta("extraer_fp")
    comun = herramienta("comun")
    cuerpo = comun.lineas_de("a) Uno.\nc) Tres.\n")
    with pytest.raises(ValueError, match="letra c fuera de orden"):
        fp.partir_letras(cuerpo)


def test_titulo_competencia_general_del_articulo_cuarto_del_real_decreto_original():
    fp = herramienta("extraer_fp")
    general = fp.articulo_original(lineas(GENERAL_450), 4)
    assert general["pagina"] == 43778
    assert general["texto"] == (
        "La competencia general de este título consiste en desarrollar, implantar, documentar y "
        "mantener aplicaciones informáticas multiplataforma, utilizando tecnologías y entornos "
        "de desarrollo específicos, garantizando el acceso a los datos de forma segura y "
        "cumpliendo los criterios de «usabilidad» y calidad exigidas en los estándares "
        "establecidos."
    )


def test_titulo_el_parrafo_que_anade_el_real_decreto_500_2024():
    fp = herramienta("extraer_fp")
    adicion = fp.parrafo_anadido(lineas(NIVEL_500), 2)
    assert adicion == {
        "texto": (
            "El título de Técnico Superior se corresponde con un nivel 5A del Marco Español "
            "de Cualificaciones para el Aprendizaje Permanente."
        ),
        "pagina": 61172,
    }
    with pytest.raises(ValueError, match="no encuentro el párrafo que se añade al artículo 3"):
        fp.parrafo_anadido(lineas(NIVEL_500), 3)


def test_elementos_del_titulo_codigos_y_procedencia():
    fp = herramienta("extraer_fp")
    articulo = articulo_titulo()
    partes = {}
    for numero, tipo in ((2, "ident"), (5, "cp"), (9, "og")):
        apartado, cuerpo = fp.articulo_reescrito(articulo, numero)
        partes[tipo] = (apartado, cuerpo)
    elementos = fp.elementos_del_titulo(
        ficha="MAD.DAM",
        norma=RD405,
        ubicacion="artículo segundo",
        original=RD450,
        identificacion=(partes["ident"][0], fp.partir_identificacion(partes["ident"][1])),
        competencias=(partes["cp"][0], fp.partir_letras(partes["cp"][1])),
        objetivos=(partes["og"][0], fp.partir_letras(partes["og"][1])),
        general=fp.articulo_original(lineas(GENERAL_450), 4),
        adicion=fp.parrafo_anadido(lineas(NIVEL_500), 2),
        norma_adicion=RD500,
    )
    por_codigo = {e["codigo"]: e for e in elementos}
    assert len(por_codigo) == len(elementos) == 8 + 1 + 1 + 26 + 26
    assert [e["tipo"] for e in elementos].count("titulo") == 9
    assert [e["orden"] for e in elementos] == list(range(1, len(elementos) + 1))
    assert all("padre" not in e for e in elementos)  # el título es la ficha, no un elemento
    # la identificación: un elemento por dato
    assert por_codigo["MAD.DAM.TIT.1"]["texto"].startswith("Denominación:")
    assert por_codigo["MAD.DAM.TIT.1"]["procedencia"] == {
        "norma": RD405,
        "ubicacion": "artículo segundo, apartado Uno (artículo 2), Denominación",
        "pagina": 79002,
        "via": [{"norma": RD450, "ubicacion": "artículo 2, Denominación", "pagina": None}],
    }
    # el párrafo que añade el RD 500/2024 es el último dato del título
    assert por_codigo["MAD.DAM.TIT.9"]["procedencia"] == {
        "norma": RD500,
        "ubicacion": "artículo segundo (párrafo final que se añade al artículo 2)",
        "pagina": 61172,
        "via": [{"norma": RD450, "ubicacion": "artículo 2", "pagina": None}],
    }
    # la competencia general no la toca ningún real decreto posterior: sin vía
    assert por_codigo["MAD.DAM.CG"]["procedencia"] == {
        "norma": RD450,
        "ubicacion": "artículo 4",
        "pagina": 43778,
    }
    assert por_codigo["MAD.DAM.CP.ñ"]["tipo"] == "competencia_profesional"
    assert por_codigo["MAD.DAM.CP.ñ"]["procedencia"]["ubicacion"] == (
        "artículo segundo, apartado Dos (artículo 5), letra ñ"
    )
    assert por_codigo["MAD.DAM.OG.y"]["tipo"] == "objetivo_general"
    assert por_codigo["MAD.DAM.OG.y"]["procedencia"]["via"][0]["ubicacion"] == (
        "artículo 9, letra y"
    )


# --- de punta a punta: la línea de órdenes, el cargador y la comprobación literal ------------

NORMAS_DAM = {
    RD450: ("real_decreto", "450/2010", "BOE"),
    RD405: ("real_decreto", "405/2023", "BOE"),
    RD500: ("real_decreto", "500/2024", "BOE"),
    DECRETO3: ("decreto", "3/2011", "BOCM"),
    DECRETO103: ("decreto", "103/2024", "BOCM"),
}


def cache_dam(tmp_path: Path) -> Path:
    """Una caché de boletines hecha solo con los fragmentos reales (los trozos van en orden)."""

    def leer(*rutas: Path) -> str:
        return "".join(r.read_text(encoding="utf-8") for r in rutas)

    cache = tmp_path / "cache"
    cache.mkdir()
    textos = {
        RD405: leer(TITULO, MOD_0485, MOD_0487, MOD_0492),
        RD450: leer(GENERAL_450),
        RD500: leer(NIVEL_500),
        DECRETO3: leer(MADRID_0373_0485, MADRID_0489_0491),
        DECRETO103: leer(HORAS_DAM),
    }
    for id_, texto in textos.items():
        (cache / f"{id_}.txt").write_text(texto, encoding="utf-8")
    return cache


def datos_dam(tmp_path: Path) -> Path:
    """La carpeta de datos con las cinco normas de prueba (las fichas las escribe el extractor)."""
    import json

    raiz = tmp_path / "datos"
    (raiz / "normas").mkdir(parents=True)
    (raiz / "fichas").mkdir()
    for id_, (rango, numero, boletin) in NORMAS_DAM.items():
        norma = {
            "id": id_,
            "rango": rango,
            "numero": numero,
            "fecha": "2023-05-29",
            "titulo": f"Norma de prueba {numero}",
            "boletin": boletin,
            "url_pdf": "https://www.boe.es/ejemplo.pdf"
            if boletin == "BOE"
            else "https://www.bocm.es/ejemplo.pdf",
            "sha256": "0" * 64,
            "estado": "vigente",
            "revisada": "2026-10-18",
        }
        (raiz / "normas" / f"{id_}.json").write_text(json.dumps(norma), encoding="utf-8")
    return raiz


def extraer_modulo(tmp_path: Path, modulo: str, *extra: str) -> dict:
    import json

    fp = herramienta("extraer_fp")
    cache = tmp_path / "cache"
    raiz = tmp_path / "datos"
    if not cache.exists():
        cache_dam(tmp_path)
    if not raiz.exists():
        datos_dam(tmp_path)
    argumentos = [
        "modulo",
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
        "--boe",
        RD405,
        "--ubicacion-boe",
        "artículo segundo, apartado Seis (anexo I)",
        "--via",
        RD450,
        "--madrid",
        DECRETO3,
        "--horas",
        DECRETO103,
        "--salida",
        str(raiz),
        *extra,
    ]
    assert fp.main(argumentos) == 0
    return json.loads((raiz / "fichas" / f"MAD.DAM.{modulo}.json").read_text(encoding="utf-8"))


def comprobar_todo(tmp_path: Path) -> list:
    from tiza.normativa import limpiar_cache

    comprobar = herramienta("comprobar")
    limpiar_cache()
    documentos = comprobar.cargar_documentos(tmp_path / "cache", list(NORMAS_DAM))
    # lo único que declara fuentes.toml aquí: el RD 1691/2023 modifica el del título
    fuentes = {RD450: {"modificada_por": ["boe-a-2023-13221", "boe-a-2024-10685"]}}
    return comprobar.comprobar_datos(tmp_path / "datos", documentos, fuentes)


def test_linea_de_ordenes_un_modulo_pasa_el_cargador_y_la_comprobacion_literal(tmp_path):
    ficha = extraer_modulo(tmp_path, "0485")
    assert (ficha["codigo"], ficha["nombre"], ficha["curso"], ficha["etapa"]) == (
        "MAD.DAM.0485",
        "Programación",
        "1",
        "fp_gs",
    )
    assert ficha["cursos_academicos"] == ["2026-27"]
    assert ficha["normas"] == [RD405, RD450, DECRETO3, DECRETO103]
    modulo_ = ficha["elementos"][0]
    assert modulo_["codigo"] == "MAD.DAM.0485" and modulo_["tipo"] == "modulo"
    assert modulo_["datos"] == {"horas": 270, "curso": "1"}
    assert modulo_["procedencia"] == {"norma": DECRETO103, "ubicacion": "anexo II", "pagina": 120}
    tipos = [e["tipo"] for e in ficha["elementos"]]
    assert tipos.count("resultado_aprendizaje") == 9
    assert tipos.count("criterio_fp") == 79
    assert tipos.count("contenido_basico") == 72
    assert tipos.count("contenido") == 123  # 13 + 83 + 27 de Madrid, no los 72 estatales
    assert [e["orden"] for e in ficha["elementos"]] == list(range(1, len(ficha["elementos"]) + 1))
    assert comprobar_todo(tmp_path) == []
    # los recuentos de fuentes.toml cuentan por norma y por tipo: los contenidos básicos son
    # del real decreto y los de Madrid, del decreto
    from tiza.normativa import cargar, limpiar_cache

    limpiar_cache()
    cargada = cargar(tmp_path / "datos").fichas["MAD.DAM.0485"]
    comprobar = herramienta("comprobar")
    esperados = {
        RD405: {
            "recuentos": {
                "MAD.DAM.0485": {"resultados": 9, "criterios_fp": 79, "contenidos_basicos": 72}
            }
        },
        DECRETO3: {"recuentos": {"MAD.DAM.0485": {"contenidos": 123}}},
    }
    assert comprobar.comprobar_recuentos(cargada, esperados) == []
    esperados[DECRETO3]["recuentos"]["MAD.DAM.0485"]["contenidos"] = 72
    assert [d.tipo for d in comprobar.comprobar_recuentos(cargada, esperados)] == ["SOBRA"]


def test_linea_de_ordenes_el_proyecto_no_tiene_curso_en_la_tabla_ni_contenidos_de_madrid(tmp_path):
    # sin decir el curso ni que Madrid no trae contenidos, se niega en vez de suponer
    with pytest.raises(SystemExit, match="la tabla no le pone curso"):
        extraer_modulo(tmp_path, "0492")
    with pytest.raises(ValueError, match="no encuentro el módulo 0492 en los contenidos de Madrid"):
        extraer_modulo(tmp_path, "0492", "--curso", "2")
    ficha = extraer_modulo(tmp_path, "0492", "--curso", "2", "--sin-contenidos-madrid")
    assert ficha["nombre"] == "Proyecto intermodular de desarrollo de aplicaciones multiplataforma"
    assert ficha["curso"] == "2"
    assert ficha["elementos"][0]["datos"] == {"horas": 50, "curso": "2"}
    assert ficha["normas"] == [RD405, RD450, DECRETO103]
    tipos = {e["tipo"] for e in ficha["elementos"]}
    assert "contenido" not in tipos and "contenido_basico" not in tipos
    assert comprobar_todo(tmp_path) == []
    # y el curso que se da no puede contradecir a la tabla
    with pytest.raises(SystemExit, match="la tabla pone el curso 1"):
        extraer_modulo(tmp_path, "0485", "--curso", "2")


def test_linea_de_ordenes_el_titulo(tmp_path):
    import json

    fp = herramienta("extraer_fp")
    raiz = datos_dam(tmp_path)
    cache = cache_dam(tmp_path)
    argumentos = [
        "titulo",
        "--ficha",
        "MAD.DAM",
        "--nombre",
        "Técnico Superior en Desarrollo de Aplicaciones Multiplataforma",
        "--cursos-academicos",
        "2026-27",
        "--cache",
        str(cache),
        "--boe",
        RD405,
        "--original",
        RD450,
        "--adicion",
        RD500,
        "--salida",
        str(raiz),
    ]
    assert fp.main(argumentos) == 0
    ficha = json.loads((raiz / "fichas" / "MAD.DAM.json").read_text(encoding="utf-8"))
    assert ficha["nombre"] == "Técnico Superior en Desarrollo de Aplicaciones Multiplataforma"
    assert (ficha["etapa"], ficha["curso"]) == ("fp_gs", None)
    assert ficha["normas"] == [RD405, RD450, RD500]
    assert len(ficha["elementos"]) == 62
    assert comprobar_todo(tmp_path) == []
    # el nombre que se da tiene que ser el del título
    with pytest.raises(ValueError, match="no figura en el artículo 2"):
        fp.main([*argumentos[:4], "Otro título", *argumentos[5:]])


def test_elementos_del_modulo_una_ficha_que_no_es_de_madrid_no_lleva_basicos():
    fp = herramienta("extraer_fp")
    with pytest.raises(ValueError, match="debe empezar por «MAD.»"):
        fp.elementos_del_modulo(
            modulo(MOD_0485, "0485"), ficha="DAM.0485", norma=RD405, ubicacion="anexo I"
        )
