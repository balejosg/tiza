"""Tests de la página del panel (``sesion.html``): sus reglas de seguridad, sin navegador."""

from __future__ import annotations

import importlib.resources
import re

import pytest

import tiza.panel as panel_pkg
from tiza.panel.estado import TIPOS_DE_PANTALLA, Puente

CSP = (
    "default-src 'none'; script-src 'nonce-__NONCE__' 'unsafe-eval'; "
    "style-src 'nonce-__NONCE__'; img-src data:; base-uri 'none'; form-action 'none'"
)


@pytest.fixture(scope="module")
def html() -> str:
    return importlib.resources.files("tiza.panel").joinpath("sesion.html").read_text("utf-8")


@pytest.fixture(scope="module")
def sin_csp(html) -> str:
    """El HTML sin la CSP (su ``'unsafe-eval'`` no es código nuestro) ni los comentarios."""
    sin = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', "", sin)


def test_es_un_dato_del_paquete(html):
    assert html.startswith("<!doctype html>")
    assert "__NONCE__" in html


def test_no_hay_etiquetas_a_ni_otros_modos_de_navegar(html):
    sin_comentarios = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert "<a" not in sin_comentarios.lower()
    for prohibido in ("<iframe", "<object", "<embed", "<form", "<link", "<base", "<img"):
        assert prohibido not in sin_comentarios.lower(), prohibido
    assert not re.search(r"\b(href|src|action)\s*=", sin_comentarios)
    assert "javascript:" not in sin_comentarios.lower()
    assert "window.open" not in sin_comentarios and "location" not in sin_comentarios


@pytest.mark.parametrize(
    "prohibido",
    [
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "new Function",
        'setTimeout("',
        'setInterval("',
        "setAttribute",
        "srcdoc",
        "createContextualFragment",
    ],
)
def test_nada_de_html_dinamico_ni_evaluacion(sin_csp, prohibido):
    assert prohibido not in sin_csp


def test_no_se_evalua_ninguna_cadena(sin_csp):
    assert not re.search(r"\beval\b", sin_csp)
    assert not re.search(r"\bFunction\s*\(", sin_csp)


def test_sin_atributos_en_linea(sin_csp):
    assert not re.search(r"\son[a-z]+\s*=", sin_csp)  # onclick=, onload=...
    assert not re.search(r"\sstyle\s*=", sin_csp)
    assert ".style." not in sin_csp


def test_la_csp_es_la_exacta(html):
    metas = re.findall(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', html)
    assert metas == [CSP]
    assert "unsafe-inline" not in html
    assert html.count("'unsafe-eval'") == 1


def test_cada_script_y_estilo_lleva_el_nonce(html):
    etiquetas = re.findall(r"<(?:script|style)\b[^>]*>", html)
    assert len(etiquetas) == 2
    assert all(e.endswith(' nonce="__NONCE__">') for e in etiquetas), etiquetas
    assert not re.search(r"<script[^>]*\bsrc\b", html)


def test_pagina_pone_un_nonce_por_arranque_en_todos_los_sitios(html):
    uno, otro = panel_pkg.nuevo_nonce(), panel_pkg.nuevo_nonce()
    assert uno != otro and len(uno) >= 16
    texto = panel_pkg.pagina(uno)
    assert "__NONCE__" not in texto
    assert texto.count(uno) == html.count("__NONCE__") == 4
    assert re.fullmatch(r"[A-Za-z0-9_-]+", uno)  # nada que rompa el atributo


def test_hay_un_render_por_tipo_de_pantalla(sin_csp):
    for tipo in TIPOS_DE_PANTALLA:
        assert re.search(rf"\n    {tipo}: function \(p\) \{{", sin_csp), tipo
    pintores = re.search(r"var pintores = \{(.*?)\n  \};", sin_csp, re.S)
    assert pintores
    declarados = set(re.findall(r"\n    (\w+): function", pintores.group(1)))
    assert declarados == set(TIPOS_DE_PANTALLA)


def test_se_pinta_con_createelement_y_textcontent(sin_csp):
    assert "document.createElement(" in sin_csp
    assert "nodo.textContent = String(texto)" in sin_csp


def test_sondea_cada_300_ms_y_retrasa_los_botones(sin_csp):
    assert "setInterval(sondear, 300)" in sin_csp
    assert "ESPERA_BOTONES = 700" in sin_csp


def test_enseña_lo_que_tiene_que_enseñar(sin_csp):
    for texto in (
        "Ver vista previa",
        "Elegir otra carpeta…",
        "Cerrar la sesión",
        "<h1>tiza</h1>",
    ):
        assert texto in sin_csp, texto
    assert 'id="cerrar-sesion" hidden' in sin_csp
    assert "estado.sesion_abierta" in sin_csp
    assert "estado.servidor" in sin_csp and "estado.carpeta" in sin_csp
    assert 'linea.error ? "error"' in sin_csp  # los errores del registro, en rojo


def _llamadas_al_puente(texto: str) -> list[tuple[str, int]]:
    """(método, número de argumentos) de cada ``puente.<método>(...)`` de la página."""
    resultado = []
    for m in re.finditer(r"puente\.(\w+)\(", texto):
        i, nivel, argumentos, hay = m.end(), 1, 0, False
        while nivel:
            c = texto[i]
            if c in "([{":
                nivel += 1
            elif c in ")]}":
                nivel -= 1
            elif c == "," and nivel == 1:
                argumentos += 1
            if nivel and not c.isspace():
                hay = True
            i += 1
        resultado.append((m.group(1), argumentos + 1 if hay else 0))
    return resultado


def test_las_llamadas_al_puente_existen_y_no_llevan_argumentos_sobrantes(sin_csp):
    esperado = {
        "estado": 0,
        "responder": 2,
        "elegir_reciente": 2,
        "buscar_carpeta": 1,
        "terminar": 1,
        "ver_vista_previa": 2,
    }
    publicos = {n for n in dir(Puente) if not n.startswith("_")}
    llamadas = _llamadas_al_puente(sin_csp)
    assert llamadas
    for metodo, cuantos in llamadas:
        assert metodo in publicos, metodo
        assert cuantos == esperado[metodo], (metodo, cuantos)
    assert {m for m, _ in llamadas} == set(esperado)
