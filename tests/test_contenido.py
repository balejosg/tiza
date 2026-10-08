"""Tests offline del módulo de contenido (frontmatter, Markdown, recursos y filtro)."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import html5lib
import pytest
from bs4 import BeautifulSoup

from dobles import enlace_simbolico
from tiza import contenido
from tiza import contenido as contenido_modulo
from tiza.contenido import (
    ErrorContenido,
    cargar,
    hash_documento,
    html_para_moodle,
    html_para_preview,
    previsualizar,
)

MADRID = ZoneInfo("Europe/Madrid")


def escribir(tmp_path, texto: str, nombre: str = "pagina.md"):
    ruta = tmp_path / nombre
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def pagina(cuerpo: str = "", **campos) -> str:
    extra = "".join(f"{clave}: {valor}\n" for clave, valor in campos.items())
    return f"---\ntipo: pagina\nnombre: Repaso de fracciones\nseccion: 3\n{extra}---\n\n{cuerpo}\n"


def tarea(cuerpo: str = "", **campos) -> str:
    base = {
        "apertura": "2026-10-01",
        "entrega": "2026-10-10",
        "limite": "2026-10-15",
    }
    base.update(campos)
    extra = "".join(f"{clave}: {valor}\n" for clave, valor in base.items())
    return (
        f"---\ntipo: tarea\nnombre: Problemas de fracciones\nseccion: 3\n{extra}---\n\n{cuerpo}\n"
    )


class TestCarga:
    def test_carga_pagina_valida(self, tmp_path):
        doc = cargar(escribir(tmp_path, pagina("## Repaso\n\nPractica con **fracciones**.")))
        assert doc.tipo == "pagina"
        assert doc.nombre == "Repaso de fracciones"
        assert doc.seccion == 3
        assert doc.fechas is None
        assert doc.recursos == []
        assert "<h2>Repaso</h2>" in doc.html
        assert "<strong>fracciones</strong>" in doc.html

    def test_carga_tarea_valida(self, tmp_path):
        doc = cargar(escribir(tmp_path, tarea("Resuelve los problemas."), "tarea.md"))
        assert doc.tipo == "tarea"
        assert doc.fechas is not None
        assert doc.fechas.apertura == datetime(2026, 10, 1, 0, 0, tzinfo=MADRID)
        assert doc.fechas.entrega == datetime(2026, 10, 10, 23, 59, tzinfo=MADRID)
        assert doc.fechas.limite == datetime(2026, 10, 15, 23, 59, tzinfo=MADRID)

    def test_acepta_fecha_con_hora(self, tmp_path):
        doc = cargar(
            escribir(
                tmp_path,
                tarea(apertura="2026-10-01 09:30", entrega="2026-10-10 18:00"),
                "tarea.md",
            )
        )
        assert doc.fechas.apertura == datetime(2026, 10, 1, 9, 30, tzinfo=MADRID)
        assert doc.fechas.entrega == datetime(2026, 10, 10, 18, 0, tzinfo=MADRID)

    def test_sin_frontmatter_falla(self, tmp_path):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, "Solo texto\n"))
        assert exc.value.codigo == "FRONTMATTER_INVALIDO"

    def test_tipo_desconocido_falla(self, tmp_path):
        md = pagina().replace("tipo: pagina", "tipo: examen")
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, md))
        assert exc.value.codigo == "TIPO_INVALIDO"

    def test_campo_faltante_falla(self, tmp_path):
        md = pagina().replace("seccion: 3\n", "")
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, md))
        assert exc.value.codigo == "CAMPO_FALTANTE"

    def test_campo_desconocido_falla(self, tmp_path):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, pagina(color="rojo")))
        assert exc.value.codigo == "CAMPO_DESCONOCIDO"

    def test_carga_etiqueta_valida(self, tmp_path):
        texto = "---\ntipo: etiqueta\nnombre: Bienvenida\nseccion: 3\n---\n\n## Hola\n"
        doc = cargar(escribir(tmp_path, texto))
        assert (doc.tipo, doc.nombre, doc.seccion) == ("etiqueta", "Bienvenida", 3)
        assert doc.fechas is None and doc.cuestionario is None
        assert "<h2>Hola</h2>" in doc.html

    def test_fechas_en_etiqueta_fallan(self, tmp_path):
        texto = "---\ntipo: etiqueta\nnombre: Bienvenida\nseccion: 3\nentrega: 2026-10-10\n---\n\nHola\n"
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, texto))
        assert exc.value.codigo == "CAMPO_DESCONOCIDO"

    def test_fechas_en_pagina_fallan(self, tmp_path):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, pagina(apertura="2026-10-01")))
        assert exc.value.codigo == "CAMPO_DESCONOCIDO"

    def test_tarea_sin_entrega_falla(self, tmp_path):
        md = tarea().replace("entrega: 2026-10-10\n", "")
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, md, "tarea.md"))
        assert exc.value.codigo == "CAMPO_FALTANTE"

    def test_fecha_invalida_falla(self, tmp_path):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, tarea(apertura="el jueves"), "tarea.md"))
        assert exc.value.codigo == "FECHA_INVALIDA"

    def test_fechas_incoherentes_fallan(self, tmp_path):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, tarea(apertura="2026-10-11"), "tarea.md"))
        assert exc.value.codigo == "FECHAS_INCOHERENTES"

    def test_limite_anterior_a_entrega_falla(self, tmp_path):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, tarea(limite="2026-10-09"), "tarea.md"))
        assert exc.value.codigo == "FECHAS_INCOHERENTES"

    def test_fechas_incoherentes_sin_limite_explican_el_orden(self, tmp_path):
        md = tarea(apertura="2026-10-11").replace("limite: 2026-10-15\n", "")
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, md, "tarea.md"))
        assert exc.value.detalle == "debe cumplirse apertura < entrega"


class TestFiltroHTML:
    @pytest.mark.parametrize(
        "peligroso",
        [
            "<script>alert(1)</script>",
            '<iframe src="https://example.org"></iframe>',
            '<form action="/x"></form>',
            '<object data="x"></object>',
            '<embed src="x">',
            '<p onclick="alert(1)">hola</p>',
            '<a href="javascript:alert(1)">x</a>',
            '<a href="data:text/html,<b>x</b>">x</a>',
        ],
    )
    def test_bloquea_html_peligroso(self, tmp_path, peligroso):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, pagina(peligroso)))
        assert exc.value.codigo == "HTML_PELIGROSO"

    def test_permite_html_normal(self, tmp_path):
        doc = cargar(
            escribir(
                tmp_path,
                pagina(
                    "<p>Hola <strong>clase</strong></p>\n\n"
                    '<img src="https://example.org/foto.png" alt="foto">\n\n'
                    "[enlace](https://example.org/material.pdf)"
                ),
            )
        )
        assert "<strong>clase</strong>" in doc.html


class TestRecursos:
    def test_detecta_recurso_local(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "foto.png").write_bytes(b"\x89PNG-falsa")
        doc = cargar(escribir(tmp_path, pagina("![foto](img/foto.png)")))
        assert [recurso.nombre for recurso in doc.recursos] == ["foto.png"]
        assert (tmp_path / "img" / "foto.png") == doc.recursos[0].ruta

    def test_recurso_ausente_falla(self, tmp_path):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, pagina("![foto](img/no-existe.png)")))
        assert exc.value.codigo == "RECURSO_AUSENTE"

    def test_recurso_duplicado_falla(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "a" / "f.png").write_bytes(b"a")
        (tmp_path / "b" / "f.png").write_bytes(b"b")
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, pagina("![a](a/f.png)\n\n![b](b/f.png)")))
        assert exc.value.codigo == "RECURSO_DUPLICADO"

    def test_html_para_moodle_usa_pluginfile(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "foto.png").write_bytes(b"png")
        doc = cargar(escribir(tmp_path, pagina("![foto](img/foto.png)")))
        html = html_para_moodle(doc)
        assert "@@PLUGINFILE@@/foto.png" in html
        assert "img/foto.png" not in html

    def test_enlace_local_tambien_se_sube(self, tmp_path):
        (tmp_path / "apuntes.pdf").write_bytes(b"%PDF-falso")
        doc = cargar(escribir(tmp_path, pagina("[apuntes](apuntes.pdf)")))
        assert [recurso.nombre for recurso in doc.recursos] == ["apuntes.pdf"]
        assert "@@PLUGINFILE@@/apuntes.pdf" in html_para_moodle(doc)

    def test_enlace_remoto_no_es_recurso(self, tmp_path):
        doc = cargar(escribir(tmp_path, pagina("[x](https://example.org/a.pdf)")))
        assert doc.recursos == []


class TestPreview:
    def test_escribe_preview_con_recursos_relativos(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "foto.png").write_bytes(b"png")
        doc = cargar(escribir(tmp_path, pagina("![foto](img/foto.png)")))
        destino = previsualizar(doc, tmp_path / ".tiza")
        assert destino == tmp_path / ".tiza" / "preview" / "pagina.html"
        html = destino.read_text(encoding="utf-8")
        assert "../../img/foto.png" in html
        assert "VISTA PREVIA" in html

    def test_preview_de_tarea_muestra_fechas(self, tmp_path):
        doc = cargar(escribir(tmp_path, tarea(), "tarea.md"))
        destino = previsualizar(doc, tmp_path / ".tiza")
        html = destino.read_text(encoding="utf-8")
        assert "2026-10-01" in html
        assert "2026-10-10" in html


class TestRecursosAcotados:
    """Con ``raiz`` (la carpeta de la asignatura), solo se suben ficheros de dentro, no ocultos y razonables."""

    def preparar(self, tmp_path):
        carpeta = tmp_path / "asig"
        (carpeta / "img").mkdir(parents=True)
        (carpeta / "img" / "foto.png").write_bytes(b"png")
        return carpeta.resolve()

    def test_un_recurso_de_dentro_se_admite(self, tmp_path):
        carpeta = self.preparar(tmp_path)
        doc = cargar(escribir(carpeta, pagina("![foto](img/foto.png)")), raiz=carpeta)
        assert [recurso.nombre for recurso in doc.recursos] == ["foto.png"]

    def test_un_recurso_en_una_carpeta_enlazada_de_dentro_se_admite(self, tmp_path):
        carpeta = self.preparar(tmp_path)
        (carpeta / "originales").mkdir()
        (carpeta / "originales" / "foto.png").write_bytes(b"png")
        enlace_simbolico(carpeta / "fotos", carpeta / "originales")
        doc = cargar(escribir(carpeta, pagina("![foto](fotos/foto.png)")), raiz=carpeta)
        assert [recurso.ruta for recurso in doc.recursos] == [carpeta / "originales" / "foto.png"]

    def test_un_recurso_con_tildes_y_espacios_se_admite(self, tmp_path):
        carpeta = self.preparar(tmp_path)
        (carpeta / "img" / "fotografía de clase.png").write_bytes(b"png")
        enlace = "img/fotograf%C3%ADa%20de%20clase.png"
        doc = cargar(escribir(carpeta, pagina(f"![foto]({enlace})")), raiz=carpeta)
        assert [recurso.nombre for recurso in doc.recursos] == ["fotografía de clase.png"]

    @pytest.mark.parametrize("existe", [True, False])
    def test_fuera_de_la_carpeta_da_el_mismo_codigo_exista_o_no(self, tmp_path, existe):
        carpeta = self.preparar(tmp_path)
        if existe:
            (tmp_path / "secreto.xlsx").write_bytes(b"x")
        ruta = escribir(carpeta, pagina("[notas](../secreto.xlsx)"))
        with pytest.raises(ErrorContenido) as exc:
            cargar(ruta, raiz=carpeta)
        assert exc.value.codigo == "RUTA_FUERA_DE_CARPETA"

    @pytest.mark.parametrize(
        "recurso", [".git/config", ".env", "img/.secreto/x.png", "tiza.toml", "img/tiza.toml"]
    )
    def test_un_recurso_oculto_o_de_configuracion_se_rechaza(self, tmp_path, recurso):
        carpeta = self.preparar(tmp_path)
        destino = carpeta / recurso
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"x")
        ruta = escribir(carpeta, pagina(f"[x]({recurso})"))
        with pytest.raises(ErrorContenido) as exc:
            cargar(ruta, raiz=carpeta)
        assert exc.value.codigo == "RECURSO_NO_PERMITIDO"

    def test_un_recurso_demasiado_grande_se_rechaza(self, tmp_path, monkeypatch):
        carpeta = self.preparar(tmp_path)
        monkeypatch.setattr(contenido, "MAX_RECURSO_BYTES", 2)  # foto.png pesa 3 bytes
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(carpeta, pagina("![foto](img/foto.png)")), raiz=carpeta)
        assert exc.value.codigo == "RECURSO_DEMASIADO_GRANDE"

    def test_sin_raiz_no_se_aplican_las_reglas_de_la_carpeta(self, tmp_path):
        (tmp_path / ".oculto.png").write_bytes(b"png")
        doc = cargar(escribir(tmp_path, pagina("![x](.oculto.png)")))
        assert [recurso.nombre for recurso in doc.recursos] == [".oculto.png"]

    def test_un_documento_demasiado_grande_se_rechaza(self, tmp_path, monkeypatch):
        monkeypatch.setattr(contenido, "MAX_DOCUMENTO_BYTES", 50)
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, pagina("x" * 100)))
        assert exc.value.codigo == "FICHERO_DEMASIADO_GRANDE"

    def test_el_hash_lee_por_trozos_y_sigue_siendo_el_mismo(self, tmp_path, monkeypatch):
        carpeta = self.preparar(tmp_path)
        doc = cargar(escribir(carpeta, pagina("![foto](img/foto.png)")), raiz=carpeta)
        esperado = hashlib.sha256()
        esperado.update(b"pagina\nRepaso de fracciones\n3\n\n")
        esperado.update(doc.cuerpo.encode("utf-8"))
        esperado.update(b"\n--recurso--\nfoto.png\npng")
        monkeypatch.setattr(contenido, "_TROZO_HASH", 2)  # varios trozos
        assert hash_documento(doc) == esperado.hexdigest()


class TestVistaPreviaSegura:
    """El agente escribe en ``.tiza``: la vista previa no puede escribir fuera a través de un enlace."""

    def test_no_escribe_fuera_a_traves_de_un_enlace_simbolico(self, tmp_path):
        ajeno = tmp_path / "ajeno.txt"
        ajeno.write_text("del docente", encoding="utf-8")
        doc = cargar(escribir(tmp_path, pagina("texto")))
        carpeta_vistas = tmp_path / ".tiza" / "preview"
        carpeta_vistas.mkdir(parents=True)
        enlace_simbolico(carpeta_vistas / "pagina.html", ajeno)
        destino = previsualizar(doc, tmp_path / ".tiza")
        assert ajeno.read_text(encoding="utf-8") == "del docente"
        assert not destino.is_symlink()
        assert "VISTA PREVIA" in destino.read_text(encoding="utf-8")

    def test_rechaza_una_carpeta_preview_que_es_un_enlace(self, tmp_path):
        fuera = tmp_path / "fuera"
        fuera.mkdir()
        tiza = tmp_path / ".tiza"
        tiza.mkdir()
        enlace_simbolico(tiza / "preview", fuera)
        doc = cargar(escribir(tmp_path, pagina("texto")))
        with pytest.raises(ErrorContenido) as exc:
            previsualizar(doc, tiza)
        assert exc.value.codigo == "DIRECTORIO_NO_SEGURO"
        assert list(fuera.iterdir()) == []

    def test_rechaza_una_carpeta_tiza_que_es_un_enlace(self, tmp_path):
        fuera = tmp_path / "fuera"
        fuera.mkdir()
        enlace_simbolico(tmp_path / ".tiza", fuera)
        doc = cargar(escribir(tmp_path, pagina("texto")))
        with pytest.raises(ErrorContenido) as exc:
            previsualizar(doc, tmp_path / ".tiza")
        assert exc.value.codigo == "DIRECTORIO_NO_SEGURO"
        assert list(fuera.iterdir()) == []


class TestNombreDeLaVista:
    def test_admite_un_nombre_para_la_vista(self, tmp_path):
        doc = cargar(escribir(tmp_path, pagina("texto")))
        destino = previsualizar(doc, tmp_path / ".tiza", nombre="01-pagina")
        assert destino == tmp_path / ".tiza" / "preview" / "01-pagina.html"
        assert "VISTA PREVIA" in destino.read_text(encoding="utf-8")

    def test_sin_nombre_usa_el_del_fichero(self, tmp_path):
        doc = cargar(escribir(tmp_path, pagina("texto")))
        destino = previsualizar(doc, tmp_path / ".tiza")
        assert destino == tmp_path / ".tiza" / "preview" / "pagina.html"


class TestEjemplosDelRepo:
    def test_los_ejemplos_cargan_y_tienen_recursos(self):
        raiz = Path(__file__).resolve().parent.parent / "ejemplos"
        for nombre in ("pagina.md", "tarea.md", "etiqueta.md"):
            doc = cargar(raiz / nombre)
            assert doc.nombre
            assert doc.recursos, f"{nombre} debería tener recursos locales"

    def test_el_ejemplo_de_cuestionario_carga_con_sus_cuatro_tipos(self):
        raiz = Path(__file__).resolve().parent.parent / "ejemplos"
        doc = cargar(raiz / "cuestionario.md")
        assert doc.tipo == "cuestionario"
        assert [p.tipo for p in doc.cuestionario.preguntas] == list(contenido.TIPOS_PREGUNTA)
        assert [recurso.nombre for recurso in doc.recursos] == ["punto.png"]

    def test_el_ejemplo_de_maquetado_pasa_el_filtro_y_tiene_un_iframe_de_cada_grupo(self, tmp_path):
        raiz = Path(__file__).resolve().parent.parent / "ejemplos"
        doc = cargar(raiz / "maquetado.html")
        assert doc.nombre and [recurso.nombre for recurso in doc.recursos] == ["punto.png"]
        assert [url.split("/")[2] for url in doc.incrustados] == [
            "www.youtube-nocookie.com",
            "view.genially.com",
            "wordwall.net",
            "www.geogebra.org",
        ]
        assert "alert alert-info" in doc.html and "linear-gradient" in doc.html
        texto = previsualizar(doc, tmp_path / ".tiza").read_text(encoding="utf-8")
        assert "<iframe" not in texto

    def test_los_ejemplos_de_h5p_cargan(self):
        raiz = Path(__file__).resolve().parent.parent / "ejemplos"
        huecos = cargar(raiz / "h5p-huecos.md")
        assert huecos.tipo == "h5p" and huecos.h5p.tipo == "rellenar_huecos"
        assert [recurso.nombre for recurso in huecos.recursos] == ["punto.png"]
        tarjetas = cargar(raiz / "h5p-tarjetas.md")
        assert tarjetas.h5p.tipo == "tarjetas"
        assert [tarjeta.anverso for tarjeta in tarjetas.h5p.tarjetas] == [
            "house",
            "book",
            "**water**",
        ]


class TestHash:
    def test_hash_estable_entre_rutas(self, tmp_path):
        (tmp_path / "sub").mkdir()
        doc1 = cargar(escribir(tmp_path, pagina("Hola"), "a.md"))
        doc2 = cargar(escribir(tmp_path, pagina("Hola"), "sub/b.md"))
        assert hash_documento(doc1) == hash_documento(doc2)

    def test_hash_cambia_con_el_texto(self, tmp_path):
        doc1 = cargar(escribir(tmp_path, pagina("Hola"), "a.md"))
        doc2 = cargar(escribir(tmp_path, pagina("Adios"), "a.md"))
        assert hash_documento(doc1) != hash_documento(doc2)

    def test_hash_cambia_si_cambia_la_imagen(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "foto.png").write_bytes(b"uno")
        doc = cargar(escribir(tmp_path, pagina("![foto](img/foto.png)")))
        antes = hash_documento(doc)
        (tmp_path / "img" / "foto.png").write_bytes(b"dos")
        doc2 = cargar(escribir(tmp_path, pagina("![foto](img/foto.png)")))
        assert antes != hash_documento(doc2)


class TestSeccionPorNombre:
    def test_acepta_nombre_y_lo_limpia(self, tmp_path):
        ruta = tmp_path / "p.md"
        ruta.write_text(
            pagina().replace("seccion: 3", 'seccion: "  Fracciones "'), encoding="utf-8"
        )
        assert cargar(ruta).seccion == "Fracciones"

    @pytest.mark.parametrize("valor", ['""', '"<b>x</b>"', "-1", "true"])
    def test_rechaza_secciones_invalidas(self, tmp_path, valor):
        ruta = tmp_path / "p.md"
        ruta.write_text(pagina().replace("seccion: 3", f"seccion: {valor}"), encoding="utf-8")
        with pytest.raises(ErrorContenido) as exc:
            cargar(ruta)
        assert exc.value.codigo == "SECCION_INVALIDA"


def test_la_vista_previa_escapa_el_nombre(tmp_path):
    md = tmp_path / "p.md"
    md.write_text(
        '---\ntipo: pagina\nnombre: "x</title><script>alert(1)</script>"\nseccion: 1\n---\n\nhola\n',
        encoding="utf-8",
    )
    destino = previsualizar(cargar(md), tmp_path / ".tiza")
    assert "<script>" not in destino.read_text(encoding="utf-8")


def test_nombre_y_seccion_rechazan_caracteres_de_control(tmp_path):
    for cabecera, codigo in (
        ('nombre: "Repaso\\e[2K"\nseccion: 3', "NOMBRE_INVALIDO"),
        ('nombre: "Repaso\\u061c"\nseccion: 3', "NOMBRE_INVALIDO"),
        ('nombre: Repaso\nseccion: "Tema\\u202e"', "SECCION_INVALIDA"),
    ):
        ruta = tmp_path / "p.md"
        ruta.write_text(f"---\ntipo: pagina\n{cabecera}\n---\n\nhola\n", encoding="utf-8")
        with pytest.raises(contenido.ErrorContenido) as exc:
            contenido.cargar(ruta)
        assert exc.value.codigo == codigo


class TestListaBlanca:
    @pytest.mark.parametrize(
        "peligroso",
        [
            '<svg><a><animate attributeName="href" values="javascript:alert(1)"/>'
            '<text x="20" y="20">Pulsa</text></a></svg>',
            '<meta http-equiv="refresh" content="0;url=https://phishing.example/login">',
            '<base href="https://evil.example/">',
            "<style>body{display:none}</style>",
            '<link rel="stylesheet" href="https://evil.example/x.css">',
            '<p style="background:url(https://tracker.example/p.gif)">hola</p>',
            '<video src="https://tracker.example/v.mp4"></video>',
            '<img src="https://example.org/a.png" srcset="https://tracker.example/p.gif 1x">',
            '<a href="https://ok.example/\x1b[2K">x</a>',
            '<a href="java&#x09;script:alert(1)">x</a>',
            '<img src="data:image/svg+xml;base64,PHN2Zz4=">',
            '<span class="position-fixed">x</span>',
            '<table><tr><td style="position:fixed">x</td></tr></table>',
        ],
    )
    def test_rechaza_lo_que_no_esta_en_la_lista_blanca(self, tmp_path, peligroso):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, pagina(peligroso)))
        assert exc.value.codigo == "HTML_PELIGROSO"

    @pytest.mark.parametrize(
        "oculto",
        [
            "<!--><script>alert(1)</script>-->",
            "<!---><script>alert(1)</script>-->",
            "<!-- a --!><script>alert(1)</script> -->",
            "<![CDATA[ x ><script>alert(1)</script> ]]>",
            "<? x ><script>alert(1)</script> ?>",
            "<!-- un comentario cualquiera -->",
        ],
    )
    def test_rechaza_comentarios_cdata_y_declaraciones(self, tmp_path, oculto):
        # html.parser los daba por buenos y el navegador ejecutaba el <script> de dentro.
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, pagina(f"Hola\n\n{oculto}")))
        assert exc.value.codigo == "HTML_PELIGROSO"

    def test_el_mensaje_nombra_lo_que_sobra(self, tmp_path):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, pagina('<p><span style="position:fixed">rojo</span></p>')))
        assert "«position»" in exc.value.detalle
        assert "<span>" in exc.value.detalle

    def test_acepta_lo_que_genera_el_markdown(self, tmp_path):
        cuerpo = (
            "| Izq | Der |\n|:----|----:|\n| a | b |\n\n"
            "```python\nprint(1)\n```\n\n"
            "3. tres\n4. cuatro\n\n"
            '![alt](https://example.org/x.png "título")\n\n'
            "<https://example.org/auto>\n\n"
            "Línea  \ncon salto\n\n> cita\n\n***\n\n"
            "<details><summary>Más</summary>Oculto</details>"
        )
        doc = cargar(escribir(tmp_path, pagina(cuerpo)))
        assert 'style="text-align:right"' in doc.html
        assert 'class="language-python"' in doc.html

    def test_ruta_de_windows_sigue_siendo_un_recurso_local(self, tmp_path):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, pagina("![foto](C:\\fotos\\no-existe.png)")))
        assert exc.value.codigo == "RECURSO_AUSENTE"


class TestVistaPreviaDeIframes:
    def test_el_recuadro_no_anida_parrafos_ni_enlaces(self, tmp_path):
        cuerpo = (
            '<p><iframe src="https://player.vimeo.com/video/1" title="v"></iframe></p>\n'
            '<a href="https://example.org"><iframe src="https://player.vimeo.com/video/2"'
            ' title="v"></iframe></a>'
        )
        doc = cargar(escribir_html(tmp_path, cuerpo))
        html = html_para_preview(doc, tmp_path)
        assert "<iframe" not in html
        assert "<p><span" in html
        assert html.count("<a ") == 2  # el del recuadro libre y el del autor, sin anidar
        assert "</strong></span></a>" in html  # dentro del enlace del autor, sin enlace propio


class TestEnlacesExternos:
    def test_recoge_enlaces_e_imagenes_externos_sin_repetir(self, tmp_path):
        (tmp_path / "foto.png").write_bytes(b"png")
        cuerpo = (
            "[web](https://example.org/a) [otra vez](https://example.org/a)\n\n"
            "![remota](https://cdn.example.org/b.png) ![local](foto.png)\n\n"
            '<a href="//example.net/c">c</a> [correo](mailto:x@example.org) [ancla](#arriba)'
        )
        doc = cargar(escribir(tmp_path, pagina(cuerpo)))
        assert doc.enlaces_externos == [
            "https://example.org/a",
            "https://cdn.example.org/b.png",
            "//example.net/c",
        ]
        assert [recurso.nombre for recurso in doc.recursos] == ["foto.png"]


class TestIncrustados:
    CUERPO = (
        "Mira el vídeo:\n\n"
        '<iframe src="https://www.youtube.com/embed/abc" title="Vídeo" allowfullscreen></iframe>\n\n'
        "Y la [web](https://example.org/a)."
    )

    def test_se_listan_aparte_de_los_enlaces_externos(self, tmp_path):
        doc = cargar(escribir(tmp_path, pagina(self.CUERPO)))
        assert doc.incrustados == ["https://www.youtube-nocookie.com/embed/abc"]
        assert doc.enlaces_externos == ["https://example.org/a"]

    def test_lo_publicado_lleva_el_iframe_normalizado_con_sandbox(self, tmp_path):
        doc = cargar(escribir(tmp_path, pagina(self.CUERPO)))
        publicado = html_para_moodle(doc)
        assert 'src="https://www.youtube-nocookie.com/embed/abc"' in publicado
        assert 'sandbox="allow-scripts allow-same-origin' in publicado
        assert "allow-top-navigation" not in publicado
        assert "youtube.com/embed" not in publicado.replace("youtube-nocookie.com/embed", "")

    def test_la_vista_previa_no_carga_nada_de_fuera(self, tmp_path):
        doc = cargar(escribir(tmp_path, pagina(self.CUERPO)))
        destino = previsualizar(doc, tmp_path / ".tiza")
        texto = destino.read_text(encoding="utf-8")
        assert "<iframe" not in texto
        assert "Aquí irá contenido incrustado de <strong>www.youtube-nocookie.com</strong>" in texto
        assert 'href="https://www.youtube-nocookie.com/embed/abc"' in texto
        assert 'rel="noopener noreferrer"' in texto

    def test_documento_sin_iframes(self, tmp_path):
        doc = cargar(escribir(tmp_path, pagina("Hola")))
        assert doc.incrustados == []

    def test_un_servidor_no_permitido_se_rechaza(self, tmp_path):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, pagina('<iframe src="https://evil.example/x"></iframe>')))
        assert exc.value.codigo == "HTML_PELIGROSO"
        assert "evil.example" in exc.value.detalle

    def test_cambiar_el_iframe_cambia_el_hash(self, tmp_path):
        uno = cargar(escribir(tmp_path, pagina(self.CUERPO)))
        otro = cargar(
            escribir(tmp_path, pagina(self.CUERPO.replace("/embed/abc", "/embed/xyz")), "b.md")
        )
        assert hash_documento(uno) != hash_documento(otro)


CABECERA = "---\ntipo: pagina\nnombre: Maquetada\nseccion: 3\n---\n"
DOCUMENTO_COMPLETO = (
    "<!DOCTYPE html>\n"
    '<html lang="es">\n<head>\n<meta charset="utf-8">\n<title>Lo ignora</title>\n</head>\n'
    '<body>\n<h1>Hola</h1>\n<p class="lead">Texto</p>\n</body>\n</html>\n'
)


def escribir_html(tmp_path, cuerpo: str, nombre: str = "pagina.html", cabecera: str = CABECERA):
    return escribir(tmp_path, cabecera + cuerpo, nombre)


class TestFicherosHtml:
    def test_un_fragmento_con_frontmatter(self, tmp_path):
        doc = cargar(escribir_html(tmp_path, '<h2 class="alert alert-info">Hola</h2>\n'))
        assert (doc.tipo, doc.nombre, doc.seccion) == ("pagina", "Maquetada", 3)
        assert '<h2 class="alert alert-info">Hola</h2>' in doc.html

    def test_un_documento_completo_publica_solo_el_body(self, tmp_path):
        doc = cargar(escribir_html(tmp_path, DOCUMENTO_COMPLETO))
        assert doc.html.strip() == '<h1>Hola</h1>\n<p class="lead">Texto</p>'
        assert "Lo ignora" not in doc.html
        assert "<html" not in html_para_moodle(doc) and "<head" not in html_para_moodle(doc)

    @pytest.mark.parametrize("nombre", ["a.html", "a.htm", "a.HTML", "A.Htm"])
    def test_extensiones_html(self, tmp_path, nombre):
        doc = cargar(escribir_html(tmp_path, "**no es markdown**\n", nombre))
        assert "**no es markdown**" in doc.html
        assert "<strong>" not in doc.html

    def test_un_md_sigue_interpretando_markdown(self, tmp_path):
        doc = cargar(escribir(tmp_path, pagina("**sí es markdown**")))
        assert "<strong>sí es markdown</strong>" in doc.html

    def test_en_un_md_la_sangria_no_convierte_el_html_en_codigo(self, tmp_path):
        cuerpo = "<div>\n  <p>Hola</p>\n\n    <div>\n      <p>Adiós</p>\n    </div>\n</div>"
        doc = cargar(escribir(tmp_path, pagina(cuerpo)))
        assert "<pre" not in doc.html and "&lt;" not in doc.html
        assert doc.html.count("<p>") == 2

    def test_en_un_md_los_bloques_de_codigo_van_entre_comillas_invertidas(self, tmp_path):
        doc = cargar(escribir(tmp_path, pagina("```\nprint(1)\n```\n\n    no es código")))
        assert "<pre><code>print(1)\n</code></pre>" in doc.html
        assert "<p>no es código</p>" in doc.html

    def test_las_lineas_en_blanco_y_la_sangria_no_rompen_el_html(self, tmp_path):
        doc = cargar(escribir_html(tmp_path, "<div>\n  <p>Hola</p>\n\n    <p>Adiós</p>\n</div>\n"))
        assert "<pre" not in doc.html and "<code" not in doc.html
        assert doc.html.count("<p>") == 2

    def test_los_recursos_son_relativos_al_html(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "foto.png").write_bytes(b"png")
        doc = cargar(escribir_html(tmp_path, '<img src="img/foto.png" alt="x">\n'))
        assert [recurso.nombre for recurso in doc.recursos] == ["foto.png"]
        assert "@@PLUGINFILE@@/foto.png" in html_para_moodle(doc)

    def test_la_cabecera_tolera_meta_charset_y_title(self, tmp_path):
        cargar(escribir_html(tmp_path, DOCUMENTO_COMPLETO))

    @pytest.mark.parametrize(
        ("cabecera_html", "nombre"),
        [
            ("<style>p{color:red}</style>", "style"),
            ("<script>alert(1)</script>", "script"),
            ('<link rel="stylesheet" href="https://evil.example/x.css">', "link"),
            ('<base href="https://evil.example/">', "base"),
            ('<meta http-equiv="refresh" content="0;url=https://evil.example/">', "meta"),
            ('<meta name="viewport" content="width=device-width">', "meta"),
            ("<noscript><style>x{}</style></noscript>", "noscript"),
        ],
    )
    def test_la_cabecera_rechaza_el_resto(self, tmp_path, cabecera_html, nombre):
        completo = f"<!DOCTYPE html><html><head>{cabecera_html}</head><body><p>x</p></body></html>"
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir_html(tmp_path, completo))
        assert exc.value.codigo == "HTML_PELIGROSO"
        assert f"<{nombre}>" in exc.value.detalle

    def test_una_cabecera_suelta_al_principio_tambien_se_rechaza(self, tmp_path):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir_html(tmp_path, "<style>p{color:red}</style><p>x</p>"))
        assert "<style>" in exc.value.detalle

    @pytest.mark.parametrize(
        ("documento", "atributo", "etiqueta"),
        [
            ('<html onclick="x()"><body><p>x</p></body></html>', "onclick", "html"),
            ('<html><body onload="x()"><p>x</p></body></html>', "onload", "body"),
            ('<html><body class="alert"><p>x</p></body></html>', "class", "body"),
            ('<html><body style="color:red"><p>x</p></body></html>', "style", "body"),
        ],
    )
    def test_html_y_body_no_llevan_atributos(self, tmp_path, documento, atributo, etiqueta):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir_html(tmp_path, documento))
        assert f"«{atributo}»" in exc.value.detalle
        assert f"<{etiqueta}>" in exc.value.detalle

    @pytest.mark.parametrize(
        "documento",
        [
            "<!-- antes --><html><body><p>x</p></body></html>",
            "<html><body><p>x</p></body></html><!-- después -->",
            "<html><!-- dentro --><body><p>x</p></body></html>",
            "<html><head><!-- cabecera --></head><body><p>x</p></body></html>",
            "<html><body><p>x</p><!-- cuerpo --></body></html>",
            "<html><body><!--><script>alert(1)</script>--></body></html>",
        ],
    )
    def test_los_comentarios_se_rechazan_donde_esten(self, tmp_path, documento):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir_html(tmp_path, documento))
        assert exc.value.codigo == "HTML_PELIGROSO"

    def test_el_doctype_solo_vale_al_principio(self, tmp_path):
        cargar(escribir_html(tmp_path, "<!DOCTYPE html><p>x</p>"))

    def test_las_mismas_reglas_que_en_markdown(self, tmp_path):
        for peligroso in (
            '<p style="position:fixed">x</p>',
            '<iframe src="https://evil.example/"></iframe>',
            "<script>alert(1)</script>",
            '<a href="javascript:alert(1)">x</a>',
        ):
            with pytest.raises(ErrorContenido) as exc:
                cargar(escribir_html(tmp_path, peligroso))
            assert exc.value.codigo == "HTML_PELIGROSO"

    def test_el_frontmatter_es_obligatorio(self, tmp_path):
        with pytest.raises(ErrorContenido) as exc:
            cargar(escribir(tmp_path, "<p>Hola</p>", "sin.html"))
        assert exc.value.codigo == "FRONTMATTER_INVALIDO"

    def test_la_vista_previa_de_un_html(self, tmp_path):
        doc = cargar(escribir_html(tmp_path, DOCUMENTO_COMPLETO, "tema1.html"))
        destino = previsualizar(doc, tmp_path / ".tiza")
        assert destino == tmp_path / ".tiza" / "preview" / "tema1.html"
        texto = destino.read_text(encoding="utf-8")
        assert "VISTA PREVIA" in texto and "<h1>Hola</h1>" in texto


def test_la_vista_previa_no_falla_si_el_recurso_esta_en_otra_unidad(tmp_path, monkeypatch):
    (tmp_path / "foto.png").write_bytes(b"png")
    (tmp_path / "p.md").write_text(
        "---\ntipo: pagina\nnombre: P\nseccion: 1\n---\n\n![x](foto.png)\n", encoding="utf-8"
    )
    doc = cargar(tmp_path / "p.md")

    def otra_unidad(*_args):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(contenido_modulo.os.path, "relpath", otra_unidad)
    texto = previsualizar(doc, tmp_path / ".tiza").read_text(encoding="utf-8")
    assert (tmp_path / "foto.png").resolve().as_uri() in texto


# --------------------------------------------------------------------------- #
# Cuestionarios
# --------------------------------------------------------------------------- #


def cuestionario(cuerpo: str = "", **campos) -> str:
    """Un cuestionario válido; ``cuerpo`` son las preguntas YAML ya indentadas."""
    extra = "".join(f"{clave}: {valor}\n" for clave, valor in campos.items())
    preguntas = "\n".join(
        "  " + linea if linea else linea for linea in cuerpo.strip("\n").split("\n")
    )
    return (
        f"---\ntipo: cuestionario\nnombre: Repaso tema 3\nseccion: 3\n{extra}"
        f"preguntas:\n{preguntas}\n---\n\nDescripción del cuestionario.\n"
    )


PREGUNTA_MULTIPLE = """
- tipo: opcion_multiple
  enunciado: ¿Cuánto es **2 + 2**?
  opciones:
    - {texto: "4", correcta: true, retro: ¡Bien!}
    - {texto: "5"}
    - {texto: "3", retro: Casi.}
  retro: Repasa las sumas.
