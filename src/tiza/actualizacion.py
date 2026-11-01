"""Versiones e instalación de tiza: lo que comparten ``tiza actualizar``, ``tiza empezar`` y el panel.

Sin ``print`` ni consola: quien llama (``cli`` o el panel) decide qué le cuenta al docente.
Aquí viven la consulta de la última versión publicada, de dónde instala uv cada referencia
(``TIZA_REF`` incluida, siempre validada), los guiones de PowerShell de la actualización en
Windows y la construcción de su entorno, que son funciones puras. El lanzamiento real
(``subprocess.Popen``) puede inyectarse.

En Windows uv no puede borrar el ``python.exe`` ni el ``tiza.exe`` que están en marcha
(os error 5): la instalación sigue en otro proceso de PowerShell que espera a que el actual
termine. Con la consola (``tiza actualizar``) es una consola nueva; con el panel, un
PowerShell oculto que deja un log y vuelve a abrir ``tiza-panel`` contando cómo fue. En
Linux el panel hace lo mismo con un ``sh`` desacoplado (``GUION_PANEL_LINUX``): cambiar las
librerías de Qt debajo de un proceso vivo es buscarse un cuelgue.

Los datos llegan a los guiones por variables de entorno (``TIZA_ACT_*``): nada de lo que
varía se interpreta como código.
"""

from __future__ import annotations

import base64
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import requests

from . import __version__, config

__all__ = [
    "ACCESO_SH",
    "ACCESOS_PS",
    "GUION_PANEL",
    "GUION_PANEL_LINUX",
    "GUION_WINDOWS",
    "PYTHON_INSTALADO",
    "REPO_GIT",
    "VARIABLE_RESULTADO",
    "ErrorActualizacion",
    "entorno_consola",
    "entorno_panel",
    "lanzar_consola",
    "lanzar_panel_oculto",
    "numeros",
    "orden_powershell",
    "origenes",
    "paquetes",
    "paquetes_con_ventana",
    "quiere_ventana",
    "resultado_del_entorno",
    "ruta_log",
    "tiene_ventana",
    "ultima_etiqueta",
    "uv_instala",
    "validar_ref",
    "version_nueva",
]

REPO_GIT = "https://github.com/balejosg/tiza"
# Python fijo (como en los instaladores): uv usaría el más nuevo, y una versión recién salida
# aún no tiene wheels de todas las dependencias (pyyaml, por ejemplo) y habría que compilarlas.
PYTHON_INSTALADO = "3.13"
ULTIMA_RELEASE = f"{REPO_GIT}/releases/latest"
REF_VALIDA = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")  # etiqueta, rama o commit

# Cómo cuenta el actualizador del panel, al volver a abrirlo, qué pasó: ``ok:<versión>`` o ``fallo``.
VARIABLE_RESULTADO = "TIZA_PANEL_ACTUALIZACION"
_VERSION_SUELTA = re.compile(r"\A\d+\.\d+\.\d+\Z")

CREATE_NEW_CONSOLE = 0x10
CREATE_NO_WINDOW = 0x08000000


class ErrorActualizacion(Exception):
    """Un fallo de la actualización con un código estable (``REF_NO_VALIDA``…) y su detalle."""

    def __init__(self, codigo: str, detalle: str) -> None:
        super().__init__(f"{codigo}: {detalle}")
        self.codigo = codigo
        self.detalle = detalle


# --- versiones ---------------------------------------------------------------------------


def validar_ref(ref: str) -> None:
    """Lanza ``REF_NO_VALIDA`` si ``ref`` no es una etiqueta, rama o commit razonable."""
    if not REF_VALIDA.match(ref) or ".." in ref:
        raise ErrorActualizacion(
            "REF_NO_VALIDA",
            "TIZA_REF solo admite letras, números, «.», «_», «-» y «/», y debe empezar por una "
            "letra o un número",
        )


def numeros(etiqueta: str) -> tuple[int, ...]:
    """«v0.20.3» → (0, 20, 3); lo que no sean números cuenta como 0."""
    return tuple(int(n) if n.isdigit() else 0 for n in etiqueta.lstrip("v").split("."))


