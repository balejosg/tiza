"""Tests offline de la política de HTML (tiza.filtro)."""

from __future__ import annotations

import pytest

from tiza import filtro
from tiza.filtro import HtmlPeligroso, analizar


def acepta(html: str) -> filtro.Analisis:
    return analizar(html)


def rechaza(html: str) -> str:
    with pytest.raises(HtmlPeligroso) as exc:
        analizar(html)
    return exc.value.detalle


class TestEtiquetas:
    @pytest.mark.parametrize("etiqueta", ["section", "article", "header", "footer", "aside"])
    def test_acepta_las_etiquetas_de_estructura(self, etiqueta):
        acepta(f"<{etiqueta}><p>texto</p></{etiqueta}>")

    @pytest.mark.parametrize(
        "etiqueta",
        ["main", "nav", "button", "form", "input", "video", "audio", "object", "embed", "canvas"],
    )
    def test_rechaza_las_que_siguen_fuera(self, etiqueta):
        assert f"<{etiqueta}>" in rechaza(f"<{etiqueta}>x</{etiqueta}>")

    @pytest.mark.parametrize(
        "html",
        [
            "<style>p{color:red}</style><p>x</p>",
            '<meta http-equiv="refresh" content="0;url=https://evil.example/">',
            '<link rel="stylesheet" href="https://evil.example/x.css">',
            "<title>t</title><p>x</p><script>alert(1)</script>",
            "<svg><a><animate attributeName='href' values='javascript:x'/></a></svg>",
            "<math><mi>x</mi></math>",
            "<textarea><script>alert(1)</script></textarea>",
            "<xmp><script>alert(1)</script></xmp>",
            "<noscript><p>x</p></noscript>",
            "<template><p>x</p></template>",
        ],
    )
    def test_rechaza_las_etiquetas_con_un_modo_de_analisis_especial(self, html):
        rechaza(html)


class TestAtributos:
    def test_enlace_que_se_abre_en_otra_pestana(self):
        acepta('<a href="https://example.org" target="_blank" rel="noopener noreferrer">x</a>')

    @pytest.mark.parametrize("destino", ["_self", "_top", "_parent", "marco"])
    def test_target_solo_admite_blank(self, destino):
        assert "target" in rechaza(f'<a href="https://example.org" target="{destino}">x</a>')

    @pytest.mark.parametrize("rel", ["author", "stylesheet", "noopener preload", "opener"])
    def test_rel_solo_admite_valores_inocuos(self, rel):
        assert "rel" in rechaza(f'<a href="https://example.org" rel="{rel}">x</a>')

    def test_rel_nofollow(self):
        acepta('<a href="https://example.org" rel="nofollow">x</a>')

    @pytest.mark.parametrize("medida", ["560", "560px", "50%", "0"])
    def test_medidas_de_imagen(self, medida):
        acepta(f'<img src="https://example.org/a.png" width="{medida}" height="{medida}">')

    @pytest.mark.parametrize("medida", ["560em", "calc(1px)", "-5", "12345px", "2001px", "50 %"])
    def test_medidas_invalidas(self, medida):
        rechaza(f'<img src="https://example.org/a.png" width="{medida}">')

    @pytest.mark.parametrize(
        "atributo",
        ['id="x"', 'data-x="1"', 'aria-label="x"', 'role="button"', 'dir="rtl"', 'onclick="x()"'],
    )
    def test_rechaza_atributos_fuera_de_la_lista(self, atributo):
        detalle = rechaza(f"<p {atributo}>x</p>")
        assert atributo.split("=")[0] in detalle
        assert "<p>" in detalle


class TestUrlsLocales:
    @pytest.mark.parametrize("url", ["\\\\servidor\\recurso\\a.png", "/\\evil.com/a.png"])
    def test_rechaza_rutas_de_red_y_barras_invertidas(self, url):
        assert "barras invertidas" in rechaza(f'<img src="{url}">')
        assert "barras invertidas" in rechaza(f'<a href="{url}">x</a>')

    def test_la_ruta_de_unidad_de_windows_sigue_siendo_local(self):
        assert acepta('<img src="C:\\fotos\\a.png">').locales == ["C:\\fotos\\a.png"]