"""


def test_carga_cuestionario_valido(tmp_path):
    doc = cargar(escribir(tmp_path, cuestionario(PREGUNTA_MULTIPLE), "cuestionario.md"))
    assert (doc.tipo, doc.nombre, doc.seccion) == ("cuestionario", "Repaso tema 3", 3)
    assert doc.fechas is None
    assert doc.cuestionario is not None
    [pregunta] = doc.cuestionario.preguntas
    assert pregunta.tipo == "opcion_multiple"
    assert "<strong>2 + 2</strong>" in pregunta.html
    assert [opcion.correcta for opcion in pregunta.opciones] == [True, False, False]
    assert [opcion.texto for opcion in pregunta.opciones] == ["4", "5", "3"]
    assert pregunta.opciones[0].retro == "¡Bien!"
    assert pregunta.opciones[0].retro_html is not None
    assert pregunta.retro_html is not None
    assert (doc.cuestionario.intentos, doc.cuestionario.mezclar_respuestas) == (1, True)
    assert doc.cuestionario.apertura is None and doc.cuestionario.cierre is None
    assert doc.cuestionario.tiempo_limite is None


def test_carga_cuestionario_con_todos_los_tipos(tmp_path):
    doc = cargar(
        escribir(
            tmp_path,
            cuestionario(
                PREGUNTA_MULTIPLE
                + """