def ultima_etiqueta() -> str | None:
    """La versión publicada más reciente (vX.Y.Z), o None si no se puede saber.

    Sin git ni la API de GitHub (que limita las consultas por IP, y en un centro muchos
    docentes salen por la misma): la página de la última release redirige a su etiqueta.
    """
    try:
        respuesta = requests.head(ULTIMA_RELEASE, allow_redirects=False, timeout=10)
    except requests.RequestException:
        return None
    destino = respuesta.headers.get("Location", "")
    encontrada = re.search(r"/releases/tag/(v\d+\.\d+\.\d+)\Z", destino)
    return encontrada.group(1) if encontrada else None


def version_nueva() -> str | None:
    """La etiqueta publicada más alta si es posterior a esta tiza; None si no, o si no se sabe.

    No falla nunca: sin conexión (o sin uv) ``tiza empezar`` sigue como siempre.
    """
    if os.environ.get("TIZA_REF") or shutil.which("uv") is None:
        return None  # quien fija TIZA_REF elige la versión a mano
    ultima = ultima_etiqueta()
    if ultima is None:
        return None
    if numeros(ultima) <= numeros(f"v{__version__}"):
        return None
    return ultima


def tiene_ventana() -> bool:
    """¿Está instalado el extra ``ventana`` (pywebview) junto a esta tiza?"""
    return importlib.util.find_spec("webview") is not None


def quiere_ventana() -> bool:
    """Windows y macOS llevan la ventana de entrada; Linux, solo si ya la tenía.

    En Linux la ventana trae Qt (cientos de MB): se instala a propósito, con
    ``TIZA_VENTANA=1`` en el instalador, y la actualización la conserva.
    """
    return sys.platform in ("win32", "darwin") or tiene_ventana()


# --- de dónde se instala -----------------------------------------------------------------


def origenes(ref: str) -> list[str]:
    """De dónde instala uv ``ref``, en orden, sin git (como los instaladores).

    Una versión publicada (vX.Y.Z) se instala desde el wheel de su release, que no hay que
    construir; si aún no está subido, desde el .zip. Una rama o un commit, desde el .zip.
    Las referencias con «/» (ramas con barra, solo para desarrollo) no tienen .zip y
    necesitan git.
    """
    validar_ref(ref)
    if "/" in ref:
        return [f"git+{REPO_GIT}@{ref}"]
    zip_ = f"{REPO_GIT}/archive/{ref}.zip"
    if re.fullmatch(r"v\d+\.\d+\.\d+", ref):
        return [f"{REPO_GIT}/releases/download/{ref}/tiza-{ref[1:]}-py3-none-any.whl", zip_]
    return [zip_]


def paquetes(ref: str, con_ventana: bool) -> list[str]:
    """Lo que se pide a uv, en orden: de cada origen, con la ventana y, si no, sin ella."""
    lista: list[str] = []
    for origen in origenes(ref):
        if con_ventana:
            lista.append(f"tiza[ventana] @ {origen}")
        lista.append(f"tiza @ {origen}")
    return lista


def paquetes_con_ventana(ref: str) -> list[str]:
    """Solo con el extra ``ventana``: sin pywebview no hay panel, así que no hay caída a sin él."""
    return [f"tiza[ventana] @ {origen}" for origen in origenes(ref)]


def uv_instala(uv: str, paquete: str) -> bool:
    orden = [uv, "tool", "install", "--force", "--python", PYTHON_INSTALADO, paquete]
    return subprocess.run(orden).returncode == 0


# --- los guiones de Windows --------------------------------------------------------------

