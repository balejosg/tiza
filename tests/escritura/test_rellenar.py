"""Aplicar un relleno sobre una plantilla Word (tiza rellenar, tarea 2). Todo sintético y offline."""

from __future__ import annotations

import hashlib
import zipfile

import pytest
from docx import Document
from docx.oxml.ns import qn
from lectura import fabrica as f

from tiza import ayuda
from tiza.escritura import ErrorEscritura
from tiza.escritura.rellenar import rellenar
from tiza.escritura.relleno import (
    Borrar,
    DuplicarTabla,
    Filas,
    InsertarDespues,
    Reemplazar,
    Relleno,
)
from tiza.lectura.word import leer_docx


def preparar(tmp_path, documento, *operaciones):
    """Guarda la plantilla y devuelve el ``Relleno`` con su hash real."""
    plantilla = tmp_path / "Plantilla.docx"
    documento.save(str(plantilla))
    datos = plantilla.read_bytes()
    return Relleno(
        plantilla=plantilla,
        sha256=hashlib.sha256(datos).hexdigest(),
        salida=tmp_path / "Salida.docx",
        operaciones=tuple(operaciones),
    )


def aplicar(tmp_path, documento, *operaciones):
    relleno = preparar(tmp_path, documento, *operaciones)
    resultado = rellenar(tmp_path, relleno)
    return resultado, Document(str(resultado.salida)), leer_docx(resultado.salida)


def fallo(tmp_path, documento, *operaciones) -> ErrorEscritura:
    relleno = preparar(tmp_path, documento, *operaciones)
    with pytest.raises(ErrorEscritura) as exc:
        rellenar(tmp_path, relleno)
    assert not relleno.salida.exists()
    return exc.value


def textos(lectura):
    """``id -> texto`` de los párrafos (también los de dentro de las celdas)."""
    encontrados = {}

    def ver(bloque):
        if bloque.tipo in ("parrafo", "titulo"):
            encontrados[bloque.id] = bloque.texto
        for hijo in bloque.hijos:
            ver(hijo)

    for bloque in lectura.bloques:
        ver(bloque)
    return encontrados


def parrafo_con_formato(documento, texto, estilo="Normal", negrita=True):
    p = documento.add_paragraph(style=estilo)
    p.add_run(texto).bold = negrita or None
    return p


# --- reemplazar ---------------------------------------------------------------------------


def test_reemplazar_conserva_estilo_y_negrita(tmp_path):
    d = f.nuevo()
    parrafo_con_formato(d, "Curso 2026/2027")
    _, nuevo, lectura = aplicar(tmp_path, d, Reemplazar("p1", ("Curso 2027/2028",)))
    p = nuevo.paragraphs[0]
    assert p.text == "Curso 2027/2028"
    assert p.style.name == "Normal"
    assert [r.bold for r in p.runs] == [True]
    assert lectura.bloques[0].texto == "Curso 2027/2028"


def test_reemplazar_parrafo_con_lista_copia_el_formato(tmp_path):
    d = f.nuevo()
    parrafo_con_formato(d, "Uno", estilo="List Bullet")
    d.add_paragraph("Final")
    _, nuevo, _ = aplicar(tmp_path, d, Reemplazar("p1", ("A", "B", "C")))
    assert [p.text for p in nuevo.paragraphs] == ["A", "B", "C", "Final"]
    assert {p.style.name for p in nuevo.paragraphs[:3]} == {"List Bullet"}
    assert all(p.runs[0].bold for p in nuevo.paragraphs[:3])


def test_reemplazar_varios_runs_deja_uno_con_el_formato_del_primero(tmp_path):
    d = f.nuevo()
    p = d.add_paragraph()
    p.add_run("Hola ").italic = True
    p.add_run("mundo").bold = True
    _, nuevo, _ = aplicar(tmp_path, d, Reemplazar("p1", ("Nuevo",)))
    runs = nuevo.paragraphs[0].runs
    assert [(r.text, r.italic, r.bold) for r in runs] == [("Nuevo", True, None)]


