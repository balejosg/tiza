"""Tests de la escritura atómica de JSON."""

from __future__ import annotations

import json
import os
import stat
import threading
from datetime import date

import pytest

from dobles import enlace_simbolico
from tiza import config, estado, ficheros, informe


def test_escribe_json_legible_sin_temporales(tmp_path):
    destino = tmp_path / "sub" / "datos.json"
    assert ficheros.escribir_json(destino, {"clave": "ñ"}) == destino
    assert json.loads(destino.read_text(encoding="utf-8")) == {"clave": "ñ"}
    assert destino.read_text(encoding="utf-8").endswith("\n")
    assert [ruta.name for ruta in destino.parent.iterdir()] == ["datos.json"]


def test_si_falla_conserva_el_anterior_y_borra_el_temporal(tmp_path, monkeypatch):
    destino = tmp_path / "datos.json"
    ficheros.escribir_json(destino, {"version": 1})

    def falla(*_args):
        raise PermissionError(13, "acceso denegado")

    monkeypatch.setattr(ficheros.os, "replace", falla)
    with pytest.raises(OSError):
        ficheros.escribir_json(destino, {"version": 2})
    assert json.loads(destino.read_text(encoding="utf-8")) == {"version": 1}
    assert [ruta.name for ruta in tmp_path.iterdir()] == ["datos.json"]


def test_dos_escrituras_no_comparten_temporal(tmp_path, monkeypatch):
    usados: list[str] = []
    real = ficheros.os.replace

    def anotar(origen, destino):
        usados.append(str(origen))
        return real(origen, destino)

    monkeypatch.setattr(ficheros.os, "replace", anotar)
    ficheros.escribir_json(tmp_path / "a.json", {})
    ficheros.escribir_json(tmp_path / "a.json", {})
    assert len(set(usados)) == 2


def _informe(curso: int) -> dict:
    return {
        "version": 1,
        "comando": "comprobar",
        "entorno": None,
        "curso": curso,
        "resultado": "ok",
        "pasos": [],
        "ficheros": [],
        "errores": [],
    }


@pytest.mark.parametrize("cual", ["informe", "estructura", "verificados", "config", "autoprueba"])
def test_un_fallo_al_escribir_conserva_el_fichero_anterior(tmp_path, monkeypatch, cual):
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path)
    escritores = {
        "informe": lambda n: informe.escribir(_informe(n), tmp_path),
        "estructura": lambda n: estado.escribir_estructura(
            tmp_path, {"pruebas": {"id": n, "secciones": []}}
        ),
        "verificados": lambda n: estado.guardar_verificado(tmp_path, "a" * 64, f"v{n}.md", n),
        "config": lambda n: config.guardar_global("https://aula.ejemplo.org/centro", f"profe{n}"),
        "autoprueba": lambda n: config.registrar_autoprueba(1234, date(2026, 10, 3), f"v{n}"),
    }
    ruta = escritores[cual](1)
    antes = ruta.read_text(encoding="utf-8")

    def falla(*_args):
        raise PermissionError(13, "acceso denegado")

    monkeypatch.setattr(ficheros.os, "replace", falla)
    with pytest.raises(OSError):
        escritores[cual](2)
    assert ruta.read_text(encoding="utf-8") == antes
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("cual", ["informe", "estructura", "verificados"])
def test_no_se_escribe_en_un_tiza_que_es_un_enlace(tmp_path, cual):
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    tiza = tmp_path / ".tiza"
    enlace_simbolico(tiza, fuera)
    escritores = {
        "informe": lambda: informe.escribir(_informe(1), tiza),
        "estructura": lambda: estado.escribir_estructura(
            tiza, {"pruebas": {"id": 1, "secciones": []}}
        ),
        "verificados": lambda: estado.guardar_verificado(tiza, "a" * 64, "v.md", 1),
    }
    with pytest.raises(ficheros.FicheroNoSeguro):
        escritores[cual]()
    assert list(fuera.iterdir()) == []


# --- escribir_texto: la escritura nunca sigue un enlace simbólico ---------------


def test_escribir_texto_escribe_sin_dejar_temporales(tmp_path):
    destino = tmp_path / "sub" / "vista.html"
    assert ficheros.escribir_texto(destino, "hola ñ\n") == destino
    assert destino.read_text(encoding="utf-8") == "hola ñ\n"
    assert [ruta.name for ruta in destino.parent.iterdir()] == ["vista.html"]


def test_escribir_texto_no_sigue_un_enlace_simbolico(tmp_path):
    ajeno = tmp_path / "ajeno.txt"
    ajeno.write_text("del docente", encoding="utf-8")
    destino = tmp_path / "vista.html"
    enlace_simbolico(destino, ajeno)
    ficheros.escribir_texto(destino, "vista")
    assert ajeno.read_text(encoding="utf-8") == "del docente"
    assert not destino.is_symlink()
    assert destino.read_text(encoding="utf-8") == "vista"