# Los accesos «tiza» del menú Inicio y del escritorio, sin administrador. Es el mismo texto
# que lleva ``install.ps1`` (un test lo comprueba): ese se ejecuta con ``irm | iex`` y no
# puede importar nada. En PowerShell, ``"$var:"`` es un error de sintaxis: ``"${var}:"``.
ACCESOS_PS = """\
function Crear-AccesosTiza([string]$bin) {
    $panel = Join-Path $bin 'tiza-panel.exe'
    if (-not (Test-Path -LiteralPath $panel)) {
        Write-Host 'No se instaló el panel de tiza (falta la ventana): tiza se usa solo desde la terminal.'
        return $false
    }
    # El icono de tiza viaja en el paquete; si no se encuentra (una versión vieja), el del ejecutable.
    $icono = "${panel},0"
    try {
        $herramientas = (uv tool dir) | Select-Object -First 1
        $candidato = Join-Path $herramientas 'tiza\\Lib\\site-packages\\tiza\\recursos\\tiza.ico'
        if (Test-Path -LiteralPath $candidato) {
            $icono = $candidato
        }
    } catch {}
    $shell = New-Object -ComObject WScript.Shell
    foreach ($carpeta in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
        try {
            $acceso = $shell.CreateShortcut((Join-Path $carpeta 'tiza.lnk'))
            $acceso.TargetPath = $panel
            $acceso.WorkingDirectory = $env:USERPROFILE
            $acceso.IconLocation = $icono
            $acceso.Description = 'Abrir tiza'
            $acceso.Save()
        } catch {
            Write-Host "No se pudo crear el acceso en ${carpeta}."
        }
    }
    return $true
}
"""

# ``tiza actualizar`` en Windows, en otra consola: espera a que esta tiza termine.
GUION_WINDOWS = (
    ACCESOS_PS
    + """
$ErrorActionPreference = 'Continue'
$Host.UI.RawUI.WindowTitle = 'Actualizar tiza'
Write-Host "Actualizando tiza a «$env:TIZA_ACT_REF». Esperando a que se cierre tiza..."
Wait-Process -Id ([int]$env:TIZA_ACT_PID) -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$uv = $env:TIZA_ACT_UV
$hecho = $false
foreach ($paquete in $env:TIZA_ACT_PAQUETES.Split('|')) {
    & $uv tool install --force --python $env:TIZA_ACT_PYTHON $paquete
    if ($LASTEXITCODE -eq 0) {
        $hecho = $true
        if ($env:TIZA_ACT_VENTANA -eq '1' -and -not $paquete.StartsWith('tiza[ventana]')) {
            Write-Host 'No se pudo instalar la ventana de entrada: se entrará con la contraseña.'
        }
        break
    }
}
Write-Host ''
if ($hecho) {
    $bin = (& $uv tool dir --bin) | Select-Object -First 1
    $tiza = Join-Path $bin 'tiza.exe'
    & $tiza instalar-skill
    if ($LASTEXITCODE -eq 0) {
        Crear-AccesosTiza $bin | Out-Null
        Write-Host 'tiza está actualizada. Ya puedes cerrar esta ventana y volver a abrir la sesión.'
    } else {
        Write-Host 'ERROR [SKILL_NO_INSTALADA]: no se pudo reinstalar la skill.'
        Write-Host 'Qué hacer: ejecuta «tiza instalar-skill».'
    }
} else {
    Write-Host 'ERROR [ACTUALIZACION_FALLIDA]: no se pudo actualizar tiza.'
    Write-Host ('Qué hacer: cierra todas las ventanas donde esté abierto tiza (también ' +
        '«tiza sesion») y vuelve a ejecutar «tiza actualizar».')
}
Read-Host 'Pulsa Intro para cerrar esta ventana'
"""
)

