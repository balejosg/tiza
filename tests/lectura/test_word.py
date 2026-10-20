"""Tests del lector de Word: todo con documentos sintéticos generados aquí."""

from __future__ import annotations

import zipfile

import pytest

from lectura import fabrica as f
from tiza.lectura.modelo import ErrorLectura, a_texto
from tiza.lectura.word import leer_docx


def leer(documento, tmp_path, nombre="doc.docx"):
    ruta = tmp_path / nombre
    documento.save(str(ruta))
    return leer_docx(ruta)


def ids(bloques):
    return [b.id for b in bloques]


def test_orden_parrafos_y_tablas(tmp_path):
    d = f.nuevo()
    d.add_heading("Título", level=1)
    d.add_paragraph("Un párrafo")
    d.add_table(rows=1, cols=2)
    d.add_paragraph("Otro")
    lectura = leer(d, tmp_path)
    assert ids(lectura.bloques) == ["p1", "p2", "t1", "p3"]
    assert [b.tipo for b in lectura.bloques] == ["titulo", "parrafo", "tabla", "parrafo"]
    assert lectura.bloques[0].nivel == 1
    assert lectura.formato == "docx" and lectura.fichero == "doc.docx"
    assert len(lectura.sha256) == 64
    texto = a_texto(lectura)
    assert texto.splitlines()[0] == "[p1] ## Título"
    assert "[t1] tabla de 1×2" in texto and "[t1] fin" in texto


def test_celda_con_varios_parrafos(tmp_path):
    d = f.nuevo()
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "Cabecera"
    celda = t.cell(0, 1)
    celda.paragraphs[0].text = "a) Uno"
    celda.add_paragraph("b) Dos")
    lectura = leer(d, tmp_path)
    c = lectura.bloques[0].hijos[0].hijos[1]
    assert c.id == "t1.f1.c2"
    assert [h.id for h in c.hijos] == ["t1.f1.c2.p1", "t1.f1.c2.p2"]
    texto = a_texto(lectura).splitlines()
    i = texto.index("[t1.f1.c2]")
    assert texto[i + 1 : i + 3] == ["  [t1.f1.c2.p1] a) Uno", "  [t1.f1.c2.p2] b) Dos"]


def test_celdas_fusionadas_una_vez(tmp_path):
    d = f.nuevo()
    t = d.add_table(rows=3, cols=3)
    t.cell(0, 0).merge(t.cell(0, 1)).text = "Ancha"
    t.cell(0, 2).text = "X"
    t.cell(1, 0).merge(t.cell(2, 0)).text = "Alta"
    filas = leer(d, tmp_path).bloques[0].hijos
    assert len(filas[0].hijos) == 2
    assert filas[0].hijos[0].ancho == 2
    assert filas[0].hijos[0].hijos[0].texto == "Ancha"
    alta = filas[1].hijos[0]
    assert alta.alto == 2 and alta.hijos[0].texto == "Alta"
    assert len(filas[1].hijos) == 3 and len(filas[2].hijos) == 2

    d2 = f.nuevo()
    t2 = d2.add_table(rows=3, cols=1)
    t2.cell(0, 0).merge(t2.cell(2, 0)).text = "Tres"
    lectura = leer(d2, tmp_path, "b.docx")
    filas = lectura.bloques[0].hijos
    assert filas[0].hijos[0].alto == 3
    assert filas[1].hijos == [] and filas[2].hijos == []
    assert a_texto(lectura).count("Tres") == 1


def _lista_letras(d, extra=None):
    f.numeracion(
        d,
        {0: [f.nivel(0, "lowerLetter", "%1)")]},
        {1: (0, None), 2: (0, None), **(extra or {})},
    )


def test_numeracion_letras_reconstruida(tmp_path):
    d = f.nuevo()
    _lista_letras(d)
    for t in ("Uno", "Dos", "Tres"):
        f.parrafo_numerado(d, t, 1)
    for t in ("Cuatro", "Cinco"):
        f.parrafo_numerado(d, t, 2)
    lectura = leer(d, tmp_path)
    assert [b.etiqueta for b in lectura.bloques] == ["a)", "b)", "c)", "a)", "b)"]
    assert a_texto(lectura).splitlines()[2] == "[p3] c) Tres"


def test_numeracion_multinivel(tmp_path):
    d = f.nuevo()
    f.numeracion(
        d,
        {0: [f.nivel(0, "decimal", "%1."), f.nivel(1, "lowerLetter", "%1.%2)")]},
        {1: (0, None)},
    )
    for texto, nivel in [("A", 0), ("B", 1), ("C", 1), ("D", 0), ("E", 1)]:
        f.parrafo_numerado(d, texto, 1, nivel)
    et = [b.etiqueta for b in leer(d, tmp_path).bloques]
    assert et == ["1.", "1.a)", "1.b)", "2.", "2.a)"]


