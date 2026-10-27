"""`tiza esquema`: un SVG del agente se convierte en PNG sin salir de la carpeta."""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from tiza import agente, ayuda, cli, informe
from tiza.escritura import ErrorEscritura, esquema

BASE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
    'viewBox="0 0 {w} {h}">{cuerpo}</svg>'
)


def svg(cuerpo: str = "", ancho: int = 400, alto: int = 300) -> str:
    return BASE.format(w=ancho, h=alto, cuerpo=cuerpo)


def escribir_svg(carpeta: Path, nombre: str = "esquema.svg", texto: str | None = None) -> Path:
    ruta = carpeta / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto if texto is not None else svg(), encoding="utf-8")
    return ruta


def ejecutar(capsys, argv):
    codigo = cli.main(argv)
    return codigo, json.loads(capsys.readouterr().out)


def _chunks(png: bytes):
    pos = 8
    while pos + 12 <= len(png):
        (largo,) = struct.unpack(">I", png[pos : pos + 4])
        tipo = png[pos + 4 : pos + 8]
        datos = png[pos + 8 : pos + 8 + largo]
        yield tipo, datos
        if tipo == b"IEND":
            break
        pos += 12 + largo


def _trozo(tipo: bytes, datos: bytes) -> bytes:
    crc = zlib.crc32(tipo + datos) & 0xFFFFFFFF
    return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", crc)


def _con_trozo(png: bytes, tipo: bytes, datos: bytes) -> bytes:
    pos = len(png) - 12  # justo antes de IEND
    return png[:pos] + _trozo(tipo, datos) + png[pos:]


