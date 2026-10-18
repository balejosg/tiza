"""Extrae un módulo profesional, o el título, de un ciclo de FP de grado superior a una ficha.

``modulo`` reúne tres fuentes, cada una de la norma que manda en ese dato:

* resultados de aprendizaje, criterios de evaluación, contenidos básicos y orientaciones
  pedagógicas, del PDF del real decreto que reescribe el anexo I del título (el RD 450/2010
  no tiene texto consolidado en el BOE: su redacción vigente sale del artículo segundo del
  RD 405/2023, «queda redactado como sigue»). La procedencia es esa norma y, en ``via``, el
  lugar del original;
* contenidos de Madrid, del PDF del decreto de currículo del ciclo;
* horas y curso, de la tabla de organización académica (anexo II) del decreto que
  modifica los planes de estudios.

``titulo`` extrae la identificación (art. 2), las competencias profesionales (art. 5) y los
objetivos generales (art. 9) en la redacción del mismo artículo, y la competencia general
(art. 4, sin reescribir) del PDF del real decreto original. Un párrafo que otra norma añade al
artículo 2 (RD 500/2024: el nivel del Marco Español de Cualificaciones) es un dato más.

No hay aquí la extracción de los módulos transversales ni de los optativos de las
órdenes de 2025: el texto de ``pdftotext`` de la Orden 3537/2025 sale cifrado (la fuente
del PDF no trae mapa de caracteres) y hay que resolver primero cómo se lee.

Las funciones de análisis trabajan sobre texto o líneas; solo :func:`main` toca ficheros.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any, NamedTuple

from . import comun
from .comun import Linea
from .extraer_lomloe import escribir_ficha

_MODULO_MADRID = re.compile(r"^\s*M[óo]dulo profesional\s+\d+\s*:", re.IGNORECASE)
_VINETA = re.compile(r"^\s*[—–-]\s+(\S.*)$")


def _sangria(texto: str) -> int:
    return len(texto) - len(texto.lstrip())


# --- el artículo de un real decreto que reescribe el título ---------------------------------

_ORDINALES = (
    "primero|segundo|tercero|cuarto|quinto|sexto|séptimo|octavo|noveno|décimo|"
    "undécimo|duodécimo|decimotercero|decimocuarto|decimoquinto|decimosexto|"
    "decimoséptimo|decimoctavo|decimonoveno|vigésimo"
)
_ARTICULO_ORDINAL = re.compile(rf"^\s*Art[íi]culo\s+({_ORDINALES})\.")


def recortar_articulo(lineas: Sequence[Linea], ordinal: str) -> list[Linea]:
    """Las líneas del «Artículo <ordinal>.» hasta el siguiente artículo con ordinal en letra.

    El RD 405/2023 actualiza dos títulos: su artículo segundo reescribe el RD 450/2010 (DAM) y
    el tercero repite módulos comunes para el otro (DAW). Quedarse con uno solo es lo que
    evita coger los del otro título.
    """
    inicio = next(
        (
            i
            for i, l in enumerate(lineas)
            if (m := _ARTICULO_ORDINAL.match(l.texto)) and m[1] == ordinal
        ),
        None,
    )
    if inicio is None:
        raise ValueError(f"no encuentro el Artículo {ordinal}")
    fin = next(
        (i for i in range(inicio + 1, len(lineas)) if _ARTICULO_ORDINAL.match(lineas[i].texto)),
        len(lineas),
    )
    return list(lineas[inicio:fin])


# --- un módulo del anexo I: resultados, criterios, contenidos básicos y orientaciones -------

_CODIGO_BOE = r"^\s*C[óo]digo:\s*{codigo}\b"
_FIN_DE_MODULO = re.compile(
    r"^\s*(?:El m[óo]dulo profesional\s+\d{4}\b|M[óo]dulo [Pp]rofesional:|Modulo profesional:)"
    rf"|^\s*Art[íi]culo\s+(?:{_ORDINALES})\."
)
_SECCION_RA = re.compile(r"^\s*Resultados de aprendizaje\b")
_SECCION_CRITERIOS = re.compile(r"^\s*Criterios de evaluaci[óo]n:?\s*$")
_SECCION_DURACION = re.compile(r"^\s*Duraci[óo]n:")
_SECCION_BASICOS = re.compile(r"^\s*Contenidos b[áa]sicos[:.]\s*$")
_SECCION_ORIENTACIONES = re.compile(r"^\s*Orientaciones pedag[óo]gicas\.?\s*$")
_RA = re.compile(r"^\s*(\d+)\.\s+(\S.*)$")
_CRITERIO = re.compile(r"^\s*([a-zñ])\)\s+(\S.*)$")
_VINETA_BOE = re.compile(r"^\s*[−–—-]\s+(\S.*)$")  # raya, menos (U+2212) y guion
_LETRAS = "abcdefghijklmnñopqrstuvwxyz"  # el orden del alfabeto español: la ñ va tras la n


def _sin_cierre_de_cita(texto: str) -> str:
    """La línea sin la comilla que cierra la cita del real decreto que modifica (``»``)."""
    return texto.rstrip().removesuffix("»").rstrip()


def analizar_modulo(lineas: Sequence[Linea], codigo_modulo: str) -> dict[str, Any]:
    """El módulo ``codigo_modulo`` de un anexo I: resultados con sus criterios, contenidos
    básicos y orientaciones, cada uno con la página del boletín en que empieza.

    ``lineas`` debe ser el artículo que reescribe el anexo (:func:`recortar_articulo`): el
    módulo tiene que aparecer una sola vez. Se para en el aviso del módulo siguiente o al
    final. Una línea que no es de ningún tipo conocido, o una letra fuera de orden, es un
    ``ValueError``: nada se pierde en silencio.

    Los contenidos básicos son encabezados (nivel 1, acaban en «:») y viñetas (nivel 2).
    Un encabezado puede abrir una página tras una viñeta que acaba en punto (el salto de
    página se lleva la línea en blanco que lo separaba), así que se reconoce por el «:» con
    que acaba.
    """
    patron = re.compile(_CODIGO_BOE.format(codigo=re.escape(codigo_modulo)))
    inicios = [i for i, l in enumerate(lineas) if patron.match(l.texto)]
    if not inicios:
        raise ValueError(f"no encuentro el módulo {codigo_modulo} en el anexo")
    if len(inicios) > 1:
        raise ValueError(
            f"el módulo {codigo_modulo} aparece más de una vez: recorta antes el artículo"
        )
    cuerpo: list[Linea] = []
    for linea in lineas[inicios[0] + 1 :]:
        if _FIN_DE_MODULO.match(linea.texto):
            break
        cuerpo.append(linea)

    def fallo(detalle: str, linea: Linea) -> ValueError:
        return ValueError(f"{codigo_modulo}: {detalle}: «{linea.texto.strip()}»")

    resultados: list[dict[str, Any]] = []
    basicos: list[dict[str, Any]] = []
    orientaciones: list[Linea] = []
    seccion = ""
    abierto: dict[str, Any] | None = None  # lo que continúa en la línea siguiente
    anterior_en_blanco = True
    anterior = ""
    for n, linea in enumerate(cuerpo):
        texto = linea.texto
        if not texto.strip():
            anterior_en_blanco = True
            if seccion == "ra":
                abierto = None
            continue
        if _SECCION_RA.match(texto):
            seccion, abierto = "ra", None
        elif _SECCION_DURACION.match(texto):
            seccion, abierto = "", None
        elif _SECCION_BASICOS.match(texto):
            seccion, abierto = "cb", None
        elif _SECCION_ORIENTACIONES.match(texto):
            seccion, abierto = "ori", None
        elif seccion == "ra":
            abierto = _linea_de_resultado(resultados, abierto, linea, fallo)
        elif seccion == "cb":
            abierto = _linea_de_basicos(basicos, abierto, cuerpo, n, anterior_en_blanco, anterior)
        elif seccion == "ori":
            orientaciones.append(linea)
        else:
            raise fallo("línea fuera de las secciones del módulo", linea)
        anterior_en_blanco = False
        anterior = texto.strip()
    if not resultados:
        raise ValueError(f"{codigo_modulo}: no hay resultados de aprendizaje")
    ori: dict[str, Any] | None = None
    if orientaciones:
        textos = [_VINETA_BOE.sub(r"\1", l.texto) for l in orientaciones]
        textos[-1] = _sin_cierre_de_cita(textos[-1])
        ori = {"texto": comun.unir(textos), "pagina": orientaciones[0].pagina}
    return {
        "codigo": codigo_modulo,
        "resultados": [
            {
                "numero": r["numero"],
                "texto": comun.unir(r["lineas"]),
                "pagina": r["pagina"],
                "criterios": [
                    {"letra": c["letra"], "texto": comun.unir(c["lineas"]), "pagina": c["pagina"]}
                    for c in r["criterios"]
                ],
            }
            for r in resultados
        ],
        "basicos": [
            {"nivel": b["nivel"], "texto": comun.unir(b["lineas"]), "pagina": b["pagina"]}
            for b in basicos
        ],
        "orientaciones": ori,
    }


def _linea_de_resultado(
    resultados: list[dict[str, Any]],
    abierto: dict[str, Any] | None,
    linea: Linea,
    fallo: Callable[[str, Linea], ValueError],
) -> dict[str, Any] | None:
    """Una línea de la sección de resultados: un resultado, un criterio o la continuación."""
    texto = linea.texto
    if _SECCION_CRITERIOS.match(texto):
        return None
    ra = _RA.match(texto)
    if ra is not None and int(ra[1]) == len(resultados) + 1:
        nuevo: dict[str, Any] = {
            "numero": ra[1],
            "lineas": [ra[2]],
            "pagina": linea.pagina,
            "criterios": [],
        }
        resultados.append(nuevo)
        return nuevo
    criterio = _CRITERIO.match(texto)
    if criterio is not None and resultados:
        previos = resultados[-1]["criterios"]
        esperada = _LETRAS[len(previos)]
        if criterio[1] != esperada:
            raise fallo(f"criterio {criterio[1]} fuera de orden (iba el {esperada})", linea)
        nuevo = {"letra": criterio[1], "lineas": [criterio[2]], "pagina": linea.pagina}
        previos.append(nuevo)
        return nuevo
    if abierto is None:
        raise fallo("línea que no es un resultado, un criterio ni su continuación", linea)
    abierto["lineas"].append(texto.strip())
    return abierto


def _linea_de_basicos(
    basicos: list[dict[str, Any]],
    abierto: dict[str, Any] | None,
    cuerpo: Sequence[Linea],
    n: int,
    anterior_en_blanco: bool,
    anterior: str,
) -> dict[str, Any]:
    """Una línea de los contenidos básicos: viñeta, encabezado o continuación de lo anterior."""
    linea = cuerpo[n]
    vineta = _VINETA_BOE.match(linea.texto)
    if vineta is not None:
        nuevo: dict[str, Any] = {"nivel": 2, "lineas": [vineta[1]], "pagina": linea.pagina}
        basicos.append(nuevo)
        return nuevo
    # un encabezado: su bloque (hasta una línea en blanco o una viñeta) acaba en «:», y empieza
    # tras un blanco o tras una frase completa
    bloque = [linea.texto.strip()]
    for siguiente in cuerpo[n + 1 :]:
        if not siguiente.texto.strip() or _VINETA_BOE.match(siguiente.texto):
            break
        bloque.append(siguiente.texto.strip())
    empieza = not basicos or anterior_en_blanco or anterior.endswith(".")
    if bloque[-1].endswith(":") and empieza:
        nuevo = {"nivel": 1, "lineas": [linea.texto.strip()], "pagina": linea.pagina}
        basicos.append(nuevo)
        return nuevo
    if abierto is None:
        raise ValueError(
            f"contenido que no es un encabezado ni una viñeta: «{linea.texto.strip()}»"
        )
    abierto["lineas"].append(linea.texto.strip())
    return abierto


def _elemento(
    codigo: str, tipo: str, texto: str, procedencia: dict[str, Any], padre: str | None
) -> dict[str, Any]:
    elemento: dict[str, Any] = {
        "codigo": codigo,
        "tipo": tipo,
        "texto": texto,
        "procedencia": procedencia,
        "orden": 0,
    }
    if padre is not None:
        elemento["padre"] = padre
    return elemento


def _arbol_de_contenidos(
    items: Sequence[Mapping[str, Any]],
    *,
    raiz: str,
    prefijo: str,
    tipo: str,
    procedencia: Callable[[int | None], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Elementos ``<prefijo>.1``, ``<prefijo>.1.2``, ``<prefijo>.1.2.1`` con sus padres."""
    elementos: list[dict[str, Any]] = []
    contadores = [0, 0, 0]
    codigos = ["", "", ""]
    for item in items:
        nivel = item["nivel"]
        contadores[nivel - 1] += 1
        for i in range(nivel, 3):
            contadores[i] = 0
        codigo = f"{prefijo}." + ".".join(str(c) for c in contadores[:nivel])
        codigos[nivel - 1] = codigo
        padre = codigos[nivel - 2] if nivel > 1 else raiz
        elementos.append(_elemento(codigo, tipo, item["texto"], procedencia(item["pagina"]), padre))
    return elementos


