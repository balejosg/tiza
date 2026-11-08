#!/bin/sh
# Instala tiza (CLI y skill) en macOS o Linux. Se puede ejecutar de nuevo para actualizar.
#   curl -LsSf https://raw.githubusercontent.com/balejosg/tiza/main/install.sh | sh
# Por defecto instala la etiqueta indicada abajo. TIZA_REF=<etiqueta|rama|commit> la cambia
# (por ejemplo TIZA_REF=main para la última versión). En Linux con escritorio, TIZA_PANEL=1
# instala además el panel (tiza sin terminal) y su acceso «tiza» en el menú de aplicaciones.
set -eu

REF="${TIZA_REF:-v0.41.0}"
# Sin git. Una versión publicada (vX.Y.Z) se instala desde el wheel de su release, que no
# hay que construir; si aún no está subido, desde el .zip. Una rama o un commit, desde el
# .zip. Las referencias con «/» (ramas con barra, solo para desarrollo) necesitan git.
REPO="https://github.com/balejosg/tiza"
case "$REF" in
    */*) ORIGENES="git+$REPO@$REF" ;;
    v[0-9]*.[0-9]*.[0-9]*) ORIGENES="$REPO/releases/download/$REF/tiza-${REF#v}-py3-none-any.whl $REPO/archive/$REF.zip" ;;
    *) ORIGENES="$REPO/archive/$REF.zip" ;;
esac
# En macOS se instala también la ventana de entrada al aula (pywebview). En Linux trae Qt
# (cientos de MB): solo con TIZA_VENTANA=1 o TIZA_PANEL=1; sin ella, la contraseña se pide en
# la terminal.
VENTANA=0
PANEL=0
[ "$(uname -s)" = "Darwin" ] && VENTANA=1
[ "${TIZA_VENTANA:-0}" = 1 ] && VENTANA=1
if [ "${TIZA_PANEL:-0}" = 1 ] && [ "$(uname -s)" = "Linux" ]; then
    VENTANA=1
    PANEL=1
fi

# El acceso «tiza» del menú de aplicaciones (el mismo bloque que usa el actualizador del panel).
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

if ! command -v uv >/dev/null 2>&1; then
    echo "Instalando uv (gestor de Python)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    export PATH
fi

# Python fijo: uv usaría el más nuevo, y una versión recién salida aún no tiene wheels de
# todas las dependencias (pyyaml, por ejemplo) y obligaría a compilarlas.
PYTHON=3.13

INSTALADO=0
CON_VENTANA=0
for ORIGEN in $ORIGENES; do
    if [ "$VENTANA" = 1 ] && uv tool install --force --python "$PYTHON" "tiza[ventana] @ $ORIGEN"; then
        INSTALADO=1
        CON_VENTANA=1
        break
    fi
    if uv tool install --force --python "$PYTHON" "tiza @ $ORIGEN"; then
        [ "$VENTANA" = 1 ] && echo "No se pudo instalar la ventana de entrada: tiza funcionará con la contraseña en la terminal."
        INSTALADO=1
        break
    fi
done
if [ "$INSTALADO" != 1 ]; then
    echo "No se pudo instalar tiza." >&2
    exit 1
fi
PATH="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin"):$PATH"
export PATH

tiza instalar-skill

echo
if [ "$PANEL" = 1 ] && [ "$CON_VENTANA" = 1 ] && crear_acceso_tiza "$(uv tool dir --bin)"; then
    echo "Listo. Busca «tiza» en tus aplicaciones para abrirlo (o usa: tiza empezar)."
elif [ "$PANEL" = 1 ]; then
    echo "Listo, sin el panel. Siguiente paso: tiza empezar"
else
    echo "Listo. Siguiente paso: tiza empezar"
fi
echo "Si 'tiza' no se encuentra, abre una terminal nueva (o ejecuta: uv tool update-shell)."