class TestClases:
    @pytest.mark.parametrize(
        "clases",
        [
            "alert alert-info",
            "alert-warning",
            "card card-body",
            "card-header",
            "table table-striped table-bordered",
            "mt-3 mb-0 px-2 py-5 mx-auto m-0",
            "text-center text-danger fw-bold",
            "bg-light text-bg-primary border border-success rounded shadow-sm",
            "row",
            "col col-6 col-md-4 col-xl-12",
            "d-flex justify-content-between align-items-center flex-column",
            "img-fluid",
            "list-unstyled lead small",
            "badge badge-info",
        ],
    )
    def test_acepta_las_clases_de_la_lista(self, clases):
        acepta(f'<div class="{clases}">x</div>')

    @pytest.mark.parametrize(
        "clase",
        [
            "position-fixed",
            "position-absolute",
            "fixed-top",
            "fixed-bottom",
            "sticky-top",
            "stretched-link",
            "modal",
            "modal-backdrop",
            "d-none",
            "collapse",
            "dropdown-menu",
            "mt-n3",
            "m-6",
            "col-13",
            "col-0",
            "propia-de-moodle",
            "navbar",
        ],
    )
    def test_rechaza_clases_fuera_de_la_lista(self, clase):
        detalle = rechaza(f'<span class="alert {clase}">x</span>')
        assert f"«{clase}»" in detalle
        assert "<span>" in detalle

    def test_btn_solo_en_enlaces(self):
        acepta('<a class="btn btn-primary btn-lg" href="https://example.org">x</a>')
        acepta('<a class="btn btn-outline-danger btn-sm" href="https://example.org">x</a>')
        assert "«btn»" in rechaza('<span class="btn">x</span>')

    def test_language_solo_en_code(self):
        acepta('<pre><code class="language-python">print(1)</code></pre>')
        assert "language-python" in rechaza('<div class="language-python">x</div>')
        rechaza('<code class="language-<b>">x</code>')

    def test_clase_vacia_o_con_controles(self):
        rechaza('<p class="alert\x1balert-info">x</p>')


def estilo(css: str, etiqueta: str = "div") -> str:
    """Valida ``<etiqueta style=css>`` y devuelve el style que se publicaría."""
    resultado = acepta(f'<{etiqueta} style="{css}">x</{etiqueta}>')
    return resultado.cuerpo.find(etiqueta).get("style", "")