def elementos_del_modulo(
    modulo: Mapping[str, Any],
    *,
    ficha: str,
    norma: str,
    ubicacion: str,
    via: Mapping[str, str] | None = None,
    orden_inicial: int = 1,
) -> list[dict[str, Any]]:
    """Elementos ``RA.n``, ``RA.n.a`` (criterio), ``EST.….CB.n`` (contenido básico) y ``ORI``.

    En el orden del anexo: resultados con sus criterios, contenidos básicos y orientaciones.
    Hijos del módulo (``ficha``) los resultados, los contenidos básicos de primer nivel y las
    orientaciones. Los contenidos básicos son los del real decreto del título (estatales): su
    código lleva ``EST.`` en vez de ``MAD.``, para no mezclarlos con los de Madrid (``CO``).

    ``via``, si la norma modifica el anexo de otra («queda redactado como sigue»), da la
    norma original (``norma``) y el lugar de su anexo (``ubicacion``): la procedencia pasa a
    ser la de la norma que modifica y el original queda en ``via``.
    """
    base = f"{ubicacion}, módulo {modulo['codigo']}"

    def procedencia(sufijo: str, pagina: int | None) -> dict[str, Any]:
        dato: dict[str, Any] = {"norma": norma, "ubicacion": base + sufijo, "pagina": pagina}
        if via:
            lugar = f"{via['ubicacion']}, módulo {modulo['codigo']}{sufijo}"
            dato["via"] = [{"norma": via["norma"], "ubicacion": lugar, "pagina": None}]
        return dato

    elementos: list[dict[str, Any]] = []
    for resultado in modulo["resultados"]:
        codigo = f"{ficha}.RA.{resultado['numero']}"
        sufijo = f", resultado de aprendizaje {resultado['numero']}"
        elementos.append(
            _elemento(
                codigo,
                "resultado_aprendizaje",
                resultado["texto"],
                procedencia(sufijo, resultado["pagina"]),
                ficha,
            )
        )
        for criterio in resultado["criterios"]:
            elementos.append(
                _elemento(
                    f"{codigo}.{criterio['letra']}",
                    "criterio_fp",
                    criterio["texto"],
                    procedencia(f"{sufijo}, criterio {criterio['letra']}", criterio["pagina"]),
                    codigo,
                )
            )
    if modulo["basicos"]:
        if not ficha.startswith("MAD."):
            raise ValueError(f"{ficha}: la ficha del módulo debe empezar por «MAD.»")
        elementos += _arbol_de_contenidos(
            modulo["basicos"],
            raiz=ficha,
            prefijo="EST." + ficha[len("MAD.") :] + ".CB",
            tipo="contenido_basico",
            procedencia=lambda pagina: procedencia(", contenidos básicos", pagina),
        )
    if modulo["orientaciones"]:
        ori = modulo["orientaciones"]
        elementos.append(
            _elemento(
                f"{ficha}.ORI",
                "orientaciones",
                ori["texto"],
                procedencia(", orientaciones pedagógicas", ori["pagina"]),
                ficha,
            )
        )
    for i, elemento in enumerate(elementos, start=orden_inicial):
        elemento["orden"] = i
    return elementos


