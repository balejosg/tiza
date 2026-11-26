"""Encuesta anónima (``mod_feedback``): modelo, validación, vista previa y hash."""

from __future__ import annotations

import pytest

from tiza import contenido, tipos

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

TODAS = """\
- tipo: informacion
  texto: Es **anónima**.
- tipo: escala
  enunciado: ¿Cómo te has sentido?
  opciones: [Muy mal, Mal, Normal, Bien, Muy bien]
  obligatoria: true
- tipo: opcion
  enunciado: ¿Qué has usado?
  opciones: [Apuntes, Pizarra]
  multiple: true
- tipo: opcion
  enunciado: ¿Cuándo estudias?
  opciones: [Mañana, Tarde]
  desplegable: true
- tipo: texto
  enunciado: ¿Qué te ha gustado?
- tipo: texto_corto
  enunciado: Una palabra
- tipo: numero
  enunciado: Del 0 al 10
  minimo: 0
  maximo: 10
"""


def documento(tmp_path, preguntas: str = TODAS, **campos) -> contenido.Documento:
    extra = "".join(f"{clave}: {valor}\n" for clave, valor in campos.items())
    ruta = tmp_path / "encuesta.md"
    ruta.write_text(
        f"---\ntipo: encuesta\nnombre: Puerta de la felicidad\nseccion: 3\n{extra}"
        f"preguntas:\n{preguntas}---\n\nCuéntanos cómo ha ido la clase.\n",
        encoding="utf-8",
        newline="\n",
    )
    return contenido.cargar(ruta, raiz=tmp_path)


def codigo(tmp_path, preguntas: str = TODAS, **campos) -> str:
    with pytest.raises(contenido.ErrorContenido) as exc:
        documento(tmp_path, preguntas, **campos)
    return exc.value.codigo


class TestModelo:
    def test_una_encuesta_valida_reune_sus_preguntas_y_ajustes(self, tmp_path):
        doc = documento(
            tmp_path,
            abre="2026-11-27",
            cierra="2026-12-20 18:00",
            respuestas="varias",
            mensaje_final="¡Gracias!",
            finalizacion="enviar",
        )
        assert doc.tipo == "encuesta"
        encuesta = doc.encuesta
        assert encuesta is not None
        assert [p.tipo for p in encuesta.preguntas] == [
            "informacion",
            "escala",
            "opcion",
            "opcion",
            "texto",
            "texto_corto",
            "numero",
        ]
        assert encuesta.respuestas == "varias"
        assert encuesta.mensaje_final == "¡Gracias!"
        assert encuesta.mensaje_final_html == "<p>¡Gracias!</p>\n"
        assert encuesta.apertura is not None and encuesta.cierre is not None
        assert doc.finalizacion is not None and doc.finalizacion.modo == "enviar"

    def test_los_valores_por_defecto_son_una_respuesta_y_sin_finalizacion(self, tmp_path):
        doc = documento(tmp_path)
        assert doc.encuesta is not None
        assert doc.encuesta.respuestas == "una"
        assert doc.encuesta.mensaje_final == ""
        assert doc.finalizacion is None

    def test_las_preguntas_guardan_lo_suyo(self, tmp_path):
        encuesta = documento(tmp_path).encuesta
        assert encuesta is not None
        informacion, escala, casillas, desplegable, texto, corto, numero = encuesta.preguntas
        assert informacion.html == "<p>Es <strong>anónima</strong>.</p>\n"
        assert escala.opciones == ("Muy mal", "Mal", "Normal", "Bien", "Muy bien")
        assert escala.obligatoria is True
        assert casillas.multiple is True and casillas.desplegable is False
        assert desplegable.desplegable is True and desplegable.multiple is False
        assert texto.obligatoria is False
        assert corto.tipo == "texto_corto"
        assert (numero.minimo, numero.maximo) == (0.0, 10.0)

    def test_una_encuesta_es_siempre_anonima(self, tmp_path):
        assert codigo(tmp_path, anonima="true") == "CAMPO_NO_PERMITIDO"

    def test_una_encuesta_no_lleva_nota(self, tmp_path):
        assert codigo(tmp_path, evalua="{RA1: 40}") == "EVALUA_NO_CALIFICABLE"

    def test_las_respuestas_solo_admiten_una_o_varias(self, tmp_path):
        assert codigo(tmp_path, respuestas="muchas") == "AJUSTE_INVALIDO"

    def test_el_mensaje_final_tiene_que_ser_texto(self, tmp_path):
        assert codigo(tmp_path, mensaje_final="[uno, dos]") == "AJUSTE_INVALIDO"

    def test_las_fechas_deben_ser_coherentes(self, tmp_path):
        assert codigo(tmp_path, abre="2026-12-20", cierra="2026-12-01") == "FECHAS_INCOHERENTES"

    def test_hace_falta_al_menos_una_pregunta(self, tmp_path):
        assert codigo(tmp_path, "") == "PREGUNTAS_INVALIDAS"


