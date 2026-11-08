"""Formato de ``calificacion.yaml`` y su validación (esquema cerrado, offline).

El agente describe cómo se calcula la nota final: qué elementos (resultados de aprendizaje o
criterios) y qué evaluaciones hay, cuánto pesa cada uno y, si hace falta, un tope. No hay
lenguaje de fórmulas. Los errores llevan la ruta YAML de lo que falla
(``elementos[1].peso``) y su línea.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

from tiza.contenido import id_evalua_valido, peso_evalua_valido
from tiza.escritura import ErrorEscritura
from tiza.escritura.relleno import cargar_yaml_sin_alias, dentro_de_la_carpeta

__all__ = [
    "Agregacion",
    "ErrorCalificacion",
    "Criterio",
    "Elemento",
    "Esquema",
    "Evaluacion",
    "Final",
    "Instrumento",
    "NivelRubrica",
    "REGLAS",
    "Tope",
    "cargar_esquema",
    "comprobar_niveles_equidistantes",
]

EXTENSIONES_ESQUEMA = frozenset({".yaml"})
TOLERANCIA_PESOS = 0.01
ETAPAS = ("primaria", "eso", "bachillerato", "fp")
MAX_NIVELES_RUBRICA = 10
REGLAS = ("media", "mediana", "mas_alta", "progresiva")
_REQUERIDAS_INSTRUMENTO = ("id", "nombre", "seccion", "evalua")
_PERMITIDAS_INSTRUMENTO = (*_REQUERIDAS_INSTRUMENTO, "recupera")


class ErrorCalificacion(Exception):
    """Error del calificador con un código estable; el detalle es texto de tiza."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


@dataclass(frozen=True)
class NivelRubrica:
    """Un nivel de la rúbrica por criterios, con su porcentaje del total de la fila."""

    id: str
    nombre: str
    porcentaje: float


NIVELES_RUBRICA = (
    NivelRubrica("destacado", "Destacado", 100.0),
    NivelRubrica("avanzado", "Avanzado", 75.0),
    NivelRubrica("adecuado", "Adecuado", 50.0),
    NivelRubrica("inicial", "Inicial", 25.0),
    NivelRubrica("no_iniciado", "No iniciado", 0.0),
)


@dataclass(frozen=True)
class Agregacion:
    """Cómo se combinan las evidencias de cada hoja y los factores de la progresiva."""

    regla: str = "media"
    factores: tuple[float, ...] = ()


@dataclass(frozen=True)
class Criterio:
    id: str
    nombre: str
    peso: float | None
    codigo: str | None = None
    regla: str | None = None


@dataclass(frozen=True)
class Elemento:
    id: str
    nombre: str
    peso: float
    codigo: str | None = None
    criterios: tuple[Criterio, ...] = ()
    regla: str | None = None


@dataclass(frozen=True)
class Instrumento:
    """Casilla manual: no tiene actividad en el aula, solo sección y qué elementos evalúa."""

    id: str
    nombre: str
    seccion: int | str
    evalua: tuple[tuple[str, float], ...]
    recupera: tuple[int, ...] | None = None


@dataclass(frozen=True)
class Evaluacion:
    nombre: str
    secciones: tuple[int | str, ...]
    peso: float | None = None
    cerrada: bool = False


@dataclass(frozen=True)
class Tope:
    si_alguno_menor_que: float
    maximo: float


@dataclass(frozen=True)
class Final:
    de: str
    tope: Tope | None = None


