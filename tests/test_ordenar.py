"""Orden y movimiento de actividades: el plan, ``ordenar_documentos`` y mover al cambiar ``seccion:``."""

from __future__ import annotations

import random

import pytest

from dobles import MoodleFalso
from tiza import contenido, publicar
from tiza.publicar import ErrorPublicacion, Movimiento, plan_de_orden


def seccion(id_, cmids, numero=None):
    return {
        "numero": numero if numero is not None else id_ // 10,
        "nombre": f"Tema {id_ // 10}",
        "id": id_,
        "modulos": [{"cmid": c, "nombre": f"A{c}", "tipo": "pagina"} for c in cmids],
    }


def aplicar(secciones, movimientos):
    """Lo que haría el aula con los movimientos; devuelve el orden de cada sección por id."""
    moodle = MoodleFalso(secciones=secciones)
    for movimiento in movimientos:
        moodle.mover(1, *movimiento)
    return {s["id"]: [m["cmid"] for m in s["modulos"]] for s in secciones}


class TestPlanDeOrden:
    def test_el_ejemplo_de_los_huecos(self):
        # [Foro, quiz, Archivo, intro, tarea] con «intro tarea quiz» → [Foro, intro, Archivo, tarea, quiz]
        secciones = [seccion(30, [1, 2, 3, 4, 5])]
        movimientos = plan_de_orden(secciones, [(30, [4, 5, 2])])
        assert aplicar(secciones, movimientos) == {30: [1, 4, 3, 5, 2]}

    def test_lo_no_nombrado_no_se_mueve(self):
        secciones = [seccion(30, [1, 2, 3, 4, 5])]
        movimientos = plan_de_orden(secciones, [(30, [5, 2])])
        assert {m.cmid for m in movimientos} <= {2, 5}
        assert aplicar(secciones, movimientos) == {30: [1, 5, 3, 4, 2]}

    def test_ya_ordenado_no_mueve_nada(self):
        secciones = [seccion(30, [1, 2, 3, 4])]
        assert plan_de_orden(secciones, [(30, [2, 4])]) == []
        assert plan_de_orden(secciones, [(30, [1, 2, 3, 4])]) == []

    def test_un_solo_elemento_no_mueve_nada(self):
        assert plan_de_orden([seccion(30, [1, 2, 3])], [(30, [2])]) == []

    def test_el_ultimo_de_la_seccion_va_al_final(self):
        secciones = [seccion(30, [1, 2, 3])]
        movimientos = plan_de_orden(secciones, [(30, [3, 1])])
        assert aplicar(secciones, movimientos) == {30: [3, 2, 1]}
        assert movimientos[0] == Movimiento(1, 30, None)

    def test_varias_secciones(self):
        secciones = [seccion(30, [1, 2, 3]), seccion(40, [4, 5, 6])]
        movimientos = plan_de_orden(secciones, [(30, [3, 2]), (40, [6, 5, 4])])
        assert aplicar(secciones, movimientos) == {30: [1, 3, 2], 40: [6, 5, 4]}

    @pytest.mark.parametrize("semilla", range(40))
    def test_cualquier_orden_converge_y_repetirlo_no_mueve(self, semilla):
        azar = random.Random(semilla)
        cmids = list(range(1, azar.randint(2, 9)))
        nombrados = azar.sample(cmids, azar.randint(1, len(cmids)))
        secciones = [seccion(30, cmids)]
        movimientos = plan_de_orden(secciones, [(30, nombrados)])
        obtenido = aplicar(secciones, movimientos)[30]
        esperado = publicar.orden_final(cmids, nombrados)
        assert obtenido == esperado
        assert plan_de_orden([seccion(30, obtenido)], [(30, nombrados)]) == []
        assert len(movimientos) <= len(nombrados)


def documento(tmp_path, nombre="Repaso", seccion_=3, fichero=None, tipo="pagina"):
    ruta = tmp_path / (fichero or f"{nombre.lower().replace(' ', '-')}.md")
    extra = "apertura: 2049-01-01\nentrega: 2049-01-02\n" if tipo == "tarea" else ""
    ruta.write_text(
        f"---\ntipo: {tipo}\nnombre: {nombre}\nseccion: {seccion_}\n{extra}---\n\nTexto\n",
        encoding="utf-8",
    )
    return contenido.cargar(ruta)


def aula(*cmids, seccion_id=30):
    """Un aula con páginas «P<cmid>» en el orden dado."""
    return MoodleFalso(
        secciones=[
            {
                "numero": 3,
                "nombre": "Tema 3",
                "id": seccion_id,
                "modulos": [{"cmid": c, "nombre": f"P{c}", "tipo": "pagina"} for c in cmids],
            }
        ]
    )


