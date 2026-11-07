"""Tarea de Moodle (``mod_assign``): entrega con fechas y recordatorio de calificación."""

from __future__ import annotations

import html
from datetime import time

from ..contenido import ErrorContenido, Fechas, numero_texto
from .base import (
    CAMPO_RECORDATORIO,
    Contexto,
    Extras,
    FechaActividad,
    Tipo,
    campo_visible,
    fechas_payload,
    formato_fecha,
    verificar,
)

# Campos propios del frontmatter y campos de fecha del formulario de Moodle
# (en español: «Permitir entregas desde», «Fecha de entrega», «Fecha límite» y
# «Recordarme calificar en»).
CAMPOS_TAREA = frozenset({"apertura", "entrega", "limite", "rubrica", "evidencia"})
CAMPOS_FECHA = ("allowsubmissionsfromdate", "duedate", "cutoffdate", "gradingduedate")


class Tarea(Tipo):
    nombre = "tarea"
    llano = "Tarea"
    modulo = "assign"
    campos = CAMPOS_TAREA
    finalizaciones = ("ninguna", "manual", "ver", "entregar", "calificar")
    banderas = ("completionview", "completionsubmit", "completionusegrade")
    campos_fecha = CAMPOS_FECHA
    calificable = True
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

    def payload(
        self,
        doc,
        html,
        itemid,
        visible,
        *,
        itemid_paquete=None,
        fijar_metodo: bool = True,
        resultados: dict[str, int] | None = None,
    ) -> dict:
        payload = {
            "_qf__mod_assign_mod_form": "1",
            "name": doc.nombre,
            "introeditor[text]": html,
            "introeditor[format]": "1",
            "introeditor[itemid]": str(itemid),
            "introattachments": str(itemid),
            "submitbutton": "Save and display",
        }
        if fijar_metodo:
            # Tiza activa el flujo de calificación al crear o republicar una tarea que
            # aún no tiene notas; con la rúbrica, además, el método de calificación.
            payload["markingworkflow"] = "1"
            payload["markingallocation"] = "0"
            if doc.rubrica is not None:
                from ..publicar import METODO_SUBMISSIONS

                payload[METODO_SUBMISSIONS] = "rubric"
        # ``evidencia: resultados``: la tarea marca los resultados de sus criterios. Solo los
        # que tiza creó y tiene con id en Moodle; sin ellos, no se envía ningún ``outcome_``.
        if doc.evidencia == "resultados":
            for criterio, _ in doc.evalua or ():
                resultado = (resultados or {}).get(criterio)
                if resultado is not None:
                    payload[f"outcome_{resultado}"] = "1"
        payload.update(fechas_payload(self, doc))
        payload.update(campo_visible(visible))
        return payload

    def payload_de(self, p, *, fijar_metodo: bool = True) -> dict[str, str]:
        """Al actualizar, el área de «Archivos adicionales» es la del formulario, con sus ficheros.

        Una nueva y vacía los borraría en Moodle. Si el formulario no trae esa área, la clave se
        quita: lo que no se envía se conserva. En una tarea nueva todo sigue igual.
        ``fijar_metodo`` falso deja el flujo y el método de calificación como están.
        """
        payload = self.payload(
            p.doc,
            p.html,
            p.itemid,
            p.visible,
            fijar_metodo=fijar_metodo,
            resultados=p.resultados,
        )
        if p.existente is not None:
            adjuntos = (p.leido or {}).get("adjuntos")
            if adjuntos is None:
                payload.pop("introattachments", None)
            else:
                payload["introattachments"] = str(adjuntos)
        return payload

    def publicar(self, p) -> tuple[int, str, dict]:
        """Crea o actualiza la tarea y decide si la rúbrica se toca.

        Una tarea nueva recibe su rúbrica siempre. Una que ya existe solo si el docente
        confirmó que ninguna de las tareas listadas tiene notas (``p.rubrica_confirmada``)
        y ``actividad_tiene_notas`` no ve el campo de reescalado. Si no, ``RUBRICA_NO_ACTIVADA``
        y se publica el resto sin cambiar el método de calificación.
        """
        existente = p.existente
        con_notas = (
            existente is not None
            and p.doc.rubrica is not None
            and p.moodle.actividad_tiene_notas(existente.cmid)
        )
        sin_confirmacion = (
            p.doc.rubrica is not None and existente is not None and not p.rubrica_confirmada
        )
        if p.doc.rubrica is not None and existente is not None and (con_notas or sin_confirmacion):
            from .. import informe  # diferido: informe importa el registro de tipos

            detalle = (
                "la tarea ya tiene notas"
                if con_notas
                else "no se confirmó que la tarea no tenga notas"
            )
            p.pasos.append(
                informe.Paso("RUBRICA_NO_ACTIVADA", "ok", f"{p.doc.ruta.name}: {detalle}")
            )
            payload = self.payload_de(p, fijar_metodo=False)
        else:
            payload = self.payload_de(p)
        if existente is not None:
            cmid = existente.cmid
            p.moodle.actualizar(cmid, payload)
            accion = "actualizada"
        else:
            cmid = p.moodle.crear(p.curso_id, p.seccion.id, self.nombre, payload)
            accion = "creada"
        if p.doc.rubrica is not None and (
            existente is None or (not con_notas and p.rubrica_confirmada)
        ):
            p.moodle.definir_rubrica(cmid, p.doc.rubrica)
        from ..publicar import ErrorPublicacion

        try:
            info = verificar(p.moodle, self, p.doc, cmid)
        except ErrorPublicacion as exc:
            exc.cmid = cmid
            raise
        return cmid, accion, info

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

    def hash_contenido(self, doc, resumen) -> None:
        if doc.rubrica is not None:
            resumen.update(b"\n--rubrica--\n")
            resumen.update(doc.rubrica.hash().encode("utf-8"))
        # Solo cambia el hash de una tarea con ``evidencia``: las demás conservan el de siempre.
        if doc.evidencia is not None:
            resumen.update(b"\n--evidencia--\n")
            resumen.update(doc.evidencia.encode("utf-8"))

    def extra_preview(self, doc) -> str:
        return _rubrica_preview(doc)