def test_reemplazar_celda_con_tres_parrafos(tmp_path):
    d = f.nuevo()
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "Fija"
    celda = t.cell(0, 1)
    celda.paragraphs[0].style = d.styles["List Bullet"]
    celda.paragraphs[0].add_run("Vieja").bold = True
    celda.add_paragraph("Otra vieja")
    _, nuevo, lectura = aplicar(tmp_path, d, Reemplazar("t1.f1.c2", ("Uno", "Dos", "Tres")))
    parrafos = nuevo.tables[0].cell(0, 1).paragraphs
    assert [p.text for p in parrafos] == ["Uno", "Dos", "Tres"]
    assert {p.style.name for p in parrafos} == {"List Bullet"}
    assert all(p.runs[0].bold for p in parrafos)
    assert textos(lectura)["t1.f1.c1.p1"] == "Fija"


def test_reemplazar_celda_quita_tambien_la_tabla_anidada(tmp_path):
    d = f.nuevo()
    t = d.add_table(rows=1, cols=1)
    interior = t.cell(0, 0).add_table(rows=1, cols=1)
    interior.cell(0, 0).text = "Dentro"
    t.cell(0, 0).paragraphs[0].text = "Antes"
    _, nuevo, _ = aplicar(tmp_path, d, Reemplazar("t1.f1.c1", ("Solo esto",)))
    celda = nuevo.tables[0].cell(0, 0)
    assert [p.text for p in celda.paragraphs] == ["Solo esto"]
    assert celda.tables == []
    assert celda._tc.find(qn("w:tcPr")) is not None


def test_control_de_contenido_conservado(tmp_path):
    d = f.nuevo()
    f.control_en_linea(d)
    _, nuevo, lectura = aplicar(tmp_path, d, Reemplazar("p1", ("Informática",)))
    p = nuevo.paragraphs[0]._p
    controles = p.findall(qn("w:sdt"))
    assert len(controles) == 1
    assert textos(lectura)["p1"] == "Informática"
    assert [t.text for t in p.iter(qn("w:t"))] == ["Informática"]


def test_control_en_linea_pierde_el_marcador_de_ejemplo(tmp_path):
    d = f.nuevo()
    f.control_en_linea(d)
    _, nuevo, _ = aplicar(tmp_path, d, Reemplazar("p1", ("Informática",)))
    control = nuevo.paragraphs[0]._p.find(qn("w:sdt"))
    assert control.find(qn("w:sdtPr") + "/" + qn("w:showingPlcHdr")) is None
    assert control.find(qn("w:sdtPr") + "/" + qn("w:alias")) is not None
    run = control.find(qn("w:sdtContent") + "/" + qn("w:r"))
    assert run.find(qn("w:rPr") + "/" + qn("w:rStyle")) is None
    assert run.find(qn("w:rPr") + "/" + qn("w:b")) is not None  # el resto del formato se queda


def test_reemplazar_quita_los_campos_completos(tmp_path):
    d = f.nuevo()
    f.parrafo_xml(
        d,
        "<w:r><w:t>Página </w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:t>7</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        "<w:r><w:t> de total</w:t></w:r>",
    )
    _, nuevo, lectura = aplicar(tmp_path, d, Reemplazar("p1", ("Portada",)))
    p = nuevo.paragraphs[0]._p
    assert p.findall(".//" + qn("w:fldChar")) == []
    assert p.findall(".//" + qn("w:instrText")) == []
    assert textos(lectura)["p1"] == "Portada"


def test_reemplazar_parrafo_que_solo_tiene_un_campo(tmp_path):
    d = f.nuevo()
    f.parrafo_xml(
        d,
        '<w:r><w:rPr><w:i/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>'
        "<w:r><w:instrText> PAGE </w:instrText></w:r>"
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:rPr><w:i/></w:rPr><w:t>7</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>',
    )
    _, nuevo, _ = aplicar(tmp_path, d, Reemplazar("p1", ("Texto",)))
    p = nuevo.paragraphs[0]
    assert [(r.text, r.italic) for r in p.runs] == [("Texto", True)]
    assert p._p.findall(".//" + qn("w:fldChar")) == []


def test_reemplazar_con_lista_deja_el_salto_de_seccion_en_el_ultimo(tmp_path):
    d = f.nuevo()
    p = d.add_paragraph("Fin de sección")
    p._p.get_or_add_pPr().append(f.elemento("<w:sectPr/>"))
    _, nuevo, _ = aplicar(tmp_path, d, Reemplazar("p1", ("A", "B")))
    con_salto = [
        x.text
        for x in nuevo.paragraphs
        if x._p.find(qn("w:pPr") + "/" + qn("w:sectPr")) is not None
    ]
    assert con_salto == ["B"]


