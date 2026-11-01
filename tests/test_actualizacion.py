"""Tests de ``tiza.actualizacion``: los guiones de Windows y su entorno, sin lanzar nada."""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tiza import actualizacion
from tiza.actualizacion import (
    ACCESOS_PS,
    GUION_PANEL,
    GUION_WINDOWS,
    ErrorActualizacion,
)

RAIZ = Path(__file__).resolve().parent.parent
WHEEL = f"{actualizacion.REPO_GIT}/releases/download/v0.30.0/tiza-0.30.0-py3-none-any.whl"
ZIP = f"{actualizacion.REPO_GIT}/archive/v0.30.0.zip"


def decodificar(orden: list[str]) -> str:
    return base64.b64decode(orden[-1]).decode("utf-16-le")


# --- los accesos y el instalador -------------------------------------------------------------


def test_install_ps1_lleva_el_mismo_bloque_de_accesos_que_la_actualizacion():
    instalador = (RAIZ / "install.ps1").read_text(encoding="utf-8")
    assert ACCESOS_PS in instalador


def test_install_ps1_crea_los_accesos_y_dice_como_abrir_tiza():
    instalador = (RAIZ / "install.ps1").read_text(encoding="utf-8")
    assert instalador.index("Crear-AccesosTiza $bin") > instalador.index("tiza instalar-skill")
    assert "menú Inicio" in instalador and "tiza empezar" in instalador
    assert "sin el panel" in instalador  # si no hay tiza-panel.exe, lo dice claro


def test_los_accesos_apuntan_al_exe_del_panel_en_el_inicio_y_el_escritorio():
    assert "tiza-panel.exe" in ACCESOS_PS
    assert "GetFolderPath('Programs')" in ACCESOS_PS
    assert "GetFolderPath('Desktop')" in ACCESOS_PS
    assert "WScript.Shell" in ACCESOS_PS
    assert "$acceso.TargetPath = $panel" in ACCESOS_PS
    assert "$acceso.WorkingDirectory = $env:USERPROFILE" in ACCESOS_PS
    assert "$acceso.IconLocation = $icono" in ACCESOS_PS
    assert "$herramientas = (uv tool dir) | Select-Object -First 1" in ACCESOS_PS
    assert (
        r"$candidato = Join-Path $herramientas "
        r"'tiza\Lib\site-packages\tiza\recursos\tiza.ico'" in ACCESOS_PS
    )
    assert "if (Test-Path -LiteralPath $candidato)" in ACCESOS_PS
    assert '$icono = "${panel},0"' in ACCESOS_PS  # una versión sin el icono no rompe el acceso
    assert "RunAs" not in ACCESOS_PS  # sin administrador


@pytest.mark.parametrize("texto", [ACCESOS_PS, GUION_WINDOWS, GUION_PANEL])
def test_ningun_guion_interpola_variable_con_dos_puntos_pegados(texto):
    # En PowerShell, "$var:" es un error de sintaxis ("${var}:"). Se admiten $env:NOMBRE
    # y los ámbitos conocidos; cualquier otra "$nombre:" dentro de una cadena es un fallo.
    for casamiento in re.finditer(r"\$([A-Za-z_][A-Za-z0-9_]*):", texto):
        assert casamiento.group(1) in {"env", "global", "script", "local"}, casamiento.group(0)


