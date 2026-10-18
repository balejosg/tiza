"""Descifrado de la Orden 3537/2025 (`herramientas/normativa/cifrado.py`).

El PDF del BOCM declara los glifos de su fuente del cuerpo como `/g38`, `/g50`… (el número
de glifo de Arial) y `pdftotext` los saca como el carácter U+00NN, sin los que Unicode tiene
por espacio (`(` y `)`). El fragmento real `bocm-20250827-6_cifrado.pdf` es un PDF mínimo con
los objetos reales de esa fuente y un trozo del contenido de la página 278. Sin red; la
prueba de punta a punta usa `pdftotext` solo si está instalado.
"""

from __future__ import annotations

import importlib
import re
import shutil
from pathlib import Path
from types import ModuleType

import pytest

FUENTES = Path(__file__).parents[2] / "herramientas" / "normativa" / "fuentes"
PDF_CIFRADO = FUENTES / "bocm-20250827-6_cifrado.pdf"


@pytest.fixture(autouse=True)
def _herramientas_en_la_ruta(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))


def herramienta(nombre: str) -> ModuleType:
    return importlib.import_module(f"herramientas.normativa.{nombre}")


def test_la_tabla_es_una_biyeccion():
    cifrado = herramienta("cifrado")
    tabla = cifrado.GLIFOS_ARIAL
    assert len(set(tabla.values())) == len(tabla)  # dos glifos no dan el mismo carácter
    assert all(len(c) == 1 for c in tabla.values())
    # el ASCII imprimible es el número de glifo menos 29 (el espacio es el glifo 3)
    assert all(tabla[g] == chr(g + 29) for g in range(3, 98))
    # y los que no son ASCII son los verificados contra la imagen de la página
    assert {g: tabla[g] for g in tabla if g > 97} == {
        105: "á",
        112: "é",
        116: "í",
        120: "ñ",
        121: "ó",
        126: "ú",
        129: "ü",
        157: "ª",
        169: "«",
        170: "»",
        179: "“",
        180: "”",
        200: "Á",
    }


def test_el_pdf_real_declara_los_glifos_por_su_nombre():
    pdf = PDF_CIFRADO.read_bytes()
    assert re.search(rb"/Differences\[2/g3/g38/g50", pdf)


def test_el_parche_redeclara_los_nombres_en_una_actualizacion_incremental():
    cifrado = herramienta("cifrado")
    original = PDF_CIFRADO.read_bytes()
    parcheado = cifrado.parchear_pdf(original, "glifos-arial")
    assert parcheado.startswith(original)  # el original no se toca
    nuevo = parcheado[len(original) :]
    assert b"/g38" not in nuevo
    assert b"/uni0043" in nuevo  # el glifo 38 es la «C»
    # el nuevo xref apunta al objeto 81 y su startxref al nuevo xref
    inicio = int(re.search(rb"startxref\s+(\d+)\s+%%EOF\s*$", parcheado)[1])
    assert parcheado[inicio:].startswith(b"xref")
    objeto = int(re.search(rb"81 1\s+(\d{10}) 00000 n", parcheado[inicio:])[1])
    assert parcheado[objeto:].startswith(b"81 0 obj")
    assert re.search(rb"/Prev \d+", nuevo)


def test_un_pdf_sin_fuente_cifrada_es_un_error():
    cifrado = herramienta("cifrado")
    with pytest.raises(ValueError, match="no hay ninguna fuente"):
        cifrado.parchear_pdf(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n", "glifos-arial")


def test_un_cifrado_desconocido_es_un_error():
    cifrado = herramienta("cifrado")
    with pytest.raises(ValueError, match="cifrado desconocido"):
        cifrado.parchear_pdf(PDF_CIFRADO.read_bytes(), "rot13")


def test_un_glifo_sin_tabla_queda_en_el_area_privada_y_se_detecta():
    cifrado = herramienta("cifrado")
    pdf = PDF_CIFRADO.read_bytes().replace(b"/g200", b"/g201")  # un glifo sin verificar
    nuevo = cifrado.parchear_pdf(pdf, "glifos-arial")
    assert b"/uniE0C9" in nuevo  # 201 = 0xC9: U+E000 + 0xC9
    with pytest.raises(ValueError, match="glifo 201"):
        cifrado.comprobar_descifrado("texto  con un glifo sin tabla")


def test_el_texto_descifrado_no_admite_controles_de_la_fuente_cifrada():
    cifrado = herramienta("cifrado")
    cifrado.comprobar_descifrado("texto normal\ncon dos líneas\f\n")
    with pytest.raises(ValueError, match="control"):
        cifrado.comprobar_descifrado("FRPSHWHQFLDV\x03GH")  # el texto cifrado de pdftotext


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="necesita pdftotext (poppler)")
def test_punta_a_punta_con_pdftotext_salen_los_signos_y_las_letras():
    comun = herramienta("comun")
    texto = comun.convertir_pdf(PDF_CIFRADO, cifrado="glifos-arial")
    lineas = [" ".join(l.split()) for l in texto.splitlines() if l.strip()]
    assert lineas[0].startswith(
        "3. Identifica la estructura de los sistemas basados en cloud o nube describiendo su"
    )
    assert "tipología y campo de aplicación." in lineas[1]
    assert lineas[2] == "a) Se han identificado los diferentes niveles de la cloud o nube."
    assert lineas[3].startswith("b) Se han identificado las principales funciones de la cloud")


def test_un_objeto_con_flujo_antes_de_la_codificacion_no_se_la_traga():
    # en el PDF real hay flujos binarios entre los objetos: el regex no puede cruzarlos
    cifrado = herramienta("cifrado")
    original = PDF_CIFRADO.read_bytes()
    flujo = b"7 0 obj\n<</Length 3>>\nstream\nabc\nendstream\nendobj\n"
    pdf = original.replace(b"81 0 obj", flujo + b"81 0 obj", 1)
    parcheado = cifrado.parchear_pdf(pdf, "glifos-arial")
    assert re.search(rb"\n81 0 obj\n<</Type/Encoding/Differences\[2/uni0020", parcheado)
    assert b"\n7 0 obj" not in parcheado[len(pdf) :]


def test_fuentes_toml_declara_el_cifrado_y_lo_valida(tmp_path):
    comun = herramienta("comun")
    registros = comun.leer_fuentes()
    assert registros["bocm-20250827-6"]["cifrado"] == "glifos-arial"
    assert registros["boe-a-2023-13221"]["cifrado"] is None
    # solo lo usa el mantenedor: no pasa al paquete
    assert "cifrado" not in comun.norma_para_el_paquete(registros["bocm-20250827-6"])
    base = Path(comun.RUTA_FUENTES).read_text(encoding="utf-8")
    malo = tmp_path / "fuentes.toml"
    malo.write_text(base.replace('cifrado = "glifos-arial"', 'cifrado = "rot13"'), encoding="utf-8")
    with pytest.raises(ValueError, match="cifrado desconocido"):
        comun.leer_fuentes(malo)


def test_un_txt_en_cache_sin_descifrar_se_rechaza_para_una_norma_cifrada(tmp_path):
    comun = herramienta("comun")
    (tmp_path / "norma.txt").write_text("FRPSHWHQFLDV\x03GH\x03", encoding="utf-8")
    with pytest.raises(ValueError, match="control"):
        comun.texto_de_norma(tmp_path, "norma", "glifos-arial")
    # una norma sin cifrado se lee tal cual
    assert comun.texto_de_norma(tmp_path, "norma") == "FRPSHWHQFLDV\x03GH\x03"
