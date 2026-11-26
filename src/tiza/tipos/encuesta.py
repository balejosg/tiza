"""Encuesta anónima de Moodle (``mod_feedback``): preguntas, ajustes y publicación."""

from __future__ import annotations

import base64
import html as _html
import math
import re
from datetime import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .. import contenido, filtro
from ..contenido import Encuesta as EncuestaContenido
from ..contenido import ErrorContenido, Imagen, PreguntaEncuesta, numero_texto
from ..encuesta import items_del_documento, items_xml
from .base import (
    Contexto,
    ContextoPublicacion,
    Extras,
    FechaActividad,
    Tipo,
    campo_visible,
    deshacer_modulo,
    fechas_payload,
    formato_fecha,
    payload_finalizacion,
    verificar,
)

# Campos propios del frontmatter (las preguntas van dentro) y campos de fecha del
# formulario de Moodle («Abrir la encuesta» y «Cerrar la encuesta»).
CAMPOS_ENCUESTA = frozenset(
    {"preguntas", "respuestas", "mensaje_final", "abre", "cierra", "anonima"}
)
CAMPOS_FECHA = ("timeopen", "timeclose")

TIPOS_PREGUNTA = (
    "escala",
    "opcion",
    "texto",
    "texto_corto",
    "numero",
    "informacion",
)
NOMBRES_PREGUNTA = {
    "escala": "Escala",
    "opcion": "Opción",
    "texto": "Texto largo",
    "texto_corto": "Texto corto",
    "numero": "Número",
    "informacion": "Información",
}
_CAMPOS_PREGUNTA = {
    "escala": {"tipo", "enunciado", "opciones", "obligatoria"},
    "opcion": {"tipo", "enunciado", "opciones", "multiple", "desplegable", "obligatoria"},
    "texto": {"tipo", "enunciado", "obligatoria"},
    "texto_corto": {"tipo", "enunciado", "obligatoria"},
    "numero": {"tipo", "enunciado", "minimo", "maximo", "obligatoria"},
    "informacion": {"tipo", "texto"},
}
MAX_PREGUNTAS = 100
MIN_OPCIONES, MAX_OPCIONES = 2, 10
MAX_ENUNCIADO = 5000
MAX_OPCION = 255
SEPARADORES_DE_MOODLE = ("|", "####", ">>>>>", "<<<<<")