# La actualización desde el panel, en un PowerShell oculto: instala solo con el extra
# ``ventana``, anota en el log (sin secretos: versiones, órdenes de uv y códigos de salida) y
# vuelve a abrir ``tiza-panel`` en una ventana normal (un proceso lanzado desde otro oculto
# puede heredar SW_HIDE) con ``TIZA_PANEL_ACTUALIZACION`` diciendo cómo fue.
GUION_PANEL = (
    ACCESOS_PS
    + """
$ErrorActionPreference = 'Continue'
$log = $env:TIZA_ACT_LOG
function Anotar([string]$texto) {
    try {
        Add-Content -LiteralPath $log -Value ((Get-Date -Format 's') + ' ' + $texto) -Encoding UTF8
    } catch {}
}
try { Set-Content -LiteralPath $log -Value '' -Encoding UTF8 } catch {}
Anotar "Actualizando tiza de $env:TIZA_ACT_ANTERIOR a $env:TIZA_ACT_REF"
Wait-Process -Id ([int]$env:TIZA_ACT_PID) -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$uv = $env:TIZA_ACT_UV
$hecho = $false
foreach ($paquete in $env:TIZA_ACT_PAQUETES.Split('|')) {
    Anotar "uv tool install $paquete"
    # PowerShell 5.1 envuelve el stderr de uv en NativeCommandError: sin él, el log se lee mejor.
    $ErrorActionPreference = 'SilentlyContinue'
    $salida = & $uv tool install --force --python $env:TIZA_ACT_PYTHON $paquete 2>&1 |
        ForEach-Object { "$_" } | Out-String
    $codigo = $LASTEXITCODE
    $ErrorActionPreference = 'Continue'
    Anotar $salida
    Anotar "uv termino con codigo $codigo"
    if ($codigo -eq 0) {
        $hecho = $true
        break
    }
}
$bin = (& $uv tool dir --bin) | Select-Object -First 1
if ($hecho) {
    $tiza = Join-Path $bin 'tiza.exe'
    & $tiza instalar-skill 2>&1 | Out-Null
    Anotar "instalar-skill termino con codigo $LASTEXITCODE"
    Crear-AccesosTiza $bin | Out-Null
    $env:TIZA_PANEL_ACTUALIZACION = 'ok:' + $env:TIZA_ACT_REF.TrimStart('v')
} else {
    Anotar 'No se pudo instalar tiza.'
    $env:TIZA_PANEL_ACTUALIZACION = 'fallo'
}
Get-ChildItem Env:TIZA_ACT_* | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
$panel = Join-Path $bin 'tiza-panel.exe'
if (Test-Path -LiteralPath $panel) {
    Anotar 'Se vuelve a abrir el panel.'
    Start-Process -FilePath $panel -WorkingDirectory $env:USERPROFILE -WindowStyle Normal
} else {
    Anotar 'No se encontro tiza-panel.exe.'
}
"""
)


# --- Linux: el acceso del menú de aplicaciones y el actualizador del panel -------------------

# El acceso «tiza» del menú de aplicaciones (``tiza.desktop``), sin administrador. Es el mismo
# texto que lleva ``install.sh`` (un test lo comprueba): ese se ejecuta con ``curl | sh``. El
# nombre ``tiza.desktop`` es el que da el panel a Qt (``setDesktopFileName``): en Wayland así
# lo asocia GNOME al acceso y el panel minimizado sigue en el dock.
ACCESO_SH = """\
crear_acceso_tiza() {
    panel="$1/tiza-panel"
    if [ ! -x "$panel" ]; then
        echo "No se instaló el panel de tiza (falta la ventana): tiza se usa solo desde la terminal."
        return 1
    fi
    datos="${XDG_DATA_HOME:-$HOME/.local/share}"
    icono="$datos/icons/tiza.png"
    mkdir -p "$datos/applications" "$datos/icons"
    for candidato in "$(uv tool dir 2>/dev/null)"/tiza/lib/python*/site-packages/tiza/recursos/logo.png; do
        if [ -f "$candidato" ]; then
            cp "$candidato" "$icono"
            break
        fi
    done
    cat > "$datos/applications/tiza.desktop" <<FIN_DEL_ACCESO
[Desktop Entry]
Type=Application
Name=tiza
Comment=Abrir la sesión de tiza con el aula virtual
Exec="$panel"
Icon=$icono
Terminal=false
Categories=Education;
StartupWMClass=tiza-panel
FIN_DEL_ACCESO
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$datos/applications" >/dev/null 2>&1
    fi
    return 0
}
"""

