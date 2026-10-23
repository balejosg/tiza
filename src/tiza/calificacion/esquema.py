"""Formato de ``calificacion.yaml`` y su validación (esquema cerrado, offline).

El agente describe cómo se calcula la nota final: qué elementos (resultados de aprendizaje o
criterios) y qué evaluaciones hay, cuánto pesa cada uno y, si hace falta, un tope. No hay
lenguaje de fórmulas. Los errores llevan la ruta YAML de lo que falla
(``elementos[1].peso``) y su línea.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tiza.escritura import ErrorEscritura
from tiza.escritura.relleno import cargar_yaml_sin_alias, dentro_de_la_carpeta

__all__ = [
    "ErrorCalificacion",
    "Criterio",
    "Elemento",
    "Esquema",
    "Evaluacion",
    "Final",
    "Instrumento",
    "Tope",
    "cargar_esquema",
]

EXTENSIONES_ESQUEMA = frozenset({".yaml"})
TOLERANCIA_PESOS = 0.01
_RE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,15}")
MAX_PESO_EVALUA = 100  # peso máximo de un elemento en «evalua» de un instrumento


class ErrorCalificacion(Exception):
    """Error del calificador con un código estable; el detalle es texto de tiza."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


@dataclass(frozen=True)
class Criterio:
    id: str
    nombre: str
    peso: float | None
    codigo: str | None = None


@dataclass(frozen=True)
class Elemento:
    id: str
    nombre: str
    peso: float
    codigo: str | None = None
    criterios: tuple[Criterio, ...] = ()


@dataclass(frozen=True)
class Instrumento:
    """Casilla manual: no tiene actividad en el aula, solo sección y qué elementos evalúa."""

    id: str
    nombre: str
    seccion: int | str
    evalua: tuple[tuple[str, float], ...]


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

    def suman_100(self, pesos: list[float], ruta: str) -> None:
        total = sum(pesos)
        if abs(total - 100) > TOLERANCIA_PESOS:
            raise self.error(
                "PESOS_NO_SUMAN_100", ruta, f"los pesos de {ruta} suman {total:g} y deben sumar 100"
            )

    def id_(self, valor: Any, ruta: str) -> str:
        if not isinstance(valor, str) or not _RE_ID.fullmatch(valor):
            raise self.invalido(
                ruta,
                "debe empezar por una letra y tener solo letras, cifras o _ (16 como mucho)",
            )
        return valor

    def elementos(self, valor: Any) -> tuple[Elemento, ...]:
        resultado: list[Elemento] = []
        vistos: set[str] = set()  # ids de elementos y de criterios, en un solo espacio
        for i, bruto in enumerate(self.lista(valor, "elementos")):
            ruta = f"elementos[{i}]"
            datos = self.mapa(
                bruto,
                ruta,
                ("id", "nombre", "peso", "codigo", "criterios"),
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
            resultado.append(
                Elemento(
                    id_,
                    self.texto(datos["nombre"], f"{ruta}.nombre"),
                    self.peso(datos["peso"], f"{ruta}.peso"),
                    codigo,
                    criterios,
                )
            )
        return tuple(resultado)

    def criterios(self, valor: Any, ruta: str, vistos: set[str]) -> tuple[Criterio, ...]:
        resultado: list[Criterio] = []
        for j, bruto in enumerate(self.lista(valor, ruta)):
            destino = f"{ruta}[{j}]"
            datos = self.mapa(bruto, destino, ("id", "nombre", "peso", "codigo"), ("id", "nombre"))
            id_ = self.id_(datos["id"], f"{destino}.id")
            if id_ in vistos:
                raise self.error("ID_REPETIDO", f"{destino}.id", f"el id «{id_}» está repetido")
            vistos.add(id_)
            codigo = self.texto(datos["codigo"], f"{destino}.codigo") if "codigo" in datos else None
            peso = self.peso(datos["peso"], f"{destino}.peso") if "peso" in datos else None
            resultado.append(
                Criterio(id_, self.texto(datos["nombre"], f"{destino}.nombre"), peso, codigo)
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

    def instrumentos(self, valor: Any) -> tuple[Instrumento, ...]:
        resultado: list[Instrumento] = []
        vistos: set[str] = set()
        for i, bruto in enumerate(self.lista(valor, "instrumentos")):
            ruta = f"instrumentos[{i}]"
            claves = ("id", "nombre", "seccion", "evalua")
            datos = self.mapa(bruto, ruta, claves, claves)
            id_ = self.id_(datos["id"], f"{ruta}.id")
            if id_ in vistos:
                raise self.error("ID_REPETIDO", f"{ruta}.id", f"el id «{id_}» está repetido")
            vistos.add(id_)
            resultado.append(
                Instrumento(
                    id_,
                    self.texto(datos["nombre"], f"{ruta}.nombre"),
                    self.seccion(datos["seccion"], f"{ruta}.seccion")[1],
                    self.evalua(datos["evalua"], f"{ruta}.evalua"),
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
            if (
                isinstance(peso, bool)
                or not isinstance(peso, int | float)
                or not 0 <= peso <= MAX_PESO_EVALUA
                or round(peso, 2) != peso
            ):
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


def cargar_esquema(ruta: Path, carpeta: Path) -> Esquema:
    """Lee y valida un ``calificacion.yaml`` de la carpeta de la asignatura.

    Lanza ``ErrorCalificacion`` con un código estable. No habla con el aula.
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
        ("organizacion", "elementos", "evaluaciones", "final", "instrumentos"),
        ("organizacion", "final"),
    )
    organizacion = datos["organizacion"]
    if organizacion not in ("elementos", "evaluaciones"):
        raise lector.invalido("organizacion", "debe ser «elementos» o «evaluaciones»")
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
    instrumentos = lector.instrumentos(datos["instrumentos"]) if "instrumentos" in datos else ()
    return Esquema(organizacion, elementos, evaluaciones, final, instrumentos)