# --- contenidos de Madrid (PDF del decreto del ciclo) -------------------------------------


_CODIGO_MADRID = re.compile(r"\(\s*c[óo]digo:\s*(\w+)\s*\)", re.IGNORECASE)
_CONTENIDOS_MADRID = re.compile(r"^\s*Contenidos\s*\(\s*duraci[óo]n:?\s*\d+\s*horas\s*\)\s*$")
_ANEXO_MADRID = re.compile(r"^\s*ANEXO\b")
# el glifo de viñeta de los apartados (un carácter de control en la fuente del boletín)
_SUBVINETA = re.compile(r"^\s*\x02\s*(\S.*)$")
_MARGEN = 2  # columnas de más sobre el margen de la página que aún cuentan como el margen
_CIERRA_CON_GUION = re.compile(r"\w-$")


def _cabeceras_madrid(lineas: Sequence[Linea]) -> list[tuple[int, str]]:
    """``(índice, código)`` de cada «Módulo profesional NN: …». El código va en esa línea o en
    la siguiente, y en mayúsculas en los módulos incorporados por Madrid («CÓDIGO: CM14»)."""
    cabeceras = []
    for i, linea in enumerate(lineas):
        if not _MODULO_MADRID.match(linea.texto):
            continue
        for candidata in lineas[i : i + 3]:
            if (m := _CODIGO_MADRID.search(candidata.texto)) is not None:
                cabeceras.append((i, m[1]))
                break
        else:
            raise ValueError(f"módulo sin código: «{linea.texto.strip()}»")
    return cabeceras


