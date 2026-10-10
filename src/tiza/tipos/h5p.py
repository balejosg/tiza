"""Contenido interactivo H5P (``mod_h5pactivity``): actividad generada o paquete subido."""

from __future__ import annotations

from .base import Tipo

# Todos los campos que puede llevar el bloque del frontmatter, entre los del
# documento («actividad», «paquete») y los de la actividad generada. Lo usa
# ``test_agente`` para comprobar que la skill los enseña todos.
CAMPOS_H5P = frozenset(
    {
        "actividad",
        "paquete",
        "tipo",
        "textos",
        "texto",
        "enunciado",
        "distractores",
        "tarjetas",
        "anverso",
        "reverso",
        "mayusculas",
        "calificacion",
        "reintentar",
        "ver_solucion",
    }
)


class H5P(Tipo):
    nombre = "h5p"
    llano = "Contenido interactivo (H5P)"
    modulo = "h5pactivity"
    campos = frozenset({"actividad", "paquete"})
    finalizaciones = ("ninguna", "manual", "ver", "calificar")
    banderas = ("completionview", "completionusegrade")