class Encuesta(Tipo):
    nombre = "encuesta"
    llano = "Encuesta anónima"
    modulo = "feedback"
    campos = CAMPOS_ENCUESTA
    finalizaciones = ("ninguna", "enviar")
    banderas = ("completionsubmit",)
    banderas_de_modo = {"enviar": "completionsubmit"}
    campos_fecha = CAMPOS_FECHA
    lee_formulario_al_actualizar = True  # para saber si Moodle ya congeló «varias respuestas»
    importable = False  # D8: una encuesta de una copia sigue sin admitirse

    def validar(self, datos: dict, ctx: Contexto) -> Extras:
        return Extras(encuesta=_validar_encuesta(datos, ctx))

    def fechas(self, doc) -> tuple[FechaActividad, ...]:
        encuesta = doc.encuesta
        return (
            FechaActividad("abre", encuesta.apertura if encuesta else None, "timeopen"),
            FechaActividad(
                "cierra",
                encuesta.cierre if encuesta else None,
                "timeclose",
                exige_clase=True,
            ),
        )

    def payload_solo_fechas(self, doc) -> dict[str, str]:
        return {
            "_qf__mod_feedback_mod_form": "1",
            "submitbutton2": "Save and return to course",
            **fechas_payload(self, doc),
        }

    def payload(self, doc, html, itemid, visible, *, itemid_paquete=None) -> dict:
        encuesta = doc.encuesta
        assert encuesta is not None
        payload = {
            "_qf__mod_feedback_mod_form": "1",
            "name": doc.nombre,
            "introeditor[text]": html,
            "introeditor[format]": "1",
            "introeditor[itemid]": str(itemid),
            "anonymous": "1",
            "multiple_submit": "1" if encuesta.respuestas == "varias" else "0",
            "page_after_submit_editor[text]": encuesta.mensaje_final_html,
            "page_after_submit_editor[format]": "1",
            "email_notification": "0",
            "autonumbering": "0",
            "publish_stats": "0",
            "submitbutton2": "Save and return to course",
        }
        payload.update(fechas_payload(self, doc))
        payload.update(payload_finalizacion(self, doc))
        payload.update(campo_visible(visible))
        return payload

    def publicar(self, p: ContextoPublicacion) -> tuple[int, str, dict]:
        """Crea o republica la encuesta sin borrar nunca sus respuestas.

        Las preguntas solo se reimportan si el aula muestra otras y Moodle no ha congelado
        «varias respuestas». Si no se puede saber si hay respuestas, se trata como que las hay.
        """
        from ..publicar import DETALLE_ENCUESTA_CON_RESPUESTAS, ErrorPublicacion

        doc = p.doc
        encuesta = doc.encuesta
        assert encuesta is not None
        payload = self.payload(doc, p.html, p.itemid, p.visible)

        if p.existente is None:
            cmid = p.moodle.crear(p.curso_id, p.seccion.id, self.nombre, payload)
            try:
                self._importar_y_verificar(p, cmid)
            except ErrorPublicacion as exc:
                deshacer_modulo(p.moodle, p.curso_id, cmid, exc)
                raise
            accion = "creada"
        else:
            cmid = p.existente.cmid
            estado = _estado_respuestas(p)
            if not _preguntas_iguales(doc, p.moodle.exportar_encuesta(cmid)):
                if estado["hay_respuestas"]:
                    raise ErrorPublicacion(
                        "ENCUESTA_CON_RESPUESTAS", DETALLE_ENCUESTA_CON_RESPUESTAS
                    )
                self._importar_y_verificar(p, cmid)
            elif estado["hay_respuestas"] and _cambia_el_numero_de_respuestas(doc, estado):
                raise ErrorPublicacion(
                    "ENCUESTA_CON_RESPUESTAS",
                    "La encuesta ya tiene respuestas y Moodle no deja cambiar cuántas veces "
                    "puede responder cada alumno. No se ha tocado nada.",
                )
            p.moodle.actualizar(cmid, payload)
            accion = "actualizada"

        try:
            info = verificar(p.moodle, self, doc, cmid)
            if not _preguntas_iguales(doc, p.moodle.exportar_encuesta(cmid)):
                raise ErrorPublicacion("VERIFICACION_ENCUESTA", doc.ruta.name)
            estado = info.get("multiple_submit") or {}
            if info.get("anonymous") != "1":
                raise ErrorPublicacion("VERIFICACION_ENCUESTA", doc.ruta.name)
            esperado = "1" if encuesta.respuestas == "varias" else "0"
            if estado.get("forma") == "select" and estado.get("valor") not in (None, esperado):
                raise ErrorPublicacion("VERIFICACION_ENCUESTA", doc.ruta.name)
        except ErrorPublicacion as exc:
            if p.existente is None:
                deshacer_modulo(p.moodle, p.curso_id, cmid, exc)
            else:
                exc.cmid = cmid
            raise
        return cmid, accion, info

    def _importar_y_verificar(self, p: ContextoPublicacion, cmid: int) -> None:
        """Importa las preguntas y sube las imágenes de sus etiquetas."""
        from ..publicar import ErrorPublicacion

        p.moodle.importar_encuesta(p.curso_id, cmid, items_xml(p.doc))
        ids = p.moodle.items_de_encuesta(cmid)
        encuesta = p.doc.encuesta
        assert encuesta is not None
        for posicion, pregunta in enumerate(encuesta.preguntas, 1):
            if pregunta.tipo != "informacion" or not pregunta.imagenes:
                continue
            if posicion > len(ids):
                raise ErrorPublicacion("ERROR_ENCUESTA_ITEMS", p.doc.ruta.name)
            p.moodle.imagen_de_etiqueta(
                p.curso_id, cmid, ids[posicion - 1], pregunta.html, pregunta.imagenes
            )

    def urls_pluginfile(self, base_url, contexto, instance, nombre) -> list[str]:
        # La descripción de una encuesta va en mod_feedback/intro (sin itemid).
        raiz = f"{base_url}/pluginfile.php/{contexto}/mod_feedback"
        return [f"{raiz}/intro/{nombre}", f"{raiz}/intro/0/{nombre}"]

    def metadatos_preview(self, doc) -> list[tuple[str, str]]:
        encuesta = doc.encuesta
        if encuesta is None:
            return []
        filas: list[tuple[str, str]] = [("Anónima", "sí")]
        filas.append(
            (
                "Respuestas",
                "varias por alumno" if encuesta.respuestas == "varias" else "una por alumno",
            )
        )
        if encuesta.apertura is not None:
            filas.append(("Abre", formato_fecha(encuesta.apertura)))
        if encuesta.cierre is not None:
            filas.append(("Cierra", formato_fecha(encuesta.cierre)))
        if encuesta.mensaje_final:
            filas.append(("Mensaje final", encuesta.mensaje_final))
        return filas

    def extra_preview(self, doc) -> str:
        if doc.encuesta is None:
            return ""
        partes = ["<hr>", "<h2>Preguntas de la encuesta</h2>", "<ol>"]
        for pregunta in doc.encuesta.preguntas:
            partes.append("<li>")
            partes.append(f"<p><strong>{_html.escape(NOMBRES_PREGUNTA[pregunta.tipo])}</strong>")
            if pregunta.tipo != "informacion" and pregunta.obligatoria:
                partes.append(" (obligatoria)")
            if pregunta.tipo == "opcion" and pregunta.multiple:
                partes.append(" (varias respuestas)")
            if pregunta.tipo == "opcion" and pregunta.desplegable:
                partes.append(" (desplegable)")
            if pregunta.tipo == "texto_corto":
                partes.append(" (una línea)")
            partes.append("</p>")
            if pregunta.tipo == "informacion":
                partes.append(f"<div>{_imagenes_en_linea(pregunta.html, pregunta.imagenes)}</div>")
            else:
                partes.append(f"<p>{_html.escape(pregunta.enunciado)}</p>")
                if pregunta.tipo == "escala":
                    partes.append("<ol>")
                    for opcion in pregunta.opciones:
                        partes.append(f"<li>{_html.escape(opcion)}</li>")
                    partes.append("</ol>")
                elif pregunta.tipo == "opcion":
                    marca = "casillas" if pregunta.multiple else "una"
                    if pregunta.desplegable:
                        marca = "desplegable"
                    partes.append(f"<ul><li>Opciones ({marca}): ")
                    partes.append(", ".join(_html.escape(opcion) for opcion in pregunta.opciones))
                    partes.append("</li></ul>")
                elif pregunta.tipo == "numero" and (
                    pregunta.minimo is not None or pregunta.maximo is not None
                ):
                    minimo = numero_texto(pregunta.minimo) if pregunta.minimo is not None else ""
                    maximo = numero_texto(pregunta.maximo) if pregunta.maximo is not None else ""
                    partes.append(f"<p>Entre {minimo} y {maximo}</p>")
            partes.append("</li>")
        partes.append("</ol>")
        return "\n".join(partes)

    def hash_contenido(self, doc, resumen) -> None:
        if doc.encuesta is None:
            return
        resumen.update(b"\n--encuesta-preguntas--\n")
        resumen.update(repr(doc.encuesta.preguntas).encode("utf-8"))

    def hash_extra(self, doc, resumen) -> None:
        if doc.encuesta is None:
            return
        encuesta = doc.encuesta
        resumen.update(b"\n--encuesta-ajustes--\n")
        resumen.update(
            repr(
                (
                    encuesta.respuestas,
                    encuesta.mensaje_final,
                    encuesta.apertura,
                    encuesta.cierre,
                )
            ).encode("utf-8")
        )

    def extras_resumen(self, doc) -> dict:
        encuesta = doc.encuesta
        if encuesta is None:
            return {}
        return {
            "encuesta_anonima": True,
            "encuesta_preguntas": len(encuesta.preguntas),
            "encuesta_finalizacion": doc.finalizacion.modo if doc.finalizacion else None,
        }

    def detalle(self, doc) -> str | None:
        if doc.encuesta is None:
            return None
        return f"{len(doc.encuesta.preguntas)} preguntas"