class TestCSS:
    @pytest.mark.parametrize(
        "css",
        [
            "color:red",
            "color:#fff",
            "color:#ffcc0080",
            "color:rgb(255, 0, 0)",
            "color:rgba(0 0 0 / 50%)",
            "color:hsl(120deg 50% 50%)",
            "background:linear-gradient(to right, #fff, red 50%)",
            "background:radial-gradient(circle, #fff, #000)",
            "background-color:lightyellow",
            "margin:0 auto",
            "margin-top:1.5em;padding:10px 20px",
            "border:1px solid #ccc",
            "border-bottom:2px dashed red",
            "border-radius:8px",
            "border-collapse:collapse",
            "box-shadow:0 2px 4px rgba(0,0,0,.2)",
            "box-sizing:border-box",
            "font-family:'Comic Sans MS', Arial, sans-serif",
            "font-size:1.2rem;font-weight:700;font-style:italic;line-height:1.5",
            "text-align:center;text-decoration:underline;text-transform:uppercase",
            "letter-spacing:2px;text-indent:2em;vertical-align:middle;white-space:pre-wrap",
            "width:100%;max-width:560px;min-height:100px",
            "aspect-ratio:16/9",
            "aspect-ratio:16 / 9",
            "display:flex;justify-content:space-between;align-items:center;gap:10px",
            "display:grid;grid-template-columns:repeat(3, 1fr)",
            "grid-template-columns:minmax(0, 1fr) 2fr",
            "grid-column:1 / 3",
            "flex:1 1 0%;flex-wrap:wrap;flex-direction:column",
            "float:left;clear:both;overflow:auto;overflow-x:hidden",
            "list-style-type:square",
            "color:red;",
            "color:red;;margin:0",
            "COLOR : Red",
        ],
    )
    def test_acepta_lo_que_maqueta(self, css):
        assert estilo(css)

    def test_el_css_publicado_se_reescribe_desde_los_tokens(self):
        assert estilo("COLOR : Red ;  margin:0   auto;") == "color:Red;margin:0 auto"
        assert estilo("font-family: 'A B' ,  sans-serif") == 'font-family:"A B" , sans-serif'
        assert estilo("text-align:right") == "text-align:right"

    def test_style_vacio_se_quita(self):
        assert estilo("  ;  ") == ""

    @pytest.mark.parametrize(
        ("css", "nombre"),
        [
            ("position:fixed", "position"),
            ("position:absolute;top:0;left:0", "position"),
            ("top:0", "top"),
            ("left:0", "left"),
            ("z-index:9999", "z-index"),
            ("transform:translate(0,0)", "transform"),
            ("visibility:hidden", "visibility"),
            ("opacity:0", "opacity"),
            ("content:'x'", "content"),
            ("cursor:pointer", "cursor"),
            ("pointer-events:none", "pointer-events"),
            ("animation:x 1s", "animation"),
            ("--x:1", "--x"),
            ("-webkit-box-shadow:0 0 1px red", "-webkit-box-shadow"),
            ("behavior:url(x.htc)", "behavior"),
        ],
    )
    def test_rechaza_propiedades_fuera_de_la_lista(self, css, nombre):
        detalle = rechaza(f'<div style="{css}">x</div>')
        assert f"«{nombre}»" in detalle
        assert "<div>" in detalle

    @pytest.mark.parametrize(
        ("css", "motivo"),
        [
            ("background:url(https://tracker.example/p.gif)", "url"),
            ('background:url("https://tracker.example/p.gif")', "url"),
            ("background:u\\72l(https://tracker.example/p.gif)", "url"),
            ("background:URL( https://tracker.example/p.gif )", "url"),
            ("background-color:red;background:url(x)", "url"),
            ("width:calc(100% - 10px)", "calc"),
            ("color:var(--x)", "var"),
            ("width:attr(data-w)", "attr"),
            ("background:image-set(red 1x)", "image-set"),
            ("color:expression(alert(1))", "expression"),
            ("color:red !important", "important"),
            ("color:red!IMPORTANT", "important"),
            ("color:red /* x */", "comentario"),
            ("/* x */ color:red", "comentario"),
            ("color:red; /* x */", "comentario"),
            ("margin:-5px", "negativ"),
            ("margin:0 -1em", "negativ"),
            ("width:-1%", "negativ"),
            ("line-height:-1", "negativ"),
            ("width:99999px", "grande"),
            ("width:1e999px", "grande"),
            ("box-shadow:0 0 0 5000px white", "grande"),
            ("box-shadow:0 0 0 50rem white", "grande"),
            ("padding:400px", "grande"),
            ("padding-top:100px", "grande"),
            ("padding:2000rem", "grande"),
            ("font-size:2000rem", "grande"),
            ("width:50vw", "vw"),
            ("width:10cm", "cm"),
            ("color:#12", "color"),
            ("color:#12345", "color"),
            ("color:#ggg", "color"),
            ("color:re\\d", "identificador"),
            ("color:red\\;margin:0", "identificador"),
            ("font-family:'a\\'b'", "texto"),
            ("color:'rojo'", "texto"),
            ("color:;", "vac"),
            ("color:red {}", "regla"),
            ("p { color: red }", "regla"),
            ("@import 'x'", "regla"),
            ("color:red; @import 'x'", "regla"),
            ("color:red;background:}", "mal formado"),
            ("margin:0 auto)", "mal formado"),
            ("color", "mal formado"),
            ("display:none", "display"),
            ("display:contents", "display"),
            ("margin:[1px]", "bloque"),
        ],
    )
    def test_rechaza_valores_peligrosos_o_fuera_de_la_lista(self, css, motivo):
        en_atributo = css.replace('"', "&quot;")
        detalle = rechaza(f'<div style="{en_atributo}">x</div>')
        assert motivo in detalle.lower()

    def test_style_demasiado_largo(self):
        assert "largo" in rechaza(f'<p style="color:red;{"margin:0;" * 600}">x</p>')

    def test_el_style_vale_en_cualquier_etiqueta(self):
        for etiqueta in ("p", "span", "h2", "li", "section", "img", "a"):
            estilo("color:red", etiqueta)
        resultado = acepta('<table><tr><td style="text-align:right;color:red">x</td></tr></table>')
        assert 'style="text-align:right;color:red"' in str(resultado.cuerpo)