def test_start_override(tmp_path):
    d = f.nuevo()
    _lista_letras(d, {3: (0, 4)})
    f.parrafo_numerado(d, "Uno", 3)
    f.parrafo_numerado(d, "Dos", 3)
    assert [b.etiqueta for b in leer(d, tmp_path).bloques] == ["d)", "e)"]


def test_indice_omitido(tmp_path):
    d = f.nuevo()
    f.indice(d)
    d.add_paragraph("Texto")
    lectura = leer(d, tmp_path)
    assert ids(lectura.bloques) == ["p1"]
    assert "índice" not in a_texto(lectura)


def test_cambios_sin_aceptar(tmp_path):
    d = f.nuevo()
    f.parrafo_xml(
        d,
        '<w:r><w:t xml:space="preserve">Hola </w:t></w:r>'
        '<w:ins w:id="1" w:author="x"><w:r><w:t>mundo</w:t></w:r></w:ins>'
        '<w:del w:id="2" w:author="x"><w:r><w:delText>viejo</w:delText></w:r></w:del>',
    )
    lectura = leer(d, tmp_path)
    assert lectura.bloques[0].texto == "Hola mundo"
    assert "CAMBIOS_SIN_ACEPTAR" in lectura.avisos


def test_sin_cambios_no_hay_aviso(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Nada")
    assert leer(d, tmp_path).avisos == []


def test_doc_antiguo_rechazado(tmp_path):
    cabecera = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 64
    cifrado = tmp_path / "cifrado.docx"
    cifrado.write_bytes(cabecera + "EncryptedPackage".encode("utf-16-le"))
    with pytest.raises(ErrorLectura) as exc:
        leer_docx(cifrado)
    assert exc.value.codigo == "DOCUMENTO_PROTEGIDO"
    antiguo = tmp_path / "antiguo.docx"
    antiguo.write_bytes(cabecera + "WordDocument".encode("utf-16-le"))
    with pytest.raises(ErrorLectura) as exc:
        leer_docx(antiguo)
    assert exc.value.codigo == "FORMATO_NO_ADMITIDO"


def test_no_es_zip_ni_ooxml(tmp_path):
    ruta = tmp_path / "x.docx"
    ruta.write_bytes(b"no soy un zip")
    with pytest.raises(ErrorLectura) as exc:
        leer_docx(ruta)
    assert exc.value.codigo == "FORMATO_NO_ADMITIDO"
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("otra.xml", "<a/>")
    with pytest.raises(ErrorLectura) as exc:
        leer_docx(ruta)
    assert exc.value.codigo == "FORMATO_NO_ADMITIDO"


def test_zip_bomba(tmp_path, monkeypatch):
    d = f.nuevo()
    d.add_paragraph("x")
    datos = f.reescribir(f.a_bytes(d), "word/document.xml", b"0" * (100 * 1024 * 1024))
    ruta = tmp_path / "bomba.docx"
    ruta.write_bytes(datos)

    def prohibido(*_a, **_k):
        raise AssertionError("no debe descomprimir")

    monkeypatch.setattr(zipfile.ZipFile, "open", prohibido)
    monkeypatch.setattr(zipfile.ZipFile, "read", prohibido)
    with pytest.raises(ErrorLectura) as exc:
        leer_docx(ruta)
    assert exc.value.codigo == "DOCUMENTO_DEMASIADO_GRANDE"


def test_fichero_demasiado_grande(tmp_path, monkeypatch):
    monkeypatch.setattr("tiza.lectura.word.MAXIMO_FICHERO", 10)
    ruta = tmp_path / "g.docx"
    ruta.write_bytes(b"x" * 100)
    with pytest.raises(ErrorLectura) as exc:
        leer_docx(ruta)
    assert exc.value.codigo == "DOCUMENTO_DEMASIADO_GRANDE"


def test_fichero_bloqueado(tmp_path, monkeypatch):
    ruta = tmp_path / "b.docx"
    ruta.write_bytes(b"x")

    def negar(*_a, **_k):
        raise PermissionError("bloqueado")

    monkeypatch.setattr("tiza.lectura.word.leer_bytes_acotado", negar)
    with pytest.raises(ErrorLectura) as exc:
        leer_docx(ruta)
    assert exc.value.codigo == "FICHERO_BLOQUEADO"


def test_ids_estables(tmp_path):
    d = f.nuevo()
    d.add_heading("T", 2)
    d.add_paragraph("a")
    t = d.add_table(rows=2, cols=2)
    t.cell(1, 1).text = "z"
    ruta = tmp_path / "e.docx"
    d.save(str(ruta))
    a, b = leer_docx(ruta), leer_docx(ruta)
    assert ids(a.bloques) == ids(b.bloques)
    assert a_texto(a) == a_texto(b)
    assert a.sha256 == b.sha256


def test_titulo_por_nombre_y_outline(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Uno", style="Heading 3")
    p = d.add_paragraph("Dos")
    p._p.get_or_add_pPr().append(f.elemento('<w:outlineLvl w:val="1"/>'))
    d.add_paragraph("Tres")
    b = leer(d, tmp_path).bloques
    assert [(x.tipo, x.nivel) for x in b] == [("titulo", 3), ("titulo", 2), ("parrafo", 0)]
    assert b[0].estilo.lower() == "heading 3"


def test_tabla_anidada_y_campos(tmp_path):
    d = f.nuevo()
    t = d.add_table(rows=1, cols=1)
    interior = t.cell(0, 0).add_table(rows=1, cols=1)
    interior.cell(0, 0).text = "dentro"
    f.parrafo_xml(
        d,
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGE </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>7</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>',
    )
    lectura = leer(d, tmp_path)
    celda = lectura.bloques[0].hijos[0].hijos[0]
    anidada = [h for h in celda.hijos if h.tipo == "tabla"][0]
    assert anidada.id == "t1.f1.c1.t1"
    assert anidada.hijos[0].hijos[0].hijos[0].texto == "dentro"
    assert lectura.bloques[1].texto == "7"


def test_error_inesperado_al_interpretar_no_escapa(tmp_path, monkeypatch):
    d = f.nuevo()
    d.add_paragraph("x")

    def roto(self, *_args, **_kw):
        raise RecursionError("texto de la librería")

    monkeypatch.setattr("tiza.lectura.word._Lector.contenido", roto)
    with pytest.raises(ErrorLectura) as e:
        leer(d, tmp_path)
    assert e.value.codigo == "FORMATO_NO_ADMITIDO"
    assert e.value.detalle == "No se puede interpretar el documento."


# --- Encabezados y pies --------------------------------------------------------------------


def test_encabezados_y_pies_tienen_ids_por_primera_aparicion(tmp_path):
    d = f.nuevo()
    f.dos_secciones(d)
    lectura = leer(d, tmp_path)
    assert ids(lectura.bloques) == ["p1", "p2", "p3"]
    assert [(b.id, b.tipo) for b in lectura.partes] == [
        ("e1", "encabezado"),
        ("pie1", "pie"),
        ("pie2", "pie"),
    ]
    assert [[(h.id, h.texto) for h in b.hijos] for b in lectura.partes] == [
        [("e1.p1", "Curso 2026/27")],
        [("pie1.p1", "Página 1")],
        [("pie2.p1", "Departamento de Informática")],
    ]
    assert a_texto(lectura).splitlines()[3:] == [
        "[e1] encabezado",
        "  [e1.p1] Curso 2026/27",
        "[e1] fin",
        "[pie1] pie",
        "  [pie1.p1] Página 1",
        "[pie1] fin",
        "[pie2] pie",
        "  [pie2.p1] Departamento de Informática",
        "[pie2] fin",
    ]


def test_los_ids_del_cuerpo_no_cambian_con_encabezados_y_pies(tmp_path):
    con = f.nuevo()
    f.dos_secciones(con)
    sin = f.nuevo()
    sin.add_paragraph("Antes 1")
    sin.add_paragraph("Antes 2")
    sin.add_section()
    sin.add_paragraph("Después")
    leida_con, leida_sin = leer(con, tmp_path, "con.docx"), leer(sin, tmp_path, "sin.docx")
    assert leida_sin.partes == []
    assert leida_con.bloques == leida_sin.bloques
    assert a_texto(leida_con).startswith(a_texto(leida_sin))


def test_una_parte_sin_texto_no_sale_pero_no_cambia_los_ids_de_las_demas(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Uno")
    d.add_section()
    d.add_paragraph("Dos")
    primera, segunda = d.sections
    primera.header.paragraphs[0].text = ""  # e1, sin texto
    primera.footer.paragraphs[0].text = ""  # pie1, sin texto
    segunda.header.is_linked_to_previous = False
    segunda.header.paragraphs[0].text = "Curso 2026/27"  # e2
    segunda.footer.is_linked_to_previous = False
    segunda.footer.paragraphs[0].text = "Pie"  # pie2
    lectura = leer(d, tmp_path)
    assert [b.id for b in lectura.partes] == ["e2", "pie2"]


def test_tablas_en_un_encabezado_usan_el_mismo_recorrido(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Cuerpo")
    cabecera = d.sections[0].header
    tabla = cabecera.add_table(1, 2, d.sections[0].page_width)
    tabla.cell(0, 0).text = "Curso 2026/27"
    tabla.cell(0, 1).text = "IES Ejemplo"
    lectura = leer(d, tmp_path)
    (encabezado,) = lectura.partes
    assert encabezado.id == "e1"
    assert encabezado.hijos[0].id == "e1.t1"
    assert [c.id for c in encabezado.hijos[0].hijos[0].hijos] == ["e1.t1.f1.c1", "e1.t1.f1.c2"]
    assert "  [e1.t1.f1.c1]\n    [e1.t1.f1.c1.p1] Curso 2026/27" in a_texto(lectura)