def test_reemplazar_en_un_hipervinculo_conserva_el_contenedor(tmp_path):
    d = f.nuevo()
    f.parrafo_xml(d, '<w:hyperlink w:anchor="x"><w:r><w:t>Enlace</w:t></w:r></w:hyperlink>')
    _, nuevo, _ = aplicar(tmp_path, d, Reemplazar("p1", ("Otro",)))
    enlace = nuevo.paragraphs[0]._p.find(qn("w:hyperlink"))
    assert enlace is not None and nuevo.paragraphs[0].text == "Otro"


# --- insertar_despues ---------------------------------------------------------------------


def test_insertar_titulo_con_estilo_en_espanol(tmp_path):
    d = f.nuevo()
    f.estilo_titulo_en_espanol(d)
    d.add_paragraph("Inicio")
    _, nuevo, lectura = aplicar(
        tmp_path, d, InsertarDespues("p1", ("Nuevo apartado",), estilo="Título 2")
    )
    p = nuevo.paragraphs[1]
    assert p.text == "Nuevo apartado"
    assert p._p.find(qn("w:pPr") + "/" + qn("w:pStyle")).get(qn("w:val")) == "Ttulo2"
    assert (lectura.bloques[1].tipo, lectura.bloques[1].nivel) == ("titulo", 2)


def test_estilo_por_styleid_y_por_nombre_en_ingles(tmp_path):
    d = f.nuevo()
    f.estilo_titulo_en_espanol(d)
    d.add_paragraph("Inicio")
    relleno = preparar(
        tmp_path,
        d,
        InsertarDespues("p1", ("A",), estilo="Ttulo2"),
        InsertarDespues("p1", ("B",), estilo="Heading 1"),
    )
    _, nuevo = rellenar(tmp_path, relleno), Document(str(relleno.salida))
    assert [p.style.name for p in nuevo.paragraphs] == ["Normal", "Heading 1", "Título 2"]


def test_estilo_inexistente_con_la_lista(tmp_path):
    d = f.nuevo()
    d.styles.element.remove(d.styles["Heading 7"].element)
    d.add_paragraph("Inicio")
    error = fallo(tmp_path, d, InsertarDespues("p1", ("X",), estilo="Heading 7"))
    assert error.codigo == "ESTILO_INEXISTENTE"
    assert "Heading 7" in error.detalle and "Normal" in error.detalle


def test_insertar_sin_estilo_copia_el_del_parrafo(tmp_path):
    d = f.nuevo()
    parrafo_con_formato(d, "Apartado", estilo="Heading 2", negrita=False).runs[0].italic = True
    _, nuevo, _ = aplicar(tmp_path, d, InsertarDespues("p1", ("Otro", "Y otro")))
    assert [p.style.name for p in nuevo.paragraphs] == ["Heading 2"] * 3
    assert all(p.runs[0].italic for p in nuevo.paragraphs)


def test_insertar_tras_una_tabla_usa_el_estilo_por_defecto(tmp_path):
    d = f.nuevo()
    f.tabla_con_total(d)
    d.add_paragraph("Final", style="Heading 1")
    _, nuevo, lectura = aplicar(tmp_path, d, InsertarDespues("t1", ("Tras la tabla",)))
    cuerpo = [e.tag for e in nuevo.element.body]
    assert cuerpo[:2] == [qn("w:tbl"), qn("w:p")]
    p = nuevo.paragraphs[0]
    assert p.text == "Tras la tabla" and p.style.name == "Normal"
    assert p.runs[0]._r.find(qn("w:rPr")) is None
    assert [b.id for b in lectura.bloques] == ["t1", "p1", "p2"]


def test_lista_numerada_continua(tmp_path):
    d = f.nuevo()
    f.lista_de_letras(d, ["Uno", "Dos", "Tres"])
    d.add_paragraph("Después")
    _, _, lectura = aplicar(tmp_path, d, InsertarDespues("p3", ("Cuatro", "Cinco")))
    assert [(b.etiqueta, b.texto) for b in lectura.bloques] == [
        ("a)", "Uno"),
        ("b)", "Dos"),
        ("c)", "Tres"),
        ("d)", "Cuatro"),
        ("e)", "Cinco"),
        ("", "Después"),
    ]


# --- filas --------------------------------------------------------------------------------


