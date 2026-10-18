"""Consultas exactas a la fuente de normativa: por código, sin interpretar nada.

Cada consulta devuelve un dataclass de :mod:`.salida` o lanza
:class:`~tiza.normativa.datos.ErrorNormativa`. Las que dependen del curso académico
(de septiembre a agosto) toman ``curso_academico`` (``None`` es el curso en vigor
según ``hoy``, que por defecto es la fecha de hoy en Europe/Madrid) y nunca caen
en silencio a otro curso: si no hay datos del pedido, es ``CURSO_SIN_DATOS`` con los
cursos que sí hay. Todas aceptan ``indice`` para consultar otros datos (los tests).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import TypedDict
from zoneinfo import ZoneInfo

from . import salida
from .datos import ErrorNormativa, Indice, cargar, normalizar_cita
from .modelo import NOMBRE_DEL_RANGO, Elemento, Ficha, Norma, Procedencia

__all__ = [
    "MAX_RESULTADOS",
    "buscar",
    "catalogo",
    "curso_de",
    "elemento",
    "ficha",
    "hoy_en_madrid",
    "norma",
    "programacion",
]

MAX_RESULTADOS = 20
# Etapa de la programación -> ficha que reúne lo que la normativa exige de ella.
_FICHA_DE_PROGRAMACION = {
    "eso": "MAD.ESO.PROG",
    "bachillerato": "MAD.BACH.PROG",
    "fp": "MAD.FP.PROG",
}
_CURSO_ACADEMICO = re.compile(r"(\d{4})-(\d{2})")
_ECO = re.compile(r"[\w .,/#()«»-]{1,80}")  # lo pedido que se puede repetir en un detalle


class _Cabecera(TypedDict):
    version_datos: str
    curso_academico: str
    curso_en_vigor: bool


def hoy_en_madrid() -> date:
    """La fecha de hoy en Europe/Madrid."""
    return datetime.now(ZoneInfo("Europe/Madrid")).date()


def curso_de(fecha: date) -> str:
    """El curso académico de una fecha: de septiembre a agosto («2026-27»)."""
    inicio = fecha.year if fecha.month >= 9 else fecha.year - 1
    return f"{inicio}-{(inicio + 1) % 100:02d}"


# --- consultas ---------------------------------------------------------------


def catalogo(
    curso_academico: str | None = None,
    *,
    hoy: date | None = None,
    indice: Indice | None = None,
) -> salida.Catalogo:
    """Las materias y los módulos de un curso académico, con sus normas."""
    datos = indice or cargar()
    curso, vigente = _curso(curso_academico, hoy, _cursos_de_los_datos(datos))
    fichas = sorted(
        (f for f in datos.fichas.values() if curso in f.cursos_academicos),
        key=lambda f: f.codigo,
    )
    return salida.Catalogo(
        **_cabecera(datos, curso, vigente),
        fichas=tuple(
            salida.FichaResumen(
                codigo=f.codigo,
                nombre=f.nombre,
                etapa=f.etapa,
                curso=f.curso,
                desde=_iso(f.desde),
                normas=tuple(_ref(datos, n) for n in f.normas),
            )
            for f in fichas
        ),
    )


def ficha(
    codigo: str,
    curso_academico: str | None = None,
    *,
    hoy: date | None = None,
    indice: Indice | None = None,
) -> salida.FichaSalida:
    """Todos los elementos de una materia o módulo, con su texto y su procedencia."""
    datos = indice or cargar()
    f = _ficha_de(datos, codigo)
    curso, vigente = _curso(curso_academico, hoy, f.cursos_academicos)
    return salida.FichaSalida(
        **_cabecera(datos, curso, vigente),
        codigo=f.codigo,
        nombre=f.nombre,
        etapa=f.etapa,
        curso=f.curso,
        desde=_iso(f.desde),
        normas=tuple(_ref(datos, n) for n in f.normas),
        elementos=tuple(_fragmento(datos, e) for e in f.elementos),
    )


def elemento(
    codigo: str,
    curso_academico: str | None = None,
    *,
    hoy: date | None = None,
    indice: Indice | None = None,
) -> salida.ElementoSalida:
    """Un elemento por su código, con su texto, su procedencia y sus relaciones."""
    datos = indice or cargar()
    if codigo not in datos.elementos:
        raise ErrorNormativa(
            "CODIGO_DESCONOCIDO", f"No hay ningún elemento con el código {_eco(codigo)}."
        )
    f, e = datos.elementos[codigo]
    curso, vigente = _curso(curso_academico, hoy, f.cursos_academicos)
    return salida.ElementoSalida(
        **_cabecera(datos, curso, vigente),
        ficha=f.codigo,
        desde=_iso(f.desde),
        elemento=_fragmento(datos, e),
    )


def _nombre_oficial(rango: str) -> str:
    """«Real Decreto», «Decreto»… en título; «Corrección de errores», solo con la inicial."""
    nombre = NOMBRE_DEL_RANGO[rango]
    return nombre[:1].upper() + nombre[1:] if rango == "correccion" else nombre.title()


def norma(
    cita: str,
    *,
    hoy: date | None = None,
    indice: Indice | None = None,
) -> salida.NormaSalida:
    """Una norma por su cita libre («Decreto 27/2025», «RD 405/2023»…).

    No depende del curso: la cabecera lleva el curso académico de ``hoy``. Si la cita
    es una errata publicada de la norma, ``cita_pedida`` y ``cita_correcta`` lo dicen.
    """
    datos = indice or cargar()
    if not datos.normas:
        raise ErrorNormativa("NORMATIVA_SIN_DATOS", "La fuente de normativa no trae normas.")
    clave = normalizar_cita(cita)
    id_ = datos.alias.get(clave)
    if id_ is None:
        raise ErrorNormativa("NORMA_DESCONOCIDA", f"No hay ninguna norma con la cita {_eco(cita)}.")
    n = datos.normas[id_]
    nombre = f"{NOMBRE_DEL_RANGO[n.rango]} {n.numero}"
    canonicas = {normalizar_cita(nombre)}
    if n.rango == "real_decreto":
        canonicas.add(normalizar_cita(f"rd {n.numero}"))
    pedida = None
    correcta = None
    if clave not in canonicas:
        pedida = next(c for c in n.citas if normalizar_cita(c) == clave)
        # el estilo oficial: «Decreto 27/2025», «Orden 5/2025», «Real Decreto 1/2024»
        correcta = f"{_nombre_oficial(n.rango)} {n.numero}"
    vigente = curso_de(hoy or hoy_en_madrid())
    return salida.NormaSalida(
        **_cabecera(datos, vigente, True),
        id=n.id,
        rango=n.rango,
        numero=n.numero,
        fecha=n.fecha.isoformat(),
        titulo=n.titulo,
        boletin=n.boletin,
        url_pdf=n.url_pdf,
        url_api=n.url_api,
        estado=n.estado,
        derogada_por=None if n.derogada_por is None else _ref(datos, n.derogada_por),
        desde=_iso(n.desde),
        correcciones=tuple(_correccion(datos, c) for c in n.correcciones),
        modifica=tuple(_ref(datos, m) for m in n.modifica),
        modificada_por=tuple(_ref(datos, m) for m in n.modificada_por),
        derogaciones_parciales=n.derogaciones_parciales,
        cita_pedida=pedida,
        cita_correcta=correcta,
    )


def buscar(
    texto: str,
    codigo_ficha: str | None = None,
    curso_academico: str | None = None,
    *,
    hoy: date | None = None,
    indice: Indice | None = None,
) -> salida.Resultados:
    """Búsqueda de texto simple: todas las palabras, sin tildes ni mayúsculas.

    Mira el texto de los elementos de una ficha o de todas las del curso; devuelve
    como mucho :data:`MAX_RESULTADOS` y ``total`` dice cuántos había.
    """
    datos = indice or cargar()
    palabras = _plano(texto).split()
    if not palabras:
        raise ErrorNormativa("TEXTO_VACIO", "Falta el texto que buscar.")
    if codigo_ficha is None:
        curso, vigente = _curso(curso_academico, hoy, _cursos_de_los_datos(datos))
        fichas = sorted(
            (f for f in datos.fichas.values() if curso in f.cursos_academicos),
            key=lambda f: f.codigo,
        )
    else:
        una = _ficha_de(datos, codigo_ficha)
        curso, vigente = _curso(curso_academico, hoy, una.cursos_academicos)
        fichas = [una]
    hallados = [
        (f, e) for f in fichas for e in f.elementos if all(p in _plano(e.texto) for p in palabras)
    ]
    return salida.Resultados(
        **_cabecera(datos, curso, vigente),
        total=len(hallados),
        resultados=tuple(
            salida.Resultado(
                codigo=e.codigo,
                ficha=f.codigo,
                tipo=e.tipo,
                texto=e.texto,
                procedencia=_procedencia(datos, e.procedencia),
            )
            for f, e in hallados[:MAX_RESULTADOS]
        ),
    )


def programacion(
    etapa: str,
    curso_academico: str | None = None,
    *,
    hoy: date | None = None,
    indice: Indice | None = None,
) -> salida.Requisitos:
    """Lo que la normativa exige de la programación de una etapa (``eso``, ``bachillerato``, ``fp``)."""
    datos = indice or cargar()
    clave = etapa.strip().lower()
    if clave not in _FICHA_DE_PROGRAMACION:
        raise ErrorNormativa(
            "ETAPA_DESCONOCIDA",
            f"La etapa {_eco(etapa)} no es una de las admitidas.",
            tuple(_FICHA_DE_PROGRAMACION),
        )
    f = _ficha_de(datos, _FICHA_DE_PROGRAMACION[clave])
    curso, vigente = _curso(curso_academico, hoy, f.cursos_academicos)
    requisitos = tuple(
        _fragmento(datos, e) for e in f.elementos if e.tipo == "requisito_programacion"
    )
    if not requisitos:
        raise ErrorNormativa(
            "NORMATIVA_SIN_DATOS",
            f"La ficha {_eco(f.codigo)} no trae ningún requisito de la programación.",
        )
    return salida.Requisitos(
        **_cabecera(datos, curso, vigente),
        etapa=clave,
        ficha=f.codigo,
        requisitos=requisitos,
    )


# --- piezas comunes ------------------------------------------------------------


def _eco(valor: str) -> str:
    """Lo pedido, para repetirlo en un detalle: solo si es corto y sin caracteres raros."""
    return f"«{valor}»" if _ECO.fullmatch(valor) else "pedido (no se puede mostrar)"


def _iso(fecha: date | None) -> str | None:
    return None if fecha is None else fecha.isoformat()


def _plano(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar."""
    base = unicodedata.normalize("NFD", texto)
    return "".join(c for c in base if not unicodedata.combining(c)).casefold()


