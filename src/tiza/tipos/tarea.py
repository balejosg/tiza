"""Tarea de Moodle (``mod_assign``): entrega con fechas y recordatorio de calificación."""

from __future__ import annotations

from datetime import time

from ..contenido import ErrorContenido, Fechas
from .base import (
    CAMPO_RECORDATORIO,
    Contexto,
    Extras,
    FechaActividad,
    Tipo,
    campo_visible,
    fechas_payload,
    formato_fecha,
)

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
    lee_formulario_al_actualizar = True  # para reenviar el área de «Archivos adicionales»

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

    def payload(self, doc, html, itemid, visible, *, itemid_paquete=None) -> dict:
        payload = {
            "_qf__mod_assign_mod_form": "1",
            "name": doc.nombre,
            "introeditor[text]": html,
            "introeditor[format]": "1",
            "introeditor[itemid]": str(itemid),
            "introattachments": str(itemid),
            "submitbutton": "Save and display",
        }
        payload.update(fechas_payload(self, doc))
        payload.update(campo_visible(visible))
        return payload

    def payload_de(self, p) -> dict[str, str]:
        """Al actualizar, el área de «Archivos adicionales» es la del formulario, con sus ficheros.

        Una nueva y vacía los borraría en Moodle. Si el formulario no trae esa área, la clave se
        quita: lo que no se envía se conserva. En una tarea nueva todo sigue igual.
        """
        payload = super().payload_de(p)
        if p.existente is not None:
            adjuntos = (p.leido or {}).get("adjuntos")
            if adjuntos is None:
                payload.pop("introattachments", None)
            else:
                payload["introattachments"] = str(adjuntos)
        return payload

    def urls_pluginfile(self, base_url, contexto, instance, nombre) -> list[str]:
        # En una tarea, intro no lleva itemid e introattachment usa el 0.
        raiz = f"{base_url}/pluginfile.php/{contexto}/mod_assign"
        return [f"{raiz}/intro/{nombre}", f"{raiz}/introattachment/0/{nombre}"]

    def metadatos_preview(self, doc) -> list[tuple[str, str]]:
        fechas = doc.fechas
        if fechas is None:
            return []
        filas = [
            ("Apertura", formato_fecha(fechas.apertura)),
            ("Entrega", formato_fecha(fechas.entrega)),
        ]
        if fechas.limite is not None:
            filas.append(("Límite", formato_fecha(fechas.limite)))
        return filas

    def hash_fechas(self, doc, resumen) -> None:
        if doc.fechas is None:
            return
        resumen.update(formato_fecha(doc.fechas.apertura).encode("utf-8"))
        resumen.update(formato_fecha(doc.fechas.entrega).encode("utf-8"))
        if doc.fechas.limite is not None:
            resumen.update(formato_fecha(doc.fechas.limite).encode("utf-8"))
