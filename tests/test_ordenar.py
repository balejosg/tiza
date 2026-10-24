"""Orden y movimiento de actividades: el plan, ``ordenar_documentos`` y mover al cambiar ``seccion:``."""

from __future__ import annotations

import dataclasses
import random

import pytest

from dobles import MoodleFalso
from tiza import contenido, estado, publicar
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


class TestOrigenAlOrdenar:
    """``resolver_orden`` agrupa por la sección del ``origen`` y no se traga un origen ausente."""

    def _origen(self, tmp_path, nombre, cmid):
        ruta = tmp_path / f"{nombre.lower()}.md"
        ruta.write_text(
            f"---\ntipo: pagina\nnombre: {nombre}\nseccion: 3\n"
            f"origen:\n  curso: 1234\n  cmid: {cmid}\n---\n\nTexto\n",
            encoding="utf-8",
        )
        return contenido.cargar(ruta)

    def test_el_origen_encontrado_en_otra_seccion_manda_su_seccion(self, tmp_path):
        moodle = aula(1, 2)  # sección 30 con P1 y P2
        moodle.secciones.append(
            {
                "numero": 4,
                "nombre": "Tema 4",
                "id": 40,
                "modulos": [{"cmid": 7, "nombre": "Cambiada", "tipo": "pagina"}],
            }
        )
        docs = [self._origen(tmp_path, "Renombrada", 7), documento(tmp_path, "P1")]
        grupos = publicar.resolver_orden(moodle.secciones, docs, 1234)
        assert [(s["id"], [m["cmid"] for _, m in par]) for s, par in grupos] == [
            (40, [7]),
            (30, [1]),
        ]

    def test_ordenar_con_origen_encontrado_no_mueve_nada_si_ya_esta(self, tmp_path):
        moodle = aula(1, 2)
        docs = [self._origen(tmp_path, "P2", 2)]
        ficheros = publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert {f.accion for f in ficheros} == {"sin_cambios"}
        assert not [x for x in moodle.llamadas if x[0] == "mover"]

    def test_origen_ausente_es_origen_no_encontrado(self, tmp_path):
        moodle = aula(1, 2)
        docs = [self._origen(tmp_path, "Perdida", 9)]
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.resolver_orden(moodle.secciones, docs, 1234)
        assert (exc.value.codigo, exc.value.detalle) == ("ORIGEN_NO_ENCONTRADO", "perdida.md")
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert exc.value.codigo == "ORIGEN_NO_ENCONTRADO"
        assert not [x for x in moodle.llamadas if x[0] == "mover"]


class TestModulosFuera:
    def test_salta_las_secciones_que_no_son_dict(self, tmp_path):
        secciones = [
            None,
            "basura",
            {
                "numero": 4,
                "nombre": "Tema 4",
                "id": 40,
                "modulos": [{"cmid": 1, "nombre": "P1", "tipo": "pagina"}],
            },
        ]
        doc = documento(tmp_path, "P1")
        hallados = publicar.modulos_fuera(secciones, doc)
        assert [(s["id"], m["cmid"]) for s, m in hallados] == [(40, 1)]


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