- tipo: verdadero_falso
  enunciado: El agua hierve a 100 °C a nivel del mar.
  respuesta: falso
- tipo: respuesta_corta
  enunciado: Capital de Francia
  aceptadas: [París, "París "]
- tipo: numerica
  enunciado: π con dos decimales
  valor: 3.14
  tolerancia: 0.005
""",
                apertura="2026-10-20 08:00",
                cierre="2026-10-27 23:59",
                tiempo_limite="30",
                intentos="ilimitados",
                mezclar_respuestas="false",
            ),
            "cuestionario.md",
        )
    )
    assert doc.cuestionario.apertura == datetime(2026, 10, 20, 8, 0, tzinfo=MADRID)
    assert doc.cuestionario.cierre == datetime(2026, 10, 27, 23, 59, tzinfo=MADRID)
    assert (doc.cuestionario.tiempo_limite, doc.cuestionario.intentos) == (30, 0)
    assert doc.cuestionario.mezclar_respuestas is False
    tipos = [pregunta.tipo for pregunta in doc.cuestionario.preguntas]
    assert tipos == ["opcion_multiple", "verdadero_falso", "respuesta_corta", "numerica"]
    verdadero_falso, corta, numerica = doc.cuestionario.preguntas[1:]
    assert verdadero_falso.respuesta == "falso"
    assert corta.aceptadas == ("París", "París")
    assert corta.mayusculas is False
    assert numerica.valor == 3.14 and numerica.tolerancia == 0.005


def test_fecha_sin_hora_usa_el_fin_del_dia_en_el_cierre(tmp_path):
    doc = cargar(
        escribir(
            tmp_path,
            cuestionario(PREGUNTA_MULTIPLE, apertura="2026-10-20", cierre="2026-10-27"),
            "cuestionario.md",
        )
    )
    assert doc.cuestionario.apertura.hour == 0
    assert doc.cuestionario.cierre.hour == 23 and doc.cuestionario.cierre.minute == 59


@pytest.mark.parametrize(
    ("cuerpo", "extra", "codigo", "detalle"),
    [
        (PREGUNTA_MULTIPLE, {"color": "rojo"}, "CAMPO_DESCONOCIDO", "«color»"),
        (
            PREGUNTA_MULTIPLE.replace("  enunciado:", "  nivel: 3\n  enunciado:"),
            {},
            "CAMPO_DESCONOCIDO",
            "pregunta 1",
        ),
        (
            "- tipo: verdadero_falso\n  enunciado: x\n  respuesta: verdadero\n  opciones: []\n",
            {},
            "CAMPO_DESCONOCIDO",
            "«opciones»",
        ),
        (
            PREGUNTA_MULTIPLE.replace('{texto: "5"}', '{texto: "5", color: azul}'),
            {},
            "CAMPO_DESCONOCIDO",
            "opción 2",
        ),
        ("- tipo: inventada\n  enunciado: x\n", {}, "TIPO_PREGUNTA_INVALIDO", "pregunta 1"),
        (
            "- tipo: verdadero_falso\n  enunciado: '   '\n  respuesta: verdadero\n",
            {},
            "ENUNCIADO_INVALIDO",
            "pregunta 1",
        ),
        (
            '- tipo: opcion_multiple\n  enunciado: x\n  opciones:\n    - {texto: "4", correcta: true}\n',
            {},
            "OPCIONES_INVALIDAS",
            "pregunta 1",
        ),
        (
            '- tipo: opcion_multiple\n  enunciado: x\n  opciones:\n    - {texto: "4"}\n    - {texto: "5"}\n',
            {},
            "OPCIONES_INVALIDAS",
            "ninguna opción",
        ),
        (
            "- tipo: verdadero_falso\n  enunciado: x\n  respuesta: quizá\n",
            {},
            "RESPUESTA_PREGUNTA_INVALIDA",
            "pregunta 1",
        ),
        (
            "- tipo: respuesta_corta\n  enunciado: x\n  aceptadas: []\n",
            {},
            "RESPUESTA_PREGUNTA_INVALIDA",
            "aceptadas",
        ),
        (
            "- tipo: respuesta_corta\n  enunciado: x\n  aceptadas: ['']\n",
            {},
            "RESPUESTA_PREGUNTA_INVALIDA",
            "aceptadas",
        ),
        (
            "- tipo: respuesta_corta\n  enunciado: x\n  aceptadas: [París]\n  mayusculas: si\n",
            {},
            "RESPUESTA_PREGUNTA_INVALIDA",
            "mayusculas",
        ),
        (
            '- tipo: numerica\n  enunciado: x\n  valor: "tres"\n',
            {},
            "RESPUESTA_PREGUNTA_INVALIDA",
            "valor",
        ),
        (
            "- tipo: numerica\n  enunciado: x\n  valor: 3\n  tolerancia: -1\n",
            {},
            "RESPUESTA_PREGUNTA_INVALIDA",
            "tolerancia",
        ),
        (PREGUNTA_MULTIPLE, {"tiempo_limite": "0"}, "AJUSTE_INVALIDO", "tiempo_limite"),
        (PREGUNTA_MULTIPLE, {"tiempo_limite": "601"}, "AJUSTE_INVALIDO", "tiempo_limite"),
        (PREGUNTA_MULTIPLE, {"tiempo_limite": '"30"'}, "AJUSTE_INVALIDO", "tiempo_limite"),
        (PREGUNTA_MULTIPLE, {"intentos": "0"}, "AJUSTE_INVALIDO", "intentos"),
        (PREGUNTA_MULTIPLE, {"intentos": "11"}, "AJUSTE_INVALIDO", "intentos"),
        (PREGUNTA_MULTIPLE, {"intentos": '"ilimitado"'}, "AJUSTE_INVALIDO", "intentos"),
        (PREGUNTA_MULTIPLE, {"intentos": "true"}, "AJUSTE_INVALIDO", "intentos"),
        (PREGUNTA_MULTIPLE, {"mezclar_respuestas": "sí"}, "AJUSTE_INVALIDO", "mezclar_respuestas"),
        (PREGUNTA_MULTIPLE, {"apertura": "el jueves"}, "FECHA_INVALIDA", "jueves"),
        (
            PREGUNTA_MULTIPLE,
            {"apertura": "2026-10-28", "cierre": "2026-10-27"},
            "FECHAS_INCOHERENTES",
            "apertura < cierre",
        ),
    ],
)
def test_falla_una_pregunta_o_un_ajuste(tmp_path, cuerpo, extra, codigo, detalle):
    ruta = escribir(tmp_path, cuestionario(cuerpo, **extra), "cuestionario.md")
    with pytest.raises(ErrorContenido) as exc:
        cargar(ruta)
    assert exc.value.codigo == codigo
    assert detalle in exc.value.detalle


def test_preguntas_ausentes_o_demasiadas(tmp_path):
    sin_preguntas = "---\ntipo: cuestionario\nnombre: Q\nseccion: 1\npreguntas: []\n---\n\nx\n"
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, sin_preguntas, "vacio.md"))
    assert exc.value.codigo == "PREGUNTAS_INVALIDAS"
    faltan = "---\ntipo: cuestionario\nnombre: Q\nseccion: 1\n---\n\nx\n"
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, faltan, "sin.md"))
    assert exc.value.codigo == "PREGUNTAS_INVALIDAS"
    muchas = "".join(
        f"- tipo: verdadero_falso\n  enunciado: Pregunta {i}\n  respuesta: verdadero\n"
        for i in range(1, 102)
    )
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, cuestionario(muchas), "muchas.md"))
    assert exc.value.codigo == "PREGUNTAS_INVALIDAS"


def test_el_detalle_de_los_errores_nombra_la_pregunta_y_la_opción(tmp_path):
    md = cuestionario(
        "- tipo: opcion_multiple\n  enunciado: x\n  opciones:\n"
        '    - {texto: "4", correcta: true}\n    - {texto: "5", correcta: true, retro: 7}\n'
    )
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, md, "cuestionario.md"))
    assert "pregunta 1, opción 2" in exc.value.detalle
    assert "retro" in exc.value.detalle


@pytest.mark.parametrize(
    "campo",
    [
        'enunciado: "<script>alert(1)</script>"',
        'enunciado: "**x**"\n  opciones:\n    - {texto: "<form></form>", correcta: true}\n    - {texto: "b"}',
        'enunciado: "**x**"\n  retro: "<style>p{}</style>"',
    ],
)
def test_html_peligroso_en_una_pregunta(tmp_path, campo):
    if campo.startswith('enunciado: "<script'):
        cuerpo = f"- tipo: verdadero_falso\n  {campo}\n  respuesta: verdadero\n"
    else:
        cuerpo = f"- tipo: opcion_multiple\n  {campo}\n"
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, cuestionario(cuerpo), "cuestionario.md"))
    assert exc.value.codigo == "HTML_PELIGROSO"
    assert "pregunta 1" in exc.value.detalle


def test_recurso_local_en_una_pregunta(tmp_path):
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "foto.png").write_bytes(b"png")
    md = cuestionario(
        "- tipo: verdadero_falso\n  enunciado: Mira ![foto](img/foto.png)\n  respuesta: verdadero\n"
    )
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, md, "cuestionario.md"))
    assert exc.value.codigo == "RECURSO_EN_PREGUNTA"
    assert "foto.png" in exc.value.detalle


def test_los_iframes_de_las_preguntas_se_admiten_y_se_listan(tmp_path):
    md = cuestionario(
        "- tipo: verdadero_falso\n"
        "  enunciado: '<iframe src=\"https://www.youtube.com/embed/abc\"></iframe>'\n"
        "  respuesta: verdadero\n",
        apertura="2026-10-20",
    )
    md += "\n[web de apoyo](https://ejemplo.org/apoyo)\n"
    doc = cargar(escribir(tmp_path, md, "cuestionario.md"))
    assert doc.cuestionario.incrustados == ("https://www.youtube-nocookie.com/embed/abc",)
    assert doc.enlaces_externos == ["https://ejemplo.org/apoyo"]


def test_el_hash_del_cuestionario_detecta_cambios(tmp_path):
    uno = cargar(escribir(tmp_path, cuestionario(PREGUNTA_MULTIPLE), "a.md"))
    otro = cargar(escribir(tmp_path, cuestionario(PREGUNTA_MULTIPLE, intentos="2"), "b.md"))
    assert hash_documento(uno) != hash_documento(otro)
    cambiada = cargar(
        escribir(
            tmp_path,
            cuestionario(
                PREGUNTA_MULTIPLE.replace('- {texto: "5"}', '- {texto: "5", retro: casi}')
            ),
            "c.md",
        )
    )
    assert hash_documento(uno) != hash_documento(cambiada)
    igual = cargar(escribir(tmp_path, cuestionario(PREGUNTA_MULTIPLE), "d.md"))
    assert hash_documento(uno) == hash_documento(igual)


def test_el_hash_cambia_al_mover_la_correcta(tmp_path):
    una = cargar(escribir(tmp_path, cuestionario(PREGUNTA_MULTIPLE), "a.md"))
    otra = cargar(
        escribir(
            tmp_path,
            cuestionario(
                PREGUNTA_MULTIPLE.replace('{texto: "4", correcta: true}', '{texto: "4"}').replace(
                    '- {texto: "5"}', '- {texto: "5", correcta: true}'
                )
            ),
            "b.md",
        )
    )
    assert hash_documento(una) != hash_documento(otra)


def test_la_vista_previa_muestra_la_respuesta_de_cada_tipo(tmp_path):
    doc = cargar(
        escribir(
            tmp_path,
            cuestionario(
                """
