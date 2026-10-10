"""Tests de presencia humana: TTY, confirmación de destino y contraseña."""

from __future__ import annotations

import inspect
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tiza import informe, sesion, terminal


class TerminalFalsa:
    def __init__(self, interactiva: bool):
        self._interactiva = interactiva

    def isatty(self) -> bool:
        return self._interactiva

    def readline(self) -> str:
        return "s\n"

    def write(self, texto: str) -> int:
        return len(texto)

    def flush(self) -> None:
        pass


def test_sin_tty_falla(monkeypatch):
    monkeypatch.setattr("sys.stdin", TerminalFalsa(False))
    monkeypatch.setattr("sys.stdout", TerminalFalsa(True))
    with pytest.raises(terminal.ErrorTerminal) as exc:
        terminal.exigir_tty()
    assert exc.value.codigo == "SIN_TTY"


def test_con_tty_pasa(monkeypatch):
    monkeypatch.setattr("sys.stdin", TerminalFalsa(True))
    monkeypatch.setattr("sys.stdout", TerminalFalsa(True))
    terminal.exigir_tty()


def test_confirmar_destino_muestra_curso_y_entorno(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "s")
    assert terminal.confirmar_destino("pruebas", 1234) is True
    salida = capsys.readouterr().out
    assert "pruebas" in salida
    assert "1234" in salida


def test_confirmar_destino_acepta_s(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "s")
    assert terminal.confirmar_destino("pruebas", 1234) is True