def test_el_instalador_no_tiene_variables_con_dos_puntos_pegados():
    instalador = (RAIZ / "install.ps1").read_text(encoding="utf-8")
    for casamiento in re.finditer(r"\$([A-Za-z_][A-Za-z0-9_]*):", instalador):
        assert casamiento.group(1) in {"env", "global", "script", "local"}, casamiento.group(0)


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="sin PowerShell para el parser")
@pytest.mark.parametrize("nombre", ["install.ps1", "GUION_WINDOWS", "GUION_PANEL"])
def test_la_sintaxis_de_powershell_es_valida(tmp_path, nombre):
    if nombre == "install.ps1":
        ruta = RAIZ / nombre
    else:
        ruta = tmp_path / "guion.ps1"
        ruta.write_text(
            GUION_WINDOWS if nombre == "GUION_WINDOWS" else GUION_PANEL, encoding="utf-8-sig"
        )
    comando = (
        "$e=$null;$t=$null;"
        "[void][System.Management.Automation.Language.Parser]::ParseFile($env:RUTA_A_ANALIZAR,[ref]$t,[ref]$e);"
        "if ($e.Count -gt 0) { $e | ForEach-Object { $_.Message }; exit 1 }"
    )
    resultado = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", comando],
        env={**os.environ, "RUTA_A_ANALIZAR": str(ruta)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr


# --- tiza actualizar (consola) -----------------------------------------------------------------


def test_el_guion_de_la_consola_espera_instala_reinstala_la_skill_y_crea_los_accesos():
    assert GUION_WINDOWS.startswith(ACCESOS_PS)
    assert "Wait-Process -Id ([int]$env:TIZA_ACT_PID)" in GUION_WINDOWS
    assert GUION_WINDOWS.index("Wait-Process") < GUION_WINDOWS.index("tool install --force")
    assert GUION_WINDOWS.index("instalar-skill") < GUION_WINDOWS.index("Crear-AccesosTiza $bin |")
    assert "Read-Host" in GUION_WINDOWS


def test_el_entorno_de_la_consola_lleva_los_datos_y_no_se_interpreta_nada():
    paquetes = actualizacion.paquetes("v0.30.0", True)
    entorno = actualizacion.entorno_consola(
        {"PATH": "x"}, pid=7, ref="v0.30.0", uv="C:/uv.exe", paquetes=paquetes, con_ventana=True
    )
    assert entorno["PATH"] == "x"
    assert entorno["TIZA_ACT_PID"] == "7"
    assert entorno["TIZA_ACT_UV"] == "C:/uv.exe"
    assert entorno["TIZA_ACT_REF"] == "v0.30.0"
    assert entorno["TIZA_ACT_PYTHON"] == actualizacion.PYTHON_INSTALADO
    assert entorno["TIZA_ACT_VENTANA"] == "1"
    assert entorno["TIZA_ACT_PAQUETES"].split("|") == paquetes


def test_lanzar_consola_usa_una_consola_nueva_y_un_guion_fijo(monkeypatch):
    lanzadas: list[tuple] = []
    monkeypatch.delenv(actualizacion.VARIABLE_RESULTADO, raising=False)
    actualizacion.lanzar_consola(
        "/bin/uv",
        "v0.30.0",
        ["tiza @ x"],
        False,
        lanzar=lambda orden, **k: lanzadas.append((orden, k)),
    )
    [(orden, opciones)] = lanzadas
    assert orden[:3] == ["powershell.exe", "-NoProfile", "-EncodedCommand"]
    assert "-WindowStyle" not in orden
    assert decodificar(orden) == GUION_WINDOWS
    assert opciones["creationflags"] == 0x10


# --- actualizar desde el panel ---------------------------------------------------------------


def test_el_guion_del_panel_espera_instala_con_ventana_y_vuelve_a_abrir_el_panel():
    g = GUION_PANEL
    assert g.startswith(ACCESOS_PS)
    assert g.index("Wait-Process -Id ([int]$env:TIZA_ACT_PID)") < g.index("tool install --force")
    assert "$env:TIZA_ACT_PAQUETES.Split('|')" in g
    assert "instalar-skill" in g
    assert g.index("instalar-skill") < g.index("Crear-AccesosTiza $bin |")
    assert "$env:TIZA_ACT_LOG" in g
    assert "Read-Host" not in g  # oculto: nadie podría pulsar Intro
    # Se vuelve a abrir en una ventana normal, con lo ocurrido en la variable de entorno.
    assert "Start-Process -FilePath $panel" in g
    assert "-WindowStyle Normal" in g
    assert "$env:TIZA_PANEL_ACTUALIZACION = 'ok:'" in g
    assert "$env:TIZA_PANEL_ACTUALIZACION = 'fallo'" in g
    assert g.index("TIZA_PANEL_ACTUALIZACION = 'fallo'") < g.index("Start-Process")
    assert "tiza-panel.exe" in g


def test_el_entorno_del_panel_solo_lleva_paquetes_con_ventana_y_el_log():
    log = Path("C:/Users/ana/AppData/Local/tiza/actualizar.log")
    entorno = actualizacion.entorno_panel(
        {"PATH": "x", actualizacion.VARIABLE_RESULTADO: "ok:1.1.1"},
        pid=42,
        ref="v0.30.0",
        uv="C:/uv.exe",
        log=log,
        anterior="0.29.2",
    )
    assert entorno["TIZA_ACT_PID"] == "42"
    assert entorno["TIZA_ACT_REF"] == "v0.30.0"
    assert entorno["TIZA_ACT_UV"] == "C:/uv.exe"
    assert entorno["TIZA_ACT_PYTHON"] == "3.13"
    assert entorno["TIZA_ACT_LOG"] == str(log)
    assert entorno["TIZA_ACT_ANTERIOR"] == "0.29.2"
    assert entorno["TIZA_ACT_PAQUETES"].split("|") == [
        f"tiza[ventana] @ {WHEEL}",
        f"tiza[ventana] @ {ZIP}",
    ]
    assert entorno["PATH"] == "x"
    # El resultado de una actualización anterior no pasa al actualizador.
    assert actualizacion.VARIABLE_RESULTADO not in entorno


@pytest.mark.parametrize(
    "ref", ["-x", "a b", "a;b", "$(id)", "../x", "a/../b", "a@b", "x" * 101, ""]
)
def test_una_ref_sin_validar_nunca_llega_al_entorno(ref):
    with pytest.raises(ErrorActualizacion) as exc:
        actualizacion.entorno_panel({}, pid=1, ref=ref, uv="uv", log=Path("l"), anterior="0.1.0")
    assert exc.value.codigo == "REF_NO_VALIDA"
    with pytest.raises(ErrorActualizacion):
        actualizacion.entorno_consola(
            {}, pid=1, ref=ref, uv="uv", paquetes=["x"], con_ventana=False
        )


def test_lanzar_el_panel_oculto_no_abre_ventana_y_deja_el_log_en_su_carpeta(tmp_path):
    log = tmp_path / "global" / "actualizar.log"
    lanzadas: list[tuple] = []
    ok = actualizacion.lanzar_panel_oculto(
        "/bin/uv",
        "v0.30.0",
        anterior="0.29.2",
        log=log,
        lanzar=lambda orden, **k: lanzadas.append((orden, k)),
        plataforma="win32",
    )
    assert ok is True
    [(orden, opciones)] = lanzadas
    assert orden[:5] == [
        "powershell.exe",
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-EncodedCommand",
    ]
    assert decodificar(orden) == GUION_PANEL
    assert opciones["creationflags"] == 0x08000000  # CREATE_NO_WINDOW
    assert opciones["env"]["TIZA_ACT_LOG"] == str(log)
    assert log.parent.is_dir()


def test_si_no_se_puede_lanzar_el_actualizador_se_dice_que_no(tmp_path):
    def sin_powershell(*_a, **_k):
        raise OSError("no")

    for plataforma in ("win32", "linux"):
        assert not actualizacion.lanzar_panel_oculto(
            "/bin/uv",
            "v0.30.0",
            log=tmp_path / "l.log",
            lanzar=sin_powershell,
            plataforma=plataforma,
        )


def test_lanzar_con_una_ref_invalida_no_lanza_nada(tmp_path):
    def no(*_a, **_k):
        raise AssertionError("no debe lanzar")

    for plataforma in ("win32", "linux"):
        assert not actualizacion.lanzar_panel_oculto(
            "/bin/uv", "v1; calc", log=tmp_path / "l.log", lanzar=no, plataforma=plataforma
        )


def test_la_ruta_del_log_esta_en_la_carpeta_global(monkeypatch, tmp_path):
    monkeypatch.setattr(actualizacion.config, "directorio_global", lambda: tmp_path)
    assert actualizacion.ruta_log() == tmp_path / "actualizar.log"


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("ok:0.30.0", (True, "0.30.0")),
        ("ok:10.2.33", (True, "10.2.33")),
        ("fallo", (False, "")),
        (" fallo ", (False, "")),
        ("ok:", None),
        ("ok:main", None),
        ("ok:1.2", None),
        ("ok:1.2.3; calc", None),
        ("fallo:1.2.3", None),
        ("", None),
    ],
)
def test_resultado_del_entorno(valor, esperado):
    assert (
        actualizacion.resultado_del_entorno({actualizacion.VARIABLE_RESULTADO: valor}) == esperado
    )


