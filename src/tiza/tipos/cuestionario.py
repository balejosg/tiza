"""Cuestionario de Moodle (``mod_quiz``): ajustes, preguntas y fechas."""

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
from ..contenido import ErrorContenido, numero_texto
from ..cuestionario import preguntas_xml
from .base import (
    Contexto,
    ContextoPublicacion,
    Extras,
    FechaActividad,
    Tipo,
    borrar_nuevas,
    campo_visible,
    deshacer_modulo,
    fechas_payload,
    formato_fecha,
    importar_preguntas,
    verificar,
)

# Campos propios del frontmatter (las preguntas van dentro) y campos de fecha del
# formulario de Moodle («Abrir el cuestionario» y «Cerrar el cuestionario»).
CAMPOS_CUESTIONARIO = frozenset(
    {"apertura", "cierre", "tiempo_limite", "intentos", "mezclar_respuestas", "preguntas"}
)
CAMPOS_FECHA = ("timeopen", "timeclose")

TIPOS_PREGUNTA = (
    "opcion_multiple",
    "verdadero_falso",
    "respuesta_corta",
    "numerica",
    "emparejamiento",
)
NOMBRES_PREGUNTA = {
    "opcion_multiple": "Opción múltiple",
    "verdadero_falso": "Verdadero o falso",
    "respuesta_corta": "Respuesta corta",
    "numerica": "Numérica",
    "emparejamiento": "Emparejamiento",
}
_CAMPOS_PREGUNTA_BASE = {"tipo", "enunciado", "retro"}
_CAMPOS_PREGUNTA = {
    "opcion_multiple": _CAMPOS_PREGUNTA_BASE | {"opciones"},
    "verdadero_falso": _CAMPOS_PREGUNTA_BASE | {"respuesta"},
    "respuesta_corta": _CAMPOS_PREGUNTA_BASE | {"aceptadas", "mayusculas"},
    "numerica": _CAMPOS_PREGUNTA_BASE | {"valor", "tolerancia"},
    "emparejamiento": _CAMPOS_PREGUNTA_BASE | {"parejas", "distractores"},
}
_CAMPOS_PAREJA = {"pregunta", "respuesta"}
MIN_PAREJAS, MAX_PAREJAS, MAX_DISTRACTORES = 2, 10, 10
MIN_RESPUESTAS_DISTINTAS = 3  # lo que exige el formulario de Moodle al editar
MAX_RESPUESTA = 255
_CAMPOS_OPCION = {"texto", "correcta", "retro"}
MAX_PREGUNTAS = 100
MAX_ENUNCIADO = 5000


