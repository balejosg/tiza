"""Nombre de la carpeta de trabajo y del fichero de asignatura.

Están centralizados aquí para que un cambio de nombre del producto no se escape
de ningún módulo: los literales ``.tiza`` y ``tiza.toml`` solo viven en este
fichero.
"""

from __future__ import annotations

CARPETA_TRABAJO = ".tiza"  # estado de la asignatura: informe, estructura, buzón y vistas
FICHERO_ASIGNATURA = "tiza.toml"  # cursos de esta asignatura; lo escribe el docente
# Calendario escolar opcional: solo da avisos de fechas, nunca bloquea una publicación.
FICHERO_CALENDARIO = "calendario.toml"
