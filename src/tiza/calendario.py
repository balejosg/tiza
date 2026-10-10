"""Calendario escolar de la asignatura: avisos de fechas, sin red ni estado.

``calendario.toml`` lo escribe el docente o el agente a partir del calendario
oficial. Es una ayuda: un aviso nunca impide publicar, porque un festivo o un
fin de semana pueden ser intencionados. Lo que el agente escribe se trata como
hostil: se lee acotado y sin seguir enlaces, igual que los demás ficheros de la
carpeta.

Nada de este módulo habla con el aula ni maneja datos del alumnado.
"""

from __future__ import annotations

import os
import re
import tomllib
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import rutas, tipos
from .ficheros import FicheroNoSeguro, leer_bytes_acotado

if TYPE_CHECKING:  # solo para el tipo; contenido no importa este módulo
    from .contenido import Documento

__all__ = [
    "AVISOS",
    "Calendario",
    "ErrorCalendario",
    "avisos",
    "avisos_por_campo",
    "cargar",
    "fechas_del_documento",
]

MAX_BYTES = 64 * 1024
MAX_FESTIVOS = 200
MAX_MOTIVO = 100
AVISOS = ("FECHA_FUERA_DE_CURSO", "FECHA_FESTIVA", "FECHA_FIN_DE_SEMANA", "FECHA_SIN_CLASE")
_CAMPOS = frozenset({"inicio", "fin", "festivos", "dias_de_clase"})
_CAMPOS_FESTIVO = frozenset({"desde", "hasta", "motivo"})
_DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
_NO_IMPRIMIBLE = re.compile(r"[<>\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


class ErrorCalendario(Exception):
    """Error del calendario con un código estable; el detalle es texto de tiza."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


@dataclass(frozen=True)
class Calendario:
    """Calendario ya validado. ``dias_de_clase`` usa 0 = lunes; None: no se avisa."""

    inicio: date | None = None
    fin: date | None = None
    festivos: tuple[tuple[date, date], ...] = ()  # rangos inclusivos (un día: desde == hasta)
    dias_de_clase: frozenset[int] | None = None


def cargar(carpeta: str | Path) -> Calendario | None:
    """El calendario de la carpeta, o None si no hay ``calendario.toml``.

    Raises:
        ErrorCalendario: ``CALENDARIO_INVALIDO`` si existe pero no se puede usar.
    """
    ruta = Path(carpeta) / rutas.FICHERO_CALENDARIO
    if not os.path.lexists(ruta):
        return None
    try:
        texto = leer_bytes_acotado(ruta, MAX_BYTES).decode("utf-8")
    except FicheroNoSeguro as exc:
        raise ErrorCalendario("CALENDARIO_INVALIDO", _motivo_de_lectura(exc.motivo)) from None
    except (OSError, UnicodeDecodeError):
        raise ErrorCalendario("CALENDARIO_INVALIDO", "no se puede leer como UTF-8") from None
    try:
        datos = tomllib.loads(texto)
    except (ValueError, RecursionError):
        # TOMLDecodeError es un ValueError; también lo es un entero de miles de cifras, y
        # una lista anidada miles de veces agota la pila: ninguno puede romper la sesión.
        raise ErrorCalendario("CALENDARIO_INVALIDO", "no es TOML válido") from None
    return _validar(datos)


def _motivo_de_lectura(motivo: str) -> str:
    return {
        "enlace": "es un enlace simbólico",
        "grande": "pasa de 64 KB",
    }.get(motivo, "no es un fichero normal")


def _citar(texto: object) -> str:
    """Lo que escribió el docente o el agente, sin caracteres que el informe no admite."""
    return _NO_IMPRIMIBLE.sub("?", str(texto))[:60]


def _error(detalle: str) -> ErrorCalendario:
    return ErrorCalendario("CALENDARIO_INVALIDO", detalle)


def _validar(datos: dict[str, Any]) -> Calendario:
    for campo in datos:
        if campo not in _CAMPOS:
            raise _error(f"campo «{_citar(campo)}» no permitido")
    inicio = _fecha(datos["inicio"], "inicio") if "inicio" in datos else None
    fin = _fecha(datos["fin"], "fin") if "fin" in datos else None
    if inicio is not None and fin is not None and inicio > fin:
        raise _error("«inicio» debe ser anterior o igual a «fin»")
    festivos = _festivos(datos.get("festivos", []))
    dias = _dias_de_clase(datos["dias_de_clase"]) if "dias_de_clase" in datos else None
    return Calendario(inicio=inicio, fin=fin, festivos=festivos, dias_de_clase=dias)


def _fecha(valor: Any, campo: str) -> date:
    # tomllib da «datetime» para las fechas con hora; aquí solo valen fechas de día.
    if isinstance(valor, datetime) or not isinstance(valor, date):
        raise _error(f"«{campo}» debe ser una fecha AAAA-MM-DD")
    return valor


def _festivos(valor: Any) -> tuple[tuple[date, date], ...]:
    if not isinstance(valor, list):
        raise _error("«festivos» debe ser una lista")
    if len(valor) > MAX_FESTIVOS:
        raise _error(f"«festivos» admite como mucho {MAX_FESTIVOS} entradas")
    rangos: list[tuple[date, date]] = []
    for entrada in valor:
        if isinstance(entrada, dict):
            for campo in entrada:
                if campo not in _CAMPOS_FESTIVO:
                    raise _error(f"campo «{_citar(campo)}» no permitido en un festivo")
            if "desde" not in entrada or "hasta" not in entrada:
                raise _error("un festivo por rango necesita «desde» y «hasta»")
            desde = _fecha(entrada["desde"], "desde")
            hasta = _fecha(entrada["hasta"], "hasta")
            _motivo(entrada.get("motivo"))
        else:
            desde = hasta = _fecha(entrada, "festivos")
        if desde > hasta:
            raise _error("en un festivo, «desde» debe ser anterior o igual a «hasta»")
        rangos.append((desde, hasta))
    return tuple(rangos)


def _motivo(valor: Any) -> None:
    if valor is None:
        return
    if not isinstance(valor, str) or len(valor) > MAX_MOTIVO or _NO_IMPRIMIBLE.search(valor):
        raise _error(f"«motivo» debe ser texto de hasta {MAX_MOTIVO} caracteres")


def _dias_de_clase(valor: Any) -> frozenset[int]:
    if not isinstance(valor, list) or not valor:
        raise _error("«dias_de_clase» debe ser una lista con al menos un día")
    dias: set[int] = set()
    for nombre in valor:
        if not isinstance(nombre, str):
            raise _error("los días de clase deben ser nombres como «lunes»")
        normal = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
        normal = normal.strip().casefold()
        if normal not in _DIAS:
            raise _error(f"día de clase no válido: «{_citar(nombre)}»")
        dias.add(_DIAS.index(normal))
    return frozenset(dias)


def fechas_del_documento(doc: Documento) -> tuple[tuple[str, date, bool], ...]:
    """(campo, día, es_día_de_clase) de las fechas que el calendario revisa.

    La entrega y el cierre son los días en que el alumnado trabaja; la apertura y
    el límite no se exigen en día de clase. Cada tipo lo declara en su adapter.
    """
    return tuple(
        (fecha.campo, fecha.momento.date(), fecha.exige_clase)
        for fecha in tipos.obtener(doc.tipo).fechas(doc)
        if fecha.momento is not None
    )


def avisos(calendario: Calendario | None, dia: date, *, clase: bool) -> tuple[str, ...]:
    """Los avisos de un día, en orden fijo. Sin calendario, ninguno."""
    if calendario is None:
        return ()
    salida: list[str] = []
    fuera = (calendario.inicio is not None and dia < calendario.inicio) or (
        calendario.fin is not None and dia > calendario.fin
    )
    if fuera:
        salida.append("FECHA_FUERA_DE_CURSO")
    if any(desde <= dia <= hasta for desde, hasta in calendario.festivos):
        salida.append("FECHA_FESTIVA")
    if dia.weekday() >= 5:
        salida.append("FECHA_FIN_DE_SEMANA")
    if (
        clase
        and calendario.dias_de_clase is not None
        and dia.weekday() not in calendario.dias_de_clase
    ):
        salida.append("FECHA_SIN_CLASE")
    return tuple(salida)


def avisos_por_campo(calendario: Calendario | None, doc: Documento) -> dict[str, tuple[str, ...]]:
    """Avisos de cada fecha del documento, por nombre de campo («entrega», «cierre»…)."""
    return {
        campo: avisos(calendario, dia, clase=clase)
        for campo, dia, clase in fechas_del_documento(doc)
    }