class Cuestionario(Tipo):
    nombre = "cuestionario"
    llano = "Cuestionario"
    modulo = "quiz"
    campos = CAMPOS_CUESTIONARIO
    finalizaciones = ("ninguna", "manual", "ver", "calificar")
    banderas = ("completionview", "completionusegrade")
    campos_fecha = CAMPOS_FECHA

    def validar(self, datos: dict, ctx: Contexto) -> Extras:
        return Extras(cuestionario=_validar_cuestionario(datos, ctx))

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

    def payload(self, doc, html, itemid, visible, *, itemid_paquete=None) -> dict:
        cuestionario = doc.cuestionario
        assert cuestionario is not None
        payload = {
            "_qf__mod_quiz_mod_form": "1",
            "name": doc.nombre,
            "introeditor[text]": html,
            "introeditor[format]": "1",
            "introeditor[itemid]": str(itemid),
            "submitbutton2": "Save and return to course",
        }
        payload.update(fechas_payload(self, doc))
        if cuestionario.tiempo_limite is not None:
            payload["timelimit[enabled]"] = "1"
            payload["timelimit[number]"] = str(cuestionario.tiempo_limite)
            payload["timelimit[timeunit]"] = "60"  # minutos
        else:
            payload["timelimit[enabled]"] = "0"
        # En Moodle, 0 intentos es «ilimitados».
        payload["attempts"] = "0" if cuestionario.intentos == 0 else str(cuestionario.intentos)
        payload["shuffleanswers"] = "1" if cuestionario.mezclar_respuestas else "0"
        payload.update(campo_visible(visible))
        return payload

    def publicar(self, p: ContextoPublicacion) -> tuple[int, str, dict]:
        """Crea o republica un cuestionario con sus preguntas.

        Lo nuevo se crea con sus preguntas y, si algo falla después de crear el
        módulo, se borra entero (se lleva sus preguntas). En uno existente se añade
        antes de quitar para que un fallo no lo deje vacío.
        """
        from ..publicar import DETALLE_INTENTOS, ErrorPublicacion

        doc = p.doc
        cuestionario = doc.cuestionario
        assert cuestionario is not None
        cuantas = len(cuestionario.preguntas)
        payload = self.payload(doc, p.html, p.itemid, p.visible)
        xml = preguntas_xml(doc)
        nuevas: list[int] = []

        if p.existente is None:
            cmid = p.moodle.crear(p.curso_id, p.seccion["id"], self.nombre, payload)
            try:
                categoria = p.moodle.categoria_cuestionario(cmid)
                nuevas = importar_preguntas(p.moodle, p.curso_id, cmid, categoria, xml, cuantas)
                p.moodle.anadir_preguntas(cmid, nuevas)
            except ErrorPublicacion as exc:
                deshacer_modulo(p.moodle, p.curso_id, cmid, exc)
                raise
            accion = "creada"
        else:
            cmid = p.existente["cmid"]
            if p.moodle.tiene_intentos(cmid):
                raise ErrorPublicacion("CUESTIONARIO_CON_INTENTOS", DETALLE_INTENTOS)
            categoria = p.moodle.categoria_cuestionario(cmid)
            # Lo que hay ahora: sus huecos y las preguntas de su banco.
            viejos = p.moodle.huecos(cmid)
            viejas = p.moodle.preguntas_en_categoria(cmid, categoria)
            try:
                nuevas = importar_preguntas(p.moodle, p.curso_id, cmid, categoria, xml, cuantas)
            except ErrorPublicacion:
                # La republicación no ha cambiado nada: fuera las nuevas a medias.
                borrar_nuevas(p.moodle, cmid, nuevas)
                raise
            try:
                p.moodle.anadir_preguntas(cmid, nuevas)
            except ErrorPublicacion:
                borrar_nuevas(p.moodle, cmid, nuevas)
                raise
            quizid = p.moodle.leer_modulo(cmid).get("instance")
            if not isinstance(quizid, int):
                raise ErrorPublicacion("ERROR_QUITAR_PREGUNTAS")
            for hueco, _pregunta in viejos:
                p.moodle.quitar_hueco(p.curso_id, quizid, hueco)
            p.moodle.borrar_preguntas(cmid, sorted(viejas))
            p.moodle.actualizar(cmid, payload)
            accion = "actualizada"

        try:
            info = verificar(p.moodle, self, doc, cmid, preguntas=nuevas)
            _verificar_imagenes(p.moodle, doc, cmid, nuevas)
        except ErrorPublicacion as exc:
            if p.existente is None:
                deshacer_modulo(p.moodle, p.curso_id, cmid, exc)
            else:
                exc.cmid = cmid
            raise
        return cmid, accion, info

    def urls_pluginfile(self, base_url, contexto, instance, nombre) -> list[str]:
        # La descripción de un cuestionario va en mod_quiz/intro (sin itemid).
        raiz = f"{base_url}/pluginfile.php/{contexto}/mod_quiz"
        return [f"{raiz}/intro/{nombre}", f"{raiz}/intro/0/{nombre}"]

    def metadatos_preview(self, doc) -> list[tuple[str, str]]:
        cuestionario = doc.cuestionario
        if cuestionario is None:
            return []
        filas: list[tuple[str, str]] = []
        if cuestionario.apertura is not None:
            filas.append(("Apertura", formato_fecha(cuestionario.apertura)))
        if cuestionario.cierre is not None:
            filas.append(("Cierre", formato_fecha(cuestionario.cierre)))
        if cuestionario.tiempo_limite is not None:
            filas.append(("Tiempo límite", f"{cuestionario.tiempo_limite} minutos"))
        filas.append(
            ("Intentos", "ilimitados" if cuestionario.intentos == 0 else str(cuestionario.intentos))
        )
        filas.append(("Mezclar respuestas", "sí" if cuestionario.mezclar_respuestas else "no"))
        return filas

    def extra_preview(self, doc) -> str:
        """Las preguntas, numeradas y con las correctas marcadas."""
        if doc.cuestionario is None:
            return ""
        imagenes = {imagen.nombre: imagen for imagen in doc.cuestionario.imagenes}

        def c(html: str | None) -> str | None:
            return _imagenes_en_linea(html, imagenes)

        partes = ["<hr>", "<h2>Preguntas del cuestionario</h2>", "<ol>"]
        for pregunta in doc.cuestionario.preguntas:
            tipo = NOMBRES_PREGUNTA.get(pregunta.tipo, pregunta.tipo)
            partes.append(f"<li><p><strong>{_html.escape(tipo)}</strong></p>")
            partes.append(f"<div>{c(pregunta.html)}</div>")
            if pregunta.opciones:
                partes.append("<ul>")
                for opcion in pregunta.opciones:
                    marca = " <strong>(correcta)</strong>" if opcion.correcta else ""
                    partes.append(
                        f"<li>{c(opcion.html)}{marca}{_retro_preview(c(opcion.retro_html))}</li>"
                    )
                partes.append("</ul>")
            elif pregunta.tipo == "emparejamiento":
                partes.append("<table><tr><th>Pregunta</th><th>Respuesta correcta</th></tr>")
                for pareja in pregunta.parejas:
                    partes.append(
                        f"<tr><td>{c(pareja.html)}</td><td>{_html.escape(pareja.respuesta)}</td></tr>"
                    )
                partes.append("</table>")
                if pregunta.distractores:
                    sobrantes = ", ".join(_html.escape(d) for d in pregunta.distractores)
                    partes.append(
                        f"<p>Distractores (no son de nadie): <strong>{sobrantes}</strong></p>"
                    )
            elif pregunta.tipo == "verdadero_falso":
                respuesta = "Verdadero" if pregunta.respuesta == "verdadero" else "Falso"
                partes.append(f"<p>Respuesta correcta: <strong>{respuesta}</strong></p>")
            elif pregunta.tipo == "respuesta_corta":
                aceptadas = ", ".join(_html.escape(a) for a in pregunta.aceptadas)
                partes.append(f"<p>Respuestas válidas: <strong>{aceptadas}</strong></p>")
            elif pregunta.tipo == "numerica" and pregunta.valor is not None:
                partes.append(
                    f"<p>Valor: <strong>{_html.escape(numero_texto(pregunta.valor))}</strong>"
                )
                if pregunta.tolerancia:
                    partes[-1] += (
                        f" (tolerancia ±{_html.escape(numero_texto(pregunta.tolerancia))})"
                    )
                partes[-1] += "</p>"
            partes.append(_retro_preview(c(pregunta.retro_html)))
            partes.append("</li>")
        partes.append("</ol>")
        return "\n".join(partes)

    def hash_contenido(self, doc, resumen) -> None:
        if doc.cuestionario is None:
            return
        resumen.update(b"\n--cuestionario--\n")
        resumen.update(repr(doc.cuestionario).encode("utf-8"))

    def extras_resumen(self, doc) -> dict:
        if doc.cuestionario is None or not doc.cuestionario.imagenes:
            return {}
        return {"imagenes_preguntas": len(doc.cuestionario.imagenes)}

    def detalle(self, doc) -> str | None:
        if doc.cuestionario is None:
            return None
        return f"{len(doc.cuestionario.preguntas)} preguntas"