def test_sin_variable_no_hay_resultado():
    assert actualizacion.resultado_del_entorno({}) is None


# --- versiones y orígenes ----------------------------------------------------------------------


def test_numeros_compara_numericamente():
    assert actualizacion.numeros("v0.10.0") > actualizacion.numeros("v0.5.1")
    assert actualizacion.numeros("v0.20.3") == (0, 20, 3)


def test_origenes_validan_la_ref():
    with pytest.raises(ErrorActualizacion):
        actualizacion.origenes("a b")
    assert actualizacion.origenes("v0.30.0") == [WHEEL, ZIP]
    assert actualizacion.origenes("feature/x") == [f"git+{actualizacion.REPO_GIT}@feature/x"]


def test_paquetes_con_ventana_no_tiene_caida_a_sin_ella():
    assert actualizacion.paquetes_con_ventana("main") == [
        f"tiza[ventana] @ {actualizacion.REPO_GIT}/archive/main.zip"
    ]
    assert actualizacion.paquetes("main", True)[-1].startswith("tiza @ ")


# --- Linux: el acceso y el actualizador del panel ---------------------------------------------

POSIX = pytest.mark.skipif(shutil.which("sh") is None or os.name == "nt", reason="sin sh")


def test_install_sh_lleva_el_mismo_bloque_del_acceso_que_la_actualizacion():
    instalador = (RAIZ / "install.sh").read_text(encoding="utf-8")
    assert actualizacion.ACCESO_SH in instalador
    assert actualizacion.GUION_PANEL_LINUX.startswith(actualizacion.ACCESO_SH)


