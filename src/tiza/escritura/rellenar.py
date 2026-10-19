"""Aplica un ``Relleno`` sobre una copia de una plantilla Word (``tiza rellenar``). Offline.

La plantilla se lee una sola vez, con los límites de ``tiza leer``, y se comprueba su
``sha256``. Los ids se resuelven con el mismo recorrido que da los ids de la lectura
(``lectura.word``) y **todo** lo que depende de la plantilla se valida antes de tocar el XML:
si algo falla no se escribe nada. Después se aplican las operaciones en el orden del YAML
sobre los elementos ya resueltos (un ``duplicar_tabla`` copia la tabla tal y como esté en ese
momento) y el resultado se escribe en un fichero nuevo, sin sobrescribir nunca.

Se conservan los estilos, la numeración, los encabezados y pies y los controles de contenido:
solo se cambia el texto, y el texto nuevo toma el formato del que sustituye.
"""

from __future__ import annotations

import copy
import hashlib
import io
import os
import re
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from tiza.escritura import ErrorEscritura
from tiza.escritura.relleno import (
    EXTENSIONES_PLANTILLA,
    DuplicarTabla,
    Filas,
    InsertarDespues,
    Operacion,
    Reemplazar,
    Relleno,
    dentro_de_la_carpeta,
)
from tiza.escritura.word import escribir_sin_sobrescribir
from tiza.lectura.modelo import ErrorLectura
from tiza.lectura.word import analizar_docx, celdas_directas, leer_bytes_docx, mapa_de_tabla

__all__ = ["ResultadoRelleno", "rellenar"]

_P, _R, _T = qn("w:p"), qn("w:r"), qn("w:t")
_TBL, _TR, _TC = qn("w:tbl"), qn("w:tr"), qn("w:tc")
_PPR, _RPR, _TCPR, _SECT = qn("w:pPr"), qn("w:rPr"), qn("w:tcPr"), qn("w:sectPr")
_ESPACIO = "{http://www.w3.org/XML/1998/namespace}space"
_BORRADOS = (qn("w:del"), qn("w:moveFrom"))  # lo borrado con el control de cambios no cuenta
_NO_RECORRER = (_PPR, _RPR, qn("w:sdtPr"), qn("w:sdtEndPr"), *_BORRADOS)
_MARCAS_DE_CAMBIO = (
    qn("w:ins"),
    qn("w:del"),
    qn("w:moveFrom"),
    qn("w:moveTo"),
    qn("w:rPrChange"),
    qn("w:pPrChange"),
    qn("w:trPrChange"),
)
_NOMBRE_DE = {_P: "un párrafo", _TBL: "una tabla", _TR: "una fila", _TC: "una celda"}
_MAX_ESTILOS_EN_EL_ERROR = 40


@dataclass(frozen=True)
class ResultadoRelleno:
    """``salida``: el Word creado; ``operaciones``: las aplicadas; ``avisos``: códigos de aviso."""

    salida: Path
    operaciones: int
    avisos: tuple[str, ...]


# --- Texto y formato de un párrafo --------------------------------------------------------


def _runs(contenedor: Any, campo: list[int]) -> Iterator[tuple[Any, bool]]:
    """Los ``w:r`` y ``w:fldSimple`` de un párrafo en orden, y si están dentro de un campo."""
    for hijo in contenedor:
        if not isinstance(hijo.tag, str) or hijo.tag in _NO_RECORRER:
            continue
        if hijo.tag == _R:
            tipos = [f.get(qn("w:fldCharType")) for f in hijo.findall(qn("w:fldChar"))]
            if "begin" in tipos:
                campo[0] += 1
            dentro = campo[0] > 0
            if "end" in tipos and campo[0] > 0:
                campo[0] -= 1
            yield hijo, dentro
        elif hijo.tag == qn("w:fldSimple"):
            yield hijo, True
        else:  # hyperlink, sdt y su sdtContent, ins, smartTag…
            yield from _runs(hijo, campo)