def _imagenes_en_linea(html: str | None, imagenes: dict[str, contenido.Imagen]) -> str | None:
    """Las imágenes de las preguntas como ``data:`` en la vista previa (que no carga nada de fuera)."""
    if html is None:
        return None

    def reemplazo(m: re.Match[str]) -> str:
        imagen = imagenes[m.group(1)]
        return f"data:{imagen.mime};base64,{base64.b64encode(imagen.datos).decode('ascii')}"

    return _REF_IMAGEN.sub(reemplazo, html)


_REF_IMAGEN = re.compile(re.escape(contenido.PREFIJO_IMAGEN) + r"(img-[0-9a-f]{16}\.[a-z]+)")


def imagenes_visibles(pregunta) -> int:
    """Imágenes que enseña la vista previa de la pregunta: enunciado, opciones y parejas."""
    marca = contenido.PREFIJO_IMAGEN
    total = pregunta.html.count(marca)
    total += sum(opcion.html.count(marca) for opcion in pregunta.opciones)
    total += sum(pareja.html.count(marca) for pareja in pregunta.parejas)
    return total


def _verificar_imagenes(moodle, doc, cmid: int, nuevas: list[int]) -> None:
    """Que el aula guardó y sirve las imágenes de cada pregunta (sin crear un intento)."""
    from ..publicar import ErrorPublicacion

    for pregunta, identificador in zip(doc.cuestionario.preguntas, nuevas, strict=True):
        esperadas = imagenes_visibles(pregunta)
        if not esperadas:
            continue
        encontradas, servidas = moodle.imagenes_de_pregunta(cmid, identificador)
        if encontradas != esperadas or servidas != encontradas:
            raise ErrorPublicacion("VERIFICACION_IMAGENES", doc.ruta.name)