def test_confirmar_destino_rechaza_enter(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    assert terminal.confirmar_destino("pruebas", 1234) is False


def test_confirmar_destino_rechaza_n(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    assert terminal.confirmar_destino("pruebas", 1234) is False


def test_password_solo_desde_getpass(monkeypatch):
    monkeypatch.setenv("TIZA_PASSWORD", "desde-el-entorno")
    monkeypatch.setattr(terminal.getpass, "getpass", lambda _prompt="": "desde-la-terminal")
    assert terminal.pedir_password() == "desde-la-terminal"


def test_texto_seguro_quita_escapes_y_controles_bidi():
    sucio = "Tema\x1b[2K\x9b8m\N{RIGHT-TO-LEFT OVERRIDE}oculto\u061c\N{LEFT-TO-RIGHT ISOLATE}\x00"
    limpio = terminal.texto_seguro(sucio)
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


def test_texto_seguro_recorta():
    assert terminal.texto_seguro("x" * 500, maximo=10) == "x" * 9 + "…"


def test_texto_seguro_con_maximo_no_positivo_devuelve_vacio():
    assert terminal.texto_seguro("abc", maximo=0) == ""
    assert terminal.texto_seguro("abc", maximo=-5) == ""


def test_texto_seguro_no_trunca_si_cabe_justo():
    assert terminal.texto_seguro("abc", maximo=3) == "abc"


def test_texto_seguro_conserva_acentos():
    assert terminal.texto_seguro("Matemáticas 2ºB «ñ»") == "Matemáticas 2ºB «ñ»"


def responder(monkeypatch, respuestas):
    pendientes = iter(respuestas)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(pendientes))


CURSOS = [{"id": 5678, "nombre": "Matemáticas 2ºB"}, {"id": 1234, "nombre": "Pruebas de Mates"}]


def test_confirmar_acepta_si(monkeypatch):
    for respuesta, esperado in (("s", True), ("Sí", True), ("", False), ("n", False)):
        responder(monkeypatch, [respuesta])
        assert terminal.confirmar("¿Seguir?") is esperado


def test_confirmar_destino_muestra_nombre(monkeypatch, capsys):
    responder(monkeypatch, ["s"])
    assert terminal.confirmar_destino("real", 5678, "Matemáticas 2ºB") is True
    assert "«Matemáticas 2ºB» (id 5678)" in capsys.readouterr().out


def test_describir_curso_sin_nombre():
    assert terminal.describir_curso(5678, None) == "id 5678"


def test_elegir_curso_por_numero(monkeypatch, capsys):
    responder(monkeypatch, ["2"])
    assert terminal.elegir_curso("pruebas", CURSOS) == 1234
    salida = capsys.readouterr().out
    assert "1. Matemáticas 2ºB" in salida and "2. Pruebas de Mates" in salida


def test_elegir_curso_excluye_el_otro(monkeypatch, capsys):
    responder(monkeypatch, ["1"])
    assert terminal.elegir_curso("real", CURSOS, excluir=1234) == 5678
    assert "Pruebas de Mates" not in capsys.readouterr().out
    responder(monkeypatch, ["0", "1234", "999"])  # id manual igual al otro: se rechaza
    assert terminal.elegir_curso("real", CURSOS, excluir=1234) == 999


def test_elegir_curso_reintenta_y_cancela(monkeypatch):
    responder(monkeypatch, ["7", "x", ""])
    assert terminal.elegir_curso("pruebas", CURSOS) is None


def test_elegir_curso_de_pruebas_admite_no_tener(monkeypatch, capsys):
    responder(monkeypatch, ["3"])
    assert terminal.elegir_curso("pruebas", CURSOS) == sesion.SIN_PRUEBAS
    assert "No tengo curso de pruebas" in capsys.readouterr().out


def test_elegir_curso_real_no_admite_no_tener(monkeypatch):
    responder(monkeypatch, ["3", ""])
    assert terminal.elegir_curso("real", CURSOS) is None


def test_elegir_curso_sin_lista_pide_id(monkeypatch):
    responder(monkeypatch, ["4321"])
    assert terminal.elegir_curso("pruebas", []) == 4321


def test_elegir_cursos_reales_con_numeros_separados_por_comas(monkeypatch, capsys):
    responder(monkeypatch, ["2, 1"])
    assert terminal.elegir_cursos_reales(CURSOS) == [1234, 5678]
    salida = capsys.readouterr().out
    assert "1. Matemáticas 2ºB" in salida and "2. Pruebas de Mates" in salida


def test_elegir_cursos_reales_excluye_el_de_pruebas(monkeypatch, capsys):
    responder(monkeypatch, ["1"])
    assert terminal.elegir_cursos_reales(CURSOS, excluir=1234) == [5678]
    assert "Pruebas de Mates" not in capsys.readouterr().out


@pytest.mark.parametrize("mala", ["3", "0,1", "1,1", "a", "1,,2", "1;2", "9" * 5000])
def test_elegir_cursos_reales_rechaza_y_reintenta(monkeypatch, mala):
    responder(monkeypatch, [mala, "1"])
    assert terminal.elegir_cursos_reales(CURSOS) == [5678]


def test_elegir_cursos_reales_no_pasa_del_maximo(monkeypatch):
    cursos = [{"id": n, "nombre": f"Curso {n}"} for n in range(1, 9)]
    responder(monkeypatch, ["1,2,3,4,5,6,7", "1,2,3,4,5,6"])
    assert terminal.elegir_cursos_reales(cursos) == [1, 2, 3, 4, 5, 6]


def test_elegir_cursos_reales_pide_ids_a_mano(monkeypatch):
    responder(monkeypatch, ["0", "7, 1234, x", "1234", "7,8"])
    assert terminal.elegir_cursos_reales(CURSOS, excluir=1234) == [7, 8]


def test_elegir_cursos_reales_sin_lista_pide_ids(monkeypatch):
    responder(monkeypatch, ["4321,4322"])
    assert terminal.elegir_cursos_reales([]) == [4321, 4322]


def test_elegir_cursos_reales_cancela_con_enter_y_con_eof(monkeypatch):
    responder(monkeypatch, [""])
    assert terminal.elegir_cursos_reales(CURSOS) is None
    responder(monkeypatch, ["0", ""])
    assert terminal.elegir_cursos_reales(CURSOS) is None


def eof(monkeypatch):
    def _input(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _input)


def test_confirmar_eof_devuelve_false(monkeypatch):
    eof(monkeypatch)
    assert terminal.confirmar("¿Seguir?") is False


def test_elegir_cursos_reales_eof_devuelve_none(monkeypatch):
    eof(monkeypatch)
    assert terminal.elegir_cursos_reales(CURSOS) is None
    assert terminal.elegir_cursos_reales([]) is None


def test_elegir_curso_eof_devuelve_none(monkeypatch):
    eof(monkeypatch)
    assert terminal.elegir_curso("pruebas", CURSOS) is None


def test_elegir_curso_sin_lista_eof_devuelve_none(monkeypatch):
    eof(monkeypatch)
    assert terminal.elegir_curso("pruebas", []) is None


def test_elegir_curso_entrada_gigante_reintenta_y_cancela(monkeypatch):
    responder(monkeypatch, ["9" * 5000, ""])
    assert terminal.elegir_curso("pruebas", CURSOS) is None


def test_pedir_id_entrada_gigante_luego_valido(monkeypatch):
    responder(monkeypatch, ["9" * 5000, "123"])
    assert terminal.elegir_curso("pruebas", []) == 123


def test_preguntar_con_limite_si(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p="": "s")
    assert terminal.preguntar_con_limite("¿Ampliar?", 1) is True


def test_preguntar_con_limite_no(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p="": "")
    assert terminal.preguntar_con_limite("¿Ampliar?", 1) is False


def test_preguntar_con_limite_sin_respuesta_es_no(monkeypatch):
    bloqueo = threading.Event()
    monkeypatch.setattr("builtins.input", lambda _p="": bloqueo.wait(5) and "s")
    try:
        assert terminal.preguntar_con_limite("¿Ampliar?", 0.1, tramo=0.02) is False
    finally:
        bloqueo.set()


def test_preguntar_con_limite_espera_en_tramos(monkeypatch):
    esperas: list = []
    import queue as cola

    class ColaQueMide(cola.Queue):
        def get(self, block=True, timeout=None):
            esperas.append(timeout)
            raise cola.Empty

    monkeypatch.setattr(terminal.queue, "Queue", ColaQueMide)
    monkeypatch.setattr("builtins.input", lambda _p="": threading.Event().wait(1) and "")
    assert terminal.preguntar_con_limite("¿Ampliar?", 0.05, tramo=0.01) is False
    assert esperas and max(esperas) <= 0.01


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
    return sesion.DocumentoResumen(**datos)


def test_presencia_terminal_cumple_la_interfaz():
    metodos = [
        nombre
        for nombre, valor in vars(sesion.Presencia).items()
        if callable(valor) and not nombre.startswith("_")
    ]
    for nombre in metodos:
        esperado = list(inspect.signature(getattr(sesion.Presencia, nombre)).parameters)
        obtenido = list(inspect.signature(getattr(terminal.PresenciaTerminal, nombre)).parameters)
        assert obtenido == esperado, nombre


def test_la_terminal_sabe_mostrar_todos_los_avisos(capsys):
    datos = {
        "CREANDO_SECCION": {"nombre": "Tema"},
        "CURSOS_GUARDADOS": {"ruta": Path("tiza.toml")},
        "ERROR_INTERNO": {"tipo": "RuntimeError"},
        "FALLO": {"codigo": "LOGIN_FALLIDO", "detalle": ""},
        "MAXIMO_ALCANZADO": {"horas": 8},
        "PUBLICANDO_EN_PRUEBAS": {"documentos": (_doc(),)},
        "QUEDAN_MINUTOS": {"minutos": 5},
        "RESULTADO": {"documento": informe.crear("publicar", "ok", [], [], [], "pruebas", 1234)},
        "SESION_ABIERTA": {"caduca": datetime(2026, 10, 3, 10, 0, tzinfo=UTC)},
        "SESION_CERRADA": {"motivo": "caducada"},
    }
    presencia = terminal.PresenciaTerminal()
    for codigo in sorted(sesion.AVISOS):
        presencia.informar(sesion.Aviso(codigo, datos.get(codigo, {})))
    salida = capsys.readouterr()
    assert "Creando la sección «Tema» (oculta)..." in salida.out
    assert "La sesión ha caducado; se cierra." in salida.out
    assert "ERROR [LOGIN_FALLIDO]" in salida.err
    assert "Operación cancelada." in salida.err


def test_confirmar_real_sin_pruebas_muestra_lo_justo(monkeypatch, capsys):
    vistos: list = []
    monkeypatch.setattr(
        terminal,
        "confirmar_destino",
        lambda entorno, curso, nombre=None: vistos.append((entorno, curso, nombre)) or True,
    )
    resumen = sesion.ResumenSinPruebas(
        curso=5678,
        nombre_curso="Matemáticas 2ºB",
        documentos=(
            sesion.DocumentoBreve("t.md", "tarea", "Problemas", existe=True),
            sesion.DocumentoBreve("nueva.md", "pagina", "Nueva", existe=False),
            sesion.DocumentoBreve("duda.md", "pagina", "Duda", existe=None),
        ),
        secciones_nuevas=("Fracciones",),
    )
    assert terminal.PresenciaTerminal().confirmar_real_sin_pruebas(resumen) is True
    salida = capsys.readouterr().out
    assert (
        "Sin curso de pruebas: se publicará solo en oculto en el curso «Matemáticas 2ºB» (id 5678)"
        in salida
    )
    assert "Tarea «Problemas»" in salida and "t.md" in salida
    assert "Página «Nueva»" in salida and "Página «Duda»" in salida
    assert salida.count("Ya existe en el aula: se ocultará si estaba visible.") == 1
    assert "Puede que ya exista en el aula: se ocultará si estaba visible." in salida
    assert "Se creará la sección «Fracciones» (oculta)" in salida
    assert "vista previa" not in salida
    assert vistos == [("real", 5678, "Matemáticas 2ºB")]


def test_confirmar_real_muestra_todo_y_pregunta_con_el_nombre(monkeypatch, capsys, tmp_path):
    vista = tmp_path / "t.html"
    vista.write_text("x", encoding="utf-8")
    vistos: list = []
    monkeypatch.setattr(
        terminal,
        "confirmar_destino",
        lambda entorno, curso, nombre=None: vistos.append((entorno, curso, nombre)) or True,
    )
    resumen = sesion.ResumenPublicacion(
        curso=5678,
        nombre_curso="Matemáticas 2ºB",
        documentos=(
            _doc(
                vista_previa=vista,
                enlaces_externos=("https://ejemplo.org/x",),
                incrustados=("https://www.youtube-nocookie.com/embed/a\x1bbc",),
                recursos=("img/fo\x1bto.png",),
            ),
        ),
        secciones_nuevas=("Fracciones",),
        visible=None,
    )
    assert terminal.PresenciaTerminal().confirmar_real(resumen) is True
    salida = capsys.readouterr().out
    assert "curso REAL «Matemáticas 2ºB» (id 5678)" in salida
    assert "Tarea «Problemas» → sección «Fracciones»" in salida
    assert "fichero t.md, verificado en pruebas" in salida
    assert f"vista previa: {vista.resolve().as_uri()}" in salida
    assert "enlace externo: https://ejemplo.org/x" in salida
    assert "incrusta: https://www.youtube-nocookie.com/embed/abc" in salida
    assert "se sube el fichero img/foto.png" in salida
    assert "\x1b" not in salida
    assert "Se creará la sección «Fracciones» (oculta)." in salida
    assert "conserva su visibilidad" in salida
    assert vistos == [("real", 5678, "Matemáticas 2ºB")]


def test_confirmar_real_muestra_el_tipo_y_el_paquete_h5p(monkeypatch, capsys):
    monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: True)
    generado = _doc(
        tipo="h5p",
        nombre="Repaso H5P",
        h5p="Rellenar huecos",
    )
    paquete = _doc(
        tipo="h5p",
        nombre="Actividad con paquete",
        h5p_libreria="H5P.Blanks 1.14",
        h5p_descartadas=("H5P.Blanks-1.14", "FontAwesome-4.5"),
        enlaces_externos=("https://ejemplo.org/apoyo",),
    )
    resumen = sesion.ResumenPublicacion(
        curso=5678,
        nombre_curso="Matemáticas 2ºB",
        documentos=(generado, paquete),
        secciones_nuevas=(),
        visible=None,
    )
    assert terminal.PresenciaTerminal().confirmar_real(resumen) is True
    salida = capsys.readouterr().out
    assert "Contenido interactivo (H5P) «Repaso H5P»" in salida
    assert "actividad H5P: Rellenar huecos" in salida
    assert "paquete H5P: H5P.Blanks 1.14" in salida
    assert "no se sube la librería H5P.Blanks-1.14" in salida
    assert "enlace externo: https://ejemplo.org/apoyo" in salida