# --------------------------------------------------------------------------- #
# Validación de la encuesta y de sus preguntas
# --------------------------------------------------------------------------- #


def _validar_encuesta(datos: dict[str, Any], ctx: Contexto) -> EncuestaContenido:
    if "anonima" in datos:
        raise ErrorContenido(
            "CAMPO_NO_PERMITIDO",
            "«anonima» no se admite: las encuestas de tiza son siempre anónimas. "
            "Si necesitas saber quién responde, usa una tarea",
        )
    respuestas = datos.get("respuestas", "una")
    if respuestas not in ("una", "varias"):
        raise ErrorContenido("AJUSTE_INVALIDO", "«respuestas» debe ser «una» o «varias»")

    mensaje = datos.get("mensaje_final", "")
    if not isinstance(mensaje, str):
        raise ErrorContenido("AJUSTE_INVALIDO", "«mensaje_final» debe ser texto")
    externos: list[str] = []
    incrustados: list[str] = []
    imagenes = _Imagenes()
    mensaje_html = ""
    if mensaje.strip():
        mensaje_html, _usadas = _html_de_campo(
            ctx,
            mensaje,
            "el mensaje final",
            permitir_imagenes=False,
            externos=externos,
            incrustados=incrustados,
            imagenes=imagenes,
        )

    apertura = ctx.fecha(datos["abre"], time(0, 0)) if datos.get("abre") is not None else None
    cierre = ctx.fecha(datos["cierra"], time(23, 59)) if datos.get("cierra") is not None else None
    if apertura is not None and cierre is not None and not apertura < cierre:
        raise ErrorContenido("FECHAS_INCOHERENTES", "debe cumplirse abre < cierra")

    valor_preguntas = datos.get("preguntas")
    if not isinstance(valor_preguntas, list) or not 1 <= len(valor_preguntas) <= MAX_PREGUNTAS:
        raise ErrorContenido(
            "PREGUNTAS_INVALIDAS",
            f"«preguntas» debe ser una lista de 1 a {MAX_PREGUNTAS} preguntas",
        )
    preguntas = tuple(
        _validar_pregunta(pregunta, numero, ctx, externos, incrustados, imagenes)
        for numero, pregunta in enumerate(valor_preguntas, 1)
    )
    return EncuestaContenido(
        preguntas=preguntas,
        respuestas=respuestas,
        mensaje_final=mensaje,
        mensaje_final_html=mensaje_html,
        apertura=apertura,
        cierre=cierre,
        externos=tuple(externos),
        incrustados=tuple(incrustados),
        imagenes=tuple(imagenes.por_nombre.values()),
    )