def fila(*celdas):
    return tuple((c,) if isinstance(c, str) else tuple(c) for c in celdas)


def test_filas_antes_del_total(tmp_path):
    d = f.nuevo()
    f.tabla_con_total(d)
    nuevas = (fila("RA3", "Reconoce C", "0"), fila("RA4", "Reconoce D", "0"))
    _, nuevo, lectura = aplicar(tmp_path, d, Filas("t1", 2, 4, nuevas))
    tabla = lectura.bloques[0]
    celdas = [[c.hijos[0].texto for c in fila_.hijos] for fila_ in tabla.hijos]
    assert celdas == [
        ["RA", "Resultado de aprendizaje", "%"],
        ["RA1", "Reconoce A", "40"],
        ["RA2", "Reconoce B", "60"],
        ["RA3", "Reconoce C", "0"],
        ["RA4", "Reconoce D", "0"],
        ["TOTAL", "100"],
    ]
    total = nuevo.tables[0].rows[-1]._tr
    assert (
        total.find(qn("w:tc") + "/" + qn("w:tcPr") + "/" + qn("w:gridSpan")).get(qn("w:val")) == "2"
    )


def test_filas_al_final_y_con_varios_parrafos_en_una_celda(tmp_path):
    d = f.nuevo()
    f.tabla_con_total(d)
    nueva = fila("RA9", ("Uno", "Dos"), "5")
    _, _, lectura = aplicar(tmp_path, d, Filas("t1", 2, None, (nueva,)))
    ultima = lectura.bloques[0].hijos[-1]
    assert [h.texto for h in ultima.hijos[1].hijos] == ["Uno", "Dos"]
    assert lectura.bloques[0].alto == 5


def test_filas_copian_el_formato_de_la_fila_modelo(tmp_path):
    d = f.nuevo()
    t = f.tabla_con_total(d)
    t.cell(1, 1).paragraphs[0].runs[0].italic = True
    _, nuevo, _ = aplicar(tmp_path, d, Filas("t1", 2, 4, (fila("a", "b", "c"),)))
    assert nuevo.tables[0].cell(3, 1).paragraphs[0].runs[0].italic is True


def test_fila_modelo_fusionada_rechazada(tmp_path):
    d = f.nuevo()
    f.tabla_con_total(d)
    error = fallo(tmp_path, d, Filas("t1", 4, None, (fila("a", "b"),)))
    assert error.codigo == "FILA_MODELO_FUSIONADA"


def test_fila_modelo_con_fusion_vertical_rechazada(tmp_path):
    d = f.nuevo()
    f.tabla_vmerge(d)
    error = fallo(tmp_path, d, Filas("t1", 2, None, (fila("a", "b"),)))
    assert error.codigo == "FILA_MODELO_FUSIONADA"


def test_celdas_que_no_coinciden(tmp_path):
    d = f.nuevo()
    f.tabla_con_total(d)
    error = fallo(tmp_path, d, Filas("t1", 2, 4, (fila("solo", "dos"),)))
    assert error.codigo == "CELDAS_NO_COINCIDEN"
    assert "operaciones[0].contenido[0]" in error.detalle


# --- duplicar_tabla -----------------------------------------------------------------------