def test_pedir_password_ensena_el_servidor(monkeypatch, capsys):
    monkeypatch.setattr(terminal.getpass, "getpass", lambda _prompt="": "secreta")
    presencia = terminal.PresenciaTerminal()
    assert presencia.pedir_password("aula.ejemplo.org", "profe") == "secreta"
    assert "contraseña del aula de aula.ejemplo.org (usuario: profe)" in capsys.readouterr().out


def test_confirmar_cursos_avisa_del_curso_ajeno(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "s")
    cursos = [
        sesion.CursoSesion("pruebas", 1234, "Pruebas de Mates", False),
        sesion.CursoSesion("real", 9999, None, True),
    ]
    assert terminal.PresenciaTerminal().confirmar_cursos(cursos) is True
    salida = capsys.readouterr().out
    assert "«Pruebas de Mates» (id 1234)" in salida
    assert "id 9999 — no aparece entre tus cursos" in salida
    assert "cada publicación en real se confirmará aquí" in salida
    assert "Sin curso de pruebas" not in salida


def test_confirmar_cursos_avisa_si_no_hay_pruebas(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "s")
    cursos = [sesion.CursoSesion("real", 5678, "Matemáticas", False)]
    assert terminal.PresenciaTerminal().confirmar_cursos(cursos) is True
    salida = capsys.readouterr().out
    assert (
        "Sin curso de pruebas: no habrá verificación previa y en real solo se publicará oculto"
        in salida
    )


