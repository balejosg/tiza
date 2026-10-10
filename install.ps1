# Instala tiza (CLI y skill) en Windows. Se puede ejecutar de nuevo para actualizar.
#   irm https://raw.githubusercontent.com/balejosg/tiza/main/install.ps1 | iex
# Por defecto instala la etiqueta indicada abajo. $env:TIZA_REF = "<etiqueta|rama|commit>" la cambia
# (por ejemplo "main" para la última versión).
$ErrorActionPreference = "Stop"

$ref = if ($env:TIZA_REF) { $env:TIZA_REF } else { "v0.16.1" }
# Sin git: se descarga el .zip de GitHub. Las referencias con «/» (ramas con
# barra) siguen necesitando git.
$paquete = if ($ref -match "/") {
    "git+https://github.com/balejosg/tiza@$ref"
} else {
    "tiza @ https://github.com/balejosg/tiza/archive/$ref.zip"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Instalando uv (gestor de Python)..."
    # En un proceso hijo: el instalador de uv termina con «exit» y cerraría esta
    # ventana de PowerShell si se ejecutara aquí con Invoke-Expression.
    $nombre = if ($PSVersionTable.PSEdition -eq "Core") { "pwsh.exe" } else { "powershell.exe" }
    $exe = Join-Path $PSHOME $nombre
    try {
        & $exe -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    } catch {
        $LASTEXITCODE = 1
    }
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo instalar uv. Instálalo a mano con «winget install --id=astral-sh.uv -e» (o mira https://docs.astral.sh/uv/) y vuelve a ejecutar este instalador."
    }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv se instaló en una carpeta que no está en el PATH de esta terminal. Abre una terminal nueva y repite."
    }
}

uv tool install --force "$paquete"
if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar tiza." }
$env:Path = "$(uv tool dir --bin);$env:Path"

tiza instalar-skill
if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar la skill." }

Write-Host ""
Write-Host "Listo. Siguiente paso: tiza configurar"
Write-Host "Si 'tiza' no se encuentra, abre una terminal nueva (o ejecuta: uv tool update-shell)."
