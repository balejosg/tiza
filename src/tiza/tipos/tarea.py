"""Tarea de Moodle (``mod_assign``): entrega con fechas y recordatorio de calificación."""

from __future__ import annotations

from .base import CAMPO_RECORDATORIO, FechaActividad, Tipo, fechas_payload

# Campos propios del frontmatter y campos de fecha del formulario de Moodle
# (en español: «Permitir entregas desde», «Fecha de entrega», «Fecha límite» y
# «Recordarme calificar en»).
CAMPOS_TAREA = frozenset({"apertura", "entrega", "limite"})
CAMPOS_FECHA = ("allowsubmissionsfromdate", "duedate", "cutoffdate", "gradingduedate")


class Tarea(Tipo):
    nombre = "tarea"
    llano = "Tarea"
    modulo = "assign"
    campos = CAMPOS_TAREA
    finalizaciones = ("ninguna", "manual", "ver", "entregar", "calificar")
    banderas = ("completionview", "completionsubmit", "completionusegrade")
    campos_fecha = CAMPOS_FECHA

    def fechas(self, doc) -> tuple[FechaActividad, ...]:
        fechas = doc.fechas
        return (
            FechaActividad(
                "apertura", fechas.apertura if fechas else None, "allowsubmissionsfromdate"
            ),
            FechaActividad(
                "entrega", fechas.entrega if fechas else None, "duedate", exige_clase=True
            ),
            FechaActividad("límite", fechas.limite if fechas else None, "cutoffdate"),
            # Tiza nunca pone el recordatorio: aquí va solo para desactivarlo y para que
            # la confirmación de real enseñe que se quita.
            FechaActividad(CAMPO_RECORDATORIO, None, "gradingduedate"),
        )

    def payload_solo_fechas(self, doc) -> dict[str, str]:
        return {
            "_qf__mod_assign_mod_form": "1",
            "submitbutton": "Save and display",
            **fechas_payload(self, doc),
        }