def test_confirmar_sin_pruebas_pregunta(monkeypatch, capsys):
    responder(monkeypatch, ["s"])
    presencia = terminal.PresenciaTerminal()
    assert presencia.confirmar_sin_pruebas() is True
    salida = capsys.readouterr().out
    assert "sin curso de pruebas" in salida.lower()
    assert "verificación previa" in salida
    responder(monkeypatch, [""])
    assert presencia.confirmar_sin_pruebas() is False


def test_ofrecer_ampliacion_usa_la_pregunta_con_plazo(monkeypatch):
    preguntas: list = []
    monkeypatch.setattr(
        terminal,
        "preguntar_con_limite",
        lambda pregunta, segundos: preguntas.append((pregunta, segundos)) or True,
    )
    assert terminal.PresenciaTerminal().ofrecer_ampliacion(30, 300) is True
    assert preguntas == [
        ("Se ha acabado el tiempo de la sesión. ¿Ampliar 30 minutos más? [s/N] ", 300)
    ]


def test_cierre_porque_tiza_cambio(capsys):
    terminal.PresenciaTerminal().informar(
        sesion.Aviso("SESION_CERRADA", {"motivo": "desactualizada"})
    )
    assert "tiza ha cambiado mientras la sesión estaba abierta" in capsys.readouterr().out


