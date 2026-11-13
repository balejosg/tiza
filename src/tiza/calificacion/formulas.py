"""Las fórmulas del calificador: texto puro, sin aula ni python-moodle.

La notación interna es la de Moodle en inglés (``min``, ``floor``, separador «,», decimal con
punto). ``formula_moodle`` la pasa a la sintaxis del aula. ``publicar`` las reexporta.
"""

from __future__ import annotations

import re

__all__ = [
    "formula_copia",
    "formula_moodle",
    "formula_resultado",
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


def formula_copia(idnumber: str) -> str:
    """Una copia de una sola referencia."""
    return f"=[[{idnumber}]]"


def formula_resultado(idnumber: str, niveles: int) -> str:
    """Un resultado del aula (1..niveles) reescalado a 0-100, con la escala lineal.

    La escala de ``idnumber`` debe estar ordenada de menor a mayor: el nivel 1 es el más bajo
    y ``niveles`` el más alto. La escala del aula la crea la publicación así (Tarea 3); los
    niveles de ``niveles_rubrica`` se ordenan antes de enviarlos. S2 midió que el resultado no
    se puede ponderar directamente en media ponderada: este calculado lleva el peso.
    """
    if niveles < 2:
        raise ValueError("formula_resultado necesita al menos 2 niveles")
    return f"=([[{idnumber}]]-1)/{niveles - 1}*100"


def formula_tope(umbral: float, maximo: float, notas: list[str]) -> str:
    """La final con tope, sobre 100: ``min(nota, máximo·10 + 1000·floor(min(notas)/(umbral·10)))``.

    Las notas son los totales de los elementos (``TZ_E_<id>``), ya sobre 100. Si alguna baja
    del umbral, ``floor`` da 0 y la final no pasa de ``maximo·10``; si no, el término enorme
    anula el tope. Sin notas activas (ninguna evaluación cerrada todavía) no hay ``min``: la
    final es ``TZ_FINAL``. Notación interna (separador «,»): pasa por ``formula_moodle``.
    """
    if not notas:
        return formula_copia("TZ_FINAL")
    minimo = ",".join(f"[[{n}]]" for n in notas)
    return (
        f"=min([[TZ_FINAL]],{texto_numero(maximo * 10)}+"
        f"1000*floor(min({minimo})/{texto_numero(umbral * 10)}))"
    )