def _pixel(png: bytes, x: int = 0, y: int = 0) -> tuple[int, ...]:
    """El primer píxel de un PNG RGBA/RGB de 8 bits (las pruebas no usan otro)."""
    ancho = alto = canales = 0
    datos = b""
    for tipo, trozo in _chunks(png):
        if tipo == b"IHDR":
            ancho, alto, profundidad, color = struct.unpack(">IIBB", trozo[:10])
            assert profundidad == 8
            canales = {2: 3, 6: 4}[color]
        elif tipo == b"IDAT":
            datos += trozo
        elif tipo == b"IEND":
            break
    assert ancho and alto
    crudo = zlib.decompress(datos)
    fila_bytes = ancho * canales
    previa = bytearray(fila_bytes)
    pos = 0
    for numero_de_fila in range(alto):
        filtro = crudo[pos]
        pos += 1
        fila = bytearray(crudo[pos : pos + fila_bytes])
        pos += fila_bytes
        for i in range(len(fila)):
            a = fila[i - canales] if i >= canales else 0
            b = previa[i]
            c = previa[i - canales] if i >= canales else 0
            if filtro == 1:
                fila[i] = (fila[i] + a) & 255
            elif filtro == 2:
                fila[i] = (fila[i] + b) & 255
            elif filtro == 3:
                fila[i] = (fila[i] + ((a + b) // 2)) & 255
            elif filtro == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predictor = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                fila[i] = (fila[i] + predictor) & 255
            elif filtro != 0:
                raise AssertionError(f"filtro PNG desconocido: {filtro}")
        previa = fila
        if numero_de_fila == y:
            valor = tuple(fila[x * canales : x * canales + canales])
            return (*valor, 255) if canales == 3 else valor
    raise AssertionError("no hay esa fila")


def test_convierte_y_marca_el_png(tmp_path):
    escribir_svg(tmp_path, "img/ciclo.svg", svg('<circle cx="200" cy="150" r="80"/>'))
    resultado = agente.esquema("img/ciclo.svg", tmp_path)
    assert resultado.a_dict() == {
        "fuente": "img/ciclo.svg",
        "imagen": "img/ciclo.png",
        "ancho": 1200,
        "alto": 900,
        "bytes": len((tmp_path / "img/ciclo.png").read_bytes()),
        "sustituye": False,
    }
    png = (tmp_path / "img/ciclo.png").read_bytes()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert esquema.marca_de_png(png) == "img/ciclo.svg"
    assert dict(_chunks(png))[b"IEND"] == b""


def test_la_segunda_vez_sustituye_su_propio_png(tmp_path):
    escribir_svg(tmp_path, "img/ciclo.svg")
    assert agente.esquema("img/ciclo.svg", tmp_path).sustituye is False
    assert agente.esquema("img/ciclo.svg", tmp_path).sustituye is True


def test_al_cambiar_el_svg_se_sustituye_el_png(tmp_path):
    escribir_svg(tmp_path, "img/ciclo.svg")
    agente.esquema("img/ciclo.svg", tmp_path)
    escribir_svg(tmp_path, "img/ciclo.svg", svg('<rect width="20" height="20"/>'))
    assert agente.esquema("img/ciclo.svg", tmp_path).sustituye is True


def test_no_sustituye_un_png_que_no_es_suyo(tmp_path):
    escribir_svg(tmp_path, "img/foto.svg")
    original = b"\x89PNG\r\n\x1a\nno es un PNG de verdad"
    (tmp_path / "img/foto.png").write_bytes(original)
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("img/foto.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_EXISTE"
    assert "--salida img/foto-esquema.png" in error.value.detalle
    assert (tmp_path / "img/foto.png").read_bytes() == original


def test_no_sustituye_el_png_de_otro_svg(tmp_path):
    escribir_svg(tmp_path, "a.svg")
    escribir_svg(tmp_path, "b.svg")
    agente.esquema("a.svg", tmp_path, "comun.png", ancho=400)
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("b.svg", tmp_path, "comun.png", ancho=400)
    assert error.value.codigo == "ESQUEMA_EXISTE"
    assert esquema.marca_de_png((tmp_path / "comun.png").read_bytes()) == "a.svg"


def test_salida_explicita_y_ancho(tmp_path):
    escribir_svg(tmp_path, "img/x.svg", svg('<rect width="10" height="10"/>'))
    resultado = agente.esquema("img/x.svg", tmp_path, "img/y.png", ancho=500)
    assert (resultado.imagen, resultado.ancho, resultado.alto) == ("img/y.png", 500, 375)
    assert (tmp_path / "img/y.png").is_file()


def test_salida_en_subcarpeta_que_no_existe(tmp_path):
    escribir_svg(tmp_path, "x.svg")
    resultado = agente.esquema("x.svg", tmp_path, "img/nueva/y.png", ancho=400)
    assert resultado.imagen == "img/nueva/y.png"
    assert (tmp_path / "img/nueva/y.png").is_file()


@pytest.mark.parametrize(
    ("llamada", "codigo"),
    [
        (("fuera.svg", "../fuera.png"), "FICHERO_FUERA"),
        (("x.svg", "../fuera.png"), "FICHERO_FUERA"),
        (("x.svg", ".tiza/x.png"), "FICHERO_TEMPORAL"),
        ((".tiza/x.svg", None), "FICHERO_TEMPORAL"),
        (("x.png", None), "FORMATO_NO_ADMITIDO"),
        (("x.svg", "x.jpg"), "FORMATO_NO_ADMITIDO"),
        (("ausente.svg", None), "FICHERO_AUSENTE"),
    ],
)
def test_rutas_y_formatos(tmp_path, llamada, codigo):
    escribir_svg(tmp_path, "x.svg")
    fuente, salida = llamada
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema(fuente, tmp_path, salida, ancho=400)
    assert error.value.codigo == codigo


def test_el_svg_pasa_de_512_kb(tmp_path):
    (tmp_path / "grande.svg").write_bytes(b"<svg>" + b" " * (esquema.MAX_SVG_BYTES + 1))
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("grande.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_DEMASIADO_GRANDE"


def test_ancho_fuera_de_rango(tmp_path):
    escribir_svg(tmp_path, "x.svg")
    for ancho in (399, 2001):
        with pytest.raises(ErrorEscritura) as error:
            agente.esquema("x.svg", tmp_path, ancho=ancho)
        assert error.value.codigo == "ESQUEMA_DEMASIADO_GRANDE"


def test_demasiados_elementos(tmp_path):
    escribir_svg(
        tmp_path,
        "x.svg",
        svg('<rect width="1" height="1"/>' * (esquema.MAX_ELEMENTOS + 1)),
    )
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path, ancho=400)
    assert error.value.codigo == "ESQUEMA_DEMASIADO_GRANDE"


def test_proporcion_entre_1_4_y_4_1(tmp_path):
    escribir_svg(
        tmp_path, "alto.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="400"/>'
    )
    escribir_svg(
        tmp_path, "ancho.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100"/>'
    )
    assert agente.esquema("alto.svg", tmp_path, ancho=400).alto == 1600
    assert agente.esquema("ancho.svg", tmp_path, ancho=400).alto == 100
    escribir_svg(
        tmp_path,
        "muy-alto.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="401"/>',
    )
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("muy-alto.svg", tmp_path, ancho=400)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"
    assert "1604" in error.value.detalle


def test_el_tamano_absurdo_no_llega_a_resvg(tmp_path, monkeypatch):
    escribir_svg(
        tmp_path,
        "x.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="96000"/>',
    )

    def no_deberia(*_args, **_kwargs):
        raise AssertionError("resvg no debería ejecutarse con una proporción absurda")

    monkeypatch.setattr(esquema, "_renderizar", no_deberia)
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


def test_proporcion_no_finita(tmp_path):
    escribir_svg(
        tmp_path,
        "x.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1e-308 1e308"/>',
    )
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


def test_sin_medidas(tmp_path):
    escribir_svg(tmp_path, "x.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


def test_viewbox_sin_width_height(tmp_path):
    escribir_svg(
        tmp_path,
        "x.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><rect width="10" height="10"/></svg>',
    )
    assert agente.esquema("x.svg", tmp_path, ancho=400).alto == 200


def test_width_height_sin_viewbox(tmp_path):
    escribir_svg(
        tmp_path,
        "x.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect width="10" height="10"/></svg>',
    )
    assert agente.esquema("x.svg", tmp_path, ancho=400).alto == 200


def test_doctype_y_entidades(tmp_path):
    escribir_svg(
        tmp_path,
        "x.svg",
        '<!DOCTYPE svg [<!ENTITY x "x">]><svg xmlns="http://www.w3.org/2000/svg" '
        'width="100" height="100"><text>&x;</text></svg>',
    )
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


def test_doctype_con_sistema_externo(tmp_path):
    escribir_svg(
        tmp_path,
        "x.svg",
        '<!DOCTYPE svg SYSTEM "http://127.0.0.1:1/x.dtd"><svg '
        'xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>',
    )
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


@pytest.mark.parametrize(
    "elemento",
    [
        '<image href="foto.png"/>',
        "<script>alert(1)</script>",
        "<foreignObject/>",
        "<filter/>",
        '<a href="#x"/>',
        "<animate/>",
        "<metadata/>",
    ],
)
def test_elementos_fuera_de_la_lista(tmp_path, elemento):
    escribir_svg(
        tmp_path,
        "x.svg",
        svg("\n" * 11 + elemento, ancho=100, alto=100),
    )
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"
    assert "línea 12" in error.value.detalle


@pytest.mark.parametrize(
    "href",
    [
        "http://ejemplo.test/x.svg",
        "../fuera.svg",
        "/etc/passwd",
        "file:///etc/passwd",
        "data:image/png;base64,AAAA",
        "//ejemplo.test/x.svg",
    ],
)
def test_href_externo(tmp_path, href):
    escribir_svg(
        tmp_path,
        "x.svg",
        svg(
            f'<use href="{href}"/>',
            ancho=100,
            alto=100,
        ),
    )
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


def test_xlink_href_externo(tmp_path):
    escribir_svg(
        tmp_path,
        "x.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" width="100" height="100">'
        '<use xlink:href="http://ejemplo.test/x.svg#a"/></svg>',
    )
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


def test_xml_base_no_se_admite(tmp_path):
    escribir_svg(
        tmp_path,
        "x.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" xml:base="http://ejemplo.test/" '
        'width="100" height="100"/>',
    )
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


def test_el_style_no_lleva_elementos_dentro(tmp_path):
    escribir_svg(tmp_path, "x.svg", svg("<style><rect/></style>", ancho=100, alto=100))
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


def test_los_comentarios_no_impiden_el_esquema(tmp_path):
    escribir_svg(tmp_path, "x.svg", svg("<!-- una nota --><rect width='10' height='10'/>"))
    assert agente.esquema("x.svg", tmp_path, ancho=400).alto == 300


def test_use_interno_con_href_y_xlink(tmp_path):
    escribir_svg(
        tmp_path,
        "x.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" width="100" height="100">'
        '<defs><circle id="c" cx="10" cy="10" r="5"/></defs>'
        '<use href="#c"/><use xlink:href="#c"/></svg>',
    )
    assert agente.esquema("x.svg", tmp_path, ancho=400).alto == 400


@pytest.mark.parametrize(
    "estilo",
    [
        "fill: url(http://ejemplo.test/x.svg#g)",
        "fill: url(../fuera.png)",
        "fill: url(file:///etc/passwd)",
        "fill: url(data:image/png;base64,AAAA)",
        "fill: url(\\68 ttp://ejemplo.test/x.svg#g)",
    ],
)
def test_css_url_externo_en_atributo(tmp_path, estilo):
    escribir_svg(
        tmp_path,
        "x.svg",
        svg(f'<rect width="10" height="10" style="{estilo}"/>', ancho=100, alto=100),
    )
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


@pytest.mark.parametrize(
    "css",
    [
        "rect { fill: url(http://ejemplo.test/x.svg#g); }",
        "rect { fill: url(../fuera.png); }",
        "rect { fill: url(file:///etc/passwd); }",
        "rect { fill: url(data:image/png;base64,AAAA); }",
        "rect { fill: url(\\68 ttp://ejemplo.test/x.svg#g); }",
        "@import url(http://ejemplo.test/x.css);",
        "@media screen { rect { fill: red; } }",
    ],
)
def test_css_url_externo_en_style(tmp_path, css):
    escribir_svg(
        tmp_path,
        "x.svg",
        svg(f"<style>{css}</style><rect width='10' height='10'/>", ancho=100, alto=100),
    )
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


def test_css_interno_con_gradiente(tmp_path):
    escribir_svg(
        tmp_path,
        "x.svg",
        svg(
            '<defs><linearGradient id="g"><stop offset="0" stop-color="red"/>'
            '<stop offset="1" stop-color="blue"/></linearGradient></defs>'
            '<rect width="400" height="300" style="fill: url(#g)"/>',
        ),
    )
    assert agente.esquema("x.svg", tmp_path, ancho=400).alto == 300


def test_regla_at_en_el_atributo_style(tmp_path):
    escribir_svg(
        tmp_path,
        "x.svg",
        svg('<rect width="10" height="10" style="@import url(http://ejemplo.test/x.css)"/>'),
    )
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


@pytest.mark.parametrize(
    "cuerpo",
    [
        '<rect width="10" height="10" style="filter: blur(10px)"/>',
        '<rect width="10" height="10" filter="url(#f)"/>',
    ],
)
def test_filtros(tmp_path, cuerpo):
    escribir_svg(tmp_path, "x.svg", svg(cuerpo))
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


def test_filter_none_no_estorba(tmp_path):
    escribir_svg(tmp_path, "x.svg", svg('<rect width="10" height="10" filter="none"/>'))
    assert agente.esquema("x.svg", tmp_path, ancho=400).alto == 300


def test_atributo_de_evento(tmp_path):
    escribir_svg(tmp_path, "x.svg", svg('<rect width="10" height="10" onclick="x()"/>'))
    with pytest.raises(ErrorEscritura) as error:
        agente.esquema("x.svg", tmp_path)
    assert error.value.codigo == "ESQUEMA_NO_ADMITIDO"


def test_el_fondo_siempre_es_blanco(tmp_path):
    escribir_svg(tmp_path, "x.svg", svg('<circle cx="200" cy="150" r="80" fill="red"/>'))
    png, _, _ = esquema.convertir((tmp_path / "x.svg").read_bytes(), "x.svg", 400)
    assert _pixel(png) == (255, 255, 255, 255)


def test_cualquier_font_family_cae_en_la_fuente_del_paquete(tmp_path):
    texto = "Hola ñ → ≤ ≥"
    sin = svg(f'<text x="10" y="50" font-size="24">{texto}</text>')
    con = svg(f'<text x="10" y="50" font-size="24" font-family="Comic Sans">{texto}</text>')
    assert (
        esquema.convertir(sin.encode(), "x.svg", 400)[0]
        == esquema.convertir(con.encode(), "x.svg", 400)[0]
    )


def test_font_family_en_el_atributo_style_cae_en_la_fuente(tmp_path):
    texto = "Hola ñ →"
    con = svg(f'<text x="10" y="50" style="font-family: Comic Sans; font-size: 24">{texto}</text>')
    sin = svg(f'<text x="10" y="50" style="font-size: 24">{texto}</text>')
    assert (
        esquema.convertir(con.encode(), "x.svg", 400)[0]
        == esquema.convertir(sin.encode(), "x.svg", 400)[0]
    )


def test_font_shorthand_conserva_el_tamano_y_el_peso(tmp_path):
    texto = '<text class="a" x="10" y="50">Hola ñ →</text>'
    con_arial = svg(f"<style>.a{{font: bold 24px Arial}}</style>{texto}")
    con_liberation = svg(f"<style>.a{{font: bold 24px Liberation Sans}}</style>{texto}")
    assert (
        esquema.convertir(con_arial.encode(), "x.svg", 400)[0]
        == esquema.convertir(con_liberation.encode(), "x.svg", 400)[0]
    )


def test_fuentes_en_temporal_si_la_wheel_esta_comprimida(tmp_path, monkeypatch):
    monkeypatch.setattr(esquema.recursos, "ruta", lambda _nombre: None)
    escribir_svg(tmp_path, "x.svg", svg('<text x="10" y="50">Hola ñ →</text>'))
    assert agente.esquema("x.svg", tmp_path, ancho=400).alto == 300


def test_el_png_pasa_de_1_mb(tmp_path, monkeypatch):
    escribir_svg(tmp_path, "x.svg", svg('<rect width="10" height="10"/>'))
    png, _, _ = esquema.convertir((tmp_path / "x.svg").read_bytes(), "x.svg", 400)
    grande = _con_trozo(png, b"tEXt", b"relleno\x00" + b"a" * esquema.MAX_PNG_BYTES)
    monkeypatch.setattr(esquema, "_renderizar", lambda *a, **k: grande)
    with pytest.raises(ErrorEscritura) as error:
        esquema.convertir((tmp_path / "x.svg").read_bytes(), "x.svg", 400)
    assert error.value.codigo == "ESQUEMA_DEMASIADO_GRANDE"


def test_marca_de_png_es_tolerante():
    assert esquema.marca_de_png(b"no es un png") is None
    assert esquema.marca_de_png(b"\x89PNG\r\n\x1a\n") is None


def test_resvg_no_se_carga_al_importar_el_modulo():
    code = (
        "import sys, tiza.escritura.esquema; "
        "assert 'resvg_py' not in sys.modules, 'resvg_py cargado al importar'"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd=Path(__file__).parents[1])


def test_informe_esquema_valido_y_cerrado():
    datos = {
        "fuente": "img/ciclo.svg",
        "imagen": "img/ciclo.png",
        "ancho": 1200,
        "alto": 800,
        "bytes": 100,
        "sustituye": False,
    }
    assert informe.Esquema(**datos).a_dict() == datos
    for cambio, codigo in [
        ({**datos, "otro": 1}, "CAMPO_NO_PERMITIDO"),
        ({**datos, "fuente": "../x.svg"}, "VALOR_NO_PERMITIDO"),
        ({**datos, "imagen": "/x.png"}, "VALOR_NO_PERMITIDO"),
        ({**datos, "ancho": 0}, "VALOR_NO_PERMITIDO"),
        ({**datos, "bytes": 0}, "VALOR_NO_PERMITIDO"),
        ({**datos, "bytes": -1}, "VALOR_NO_PERMITIDO"),
        ({**datos, "sustituye": "no"}, "TIPO_INCORRECTO"),
    ]:
        with pytest.raises(informe.ErrorInforme) as error:
            informe.validar_esquema(cambio)
        assert error.value.codigo == codigo


def test_ayuda_explica_los_codigos_de_esquema():
    for codigo in ("ESQUEMA_NO_ADMITIDO", "ESQUEMA_DEMASIADO_GRANDE", "ESQUEMA_EXISTE"):
        assert ayuda.explicar(codigo)


def test_cli_esquema_resumen(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    escribir_svg(tmp_path, "img/x.svg", svg('<rect width="10" height="10"/>'))
    codigo, resumen = ejecutar(capsys, ["esquema", "img/x.svg", "--ancho", "400"])
    assert codigo == 0
    assert resumen["fuente"] == "img/x.svg"
    assert resumen["imagen"] == "img/x.png"
    assert resumen["ancho"] == 400
    assert (tmp_path / "img/x.png").is_file()
    assert not (tmp_path / ".tiza" / "informe.json").exists()


def test_cli_esquema_error(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    codigo, resumen = ejecutar(capsys, ["esquema", "ausente.svg"])
    assert codigo == 2
    assert resumen["error"] == "FICHERO_AUSENTE"
    assert resumen["que_hacer"]