def analizar_contenidos_madrid(lineas: Sequence[Linea], codigo_modulo: str) -> list[dict[str, Any]]:
    """Los contenidos de un módulo: nivel 1 (encabezado), 2 (viñeta «—») y 3 (apartado, con su
    propio glifo de viñeta, un carácter de control en la fuente del boletín).

    El módulo empieza en su «Módulo profesional NN: … (código: XXXX)» (que puede ocupar dos
    líneas) y acaba en el del siguiente o en el siguiente anexo. ``pdftotext`` sangra cada
    página respecto a su margen: lo que es un encabezado y lo que es la continuación de una
    viñeta se decide contra la sangría de las viñetas «—» de la misma página (siempre están
    en el margen del texto). Una línea sin viñeta en ese margen es un encabezado; más
    adentro, o tras una palabra partida, sigue lo anterior. Una viñeta en un lugar que no
    encaja es un ``ValueError``.
    """
    cabeceras = _cabeceras_madrid(lineas)
    posicion = next((n for n, (_, c) in enumerate(cabeceras) if c == codigo_modulo), None)
    if posicion is None:
        raise ValueError(f"no encuentro el módulo {codigo_modulo} en los contenidos de Madrid")
    inicio = cabeceras[posicion][0]
    fin = cabeceras[posicion + 1][0] if posicion + 1 < len(cabeceras) else len(lineas)
    anexo = next((i for i in range(inicio + 1, fin) if _ANEXO_MADRID.match(lineas[i].texto)), None)
    cuerpo = list(lineas[inicio + 1 : anexo if anexo is not None else fin])
    titulo = next((i for i, l in enumerate(cuerpo[:4]) if _CONTENIDOS_MADRID.match(l.texto)), None)
    if titulo is None:
        raise ValueError(f"{codigo_modulo}: no encuentro «Contenidos (duración N horas)»")
    cuerpo = [l for l in cuerpo[titulo + 1 :] if l.texto.strip()]

    # el margen de cada página: la sangría de sus viñetas o, si no tiene, la de su línea más a
    # la izquierda
    vinetas: dict[int | None, int] = {}
    for linea in cuerpo:
        if _VINETA.match(linea.texto):
            vinetas[linea.pagina] = min(vinetas.get(linea.pagina, 10**6), _sangria(linea.texto))
    margenes = {
        p: vinetas.get(p, min(_sangria(l.texto) for l in cuerpo if l.pagina == p))
        for p in {l.pagina for l in cuerpo}
    }

    items: list[dict[str, Any]] = []
    for linea in cuerpo:
        texto = linea.texto.strip()
        relativa = _sangria(linea.texto) - margenes[linea.pagina]
        ultimo = items[-1] if items else None
        vineta = _VINETA.match(linea.texto)
        subvineta = _SUBVINETA.match(linea.texto)
        if vineta is not None and relativa <= _MARGEN:
            items.append({"nivel": 2, "lineas": [vineta[1]], "pagina": linea.pagina})
        elif subvineta is not None and ultimo is not None and ultimo["nivel"] >= 2:
            items.append({"nivel": 3, "lineas": [subvineta[1]], "pagina": linea.pagina})
        elif vineta is not None or subvineta is not None:
            raise ValueError(f"viñeta en un lugar que no está previsto: «{texto}»")
        elif ultimo is None:
            if relativa > _MARGEN:
                raise ValueError(f"el módulo {codigo_modulo} empieza sin encabezado: «{texto}»")
            items.append({"nivel": 1, "lineas": [texto], "pagina": linea.pagina})
        elif _CIERRA_CON_GUION.search(ultimo["lineas"][-1]):
            ultimo["lineas"].append(texto)  # una palabra partida
        elif relativa > _MARGEN or (
            ultimo["nivel"] == 1 and not ultimo["lineas"][-1].endswith(":")
        ):
            ultimo["lineas"].append(texto)  # la línea siguiente de lo mismo
        else:
            items.append({"nivel": 1, "lineas": [texto], "pagina": linea.pagina})
    return [
        {"nivel": i["nivel"], "texto": comun.unir(i["lineas"]), "pagina": i["pagina"]}
        for i in items
    ]