@dataclass
class _Analisis:
    candidato: Any | None  # el primer run con texto fuera de los campos
    quitar: list[Any]  # los demás runs con texto y todos los campos
    en_campo: Any | None  # el primer run con texto dentro de un campo (para su formato)


def _analizar(p: Any) -> _Analisis:
    resultado = _Analisis(None, [], None)
    for nodo, en_campo in _runs(p, [0]):
        con_texto = nodo.tag == _R and nodo.find(_T) is not None
        if en_campo:
            resultado.quitar.append(nodo)
            if con_texto and resultado.en_campo is None:
                resultado.en_campo = nodo
        elif con_texto:
            if resultado.candidato is None:
                resultado.candidato = nodo
            else:
                resultado.quitar.append(nodo)
    return resultado


def _controles(run: Any) -> list[Any]:
    """Los ``w:sdt`` que envuelven al run (hasta la celda o el cuerpo)."""
    encontrados = []
    for ancestro in run.iterancestors():
        if ancestro.tag in (_TC, qn("w:body")):
            break
        if ancestro.tag == qn("w:sdt"):
            encontrados.append(ancestro)
    return encontrados


def _marcador(control: Any) -> Any | None:
    return control.find(qn("w:sdtPr") + "/" + qn("w:showingPlcHdr"))


def _sin_marcador(nodo: Any) -> None:
    """Quita ``w:showingPlcHdr`` de los controles que envuelven al nodo."""
    for control in _controles(nodo):
        marca = _marcador(control)
        if marca is not None:
            marca.getparent().remove(marca)


def _rpr_limpio(origen: Any | None, es_marcador: bool = False) -> Any | None:
    """Una copia del ``w:rPr`` sin marcas de cambio ni (si era un marcador) su estilo."""
    if origen is None:
        return None
    rpr = copy.deepcopy(origen)
    for hijo in list(rpr):
        if hijo.tag in _MARCAS_DE_CAMBIO or (
            es_marcador
            and hijo.tag == qn("w:rStyle")
            and hijo.get(qn("w:val")) == "PlaceholderText"
        ):
            rpr.remove(hijo)
    return rpr if len(rpr) else None


def _formato(p: Any) -> Any | None:
    """El formato de carácter del texto del párrafo: el de su primer run con texto."""
    analisis = _analizar(p)
    run = analisis.candidato if analisis.candidato is not None else analisis.en_campo
    if run is not None:
        marcador = any(_marcador(c) is not None for c in _controles(run))
        return _rpr_limpio(run.find(_RPR), marcador)
    return _rpr_limpio(p.find(_PPR + "/" + _RPR))  # el de la marca de párrafo


def _ppr_limpio(ppr: Any) -> Any:
    """Una copia del ``w:pPr`` apta para otro párrafo (sin salto de sección ni cambios)."""
    copia = copy.deepcopy(ppr)
    for hijo in list(copia):
        if hijo.tag in (_SECT, qn("w:pPrChange")):
            copia.remove(hijo)
        elif hijo.tag == _RPR:
            for marca in list(hijo):
                if marca.tag in _MARCAS_DE_CAMBIO:
                    hijo.remove(marca)
    return copia


def _ppr_de_estilo(estilo: str) -> Any:
    ppr = OxmlElement("w:pPr")
    pstyle = OxmlElement("w:pStyle")
    pstyle.set(qn("w:val"), estilo)
    ppr.append(pstyle)
    return ppr


def _run_nuevo(texto: str, formato: Any | None) -> Any:
    run = OxmlElement("w:r")
    if formato is not None:
        run.append(copy.deepcopy(formato))
    run.append(_texto(texto))
    return run


def _texto(texto: str) -> Any:
    t = OxmlElement("w:t")
    t.set(_ESPACIO, "preserve")
    t.text = texto
    return t


def _parrafo(texto: str, ppr: Any | None, formato: Any | None) -> Any:
    p = OxmlElement("w:p")
    if ppr is not None:
        p.append(_ppr_limpio(ppr))
    p.append(_run_nuevo(texto, formato))
    return p