def test_duplicar_tabla_de_unidad(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Antes")
    f.tabla_unidad(d)
    d.add_paragraph("Después")
    copias = ({"f1.c1": ("UNIDAD DE TRABAJO 11",)}, {"f1.c1": ("UNIDAD DE TRABAJO 12",)})
    _, _, lectura = aplicar(tmp_path, d, DuplicarTabla("t1", "t1", 2, copias))
    assert [b.id for b in lectura.bloques] == ["p1", "t1", "t2", "t3", "p2"]
    celdas = [
        [[c.hijos[0].texto for c in fila_.hijos] for fila_ in tabla.hijos]
        for tabla in lectura.bloques[1:4]
    ]
    assert celdas[0] == [["UNIDAD DE TRABAJO 1"], ["Título", "Introducción"], ["Horas", "12"]]
    assert celdas[1] == [["UNIDAD DE TRABAJO 11"]] + celdas[0][1:]
    assert celdas[2] == [["UNIDAD DE TRABAJO 12"]] + celdas[0][1:]


def test_duplicar_tablas_deja_un_parrafo_entre_ellas(tmp_path):
    d = f.nuevo()
    f.tabla_unidad(d)
    _, nuevo, _ = aplicar(tmp_path, d, DuplicarTabla("t1", "t1", 2, ({}, {})))
    etiquetas = [e.tag.rsplit("}", 1)[-1] for e in nuevo.element.body]
    assert etiquetas[:5] == ["tbl", "p", "tbl", "p", "tbl"]


def test_duplicar_lleva_lo_que_se_hizo_antes_con_la_tabla(tmp_path):
    d = f.nuevo()
    f.tabla_unidad(d)
    _, _, lectura = aplicar(
        tmp_path,
        d,
        Reemplazar("t1.f3.c2", ("99",)),
        DuplicarTabla("t1", "t1", 1, ({"f3.c1": ("Horas lectivas",)},)),
    )
    copia = lectura.bloques[1]
    assert [h.texto for h in copia.hijos[2].hijos[0].hijos] == ["Horas lectivas"]
    assert [h.texto for h in copia.hijos[2].hijos[1].hijos] == ["99"]


def test_duplicar_con_celda_inexistente(tmp_path):
    d = f.nuevo()
    f.tabla_unidad(d)
    error = fallo(tmp_path, d, DuplicarTabla("t1", "t1", 1, ({"f9.c1": ("x",)},)))
    assert error.codigo == "ID_DESCONOCIDO" and "f9.c1" in error.detalle


# --- borrar -------------------------------------------------------------------------------


def test_borrar_parrafo_fila_y_tabla(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Sobra")
    d.add_paragraph("Se queda")
    f.tabla_con_total(d)
    f.tabla_unidad(d)
    d.add_paragraph("Final")
    _, _, lectura = aplicar(tmp_path, d, Borrar("p1"), Borrar("t1.f3"), Borrar("t2"))
    assert [b.id for b in lectura.bloques] == ["p1", "t1", "p2"]
    assert textos(lectura)["p1"] == "Se queda"
    assert lectura.bloques[1].alto == 3


def test_borrar_el_unico_parrafo_de_una_celda_deja_un_parrafo_vacio(tmp_path):
    d = f.nuevo()
    f.tabla_unidad(d)
    _, nuevo, _ = aplicar(tmp_path, d, Borrar("t1.f2.c2.p1"))
    celda = nuevo.tables[0].cell(1, 1)
    assert len(celda.paragraphs) == 1 and celda.text == ""


def test_borrar_todas_las_filas_quita_la_tabla(tmp_path):
    d = f.nuevo()
    f.tabla_unidad(d)
    _, nuevo, lectura = aplicar(tmp_path, d, Borrar("t1.f1"), Borrar("t1.f2"), Borrar("t1.f3"))
    assert nuevo.tables == []
    assert nuevo.element.body.find(qn("w:p")) is not None  # el cuerpo no acaba en una tabla
    assert lectura.bloques == []


def test_borrar_fila_con_fusion_vertical_rechazada(tmp_path):
    d = f.nuevo()
    f.tabla_vmerge(d)
    for numero in (1, 2):  # el inicio y la continuación de la fusión
        error = fallo(tmp_path, d, Borrar(f"t1.f{numero}"))
        assert error.codigo == "FILA_FUSIONADA"
    assert (tmp_path / "Salida.docx").exists() is False


def test_borrar_fila_con_fusion_horizontal_vale(tmp_path):
    d = f.nuevo()
    f.tabla_con_total(d)
    _, _, lectura = aplicar(tmp_path, d, Borrar("t1.f4"))
    assert lectura.bloques[0].alto == 3


# --- resolución, plantilla y salida ---------------------------------------------------------


def test_ids_resueltos_antes_de_escribir(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Uno")
    d.add_paragraph("Dos")
    error = fallo(
        tmp_path,
        d,
        Reemplazar("p1", ("A",)),
        Reemplazar("p2", ("B",)),
        Reemplazar("p9", ("C",)),
    )
    assert error.codigo == "ID_DESCONOCIDO" and "p9" in error.detalle


def test_id_de_otro_tipo_no_vale(tmp_path):
    d = f.nuevo()
    f.tabla_unidad(d)
    error = fallo(tmp_path, d, Borrar("t1.f1.c1"))
    assert error.codigo == "ID_DESCONOCIDO"


def test_plantilla_intacta(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Uno")
    relleno = preparar(tmp_path, d, Reemplazar("p1", ("Dos",)))
    antes = hashlib.sha256(relleno.plantilla.read_bytes()).hexdigest()
    rellenar(tmp_path, relleno)
    assert hashlib.sha256(relleno.plantilla.read_bytes()).hexdigest() == antes == relleno.sha256


def test_plantilla_cambiada(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Uno")
    relleno = preparar(tmp_path, d, Reemplazar("p1", ("Dos",)))
    cambiado = Relleno(relleno.plantilla, "0" * 64, relleno.salida, relleno.operaciones)
    with pytest.raises(ErrorEscritura) as exc:
        rellenar(tmp_path, cambiado)
    assert exc.value.codigo == "PLANTILLA_CAMBIADA"
    assert not relleno.salida.exists()


def test_la_salida_existente_no_se_sobrescribe(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Uno")
    relleno = preparar(tmp_path, d, Reemplazar("p1", ("Dos",)))
    relleno.salida.write_bytes(b"del docente")
    with pytest.raises(ErrorEscritura) as exc:
        rellenar(tmp_path, relleno)
    assert exc.value.codigo == "DOCUMENTO_EXISTE"
    assert relleno.salida.read_bytes() == b"del docente"


def test_plantilla_que_no_es_un_docx(tmp_path):
    relleno = Relleno(tmp_path / "P.docx", "a" * 64, tmp_path / "S.docx", ())
    (tmp_path / "P.docx").write_bytes(b"no soy un zip")
    with pytest.raises(ErrorEscritura) as exc:
        rellenar(tmp_path, relleno)
    assert exc.value.codigo == "FORMATO_NO_ADMITIDO"


def test_plantilla_ausente(tmp_path):
    relleno = Relleno(tmp_path / "P.docx", "a" * 64, tmp_path / "S.docx", ())
    with pytest.raises(ErrorEscritura) as exc:
        rellenar(tmp_path, relleno)
    assert exc.value.codigo == "DOCUMENTO_AUSENTE"


def test_cambios_sin_aceptar_se_avisan(tmp_path):
    d = f.nuevo()
    f.parrafo_xml(d, '<w:ins w:id="1" w:author="a"><w:r><w:t>Nuevo</w:t></w:r></w:ins>')
    d.add_paragraph("Otro")
    resultado, _, _ = aplicar(tmp_path, d, Reemplazar("p2", ("Dos",)))
    assert resultado.avisos == ("CAMBIOS_SIN_ACEPTAR",)


def test_conserva_encabezado_pie_indice_y_numeracion(tmp_path):
    d = f.nuevo()
    f.indice(d)
    f.encabezado_y_pie(d, "Cabecera del departamento", "Pie de página")
    f.lista_de_letras(d, ["Uno", "Dos"])
    d.add_paragraph("Fin")
    resultado, nuevo, lectura = aplicar(
        tmp_path, d, Reemplazar("p3", ("Final",)), InsertarDespues("p2", ("Tres",))
    )
    assert resultado.operaciones == 2
    seccion = nuevo.sections[0]
    assert seccion.header.paragraphs[0].text == "Cabecera del departamento"
    assert seccion.footer.paragraphs[0].text == "Pie de página"
    assert nuevo.element.body.find(qn("w:sdt")) is not None  # el índice sigue ahí
    assert [(b.etiqueta, b.texto) for b in lectura.bloques] == [
        ("a)", "Uno"),
        ("b)", "Dos"),
        ("c)", "Tres"),
        ("", "Final"),
    ]
    with zipfile.ZipFile(resultado.salida) as zf:
        assert "word/numbering.xml" in zf.namelist()


def test_salida_fuera_de_la_carpeta(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Uno")
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    relleno = preparar(tmp_path, d, Reemplazar("p1", ("Dos",)))
    with pytest.raises(ErrorEscritura) as exc:
        rellenar(carpeta, relleno)
    assert exc.value.codigo == "FICHERO_FUERA"


def test_los_codigos_nuevos_tienen_su_texto():
    for codigo in (
        "PLANTILLA_CAMBIADA",
        "ID_DESCONOCIDO",
        "CELDAS_NO_COINCIDEN",
        "FILA_MODELO_FUSIONADA",
        "FILA_FUSIONADA",
        "ESTILO_INEXISTENTE",
    ):
        assert ayuda.explicar(codigo), codigo
