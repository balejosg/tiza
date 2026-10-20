"""Aplicar un relleno sobre una plantilla Word (tiza rellenar, tarea 2). Todo sintético y offline."""

from __future__ import annotations

import hashlib
import zipfile
from collections import Counter

import pytest
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from lectura import fabrica as f

from dobles import enlace_simbolico
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
from tiza.lectura.modelo import ErrorLectura
from tiza.lectura.word import analizar_docx, leer_docx


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
    assert [p.style.name for p in nuevo.paragraphs] == ["Normal", "Título 2", "Heading 1"]


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


# --- ronda de arreglos 1 ------------------------------------------------------------------

WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def test_reemplazar_deja_sin_marcador_de_ejemplo_a_todos_los_controles(tmp_path):
    d = f.nuevo()
    f.parrafo_xml(
        d,
        '<w:r><w:t xml:space="preserve">Módulo: </w:t></w:r>'
        '<w:sdt><w:sdtPr><w:id w:val="5"/><w:showingPlcHdr/></w:sdtPr><w:sdtContent>'
        '<w:r><w:rPr><w:rStyle w:val="PlaceholderText"/></w:rPr><w:t>Haga clic aquí</w:t></w:r>'
        "</w:sdtContent></w:sdt>",
    )
    _, nuevo, lectura = aplicar(tmp_path, d, Reemplazar("p1", ("Módulo: Informática",)))
    controles = list(nuevo.element.body.iter(qn("w:sdt")))
    assert controles and all(c.find(".//" + qn("w:showingPlcHdr")) is None for c in controles)
    assert textos(lectura)["p1"] == "Módulo: Informática"


def plantilla_con_ids(d):
    """Una tabla con paraId/textId, un control con id y una imagen con id (en celdas distintas)."""
    t = f.tabla_unidad(d)
    for n, p in enumerate(d.element.body.iter(qn("w:p")), start=1):
        p.set(f"{{{W14}}}paraId", f"0000{n:04X}")
        p.set(f"{{{W14}}}textId", "77777777")
    for n, tr in enumerate(t._tbl.iter(qn("w:tr")), start=1):
        tr.set(f"{{{W14}}}paraId", f"1000{n:04X}")
    celda = t.cell(1, 1)._tc
    celda.append(
        f.elemento(
            '<w:sdt><w:sdtPr><w:id w:val="41"/></w:sdtPr><w:sdtContent>'
            "<w:p><w:r><w:t>Control</w:t></w:r></w:p></w:sdtContent></w:sdt>"
        )
    )
    celda.append(
        parse_xml(
            f'<w:p xmlns:w="{WORD}" xmlns:wp="{WP}"><w:r><w:drawing><wp:inline>'
            '<wp:docPr id="7" name="Imagen"/></wp:inline></w:drawing></w:r>'
            '<w:bookmarkStart w:id="3" w:name="m"/><w:bookmarkEnd w:id="3"/></w:p>'
        )
    )
    return t


def comprobar_ids_unicos(documento):
    cuerpo = documento.element.body
    para = Counter(p.get(f"{{{W14}}}paraId") for p in cuerpo.iter() if p.get(f"{{{W14}}}paraId"))
    assert [k for k, v in para.items() if v > 1] == []
    sdt = Counter(i.get(qn("w:val")) for i in cuerpo.iter(qn("w:id")))
    assert [k for k, v in sdt.items() if v > 1] == []
    imagenes = Counter(i.get("id") for i in cuerpo.iter(f"{{{WP}}}docPr"))
    assert [k for k, v in imagenes.items() if v > 1] == []


def test_las_copias_no_repiten_ids(tmp_path):
    d = f.nuevo()
    plantilla_con_ids(d)
    _, nuevo, _ = aplicar(
        tmp_path,
        d,
        DuplicarTabla("t1", "t1", 2, ({}, {})),
        Filas("t1", 3, None, (fila("a", "b"), fila("c", "d"))),
    )
    comprobar_ids_unicos(nuevo)
    assert len(list(nuevo.element.body.iter(qn("w:sdt")))) == 3
    assert len(list(nuevo.element.body.iter(f"{{{WP}}}docPr"))) == 3
    # Lo copiado no lleva marcadores; el original conserva el suyo.
    assert len(list(nuevo.element.body.iter(qn("w:bookmarkStart")))) == 1