def _reemplazar_parrafo(p: Any, textos: tuple[str, ...]) -> Any:
    """El primer texto va al primer run con texto (con su formato); los demás, a párrafos nuevos.

    Devuelve el último párrafo que ocupa el lugar de ``p`` (``p`` si no hay párrafos nuevos).
    """
    formato = _formato(p)
    analisis = _analizar(p)
    # Un control que se vacía o se reescribe ya no enseña su texto de ejemplo.
    if analisis.candidato is not None:
        _sin_marcador(analisis.candidato)
    for nodo in analisis.quitar:
        _sin_marcador(nodo)
        nodo.getparent().remove(nodo)
    run = analisis.candidato
    if run is None:
        run = OxmlElement("w:r")
        p.append(run)
    else:
        for hijo in list(run):
            run.remove(hijo)
    if formato is not None:
        run.append(copy.deepcopy(formato))
    run.append(_texto(textos[0]))
    ppr = p.find(_PPR)
    anterior = p
    for texto in textos[1:]:
        nuevo = _parrafo(texto, ppr, formato)
        anterior.addnext(nuevo)
        anterior = nuevo
    salto = ppr.find(_SECT) if ppr is not None else None
    if salto is not None and anterior is not p:  # el salto de sección va en el último párrafo
        ppr.remove(salto)
        anterior.find(_PPR).append(salto)
    return anterior


def _poner_celda(tc: Any, textos: tuple[str, ...]) -> None:
    """Sustituye todo el contenido de la celda por párrafos con el formato del primero."""
    primero = tc.find(_P)
    ppr = primero.find(_PPR) if primero is not None else None
    formato = _formato(primero) if primero is not None else None
    nuevos = [_parrafo(texto, ppr, formato) for texto in textos]
    envoltorio = tc.getparent()  # un control de fila que envuelve la celda también se reescribe
    while envoltorio is not None and envoltorio.tag in (qn("w:sdtContent"), qn("w:sdt")):
        marca = _marcador(envoltorio) if envoltorio.tag == qn("w:sdt") else None
        if marca is not None:
            marca.getparent().remove(marca)
        envoltorio = envoltorio.getparent()
    for hijo in list(tc):
        if hijo.tag != _TCPR:
            tc.remove(hijo)
    for nuevo in nuevos:
        tc.append(nuevo)


# --- Estilos ------------------------------------------------------------------------------


def _normal(texto: str) -> str:
    sin_marcas = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    compacto = " ".join(sin_marcas.casefold().split())
    return re.sub(r"^(?:titulo|heading) ?([1-9])$", r"heading \1", compacto)


def _visible(texto: str) -> str:
    return "".join(c for c in texto if unicodedata.category(c) != "Cc")[:60]


class _Estilos:
    """Los estilos de párrafo de la plantilla: se buscan por nombre visible y por ``styleId``."""

    def __init__(self, documento: Any) -> None:
        self.nombres: dict[str, str] = {}  # styleId -> nombre
        self.defecto: str | None = None
        for estilo in documento.styles.element.findall(qn("w:style")):
            ident = estilo.get(qn("w:styleId"))
            if ident is None or (estilo.get(qn("w:type")) or "paragraph") != "paragraph":
                continue
            nombre = estilo.find(qn("w:name"))
            self.nombres[ident] = (nombre.get(qn("w:val")) if nombre is not None else None) or ident
            if estilo.get(qn("w:default")) in ("1", "true", "on") and self.defecto is None:
                self.defecto = ident

    def exigir(self, estilo: str) -> str:
        if estilo in self.nombres:
            return estilo
        for pasada in (lambda x: x, _normal):
            for ident, nombre in self.nombres.items():
                if pasada(estilo) in (pasada(ident), pasada(nombre)):
                    return ident
        todos = sorted({_visible(n) for n in self.nombres.values()})
        lista = ", ".join(todos[:_MAX_ESTILOS_EN_EL_ERROR])
        if len(todos) > _MAX_ESTILOS_EN_EL_ERROR:
            lista += f" y {len(todos) - _MAX_ESTILOS_EN_EL_ERROR} más"
        raise ErrorEscritura(
            "ESTILO_INEXISTENTE",
            f"La plantilla no tiene el estilo de párrafo «{_visible(estilo)}». Estilos de párrafo: {lista}.",
        )


