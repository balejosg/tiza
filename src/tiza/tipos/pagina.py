"""Página de Moodle (``mod_page``): contenido con texto e imágenes."""

from __future__ import annotations

from .base import Tipo, campo_visible


class Pagina(Tipo):
    nombre = "pagina"
    llano = "Página"
    modulo = "page"
    finalizaciones = ("ninguna", "manual", "ver")
    banderas = ("completionview",)

    def payload(self, doc, html, itemid, visible, *, itemid_paquete=None) -> dict:
        payload = {
            "_qf__mod_page_mod_form": "1",
            "name": doc.nombre,
            "page[text]": html,
            "page[format]": "1",
            "page[itemid]": str(itemid),
            "submitbutton": "Save and return to course",
        }
        payload.update(campo_visible(visible))
        return payload

    def urls_pluginfile(self, base_url, contexto, instance, nombre) -> list[str]:
        raiz = f"{base_url}/pluginfile.php/{contexto}/mod_page"
        return [f"{raiz}/content/{instance}/{nombre}"]