class TestOrdenarPorRegistro:
    """Una actividad que se llama distinto en el aula se encuentra por el registro de lo publicado."""

    def con_registro(self, doc, curso, cmid):
        return dataclasses.replace(doc, publicados={curso: estado.Publicado(cmid, doc.tipo)})

    def test_ordena_actividades_que_ya_no_se_llaman_como_su_fichero(self, tmp_path):
        moodle = aula(1, 2, 3)  # P1, P2, P3 en el aula
        docs = [
            self.con_registro(documento(tmp_path, nombre), 1234, cmid)
            for nombre, cmid in (("Tercera", 3), ("Primera", 1))
        ]
        ficheros = publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert [m["cmid"] for m in moodle.secciones[0]["modulos"]] == [3, 2, 1]
        assert [(f.nombre, f.accion, f.cmid) for f in ficheros] == [
            ("tercera.md", "ordenada", 3),
            ("primera.md", "ordenada", 1),
        ]

    def test_sin_registro_siguen_ausentes(self, tmp_path):
        moodle = aula(1, 2, 3)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.ordenar_documentos(
                moodle, 1234, moodle.secciones, [documento(tmp_path, "Primera")]
            )
        assert exc.value.codigo == "ACTIVIDAD_AUSENTE"

    def test_el_registro_de_otro_curso_no_cuenta(self, tmp_path):
        moodle = aula(1, 2, 3)
        doc = self.con_registro(documento(tmp_path, "Primera"), 9999, 1)
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.ordenar_documentos(moodle, 1234, moodle.secciones, [doc])
        assert exc.value.codigo == "ACTIVIDAD_AUSENTE"

    def test_dos_ficheros_con_el_mismo_cmid_en_el_registro_son_ambiguos(self, tmp_path):
        moodle = aula(1, 2, 3)
        docs = [
            self.con_registro(documento(tmp_path, nombre), 1234, 1) for nombre in ("Uno", "Dos")
        ]
        with pytest.raises(ErrorPublicacion) as exc:
            publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert exc.value.codigo == "ACTIVIDAD_AMBIGUA"
        assert not [x for x in moodle.llamadas if x[0] == "mover"]

    def test_se_ordena_en_la_seccion_en_la_que_esta_la_actividad(self, tmp_path):
        moodle = MoodleFalso(
            secciones=[
                {
                    "numero": 2,
                    "nombre": "Tema 2",
                    "id": 20,
                    "modulos": [{"cmid": c, "nombre": f"P{c}", "tipo": "pagina"} for c in (1, 2)],
                },
                {"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []},
            ]
        )
        # Los dos ficheros dicen «sección 3», pero sus actividades siguen en la 2.
        docs = [
            self.con_registro(documento(tmp_path, nombre), 1234, cmid)
            for nombre, cmid in (("Segunda", 2), ("Primera", 1))
        ]
        ficheros = publicar.ordenar_documentos(moodle, 1234, moodle.secciones, docs)
        assert [m["cmid"] for m in moodle.secciones[0]["modulos"]] == [2, 1]
        assert {f.seccion for f in ficheros} == {"Tema 2"}
        assert not [x for x in moodle.llamadas if x[0] == "mover" and x[3] != 20]


# --------------------------------------------------------------------------- #
# La sesión: ordenar en pruebas y en real
# --------------------------------------------------------------------------- #

from dobles import PresenciaFalsa, dejar_peticion, peticion  # noqa: E402
from tiza import buzon, config, mensajes, publicacion, sesion_abierta  # noqa: E402

URL = "https://aula.ejemplo.org/centro"
CFG = config.Config(url=URL, usuario="profe", cursos={"pruebas": 1234}, reales=(5678,))
CFG_SIN_PRUEBAS = config.Config(
    url=URL, usuario="profe", cursos={}, reales=(5678,), sin_pruebas=True
)
CFG_DOS = config.Config(url=URL, usuario="profe", cursos={"pruebas": 1234}, reales=(101, 102))


def carpeta_con(tmp_path, *nombres, restricciones=None):
    """Una carpeta con una página por nombre (P1.md…), todas en la sección 3."""
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir(exist_ok=True)
    for nombre in nombres:
        extra = ""
        if restricciones and nombre in restricciones:
            extra = f"restricciones: {{completar: [{restricciones[nombre]}.md]}}\n"
        (carpeta / f"{nombre}.md").write_text(
            f"---\ntipo: pagina\nnombre: {nombre}\nseccion: 3\n{extra}---\n\nTexto\n",
            encoding="utf-8",
        )
    return carpeta.resolve()


def seccion_de(*modulos, id_=30):
    return [
        {
            "numero": 3,
            "nombre": "Tema 3",
            "id": id_,
            "modulos": [
                {"cmid": cmid, "nombre": nombre, "tipo": tipo} for cmid, nombre, tipo in modulos
            ],
        }
    ]


def aula_de_la_sesion(*modulos):
    """P1, P2 y P3 con un foro entre ellos que no es de tiza."""
    return MoodleFalso(secciones=seccion_de(*modulos))


MODULOS = (
    (1, "P2", "pagina"),
    (2, "Foro de dudas", "foro"),
    (3, "P1", "pagina"),
    (4, "P3", "pagina"),
)


def pedir(carpeta, entorno, ficheros, **cambios):
    datos = peticion(entorno, None, comando="ordenar", ficheros=list(ficheros), **cambios)
    if entorno == "real":
        dejar_peticion(carpeta, datos)
    return datos


def atender(datos, moodle, cfg, carpeta, presencia, **opciones):
    return sesion_abierta.SesionAbierta(moodle, cfg, carpeta, presencia, **opciones).atender(datos)


def orden_en(moodle, curso=None):
    secciones = moodle._de(curso)
    return [[m["cmid"] for m in s["modulos"]] for s in secciones]


class TestOrdenarEnLaSesion:
    def test_pruebas_ordena_avisa_y_gasta_un_cupo(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2", "P3")
        moodle = aula_de_la_sesion(*MODULOS)
        presencia = PresenciaFalsa()
        sesion = sesion_abierta.SesionAbierta(moodle, CFG, carpeta, presencia)
        documento = sesion.atender(pedir(carpeta, "pruebas", ["P1.md", "P2.md", "P3.md"]))
        assert documento["comando"] == "ordenar"
        assert documento["resultado"] == "ok"
        assert [f["accion"] for f in documento["ficheros"]] == ["ordenada"] * 3
        assert [f["oculto"] for f in documento["ficheros"]] == [None] * 3
        assert orden_en(moodle) == [[3, 2, 1, 4]]  # los huecos de P2, P1, P3: 1.º, 3.º y 4.º
        assert sesion.cupo["pruebas"] == 1
        assert presencia.codigos()[0] == "ORDENANDO_EN_PRUEBAS"
        assert presencia.resumenes_orden == []  # en pruebas no se pregunta

    def test_repetirlo_no_llama_al_aula_y_todo_es_sin_cambios(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2", "P3")
        moodle = aula_de_la_sesion(*MODULOS)
        sesion = sesion_abierta.SesionAbierta(moodle, CFG, carpeta, PresenciaFalsa())
        sesion.atender(pedir(carpeta, "pruebas", ["P1.md", "P2.md", "P3.md"]))
        moodle.llamadas.clear()
        documento = sesion.atender(pedir(carpeta, "pruebas", ["P1.md", "P2.md", "P3.md"]))
        assert {f["accion"] for f in documento["ficheros"]} == {"sin_cambios"}
        assert not [x for x in moodle.llamadas if x[0] == "mover"]

    def test_encuentra_por_el_registro_la_actividad_que_cambio_de_nombre(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2", "P3")
        modulos = list(MODULOS)
        modulos[2] = (3, "Primera práctica", "pagina")  # P1.md, en el aula con otro nombre
        pedido = pedir(carpeta, "pruebas", ["P1.md", "P2.md", "P3.md"])

        sin_registro = atender(pedido, aula_de_la_sesion(*modulos), CFG, carpeta, PresenciaFalsa())
        assert sin_registro["errores"] == ["ACTIVIDAD_AUSENTE"]

        estado.guardar_publicado(
            carpeta / ".tiza", 1234, "P1.md", estado.Publicado(cmid=3, tipo="pagina")
        )
        moodle = aula_de_la_sesion(*modulos)
        documento = atender(pedido, moodle, CFG, carpeta, PresenciaFalsa())
        assert documento["resultado"] == "ok"
        assert [f["accion"] for f in documento["ficheros"]] == ["ordenada"] * 3
        assert orden_en(moodle) == [[3, 2, 1, 4]]

    def test_no_exige_verificacion_ni_marca_nada_como_verificado(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2")
        sesion = sesion_abierta.SesionAbierta(
            aula_de_la_sesion(*MODULOS), CFG, carpeta, PresenciaFalsa()
        )
        sesion.atender(pedir(carpeta, "pruebas", ["P1.md", "P2.md"]))
        assert sesion.verificados == {}

    def test_sin_curso_de_pruebas(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2")
        documento = atender(
            pedir(carpeta, "pruebas", ["P1.md", "P2.md"]),
            aula_de_la_sesion(*MODULOS),
            CFG_SIN_PRUEBAS,
            carpeta,
            PresenciaFalsa(),
        )
        assert documento["errores"] == ["SIN_CURSO_PRUEBAS"]

    def test_el_cupo_se_agota(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2")
        sesion = sesion_abierta.SesionAbierta(
            aula_de_la_sesion(*MODULOS), CFG, carpeta, PresenciaFalsa()
        )
        sesion.cupo["pruebas"] = publicacion.MAX_PUBLICACIONES_PRUEBAS
        documento = sesion.atender(pedir(carpeta, "pruebas", ["P1.md", "P2.md"]))
        assert documento["errores"] == ["LIMITE_PUBLICACIONES"]

    def test_actividad_ausente_no_mueve_nada(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2", "Otra")
        moodle = aula_de_la_sesion(*MODULOS)
        documento = atender(
            pedir(carpeta, "pruebas", ["P1.md", "Otra.md"]), moodle, CFG, carpeta, PresenciaFalsa()
        )
        assert documento["errores"] == ["ACTIVIDAD_AUSENTE"]
        assert [p["detalle"] for p in documento["pasos"] if p["codigo"] == "ORDENAR"] == ["Otra.md"]
        assert orden_en(moodle) == [[1, 2, 3, 4]]

    def test_el_informe_no_lleva_nombres_del_aula(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2")
        atender(
            pedir(carpeta, "pruebas", ["P1.md", "P2.md"]),
            aula_de_la_sesion(*MODULOS),
            CFG,
            carpeta,
            PresenciaFalsa(),
        )
        assert "Foro de dudas" not in (carpeta / ".tiza" / "informe.json").read_text("utf-8")


class TestOrdenarEnReal:
    def test_ensena_el_orden_nuevo_con_lo_que_no_es_de_tiza_y_ordena_si_confirma(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2", "P3")
        moodle = aula_de_la_sesion(*MODULOS)
        presencia = PresenciaFalsa(real=True)
        documento = atender(
            pedir(carpeta, "real", ["P1.md", "P2.md", "P3.md"]),
            moodle,
            CFG,
            carpeta,
            presencia,
            nombres={5678: "Mates"},
        )
        assert documento["resultado"] == "ok"
        assert orden_en(moodle) == [[3, 2, 1, 4]]
        [resumen] = presencia.resumenes_orden
        assert resumen.nombre_curso == "Mates"
        [seccion] = resumen.secciones
        assert [(a.nombre, a.fichero) for a in seccion.actividades] == [
            ("P1", "P1.md"),
            ("Foro de dudas", None),
            ("P2", "P2.md"),
            ("P3", "P3.md"),
        ]
        detalle = mensajes.detalle_orden(resumen)
        assert any("Foro de dudas" in linea for _, lineas in detalle.secciones for linea in lineas)
        assert [f["accion"] for f in documento["ficheros"]] == ["ordenada"] * 3

    def test_si_el_docente_dice_que_no_no_se_mueve_nada(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2")
        moodle = aula_de_la_sesion(*MODULOS)
        documento = atender(
            pedir(carpeta, "real", ["P1.md", "P2.md"]),
            moodle,
            CFG,
            carpeta,
            PresenciaFalsa(real=False),
        )
        assert documento["resultado"] == "abortado"
        assert documento["errores"] == ["ABORTADO"]
        assert not [x for x in moodle.llamadas if x[0] == "mover"]

    def test_sin_cambios_no_pregunta(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P2", "P1")
        presencia = PresenciaFalsa(real=False)
        documento = atender(
            pedir(carpeta, "real", ["P2.md", "P1.md"]),
            aula_de_la_sesion(*MODULOS),
            CFG,
            carpeta,
            presencia,
        )
        assert presencia.resumenes_orden == []
        assert documento["resultado"] == "ok"
        assert {f["accion"] for f in documento["ficheros"]} == {"sin_cambios"}

    def test_peticion_retirada_tras_confirmar(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2")
        datos = pedir(carpeta, "real", ["P1.md", "P2.md"])
        ruta = buzon.carpeta_buzon(carpeta / ".tiza") / f"{datos['id']}{buzon.SUFIJO_PETICION}"

        class Retira(PresenciaFalsa):
            def confirmar_orden(self, resumen):
                ruta.unlink()
                return super().confirmar_orden(resumen)

        moodle = aula_de_la_sesion(*MODULOS)
        documento = atender(datos, moodle, CFG, carpeta, Retira(real=True))
        assert documento["errores"] == ["PETICION_RETIRADA"]
        assert not [x for x in moodle.llamadas if x[0] == "mover"]

    def test_no_exige_oculto_ni_verificacion_sin_curso_de_pruebas(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2")
        moodle = aula_de_la_sesion(*MODULOS)
        documento = atender(
            pedir(carpeta, "real", ["P1.md", "P2.md"]),
            moodle,
            CFG_SIN_PRUEBAS,
            carpeta,
            PresenciaFalsa(real=True),
        )
        assert documento["resultado"] == "ok"
        assert orden_en(moodle) == [[3, 2, 1, 4]]

    def test_avisa_si_una_actividad_queda_encima_de_la_que_debe_completarse_antes(self, tmp_path):
        # P2 exige completar P1; ordenar «P2 P1» deja P2 encima de P1.
        carpeta = carpeta_con(tmp_path, "P1", "P2", restricciones={"P2": "P1"})
        moodle = aula_de_la_sesion((1, "P1", "pagina"), (2, "P2", "pagina"))
        presencia = PresenciaFalsa(real=True)
        atender(pedir(carpeta, "real", ["P2.md", "P1.md"]), moodle, CFG, carpeta, presencia)
        [resumen] = presencia.resumenes_orden
        assert resumen.dependencias == (("P2.md", "P1.md"),)
        assert any("P2.md" in linea for linea in mensajes.detalle_orden(resumen).finales)
        assert orden_en(moodle) == [[2, 1]]  # el aviso no impide ordenar

    def test_sin_dependencias_invertidas_no_hay_aviso(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2", restricciones={"P2": "P1"})
        moodle = aula_de_la_sesion((2, "P2", "pagina"), (1, "P1", "pagina"))
        presencia = PresenciaFalsa(real=True)
        atender(pedir(carpeta, "real", ["P1.md", "P2.md"]), moodle, CFG, carpeta, presencia)
        assert presencia.resumenes_orden[0].dependencias == ()


def aula_con_dos_cursos(segundo=None):
    primero = seccion_de((1, "P2", "pagina"), (2, "P1", "pagina"))
    segundo = (
        segundo if segundo is not None else seccion_de((1, "P2", "pagina"), (2, "P1", "pagina"))
    )
    return MoodleFalso(secciones_por_curso={101: primero, 102: segundo})


class TestOrdenarEnVariosCursosReales:
    def test_una_confirmacion_por_curso_y_cada_curso_con_sus_huecos(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2")
        moodle = aula_con_dos_cursos(
            seccion_de((9, "Foro", "foro"), (1, "P2", "pagina"), (2, "P1", "pagina"))
        )
        presencia = PresenciaFalsa(real=(True, True))
        documento = atender(
            pedir(carpeta, "real", ["P1.md", "P2.md"]),
            moodle,
            CFG_DOS,
            carpeta,
            presencia,
            nombres={101: "1º A", 102: "1º B"},
        )
        assert documento["resultado"] == "ok"
        assert [(r.curso, r.posicion, r.total) for r in presencia.resumenes_orden] == [
            (101, 1, 2),
            (102, 2, 2),
        ]
        assert orden_en(moodle, 101) == [[2, 1]]
        assert orden_en(moodle, 102) == [[9, 2, 1]]
        assert [(f["curso"], f["accion"]) for f in documento["ficheros"]] == [
            (101, "ordenada")
        ] * 2 + [(102, "ordenada")] * 2
        assert documento["curso"] is None

    def test_un_no_omite_ese_curso_y_sigue(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2")
        moodle = aula_con_dos_cursos()
        documento = atender(
            pedir(carpeta, "real", ["P1.md", "P2.md"]),
            moodle,
            CFG_DOS,
            carpeta,
            PresenciaFalsa(real=(False, True)),
        )
        assert documento["resultado"] == "ok"
        assert orden_en(moodle, 101) == [[1, 2]]
        assert orden_en(moodle, 102) == [[2, 1]]
        assert ("CURSO_OMITIDO", "101") in [(p["codigo"], p["detalle"]) for p in documento["pasos"]]

    def test_ausente_en_un_curso_falla_antes_de_mover_en_el_y_se_para(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2")
        # En el segundo curso falta P2: el primero ya está hecho, el segundo no se toca.
        moodle = aula_con_dos_cursos(seccion_de((2, "P1", "pagina")))
        presencia = PresenciaFalsa(real=(True, True))
        documento = atender(
            pedir(carpeta, "real", ["P1.md", "P2.md"]), moodle, CFG_DOS, carpeta, presencia
        )
        assert documento["resultado"] == "error"
        assert documento["errores"] == ["ACTIVIDAD_AUSENTE"]
        assert orden_en(moodle, 101) == [[2, 1]]
        assert orden_en(moodle, 102) == [[2]]
        assert len(presencia.resumenes_orden) == 1  # al segundo ni se le pregunta
        assert [f["curso"] for f in documento["ficheros"]] == [101, 101]

    def test_ausente_en_el_primero_no_sigue_con_el_segundo(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1", "P2")
        moodle = aula_con_dos_cursos()
        moodle.secciones_por_curso[101] = seccion_de((2, "P1", "pagina"))
        presencia = PresenciaFalsa(real=(True, True))
        documento = atender(
            pedir(carpeta, "real", ["P1.md", "P2.md"]), moodle, CFG_DOS, carpeta, presencia
        )
        assert documento["errores"] == ["ACTIVIDAD_AUSENTE"]
        assert presencia.resumenes_orden == []
        assert orden_en(moodle, 102) == [[1, 2]]


class TestPublicarMueveDeSeccion:
    """Lo que el docente ve y lo que ocurre al publicar con ``seccion:`` cambiada."""

    def _aula(self):
        return MoodleFalso(
            secciones=[
                {
                    "numero": 2,
                    "nombre": "Tema 2",
                    "id": 20,
                    "modulos": [{"cmid": 55, "nombre": "P1", "tipo": "pagina"}],
                },
                {"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []},
            ]
        )

    def _publicar(self, tmp_path, entorno, cfg, presencia, **cambios):
        carpeta = carpeta_con(tmp_path, "P1")  # seccion: 3; en el aula está en la 2
        datos = peticion(entorno, cambios.pop("visible", None), **cambios)
        datos["ficheros"] = ["P1.md"]
        if entorno == "real":
            dejar_peticion(carpeta, datos)
        moodle = self._aula()
        verificados = {}
        if entorno == "real" and "pruebas" in cfg.cursos:
            from tiza import contenido, estado

            doc = contenido.cargar(carpeta / "P1.md", raiz=carpeta)
            estado.guardar_verificado(carpeta / ".tiza", contenido.hash_documento(doc), "P1.md", 55)
            verificados = estado.cargar_verificados(carpeta / ".tiza")
        documento = atender(datos, moodle, cfg, carpeta, presencia, verificados=verificados)
        return moodle, documento

    def test_pruebas_mueve_y_dice_movida(self, tmp_path):
        moodle, documento = self._publicar(
            tmp_path, "pruebas", CFG, PresenciaFalsa(), visible=False
        )
        assert [(f["accion"], f["cmid"]) for f in documento["ficheros"]] == [("movida", 55)]
        assert orden_en(moodle) == [[], [55]]

    def test_la_confirmacion_de_real_dice_de_donde_a_donde(self, tmp_path):
        presencia = PresenciaFalsa(real=True)
        moodle, documento = self._publicar(tmp_path, "real", CFG, presencia)
        assert documento["resultado"] == "ok"
        [resumen] = presencia.resumenes
        assert resumen.movimientos == (publicacion.CambioSeccion("P1.md", "Tema 2", "Tema 3"),)
        assert any(
            "de la sección «Tema 2» a «Tema 3»" in f for f in mensajes.detalle_real(resumen).finales
        )
        assert orden_en(moodle) == [[], [55]]

    def test_sin_pruebas_la_confirmacion_corta_lo_dice_y_va_oculto(self, tmp_path):
        presencia = PresenciaFalsa(real=True)
        moodle, documento = self._publicar(
            tmp_path, "real", CFG_SIN_PRUEBAS, presencia, visible=False
        )
        assert documento["resultado"] == "ok"
        [corto] = presencia.resumenes_cortos
        assert corto.movimientos == (publicacion.CambioSeccion("P1.md", "Tema 2", "Tema 3"),)
        assert any("Tema 2" in f for f in mensajes.detalle_corto(corto).finales)
        assert moodle.formularios[55]["visible"] == "0"

    def test_sin_pruebas_sigue_exigiendo_oculto(self, tmp_path):
        _, documento = self._publicar(tmp_path, "real", CFG_SIN_PRUEBAS, PresenciaFalsa(real=True))
        assert documento["errores"] == ["SOLO_OCULTO_SIN_PRUEBAS"]

    def test_solo_fechas_no_mueve(self, tmp_path):
        carpeta = tmp_path / "asignatura"
        carpeta.mkdir()
        (carpeta / "T.md").write_text(
            "---\ntipo: tarea\nnombre: T\nseccion: 3\napertura: 2049-01-01\nentrega: 2049-01-02\n---\n\nX\n",
            encoding="utf-8",
        )
        moodle = MoodleFalso(
            secciones=[
                {
                    "numero": 2,
                    "nombre": "Tema 2",
                    "id": 20,
                    "modulos": [{"cmid": 9, "nombre": "T", "tipo": "tarea"}],
                },
                {"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []},
            ]
        )
        datos = peticion("pruebas", None, solo_fechas=True, ficheros=["T.md"])
        documento = atender(datos, moodle, CFG, carpeta.resolve(), PresenciaFalsa())
        assert documento["errores"] == ["MODULO_AUSENTE"]
        assert not [x for x in moodle.llamadas if x[0] == "mover"]

    def test_varios_candidatos_no_mueve_ni_crea(self, tmp_path):
        carpeta = carpeta_con(tmp_path, "P1")
        moodle = MoodleFalso(
            secciones=[
                {
                    "numero": 1,
                    "nombre": "T1",
                    "id": 10,
                    "modulos": [{"cmid": 5, "nombre": "P1", "tipo": "pagina"}],
                },
                {
                    "numero": 2,
                    "nombre": "T2",
                    "id": 20,
                    "modulos": [{"cmid": 6, "nombre": "P1", "tipo": "pagina"}],
                },
                {"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []},
            ]
        )
        datos = peticion("pruebas", False, ficheros=["P1.md"])
        documento = atender(datos, moodle, CFG, carpeta, PresenciaFalsa())
        assert documento["errores"] == ["ACTIVIDAD_AMBIGUA"]
        assert not [x for x in moodle.llamadas if x[0] in ("mover", "crear")]
