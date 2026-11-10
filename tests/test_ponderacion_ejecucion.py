"""Ejecutar y verificar el plan de ponderación (``preparar_ponderacion`` y ``ponderacion_con``).

El aula es ``AulaPonderada``: un ``MoodleFalso`` cuyo árbol de ponderación refleja las escrituras
(con fallos y derivas a voluntad). El plan puro se prueba en ``calificacion/test_ponderacion.py``.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from calificacion.test_ponderacion import (
    FICHEROS,
    PRIMERA,
    REF_FICHEROS,
    aula_e1,
    aula_natural,
    categoria,
    esquema_e1,
    esquema_natural,
)

from dobles import MoodleFalso, PresenciaFalsa
from tiza import estado, informe, publicacion
from tiza.calificacion import ponderacion
from tiza.colocacion import ArbolNotas, FilaNota
from tiza.publicar import ErrorPublicacion

CURSO = 2
REF_EXAMEN = "categoria:EXAMEN_1EV"
REF_PRIMERA = f"categoria:{PRIMERA}"


def secciones() -> list[dict]:
    return [
        {
            "numero": 1,
            "nombre": PRIMERA,
            "id": 10,
            "modulos": [
                {"cmid": cmid, "nombre": nombre, "tipo": tipo}
                for _, tipo, nombre, _, cmid in FICHEROS
            ],
        },
        {"numero": 2, "nombre": "SEGUNDA", "id": 11, "modulos": []},
    ]


class AulaPonderada(MoodleFalso):
    """Un aula cuyo calificador de ponderación refleja las escrituras.

    ``sin_efecto``: eids de elementos cuyo coeficiente se acepta pero no se guarda.
    ``deriva``: cuántas escrituras de pesos naturales quedan al 90 % de lo pedido (Moodle
    reescalando). ``fallar_tras``: número de escrituras que salen bien antes de fallar.
    """

    def __init__(self, arbol: ponderacion.ArbolPonderacion, **kw) -> None:
        super().__init__(secciones=secciones(), **kw)
        self.arboles_ponderacion[CURSO] = arbol
        self.arboles[CURSO] = ArbolNotas(
            (FilaNota("cg1", None, None, "Curso"), FilaNota("cg2", "cg1", None, PRIMERA))
        )
        self.sin_efecto: set[str] = set()
        self.deriva = 0
        self.fallar_tras: int | None = None

    def _escribir_calificador(self, metodo, *args):
        if self.fallar_tras is not None and len(self.escrituras) >= self.fallar_tras:
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        super()._escribir_calificador(metodo, *args)

    def _cambiar(self, eid, **campos) -> None:
        arbol = self.arboles_ponderacion[CURSO]
        nodos = tuple(dataclasses.replace(n, **campos) if n.eid == eid else n for n in arbol.nodos)
        self.arboles_ponderacion[CURSO] = ponderacion.ArbolPonderacion(
            arbol.curso, nodos, arbol.decimal
        )

    def crear_categoria(
        self,
        curso,
        nombre,
        idnumber,
        padre_eid,
        peso,
        visualizacion,
        agregacion=13,
        solo_no_vacias=True,
        coeficiente=None,
    ):
        eid = super().crear_categoria(
            curso,
            nombre,
            idnumber,
            padre_eid,
            peso,
            visualizacion,
            agregacion,
            solo_no_vacias,
            coeficiente,
        )
        arbol = self.arboles_ponderacion[curso]
        nueva = categoria(
            eid,
            nombre,
            padre=padre_eid,
            agregacion=agregacion,
            solo=solo_no_vacias,
            coeficiente=coeficiente,
            peso=coeficiente if coeficiente is not None else 1.0,
            idnumber=idnumber,
        )
        self.arboles_ponderacion[curso] = ponderacion.ArbolPonderacion(
            arbol.curso, (*arbol.nodos, nueva), arbol.decimal
        )
        return eid

    def mover_nota(self, curso, eid, categoria_eid, despues_de):
        super().mover_nota(curso, eid, categoria_eid, despues_de)
        self._cambiar(eid, padre_eid=categoria_eid, coeficiente=None, peso=1.0, sobrescrito=False)

    def fijar_agregacion(self, curso, eid, agregacion, solo_no_vacias=None):
        super().fijar_agregacion(curso, eid, agregacion, solo_no_vacias)
        campos = {"agregacion": agregacion}
        if solo_no_vacias is not None:
            campos["solo_no_vacias"] = solo_no_vacias
        self._cambiar(eid, **campos)

    def fijar_coeficiente(self, curso, eid, valor, metodo_del_padre):
        super().fijar_coeficiente(curso, eid, valor, metodo_del_padre)
        if eid in self.sin_efecto:
            return
        natural = metodo_del_padre == "natural"
        if natural and self.deriva > 0:
            self.deriva -= 1
            valor = valor * 0.9
        self._cambiar(eid, coeficiente=valor, peso=valor, sobrescrito=natural)


def aula_con_e1(**kw) -> AulaPonderada:
    return AulaPonderada(aula_e1(), **kw)


def preparar(aula, esquema, tmp_path):
    return publicacion.preparar_ponderacion(aula, CURSO, esquema, tmp_path / ".tiza")


def ejecutar(aula, esquema, tmp_path, *, presencia=None):
    plan_curso = preparar(aula, esquema, tmp_path)
    return plan_curso, publicacion.ponderacion_con(
        aula, "real", CURSO, plan_curso, tmp_path / ".tiza", presencia=presencia
    )


def pasos(informe_: dict, codigo: str) -> list[dict]:
    return [p for p in informe_["pasos"] if p["codigo"] == codigo]


def huellas(tmp_path) -> dict[str, str]:
    return estado.cargar_huellas_ponderacion(tmp_path / ".tiza", CURSO)


# --- preparar_ponderacion ---


def test_preparar_lee_el_aula_y_devuelve_el_plan_sin_escribir(tmp_path):
    aula = aula_con_e1()
    plan_curso = preparar(aula, esquema_e1(), tmp_path)
    assert isinstance(plan_curso, publicacion.PlanPonderacionCurso)
    assert plan_curso.curso == CURSO
    assert [o.tipo for o in plan_curso.plan.operaciones] == [
        "crear",
        *["mover"] * 4,
        *["coeficiente"] * 4,
    ]
    assert plan_curso.arbol is aula.arboles_ponderacion[CURSO]
    assert plan_curso.huellas == {} and plan_curso.tzp == {}
    assert set(plan_curso.nombres) == {
        PRIMERA,
        "Examen 1.ª evaluación",
        "Test 1",
        "Test 2",
        "Test 3",
        "Monta tu PC",
    }
    assert aula.escrituras == []
    llamadas = [c[0] for c in aula.llamadas]
    for esperada in ("estructura", "arbol_notas", "idnumbers_de", "arbol_ponderacion"):
        assert esperada in llamadas
    assert ("idnumbers_de", CURSO, frozenset({"cg1", "cg2"})) in aula.llamadas
    assert ("arbol_ponderacion", CURSO, frozenset(plan_curso.nombres)) in aula.llamadas
    assert not (tmp_path / ".tiza" / "ponderacion.json").exists()


def test_preparar_recoge_las_categorias_tzp_del_aula(tmp_path):
    aula = aula_con_e1()
    aula.idnumbers[CURSO] = {"cg2": "TZP_OTRA", "cg1": ""}
    assert preparar(aula, esquema_e1(), tmp_path).tzp == {"cg2": "TZP_OTRA"}


def test_preparar_con_el_calificador_de_tiza_es_un_error(tmp_path):
    aula = aula_con_e1()
    aula.idnumbers[CURSO] = {"cg2": "TZ_TIZA"}
    with pytest.raises(ponderacion.ErrorPonderacion) as error:
        preparar(aula, esquema_e1(), tmp_path)
    assert error.value.codigo == "PONDERACION_CON_CALIFICADOR_DE_TIZA"


# --- ponderacion_con ---


def test_las_escrituras_van_en_orden_y_crear_lleva_solo_y_coeficiente(tmp_path):
    aula = aula_con_e1()
    plan_curso, resultado = ejecutar(aula, esquema_e1(), tmp_path)
    assert resultado["resultado"] == "ok"
    assert [e[0] for e in aula.escrituras] == [
        "crear_categoria",
        "fijar_coeficiente",
        *["mover_nota"] * 4,
        *["fijar_coeficiente"] * 4,
    ]
    nueva = aula.escrituras[0]
    assert nueva[2:5] == ("Examen 1.ª evaluación", "TZP_EXAMEN_1EV", "cg2")
    assert aula.opciones_de_escritura == [("crear_categoria", "TZP_EXAMEN_1EV", False, 1.2857)]
    eid_examen = next(n.eid for n in aula.arboles_ponderacion[CURSO].nodos if n.idnumber)
    movidas = [e for e in aula.escrituras if e[0] == "mover_nota"]
    assert [(e[2], e[3], e[4]) for e in movidas] == [
        ("ig11", eid_examen, None),
        ("ig12", eid_examen, "ig11"),
        ("ig13", eid_examen, "ig12"),
        ("ig14", eid_examen, "ig13"),
    ]
    coeficientes = [e for e in aula.escrituras if e[0] == "fijar_coeficiente"]
    assert [(e[2], e[3], e[4]) for e in coeficientes] == [
        (eid_examen, 1.2857, "media_ponderada"),
        ("ig11", 16.0, "media_ponderada"),
        ("ig12", 8.0, "media_ponderada"),
        ("ig13", 6.0, "media_ponderada"),
        ("ig14", 45.0, "media_ponderada"),
    ]
    assert not plan_curso.plan.sin_cambios


def test_no_hay_pregunta_ni_se_pide_un_informe_de_notas(tmp_path):
    class Prohibida(PresenciaFalsa):
        def __getattribute__(self, nombre):
            if nombre.startswith("_") or nombre in ("__class__",):
                return super().__getattribute__(nombre)
            raise AssertionError(f"ponderacion_con no debe llamar a la presencia: {nombre}")

    aula = aula_con_e1()
    _, resultado = ejecutar(aula, esquema_e1(), tmp_path, presencia=Prohibida())
    assert resultado["resultado"] == "ok"
    for llamada in aula.llamadas:
        assert "report" not in str(llamada[0]).lower()
    assert {c[0] for c in aula.llamadas} <= {
        "estructura",
        "arbol_notas",
        "idnumbers_de",
        "arbol_ponderacion",
        "crear_categoria",
        "mover_nota",
        "fijar_coeficiente",
        "fijar_agregacion",
    }


def test_verificacion_correcta_informe_y_huellas(tmp_path):
    aula = aula_con_e1()
    _, resultado = ejecutar(aula, esquema_e1(), tmp_path)
    assert resultado["resultado"] == "ok"
    informe.validar(resultado)
    assert [p["codigo"] for p in resultado["pasos"]] == [
        "LOGIN",
        "PONDERACION_CAMBIOS",
        "PONDERACION",
    ]
    assert pasos(resultado, "PONDERACION")[0]["detalle"] == "aplicada"
    assert (
        pasos(resultado, "PONDERACION_CAMBIOS")[0]["detalle"]
        == "crear: 1; mover: 4; coeficiente: 5"
    )
    guardadas = huellas(tmp_path)
    assert set(guardadas) == {*REF_FICHEROS, REF_EXAMEN, REF_PRIMERA}
    segunda = preparar(aula, esquema_e1(), tmp_path)
    assert segunda.plan.sin_cambios and not segunda.plan.operaciones


def test_segunda_pasada_no_escribe_y_dice_sin_cambios(tmp_path):
    aula = aula_con_e1()
    ejecutar(aula, esquema_e1(), tmp_path)
    escritas = len(aula.escrituras)
    _, resultado = ejecutar(aula, esquema_e1(), tmp_path)
    assert len(aula.escrituras) == escritas
    assert pasos(resultado, "PONDERACION")[0]["detalle"] == "sin cambios"
    assert not pasos(resultado, "PONDERACION_CAMBIOS")
    assert resultado["resultado"] == "ok"


def test_sin_cambios_ni_huellas_no_crea_el_fichero(tmp_path):
    aula = aula_con_e1()
    ejecutar(aula, esquema_e1(), tmp_path)
    (tmp_path / ".tiza" / "ponderacion.json").unlink()
    # Sin huellas el plan sigue sin cambios: se anotan, porque lo del aula ya está bien.
    ejecutar(aula, esquema_e1(), tmp_path)
    assert set(huellas(tmp_path)) == {*REF_FICHEROS, REF_EXAMEN, REF_PRIMERA}


def test_el_sin_cambios_sin_nada_que_anotar_no_crea_el_fichero(tmp_path):
    vacio = ponderacion.PlanPonderacion(
        CURSO, (), (), (), (), (), (), corta=False, sin_cambios=True
    )
    aula = aula_con_e1()
    base = preparar(aula, esquema_e1(), tmp_path)
    plan_curso = dataclasses.replace(base, plan=vacio, esquema=type(base.esquema)(entradas=()))
    resultado = publicacion.ponderacion_con(aula, "real", CURSO, plan_curso, tmp_path / ".tiza")
    assert resultado["resultado"] == "ok"
    assert aula.escrituras == []
    assert not (tmp_path / ".tiza" / "ponderacion.json").exists()


def test_una_escritura_que_el_aula_no_refleja_es_parcial_y_sin_huella(tmp_path):
    aula = aula_con_e1()
    aula.sin_efecto = {"ig14"}
    _, resultado = ejecutar(aula, esquema_e1(), tmp_path)
    assert resultado["resultado"] == "ok"  # no corta el curso
    assert pasos(resultado, "PONDERACION")[0]["detalle"] == "parcial"
    fallos = pasos(resultado, "PONDERACION_NO_APLICADA")
    # Sin el 45 de la última, ningún porcentaje del examen es el pedido.
    assert {p["resultado"] for p in fallos} == {"fallo"}
    assert [p["detalle"] for p in fallos] == list(REF_FICHEROS)
    guardadas = huellas(tmp_path)
    assert not set(REF_FICHEROS) & set(guardadas)
    assert REF_EXAMEN in guardadas  # la categoría sí quedó verificada
    # El detalle solo lleva la referencia del esquema, nunca nombres ni ids del aula.
    assert "ig14" not in json.dumps(resultado)


def test_la_huella_vieja_de_lo_no_verificado_se_conserva(tmp_path):
    aula = aula_con_e1()
    aula.sin_efecto = {"ig14"}
    estado.guardar_huellas_ponderacion(tmp_path / ".tiza", CURSO, {REF_FICHEROS[3]: "a" * 64})
    ejecutar(aula, esquema_e1(), tmp_path)
    assert huellas(tmp_path)[REF_FICHEROS[3]] == "a" * 64


def test_un_fallo_a_medias_para_en_seco_y_la_pasada_siguiente_converge(tmp_path):
    aula = aula_con_e1()
    aula.fallar_tras = 6  # crear, 4 mover y el primer coeficiente
    _, resultado = ejecutar(aula, esquema_e1(), tmp_path)
    assert resultado["resultado"] == "error"
    assert resultado["errores"] == ["ESCRITURA_CALIFICADOR"]
    fallo = pasos(resultado, "PONDERACION")[0]
    assert (fallo["resultado"], fallo["detalle"]) == (
        "fallo",
        "ESCRITURA_CALIFICADOR tras 6 cambios",
    )
    assert pasos(resultado, "PONDERACION_CAMBIOS")[0]["detalle"] == (
        "crear: 1; mover: 4; coeficiente: 1"
    )
    guardadas = huellas(tmp_path)
    assert REF_EXAMEN in guardadas  # lo verificado: la categoría creada
    assert not set(REF_FICHEROS) & set(guardadas)  # con un solo coeficiente, ningún reparto cuadra
    assert pasos(resultado, "PONDERACION_NO_APLICADA") == []

    aula.fallar_tras = None
    segunda, resultado = ejecutar(aula, esquema_e1(), tmp_path)
    assert resultado["resultado"] == "ok"
    assert [o.tipo for o in segunda.plan.operaciones] == ["coeficiente"] * 4
    assert {*REF_FICHEROS, REF_EXAMEN, REF_PRIMERA} <= set(huellas(tmp_path))
    assert preparar(aula, esquema_e1(), tmp_path).plan.sin_cambios


def test_una_lectura_que_falla_tras_escribir_es_un_error_sin_huellas(tmp_path):
    aula = aula_con_e1()
    plan_curso = preparar(aula, esquema_e1(), tmp_path)
    aula.fallos["arbol_ponderacion"] = ["LECTURA_CALIFICADOR"]
    resultado = publicacion.ponderacion_con(aula, "real", CURSO, plan_curso, tmp_path / ".tiza")
    assert resultado["resultado"] == "error"
    assert resultado["errores"] == ["LECTURA_CALIFICADOR"]
    assert not (tmp_path / ".tiza" / "ponderacion.json").exists()


def test_un_plan_que_corta_no_escribe_y_dice_categoria_bloqueada(tmp_path):
    aula = aula_con_e1()
    plan_curso = preparar(aula, esquema_e1(), tmp_path)
    corta = dataclasses.replace(plan_curso.plan, operaciones=(), corta=True)
    resultado = publicacion.ponderacion_con(
        aula, "real", CURSO, dataclasses.replace(plan_curso, plan=corta), tmp_path / ".tiza"
    )
    assert resultado["resultado"] == "error"
    assert resultado["errores"] == ["CATEGORIA_BLOQUEADA"]
    assert [
        (p["codigo"], p["resultado"], p["detalle"]) for p in pasos(resultado, "PONDERACION")
    ] == [("PONDERACION", "fallo", "CATEGORIA_BLOQUEADA")]
    assert aula.escrituras == []


def test_los_cambios_a_mano_conservan_su_huella_vieja(tmp_path):
    aula = aula_con_e1()
    ejecutar(aula, esquema_e1(), tmp_path)
    antes = huellas(tmp_path)
    aula._cambiar("ig11", coeficiente=3.0, peso=3.0)  # el docente lo retoca
    _, resultado = ejecutar(aula, esquema_e1(), tmp_path)
    assert huellas(tmp_path)[REF_FICHEROS[0]] == antes[REF_FICHEROS[0]]
    assert resultado["resultado"] == "ok"


# --- natural: los pesos se repiten ---


def aula_natural_viva(**kw) -> AulaPonderada:
    return AulaPonderada(aula_natural(Actitud=50.0), **kw)


def test_natural_repite_los_pesos_hasta_que_el_aula_los_deja_bien(tmp_path):
    aula = aula_natural_viva()
    aula.deriva = 1  # la primera escritura del peso del examen queda al 90 %
    _, resultado = ejecutar(aula, esquema_natural(), tmp_path)
    assert resultado["resultado"] == "ok"
    assert pasos(resultado, "PONDERACION")[0]["detalle"] == "aplicada"
    assert not pasos(resultado, "PONDERACION_NO_APLICADA")
    eid_examen = next(n.eid for n in aula.arboles_ponderacion[CURSO].nodos if n.idnumber)
    pesos = [e for e in aula.escrituras if e[0] == "fijar_coeficiente" and e[2] == eid_examen]
    assert [e[3] for e in pesos] == [30.0, 30.0]
    assert pasos(resultado, "PONDERACION_CAMBIOS")[0]["detalle"] == (
        "crear: 1; mover: 4; coeficiente: 6"
    )
    assert REF_EXAMEN in huellas(tmp_path)
    assert preparar(aula, esquema_natural(), tmp_path).plan.sin_cambios


def test_natural_que_no_converge_se_agota_y_avisa_sin_cortar(tmp_path):
    aula = aula_natural_viva()
    aula.deriva = 1000
    _, resultado = ejecutar(aula, esquema_natural(), tmp_path)
    assert resultado["resultado"] == "ok"
    assert pasos(resultado, "PONDERACION")[0]["detalle"] == "parcial"
    detalles = [p["detalle"] for p in pasos(resultado, "PONDERACION_NO_APLICADA")]
    assert "pesos inestables" in detalles
    eid_examen = next(n.eid for n in aula.arboles_ponderacion[CURSO].nodos if n.idnumber)
    pesos = [e for e in aula.escrituras if e[0] == "fijar_coeficiente" and e[2] == eid_examen]
    assert len(pesos) == 1 + publicacion.MAX_PASADAS_DE_PESOS
    assert REF_EXAMEN not in huellas(tmp_path)


def test_media_ponderada_no_repite_los_pesos(tmp_path):
    aula = aula_con_e1()
    ejecutar(aula, esquema_e1(), tmp_path)
    lecturas = [c for c in aula.llamadas if c[0] == "arbol_ponderacion"]
    assert len(lecturas) == 2  # la del plan y la de la verificación