@dataclass(frozen=True)
class Esquema:
    organizacion: str
    elementos: tuple[Elemento, ...]
    evaluaciones: tuple[Evaluacion, ...]
    final: Final
    instrumentos: tuple[Instrumento, ...] = ()
    etapa: str | None = None
    niveles_rubrica: tuple[NivelRubrica, ...] = NIVELES_RUBRICA
    actividades_pesan_igual: bool = False
    agregacion: Agregacion = field(default_factory=Agregacion)

    def regla_de(self, hoja: str) -> str:
        """La regla de una hoja (criterio o elemento sin criterios) o la general.

        Un elemento con criterios no contagia su regla a los criterios: la regla va en el
        elemento sin criterios o en cada criterio.
        """
        for elemento in self.elementos:
            if elemento.criterios:
                for criterio in elemento.criterios:
                    if criterio.id == hoja:
                        return criterio.regla or self.agregacion.regla
            elif elemento.id == hoja:
                return elemento.regla or self.agregacion.regla
        return self.agregacion.regla


class _Lector:
    """Valida con la ruta YAML y la línea de lo que falla."""

    def __init__(self, lineas: dict[str, int]) -> None:
        self.lineas = lineas

    def error(self, codigo: str, ruta: str, motivo: str) -> ErrorCalificacion:
        linea = self.lineas.get(ruta)
        donde = f" (línea {linea})" if linea is not None else ""
        return ErrorCalificacion(codigo, f"{ruta}: {motivo}{donde}" if ruta else f"{motivo}{donde}")

    def invalido(self, ruta: str, motivo: str) -> ErrorCalificacion:
        return self.error("ESQUEMA_INVALIDO", ruta, motivo)

    def mapa(
        self, valor: Any, ruta: str, permitidas: tuple[str, ...], requeridas: tuple[str, ...]
    ) -> dict[str, Any]:
        if not isinstance(valor, dict):
            raise self.invalido(ruta, "debe ser un bloque de claves («clave: valor»)")
        for clave in valor:
            if not isinstance(clave, str):
                raise self.invalido(ruta, "tiene una clave que no es texto")
            if clave not in permitidas:
                hija = f"{ruta}.{clave}" if ruta else clave
                raise self.invalido(hija, f"clave desconocida; válidas: {', '.join(permitidas)}")
        for clave in requeridas:
            if clave not in valor:
                raise self.invalido(ruta, f"falta la clave «{clave}»")
        return valor

    def lista(self, valor: Any, ruta: str) -> list[Any]:
        if not isinstance(valor, list) or not valor:
            raise self.invalido(ruta, "debe ser una lista con al menos un elemento")
        return valor

    def texto(self, valor: Any, ruta: str) -> str:
        if not isinstance(valor, str) or not valor.strip():
            raise self.invalido(ruta, "debe ser un texto no vacío")
        return valor.strip()

    def numero(self, valor: Any, ruta: str) -> float:
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise self.invalido(ruta, "debe ser un número")
        if abs(valor) > 1e6:
            raise self.invalido(ruta, "es un número demasiado grande")
        if not math.isfinite(valor):
            raise self.invalido(ruta, "debe ser un número finito")
        if abs(valor * 100 - round(valor * 100)) > 1e-6:
            raise self.invalido(ruta, "admite como mucho 2 decimales")
        return float(valor)

    def peso(self, valor: Any, ruta: str) -> float:
        numero = self.numero(valor, ruta)
        if numero <= 0:
            raise self.invalido(ruta, "debe ser mayor que 0")
        return numero

    def regla(self, valor: Any, ruta: str) -> str:
        if not isinstance(valor, str) or valor not in REGLAS:
            raise self.invalido(ruta, f"debe ser una de {', '.join(REGLAS)}")
        return valor

    def agregacion(self, valor: Any) -> Agregacion:
        datos = self.mapa(valor, "agregacion", ("regla", "factores"), ())
        regla = self.regla(datos["regla"], "agregacion.regla") if "regla" in datos else "media"
        factores: tuple[float, ...] = ()
        if "factores" in datos:
            crudos = datos["factores"]
            if not isinstance(crudos, list):
                raise self.invalido("agregacion.factores", "debe ser una lista de factores")
            # Una lista vacía es válida aquí: «sin factores» lo decide _comprobar_reglas con la
            # regla de cada hoja (PROGRESIVA_SIN_FACTORES), no la forma del YAML.
            salida: list[float] = []
            for i, bruto in enumerate(crudos):
                ruta = f"agregacion.factores[{i}]"
                factor = self.peso(bruto, ruta)
                if factor > 100:
                    raise self.invalido(ruta, "debe ser como mucho 100")
                salida.append(factor)
            factores = tuple(salida)
        return Agregacion(regla, factores)

    def recupera(self, valor: Any, ruta: str) -> tuple[int, ...]:
        """Un número de evaluación o una lista no vacía de números distintos (1-based)."""
        if isinstance(valor, bool):
            raise self.invalido(ruta, "debe ser un número de evaluación o una lista de números")
        if isinstance(valor, int):
            if valor < 1:
                raise self.invalido(ruta, "debe ser un número de evaluación mayor que 0")
            return (valor,)
        if isinstance(valor, list):
            if not valor:
                raise self.invalido(ruta, "debe ser una lista con al menos un número de evaluación")
            salida: list[int] = []
            for i, item in enumerate(valor):
                destino = f"{ruta}[{i}]"
                if isinstance(item, bool) or not isinstance(item, int) or item < 1:
                    raise self.invalido(destino, "debe ser un número de evaluación mayor que 0")
                salida.append(item)
            if len(salida) != len(set(salida)):
                raise self.invalido(ruta, "no puede repetir números de evaluación")
            return tuple(salida)
        raise self.invalido(ruta, "debe ser un número de evaluación o una lista de números")

    def suman_100(self, pesos: list[float], ruta: str) -> None:
        total = sum(pesos)
        if abs(total - 100) > TOLERANCIA_PESOS:
            raise self.error(
                "PESOS_NO_SUMAN_100", ruta, f"los pesos de {ruta} suman {total:g} y deben sumar 100"
            )

    def id_(self, valor: Any, ruta: str) -> str:
        if not id_evalua_valido(valor):
            raise self.invalido(
                ruta,
                "debe empezar por una letra y tener solo letras, cifras o _ (16 como mucho)",
            )
        return valor

    def etapa(self, valor: Any) -> str | None:
        if valor is None:
            return None
        if not isinstance(valor, str) or valor not in ETAPAS:
            raise self.invalido("etapa", "debe ser primaria, eso, bachillerato o fp")
        return valor

    def niveles_rubrica(self, valor: Any) -> tuple[NivelRubrica, ...]:
        if not isinstance(valor, list) or not 2 <= len(valor) <= MAX_NIVELES_RUBRICA:
            raise self.invalido(
                "niveles_rubrica", f"debe ser una lista de 2 a {MAX_NIVELES_RUBRICA} niveles"
            )
        resultado: list[NivelRubrica] = []
        vistos: set[str] = set()
        porcentajes: list[float] = []
        for i, bruto in enumerate(valor):
            ruta = f"niveles_rubrica[{i}]"
            datos = self.mapa(
                bruto,
                ruta,
                ("id", "nombre", "porcentaje"),
                ("id", "nombre", "porcentaje"),
            )
            id_ = self.id_(datos["id"], f"{ruta}.id")
            if id_ in vistos:
                raise self.error("ID_REPETIDO", f"{ruta}.id", f"el id «{id_}» está repetido")
            vistos.add(id_)
            nombre = self.texto(datos["nombre"], f"{ruta}.nombre")
            porcentaje = self.numero(datos["porcentaje"], f"{ruta}.porcentaje")
            if not 0 <= porcentaje <= 100:
                raise self.invalido(f"{ruta}.porcentaje", "debe estar entre 0 y 100")
            if porcentaje in porcentajes:
                raise self.invalido(f"{ruta}.porcentaje", "no puede repetirse")
            porcentajes.append(porcentaje)
            resultado.append(NivelRubrica(id_, nombre, porcentaje))
        if 0 not in porcentajes:
            raise self.invalido("niveles_rubrica", "debe incluir un nivel con el 0 %")
        if 100 not in porcentajes:
            raise self.invalido("niveles_rubrica", "debe incluir un nivel con el 100 %")
        return tuple(resultado)

    def booleano(self, valor: Any, ruta: str) -> bool:
        if not isinstance(valor, bool):
            raise self.invalido(ruta, "debe ser true o false")
        return valor

    def elementos(self, valor: Any) -> tuple[Elemento, ...]:
        resultado: list[Elemento] = []
        vistos: set[str] = set()  # ids de elementos y de criterios, en un solo espacio
        for i, bruto in enumerate(self.lista(valor, "elementos")):
            ruta = f"elementos[{i}]"
            datos = self.mapa(
                bruto,
                ruta,
                ("id", "nombre", "peso", "codigo", "criterios", "regla"),
                ("id", "nombre", "peso"),
            )
            id_ = self.id_(datos["id"], f"{ruta}.id")
            if id_ in vistos:
                raise self.error("ID_REPETIDO", f"{ruta}.id", f"el id «{id_}» está repetido")
            vistos.add(id_)
            codigo = self.texto(datos["codigo"], f"{ruta}.codigo") if "codigo" in datos else None
            criterios = (
                self.criterios(datos["criterios"], f"{ruta}.criterios", vistos)
                if "criterios" in datos
                else ()
            )
            regla = self.regla(datos["regla"], f"{ruta}.regla") if "regla" in datos else None
            if regla is not None and criterios:
                raise self.invalido(
                    f"{ruta}.regla",
                    "la regla de un elemento con criterios va en el elemento sin criterios "
                    "o en cada criterio",
                )
            resultado.append(
                Elemento(
                    id_,
                    self.texto(datos["nombre"], f"{ruta}.nombre"),
                    self.peso(datos["peso"], f"{ruta}.peso"),
                    codigo,
                    criterios,
                    regla,
                )
            )
        return tuple(resultado)

    def criterios(self, valor: Any, ruta: str, vistos: set[str]) -> tuple[Criterio, ...]:
        resultado: list[Criterio] = []
        for j, bruto in enumerate(self.lista(valor, ruta)):
            destino = f"{ruta}[{j}]"
            datos = self.mapa(
                bruto, destino, ("id", "nombre", "peso", "codigo", "regla"), ("id", "nombre")
            )
            id_ = self.id_(datos["id"], f"{destino}.id")
            if id_ in vistos:
                raise self.error("ID_REPETIDO", f"{destino}.id", f"el id «{id_}» está repetido")
            vistos.add(id_)
            codigo = self.texto(datos["codigo"], f"{destino}.codigo") if "codigo" in datos else None
            peso = self.peso(datos["peso"], f"{destino}.peso") if "peso" in datos else None
            regla = self.regla(datos["regla"], f"{destino}.regla") if "regla" in datos else None
            resultado.append(
                Criterio(id_, self.texto(datos["nombre"], f"{destino}.nombre"), peso, codigo, regla)
            )
        con_peso = [c.peso for c in resultado if c.peso is not None]
        if con_peso:
            if len(con_peso) != len(resultado):
                raise self.invalido(ruta, "o todos los criterios llevan peso o ninguno")
            self.suman_100(con_peso, ruta)
        return tuple(resultado)

    def seccion(self, valor: Any, ruta: str) -> tuple[int | str, int | str]:
        """Una sección (número >= 0 o nombre): devuelve (clave para comparar, valor)."""
        if isinstance(valor, bool) or not isinstance(valor, (int, str)):
            raise self.invalido(ruta, "debe ser un número de sección o un nombre")
        if isinstance(valor, int):
            if valor < 0:
                raise self.invalido(ruta, "el número de sección no puede ser negativo")
            return valor, valor
        valor = self.texto(valor, ruta)
        return valor.casefold(), valor

    def instrumentos(self, valor: Any, evaluaciones: int) -> tuple[Instrumento, ...]:
        resultado: list[Instrumento] = []
        vistos: set[str] = set()
        for i, bruto in enumerate(self.lista(valor, "instrumentos")):
            ruta = f"instrumentos[{i}]"
            datos = self.mapa(bruto, ruta, _PERMITIDAS_INSTRUMENTO, _REQUERIDAS_INSTRUMENTO)
            id_ = self.id_(datos["id"], f"{ruta}.id")
            if id_ in vistos:
                raise self.error("ID_REPETIDO", f"{ruta}.id", f"el id «{id_}» está repetido")
            vistos.add(id_)
            recupera = (
                self.recupera(datos["recupera"], f"{ruta}.recupera")
                if "recupera" in datos
                else None
            )
            if recupera is not None:
                for n in recupera:
                    if not 1 <= n <= evaluaciones:
                        raise self.error(
                            "RECUPERA_INVALIDO",
                            f"{ruta}.recupera",
                            f"recupera {n} y no hay evaluación {n}",
                        )
            resultado.append(
                Instrumento(
                    id_,
                    self.texto(datos["nombre"], f"{ruta}.nombre"),
                    self.seccion(datos["seccion"], f"{ruta}.seccion")[1],
                    self.evalua(datos["evalua"], f"{ruta}.evalua"),
                    recupera,
                )
            )
        return tuple(resultado)

    def evalua(self, valor: Any, ruta: str) -> tuple[tuple[str, float], ...]:
        """Las mismas reglas que el ``evalua`` de una actividad (``contenido._validar_evalua``)."""
        if not isinstance(valor, dict) or not valor:
            raise self.invalido(ruta, "debe ser un mapa de ids a pesos, como {RA1: 40, RA3: 25}")
        salida: list[tuple[str, float]] = []
        for clave, peso in valor.items():
            destino = f"{ruta}.{clave}"
            self.id_(clave, destino)
            if not peso_evalua_valido(peso):
                raise self.invalido(destino, "debe ser un número de 0 a 100 con hasta 2 decimales")
            salida.append((clave, peso))
        return tuple(salida)

    def evaluaciones(self, valor: Any, con_peso: bool) -> tuple[Evaluacion, ...]:
        resultado: list[Evaluacion] = []
        vistas: set[int | str] = set()
        for i, bruto in enumerate(self.lista(valor, "evaluaciones")):
            ruta = f"evaluaciones[{i}]"
            datos = self.mapa(
                bruto,
                ruta,
                ("nombre", "secciones", "peso", "cerrada"),
                ("nombre", "secciones") + (("peso",) if con_peso else ()),
            )
            secciones: list[int | str] = []
            for j, seccion in enumerate(self.lista(datos["secciones"], f"{ruta}.secciones")):
                destino = f"{ruta}.secciones[{j}]"
                clave, seccion = self.seccion(seccion, destino)
                if clave in vistas:
                    raise self.error(
                        "SECCION_REPETIDA",
                        destino,
                        f"la sección «{seccion}» ya está en otra evaluación",
                    )
                vistas.add(clave)
                secciones.append(seccion)
            cerrada = datos.get("cerrada", False)
            if not isinstance(cerrada, bool):
                raise self.invalido(f"{ruta}.cerrada", "debe ser true o false")
            peso = self.peso(datos["peso"], f"{ruta}.peso") if "peso" in datos else None
            resultado.append(
                Evaluacion(
                    self.texto(datos["nombre"], f"{ruta}.nombre"), tuple(secciones), peso, cerrada
                )
            )
        return tuple(resultado)

    def final(self, valor: Any) -> Final:
        datos = self.mapa(valor, "final", ("de", "tope"), ("de",))
        de = datos["de"]
        if de not in ("elementos", "evaluaciones"):
            raise self.invalido("final.de", "debe ser «elementos» o «evaluaciones»")
        if "tope" not in datos:
            return Final(de)
        if de != "elementos":
            raise self.error(
                "TOPE_SIN_ELEMENTOS",
                "final.tope",
                "el tope solo vale cuando la final es de elementos",
            )
        tope = self.mapa(
            datos["tope"],
            "final.tope",
            ("si_alguno_menor_que", "maximo"),
            ("si_alguno_menor_que", "maximo"),
        )
        umbral = self.numero(tope["si_alguno_menor_que"], "final.tope.si_alguno_menor_que")
        if not 0 < umbral <= 10:
            raise self.invalido(
                "final.tope.si_alguno_menor_que", "debe estar entre 0 (excluido) y 10"
            )
        maximo = self.numero(tope["maximo"], "final.tope.maximo")
        if not 0 <= maximo < 10:
            raise self.invalido("final.tope.maximo", "debe estar entre 0 y 10 (excluido)")
        return Final(de, Tope(umbral, maximo))