def _ficha_de(datos: Indice, codigo: str) -> Ficha:
    if codigo not in datos.fichas:
        raise ErrorNormativa(
            "NORMATIVA_SIN_DATOS",
            f"La fuente de normativa no trae la ficha {_eco(codigo)}.",
            tuple(sorted(datos.fichas)),
        )
    return datos.fichas[codigo]


def _cursos_de_los_datos(datos: Indice) -> tuple[str, ...]:
    if not datos.fichas:
        raise ErrorNormativa("NORMATIVA_SIN_DATOS", "La fuente de normativa no trae fichas.")
    return tuple(sorted({c for f in datos.fichas.values() for c in f.cursos_academicos}))


def _curso(pedido: str | None, hoy: date | None, disponibles: tuple[str, ...]) -> tuple[str, bool]:
    """El curso a responder y si es el que está en vigor; sin datos de él, ``CURSO_SIN_DATOS``."""
    vigente = curso_de(hoy or hoy_en_madrid())
    curso = vigente if pedido is None else pedido
    if curso not in disponibles:
        motivo = "" if _CURSO_ACADEMICO.fullmatch(curso) else " (debe ser como «2026-27»)"
        raise ErrorNormativa(
            "CURSO_SIN_DATOS",
            f"No hay datos del curso académico {_eco(curso)}{motivo}.",
            tuple(sorted(disponibles)),
        )
    return curso, curso == vigente


