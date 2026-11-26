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
