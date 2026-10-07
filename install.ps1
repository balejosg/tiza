# Instala tiza (CLI y skill) en Windows. Se puede ejecutar de nuevo para actualizar.
#   irm https://raw.githubusercontent.com/balejosg/tiza/main/install.ps1 | iex
# Por defecto instala la etiqueta indicada abajo. $env:TIZA_REF = "<etiqueta|rama|commit>" la cambia
# (por ejemplo "main" para la última versión).
$ErrorActionPreference = "Stop"

$ref = if ($env:TIZA_REF) { $env:TIZA_REF } else { "v0.11.0" }
$repo = "git+https://github.com/balejosg/tiza@$ref"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Instalando uv (gestor de Python)..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

uv tool install --force $repo
if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar tiza." }
$env:Path = "$(uv tool dir --bin);$env:Path"

tiza instalar-skill
if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar la skill." }

Write-Host ""
Write-Host "Listo. Siguiente paso: tiza configurar"
Write-Host "Si 'tiza' no se encuentra, abre una terminal nueva (o ejecuta: uv tool update-shell)."