SANDBOX = (
    "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox "
    "allow-forms allow-presentation"
)
YOUTUBE = (
    '<iframe width="560" height="315" src="https://www.youtube.com/embed/dQw4w9WgXcQ" '
    'title="YouTube video player" frameborder="0" '
    'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; '
    'picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" '
    "allowfullscreen></iframe>"
)
SERVIDORES_INCRUSTABLES = [
    "https://www.youtube.com/embed/x",
    "https://youtube.com/embed/x",
    "https://www.youtube-nocookie.com/embed/x",
    "https://player.vimeo.com/video/76979871?h=8272103f6e",
    "https://view.genially.com/65495004effe9800116a9afa",
    "https://view.genial.ly/65495004effe9800116a9afa",
    "https://www.canva.com/design/DAF/view?embed",
    "https://wordwall.net/embed/abc123?themeId=1",
    "https://www.educaplay.com/game/123-juego.html",
    "https://es.educaplay.com/juego/123-juego.html",
    "https://learningapps.org/watch?v=pabc123",
    "https://www.geogebra.org/material/iframe/id/abc/width/800",
    "https://phet.colorado.edu/sims/html/balloons/latest/balloons_es.html",
]


def iframe(src: str, extra: str = "") -> str:
    return f'<iframe src="{src}" {extra}></iframe>'


def etiqueta_iframe(resultado: filtro.Analisis):
    return resultado.cuerpo.find("iframe")


class TestCoherenciaConLaSkill:
    """La lista blanca y los servicios que promete la skill no pueden separarse."""

    SERVICIOS = {
        "YouTube": "youtube",
        "Vimeo": "vimeo",
        "Genially": "genial",
        "Canva": "canva",
        "Wordwall": "wordwall",
        "Educaplay": "educaplay",
        "LearningApps": "learningapps",
        "GeoGebra": "geogebra",
        "PhET": "phet",
    }

    def _linea_de_iframes(self) -> str:
        from pathlib import Path

        skill = Path(filtro.__file__).parent / "skill" / "tiza" / "SKILL.md"
        (linea,) = [
            fila
            for fila in skill.read_text(encoding="utf-8").splitlines()
            if "**`<iframe>`**" in fila
        ]
        return linea

    def test_cada_servicio_de_la_skill_tiene_servidor(self):
        linea = self._linea_de_iframes()
        for nombre, huella in self.SERVICIOS.items():
            assert nombre in linea
            assert any(huella in s for s in filtro._SERVIDORES_INCRUSTABLES), nombre

    def test_cada_servidor_pertenece_a_un_servicio_de_la_skill(self):
        huellas = self.SERVICIOS.values()
        for servidor in filtro._SERVIDORES_INCRUSTABLES:
            assert any(h in servidor for h in huellas), servidor