# --- Resolución de las operaciones --------------------------------------------------------


def _elemento(mapa: dict[str, Any], id_: str, *tipos: str) -> Any:
    elemento = mapa.get(id_)
    if elemento is None:
        raise ErrorEscritura(
            "ID_DESCONOCIDO",
            f"El id «{id_}» no existe en la plantilla. Vuelve a leerla con «tiza leer» y copia sus ids.",
        )
    if elemento.tag not in tipos:
        pide = " o ".join(_NOMBRE_DE[t] for t in tipos)
        raise ErrorEscritura(
            "ID_DESCONOCIDO", f"El id «{id_}» es {_NOMBRE_DE[elemento.tag]} y se esperaba {pide}."
        )
    return elemento


def _fusiones(tr: Any) -> tuple[bool, bool]:
    """Si la fila tiene alguna celda con ``gridSpan`` mayor que 1 y alguna con ``vMerge``."""
    ancha = vertical = False
    for tc in celdas_directas(tr):
        tcpr = tc.find(_TCPR)
        if tcpr is None:
            continue
        span = tcpr.find(qn("w:gridSpan"))
        ancha = ancha or (span is not None and (span.get(qn("w:val")) or "1") not in ("0", "1"))
        vertical = vertical or tcpr.find(qn("w:vMerge")) is not None
    return ancha, vertical


def _asegurar_cierre(contenedor: Any) -> None:
    """Una celda acaba siempre en un párrafo, y el cuerpo no puede acabar en una tabla."""
    hijos = [h for h in contenedor if h.tag not in (_TCPR, _SECT)]
    if contenedor.tag == _TC:
        falta = not hijos or hijos[-1].tag != _P
    else:
        falta = not hijos or hijos[-1].tag == _TBL
    if falta:
        nuevo = OxmlElement("w:p")
        if hijos:
            hijos[-1].addnext(nuevo)
        elif contenedor.tag == _TC:
            contenedor.append(nuevo)
        else:
            contenedor.insert(0, nuevo)


def _borrar(elemento: Any) -> None:
    padre = elemento.getparent()
    antes, despues = elemento.getprevious(), elemento.getnext()
    padre.remove(elemento)
    if elemento.tag == _TR and padre.find(_TR) is None:  # una tabla sin filas no es válida
        _borrar(padre)
    elif padre.tag in (_TC, qn("w:body")):
        if antes is not None and despues is not None and antes.tag == despues.tag == _TBL:
            antes.addnext(OxmlElement("w:p"))  # sin un párrafo entre ellas, Word las funde
        _asegurar_cierre(padre)


_W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
_ATRIBUTOS_DE_PARRAFO = (f"{{{_W14}}}paraId", f"{{{_W14}}}textId")
_SDT_ID = qn("w:sdtPr") + "/" + qn("w:id")
_DOCPR = qn("wp:docPr")


class _Ids:
    """Ids únicos para lo que se copia: mayores que el máximo del documento."""

    def __init__(self, raiz: Any) -> None:
        self.control = max(
            (_entero(c.get(qn("w:val"))) for c in raiz.iterfind(".//" + _SDT_ID)), default=0
        )
        self.imagen = max((_entero(d.get("id")) for d in raiz.iter(_DOCPR)), default=0)

    def renovar(self, elemento: Any) -> None:
        """Quita lo que no puede repetirse en una copia y da ids nuevos a controles e imágenes."""
        for nodo in elemento.iter():
            if isinstance(nodo.tag, str):
                for atributo in _ATRIBUTOS_DE_PARRAFO:
                    nodo.attrib.pop(atributo, None)
        for marca in list(elemento.iter(qn("w:bookmarkStart"), qn("w:bookmarkEnd"))):
            marca.getparent().remove(marca)
        for identificador in elemento.iterfind(".//" + _SDT_ID):
            self.control += 1
            identificador.set(qn("w:val"), str(self.control))
        for imagen in elemento.iter(_DOCPR):
            self.imagen += 1
            imagen.set("id", str(self.imagen))