def _retro_preview(retro_html: str | None) -> str:
    """La retroalimentación como bloque: su HTML ya trae párrafos y no cabe en un <p>."""
    if retro_html is None:
        return ""
    return f"<div><p><em>Retroalimentación:</em></p>{retro_html}</div>"


def _tomar_imagenes(ctx: Contexto, analisis, donde: str, imagenes: _Imagenes) -> None:
    locales = set(analisis.locales)
    for enlace in analisis.cuerpo.find_all("a"):
        if enlace.get("href") in locales:
            nombre = Path(unquote(urlsplit(str(enlace.get("href"))).path)).name
            raise ErrorContenido(
                "RECURSO_EN_PREGUNTA",
                f"{donde}: un enlace a un fichero local («{nombre}») no se admite en una pregunta",
            )
    for etiqueta in analisis.cuerpo.find_all("img"):
        valor = etiqueta.get("src")
        if valor not in locales:
            continue
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
        imagenes.por_nombre.setdefault(imagen.nombre, imagen)
        imagenes.bytes_usados += len(imagen.datos)
        if imagenes.bytes_usados > contenido.MAX_IMAGENES_CUESTIONARIO_BYTES:
            raise ErrorContenido(
                "IMAGEN_DEMASIADO_GRANDE",
                f"{donde}: las imágenes del cuestionario pasan de "
                f"{contenido.MAX_IMAGENES_CUESTIONARIO_BYTES // 2**20} MB en total",
            )
        etiqueta["src"] = f"{contenido.PREFIJO_IMAGEN}{imagen.nombre}"


# --------------------------------------------------------------------------- #
# Validación del cuestionario, sus preguntas y sus opciones
# --------------------------------------------------------------------------- #


def _validar_cuestionario(datos: dict[str, Any], ctx: Contexto) -> contenido.Cuestionario:
    apertura = (
        ctx.fecha(datos["apertura"], time(0, 0)) if datos.get("apertura") is not None else None
    )
    cierre = ctx.fecha(datos["cierre"], time(23, 59)) if datos.get("cierre") is not None else None
    if apertura is not None and cierre is not None and not apertura < cierre:
        raise ErrorContenido("FECHAS_INCOHERENTES", "debe cumplirse apertura < cierre")

    tiempo_limite = datos.get("tiempo_limite")
    if tiempo_limite is not None and (
        isinstance(tiempo_limite, bool)
        or not isinstance(tiempo_limite, int)
        or not 1 <= tiempo_limite <= 600
    ):
        raise ErrorContenido(
            "AJUSTE_INVALIDO", "«tiempo_limite» debe ser un número entero entre 1 y 600 (minutos)"
        )

    intentos = _leer_intentos(datos.get("intentos"))
    mezclar = datos.get("mezclar_respuestas")
    if mezclar is None:
        mezclar = True
    elif not isinstance(mezclar, bool):
        raise ErrorContenido("AJUSTE_INVALIDO", "«mezclar_respuestas» debe ser true o false")

    valor_preguntas = datos.get("preguntas")
    if not isinstance(valor_preguntas, list) or not 1 <= len(valor_preguntas) <= MAX_PREGUNTAS:
        raise ErrorContenido(
            "PREGUNTAS_INVALIDAS",
            f"«preguntas» debe ser una lista de 1 a {MAX_PREGUNTAS} preguntas",
        )

    externos: list[str] = []
    incrustados: list[str] = []
    imagenes = _Imagenes()
    preguntas = tuple(
        _validar_pregunta(pregunta, numero, ctx, externos, incrustados, imagenes)
        for numero, pregunta in enumerate(valor_preguntas, 1)
    )
    return contenido.Cuestionario(
        preguntas=preguntas,
        apertura=apertura,
        cierre=cierre,
        tiempo_limite=tiempo_limite,
        intentos=intentos,
        mezclar_respuestas=mezclar,
        externos=tuple(externos),
        incrustados=tuple(incrustados),
        imagenes=tuple(imagenes.por_nombre.values()),
    )