def elementos_de_contenidos(
    items: Sequence[Mapping[str, Any]],
    *,
    ficha: str,
    norma: str,
    ubicacion: str,
    orden_inicial: int = 1,
) -> list[dict[str, Any]]:
    """Elementos ``contenido`` de Madrid (``CO.1``, ``CO.1.2``, ``CO.1.2.1``) con sus padres.

    Los ``contenido_basico`` (``CB.n``) son los estatales del real decreto del título: no se
    mezclan con estos.
    """
    elementos = _arbol_de_contenidos(
        items,
        raiz=ficha,
        prefijo=f"{ficha}.CO",
        tipo="contenido",
        procedencia=lambda pagina: {"norma": norma, "ubicacion": ubicacion, "pagina": pagina},
    )
    for i, elemento in enumerate(elementos, start=orden_inicial):
        elemento["orden"] = i
    return elementos


# --- horas y curso (tabla del anexo II) -------------------------------------------------------


class FilaHoras(NamedTuple):
    """La fila de un módulo en la tabla de organización académica.

    ``curso`` es ``None`` si la tabla no le pone horas semanales en ningún curso (el proyecto
    intermodular se desarrolla a lo largo de los dos cursos).
    """

    nombre: str
    horas: int
    curso: str | None
    pagina: int | None


def analizar_horas_curso(lineas: Sequence[Linea], *, ciclo: str, codigo_modulo: str) -> FilaHoras:
    """La fila de ``codigo_modulo`` en la tabla del ciclo ``ciclo`` (anexo II).

    Las horas son la primera cifra de la fila; el curso, la columna («Curso 1º» o «Curso 2º»)
    más cercana a la última cifra, que son las horas semanales (si la fila trae tres celdas:
    horas, créditos ECTS y horas semanales). La denominación puede seguir en la línea de abajo.
    """
    inicio = next(
        (i for i, l in enumerate(lineas) if "Ciclo Formativo:" in l.texto and ciclo in l.texto),
        None,
    )
    if inicio is None:
        raise ValueError(f"no encuentro el ciclo «{ciclo}»")
    columnas: tuple[int, int] | None = None
    for i in range(inicio + 1, len(lineas)):
        linea = lineas[i]
        if "Ciclo Formativo:" in linea.texto or "HORAS TOTALES" in linea.texto:
            break
        if "Curso 1º" in linea.texto and "Curso 2º" in linea.texto:
            columnas = (linea.texto.index("Curso 1º"), linea.texto.index("Curso 2º"))
            continue
        fila = re.match(rf"^\s*{re.escape(codigo_modulo)}\s+(.*?)\s{{2,}}(\d.*)$", linea.texto)
        if fila is None:
            continue
        if columnas is None:
            raise ValueError("la tabla no tiene las columnas «Curso 1º» y «Curso 2º»")
        celdas = [(fila.start(2) + c.start(), c[0]) for c in re.finditer(r"\S+", fila[2])]
        if not celdas[0][1].isdigit():
            raise ValueError(f"{codigo_modulo}: la fila no empieza por las horas")
        nombre = fila[1]
        # la denominación sigue en la línea de abajo: sin cifras y más adentro que el código
        if i + 1 < len(lineas):
            siguiente = lineas[i + 1].texto
            if (
                siguiente.strip()
                and not re.search(r"\d", siguiente)
                and "HORAS TOTALES" not in siguiente
                and _sangria(siguiente) > _sangria(linea.texto)
            ):
                nombre += " " + siguiente.strip()
        curso = None
        if len(celdas) >= 3:
            posicion = celdas[-1][0]
            curso = "1" if abs(posicion - columnas[0]) <= abs(posicion - columnas[1]) else "2"
        return FilaHoras(comun.unir([nombre]), int(celdas[0][1]), curso, linea.pagina)
    raise ValueError(f"no encuentro el módulo {codigo_modulo} en la tabla de «{ciclo}»")


def elemento_modulo(
    nombre: str,
    horas: int,
    curso: str,
    *,
    ficha: str,
    norma: str,
    ubicacion: str,
    pagina: int | None,
    orden: int = 1,
) -> dict[str, Any]:
    return {
        "codigo": ficha,
        "tipo": "modulo",
        "texto": nombre,
        "procedencia": {"norma": norma, "ubicacion": ubicacion, "pagina": pagina},
        "orden": orden,
        "datos": {"horas": horas, "curso": curso},
    }


# --- el título: identificación, competencias y objetivos --------------------------------------

# Dónde están en el real decreto del título (RD 450/2010 y los que lo reescriben).
ARTICULO_IDENTIFICACION = 2
ARTICULO_COMPETENCIA_GENERAL = 4
ARTICULO_COMPETENCIAS = 5
ARTICULO_OBJETIVOS = 9
_DATO_DE_IDENTIFICACION = re.compile(r"^\s*([A-ZÁÉÍÓÚÑ][^:]{2,120}):(?:\s+\S.*|\s*)$")