def _validar_pregunta(
    valor: Any,
    numero: int,
    ctx: Contexto,
    externos: list[str],
    incrustados: list[str],
    imagenes: _Imagenes,
) -> PreguntaEncuesta:
    donde = f"pregunta {numero}"
    if not isinstance(valor, dict):
        raise ErrorContenido("PREGUNTAS_INVALIDAS", f"{donde}: cada pregunta debe ser un mapa")

    tipo = valor.get("tipo")
    if tipo not in TIPOS_PREGUNTA:
        raise ErrorContenido(
            "TIPO_PREGUNTA_INVALIDO",
            f"{donde}: «tipo» debe ser uno de: {', '.join(TIPOS_PREGUNTA)}",
        )
    for campo in valor:
        if campo not in _CAMPOS_PREGUNTA[tipo]:
            linea = contenido.linea_de_campo(ctx.ruta, ("preguntas", numero - 1, campo))
            donde_linea = f" (línea {linea})" if linea is not None else ""
            raise ErrorContenido(
                "CAMPO_NO_PERMITIDO",
                f"{donde}: campo «{campo}» no permitido en «{tipo}»{donde_linea}",
            )

    if tipo == "informacion":
        texto = valor.get("texto")
        if not isinstance(texto, str) or not texto.strip() or len(texto) > MAX_ENUNCIADO:
            raise ErrorContenido(
                "ENUNCIADO_INVALIDO",
                f"{donde}: el texto debe ser texto de 1 a {MAX_ENUNCIADO} caracteres",
            )
        html, usadas = _html_de_campo(
            ctx,
            texto,
            donde,
            permitir_imagenes=True,
            externos=externos,
            incrustados=incrustados,
            imagenes=imagenes,
        )
        return PreguntaEncuesta(tipo=tipo, html=html, imagenes=usadas)

    enunciado = _enunciado_plano(valor.get("enunciado"), donde)
    obligatoria = valor.get("obligatoria")
    if obligatoria is None:
        obligatoria = False
    elif not isinstance(obligatoria, bool):
        raise ErrorContenido("PREGUNTAS_INVALIDAS", f"{donde}: «obligatoria» debe ser true o false")

    if tipo == "escala":
        opciones = _opciones(valor.get("opciones"), donde)
        return PreguntaEncuesta(
            tipo=tipo, enunciado=enunciado, opciones=opciones, obligatoria=obligatoria
        )
    if tipo == "opcion":
        opciones = _opciones(valor.get("opciones"), donde)
        multiple = _bool(valor.get("multiple"), "multiple", donde)
        desplegable = _bool(valor.get("desplegable"), "desplegable", donde)
        if multiple and desplegable:
            raise ErrorContenido(
                "AJUSTE_INVALIDO", f"{donde}: «multiple» y «desplegable» no pueden ir juntos"
            )
        return PreguntaEncuesta(
            tipo=tipo,
            enunciado=enunciado,
            opciones=opciones,
            multiple=multiple,
            desplegable=desplegable,
            obligatoria=obligatoria,
        )
    if tipo == "numero":
        minimo = _limite(valor.get("minimo"), "minimo", donde)
        maximo = _limite(valor.get("maximo"), "maximo", donde)
        if minimo is not None and maximo is not None and not minimo < maximo:
            raise ErrorContenido(
                "NUMERO_INVALIDO", f"{donde}: «minimo» tiene que ser menor que «maximo»"
            )
        return PreguntaEncuesta(
            tipo=tipo,
            enunciado=enunciado,
            minimo=minimo,
            maximo=maximo,
            obligatoria=obligatoria,
        )
    return PreguntaEncuesta(tipo=tipo, enunciado=enunciado, obligatoria=obligatoria)