# La actualización desde el panel en Linux, en un ``sh`` desacoplado (sesión propia, sin
# terminal): espera a que el panel termine, instala solo con el extra ``ventana``, anota en el
# log (versiones, órdenes de uv y códigos de salida), rehace el acceso y vuelve a abrir el
# panel con ``TIZA_PANEL_ACTUALIZACION`` diciendo cómo fue.
GUION_PANEL_LINUX = (
    ACCESO_SH
    + """
log="$TIZA_ACT_LOG"
anotar() {
    printf '%s %s\\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$1" >> "$log" 2>/dev/null
}
: > "$log" 2>/dev/null
anotar "Actualizando tiza de $TIZA_ACT_ANTERIOR a $TIZA_ACT_REF"
while kill -0 "$TIZA_ACT_PID" 2>/dev/null; do
    sleep 1
done
sleep 1
uv="$TIZA_ACT_UV"
hecho=0
anterior_ifs=$IFS
IFS='|'
for paquete in $TIZA_ACT_PAQUETES; do
    IFS=$anterior_ifs
    anotar "uv tool install $paquete"
    "$uv" tool install --force --python "$TIZA_ACT_PYTHON" "$paquete" >> "$log" 2>&1
    codigo=$?
    anotar "uv termino con codigo $codigo"
    if [ "$codigo" -eq 0 ]; then
        hecho=1
        break
    fi
done
IFS=$anterior_ifs
bin="$("$uv" tool dir --bin 2>/dev/null)"
if [ "$hecho" = 1 ]; then
    "$bin/tiza" instalar-skill >/dev/null 2>&1
    anotar "instalar-skill termino con codigo $?"
    crear_acceso_tiza "$bin" >/dev/null 2>&1
    TIZA_PANEL_ACTUALIZACION="ok:${TIZA_ACT_REF#v}"
else
    anotar "No se pudo instalar tiza."
    TIZA_PANEL_ACTUALIZACION=fallo
fi
export TIZA_PANEL_ACTUALIZACION
unset TIZA_ACT_PID TIZA_ACT_REF TIZA_ACT_UV TIZA_ACT_PYTHON TIZA_ACT_PAQUETES TIZA_ACT_LOG \\
    TIZA_ACT_ANTERIOR
if [ -x "$bin/tiza-panel" ]; then
    anotar "Se vuelve a abrir el panel."
    cd "$HOME" || exit 1
    exec "$bin/tiza-panel"
fi
anotar "No se encontro tiza-panel."
"""
)


def orden_sh(guion: str) -> list[str]:
    """La orden que ejecuta ``guion`` con ``/bin/sh`` (el guion va como argumento, no por disco)."""
    return ["/bin/sh", "-c", guion, "tiza-actualizar"]


def _codificar(guion: str) -> str:
    return base64.b64encode(guion.encode("utf-16-le")).decode("ascii")


def orden_powershell(guion: str, *, oculto: bool) -> list[str]:
    """La orden de PowerShell que ejecuta ``guion`` (``-EncodedCommand``), oculta o no."""
    orden = ["powershell.exe", "-NoProfile"]
    if oculto:
        orden += ["-WindowStyle", "Hidden"]
    return [*orden, "-EncodedCommand", _codificar(guion)]


def _entorno_comun(
    base: Mapping[str, str], *, pid: int, ref: str, uv: str, paquetes: Sequence[str]
) -> dict[str, str]:
    validar_ref(ref)
    entorno = {k: v for k, v in base.items() if k != VARIABLE_RESULTADO}
    entorno.update(
        {
            "TIZA_ACT_PID": str(pid),
            "TIZA_ACT_REF": ref,
            "TIZA_ACT_UV": uv,
            "TIZA_ACT_PYTHON": PYTHON_INSTALADO,
            "TIZA_ACT_PAQUETES": "|".join(paquetes),
        }
    )
    return entorno


def entorno_consola(
    base: Mapping[str, str],
    *,
    pid: int,
    ref: str,
    uv: str,
    paquetes: Sequence[str],
    con_ventana: bool,
) -> dict[str, str]:
    """Las variables de ``GUION_WINDOWS`` (``tiza actualizar``)."""
    entorno = _entorno_comun(base, pid=pid, ref=ref, uv=uv, paquetes=paquetes)
    entorno.update({"TIZA_ACT_VENTANA": "1" if con_ventana else "0"})
    return entorno


