#!/bin/sh
# Instala tiza (CLI y skill) en macOS o Linux. Se puede ejecutar de nuevo para actualizar.
#   curl -LsSf https://raw.githubusercontent.com/balejosg/tiza/main/install.sh | sh
# Por defecto instala la etiqueta indicada abajo. TIZA_REF=<etiqueta|rama|commit> la cambia
# (por ejemplo TIZA_REF=main para la última versión).
set -eu

REF="${TIZA_REF:-v0.20.1}"
# Sin git: se descarga el .zip de GitHub. Las referencias con «/» (ramas con
# barra) siguen necesitando git.
case "$REF" in
    */*) ORIGEN="git+https://github.com/balejosg/tiza@$REF" ;;
    *) ORIGEN="https://github.com/balejosg/tiza/archive/$REF.zip" ;;
esac
PAQUETE="tiza @ $ORIGEN"
# En macOS se instala también la ventana de entrada al aula (pywebview); en Linux no hay.
VENTANA=0
[ "$(uname -s)" = "Darwin" ] && VENTANA=1

if ! command -v uv >/dev/null 2>&1; then
    echo "Instalando uv (gestor de Python)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    export PATH
fi

if [ "$VENTANA" = 1 ] && uv tool install --force "tiza[ventana] @ $ORIGEN"; then
    :
else
    [ "$VENTANA" = 1 ] && echo "No se pudo instalar la ventana de entrada: tiza funcionará con la contraseña en la terminal."
    uv tool install --force "$PAQUETE"
fi
PATH="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin"):$PATH"
export PATH

tiza instalar-skill

echo
echo "Listo. Siguiente paso: tiza empezar"
echo "Si 'tiza' no se encuentra, abre una terminal nueva (o ejecuta: uv tool update-shell)."