def comprobar_niveles_equidistantes(esquema: Esquema) -> None:
    """Los porcentajes de ``niveles_rubrica`` deben estar igual de separados.

    La escala de los resultados se reescala con una fórmula lineal, así que solo reproduce
    porcentajes equidistantes. Los niveles por defecto (0, 25, 50, 75 y 100) lo son.
    """
    porcentajes = sorted(nivel.porcentaje for nivel in esquema.niveles_rubrica)
    if len(porcentajes) < 2:
        return
    diferencias = [b - a for a, b in pairwise(porcentajes)]
    # Un paso puede diferir en la última cifra decimal por el redondeo (33,33 y 33,34).
    if any(
        abs(diferencia - diferencias[0]) > TOLERANCIA_PESOS + 1e-9 for diferencia in diferencias
    ):
        texto = ", ".join(f"{porcentaje:g}" for porcentaje in porcentajes)
        raise ErrorCalificacion(
            "NIVELES_NO_EQUIDISTANTES",
            "niveles_rubrica: los porcentajes deben estar igual de separados para usar "
            f"resultados (por ejemplo 0, 25, 50, 75 y 100); ahora son {texto}",
        )


def _reglas_de_hojas(
    elementos: tuple[Elemento, ...], agregacion: Agregacion
) -> list[tuple[str, str, str]]:
    """(hoja, regla efectiva, ruta YAML de donde sale) de cada hoja del esquema."""
    resultado: list[tuple[str, str, str]] = []
    for i, elemento in enumerate(elementos):
        if elemento.criterios:
            for j, criterio in enumerate(elemento.criterios):
                if criterio.regla is not None:
                    ruta = f"elementos[{i}].criterios[{j}].regla"
                    resultado.append((criterio.id, criterio.regla, ruta))
                else:
                    resultado.append((criterio.id, agregacion.regla, "agregacion.regla"))
        elif elemento.regla is not None:
            resultado.append((elemento.id, elemento.regla, f"elementos[{i}].regla"))
        else:
            resultado.append((elemento.id, agregacion.regla, "agregacion.regla"))
    return resultado