class TestIframes:
    @pytest.mark.parametrize("src", SERVIDORES_INCRUSTABLES)
    def test_acepta_los_servidores_de_la_lista(self, src):
        resultado = acepta(iframe(src, 'title="x" allowfullscreen'))
        assert etiqueta_iframe(resultado) is not None
        assert len(resultado.incrustados) == 1

    def test_el_codigo_de_youtube_entra_tal_cual(self):
        resultado = acepta(YOUTUBE)
        etiqueta = etiqueta_iframe(resultado)
        assert etiqueta["width"] == "560"
        assert etiqueta["title"] == "YouTube video player"
        assert etiqueta.has_attr("allowfullscreen")
        assert etiqueta["allow"] == (
            "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; "
            "picture-in-picture; web-share"
        )

    @pytest.mark.parametrize(
        "origen",
        [
            "https://www.youtube.com/embed/x",
            "https://youtube.com/embed/x",
            "https://WWW.YouTube.com/embed/x",
        ],
    )
    def test_youtube_se_publica_sin_cookies(self, origen):
        resultado = acepta(iframe(origen))
        assert etiqueta_iframe(resultado)["src"] == "https://www.youtube-nocookie.com/embed/x"
        assert resultado.incrustados == ["https://www.youtube-nocookie.com/embed/x"]

    def test_cada_iframe_lleva_un_sandbox_fijo_sin_top_navigation(self):
        etiqueta = etiqueta_iframe(acepta(iframe("https://wordwall.net/embed/x")))
        assert etiqueta["sandbox"] == SANDBOX
        assert "top-navigation" not in etiqueta["sandbox"]

    def test_incrustados_en_orden_y_sin_repetir(self):
        resultado = acepta(
            iframe("https://wordwall.net/embed/a")
            + iframe("https://learningapps.org/watch?v=b")
            + iframe("https://wordwall.net/embed/a")
        )
        assert resultado.incrustados == [
            "https://wordwall.net/embed/a",
            "https://learningapps.org/watch?v=b",
        ]
        assert resultado.externos == []

    def test_plantilla_para_genially_canva_y_learningapps(self):
        resultado = acepta(
            '<iframe src="https://view.genially.com/abc" title="Genially" '
            'style="width:100%;aspect-ratio:16/9;border:0" allowfullscreen></iframe>'
        )
        assert etiqueta_iframe(resultado)["style"] == "width:100%;aspect-ratio:16/9;border:0"

    @pytest.mark.parametrize(
        "src",
        [
            "http://www.youtube.com/embed/x",
            "//www.youtube.com/embed/x",
            "https://youtube.com.evil.example/embed/x",
            "https://www.youtube.com.evil.example/embed/x",
            "https://evilyoutube.com/embed/x",
            "https://evil.example/",
            "https://evil.example\\@www.youtube.com/embed/x",
            "https://www.youtube.com\\@evil.example/embed/x",
            "https://usuario@www.youtube.com/embed/x",
            "https://usuario:clave@www.youtube.com/embed/x",
            "https://www.youtube.com:444/embed/x",
            "https://www.youtube.com:443/embed/x",
            "https://www.youtube.com/watch?v=x",
            "https://www.youtube.com/",
            "https://www.youtube.com/embed/x y",
            "https://www.youtube.com/embed/x\x1b",
            "https://www.youtube.com/embed/x&quot;&gt;",
            "https://[::1]/embed/x",
            "https://192.168.0.1/x",
            "https://www.youtube.com./embed/x",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "about:blank",
            "blob:https://www.youtube.com/x",
            "ftp://www.youtube.com/embed/x",
            "",
            "   ",
            "embed/x",
            "/embed/x",
        ],
    )
    def test_rechaza_urls_fuera_de_la_lista(self, src):
        rechaza(iframe(src))

    def test_el_mensaje_nombra_el_servidor(self):
        assert "evil.example" in rechaza(iframe("https://evil.example/x"))
        assert "<iframe>" in rechaza(iframe("https://evil.example/x"))

    def test_sin_src(self):
        assert "src" in rechaza("<iframe></iframe>")

    @pytest.mark.parametrize(
        "atributo",
        [
            'srcdoc="<script>alert(1)</script>"',
            'sandbox="allow-top-navigation"',
            'name="x"',
            'onload="alert(1)"',
            'id="x"',
            'csp="script-src none"',
            'credentialless="true"',
            'allowpaymentrequest="true"',
            'allow="camera"',
            'allow="microphone; autoplay"',
            'allow="geolocation"',
            'allow="autoplay; allow-top-navigation-by-user-activation"',
            'allow="autoplay https://evil.example"',
            'frameborder="9"',
            'scrolling="x"',
            'loading="x"',
            'referrerpolicy="unsafe-url"',
            'width="560em"',
            'height="-5"',
            'class="position-fixed"',
            'style="position:fixed;top:0;left:0;width:100%;height:100%"',
            'allowfullscreen="x"',
        ],
    )
    def test_rechaza_atributos_o_valores_fuera_de_la_lista(self, atributo):
        rechaza(iframe("https://wordwall.net/embed/x", atributo))

    @pytest.mark.parametrize(
        "contenido_interno",
        [
            "<script>alert(1)</script>",
            "texto",
            "<p>x</p>",
            "<iframe src='https://wordwall.net/embed/x'></iframe>",
        ],
    )
    def test_el_iframe_debe_estar_vacio(self, contenido_interno):
        assert "vacío" in rechaza(
            f'<iframe src="https://wordwall.net/embed/x">{contenido_interno}</iframe>'
        )

    def test_un_iframe_con_espacios_dentro_se_publica_vacio(self):
        etiqueta = etiqueta_iframe(
            acepta('<iframe src="https://wordwall.net/embed/x"> \n </iframe>')
        )
        assert etiqueta.contents == []

    def test_los_valores_de_allow_se_normalizan(self):
        etiqueta = etiqueta_iframe(
            acepta(iframe("https://wordwall.net/embed/x", 'allow="  autoplay ;fullscreen;;  "'))
        )
        assert etiqueta["allow"] == "autoplay; fullscreen"

    def test_allowfullscreen_se_normaliza(self):
        for valor in ('allowfullscreen=""', 'allowfullscreen="allowfullscreen"', "allowfullscreen"):
            etiqueta = etiqueta_iframe(acepta(iframe("https://wordwall.net/embed/x", valor)))
            assert etiqueta["allowfullscreen"] == ""


