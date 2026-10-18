"""Extrae los requisitos de la programación didáctica (``MAD.<ETAPA>.PROG``) de los boletines.

Es declarativo: ``requisitos.toml`` lista, por ficha, cada requisito con su código, su norma,
su ubicación, su página y dos anclas literales (el principio y el final del apartado). El
texto guardado es **el que hay entre las anclas, ambas incluidas**, sacado de la página del
PDF o, si el requisito no lleva página, del XML consolidado del BOE, con la misma
normalización que ``comprobar`` (espacios simples, NFC y palabras partidas recompuestas).
Nada se escribe a mano: un ancla que no aparece, que aparece más de una vez o que deja el
fin antes del inicio es un error.

Un requisito que enumera letras («incluirá, al menos, los siguientes elementos: a)…») se
guarda como un elemento con la frase que las introduce y un elemento hijo por letra
(``padre``), cada uno sin su marca «a)» (va en la ubicación).

Uso::

    python -m herramientas.normativa.extraer_requisitos --cache <dir> [--salida <datos>]
"""

from __future__ import annotations

import argparse
import sys
import tomllib
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

from . import comun
from .extraer_lomloe import escribir_ficha

# Un ancla de fin más corta que esto (un «a.», un «el») casaría en cualquier sitio de la
# región (la página del requisito y la siguiente) y recortaría el apartado sin avisar.
MINIMO_ANCLA_FIN = 10
RUTA_REQUISITOS = Path(__file__).with_name("requisitos.toml")
TIPO = "requisito_programacion"
ETAPAS = ("eso", "bachillerato", "fp_gs")
_CLAVES_FICHA = {"codigo", "nombre", "etapa", "cursos_academicos", "requisitos"}
_CLAVES_REQUISITO = {"codigo", "norma", "ubicacion", "pagina", "inicio", "fin", "padre"}


@dataclass(frozen=True)
class Fuente:
    """El texto de una norma: las líneas del PDF con su página y, si la hay, el XML del BOE."""

    lineas: list[comun.Linea] = field(default_factory=list)
    xml: str | None = None


@dataclass(frozen=True)
class Entrada:
    """Un requisito de ``requisitos.toml``."""

    codigo: str
    norma: str
    ubicacion: str
    pagina: int | None
    inicio: str
    fin: str
    padre: str | None = None


def _normal(texto: str) -> str:
    return comun.unir([unicodedata.normalize("NFC", texto)])


def _una_vez(region: str, ancla: str, donde: str, etiqueta: str) -> int:
    buscada = _normal(ancla)
    if (n := region.count(buscada)) == 0:
        raise ValueError(f"{donde}: el ancla de {etiqueta} no aparece: «{buscada}»")
    if n > 1:
        raise ValueError(f"{donde}: el ancla de {etiqueta} aparece más de una vez: «{buscada}»")
    return region.index(buscada)


def extraer_texto(entrada: Entrada, fuente: Fuente) -> str:
    """El texto literal entre las anclas de ``entrada`` (incluidas), ya normalizado."""
    donde = entrada.codigo
    if entrada.pagina is None:
        if fuente.xml is None:
            raise ValueError(f"{donde}: falta la página y la norma no tiene XML consolidado")
        region = "\n".join(comun.textos_de_xml(fuente.xml))
    else:
        paginas = {l.pagina for l in fuente.lineas}
        if entrada.pagina not in paginas:
            raise ValueError(f"{donde}: la norma no tiene la página {entrada.pagina}")
        # el apartado puede acabar en la página siguiente, y no más allá: el fin tiene que estar
        # en la página del inicio o en la siguiente
        region = comun.unir(
            l.texto for l in fuente.lineas if l.pagina in (entrada.pagina, entrada.pagina + 1)
        )
    inicio = _una_vez(region, entrada.inicio, donde, "inicio")
    fin = _normal(entrada.fin)
    if len(fin) < MINIMO_ANCLA_FIN:
        raise ValueError(
            f"{donde}: el ancla de fin es demasiado corta (menos de {MINIMO_ANCLA_FIN} "
            f"caracteres): «{fin}»"
        )
    ultimo = region.find(fin, max(inicio, inicio + len(_normal(entrada.inicio)) - len(fin)))
    if ultimo < 0:
        antes = region.find(fin)
        if antes >= 0 and antes < inicio:
            raise ValueError(f"{donde}: el ancla de fin está antes del inicio: «{fin}»")
        raise ValueError(f"{donde}: el ancla de fin no aparece tras el inicio: «{fin}»")
    texto = region[inicio : ultimo + len(fin)]
    if entrada.pagina is None and "\n" in texto:
        raise ValueError(f"{donde}: el apartado ocupa más de un párrafo del XML")
    return texto