def articulo_reescrito(lineas: Sequence[Linea], numero: int) -> tuple[str, list[Linea]]:
    """``(apartado, cuerpo)`` del artículo ``numero`` que un real decreto reescribe.

    El apartado es el ordinal en letra con que empieza («Uno», «Dos»…) y el cuerpo, las líneas
    del artículo entre comillas, tras su encabezado y hasta la comilla de cierre (sin ella).
    """
    inicio = next(
        (
            (i, m[1])
            for i, l in enumerate(lineas)
            if (
                m := re.match(
                    rf"^\s*(\w+)\.\s+El art[íi]culo\s+{numero}\s+queda redactado", l.texto
                )
            )
        ),
        None,
    )
    if inicio is None:
        raise ValueError(f"no encuentro el apartado que reescribe el artículo {numero}")
    encabezado = next(
        (
            k
            for k in range(inicio[0] + 1, len(lineas))
            if re.match(rf"^\s*«\s*Art[íi]culo\s+{numero}\.", lineas[k].texto)
        ),
        None,
    )
    if encabezado is None:
        raise ValueError(f"no encuentro «Artículo {numero}.» tras el apartado {inicio[1]}")
    cuerpo: list[Linea] = []
    for linea in lineas[encabezado + 1 :]:
        cuerpo.append(linea)
        if linea.texto.rstrip().endswith("»"):
            cuerpo[-1] = Linea(_sin_cierre_de_cita(linea.texto), linea.pagina)
            return inicio[1], cuerpo
    raise ValueError(f"el artículo {numero} no acaba en «»»")


def partir_identificacion(cuerpo: Sequence[Linea]) -> list[dict[str, Any]]:
    """Los datos de «El título … queda identificado por los siguientes elementos:».

    Cada dato empieza en «Etiqueta:» (y su valor puede seguir en la línea de abajo); su
    ``lugar`` es la etiqueta.
    """
    intro = next(
        (i for i, l in enumerate(cuerpo) if l.texto.rstrip().endswith("siguientes elementos:")),
        None,
    )
    if intro is None:
        raise ValueError("no encuentro «siguientes elementos:» en la identificación")
    datos: list[dict[str, Any]] = []
    for linea in cuerpo[intro + 1 :]:
        if not linea.texto.strip():
            continue
        dato = _DATO_DE_IDENTIFICACION.match(linea.texto)
        if dato is not None:
            datos.append(
                {"lugar": dato[1].strip(), "lineas": [linea.texto], "pagina": linea.pagina}
            )
        elif datos:
            datos[-1]["lineas"].append(linea.texto)
        else:
            raise ValueError(f"línea suelta antes del primer dato: «{linea.texto.strip()}»")
    if not datos:
        raise ValueError("la identificación no trae ningún dato")
    return [
        {"lugar": d["lugar"], "texto": comun.unir(d["lineas"]), "pagina": d["pagina"]}
        for d in datos
    ]


def partir_letras(cuerpo: Sequence[Linea]) -> list[dict[str, Any]]:
    """Los apartados «a) …» de una lista, en el orden del alfabeto español (la ñ tras la n).

    El texto anterior a «a)» (la frase que presenta la lista) no cuenta.
    """
    elementos: list[dict[str, Any]] = []
    for linea in cuerpo:
        letra = _CRITERIO.match(linea.texto)
        if letra is not None:
            esperada = _LETRAS[len(elementos)]
            if letra[1] != esperada:
                raise ValueError(f"letra {letra[1]} fuera de orden (iba la {esperada})")
            elementos.append(
                {
                    "clave": letra[1],
                    "lugar": f"letra {letra[1]}",
                    "lineas": [letra[2]],
                    "pagina": linea.pagina,
                }
            )
        elif elementos and linea.texto.strip():
            elementos[-1]["lineas"].append(linea.texto)
    if not elementos:
        raise ValueError("no hay ningún apartado «a)»")
    return [
        {
            "clave": e["clave"],
            "lugar": e["lugar"],
            "texto": comun.unir(e["lineas"]),
            "pagina": e["pagina"],
        }
        for e in elementos
    ]


def articulo_original(lineas: Sequence[Linea], numero: int) -> dict[str, Any]:
    """El texto del «Artículo N.» de un real decreto sin reescribir: ``{texto, pagina}``."""
    inicio = next(
        (i for i, l in enumerate(lineas) if re.match(rf"^\s*Art[íi]culo\s+{numero}\.\s", l.texto)),
        None,
    )
    if inicio is None:
        raise ValueError(f"no encuentro el artículo {numero}")
    cuerpo = []
    for linea in lineas[inicio + 1 :]:
        if re.match(r"^\s*Art[íi]culo\s+\d+\.\s", linea.texto):
            break
        if linea.texto.strip():
            cuerpo.append(linea)
    if not cuerpo:
        raise ValueError(f"el artículo {numero} está vacío")
    return {"texto": comun.unir(l.texto for l in cuerpo), "pagina": cuerpo[0].pagina}


def parrafo_anadido(lineas: Sequence[Linea], numero: int) -> dict[str, Any]:
    """El párrafo entre comillas que «se añade un nuevo párrafo final al artículo N»."""
    inicio = next(
        (
            i
            for i, l in enumerate(lineas)
            if re.search(rf"p[áa]rrafo final al art[íi]culo\s+{numero}\b", l.texto)
        ),
        None,
    )
    cita = None
    if inicio is not None:
        cita = next(
            (k for k in range(inicio + 1, len(lineas)) if lineas[k].texto.strip()),
            None,
        )
    if cita is None or not lineas[cita].texto.strip().startswith("«"):
        raise ValueError(f"no encuentro el párrafo que se añade al artículo {numero}")
    cuerpo: list[str] = []
    for linea in lineas[cita:]:
        cuerpo.append(linea.texto.strip())
        if linea.texto.rstrip().endswith("»"):
            texto = comun.unir(cuerpo).removeprefix("«").removesuffix("»").strip()
            return {"texto": texto, "pagina": lineas[cita].pagina}
    raise ValueError(f"el párrafo que se añade al artículo {numero} no acaba en «»»")


