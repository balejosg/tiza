"""Tests del texto llano que ve el docente (``tiza.mensajes``), sin terminal ni ventana."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dobles import avisos_de_ejemplo
from tiza import ayuda, informe, mensajes, publicacion
from tiza.tipos import FechaActividad


def _doc(**cambios):
    datos = {
        "fichero": "t.md",
        "tipo": "tarea",
        "nombre": "Problemas",
        "seccion": "Fracciones",
        "fechas": None,
        "vista_previa": None,
        "enlaces_externos": (),
        "incrustados": (),
        "recursos": (),
    }
    datos.update(cambios)
    return publicacion.DocumentoResumen(**datos)


def _resumen(doc=None, **cambios):
    datos = {
        "curso": 5678,
        "nombre_curso": "Matemáticas 2ºB",
        "documentos": (doc or _doc(),),
        "secciones_nuevas": (),
        "visible": None,
    }
    datos.update(cambios)
    return publicacion.ResumenPublicacion(**datos)


class TestTexto:
    def test_texto_seguro_quita_escapes_y_controles_bidi(self):
        sucio = (
            "Tema\x1b[2K\x9b8m\N{RIGHT-TO-LEFT OVERRIDE}oculto\u061c\N{LEFT-TO-RIGHT ISOLATE}\x00"
        )
        limpio = mensajes.texto_seguro(sucio)
        for caracter in (
            "\x1b",
            "\x9b",
            "\N{RIGHT-TO-LEFT OVERRIDE}",
            "\u061c",
            "\N{LEFT-TO-RIGHT ISOLATE}",
            "\x00",
        ):
            assert caracter not in limpio
        assert limpio.startswith("Tema")

    def test_texto_seguro_recorta(self):
        assert mensajes.texto_seguro("x" * 500, maximo=10) == "x" * 9 + "…"

    def test_texto_seguro_con_maximo_no_positivo_devuelve_vacio(self):
        assert mensajes.texto_seguro("abc", maximo=0) == ""
        assert mensajes.texto_seguro("abc", maximo=-5) == ""

    def test_texto_seguro_no_trunca_si_cabe_justo(self):
        assert mensajes.texto_seguro("abc", maximo=3) == "abc"

    def test_texto_seguro_conserva_acentos(self):
        assert mensajes.texto_seguro("Matemáticas 2ºB «ñ»") == "Matemáticas 2ºB «ñ»"


def test_describir_curso_sin_nombre():
    assert mensajes.describir_curso(5678, None) == "id 5678"


def test_describir_curso_sanea_el_nombre_de_moodle():
    assert mensajes.describir_curso(5678, "Mates\x1b[2K") == "«Mates[2K» (id 5678)"
    assert "\x1b" not in mensajes.describir_curso(5678, "Mates\x1b[2K")


def test_nombre_llano_de_un_tipo_conocido():
    assert mensajes.nombre_llano("h5p") == "Contenido interactivo (H5P)"
    assert mensajes.nombre_llano("pagina") == "Página"


def test_nombre_llano_de_un_tipo_ajeno_se_queda_crudo():
    assert mensajes.nombre_llano("foro") == "foro"


def test_para_que_son_las_dos_preguntas():
    assert set(mensajes.PARA_QUE) == {"pruebas", "real"}


def test_la_visibilidad_tiene_los_tres_estados():
    assert set(mensajes.VISIBILIDAD) == {True, False, None}


@pytest.mark.parametrize("motivo", ["aula", "caducada", "desactualizada", "docente"])
def test_texto_cierre_de_cada_motivo(motivo):
    assert mensajes.texto_cierre(motivo)


class TestCambiosDeFecha:
    def doc(self, **cambios):
        return publicacion.DocumentoResumen("t.md", "tarea", "Problemas", 3, None, **cambios)

    def test_una_linea_por_fecha_segun_su_estado(self):
        cambios = (
            publicacion.CambioFecha("apertura", (2026, 10, 1, 0, 0), (2026, 10, 1, 0, 0), "igual"),
            publicacion.CambioFecha(
                "entrega",
                (2026, 10, 10, 23, 59),
                (2026, 10, 12, 23, 59),
                "cambia",
                ("FECHA_FESTIVA",),
            ),
            publicacion.CambioFecha("límite", None, (2026, 10, 15, 23, 59), "nueva"),
        )
        assert mensajes.describir_cambios(self.doc(cambios=cambios)) == [
            "apertura 01/10/2026 00:00 (sin cambios)",
            "entrega antes 10/10/2026 23:59 → ahora 12/10/2026 23:59 — festivo",
            "límite 15/10/2026 23:59 (la actividad es nueva)",
        ]

    def test_si_no_se_pudo_leer_el_aula_se_dice(self):
        cambio = publicacion.CambioFecha("entrega", None, (2026, 10, 12, 23, 59), "desconocida")
        assert mensajes.describir_cambios(self.doc(cambios=(cambio,))) == [
            "entrega: no se pudieron leer las fechas actuales del aula; "
            "se publicaría 12/10/2026 23:59"
        ]

    def test_sin_cambios_calculados_no_hay_lineas(self):
        assert mensajes.describir_cambios(self.doc()) == []

    def test_con_cambios_la_descripcion_no_repite_las_fechas(self):
        fechas = (
            FechaActividad("apertura", datetime(2026, 10, 1, 0, 0), "allowsubmissionsfromdate"),
            FechaActividad("entrega", datetime(2026, 10, 12, 23, 59), "duedate"),
        )
        sin_cambios = publicacion.DocumentoResumen("t.md", "tarea", "P", 3, fechas)
        con_cambios = publicacion.DocumentoResumen("t.md", "tarea", "P", 3, fechas, cambios=())
        assert "entrega 12/10/2026 23:59" in mensajes.describir_documento(sin_cambios)
        assert "entrega" not in mensajes.describir_documento(con_cambios)

    def test_la_descripcion_ensena_las_fechas_del_cuestionario(self):
        # Regresión del issue #4: las fechas del cuestionario no las enseñaba nadie.
        fechas = (
            FechaActividad("apertura", datetime(2026, 10, 20, 8, 0), "timeopen"),
            FechaActividad("cierre", datetime(2026, 10, 27, 23, 59), "timeclose", True),
        )
        doc = publicacion.DocumentoResumen("c.md", "cuestionario", "C", 3, fechas)
        texto = mensajes.describir_documento(doc)
        assert "apertura 20/10/2026 08:00" in texto
        assert "cierre 27/10/2026 23:59" in texto

    def test_el_recordatorio_de_calificacion_que_se_quita_se_ensena(self):
        cambio = publicacion.CambioFecha(
            publicacion.CAMPO_RECORDATORIO, (2026, 10, 20, 0, 0), None, "cambia"
        )
        assert mensajes.describir_cambios(self.doc(cambios=(cambio,))) == [
            "recordatorio de calificación antes 20/10/2026 00:00 → ahora sin fecha"
        ]

    @pytest.mark.parametrize(
        ("estado", "recuerda"),
        [("cambia", True), ("desconocida", True), ("igual", False), ("nueva", False)],
    )
    def test_las_excepciones_se_recuerdan_si_la_fecha_cambia_o_no_se_sabe(self, estado, recuerda):
        cambio = publicacion.CambioFecha(
            "entrega", (2026, 10, 10, 23, 59), (2026, 10, 12, 23, 59), estado
        )
        resumen = publicacion.ResumenPublicacion(
            5678, None, (self.doc(cambios=(cambio,)),), (), None, solo_fechas=True
        )
        assert mensajes.cambian_fechas(resumen) is recuerda

    def test_el_recordatorio_por_si_solo_no_obliga_a_recordar_las_excepciones(self):
        recordatorio = publicacion.CambioFecha(
            publicacion.CAMPO_RECORDATORIO, (2026, 10, 20, 0, 0), None, "cambia"
        )
        entrega = publicacion.CambioFecha(
            "entrega", (2026, 10, 10, 23, 59), (2026, 10, 12, 23, 59), "cambia"
        )
        solo = publicacion.ResumenPublicacion(
            5678, None, (self.doc(cambios=(recordatorio,)),), (), None, solo_fechas=True
        )
        con_entrega = publicacion.ResumenPublicacion(
            5678, None, (self.doc(cambios=(recordatorio, entrega)),), (), None, solo_fechas=True
        )
        assert mensajes.cambian_fechas(solo) is False
        assert mensajes.cambian_fechas(con_entrega) is True


class TestAvisos:
    def test_el_ejemplo_cubre_todos_los_avisos(self):
        assert set(avisos_de_ejemplo()) == set(publicacion.AVISOS)

    @pytest.mark.parametrize("codigo", sorted(publicacion.AVISOS))
    def test_todos_los_avisos_tienen_constructor_tipado(self, codigo):
        assert callable(getattr(publicacion.Aviso, codigo.lower()))

    @pytest.mark.parametrize("codigo", sorted(publicacion.AVISOS))
    def test_todos_los_avisos_se_convierten_en_texto(self, codigo):
        lineas = mensajes.lineas_de_aviso(avisos_de_ejemplo()[codigo])
        assert lineas
        assert all(isinstance(linea, mensajes.Linea) for linea in lineas)

    def test_creando_seccion_sale_saneada(self):
        lineas = mensajes.lineas_de_aviso(publicacion.Aviso.creando_seccion("Tema\x1b\u202e"))
        assert [linea.texto for linea in lineas] == ["Creando la sección «Tema» (oculta)..."]
        assert not lineas[0].error

    def test_fallo_lleva_codigo_y_que_hacer_a_stderr(self):
        lineas = mensajes.lineas_de_aviso(publicacion.Aviso.fallo("LOGIN_FALLIDO", ""))
        assert lineas[0].texto == "ERROR [LOGIN_FALLIDO]"
        assert lineas[1].texto == "Qué hacer: " + str(ayuda.explicar("LOGIN_FALLIDO"))
        assert all(linea.error for linea in lineas)

    def test_error_interno_cuenta_el_tipo_y_que_hacer(self):
        lineas = mensajes.lineas_de_aviso(publicacion.Aviso.error_interno("RuntimeError"))
        assert "ERROR [ERROR_INTERNO]" in lineas[0].texto
        assert "RuntimeError" in lineas[0].texto
        assert lineas[1].texto.startswith("Qué hacer: ")

    def test_publicando_en_pruebas_usa_el_nombre_llano_del_tipo(self):
        aviso = publicacion.Aviso.publicando_en_pruebas((_doc(tipo="h5p", nombre="Repaso H5P"),))
        lineas = mensajes.lineas_de_aviso(aviso)
        assert lineas[0].texto == "El agente pide publicar en pruebas:"
        assert (
            lineas[1].texto == "- Contenido interactivo (H5P) «Repaso H5P» → sección «Fracciones»"
        )

    def test_sesion_abierta_lleva_la_hora_completa(self):
        caduca = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
        lineas = mensajes.lineas_de_aviso(publicacion.Aviso.sesion_abierta(caduca))
        assert lineas[0].texto.startswith("Sesión abierta hasta el ")
        assert caduca.astimezone().strftime("%d/%m/%Y %H:%M") in lineas[0].texto

    def test_sesion_cerrada_usa_el_texto_unico(self):
        lineas = mensajes.lineas_de_aviso(publicacion.Aviso.sesion_cerrada("caducada"))
        assert [linea.texto for linea in lineas] == [mensajes.texto_cierre("caducada")]
        assert "La sesión ha caducado; se cierra." in lineas[0].texto

    def test_resultado_reutiliza_el_resumen_del_informe(self):
        documento = informe.crear("publicar", "ok", [], [], [], "pruebas", 1234)
        lineas = mensajes.lineas_de_aviso(publicacion.Aviso.resultado(documento))
        assert lineas[0].texto == "Informe: ok (publicar)"

    def test_lineas_de_error_sin_texto_de_ayuda_es_solo_el_codigo(self):
        lineas = mensajes.lineas_de_error("CODIGO_DESCONOCIDO")
        assert [linea.texto for linea in lineas] == ["ERROR [CODIGO_DESCONOCIDO]"]


class TestDetalleReal:
    def test_compone_encabezado_documentos_y_cierre(self):
        cambio = publicacion.CambioFecha(
            "entrega",
            (2026, 10, 10, 23, 59),
            (2026, 10, 12, 23, 59),
            "cambia",
            ("FECHA_FESTIVA",),
        )
        doc = _doc(
            enlaces_externos=("https://ejemplo.org/x",),
            incrustados=("https://www.youtube-nocookie.com/embed/a",),
            recursos=("img/foto.png",),
            itinerario=("Se completa al: entregarla",),
            h5p="Rellenar huecos",
            h5p_libreria="H5P.Blanks 1.14",
            h5p_descartadas=("FontAwesome-4.5",),
            cambios=(cambio,),
        )
        detalle = mensajes.detalle_real(_resumen(doc))
        assert detalle.curso == "«Matemáticas 2ºB» (id 5678)"
        assert (
            detalle.encabezado == "Se va a publicar en el curso REAL «Matemáticas 2ºB» (id 5678):"
        )
        assert detalle.aviso_calendario is None
        [documento] = detalle.documentos
        assert documento.titulo == "Tarea «Problemas» → sección «Fracciones»"
        assert documento.lineas == (
            "fichero t.md, verificado en pruebas",
            "entrega antes 10/10/2026 23:59 → ahora 12/10/2026 23:59 — festivo",
            "Se completa al: entregarla",
            "actividad H5P: Rellenar huecos",
            "paquete H5P: H5P.Blanks 1.14",
            "no se sube la librería FontAwesome-4.5",
            "enlace externo: https://ejemplo.org/x",
            "incrusta: https://www.youtube-nocookie.com/embed/a",
            "se sube el fichero img/foto.png",
        )
        assert documento.vista_previa is None
        assert detalle.finales == (mensajes.EXCEPCIONES_TEXTO, mensajes.VISIBILIDAD[None])

    def test_con_solo_fechas_oculta_el_contenido(self):
        cambio = publicacion.CambioFecha(
            "entrega", (2026, 10, 10, 23, 59), (2026, 10, 12, 23, 59), "cambia"
        )
        doc = _doc(
            enlaces_externos=("https://ejemplo.org/x",),
            recursos=("img/foto.png",),
            cambios=(cambio,),
        )
        detalle = mensajes.detalle_real(_resumen(doc, solo_fechas=True))
        assert detalle.solo_fechas is True
        assert (
            detalle.encabezado
            == "Se van a cambiar solo las fechas en el curso REAL «Matemáticas 2ºB» (id 5678):"
        )
        [documento] = detalle.documentos
        assert documento.lineas == (
            "fichero t.md",
            "entrega antes 10/10/2026 23:59 → ahora 12/10/2026 23:59",
        )
        assert detalle.finales == (mensajes.EXCEPCIONES_TEXTO, mensajes.SOLO_FECHAS_TEXTO)
        assert "https://ejemplo.org/x" not in " ".join(documento.lineas)
        assert "img/foto.png" not in " ".join(documento.lineas)

    def test_con_aviso_de_calendario_lo_explica(self):
        detalle = mensajes.detalle_real(_resumen(aviso_calendario="CALENDARIO_INVALIDO"))
        assert detalle.aviso_calendario == (
            "AVISO: calendario.toml no se puede usar. " + str(ayuda.explicar("CALENDARIO_INVALIDO"))
        )

    def test_con_secciones_nuevas_y_varios_cursos_lleva_la_posicion(self):
        detalle = mensajes.detalle_real(
            _resumen(secciones_nuevas=("Fracciones",), posicion=2, total=3)
        )
        assert (detalle.posicion, detalle.total) == (2, 3)
        assert "Se creará la sección «Fracciones» (oculta)." in detalle.finales

    def test_la_vista_previa_viaja_en_el_documento(self, tmp_path):
        vista = tmp_path / "vista.html"
        detalle = mensajes.detalle_real(_resumen(_doc(vista_previa=vista)))
        assert detalle.documentos[0].vista_previa == vista


class TestDetalleCorto:
    def test_compone_aviso_documentos_y_secciones(self):
        resumen = publicacion.ResumenSinPruebas(
            curso=5678,
            nombre_curso="Matemáticas 2ºB",
            documentos=(
                publicacion.DocumentoBreve("t.md", "tarea", "Problemas", existe=True),
                publicacion.DocumentoBreve("nueva.md", "pagina", "Nueva", existe=False),
                publicacion.DocumentoBreve(
                    "duda.md",
                    "pagina",
                    "Duda",
                    existe=None,
                    itinerario=("Si no se cumple: se oculta",),
                ),
            ),
            secciones_nuevas=("Fracciones",),
        )
        detalle = mensajes.detalle_corto(resumen)
        assert detalle.curso == "«Matemáticas 2ºB» (id 5678)"
        assert detalle.aviso == "Sin curso de pruebas: se publicará solo en oculto."
        assert detalle.encabezado == "Se va a publicar en el curso REAL, sin verificación previa:"
        assert [documento.titulo for documento in detalle.documentos] == [
            "Tarea «Problemas» (fichero t.md)",
            "Página «Nueva» (fichero nueva.md)",
            "Página «Duda» (fichero duda.md)",
        ]
        assert detalle.documentos[0].lineas == (
            "Ya existe en el aula: se ocultará si estaba visible.",
        )
        assert detalle.documentos[1].lineas == ()
        assert detalle.documentos[2].lineas == (
            "Puede que ya exista en el aula: se ocultará si estaba visible.",
            "Si no se cumple: se oculta",
        )
        assert detalle.finales == ("Se creará la sección «Fracciones» (oculta).",)

    def test_el_itinerario_se_sanea_al_convertirse(self):
        resumen = publicacion.ResumenSinPruebas(
            curso=1,
            nombre_curso=None,
            documentos=(
                publicacion.DocumentoBreve("p.md", "pagina", "P", itinerario=("hola\x1b[31mrojo",)),
            ),
            secciones_nuevas=(),
        )
        [documento] = mensajes.detalle_corto(resumen).documentos
        assert "\x1b" not in " ".join(documento.lineas)
