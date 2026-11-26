"""Aula y publicación de una encuesta anónima (``mod_feedback``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tiza import publicar
from tiza.contenido import Imagen
from tiza.publicar import ErrorPublicacion

AQUI = Path(__file__).parent


class _R:
    def __init__(
        self,
        texto: str = "",
        status_code: int = 200,
        url: str = "https://aula/centro/x.php",
        headers: dict | None = None,
    ) -> None:
        self.text = texto
        self.status_code = status_code
        self.url = url
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        pass

    def close(self) -> None:
        pass


class _SesionEncuesta:
    def __init__(self) -> None:
        self.paginas: dict[str, object] = {}
        self.gets: list[tuple] = []
        self.posts: list[tuple] = []
        self.posts_guion: list[_R] = []

    def respuesta(self, clave: str, valor) -> None:
        self.paginas[clave] = valor

    def get(self, url, params=None, **kwargs):
        self.gets.append((url, params, kwargs))
        if "pluginfile.php" in url and "pluginfile" in self.paginas:
            return self.paginas["pluginfile"]
        for clave, valor in self.paginas.items():
            if clave in url:
                return valor if isinstance(valor, _R) else _R(str(valor))
        return _R("")

    def post(self, url, data=None, **kwargs):
        self.posts.append((url, data))
        if self.posts_guion:
            return self.posts_guion.pop(0)
        return _R("", 303, headers={"Location": "https://aula/centro/mod/feedback/edit.php?id=5"})


def moodle(sesion: _SesionEncuesta) -> publicar.Moodle:
    aula = publicar.Moodle("https://aula/centro", sesion, "clave", pausa=0)
    aula.contexto = lambda curso: 999  # type: ignore[method-assign]
    aula.subir = lambda curso, contexto, ruta, itemid: (itemid, Path(ruta).name)  # type: ignore[method-assign]
    return aula


FORMULARIO_IMPORTAR = """
<html><body>
<form action="https://aula/centro/mod/feedback/import.php" method="post">
<input type="hidden" name="id" value="5">
<input type="hidden" name="sesskey" value="clave">
<input type="hidden" name="_qf__feedback_import_form" value="1">
<input type="hidden" name="choosefile" value="1234">
<select name="deleteolditems">
<option value="1" selected>Borrar ítems antiguos</option>
<option value="">Agregar ítems nuevos</option>
</select>
<input type="submit" name="savechanges" value="Sí">
<input type="submit" name="cancel" value="Cancelar">
</form>
</body></html>
"""

MODOEDIT_SELECT = """
<html><body>
<form action="https://aula/centro/course/modedit.php" method="post">
<input type="hidden" name="name" value="Encuesta">
<input type="hidden" name="instance" value="7">
<select name="multiple_submit">
<option value="0" selected>No</option>
<option value="1">Sí</option>
</select>
<script>var cfg = {"contextid": 1077};</script>
</form>
</body></html>
"""

MODOEDIT_CONGELADO = """
<html><body>
<form action="https://aula/centro/course/modedit.php" method="post">
<input type="hidden" name="name" value="Encuesta">
<input type="hidden" name="instance" value="7">
<input type="hidden" name="multiple_submit" value="1">
<input type="text" name="multiple_submit_static" value="Sí" disabled>
<script>var cfg = {"contextid": 1077};</script>
</form>
</body></html>
"""

EDIT_PHP = r"""
<html><body>
<a href="https://aula/centro/mod/feedback/edit_item.php?id=18">editar</a>
<a href="https://aula/centro/mod/feedback/edit_item.php?id=18">duplicado</a>
<script>{"url":"https:\/\/aula\/centro\/mod\/feedback\/edit_item.php?id=19"}</script>
<a href="/mod/feedback/edit_item.php?id=20">otro</a>
</body></html>
"""

EDIT_ITEM = """
<html><body>
<form action="https://aula/centro/mod/feedback/edit_item.php?id=18" method="post">
<input type="hidden" name="cmid" value="5">
<input type="hidden" name="id" value="18">
<input type="hidden" name="typ" value="label">
<input type="hidden" name="sesskey" value="clave">
<input type="hidden" name="presentation_editor[itemid]" value="777">
<input type="hidden" name="presentation_editor[format]" value="1">
<textarea name="presentation_editor[text]">viejo</textarea>
<input type="submit" name="save_item" value="Guardar cambios">
</form>
</body></html>
"""


class TestImportar:
    def test_sube_el_xml_y_borra_los_items_antiguos(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("mod/feedback/import.php", FORMULARIO_IMPORTAR)
        subidas: list[tuple] = []

        aula = moodle(sesion)
        aula.subir = lambda curso, contexto, ruta, itemid: (  # type: ignore[method-assign]
            subidas.append((Path(ruta).name, Path(ruta).read_bytes(), itemid)) or (itemid, "")
        )
        aula.importar_encuesta(838, 5, b"<FEEDBACK/>")
        assert subidas == [("encuesta.xml", b"<FEEDBACK/>", 1234)]
        _url, datos = sesion.posts[0]
        campos = dict(datos)
        assert campos["deleteolditems"] == "1"
        assert campos["savechanges"] == "Sí"
        assert campos["choosefile"] == "1234"
        assert campos["id"] == "5"

    def test_fuera_de_edit_es_un_error(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("mod/feedback/import.php", FORMULARIO_IMPORTAR)
        sesion.posts_guion = [
            _R("", 303, headers={"Location": "https://aula/centro/login/index.php"})
        ]
        with pytest.raises(ErrorPublicacion) as exc:
            moodle(sesion).importar_encuesta(838, 5, b"<FEEDBACK/>")
        assert exc.value.codigo == "ERROR_IMPORTACION_ENCUESTA"

    def test_sin_formulario_es_un_error(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("mod/feedback/import.php", "<html></html>")
        with pytest.raises(ErrorPublicacion) as exc:
            moodle(sesion).importar_encuesta(838, 5, b"<FEEDBACK/>")
        assert exc.value.codigo == "ERROR_IMPORTACION_ENCUESTA"


class TestExportar:
    def test_lee_las_preguntas_sin_el_texto_crudo(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("mod/feedback/export.php", (AQUI / "encuesta-export.xml").read_text())
        items = moodle(sesion).exportar_encuesta(5)
        assert [item["tipo"] for item in items] == [
            "label",
            "multichoicerated",
            "multichoice",
            "multichoice",
            "multichoice",
            "textfield",
            "textarea",
            "numeric",
        ]
        escala = items[1]
        assert escala["texto"] == "Escala"
        assert escala["etiqueta"] == "escala"
        assert escala["presentacion"] == (
            "r>>>>>1####Muy mal|2####Mal|3####Normal|4####Bien|5####Muy bien<<<<<1"
        )
        assert escala["opciones"] == "h"
        assert escala["obligatoria"] is True
        assert items[0]["presentacion"] == (
            '<p>Con imagen: <img src="@@PLUGINFILE@@/punto.png" alt="Un punto"></p>'
        )

    def test_un_xml_roto_es_un_error(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("mod/feedback/export.php", "<FEEDBACK><ITEMS>")
        with pytest.raises(ErrorPublicacion) as exc:
            moodle(sesion).exportar_encuesta(5)
        assert exc.value.codigo == "ERROR_EXPORTACION_ENCUESTA"


class TestExportacionHostil:
    @pytest.mark.parametrize(
        "cabecera",
        [
            '<!DOCTYPE FEEDBACK [<!ENTITY a "aaaa">]>',
            "<!doctype FEEDBACK>",
            '<!DOCTYPE FEEDBACK SYSTEM "http://fuera/x.dtd">',
        ],
    )
    def test_un_doctype_o_entidades_son_un_error(self, cabecera):
        sesion = _SesionEncuesta()
        sesion.respuesta(
            "mod/feedback/export.php",
            '<?xml version="1.0"?>' + cabecera + '<FEEDBACK VERSION="200701"><ITEMS>'
            '<ITEM TYPE="textarea" REQUIRED="0"><ITEMTEXT>&a;</ITEMTEXT></ITEM>'
            "</ITEMS></FEEDBACK>",
        )
        with pytest.raises(ErrorPublicacion) as exc:
            moodle(sesion).exportar_encuesta(5)
        assert exc.value.codigo == "ERROR_EXPORTACION_ENCUESTA"


class TestRespuestas:
    def test_un_select_es_sin_respuestas(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("modedit.php", MODOEDIT_SELECT)
        assert moodle(sesion).encuesta_tiene_respuestas(5) is False
        assert all("view.php" not in url for url, _params, _kw in sesion.gets)
        assert all("show_entries" not in url for url, _params, _kw in sesion.gets)
        assert all("analysis" not in url for url, _params, _kw in sesion.gets)

    def test_el_hidden_con_el_estatico_deshabilitado_es_con_respuestas(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("modedit.php", MODOEDIT_CONGELADO)
        assert moodle(sesion).encuesta_tiene_respuestas(5) is True

    def test_cualquier_otra_forma_se_trata_como_con_respuestas(self):
        sesion = _SesionEncuesta()
        sesion.respuesta(
            "modedit.php",
            '<form action="modedit.php"><input type="text" name="multiple_submit" value="0"></form>',
        )
        assert moodle(sesion).encuesta_tiene_respuestas(5) is True

    def test_un_error_de_lectura_se_trata_como_con_respuestas(self):
        class SesionRota(_SesionEncuesta):
            def get(self, url, params=None, **kwargs):
                raise publicar.requests.RequestException("sin red")

        assert moodle(SesionRota()).encuesta_tiene_respuestas(5) is True

    def test_leer_modulo_dice_la_forma_y_el_valor(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("modedit.php", MODOEDIT_CONGELADO)
        info = moodle(sesion).leer_modulo(5)
        assert info["multiple_submit"] == {"forma": "congelado", "valor": "1"}
        assert info["anonymous"] is None  # este formulario de prueba no lo trae


class TestItems:
    def test_los_ids_salen_de_edit_en_orden_y_sin_repetir(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("mod/feedback/edit.php", EDIT_PHP)
        assert moodle(sesion).items_de_encuesta(5) == [18, 19, 20]
        assert all("view.php" not in url for url, _params, _kw in sesion.gets)

    def test_sin_ids_es_un_error(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("mod/feedback/edit.php", "<html></html>")
        with pytest.raises(ErrorPublicacion) as exc:
            moodle(sesion).items_de_encuesta(5)
        assert exc.value.codigo == "ERROR_ENCUESTA_ITEMS"


class TestImagenDeEtiqueta:
    def _aula(self, sesion):
        sesion.respuesta("modedit.php", MODOEDIT_SELECT)
        sesion.respuesta("mod/feedback/edit_item.php", EDIT_ITEM)
        aula = moodle(sesion)
        subidas: list[tuple] = []
        aula.subir = lambda curso, contexto, ruta, itemid: (  # type: ignore[method-assign]
            subidas.append((Path(ruta).name, Path(ruta).read_bytes(), itemid)) or (itemid, "")
        )
        return aula, subidas

    def test_sube_las_imagenes_y_guarda_el_html(self):
        sesion = _SesionEncuesta()
        aula, subidas = self._aula(sesion)
        imagen = Imagen(nombre="img-abc.png", mime="image/png", datos=b"png")
        aula.imagen_de_etiqueta(838, 5, 18, "<p>Con imagen <img></p>", [imagen])
        assert subidas == [("img-abc.png", b"png", 777)]
        _url, datos = sesion.posts[0]
        campos = dict(datos)
        assert campos["presentation_editor[text]"] == "<p>Con imagen <img></p>"
        assert campos["presentation_editor[format]"] == "1"
        assert campos["save_item"] == "Guardar cambios"
        assert "typ=" not in _url
        assert all("typ=" not in url for url, _params, _kw in sesion.gets)

    def test_sin_formulario_es_un_error(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("modedit.php", MODOEDIT_SELECT)
        sesion.respuesta("mod/feedback/edit_item.php", "<html></html>")
        with pytest.raises(ErrorPublicacion) as exc:
            moodle(sesion).imagen_de_etiqueta(
                838, 5, 18, "<p>x</p>", [Imagen(nombre="a.png", mime="image/png", datos=b"x")]
            )
        assert exc.value.codigo == "ERROR_ENCUESTA_IMAGEN"

    def test_si_la_imagen_no_se_sirve_es_un_error(self):
        sesion = _SesionEncuesta()
        aula, _subidas = self._aula(sesion)
        sesion.respuesta("pluginfile", _R("", 404))
        with pytest.raises(ErrorPublicacion) as exc:
            aula.imagen_de_etiqueta(
                838, 5, 18, "<p>x</p>", [Imagen(nombre="a.png", mime="image/png", datos=b"x")]
            )
        assert exc.value.codigo == "VERIFICACION_IMAGENES"


# --------------------------------------------------------------------------- #
# Publicación con el doble del aula
# --------------------------------------------------------------------------- #

from dobles import MoodleFalso, estructura_de  # noqa: E402
from tiza import contenido  # noqa: E402

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

PREGUNTAS = """\
- tipo: escala
  enunciado: ¿Cómo te has sentido?
  opciones: [Muy mal, Mal, Normal, Bien, Muy bien]