def _porcentaje(valor: float) -> str:
    return numero_texto(valor).replace(".", ",")


def _rubrica_preview(doc) -> str:
    """La rúbrica en la vista previa: descripción y tabla de filas por niveles."""
    if doc.rubrica is None:
        return ""
    cargada = doc.rubrica
    total = sum(criterio.maximo for criterio in cargada.criterios)
    ids_niveles: list[str] = []
    for criterio in cargada.criterios:
        for nivel in criterio.niveles:
            if nivel.id not in ids_niveles:
                ids_niveles.append(nivel.id)
    partes = [
        "<hr>",
        f"<h2>Rúbrica: {html.escape(cargada.nombre)}</h2>",
        cargada.html,
        "<table><thead><tr><th>Criterio</th><th>Peso</th>"
        + "".join(f"<th>{html.escape(nivel)}</th>" for nivel in ids_niveles)
        + "</tr></thead><tbody>",
    ]
    for criterio in cargada.criterios:
        por_nivel = {nivel.id: nivel for nivel in criterio.niveles}
        celdas: list[str] = []
        for id_ in ids_niveles:
            nivel = por_nivel.get(id_)
            if nivel is None:
                celdas.append("<td></td>")
                continue
            celdas.append(
                f"<td><strong>{numero_texto(nivel.puntos)} puntos</strong><br>"
                f"{html.escape(nivel.descripcion)}</td>"
            )
        peso = _porcentaje(round(criterio.maximo / total * 100, 2))
        partes.append(
            f"<tr><td><strong>{html.escape(criterio.nombre)}</strong><br>"
            f"{html.escape(criterio.descripcion)}</td><td>{peso} %</td>" + "".join(celdas) + "</tr>"
        )
    partes.append("</tbody></table>")
    return "\n".join(partes)
