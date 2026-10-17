"""Extrae un módulo profesional de formación profesional (grado superior) a una ficha.

Reúne tres fuentes, cada una de la norma que manda en ese dato:

* resultados de aprendizaje, criterios de evaluación y orientaciones pedagógicas, del
  texto consolidado del BOE (XML de los bloques del anexo del real decreto del título).
  Con ``--modificaciones`` un elemento puede tener procedencia doble: la norma que lo
  modifica y, en ``via``, el lugar del original;
* contenidos de Madrid, del PDF del decreto de currículo del ciclo;
* horas y curso, de la tabla de organización académica (anexo II) del decreto que
  modifica los planes de estudios.

No hay aquí la extracción de los módulos transversales ni de los optativos de las
órdenes de 2025: el texto de ``pdftotext`` de la Orden 3537/2025 sale cifrado (la fuente
del PDF no trae mapa de caracteres) y hay que resolver primero cómo se lee.

Las funciones de análisis trabajan sobre texto o líneas; solo :func:`main` toca ficheros.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

from . import comun
from .comun import Linea
from .extraer_lomloe import escribir_ficha

_MODULO_MADRID = re.compile(r"^\s*M[óo]dulo profesional\s+\d+:.*\(c[óo]digo:\s*(\w+)\)")
_VINETA = re.compile(r"^\s*[—–-]\s+(\S.*)$")
_NOMBRE_BOE = re.compile(r"^M[óo]dulo [Pp]rofesional:\s*(.+?)\.?$")
_RA = re.compile(r"^(\d+)\.\s+(\S.*)$")
_CRITERIO = re.compile(r"^([a-z])\)\s+(\S.*)$")


def _sangria(texto: str) -> int:
    return len(texto) - len(texto.lstrip())


# --- contenidos de Madrid (PDF del decreto del ciclo) -------------------------------------


def analizar_contenidos_madrid(lineas: Sequence[Linea], codigo_modulo: str) -> list[dict[str, Any]]:
    """Los contenidos de un módulo: nivel 1 (tema), 2 (viñeta «—») y 3 (apartado sin viñeta)."""
    inicio = next(
        (
            i
            for i, l in enumerate(lineas)
            if (m := _MODULO_MADRID.match(l.texto)) and m[1] == codigo_modulo
        ),
        None,
    )
    if inicio is None:
        raise ValueError(f"no encuentro el módulo {codigo_modulo} en los contenidos de Madrid")
    items: list[dict[str, Any]] = []
    base: int | None = None
    for linea in lineas[inicio + 1 :]:
        texto = linea.texto.strip()
        if not texto:
            continue
        if _MODULO_MADRID.match(linea.texto):
            break
        if texto.startswith("Contenidos (duración"):
            continue
        base = _sangria(linea.texto) if base is None else base
        ultimo = items[-1] if items else None
        vineta = _VINETA.match(linea.texto)
        if vineta and _sangria(linea.texto) <= base + 2:
            items.append({"nivel": 2, "lineas": [vineta[1]], "pagina": linea.pagina})
        elif _sangria(linea.texto) <= base + 2:
            if ultimo and ultimo["nivel"] == 1 and not ultimo["lineas"][-1].endswith(":"):
                ultimo["lineas"].append(texto)  # un tema que ocupa dos líneas
            else:
                items.append({"nivel": 1, "lineas": [texto], "pagina": linea.pagina})
        elif ultimo is None:
            continue
        elif ultimo["lineas"][-1].endswith(":"):
            items.append(
                {"nivel": min(ultimo["nivel"] + 1, 3), "lineas": [texto], "pagina": linea.pagina}
            )
        elif ultimo["nivel"] == 3 and ultimo["lineas"][-1].endswith((".", ";")):
            items.append({"nivel": 3, "lineas": [texto], "pagina": linea.pagina})
        else:
            ultimo["lineas"].append(texto)  # la línea siguiente de un mismo contenido
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
    """Elementos ``contenido_basico`` (``CB.1``, ``CB.1.2``, ``CB.1.2.1``) con sus padres."""
    elementos: list[dict[str, Any]] = []
    contadores = [0, 0, 0]
    codigos = ["", "", ""]
    for item in items:
        nivel = item["nivel"]
        contadores[nivel - 1] += 1
        for i in range(nivel, 3):
            contadores[i] = 0
        codigo = f"{ficha}.CB." + ".".join(str(c) for c in contadores[:nivel])
        codigos[nivel - 1] = codigo
        elemento: dict[str, Any] = {
            "codigo": codigo,
            "tipo": "contenido_basico",
            "texto": item["texto"],
            "procedencia": {"norma": norma, "ubicacion": ubicacion, "pagina": item["pagina"]},
            "orden": orden_inicial + len(elementos),
        }
        if nivel > 1:
            elemento["padre"] = codigos[nivel - 2]
        elementos.append(elemento)
    return elementos


# --- horas y curso (tabla del anexo II) -------------------------------------------------------


def analizar_horas_curso(
    lineas: Sequence[Linea], *, ciclo: str, codigo_modulo: str
) -> tuple[int, str, int | None]:
    """``(horas, curso, página)`` de un módulo en la tabla de su ciclo.

    Las horas son la primera cifra de la fila; el curso, la columna («Curso 1º» o «Curso 2º»)
    más cercana a la última cifra, que son las horas semanales.
    """
    inicio = next(
        (i for i, l in enumerate(lineas) if "Ciclo Formativo:" in l.texto and ciclo in l.texto),
        None,
    )
    if inicio is None:
        raise ValueError(f"no encuentro el ciclo «{ciclo}»")
    columnas: tuple[int, int] | None = None
    for linea in lineas[inicio + 1 :]:
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
        cifras = [(fila.start(2) + n.start(), int(n[0])) for n in re.finditer(r"\d+", fila[2])]
        if len(cifras) < 3:
            raise ValueError(f"{codigo_modulo}: la fila no trae horas semanales")
        posicion = cifras[-1][0]
        curso = "1" if abs(posicion - columnas[0]) <= abs(posicion - columnas[1]) else "2"
        return cifras[0][1], curso, linea.pagina
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
        "codigo": f"{ficha}.MOD",
        "tipo": "modulo",
        "texto": nombre,
        "procedencia": {"norma": norma, "ubicacion": ubicacion, "pagina": pagina},
        "orden": orden,
        "datos": {"horas": horas, "curso": curso},
    }


# --- resultados, criterios y orientaciones (XML consolidado del BOE) -----------------------


def analizar_modulo_boe(parrafos: Sequence[str], codigo_modulo: str) -> dict[str, Any]:
    """El módulo ``codigo_modulo`` del anexo: nombre, resultados con sus criterios, orientaciones."""
    inicio = next(
        (i for i, p in enumerate(parrafos) if re.match(rf"^C[óo]digo:\s*{codigo_modulo}\b", p)),
        None,
    )
    if inicio is None:
        raise ValueError(f"no encuentro el módulo {codigo_modulo} en el XML del BOE")
    nombre = _NOMBRE_BOE.match(parrafos[inicio - 1]) if inicio else None
    if nombre is None:
        raise ValueError(f"{codigo_modulo}: no encuentro «Módulo Profesional: …» antes del código")
    resultados: list[dict[str, Any]] = []
    orientaciones: list[str] = []
    estado = ""
    for parrafo in parrafos[inicio + 1 :]:
        if _NOMBRE_BOE.match(parrafo):
            break
        if parrafo.startswith("Resultados de aprendizaje"):
            estado = "ra"
        elif parrafo.startswith(("Duración", "Contenidos básicos")):
            estado = ""
        elif parrafo.startswith("Orientaciones pedagógicas"):
            estado = "ori"
        elif estado == "ori":
            orientaciones.append(parrafo)
        elif estado == "ra":
            if (ra := _RA.match(parrafo)) is not None:
                resultados.append({"numero": ra[1], "texto": ra[2], "criterios": []})
            elif (ce := _CRITERIO.match(parrafo)) is not None and resultados:
                resultados[-1]["criterios"].append({"letra": ce[1], "texto": ce[2]})
    if not resultados:
        raise ValueError(f"{codigo_modulo}: no hay resultados de aprendizaje")
    return {
        "codigo": codigo_modulo,
        "nombre": nombre[1],
        "resultados": resultados,
        "orientaciones": comun.unir(orientaciones) or None,
    }


def elementos_del_boe(
    modulo: Mapping[str, Any],
    *,
    ficha: str,
    norma: str,
    ubicacion: str,
    orden_inicial: int = 1,
    modificados: Mapping[str, tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Elementos ``RA.n``, ``RA.n.CE.a`` y ``ORI`` del módulo.

    ``modificados`` da, por código de elemento, la norma que lo modifica y su ubicación:
    la procedencia pasa a ser esa y el lugar del original queda en ``via``.
    """
    modificados = modificados or {}
    elementos: list[dict[str, Any]] = []

    def anadir(codigo: str, tipo: str, texto: str, lugar: str, padre: str | None = None) -> None:
        original = {"norma": norma, "ubicacion": lugar, "pagina": None}
        if codigo in modificados:
            otra, donde = modificados[codigo]
            procedencia: dict[str, Any] = {
                "norma": otra,
                "ubicacion": donde,
                "pagina": None,
                "via": [original],
            }
        else:
            procedencia = original
        elemento: dict[str, Any] = {
            "codigo": codigo,
            "tipo": tipo,
            "texto": comun.unir([texto]),
            "procedencia": procedencia,
            "orden": orden_inicial + len(elementos),
        }
        if padre is not None:
            elemento["padre"] = padre
        elementos.append(elemento)

    base = f"{ubicacion}, módulo {modulo['codigo']}"
    for resultado in modulo["resultados"]:
        codigo = f"{ficha}.RA.{resultado['numero']}"
        anadir(
            codigo,
            "resultado_aprendizaje",
            resultado["texto"],
            f"{base}, resultado de aprendizaje {resultado['numero']}",
        )
        for criterio in resultado["criterios"]:
            anadir(
                f"{codigo}.CE.{criterio['letra']}",
                "criterio_fp",
                criterio["texto"],
                f"{base}, resultado de aprendizaje {resultado['numero']}, criterio {criterio['letra']}",
                padre=codigo,
            )
    if modulo["orientaciones"]:
        anadir(
            f"{ficha}.ORI",
            "orientaciones",
            modulo["orientaciones"],
            f"{base}, orientaciones pedagógicas",
        )
    return elementos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Extrae un módulo de FP de grado superior a una ficha."
    )
    ap.add_argument("--ficha", required=True, help="código de la ficha, p. ej. MAD.FPGS.DAM.0485")
    ap.add_argument("--modulo", required=True, help="código del módulo, p. ej. 0485")
    ap.add_argument(
        "--ciclo", required=True, help="nombre del ciclo en la tabla de horas, en mayúsculas"
    )
    ap.add_argument("--cursos-academicos", required=True, help="separados por comas")
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--boe", required=True, help="id de la norma del BOE con el XML del anexo")
    ap.add_argument("--ubicacion-boe", default="anexo I")
    ap.add_argument("--madrid", required=True, help="id de la norma con los contenidos de Madrid")
    ap.add_argument("--ubicacion-madrid", default="anexo I")
    ap.add_argument("--horas", required=True, help="id de la norma con la tabla de horas")
    ap.add_argument("--ubicacion-horas", default="anexo II")
    ap.add_argument("--modificaciones", type=Path, help="JSON {código: [norma, ubicación]}")
    ap.add_argument("--salida", type=Path, help="carpeta de datos (por defecto, la del paquete)")
    args = ap.parse_args(argv)

    xml = (args.cache / f"{args.boe}.xml").read_text(encoding="utf-8")
    modulo = analizar_modulo_boe(comun.parrafos_de_xml(xml), args.modulo)
    horas, curso, pagina = analizar_horas_curso(
        comun.lineas_limpias(comun.texto_de_norma(args.cache, args.horas)),
        ciclo=args.ciclo,
        codigo_modulo=args.modulo,
    )
    contenidos = analizar_contenidos_madrid(
        comun.lineas_limpias(comun.texto_de_norma(args.cache, args.madrid)), args.modulo
    )
    modificados = {}
    if args.modificaciones:
        modificados = {
            k: (v[0], v[1]) for k, v in json.loads(args.modificaciones.read_text("utf-8")).items()
        }
    elementos = [
        elemento_modulo(
            modulo["nombre"],
            horas,
            curso,
            ficha=args.ficha,
            norma=args.horas,
            ubicacion=args.ubicacion_horas,
            pagina=pagina,
        )
    ]
    elementos += elementos_del_boe(
        modulo,
        ficha=args.ficha,
        norma=args.boe,
        ubicacion=args.ubicacion_boe,
        orden_inicial=len(elementos) + 1,
        modificados=modificados,
    )
    elementos += elementos_de_contenidos(
        contenidos,
        ficha=args.ficha,
        norma=args.madrid,
        ubicacion=args.ubicacion_madrid,
        orden_inicial=len(elementos) + 1,
    )
    normas = list(
        dict.fromkeys([args.boe, args.madrid, args.horas, *(v[0] for v in modificados.values())])
    )
    ficha = {
        "codigo": args.ficha,
        "nombre": modulo["nombre"],
        "etapa": "fp_gs",
        "curso": curso,
        "cursos_academicos": args.cursos_academicos.split(","),
        "normas": normas,
        "elementos": elementos,
    }
    raiz = args.salida or Path(str(files("tiza.normativa").joinpath("datos")))
    print(escribir_ficha(ficha, raiz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