class TestCambiosDeFecha:
    def doc(self, **cambios):
        return sesion.DocumentoResumen("t.md", "tarea", "Problemas", 3, None, **cambios)

    def test_una_linea_por_fecha_segun_su_estado(self):
        cambios = (
            sesion.CambioFecha("apertura", (2026, 10, 1, 0, 0), (2026, 10, 1, 0, 0), "igual"),
            sesion.CambioFecha(
                "entrega",
                (2026, 10, 10, 23, 59),
                (2026, 10, 12, 23, 59),
                "cambia",
                ("FECHA_FESTIVA",),
            ),
            sesion.CambioFecha("límite", None, (2026, 10, 15, 23, 59), "nueva"),
        )
        assert terminal.describir_cambios(self.doc(cambios=cambios)) == [
            "apertura 01/10/2026 00:00 (sin cambios)",
            "entrega antes 10/10/2026 23:59 → ahora 12/10/2026 23:59 — festivo",
            "límite 15/10/2026 23:59 (la actividad es nueva)",
        ]

    def test_si_no_se_pudo_leer_el_aula_se_dice(self):
        cambio = sesion.CambioFecha("entrega", None, (2026, 10, 12, 23, 59), "desconocida")
        assert terminal.describir_cambios(self.doc(cambios=(cambio,))) == [
            "entrega: no se pudieron leer las fechas actuales del aula; "
            "se publicaría 12/10/2026 23:59"
        ]

    def test_sin_cambios_calculados_no_hay_lineas(self):
        assert terminal.describir_cambios(self.doc()) == []

    def test_con_cambios_la_descripcion_no_repite_las_fechas(self):
        from tiza.contenido import Fechas

        fechas = Fechas(
            apertura=datetime(2026, 10, 1, 0, 0),
            entrega=datetime(2026, 10, 12, 23, 59),
            limite=None,
        )
        sin_cambios = sesion.DocumentoResumen("t.md", "tarea", "P", 3, fechas)
        con_cambios = sesion.DocumentoResumen("t.md", "tarea", "P", 3, fechas, cambios=())
        assert "entrega 12/10/2026 23:59" in terminal.describir_documento(sin_cambios)
        assert "entrega" not in terminal.describir_documento(con_cambios)

    def test_solo_fechas_no_lista_el_contenido_y_avisa_de_las_excepciones(
        self, monkeypatch, capsys
    ):
        monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: False)
        cambio = sesion.CambioFecha(
            "entrega", (2026, 10, 10, 23, 59), (2026, 10, 12, 23, 59), "cambia"
        )
        doc = self.doc(
            enlaces_externos=("https://ejemplo.org/x",),
            recursos=("img/foto.png",),
            cambios=(cambio,),
        )
        resumen = sesion.ResumenPublicacion(5678, None, (doc,), (), None, solo_fechas=True)
        terminal.PresenciaTerminal().confirmar_real(resumen)
        salida = capsys.readouterr().out
        assert "cambiar solo las fechas" in salida
        assert "https://ejemplo.org/x" not in salida and "img/foto.png" not in salida
        assert "excepciones de fecha de alumnos" in salida
        assert "Solo cambian las fechas" in salida
        assert "Se publicará" not in salida

    @pytest.mark.parametrize(
        ("estado", "recuerda"),
        [("cambia", True), ("desconocida", True), ("igual", False), ("nueva", False)],
    )
    def test_las_excepciones_se_recuerdan_si_la_fecha_cambia_o_no_se_sabe(
        self, monkeypatch, capsys, estado, recuerda
    ):
        monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: False)
        cambio = sesion.CambioFecha(
            "entrega", (2026, 10, 10, 23, 59), (2026, 10, 12, 23, 59), estado
        )
        resumen = sesion.ResumenPublicacion(
            5678, None, (self.doc(cambios=(cambio,)),), (), None, solo_fechas=True
        )
        assert terminal.cambian_fechas(resumen) is recuerda
        terminal.PresenciaTerminal().confirmar_real(resumen)
        assert ("excepciones de fecha de alumnos" in capsys.readouterr().out) is recuerda

    def test_el_recordatorio_de_calificacion_que_se_quita_se_enseña(self):
        cambio = sesion.CambioFecha(sesion.CAMPO_RECORDATORIO, (2026, 10, 20, 0, 0), None, "cambia")
        assert terminal.describir_cambios(self.doc(cambios=(cambio,))) == [
            "recordatorio de calificación antes 20/10/2026 00:00 → ahora sin fecha"
        ]

    def test_el_recordatorio_por_si_solo_no_obliga_a_recordar_las_excepciones(self):
        recordatorio = sesion.CambioFecha(
            sesion.CAMPO_RECORDATORIO, (2026, 10, 20, 0, 0), None, "cambia"
        )
        entrega = sesion.CambioFecha(
            "entrega", (2026, 10, 10, 23, 59), (2026, 10, 12, 23, 59), "cambia"
        )
        solo = sesion.ResumenPublicacion(
            5678, None, (self.doc(cambios=(recordatorio,)),), (), None, solo_fechas=True
        )
        con_entrega = sesion.ResumenPublicacion(
            5678, None, (self.doc(cambios=(recordatorio, entrega)),), (), None, solo_fechas=True
        )
        assert terminal.cambian_fechas(solo) is False
        assert terminal.cambian_fechas(con_entrega) is True

    def test_el_aviso_de_calendario_se_explica_en_una_linea(self, monkeypatch, capsys):
        monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: False)
        resumen = sesion.ResumenPublicacion(
            5678, None, (self.doc(),), (), False, aviso_calendario="CALENDARIO_INVALIDO"
        )
        terminal.PresenciaTerminal().confirmar_real(resumen)
        salida = capsys.readouterr().out
        assert "AVISO: calendario.toml no se puede usar." in salida