def _enunciado_plano(valor: Any, donde: str) -> str:
    """El enunciado de una pregunta es texto plano: Moodle no le da formato HTML."""
    if not isinstance(valor, str) or not valor.strip() or len(valor) > MAX_ENUNCIADO:
        raise ErrorContenido(
            "ENUNCIADO_INVALIDO",
            f"{donde}: el enunciado debe ser texto de 1 a {MAX_ENUNCIADO} caracteres",
        )
    texto = valor.strip()
    if "![" in texto:
        raise ErrorContenido(
            "RECURSO_EN_PREGUNTA",
            f"{donde}: solo «informacion» admite imágenes; los demás enunciados son texto plano",
        )
    if re.search(r"[<>]", texto) or filtro.CONTROL.search(texto):
        raise ErrorContenido(
            "ENUNCIADO_INVALIDO",
            f"{donde}: el enunciado es texto plano, sin HTML ni símbolos < > ni saltos de línea",
        )
    return texto


def _bool(valor: Any, campo: str, donde: str) -> bool:
    if valor is None:
        return False
    if not isinstance(valor, bool):
        raise ErrorContenido("AJUSTE_INVALIDO", f"{donde}: «{campo}» debe ser true o false")
    return valor


def _opciones(valor: Any, donde: str) -> tuple[str, ...]:
    if not isinstance(valor, list) or not MIN_OPCIONES <= len(valor) <= MAX_OPCIONES:
        raise ErrorContenido(
            "OPCIONES_INVALIDAS",
            f"{donde}: «opciones» debe ser una lista de {MIN_OPCIONES} a {MAX_OPCIONES}",
        )
    return tuple(
        _opcion(opcion, f"{donde}, opción {numero}") for numero, opcion in enumerate(valor, 1)
    )