def _leer_intentos(valor: Any) -> int:
    if valor is None:
        return 1
    if isinstance(valor, str) and valor.strip().casefold() == "ilimitados":
        return 0
    if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= 10:
        raise ErrorContenido(
            "AJUSTE_INVALIDO", "«intentos» debe ser un número entero entre 1 y 10 o «ilimitados»"
        )
    return valor


def _validar_pregunta(
    valor: Any,
    numero: int,
    ctx: Contexto,
    externos: list[str],
    incrustados: list[str],
    imagenes: _Imagenes,
) -> contenido.Pregunta:
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
            raise ErrorContenido(
                "CAMPO_DESCONOCIDO", f"{donde}: campo «{campo}» no permitido en «{tipo}»"
            )

    enunciado = valor.get("enunciado")
    if not isinstance(enunciado, str) or not enunciado.strip() or len(enunciado) > MAX_ENUNCIADO:
        raise ErrorContenido(
            "ENUNCIADO_INVALIDO",
            f"{donde}: el enunciado debe ser texto de 1 a {MAX_ENUNCIADO} caracteres",
        )
    html = _html_de_campo(ctx, enunciado, donde, externos, incrustados, imagenes)

    retro = _texto_opcional(valor.get("retro"), donde, "retro")
    retro_html = (
        _html_de_campo(ctx, retro, donde, externos, incrustados, imagenes)
        if retro is not None
        else None
    )

    if tipo == "opcion_multiple":
        opciones = _validar_opciones(
            valor.get("opciones"), donde, ctx, externos, incrustados, imagenes
        )
        return contenido.Pregunta(
            tipo=tipo,
            enunciado=enunciado,
            html=html,
            opciones=opciones,
            retro=retro,
            retro_html=retro_html,
        )
    if tipo == "verdadero_falso":
        respuesta = valor.get("respuesta")
        if respuesta not in ("verdadero", "falso"):
            raise ErrorContenido(
                "RESPUESTA_PREGUNTA_INVALIDA", f"{donde}: «respuesta» debe ser verdadero o falso"
            )
        return contenido.Pregunta(
            tipo=tipo,
            enunciado=enunciado,
            html=html,
            respuesta=respuesta,
            retro=retro,
            retro_html=retro_html,
        )
    if tipo == "respuesta_corta":
        aceptadas = valor.get("aceptadas")
        if (
            not isinstance(aceptadas, list)
            or not aceptadas
            or any(not isinstance(a, str) or not a.strip() for a in aceptadas)
        ):
            raise ErrorContenido(
                "RESPUESTA_PREGUNTA_INVALIDA",
                f"{donde}: «aceptadas» debe ser una lista de respuestas no vacías",
            )
        mayusculas = valor.get("mayusculas")
        if mayusculas is not None and not isinstance(mayusculas, bool):
            raise ErrorContenido(
                "RESPUESTA_PREGUNTA_INVALIDA", f"{donde}: «mayusculas» debe ser true o false"
            )
        return contenido.Pregunta(
            tipo=tipo,
            enunciado=enunciado,
            html=html,
            aceptadas=tuple(a.strip() for a in aceptadas),
            mayusculas=bool(mayusculas),
            retro=retro,
            retro_html=retro_html,
        )
    if tipo == "emparejamiento":
        parejas = _validar_parejas(
            valor.get("parejas"), donde, ctx, externos, incrustados, imagenes
        )
        distractores = _validar_distractores(valor.get("distractores"), donde)
        if len({p.respuesta for p in parejas} | set(distractores)) < MIN_RESPUESTAS_DISTINTAS:
            raise ErrorContenido(
                "PAREJAS_INVALIDAS",
                f"{donde}: hacen falta al menos {MIN_RESPUESTAS_DISTINTAS} respuestas distintas "
                "(añade «distractores»)",
            )
        return contenido.Pregunta(
            tipo=tipo,
            enunciado=enunciado,
            html=html,
            retro=retro,
            retro_html=retro_html,
            parejas=parejas,
            distractores=distractores,
        )
    # numerica
    valor_num = valor.get("valor")
    if (
        isinstance(valor_num, bool)
        or not isinstance(valor_num, (int, float))
        or not math.isfinite(valor_num)
    ):
        raise ErrorContenido("RESPUESTA_PREGUNTA_INVALIDA", f"{donde}: «valor» debe ser un número")
    tolerancia = valor.get("tolerancia")
    if tolerancia is None:
        tolerancia = 0
    if (
        isinstance(tolerancia, bool)
        or not isinstance(tolerancia, (int, float))
        or not math.isfinite(tolerancia)
        or tolerancia < 0
    ):
        raise ErrorContenido(
            "RESPUESTA_PREGUNTA_INVALIDA",
            f"{donde}: «tolerancia» debe ser un número mayor o igual que 0",
        )
    return contenido.Pregunta(
        tipo=tipo,
        enunciado=enunciado,
        html=html,
        valor=float(valor_num),
        tolerancia=float(tolerancia),
        retro=retro,
        retro_html=retro_html,
    )


