"""Numeración que viene del estilo, viñetas y romanos."""

from __future__ import annotations

from docx.oxml.ns import qn

from lectura import fabrica as f
from tiza.lectura.word import leer_docx


def test_numeracion_del_estilo_vineta_y_romanos(tmp_path):
    d = f.nuevo()
    f.numeracion(
        d,
        {0: [f.nivel(0, "upperRoman", "%1.")], 1: [f.nivel(0, "bullet", "o")]},
        {1: (0, None), 2: (1, None)},
    )
    ppr = d.styles["List Number"].element.get_or_add_pPr()
    for viejo in ppr.findall(qn("w:numPr")):
        ppr.remove(viejo)
    ppr.append(f.elemento('<w:numPr><w:numId w:val="1"/></w:numPr>'))
    for _ in range(4):
        d.add_paragraph("Romano", style="List Number")
    f.parrafo_numerado(d, "Punto", 2)
    ruta = tmp_path / "n.docx"
    d.save(str(ruta))
    assert [b.etiqueta for b in leer_docx(ruta).bloques] == ["I.", "II.", "III.", "IV.", "-"]