def test_install_sh_solo_crea_el_acceso_con_el_panel_y_la_ventana():
    instalador = (RAIZ / "install.sh").read_text(encoding="utf-8")
    assert 'if [ "${TIZA_PANEL:-0}" = 1 ] && [ "$(uname -s)" = "Linux" ]' in instalador
    creacion = 'if [ "$PANEL" = 1 ] && [ "$CON_VENTANA" = 1 ] && crear_acceso_tiza'
    assert creacion in instalador
    assert instalador.index(creacion) > instalador.index("tiza instalar-skill")
    assert "Busca «tiza» en tus aplicaciones" in instalador


def _ejecutable(ruta: Path, texto: str) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("#!/bin/sh\n" + texto, encoding="utf-8")
    ruta.chmod(0o755)
    return ruta


@POSIX
def test_el_acceso_de_linux_apunta_al_panel_con_el_icono(tmp_path):
    bin_ = tmp_path / "bin"
    _ejecutable(bin_ / "tiza-panel", "exit 0\n")
    herramientas = tmp_path / "herramientas"
    logo = herramientas / "tiza/lib/python3.13/site-packages/tiza/recursos/logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"PNG")
    _ejecutable(tmp_path / "uvbin" / "uv", f'echo "{herramientas}"\n')
    datos = tmp_path / "datos"
    entorno = {
        "PATH": f"{tmp_path / 'uvbin'}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XDG_DATA_HOME": str(datos),
    }
    guion = actualizacion.ACCESO_SH + f'crear_acceso_tiza "{bin_}"\n'
    resultado = subprocess.run(["sh", "-c", guion], env=entorno, capture_output=True, text=True)
    assert resultado.returncode == 0, resultado.stderr
    acceso = (datos / "applications" / "tiza.desktop").read_text(encoding="utf-8")
    assert f'Exec="{bin_ / "tiza-panel"}"' in acceso
    assert f"Icon={datos / 'icons' / 'tiza.png'}" in acceso
    assert "Terminal=false" in acceso and "StartupWMClass=tiza-panel" in acceso
    assert (datos / "icons" / "tiza.png").read_bytes() == b"PNG"