# --------------------------------------------------------------------------- #
# Invariante: lo que se acepta, leído como lo lee un navegador, es la lista blanca
# --------------------------------------------------------------------------- #

ATAQUES = [
    "<!--><script>alert(1)</script>-->",
    "<!---><script>alert(1)</script>-->",
    "<!-- a --!><script>alert(1)</script> -->",
    "<![CDATA[ x ><script>alert(1)</script> ]]>",
    "<? x ><script>alert(1)</script> ?>",
    "<svg><a><animate attributeName='href' values='javascript:alert(1)'/></a></svg>",
    "<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>",
    "<noscript><p title='</noscript><img src=x onerror=alert(1)>'>",
    "<table><td><style></table><img src=x onerror=alert(1)>",
    "<form><math><mtext></form><form><mglyph><style></math><img src onerror=alert(1)>",
    "<select><template><iframe src='https://wordwall.net/embed/x'>",
    "<a href='https://x.org' title='</a><script>alert(1)</script>'>x</a>",
    "<p style='color:red\">'><script>alert(1)</script>",
    "<iframe src='https://wordwall.net/embed/x'><script>alert(1)</script></iframe>",
    "<textarea></textarea><script>alert(1)</script>",
    "<xmp><script>alert(1)</script></xmp>",
    "<plaintext><script>alert(1)</script>",
    "<listing>\n<script>alert(1)</script></listing>",
    "<img src=x onerror=alert(1)>",
    "<b onmouseover=alert(1)>x</b>",
    "<body onload=alert(1)>",
    "<html onclick=alert(1)><p>x",
    "<a href='  javascript:alert(1)'>x</a>",
    "<a href='jav&#x09;ascript:alert(1)'>x</a>",
    "<a href='&#106;avascript:alert(1)'>x</a>",
    "<a href='data:text/html,<script>alert(1)</script>'>x</a>",
    "<img src='data:image/svg+xml;base64,PHN2Zz4='>",
    "<p style='background:url(javascript:alert(1))'>x</p>",
    "<p style='width:expression(alert(1))'>x</p>",
    "<p style='position:fixed;top:0;left:0;width:100%;height:100%'>x</p>",
    "<object data='x'></object><embed src='x'><applet code='x'></applet>",
    "<link rel=stylesheet href=https://evil.example/x.css><style>@import 'x'</style>",
    "<base href='https://evil.example/'><meta http-equiv=refresh content='0;url=https://e/'>",
    "<frameset><frame src='https://evil.example/'></frameset>",
    "<isindex action='javascript:alert(1)'>",
    "<button formaction='javascript:alert(1)'>x</button>",
    "<input autofocus onfocus=alert(1)>",
    "<video><source onerror=alert(1)></video>",
    "<details open ontoggle=alert(1)>x</details>",
]
TROZOS = [
    "<",
    ">",
    '"',
    "'",
    "\n",
    "\n\n",
    "&lt;",
    "&amp;",
    "<!--",
    "-->",
    "--!>",
    "<![CDATA[",
    "]]>",
    "<?",
    "<script>",
    "</script>",
    "<style>",
    "</style>",
    "<svg>",
    "</svg>",
    "<math>",
    "<mtext>",
    "<mglyph>",
    "<table>",
    "<tr>",
    "<td>",
    "</table>",
    "<noscript>",
    "</noscript>",
    "<template>",
    "<select>",
    "<option>",
    "<form>",
    "</form>",
    "<textarea>",
    "</textarea>",
    "<title>",
    "<xmp>",
    "<pre>",
    "</pre>",
    "<p>",
    "</p>",
    "<div>",
    "</div>",
    "<b>",
    "</b>",
    "<a href='https://example.org/'>",
    "</a>",
    "<img src='https://example.org/a.png' alt='",
    "<iframe src='https://wordwall.net/embed/x'>",
    "</iframe>",
    "<span style='color:red'>",
    "<span class='alert'>",
    "<span title='",
    "texto",
    " ",
]


