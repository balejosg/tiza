"""Extrae una materia de la LOMLOE del texto de un boletín (``pdftotext -layout``) a una ficha.

Competencias específicas (número y enunciado: el texto en negrita, hasta el párrafo que
lo explica), los descriptores con los que se conectan, los criterios de evaluación de un
curso agrupados por «Competencia específica N.» y los contenidos de ese curso por bloques
(letra y título) y viñetas. Escribe ``fichas/<código>.json``.

Uso::

    python -m herramientas.normativa.extraer_lomloe --norma bocm-20230531-18 \\
        --materia CCOMP --curso 1 --nombre "Ciencias de la Computación" \\
        --etapa bachillerato --cursos-academicos 2023-24,2024-25 --cache <dir>

Las funciones de análisis trabajan sobre texto; solo :func:`main` toca ficheros.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

from . import comun
from .comun import Linea

ETAPAS = {"eso": "ESO", "bachillerato": "BACH"}
ORDINALES = {"1": "primer", "2": "segundo", "3": "tercer", "4": "cuarto"}

_ANEXO = re.compile(r"^\s*ANEXO\s+([IVXLC]+)\s*$")
_COMPETENCIAS = re.compile(r"^\s*Competencias espec[ií]ficas\.?\s*$")
_CRITERIOS = re.compile(r"^\s*Criterios de evaluaci[oó]n\.?\s*$")
_CONTENIDOS = re.compile(r"^\s*Contenidos\.?\s*$")
_GRUPO = re.compile(r"^\s*Competencia espec[ií]fica (\d+)\.?\s*$")
_CURSO_CUALQUIERA = re.compile(r"^\s*\d\s*\.?\s*[º°]\s*\.?\s*[A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚ ]*\.?\s*$")
_NUMERADA = re.compile(r"^\s*(\d+)\.\s+(\S.*)$")
_CRITERIO = re.compile(r"^\s*(\d+)\.(\d+)\s+(\S.*)$")
_BLOQUE = re.compile(r"^\s*([A-Z])\.\s+(\S.*)$")
_VINETA = re.compile(r"^\s*[-–—•]\s+(\S.*)$")
_SUBVINETA = re.compile(r"^\s*x\s+(\S.*)$")
_DESCRIPTORES_FRASE = "Esta competencia específica se conecta"
_DESCRIPTOR = re.compile(r"\b[A-Z]{2,6}\d+(?:\.\d+)?\b")


def _indice(lineas: Sequence[Linea], patron: re.Pattern[str], desde: int = 0) -> int | None:
    for i in range(desde, len(lineas)):
        if patron.match(lineas[i].texto):
            return i
    return None


def _marca_de_curso(curso: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{curso}\s*\.?\s*[º°]\s*\.?\s*[A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚ ]*\.?\s*$")


def _competencias(lineas: Sequence[Linea]) -> list[dict[str, Any]]:
    """Las competencias del apartado: número, enunciado, descriptores y página."""
    actuales: list[dict[str, Any]] = []
    estado = ""
    for i, linea in enumerate(lineas):
        texto = linea.texto.strip()
        if not texto:
            continue
        numerada = _NUMERADA.match(linea.texto)
        if numerada and int(numerada[1]) == len(actuales) + 1:
            actuales.append(
                {
                    "numero": int(numerada[1]),
                    "enunciado": [numerada[2]],
                    "descriptores": [],
                    "pagina": linea.pagina,
                }
            )
            estado = "enunciado"
            if _cierra_el_enunciado(lineas, i, numerada[2]):
                estado = "explicacion"
        elif not actuales:
            continue
        elif texto.startswith(_DESCRIPTORES_FRASE) or estado == "descriptores":
            estado = "descriptores"
            actuales[-1]["descriptores"].append(texto)
        elif estado == "enunciado":
            actuales[-1]["enunciado"].append(texto)
            if _cierra_el_enunciado(lineas, i, texto):
                estado = "explicacion"
    return actuales


def _cierra_el_enunciado(lineas: Sequence[Linea], i: int, texto: str) -> bool:
    """El enunciado acaba en una línea que acaba en punto y a la que sigue otra en mayúscula."""
    if not texto.rstrip().endswith("."):
        return False
    for siguiente in lineas[i + 1 :]:
        if siguiente.texto.strip():
            return siguiente.texto.strip()[:1].isupper()
    return True


def _descriptores(lineas: list[str], prefijo: str) -> list[str]:
    frase = comun.unir(lineas)
    if ":" not in frase:
        return []
    return [f"{prefijo}.{c}" for c in _DESCRIPTOR.findall(frase.split(":", 1)[1])]


def _criterios(lineas: Sequence[Linea]) -> list[dict[str, Any]]:
    """Los criterios del curso: grupo (competencia), número y texto."""
    criterios: list[dict[str, Any]] = []
    grupo = 0
    for linea in lineas:
        texto = linea.texto.strip()
        if not texto:
            continue
        if (g := _GRUPO.match(linea.texto)) is not None:
            grupo = int(g[1])
        elif (c := _CRITERIO.match(linea.texto)) is not None and int(c[1]) == grupo:
            criterios.append(
                {"ce": grupo, "numero": f"{c[1]}.{c[2]}", "lineas": [c[3]], "pagina": linea.pagina}
            )
        elif criterios:
            criterios[-1]["lineas"].append(texto)
    return criterios


def _contenidos(lineas: Sequence[Linea]) -> list[dict[str, Any]]:
    """Bloques (letra y título), viñetas «-» y subviñetas «x», hasta la primera línea en blanco."""
    items: list[dict[str, Any]] = []
    bloques = 0
    vistas = 0
    for linea in lineas:
        if not linea.texto.strip():
            if vistas:
                break
            continue
        if _CURSO_CUALQUIERA.match(linea.texto):
            break  # el apartado del curso siguiente, si la línea en blanco cayó al cambiar de página
        vistas += 1
        bloque = _BLOQUE.match(linea.texto)
        vineta = _VINETA.match(linea.texto)
        sub = _SUBVINETA.match(linea.texto)
        if bloque and bloque[1] == chr(ord("A") + bloques):
            items.append(
                {"nivel": 0, "lineas": [bloque[2]], "letra": bloque[1], "pagina": linea.pagina}
            )
            bloques += 1
        elif vineta and items:
            items.append({"nivel": 1, "lineas": [vineta[1]], "pagina": linea.pagina})
        elif sub and items:
            items.append({"nivel": 2, "lineas": [sub[1]], "pagina": linea.pagina})
        elif items and linea.texto.strip() != "-":
            items[-1]["lineas"].append(linea.texto.strip())
    return items


def _buscar_anexo(lineas: Sequence[Linea], hasta: int) -> str | None:
    for i in range(hasta, -1, -1):
        if (m := _ANEXO.match(lineas[i].texto)) is not None:
            return f"anexo {m[1]}"
    return None


def extraer_materia(
    texto: str,
    *,
    norma: str,
    nombre: str,
    sigla: str,
    etapa: str,
    curso: str,
    cursos_academicos: Sequence[str],
    anexo: str | None = None,
    desde: str | None = None,
) -> dict[str, Any]:
    """La ficha (``dict`` listo para ``fichas/<código>.json``) de una materia y un curso."""
    abreviatura = ETAPAS[etapa]
    lineas = comun.lineas_limpias(texto)
    titulo = next((i for i, l in enumerate(lineas) if l.texto.strip() == nombre), None)
    if titulo is None:
        raise ValueError(f"no encuentro la materia «{nombre}» en el texto de {norma}")
    anexo = anexo or _buscar_anexo(lineas, titulo)
    if anexo is None:
        raise ValueError("no encuentro el anexo de la materia: indícalo con --anexo")
    region = lineas[titulo + 1 :]

    inicio = _indice(region, _COMPETENCIAS)
    if inicio is None:
        raise ValueError(f"«{nombre}»: no encuentro «Competencias específicas.»")
    fin = min(
        (
            i
            for i in (
                _indice(region, _CURSO_CUALQUIERA, inicio + 1),
                _indice(region, _CRITERIOS, inicio + 1),
            )
            if i is not None
        ),
        default=len(region),
    )
    competencias = _competencias(region[inicio + 1 : fin])
    if not competencias:
        raise ValueError(f"«{nombre}»: no hay competencias específicas")

    marca = _indice(region, _marca_de_curso(curso), inicio + 1)
    if marca is None:
        raise ValueError(f"«{nombre}»: no encuentro el apartado del curso {curso}")
    seccion = region[marca + 1 :]
    cr = _indice(seccion, _CRITERIOS)
    co = _indice(seccion, _CONTENIDOS)
    if cr is None or co is None or co < cr:
        raise ValueError(
            f"«{nombre}», curso {curso}: faltan «Criterios de evaluación.» o «Contenidos.»"
        )
    criterios = _criterios(seccion[cr + 1 : co])
    contenidos = _contenidos(seccion[co + 1 :])

    ficha_codigo = f"MAD.{abreviatura}.{sigla}.{curso}"
    ordinal = f"{curso}.º"
    elementos: list[dict[str, Any]] = []

    def anadir(
        codigo: str,
        tipo: str,
        lineas_texto: list[str],
        pagina: int | None,
        ubicacion: str,
        padre: str | None = None,
        relaciones: dict[str, list[str]] | None = None,
    ) -> None:
        elemento: dict[str, Any] = {
            "codigo": codigo,
            "tipo": tipo,
            "texto": comun.unir(lineas_texto),
            "procedencia": {"norma": norma, "ubicacion": ubicacion, "pagina": pagina},
            "orden": len(elementos) + 1,
        }
        if padre is not None:
            elemento["padre"] = padre
        if relaciones:
            elemento["relaciones"] = relaciones
        elementos.append(elemento)

    for c in competencias:
        codigo = f"{ficha_codigo}.CE.{c['numero']}"
        descriptores = _descriptores(c["descriptores"], f"EST.{abreviatura}.DESC")
        anadir(
            codigo,
            "competencia_especifica",
            c["enunciado"],
            c["pagina"],
            f"{anexo}, competencia específica {c['numero']}",
            relaciones={"descriptores": descriptores} if descriptores else None,
        )
        for criterio in (k for k in criterios if k["ce"] == c["numero"]):
            anadir(
                f"{ficha_codigo}.CR.{criterio['numero']}",
                "criterio",
                criterio["lineas"],
                criterio["pagina"],
                f"{anexo}, {ordinal}, criterio {criterio['numero']}",
                padre=codigo,
            )
    conocidas = {c["numero"] for c in competencias}
    sueltos = sorted({k["ce"] for k in criterios} - conocidas)
    if sueltos:
        raise ValueError(f"criterios de competencias que no existen: {sueltos}")

    bloque = ""
    contenido = ""
    n_contenido = n_sub = 0
    for item in contenidos:
        if item["nivel"] == 0:
            bloque = f"{ficha_codigo}.CO.{item['letra']}"
            n_contenido = 0
            anadir(
                bloque,
                "bloque_contenidos",
                item["lineas"],
                item["pagina"],
                f"{anexo}, {ordinal}, contenidos, bloque {item['letra']}",
            )
        elif item["nivel"] == 1 or not contenido:
            n_contenido += 1
            n_sub = 0
            contenido = f"{bloque}.{n_contenido}"
            anadir(
                contenido,
                "contenido",
                item["lineas"],
                item["pagina"],
                f"{anexo}, {ordinal}, contenidos, bloque {bloque.rsplit('.', 1)[1]}",
                padre=bloque,
            )
        else:
            n_sub += 1
            anadir(
                f"{contenido}.{n_sub}",
                "contenido",
                item["lineas"],
                item["pagina"],
                f"{anexo}, {ordinal}, contenidos, bloque {bloque.rsplit('.', 1)[1]}",
                padre=contenido,
            )

    ficha: dict[str, Any] = {
        "codigo": ficha_codigo,
        "nombre": f"{nombre}, {ORDINALES.get(curso, curso)} curso",
        "etapa": etapa,
        "curso": curso,
        "cursos_academicos": list(cursos_academicos),
        "normas": [norma],
        "elementos": elementos,
    }
    if desde:
        ficha["desde"] = desde
    return ficha


def escribir_ficha(ficha: dict[str, Any], raiz: Path) -> Path:
    """Escribe ``fichas/<código>.json`` bajo ``raiz``."""
    destino = raiz / "fichas" / f"{ficha['codigo']}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(ficha, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destino


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extrae una materia de la LOMLOE a una ficha JSON.")
    ap.add_argument("--norma", required=True, help="id de la norma, p. ej. bocm-20230531-18")
    ap.add_argument("--materia", required=True, help="sigla de la materia, p. ej. CCOMP")
    ap.add_argument("--curso", required=True, help="curso de la etapa (1, 2…)")
    ap.add_argument(
        "--nombre", required=True, help="título de la materia tal como está en el anexo"
    )
    ap.add_argument("--etapa", required=True, choices=sorted(ETAPAS))
    ap.add_argument(
        "--cursos-academicos", required=True, help="separados por comas: 2023-24,2024-25"
    )
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--anexo", help="p. ej. «anexo IV»; por defecto, el que precede al título")
    ap.add_argument("--desde", help="AAAA-MM-DD si la ficha solo rige a partir de esa fecha")
    ap.add_argument("--salida", type=Path, help="carpeta de datos (por defecto, la del paquete)")
    args = ap.parse_args(argv)
    ficha = extraer_materia(
        comun.texto_de_norma(args.cache, args.norma),
        norma=args.norma,
        nombre=args.nombre,
        sigla=args.materia,
        etapa=args.etapa,
        curso=args.curso,
        cursos_academicos=args.cursos_academicos.split(","),
        anexo=args.anexo,
        desde=args.desde,
    )
    raiz = args.salida or Path(str(files("tiza.normativa").joinpath("datos")))
    print(escribir_ficha(ficha, raiz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
