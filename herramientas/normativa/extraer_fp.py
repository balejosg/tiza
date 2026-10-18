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

``transversal`` extrae un módulo transversal (Itinerario, Inglés, Digitalización,
Sostenibilidad): resultados, criterios y contenidos de la Orden 3537/2025 de Madrid (el currículo que se
aplica allí; el mínimo estatal del RD 659/2023 se cita solo en las normas de la ficha),
cuyo PDF sale cifrado de ``pdftotext`` y se lee descifrado (:mod:`.cifrado`, declarado en
``fuentes.toml``); y horas y curso de la tabla del decreto de planes de estudios.

``optativo`` extrae un módulo optativo del catálogo de Madrid: su currículo (resultados,
criterios y contenidos) es el anexo II de la Orden 3536/2025, que no deja espacio tras el
número de resultado («1.Reconoce»); sus horas salen del encabezado del módulo y se cruzan con
las del catálogo (anexo I en la redacción de la Orden 3822/2026), de donde sale también el
curso de los transversales. La corrección «Phyton»→«Python» de la Orden 3822/2026 se aplica
con las ``sustituciones`` que declara ``fuentes.toml``.

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
_LETRAS = "abcdefghijklmnñopqrstuvwxyz"  # el orden del alfabeto español: la ñ va tras la n
_ESTRUCTURA_FIN_ORDEN = re.compile(r"^\s*(?:ANEXO\s+[IVX]+\s*$|\(\d{2}/\d+\.\d+/\d{2}\)\s*$)")
_MODULO_ORDEN = r"^\s*M[óo]dulo profesional\s+{codigo}\."
_APARTADO_ORDEN = re.compile(r"^\s*(\d+)\.\s+(\S.*)$")
_LETRA_ORDEN = re.compile(r"^\s*([a-zñ])\)\s*(\S.*)$")
_CRITERIO_ORDEN = _LETRA_ORDEN


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
        textos = [comun.VINETA.sub(r"\1", l.texto) for l in orientaciones]
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
    vineta = comun.VINETA.match(linea.texto)
    if vineta is not None:
        nuevo: dict[str, Any] = {"nivel": 2, "lineas": [vineta[1]], "pagina": linea.pagina}
        basicos.append(nuevo)
        return nuevo
    # un encabezado: su bloque (hasta una línea en blanco o una viñeta) acaba en «:», y empieza
    # tras un blanco o tras una frase completa
    bloque = [linea.texto.strip()]
    for siguiente in cuerpo[n + 1 :]:
        if not siguiente.texto.strip() or comun.VINETA.match(siguiente.texto):
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
        dato = procedencia(sufijo, resultado["pagina"])
        elementos.append(
            _elemento(codigo, "resultado_aprendizaje", resultado["texto"], dato, ficha)
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


# --- resultados y criterios de una orden de Madrid (módulos transversales) --------------------


def analizar_resultados_orden(lineas: Sequence[Linea], codigo_modulo: str) -> dict[str, Any]:
    """Los resultados de aprendizaje y criterios de evaluación de un módulo transversal en la
    Orden 3537/2025, con la forma de :func:`analizar_modulo` (sin contenidos básicos ni
    orientaciones: los contenidos son aparte, :func:`analizar_contenidos_orden`).

    El bloque va desde «Resultados de aprendizaje y criterios de evaluación» hasta
    «Contenidos:». Los resultados («1. …») y las letras («a) …», a veces pegada al texto) van
    por orden y cada uno con la página en que empieza; lo que no encaja es un ``ValueError``.
    """
    patron = re.compile(_MODULO_ORDEN.format(codigo=re.escape(codigo_modulo)))
    inicio = next((i for i, l in enumerate(lineas) if patron.match(l.texto)), None)
    if inicio is None:
        raise ValueError(f"no encuentro el módulo {codigo_modulo} en la orden")
    return _resultados_del_cuerpo(lineas[inicio + 1 :], codigo_modulo, _RA)


def _resultados_del_cuerpo(
    cuerpo: Sequence[Linea], codigo_modulo: str, patron_ra: re.Pattern[str]
) -> dict[str, Any]:
    """Los resultados y criterios del cuerpo de un módulo (tras su encabezado).

    ``patron_ra`` es lo que abre un resultado: el anexo II de la Orden 3536/2025 no deja
    espacio tras el número («1.Reconoce»).
    """
    desde = next((i for i, l in enumerate(cuerpo) if _SECCION_RA.match(l.texto)), None)
    hasta = next(
        (i for i, l in enumerate(cuerpo) if re.match(r"^\s*Contenidos:\s*$", l.texto)), None
    )
    if desde is None or hasta is None or hasta < desde:
        raise ValueError(f"{codigo_modulo}: no encuentro los resultados de aprendizaje")
    resultados: list[dict[str, Any]] = []
    abierto: dict[str, Any] | None = None
    for linea in cuerpo[desde + 1 : hasta]:
        if not linea.texto.strip():
            continue
        ra = patron_ra.match(linea.texto)
        criterio = _CRITERIO_ORDEN.match(linea.texto)
        if ra is not None and int(ra[1]) == len(resultados) + 1:
            abierto = {"numero": ra[1], "lineas": [ra[2]], "pagina": linea.pagina, "criterios": []}
            resultados.append(abierto)
        elif criterio is not None and resultados:
            previos = resultados[-1]["criterios"]
            esperada = _LETRAS[len(previos)]
            if criterio[1] != esperada:
                raise ValueError(
                    f"{codigo_modulo}: criterio {criterio[1]} fuera de orden (iba el {esperada})"
                )
            abierto = {"letra": criterio[1], "lineas": [criterio[2]], "pagina": linea.pagina}
            previos.append(abierto)
        elif abierto is not None:
            abierto["lineas"].append(linea.texto.strip())
        else:
            raise ValueError(f"{codigo_modulo}: línea suelta antes del primer resultado")
    if not resultados:
        raise ValueError(f"{codigo_modulo}: no hay resultados de aprendizaje")
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
        "basicos": [],
        "orientaciones": None,
    }


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
        if comun.VINETA.match(linea.texto):
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
        vineta = comun.VINETA.match(linea.texto)
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