def elementos_del_titulo(
    *,
    ficha: str,
    norma: str,
    ubicacion: str,
    original: str,
    identificacion: tuple[str, Sequence[Mapping[str, Any]]],
    competencias: tuple[str, Sequence[Mapping[str, Any]]],
    objetivos: tuple[str, Sequence[Mapping[str, Any]]],
    general: Mapping[str, Any] | None = None,
    adicion: Mapping[str, Any] | None = None,
    norma_adicion: str | None = None,
    ubicacion_adicion: str = "artículo segundo",
) -> list[dict[str, Any]]:
    """Elementos de la ficha del título (``ficha``, p. ej. ``MAD.DAM``), sin padre.

    * ``TIT.n`` (``titulo``): un dato de la identificación (art. 2) cada uno; el párrafo que
      otra norma añade al artículo (``adicion``) es el último;
    * ``CG`` (``competencia_general``, art. 4 del real decreto original, sin vía);
    * ``CP.a`` (``competencia_profesional``, art. 5) y ``OG.a`` (``objetivo_general``, art. 9).

    Lo que reescribe la norma ``norma`` (``ubicacion``: «artículo segundo») lleva esa
    procedencia y, en ``via``, el lugar del real decreto ``original``; las tuplas son
    ``(apartado, elementos)`` de :func:`articulo_reescrito` y de las funciones de partir.
    """

    def procedencia(apartado: str, articulo: int, lugar: str, pagina: int | None) -> dict[str, Any]:
        return {
            "norma": norma,
            "ubicacion": f"{ubicacion}, apartado {apartado} (artículo {articulo}), {lugar}",
            "pagina": pagina,
            "via": [
                {"norma": original, "ubicacion": f"artículo {articulo}, {lugar}", "pagina": None}
            ],
        }

    elementos: list[dict[str, Any]] = []
    apartado, datos = identificacion
    for n, dato in enumerate(datos, start=1):
        elementos.append(
            _elemento(
                f"{ficha}.TIT.{n}",
                "titulo",
                dato["texto"],
                procedencia(apartado, ARTICULO_IDENTIFICACION, dato["lugar"], dato["pagina"]),
                None,
            )
        )
    if adicion is not None:
        if norma_adicion is None:
            raise ValueError("el párrafo que se añade necesita la norma que lo añade")
        elementos.append(
            _elemento(
                f"{ficha}.TIT.{len(datos) + 1}",
                "titulo",
                adicion["texto"],
                {
                    "norma": norma_adicion,
                    "ubicacion": (
                        f"{ubicacion_adicion} (párrafo final que se añade al artículo "
                        f"{ARTICULO_IDENTIFICACION})"
                    ),
                    "pagina": adicion["pagina"],
                    "via": [
                        {
                            "norma": original,
                            "ubicacion": f"artículo {ARTICULO_IDENTIFICACION}",
                            "pagina": None,
                        }
                    ],
                },
                None,
            )
        )
    if general is not None:
        elementos.append(
            _elemento(
                f"{ficha}.CG",
                "competencia_general",
                general["texto"],
                {
                    "norma": original,
                    "ubicacion": f"artículo {ARTICULO_COMPETENCIA_GENERAL}",
                    "pagina": general["pagina"],
                },
                None,
            )
        )
    for (apartado, letras), articulo, sigla, tipo in (
        (competencias, ARTICULO_COMPETENCIAS, "CP", "competencia_profesional"),
        (objetivos, ARTICULO_OBJETIVOS, "OG", "objetivo_general"),
    ):
        for letra in letras:
            elementos.append(
                _elemento(
                    f"{ficha}.{sigla}.{letra['clave']}",
                    tipo,
                    letra["texto"],
                    procedencia(apartado, articulo, letra["lugar"], letra["pagina"]),
                    None,
                )
            )
    for i, elemento in enumerate(elementos, start=1):
        elemento["orden"] = i
    return elementos


def _ficha_de_fp(
    codigo: str,
    nombre: str,
    curso: str | None,
    cursos_academicos: str,
    normas: Sequence[str],
    elementos: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "codigo": codigo,
        "nombre": nombre,
        "etapa": "fp_gs",
        "curso": curso,
        "cursos_academicos": cursos_academicos.split(","),
        "normas": list(dict.fromkeys(normas)),
        "elementos": elementos,
    }


def _extraer_modulo(args: argparse.Namespace) -> dict[str, Any]:
    articulo = recortar_articulo(
        comun.lineas_limpias(comun.texto_de_norma(args.cache, args.boe)), args.articulo
    )
    modulo = analizar_modulo(articulo, args.modulo)
    fila = analizar_horas_curso(
        comun.lineas_limpias(comun.texto_de_norma(args.cache, args.horas)),
        ciclo=args.ciclo,
        codigo_modulo=args.modulo,
    )
    if fila.curso is None and args.curso is None:
        raise SystemExit(
            f"{args.modulo}: la tabla no le pone curso; decídelo con --curso y explícalo "
            "en fuentes.toml"
        )
    if fila.curso is not None and args.curso not in (None, fila.curso):
        raise SystemExit(f"{args.modulo}: la tabla pone el curso {fila.curso}, no el {args.curso}")
    curso = fila.curso or args.curso
    elementos = [
        elemento_modulo(
            fila.nombre,
            fila.horas,
            curso,
            ficha=args.ficha,
            norma=args.horas,
            ubicacion=args.ubicacion_horas,
            pagina=fila.pagina,
        )
    ]
    via = {"norma": args.via, "ubicacion": args.ubicacion_via} if args.via else None
    elementos += elementos_del_modulo(
        modulo,
        ficha=args.ficha,
        norma=args.boe,
        ubicacion=args.ubicacion_boe,
        via=via,
        orden_inicial=len(elementos) + 1,
    )
    normas = [args.boe, *([args.via] if args.via else [])]
    if not args.sin_contenidos_madrid:
        contenidos = analizar_contenidos_madrid(
            comun.lineas_limpias(comun.texto_de_norma(args.cache, args.madrid)), args.modulo
        )
        elementos += elementos_de_contenidos(
            contenidos,
            ficha=args.ficha,
            norma=args.madrid,
            ubicacion=args.ubicacion_madrid,
            orden_inicial=len(elementos) + 1,
        )
        normas.append(args.madrid)
    normas.append(args.horas)
    return _ficha_de_fp(args.ficha, fila.nombre, curso, args.cursos_academicos, normas, elementos)