- tipo: texto
  enunciado: ¿Qué te ha gustado?
"""


def encuesta(tmp_path, preguntas: str = PREGUNTAS, **campos) -> contenido.Documento:
    extra = "".join(f"{clave}: {valor}\n" for clave, valor in campos.items())
    ruta = tmp_path / "encuesta.md"
    ruta.write_text(
        "---\ntipo: encuesta\nnombre: Puerta de la felicidad\nseccion: 3\n"
        f"{extra}preguntas:\n{preguntas}---\n\nCuéntanos cómo ha ido.\n",
        encoding="utf-8",
        newline="\n",
    )
    return contenido.cargar(ruta, raiz=tmp_path)


def publicar_doc(moodle, doc):
    return publicar.publicar_documento(
        moodle, 1234, estructura_de(moodle.secciones), doc, visible=None
    )


class TestPublicarEncuesta:
    def test_crea_la_encuesta_anonima_y_la_verifica(self, tmp_path):
        moodle = MoodleFalso()
        resultado = publicar_doc(moodle, encuesta(tmp_path))
        assert (resultado.tipo, resultado.accion, resultado.oculto) == (
            "encuesta",
            "creada",
            True,
        )
        crear = next(llamada for llamada in moodle.llamadas if llamada[0] == "crear")
        assert crear[3] == "encuesta"
        assert crear[4]["anonymous"] == "1"
        assert crear[4]["multiple_submit"] == "0"
        assert crear[4]["_qf__mod_feedback_mod_form"] == "1"
        assert len(moodle.importados_encuesta) == 1
        assert len(moodle.encuestas[resultado.cmid]) == 2

    def test_republicar_sin_cambiar_las_preguntas_no_reimporta(self, tmp_path):
        moodle = MoodleFalso()
        doc = encuesta(tmp_path)
        primero = publicar_doc(moodle, doc)
        segundo = publicar_doc(moodle, doc)
        assert (primero.cmid, segundo.cmid) == (100, 100)
        assert segundo.accion == "actualizada"
        assert len(moodle.importados_encuesta) == 1

    def test_cambiar_una_pregunta_sin_respuestas_la_reimporta(self, tmp_path):
        moodle = MoodleFalso()
        publicar_doc(moodle, encuesta(tmp_path))
        cambiada = encuesta(
            tmp_path, PREGUNTAS.replace("¿Qué te ha gustado?", "¿Qué harías distinto?")
        )
        resultado = publicar_doc(moodle, cambiada)
        assert resultado.accion == "actualizada"
        assert len(moodle.importados_encuesta) == 2
        assert "¿Qué harías distinto?" in [
            item["texto"] for item in moodle.encuestas[resultado.cmid]
        ]

    def test_cambiar_una_pregunta_con_respuestas_no_toca_nada(self, tmp_path):
        moodle = MoodleFalso()
        primero = publicar_doc(moodle, encuesta(tmp_path))
        moodle.respuestas_encuesta[primero.cmid] = True
        cambiada = encuesta(
            tmp_path, PREGUNTAS.replace("¿Qué te ha gustado?", "¿Qué harías distinto?")
        )
        actualizaciones = len([l for l in moodle.llamadas if l[0] == "actualizar"])
        with pytest.raises(ErrorPublicacion) as exc:
            publicar_doc(moodle, cambiada)
        assert exc.value.codigo == "ENCUESTA_CON_RESPUESTAS"
        assert "No se ha tocado nada" in exc.value.detalle
        assert len(moodle.importados_encuesta) == 1
        assert len([l for l in moodle.llamadas if l[0] == "actualizar"]) == actualizaciones

    def test_los_ajustes_si_se_cambian_con_respuestas(self, tmp_path):
        moodle = MoodleFalso()
        primero = publicar_doc(moodle, encuesta(tmp_path))
        moodle.respuestas_encuesta[primero.cmid] = True
        cambiada = encuesta(
            tmp_path, mensaje_final="¡Gracias!", cierra="2026-12-20", respuestas="una"
        )
        resultado = publicar_doc(moodle, cambiada)
        assert resultado.accion == "actualizada"
        assert len(moodle.importados_encuesta) == 1
        assert moodle.formularios[primero.cmid]["name"] == "Puerta de la felicidad"
        assert "¡Gracias!" in moodle.formularios[primero.cmid]["page_after_submit_editor[text]"]

    def test_cambiar_las_respuestas_con_respuestas_no_toca_nada(self, tmp_path):
        moodle = MoodleFalso()
        primero = publicar_doc(moodle, encuesta(tmp_path))
        moodle.respuestas_encuesta[primero.cmid] = True
        with pytest.raises(ErrorPublicacion) as exc:
            publicar_doc(moodle, encuesta(tmp_path, respuestas="varias"))
        assert exc.value.codigo == "ENCUESTA_CON_RESPUESTAS"
        assert len(moodle.importados_encuesta) == 1

    def test_cambiar_las_respuestas_sin_respuestas_se_publica(self, tmp_path):
        moodle = MoodleFalso()
        publicar_doc(moodle, encuesta(tmp_path))
        publicar_doc(moodle, encuesta(tmp_path, respuestas="varias"))
        assert moodle.varias_encuesta[100] == "1"
        assert len(moodle.importados_encuesta) == 1

    def test_si_no_se_puede_saber_si_hay_respuestas_se_trata_como_que_las_hay(self, tmp_path):
        class MoodleDudoso(MoodleFalso):
            def leer_modulo(self, cmid):
                info = super().leer_modulo(cmid)
                info["multiple_submit"] = {"forma": "desconocida", "valor": None}
                return info

        moodle = MoodleDudoso()
        publicar_doc(moodle, encuesta(tmp_path))
        cambiada = encuesta(
            tmp_path, PREGUNTAS.replace("¿Qué te ha gustado?", "¿Qué harías distinto?")
        )
        with pytest.raises(ErrorPublicacion) as exc:
            publicar_doc(moodle, cambiada)
        assert exc.value.codigo == "ENCUESTA_CON_RESPUESTAS"

    def test_una_etiqueta_con_imagen_sube_la_imagen(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "punto.png").write_bytes(_PNG)
        preguntas = '- tipo: informacion\n  texto: "![Un punto](img/punto.png)"\n'
        moodle = MoodleFalso()
        resultado = publicar_doc(moodle, encuesta(tmp_path, preguntas))
        llamada = next(l for l in moodle.llamadas if l[0] == "imagen_de_etiqueta")
        assert llamada[2] == moodle.items_encuesta[resultado.cmid][0]
        assert "@@PLUGINFILE@@/" in llamada[3]
        assert llamada[4] and llamada[4][0].startswith("img-")
        assert "@@PLUGINFILE@@" in moodle.encuestas[resultado.cmid][0]["presentacion"]

    def test_si_la_verificacion_falla_una_encuesta_nueva_se_borra(self, tmp_path):
        class MoodleQueMiente(MoodleFalso):
            def exportar_encuesta(self, cmid):
                items = super().exportar_encuesta(cmid)
                if items:
                    items[0] = {**items[0], "texto": "otra cosa"}
                return items

        moodle = MoodleQueMiente()
        with pytest.raises(ErrorPublicacion) as exc:
            publicar_doc(moodle, encuesta(tmp_path))
        assert exc.value.codigo == "VERIFICACION_ENCUESTA"
        assert any(llamada[0] == "borrar" for llamada in moodle.llamadas)

    def test_solo_fechas_cambia_las_fechas_sin_reimportar(self, tmp_path):
        moodle = MoodleFalso()
        doc = encuesta(tmp_path, abre="2026-11-27", cierra="2026-12-20")
        publicar_doc(moodle, doc)
        cambiado = encuesta(tmp_path, abre="2026-11-28", cierra="2026-12-21")
        resultado = publicar.publicar_fechas(moodle, estructura_de(moodle.secciones), cambiado)
        assert resultado.accion == "actualizada"
        assert len(moodle.importados_encuesta) == 1
        _url, datos = next(l for l in moodle.llamadas if l[0] == "actualizar")[1:]
        assert datos["timeopen[day]"] == "28"
        assert datos["timeclose[day]"] == "21"


class TestRespuestasJustoAntesDeImportar:
    def test_una_respuesta_que_llega_tras_leer_el_formulario_para_la_importacion(self, tmp_path):
        class MoodleConRespuestaTardia(MoodleFalso):
            def encuesta_tiene_respuestas(self, cmid):
                super().encuesta_tiene_respuestas(cmid)
                return True  # un alumno envía después de que se leyera el formulario

        moodle = MoodleConRespuestaTardia()
        publicar_doc(moodle, encuesta(tmp_path))
        cambiada = encuesta(
            tmp_path, PREGUNTAS.replace("¿Qué te ha gustado?", "¿Qué harías distinto?")
        )
        with pytest.raises(ErrorPublicacion) as exc:
            publicar_doc(moodle, cambiada)
        assert exc.value.codigo == "ENCUESTA_CON_RESPUESTAS"
        assert len(moodle.importados_encuesta) == 1

    def test_la_comprobacion_va_justo_antes_de_importar(self, tmp_path):
        moodle = MoodleFalso()
        publicar_doc(moodle, encuesta(tmp_path))
        moodle.llamadas.clear()
        cambiada = encuesta(
            tmp_path, PREGUNTAS.replace("¿Qué te ha gustado?", "¿Qué harías distinto?")
        )
        publicar_doc(moodle, cambiada)
        nombres = [llamada[0] for llamada in moodle.llamadas]
        importar = nombres.index("importar_encuesta")
        assert nombres[importar - 1] == "encuesta_tiene_respuestas"


class TestImagenRotaAlRepublicar:
    def _publicada(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "punto.png").write_bytes(_PNG)
        preguntas = '- tipo: informacion\n  texto: "![Un punto](img/punto.png)"\n' + PREGUNTAS
        moodle = MoodleFalso()
        doc = encuesta(tmp_path, preguntas)
        resultado = publicar_doc(moodle, doc)
        return moodle, doc, resultado.cmid

    def test_una_imagen_que_no_se_sirve_se_vuelve_a_subir_sin_reimportar(self, tmp_path):
        moodle, doc, cmid = self._publicada(tmp_path)
        etiqueta = moodle.items_encuesta[cmid][0]
        moodle.imagenes_encuesta.pop(etiqueta)  # la subida falló la vez anterior
        moodle.llamadas.clear()
        publicar_doc(moodle, doc)
        assert [l for l in moodle.llamadas if l[0] == "imagen_de_etiqueta"][0][2] == etiqueta
        assert len(moodle.importados_encuesta) == 1

    def test_una_imagen_que_se_sirve_no_se_vuelve_a_subir(self, tmp_path):
        moodle, doc, _cmid = self._publicada(tmp_path)
        moodle.llamadas.clear()
        publicar_doc(moodle, doc)
        assert not [l for l in moodle.llamadas if l[0] == "imagen_de_etiqueta"]
        assert len(moodle.importados_encuesta) == 1

    def test_tambien_con_respuestas_porque_una_etiqueta_no_tiene_respuestas(self, tmp_path):
        moodle, doc, cmid = self._publicada(tmp_path)
        etiqueta = moodle.items_encuesta[cmid][0]
        moodle.imagenes_encuesta.pop(etiqueta)
        moodle.respuestas_encuesta[cmid] = True
        publicar_doc(moodle, doc)
        assert moodle.imagenes_encuesta[etiqueta]
        assert moodle.respuestas_encuesta[cmid] is True


class TestImagenesServidas:
    def test_mira_cada_imagen_en_el_area_del_item(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("modedit.php", MODOEDIT_SELECT)
        sesion.respuesta("pluginfile", _R("png", 200))
        imagen = Imagen(nombre="img-abc.png", mime="image/png", datos=b"png")
        aula = moodle(sesion)
        aula.comprobar_pluginfile = lambda url: (  # type: ignore[method-assign]
            sesion.gets.append((url, None, {})) or True
        )
        assert aula.imagenes_de_etiqueta_servidas(5, 18, [imagen]) is True
        assert any(url.endswith("/mod_feedback/item/18/img-abc.png") for url, _p, _k in sesion.gets)

    def test_una_que_falta_es_false(self):
        sesion = _SesionEncuesta()
        sesion.respuesta("modedit.php", MODOEDIT_SELECT)
        aula = moodle(sesion)
        aula.comprobar_pluginfile = lambda url: False  # type: ignore[method-assign]
        imagen = Imagen(nombre="img-abc.png", mime="image/png", datos=b"png")
        assert aula.imagenes_de_etiqueta_servidas(5, 18, [imagen]) is False


class TestValorCongeladoDesconocido:
    @pytest.mark.parametrize("valor", [None, "", "2"])
    def test_con_respuestas_y_sin_saber_el_valor_no_toca_nada(self, tmp_path, valor):
        class MoodleSinValor(MoodleFalso):
            def leer_modulo(self, cmid):
                info = super().leer_modulo(cmid)
                if self.respuestas_encuesta.get(cmid):
                    info["multiple_submit"] = {"forma": "congelado", "valor": valor}
                return info

        moodle = MoodleSinValor()
        primero = publicar_doc(moodle, encuesta(tmp_path))
        moodle.respuestas_encuesta[primero.cmid] = True
        actualizaciones = len([l for l in moodle.llamadas if l[0] == "actualizar"])
        with pytest.raises(ErrorPublicacion) as exc:
            publicar_doc(moodle, encuesta(tmp_path, mensaje_final="¡Gracias!"))
        assert exc.value.codigo == "ENCUESTA_CON_RESPUESTAS"
        assert "No se ha tocado nada" in exc.value.detalle
        assert len([l for l in moodle.llamadas if l[0] == "actualizar"]) == actualizaciones