def analizar_contenidos_orden(lineas: Sequence[Linea], codigo_modulo: str) -> list[dict[str, Any]]:
    """Los contenidos de un módulo transversal en la Orden 3537/2025: apartados «1. …» (nivel 1)
    y sus letras «a) …» (nivel 2, a veces pegada al texto: «m)Gustos»).

    El módulo empieza en su «Módulo profesional NNNN. …» y el bloque, en «Contenidos:»; acaba
    en el siguiente anexo o en el sello final del boletín («(03/13.366/25)»). Los números y
    las letras van por orden: lo que no encaja es un ``ValueError``, no se interpreta a medias.
    La sangría de ``pdftotext`` cambia de una página a otra y no se usa.
    """
    patron = re.compile(_MODULO_ORDEN.format(codigo=re.escape(codigo_modulo)))
    inicio = next((i for i, l in enumerate(lineas) if patron.match(l.texto)), None)
    if inicio is None:
        raise ValueError(f"no encuentro el módulo {codigo_modulo} en la orden")
    fin = next(
        (i for i in range(inicio + 1, len(lineas)) if _ESTRUCTURA_FIN_ORDEN.match(lineas[i].texto)),
        len(lineas),
    )
    return _contenidos_del_cuerpo(lineas[inicio + 1 : fin], codigo_modulo, _APARTADO_ORDEN)


_ROMANOS = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x")
_ROMANO = re.compile(r"^\s*([ivx]+)\.\s+(\S.*)$")


