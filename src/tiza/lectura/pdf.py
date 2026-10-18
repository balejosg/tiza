"""Lector de PDF: el texto de cada página, línea a línea, con la página en el id.

Lee el fichero entero una vez (con límite) y trabaja sobre esos bytes en memoria. Extrae el
texto en modo normal: las tablas salen columna a columna y por eso siempre se avisa.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from pypdf import PdfReader

from tiza.ficheros import FicheroNoSeguro, leer_bytes_acotado
from tiza.lectura.modelo import Bloque, ErrorLectura, Lectura

__all__ = ["leer_pdf"]

MAXIMO_FICHERO = 30 * 1024 * 1024
MAXIMO_PAGINAS = 400


def _fallo(codigo: str, detalle: str = "") -> ErrorLectura:
    return ErrorLectura(codigo, detalle)


def _no_es_pdf() -> ErrorLectura:
    return _fallo("FORMATO_NO_ADMITIDO", "No se puede leer el PDF: está dañado o no es un PDF.")


def leer_pdf(ruta: Path) -> Lectura:
    """Lee un PDF y devuelve una línea de texto por bloque, con id ``g<página>.<n>``."""
    ruta = Path(ruta)
    try:
        datos = leer_bytes_acotado(ruta, MAXIMO_FICHERO)
    except PermissionError:
        raise _fallo("FICHERO_BLOQUEADO", "El fichero está abierto o bloqueado.") from None
    except FicheroNoSeguro as exc:
        if exc.motivo == "grande":
            raise _fallo("DOCUMENTO_DEMASIADO_GRANDE", "El fichero pasa de 30 MB.") from None
        raise _fallo("FORMATO_NO_ADMITIDO", "No es un fichero normal.") from None
    bloques: list[Bloque] = []
    try:
        lector = PdfReader(io.BytesIO(datos))
        if lector.is_encrypted and not lector.decrypt(""):
            raise _fallo("PDF_PROTEGIDO", "El PDF está protegido con contraseña.")
        paginas = lector.pages
        total = len(paginas)
        if total > MAXIMO_PAGINAS:
            raise _fallo(
                "DOCUMENTO_DEMASIADO_GRANDE", f"El PDF tiene más de {MAXIMO_PAGINAS} páginas."
            )
        for numero in range(total):
            texto = paginas[numero].extract_text() or ""
            n = 0
            for linea in texto.splitlines():
                linea = linea.strip()
                if not linea:
                    continue
                n += 1
                bloques.append(Bloque(id=f"g{numero + 1}.{n}", tipo="parrafo", texto=linea))
    except ErrorLectura:
        raise
    except Exception:  # pypdf lanza errores muy variados con entrada mal formada
        raise _no_es_pdf() from None
    if not bloques:
        raise _fallo("PDF_SIN_TEXTO", "El PDF no tiene texto: parece un escaneado.")
    return Lectura(
        fichero=ruta.name,
        formato="pdf",
        bloques=bloques,
        avisos=["PDF_SIN_TABLAS"],
        sha256=hashlib.sha256(datos).hexdigest(),
        paginas=total,
    )
