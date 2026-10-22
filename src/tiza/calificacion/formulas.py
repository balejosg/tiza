"""Las fórmulas del calificador: texto puro, sin aula ni python-moodle.

La notación interna es la de Moodle en inglés (``min``, ``floor``, separador «,», decimal con
punto). ``formula_moodle`` la pasa a la sintaxis del aula. ``publicar`` las reexporta.
"""

from __future__ import annotations

import re

__all__ = [
    "formula_copia",
    "formula_indicador",
    "formula_moodle",
    "formula_nota",
    "formula_tope",
    "texto_numero",
]


def texto_numero(valor: float) -> str:
    """Un número para un formulario o una fórmula: punto decimal y hasta 5 decimales."""
    texto = f"{round(float(valor), 5):.5f}".rstrip("0").rstrip(".")
    return texto if texto not in ("", "-0") else "0"


def formula_moodle(plantilla: str, decimal: str) -> str:
    """La fórmula interna en la sintaxis del aula.

    La notación interna es la de Moodle en inglés (``min``, ``average``, ``floor``, separador
    «,», decimal con punto).

    Si el aula muestra «,» como decimal, el separador de argumentos es «;»; con «.», se deja
    igual. Los decimales de la plantilla (siempre con punto) no se tocan.
    """
    if decimal != ",":
        return plantilla
    # Solo las comas fuera de [[...]] (el número de ID es texto y no se toca).
    partes = re.split(r"(\[\[.*?\]\])", plantilla)
    return "".join(p if p.startswith("[[") else p.replace(",", ";") for p in partes)


def formula_nota(total: str, contador: str) -> str:
    """La nota sobre 10 de un total entre su contador: las dos referencias se vacían a la vez."""
    return f"=[[{total}]]/[[{contador}]]*10"


def formula_indicador(idnumber: str, maximo: float) -> str:
    """Un indicador del contador: vale ``maximo`` cuando ``idnumber`` tiene nota, y vacío si no."""
    return f"=[[{idnumber}]]*0+{texto_numero(maximo)}"


def formula_copia(idnumber: str) -> str:
    """Una copia de una sola referencia."""
    return f"=[[{idnumber}]]"


def formula_tope(umbral: float, maximo: float, notas: list[str]) -> str:
    """La final con tope: ``min(nota, máximo + 1000*floor(min(notas)/umbral))``.

    Si alguna nota baja del umbral, ``floor`` da 0 y la final no pasa de ``maximo``; si no,
    el término enorme anula el tope. Un elemento sin ninguna nota cuenta como 0 aquí.
    Notación interna (separador «,»): pasa por ``formula_moodle``.
    """
    minimo = ",".join(f"[[{n}]]" for n in notas)
    return (
        f"=min([[TZ_TIZA]]/[[TZ_K_TIZA]]*10,"
        f"{texto_numero(maximo)}+1000*floor(min({minimo})/{texto_numero(umbral)}))"
    )
