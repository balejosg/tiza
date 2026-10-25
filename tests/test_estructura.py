"""Tests de ``estructura``: tipos, constructores, localización y orden. Sin aula y sin red."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from tiza import contenido, estado
from tiza.estructura import (
    Actividad,
    ErrorEstructura,
    Estructura,
    Localizacion,
    Seccion,
    aplica_origen,
    nombre_de_seccion,
)


def actividad(cmid: int = 1, nombre: str = "Repaso", tipo: str = "pagina") -> Actividad:
    return Actividad(cmid=cmid, nombre=nombre, tipo=tipo)


def seccion(
    numero: int = 3,
    nombre: str | None = None,
    id_: int = 30,
    actividades: tuple[Actividad, ...] = (),
) -> Seccion:
    return Seccion(
        numero=numero,
        nombre=f"Tema {numero}" if nombre is None else nombre,
        id=id_,
        actividades=actividades,
    )


def aula(*secciones: Seccion) -> Estructura:
    return Estructura(secciones)


def documento(
    tmp_path: Path,
    *,
    nombre: str = "Repaso",
    seccion_: int | str = 3,
    tipo: str = "pagina",
    fichero: str = "pagina.md",
    origen: contenido.Origen | None = None,
    publicados: dict[int, estado.Publicado] | None = None,
) -> contenido.Documento:
    return contenido.Documento(
        ruta=tmp_path / fichero,
        tipo=tipo,
        nombre=nombre,
        seccion=seccion_,
        cuerpo="",
        html="",
        recursos=[],
        origen=origen,
        publicados=publicados or {},
    )


def con_origen(doc: contenido.Documento, curso: int = 5, cmid: int = 501) -> contenido.Documento:
    return dataclasses.replace(doc, origen=contenido.Origen(curso=curso, cmid=cmid))


def con_registro(
    doc: contenido.Documento, curso: int = 5, cmid: int = 7, tipo: str | None = None
) -> contenido.Documento:
    return dataclasses.replace(
        doc, publicados={curso: estado.Publicado(cmid=cmid, tipo=tipo or doc.tipo)}
    )


def modulo_dict(cmid: int = 7, nombre: str = "Repaso", tipo: str = "pagina") -> dict:
    return {"cmid": cmid, "nombre": nombre, "tipo": tipo}


def seccion_dict(
    numero: int = 3,
    nombre: str | None = None,
    id_: int = 30,
    modulos: list[dict] | None = None,
) -> dict:
    return {
        "numero": numero,
        "nombre": f"Tema {numero}" if nombre is None else nombre,
        "id": id_,
        "modulos": [] if modulos is None else modulos,
    }


SECCIONES_AULA = [
    seccion_dict(3, modulos=[modulo_dict(7), modulo_dict(8, "Tarea", "tarea")]),
    seccion_dict(1, id_=10),
]


class TestConstruccion:
    def test_acepta_el_aula_y_conserva_el_orden_y_las_actividades(self):
        estructura = Estructura.de_dicts(SECCIONES_AULA)
        assert [seccion.numero for seccion in estructura] == [3, 1]
        assert len(estructura) == 2
        primera = estructura.secciones[0]
        assert primera.actividades == (
            Actividad(cmid=7, nombre="Repaso", tipo="pagina"),
            Actividad(cmid=8, nombre="Tarea", tipo="tarea"),
        )
        assert primera.cmids == (7, 8)
        assert estructura.secciones[1].actividades == ()

    def test_acepta_la_guardada_y_la_deja_sin_actividades(self):
        estructura = Estructura.de_dicts_guardada(
            [
                {"numero": 3, "nombre": "Tema 3", "id": 30},
                {"numero": 1, "nombre": "Tema 1", "id": 10},
            ]
        )
        assert [seccion.numero for seccion in estructura] == [3, 1]
        assert all(seccion.actividades == () for seccion in estructura)

    def test_tambien_acepta_tuplas(self):
        estructura = Estructura.de_dicts((seccion_dict(3), seccion_dict(1, id_=10)))
        assert [seccion.numero for seccion in estructura] == [3, 1]

    def test_no_ordena_las_secciones(self):
        estructura = Estructura.de_dicts([seccion_dict(3), seccion_dict(1, id_=10)])
        assert [seccion.numero for seccion in estructura] == [3, 1]

    def test_no_impone_unicidad_de_numero_id_ni_cmid(self):
        estructura = Estructura.de_dicts(
            [
                seccion_dict(3, id_=30, modulos=[modulo_dict(7)]),
                seccion_dict(3, id_=30, modulos=[modulo_dict(7)]),
            ]
        )
        assert len(estructura) == 2
        assert [seccion.cmids for seccion in estructura] == [(7,), (7,)]

    def test_sanea_el_nombre_de_la_seccion(self):
        estructura = Estructura.de_dicts(
            [seccion_dict(3, nombre="  Tema <1>\x07  repaso ", modulos=[])]
        )
        assert estructura.secciones[0].nombre == "Tema ‹1› repaso"

    def test_es_inmutable_y_sin_listas_dentro(self):
        estructura = Estructura.de_dicts(SECCIONES_AULA)
        with pytest.raises(dataclasses.FrozenInstanceError):
            estructura.secciones = ()
        with pytest.raises(dataclasses.FrozenInstanceError):
            estructura.secciones[0].nombre = "Otro"
        with pytest.raises(dataclasses.FrozenInstanceError):
            estructura.secciones[0].actividades[0].cmid = 99
        assert isinstance(estructura.secciones, tuple)
        assert all(isinstance(seccion.actividades, tuple) for seccion in estructura)

    def test_seccion_con_id(self):
        estructura = Estructura.de_dicts([seccion_dict(3, id_=30), seccion_dict(1, id_=10)])
        assert estructura.seccion_con_id(10) is estructura.secciones[1]
        assert estructura.seccion_con_id(20) is None


@pytest.mark.parametrize(
    "secciones",
    [
        None,
        {"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []},
        "no es una lista",
        [None],
        [["no es un mapa"]],
        [{"nombre": "Tema 3", "id": 30, "modulos": []}],
        [{"numero": True, "nombre": "Tema 3", "id": 30, "modulos": []}],
        [{"numero": "3", "nombre": "Tema 3", "id": 30, "modulos": []}],
        [{"numero": 3.0, "nombre": "Tema 3", "id": 30, "modulos": []}],
        [{"numero": 3, "nombre": "Tema 3", "modulos": []}],
        [{"numero": 3, "nombre": "Tema 3", "id": True, "modulos": []}],
        [{"numero": 3, "nombre": "Tema 3", "id": "30", "modulos": []}],
        [{"numero": 3, "id": 30, "modulos": []}],
        [{"numero": 3, "nombre": 30, "id": 30, "modulos": []}],
        [{"numero": 3, "nombre": "Tema 3", "id": 30}],
        [{"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": None}],
        [{"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": {}}],
        [{"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": "no"}],
        [{"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": [None]}],
        [{"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": [["no"]]}],
        [
            {
                "numero": 3,
                "nombre": "Tema 3",
                "id": 30,
                "modulos": [{"nombre": "Repaso", "tipo": "pagina"}],
            }
        ],
        [
            {
                "numero": 3,
                "nombre": "Tema 3",
                "id": 30,
                "modulos": [{"cmid": True, "nombre": "Repaso", "tipo": "pagina"}],
            }
        ],
        [
            {
                "numero": 3,
                "nombre": "Tema 3",
                "id": 30,
                "modulos": [{"cmid": "7", "nombre": "Repaso", "tipo": "pagina"}],
            }
        ],
        [
            {
                "numero": 3,
                "nombre": "Tema 3",
                "id": 30,
                "modulos": [{"cmid": 7, "tipo": "pagina"}],
            }
        ],
        [
            {
                "numero": 3,
                "nombre": "Tema 3",
                "id": 30,
                "modulos": [{"cmid": 7, "nombre": 7, "tipo": "pagina"}],
            }
        ],
        [
            {
                "numero": 3,
                "nombre": "Tema 3",
                "id": 30,
                "modulos": [{"cmid": 7, "nombre": "Repaso"}],
            }
        ],
        [
            {
                "numero": 3,
                "nombre": "Tema 3",
                "id": 30,
                "modulos": [{"cmid": 7, "nombre": "Repaso", "tipo": 7}],
            }
        ],
    ],
)
def test_rechaza_las_formas_invalidas_del_aula(secciones):
    with pytest.raises(ErrorEstructura) as exc:
        Estructura.de_dicts(secciones)
    assert exc.value.codigo == "ESTRUCTURA_DEL_AULA_INVALIDA"
    assert exc.value.detalle


@pytest.mark.parametrize(
    "secciones",
    [
        None,
        "no es una lista",
        [None],
        [["no es un mapa"]],
        [{"nombre": "Tema 3", "id": 30}],
        [{"numero": True, "nombre": "Tema 3", "id": 30}],
        [{"numero": "3", "nombre": "Tema 3", "id": 30}],
        [{"numero": 3, "nombre": "Tema 3"}],
        [{"numero": 3, "nombre": "Tema 3", "id": True}],
        [{"numero": 3, "nombre": "Tema 3", "id": "30"}],
        [{"numero": 3, "id": 30}],
        [{"numero": 3, "nombre": 30, "id": 30}],
        [{"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []}],
    ],
)
def test_rechaza_las_formas_invalidas_de_la_guardada(secciones):
    with pytest.raises(ErrorEstructura) as exc:
        Estructura.de_dicts_guardada(secciones)
    assert exc.value.codigo == "ESTRUCTURA_DEL_AULA_INVALIDA"
    assert exc.value.detalle


def test_el_detalle_no_lleva_valores_del_aula():
    with pytest.raises(ErrorEstructura) as exc:
        Estructura.de_dicts([{"numero": 3, "nombre": "<script> SECRETO \x00", "modulos": []}])
    assert "SECRETO" not in exc.value.detalle
    assert "<script>" not in exc.value.detalle
    assert "\x00" not in exc.value.detalle


class TestBuscarSeccion:
    def test_por_numero(self):
        estructura = aula(seccion(1, id_=10), seccion(3, id_=30))
        assert estructura.buscar_seccion(3) is estructura.secciones[1]
        assert estructura.buscar_seccion(2) is None

    def test_por_nombre_sin_distinguir_mayusculas(self):
        estructura = aula(seccion(3, "Proyecto", 9))
        assert estructura.buscar_seccion("proyecto") is estructura.secciones[0]
        assert estructura.buscar_seccion("PROYECTO") is estructura.secciones[0]
        assert estructura.buscar_seccion("Otra") is None

    def test_normaliza_el_nombre_en_los_dos_lados(self):
        guardada = Estructura.de_dicts_guardada([{"numero": 3, "nombre": " Tema  1 ", "id": 30}])
        assert guardada.buscar_seccion("Tema 1").id == 30
        # Aunque la sección se construya a mano con el nombre sin sanear.
        bruta = aula(Seccion(numero=3, nombre="Tema  1", id=30))
        assert bruta.buscar_seccion("Tema  1").id == 30

    def test_una_seccion_sin_actividades_tambien_se_encuentra(self):
        estructura = Estructura.de_dicts_guardada([{"numero": 3, "nombre": "Tema 3", "id": 30}])
        assert estructura.buscar_seccion(3).actividades == ()


def test_nombre_de_seccion_sanea_angulos_y_controles():
    assert nombre_de_seccion("Tema <1>\x07  repaso") == "Tema ‹1› repaso"


class TestLocalizar:
    def test_el_origen_halla_aunque_cambien_el_nombre_y_la_seccion(self, tmp_path):
        estructura = aula(
            seccion(2, id_=20, actividades=(actividad(501, "Viejo"),)),
            seccion(3, id_=30),
        )
        doc = con_origen(documento(tmp_path), 5, 501)
        loc = estructura.localizar(doc, 5)
        assert (loc.seccion.id, loc.modulo.cmid, loc.por) == (20, 501, "origen")
        assert loc.actividad is loc.modulo
        assert loc.problema is None

    def test_el_origen_ausente_es_problema(self, tmp_path):
        estructura = aula(seccion(3, id_=30))
        loc = estructura.localizar(con_origen(documento(tmp_path), 5, 999), 5)
        assert loc.problema == "ORIGEN_NO_ENCONTRADO"
        assert (loc.seccion, loc.modulo, loc.por) == (None, None, None)
        assert (loc.borrada, loc.varios, loc.actividad) == (False, False, None)

    def test_el_origen_de_otro_tipo_es_problema(self, tmp_path):
        estructura = aula(seccion(2, id_=20, actividades=(actividad(501, "Viejo", "tarea"),)))
        loc = estructura.localizar(con_origen(documento(tmp_path), 5, 501), 5)
        assert loc.problema == "ORIGEN_NO_ENCONTRADO"
        assert loc.actividad is None

    @pytest.mark.parametrize(("curso_origen", "curso"), [(4, 5), (5, None)])
    def test_el_origen_de_otro_curso_o_sin_curso_se_ignora(self, tmp_path, curso_origen, curso):
        estructura = aula(
            seccion(2, id_=20, actividades=(actividad(501, "Viejo"),)),
            seccion(3, id_=30),
        )
        doc = con_origen(documento(tmp_path), curso_origen, 501)
        loc = estructura.localizar(doc, curso)
        assert (loc.por, loc.modulo, loc.seccion.id) == (None, None, 30)

    def test_el_registro_halla_con_otro_nombre_y_en_otra_seccion(self, tmp_path):
        estructura = aula(
            seccion(2, id_=20, actividades=(actividad(7, "Viejo"),)),
            seccion(3, id_=30, actividades=(actividad(8, "Otra"),)),
        )
        loc = estructura.localizar(con_registro(documento(tmp_path), 5, 7), 5)
        assert (loc.seccion.id, loc.modulo.cmid, loc.por) == (20, 7, "registro")
        assert loc.actividad is loc.modulo
        assert loc.problema is None

    def test_el_registro_gana_al_nombre_en_otra_seccion(self, tmp_path):
        estructura = aula(
            seccion(2, id_=20, actividades=(actividad(7, "Viejo"),)),
            seccion(3, id_=30, actividades=(actividad(8, "Otra"),)),
            seccion(4, id_=40, actividades=(actividad(9, "Repaso"),)),
        )
        loc = estructura.localizar(con_registro(documento(tmp_path), 5, 7), 5)
        assert (loc.modulo.cmid, loc.por) == (7, "registro")

    def test_el_registro_con_nombre_en_conflicto_es_problema(self, tmp_path):
        estructura = aula(
            seccion(3, id_=30, actividades=(actividad(7, "Viejo"), actividad(8, "Repaso")))
        )
        loc = estructura.localizar(con_registro(documento(tmp_path), 5, 7), 5)
        assert loc.problema == "ACTIVIDAD_AMBIGUA"
        assert (loc.seccion, loc.modulo, loc.por) == (None, None, None)
        assert (loc.borrada, loc.varios, loc.actividad) == (False, False, None)

    def test_el_registro_con_su_mismo_nombre_no_es_conflicto(self, tmp_path):
        estructura = aula(
            seccion(3, id_=30, actividades=(actividad(7, "Repaso"), actividad(9, "Repaso")))
        )
        loc = estructura.localizar(con_registro(documento(tmp_path), 5, 7), 5)
        assert (loc.modulo.cmid, loc.por, loc.varios) == (7, "registro", False)
        assert loc.problema is None

    @pytest.mark.parametrize(
        "actividades",
        [
            (actividad(8, "Otra"),),
            (actividad(7, "Viejo", "tarea"),),
        ],
    )
    def test_el_registro_de_un_cmid_que_ya_no_esta_o_es_de_otro_tipo(self, tmp_path, actividades):
        estructura = aula(seccion(3, id_=30, actividades=actividades))
        loc = estructura.localizar(con_registro(documento(tmp_path), 5, 7), 5)
        assert (loc.modulo, loc.por, loc.borrada) == (None, None, True)
        assert loc.seccion.id == 30
        assert loc.problema is None

    def test_el_registro_borrado_pero_hallado_por_nombre_no_esta_borrada(self, tmp_path):
        estructura = aula(seccion(3, id_=30, actividades=(actividad(8, "Repaso"),)))
        loc = estructura.localizar(con_registro(documento(tmp_path), 5, 7), 5)
        assert (loc.modulo.cmid, loc.por, loc.borrada) == (8, "nombre", False)

    @pytest.mark.parametrize("curso", [None, 6])
    def test_sin_curso_o_con_otro_curso_se_ignora_el_registro(self, tmp_path, curso):
        estructura = aula(
            seccion(2, id_=20, actividades=(actividad(7, "Viejo"),)),
            seccion(3, id_=30),
        )
        loc = estructura.localizar(con_registro(documento(tmp_path), 5, 7), curso)
        assert (loc.modulo, loc.por, loc.borrada) == (None, None, False)
        assert loc.seccion.id == 30

    @pytest.mark.parametrize(
        ("actividades", "varios"), [((actividad(7),), False), ((actividad(7), actividad(9)), True)]
    )
    def test_el_nombre_en_su_seccion_da_la_primera_y_marca_varios(
        self, tmp_path, actividades, varios
    ):
        estructura = aula(seccion(3, id_=30, actividades=actividades))
        loc = estructura.localizar(documento(tmp_path), 5)
        assert (loc.seccion.id, loc.modulo.cmid, loc.por) == (30, 7, "nombre")
        assert loc.varios is varios
        assert loc.actividad is loc.modulo

    def test_el_nombre_en_otra_seccion_si_solo_hay_una(self, tmp_path):
        estructura = aula(seccion(2, id_=20, actividades=(actividad(8),)))
        loc = estructura.localizar(documento(tmp_path), 5)
        assert (loc.seccion.id, loc.modulo.cmid, loc.por) == (20, 8, "otra_seccion")
        assert loc.varios is False
        assert loc.actividad is None

    def test_varias_en_otras_secciones_no_dan_modulo(self, tmp_path):
        estructura = aula(
            seccion(2, id_=20, actividades=(actividad(8),)),
            seccion(4, id_=40, actividades=(actividad(9),)),
        )
        loc = estructura.localizar(documento(tmp_path), 5)
        assert (loc.modulo, loc.por, loc.varios, loc.seccion) == (
            None,
            "otra_seccion",
            True,
            None,
        )
        assert loc.actividad is None

    @pytest.mark.parametrize(("seccion_", "id_esperado"), [(3, 30), (99, None)])
    def test_nada_es_nueva_con_o_sin_seccion_propia(self, tmp_path, seccion_, id_esperado):
        estructura = aula(seccion(3, id_=30))
        loc = estructura.localizar(documento(tmp_path, seccion_=seccion_), 5)
        assert (loc.modulo, loc.por, loc.borrada, loc.varios) == (None, None, False, False)
        assert (loc.seccion.id if loc.seccion is not None else None) == id_esperado
        assert loc.problema is None

    def test_el_origen_manda_sobre_el_registro(self, tmp_path):
        estructura = aula(
            seccion(2, id_=20, actividades=(actividad(501, "Viejo"), actividad(7, "Otro")))
        )
        doc = con_registro(con_origen(documento(tmp_path), 5, 501), 5, 7)
        loc = estructura.localizar(doc, 5)
        assert (loc.modulo.cmid, loc.por) == (501, "origen")

    def test_el_cmid_repetido_en_dos_secciones_el_origen_sigue_buscando(self, tmp_path):
        estructura = aula(
            seccion(2, id_=20, actividades=(actividad(500, "Primera", "tarea"),)),
            seccion(3, id_=30, actividades=(actividad(500, "Segunda", "pagina"),)),
        )
        loc = estructura.localizar(con_origen(documento(tmp_path), 5, 500), 5)
        assert (loc.seccion.id, loc.modulo.nombre, loc.por) == (30, "Segunda", "origen")

    def test_el_cmid_repetido_en_dos_secciones_el_registro_no_sigue(self, tmp_path):
        estructura = aula(
            seccion(2, id_=20, actividades=(actividad(500, "Primera", "tarea"),)),
            seccion(3, id_=30, actividades=(actividad(500, "Segunda", "pagina"),)),
        )
        loc = estructura.localizar(con_registro(documento(tmp_path), 5, 500), 5)
        assert (loc.modulo, loc.por, loc.borrada) == (None, None, True)

    def test_los_invariantes_de_localizacion(self, tmp_path):
        problema = Localizacion(None, None, None, problema="ACTIVIDAD_AMBIGUA")
        nueva = Localizacion(seccion(3), None, None)
        otra = Localizacion(seccion(2), actividad(), "otra_seccion")
        varias = Localizacion(None, None, "otra_seccion", varios=True)
        por_nombre = Localizacion(seccion(3), actividad(), "nombre")
        for loc in (problema, nueva, otra, varias, por_nombre):
            if loc.problema is not None:
                assert (loc.seccion, loc.modulo, loc.por) == (None, None, None)
                assert (loc.borrada, loc.varios) == (False, False)
            if loc.por in ("origen", "registro", "nombre"):
                assert loc.modulo is not None and loc.seccion is not None
            if loc.por == "otra_seccion" and loc.modulo is None:
                assert loc.varios is True and loc.seccion is None
            if loc.por is None:
                assert loc.modulo is None

    @pytest.mark.parametrize(
        ("estructura", "esperado"),
        [
            (aula(seccion(3)), "ORIGEN_NO_ENCONTRADO"),
            (
                aula(seccion(3, actividades=(actividad(7, "Viejo"), actividad(8, "Repaso")))),
                "ORIGEN_NO_ENCONTRADO",
            ),
            (
                aula(
                    seccion(2, actividades=(actividad(501, "Repaso"),)),
                    seccion(3, actividades=(actividad(7, "Viejo"), actividad(8, "Repaso"))),
                ),
                "ORIGEN_NO_ENCONTRADO",
            ),
            (aula(seccion(3, actividades=(actividad(999, "Repaso"),))), None),
        ],
    )
    def test_con_origen_el_problema_solo_puede_ser_origen_no_encontrado(
        self, tmp_path, estructura, esperado
    ):
        # La propiedad de ``_separar_rechazados``: si ``aplica_origen`` es verdadero, el paso
        # del registro (el único que da ACTIVIDAD_AMBIGUA) no llega a ejecutarse.
        doc = con_registro(con_origen(documento(tmp_path), 5, 999), 5, 7)
        assert aplica_origen(doc, 5)
        loc = estructura.localizar(doc, 5)
        assert loc.problema == esperado


class TestYaExiste:
    def test_documento_nuevo_es_falso(self, tmp_path):
        estructura = aula(seccion(3))
        assert estructura.ya_existe(documento(tmp_path)) is False

    def test_mismo_tipo_y_nombre_en_su_seccion_es_verdadero(self, tmp_path):
        estructura = aula(seccion(3, actividades=(actividad(100),)))
        assert estructura.ya_existe(documento(tmp_path)) is True

    @pytest.mark.parametrize(
        "actividades",
        [
            (actividad(100, "Repaso", "tarea"),),
            (actividad(101, "Otro", "pagina"),),
        ],
    )
    def test_otro_tipo_u_otro_nombre_no_cuenta(self, tmp_path, actividades):
        estructura = aula(seccion(3, actividades=actividades))
        assert estructura.ya_existe(documento(tmp_path)) is False

    def test_si_la_seccion_no_existe_es_falso(self, tmp_path):
        estructura = aula(seccion(3))
        assert estructura.ya_existe(documento(tmp_path, seccion_=99)) is False

    def test_el_origen_y_el_registro_son_verdadero(self, tmp_path):
        por_origen = aula(seccion(2, actividades=(actividad(501, "Viejo"),)))
        assert por_origen.ya_existe(con_origen(documento(tmp_path), 5, 501), 5) is True
        por_registro = aula(seccion(2, actividades=(actividad(7, "Viejo"),)))
        assert por_registro.ya_existe(con_registro(documento(tmp_path), 5, 7), 5) is True

    def test_un_problema_da_nada(self, tmp_path):
        ambiguo = aula(seccion(3, actividades=(actividad(7, "Viejo"), actividad(8, "Repaso"))))
        assert ambiguo.ya_existe(con_registro(documento(tmp_path), 5, 7), 5) is None
        perdido = aula(seccion(3))
        assert perdido.ya_existe(con_origen(documento(tmp_path), 5, 999), 5) is None


class TestDesdeDondeSeMueve:
    def test_el_origen_en_otra_seccion(self, tmp_path):
        estructura = aula(seccion(2, actividades=(actividad(55),)))
        assert estructura.desde_donde_se_mueve(con_origen(documento(tmp_path), 5, 55), 5) == (
            "Tema 2"
        )

    def test_el_registro_en_otra_seccion(self, tmp_path):
        estructura = aula(seccion(2, actividades=(actividad(55, "Viejo"),)))
        assert estructura.desde_donde_se_mueve(con_registro(documento(tmp_path), 5, 55), 5) == (
            "Tema 2"
        )

    def test_el_nombre_en_otra_seccion(self, tmp_path):
        estructura = aula(seccion(2, actividades=(actividad(55),)))
        assert estructura.desde_donde_se_mueve(documento(tmp_path), 5) == "Tema 2"

    def test_el_registro_en_su_seccion_no_se_mueve(self, tmp_path):
        estructura = aula(seccion(3, actividades=(actividad(55, "Viejo"),)))
        assert estructura.desde_donde_se_mueve(con_registro(documento(tmp_path), 5, 55), 5) is None

    def test_el_origen_en_su_seccion_no_se_mueve(self, tmp_path):
        estructura = aula(seccion(3, actividades=(actividad(55),)))
        assert estructura.desde_donde_se_mueve(con_origen(documento(tmp_path), 5, 55), 5) is None

    def test_el_nombre_en_su_seccion_no_se_mueve(self, tmp_path):
        estructura = aula(seccion(3, actividades=(actividad(55),)))
        assert estructura.desde_donde_se_mueve(documento(tmp_path), 5) is None

    def test_varias_en_otras_secciones_no_se_mueve(self, tmp_path):
        estructura = aula(
            seccion(2, actividades=(actividad(55),)),
            seccion(4, actividades=(actividad(56),)),
        )
        assert estructura.desde_donde_se_mueve(documento(tmp_path), 5) is None

    def test_un_problema_no_se_mueve(self, tmp_path):
        estructura = aula(seccion(3))
        assert estructura.desde_donde_se_mueve(con_origen(documento(tmp_path), 5, 999), 5) is None

    def test_sin_seccion_propia_el_origen_se_mueve(self, tmp_path):
        estructura = aula(seccion(2, actividades=(actividad(55),)))
        doc = con_origen(documento(tmp_path, seccion_=99), 5, 55)
        assert estructura.desde_donde_se_mueve(doc, 5) == "Tema 2"

    def test_una_seccion_sin_nombre_da_texto_vacio(self, tmp_path):
        estructura = aula(seccion(2, nombre="", actividades=(actividad(55),)))
        assert estructura.desde_donde_se_mueve(documento(tmp_path), 5) == ""


class TestSeccionesQueFaltan:
    def test_sin_duplicados_ignorando_mayusculas(self, tmp_path):
        estructura = Estructura.de_dicts_guardada([{"numero": 3, "nombre": "Tema 3", "id": 30}])
        docs = [
            documento(tmp_path, seccion_="Tema 3", fichero="a.md"),
            documento(tmp_path, seccion_="tema 3", fichero="b.md"),
            documento(tmp_path, seccion_="Tema 4", fichero="c.md"),
            documento(tmp_path, seccion_="TEMA 4", fichero="d.md"),
            documento(tmp_path, seccion_="Tema 5", fichero="e.md"),
        ]
        assert estructura.secciones_que_faltan(docs) == ["Tema 4", "Tema 5"]

    def test_la_clave_numerica_no_cuenta(self, tmp_path):
        estructura = aula(seccion(3))
        assert estructura.secciones_que_faltan([documento(tmp_path, seccion_=99)]) == []

    def test_el_nombre_guardado_se_compara_saneado(self, tmp_path):
        estructura = Estructura.de_dicts_guardada([{"numero": 3, "nombre": " Tema  3 ", "id": 30}])
        assert estructura.secciones_que_faltan([documento(tmp_path, seccion_="tema  3")]) == []

    def test_sin_documentos_no_falta_nada(self):
        assert aula(seccion(3)).secciones_que_faltan([]) == []


class TestResolverOrden:
    def test_grupos_en_orden_de_primera_aparicion_y_el_origen_manda_su_seccion(self, tmp_path):
        estructura = aula(
            seccion(3, id_=30, actividades=(actividad(1),)),
            seccion(4, id_=40, actividades=(actividad(7, "Cambiada"),)),
        )
        docs = [
            con_origen(documento(tmp_path, nombre="Renombrada", fichero="origen.md"), 5, 7),
            documento(tmp_path, nombre="Repaso", fichero="propia.md"),
        ]
        resolucion = estructura.resolver_orden(docs, 5)
        assert resolucion.problema is None
        assert [
            (seccion.id, [actividad.cmid for _, actividad in par])
            for seccion, par in resolucion.grupos
        ] == [
            (40, [7]),
            (30, [1]),
        ]
        assert resolucion.grupos[0][1][0][1] == Actividad(7, "Cambiada", "pagina")

    def test_fichero_repetido(self, tmp_path):
        estructura = aula(seccion(3, actividades=(actividad(1),)))
        docs = [
            documento(tmp_path, fichero="pagina.md"),
            documento(tmp_path, fichero="pagina.md"),
        ]
        resolucion = estructura.resolver_orden(docs, 5)
        assert resolucion.grupos == ()
        assert resolucion.problema == ("FICHERO_REPETIDO", "pagina.md")

    def test_actividad_ausente(self, tmp_path):
        estructura = aula(seccion(3))
        resolucion = estructura.resolver_orden([documento(tmp_path)], 5)
        assert resolucion.grupos == ()
        assert resolucion.problema == ("ACTIVIDAD_AUSENTE", "pagina.md")

    def test_actividad_ambigua_por_varios(self, tmp_path):
        estructura = aula(seccion(3, actividades=(actividad(7), actividad(9))))
        resolucion = estructura.resolver_orden([documento(tmp_path)], 5)
        assert resolucion.grupos == ()
        assert resolucion.problema == ("ACTIVIDAD_AMBIGUA", "pagina.md")

    def test_actividad_ambigua_por_cmid_repetido_entre_documentos(self, tmp_path):
        estructura = aula(seccion(3, actividades=(actividad(7),)))
        docs = [
            documento(tmp_path, fichero="a.md"),
            con_registro(documento(tmp_path, fichero="b.md", nombre="Otro"), 5, 7),
        ]
        resolucion = estructura.resolver_orden(docs, 5)
        assert resolucion.grupos == ()
        assert resolucion.problema == ("ACTIVIDAD_AMBIGUA", "b.md")

    def test_origen_no_encontrado(self, tmp_path):
        estructura = aula(seccion(3))
        resolucion = estructura.resolver_orden([con_origen(documento(tmp_path), 5, 999)], 5)
        assert resolucion.grupos == ()
        assert resolucion.problema == ("ORIGEN_NO_ENCONTRADO", "pagina.md")

    @pytest.mark.parametrize(
        ("orden", "esperado"),
        [
            (("origen", "ausente"), "ORIGEN_NO_ENCONTRADO"),
            (("ausente", "origen"), "ACTIVIDAD_AUSENTE"),
        ],
    )
    def test_el_primer_problema_en_orden_de_documentos_gana(self, tmp_path, orden, esperado):
        estructura = aula(seccion(3))
        disponibles = {
            "origen": con_origen(documento(tmp_path, fichero="origen.md"), 5, 999),
            "ausente": documento(tmp_path, fichero="ausente.md"),
        }
        resolucion = estructura.resolver_orden([disponibles[nombre] for nombre in orden], 5)
        assert resolucion.grupos == ()
        assert resolucion.problema == (esperado, f"{orden[0]}.md")


@pytest.mark.parametrize(
    "secciones",
    [
        (),
        (Seccion(3, "Tema 3", 30),),
        (
            Seccion(3, "Tema 3", 30, (Actividad(7, "Repaso", "pagina"),)),
            Seccion(1, "Tema 1", 10, (Actividad(8, "Tarea", "tarea"),)),
        ),
    ],
)
def test_sin_actividades_proyecta_la_misma_estructura_sin_actividades(secciones):
    original = Estructura(secciones)
    proyectada = original.sin_actividades()
    assert isinstance(proyectada, Estructura)
    assert [(s.numero, s.nombre, s.id) for s in proyectada] == [
        (s.numero, s.nombre, s.id) for s in original
    ]
    assert all(seccion.actividades == () for seccion in proyectada)
    # La original no cambia.
    assert [seccion.actividades for seccion in original] == [
        seccion.actividades for seccion in secciones
    ]


@pytest.mark.parametrize(
    ("seccion_", "esperado"),
    [
        (Seccion(1, "Tema 1", 10), {"numero": 1, "nombre": "Tema 1", "id": 10}),
        (
            Seccion(3, "Tema ‹3›", 30, (Actividad(7, "Repaso", "pagina"),)),
            {"numero": 3, "nombre": "Tema ‹3›", "id": 30},
        ),
    ],
)
def test_para_fichero_solo_lleva_las_tres_claves(seccion_, esperado):
    fichero = seccion_.para_fichero()
    assert fichero == esperado
    assert set(fichero) == {"numero", "nombre", "id"}