def etiquetas_de(html: str) -> set[str]:
    """Etiquetas que ve un navegador, sin las que construye siempre (html, head, body)."""
    arbol = filtro.BeautifulSoup(html, "html5lib")
    assert not [n for n in arbol.descendants if isinstance(n, filtro.PreformattedString)]
    return {t.name for t in arbol.find_all(True)} - {"html", "head", "body"}


def comprobar_invariante(entrada: str) -> None:
    try:
        analisis = analizar(entrada)
    except HtmlPeligroso:
        return
    publicado = filtro.serializar(analisis.cuerpo)
    # 1) lo publicado solo lleva etiquetas de la lista blanca, sin comentarios ni CDATA
    assert etiquetas_de(publicado) <= filtro.ETIQUETAS_PERMITIDAS, entrada
    # 2) volver a analizarlo (lo que hace el navegador del alumno) no cambia nada; solo se
    #    ignora el espacio en blanco de los extremos, que un navegador descarta al empezar
    segundo = analizar(publicado)
    assert filtro.serializar(segundo.cuerpo).strip() == publicado.strip(), entrada
    assert segundo.incrustados == analisis.incrustados, entrada
    # 3) lo único que sale de la página son los iframes de la lista y los enlaces
    assert all(url.startswith("https://") for url in analisis.incrustados), entrada


class TestSerializacion:
    @pytest.mark.parametrize(
        "entrada",
        [
            "&lt;script&gt;alert(1)&lt;/script&gt;",
            "texto suelto &lt;img src=x onerror=alert(1)&gt;",
            "</noscript><</form>texto",
            "a &amp; b &lt; c",
            "<p>dentro</p>&lt;b&gt;fuera&lt;/b&gt;",
        ],
    )
    def test_el_texto_suelto_sale_escapado(self, entrada):
        publicado = filtro.serializar(analizar(entrada).cuerpo)
        assert "<script" not in publicado and "<img" not in publicado and "<b>" not in publicado
        assert etiquetas_de(publicado) <= {"p"}

    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("<pre>\n\nx</pre>", "<pre>\n\nx</pre>"),  # la segunda línea en blanco se conserva
            ("<pre>\n\n\nx</pre>", "<pre>\n\n\nx</pre>"),
            ("<pre>\nx</pre>", "<pre>x</pre>"),  # el navegador descarta ese primer salto
            ("<pre>x</pre>", "<pre>x</pre>"),
        ],
    )
    def test_pre_se_lee_igual_que_el_arbol(self, entrada, esperado):
        publicado = filtro.serializar(analizar(entrada).cuerpo)
        assert publicado == esperado
        assert filtro.serializar(analizar(publicado).cuerpo) == esperado

    def test_serializar_no_modifica_el_arbol(self):
        analisis = analizar("<pre>\n\nx</pre>")
        assert filtro.serializar(analisis.cuerpo) == filtro.serializar(analisis.cuerpo)

    def test_el_texto_suelto_del_cuerpo_conserva_su_significado(self):
        assert filtro.serializar(analizar("a &lt; b &amp; c").cuerpo) == "a &lt; b &amp; c"


class TestInvariante:
    @pytest.mark.parametrize("ataque", ATAQUES)
    def test_corpus_de_ataques(self, ataque):
        comprobar_invariante(ataque)
        comprobar_invariante(f"<p>antes</p>{ataque}<p>después</p>")
        comprobar_invariante(f"<div>{ataque}</div>")

    def test_ningun_ataque_del_corpus_publica_un_script(self):
        for ataque in ATAQUES:
            try:
                resultado = analizar(ataque)
            except HtmlPeligroso:
                continue
            assert not resultado.cuerpo.find_all(["script", "style", "svg", "math", "form"])

    def test_mezclas_aleatorias_de_trozos(self):
        import random

        azar = random.Random(20261003)
        for _ in range(4000):
            entrada = "".join(azar.choice(TROZOS) for _ in range(azar.randint(1, 12)))
            comprobar_invariante(entrada)
