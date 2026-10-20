# Instala tiza (CLI y skill) en Windows. Se puede ejecutar de nuevo para actualizar.
#   irm https://raw.githubusercontent.com/balejosg/tiza/main/install.ps1 | iex
# Por defecto instala la etiqueta indicada abajo. $env:TIZA_REF = "<etiqueta|rama|commit>" la cambia
# (por ejemplo "main" para la última versión).
$ErrorActionPreference = "Stop"

$ref = if ($env:TIZA_REF) { $env:TIZA_REF } else { "v0.24.2" }
# Sin git. Una versión publicada (vX.Y.Z) se instala desde el wheel de su release, que no
# hay que construir; si aún no está subido, desde el .zip. Una rama o un commit, desde el
# .zip. Las referencias con «/» (ramas con barra, solo para desarrollo) necesitan git.
$repo = "https://github.com/balejosg/tiza"
$origenes = if ($ref -match "/") {
    @("git+$repo@$ref")
} elseif ($ref -match "^v\d+\.\d+\.\d+$") {
    @("$repo/releases/download/$ref/tiza-$($ref.Substring(1))-py3-none-any.whl", "$repo/archive/$ref.zip")
} else {
    @("$repo/archive/$ref.zip")
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

# Python fijo: uv usaría el más nuevo, y una versión recién salida aún no tiene wheels de
# todas las dependencias (pyyaml, por ejemplo) y obligaría a compilarlas.
$python = "3.13"

# Se instala también la ventana de entrada al aula (pywebview, sobre el WebView2 de
# Windows); si falla, tiza se instala sin ella y el docente entra con la contraseña en la terminal.
$instalado = $false
foreach ($origen in $origenes) {
    uv tool install --force --python $python "tiza[ventana] @ $origen"
    if ($LASTEXITCODE -eq 0) { $instalado = $true; break }
    uv tool install --force --python $python "tiza @ $origen"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "No se pudo instalar la ventana de entrada: tiza funcionará con la contraseña en la terminal."
        $instalado = $true
        break
    }
}
if (-not $instalado) { throw "No se pudo instalar tiza." }
$env:Path = "$(uv tool dir --bin);$env:Path"

tiza instalar-skill
if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar la skill." }

Write-Host ""
Write-Host "Listo. Siguiente paso: tiza empezar"
Write-Host "Si 'tiza' no se encuentra, abre una terminal nueva (o ejecuta: uv tool update-shell)."
