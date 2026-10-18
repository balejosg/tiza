"""Lector de Word (.docx): párrafos, tablas, celdas y numeración automática.

Lee el fichero entero una vez (con límite) y trabaja sobre esos bytes en memoria: el .docx no
se vuelve a abrir desde el disco. Nunca ejecuta nada del documento: solo lee su XML.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn

from tiza.ficheros import FicheroNoSeguro, leer_bytes_acotado
from tiza.lectura.modelo import Bloque, ErrorLectura, Lectura

__all__ = ["leer_docx"]

MAXIMO_FICHERO = 30 * 1024 * 1024
MAXIMO_XML = 60 * 1024 * 1024
MAXIMO_TOTAL = 400 * 1024 * 1024
_CABECERA_OLE = bytes.fromhex("D0CF11E0")
_PARTES_XML = ("word/document.xml", "word/numbering.xml", "word/styles.xml")
_NOMBRE_TITULO = re.compile(r"^(?:heading|t[ií]tulo)\s*([1-9])$", re.IGNORECASE)
_DESCARTADOS = {"del", "moveFrom"}  # lo borrado con el control de cambios no cuenta
_CAMBIOS = {"ins", "del", "moveFrom", "moveTo"}
_FORMATOS_DECIMAL = {"decimal", "decimalZero", "ordinal", "cardinalText", "ordinalText"}


def _fallo(codigo: str, detalle: str = "") -> ErrorLectura:
    return ErrorLectura(codigo, detalle)


def _val(elemento: Any, nombre: str) -> str | None:
    """El atributo ``w:val`` del primer hijo ``w:<nombre>``, o ``None``."""
    hijo = elemento.find(qn(f"w:{nombre}")) if elemento is not None else None
    return None if hijo is None else hijo.get(qn("w:val"))


def _entero(texto: str | None) -> int | None:
    try:
        return int(texto) if texto is not None else None
    except ValueError:
        return None


# --- Numeración ---------------------------------------------------------------------------


def _letras(n: int, mayusculas: bool) -> str:
    n = max(n, 1)
    texto = chr(97 + (n - 1) % 26) * ((n - 1) // 26 + 1)
    return texto.upper() if mayusculas else texto


def _romano(n: int, mayusculas: bool) -> str:
    if not 0 < n < 4000:
        return str(n)
    partes = []
    for valor, simbolo in (
        (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
        (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
    ):  # fmt: skip
        while n >= valor:
            partes.append(simbolo)
            n -= valor
    texto = "".join(partes)
    return texto.upper() if mayusculas else texto


def _formatear(n: int, formato: str) -> str:
    if formato == "lowerLetter":
        return _letras(n, False)
    if formato == "upperLetter":
        return _letras(n, True)
    if formato == "lowerRoman":
        return _romano(n, False)
    if formato == "upperRoman":
        return _romano(n, True)
    if formato == "decimalZero":
        return f"{n:02d}"
    return str(n)


@dataclass
class _Nivel:
    inicio: int = 1
    formato: str = "decimal"
    texto: str = "%1."
    estilo: str = ""


@dataclass
class _Numeracion:
    """``numbering.xml`` ya leído, con los contadores de cada lista."""

    abstractas: dict[str, dict[int, _Nivel]] = field(default_factory=dict)
    listas: dict[str, str] = field(default_factory=dict)  # numId -> abstractNumId
    reinicios: dict[str, dict[int, int]] = field(default_factory=dict)  # numId -> nivel -> inicio
    niveles_de_estilo: dict[str, tuple[str, int]] = field(default_factory=dict)
    contadores: dict[str, list[int | None]] = field(default_factory=dict)

    @classmethod
    def desde(cls, raiz: Any) -> _Numeracion:
        num = cls()
        if raiz is None:
            return num
        for abstracta in raiz.findall(qn("w:abstractNum")):
            ident = abstracta.get(qn("w:abstractNumId"))
            niveles: dict[int, _Nivel] = {}
            for lvl in abstracta.findall(qn("w:lvl")):
                indice = _entero(lvl.get(qn("w:ilvl")))
                if indice is None or not 0 <= indice <= 8:
                    continue
                inicio = _entero(_val(lvl, "start"))
                niveles[indice] = _Nivel(
                    inicio=1 if inicio is None else inicio,
                    formato=_val(lvl, "numFmt") or "decimal",
                    texto=_val(lvl, "lvlText") or "",
                    estilo=_val(lvl, "pStyle") or "",
                )
                if niveles[indice].estilo and ident is not None:
                    num.niveles_de_estilo.setdefault(niveles[indice].estilo, (ident, indice))
            if ident is not None:
                num.abstractas[ident] = niveles
        for lista in raiz.findall(qn("w:num")):
            ident = lista.get(qn("w:numId"))
            if ident is None:
                continue
            num.listas[ident] = _val(lista, "abstractNumId") or ""
            reinicios: dict[int, int] = {}
            for over in lista.findall(qn("w:lvlOverride")):
                indice = _entero(over.get(qn("w:ilvl")))
                inicio = _entero(_val(over, "startOverride"))
                if indice is not None and inicio is not None:
                    reinicios[indice] = inicio
            num.reinicios[ident] = reinicios
        return num

    def etiqueta(self, num_id: str, ilvl: int) -> str:
        """La etiqueta del siguiente párrafo de esa lista y nivel («c)», «2.», «-»)."""
        niveles = self.abstractas.get(self.listas.get(num_id, ""))
        if not niveles or ilvl not in niveles:
            return ""
        contadores = self.contadores.setdefault(num_id, [None] * 9)
        actual = niveles[ilvl]
        previo = contadores[ilvl]
        if previo is None:
            contadores[ilvl] = self.reinicios.get(num_id, {}).get(ilvl, actual.inicio)
        else:
            contadores[ilvl] = previo + 1
        for inferior in range(ilvl + 1, 9):
            contadores[inferior] = None
        if actual.formato == "none":
            return ""
        if actual.formato == "bullet":
            return "-"

        def sustituir(coincidencia: re.Match[str]) -> str:
            nivel = int(coincidencia.group(1)) - 1
            destino = niveles.get(nivel)
            valor = contadores[nivel]
            if valor is None:
                valor = destino.inicio if destino else 1
            return _formatear(valor, destino.formato if destino else "decimal")

        return re.sub(r"%([1-9])", sustituir, actual.texto)


# --- Estilos ------------------------------------------------------------------------------


class _Estilos:
    def __init__(self, raiz: Any) -> None:
        self.por_id: dict[str, Any] = {}
        if raiz is not None:
            for estilo in raiz.findall(qn("w:style")):
                ident = estilo.get(qn("w:styleId"))
                if ident is not None:
                    self.por_id[ident] = estilo

    def cadena(self, ident: str) -> list[Any]:
        """El estilo y los que hereda (``basedOn``), sin vueltas infinitas."""
        resultado: list[Any] = []
        vistos: set[str] = set()
        while ident and ident in self.por_id and ident not in vistos:
            vistos.add(ident)
            estilo = self.por_id[ident]
            resultado.append(estilo)
            ident = _val(estilo, "basedOn") or ""
        return resultado

    def nombre(self, ident: str) -> str:
        estilo = self.por_id.get(ident)
        return (_val(estilo, "name") if estilo is not None else None) or ident

    def esquema(self, ident: str) -> int | None:
        """Nivel de esquema 0-8 del estilo (``outlineLvl``), o ``None``."""
        for estilo in self.cadena(ident):
            ppr = estilo.find(qn("w:pPr"))
            valor = _entero(_val(ppr, "outlineLvl")) if ppr is not None else None
            if valor is not None:
                return valor
        return None

    def numeracion(self, ident: str) -> tuple[str | None, int | None]:
        """``(numId, ilvl)`` que el estilo (o los que hereda) da a sus párrafos."""
        num_id: str | None = None
        ilvl: int | None = None
        for estilo in self.cadena(ident):
            ppr = estilo.find(qn("w:pPr"))
            num_pr = ppr.find(qn("w:numPr")) if ppr is not None else None
            if num_pr is None:
                continue
            if num_id is None:
                num_id = _val(num_pr, "numId")
            if ilvl is None:
                ilvl = _entero(_val(num_pr, "ilvl"))
        return num_id, ilvl


# --- Lectura del cuerpo -------------------------------------------------------------------


class _Lector:
    def __init__(self, numeracion: _Numeracion, estilos: _Estilos) -> None:
        self.numeracion = numeracion
        self.estilos = estilos
        self.cambios = False

    # texto -------------------------------------------------------------------------------
    def _texto(self, elemento: Any, partes: list[str]) -> None:
        for hijo in elemento:
            nombre = hijo.tag.rsplit("}", 1)[-1] if isinstance(hijo.tag, str) else ""
            if nombre in _CAMBIOS:
                self.cambios = True
            if nombre in _DESCARTADOS:
                continue
            if nombre == "t":
                partes.append(hijo.text or "")
            elif nombre in ("tab", "br", "cr", "noBreakHyphen"):
                partes.append("-" if nombre == "noBreakHyphen" else " ")
            elif nombre in ("pPr", "rPr", "instrText", "delText"):
                continue
            else:  # r, ins, moveTo, hyperlink, fldSimple, smartTag, sdt, sdtContent…
                self._texto(hijo, partes)

    def _parrafo(self, p: Any, id_: str) -> tuple[Bloque, bool]:
        """El bloque del párrafo y si va vacío (sin texto): no se publica si lo está."""
        partes: list[str] = []
        self._texto(p, partes)
        texto = " ".join("".join(partes).split())
        ppr = p.find(qn("w:pPr"))
        ident = _val(ppr, "pStyle") or "" if ppr is not None else ""
        etiqueta = self._etiqueta(ppr, ident)
        nivel = self._nivel(ppr, ident)
        estilo = self.estilos.nombre(ident) if ident else ""
        bloque = Bloque(
            id=id_,
            tipo="titulo" if nivel else "parrafo",
            texto=texto,
            nivel=nivel,
            estilo=estilo,
            etiqueta=etiqueta,
        )
        return bloque, texto == ""

    def _etiqueta(self, ppr: Any, estilo: str) -> str:
        num_id, ilvl = (None, None)
        num_pr = ppr.find(qn("w:numPr")) if ppr is not None else None
        if num_pr is not None:
            num_id, ilvl = _val(num_pr, "numId"), _entero(_val(num_pr, "ilvl"))
        if estilo:
            de_estilo = self.estilos.numeracion(estilo)
            num_id = num_id if num_id is not None else de_estilo[0]
            if ilvl is None:
                ilvl = de_estilo[1]
                if ilvl is None and num_id is not None:
                    enlazado = self.numeracion.niveles_de_estilo.get(estilo)
                    if enlazado is not None:
                        ilvl = enlazado[1]
        if num_id is None or num_id == "0":
            return ""
        return self.numeracion.etiqueta(num_id, ilvl if ilvl is not None and 0 <= ilvl <= 8 else 0)

    def _nivel(self, ppr: Any, estilo: str) -> int:
        esquema = _entero(_val(ppr, "outlineLvl")) if ppr is not None else None
        if esquema is None and estilo:
            esquema = self.estilos.esquema(estilo)
        if esquema is not None:
            return esquema + 1 if 0 <= esquema <= 8 else 0
        coincidencia = _NOMBRE_TITULO.match(self.estilos.nombre(estilo)) if estilo else None
        return int(coincidencia.group(1)) if coincidencia else 0

    # estructura --------------------------------------------------------------------------
    def _elementos(self, contenedor: Any):
        """Los ``w:p`` y ``w:tbl`` de un contenedor, en orden, entrando en los ``w:sdt``."""
        for hijo in contenedor:
            if not isinstance(hijo.tag, str):
                continue
            if hijo.tag in (qn("w:p"), qn("w:tbl")):
                yield hijo
            elif hijo.tag == qn("w:sdt"):
                galeria = hijo.find(
                    qn("w:sdtPr") + "/" + qn("w:docPartObj") + "/" + qn("w:docPartGallery")
                )
                if (
                    galeria is not None
                    and (galeria.get(qn("w:val")) or "").lower() == "table of contents"
                ):
                    continue
                contenido = hijo.find(qn("w:sdtContent"))
                if contenido is not None:
                    yield from self._elementos(contenido)
            elif hijo.tag in (qn("w:ins"), qn("w:moveTo")):
                self.cambios = True
                yield from self._elementos(hijo)
            elif hijo.tag in (qn("w:del"), qn("w:moveFrom")):
                self.cambios = True

    def contenido(self, contenedor: Any, prefijo: str) -> list[Bloque]:
        """Párrafos y tablas de un contenedor (cuerpo o celda), con ids ``<prefijo>p<n>``."""
        bloques: list[Bloque] = []
        parrafos = tablas = 0
        for elemento in self._elementos(contenedor):
            if elemento.tag == qn("w:tbl"):
                tablas += 1
                bloques.append(self._tabla(elemento, f"{prefijo}t{tablas}"))
                continue
            bloque, vacio = self._parrafo(elemento, f"{prefijo}p{parrafos + 1}")
            if vacio:
                continue
            parrafos += 1
            bloques.append(bloque)
        return bloques

    def _tabla(self, tbl: Any, id_: str) -> Bloque:
        tabla = Bloque(id=id_, tipo="tabla")
        origenes: dict[int, Bloque] = {}  # columna -> celda de la fila anterior que la ocupa
        columnas = len(tbl.findall(qn("w:tblGrid") + "/" + qn("w:gridCol")))
        filas = [f for f in tbl if f.tag == qn("w:tr")]
        for numero, tr in enumerate(filas, start=1):
            fila = Bloque(id=f"{id_}.f{numero}", tipo="fila")
            trpr = tr.find(qn("w:trPr"))
            columna = _entero(_val(trpr, "gridBefore")) or 0 if trpr is not None else 0
            nuevos: dict[int, Bloque] = {}
            for tc in tr.iter(qn("w:tc")):
                if tc.getparent() is not tr and tc.getparent().tag != qn("w:sdtContent"):
                    continue
                tcpr = tc.find(qn("w:tcPr"))
                ancho = max(_entero(_val(tcpr, "gridSpan")) or 1, 1) if tcpr is not None else 1
                fusion = tcpr.find(qn("w:vMerge")) if tcpr is not None else None
                continuacion = fusion is not None and fusion.get(qn("w:val")) in (None, "continue")
                origen = origenes.get(columna) if continuacion else None
                if origen is not None:
                    origen.alto += 1
                    nuevos[columna] = origen
                else:
                    celda = Bloque(
                        id=f"{fila.id}.c{len(fila.hijos) + 1}", tipo="celda", ancho=ancho
                    )
                    celda.hijos = self.contenido(tc, f"{celda.id}.")
                    fila.hijos.append(celda)
                    nuevos[columna] = celda
                columna += ancho
            origenes = nuevos
            columnas = max(columnas, columna)
            tabla.hijos.append(fila)
        tabla.ancho, tabla.alto = columnas, len(filas)
        return tabla


# --- Entrada ------------------------------------------------------------------------------


def _comprobar_zip(datos: bytes) -> None:
    if datos[:4] == _CABECERA_OLE:
        if "EncryptedPackage".encode("utf-16-le") in datos:
            raise _fallo("DOCUMENTO_PROTEGIDO", "El documento está cifrado con contraseña.")
        raise _fallo("FORMATO_NO_ADMITIDO", "Es un Word antiguo (.doc), no un .docx.")
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as zf:
            info = {i.filename: i for i in zf.infolist()}
    except (zipfile.BadZipFile, ValueError, NotImplementedError, OSError):
        raise _fallo("FORMATO_NO_ADMITIDO", "No es un documento .docx.") from None
    if "word/document.xml" not in info:
        raise _fallo("FORMATO_NO_ADMITIDO", "Falta word/document.xml: no es un .docx.")
    xml = sum(info[n].file_size for n in _PARTES_XML if n in info)
    total = sum(i.file_size for i in info.values())
    if xml > MAXIMO_XML or total > MAXIMO_TOTAL:
        raise _fallo(
            "DOCUMENTO_DEMASIADO_GRANDE", "El documento descomprimido es demasiado grande."
        )


def _raiz(datos: bytes, miembro: str) -> Any:
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as zf:
            if miembro not in zf.namelist():
                return None
            return parse_xml(zf.read(miembro))
    except (zipfile.BadZipFile, ValueError, KeyError):
        raise _fallo("FORMATO_NO_ADMITIDO", f"No se puede leer {miembro}.") from None
    except Exception:
        raise _fallo("FORMATO_NO_ADMITIDO", f"{miembro} no es XML válido.") from None


def leer_docx(ruta: Path) -> Lectura:
    """Lee un .docx y devuelve sus bloques en orden de documento."""
    ruta = Path(ruta)
    try:
        datos = leer_bytes_acotado(ruta, MAXIMO_FICHERO)
    except PermissionError:
        raise _fallo("FICHERO_BLOQUEADO", "El fichero está abierto o bloqueado.") from None
    except FicheroNoSeguro as exc:
        if exc.motivo == "grande":
            raise _fallo("DOCUMENTO_DEMASIADO_GRANDE", "El fichero pasa de 30 MB.") from None
        raise _fallo("FORMATO_NO_ADMITIDO", "No es un fichero normal.") from None
    _comprobar_zip(datos)
    try:
        numeracion = _Numeracion.desde(_raiz(datos, "word/numbering.xml"))
        estilos = _Estilos(_raiz(datos, "word/styles.xml"))
        try:
            documento = Document(io.BytesIO(datos))
        except Exception:
            raise _fallo("FORMATO_NO_ADMITIDO", "No se puede abrir el documento.") from None
        lector = _Lector(numeracion, estilos)
        bloques = lector.contenido(documento.element.body, "")
    except ErrorLectura:
        raise
    except Exception:  # XML raro, números que no lo son, recursión: nunca texto de la librería
        raise _fallo("FORMATO_NO_ADMITIDO", "No se puede interpretar el documento.") from None
    return Lectura(
        fichero=ruta.name,
        formato="docx",
        bloques=bloques,
        avisos=["CAMBIOS_SIN_ACEPTAR"] if lector.cambios else [],
        sha256=hashlib.sha256(datos).hexdigest(),
    )