- tipo: verdadero_falso
  enunciado: El agua hierve a 100 °C.
  respuesta: verdadero
- tipo: respuesta_corta
  enunciado: Capital de Francia
  aceptadas: [París]
- tipo: numerica
  enunciado: π con dos decimales
  valor: 3.14
  tolerancia: 0.005
"""
            ),
            "cuestionario.md",
        )
    )
    texto = previsualizar(doc, tmp_path / ".tiza").read_text(encoding="utf-8")
    assert "Respuesta correcta: <strong>Verdadero</strong>" in texto
    assert "Respuestas válidas: <strong>París</strong>" in texto
    assert "Valor: <strong>3.14</strong> (tolerancia ±0.005)" in texto


def test_la_vista_previa_muestra_la_descripcion_del_cuestionario(tmp_path):
    doc = cargar(escribir(tmp_path, cuestionario(PREGUNTA_MULTIPLE), "cuestionario.md"))
    texto = previsualizar(doc, tmp_path / ".tiza").read_text(encoding="utf-8")
    assert "<p>Descripción del cuestionario.</p>" in texto
    assert "VISTA PREVIA" in texto


def test_la_vista_previa_numerica_redondea_los_decimales_de_mas(tmp_path):
    doc = cargar(
        escribir(
            tmp_path,
            cuestionario("- tipo: numerica\n  enunciado: x\n  valor: 5.0\n  tolerancia: 0\n"),
            "cuestionario.md",
        )
    )
    texto = previsualizar(doc, tmp_path / ".tiza").read_text(encoding="utf-8")
    assert "Valor: <strong>5</strong>" in texto
    assert "tolerancia" not in texto


def test_la_vista_previa_muestra_las_preguntas_y_las_correctas(tmp_path):
    doc = cargar(
        escribir(
            tmp_path,
            cuestionario(PREGUNTA_MULTIPLE, tiempo_limite="30", intentos="2"),
            "cuestionario.md",
        )
    )
    texto = previsualizar(doc, tmp_path / ".tiza").read_text(encoding="utf-8")
    assert "Preguntas del cuestionario" in texto
    assert "<strong>(correcta)</strong>" in texto
    assert "Repasa las sumas." in texto
    assert "Tiempo límite:" in texto and "30 minutos" in texto
    assert "Intentos:</strong> 2<" in texto


def test_la_vista_previa_del_cuestionario_no_anida_parrafos(tmp_path):
    # La retro ya es un bloque <p>: incrustada en <p> o <em> el navegador rehace el marcado.
    doc = cargar(escribir(tmp_path, cuestionario(PREGUNTA_MULTIPLE), "cuestionario.md"))
    texto = previsualizar(doc, tmp_path / ".tiza").read_text(encoding="utf-8")
    html5lib.HTMLParser(strict=True).parse(texto)  # <p> dentro de <p> da ParseError
    arbol = BeautifulSoup(texto, "html5lib")
    assert arbol.select("p p, em p, strong p") == []
    assert "Retroalimentación:" in texto and "¡Bien!" in texto


def test_render_respeta_lineas_en_blanco_dentro_de_pre_en_un_div():
    # Un bloque HTML que empieza por <div> termina en la primera línea en blanco:
    # lo que quedaba del <pre> se interpretaba como Markdown (párrafos y listas).
    cuerpo = (
        '<div class="card">\n'
        '<pre style="white-space: pre-wrap;">MIEMBROS: [Tu Nombre]\n'
        "\n"
        "PARTE 1:\n"
        "• Fase 1:\n"
        "  - Opciones: ...\n"
        "\n"
        "PARTE 2:\n"
        "</pre>\n"
        "</div>\n"
    )
    html = contenido._render(cuerpo)
    assert "<ul>" not in html
    assert "<p>" not in html
    assert "[Tu Nombre]\n\nPARTE 1:\n• Fase 1:\n  - Opciones: ...\n\nPARTE 2:\n</pre>" in html


# --------------------------------------------------------------------------- #
# Actividades H5P
# --------------------------------------------------------------------------- #


def h5p(actividad: str, **campos) -> str:
    """Un documento h5p válido; ``actividad`` es el YAML ya escrito."""
    extra = "".join(f"{clave}: {valor}\n" for clave, valor in campos.items())
    indentado = "\n".join(
        "  " + linea if linea else linea for linea in actividad.strip("\n").split("\n")
    )
    return (
        f"---\ntipo: h5p\nnombre: Actividad H5P\nseccion: 3\n{extra}"
        f"actividad:\n{indentado}\n---\n\nDescripción de la actividad.\n"
    )


RELLENAR_HUECOS = """
tipo: rellenar_huecos
textos:
  - "El agua hierve a [[100]] grados."
  - "La capital de Francia es [[París|Paris]]."