def _cabecera(datos: Indice, curso: str, en_vigor: bool) -> _Cabecera:
    if not datos.normas:
        raise ErrorNormativa("NORMATIVA_SIN_DATOS", "La fuente de normativa no trae normas.")
    revision = max(n.revisada for n in datos.normas.values())
    return _Cabecera(
        version_datos=revision.isoformat(), curso_academico=curso, curso_en_vigor=en_vigor
    )


def _ref(datos: Indice, id_: str) -> salida.NormaRef:
    n: Norma = datos.normas[id_]
    return salida.NormaRef(
        id=n.id,
        rango=n.rango,
        numero=n.numero,
        fecha=n.fecha.isoformat(),
        boletin=n.boletin,
        url=n.url_pdf,
    )


def _correccion(datos: Indice, referencia: str) -> salida.CorreccionSalida:
    id_, _, fragmento = referencia.partition("#")
    return salida.CorreccionSalida(norma=_ref(datos, id_), fragmento=fragmento or None)


def _procedencia(datos: Indice, p: Procedencia) -> salida.ProcedenciaSalida:
    return salida.ProcedenciaSalida(
        norma=_ref(datos, p.norma),
        ubicacion=p.ubicacion,
        pagina=p.pagina,
        via=tuple(_procedencia(datos, v) for v in p.via),
    )


def _fragmento(datos: Indice, e: Elemento) -> salida.Fragmento:
    relaciones: dict[str, tuple[salida.RelacionSalida, ...]] = {}
    for nombre, codigos in e.relaciones.items():
        relaciones[nombre] = tuple(
            salida.RelacionSalida(
                codigo=otro.codigo,
                ficha=de.codigo,
                tipo=otro.tipo,
                texto=otro.texto,
            )
            for de, otro in (datos.elementos[c] for c in codigos)
        )
    return salida.Fragmento(
        codigo=e.codigo,
        tipo=e.tipo,
        texto=e.texto,
        procedencia=_procedencia(datos, e.procedencia),
        padre=e.padre,
        orden=e.orden,
        datos=dict(e.datos),
        relaciones=relaciones,
    )