def _contenidos_del_cuerpo(
    cuerpo: Sequence[Linea],
    codigo_modulo: str,
    patron_apartado: re.Pattern[str],
    *,
    libre: bool = False,
) -> list[dict[str, Any]]:
    """Los contenidos del cuerpo de un módulo, de «Contenidos:» al final del cuerpo.

    Con ``libre`` (los optativos del anexo II de la Orden 3536/2025) admite además los
    subapartados en romanos («i. …», nivel 3, bajo una letra) y que un módulo no numere sus
    títulos (CMO-310): si lo primero tras «Contenidos:» no es «1. …», cada título es una línea
    sin marca que sigue a un punto y está menos sangrada que la letra anterior, o que sigue a
    otro título. La sangría cambia de una página a otra, así que si la letra anterior está en
    otra página no se adivina: es un ``ValueError``.
    """
    titulo = next(
        (i for i, l in enumerate(cuerpo) if re.match(r"^\s*Contenidos:\s*$", l.texto)), None
    )
    if titulo is None:
        raise ValueError(f"{codigo_modulo}: no encuentro «Contenidos:»")
    items: list[dict[str, Any]] = []
    apartados = letras = romanos = 0
    sin_numerar = False
    letra_previa: Linea | None = None  # la línea de la última letra, para comparar sangrías
    anterior = ""
    for linea in cuerpo[titulo + 1 :]:
        if not linea.texto.strip():
            continue
        apartado = patron_apartado.match(linea.texto)
        letra = _LETRA_ORDEN.match(linea.texto)
        romano = _ROMANO.match(linea.texto) if libre else None
        if libre and not items and apartado is None:
            sin_numerar = True
        if apartado is not None and not sin_numerar:
            if int(apartado[1]) != apartados + 1:
                raise ValueError(
                    f"{codigo_modulo}: apartado {apartado[1]} fuera de orden (iba el {apartados + 1})"
                )
            apartados, letras, romanos = apartados + 1, 0, 0
            items.append({"nivel": 1, "lineas": [apartado[2]], "pagina": linea.pagina})
        elif letra is not None and apartados:
            if letra[1] != _LETRAS[letras]:
                raise ValueError(
                    f"{codigo_modulo}: letra {letra[1]} fuera de orden (iba la {_LETRAS[letras]})"
                )
            letras, romanos, letra_previa = letras + 1, 0, linea
            items.append({"nivel": 2, "lineas": [letra[2]], "pagina": linea.pagina})
        elif (
            romano is not None
            and items
            and items[-1]["nivel"] >= 2
            and romano[1] == _ROMANOS[romanos]
        ):
            romanos += 1
            items.append({"nivel": 3, "lineas": [romano[2]], "pagina": linea.pagina})
        elif sin_numerar and _es_titulo(linea, anterior, items, letra_previa, codigo_modulo):
            apartados, letras, romanos = apartados + 1, 0, 0
            items.append({"nivel": 1, "lineas": [linea.texto.strip()], "pagina": linea.pagina})
        elif items:
            items[-1]["lineas"].append(linea.texto.strip())
        else:
            raise ValueError(f"{codigo_modulo}: texto antes del primer apartado: «{linea.texto}»")
        anterior = linea.texto
    if not items:
        raise ValueError(f"{codigo_modulo}: «Contenidos:» está vacío")
    return [
        {"nivel": i["nivel"], "texto": comun.unir(i["lineas"]), "pagina": i["pagina"]}
        for i in items
    ]


def _es_titulo(
    linea: Linea,
    anterior: str,
    items: Sequence[Mapping[str, Any]],
    letra_previa: Linea | None,
    codigo_modulo: str,
) -> bool:
    """¿Una línea sin marca de un módulo sin títulos numerados abre un título nuevo?"""
    if not items:
        return True
    if not anterior.rstrip().endswith("."):
        return False  # la frase anterior no ha acabado: es su continuación
    if items[-1]["nivel"] == 1:
        return True  # tras un título que acaba, otro título
    if letra_previa is None or letra_previa.pagina != linea.pagina:
        raise ValueError(
            f"{codigo_modulo}: no sé si «{linea.texto.strip()}» es un título o la continuación "
            "de la letra anterior (otra página: la sangría no sirve)"
        )
    return _sangria(linea.texto) < _sangria(letra_previa.texto)


# --- módulos optativos: anexo II de la Orden 3536/2025 y catálogo del anexo I -----------------

_RA_OPTATIVO = re.compile(r"^\s*(\d+)\.\s*(\S.*)$")  # «1.Reconoce»: sin espacio tras el número
_UN_OPTATIVO = re.compile(r"^\s*CMO-\s*\d{3}\b")
_FIN_DE_OPTATIVO = re.compile(
    r"^\s*(?:[A-Z]\)\s+M[óo]dulos profesionales|ANEXO\b|\(\d{2}/\d+\.\d+/\d{2}\)\s*$)"
)
_ENCABEZADO_OPTATIVO = re.compile(
    r"CMO-\s*\d{3}\s+(?P<nombre>.+?)(?:\s*\((?P<horas>\d+)\s+horas\))?\.?"
)


