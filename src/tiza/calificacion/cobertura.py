"""Mapa de cobertura del calificador: qué evalúa cada hoja, con qué y con qué regla.

Es puro y offline: reutiliza las actividades que ya valida :mod:`tiza.calificacion.deseado`
(sin repetir la validación) y el reparto de pesos que ve ``tiza comprobar``. El mapa incluye
**todas** las hojas del esquema, también las que no tienen ninguna evidencia, para que el agente
pueda enseñar los huecos antes de montar nada.

El instrumento se deduce de lo que ya declara el documento o la casilla manual (D-F1-6); no hay
un campo nuevo en el frontmatter.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tiza.calificacion.deseado import (
    _Actividad,
    _actividades,
    _hojas,
    _ruta_relativa,
    reparto_por_hoja,
)
from tiza.calificacion.esquema import Criterio, Elemento, Esquema
from tiza.contenido import Documento
from tiza.estado import texto_guardado

__all__ = [
    "Cobertura",
    "Evidencia",
    "HojaCobertura",
    "INSTRUMENTOS",
    "avisos",
    "cobertura",
]

INSTRUMENTOS = (
    "tarea_rubrica_criterios",
    "tarea_rubrica_filas",
    "tarea_resultados",
    "tarea",
    "cuestionario",
    "h5p",
    "casilla_manual",
)


@dataclass(frozen=True)
class Evidencia:
    """Una actividad (o casilla manual) que evalúa una hoja.

    ``evaluacion`` es 1-based, como la nombra el docente. ``peso`` es el porcentaje normalizado de
    ``reparto_por_hoja``. ``recupera`` son las evaluaciones que recupera; vacío si no recupera.
    """

    ruta: str
    nombre: str
    instrumento: str
    evaluacion: int
    peso: float
    recupera: tuple[int, ...] = ()


@dataclass(frozen=True)
class HojaCobertura:
    """Un criterio o un elemento sin criterios, con sus evidencias y su regla."""

    id: str
    codigo: str | None
    nombre: str
    elemento: str
    regla: str
    evidencias: tuple[Evidencia, ...]


@dataclass(frozen=True)
class Cobertura:
    """El mapa completo: la etapa, las evaluaciones y una hoja por criterio, en orden."""

    etapa: str | None
    evaluaciones: tuple[tuple[int, str, bool], ...]  # (número 1-based, nombre, cerrada)
    hojas: tuple[HojaCobertura, ...]

    def como_dict(self) -> dict:
        """La forma que valida y escribe :func:`tiza.estado.escribir_cobertura`."""
        return {
            "etapa": self.etapa,
            "evaluaciones": [
                {"numero": numero, "nombre": texto_guardado(nombre), "cerrada": cerrada}
                for numero, nombre, cerrada in self.evaluaciones
            ],
            "hojas": [
                {
                    "id": hoja.id,
                    "codigo": texto_guardado(hoja.codigo) if hoja.codigo is not None else None,
                    "nombre": texto_guardado(hoja.nombre),
                    "elemento": hoja.elemento,
                    "regla": hoja.regla,
                    "evidencias": [
                        {
                            "ruta": evidencia.ruta,
                            "nombre": texto_guardado(evidencia.nombre),
                            "instrumento": evidencia.instrumento,
                            "evaluacion": evidencia.evaluacion,
                            "peso": evidencia.peso,
                            "recupera": list(evidencia.recupera),
                        }
                        for evidencia in hoja.evidencias
                    ],
                }
                for hoja in self.hojas
            ],
        }


def cobertura(esquema: Esquema, documentos: list[Documento], carpeta: Path) -> Cobertura:
    """El mapa de cobertura del esquema con las actividades de la carpeta.

    Reutiliza la validación de :func:`tiza.calificacion.deseado.deseado`: si una actividad no
    cuadra con el esquema, lanza el mismo ``ErrorCalificacion``. Las evidencias van en el orden
    estable de ``deseado._actividades`` (ruta relativa) y los pesos, en el de ``reparto_por_hoja``.
    """
    raiz = Path(carpeta)
    actividades = _actividades(esquema, documentos, raiz)
    por_ruta = {_ruta_relativa(documento.ruta, raiz): documento for documento in documentos}
    reparto = dict(reparto_por_hoja(esquema, documentos, raiz))
    hojas: list[HojaCobertura] = []
    for id_hoja, id_elemento in _hojas(esquema):
        elemento, criterio = _datos_de_hoja(esquema, id_hoja)
        de_hoja = [actividad for actividad in actividades if id_hoja in dict(actividad.evalua)]
        pesos = reparto.get(id_hoja, ())
        if len(pesos) != len(de_hoja):  # defensa: reparto y actividades salen del mismo cálculo
            raise AssertionError(f"el reparto de {id_hoja} no coincide con sus actividades")
        evidencias = tuple(
            Evidencia(
                ruta=_ruta_de_actividad(esquema, actividad),
                nombre=texto_guardado(actividad.nombre),
                instrumento=_instrumento(actividad, por_ruta),
                evaluacion=actividad.evaluacion + 1,
                peso=peso,
                recupera=actividad.recupera,
            )
            for actividad, (_, peso) in zip(de_hoja, pesos, strict=True)
        )
        hojas.append(
            HojaCobertura(
                id=id_hoja,
                codigo=criterio.codigo if criterio is not None else elemento.codigo,
                nombre=criterio.nombre if criterio is not None else elemento.nombre,
                elemento=id_elemento,
                regla=esquema.regla_de(id_hoja),
                evidencias=evidencias,
            )
        )
    return Cobertura(
        etapa=esquema.etapa,
        evaluaciones=tuple(
            (numero, evaluacion.nombre, evaluacion.cerrada)
            for numero, evaluacion in enumerate(esquema.evaluaciones, 1)
        ),
        hojas=tuple(hojas),
    )


def avisos(cobertura: Cobertura, esquema: Esquema) -> tuple[tuple[str, str], ...]:
    """Los huecos de D-F1-4, como pares ``(código, detalle)`` ordenados.

    Una recuperación no cuenta como evidencia: no tapa el hueco de una hoja ni convierte una
    única evidencia en dos. Los avisos son informativos: no impiden montar el calificador.
    """
    salida: list[tuple[str, str]] = []
    for hoja in cobertura.hojas:
        evidencias = [evidencia for evidencia in hoja.evidencias if not evidencia.recupera]
        if not evidencias:
            salida.append(("HOJA_SIN_EVIDENCIAS", hoja.id))
        elif len(evidencias) == 1:
            salida.append(("HOJA_CON_UNA_EVIDENCIA", f"{hoja.id}: {evidencias[0].nombre}"))
        regla = esquema.regla_de(hoja.id)
        if regla == "mediana" and len(evidencias) < 3:
            salida.append(
                ("MEDIANA_CON_POCAS_EVIDENCIAS", f"{hoja.id}: {len(evidencias)} evidencias")
            )
        if regla == "progresiva" and evidencias:
            evaluaciones = {evidencia.evaluacion for evidencia in evidencias}
            if len(evaluaciones) == 1:
                salida.append(
                    (
                        "PROGRESIVA_EN_UNA_EVALUACION",
                        f"{hoja.id}: evaluación {evidencias[0].evaluacion}",
                    )
                )
    return tuple(sorted(salida))


def _datos_de_hoja(esquema: Esquema, id_hoja: str) -> tuple[Elemento, Criterio | None]:
    for elemento in esquema.elementos:
        if elemento.criterios:
            for criterio in elemento.criterios:
                if criterio.id == id_hoja:
                    return elemento, criterio
        elif elemento.id == id_hoja:
            return elemento, None
    raise AssertionError(f"«{id_hoja}» no es una hoja del esquema")


def _ruta_de_actividad(esquema: Esquema, actividad: _Actividad) -> str:
    """La ruta del documento o ``instrumentos[<n>]`` en una casilla manual."""
    if not actividad.manual:
        return actividad.ruta
    prefijo = "TZ_M_"
    id_ = actividad.ruta.removeprefix(prefijo)
    for indice, instrumento in enumerate(esquema.instrumentos):
        if instrumento.id == id_:
            return f"instrumentos[{indice}]"
    return actividad.ruta


def _instrumento(actividad: _Actividad, por_ruta: dict[str, Documento]) -> str:
    """El instrumento deducido (D-F1-6): lo que ya declara la actividad, sin campo nuevo."""
    if actividad.manual:
        return "casilla_manual"
    documento = por_ruta.get(actividad.ruta)
    if documento is None:
        return "tarea"
    if documento.tipo == "cuestionario":
        return "cuestionario"
    if documento.tipo == "h5p":
        return "h5p"
    if documento.tipo == "tarea":
        if documento.evidencia == "resultados":
            return "tarea_resultados"
        if documento.rubrica is not None:
            if any(criterio.criterio is not None for criterio in documento.rubrica.criterios):
                return "tarea_rubrica_filas"
            return "tarea_rubrica_criterios"
        return "tarea"
    return "tarea"