class TestPreguntas:
    def test_el_tipo_de_pregunta_tiene_que_ser_uno_de_los_admitidos(self, tmp_path):
        preguntas = "- tipo: dibujo\n  enunciado: Dibuja\n"
        assert codigo(tmp_path, preguntas) == "TIPO_PREGUNTA_INVALIDO"

    def test_un_campo_desconocido_se_rechaza_con_su_linea(self, tmp_path):
        preguntas = "- tipo: texto\n  enunciado: Uno\n  obligatoria: false\n  largo: true\n"
        with pytest.raises(contenido.ErrorContenido) as exc:
            documento(tmp_path, preguntas)
        assert exc.value.codigo == "CAMPO_NO_PERMITIDO"
        assert "«largo»" in exc.value.detalle
        assert "línea" in exc.value.detalle

    def test_informacion_no_admite_obligatoria(self, tmp_path):
        preguntas = "- tipo: informacion\n  texto: Hola\n  obligatoria: true\n"
        assert codigo(tmp_path, preguntas) == "CAMPO_NO_PERMITIDO"

    def test_cada_tipo_admite_solo_sus_campos(self, tmp_path):
        preguntas = "- tipo: texto\n  enunciado: Uno\n  opciones: [A, B]\n"
        assert codigo(tmp_path, preguntas) == "CAMPO_NO_PERMITIDO"

    def test_una_escala_necesita_de_dos_a_diez_opciones(self, tmp_path):
        una = "- tipo: escala\n  enunciado: Uno\n  opciones: [Solo]\n"
        once = "- tipo: escala\n  enunciado: Uno\n  opciones: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]\n"
        assert codigo(tmp_path, una) == "OPCIONES_INVALIDAS"
        assert codigo(tmp_path, once) == "OPCIONES_INVALIDAS"

    def test_una_opcion_no_puede_ser_a_la_vez_casillas_y_desplegable(self, tmp_path):
        preguntas = (
            "- tipo: opcion\n  enunciado: Uno\n  opciones: [A, B]\n"
            "  multiple: true\n  desplegable: true\n"
        )
        assert codigo(tmp_path, preguntas) == "AJUSTE_INVALIDO"

    @pytest.mark.parametrize("separador", ["A | B", "A #### B", "A >>>>> B", "A <<<<< B"])
    def test_las_opciones_no_llevan_separadores_de_moodle(self, tmp_path, separador):
        preguntas = f'- tipo: opcion\n  enunciado: Uno\n  opciones: ["{separador}", B]\n'
        assert codigo(tmp_path, preguntas) == "OPCION_CON_SEPARADOR"

    def test_una_opcion_es_texto_plano(self, tmp_path):
        preguntas = '- tipo: opcion\n  enunciado: Uno\n  opciones: ["<b>A</b>", B]\n'
        assert codigo(tmp_path, preguntas) == "OPCIONES_INVALIDAS"

    def test_el_numero_admite_minimo_maximo_o_ninguno(self, tmp_path):
        solo_minimo = "- tipo: numero\n  enunciado: Uno\n  minimo: 0\n"
        assert documento(tmp_path, solo_minimo).encuesta is not None
        solo_maximo = "- tipo: numero\n  enunciado: Uno\n  maximo: 10\n"
        assert documento(tmp_path, solo_maximo).encuesta is not None
        ninguno = "- tipo: numero\n  enunciado: Uno\n"
        assert documento(tmp_path, ninguno).encuesta is not None

    def test_el_minimo_tiene_que_ser_menor_que_el_maximo(self, tmp_path):
        preguntas = "- tipo: numero\n  enunciado: Uno\n  minimo: 10\n  maximo: 0\n"
        assert codigo(tmp_path, preguntas) == "NUMERO_INVALIDO"

    def test_obligatoria_tiene_que_ser_booleana(self, tmp_path):
        preguntas = "- tipo: texto\n  enunciado: Uno\n  obligatoria: sí\n"
        assert codigo(tmp_path, preguntas) == "PREGUNTAS_INVALIDAS"

    def test_el_enunciado_no_puede_quedarse_vacio(self, tmp_path):
        preguntas = '- tipo: texto\n  enunciado: ""\n'
        assert codigo(tmp_path, preguntas) == "ENUNCIADO_INVALIDO"

    def test_el_enunciado_de_una_pregunta_es_texto_plano(self, tmp_path):
        preguntas = '- tipo: texto\n  enunciado: "<b>Hola</b>"\n'
        assert codigo(tmp_path, preguntas) == "ENUNCIADO_INVALIDO"


