"""Tests de la vigilancia de lo publicado: reglas de lectura, una por una.

Todo offline: el aula es un doble que solo sabe leer un formulario (y contar lecturas), y los
almacenes son ``copia.json`` y ``publicados.json`` en ``tmp_path``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from dobles import estructura_de
from tiza import contenido, estado, tipos
from tiza.contenido import Documento, Origen
from tiza.publicar import ErrorPublicacion
from tiza.vigilancia import (
    Anotacion,
    Cambio,
    EstadoDeCambios,
    Rechazo,
    Vigilancia,
)


class Aula:
    """Un aula mínima: un formulario por cmid, contador de lecturas y fallo opcional."""

    def __init__(self, formularios: dict[int, dict] | None = None, falla: bool = False) -> None:
        self.formularios = formularios or {}
        self.falla = falla
        self.lecturas: list[int] = []

    def leer_modulo(self, cmid: int) -> dict:
        self.lecturas.append(cmid)
        if self.falla:
            raise ErrorPublicacion("ERROR_CONSULTA")
        return self.formularios[cmid]


class Lector:
    """Un lector de formulario que cuenta sus llamadas y puede fallar."""

    def __init__(self, formulario: dict | None = None) -> None:
        self.formulario = formulario
        self.llamadas = 0

    def __call__(self) -> dict:
        self.llamadas += 1
        if self.formulario is None:
            raise ErrorPublicacion("ERROR_CONSULTA")
        return self.formulario


def _doc(
    carpeta: Path,
    *,
    nombre: str = "A",
    tipo: str = "pagina",
    seccion: int = 3,
    origen: Origen | None = None,
    publicados: dict | None = None,
) -> Documento:
    fechas = "apertura: 2026-10-01\nentrega: 2026-10-12\n" if tipo == "tarea" else ""
    ruta = carpeta / f"{nombre}.md"
    ruta.write_text(
        f"---\ntipo: {tipo}\nnombre: {nombre}\nseccion: {seccion}\n{fechas}---\n\nTexto.\n",
        encoding="utf-8",
    )
    doc = contenido.cargar(ruta)
    if origen is not None:
        doc = replace(doc, origen=origen)
    if publicados is not None:
        doc = replace(doc, publicados=publicados)
    return doc


def _estructura(cmid: int = 501, nombre: str = "A", tipo: str = "pagina"):
    return estructura_de(
        [
            {
                "numero": 3,
                "nombre": "Tema 3",
                "id": 30,
                "modulos": [{"cmid": cmid, "nombre": nombre, "tipo": tipo}],
            }
        ]
    )


def _copia(
    carpeta: Path,
    *,
    huella: str | None,
    marca: str | None = None,
    curso: int = 5678,
    cmid: int = 501,
    fichero: str = "A.md",
) -> None:
    entrada = {
        "moodle": "https://aula.ejemplo.org/centro",
        "fecha_importacion": "2026-10-19T10:00:00+00:00",
        "secciones": [{"numero": 3, "nombre": "Tema 3", "resumen_html_presente": False}],
        "actividades": [
            {
                "cmid": cmid,
                "modulo": "page",
                "seccion": 3,
                "nombre": "A",
                "fichero": fichero,
                "estado": "IMPORTADA",
                "detalle": None,
                "huella_aula": huella,
                "huella_fichero": marca,
            }
        ],
    }
    estado.escribir_copia(
        carpeta / ".tiza", {"version": 1, "cursos": {str(curso): entrada}, "como_nuevas": None}
    )


def _vigilancia(
    aula: Aula, carpeta: Path, documentos: list[Documento], *, curso: int = 5678, real: bool = True
) -> Vigilancia:
    return Vigilancia.de(aula, carpeta / ".tiza", curso, documentos, real)


def _form(doc: Documento, *, texto: str | None = None, fechas: dict | None = None) -> dict:
    if texto is None:
        texto = contenido.html_para_moodle(doc)
    if fechas is None:
        fechas = {}
        if doc.tipo == "tarea" and doc.fechas is not None:
            fechas = {
                "allowsubmissionsfromdate": tipos.partes_fecha(doc.fechas.apertura),
                "duedate": tipos.partes_fecha(doc.fechas.entrega),
                "cutoffdate": (
                    tipos.partes_fecha(doc.fechas.limite) if doc.fechas.limite else None
                ),
            }
    return {"nombre": doc.nombre, "texto": texto, "fechas": fechas}


def _huella(doc: Documento, leido: dict) -> str:
    return tipos.huella_del_formulario(tipos.obtener(doc.tipo), doc, leido)


def _entrada(cmid: int = 501, *, huella: str | None, marca: str | None = None) -> dict:
    return {5678: estado.Publicado(cmid, "pagina", huella=huella, marca=marca)}


# --- M1: rechazos antes de confirmar ---------------------------------------------------------


def test_rechaza_un_origen_que_ya_no_esta_en_el_curso(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=999))
    _copia(carpeta, huella="a" * 64, cmid=999)
    rechazos = _vigilancia(Aula(), carpeta, [doc]).rechazos(_estructura(), [doc], False)
    assert [(r.documento, r.codigo) for r in rechazos] == [(doc, "ORIGEN_NO_ENCONTRADO")]


def test_rechaza_un_origen_sin_huella_en_la_copia(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella=None)
    rechazos = _vigilancia(Aula(), carpeta, [doc]).rechazos(_estructura(), [doc], False)
    assert [r.codigo for r in rechazos] == ["ORIGEN_SIN_HUELLA"]


def test_rechaza_como_cambiada_si_el_fichero_sigue_como_en_la_marca(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64, marca=doc.sha256_fichero)
    rechazos = _vigilancia(Aula(), carpeta, [doc]).rechazos(_estructura(), [doc], False)
    assert [(r.codigo, r.cmid_copia, r.por_decision) for r in rechazos] == [
        ("CAMBIADA_EN_EL_AULA", 501, False)
    ]


def test_una_marca_ilegible_bloquea_siempre(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64, marca=estado.MARCA_ILEGIBLE)
    rechazos = _vigilancia(Aula(), carpeta, [doc]).rechazos(_estructura(), [doc], False)
    assert [r.codigo for r in rechazos] == ["CAMBIADA_EN_EL_AULA"]


@pytest.mark.parametrize("marca", [None, "b" * 64])
def test_sin_marca_o_con_la_de_otra_actividad_o_ya_juntado_no_rechaza(tmp_path, marca):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64, marca=marca)
    assert _vigilancia(Aula(), carpeta, [doc]).rechazos(_estructura(), [doc], False) == ()


def test_con_solo_fechas_no_mira_si_el_origen_esta_pero_si_la_huella_y_la_marca(tmp_path):
    carpeta = tmp_path.resolve()
    perdido = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    sin_huella = _doc(carpeta, nombre="B", origen=Origen(curso=5678, cmid=501))
    vacia = estructura_de([{"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []}])
    _copia(carpeta, huella="a" * 64, cmid=501)
    vigilancia = _vigilancia(Aula(), carpeta, [perdido, sin_huella])
    # El origen perdido no cuenta con --solo-fechas; la huella sí (y 501 la tiene).
    assert vigilancia.rechazos(vacia, [perdido, sin_huella], True) == ()
    _copia(carpeta, huella=None, cmid=501)
    vigilancia = _vigilancia(Aula(), carpeta, [sin_huella])
    assert [r.codigo for r in vigilancia.rechazos(vacia, [sin_huella], True)] == [
        "ORIGEN_SIN_HUELLA"
    ]


def test_la_marca_del_registro_no_rechaza_antes_de_confirmar(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados={5678: estado.Publicado(501, "pagina", "a" * 64, "a" * 64)})
    assert _vigilancia(Aula(), carpeta, [doc]).rechazos(_estructura(), [doc], False) == ()


def test_el_rechazo_del_no_lleva_por_decision_y_no_lleva_cmid_de_copia(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    rechazo = _vigilancia(Aula(), carpeta, [doc]).rechazo_del_no(doc)
    assert rechazo == Rechazo(doc, "CAMBIADA_EN_EL_AULA", por_decision=True, cmid_copia=None)


def test_sin_origen_en_este_curso_no_hay_rechazos_ni_se_carga_la_copia(tmp_path):
    carpeta = tmp_path.resolve()
    (carpeta / ".tiza").mkdir()
    (carpeta / ".tiza" / "copia.json").write_text("{}", encoding="utf-8")
    doc = _doc(carpeta, origen=Origen(curso=9999, cmid=501))
    vigilancia = _vigilancia(Aula(), carpeta, [doc])
    assert vigilancia.huellas == {} and vigilancia.marcas == {}
    assert vigilancia.rechazos(_estructura(), [doc], False) == ()


def test_rechazos_no_lee_el_aula(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64, marca=doc.sha256_fichero)
    aula = Aula(falla=True)
    _vigilancia(aula, carpeta, [doc]).rechazos(_estructura(), [doc], False)
    assert aula.lecturas == []


def test_una_copia_que_no_vale_da_error_al_construir(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    (carpeta / ".tiza").mkdir()
    (carpeta / ".tiza" / "copia.json").write_text(json.dumps({"version": 7}), encoding="utf-8")
    with pytest.raises(estado.ErrorEstado) as exc:
        _vigilancia(Aula(), carpeta, [doc])
    assert exc.value.codigo == "COPIA_INVALIDA"
    (carpeta / ".tiza" / "copia.json").write_text("no es json", encoding="utf-8")
    with pytest.raises(estado.ErrorEstado) as exc:
        _vigilancia(Aula(), carpeta, [doc])
    assert exc.value.codigo == "IMPORTACION_ILEGIBLE"


def test_sin_copia_no_hay_nada_que_comparar(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    vigilancia = _vigilancia(Aula(), carpeta, [doc])
    assert (vigilancia.huellas, vigilancia.marcas) == ({}, {})


# --- M2: retoques que se preguntan -----------------------------------------------------------


def test_solo_pregunta_por_lo_hallado_por_registro_con_huella(tmp_path):
    carpeta = tmp_path.resolve()
    origen = _doc(carpeta, nombre="O", origen=Origen(curso=5678, cmid=501))
    por_nombre = _doc(carpeta, nombre="N")
    con_huella = _doc(carpeta, nombre="R", publicados=_entrada(huella="a" * 64))
    sin_huella = _doc(carpeta, nombre="S", publicados=_entrada(huella=None))
    leido = _form(con_huella)
    aula = Aula({501: leido})
    retoques = _vigilancia(aula, carpeta, [origen, por_nombre, con_huella, sin_huella]).retoques(
        _estructura(nombre="R"), [origen, por_nombre, con_huella, sin_huella]
    )
    assert retoques == ()
    assert aula.lecturas == [501]


def test_marca_sin_juntar_es_retoque_sin_leer_el_aula(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    doc = replace(
        doc, publicados={5678: estado.Publicado(501, "pagina", "a" * 64, doc.sha256_fichero)}
    )
    aula = Aula(falla=True)
    retoques = _vigilancia(aula, carpeta, [doc]).retoques(_estructura(), [doc])
    assert retoques == (doc,)
    assert aula.lecturas == []


def test_formulario_distinto_de_la_huella_y_de_lo_enviado_es_retoque(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados=_entrada(huella="a" * 64))
    aula = Aula({501: _form(doc, texto="<p>A mano</p>")})
    assert _vigilancia(aula, carpeta, [doc]).retoques(_estructura(), [doc]) == (doc,)


def test_formulario_igual_a_lo_enviado_no_es_retoque(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados=_entrada(huella="a" * 64))
    leido = _form(doc)
    assert _huella(doc, leido) != "a" * 64
    assert _vigilancia(Aula({501: leido}), carpeta, [doc]).retoques(_estructura(), [doc]) == ()


def test_con_solo_fechas_las_fechas_ya_puestas_no_son_retoque(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, tipo="tarea", publicados=_entrada(huella="a" * 64))
    leido = _form(doc, texto="<p>Texto del aula</p>")
    aula = Aula({501: leido})
    vigilancia = _vigilancia(aula, carpeta, [doc])
    assert vigilancia.retoques(_estructura(tipo="tarea"), [doc], solo_fechas=True) == ()
    assert vigilancia.retoques(_estructura(tipo="tarea"), [doc], solo_fechas=False) == (doc,)


def test_si_no_se_puede_leer_el_formulario_es_retoque(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados=_entrada(huella="a" * 64))
    assert _vigilancia(Aula(falla=True), carpeta, [doc]).retoques(_estructura(), [doc]) == (doc,)


def test_por_origen_por_nombre_o_con_problema_no_lee_ni_pregunta(tmp_path):
    carpeta = tmp_path.resolve()
    origen = _doc(carpeta, nombre="O", origen=Origen(curso=5678, cmid=501))
    por_nombre = _doc(carpeta, nombre="N")
    problema = _doc(carpeta, nombre="P", origen=Origen(curso=5678, cmid=999))
    aula = Aula(falla=True)
    docs = [origen, por_nombre, problema]
    assert _vigilancia(aula, carpeta, docs).retoques(_estructura(nombre="N"), docs) == ()
    assert aula.lecturas == []


def test_en_pruebas_no_hay_retoques_ni_lecturas(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados=_entrada(huella="a" * 64))
    aula = Aula(falla=True)
    vigilancia = _vigilancia(aula, carpeta, [doc], real=False)
    assert vigilancia.retoques(_estructura(), [doc]) == ()
    assert aula.lecturas == []


# --- M5: estado de cambios ---------------------------------------------------------------


def test_estado_de_un_origen_con_huella_cambiada_o_sin_cambios(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    leido = _form(doc)
    _copia(carpeta, huella=_huella(doc, leido))
    cambio = _vigilancia(Aula({501: leido}), carpeta, [doc]).estado_por_documento(
        _estructura(), [doc]
    )
    assert cambio == (Cambio(doc, 501, EstadoDeCambios.SIN_CAMBIOS),)
    leido = _form(doc, texto="<p>A mano</p>")
    cambio = _vigilancia(Aula({501: leido}), carpeta, [doc]).estado_por_documento(
        _estructura(), [doc]
    )
    assert cambio[0].estado is EstadoDeCambios.CAMBIADA


def test_estado_de_un_origen_sin_huella_es_sin_registro_con_su_cmid(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella=None)
    cambio = _vigilancia(Aula(falla=True), carpeta, [doc]).estado_por_documento(
        _estructura(), [doc]
    )
    assert [(c.cmid, c.estado) for c in cambio] == [(501, EstadoDeCambios.SIN_REGISTRO)]


def test_estado_de_lo_hallado_por_nombre_es_sin_registro_con_su_cmid(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    cambio = _vigilancia(Aula(falla=True), carpeta, [doc]).estado_por_documento(
        _estructura(), [doc]
    )
    assert [(c.cmid, c.estado) for c in cambio] == [(501, EstadoDeCambios.SIN_REGISTRO)]


def test_estado_con_marca_sin_juntar_es_cambiada_sin_leer(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64, marca=doc.sha256_fichero)
    aula = Aula(falla=True)
    cambio = _vigilancia(aula, carpeta, [doc]).estado_por_documento(_estructura(), [doc])
    assert [(c.cmid, c.estado) for c in cambio] == [(501, EstadoDeCambios.CAMBIADA)]
    assert aula.lecturas == []


def test_estado_de_un_registro_con_huella(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados=_entrada(huella="a" * 64))
    leido = _form(doc)
    cambio = _vigilancia(Aula({501: leido}), carpeta, [doc]).estado_por_documento(
        _estructura(), [doc]
    )
    assert [(c.cmid, c.estado) for c in cambio] == [(501, EstadoDeCambios.SIN_CAMBIOS)]


def test_estado_de_una_entrada_sin_huella_es_sin_registro_con_su_cmid(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados=_entrada(huella=None))
    cambio = _vigilancia(Aula(falla=True), carpeta, [doc]).estado_por_documento(
        _estructura(), [doc]
    )
    assert [(c.cmid, c.estado) for c in cambio] == [(501, EstadoDeCambios.SIN_REGISTRO)]


def test_estado_si_falla_la_lectura_es_cambiada(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados=_entrada(huella="a" * 64))
    cambio = _vigilancia(Aula(falla=True), carpeta, [doc]).estado_por_documento(
        _estructura(), [doc]
    )
    assert [(c.cmid, c.estado) for c in cambio] == [(501, EstadoDeCambios.CAMBIADA)]


def test_estado_con_problema_de_localizacion_es_sin_registro_sin_cmid(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=999))
    _copia(carpeta, huella="a" * 64, cmid=999)
    cambio = _vigilancia(Aula(falla=True), carpeta, [doc]).estado_por_documento(
        _estructura(), [doc]
    )
    assert [(c.cmid, c.estado) for c in cambio] == [(None, EstadoDeCambios.SIN_REGISTRO)]


def test_estado_no_distingue_solo_fechas(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, tipo="tarea", publicados=_entrada(huella="a" * 64))
    # El texto del aula con las fechas del fichero se aceptaría con --solo-fechas; aquí no.
    leido = _form(doc, texto="<p>Texto del aula</p>")
    cambio = _vigilancia(Aula({501: leido}), carpeta, [doc]).estado_por_documento(
        _estructura(tipo="tarea"), [doc]
    )
    assert [(c.cmid, c.estado) for c in cambio] == [(501, EstadoDeCambios.CAMBIADA)]


# --- M3: la actividad vigilada al publicar entero ------------------------------------------


def test_actividad_de_copia_cambiada_si_el_formulario_difiere_de_la_huella_y_de_lo_enviado(
    tmp_path,
):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64)
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(), doc)
    assert vigilada is not None and vigilada.de_copia
    assert vigilada.comprobar(Lector(_form(doc, texto="<p>A mano</p>")), solo_fechas=False)


def test_actividad_de_copia_que_ya_tiene_lo_de_tiza_se_acepta(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64)
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(), doc)
    assert vigilada is not None
    assert not vigilada.comprobar(Lector(_form(doc)), solo_fechas=False)


def test_actividad_de_copia_no_mira_la_marca_al_escribir(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    leido = _form(doc)
    _copia(carpeta, huella=_huella(doc, leido), marca=doc.sha256_fichero)
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(), doc)
    assert vigilada is not None
    assert not vigilada.comprobar(Lector(leido), solo_fechas=False)


def test_actividad_de_registro_con_marca_sin_juntar_no_lee_el_aula(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    doc = replace(
        doc, publicados={5678: estado.Publicado(501, "pagina", "a" * 64, doc.sha256_fichero)}
    )
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(), doc)
    assert vigilada is not None and not vigilada.de_copia
    lector = Lector(_form(doc))
    assert vigilada.comprobar(lector, solo_fechas=False)
    assert lector.llamadas == 0


def test_actividad_de_registro_cambiada_si_difiere(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados=_entrada(huella="a" * 64))
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(), doc)
    assert vigilada is not None
    assert vigilada.comprobar(Lector(_form(doc, texto="<p>A mano</p>")), solo_fechas=False)


def test_si_el_docente_dijo_si_no_hay_actividad_vigilada_de_registro_pero_si_de_copia(tmp_path):
    carpeta = tmp_path.resolve()
    registro = _doc(carpeta, publicados=_entrada(huella="a" * 64))
    origen = _doc(carpeta, nombre="O", origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64)
    vigilancia = _vigilancia(Aula(), carpeta, [registro, origen])
    assert vigilancia.actividad(_estructura(), registro, sobrescribe=True) is None
    de_copia = vigilancia.actividad(_estructura(nombre="O"), origen, sobrescribe=True)
    assert de_copia is not None and de_copia.de_copia


def test_en_pruebas_no_hay_actividad_vigilada_de_registro(tmp_path):
    carpeta = tmp_path.resolve()
    registro = _doc(carpeta, publicados=_entrada(huella="a" * 64))
    origen = _doc(carpeta, nombre="O", origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64)
    vigilancia = _vigilancia(Aula(), carpeta, [registro, origen], real=False)
    assert vigilancia.actividad(_estructura(), registro) is None
    assert vigilancia.actividad(_estructura(nombre="O"), origen) is not None


def test_una_lectura_fallida_al_comprobar_se_propaga(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados=_entrada(huella="a" * 64))
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(), doc)
    assert vigilada is not None
    with pytest.raises(ErrorPublicacion):
        vigilada.comprobar(Lector(None), solo_fechas=False)


def test_comprobar_usa_el_lector_una_sola_vez(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados=_entrada(huella="a" * 64))
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(), doc)
    assert vigilada is not None
    lector = Lector(_form(doc))
    assert not vigilada.comprobar(lector, solo_fechas=False)
    assert lector.llamadas == 1


def test_origen_sin_huella_no_da_actividad_vigilada(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella=None)
    assert _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(), doc) is None


def test_registro_sin_huella_no_da_actividad_vigilada(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados=_entrada(huella=None))
    assert _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(), doc) is None


# --- M4: la actividad vigilada en solo-fechas ----------------------------------------------

_FECHAS_VIEJAS = {
    "allowsubmissionsfromdate": (2026, 10, 1, 0, 0),
    "duedate": (2026, 10, 10, 23, 59),
    "cutoffdate": None,
}


def test_solo_fechas_de_copia_cambiada_si_cambio_el_texto_y_las_fechas_no_son_las_pedidas(
    tmp_path,
):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, tipo="tarea", origen=Origen(curso=5678, cmid=501))
    base = _huella(doc, _form(doc, texto="<p>Texto viejo</p>", fechas=_FECHAS_VIEJAS))
    _copia(carpeta, huella=base)
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(tipo="tarea"), doc)
    assert vigilada is not None
    leido = _form(doc, texto="<p>Texto a mano</p>", fechas=_FECHAS_VIEJAS)
    assert vigilada.comprobar(Lector(leido), solo_fechas=True)


def test_solo_fechas_de_copia_con_las_fechas_ya_puestas_se_acepta_sin_huella_nueva(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, tipo="tarea", origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64)
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(tipo="tarea"), doc)
    assert vigilada is not None
    leido = _form(doc)
    assert not vigilada.comprobar(Lector(leido), solo_fechas=True)
    vigilada.fechas_verificadas(leido)
    assert vigilada.huella_nueva is None


def test_solo_fechas_de_registro_cambiada_por_marca_o_por_texto(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, tipo="tarea")
    doc = replace(
        doc, publicados={5678: estado.Publicado(501, "tarea", "a" * 64, doc.sha256_fichero)}
    )
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(tipo="tarea"), doc)
    assert vigilada is not None
    lector = Lector(_form(doc))
    assert vigilada.comprobar(lector, solo_fechas=True)
    assert lector.llamadas == 0
    doc = replace(doc, publicados={5678: estado.Publicado(501, "tarea", "a" * 64)})
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(tipo="tarea"), doc)
    assert vigilada is not None
    leido = _form(doc, texto="<p>Texto a mano</p>", fechas=_FECHAS_VIEJAS)
    assert vigilada.comprobar(Lector(leido), solo_fechas=True)


def test_solo_fechas_de_registro_con_las_fechas_ya_puestas_se_acepta_sin_huella_nueva(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, tipo="tarea", publicados=_entrada(huella="a" * 64))
    doc = replace(doc, publicados={5678: estado.Publicado(501, "tarea", "a" * 64, None)})
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(tipo="tarea"), doc)
    assert vigilada is not None
    leido = _form(doc)
    assert not vigilada.comprobar(Lector(leido), solo_fechas=True)
    vigilada.fechas_verificadas(leido)
    assert vigilada.huella_nueva is None


def test_solo_fechas_con_sobrescribir_no_compara_ni_renueva(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, tipo="tarea", publicados=_entrada(huella="a" * 64, marca="b" * 64))
    estado.guardar_publicado(
        carpeta / ".tiza",
        5678,
        "A.md",
        estado.Publicado(501, "tarea", huella="a" * 64, marca="b" * 64),
    )
    vigilancia = _vigilancia(Aula(), carpeta, [doc])
    assert vigilancia.actividad(_estructura(tipo="tarea"), doc, sobrescribe=True) is None
    # Sin actividad vigilada no hay huella nueva y no se renueva nada.
    assert vigilancia.anotar_fechas(doc, "A.md", None) == Anotacion()
    assert estado.cargar_publicados(carpeta / ".tiza", 5678)["A.md"] == estado.Publicado(
        501, "tarea", huella="a" * 64, marca="b" * 64
    )


def test_la_huella_nueva_es_la_del_formulario_verificado(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, tipo="tarea", origen=Origen(curso=5678, cmid=501))
    leido = _form(doc)
    _copia(carpeta, huella=_huella(doc, leido))
    vigilada = _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(tipo="tarea"), doc)
    assert vigilada is not None
    assert not vigilada.comprobar(Lector(leido), solo_fechas=True)
    vigilada.fechas_verificadas(leido)
    assert vigilada.huella_nueva == _huella(doc, leido)
    assert vigilada.huella_nueva is not None


def test_con_un_problema_de_localizacion_no_hay_actividad_vigilada(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=999))
    _copia(carpeta, huella="a" * 64, cmid=999)
    assert _vigilancia(Aula(), carpeta, [doc]).actividad(_estructura(), doc) is None


# --- R1: renovar la huella de la copia ------------------------------------------------------


def test_anotar_renueva_la_huella_de_la_copia_con_lo_enviado_sin_releer(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64, marca=doc.sha256_fichero)
    aula = Aula(falla=True)
    anotacion = _vigilancia(aula, carpeta, [doc], real=False).anotar_publicado(doc, "A.md", 501)
    assert anotacion == Anotacion()
    esperada = tipos.huella_de_lo_enviado(
        tipos.obtener(doc.tipo), doc, contenido.html_para_moodle(doc)
    )
    assert estado.huellas_de_copia(carpeta / ".tiza", 5678) == {501: esperada}
    assert estado.marcas_de_copia(carpeta / ".tiza", 5678) == {}
    [actividad] = estado.cargar_copia(carpeta / ".tiza")["cursos"]["5678"]["actividades"]
    assert actividad["estado"] == "IMPORTADA"
    assert aula.lecturas == []


def test_anotar_renueva_solo_la_entrada_de_su_curso(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64)
    datos = estado.cargar_copia(carpeta / ".tiza")
    otra = {
        **datos["cursos"]["5678"],
        "actividades": [dict(datos["cursos"]["5678"]["actividades"][0])],
    }
    otra["actividades"][0]["huella_aula"] = "b" * 64
    datos["cursos"]["9999"] = otra
    estado.escribir_copia(carpeta / ".tiza", datos)
    _vigilancia(Aula(), carpeta, [doc], real=False).anotar_publicado(doc, "A.md", 501)
    ahora = estado.cargar_copia(carpeta / ".tiza")
    assert ahora["cursos"]["9999"]["actividades"][0]["huella_aula"] == "b" * 64
    assert ahora["cursos"]["5678"]["actividades"][0]["huella_aula"] != "a" * 64


@pytest.mark.parametrize("renueva", [False, True])
def test_anotar_fechas_de_copia_renueva_solo_si_hay_huella_nueva(tmp_path, renueva):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64, marca=doc.sha256_fichero)
    vigilancia = _vigilancia(Aula(), carpeta, [doc])
    vigilada = vigilancia.actividad(_estructura(), doc)
    assert vigilada is not None and vigilada.de_copia
    leido = _form(doc)
    if renueva:
        vigilada.fechas_verificadas(leido)
        nueva = vigilada.huella_nueva
        assert nueva is not None
    else:
        assert not vigilada.comprobar(Lector(leido), solo_fechas=True)
        vigilada.fechas_verificadas(leido)
        nueva = "a" * 64
    assert vigilancia.anotar_fechas(doc, "A.md", vigilada) == Anotacion()
    assert estado.huellas_de_copia(carpeta / ".tiza", 5678) == {501: nueva}
    assert estado.marcas_de_copia(carpeta / ".tiza", 5678) == (
        {} if renueva else {501: doc.sha256_fichero}
    )


def test_anotar_con_copia_sin_la_actividad_da_huella_no_guardada(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64, cmid=999)
    anotacion = _vigilancia(Aula(), carpeta, [doc], real=False).anotar_publicado(doc, "A.md", 501)
    assert anotacion == Anotacion(("HUELLA_NO_GUARDADA",))


def test_anotar_con_copia_que_no_se_puede_escribir_da_huella_no_guardada(tmp_path, monkeypatch):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64)

    def falla(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(estado, "guardar_huella_de_copia", falla)
    anotacion = _vigilancia(Aula(), carpeta, [doc], real=False).anotar_publicado(doc, "A.md", 501)
    assert anotacion == Anotacion(("HUELLA_NO_GUARDADA",))


# --- R2: renovar la entrada del registro tras --solo-fechas ---------------------------------


def _vigilada_de_registro(carpeta: Path, doc: Documento, *, cmid: int = 501):
    vigilancia = _vigilancia(Aula(), carpeta, [doc])
    vigilada = vigilancia.actividad(_estructura(cmid=cmid, tipo=doc.tipo), doc)
    assert vigilada is not None and not vigilada.de_copia
    vigilada.fechas_verificadas(_form(doc))
    assert vigilada.huella_nueva is not None
    return vigilancia, vigilada


def _vigilada_de_copia(carpeta: Path, doc: Documento):
    vigilancia = _vigilancia(Aula(), carpeta, [doc])
    vigilada = vigilancia.actividad(_estructura(), doc)
    assert vigilada is not None and vigilada.de_copia
    vigilada.fechas_verificadas(_form(doc))
    assert vigilada.huella_nueva is not None
    return vigilancia, vigilada


def test_anotar_fechas_de_registro_pone_la_huella_nueva_y_quita_la_marca(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(
        carpeta,
        tipo="tarea",
        publicados={5678: estado.Publicado(501, "tarea", "a" * 64, "b" * 64)},
    )
    estado.guardar_publicado(
        carpeta / ".tiza",
        5678,
        "A.md",
        estado.Publicado(501, "tarea", "a" * 64, "b" * 64),
    )
    vigilancia, vigilada = _vigilada_de_registro(carpeta, doc)
    assert vigilancia.anotar_fechas(doc, "A.md", vigilada) == Anotacion()
    assert estado.cargar_publicados(carpeta / ".tiza", 5678)["A.md"] == estado.Publicado(
        501, "tarea", vigilada.huella_nueva, None
    )


def test_anotar_fechas_renueva_una_clave_con_dos_puntos_ya_escrita(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(
        carpeta,
        tipo="tarea",
        publicados={5678: estado.Publicado(7, "tarea", "a" * 64)},
    )
    (carpeta / ".tiza").mkdir()
    registro = {
        "version": 1,
        "cursos": {
            "5678": {
                "ficheros": {
                    "a:b.md": {
                        "cmid": 7,
                        "tipo": "tarea",
                        "huella": "a" * 64,
                        "marca": "b" * 64,
                    }
                }
            }
        },
    }
    (carpeta / ".tiza" / "publicados.json").write_text(json.dumps(registro), encoding="utf-8")
    vigilancia, vigilada = _vigilada_de_registro(carpeta, doc, cmid=7)
    assert vigilancia.anotar_fechas(doc, "a:b.md", vigilada) == Anotacion()
    assert estado.cargar_publicados(carpeta / ".tiza", 5678)["a:b.md"] == estado.Publicado(
        7, "tarea", vigilada.huella_nueva, None
    )


def test_anotar_fechas_sin_entrada_no_crea_nada(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(
        carpeta,
        tipo="tarea",
        publicados={5678: estado.Publicado(501, "tarea", "a" * 64)},
    )
    vigilancia, vigilada = _vigilada_de_registro(carpeta, doc)
    assert vigilancia.anotar_fechas(doc, "A.md", vigilada) == Anotacion()
    assert not (carpeta / ".tiza" / "publicados.json").exists()


def test_anotar_fechas_con_registro_que_no_se_puede_escribir_da_registro_no_guardado(
    tmp_path, monkeypatch
):
    carpeta = tmp_path.resolve()
    doc = _doc(
        carpeta,
        tipo="tarea",
        publicados={5678: estado.Publicado(501, "tarea", "a" * 64)},
    )
    estado.guardar_publicado(
        carpeta / ".tiza", 5678, "A.md", estado.Publicado(501, "tarea", "a" * 64)
    )
    vigilancia, vigilada = _vigilada_de_registro(carpeta, doc)

    def falla(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(estado, "guardar_publicado", falla)
    assert vigilancia.anotar_fechas(doc, "A.md", vigilada) == Anotacion(("REGISTRO_NO_GUARDADO",))


def test_anotar_fechas_con_una_ruta_que_no_vale_no_hace_nada(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(
        carpeta,
        tipo="tarea",
        publicados={5678: estado.Publicado(501, "tarea", "a" * 64)},
    )
    estado.guardar_publicado(
        carpeta / ".tiza", 5678, "A.md", estado.Publicado(501, "tarea", "a" * 64)
    )
    vigilancia, vigilada = _vigilada_de_registro(carpeta, doc)
    assert vigilancia.anotar_fechas(doc, "../A.md", vigilada) == Anotacion()
    assert estado.cargar_publicados(carpeta / ".tiza", 5678)["A.md"].huella == "a" * 64


# --- R3: el registro de lo publicado -------------------------------------------------------


def test_primera_publicacion_en_pruebas_registra_sin_huella_y_en_real_con_la_releida(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    anotacion = _vigilancia(Aula(falla=True), carpeta, [doc], real=False).anotar_publicado(
        doc, "A.md", 501
    )
    assert anotacion == Anotacion()
    assert estado.cargar_publicados(carpeta / ".tiza", 5678)["A.md"] == estado.Publicado(
        501, "pagina"
    )
    leido = _form(doc)
    aula = Aula({501: leido})
    anotacion = _vigilancia(aula, carpeta, [doc], real=True).anotar_publicado(doc, "A.md", 501)
    assert anotacion == Anotacion()
    assert estado.cargar_publicados(carpeta / ".tiza", 5678)["A.md"] == estado.Publicado(
        501, "pagina", _huella(doc, leido), None
    )
    assert aula.lecturas == [501]


def test_mismo_cmid_conserva_huella_y_marca_si_no_se_relee(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, publicados=_entrada(huella="a" * 64, marca="b" * 64))
    estado.guardar_publicado(
        carpeta / ".tiza",
        5678,
        "A.md",
        estado.Publicado(501, "pagina", huella="a" * 64, marca="b" * 64),
    )
    aula = Aula(falla=True)
    anotacion = _vigilancia(aula, carpeta, [doc], real=False).anotar_publicado(doc, "A.md", 501)
    assert anotacion == Anotacion()
    assert estado.cargar_publicados(carpeta / ".tiza", 5678)["A.md"] == estado.Publicado(
        501, "pagina", huella="a" * 64, marca="b" * 64
    )
    assert aula.lecturas == []


def test_cmid_distinto_borra_huella_y_marca(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    estado.guardar_publicado(
        carpeta / ".tiza",
        5678,
        "A.md",
        estado.Publicado(400, "pagina", huella="a" * 64, marca="b" * 64),
    )
    anotacion = _vigilancia(Aula(), carpeta, [doc], real=False).anotar_publicado(doc, "A.md", 501)
    assert anotacion == Anotacion()
    assert estado.cargar_publicados(carpeta / ".tiza", 5678)["A.md"] == estado.Publicado(
        501, "pagina"
    )


def test_con_origen_en_real_no_relee_y_guarda_la_huella_de_la_copia(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64, marca=doc.sha256_fichero)
    estado.guardar_publicado(
        carpeta / ".tiza",
        5678,
        "A.md",
        estado.Publicado(501, "pagina", huella="a" * 64, marca="b" * 64),
    )
    aula = Aula(falla=True)
    anotacion = _vigilancia(aula, carpeta, [doc], real=True).anotar_publicado(doc, "A.md", 501)
    assert anotacion == Anotacion()
    nueva = estado.huellas_de_copia(carpeta / ".tiza", 5678)[501]
    assert nueva != "a" * 64
    assert estado.cargar_publicados(carpeta / ".tiza", 5678)["A.md"] == estado.Publicado(
        501, "pagina", huella=nueva, marca=None
    )
    assert aula.lecturas == []


def test_si_falla_la_relectura_la_entrada_queda_sin_huella_y_se_avisa(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    anotacion = _vigilancia(Aula(falla=True), carpeta, [doc], real=True).anotar_publicado(
        doc, "A.md", 501
    )
    assert anotacion == Anotacion(("REGISTRO_NO_GUARDADO",))
    assert estado.cargar_publicados(carpeta / ".tiza", 5678)["A.md"] == estado.Publicado(
        501, "pagina"
    )


def test_una_ruta_nueva_con_dos_puntos_no_se_registra_ni_se_avisa_pero_guarda_la_base(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    anotacion = _vigilancia(Aula(), carpeta, [doc], real=True).anotar_publicado(doc, "A:b.md", 501)
    assert anotacion == Anotacion()
    assert not (carpeta / ".tiza" / "publicados.json").exists()
    base = estado.ruta_base(carpeta / ".tiza", 5678, 501)
    assert (base / estado.FICHERO_BASE_FUENTE).read_bytes() == doc.ruta.read_bytes()
    assert (base / estado.FICHERO_BASE_ENVIADO).read_text(encoding="utf-8") == (
        contenido.html_para_moodle(doc)
    )


def test_un_registro_danado_da_registro_no_guardado(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    (carpeta / ".tiza").mkdir()
    (carpeta / ".tiza" / "publicados.json").write_text("no es json", encoding="utf-8")
    anotacion = _vigilancia(Aula(), carpeta, [doc], real=False).anotar_publicado(doc, "A.md", 501)
    assert anotacion == Anotacion(("REGISTRO_NO_GUARDADO",))


def test_anotar_fechas_no_escribe_la_entrada_entera(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64)
    estado.guardar_publicado(
        carpeta / ".tiza",
        5678,
        "A.md",
        estado.Publicado(501, "pagina", huella="c" * 64),
    )
    vigilancia, vigilada = _vigilada_de_copia(carpeta, doc)
    assert vigilancia.anotar_fechas(doc, "A.md", vigilada) == Anotacion()
    assert estado.cargar_publicados(carpeta / ".tiza", 5678)["A.md"] == estado.Publicado(
        501, "pagina", huella="c" * 64
    )


# --- R4: la base de lo publicado -----------------------------------------------------------


def test_en_real_guarda_la_base_con_fuente_y_enviado(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    anotacion = _vigilancia(Aula({501: _form(doc)}), carpeta, [doc], real=True).anotar_publicado(
        doc, "A.md", 501
    )
    assert anotacion == Anotacion()
    base = estado.ruta_base(carpeta / ".tiza", 5678, 501)
    assert (base / estado.FICHERO_BASE_FUENTE).read_bytes() == doc.ruta.read_bytes()
    assert (base / estado.FICHERO_BASE_ENVIADO).read_text(encoding="utf-8") == (
        contenido.html_para_moodle(doc)
    )


def test_en_pruebas_no_guarda_base(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    assert (
        _vigilancia(Aula(), carpeta, [doc], real=False).anotar_publicado(doc, "A.md", 501)
        == Anotacion()
    )
    assert not (carpeta / ".tiza" / "publicados").exists()


def test_recreada_guarda_la_base_nueva_antes_de_olvidar_la_vieja(tmp_path, monkeypatch):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    dir_tiza = carpeta / ".tiza"
    estado.guardar_publicado(
        dir_tiza, 5678, "A.md", estado.Publicado(400, "pagina", huella="a" * 64)
    )
    estado.guardar_base(dir_tiza, 5678, 400, b"viejo", "viejo")
    orden = []
    guardar, olvidar = estado.guardar_base, estado.olvidar_base
    monkeypatch.setattr(
        estado, "guardar_base", lambda *a, **k: (orden.append("guardar"), guardar(*a, **k))[1]
    )
    monkeypatch.setattr(
        estado,
        "olvidar_base",
        lambda *a, **k: (orden.append(("olvidar", a[2])), olvidar(*a, **k))[1],
    )
    assert (
        _vigilancia(Aula({501: _form(doc)}), carpeta, [doc], real=True).anotar_publicado(
            doc, "A.md", 501
        )
        == Anotacion()
    )
    assert orden == ["guardar", ("olvidar", 400)]
    assert not estado.ruta_base(dir_tiza, 5678, 400).exists()
    assert estado.ruta_base(dir_tiza, 5678, 501).is_dir()


def test_si_falla_guardar_la_base_no_queda_la_anterior_y_da_base_no_guardada(tmp_path, monkeypatch):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    estado.guardar_base(carpeta / ".tiza", 5678, 501, b"viejo", "viejo")

    def falla(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(estado, "guardar_base", falla)
    anotacion = _vigilancia(Aula({501: _form(doc)}), carpeta, [doc], real=True).anotar_publicado(
        doc, "A.md", 501
    )
    assert anotacion == Anotacion(("BASE_NO_GUARDADA",))
    assert not estado.ruta_base(carpeta / ".tiza", 5678, 501).exists()


def test_fichero_cambiado_tras_cargarlo_no_guarda_base(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    leido = _form(doc)
    doc.ruta.write_text(doc.ruta.read_text(encoding="utf-8") + "\nMás.\n", encoding="utf-8")
    anotacion = _vigilancia(Aula({501: leido}), carpeta, [doc], real=True).anotar_publicado(
        doc, "A.md", 501
    )
    assert anotacion == Anotacion(("BASE_NO_GUARDADA",))
    assert not (carpeta / ".tiza" / "publicados").exists()


def test_registro_danado_no_da_previo_ni_borra_nada(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    dir_tiza = carpeta / ".tiza"
    estado.guardar_base(dir_tiza, 5678, 400, b"viejo", "viejo")
    (dir_tiza / "publicados.json").write_text("no es json", encoding="utf-8")
    anotacion = _vigilancia(Aula(), carpeta, [doc], real=True).anotar_publicado(doc, "A.md", 501)
    assert anotacion == Anotacion(("REGISTRO_NO_GUARDADO",))
    assert estado.ruta_base(dir_tiza, 5678, 400).is_dir()
    assert estado.ruta_base(dir_tiza, 5678, 501).is_dir()


def test_el_previo_con_dos_puntos_se_lee(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    dir_tiza = carpeta / ".tiza"
    dir_tiza.mkdir()
    registro = {
        "version": 1,
        "cursos": {
            "5678": {
                "ficheros": {
                    "A:b.md": {"cmid": 400, "tipo": "pagina", "huella": None, "marca": None}
                }
            }
        },
    }
    (dir_tiza / "publicados.json").write_text(json.dumps(registro), encoding="utf-8")
    estado.guardar_base(dir_tiza, 5678, 400, b"viejo", "viejo")
    anotacion = _vigilancia(Aula({501: _form(doc)}), carpeta, [doc], real=True).anotar_publicado(
        doc, "A:b.md", 501
    )
    assert anotacion == Anotacion()
    assert not estado.ruta_base(dir_tiza, 5678, 400).exists()
    assert estado.ruta_base(dir_tiza, 5678, 501).is_dir()


def test_anotar_fechas_no_guarda_base(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(
        carpeta,
        tipo="tarea",
        publicados={5678: estado.Publicado(501, "tarea", "a" * 64)},
    )
    estado.guardar_publicado(
        carpeta / ".tiza", 5678, "A.md", estado.Publicado(501, "tarea", "a" * 64)
    )
    vigilancia, vigilada = _vigilada_de_registro(carpeta, doc)
    assert vigilancia.anotar_fechas(doc, "A.md", vigilada) == Anotacion()
    assert not (carpeta / ".tiza" / "publicados").exists()


# --- O.1: el orden de las escrituras -------------------------------------------------------


def test_los_fallos_salen_en_el_orden_de_las_escrituras(tmp_path, monkeypatch):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64)

    def falla(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(estado, "guardar_huella_de_copia", falla)
    monkeypatch.setattr(estado, "guardar_publicado", falla)
    monkeypatch.setattr(estado, "guardar_base", falla)
    anotacion = _vigilancia(Aula({501: _form(doc)}), carpeta, [doc], real=True).anotar_publicado(
        doc, "A.md", 501
    )
    assert anotacion.fallos == (
        "HUELLA_NO_GUARDADA",
        "REGISTRO_NO_GUARDADO",
        "BASE_NO_GUARDADA",
    )


def test_renovar_copia_sin_huella_nueva_usa_lo_enviado(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64)
    assert _vigilancia(Aula(), carpeta, [doc], real=False)._renovar_copia(doc)
    esperada = tipos.huella_de_lo_enviado(
        tipos.obtener(doc.tipo), doc, contenido.html_para_moodle(doc)
    )
    assert estado.huellas_de_copia(carpeta / ".tiza", 5678) == {501: esperada}


def test_anotar_con_una_ruta_que_no_vale_no_la_registra_pero_guarda_la_base(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    anotacion = _vigilancia(Aula({501: _form(doc)}), carpeta, [doc], real=True).anotar_publicado(
        doc, "../A.md", 501
    )
    assert anotacion == Anotacion()
    assert not (carpeta / ".tiza" / "publicados.json").exists()
    assert estado.ruta_base(carpeta / ".tiza", 5678, 501).is_dir()


def test_si_la_base_vieja_no_se_puede_olvidar_la_publicacion_sigue(tmp_path, monkeypatch):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    dir_tiza = carpeta / ".tiza"
    estado.guardar_publicado(
        dir_tiza, 5678, "A.md", estado.Publicado(400, "pagina", huella="a" * 64)
    )
    estado.guardar_base(dir_tiza, 5678, 400, b"viejo", "viejo")

    def no_olvida(*_args, **_kwargs):
        raise OSError("no se puede")

    monkeypatch.setattr(estado, "olvidar_base", no_olvida)
    anotacion = _vigilancia(Aula({501: _form(doc)}), carpeta, [doc], real=True).anotar_publicado(
        doc, "A.md", 501
    )
    assert anotacion == Anotacion()
    assert estado.ruta_base(dir_tiza, 5678, 400).is_dir()
    assert estado.ruta_base(dir_tiza, 5678, 501).is_dir()


def test_anotar_publicado_actualiza_una_clave_con_dos_puntos_ya_escrita(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta)
    dir_tiza = carpeta / ".tiza"
    dir_tiza.mkdir()
    registro = {
        "version": 1,
        "cursos": {
            "5678": {
                "ficheros": {
                    "A:b.md": {
                        "cmid": 7,
                        "tipo": "pagina",
                        "huella": "a" * 64,
                        "marca": "b" * 64,
                    }
                }
            }
        },
    }
    (dir_tiza / "publicados.json").write_text(json.dumps(registro), encoding="utf-8")
    leido = _form(doc)
    anotacion = _vigilancia(Aula({501: leido}), carpeta, [doc], real=True).anotar_publicado(
        doc, "A:b.md", 501
    )
    assert anotacion == Anotacion()
    assert estado.cargar_publicados(dir_tiza, 5678)["A:b.md"] == estado.Publicado(
        501, "pagina", _huella(doc, leido), None
    )


def test_anotar_publicado_con_origen_guarda_en_el_registro_la_huella_de_la_copia(tmp_path):
    carpeta = tmp_path.resolve()
    doc = _doc(carpeta, origen=Origen(curso=5678, cmid=501))
    _copia(carpeta, huella="a" * 64, marca=doc.sha256_fichero)
    estado.guardar_publicado(
        carpeta / ".tiza",
        5678,
        "A.md",
        estado.Publicado(501, "pagina", huella="b" * 64, marca=doc.sha256_fichero),
    )
    anotacion = _vigilancia(Aula(falla=True), carpeta, [doc], real=True).anotar_publicado(
        doc, "A.md", 501
    )
    assert anotacion == Anotacion()
    entrada = estado.cargar_publicados(carpeta / ".tiza", 5678)["A.md"]
    assert entrada.huella == estado.huellas_de_copia(carpeta / ".tiza", 5678)[501]
    assert entrada.marca is None