def test_filas_no_copian_marcadores(tmp_path):
    d = f.nuevo()
    t = f.tabla_unidad(d)
    t.cell(1, 0).paragraphs[0]._p.append(f.elemento('<w:bookmarkStart w:id="3" w:name="m"/>'))
    t.cell(1, 0).paragraphs[0]._p.append(f.elemento('<w:bookmarkEnd w:id="3"/>'))
    _, nuevo, _ = aplicar(tmp_path, d, Filas("t1", 2, None, (fila("a", "b"),)))
    assert len(list(nuevo.element.body.iter(qn("w:bookmarkStart")))) == 1


def test_duplicar_separa_tambien_de_la_tabla_que_viene_detras(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Antes")
    f.tabla_unidad(d)
    _, nuevo, lectura = aplicar(tmp_path, d, DuplicarTabla("t1", "p1", 1, ({},)))
    etiquetas = [e.tag.rsplit("}", 1)[-1] for e in nuevo.element.body][:5]
    assert etiquetas == ["p", "tbl", "p", "tbl", "sectPr"]
    assert [b.id for b in lectura.bloques] == ["p1", "t1", "t2"]


def test_antes_de_una_continuacion_de_fusion_rechazado(tmp_path):
    d = f.nuevo()
    f.tabla_vmerge(d)
    error = fallo(tmp_path, d, Filas("t1", 3, 2, (fila("a", "b"),)))
    assert error.codigo == "FILA_FUSIONADA"
    assert "operaciones[0]" in error.detalle


def test_antes_del_inicio_de_una_fusion_vale(tmp_path):
    d = f.nuevo()
    f.tabla_vmerge(d)
    _, _, lectura = aplicar(tmp_path, d, Filas("t1", 3, 1, (fila("a", "b"),)))
    assert lectura.bloques[0].alto == 4


def test_el_mapa_de_ids_coincide_con_los_bloques_de_la_lectura(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Uno")
    d.add_paragraph("")
    f.tabla_vmerge(d)
    d.add_paragraph("")
    d.element.body.insert(
        3,
        f.elemento(
            "<w:sdt><w:sdtPr/><w:sdtContent><w:p><w:r><w:t>En el control</w:t></w:r></w:p>"
            "</w:sdtContent></w:sdt>"
        ),
    )
    anidada = d.add_table(rows=2, cols=2)
    anidada.cell(0, 0).text = "Fuera"
    interior = anidada.cell(0, 1).add_table(rows=1, cols=2)
    interior.cell(0, 0).text = "Dentro"
    anidada.cell(0, 1).add_paragraph("Tras la anidada")
    d.add_paragraph("")
    d.add_paragraph("Último")
    ruta = tmp_path / "doc.docx"
    d.save(str(ruta))
    analisis = analizar_docx(ruta.read_bytes(), ruta.name)

    ids = []

    def recoger(bloque):
        ids.append(bloque.id)
        for hijo in bloque.hijos:
            recoger(hijo)

    for bloque in analisis.lectura.bloques:
        recoger(bloque)
    assert "t2.f1.c2.t1.f1.c1.p1" in ids and "p2" in ids and any(".c2" in i for i in ids)
    assert set(analisis.mapa) == set(ids) and len(ids) == len(set(ids))
    etiquetas = {"p": "p", "t": "tbl", "f": "tr", "c": "tc"}
    for id_, elemento in analisis.mapa.items():
        ultimo = id_.rsplit(".", 1)[-1]
        assert elemento.tag == qn(f"w:{etiquetas[ultimo[0]]}"), id_


def tabla_con_celda_en_control_de_fila(d):
    """Tabla de una fila de dos celdas; la primera va dentro de un control de fila con marcador."""
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "Haga clic aquí"
    t.cell(0, 1).text = "Fija"
    tc = t._tbl.find(qn("w:tr")).find(qn("w:tc"))
    control = f.elemento("<w:sdt><w:sdtPr><w:showingPlcHdr/></w:sdtPr><w:sdtContent/></w:sdt>")
    tc.addprevious(control)
    control.find(qn("w:sdtContent")).append(tc)
    return t


def test_reemplazar_celda_quita_el_marcador_del_control_de_fila(tmp_path):
    d = f.nuevo()
    tabla_con_celda_en_control_de_fila(d)
    assert [c.id for c in leer_docx_de(tmp_path, d).bloques[0].hijos[0].hijos] == [
        "t1.f1.c1",
        "t1.f1.c2",
    ]
    _, nuevo, lectura = aplicar(tmp_path, d, Reemplazar("t1.f1.c1", ("Informática",)))
    controles = list(nuevo.element.body.iter(qn("w:sdt")))
    assert len(controles) == 1 and controles[0].find(".//" + qn("w:showingPlcHdr")) is None
    assert textos(lectura)["t1.f1.c1.p1"] == "Informática"


def test_filas_quitan_el_marcador_del_control_de_fila_copiado(tmp_path):
    d = f.nuevo()
    tabla_con_celda_en_control_de_fila(d)
    _, nuevo, lectura = aplicar(tmp_path, d, Filas("t1", 1, None, (fila("A", "B"),)))
    controles = list(nuevo.element.body.iter(qn("w:sdt")))
    assert len(controles) == 2
    assert [c.find(".//" + qn("w:showingPlcHdr")) is None for c in controles] == [False, True]
    assert textos(lectura)["t1.f2.c1.p1"] == "A"


def leer_docx_de(tmp_path, documento):
    ruta = tmp_path / "previa.docx"
    documento.save(str(ruta))
    return leer_docx(ruta)


# --- ronda de arreglos de la revisión final ----------------------------------------------


def _orden(nuevo):
    return [p.text for p in nuevo.paragraphs]


def test_dos_insertar_despues_sobre_la_misma_ancla_salen_en_el_orden_del_yaml(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Uno")
    d.add_paragraph("Dos")
    _, nuevo, _ = aplicar(
        tmp_path,
        d,
        InsertarDespues("p1", ("A1", "A2")),
        InsertarDespues("p1", ("B1",)),
    )
    assert _orden(nuevo) == ["Uno", "A1", "A2", "B1", "Dos"]


def test_dos_duplicar_tabla_tras_la_misma_ancla_salen_en_el_orden_del_yaml(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Ancla")
    f.tabla_unidad(d)
    d.add_paragraph("Final")
    _, _, lectura = aplicar(
        tmp_path,
        d,
        DuplicarTabla("t1", "p1", 1, ({"f1.c1": ("PRIMERA",)},)),
        DuplicarTabla("t1", "p1", 1, ({"f1.c1": ("SEGUNDA",)},)),
    )
    cabeceras = [b.hijos[0].hijos[0].hijos[0].texto for b in lectura.bloques if b.tipo == "tabla"]
    assert cabeceras == ["PRIMERA", "SEGUNDA", "UNIDAD DE TRABAJO 1"]


def test_insertar_despues_y_duplicar_tabla_tras_la_misma_ancla_en_orden(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Ancla")
    f.tabla_unidad(d)
    _, nuevo, _ = aplicar(
        tmp_path,
        d,
        InsertarDespues("p1", ("Título",)),
        DuplicarTabla("t1", "p1", 1, ({"f1.c1": ("COPIA",)},)),
        InsertarDespues("p1", ("Cierre",)),
    )
    etiquetas = []
    for hijo in nuevo.element.body:
        if hijo.tag == qn("w:p"):
            etiquetas.append("".join(t.text or "" for t in hijo.iter(qn("w:t"))))
        elif hijo.tag == qn("w:tbl"):
            etiquetas.append("tabla")
    assert etiquetas[:6] == ["Ancla", "Título", "tabla", "Cierre", "", "tabla"]


def test_borrar_el_parrafo_entre_dos_tablas_deja_un_parrafo_vacio(tmp_path):
    d = f.nuevo()
    f.tabla_unidad(d)
    d.add_paragraph("Separador")
    f.tabla_unidad(d)
    d.add_paragraph("Final")
    _, nuevo, _ = aplicar(tmp_path, d, Borrar("p1"))
    etiquetas = [e.tag.rsplit("}", 1)[-1] for e in nuevo.element.body]
    assert etiquetas[:4] == ["tbl", "p", "tbl", "p"]
    assert "".join(t.text or "" for t in nuevo.element.body[1].iter(qn("w:t"))) == ""


# --- enlaces simbólicos hacia fuera de la carpeta -----------------------------------------


def _entorno_con_fuera(tmp_path):
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    d = f.nuevo()
    d.add_paragraph("Uno")
    real = fuera / "Real.docx"
    d.save(str(real))
    return carpeta, fuera, real


def _yaml_relleno(carpeta, plantilla, salida, sha):
    ruta = carpeta / "relleno.yaml"
    ruta.write_text(
        f'plantilla: "{plantilla}"\nsha256: "{sha}"\nsalida: "{salida}"\n'
        "operaciones:\n  - op: reemplazar\n    id: p1\n    texto: Dos\n",
        encoding="utf-8",
    )
    return ruta


def test_rellenar_plantilla_enlace_hacia_fuera_da_fichero_fuera(tmp_path):
    carpeta, fuera, real = _entorno_con_fuera(tmp_path)
    enlace = carpeta / "Plantilla.docx"
    enlace_simbolico(enlace, real)
    relleno = Relleno(
        enlace,
        hashlib.sha256(real.read_bytes()).hexdigest(),
        carpeta / "Salida.docx",
        (Reemplazar("p1", ("Dos",)),),
    )
    with pytest.raises(ErrorEscritura) as exc:
        rellenar(carpeta, relleno)
    assert exc.value.codigo == "FICHERO_FUERA"
    assert not (carpeta / "Salida.docx").exists()


def test_rellenar_salida_enlace_colgante_hacia_fuera_no_crea_nada_fuera(tmp_path):
    carpeta, fuera, real = _entorno_con_fuera(tmp_path)
    plantilla = carpeta / "Plantilla.docx"
    plantilla.write_bytes(real.read_bytes())
    enlace = carpeta / "Salida.docx"
    enlace_simbolico(enlace, fuera / "Nuevo.docx")
    relleno = Relleno(
        plantilla,
        hashlib.sha256(real.read_bytes()).hexdigest(),
        enlace,
        (Reemplazar("p1", ("Dos",)),),
    )
    with pytest.raises(ErrorEscritura) as exc:
        rellenar(carpeta, relleno)
    assert exc.value.codigo == "FICHERO_FUERA"
    assert not (fuera / "Nuevo.docx").exists()
    assert sorted(p.name for p in fuera.iterdir()) == ["Real.docx"]


def test_agente_rellenar_con_enlaces_hacia_fuera_da_fichero_fuera(tmp_path):
    from tiza import agente

    carpeta, fuera, real = _entorno_con_fuera(tmp_path)
    sha = hashlib.sha256(real.read_bytes()).hexdigest()

    # El propio relleno.yaml es un enlace a un YAML de fuera.
    externo = fuera / "relleno.yaml"
    _yaml_relleno(fuera, "Plantilla.docx", "Salida.docx", sha).replace(externo)
    enlace_yaml = carpeta / "relleno.yaml"
    enlace_simbolico(enlace_yaml, externo)
    with pytest.raises(ErrorLectura) as exc:
        agente.rellenar("relleno.yaml", carpeta)
    assert exc.value.codigo == "FICHERO_FUERA"
    enlace_yaml.unlink()

    # La plantilla es un enlace a un Word de fuera.
    enlace_simbolico(carpeta / "Plantilla.docx", real)
    _yaml_relleno(carpeta, "Plantilla.docx", "Salida.docx", sha)
    with pytest.raises(ErrorEscritura) as exc:
        agente.rellenar("relleno.yaml", carpeta)
    assert exc.value.codigo == "FICHERO_FUERA"
    (carpeta / "Plantilla.docx").unlink()

    # La salida es un enlace colgante hacia fuera.
    (carpeta / "Plantilla.docx").write_bytes(real.read_bytes())
    enlace_simbolico(carpeta / "Salida.docx", fuera / "Nuevo.docx")
    with pytest.raises(ErrorEscritura) as exc:
        agente.rellenar("relleno.yaml", carpeta)
    assert exc.value.codigo == "FICHERO_FUERA"
    assert not (fuera / "Nuevo.docx").exists()


# --- reemplazar con varios párrafos y otras operaciones sobre el mismo id -----------------


def test_reemplazar_con_lista_y_luego_insertar_en_el_mismo_id(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Uno")
    d.add_paragraph("Dos")
    _, nuevo, _ = aplicar(tmp_path, d, Reemplazar("p1", ("A", "B")), InsertarDespues("p1", ("C",)))
    assert _orden(nuevo) == ["A", "B", "C", "Dos"]


def test_insertar_y_luego_reemplazar_con_lista_en_el_mismo_id(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Uno")
    d.add_paragraph("Dos")
    _, nuevo, _ = aplicar(tmp_path, d, InsertarDespues("p1", ("C",)), Reemplazar("p1", ("A", "B")))
    # Los párrafos nuevos sustituyen a p1, así que van antes de lo insertado tras él.
    assert _orden(nuevo) == ["A", "B", "C", "Dos"]


def test_reemplazar_con_lista_y_luego_duplicar_tabla_tras_el_mismo_id(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Uno")
    f.tabla_unidad(d)
    _, nuevo, _ = aplicar(
        tmp_path,
        d,
        Reemplazar("p1", ("A", "B")),
        DuplicarTabla("t1", "p1", 1, ({"f1.c1": ("COPIA",)},)),
    )
    cuerpo = [
        "".join(t.text or "" for t in e.iter(qn("w:t"))) if e.tag == qn("w:p") else "tabla"
        for e in nuevo.element.body
    ]
    assert cuerpo[:4] == ["A", "B", "tabla", ""]
    assert "COPIA" in "".join(t.text or "" for t in nuevo.element.body[2].iter(qn("w:t")))


# --- Encabezados y pies -------------------------------------------------------------------


def _miembros(ruta):
    """``nombre -> bytes`` de cada encabezado y pie del zip."""
    with zipfile.ZipFile(ruta) as zf:
        return {
            n: zf.read(n)
            for n in zf.namelist()
            if n.startswith(("word/header", "word/footer")) and n.endswith(".xml")
        }


def test_reemplazar_el_encabezado_lo_cambia_y_conserva_su_estilo(tmp_path):
    d = f.nuevo()
    f.dos_secciones(d)
    parrafo = d.sections[0].header.paragraphs[0]
    parrafo.runs[0].bold = True
    resultado, nuevo, lectura = aplicar(tmp_path, d, Reemplazar("e1.p1", ("Curso 2027/28",)))
    assert nuevo.sections[0].header.paragraphs[0].text == "Curso 2027/28"
    assert nuevo.sections[0].header.paragraphs[0].runs[0].bold is True
    assert nuevo.sections[1].header.is_linked_to_previous  # sigue compartido
    assert [(b.id, [h.texto for h in b.hijos]) for b in lectura.partes] == [
        ("e1", ["Curso 2027/28"]),
        ("pie1", ["Página 1"]),
        ("pie2", ["Departamento de Informática"]),
    ]
    assert not any(b"2026/27" in xml for xml in _miembros(resultado.salida).values())


def test_un_pie_con_pagina_que_no_se_toca_conserva_el_campo(tmp_path):
    d = f.nuevo()
    f.dos_secciones(d)
    resultado, _, _ = aplicar(tmp_path, d, Reemplazar("e1.p1", ("Curso 2027/28",)))
    pies = [x for n, x in _miembros(resultado.salida).items() if n.startswith("word/footer")]
    assert sum(b"PAGE" in x for x in pies) == 1


def test_reemplazar_un_parrafo_de_pie_con_campo_quita_el_campo(tmp_path):
    d = f.nuevo()
    f.dos_secciones(d)
    resultado, nuevo, _ = aplicar(tmp_path, d, Reemplazar("pie1.p1", ("Sin número",)))
    assert nuevo.sections[0].footer.paragraphs[0].text == "Sin número"
    pies = [x for n, x in _miembros(resultado.salida).items() if n.startswith("word/footer")]
    assert not any(b"PAGE" in x for x in pies)


def test_insertar_borrar_y_tablas_funcionan_en_encabezados_y_pies(tmp_path):
    d = f.nuevo()
    d.add_paragraph("Cuerpo")
    cabecera = d.sections[0].header
    cabecera.paragraphs[0].text = "IES Ejemplo"
    tabla = cabecera.add_table(3, 2, d.sections[0].page_width)
    for n, (a, b) in enumerate([("Curso", "2026/27"), ("Grupo", "1A"), ("Total", "x")]):
        tabla.cell(n, 0).text, tabla.cell(n, 1).text = a, b
    d.sections[0].footer.paragraphs[0].text = "Pie"
    _, nuevo, lectura = aplicar(
        tmp_path,
        d,
        InsertarDespues("e1.p1", ("Departamento",)),
        Filas("e1.t1", 2, 3, (fila("Aula", "B2"),)),
        DuplicarTabla("e1.t1", "e1.p1", 1, ({"f1.c2": ("2027/28",)},)),
        Borrar("pie1.p1"),
    )
    cabecera = nuevo.sections[0].header
    assert [p.text for p in cabecera.paragraphs][:2] == ["IES Ejemplo", "Departamento"]
    assert [[c.text for c in r.cells] for r in cabecera.tables[0].rows][-2:] == [
        ["Aula", "B2"],
        ["Total", "x"],
    ]
    assert len(cabecera.tables) == 2
    assert [b.id for b in lectura.partes] == ["e1"]  # el pie quedó sin texto: no sale
    assert [t.cell(0, 1).text for t in cabecera.tables] == ["2027/28", "2026/27"]
    pie = nuevo.sections[0].footer
    assert pie._element[-1].tag == qn("w:p")  # sigue acabando en un párrafo


def test_el_mapa_de_ids_incluye_encabezados_y_pies(tmp_path):
    d = f.nuevo()
    f.dos_secciones(d)
    cabecera = d.sections[0].header
    tabla = cabecera.add_table(1, 2, d.sections[0].page_width)
    tabla.cell(0, 0).text = "IES"
    tabla.cell(0, 1).text = "Curso"
    ruta = tmp_path / "doc.docx"
    d.save(str(ruta))
    analisis = analizar_docx(ruta.read_bytes(), ruta.name)
    ids = []

    def recoger(bloque):
        if bloque.tipo not in ("encabezado", "pie"):  # los contenedores no son elementos
            ids.append(bloque.id)
        for hijo in bloque.hijos:
            recoger(hijo)

    for bloque in [*analisis.lectura.bloques, *analisis.lectura.partes]:
        recoger(bloque)
    assert {"e1.p1", "e1.t1", "e1.t1.f1.c2.p1", "pie1.p1", "pie2.p1"} <= set(ids)
    assert set(analisis.mapa) == set(ids) and len(ids) == len(set(ids))
    assert analisis.mapa["e1.p1"].getroottree().getroot().tag == qn("w:hdr")
    assert analisis.mapa["pie2.p1"].getroottree().getroot().tag == qn("w:ftr")


def test_un_id_de_parte_inexistente_es_id_desconocido(tmp_path):
    d = f.nuevo()
    f.dos_secciones(d)
    assert fallo(tmp_path, d, Reemplazar("e2.p1", ("x",))).codigo == "ID_DESCONOCIDO"