def test_con_varios_cursos_cada_confirmacion_lleva_su_cabecera(monkeypatch, capsys):
    monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: True)
    resumen = sesion.ResumenPublicacion(
        curso=102,
        nombre_curso="1º B",
        documentos=(),
        secciones_nuevas=(),
        visible=None,
        posicion=2,
        total=3,
    )
    assert terminal.PresenciaTerminal().confirmar_real(resumen) is True
    assert "Curso 2 de 3: «1º B» (id 102)" in capsys.readouterr().out
    corto = sesion.ResumenSinPruebas(
        curso=103, nombre_curso=None, documentos=(), secciones_nuevas=(), posicion=3, total=3
    )
    assert terminal.PresenciaTerminal().confirmar_real_sin_pruebas(corto) is True
    assert "Curso 3 de 3: id 103" in capsys.readouterr().out


def test_con_un_solo_curso_no_hay_cabecera(monkeypatch, capsys):
    monkeypatch.setattr(terminal, "confirmar_destino", lambda *a, **k: True)
    resumen = sesion.ResumenPublicacion(
        curso=5678, nombre_curso=None, documentos=(), secciones_nuevas=(), visible=None
    )
    terminal.PresenciaTerminal().confirmar_real(resumen)
    assert "Curso 1 de" not in capsys.readouterr().out