"""


def test_carga_h5p_rellenar_huecos_valido(tmp_path):
    doc = cargar(escribir(tmp_path, h5p(RELLENAR_HUECOS), "actividad.md"))
    assert (doc.tipo, doc.nombre, doc.seccion) == ("h5p", "Actividad H5P", 3)
    assert doc.cuestionario is None and doc.fechas is None
    assert doc.h5p is not None and doc.h5p.tipo == "rellenar_huecos"
    assert len(doc.h5p.textos) == 2
    assert doc.h5p.textos[0].h5p == "<p>El agua hierve a *100* grados.</p>\n"
    [marca] = [parte for parte in doc.h5p.textos[1].partes if not isinstance(parte, str)]
    assert marca.respuestas == ("París", "Paris")
    assert doc.h5p.mayusculas is False
    assert doc.h5p.calificacion == 10
    assert doc.h5p.reintentar is True and doc.h5p.ver_solucion is True
    assert doc.paquete is None


def test_carga_h5p_con_ajustes(tmp_path):
    actividad = (
        RELLENAR_HUECOS
        + "mayusculas: true\ncalificacion: 5\nreintentar: false\nver_solucion: false\n"
    )
    doc = cargar(escribir(tmp_path, h5p(actividad), "actividad.md"))
    assert (doc.h5p.mayusculas, doc.h5p.calificacion) == (True, 5)
    assert (doc.h5p.reintentar, doc.h5p.ver_solucion) == (False, False)


def test_carga_h5p_arrastrar_palabras(tmp_path):
    actividad = """