@POSIX
def test_sin_el_panel_no_se_crea_el_acceso(tmp_path):
    entorno = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path)}
    guion = actualizacion.ACCESO_SH + f'crear_acceso_tiza "{tmp_path / "nada"}"\n'
    resultado = subprocess.run(["sh", "-c", guion], env=entorno, capture_output=True, text=True)
    assert resultado.returncode == 1
    assert "solo desde la terminal" in resultado.stdout
    assert not (tmp_path / "applications").exists()


def _actualizar_en_linux(tmp_path: Path, *, uv_codigo: int) -> tuple[Path, Path]:
    """Ejecuta GUION_PANEL_LINUX con un uv, un tiza y un tiza-panel falsos; nada sale a la red."""
    bin_ = tmp_path / "bin"
    anotado = tmp_path / "reabierto.txt"
    _ejecutable(bin_ / "tiza", "exit 0\n")
    _ejecutable(
        bin_ / "tiza-panel",
        f'echo "$TIZA_PANEL_ACTUALIZACION ${{TIZA_ACT_REF:-sin}} $PWD" > "{anotado}"\n',
    )
    uv = _ejecutable(
        tmp_path / "uv",
        f'if [ "$2" = dir ]; then echo "{bin_}"; exit 0; fi\n'
        f'echo "$@" >> "{tmp_path / "ordenes.txt"}"\n'
        f"exit {uv_codigo}\n",
    )
    terminado = subprocess.Popen(["true"])
    terminado.wait()
    log = tmp_path / "actualizar.log"
    entorno = actualizacion.entorno_panel(
        {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path / "d")},
        pid=terminado.pid,
        ref="v0.38.0",
        uv=str(uv),
        log=log,
        anterior="0.37.0",
    )
    resultado = subprocess.run(
        actualizacion.orden_sh(actualizacion.GUION_PANEL_LINUX),
        env=entorno,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert resultado.returncode == 0, resultado.stderr
    return anotado, log


@POSIX
def test_el_actualizador_de_linux_instala_rehace_el_acceso_y_reabre_el_panel(tmp_path):
    anotado, log = _actualizar_en_linux(tmp_path, uv_codigo=0)
    assert anotado.read_text(encoding="utf-8").split() == ["ok:0.38.0", "sin", str(tmp_path)]
    ordenes = (tmp_path / "ordenes.txt").read_text(encoding="utf-8").splitlines()
    assert len(ordenes) == 1 and "tiza[ventana] @ " in ordenes[0]
    assert "--force --python 3.13" in ordenes[0]
    texto = log.read_text(encoding="utf-8")
    assert "Actualizando tiza de 0.37.0 a v0.38.0" in texto
    assert "uv termino con codigo 0" in texto and "Se vuelve a abrir el panel." in texto
    assert (tmp_path / "d" / "applications" / "tiza.desktop").is_file()


@POSIX
def test_si_uv_falla_el_actualizador_de_linux_reabre_contando_el_fallo(tmp_path):
    anotado, log = _actualizar_en_linux(tmp_path, uv_codigo=2)
    assert anotado.read_text(encoding="utf-8").split()[0] == "fallo"
    ordenes = (tmp_path / "ordenes.txt").read_text(encoding="utf-8").splitlines()
    assert len(ordenes) == 2  # el wheel y el .zip, los dos con la ventana
    assert "No se pudo instalar tiza." in log.read_text(encoding="utf-8")


def test_lanzar_el_actualizador_de_linux_lo_desacopla_del_panel(tmp_path):
    log = tmp_path / "global" / "actualizar.log"
    lanzadas: list[tuple] = []
    ok = actualizacion.lanzar_panel_oculto(
        "/bin/uv",
        "v0.38.0",
        anterior="0.37.0",
        log=log,
        lanzar=lambda orden, **k: lanzadas.append((orden, k)),
        plataforma="linux",
    )
    assert ok is True
    [(orden, opciones)] = lanzadas
    assert orden == actualizacion.orden_sh(actualizacion.GUION_PANEL_LINUX)
    assert opciones["start_new_session"] is True
    assert opciones["stdin"] == subprocess.DEVNULL
    assert opciones["env"]["TIZA_ACT_LOG"] == str(log)
    assert "creationflags" not in opciones
    assert log.parent.is_dir()
