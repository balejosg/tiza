"""Tests de la página del panel (``sesion.html``): sus reglas de seguridad, sin navegador."""

from __future__ import annotations

import base64
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
    for prohibido in ("<iframe", "<object", "<embed", "<form", "<link", "<base"):
        assert prohibido not in sin_comentarios.lower(), prohibido
    # La única imagen es el logo del paquete, que ``pagina`` convierte en un data: URI.
    assert len(re.findall(r"<img\b", sin_comentarios, re.I)) == 1
    sin_logo = re.sub(r'<img\b[^>]*\bsrc="__LOGO__"[^>]*>', "", sin_comentarios)
    assert not re.search(r"\b(href|src|action)\s*=", sin_logo)
    assert 'src="__LOGO__"' in sin_comentarios
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


def test_pagina_incrusta_el_logo_del_paquete_como_data_uri():
    texto = panel_pkg.pagina("nonce")
    assert "__LOGO__" not in texto
    logos = re.findall(r'src="data:image/png;base64,([A-Za-z0-9+/=]+)"', texto)
    assert len(logos) == 1
    assert base64.b64decode(logos[0]).startswith(b"\x89PNG\r\n\x1a\n")


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
    assert 'id="insignia"' in sin_csp and "estado.caduca" in sin_csp
    assert "Sesión abierta · quedan " in sin_csp
    assert "minutos < estado.aviso_minutos" in sin_csp
    assert 'id="pasos"' in sin_csp and "pintarPasos(estado.paso)" in sin_csp
    for campo in ("texto_si", "texto_no", "riesgo"):
        assert campo in sin_csp, campo
    assert 'p.riesgo === "real"' in sin_csp and 'p.riesgo === "peligro"' in sin_csp
    assert "button.real" in sin_csp


def test_valida_en_linea_y_no_llama_al_puente_con_datos_invalidos(sin_csp):
    for texto in (
        "Escribe solo el número que va tras id=",
        "Escribe los ids separados por comas.",
        "Escribe solo números separados por comas.",
        "Como mucho ",
        "Hay ids repetidos.",
        "Marca al menos un curso.",
        "Escribe la dirección del aula.",
        "Escribe tu usuario.",
    ):
        assert texto in sin_csp, texto
    assert 'ponerError(errorUrl, direccion ? "" : "Escribe la dirección del aula.")' in sin_csp
    assert "if (!direccion || !nombre) { return; }" in sin_csp
    assert "usar.condicion" in sin_csp and "actualizarBoton(usar)" in sin_csp
    assert 'contador.textContent = marcadas() + " de " + p.maximo + " marcados"' in sin_csp


def test_enter_solo_pulsa_el_boton_principal_cuando_ya_esta_habilitado(sin_csp):
    assert 'evento.key !== "Enter"' in sin_csp
    assert 'evento.target.tagName !== "INPUT"' in sin_csp
    assert "if (botonPrincipal && !botonPrincipal.disabled) { botonPrincipal.click(); }" in sin_csp
    assert "actualizarBoton(usarId)" in sin_csp


def test_el_foco_va_al_titulo_y_en_configurar_al_primer_campo_vacio(sin_csp):
    assert "titulo.tabIndex = -1;" in sin_csp
    assert "titulo.focus();" in sin_csp
    assert "if (!campos[i].value) { destino = campos[i]; break; }" in sin_csp
    assert "if (destino) { destino.focus(); }" in sin_csp


def test_la_zona_de_anuncio_es_corta_y_no_toda_la_tarjeta(sin_csp):
    assert '<p id="anuncio" class="sr-only" aria-live="polite"></p>' in sin_csp
    assert '<section id="pantalla" class="tarjeta">' in sin_csp
    assert 'document.getElementById("anuncio").textContent = pantalla.titulo || ""' in sin_csp


def test_las_confirmaciones_largas_llevan_barra_fija(sin_csp):
    assert "position: sticky" in sin_csp and "bottom: 0" in sin_csp
    assert sin_csp.count("nodos.push(acciones(p.pregunta, siNo(p)))") == 2
    assert "function acciones(pregunta, cajaBotones)" in sin_csp


