"""Tests de la capa de Linux del panel (``tiza.panel.linux``) sin Qt ni pywebview."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from tiza.panel import linux


class Evento:
    def __init__(self) -> None:
        self.funciones: list = []

    def __iadd__(self, funcion):
        self.funciones.append(funcion)
        return self

    def lanzar(self) -> None:
        for funcion in self.funciones:
            funcion()


# --- Wayland o X11 -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entorno", "esperado"),
    [
        ({"WAYLAND_DISPLAY": "wayland-0"}, True),
        ({"WAYLAND_DISPLAY": "wayland-0", "QT_QPA_PLATFORM": "xcb"}, False),
        ({"DISPLAY": ":0"}, False),
        ({}, False),
    ],
)
def test_en_wayland(entorno, esperado):
    assert linux.en_wayland(entorno) is esperado


# --- libxcb-cursor -------------------------------------------------------------------------


def _sin_llamar(*_a, **_k):
    raise AssertionError("no debía llamarse")


def test_en_wayland_no_hace_falta_la_libreria(tmp_path):
    falta = linux.preparar_qt(
        {"WAYLAND_DISPLAY": "wayland-0"},
        carpeta=tmp_path,
        buscar_libreria=_sin_llamar,
        bajar=_sin_llamar,
        cargar=_sin_llamar,
    )
    assert falta is None


def test_si_el_sistema_la_tiene_no_se_carga_nada(tmp_path):
    falta = linux.preparar_qt(
        {"DISPLAY": ":0"},
        carpeta=tmp_path,
        buscar_libreria=lambda _n: "libxcb-cursor.so.0",
        bajar=_sin_llamar,
        cargar=_sin_llamar,
    )
    assert falta is None


def test_si_falta_se_usa_la_copia_propia(tmp_path):
    propia = tmp_path / linux.LIBRERIA_CURSOR
    propia.write_bytes(b"ELF")
    cargadas: list[str] = []
    falta = linux.preparar_qt(
        {"DISPLAY": ":0"},
        carpeta=tmp_path,
        buscar_libreria=lambda _n: None,
        bajar=_sin_llamar,
        cargar=cargadas.append,
    )
    assert falta is None
    assert cargadas == [str(propia)]


def test_si_falta_y_no_hay_copia_se_baja_y_se_carga(tmp_path):
    def bajar(destino: Path) -> Path:
        (destino / linux.LIBRERIA_CURSOR).write_bytes(b"ELF")
        return destino / linux.LIBRERIA_CURSOR

    cargadas: list[str] = []
    falta = linux.preparar_qt(
        {"DISPLAY": ":0"},
        carpeta=tmp_path,
        buscar_libreria=lambda _n: None,
        bajar=bajar,
        cargar=cargadas.append,
    )
    assert falta is None
    assert cargadas == [str(tmp_path / linux.LIBRERIA_CURSOR)]


def test_si_no_se_puede_bajar_se_dice_que_hacer(tmp_path):
    falta = linux.preparar_qt(
        {"DISPLAY": ":0"},
        carpeta=tmp_path,
        buscar_libreria=lambda _n: None,
        bajar=lambda _d: None,
        cargar=_sin_llamar,
    )
    assert falta is not None
    assert "libxcb-cursor0" in falta and "tiza empezar" in falta


def test_si_la_copia_no_carga_se_dice_que_hacer(tmp_path):
    (tmp_path / linux.LIBRERIA_CURSOR).write_bytes(b"roto")

    def cargar(_ruta: str) -> None:
        raise OSError("no es un ELF")

    falta = linux.preparar_qt(
        {"DISPLAY": ":0"}, carpeta=tmp_path, buscar_libreria=lambda _n: None, cargar=cargar
    )
    assert falta is not None and "libxcb-cursor0" in falta


def test_la_libreria_propia_vive_en_la_configuracion_de_tiza(tmp_path, monkeypatch):
    # El agente no puede escribir ahí (denyWrite): lo que se carga fuera del sandbox es de tiza.
    monkeypatch.setattr("tiza.config.directorio_global", lambda: tmp_path / "tiza")
    assert linux.carpeta_librerias() == tmp_path / "tiza" / "lib"


def test_bajar_sin_apt_no_hace_nada(tmp_path):
    assert linux.bajar_libreria(tmp_path, ejecutar=_sin_llamar, buscar=lambda _n: None) is None


def test_bajar_con_apt_extrae_la_libreria(tmp_path):
    ordenes: list[list[str]] = []

    def ejecutar(orden, **opciones):
        ordenes.append(orden)
        trabajo = Path(opciones["cwd"])
        if orden[:2] == ["apt-get", "download"]:
            (trabajo / "libxcb-cursor0_0.1.4_amd64.deb").write_bytes(b"deb")
        else:
            destino = Path(orden[3]) / "usr/lib/x86_64-linux-gnu"
            destino.mkdir(parents=True)
            (destino / "libxcb-cursor.so.0.0.0").write_bytes(b"ELF")
            (destino / linux.LIBRERIA_CURSOR).symlink_to("libxcb-cursor.so.0.0.0")
        return subprocess.CompletedProcess(orden, 0)

    final = linux.bajar_libreria(tmp_path / "lib", ejecutar=ejecutar, buscar=lambda n: n)
    assert final == tmp_path / "lib" / linux.LIBRERIA_CURSOR
    assert final.read_bytes() == b"ELF" and not final.is_symlink()
    assert ordenes[0] == ["apt-get", "download", linux.PAQUETE_CURSOR]
    assert ordenes[1][:2] == ["dpkg-deb", "-x"]


def test_bajar_si_apt_falla_no_deja_nada(tmp_path):
    def ejecutar(orden, **_opciones):
        return subprocess.CompletedProcess(orden, 100)

    destino = tmp_path / "lib"
    assert linux.bajar_libreria(destino, ejecutar=ejecutar, buscar=lambda n: n) is None
    assert not destino.exists()


def test_bajar_si_apt_tarda_demasiado_no_rompe(tmp_path):
    def ejecutar(orden, **_opciones):
        raise subprocess.TimeoutExpired(orden, 1)

    assert linux.bajar_libreria(tmp_path, ejecutar=ejecutar, buscar=lambda n: n) is None


# --- recogida de basura en el hilo de la interfaz ------------------------------------------


def test_el_latido_emite_hasta_que_se_para():
    emitidos = threading.Semaphore(0)
    latido = linux.Latido(emitidos.release, cada=0.01)
    latido.empezar()
    assert emitidos.acquire(timeout=5)
    assert emitidos.acquire(timeout=5)
    latido.parar()
    latido._hilo.join(5)
    assert not latido._hilo.is_alive()


def test_el_latido_termina_si_la_senal_ya_no_existe():
    def emitir() -> None:
        raise RuntimeError("objeto de Qt borrado")

    latido = linux.Latido(emitir, cada=0.01)
    latido.empezar()
    latido._hilo.join(5)
    assert not latido._hilo.is_alive()


# --- operaciones de ventana ----------------------------------------------------------------


class VentanaPywebview:
    def __init__(self) -> None:
        self.events = SimpleNamespace(minimized=Evento(), restored=Evento())
        self.cambios: list = []
        self._on_top = False

    @property
    def on_top(self) -> bool:
        return self._on_top

    @on_top.setter
    def on_top(self, valor: bool) -> None:
        self._on_top = valor
        self.cambios.append(("on_top", valor))

    def restore(self) -> None:
        self.cambios.append("restore")

    def show(self) -> None:
        self.cambios.append("show")


def test_la_ventana_qt_sabe_si_esta_minimizada_por_los_eventos():
    ventana = VentanaPywebview()
    qt = linux.VentanaQt(ventana)
    assert qt.minimizada() is False  # sin eventos (Wayland), no
    ventana.events.minimized.lanzar()
    assert qt.minimizada() is True
    ventana.events.restored.lanzar()
    assert qt.minimizada() is False
    ventana.events.minimized.lanzar()
    qt.restaurar()
    assert qt.minimizada() is False


def test_la_ventana_qt_usa_la_api_de_pywebview():
    ventana = VentanaPywebview()
    alertas: list[int] = []
    qt = linux.VentanaQt(ventana, alertar=lambda: alertas.append(1))
    qt.poner_encima(True)
    qt.restaurar()
    qt.mostrar()
    qt.poner_encima(False)
    qt.parpadear()
    assert ventana.cambios == [("on_top", True), "restore", "show", ("on_top", False)]
    assert alertas == [1]


# --- avisos sin consola --------------------------------------------------------------------


def test_avisar_con_qt_no_busca_otros_programas():
    anotado: list[str] = []
    linux.avisar(
        "hola", con_qt=True, qt=lambda _t: True, ejecutar=_sin_llamar, anotar=anotado.append
    )
    assert anotado == ["hola"]


def test_avisar_sin_qt_usa_zenity_si_esta():
    ordenes: list[list[str]] = []
    linux.avisar(
        "falta algo",
        con_qt=False,
        qt=_sin_llamar,
        buscar=lambda n: f"/usr/bin/{n}",
        ejecutar=lambda orden, **_k: ordenes.append(orden),
        anotar=lambda _t: None,
    )
    assert len(ordenes) == 1
    assert ordenes[0][0] == "/usr/bin/zenity"
    assert "--no-markup" in ordenes[0] and "--text=falta algo" in ordenes[0]


def test_avisar_si_qt_falla_prueba_kdialog():
    ordenes: list[list[str]] = []
    linux.avisar(
        "falta algo",
        con_qt=True,
        qt=lambda _t: False,
        buscar=lambda n: f"/usr/bin/{n}" if n == "kdialog" else None,
        ejecutar=lambda orden, **_k: ordenes.append(orden),
        anotar=lambda _t: None,
    )
    assert ordenes == [["/usr/bin/kdialog", "--title", "tiza", "--error", "falta algo"]]


def test_avisar_sin_nada_queda_en_el_log():
    anotado: list[str] = []
    linux.avisar(
        "falta algo",
        con_qt=False,
        buscar=lambda _n: None,
        ejecutar=_sin_llamar,
        anotar=anotado.append,
    )
    assert anotado == ["falta algo"]


def test_el_log_del_panel_esta_en_la_configuracion_de_tiza(tmp_path, monkeypatch):
    monkeypatch.setattr("tiza.config.directorio_global", lambda: tmp_path / "tiza")
    linux._anotar("una línea")
    assert (tmp_path / "tiza" / "panel.log").read_text(encoding="utf-8") == "una línea\n"


def test_el_cuadro_de_qt_va_en_un_proceso_hijo():
    ordenes: list[list[str]] = []

    def ejecutar(orden, **_k):
        ordenes.append(orden)
        return subprocess.CompletedProcess(orden, 0)

    assert linux._con_qt("hola", ejecutar) is True
    assert ordenes[0][-1] == "hola" and "QMessageBox" in ordenes[0][-2]


def test_si_qt_aborta_el_aviso_sigue_por_otro_camino():
    def aborta(orden, **_k):
        return subprocess.CompletedProcess(orden, 134)

    assert linux._con_qt("hola", aborta) is False