def _entero(texto: str | None) -> int:
    try:
        return max(int(texto), 0) if texto is not None else 0
    except ValueError:
        return 0


def _continuacion(tr: Any) -> bool:
    """¿Tiene la fila alguna celda que continúa una fusión vertical empezada más arriba?"""
    for tc in celdas_directas(tr):
        fusion = tc.find(_TCPR + "/" + qn("w:vMerge"))
        if fusion is not None and fusion.get(qn("w:val")) in (None, "continue"):
            return True
    return False


def _preparar(
    i: int,
    operacion: Operacion,
    mapa: dict[str, Any],
    estilos: _Estilos,
    ids: _Ids,
    ultimos: dict[Any, Any],
) -> Callable[[], None]:
    """Valida la operación con la plantilla y devuelve lo que la aplica sobre lo ya resuelto."""
    if isinstance(operacion, Reemplazar):
        destino = _elemento(mapa, operacion.id, _P, _TC)
        if destino.tag == _TC:
            return lambda: _poner_celda(destino, operacion.texto)

        def reemplazar() -> None:
            ultimo = _reemplazar_parrafo(destino, operacion.texto)
            # Los párrafos nuevos sustituyen al párrafo, así que van antes de lo ya insertado
            # tras él; si no había nada insertado, lo que se inserte después va detrás.
            if ultimo is not destino and destino not in ultimos:
                ultimos[destino] = ultimo

        return reemplazar

    if isinstance(operacion, InsertarDespues):
        ref = _elemento(mapa, operacion.id, _P, _TBL)
        estilo = estilos.exigir(operacion.estilo) if operacion.estilo else None

        def insertar() -> None:
            ppr = formato = None
            if estilo is not None:
                ppr = _ppr_de_estilo(estilo)
            elif ref.tag == _P:
                ppr, formato = ref.find(_PPR), _formato(ref)
            elif estilos.defecto is not None:
                ppr = _ppr_de_estilo(estilos.defecto)
            anterior = ultimos.get(ref, ref)  # tras lo ya insertado en esa ancla: orden del YAML
            for texto in operacion.parrafos:
                nuevo = _parrafo(texto, ppr, formato)
                anterior.addnext(nuevo)
                anterior = nuevo
            ultimos[ref] = anterior

        return insertar

    if isinstance(operacion, Filas):
        tabla = _elemento(mapa, operacion.tabla, _TBL)
        id_modelo = f"{operacion.tabla}.f{operacion.modelo}"
        modelo = _elemento(mapa, id_modelo, _TR)
        if any(_fusiones(modelo)):
            raise ErrorEscritura(
                "FILA_MODELO_FUSIONADA",
                f"operaciones[{i}]: la fila modelo «{id_modelo}» tiene celdas fusionadas; "
                "elige una fila sin fusiones.",
            )
        ante = None
        if operacion.antes_de is not None:
            id_ante = f"{operacion.tabla}.f{operacion.antes_de}"
            ante = _elemento(mapa, id_ante, _TR)
            if _continuacion(ante):
                raise ErrorEscritura(
                    "FILA_FUSIONADA",
                    f"operaciones[{i}]: «antes_de» apunta a la fila «{id_ante}», que continúa una "
                    "fusión vertical; insertar ahí partiría la fusión. Elige otra fila.",
                )
        celdas = len(celdas_directas(modelo))
        for k, fila in enumerate(operacion.contenido):
            if len(fila) != celdas:
                raise ErrorEscritura(
                    "CELDAS_NO_COINCIDEN",
                    f"operaciones[{i}].contenido[{k}] tiene {len(fila)} celdas y la fila modelo "
                    f"«{id_modelo}» tiene {celdas}.",
                )

        def anadir() -> None:
            ultimo = [tr for tr in tabla if tr.tag == _TR][-1]
            for fila in operacion.contenido:
                nueva = copy.deepcopy(modelo)
                for marca in list(nueva.iter(*_MARCAS_DE_CAMBIO)):
                    if marca.getparent().tag == qn("w:trPr"):
                        marca.getparent().remove(marca)
                for tc, textos in zip(celdas_directas(nueva), fila, strict=True):
                    _poner_celda(tc, textos)
                ids.renovar(nueva)
                if ante is not None:
                    ante.addprevious(nueva)
                else:
                    ultimo.addnext(nueva)
                    ultimo = nueva

        return anadir

    if isinstance(operacion, DuplicarTabla):
        original = _elemento(mapa, operacion.tabla, _TBL)
        ancla = _elemento(mapa, operacion.despues_de, _P, _TBL)

        def duplicar() -> None:
            ultimo = ultimos.get(ancla, ancla)  # tras lo ya insertado en esa ancla
            for cambios in operacion.celdas:
                copia = copy.deepcopy(original)
                ids.renovar(copia)
                celdas = mapa_de_tabla(copia)
                for relativo, textos in cambios.items():
                    tc = celdas.get(relativo)
                    if tc is None or tc.tag != _TC:
                        raise ErrorEscritura(
                            "ID_DESCONOCIDO",
                            f"operaciones[{i}]: la celda «{relativo}» no existe en la tabla "
                            f"«{operacion.tabla}» tal como está en ese momento.",
                        )
                    _poner_celda(tc, textos)
                if ultimo.tag == _TBL:  # dos tablas seguidas se fundirían en una en Word
                    separador = OxmlElement("w:p")
                    ultimo.addnext(separador)
                    ultimo = separador
                ultimo.addnext(copia)
                ultimo = copia
            siguiente = ultimo.getnext()
            if siguiente is not None and siguiente.tag == _TBL:  # también por detrás
                ultimo.addnext(OxmlElement("w:p"))
            ultimos[ancla] = ultimo

        return duplicar

    destino = _elemento(mapa, operacion.id, _P, _TBL, _TR)
    if destino.tag == _TR and _fusiones(destino)[1]:
        raise ErrorEscritura(
            "FILA_FUSIONADA",
            f"operaciones[{i}]: la fila «{operacion.id}» tiene celdas fusionadas en vertical; "
            "borrarla rompería la tabla. Cambia su texto con «reemplazar».",
        )
    return lambda: _borrar(destino)