tipo: arrastrar_palabras
texto: "El [[sol]] brilla."
distractores: [nube, lluvia]
"""
    doc = cargar(escribir(tmp_path, h5p(actividad), "actividad.md"))
    assert doc.h5p.texto.h5p == "El *sol* brilla."
    assert doc.h5p.distractores == ("nube", "lluvia")


def test_carga_h5p_marcar_palabras(tmp_path):
    actividad = """
tipo: marcar_palabras
enunciado: Marca los verbos.
texto: "El niño [[come]] pan."
"""
    doc = cargar(escribir(tmp_path, h5p(actividad), "actividad.md"))
    assert doc.h5p.enunciado == "Marca los verbos."
    assert doc.h5p.texto.h5p == "<p>El niño *come* pan.</p>\n"


def test_carga_h5p_tarjetas(tmp_path):
    actividad = """
tipo: tarjetas
tarjetas:
  - {anverso: "¿2 + 2?", reverso: "4"}
  - anverso: "**Capital** de Francia"
    reverso: París
"""
    doc = cargar(escribir(tmp_path, h5p(actividad), "actividad.md"))
    assert [tarjeta.anverso for tarjeta in doc.h5p.tarjetas] == [
        "¿2 + 2?",
        "**Capital** de Francia",
    ]
    assert doc.h5p.tarjetas[1].reverso == "París"
    assert "<strong>Capital</strong>" in doc.h5p.tarjetas[1].anverso_html


def test_h5p_sin_actividad_ni_paquete_falla(tmp_path):
    md = "---\ntipo: h5p\nnombre: A\nseccion: 1\n---\n\nx\n"
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, md, "actividad.md"))
    assert exc.value.codigo == "CAMPO_FALTANTE"


def test_h5p_con_actividad_y_paquete_falla(tmp_path):
    md = h5p(RELLENAR_HUECOS).replace("---\n\nDescripción", "paquete: otro.h5p\n---\n\nDescripción")
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, md, "actividad.md"))
    assert exc.value.codigo == "CAMPOS_INCOMPATIBLES"


@pytest.mark.parametrize(
    ("actividad", "codigo", "detalle"),
    [
        ("tipo: ruleta\n", "ACTIVIDAD_H5P_INVALIDA", "rellenar_huecos"),
        ("tipo: rellenar_huecos\nextra: 1\n", "CAMPO_DESCONOCIDO", "extra"),
        ("tipo: rellenar_huecos\ntextos: []\n", "ACTIVIDAD_H5P_INVALIDA", "textos"),
        ("tipo: rellenar_huecos\ntextos: ['sin hueco']\n", "ACTIVIDAD_H5P_INVALIDA", "hueco"),
        (
            "tipo: rellenar_huecos\ntextos: ['2 * 3 = [[6]]']\n",
            "ACTIVIDAD_H5P_INVALIDA",
            "asterisco",
        ),
        ("tipo: rellenar_huecos\ntextos: ['[[a/b]]']\n", "ACTIVIDAD_H5P_INVALIDA", "respuesta"),
        ("tipo: rellenar_huecos\ntextos: ['[[a:b]]']\n", "ACTIVIDAD_H5P_INVALIDA", "respuesta"),
        ("tipo: rellenar_huecos\ntextos: ['[[a]] y [[b']\n", "ACTIVIDAD_H5P_INVALIDA", "cerrar"),
        ("tipo: rellenar_huecos\ntextos: ['[[]]']\n", "ACTIVIDAD_H5P_INVALIDA", "vacía"),
        ("tipo: rellenar_huecos\ntextos: ['[[a|]]']\n", "ACTIVIDAD_H5P_INVALIDA", "vacía"),
        (
            "tipo: rellenar_huecos\ntextos: ['[[a]]']\nmayusculas: sí\n",
            "ACTIVIDAD_H5P_INVALIDA",
            "mayusculas",
        ),
        (
            "tipo: rellenar_huecos\ntextos: ['[[a]]']\ncalificacion: 0\n",
            "ACTIVIDAD_H5P_INVALIDA",
            "calificacion",
        ),
        (
            "tipo: rellenar_huecos\ntextos: ['[[a]]']\nreintentar: 1\n",
            "ACTIVIDAD_H5P_INVALIDA",
            "reintentar",
        ),
        ("tipo: rellenar_huecos\ntextos: ['[[a]]', '']\n", "ACTIVIDAD_H5P_INVALIDA", "texto"),
        ("tipo: tarjetas\ntarjetas: []\n", "ACTIVIDAD_H5P_INVALIDA", "tarjetas"),
        ("tipo: tarjetas\ntarjetas: [{anverso: a}]\n", "ACTIVIDAD_H5P_INVALIDA", "reverso"),
        (
            "tipo: tarjetas\ntarjetas: [{anverso: a, reverso: b, extra: 1}]\n",
            "CAMPO_DESCONOCIDO",
            "extra",
        ),
        (
            "tipo: tarjetas\ntarjetas: [{anverso: a, reverso: b}]\ncalificacion: 5\n",
            "CAMPO_DESCONOCIDO",
            "calificacion",
        ),
        ("tipo: marcar_palabras\ntexto: 'sin marca'\n", "ACTIVIDAD_H5P_INVALIDA", "enunciado"),
        ("tipo: arrastrar_palabras\ntexto: 'sin marca'\n", "ACTIVIDAD_H5P_INVALIDA", "hueco"),
    ],
)
def test_h5p_errores_de_actividad(tmp_path, actividad, codigo, detalle):
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, h5p(actividad), "actividad.md"))
    assert exc.value.codigo == codigo
    assert detalle in exc.value.detalle


def test_h5p_rechaza_bloques_y_formato_no_admitido(tmp_path):
    actividad = """