def _comprobar_reglas(
    lector: _Lector,
    agregacion: Agregacion,
    elementos: tuple[Elemento, ...],
    evaluaciones: int,
) -> None:
    """La progresiva necesita un factor por evaluación y los factores no valen sin ella."""
    progresivas = [
        (hoja, ruta)
        for hoja, regla, ruta in _reglas_de_hojas(elementos, agregacion)
        if regla == "progresiva"
    ]
    if progresivas:
        if evaluaciones == 0:
            hoja, ruta = progresivas[0]
            raise lector.invalido(
                "evaluaciones",
                f"la regla «progresiva» de «{hoja}» necesita «evaluaciones»: define las "
                "evaluaciones del curso, con un factor por cada una en «agregacion.factores»",
            )
        if not agregacion.factores:
            hoja, ruta = progresivas[0]
            raise lector.error(
                "PROGRESIVA_SIN_FACTORES",
                ruta,
                f"la regla «progresiva» de «{hoja}» necesita «agregacion.factores», "
                "uno por evaluación",
            )
        if len(agregacion.factores) != evaluaciones:
            raise lector.invalido(
                "agregacion.factores",
                f"hay {evaluaciones} evaluaciones y {len(agregacion.factores)} factores; "
                "debe haber uno por evaluación",
            )
    elif agregacion.factores:
        raise lector.invalido(
            "agregacion.factores",
            "solo valen si alguna hoja usa la regla «progresiva»",
        )


