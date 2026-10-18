"""Tests del lector de PDF: todo con PDF sintéticos generados aquí."""

from __future__ import annotations

import pytest
from pypdf import PdfReader
from pypdf._page import PageObject
from pypdf.errors import DependencyError

from lectura import fabrica as f
from tiza.lectura import pdf as modulo
from tiza.lectura.modelo import ErrorLectura, a_texto
from tiza.lectura.pdf import leer_pdf


def escribir(tmp_path, datos, nombre="doc.pdf"):
    ruta = tmp_path / nombre
    ruta.write_bytes(datos)
    return ruta


def test_pdf_por_paginas(tmp_path):
    ruta = escribir(tmp_path, f.pdf_bytes([["Uno", "", "Dos"], ["Tres"]]))
    lectura = leer_pdf(ruta)
    assert [b.id for b in lectura.bloques] == ["g1.1", "g1.2", "g2.1"]
    assert [b.texto for b in lectura.bloques] == ["Uno", "Dos", "Tres"]
    assert all(b.tipo == "parrafo" for b in lectura.bloques)
    assert lectura.formato == "pdf" and lectura.fichero == "doc.pdf"
    assert lectura.paginas == 2
    assert len(lectura.sha256) == 64
    assert a_texto(lectura).splitlines()[0] == "[g1.1] Uno"


def test_pdf_avisa_tablas(tmp_path):
    lectura = leer_pdf(escribir(tmp_path, f.pdf_bytes([["Hola"]])))
    assert lectura.avisos == ["PDF_SIN_TABLAS"]


def test_pdf_sin_texto(tmp_path):
    with pytest.raises(ErrorLectura) as e:
        leer_pdf(escribir(tmp_path, f.pdf_bytes([[], []])))
    assert e.value.codigo == "PDF_SIN_TEXTO"


def test_pdf_cifrado(tmp_path):
    datos = f.cifrar_pdf(f.pdf_bytes([["Secreto"]]), "x")
    with pytest.raises(ErrorLectura) as e:
        leer_pdf(escribir(tmp_path, datos))
    assert e.value.codigo == "PDF_PROTEGIDO"


def test_pdf_cifrado_con_contrasena_vacia_se_lee(tmp_path):
    datos = f.cifrar_pdf(f.pdf_bytes([["Abierto"]]), "")
    lectura = leer_pdf(escribir(tmp_path, datos))
    assert lectura.bloques[0].texto == "Abierto"


def test_pdf_demasiadas_paginas(tmp_path, monkeypatch):
    monkeypatch.setattr(modulo, "MAXIMO_PAGINAS", 2)

    def prohibido(*args, **kwargs):
        raise AssertionError("no debe extraerse texto antes de comprobar el límite")

    monkeypatch.setattr(PageObject, "extract_text", prohibido)
    with pytest.raises(ErrorLectura) as e:
        leer_pdf(escribir(tmp_path, f.pdf_bytes([["a"], ["b"], ["c"]])))
    assert e.value.codigo == "DOCUMENTO_DEMASIADO_GRANDE"


def test_pdf_demasiado_grande(tmp_path, monkeypatch):
    monkeypatch.setattr(modulo, "MAXIMO_FICHERO", 100)
    with pytest.raises(ErrorLectura) as e:
        leer_pdf(escribir(tmp_path, f.pdf_bytes([["a"]])))
    assert e.value.codigo == "DOCUMENTO_DEMASIADO_GRANDE"


def test_pdf_malformado(tmp_path):
    with pytest.raises(ErrorLectura) as e:
        leer_pdf(escribir(tmp_path, b"%PDF-1.4\nesto no es un pdf"))
    assert e.value.codigo == "FORMATO_NO_ADMITIDO"
    assert e.value.detalle == "No se puede leer el PDF: está dañado o no es un PDF."


def test_pdf_no_es_pdf(tmp_path):
    with pytest.raises(ErrorLectura) as e:
        leer_pdf(escribir(tmp_path, b"hola"))
    assert e.value.codigo == "FORMATO_NO_ADMITIDO"


def test_pdf_cifrado_con_aes_sin_cryptography(tmp_path, monkeypatch):
    def sin_cryptography(self, password):
        raise DependencyError("cryptography is required for AES algorithm")

    monkeypatch.setattr(PdfReader, "decrypt", sin_cryptography)
    datos = f.cifrar_pdf(f.pdf_bytes([["Abierto"]]), "")
    with pytest.raises(ErrorLectura) as e:
        leer_pdf(escribir(tmp_path, datos))
    assert e.value.codigo == "PDF_PROTEGIDO"