def _entrada(ficha: str, bruto: Any) -> Entrada:
    if not isinstance(bruto, dict):
        raise ValueError(f"{ficha}: cada requisito debe ser una tabla")
    for clave in bruto:
        if clave not in _CLAVES_REQUISITO:
            raise ValueError(f"{ficha}: clave no permitida «{clave}» en un requisito")
    for clave in ("codigo", "norma", "ubicacion", "inicio", "fin"):
        if not isinstance(bruto.get(clave), str) or not bruto[clave]:
            raise ValueError(f"{ficha}: falta «{clave}» en un requisito")
    pagina = bruto.get("pagina")
    if pagina is not None and type(pagina) is not int:
        raise ValueError(f"{bruto['codigo']}: «pagina» debe ser un entero")
    padre = bruto.get("padre")
    if padre is not None and not isinstance(padre, str):
        raise ValueError(f"{bruto['codigo']}: «padre» debe ser un código")
    return Entrada(
        bruto["codigo"],
        bruto["norma"],
        bruto["ubicacion"],
        pagina,
        bruto["inicio"],
        bruto["fin"],
        padre,
    )


def construir_ficha(ficha: dict[str, Any], leer_fuente: Callable[[str], Fuente]) -> dict[str, Any]:
    """La ficha JSON de una entrada de ``requisitos.toml``; ``leer_fuente(norma)`` da su texto."""
    codigo = ficha["codigo"]
    elementos: list[dict[str, Any]] = []
    vistos: set[str] = set()
    normas: list[str] = []
    for orden, bruto in enumerate(ficha["requisitos"], start=1):
        e = _entrada(codigo, bruto)
        if e.codigo in vistos:
            raise ValueError(f"{e.codigo}: código repetido")
        if not e.codigo.startswith(codigo + "."):
            raise ValueError(f"{e.codigo}: no cuelga de la ficha {codigo}")
        if e.padre is not None and e.padre not in vistos:
            raise ValueError(f"{e.codigo}: el padre «{e.padre}» debe estar antes en la lista")
        vistos.add(e.codigo)
        if e.norma not in normas:
            normas.append(e.norma)
        elemento: dict[str, Any] = {
            "codigo": e.codigo,
            "tipo": TIPO,
            "texto": extraer_texto(e, leer_fuente(e.norma)),
            "procedencia": {"norma": e.norma, "ubicacion": e.ubicacion, "pagina": e.pagina},
            "orden": orden,
        }
        if e.padre is not None:
            elemento["padre"] = e.padre
        elementos.append(elemento)
    return {
        "codigo": codigo,
        "nombre": ficha["nombre"],
        "etapa": ficha["etapa"],
        "curso": None,
        "cursos_academicos": list(ficha["cursos_academicos"]),
        "normas": normas,
        "elementos": elementos,
    }


def leer_requisitos(ruta: Path = RUTA_REQUISITOS) -> list[dict[str, Any]]:
    """Las fichas de ``requisitos.toml`` (una tabla ``[[ficha]]`` con sus ``[[ficha.requisitos]]``)."""
    with ruta.open("rb") as f:
        bruto = tomllib.load(f)
    fichas = bruto.get("ficha")
    if not isinstance(fichas, list) or not fichas:
        raise ValueError(f"{ruta.name}: falta la lista [[ficha]]")
    for ficha in fichas:
        for clave in ficha:
            if clave not in _CLAVES_FICHA:
                raise ValueError(f"{ficha.get('codigo')}: clave no permitida «{clave}»")
        for clave in ("codigo", "nombre", "etapa", "cursos_academicos", "requisitos"):
            if clave not in ficha:
                raise ValueError(f"{ficha.get('codigo', '?')}: falta «{clave}»")
        if ficha["etapa"] not in ETAPAS:
            raise ValueError(f"{ficha['codigo']}: etapa desconocida «{ficha['etapa']}»")
    return list(fichas)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extrae los requisitos de la programación.")
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--requisitos", type=Path, default=RUTA_REQUISITOS)
    ap.add_argument("--fuentes", type=Path, default=comun.RUTA_FUENTES)
    ap.add_argument("--salida", type=Path, help="carpeta de datos (por defecto, la del paquete)")
    args = ap.parse_args(argv)
    cifrados = {i: r.get("cifrado") for i, r in comun.leer_fuentes(args.fuentes).items()}
    cache: dict[str, Fuente] = {}

    def leer_fuente(norma: str) -> Fuente:
        if norma not in cache:
            lineas: list[comun.Linea] = []
            try:
                lineas = comun.lineas_limpias(
                    comun.texto_de_norma(args.cache, norma, cifrados.get(norma))
                )
            except FileNotFoundError:
                pass
            xml = args.cache / f"{norma}.xml"
            cache[norma] = Fuente(
                lineas, xml.read_text(encoding="utf-8") if xml.is_file() else None
            )
        return cache[norma]

    raiz = args.salida or Path(str(files("tiza.normativa").joinpath("datos")))
    try:
        for ficha in leer_requisitos(args.requisitos):
            print(escribir_ficha(construir_ficha(ficha, leer_fuente), raiz))
    except ValueError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