def test_cerrar_la_sesion_se_confirma_en_dos_pasos(sin_csp):
    assert "Cerrar la sesión y salir" in sin_csp
    assert "El asistente dejará de poder publicar. ¿Cerrar?" in sin_csp
    assert 'id="cerrar-de-verdad" class="peligro"' in sin_csp
    assert "Seguir trabajando" in sin_csp
    assert sin_csp.count("puente.terminar(") == 1
    assert (
        'document.getElementById("cerrar-sesion").addEventListener("click", function () {\n    cierrePreguntado = true;'
        in sin_csp
    )
    assert (
        'document.getElementById("seguir-trabajando").addEventListener("click", retirarCierre)'
        in sin_csp
    )


def test_el_registro_se_pliega_mientras_hay_pregunta(sin_csp):
    assert "registroPlegado" in sin_csp and "ultimaPregunta" in sin_csp
    assert '"Ver registro (" + ultimoRegistro.length' in sin_csp
    assert '"Ocultar registro"' in sin_csp
    assert "pintarPlegado(estado.pregunta === true)" in sin_csp
    assert "if (abajo) { ul.scrollTop = ul.scrollHeight; }" in sin_csp
    assert "if (estabaPlegado && !registroPlegado) { ul.scrollTop = ul.scrollHeight; }" in sin_csp


def test_la_ampliacion_cuenta_atras_desde_el_plazo(sin_csp):
    assert "limiteAmpliar" in sin_csp and 'id = "cuenta-ampliar"' in sin_csp
    assert '"La sesión se cierra en " + minutos + ":"' in sin_csp
    assert "Date.now() + pantalla.plazo * 1000" in sin_csp


def test_las_recientes_y_los_cursos_son_filas_con_pista_y_quitar(sin_csp):
    assert "button.fila" in sin_csp and "fila-reciente" in sin_csp
    assert "puente.quitar_reciente(p.numero, opcion.indice)" in sin_csp
    assert 'boton("Quitar", "quitar"' in sin_csp
    assert 'el("span", "pista", opcion.pista)' in sin_csp
    assert 'el("span", "nombre", opcion.texto)' in sin_csp
    assert 'el("label", "casilla fila")' in sin_csp


def test_el_registro_lleva_hora_y_se_puede_copiar(sin_csp):
    assert 'el("span", "hora", linea.hora)' in sin_csp
    assert "navigator.clipboard.writeText(texto)" in sin_csp
    assert "Copiar el registro" in sin_csp and '"Copiado"' in sin_csp
    assert 'id="copiar-registro" hidden' in sin_csp
    assert "copiar.hidden = true;  // si el portapapeles no vale" in sin_csp


def test_la_pantalla_final_ofrece_volver_a_empezar(sin_csp):
    assert 'p.texto_si || "Volver a empezar"' in sin_csp
    assert "final: function (p)" in sin_csp
    assert "responder(p.numero, true);" in sin_csp


def test_pulido_visual_con_movimiento_reducido_y_modo_oscuro(sin_csp):
    assert "@media (prefers-color-scheme: dark)" in sin_csp
    assert "--fondo: #171A1D" in sin_csp and "--papel: #23272B" in sin_csp
    assert "--error: #FF9B85" in sin_csp and "--aviso: #F0C060" in sin_csp
    assert "@media (prefers-reduced-motion: reduce)" in sin_csp
    assert ".puntos span { animation: none; opacity: .7; }" in sin_csp
    assert "@media (max-height: 600px)" in sin_csp
    assert "header h1 { display: none; }" in sin_csp
    assert "transition: background .12s, border-color .12s, opacity .25s" in sin_csp
    assert 'p.titulo === "Conectando…"' in sin_csp
    assert 'conPuntos("Esperando…")' in sin_csp
    assert 'conPuntos("Esperando a que entres en la ventana del aula…")' in sin_csp


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
        "quitar_reciente": 2,
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