class TestImagenes:
    def test_informacion_admite_una_imagen_local(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "punto.png").write_bytes(_PNG)
        preguntas = '- tipo: informacion\n  texto: "![Un punto](img/punto.png)"\n'
        encuesta = documento(tmp_path, preguntas).encuesta
        assert encuesta is not None
        assert len(encuesta.imagenes) == 1
        assert "@@PLUGINFILE@@/" in encuesta.preguntas[0].html
        assert encuesta.preguntas[0].imagenes == encuesta.imagenes

    def test_una_imagen_sin_texto_alternativo_se_rechaza(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "punto.png").write_bytes(_PNG)
        preguntas = '- tipo: informacion\n  texto: "![](img/punto.png)"\n'
        assert codigo(tmp_path, preguntas) == "IMAGEN_SIN_ALT"

    def test_las_demas_preguntas_no_admiten_ficheros_locales(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "punto.png").write_bytes(_PNG)
        preguntas = (
            '- tipo: escala\n  enunciado: "![Un punto](img/punto.png)"\n  opciones: [A, B]\n'
        )
        assert codigo(tmp_path, preguntas) == "RECURSO_EN_PREGUNTA"


class TestFechasYFinalizacion:
    def test_las_fechas_son_las_de_su_formulario(self, tmp_path):
        encuesta = tipos.obtener("encuesta")
        doc = documento(tmp_path, abre="2026-11-27", cierra="2026-12-20")
        fechas = encuesta.fechas(doc)
        assert [(f.campo, f.campo_moodle) for f in fechas] == [
            ("abre", "timeopen"),
            ("cierra", "timeclose"),
        ]

    def test_solo_admite_ninguna_o_enviar(self, tmp_path):
        doc = documento(tmp_path, finalizacion="ninguna")
        assert doc.finalizacion is not None and doc.finalizacion.modo == "ninguna"
        assert codigo(tmp_path, finalizacion="completar") == "FINALIZACION_NO_ADMITIDA"

    def test_el_payload_de_finalizacion_marca_completionsubmit(self, tmp_path):
        doc = documento(tmp_path, finalizacion="enviar")
        payload = tipos.obtener("encuesta").payload(doc, "", 1, None)
        assert payload["completion"] == "2"
        assert payload["completionsubmit"] == "1"


class TestVistaPreviaYResumen:
    def test_la_vista_previa_ensena_las_preguntas(self, tmp_path):
        vista = tipos.obtener("encuesta").extra_preview(documento(tmp_path))
        assert "Preguntas de la encuesta" in vista
        assert "¿Cómo te has sentido?" in vista
        assert "Muy bien" in vista

    def test_el_nombre_llano_es_encuesta_anonima(self):
        assert tipos.obtener("encuesta").llano == "Encuesta anónima"

    def test_el_detalle_dice_cuantas_preguntas(self, tmp_path):
        assert tipos.obtener("encuesta").detalle(documento(tmp_path)) == "7 preguntas"

    def test_el_resumen_dice_que_es_anonima_y_cuantas_preguntas(self, tmp_path):
        doc = documento(tmp_path, finalizacion="enviar")
        extras = tipos.obtener("encuesta").extras_resumen(doc)
        assert extras == {
            "encuesta_anonima": True,
            "encuesta_preguntas": 7,
            "encuesta_finalizacion": "enviar",
        }

    def test_una_encuesta_no_tiene_nota(self, tmp_path):
        assert tipos.obtener("encuesta").tiene_nota(documento(tmp_path)) is False


class TestHash:
    def test_el_hash_cambia_si_cambia_una_pregunta(self, tmp_path):
        uno = documento(tmp_path)
        otro = documento(tmp_path, TODAS.replace("Una palabra", "Otra palabra"))
        assert contenido.hash_documento(uno) != contenido.hash_documento(otro)

    def test_el_hash_cambia_si_cambia_un_ajuste(self, tmp_path):
        uno = documento(tmp_path)
        otro = documento(tmp_path, respuestas="varias")
        assert contenido.hash_documento(uno) != contenido.hash_documento(otro)

    def test_el_hash_cambia_si_cambia_la_imagen(self, tmp_path):
        (tmp_path / "img").mkdir()
        (tmp_path / "img" / "punto.png").write_bytes(_PNG)
        preguntas = '- tipo: informacion\n  texto: "![Un punto](img/punto.png)"\n'
        uno = documento(tmp_path, preguntas)
        (tmp_path / "img" / "punto.png").write_bytes(_PNG + b"\x00")
        otro = documento(tmp_path, preguntas)
        assert contenido.hash_documento(uno) != contenido.hash_documento(otro)
