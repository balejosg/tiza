"""Tarea de Moodle (``mod_assign``): entrega con fechas y recordatorio de calificación."""

from __future__ import annotations

from datetime import time

from ..contenido import ErrorContenido, Fechas
from .base import CAMPO_RECORDATORIO, Contexto, Extras, FechaActividad, Tipo, fechas_payload

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

    def validar(self, datos: dict, ctx: Contexto) -> Extras:
        for campo in ("apertura", "entrega"):
            if datos.get(campo) is None:
                raise ErrorContenido("CAMPO_FALTANTE", f"falta el campo «{campo}»")
        apertura = ctx.fecha(datos["apertura"], time(0, 0))
        entrega = ctx.fecha(datos["entrega"], time(23, 59))
        limite = (
            ctx.fecha(datos["limite"], time(23, 59)) if datos.get("limite") is not None else None
        )
        if not (apertura < entrega and (limite is None or entrega < limite)):
            raise ErrorContenido(
                "FECHAS_INCOHERENTES",
                "debe cumplirse apertura < entrega" + (" < límite" if limite else ""),
            )
        return Extras(fechas=Fechas(apertura=apertura, entrega=entrega, limite=limite))

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
