"""Tests de los textos «Qué hacer» de cada código de error."""

from __future__ import annotations

import re
from pathlib import Path

from tiza import ayuda

SRC = Path(__file__).resolve().parents[1] / "src" / "tiza"

# Dónde nace un código que llega al docente o al agente.
_PATRONES = (
    re.compile(r'Error[A-Za-z]*\(\s*"([A-Z][A-Z0-9_]+)"'),
    re.compile(r'_fallo\(\s*\w+,\s*"([A-Z][A-Z0-9_]+)"'),
    re.compile(r'_informe_error\(\s*\w+,\s*"([A-Z][A-Z0-9_]+)"'),
    re.compile(r'_reducir\(\s*"([A-Z][A-Z0-9_]+)"'),
    re.compile(r'\[\s*"([A-Z][A-Z0-9_]+)"\s*\]'),
    re.compile(r"ERROR \[([A-Z][A-Z0-9_]+)\]"),
    re.compile(r'_imprimir_error\(\s*"([A-Z][A-Z0-9_]+)"'),
    re.compile(r'errores\.append\(\s*"([A-Z][A-Z0-9_]+)"'),
    # El borrador del informe acumula los códigos de error (no los pasos: esos
    # no son códigos de error y tienen su propio registro, informe.PASOS).
    re.compile(r'borrador\.error\(\s*"([A-Z][A-Z0-9_]+)"'),
)
# informe.py valida el esquema; sus códigos nunca llegan al usuario como código
# de error (se descartan o se convierten en ERROR_INTERNO).
_EXCLUIDOS = {"informe.py"}


def codigos_del_codigo_fuente() -> set[str]:
    codigos: set[str] = set()
    for ruta in SRC.rglob("*.py"):
        if ruta.name in _EXCLUIDOS:
            continue
        texto = ruta.read_text(encoding="utf-8")
        for patron in _PATRONES:
            codigos.update(patron.findall(texto))
    return codigos


def test_todo_codigo_del_codigo_fuente_tiene_explicacion():
    faltan = sorted(c for c in codigos_del_codigo_fuente() if ayuda.explicar(c) is None)
    assert faltan == []


def test_encuentra_codigos_conocidos():
    # Si el patrón deja de encontrar códigos, el test anterior pasaría en falso.
    codigos = codigos_del_codigo_fuente()
    assert {
        "SIN_SESION",
        "SESION_CADUCADA",
        "LOGIN_FALLIDO",
        "URL_INACCESIBLE",
        "SECCION_ES_ID",
    } <= codigos


def test_textos_son_de_una_linea_y_seguros():
    for codigo, texto in ayuda.MENSAJES.items():
        assert re.fullmatch(r"[A-Z][A-Z0-9_]{1,39}", codigo), codigo
        assert texto.strip() == texto and texto, codigo
        assert len(texto) <= 300, codigo
        assert not re.search(r"[<>\x00-\x1f\x7f]", texto), codigo


def test_codigo_desconocido_da_none():
    assert ayuda.explicar("NO_EXISTE") is None