tipo: marcar_palabras
enunciado: "Marca:\\n\\n- uno\\n- dos"
texto: "El niño [[come]] pan."
"""
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, h5p(actividad), "actividad.md"))
    assert exc.value.codigo == "ACTIVIDAD_H5P_INVALIDA"


def test_h5p_rechaza_html_peligroso(tmp_path):
    actividad = """
tipo: marcar_palabras
enunciado: "<script>alert(1)</script>"
texto: "El niño [[come]] pan."
"""
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, h5p(actividad), "actividad.md"))
    assert exc.value.codigo == "HTML_PELIGROSO"


def paquete_h5p(tmp_path, nombre: str = "paquete.h5p", titulo: str = "Mi paquete"):
    import io as _io
    import zipfile as _zipfile

    ruta = tmp_path / nombre
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as zip_:
        zip_.writestr(
            "h5p.json",
            f'{{"title":"{titulo}","mainLibrary":"H5P.Blanks",'
            '"preloadedDependencies":[{"machineName":"H5P.Blanks","majorVersion":1,'
            '"minorVersion":14}]}',
        )
        zip_.writestr("content/content.json", '{"questions":[]}')
        zip_.writestr("content/imagen.png", b"png")
    ruta.write_bytes(buf.getvalue())
    return ruta


def test_h5p_paquete_se_resuelve_y_entra_en_el_hash(tmp_path):
    paquete_h5p(tmp_path)
    md = "---\ntipo: h5p\nnombre: A\nseccion: 1\npaquete: paquete.h5p\n---\n\nDescripción.\n"
    doc = cargar(escribir(tmp_path, md, "actividad.md"), raiz=tmp_path)
    assert doc.paquete is not None and doc.paquete.nombre == "paquete.h5p"
    original = hash_documento(doc)
    paquete_h5p(tmp_path, titulo="Otro título")
    otro = cargar(escribir(tmp_path, md, "activ2.md"), raiz=tmp_path)
    assert hash_documento(otro) != original


def test_h5p_paquete_ausente_falla(tmp_path):
    md = "---\ntipo: h5p\nnombre: A\nseccion: 1\npaquete: no-existe.h5p\n---\n\nx\n"
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, md, "actividad.md"), raiz=tmp_path)
    assert exc.value.codigo == "RECURSO_AUSENTE"


def test_h5p_paquete_invalido_falla_al_cargar(tmp_path):
    (tmp_path / "roto.h5p").write_bytes(b"no es un zip")
    md = "---\ntipo: h5p\nnombre: A\nseccion: 1\npaquete: roto.h5p\n---\n\nx\n"
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, md, "actividad.md"), raiz=tmp_path)
    assert exc.value.codigo == "PAQUETE_H5P_INVALIDO"


def test_h5p_paquete_muestra_los_enlaces_externos(tmp_path):
    import zipfile as _zipfile

    ruta = tmp_path / "paquete.h5p"
    with _zipfile.ZipFile(ruta, "w") as zip_:
        zip_.writestr(
            "h5p.json",
            '{"title":"Mi paquete","mainLibrary":"H5P.Blanks",'
            '"preloadedDependencies":[{"machineName":"H5P.Blanks","majorVersion":1,'
            '"minorVersion":14}]}',
        )
        zip_.writestr("content/content.json", '{"questions":["Mira https://ejemplo.org/apoyo."]}')
    md = "---\ntipo: h5p\nnombre: A\nseccion: 1\npaquete: paquete.h5p\n---\n\nx\n"
    doc = cargar(escribir(tmp_path, md, "actividad.md"), raiz=tmp_path)
    assert doc.enlaces_externos == ["https://ejemplo.org/apoyo"]


def test_h5p_paquete_oculto_falla(tmp_path):
    (tmp_path / ".oculto.h5p").write_bytes(b"x")
    md = "---\ntipo: h5p\nnombre: A\nseccion: 1\npaquete: .oculto.h5p\n---\n\nx\n"
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, md, "actividad.md"), raiz=tmp_path)
    assert exc.value.codigo == "RECURSO_NO_PERMITIDO"


def test_h5p_paquete_fuera_de_la_carpeta_falla(tmp_path):
    fuera = paquete_h5p(tmp_path)
    carpeta = tmp_path / "clase"
    carpeta.mkdir()
    md = f"---\ntipo: h5p\nnombre: A\nseccion: 1\npaquete: {fuera}\n---\n\nx\n"
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(carpeta, md, "actividad.md"), raiz=carpeta)
    assert exc.value.codigo == "RUTA_FUERA_DE_CARPETA"


def test_h5p_paquete_que_no_es_h5p_falla(tmp_path):
    (tmp_path / "paquete.zip").write_bytes(b"x")
    md = "---\ntipo: h5p\nnombre: A\nseccion: 1\npaquete: paquete.zip\n---\n\nx\n"
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, md, "actividad.md"), raiz=tmp_path)
    assert exc.value.codigo == "PAQUETE_H5P_INVALIDO"


def test_h5p_paquete_demasiado_grande_falla(tmp_path, monkeypatch):
    monkeypatch.setattr(contenido, "MAX_PAQUETE_H5P_BYTES", 4)
    paquete_h5p(tmp_path)
    md = "---\ntipo: h5p\nnombre: A\nseccion: 1\npaquete: paquete.h5p\n---\n\nx\n"
    with pytest.raises(ErrorContenido) as exc:
        cargar(escribir(tmp_path, md, "actividad.md"), raiz=tmp_path)
    assert exc.value.codigo == "PAQUETE_H5P_DEMASIADO_GRANDE"


def test_la_vista_previa_muestra_los_huecos_subrayados(tmp_path):
    doc = cargar(escribir(tmp_path, h5p(RELLENAR_HUECOS), "actividad.md"))
    texto = previsualizar(doc, tmp_path / ".tiza").read_text(encoding="utf-8")
    assert "Actividad H5P" in texto
    assert "El agua hierve a <u>100</u> grados." in texto
    assert "<u>París | Paris</u>" in texto


def test_la_vista_previa_muestra_las_tarjetas(tmp_path):
    actividad = """
tipo: tarjetas
tarjetas:
  - {anverso: "¿2 + 2?", reverso: "4"}
"""
    doc = cargar(escribir(tmp_path, h5p(actividad), "actividad.md"))
    texto = previsualizar(doc, tmp_path / ".tiza").read_text(encoding="utf-8")
    assert "¿2 + 2?" in texto and "<strong>Reverso:</strong>" in texto
    assert ">4<" in texto


def test_la_vista_previa_muestra_el_resumen_del_paquete(tmp_path):
    paquete_h5p(tmp_path, titulo="Mi paquete")
    md = "---\ntipo: h5p\nnombre: A\nseccion: 1\npaquete: paquete.h5p\n---\n\nx\n"
    doc = cargar(escribir(tmp_path, md, "actividad.md"), raiz=tmp_path)
    texto = previsualizar(doc, tmp_path / ".tiza").read_text(encoding="utf-8")
    assert "Mi paquete" in texto
    assert "H5P.Blanks" in texto
    assert "content/content.json" in texto or "content.json" in texto