def cargar_esquema(ruta: Path, carpeta: Path, *, resultados: bool = False) -> Esquema:
    """Lee y valida un ``calificacion.yaml`` de la carpeta de la asignatura.

    ``resultados`` exige además que los niveles de la rúbrica sean equidistantes (solo hace
    falta cuando alguna tarea usa ``evidencia: resultados``). Lanza ``ErrorCalificacion`` con
    un código estable. No habla con el aula.
    """
    try:
        origen = dentro_de_la_carpeta(Path(ruta), Path(carpeta), EXTENSIONES_ESQUEMA)
    except ErrorEscritura as error:
        codigo = "ESQUEMA_FUERA_DE_CARPETA" if error.codigo == "FICHERO_FUERA" else error.codigo
        raise ErrorCalificacion(codigo, error.detalle) from None
    lineas: dict[str, int] = {}
    try:
        datos = cargar_yaml_sin_alias(origen, lineas)
    except ErrorEscritura as error:
        codigo = "ESQUEMA_INVALIDO" if error.codigo == "RELLENO_INVALIDO" else error.codigo
        raise ErrorCalificacion(codigo, error.detalle) from None
    lector = _Lector(lineas)
    datos = lector.mapa(
        datos,
        "",
        (
            "organizacion",
            "agregacion",
            "elementos",
            "evaluaciones",
            "final",
            "instrumentos",
            "etapa",
            "niveles_rubrica",
            "actividades_pesan_igual",
        ),
        ("organizacion", "final"),
    )
    organizacion = datos["organizacion"]
    if organizacion not in ("elementos", "evaluaciones"):
        raise lector.invalido("organizacion", "debe ser «elementos» o «evaluaciones»")
    agregacion = lector.agregacion(datos["agregacion"]) if "agregacion" in datos else Agregacion()
    etapa = lector.etapa(datos.get("etapa"))
    niveles_rubrica = (
        lector.niveles_rubrica(datos["niveles_rubrica"])
        if "niveles_rubrica" in datos
        else NIVELES_RUBRICA
    )
    actividades_pesan_igual = (
        lector.booleano(datos["actividades_pesan_igual"], "actividades_pesan_igual")
        if "actividades_pesan_igual" in datos
        else False
    )
    final = lector.final(datos["final"])
    for necesaria in {organizacion, final.de}:
        if necesaria not in datos:
            raise lector.invalido("", f"falta la clave «{necesaria}»")
    elementos = lector.elementos(datos["elementos"]) if "elementos" in datos else ()
    evaluaciones = (
        lector.evaluaciones(datos["evaluaciones"], final.de == "evaluaciones")
        if "evaluaciones" in datos
        else ()
    )
    if final.de == "elementos":
        lector.suman_100([e.peso for e in elementos], "elementos")
    else:
        lector.suman_100([e.peso for e in evaluaciones if e.peso is not None], "evaluaciones")
    instrumentos = (
        lector.instrumentos(datos["instrumentos"], len(evaluaciones))
        if "instrumentos" in datos
        else ()
    )
    _comprobar_reglas(lector, agregacion, elementos, len(evaluaciones))
    esquema = Esquema(
        organizacion,
        elementos,
        evaluaciones,
        final,
        instrumentos,
        etapa,
        niveles_rubrica,
        actividades_pesan_igual,
        agregacion,
    )
    if resultados:
        comprobar_niveles_equidistantes(esquema)
    return esquema
