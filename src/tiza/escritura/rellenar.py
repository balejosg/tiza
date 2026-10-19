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
    DuplicarTabla,
    Filas,
    InsertarDespues,
    Operacion,
    Reemplazar,
    Relleno,
)
from tiza.escritura.word import escribir_sin_sobrescribir
from tiza.ficheros import fichero_en_carpeta
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


def _reemplazar_parrafo(p: Any, textos: tuple[str, ...]) -> None:
    """El primer texto va al primer run con texto (con su formato); los demás, a párrafos nuevos."""
    formato = _formato(p)
    analisis = _analizar(p)
    for nodo in analisis.quitar:
        nodo.getparent().remove(nodo)
    run = analisis.candidato
    if run is None:
        run = OxmlElement("w:r")
        p.append(run)
    else:
        for control in _controles(run):  # ya no es el texto de ejemplo del control
            marca = _marcador(control)
            if marca is not None:
                marca.getparent().remove(marca)
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


def _poner_celda(tc: Any, textos: tuple[str, ...]) -> None:
    """Sustituye todo el contenido de la celda por párrafos con el formato del primero."""
    primero = tc.find(_P)
    ppr = primero.find(_PPR) if primero is not None else None
    formato = _formato(primero) if primero is not None else None
    nuevos = [_parrafo(texto, ppr, formato) for texto in textos]
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
    padre.remove(elemento)
    if elemento.tag == _TR and padre.find(_TR) is None:  # una tabla sin filas no es válida
        _borrar(padre)
    elif padre.tag in (_TC, qn("w:body")):
        _asegurar_cierre(padre)


def _sin_marcadores(elemento: Any) -> None:
    for etiqueta in ("w:bookmarkStart", "w:bookmarkEnd"):
        for marca in list(elemento.iter(qn(etiqueta))):
            marca.getparent().remove(marca)


def _preparar(
    i: int, operacion: Operacion, mapa: dict[str, Any], estilos: _Estilos
) -> Callable[[], None]:
    """Valida la operación con la plantilla y devuelve lo que la aplica sobre lo ya resuelto."""
    if isinstance(operacion, Reemplazar):
        destino = _elemento(mapa, operacion.id, _P, _TC)
        poner = _reemplazar_parrafo if destino.tag == _P else _poner_celda
        return lambda: poner(destino, operacion.texto)

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
            anterior = ref
            for texto in operacion.parrafos:
                nuevo = _parrafo(texto, ppr, formato)
                anterior.addnext(nuevo)
                anterior = nuevo

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
            ante = _elemento(mapa, f"{operacion.tabla}.f{operacion.antes_de}", _TR)
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
            ultimo = ancla
            for cambios in operacion.celdas:
                copia = copy.deepcopy(original)
                _sin_marcadores(copia)
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


def _fuera_de_la_carpeta(ruta: Path, carpeta: Path) -> Path:
    try:
        return fichero_en_carpeta(ruta, carpeta, frozenset({".docx"}))
    except ErrorLectura as error:
        raise ErrorEscritura(error.codigo, error.detalle) from None


def rellenar(carpeta: Path, relleno: Relleno) -> ResultadoRelleno:
    """Escribe ``relleno.salida``: la plantilla con las operaciones aplicadas.

    Lanza ``ErrorEscritura`` con un código estable. Si algo falla no queda ninguna salida y la
    plantilla no se toca.
    """
    carpeta = Path(carpeta)
    plantilla = _fuera_de_la_carpeta(relleno.plantilla, carpeta)
    salida = _fuera_de_la_carpeta(relleno.salida, carpeta)
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
    estilos = _Estilos(analisis.documento)
    acciones = [
        _preparar(i, operacion, analisis.mapa, estilos)
        for i, operacion in enumerate(relleno.operaciones)
    ]
    try:
        for accion in acciones:
            accion()
        memoria = io.BytesIO()
        analisis.documento.save(memoria)
    except ErrorEscritura:
        raise
    except Exception as error:  # XML raro: nunca texto de la librería
        raise ErrorEscritura(
            "FORMATO_NO_ADMITIDO", "No se pudo aplicar el relleno sobre esta plantilla."
        ) from error
    escribir_sin_sobrescribir(memoria.getvalue(), salida)
    return ResultadoRelleno(salida, len(acciones), tuple(analisis.lectura.avisos))
