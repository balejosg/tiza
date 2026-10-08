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


def eof(monkeypatch):
    def _input(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _input)


def test_confirmar_eof_devuelve_false(monkeypatch):
    eof(monkeypatch)
    assert terminal.confirmar("¿Seguir?") is False


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