# --- Entrada ------------------------------------------------------------------------------


_SIGUIENTES_A_UPDATE_FIELDS = tuple(
    qn(f"w:{n}")
    for n in (
        "hdrShapeDefaults",
        "footnotePr",
        "endnotePr",
        "compat",
        "docVars",
        "rsids",
        "mathPr",
        "attachedSchema",
        "themeFontLang",
        "clrSchemeMapping",
        "doNotIncludeSubdocsInStats",
        "doNotAutoCompressPictures",
        "forceUpgrade",
        "captions",
        "readModeInkLockDown",
        "smartTagType",
        "schemaLibrary",
        "shapeDefaults",
        "doNotEmbedSmartTags",
        "decimalSymbol",
        "listSeparator",
    )
)


_CAMPO_INDICE = "TOC"  # nombre del campo de índice de Word, no un código de error


def _tiene_indice(raiz: Any) -> bool:
    """Un ``w:sdt`` de galería «Table of Contents» o un campo ``TOC`` en el cuerpo."""
    for galeria in raiz.iter(qn("w:docPartGallery")):
        if (galeria.get(qn("w:val")) or "").strip().lower() == "table of contents":
            return True
    for instruccion in raiz.iter(qn("w:instrText")):
        if (instruccion.text or "").split(None, 1)[:1] == [_CAMPO_INDICE]:
            return True
    for simple in raiz.iter(qn("w:fldSimple")):
        if (simple.get(qn("w:instr")) or "").split(None, 1)[:1] == [_CAMPO_INDICE]:
            return True
    return False