class TestOrdenarDocumentos:
    def test_ordena_y_relee(self, tmp_path):
        moodle = aula(1, 2, 3)
        docs = [documento(tmp_path, f"P{c}") for c in (3, 1)]
        ficheros = publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert [m["cmid"] for m in moodle.secciones[0]["modulos"]] == [3, 2, 1]
        assert [(f.nombre, f.accion, f.cmid) for f in ficheros] == [
            ("p3.md", "ordenada", 3),
            ("p1.md", "ordenada", 1),
        ]
        assert ficheros[0].seccion == "Tema 3"
        assert ficheros[0].oculto is None
        assert ficheros[0].url.endswith("/mod/page/view.php?id=3")
        assert ("estructura", 1234) in moodle.llamadas  # releyó

    def test_ya_ordenado_no_llama_al_aula(self, tmp_path):
        moodle = aula(1, 2, 3)
        docs = [documento(tmp_path, f"P{c}") for c in (1, 3)]
        ficheros = publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert {f.accion for f in ficheros} == {"sin_cambios"}
        assert not [x for x in moodle.llamadas if x[0] in ("mover", "estructura")]

    def test_actividad_ausente_no_mueve_nada(self, tmp_path):
        moodle = aula(1, 2)
        docs = [documento(tmp_path, "P2"), documento(tmp_path, "Otra")]
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert (exc.value.codigo, exc.value.detalle) == ("ACTIVIDAD_AUSENTE", "otra.md")
        assert not [x for x in moodle.llamadas if x[0] == "mover"]

    def test_actividad_ambigua(self, tmp_path):
        moodle = aula(1, 2)
        moodle.secciones[0]["modulos"].append({"cmid": 9, "nombre": "P1", "tipo": "pagina"})
        docs = [documento(tmp_path, "P1"), documento(tmp_path, "P2")]
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert exc.value.codigo == "ACTIVIDAD_AMBIGUA"

    def test_dos_ficheros_para_la_misma_actividad(self, tmp_path):
        moodle = aula(1, 2)
        docs = [
            documento(tmp_path, "P1", fichero="a.md"),
            documento(tmp_path, "P1", fichero="b.md"),
        ]
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert exc.value.codigo == "ACTIVIDAD_AMBIGUA"

    def test_fichero_repetido(self, tmp_path):
        moodle = aula(1, 2)
        doc = documento(tmp_path, "P1")
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.ordenar_documentos(moodle, 1234, moodle.secciones, [doc, doc])
        assert exc.value.codigo == "FICHERO_REPETIDO"

    def test_orden_no_aplicado_si_el_aula_no_lo_hace(self, tmp_path):
        moodle = aula(1, 2, 3)
        moodle.mover_sin_efecto = True
        docs = [documento(tmp_path, f"P{c}") for c in (3, 1)]
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert exc.value.codigo == "ORDEN_NO_APLICADO"

    def test_error_mover(self, tmp_path):
        moodle = aula(1, 2, 3)
        moodle.mover_falla = True
        docs = [documento(tmp_path, f"P{c}") for c in (3, 1)]
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert exc.value.codigo == "ERROR_MOVER"

    def test_varias_secciones(self, tmp_path):
        moodle = aula(1, 2)
        moodle.secciones.append(
            {
                "numero": 4,
                "nombre": "Tema 4",
                "id": 40,
                "modulos": [{"cmid": c, "nombre": f"Q{c}", "tipo": "pagina"} for c in (7, 8)],
            }
        )
        docs = [
            documento(tmp_path, "P2"),
            documento(tmp_path, "P1"),
            documento(tmp_path, "Q8", seccion_=4),
            documento(tmp_path, "Q7", seccion_=4),
        ]
        ficheros = publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert [[m["cmid"] for m in s["modulos"]] for s in moodle.secciones] == [[2, 1], [8, 7]]
        assert {f.accion for f in ficheros} == {"ordenada"}


