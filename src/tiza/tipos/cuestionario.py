"""Cuestionario de Moodle (``mod_quiz``): ajustes, preguntas y fechas."""

from __future__ import annotations

from .base import FechaActividad, Tipo, fechas_payload

# Campos propios del frontmatter (las preguntas van dentro) y campos de fecha del
# formulario de Moodle («Abrir el cuestionario» y «Cerrar el cuestionario»).
CAMPOS_CUESTIONARIO = frozenset(
    {"apertura", "cierre", "tiempo_limite", "intentos", "mezclar_respuestas", "preguntas"}
)
CAMPOS_FECHA = ("timeopen", "timeclose")


class Cuestionario(Tipo):
    nombre = "cuestionario"
    llano = "Cuestionario"
    modulo = "quiz"
    campos = CAMPOS_CUESTIONARIO
    finalizaciones = ("ninguna", "manual", "ver", "calificar")
    banderas = ("completionview", "completionusegrade")
    campos_fecha = CAMPOS_FECHA

    def fechas(self, doc) -> tuple[FechaActividad, ...]:
        cuestionario = doc.cuestionario
        return (
            FechaActividad("apertura", cuestionario.apertura if cuestionario else None, "timeopen"),
            FechaActividad(
                "cierre",
                cuestionario.cierre if cuestionario else None,
                "timeclose",
                exige_clase=True,
            ),
        )

    def payload_solo_fechas(self, doc) -> dict[str, str]:
        return {
            "_qf__mod_quiz_mod_form": "1",
            "submitbutton2": "Save and return to course",
            **fechas_payload(self, doc),
        }