# --- leer_bytes_acotado: sin bloqueos, sin enlaces y con tope -------------------


def test_leer_bytes_acotado_lee_un_fichero_normal(tmp_path):
    ruta = tmp_path / "a.json"
    ruta.write_bytes(b'{"a": 1}')
    assert ficheros.leer_bytes_acotado(ruta, 100) == b'{"a": 1}'


def test_leer_bytes_acotado_admite_el_tamano_exacto(tmp_path):
    ruta = tmp_path / "a.bin"
    ruta.write_bytes(b"x" * 10)
    assert ficheros.leer_bytes_acotado(ruta, 10) == b"x" * 10


def test_leer_bytes_acotado_rechaza_lo_que_pasa_del_limite(tmp_path):
    ruta = tmp_path / "a.bin"
    ruta.write_bytes(b"x" * 11)
    with pytest.raises(ficheros.FicheroNoSeguro) as exc:
        ficheros.leer_bytes_acotado(ruta, 10)
    assert exc.value.motivo == "grande"


def test_leer_bytes_acotado_no_se_fia_del_tamano_declarado(tmp_path, monkeypatch):
    ruta = tmp_path / "a.bin"
    ruta.write_bytes(b"x" * 100)
    # Un fichero que crece mientras se lee: fstat dice 1 byte y hay 100.
    pequeno = os.stat_result((stat.S_IFREG | 0o644, 0, 0, 1, 0, 0, 1, 0, 0, 0))
    monkeypatch.setattr(ficheros.os, "fstat", lambda _descriptor: pequeno)
    with pytest.raises(ficheros.FicheroNoSeguro) as exc:
        ficheros.leer_bytes_acotado(ruta, 10)
    assert exc.value.motivo == "grande"


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="sin O_NOFOLLOW en este sistema")
def test_leer_bytes_acotado_no_sigue_enlaces_por_defecto(tmp_path):
    real = tmp_path / "real.json"
    real.write_bytes(b"{}")
    enlace = tmp_path / "enlace.json"
    enlace_simbolico(enlace, real)
    with pytest.raises(ficheros.FicheroNoSeguro) as exc:
        ficheros.leer_bytes_acotado(enlace, 100)
    assert exc.value.motivo == "enlace"


def test_leer_bytes_acotado_sigue_enlaces_si_se_pide(tmp_path):
    real = tmp_path / "real.json"
    real.write_bytes(b"{}")
    enlace = tmp_path / "enlace.json"
    enlace_simbolico(enlace, real)
    assert ficheros.leer_bytes_acotado(enlace, 100, enlaces=True) == b"{}"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="sin FIFO en este sistema")
def test_leer_bytes_acotado_no_se_cuelga_con_una_fifo(tmp_path):
    fifo = tmp_path / "a.peticion.json"
    os.mkfifo(fifo)
    resultado: dict = {}

    def leer() -> None:
        try:
            ficheros.leer_bytes_acotado(fifo, 100)
        except ficheros.FicheroNoSeguro as exc:
            resultado["motivo"] = exc.motivo

    hilo = threading.Thread(target=leer, daemon=True)
    hilo.start()
    hilo.join(5)
    assert not hilo.is_alive(), "se quedó esperando a que alguien escribiera en la FIFO"
    assert resultado == {"motivo": "no_regular"}


@pytest.mark.skipif(not os.path.exists("/dev/zero"), reason="sin /dev/zero en este sistema")
def test_leer_bytes_acotado_rechaza_un_dispositivo():
    with pytest.raises(ficheros.FicheroNoSeguro) as exc:
        ficheros.leer_bytes_acotado("/dev/zero", 10)
    assert exc.value.motivo == "no_regular"


def test_un_fichero_no_seguro_es_un_oserror():
    assert issubclass(ficheros.FicheroNoSeguro, OSError)


# --- asegurar_directorio: un directorio de trabajo no puede ser un enlace --------


def test_asegurar_directorio_crea_el_directorio(tmp_path):
    ruta = tmp_path / "a" / "b"
    assert ficheros.asegurar_directorio(ruta) == ruta
    assert ruta.is_dir()


def test_asegurar_directorio_acepta_uno_que_ya_existe(tmp_path):
    assert ficheros.asegurar_directorio(tmp_path) == tmp_path


def test_asegurar_directorio_se_niega_con_un_enlace(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    enlace = tmp_path / "enlace"
    enlace_simbolico(enlace, real)
    with pytest.raises(ficheros.FicheroNoSeguro) as exc:
        ficheros.asegurar_directorio(enlace)
    assert exc.value.motivo == "enlace"


def test_asegurar_directorio_se_niega_con_un_fichero(tmp_path):
    ruta = tmp_path / "x"
    ruta.write_text("hola", encoding="utf-8")
    with pytest.raises(ficheros.FicheroNoSeguro) as exc:
        ficheros.asegurar_directorio(ruta)
    assert exc.value.motivo == "no_directorio"
