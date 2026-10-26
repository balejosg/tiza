"""Tests del recorrido del panel (``tiza.panel.flujo``): sin ventana, sin pywebview, sin red."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from dobles import PresenciaFalsa
from tiza import __version__, actualizacion, arranque, config, informe, publicacion
from tiza.aislamiento import Comprobacion
from tiza.panel import flujo, recientes
from tiza.panel.estado import RETARDO_RESPUESTA, Panel, PresenciaPanel


class Reloj:
    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora


@pytest.fixture(autouse=True)
def global_aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "global")


@pytest.fixture
def asignatura(tmp_path):
    carpeta = tmp_path / "centro" / "mates"
    carpeta.mkdir(parents=True)
    return carpeta


class Escenario:
    """El hilo del flujo con un panel de reloj falso; el test hace de docente."""

    def __init__(
        self, *, preparar=None, abrir_sesion=None, revisar=None, presencia=None, abrir_login=None
    ) -> None:
        self.reloj = Reloj()
        self.panel = Panel(reloj=self.reloj, ahora=lambda: datetime(2030, 1, 1, 10, 30))
        self.presencia = presencia or PresenciaPanel(
            self.panel, reloj=self.reloj, abrir_login=abrir_login
        )
        self.cerrar = threading.Event()
        self.llamadas: list[tuple] = []
        self.resultado: dict = {}
        self.preparar = preparar or self._preparar
        self.abrir_sesion = abrir_sesion or self._abrir_sesion
        self.revisar = revisar or (lambda *_: [])
        self.hilo = threading.Thread(target=self._correr, daemon=True)

    def _preparar(self, carpeta, presencia, **opciones):
        self.llamadas.append(("preparar", carpeta, presencia, opciones))
        return arranque.Resultado(arranque.Estado.SEGUIR)

    def _abrir_sesion(self, carpeta, presencia, **opciones):
        self.llamadas.append(("abrir_sesion", carpeta, presencia, opciones))
        return 0

    def _correr(self) -> None:
        try:
            self.resultado["codigo"] = flujo.ejecutar(
                self.panel,
                self.presencia,
                home=Path("/casa"),
                sistema="Windows",
                cerrar=self.cerrar,
                abrir_sesion=self.abrir_sesion,
                preparar=self.preparar,
                revisar=self.revisar,
                minutos=45,
                version_nueva=lambda: None,
                instalar=lambda _version: False,
                pausa=0,
            )
        except BaseException as exc:  # pragma: no cover - se ve en el test
            self.resultado["error"] = exc

    def empezar(self) -> Escenario:
        self.hilo.start()
        return self

    def pantalla_de_carpeta(self) -> dict:
        limite = time.monotonic() + 5
        while time.monotonic() < limite:
            actual = self.panel.estado()["pantalla"]
            if actual["tipo"] == "carpeta":
                self.reloj.ahora += RETARDO_RESPUESTA + 0.1
                return actual
            time.sleep(0.01)
        raise AssertionError("no llegó la pantalla de carpeta")

    def elegir_con_dialogo(self, carpeta: Path) -> None:
        p = self.pantalla_de_carpeta()
        assert self.panel.pedir_dialogo(p["numero"])
        assert self.panel.atender_dialogo(lambda: str(carpeta))

    def terminar(self) -> int:
        self.hilo.join(5)
        assert not self.hilo.is_alive(), "el flujo sigue bloqueado"
        assert "error" not in self.resultado, self.resultado.get("error")
        return self.resultado["codigo"]

    def final(self) -> dict:
        return self.panel.estado()["pantalla"]


def test_recorrido_completo_con_el_dialogo(asignatura):
    e = Escenario().empezar()
    e.elegir_con_dialogo(asignatura)
    assert e.terminar() == 0
    (_, carpeta_p, presencia_p, opciones_p), (_, carpeta_s, presencia_s, opciones_s) = e.llamadas
    assert carpeta_p == carpeta_s == asignatura
    assert presencia_p is presencia_s is e.presencia
    assert opciones_p["home"] == Path("/casa") and opciones_p["sistema"] == "Windows"
    assert opciones_p["exigir_aislamiento"] is True
    assert opciones_p["version_nueva"]() is None  # lo que pasó el flujo (aquí, sin versión nueva)
    assert opciones_p["instalar"]("9.9.9") is False
    assert opciones_s == {"minutos": 45, "preparar": True, "cerrar": e.cerrar}
    assert recientes.leer() == [asignatura]
    est = e.panel.estado()
    assert est["carpeta"] == "centro / mates"
    assert est["sesion_abierta"] is False
    assert e.final()["titulo"] == "Sesión cerrada"


def test_la_carpeta_se_puede_elegir_de_las_recientes(asignatura, tmp_path):
    otra = tmp_path / "centro" / "fisica"
    otra.mkdir()
    recientes.anotar(asignatura)
    recientes.anotar(otra)  # la última usada sale primera
    e = Escenario().empezar()
    p = e.pantalla_de_carpeta()
    assert [o["texto"] for o in p["opciones"]] == ["centro / fisica", "centro / mates"]
    assert e.panel.responder(p["numero"], ("reciente", 1))
    assert e.terminar() == 0
    assert e.llamadas[0][1] == asignatura
    assert recientes.leer() == [asignatura, otra]  # la elegida pasa a ser la primera


def test_si_se_cierra_el_panel_sin_carpeta_no_se_prepara_nada():
    e = Escenario().empezar()
    e.pantalla_de_carpeta()
    e.panel.cerrar()
    assert e.terminar() == 1
    assert e.llamadas == []
    assert e.final()["titulo"] == "Cancelado"


def test_un_fallo_del_arranque_enseña_las_lineas_del_error(asignatura):
    def preparar(*_args, **_kwargs):
        return arranque.Resultado(arranque.Estado.FALLO, "URL_INVALIDA", "la url no vale")

    e = Escenario(preparar=preparar).empezar()
    e.elegir_con_dialogo(asignatura)
    assert e.terminar() == 1
    assert e.llamadas == []  # no se abrió la sesión
    final = e.final()
    assert final["titulo"] == "No se pudo abrir la sesión"
    assert final["lineas"][0] == "ERROR [URL_INVALIDA]: la url no vale"
    registro = e.panel.estado()["registro"]
    assert registro[0] == {
        "texto": "ERROR [URL_INVALIDA]: la url no vale",
        "error": True,
        "hora": "10:30",
    }


def test_abortado_por_falta_de_aislamiento_dice_que_falta(asignatura):
    faltas = [
        Comprobacion("Claude Code", "falta", "sin sandbox"),
        Comprobacion("Codex", "ok", "bien"),
    ]
    vistas: list[tuple] = []

    def revisar(home, sistema, carpeta):
        vistas.append((home, sistema, carpeta))
        return faltas

    e = Escenario(
        preparar=lambda *_a, **_k: arranque.Resultado(arranque.Estado.ABORTADO), revisar=revisar
    ).empezar()
    e.elegir_con_dialogo(asignatura)
    assert e.terminar() == 1
    assert vistas == [(Path("/casa"), "Windows", asignatura)]
    final = e.final()
    assert final["titulo"] == "Falta aislar al agente"
    assert "solo abre la sesión con el agente aislado" in final["lineas"][0]
    assert final["lineas"][1:] == ("- Claude Code: sin sandbox",)


def test_abortado_porque_el_docente_dijo_que_no_es_cancelado(asignatura):
    e = Escenario(preparar=lambda *_a, **_k: arranque.Resultado(arranque.Estado.ABORTADO)).empezar()
    e.elegir_con_dialogo(asignatura)
    assert e.terminar() == 1
    assert e.final()["titulo"] == "Cancelado"
    assert e.llamadas == []


def test_abortado_con_la_revision_ilegible_es_cancelado(asignatura):
    def revisar(*_args):
        raise OSError("no se puede leer")

    e = Escenario(
        preparar=lambda *_a, **_k: arranque.Resultado(arranque.Estado.ABORTADO), revisar=revisar
    ).empezar()
    e.elegir_con_dialogo(asignatura)
    assert e.terminar() == 1
    assert e.final()["titulo"] == "Cancelado"


def test_actualizada_deja_el_reposo_y_pide_la_salida_para_que_siga_el_actualizador(asignatura):
    e = Escenario(
        preparar=lambda *_a, **_k: arranque.Resultado(arranque.Estado.ACTUALIZADA)
    ).empezar()
    e.elegir_con_dialogo(asignatura)
    assert e.terminar() == 0
    final = e.final()
    assert final["titulo"] == "Se está actualizando"
    assert "el panel se abrirá solo en un minuto o dos" in final["lineas"][0]
    assert e.panel.salida_pedida  # el hilo de la ventana la cierra y el proceso termina
    assert e.panel.cerrado


def test_el_flujo_pasa_al_arranque_la_version_y_el_instalador_recibidos(asignatura):
    def version():
        return "v9.0.0"

    def instalar(_v):
        return True

    e = Escenario()
    e.hilo = threading.Thread(
        target=lambda: e.resultado.update(
            codigo=flujo.ejecutar(
                e.panel,
                e.presencia,
                home=Path("/casa"),
                sistema="Windows",
                cerrar=e.cerrar,
                abrir_sesion=e.abrir_sesion,
                preparar=e.preparar,
                revisar=e.revisar,
                version_nueva=version,
                instalar=instalar,
            )
        ),
        daemon=True,
    )
    e.empezar()
    e.elegir_con_dialogo(asignatura)
    e.terminar()
    opciones = e.llamadas[0][3]
    assert opciones["version_nueva"] is version and opciones["instalar"] is instalar


def test_si_no_se_entra_en_el_aula_el_final_lo_dice_claro(asignatura):
    llamadas: list[str] = []

    def sin_entrar(url):
        llamadas.append(url)
        return None  # la ventana de entrada se cerró o pasó el tiempo

    holder: dict = {}

    def abrir_sesion(carpeta, presencia, **_k):
        assert presencia.acreditar("https://aula.example", "docente") is None
        presencia.informar(
            publicacion.Aviso.resultado(
                informe.crear("sesion", "abortado", [], [], ["ABORTADO"], None, None)
            )
        )
        presencia.informar(publicacion.Aviso.cancelada())
        holder["hecho"] = True
        return 1

    e = Escenario(abrir_login=sin_entrar, abrir_sesion=abrir_sesion).empezar()
    e.elegir_con_dialogo(asignatura)
    assert e.terminar() == 1
    assert llamadas == ["https://aula.example"] and holder["hecho"]
    final = e.final()
    assert final["titulo"] == "No se entró en el aula"
    assert final["lineas"] == (
        "La ventana de entrada se cerró o pasó el tiempo.",
        "Vuelve a abrir tiza para intentarlo.",
    )
    textos = " ".join(r["texto"] for r in e.panel.estado()["registro"])
    assert "Has respondido que no" not in textos


def test_un_fallo_de_la_sesion_con_la_entrada_hecha_sigue_siendo_la_sesion_no_abierta(asignatura):
    def abrir_sesion(carpeta, presencia, **_k):
        assert presencia.acreditar("https://aula.example", "docente") is not None
        return 1

    e = Escenario(abrir_login=lambda _url: object(), abrir_sesion=abrir_sesion).empezar()
    e.elegir_con_dialogo(asignatura)
    assert e.terminar() == 1
    assert e.final()["titulo"] == "La sesión no se abrió"


def test_instalar_con_actualizador_lanza_con_uv_y_la_version():
    lanzadas: list[tuple] = []

    def lanzar(uv, version):
        lanzadas.append((uv, version))
        return True

    assert flujo.instalar_con_actualizador("v9.0.0", lanzar=lanzar, buscar_uv=lambda _n: "/bin/uv")
    assert lanzadas == [("/bin/uv", "v9.0.0")]


def test_instalar_con_actualizador_sin_uv_no_lanza_nada():
    def lanzar(*_a):
        raise AssertionError("no debe lanzar")

    assert not flujo.instalar_con_actualizador("v9.0.0", lanzar=lanzar, buscar_uv=lambda _n: None)


def test_contar_actualizacion_si_se_actualizo():
    presencia = PresenciaFalsa()
    flujo.contar_actualizacion(presencia, {actualizacion.VARIABLE_RESULTADO: "ok:0.30.0"})
    assert presencia.codigos() == ["PANEL_ACTUALIZADO"]
    assert presencia.avisos[0].datos == {"version": "0.30.0"}


def test_contar_actualizacion_si_fallo_dice_la_version_y_el_log(tmp_path):
    presencia = PresenciaFalsa()
    flujo.contar_actualizacion(presencia, {actualizacion.VARIABLE_RESULTADO: "fallo"})
    assert presencia.codigos() == ["PANEL_NO_ACTUALIZADO"]
    datos = presencia.avisos[0].datos
    assert datos["actual"] == __version__
    assert datos["log"] == str(tmp_path / "global" / "actualizar.log")


@pytest.mark.parametrize("valor", [None, "", "ok:", "ok:main", "ok:1.2", "otra cosa", "OK:1.2.3"])
def test_contar_actualizacion_ignora_lo_que_no_es_del_actualizador(valor):
    presencia = PresenciaFalsa()
    entorno = {} if valor is None else {actualizacion.VARIABLE_RESULTADO: valor}
    flujo.contar_actualizacion(presencia, entorno)
    assert presencia.codigos() == []


def test_contar_actualizacion_con_el_entorno_real_borra_la_variable(monkeypatch):
    monkeypatch.setenv(actualizacion.VARIABLE_RESULTADO, "ok:0.30.0")
    presencia = PresenciaFalsa()
    flujo.contar_actualizacion(presencia)
    assert presencia.codigos() == ["PANEL_ACTUALIZADO"]
    assert actualizacion.VARIABLE_RESULTADO not in flujo.os.environ


def test_una_sesion_que_no_llega_a_abrirse_es_un_fallo(asignatura):
    e = Escenario(abrir_sesion=lambda *_a, **_k: 1).empezar()
    e.elegir_con_dialogo(asignatura)
    assert e.terminar() == 1
    assert e.final()["titulo"] == "La sesión no se abrió"


@pytest.mark.parametrize("donde", ["preparar", "abrir_sesion"])
def test_un_error_inesperado_no_cuelga_el_panel(asignatura, donde):
    def falla(*_args, **_kwargs):
        raise RuntimeError("detalle interno que no debe verse")

    presencia = PresenciaFalsa()
    e = Escenario(presencia=presencia, **{donde: falla}).empezar()
    e.elegir_con_dialogo(asignatura)
    assert e.terminar() == 1
    assert presencia.codigos() == ["ERROR_INTERNO"]
    assert presencia.avisos[0].datos == {"tipo": "RuntimeError"}
    final = e.final()
    assert final["titulo"] == "Algo ha fallado"
    assert "detalle interno" not in str(e.panel.estado())


def test_con_una_presencia_falsa_el_flujo_no_depende_del_panel(asignatura):
    presencia = PresenciaFalsa()
    e = Escenario(presencia=presencia).empezar()
    e.elegir_con_dialogo(asignatura)
    assert e.terminar() == 0
    assert e.llamadas[0][2] is presencia