def _respuesta_plana(valor: Any, donde: str) -> str:
    """Una respuesta de emparejamiento: texto plano, que el aula muestra en un desplegable."""
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorContenido("PAREJAS_INVALIDAS", f"{donde}: la respuesta debe ser texto no vacío")
    limpio = valor.strip()
    if len(limpio) > MAX_RESPUESTA:
        raise ErrorContenido(
            "PAREJAS_INVALIDAS", f"{donde}: la respuesta pasa de {MAX_RESPUESTA} caracteres"
        )
    if re.search(r"[<>]", limpio) or filtro.CONTROL.search(limpio):
        raise ErrorContenido(
            "PAREJAS_INVALIDAS", f"{donde}: la respuesta es texto plano, sin HTML ni símbolos < >"
        )
    return limpio


def _validar_parejas(
    valor: Any,
    donde: str,
    ctx: Contexto,
    externos: list[str],
    incrustados: list[str],
    imagenes: _Imagenes,
) -> tuple[contenido.Pareja, ...]:
    if not isinstance(valor, list) or not MIN_PAREJAS <= len(valor) <= MAX_PAREJAS:
        raise ErrorContenido(
            "PAREJAS_INVALIDAS",
            f"{donde}: «parejas» debe ser una lista de {MIN_PAREJAS} a {MAX_PAREJAS}",
        )
    parejas: list[contenido.Pareja] = []
    for numero, pareja in enumerate(valor, 1):
        donde_pareja = f"{donde}, pareja {numero}"
        if not isinstance(pareja, dict):
            raise ErrorContenido("PAREJAS_INVALIDAS", f"{donde_pareja}: debe ser un mapa")
        for campo in pareja:
            if campo not in _CAMPOS_PAREJA:
                raise ErrorContenido(
                    "CAMPO_DESCONOCIDO", f"{donde_pareja}: campo «{campo}» no permitido"
                )
        pregunta = pareja.get("pregunta")
        if not isinstance(pregunta, str) or not pregunta.strip() or len(pregunta) > MAX_ENUNCIADO:
            raise ErrorContenido("PAREJAS_INVALIDAS", f"{donde_pareja}: falta «pregunta»")
        parejas.append(
            contenido.Pareja(
                pregunta=pregunta,
                html=_html_de_campo(ctx, pregunta, donde_pareja, externos, incrustados, imagenes),
                respuesta=_respuesta_plana(pareja.get("respuesta"), donde_pareja),
            )
        )
    return tuple(parejas)


