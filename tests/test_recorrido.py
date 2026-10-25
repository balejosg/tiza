"""Tests del recorrido por cursos (``tiza.recorrido``) con un trabajo falso.

Offline y sin aula: cada test mira una regla del recorrido (pruebas, cupo, omitidos,
vigencia, corte e informe) con un trabajo que solo apunta lo que le piden.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from dobles import PresenciaFalsa
from tiza import config, informe, publicacion, recorrido
from tiza.calificacion.esquema import ErrorCalificacion
from tiza.estado import ErrorEstado
from tiza.publicar import ErrorPublicacion

CFG = config.Config(
    url="https://aula.ejemplo.org/centro",
    usuario="profe",
    cursos={"pruebas": 1234},
    reales=(101, 102),
)
CFG_UNO = config.Config(
    url="https://aula.ejemplo.org/centro",
    usuario="profe",
    cursos={"pruebas": 1234},
    reales=(101,),
)
CFG_SIN_PRUEBAS = config.Config(
    url="https://aula.ejemplo.org/centro",
    usuario="profe",
    cursos={},
    reales=(101,),
)


def _informe(curso: int, resultado: str = "ok", *, fichero: bool = False) -> dict:
    """Un informe de curso válido, con LOGIN para probar el agregado."""
    errores = ["ERROR_CONSULTA"] if resultado == "error" else []
    ficheros = (
        [informe.Fichero(nombre=f"p{curso}.md", tipo="pagina", curso=curso)] if fichero else []
    )
    return informe.crear(
        "publicar",
        resultado,
        [informe.Paso("LOGIN"), informe.Paso("PUBLICAR", detalle=str(curso))],
        ficheros,
        errores,
        "real",
        curso,
    )


class TrabajoFalso(recorrido.TrabajoBase):
    """Un trabajo configurable: gasto, comprobación, aviso, preparación y resultado."""

    comando = "publicar"

    def __init__(
        self,
        *,
        gasto: int = 1,
        comprobacion: str | None = None,
        aviso: publicacion.Aviso | None = None,
        preparacion: str | None = None,
        por_curso: dict[int, recorrido.Resultado] | None = None,
        en_pruebas: dict | None = None,
    ) -> None:
        self._gasto = gasto
        self._comprobacion = comprobacion
        self._aviso = aviso
        self._preparacion = preparacion
        self._por_curso = por_curso or {}
        self._en_pruebas = en_pruebas
        self.visitados: list[int] = []
        self.turnos: list[recorrido.Turno] = []
        self.comprobaciones: list[int] = []
        self.preparaciones = 0
        self.pruebas: list[int] = []

    def gasto_en_pruebas(self) -> int:
        return self._gasto

    def comprobar_en_pruebas(self, curso: int) -> str | None:
        self.comprobaciones.append(curso)
        return self._comprobacion

    def aviso_en_pruebas(self) -> publicacion.Aviso | None:
        return self._aviso

    def preparar_real(self) -> str | None:
        self.preparaciones += 1
        return self._preparacion

    def en_pruebas(self, curso: int) -> dict:
        self.pruebas.append(curso)
        if self._en_pruebas is not None:
            return self._en_pruebas
        return informe.crear("publicar", "ok", [informe.Paso("LOGIN")], [], None, "pruebas", curso)

    def en_curso(self, turno: recorrido.Turno) -> recorrido.Resultado:
        self.visitados.append(turno.curso)
        self.turnos.append(turno)
        return self._por_curso.get(turno.curso, recorrido.Resultado.hecho(_informe(turno.curso)))


class TrabajoQuePregunta(TrabajoFalso):
    """Pregunta como publicar: la normal y, si toca, la de sobrescribir."""

    def __init__(self, *, segunda: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.segunda = segunda
        self.preguntas: list[bool] = []
        self.llamadas_preguntar = 0
        self.escribio = False

    def en_curso(self, turno: recorrido.Turno) -> recorrido.Resultado:
        self.visitados.append(turno.curso)
        self.turnos.append(turno)
        self.llamadas_preguntar += 1
        confirmado = turno.preguntar(lambda p: p.confirmar_real("resumen"))
        self.preguntas.append(confirmado)
        if not confirmado:
            return recorrido.Resultado.declinado()
        if self.segunda:
            self.llamadas_preguntar += 1
            self.preguntas.append(
                turno.preguntar(
                    lambda p: p.confirmar_sobrescribir("resumen"),
                    tras_no=True,
                )
            )
        self.escribio = True
        return recorrido.Resultado.hecho(_informe(turno.curso))


def test_pruebas_sin_curso_da_sin_curso_pruebas():
    trabajo = TrabajoFalso()
    documento = recorrido.recorrer(trabajo, CFG_SIN_PRUEBAS, PresenciaFalsa(), entorno="pruebas")
    assert documento["errores"] == ["SIN_CURSO_PRUEBAS"]
    assert trabajo.pruebas == []


def test_la_comprobacion_previa_falla_antes_de_gastar_cupo():
    trabajo = TrabajoFalso(gasto=5, comprobacion="SOLO_FECHAS_NO_APLICA")
    cupo = {"pruebas": 0}
    documento = recorrido.recorrer(trabajo, CFG, PresenciaFalsa(), entorno="pruebas", cupo=cupo)
    assert documento["errores"] == ["SOLO_FECHAS_NO_APLICA"]
    assert documento["curso"] == 1234
    assert cupo == {"pruebas": 0}
    assert trabajo.pruebas == []


def test_el_cupo_se_suma_y_se_agota_con_limite_publicaciones():
    trabajo = TrabajoFalso(gasto=2)
    cupo = {"pruebas": recorrido.MAX_PUBLICACIONES_PRUEBAS - 2}
    documento = recorrido.recorrer(trabajo, CFG, PresenciaFalsa(), entorno="pruebas", cupo=cupo)
    assert documento["resultado"] == "ok"
    assert cupo["pruebas"] == recorrido.MAX_PUBLICACIONES_PRUEBAS
    documento = recorrido.recorrer(trabajo, CFG, PresenciaFalsa(), entorno="pruebas", cupo=cupo)
    assert documento["errores"] == ["LIMITE_PUBLICACIONES"]
    assert cupo["pruebas"] == recorrido.MAX_PUBLICACIONES_PRUEBAS
    assert trabajo.pruebas == [1234]


def test_sin_cupo_no_hay_tope():
    trabajo = TrabajoFalso(gasto=10_000)
    documento = recorrido.recorrer(trabajo, CFG, PresenciaFalsa(), entorno="pruebas")
    assert documento["resultado"] == "ok"
    assert trabajo.pruebas == [1234]


@pytest.mark.parametrize("avisar", [True, False])
def test_el_aviso_en_pruebas_solo_si_se_pide(avisar):
    presencia = PresenciaFalsa()
    trabajo = TrabajoFalso(aviso=publicacion.Aviso.publicando_en_pruebas(()))
    recorrido.recorrer(
        trabajo,
        CFG,
        presencia,
        entorno="pruebas",
        avisar_en_pruebas=avisar,
    )
    assert ("PUBLICANDO_EN_PRUEBAS" in presencia.codigos()) is avisar


def test_pruebas_devuelve_el_informe_del_trabajo_tal_cual():
    esperado = _informe(1234)
    documento = recorrido.recorrer(
        TrabajoFalso(en_pruebas=esperado), CFG, PresenciaFalsa(), entorno="pruebas"
    )
    assert documento is esperado


@pytest.mark.parametrize("cfg, curso", [(CFG_UNO, 101), (CFG, None)])
def test_preparar_real_con_codigo_para_antes_de_los_cursos(cfg, curso):
    trabajo = TrabajoFalso(preparacion="VERIFICACION_PENDIENTE")
    documento = recorrido.recorrer(trabajo, cfg, PresenciaFalsa(real=True), entorno="real")
    assert documento["errores"] == ["VERIFICACION_PENDIENTE"]
    assert documento["curso"] == curso
    assert trabajo.visitados == []
    assert trabajo.preparaciones == 1


def test_preparar_real_se_llama_una_vez_con_varios_cursos():
    trabajo = TrabajoFalso()
    recorrido.recorrer(trabajo, CFG, PresenciaFalsa(real=True), entorno="real")
    assert trabajo.preparaciones == 1
    assert trabajo.visitados == [101, 102]


def test_los_omitidos_se_saltan_sin_preguntar_ni_mirar_la_vigencia():
    llamadas: list[bool] = []

    def vigente() -> bool:
        llamadas.append(True)
        return True

    trabajo = TrabajoFalso()
    documento = recorrido.recorrer(
        trabajo,
        CFG,
        PresenciaFalsa(real=True),
        entorno="real",
        vigente=vigente,
        omitidos={101},
    )
    assert trabajo.visitados == [102]
    assert len(llamadas) == 1  # la de antes del segundo curso; el omitido no la mira
    assert {"codigo": "CURSO_OMITIDO", "resultado": "ok", "detalle": "101"} in documento["pasos"]


def test_la_vigencia_se_mira_antes_de_cada_curso_salvo_el_primero():
    llamadas: list[bool] = []

    def vigente() -> bool:
        llamadas.append(True)
        return True

    trabajo = TrabajoFalso()
    recorrido.recorrer(
        trabajo,
        config.Config(
            url=CFG.url,
            usuario=CFG.usuario,
            cursos={"pruebas": 1234},
            reales=(101, 102, 103),
        ),
        PresenciaFalsa(real=True),
        entorno="real",
        vigente=vigente,
    )
    assert len(llamadas) == 2
    assert trabajo.visitados == [101, 102, 103]


def test_retirada_antes_de_un_curso_para_con_aviso_y_registro():
    presencia = PresenciaFalsa(real=True)
    trabajo = TrabajoFalso()
    documento = recorrido.recorrer(
        trabajo,
        CFG,
        presencia,
        entorno="real",
        vigente=lambda: False,
    )
    assert trabajo.visitados == [101]
    assert documento["resultado"] == "error"
    assert documento["errores"] == ["PETICION_RETIRADA"]
    assert "PETICION_RETIRADA" in presencia.codigos()
    assert ("CURSO", "ok") in [(paso["codigo"], paso["resultado"]) for paso in documento["pasos"]]
    assert ("CURSO", "fallo") in [
        (paso["codigo"], paso["resultado"]) for paso in documento["pasos"]
    ]


def test_sin_vigente_no_hay_peticion_que_retirar():
    trabajo = TrabajoQuePregunta(segunda=True)
    documento = recorrido.recorrer(
        trabajo,
        CFG_UNO,
        PresenciaFalsa(real=True, sobrescribir=True),
        entorno="real",
    )
    assert trabajo.llamadas_preguntar == 2
    assert trabajo.preguntas == [True, True]
    assert trabajo.escribio is True
    assert documento["resultado"] == "ok"


def test_retirada_tras_un_si_interrumpe_el_trabajo_sin_escribir():
    trabajo = TrabajoQuePregunta()
    documento = recorrido.recorrer(
        trabajo,
        CFG_UNO,
        PresenciaFalsa(real=True),
        entorno="real",
        vigente=lambda: False,
    )
    assert trabajo.llamadas_preguntar == 1
    assert trabajo.preguntas == []
    assert trabajo.escribio is False
    assert documento["errores"] == ["PETICION_RETIRADA"]


def test_retirada_tras_el_segundo_si_de_un_mismo_curso():
    respuestas = iter([True, False])
    trabajo = TrabajoQuePregunta(segunda=True)
    documento = recorrido.recorrer(
        trabajo,
        CFG_UNO,
        PresenciaFalsa(real=True, sobrescribir=True),
        entorno="real",
        vigente=lambda: next(respuestas),
    )
    assert trabajo.llamadas_preguntar == 2
    assert trabajo.preguntas == [True]
    assert trabajo.escribio is False
    assert documento["errores"] == ["PETICION_RETIRADA"]


def test_tras_un_no_no_se_mira_la_vigencia():
    def vigente() -> bool:
        raise AssertionError("no se debe mirar la vigencia tras el no que declina")

    trabajo = TrabajoQuePregunta()
    documento = recorrido.recorrer(
        trabajo,
        CFG_UNO,
        PresenciaFalsa(real=False),
        entorno="real",
        vigente=vigente,
    )
    assert trabajo.preguntas == [False]
    assert trabajo.escribio is False
    assert documento["resultado"] == "abortado"
    assert documento["errores"] == ["ABORTADO"]


def test_tras_un_no_a_sobrescribir_se_mira_la_vigencia():
    respuestas = iter([True, False])
    trabajo = TrabajoQuePregunta(segunda=True)
    documento = recorrido.recorrer(
        trabajo,
        CFG_UNO,
        PresenciaFalsa(real=True, sobrescribir=False),
        entorno="real",
        vigente=lambda: next(respuestas),
    )
    assert trabajo.llamadas_preguntar == 2
    assert trabajo.preguntas == [True]
    assert trabajo.escribio is False
    assert documento["errores"] == ["PETICION_RETIRADA"]


def test_el_trabajo_no_puede_capturar_la_retirada():
    assert not issubclass(
        recorrido.PeticionRetirada, (ErrorPublicacion, ErrorCalificacion, ErrorEstado)
    )

    class Tragon(TrabajoFalso):
        def en_curso(self, turno):
            try:
                turno.preguntar(lambda p: p.confirmar_real("resumen"))
            except (ErrorPublicacion, ErrorCalificacion, ErrorEstado):
                return recorrido.Resultado.declinado()
            return recorrido.Resultado.hecho(_informe(turno.curso))

    documento = recorrido.recorrer(
        Tragon(),
        CFG_UNO,
        PresenciaFalsa(real=True),
        entorno="real",
        vigente=lambda: False,
    )
    assert documento["errores"] == ["PETICION_RETIRADA"]


def test_un_declinado_se_omite_y_se_sigue():
    trabajo = TrabajoFalso(
        por_curso={
            101: recorrido.Resultado.declinado(),
            102: recorrido.Resultado.hecho(_informe(102)),
        }
    )
    documento = recorrido.recorrer(trabajo, CFG, PresenciaFalsa(real=True), entorno="real")
    assert trabajo.visitados == [101, 102]
    assert documento["resultado"] == "ok"
    assert {"codigo": "CURSO_OMITIDO", "resultado": "ok", "detalle": "101"} in documento["pasos"]
    assert ("CURSO", "ok") in [(paso["codigo"], paso["resultado"]) for paso in documento["pasos"]]


def test_un_hecho_no_ok_corta():
    trabajo = TrabajoFalso(
        por_curso={
            101: recorrido.Resultado.hecho(_informe(101, "error")),
            102: recorrido.Resultado.hecho(_informe(102)),
        }
    )
    documento = recorrido.recorrer(trabajo, CFG, PresenciaFalsa(real=True), entorno="real")
    assert trabajo.visitados == [101]
    assert documento["resultado"] == "error"
    assert documento["errores"] == ["ERROR_CONSULTA"]


def test_un_hecho_sin_cortar_deja_seguir_pero_el_informe_es_error():
    trabajo = TrabajoFalso(
        por_curso={
            101: recorrido.Resultado.hecho_sin_cortar(_informe(101, "error")),
            102: recorrido.Resultado.hecho(_informe(102)),
        }
    )
    documento = recorrido.recorrer(trabajo, CFG, PresenciaFalsa(real=True), entorno="real")
    assert trabajo.visitados == [101, 102]
    assert documento["resultado"] == "error"
    assert ("CURSO", "fallo") in [
        (paso["codigo"], paso["resultado"]) for paso in documento["pasos"]
    ]
    assert ("CURSO", "ok") in [(paso["codigo"], paso["resultado"]) for paso in documento["pasos"]]


def test_un_fallo_corta_con_su_codigo_y_el_curso():
    trabajo = TrabajoFalso(
        por_curso={101: recorrido.Resultado.fallo("ERROR_CONSULTA")},
    )
    documento = recorrido.recorrer(trabajo, CFG, PresenciaFalsa(real=True), entorno="real")
    assert trabajo.visitados == [101]
    assert documento["errores"] == ["ERROR_CONSULTA"]
    assert ("CURSO", "fallo") in [
        (paso["codigo"], paso["resultado"]) for paso in documento["pasos"]
    ]


def test_el_orden_de_los_cursos_es_el_de_la_config():
    cfg = config.Config(
        url=CFG.url,
        usuario=CFG.usuario,
        cursos={"pruebas": 1234},
        reales=(102, 101),
    )
    trabajo = TrabajoFalso()
    recorrido.recorrer(trabajo, cfg, PresenciaFalsa(real=True), entorno="real")
    assert trabajo.visitados == [102, 101]


def test_un_curso_unico_devuelve_su_informe_tal_cual():
    esperado = _informe(101)
    trabajo = TrabajoFalso(por_curso={101: recorrido.Resultado.hecho(esperado)})
    documento = recorrido.recorrer(trabajo, CFG_UNO, PresenciaFalsa(real=True), entorno="real")
    assert documento is esperado


def test_un_curso_unico_declinado_es_abortado():
    trabajo = TrabajoFalso(por_curso={101: recorrido.Resultado.declinado()})
    documento = recorrido.recorrer(trabajo, CFG_UNO, PresenciaFalsa(real=True), entorno="real")
    assert documento["resultado"] == "abortado"
    assert documento["errores"] == ["ABORTADO"]
    assert documento["curso"] == 101


def test_todos_declinados_u_omitidos_es_abortado():
    trabajo = TrabajoFalso(
        por_curso={
            101: recorrido.Resultado.declinado(),
            102: recorrido.Resultado.declinado(),
        }
    )
    documento = recorrido.recorrer(trabajo, CFG, PresenciaFalsa(real=True), entorno="real")
    assert documento["resultado"] == "abortado"
    assert documento["errores"] == ["ABORTADO"]

    documento = recorrido.recorrer(
        TrabajoFalso(),
        CFG,
        PresenciaFalsa(real=True),
        entorno="real",
        omitidos={101, 102},
    )
    assert documento["resultado"] == "abortado"
    assert documento["errores"] == ["ABORTADO"]


def test_con_varios_cursos_el_login_sale_una_vez():
    trabajo = TrabajoFalso(
        por_curso={
            101: recorrido.Resultado.hecho(_informe(101)),
            102: recorrido.Resultado.hecho(_informe(102)),
        }
    )
    documento = recorrido.recorrer(trabajo, CFG, PresenciaFalsa(real=True), entorno="real")
    assert [paso["codigo"] for paso in documento["pasos"]].count("LOGIN") == 1
    assert [paso["detalle"] for paso in documento["pasos"] if paso["codigo"] == "CURSO"] == [
        "1 de 2: 101",
        "2 de 2: 102",
    ]


def test_un_curso_fallido_sale_como_fallo_y_los_hechos_quedan():
    cfg = config.Config(
        url=CFG.url,
        usuario=CFG.usuario,
        cursos={"pruebas": 1234},
        reales=(101, 102, 103),
    )
    trabajo = TrabajoFalso(
        por_curso={
            101: recorrido.Resultado.hecho(_informe(101, fichero=True)),
            102: recorrido.Resultado.fallo("ERROR_CONSULTA"),
        }
    )
    documento = recorrido.recorrer(trabajo, cfg, PresenciaFalsa(real=True), entorno="real")
    assert trabajo.visitados == [101, 102]
    assert documento["resultado"] == "error"
    assert [fichero["nombre"] for fichero in documento["ficheros"]] == ["p101.md"]
    assert [paso["detalle"] for paso in documento["pasos"] if paso["codigo"] == "CURSO"] == [
        "1 de 3: 101",
        "2 de 3: 102",
    ]


def test_nombre_y_posicion_del_turno():
    trabajo = TrabajoFalso()
    recorrido.recorrer(
        trabajo,
        CFG,
        PresenciaFalsa(real=True),
        entorno="real",
        nombres={101: "1º A"},
    )
    assert [(t.curso, t.posicion, t.total, t.nombre_curso) for t in trabajo.turnos] == [
        (101, 1, 2, "1º A"),
        (102, 2, 2, None),
    ]


# --------------------------------------------------------------------------- #
# La estructura: el bucle y las preguntas viven solo en el recorrido
# --------------------------------------------------------------------------- #


def _arbol(modulo) -> tuple[ast.Module, str]:
    fuente = Path(modulo.__file__).read_text(encoding="utf-8")
    return ast.parse(fuente), fuente


def _padres(arbol: ast.AST) -> dict[ast.AST, ast.AST]:
    return {hijo: nodo for nodo in ast.walk(arbol) for hijo in ast.iter_child_nodes(nodo)}


def _llamadas(arbol: ast.AST) -> list[ast.Call]:
    return [nodo for nodo in ast.walk(arbol) if isinstance(nodo, ast.Call)]


def _dentro_de_preguntar(nodo: ast.AST, padres: dict[ast.AST, ast.AST]) -> bool:
    actual = nodo
    while actual in padres:
        actual = padres[actual]
        if not isinstance(actual, ast.Call):
            continue
        funcion = actual.func
        if (
            isinstance(funcion, ast.Attribute)
            and funcion.attr == "preguntar"
            and isinstance(funcion.value, ast.Name)
            and funcion.value.id == "turno"
        ):
            return True
    return False


def _arbol_de(objeto) -> ast.AST:
    return ast.parse(inspect.getsource(objeto))


def test_solo_el_recorrido_recorre_los_cursos_y_mira_la_vigencia():
    def enumera_los_reales(arbol: ast.AST) -> bool:
        return any(
            isinstance(llamada.func, ast.Name)
            and llamada.func.id == "enumerate"
            and llamada.args
            and isinstance(llamada.args[0], ast.Name)
            and llamada.args[0].id == "reales"
            for llamada in _llamadas(arbol)
        )

    def llama_a_vigente(arbol: ast.AST) -> bool:
        return any(
            isinstance(llamada.func, ast.Name) and llamada.func.id == "vigente"
            for llamada in _llamadas(arbol)
        )

    recorridos = (
        publicacion.publicar_en_cursos,
        publicacion.ordenar_en_cursos,
        publicacion.calificador_en_cursos,
        publicacion._TrabajoPublicar,
        publicacion._TrabajoOrdenar,
        publicacion._TrabajoCalificador,
    )
    for objeto in recorridos:
        arbol = _arbol_de(objeto)
        assert not enumera_los_reales(arbol), objeto.__name__
        assert not llama_a_vigente(arbol), objeto.__name__
    arbol_recorrido, _ = _arbol(recorrido)
    assert enumera_los_reales(arbol_recorrido)
    assert llama_a_vigente(arbol_recorrido)


def test_las_confirmaciones_de_los_trabajos_pasan_por_el_turno():
    for clase in (
        publicacion._TrabajoPublicar,
        publicacion._TrabajoOrdenar,
        publicacion._TrabajoCalificador,
    ):
        arbol = _arbol_de(clase)
        padres = _padres(arbol)
        for llamada in _llamadas(arbol):
            funcion = llamada.func
            if isinstance(funcion, ast.Attribute) and funcion.attr.startswith("confirmar_"):
                assert _dentro_de_preguntar(llamada, padres), f"{clase.__name__}: {funcion.attr}"


def test_las_funciones_externas_delegan_en_el_recorrido_sin_bucle():
    fuente = Path(publicacion.__file__).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    for nombre in ("publicar_en_cursos", "ordenar_en_cursos", "calificador_en_cursos"):
        nodo = next(
            nodo for nodo in arbol.body if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre
        )
        assert not any(isinstance(hijo, (ast.For, ast.AsyncFor)) for hijo in ast.walk(nodo))
        segmento = ast.get_source_segment(fuente, nodo)
        assert segmento is not None and "recorrido.recorrer(" in segmento
    assert not hasattr(publicacion, "MAX_PUBLICACIONES_PRUEBAS")
    assert hasattr(recorrido, "MAX_PUBLICACIONES_PRUEBAS")


def test_recorrido_no_carga_publicacion_ni_python_moodle():
    codigo = (
        "import sys\n"
        "import tiza.recorrido\n"
        "assert 'tiza.publicacion' not in sys.modules, 'publicacion cargada'\n"
        "assert 'py_moodle' not in sys.modules, 'python-moodle cargado'\n"
    )
    subprocess.run([sys.executable, "-I", "-c", codigo], check=True)