def _marcar_actualizar_campos(documento: Any) -> None:
    """``w:updateFields = true`` en ``word/settings.xml`` (python-docx lo crea si falta)."""
    ajustes = documento.settings.element
    for previo in ajustes.findall(qn("w:updateFields")):
        ajustes.remove(previo)
    marca = OxmlElement("w:updateFields")
    marca.set(qn("w:val"), "true")
    siguiente = next((h for h in ajustes if h.tag in _SIGUIENTES_A_UPDATE_FIELDS), None)
    if siguiente is None:
        ajustes.append(marca)
    else:
        siguiente.addprevious(marca)


def rellenar(carpeta: Path, relleno: Relleno) -> ResultadoRelleno:
    """Escribe ``relleno.salida``: la plantilla con las operaciones aplicadas.

    Lanza ``ErrorEscritura`` con un código estable. Si algo falla no queda ninguna salida y la
    plantilla no se toca.
    """
    carpeta = Path(carpeta)
    plantilla = dentro_de_la_carpeta(relleno.plantilla, carpeta, EXTENSIONES_PLANTILLA)
    salida = dentro_de_la_carpeta(relleno.salida, carpeta, EXTENSIONES_PLANTILLA)
    if os.path.lexists(salida):
        raise ErrorEscritura(
            "DOCUMENTO_EXISTE", f"Ya existe {salida.name}: tiza no sobrescribe un Word."
        )
    try:
        datos = leer_bytes_docx(plantilla)
    except FileNotFoundError:
        raise ErrorEscritura("DOCUMENTO_AUSENTE", f"No existe {plantilla.name}.") from None
    except OSError:
        raise ErrorEscritura("FICHERO_BLOQUEADO", f"No se puede leer {plantilla.name}.") from None
    except ErrorLectura as error:
        raise ErrorEscritura(error.codigo, error.detalle) from None
    if hashlib.sha256(datos).hexdigest() != relleno.sha256:
        raise ErrorEscritura(
            "PLANTILLA_CAMBIADA",
            f"{plantilla.name} ha cambiado desde que se leyó: sus ids ya no valen. "
            "Vuelve a leerla con «tiza leer» y rehaz el relleno.",
        )
    try:
        analisis = analizar_docx(datos, plantilla.name)
    except ErrorLectura as error:
        raise ErrorEscritura(error.codigo, error.detalle) from None
    indice = _tiene_indice(analisis.documento.element)
    estilos = _Estilos(analisis.documento)
    ids = _Ids(analisis.documento.element)
    ultimos: dict[Any, Any] = {}  # ancla -> último elemento insertado tras ella
    acciones = [
        _preparar(i, operacion, analisis.mapa, estilos, ids, ultimos)
        for i, operacion in enumerate(relleno.operaciones)
    ]
    try:
        for accion in acciones:
            accion()
        _marcar_actualizar_campos(analisis.documento)
        memoria = io.BytesIO()
        analisis.documento.save(memoria)
    except ErrorEscritura:
        raise
    except Exception as error:  # XML raro: nunca texto de la librería
        raise ErrorEscritura(
            "FORMATO_NO_ADMITIDO", "No se pudo aplicar el relleno sobre esta plantilla."
        ) from error
    escribir_sin_sobrescribir(memoria.getvalue(), salida)
    avisos = list(analisis.lectura.avisos)
    if indice:
        avisos.append("INDICE_SE_ACTUALIZA_AL_ABRIR")
    return ResultadoRelleno(salida, len(acciones), tuple(avisos))