def entorno_panel(
    base: Mapping[str, str],
    *,
    pid: int,
    ref: str,
    uv: str,
    log: Path,
    anterior: str,
) -> dict[str, str]:
    """Las variables de ``GUION_PANEL``: solo con el extra ``ventana`` y con el log del docente."""
    entorno = _entorno_comun(base, pid=pid, ref=ref, uv=uv, paquetes=paquetes_con_ventana(ref))
    entorno.update({"TIZA_ACT_LOG": str(log), "TIZA_ACT_ANTERIOR": anterior})
    return entorno


def ruta_log() -> Path:
    """El log de la actualización desde el panel, junto a la configuración global."""
    return config.directorio_global() / "actualizar.log"


def lanzar_consola(
    uv: str,
    ref: str,
    paquetes: Sequence[str],
    con_ventana: bool,
    *,
    lanzar: Callable[..., object] | None = None,
) -> None:
    """Windows: lanza ``GUION_WINDOWS`` en otra consola, que espera a que esta tiza termine.

    Lanza ``OSError`` si no se puede abrir la consola.
    """
    entorno = entorno_consola(
        os.environ, pid=os.getpid(), ref=ref, uv=uv, paquetes=paquetes, con_ventana=con_ventana
    )
    (lanzar or subprocess.Popen)(
        orden_powershell(GUION_WINDOWS, oculto=False),
        env=entorno,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", CREATE_NEW_CONSOLE),
    )


def lanzar_panel_oculto(
    uv: str,
    ref: str,
    *,
    anterior: str | None = None,
    log: Path | None = None,
    lanzar: Callable[..., object] | None = None,
    plataforma: str | None = None,
) -> bool:
    """Lanza el actualizador del panel sin ventana; False si no se pudo (el panel sigue como
    estaba). En Windows, ``GUION_PANEL``; en Linux, ``GUION_PANEL_LINUX``."""
    destino = log or ruta_log()
    if (plataforma or sys.platform).startswith("linux"):
        return _lanzar_panel_linux(uv, ref, anterior=anterior, log=destino, lanzar=lanzar)
    try:
        entorno = entorno_panel(
            os.environ,
            pid=os.getpid(),
            ref=ref,
            uv=uv,
            log=destino,
            anterior=anterior or __version__,
        )
        destino.parent.mkdir(parents=True, exist_ok=True)
        (lanzar or subprocess.Popen)(
            orden_powershell(GUION_PANEL, oculto=True),
            env=entorno,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", CREATE_NO_WINDOW),
        )
    except (OSError, ErrorActualizacion):
        return False
    return True


def _lanzar_panel_linux(
    uv: str,
    ref: str,
    *,
    anterior: str | None,
    log: Path,
    lanzar: Callable[..., object] | None,
) -> bool:
    try:
        entorno = entorno_panel(
            os.environ,
            pid=os.getpid(),
            ref=ref,
            uv=uv,
            log=log,
            anterior=anterior or __version__,
        )
        log.parent.mkdir(parents=True, exist_ok=True)
        (lanzar or subprocess.Popen)(
            orden_sh(GUION_PANEL_LINUX),
            env=entorno,
            cwd=str(Path.home()),
            start_new_session=True,  # sigue vivo cuando el panel termine
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, ErrorActualizacion):
        return False
    return True


def resultado_del_entorno(entorno: Mapping[str, str]) -> tuple[bool, str] | None:
    """Lo que dejó el actualizador del panel: ``(se_actualizó, versión)`` o None si no hay nada.

    ``ok:X.Y.Z`` con la versión nueva, ``fallo`` sin versión. Cualquier otra cosa se ignora.
    """
    valor = entorno.get(VARIABLE_RESULTADO, "").strip()
    if valor == "fallo":
        return (False, "")
    if valor.startswith("ok:") and _VERSION_SUELTA.match(valor[3:]):
        return (True, valor[3:])
    return None