class Optativo(NamedTuple):
    """Un módulo optativo tal como lo trae el anexo II: su encabezado y su currículo.

    ``horas`` es ``None`` en los transversales (el anexo II no se las pone); ``modulo`` tiene
    la forma de :func:`analizar_modulo` y ``contenidos`` la de :func:`analizar_contenidos_orden`.
    """

    nombre: str
    horas: int | None
    pagina: int | None
    modulo: dict[str, Any]
    contenidos: list[dict[str, Any]]


def analizar_optativo(
    lineas: Sequence[Linea],
    codigo_modulo: str,
    sustituciones: Sequence[tuple[str, str]] = (),
) -> Optativo:
    """El módulo ``codigo_modulo`` («CMO-316») en el anexo II de la Orden 3536/2025.

    Empieza en su encabezado («CMO-316 Programación en Phyton (90 horas).», que puede saltar
    de línea) y acaba en el siguiente módulo, en el apartado B) o en el final del boletín.
    ``sustituciones`` son pares (incorrecto, correcto) de una corrección de errores declarada
    en ``fuentes.toml`` (Orden 3822/2026, disposición adicional única: Phyton→Python): se
    aplican al texto antes de partirlo, y es lo único que se cambia. Lo que no encaja es un
    ``ValueError``.
    """
    aplicadas = [
        Linea(_sustituir(l.texto, sustituciones), l.pagina) if sustituciones else l for l in lineas
    ]
    numero = re.escape(codigo_modulo.removeprefix("CMO-"))
    # el encabezado, no el código a secas (el catálogo del anexo I lo cita antes): el que
    # tiene «Resultados de aprendizaje…» en las líneas siguientes
    inicio = next(
        (
            i
            for i, l in enumerate(aplicadas)
            if re.match(rf"^\s*CMO-\s*{numero}\b", l.texto)
            and any(_SECCION_RA.match(m.texto) for m in aplicadas[i + 1 : i + 4])
        ),
        None,
    )
    if inicio is None:
        raise ValueError(f"no encuentro el módulo {codigo_modulo} en la orden")
    fin = next(
        (
            i
            for i in range(inicio + 1, len(aplicadas))
            if _UN_OPTATIVO.match(aplicadas[i].texto) or _FIN_DE_OPTATIVO.match(aplicadas[i].texto)
        ),
        len(aplicadas),
    )
    cuerpo = aplicadas[inicio + 1 : fin]
    desde = next((i for i, l in enumerate(cuerpo) if _SECCION_RA.match(l.texto)), None)
    if desde is None:
        raise ValueError(f"{codigo_modulo}: no encuentro los resultados de aprendizaje")
    encabezado = comun.unir(
        [aplicadas[inicio].texto, *(l.texto for l in cuerpo[:desde] if l.texto.strip())]
    )
    partido = _ENCABEZADO_OPTATIVO.fullmatch(encabezado)
    if partido is None:
        raise ValueError(f"{codigo_modulo}: encabezado que no entiendo: «{encabezado}»")
    modulo = _resultados_del_cuerpo(cuerpo, codigo_modulo, _RA_OPTATIVO)
    contenidos = _contenidos_del_cuerpo(cuerpo, codigo_modulo, _RA_OPTATIVO, libre=True)
    horas = int(partido["horas"]) if partido["horas"] else None
    return Optativo(partido["nombre"], horas, aplicadas[inicio].pagina, modulo, contenidos)


def _sustituir(texto: str, sustituciones: Sequence[tuple[str, str]]) -> str:
    for incorrecto, correcto in sustituciones:
        texto = texto.replace(incorrecto, correcto)
    return texto


class FilaCatalogo(NamedTuple):
    """Lo que el catálogo (anexo I) dice de un módulo: sus horas (solo los específicos) y el
    curso en que se imparte (solo los transversales, y ``None`` si es «en cualquiera de los
    dos cursos»)."""

    horas: int | None
    curso: str | None
    pagina: int | None


