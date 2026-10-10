"""Etiqueta de Moodle (``mod_label``): texto y medios dentro de la página del curso."""

from __future__ import annotations

from .base import Tipo, campo_visible


class Etiqueta(Tipo):
    nombre = "etiqueta"
    llano = "Área de texto y medios"
    modulo = "label"
    finalizaciones = ("ninguna", "manual")

    def payload(self, doc, html, itemid, visible, *, itemid_paquete=None) -> dict:
        payload = {
            "_qf__mod_label_mod_form": "1",
            "name": doc.nombre,
            "introeditor[text]": html,
            "introeditor[format]": "1",
            "introeditor[itemid]": str(itemid),
            "submitbutton2": "Save and return to course",
        }
        payload.update(campo_visible(visible))
        return payload

    def urls_pluginfile(self, base_url, contexto, instance, nombre) -> list[str]:
        # El texto de una etiqueta va en mod_label/intro (sin itemid).
        raiz = f"{base_url}/pluginfile.php/{contexto}/mod_label"
        return [f"{raiz}/intro/{nombre}"]