class TestMoodleMover:
    def _moodle(self, respuesta):
        enviados = []

        class Respuesta:
            def raise_for_status(self):
                pass

            def json(self):
                return respuesta

        class Sesion:
            def post(self, url, json=None, timeout=None):
                enviados.append(json)
                return Respuesta()

            def get(self, *a, **k):
                raise AssertionError("no debe consultar nada más")

        return publicar.Moodle("https://aula", Sesion(), "clave", pausa=0), enviados

    def test_usa_cm_move_con_destino_y_antes_de(self):
        moodle, enviados = self._moodle([{"error": False}])
        moodle.mover(838, 57073, 30, 57074)
        assert enviados[0][0]["args"] == {
            "action": "cm_move",
            "courseid": "838",
            "ids": ["57073"],
            "targetsectionid": "30",
            "targetcmid": "57074",
        }

    def test_sin_antes_de_va_al_final_de_la_seccion(self):
        moodle, enviados = self._moodle([{"error": False}])
        moodle.mover(838, 57073, 30, None)
        assert "targetcmid" not in enviados[0][0]["args"]

    def test_rechazado_da_error_mover_sin_texto_del_aula(self):
        moodle, _ = self._moodle([{"error": True, "exception": {"message": "secreto"}}])
        with pytest.raises(ErrorPublicacion) as exc:
            moodle.mover(838, 1, 30, None)
        assert exc.value.codigo == "ERROR_MOVER"
        assert "secreto" not in repr(exc.value.detalle) + str(exc.value)


class TestMoverAlCambiarDeSeccion:
    def _aula(self, modulos_en_30, modulos_en_40=()):
        moodle = MoodleFalso(
            secciones=[
                {"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": list(modulos_en_30)},
                {"numero": 4, "nombre": "Tema 4", "id": 40, "modulos": list(modulos_en_40)},
            ]
        )
        return moodle

    def test_un_candidato_en_otra_seccion_se_mueve_en_vez_de_duplicar(self, tmp_path):
        antiguo = {"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}
        moodle = self._aula([antiguo])
        doc = documento(tmp_path, "Repaso", seccion_=4)
        resultado = publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=None)
        assert resultado.accion == "movida"
        assert resultado.cmid == 55
        assert resultado.seccion == "Tema 4"
        assert moodle.secciones[0]["modulos"] == []
        assert [m["cmid"] for m in moodle.secciones[1]["modulos"]] == [55]
        operaciones = [x[0] for x in moodle.llamadas]
        assert "crear" not in operaciones
        assert operaciones.index("mover") < operaciones.index("actualizar")

    def test_varios_candidatos_es_ambiguo_y_no_toca_nada(self, tmp_path):
        a = {"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}
        b = {"cmid": 56, "nombre": "Repaso", "tipo": "pagina"}
        moodle = self._aula([a], [])
        moodle.secciones.append({"numero": 5, "nombre": "Tema 5", "id": 50, "modulos": [b]})
        doc = documento(tmp_path, "Repaso", seccion_=4)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=None)
        assert exc.value.codigo == "ACTIVIDAD_AMBIGUA"
        assert not [x for x in moodle.llamadas if x[0] in ("mover", "crear", "actualizar")]

    def test_ninguno_se_crea(self, tmp_path):
        moodle = self._aula([])
        doc = documento(tmp_path, "Repaso", seccion_=4)
        resultado = publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=False)
        assert resultado.accion == "creada"
        assert not [x for x in moodle.llamadas if x[0] == "mover"]

    def test_si_ya_esta_en_su_seccion_no_se_busca_fuera(self, tmp_path):
        fuera = {"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}
        dentro = {"cmid": 66, "nombre": "Repaso", "tipo": "pagina"}
        moodle = self._aula([fuera], [dentro])
        doc = documento(tmp_path, "Repaso", seccion_=4)
        resultado = publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=None)
        assert (resultado.accion, resultado.cmid) == ("actualizada", 66)
        assert not [x for x in moodle.llamadas if x[0] == "mover"]

    def test_otro_tipo_o_nombre_en_otra_seccion_no_cuenta(self, tmp_path):
        moodle = self._aula([{"cmid": 55, "nombre": "Repaso", "tipo": "tarea"}])
        doc = documento(tmp_path, "Repaso", seccion_=4)
        resultado = publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=False)
        assert resultado.accion == "creada"

    def test_conserva_la_visibilidad(self, tmp_path):
        moodle = self._aula([{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}])
        moodle.formularios[55] = {"visible": "1"}
        doc = documento(tmp_path, "Repaso", seccion_=4)
        resultado = publicar.publicar_documento(moodle, 1234, moodle.secciones, doc, visible=None)
        assert resultado.oculto is False

    def test_origen_de_movimiento_solo_lectura(self, tmp_path):
        moodle = self._aula([{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}])
        doc = documento(tmp_path, "Repaso", seccion_=4)
        assert publicar.origen_de_movimiento(moodle.secciones, doc) == "Tema 3"
        assert not [x for x in moodle.llamadas if x[0] == "mover"]
        moodle2 = self._aula([], [{"cmid": 55, "nombre": "Repaso", "tipo": "pagina"}])
        assert publicar.origen_de_movimiento(moodle2.secciones, doc) is None