def analizar_catalogo(lineas: Sequence[Linea], codigo: str) -> FilaCatalogo:
    """La fila de ``codigo`` («CMO-316», «CMO-002I») en el catálogo del anexo I.

    Un específico tiene su familia («IFC») tras el código y la carga horaria al final de la
    fila. Un transversal comparte el bloque (líneas seguidas, sin blanco) con sus variantes
    por lengua, y el curso se lee de ese bloque: «2º curso.» o «En cualquiera de los dos
    cursos».
    """
    fila = re.compile(rf"^\s*CMO-\s*{re.escape(codigo.removeprefix('CMO-'))}\b(.*)$")
    posicion = next((i for i, l in enumerate(lineas) if fila.match(l.texto)), None)
    if posicion is None:
        raise ValueError(f"{codigo}: no está en el catálogo")
    linea = lineas[posicion]
    resto = fila.match(linea.texto)
    assert resto is not None
    if re.match(r"\s+[A-Z]{3}\b", resto[1]):
        horas = re.search(r"\s(\d+)\s*$", resto[1])
        if horas is None:
            raise ValueError(f"{codigo}: la fila del catálogo no acaba en las horas")
        return FilaCatalogo(int(horas[1]), None, linea.pagina)
    desde = posicion
    while desde > 0 and lineas[desde - 1].texto.strip():
        desde -= 1
    hasta = posicion
    while hasta + 1 < len(lineas) and lineas[hasta + 1].texto.strip():
        hasta += 1
    bloque = " ".join(" ".join(l.texto.split()) for l in lineas[desde : hasta + 1])
    curso = re.search(r"(\d)º curso", bloque)
    if curso is not None:
        return FilaCatalogo(None, curso[1], linea.pagina)
    if "En cualquiera de los" in bloque and "dos cursos" in bloque:
        return FilaCatalogo(None, None, linea.pagina)
    raise ValueError(f"{codigo}: no encuentro el curso en el catálogo")


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
    horas: int | None,
    curso: str | None,
    *,
    ficha: str,
    norma: str,
    ubicacion: str,
    pagina: int | None,
    orden: int = 1,
) -> dict[str, Any]:
    """El elemento ``modulo``; ``horas`` o ``curso`` ``None`` (el boletín no los dice) no se escriben."""
    datos: dict[str, int | str] = {}
    if horas is not None:
        datos["horas"] = horas
    if curso is not None:
        datos["curso"] = curso
    return {
        "codigo": ficha,
        "tipo": "modulo",
        "texto": nombre,
        "procedencia": {"norma": norma, "ubicacion": ubicacion, "pagina": pagina},
        "orden": orden,
        "datos": datos,
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


def _texto(cache: Path, id_: str) -> str:
    """El texto de una norma, descifrado si ``fuentes.toml`` lo declara."""
    return comun.texto_de_norma(cache, id_, comun.leer_fuentes()[id_]["cifrado"])


def _extraer_transversal(args: argparse.Namespace) -> dict[str, Any]:
    orden = comun.lineas_limpias(_texto(args.cache, args.madrid))
    modulo = analizar_resultados_orden(orden, args.modulo)
    fila = analizar_horas_curso(
        comun.lineas_limpias(_texto(args.cache, args.horas)),
        ciclo=args.ciclo,
        codigo_modulo=args.modulo,
    )
    if fila.curso is None:
        raise SystemExit(f"{args.modulo}: la tabla no le pone curso")
    elementos = [
        elemento_modulo(
            fila.nombre,
            fila.horas,
            fila.curso,
            ficha=args.ficha,
            norma=args.horas,
            ubicacion=args.ubicacion_horas,
            pagina=fila.pagina,
        )
    ]
    elementos += elementos_del_modulo(
        modulo,
        ficha=args.ficha,
        norma=args.madrid,
        ubicacion=args.ubicacion_madrid,
        orden_inicial=len(elementos) + 1,
    )
    elementos += elementos_de_contenidos(
        analizar_contenidos_orden(orden, args.modulo),
        ficha=args.ficha,
        norma=args.madrid,
        ubicacion=args.ubicacion_madrid,
        orden_inicial=len(elementos) + 1,
    )
    normas = [args.madrid, *([args.estatal] if args.estatal else []), args.horas]
    return _ficha_de_fp(
        args.ficha, fila.nombre, fila.curso, args.cursos_academicos, normas, elementos
    )


def _extraer_optativo(args: argparse.Namespace) -> dict[str, Any]:
    partido = re.fullmatch(r"(CMO-\d{3})[FIA]?", args.modulo)
    if partido is None:
        raise SystemExit(f"{args.modulo}: no es un código de módulo optativo")
    curricular = partido[1]
    sustituciones = tuple(
        (par[0], par[1]) for par in comun.leer_fuentes()[args.madrid]["sustituciones"]
    )
    optativo = analizar_optativo(
        comun.lineas_limpias(_texto(args.cache, args.madrid)), curricular, sustituciones
    )
    catalogo = analizar_catalogo(
        comun.lineas_limpias(_texto(args.cache, args.catalogo)), args.modulo
    )
    if catalogo.horas != optativo.horas:
        raise SystemExit(
            f"{args.modulo}: el catálogo dice {catalogo.horas} horas y el anexo II {optativo.horas}"
        )
    ubicacion = f"{args.ubicacion_madrid}, módulo {curricular}"
    elementos = [
        elemento_modulo(
            optativo.nombre,
            optativo.horas,
            catalogo.curso,
            ficha=args.ficha,
            norma=args.madrid,
            ubicacion=ubicacion,
            pagina=optativo.pagina,
        )
    ]
    elementos += elementos_del_modulo(
        optativo.modulo,
        ficha=args.ficha,
        norma=args.madrid,
        ubicacion=args.ubicacion_madrid,
        orden_inicial=len(elementos) + 1,
    )
    elementos += elementos_de_contenidos(
        optativo.contenidos,
        ficha=args.ficha,
        norma=args.madrid,
        ubicacion=f"{ubicacion}, contenidos",
        orden_inicial=len(elementos) + 1,
    )
    return _ficha_de_fp(
        args.ficha,
        optativo.nombre,
        catalogo.curso,
        args.cursos_academicos,
        [args.madrid, args.catalogo],
        elementos,
    )


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
        description="Extrae un módulo (técnico o transversal), o el título, de un ciclo de FP de grado superior."
    )
    sub = ap.add_subparsers(dest="orden", required=True)

    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("--ficha", required=True, help="código de la ficha, p. ej. MAD.DAM.0485")
    base.add_argument("--cursos-academicos", required=True, help="separados por comas")
    base.add_argument("--cache", type=Path, required=True)
    base.add_argument("--salida", type=Path, help="carpeta de datos (por defecto, la del paquete)")
    comunes = argparse.ArgumentParser(add_help=False, parents=[base])
    comunes.add_argument(
        "--boe", required=True, help="id de la norma que reescribe el título (RD 405/2023)"
    )
    comunes.add_argument("--articulo", default="segundo", help="ordinal del artículo que lo hace")

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

    x = sub.add_parser(
        "transversal",
        parents=[base],
        help="un módulo transversal (RD 659/2023 y su orden de Madrid)",
    )
    x.add_argument("--modulo", required=True, help="código del módulo, p. ej. 1709")
    x.add_argument("--ciclo", required=True, help="nombre del ciclo en la tabla de horas")
    x.add_argument("--madrid", required=True, help="id de la orden con el currículo de Madrid")
    x.add_argument("--ubicacion-madrid", required=True, help="p. ej. «anexo VII»")
    x.add_argument("--horas", required=True, help="id de la norma con la tabla de horas")
    x.add_argument("--ubicacion-horas", default="anexo II")
    x.add_argument(
        "--estatal",
        help="id del real decreto del mínimo estatal: se cita en las normas de la ficha",
    )

    o = sub.add_parser(
        "optativo",
        parents=[base],
        help="un módulo optativo (Orden 3536/2025, en la redacción de la Orden 3822/2026)",
    )
    o.add_argument("--modulo", required=True, help="código del catálogo, p. ej. CMO-316 o CMO-002I")
    o.add_argument("--madrid", required=True, help="id de la orden con el currículo (anexo II)")
    o.add_argument("--ubicacion-madrid", default="anexo II")
    o.add_argument("--catalogo", required=True, help="id de la orden con el catálogo vigente")

    args = ap.parse_args(argv)
    ficha = {
        "modulo": _extraer_modulo,
        "optativo": _extraer_optativo,
        "titulo": _extraer_titulo,
        "transversal": _extraer_transversal,
    }[args.orden](args)
    raiz = args.salida or Path(str(files("tiza.normativa").joinpath("datos")))
    print(escribir_ficha(ficha, raiz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