def _validar_distractores(valor: Any, donde: str) -> tuple[str, ...]:
    if valor is None:
        return ()
    if not isinstance(valor, list) or len(valor) > MAX_DISTRACTORES:
        raise ErrorContenido(
            "PAREJAS_INVALIDAS",
            f"{donde}: «distractores» debe ser una lista de hasta {MAX_DISTRACTORES} textos",
        )
    return tuple(_respuesta_plana(d, f"{donde}, distractor {n}") for n, d in enumerate(valor, 1))


def _validar_opciones(
    valor: Any,
    donde: str,
    ctx: Contexto,
    externos: list[str],
    incrustados: list[str],
    imagenes: _Imagenes,
) -> tuple[contenido.Opcion, ...]:
    if not isinstance(valor, list) or not 2 <= len(valor) <= 10:
        raise ErrorContenido(
            "OPCIONES_INVALIDAS", f"{donde}: «opciones» debe ser una lista de 2 a 10"
        )
    opciones: list[contenido.Opcion] = []
    for numero, opcion in enumerate(valor, 1):
        donde_opcion = f"{donde}, opción {numero}"
        if not isinstance(opcion, dict):
            raise ErrorContenido("OPCIONES_INVALIDAS", f"{donde_opcion}: debe ser un mapa")
        for campo in opcion:
            if campo not in _CAMPOS_OPCION:
                raise ErrorContenido(
                    "CAMPO_DESCONOCIDO", f"{donde_opcion}: campo «{campo}» no permitido"
                )
        texto = opcion.get("texto")
        if not isinstance(texto, str) or not texto.strip():
            raise ErrorContenido("OPCIONES_INVALIDAS", f"{donde_opcion}: falta «texto»")
        correcta = opcion.get("correcta")
        if correcta is not None and not isinstance(correcta, bool):
            raise ErrorContenido(
                "OPCIONES_INVALIDAS", f"{donde_opcion}: «correcta» debe ser true o false"
            )
        retro = _texto_opcional(opcion.get("retro"), donde_opcion, "retro")
        opciones.append(
            contenido.Opcion(
                texto=texto,
                html=_html_de_campo(ctx, texto, donde_opcion, externos, incrustados, imagenes),
                correcta=bool(correcta),
                retro=retro,
                retro_html=(
                    _html_de_campo(ctx, retro, donde_opcion, externos, incrustados, imagenes)
                    if retro is not None
                    else None
                ),
            )
        )
    if not any(opcion.correcta for opcion in opciones):
        raise ErrorContenido(
            "OPCIONES_INVALIDAS", f"{donde}: ninguna opción está marcada como correcta"
        )
    return tuple(opciones)


def _texto_opcional(valor: Any, donde: str, campo: str) -> str | None:
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ErrorContenido("PREGUNTAS_INVALIDAS", f"{donde}: «{campo}» debe ser texto")
    return valor


class _Imagenes:
    """Las imágenes de las preguntas, sin repetir, y los bytes que ocuparán en el XML."""

    def __init__(self) -> None:
        self.por_nombre: dict[str, contenido.Imagen] = {}
        self.bytes_usados = 0


def _html_de_campo(
    ctx: Contexto,
    texto: str,
    donde: str,
    externos: list[str],
    incrustados: list[str],
    imagenes: _Imagenes,
) -> str:
    """Renderiza un campo Markdown de una pregunta y lo pasa por el filtro.

    Las imágenes locales (con texto alternativo) se sustituyen por ``tiza-imagen:<nombre>``;
    cualquier otro fichero local es un error.
    """
    try:
        analisis = filtro.analizar(ctx.render(texto))
    except filtro.HtmlPeligroso as exc:
        raise ErrorContenido("HTML_PELIGROSO", f"{donde}: {exc.detalle}") from None
    if analisis.locales:
        _tomar_imagenes(ctx, analisis, donde, imagenes)
    for url in analisis.externos:
        if url not in externos:
            externos.append(url)
    for url in analisis.incrustados:
        if url not in incrustados:
            incrustados.append(url)
    return filtro.serializar(analisis.cuerpo)