def _extraer_titulo(args: argparse.Namespace) -> dict[str, Any]:
    articulo = recortar_articulo(
        comun.lineas_limpias(comun.texto_de_norma(args.cache, args.boe)), args.articulo
    )
    identificacion = articulo_reescrito(articulo, ARTICULO_IDENTIFICACION)
    if args.nombre not in comun.unir(l.texto for l in identificacion[1]):
        raise ValueError(f"«{args.nombre}» no figura en el artículo {ARTICULO_IDENTIFICACION}")
    original = comun.lineas_limpias(comun.texto_de_norma(args.cache, args.original))
    adicion = None
    if args.adicion:
        adicion = parrafo_anadido(
            comun.lineas_limpias(comun.texto_de_norma(args.cache, args.adicion)),
            ARTICULO_IDENTIFICACION,
        )
    elementos = elementos_del_titulo(
        ficha=args.ficha,
        norma=args.boe,
        ubicacion=f"artículo {args.articulo}",
        original=args.original,
        identificacion=(
            identificacion[0],
            partir_identificacion(identificacion[1]),
        ),
        competencias=_letras(articulo, ARTICULO_COMPETENCIAS),
        objetivos=_letras(articulo, ARTICULO_OBJETIVOS),
        general=articulo_original(original, ARTICULO_COMPETENCIA_GENERAL),
        adicion=adicion,
        norma_adicion=args.adicion,
    )
    normas = [args.boe, args.original, *([args.adicion] if args.adicion else [])]
    return _ficha_de_fp(args.ficha, args.nombre, None, args.cursos_academicos, normas, elementos)


def _letras(articulo: Sequence[Linea], numero: int) -> tuple[str, list[dict[str, Any]]]:
    apartado, cuerpo = articulo_reescrito(articulo, numero)
    return apartado, partir_letras(cuerpo)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Extrae un módulo, o el título, de un ciclo de FP de grado superior."
    )
    sub = ap.add_subparsers(dest="orden", required=True)

    comunes = argparse.ArgumentParser(add_help=False)
    comunes.add_argument("--ficha", required=True, help="código de la ficha, p. ej. MAD.DAM.0485")
    comunes.add_argument("--cursos-academicos", required=True, help="separados por comas")
    comunes.add_argument("--cache", type=Path, required=True)
    comunes.add_argument(
        "--boe", required=True, help="id de la norma que reescribe el título (RD 405/2023)"
    )
    comunes.add_argument("--articulo", default="segundo", help="ordinal del artículo que lo hace")
    comunes.add_argument(
        "--salida", type=Path, help="carpeta de datos (por defecto, la del paquete)"
    )

    m = sub.add_parser("modulo", parents=[comunes], help="un módulo profesional")
    m.add_argument("--modulo", required=True, help="código del módulo, p. ej. 0485")
    m.add_argument("--ciclo", required=True, help="nombre del ciclo en la tabla de horas")
    m.add_argument(
        "--ubicacion-boe",
        required=True,
        help="dónde está el anexo en esa norma, p. ej. «artículo segundo, apartado Seis (anexo I)»",
    )
    m.add_argument("--via", help="id del real decreto original, del que ese anexo es reescritura")
    m.add_argument("--ubicacion-via", default="anexo I")
    m.add_argument("--madrid", required=True, help="id de la norma con los contenidos de Madrid")
    m.add_argument("--ubicacion-madrid", default="anexo I")
    m.add_argument(
        "--sin-contenidos-madrid",
        action="store_true",
        help="el decreto de Madrid no trae contenidos para este módulo (el proyecto)",
    )
    m.add_argument("--horas", required=True, help="id de la norma con la tabla de horas")
    m.add_argument("--ubicacion-horas", default="anexo II")
    m.add_argument(
        "--curso", help="solo si la tabla no pone el curso del módulo (el proyecto intermodular)"
    )

    t = sub.add_parser("titulo", parents=[comunes], help="el título (identificación y perfil)")
    t.add_argument("--nombre", required=True, help="nombre del título, como en el artículo 2")
    t.add_argument("--original", required=True, help="id del real decreto original (RD 450/2010)")
    t.add_argument(
        "--adicion", help="id de la norma que añade un párrafo final al artículo 2 (RD 500/2024)"
    )

    args = ap.parse_args(argv)
    ficha = _extraer_modulo(args) if args.orden == "modulo" else _extraer_titulo(args)
    raiz = args.salida or Path(str(files("tiza.normativa").joinpath("datos")))
    print(escribir_ficha(ficha, raiz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