def _opcion(valor: Any, donde: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorContenido("OPCIONES_INVALIDAS", f"{donde}: no puede estar vacía")
    texto = valor.strip()
    if len(texto) > MAX_OPCION:
        raise ErrorContenido("OPCIONES_INVALIDAS", f"{donde}: pasa de {MAX_OPCION} caracteres")
    if any(separador in texto for separador in SEPARADORES_DE_MOODLE):
        raise ErrorContenido(
            "OPCION_CON_SEPARADOR",
            f"{donde}: no puede llevar «|», «####», «>>>>>» ni «<<<<<» "
            "(Moodle los usa como separadores)",
        )
    if re.search(r"[<>]", texto) or filtro.CONTROL.search(texto):
        raise ErrorContenido(
            "OPCIONES_INVALIDAS",
            f"{donde}: es texto plano, sin HTML ni símbolos < > ni saltos de línea",
        )
    return texto


def _limite(valor: Any, campo: str, donde: str) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ErrorContenido("NUMERO_INVALIDO", f"{donde}: «{campo}» debe ser un número")
    return float(valor)


class _Imagenes:
    """Las imágenes de las etiquetas, sin repetir, y los bytes que ocuparán."""

    def __init__(self) -> None:
        self.por_nombre: dict[str, Imagen] = {}
        self.bytes_usados = 0

    def anadir(self, imagen: Imagen, donde: str) -> None:
        if imagen.nombre in self.por_nombre:
            return
        self.por_nombre[imagen.nombre] = imagen
        self.bytes_usados += len(imagen.datos)
        if self.bytes_usados > contenido.MAX_IMAGENES_CUESTIONARIO_BYTES:
            raise ErrorContenido(
                "IMAGEN_DEMASIADO_GRANDE",
                f"{donde}: las imágenes de la encuesta pasan de "
                f"{contenido.MAX_IMAGENES_CUESTIONARIO_BYTES // 2**20} MB en total",
            )


def _html_de_campo(
    ctx: Contexto,
    texto: str,
    donde: str,
    *,
    permitir_imagenes: bool,
    externos: list[str],
    incrustados: list[str],
    imagenes: _Imagenes,
) -> tuple[str, tuple[Imagen, ...]]:
    """Renderiza un campo de la encuesta y lo pasa por el filtro.

    Las imágenes locales solo se admiten en «informacion»; su ``src`` pasa a
    ``@@PLUGINFILE@@/<nombre>``. Cualquier otro fichero local es un error.
    """
    try:
        analisis = filtro.analizar(ctx.render(texto))
    except filtro.HtmlPeligroso as exc:
        raise ErrorContenido("HTML_PELIGROSO", f"{donde}: {exc.detalle}") from None
    locales = set(analisis.locales)
    for enlace in analisis.cuerpo.find_all("a"):
        if enlace.get("href") in locales:
            nombre = Path(unquote(urlsplit(str(enlace.get("href"))).path)).name
            raise ErrorContenido(
                "RECURSO_EN_PREGUNTA",
                f"{donde}: un enlace a un fichero local («{nombre}») no se admite en una encuesta",
            )
    usadas: list[Imagen] = []
    for etiqueta in analisis.cuerpo.find_all("img"):
        valor = etiqueta.get("src")
        if valor not in locales:
            continue
        if not permitir_imagenes:
            raise ErrorContenido(
                "RECURSO_EN_PREGUNTA",
                f"{donde}: solo «informacion» admite imágenes locales; "
                "los demás textos son texto plano",
            )
        if not str(etiqueta.get("alt") or "").strip():
            raise ErrorContenido(
                "IMAGEN_SIN_ALT", f"{donde}: la imagen «{valor}» necesita texto alternativo"
            )
        if ctx.ruta is None:
            raise ErrorContenido("RECURSO_EN_PREGUNTA", f"{donde}: imagen local sin documento")
        try:
            imagen = contenido.leer_imagen(str(valor), ctx.ruta.parent, ctx.raiz)
        except ErrorContenido as exc:
            raise ErrorContenido(exc.codigo, f"{donde}: {exc.detalle}") from None
        imagenes.anadir(imagen, donde)
        etiqueta["src"] = f"@@PLUGINFILE@@/{imagen.nombre}"
        usadas.append(imagen)
    for url in analisis.externos:
        if url not in externos:
            externos.append(url)
    for url in analisis.incrustados:
        if url not in incrustados:
            incrustados.append(url)
    return filtro.serializar(analisis.cuerpo), tuple(usadas)


_REF_IMAGEN = re.compile(re.escape("@@PLUGINFILE@@/") + r"([^\s\"'<>]+)")


def _imagenes_en_linea(html: str, imagenes: tuple[Imagen, ...]) -> str:
    """Las imágenes de la vista previa como ``data:`` (la vista no carga nada de fuera)."""
    por_nombre = {imagen.nombre: imagen for imagen in imagenes}

    def reemplazo(m: re.Match[str]) -> str:
        imagen = por_nombre.get(m.group(1))
        if imagen is None:
            return m.group(0)
        return f"data:{imagen.mime};base64,{base64.b64encode(imagen.datos).decode('ascii')}"

    return _REF_IMAGEN.sub(reemplazo, html)


# --------------------------------------------------------------------------- #
# Comparación con lo que hay en el aula
# --------------------------------------------------------------------------- #


def _estado_respuestas(p: ContextoPublicacion) -> dict[str, Any]:
    """(hay_respuestas, valor de «varias respuestas») sin gastar otra petición.

    Usa el formulario de ajustes que ya cargó la publicación; si no está, lo pide.
    Ante cualquier duda, hay respuestas.
    """
    estado = (p.leido or {}).get("multiple_submit")
    if not isinstance(estado, dict):
        assert p.existente is not None
        try:
            estado = p.moodle.leer_modulo(p.existente.cmid).get("multiple_submit")
        except Exception:  # noqa: BLE001 - no poder saberlo cuenta como «con respuestas»
            estado = None
    if not isinstance(estado, dict):
        return {"hay_respuestas": True, "valor": None, "forma": "desconocida"}
    forma = estado.get("forma")
    return {
        "hay_respuestas": forma != "select",
        "valor": estado.get("valor"),
        "forma": forma,
    }


def _cambia_el_numero_de_respuestas(doc, estado: dict[str, Any]) -> bool:
    """Solo se puede afirmar si el formulario dio el valor actual."""
    actual = estado.get("valor")
    if actual not in ("0", "1"):
        return False
    esperado = "1" if doc.encuesta.respuestas == "varias" else "0"
    return actual != esperado


def _preguntas_iguales(doc, leidas: list[dict]) -> bool:
    encuesta = doc.encuesta
    if encuesta is None:
        return False
    esperadas = items_del_documento(doc)
    if len(leidas) != len(esperadas):
        return False
    for esperada, leida in zip(esperadas, leidas, strict=True):
        for campo in ("tipo", "texto", "presentacion", "opciones"):
            if _normalizar(esperada[campo]) != _normalizar(leida.get(campo)):
                return False
        if bool(esperada["obligatoria"]) != bool(leida.get("obligatoria")):
            return False
    return True


def _normalizar(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()
