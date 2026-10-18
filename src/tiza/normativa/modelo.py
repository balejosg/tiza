"""Modelo de la fuente de normativa: dataclasses congeladas, sin lógica de carga.

Una *norma* es una disposición publicada (con su PDF y su huella); una *ficha* es
una materia o un módulo con sus *elementos* (competencias, criterios, resultados
de aprendizaje…), y cada elemento dice de qué norma sale su texto
(:class:`Procedencia`). La carga y la validación viven en :mod:`.datos`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

__all__ = [
    "BOLETINES",
    "DATOS_POR_TIPO",
    "ESTADOS",
    "ETAPAS",
    "Elemento",
    "Ficha",
    "Norma",
    "Procedencia",
    "NOMBRE_DEL_RANGO",
    "RANGOS",
    "TIPOS_ELEMENTO",
]

RANGOS = ("real_decreto", "decreto", "orden", "resolucion", "correccion")
NOMBRE_DEL_RANGO = {
    "real_decreto": "real decreto",
    "decreto": "decreto",
    "orden": "orden",
    "resolucion": "resolución",
    "correccion": "corrección de errores",
}
BOLETINES = ("BOE", "BOCM", "CM")  # CM: el portal de la comunidad, no un boletín
ESTADOS = ("vigente", "derogada")
ETAPAS = ("eso", "bachillerato", "fp_gs")

# Los datos de cada tipo de elemento son un dict cerrado: aquí, la tabla única de
# las claves permitidas y del tipo de su valor. Un tipo sin datos propios queda vacío.
# Un campo ausente significa «sin dato» en el boletín, no cero (los optativos transversales
# no traen horas): nunca se rellena con un valor inventado.
DATOS_POR_TIPO: dict[str, dict[str, type]] = {
    "competencia_especifica": {},
    "descriptor": {},
    "criterio": {},
    "bloque_contenidos": {},
    "contenido": {},
    "orientaciones": {},
    "titulo": {},
    "competencia_general": {},
    "competencia_profesional": {},
    "objetivo_general": {},
    "modulo": {"horas": int, "curso": str},
    "resultado_aprendizaje": {},
    "criterio_fp": {},
    "contenido_basico": {},
    "requisito_programacion": {},
}
TIPOS_ELEMENTO = tuple(DATOS_POR_TIPO)


@dataclass(frozen=True)
class Procedencia:
    """De dónde sale un texto: la norma y el lugar exacto de la norma.

    ``via`` está vacía salvo en un texto modificado: entonces ``norma`` es la que lo
    modifica y ``via`` nombra el lugar de la norma original.
    """

    norma: str
    ubicacion: str
    pagina: int | None
    via: tuple[Procedencia, ...] = ()


@dataclass(frozen=True)
class Norma:
    """Una disposición publicada, con la huella de su PDF y la fecha de su revisión.

    ``id`` es la referencia del boletín en minúsculas (``bocm-20230531-18``).
    ``correcciones`` puede llevar un sufijo ``#fragmento`` cuando la corrección es
    de una disposición concreta de otra norma. ``citas`` son otros nombres con los
    que se conoce la norma, erratas publicadas incluidas.
    """

    id: str
    rango: str
    numero: str
    fecha: date
    titulo: str
    boletin: str
    url_pdf: str
    url_api: str | None
    sha256: str
    correcciones: tuple[str, ...]
    modifica: tuple[str, ...]
    modificada_por: tuple[str, ...]
    estado: str
    derogada_por: str | None
    desde: date | None
    derogaciones_parciales: tuple[str, ...]
    citas: tuple[str, ...]
    revisada: date


@dataclass(frozen=True)
class Elemento:
    """Un fragmento citable de una ficha, con su código estable y su procedencia."""

    codigo: str
    tipo: str
    texto: str
    procedencia: Procedencia
    padre: str | None
    relaciones: dict[str, tuple[str, ...]] = field(default_factory=dict)
    orden: int = 0
    datos: dict[str, int | str] = field(default_factory=dict)


@dataclass(frozen=True)
class Ficha:
    """Una materia o un módulo: sus elementos, en orden, y dónde y cuándo rige.

    ``desde``: si la ficha solo rige en sus cursos académicos a partir de esa fecha.
    """

    codigo: str
    nombre: str
    etapa: str
    curso: str | None
    cursos_academicos: tuple[str, ...]
    normas: tuple[str, ...]
    elementos: tuple[Elemento, ...]
    desde: date | None = None
