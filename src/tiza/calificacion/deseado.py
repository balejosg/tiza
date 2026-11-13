"""La estructura deseada del calificador: pura, sin aula y sin cmids.

A partir del esquema (``esquema.py``) y del ``evalua`` de cada actividad, calcula qué árbol de
categorías, copias y calculados debe tener el calificador. Las actividades se identifican por su
ruta relativa a la carpeta (en POSIX); poner los cmids y comparar con el aula es cosa de las
tareas siguientes.

Todo cuelga de ``TZ_TIZA``, en **media ponderada**. La **vista primaria** es siempre por
evaluaciones y es la única con actividades reales: ``TZ_V_<n>`` → ``TZ_V_<n>_<elem>`` →
``TZ_V_<n>_<crit>``. La **vista del curso** por elementos se monta sobre copias de los totales
trimestrales: ``TZ_E_<elem>`` → ``TZ_E_<crit>`` → una copia ``TZ_C_<huella(hoja|n)>`` por
trimestre con evidencias, con el coeficiente ``q_n``. ``final.de`` decide cuál de las dos cuelga
de ``TZ_FINAL`` y cuál de ``TZ_VISTA`` (peso 0). Ninguna categoría se crea vacía. Solo si la
final tiene tope hay ``TZ_NOTA_FINAL``, un único calculado sobre 100 dentro de ``TZ_TIZA``.

Una **hoja** es un criterio o un elemento sin criterios: ``evalua`` solo nombra hojas. Un elemento
con criterios tiene un nivel más: ``TZ_E_<elem>`` contiene ``TZ_E_<crit>`` (y esa, sus copias) y
``TZ_V_<n>_<elem>`` contiene ``TZ_V_<n>_<crit>`` (y esa, sus evidencias). Un instrumento del
esquema (``instrumentos``) es una actividad sin fichero en el aula: su pieza real es una casilla
manual ``TZ_M_<id>`` (clase ``manual``).

La regla de una hoja se aplica en los dos sitios donde existe: su categoría del trimestre y la del
curso. ``media`` y ``progresiva`` usan media ponderada; ``mediana`` y ``mas_alta`` usan su
agregación de Moodle y en ellas los coeficientes no cuentan, así que lo que pesa 0 (la tarea real
de una evidencia por resultados) sube al antepasado más cercano de media ponderada. La
recuperación **no es evidencia del trimestre**: vive en la vista del curso, en su hoja, envolviendo
la copia del trimestre que recupera en una categoría «más alta» ``TZ_RM_<huella>`` (o suelta si la
hoja ya es «más alta»).

Una tarea con ``evidencia: resultados`` no puede llevar su resultado ponderado en media ponderada
(espiga S2): cada criterio lleva un elemento de resultado del aula (``TZ_O_<huella(ruta|clave)>``,
clase ``resultado``, peso 0) y un calculado ``TZ_R_<huella(ruta|clave|trimestre)>`` sobre 100 con
el peso de ``evalua``; la tarea real se queda con peso 0 en su primer criterio. Con
``rubrica_filas`` hay un resultado y un calculado por fila, directamente en la categoría del
criterio (sin la subcategoría «Filas»). ``Deseado.resultados`` da las tripletas
``(ruta, clave, TZ_O_…)`` para colocarlos.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection
from dataclasses import dataclass, replace
from pathlib import Path
from typing import NoReturn

from tiza.calificacion.esquema import (
    Criterio,
    Elemento,
    ErrorCalificacion,
    Esquema,
)
from tiza.contenido import Documento
from tiza.rubrica_tarea import FilaDeResultado, nombre_de_fila

__all__ = [
    "Deseado",
    "EvidenciaDeHoja",
    "Nodo",
    "comprobar_sin_circulares",
    "deseado",
    "detalle_tope",
    "evidencias_por_hoja",
    "nombre_de_hoja",
    "normalizar_pesos",
    "reparto_por_hoja",
]

CLASES = (
    "contenedor",
    "categoria",
    "actividad",
    "manual",
    "copia",
    "nota",
    "resultado",
    "resultado_calc",
)
RAIZ = "TZ_TIZA"
FINAL = "TZ_FINAL"
VISTA = "TZ_VISTA"
NOTA_FINAL = "TZ_NOTA_FINAL"
_VISTA_ELEMENTOS = "E"
_VISTA_EVALUACIONES = "V"
# Las agregaciones de Moodle que usa tiza: media ponderada, mediana y calificación más alta.
AGREGACION_MEDIA_PONDERADA = 10
AGREGACION_MEDIANA = 2
AGREGACION_MAS_ALTA = 6


@dataclass(frozen=True)
class Nodo:
    """Un nodo del calificador deseado.

    ``peso`` es el coeficiente en un padre de media ponderada (``None``: el padre no es de media
    ponderada y Moodle no lo usa; 0: no cuenta). ``formula_de`` es, en una ``copia``, el
    ``idnumber`` (o la ruta de la actividad) que refleja; en un ``resultado_calc``, el
    ``idnumber`` del ``resultado`` del aula que reescala; en la ``nota`` final, ``None`` (su
    fórmula sale de ``Deseado.tope``). La clase ``manual`` es la casilla de calificación manual de
    un instrumento (``TZ_M_<id>``, sin ``formula_de``); sus copias llevan
    ``formula_de="TZ_M_<id>"``. El ``resultado`` es el elemento del aula (``TZ_O_…``, peso 0, sin
    ``formula_de``). Las categorías son ``TZ_E_<elem>``, ``TZ_E_<crit>``, ``TZ_V_<n>``,
    ``TZ_V_<n>_<elem>``, ``TZ_V_<n>_<crit>`` y ``TZ_RM_<huella>``. ``maximo`` es el máximo del
    calculado (100 en un ``resultado_calc`` o en la nota final); ``None`` lo deja como lo decide
    el aula. ``agregacion`` es la de Moodle (10 media ponderada, 2 mediana y 6 calificación más
    alta): solo las hojas con una regla nativa se apartan de la media ponderada.
    """

    idnumber: str
    clase: str
    nombre: str
    padre: str | None
    peso: float | None
    formula_de: str | tuple[str, str] | None = None
    visualizacion: str | None = None
    maximo: float | None = None
    agregacion: int = AGREGACION_MEDIA_PONDERADA


@dataclass(frozen=True)
class Deseado:
    """El calificador deseado.

    ``nodos`` va en orden de creación (los padres antes que los hijos). ``tope`` es ``None`` o
    ``(umbral, maximo, idnumbers TZ_E_<elemento> de los elementos activos)``; un elemento está
    activo cuando se cerró la evaluación de su primera evidencia. ``total_curso`` es ``None``
    (no se toca), ``"TZ_NOTA_FINAL"`` (el calculado con esa nota, que el total del curso copia
    dividida por 10) o ``"porcentaje"`` (solo la visualización). ``cerradas`` son los
    ``TZ_V_<n>`` de las evaluaciones cerradas;
    ``actividades`` empareja cada ruta con el ``idnumber`` de su padre real; ``avisos`` son
    pares ``(codigo, clave)``, con el id del elemento o, en ``EVIDENCIA_COMPARTIDA``, el nombre
    de la actividad o casilla manual; ``resultados`` son las tripletas ``(ruta, clave, idnumber
    TZ_O_…)`` de las tareas con ``evidencia: resultados``: la clave es el criterio o, con
    rúbrica de filas, la clave estable de cada fila. ``niveles`` es cuántos
    niveles tiene la escala de logro (``niveles_rubrica``), para la fórmula del calculado.
    ``tope_activos`` y ``tope_pendientes`` emparejan cada elemento con el número (1-based) de la
    evaluación en la que entra en el tope; los pendientes aún no cuentan y los elementos sin
    evidencias no están en ninguna de las dos listas.
    """

    nodos: tuple[Nodo, ...]
    total_curso: str | None
    tope: tuple[float, float, tuple[str, ...]] | None
    cerradas: tuple[str, ...]
    actividades: tuple[tuple[str, str], ...]
    avisos: tuple[tuple[str, str], ...] = ()
    resultados: tuple[tuple[str, str, str], ...] = ()
    niveles: int = 5
    tope_activos: tuple[tuple[str, int], ...] = ()
    tope_pendientes: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class _Actividad:
    ruta: str
    nombre: str
    evaluacion: int  # índice (desde 0) de la evaluación en la que cae su sección
    evalua: tuple[tuple[str, float], ...]
    manual: bool = False  # un instrumento: su ruta es el idnumber ``TZ_M_<id>`` de la casilla
    resultados: bool = False  # la tarea recoge la evidencia con resultados del aula
    # Con rúbrica de filas, cada fila es un resultado del aula; vacío: un resultado por criterio.
    filas: tuple[FilaDeResultado, ...] = ()
    # Lo que declaró el documento; None en una casilla manual.
    evidencia_declarada: str | None = None
    # Números de evaluación (1-based) cuyos criterios recupera; vacío: no recupera.
    recupera: tuple[int, ...] = ()


def comprobar_sin_circulares(nodos: tuple[Nodo, ...]) -> None:
    """Falla si un calculado referencia a un antepasado suyo: Moodle lo dejaría vacío."""
    padres = {n.idnumber: n.padre for n in nodos}
    for n in nodos:
        if n.formula_de is None:
            continue
        fuentes = set(n.formula_de) if isinstance(n.formula_de, tuple) else {n.formula_de}
        padre = n.padre
        while padre is not None:
            if padre in fuentes:
                raise ErrorCalificacion(
                    "REFERENCIA_CIRCULAR",
                    f"{n.idnumber} referencia a {padre}, que lo contiene: Moodle lo dejaría vacío",
                )
            padre = padres.get(padre)


def _huella(texto: str) -> str:
    """Los 10 primeros hex del sha256: el id de un nodo no depende de qué otros haya."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:10]


def _misma_seccion(a: int | str, b: int | str) -> bool:
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a.casefold() == b.casefold()
    return False


def _ruta_relativa(ruta: Path, carpeta: Path) -> str:
    try:
        return ruta.relative_to(carpeta).as_posix()
    except ValueError:
        return ruta.as_posix()


def normalizar_pesos(pesos: list[float]) -> list[float]:
    """Pesos a 100 entre los que cuentan (> 0), con 2 decimales y el ajuste en el último.

    Los de peso 0 se quedan en 0; si todos pesan 0, todos se quedan en 0.
    """
    total = sum(pesos)
    resultado = [0.0] * len(pesos)
    cuentan = [i for i, p in enumerate(pesos) if p > 0]
    if not cuentan or total <= 0:
        return resultado
    for i in cuentan[:-1]:
        resultado[i] = round(pesos[i] * 100 / total, 2)
    resultado[cuentan[-1]] = round(100.0 - sum(resultado[i] for i in cuentan[:-1]), 2)
    return resultado


def _hojas_de(elemento: Elemento) -> list[str]:
    """Las hojas de un elemento: sus criterios, o él mismo si no tiene."""
    return [c.id for c in elemento.criterios] or [elemento.id]


def _hojas(esquema: Esquema) -> list[tuple[str, str]]:
    """Las hojas (criterios, o elementos sin criterios) con su elemento, en el orden del esquema."""
    return [(hoja, elemento.id) for elemento in esquema.elementos for hoja in _hojas_de(elemento)]


def _texto_de_hoja(elemento: Elemento, criterio: Criterio | None) -> str:
    """«código · nombre» de una hoja (D9); sin código, solo su nombre."""
    nombre = elemento.nombre if criterio is None else criterio.nombre
    codigo = elemento.codigo if criterio is None else criterio.codigo
    return f"{codigo} · {nombre}" if codigo else nombre


def nombre_de_hoja(esquema: Esquema, id_: str) -> str:
    """El nombre completo que lleva el resultado de una hoja del esquema (D9).

    Es el mismo texto que la rúbrica por criterios pone en su fila, para que la publicación
    cree el resultado con él y la reconciliación lo reconozca en el aula. Si el id no está en
    el esquema, se devuelve tal cual (solo puede pasar con un esquema incoherente).
    """
    for elemento in esquema.elementos:
        if elemento.criterios:
            for criterio in elemento.criterios:
                if criterio.id == id_:
                    return _texto_de_hoja(elemento, criterio)
        elif elemento.id == id_:
            return _texto_de_hoja(elemento, None)
    return id_


def _validar(
    esquema: Esquema,
    ruta: str,
    evalua: tuple[tuple[str, float], ...],
    seccion: int | str,
) -> int | None:
    """Comprueba el ``evalua`` y la sección de una actividad o instrumento; da su evaluación.

    Devuelve ``None`` si la sección no cae en ninguna evaluación: quien llama decide el código
    (``ACTIVIDAD_SIN_EVALUACION`` si alguna hoja es progresiva y ``SECCION_SIN_EVALUACION`` si
    no).
    """
    hojas = {hoja for hoja, _ in _hojas(esquema)}
    con_criterios = {e.id for e in esquema.elementos if e.criterios}
    for id_, _ in evalua:
        if id_ in con_criterios:
            raise ErrorCalificacion(
                "ELEMENTO_CON_CRITERIOS",
                f"{ruta}: evalua nombra «{id_}», que tiene criterios: nombra sus criterios",
            )
        if id_ not in hojas:
            raise ErrorCalificacion(
                "ELEMENTO_DESCONOCIDO",
                f"{ruta}: evalua nombra «{id_}», que no está entre los elementos ni los "
                "criterios de calificacion.yaml",
            )
    return next(
        (
            i
            for i, ev in enumerate(esquema.evaluaciones)
            if any(_misma_seccion(seccion, s) for s in ev.secciones)
        ),
        None,
    )


def _validar_recupera(esquema: Esquema, ruta: str, recupera: tuple[int, ...]) -> None:
    """Cada número de ``recupera`` debe tener su evaluación en el esquema (1-based)."""
    for n in recupera:
        if not 1 <= n <= len(esquema.evaluaciones):
            raise ErrorCalificacion(
                "RECUPERA_INVALIDO", f"{ruta}: recupera {n} y no hay evaluación {n}"
            )


def _sin_evaluacion(
    esquema: Esquema,
    ruta: str,
    evalua: tuple[tuple[str, float], ...],
    seccion: int | str,
) -> NoReturn:
    """La sección no cae en ninguna evaluación: el código depende de la regla de la hoja."""
    progresiva = next((hoja for hoja, _ in evalua if esquema.regla_de(hoja) == "progresiva"), None)
    if progresiva is not None:
        raise ErrorCalificacion(
            "ACTIVIDAD_SIN_EVALUACION",
            f"{ruta}: la sección «{seccion}» no está en ninguna evaluación y «{progresiva}» "
            "usa la regla progresiva, que necesita el factor de su evaluación",
        )
    raise ErrorCalificacion(
        "SECCION_SIN_EVALUACION",
        f"{ruta}: la sección «{seccion}» no está en ninguna evaluación de calificacion.yaml",
    )


def _validar_reglas(esquema: Esquema, actividades: list[_Actividad]) -> None:
    """Las reglas nativas y las recuperaciones que no caben con el resto del esquema (D8/D10)."""
    con_recupera = [a for a in actividades if a.recupera]
    if con_recupera and esquema.final.de != "elementos":
        raise ErrorCalificacion(
            "RECUPERACION_SOLO_FINAL_DE_ELEMENTOS",
            f"{con_recupera[0].ruta}: recupera solo vale cuando la final es de elementos",
        )
    for a in con_recupera:
        for hoja, _ in a.evalua:
            if esquema.regla_de(hoja) == "mediana":
                raise ErrorCalificacion(
                    "RECUPERACION_CON_MEDIANA",
                    f"{a.ruta}: «{hoja}» usa la regla mediana y no admite recuperación",
                )
            for n in a.recupera:
                if not any(
                    b is not a
                    and not b.recupera
                    and hoja in dict(b.evalua)
                    and dict(b.evalua)[hoja] > 0
                    and b.evaluacion == n - 1
                    for b in actividades
                ):
                    raise ErrorCalificacion(
                        "RECUPERA_SIN_EVIDENCIAS",
                        f"{a.ruta}: «{hoja}» no tiene evidencias normales en la evaluación "
                        f"{n}, que recupera",
                    )


def _actividades(
    esquema: Esquema,
    documentos: list[Documento],
    carpeta: Path,
    resultados: Collection[str] | None = None,
) -> list[_Actividad]:
    """Las actividades que cuentan, validadas una a una.

    ``resultados`` son las rutas cuyos resultados están efectivos; ``None`` los da por efectivos
    a todas las tareas con ``evidencia`` (el comportamiento de siempre). Una tarea fuera de la
    colección se trata como una tarea normal: actividad real y copias.
    """
    resultado: list[_Actividad] = []
    for documento in sorted(documentos, key=lambda d: _ruta_relativa(d.ruta, carpeta)):
        if documento.evalua is None:
            continue
        ruta = _ruta_relativa(documento.ruta, carpeta)
        evalua = documento.evalua
        if esquema.actividades_pesan_igual:
            evalua = tuple((id_, 1.0) for id_, _ in evalua)
        evaluacion = _validar(esquema, ruta, evalua, documento.seccion)
        if evaluacion is None:
            _sin_evaluacion(esquema, ruta, evalua, documento.seccion)
        recupera = documento.recupera or ()
        _validar_recupera(esquema, ruta, recupera)
        filas = (
            documento.rubrica_filas.filas
            if documento.evidencia == "resultados" and documento.rubrica_filas is not None
            else ()
        )
        resultado.append(
            _Actividad(
                ruta,
                documento.nombre,
                evaluacion,
                evalua,
                resultados=documento.evidencia == "resultados"
                and (resultados is None or ruta in resultados),
                filas=tuple(filas),
                evidencia_declarada=documento.evidencia,
                recupera=recupera,
            )
        )
    for i, instrumento in enumerate(esquema.instrumentos):
        evalua = instrumento.evalua
        if esquema.actividades_pesan_igual:
            evalua = tuple((id_, 1.0) for id_, _ in evalua)
        ruta = f"instrumentos[{i}]"
        evaluacion = _validar(esquema, ruta, evalua, instrumento.seccion)
        if evaluacion is None:
            _sin_evaluacion(esquema, ruta, evalua, instrumento.seccion)
        recupera = instrumento.recupera or ()
        _validar_recupera(esquema, ruta, recupera)
        resultado.append(
            _Actividad(
                f"TZ_M_{instrumento.id}",
                instrumento.nombre,
                evaluacion,
                evalua,
                manual=True,
                recupera=recupera,
            )
        )
    return resultado


def deseado(
    esquema: Esquema,
    documentos: list[Documento],
    anterior: bool,
    carpeta: Path,
    *,
    resultados: Collection[str] | None = None,
) -> Deseado:
    """Calcula el calificador deseado. Lanza ``ErrorCalificacion`` si las actividades no cuadran.

    Solo cuentan los documentos con ``evalua``. ``anterior`` es que el curso ya tenía un
    calificador ajeno: entonces ``TZ_TIZA`` pesa 0 en el total del curso y este no se toca.
    ``resultados`` limita las tareas con ``evidencia`` que se montan con resultados: las rutas que
    no estén se tratan como tareas normales, con actividad real y copias.
    """
    actividades = _actividades(esquema, documentos, carpeta, resultados)
    _validar_reglas(esquema, actividades)
    return _Montaje(esquema, actividades, anterior).montar()


def _enumerar(ids: list[str]) -> str:
    if len(ids) == 1:
        return ids[0]
    return f"{', '.join(ids[:-1])} y {ids[-1]}"


def _ordinal(numero: int) -> str:
    return f"{numero}.ª"


def detalle_tope(deseado: Deseado) -> str:
    """El paso ``TOPE``: qué elementos cuentan ya y cuáles entrarán al cerrar su evaluación."""
    activos: dict[int, list[str]] = {}
    pendientes: dict[int, list[str]] = {}
    for elemento, evaluacion in deseado.tope_activos:
        activos.setdefault(evaluacion, []).append(elemento)
    for elemento, evaluacion in deseado.tope_pendientes:
        pendientes.setdefault(evaluacion, []).append(elemento)
    if not activos:
        texto = "sin efecto todavía: ninguna evaluación cerrada"
        if pendientes:
            todos = [elemento for ids in pendientes.values() for elemento in ids]
            verbo = "entrará" if len(todos) == 1 else "entrarán"
            texto += f" ({_enumerar(todos)} {verbo} al cerrar la suya)"
        return texto
    partes = [
        f"{_enumerar(ids)} ({_ordinal(evaluacion)} cerrada)"
        for evaluacion, ids in sorted(activos.items())
    ]
    texto = "cuenta " + "; ".join(partes)
    if pendientes:
        cola = []
        for evaluacion, ids in sorted(pendientes.items()):
            verbo = "entrará" if len(ids) == 1 else "entrarán"
            cola.append(f"{_enumerar(ids)} {verbo} al cerrar la {_ordinal(evaluacion)}")
        texto += "; " + "; ".join(cola)
    return texto


def reparto_por_hoja(
    esquema: Esquema, documentos: list[Documento], carpeta: Path
) -> tuple[tuple[str, tuple[tuple[str, float], ...]], ...]:
    """El porcentaje normalizado de cada actividad en su hoja, en orden.

    Sirve a ``tiza comprobar`` para enseñar el efecto de los pesos relativos de ``evalua``.
    Con la regla ``progresiva`` el peso se multiplica por el factor de la evaluación de la
    actividad antes de normalizar; con ``media`` no. Solo salen las hojas con actividades.
    """
    return tuple(
        (hoja, tuple((e.nombre, e.peso) for e in evidencias))
        for hoja, _, evidencias in evidencias_por_hoja(esquema, documentos, carpeta)
        if evidencias
    )


@dataclass(frozen=True)
class EvidenciaDeHoja:
    """Una actividad (o casilla manual) que evalúa una hoja, tal como la valida ``deseado``.

    ``ruta`` es la ruta relativa del documento (POSIX) o ``TZ_M_<id>`` en una casilla manual, y
    ``documento`` es ``None`` en una casilla. ``evaluacion`` es el índice desde 0. ``peso`` es el
    porcentaje normalizado en la hoja (con ``progresiva``, multiplicado antes por el factor).
    """

    ruta: str
    nombre: str
    evaluacion: int
    manual: bool
    recupera: tuple[int, ...]
    peso: float
    documento: Documento | None


def evidencias_por_hoja(
    esquema: Esquema, documentos: list[Documento], carpeta: Path
) -> tuple[tuple[str, str, tuple[EvidenciaDeHoja, ...]], ...]:
    """Todas las hojas del esquema en orden, también las vacías: ``(hoja, elemento, evidencias)``.

    Valida las actividades igual que :func:`deseado` (lanza el mismo ``ErrorCalificacion``). Es
    la base de :func:`reparto_por_hoja` y del mapa de cobertura (``calificacion.cobertura``).
    """
    actividades = _actividades(esquema, documentos, carpeta)
    por_ruta = {_ruta_relativa(d.ruta, carpeta): d for d in documentos}
    salida: list[tuple[str, str, tuple[EvidenciaDeHoja, ...]]] = []
    for hoja, elemento in _hojas(esquema):
        de_hoja = [a for a in actividades if hoja in dict(a.evalua)]
        pesos = [dict(a.evalua)[hoja] for a in de_hoja]
        if esquema.regla_de(hoja) == "progresiva":
            pesos = [
                peso * esquema.agregacion.factores[a.evaluacion]
                for peso, a in zip(pesos, de_hoja, strict=True)
            ]
        normalizados = normalizar_pesos(pesos) if de_hoja else []
        evidencias = tuple(
            EvidenciaDeHoja(
                ruta=a.ruta,
                nombre=a.nombre,
                evaluacion=a.evaluacion,
                manual=a.manual,
                recupera=a.recupera,
                peso=peso,
                documento=None if a.manual else por_ruta.get(a.ruta),
            )
            for a, peso in zip(de_hoja, normalizados, strict=True)
        )
        salida.append((hoja, elemento, evidencias))
    return tuple(salida)


@dataclass(frozen=True)
class _HojaPrimaria:
    """Los hijos de una hoja en el trimestre: dentro de su categoría y fuera, en el MP de arriba."""

    dentro: tuple[Nodo, ...]
    fuera: tuple[Nodo, ...]


@dataclass(frozen=True)
class _CriterioPrimario:
    criterio: Criterio
    peso: float
    hoja: _HojaPrimaria


@dataclass(frozen=True)
class _ElementoPrimario:
    elemento: Elemento
    peso: float
    criterios: tuple[_CriterioPrimario, ...] = ()
    hoja: _HojaPrimaria | None = None


class _Evidencia:
    """Una evidencia de una hoja en un trimestre, antes de normalizar su coeficiente."""

    __slots__ = ("tipo", "actividad", "clave", "peso", "fila")

    def __init__(
        self,
        tipo: str,
        actividad: _Actividad,
        clave: str,
        peso: float,
        fila: FilaDeResultado | None = None,
    ) -> None:
        self.tipo = tipo  # "actividad" (real o copia) o "resultado" (calculado TZ_R_)
        self.actividad = actividad
        self.clave = clave
        self.peso = peso
        self.fila = fila


class _Montaje:
    def __init__(self, esquema: Esquema, actividades: list[_Actividad], anterior: bool) -> None:
        self.esquema = esquema
        self.actividades = actividades
        self.anterior = anterior
        self.tope = esquema.final.tope
        self.elemento_de_hoja = dict(_hojas(esquema))
        self.nombre_de_hoja = {hoja: nombre_de_hoja(esquema, hoja) for hoja, _ in _hojas(esquema)}
        self.codigo_o_nombre = {
            hoja: _codigo_o_nombre_de_hoja(esquema, hoja) for hoja, _ in _hojas(esquema)
        }
        self.nodos: list[Nodo] = []
        self.reales: set[str] = set()  # rutas cuya pieza real ya está colocada
        # La recuperación es de la vista del curso: su pieza real va en el primer trimestre que
        # recupera y en la primera hoja de su ``evalua``; los demás sitios llevan una copia.
        self.sitio_real_recuperacion: dict[str, tuple[str, int]] = {}
        for a in actividades:
            if a.recupera:
                self.sitio_real_recuperacion[a.ruta] = (a.evalua[0][0], min(a.recupera))
        self.q = {hoja: self._cuotas(hoja) for hoja, _ in _hojas(esquema)}

    # -- utilidades --------------------------------------------------------

    def _agregar(self, nodo: Nodo) -> None:
        self.nodos.append(nodo)

    def _agregar_en(self, nodos: tuple[Nodo, ...], padre: str) -> None:
        for nodo in nodos:
            self._agregar(replace(nodo, padre=padre))

    def _agregacion(self, hoja: str) -> int:
        regla = self.esquema.regla_de(hoja)
        if regla == "mediana":
            return AGREGACION_MEDIANA
        if regla == "mas_alta":
            return AGREGACION_MAS_ALTA
        return AGREGACION_MEDIA_PONDERADA

    def _positiva(self, hoja: str, evaluacion: int) -> bool:
        """La hoja tiene una evidencia normal con peso > 0 en ese trimestre."""
        return any(
            not a.recupera
            and a.evaluacion == evaluacion
            and hoja in dict(a.evalua)
            and dict(a.evalua)[hoja] > 0
            for a in self.actividades
        )

    def _presente(self, hoja: str, evaluacion: int) -> bool:
        """La hoja tiene alguna actividad normal en ese trimestre (aunque pese 0)."""
        return any(
            not a.recupera and a.evaluacion == evaluacion and hoja in dict(a.evalua)
            for a in self.actividades
        )

    def _cuotas(self, hoja: str) -> dict[int, float]:
        """``q_n`` de cada trimestre con evidencia positiva, normalizado a 100.

        Sin ``peso`` en las evaluaciones (o si alguna no lo lleva), todas pesan igual. Con la
        regla ``progresiva`` el factor de cada evaluación multiplica su ``q_n``.
        """
        con_evidencia = [
            n for n in range(len(self.esquema.evaluaciones)) if self._positiva(hoja, n)
        ]
        if not con_evidencia:
            return {}
        from tiza.calificacion.cobertura import cuotas_por_evaluacion

        cuotas = cuotas_por_evaluacion(self.esquema, con_evidencia)
        if self.esquema.regla_de(hoja) == "progresiva":
            cuotas = {n: cuota * self.esquema.agregacion.factores[n] for n, cuota in cuotas.items()}
        return cuotas

    def _nula(self, hojas: list[str], evaluacion: int | None = None) -> bool:
        """Tiene actividades (en la evaluación, si se da) pero ninguna pesa > 0 en su ``evalua``."""
        hay = False
        for hoja in hojas:
            for a in self.actividades:
                if a.recupera or hoja not in dict(a.evalua):
                    continue
                if evaluacion is not None and a.evaluacion != evaluacion:
                    continue
                hay = True
                if dict(a.evalua)[hoja] > 0:
                    return False
        return hay

    def _pesos_de_elementos(
        self, elementos: list[Elemento], evaluacion: int | None = None
    ) -> list[float]:
        return normalizar_pesos(
            [0.0 if self._nula(_hojas_de(e), evaluacion) else e.peso for e in elementos]
        )

    def _pesos_de_criterios(
        self, criterios: list[Criterio], evaluacion: int | None = None
    ) -> list[float]:
        return normalizar_pesos(
            [
                0.0 if self._nula([c.id], evaluacion) else 1.0 if c.peso is None else c.peso
                for c in criterios
            ]
        )

    def _resultado_id(self, ruta: str, clave: str) -> str:
        return f"TZ_O_{_huella(f'{ruta}|{clave}')}"

    def _calc_id(self, ruta: str, clave: str, hoja: str, evaluacion: int) -> str:
        return f"TZ_R_{_huella(f'{ruta}|{clave}|{hoja}|{evaluacion}')}"

    def _copia_curso_id(self, hoja: str, evaluacion: int) -> str:
        return f"TZ_C_{_huella(f'{hoja}|{evaluacion}')}"

    def _copia_actividad_id(self, ruta: str, hoja: str, evaluacion: int) -> str:
        # ``TZ_CR_``: la copia de una actividad dentro de la vista primaria. No se usa ``TZ_C_``
        # para no confundirla con la copia de un total del curso al detectar el árbol antiguo.
        return f"TZ_CR_{_huella(f'act|{ruta}|{hoja}|{evaluacion}')}"

    def _copia_recuperacion_id(self, ruta: str, hoja: str, evaluacion: int) -> str:
        return f"TZ_C_{_huella(f'rec|{ruta}|{hoja}|{evaluacion}')}"

    def _rm_id(self, hoja: str, evaluacion: int) -> str:
        return f"TZ_RM_{_huella(f'{hoja}|recupera|{evaluacion}')}"

    def _recuperadoras(self, hoja: str, evaluacion: int) -> list[_Actividad]:
        """Las actividades que recuperan esa evaluación (1-based) en esta hoja."""
        return [
            a
            for a in self.actividades
            if hoja in dict(a.evalua) and a.recupera and evaluacion in a.recupera
        ]

    def _evidencias(self, hoja: str, evaluacion: int) -> list[_Evidencia]:
        """Las evidencias normales de la hoja en un trimestre, en orden estable."""
        salida: list[_Evidencia] = []
        for a in self.actividades:
            if a.recupera or a.evaluacion != evaluacion or hoja not in dict(a.evalua):
                continue
            crudo = dict(a.evalua)[hoja]
            if a.resultados:
                if a.filas:
                    total_filas = sum(fila.peso for fila in a.filas if fila.criterio == hoja)
                    for fila in a.filas:
                        if fila.criterio == hoja:
                            parte = fila.peso / total_filas if total_filas > 0 else 0.0
                            salida.append(
                                _Evidencia("resultado", a, fila.clave, crudo * parte, fila)
                            )
                else:
                    salida.append(_Evidencia("resultado", a, hoja, crudo))
            else:
                salida.append(_Evidencia("actividad", a, hoja, crudo))
        return salida

    def _real(self, actividad: _Actividad, padre: str, peso: float | None) -> Nodo:
        clase = "manual" if actividad.manual else "actividad"
        self.reales.add(actividad.ruta)
        return Nodo(actividad.ruta, clase, actividad.nombre, padre, peso)

    def _copia_de_actividad(
        self, actividad: _Actividad, padre: str, peso: float | None, hoja: str, evaluacion: int
    ) -> Nodo:
        idnumber = self._copia_actividad_id(actividad.ruta, hoja, evaluacion)
        return Nodo(idnumber, "copia", f"{actividad.nombre} (copia)", padre, peso, actividad.ruta)

    def _tarea_real_cero(
        self,
        actividad: _Actividad,
        regla: str,
        dentro: list[Nodo],
        fuera: list[Nodo],
    ) -> None:
        """La tarea real de B y C: peso 0, en su primer criterio o en el MP de arriba."""
        if actividad.ruta in self.reales:
            return
        nodo = self._real(actividad, "", 0.0)
        if regla in ("mediana", "mas_alta"):
            fuera.append(nodo)
        else:
            dentro.append(nodo)

    def _hijos_hoja_primaria(self, hoja: str, evaluacion: int) -> _HojaPrimaria:
        """Lo que va dentro de la categoría de la hoja y lo que sube al MP de arriba.

        Devuelve nodos con el padre vacío: quien llama crea (o no) la categoría y les pone el
        padre. ``fuera`` son las piezas reales que pesan 0 en una hoja ``mediana`` o ``mas_alta``.
        """
        regla = self.esquema.regla_de(hoja)
        evidencias = self._evidencias(hoja, evaluacion)
        dentro: list[Nodo] = []
        fuera: list[Nodo] = []
        # La tarea real de B/C se queda con peso 0 en su primer criterio, aunque no tenga filas.
        for a in self.actividades:
            if (
                a.resultados
                and not a.recupera
                and a.evaluacion == evaluacion
                and a.evalua
                and a.evalua[0][0] == hoja
            ):
                self._tarea_real_cero(a, regla, dentro, fuera)
                break
        if not evidencias:
            return _HojaPrimaria(tuple(dentro), tuple(fuera))
        pesos = normalizar_pesos([e.peso for e in evidencias])
        for evidencia, peso in zip(evidencias, pesos, strict=True):
            if evidencia.tipo == "actividad":
                if evidencia.actividad.ruta in self.reales:
                    nodo = self._copia_de_actividad(evidencia.actividad, "", peso, hoja, evaluacion)
                else:
                    nodo = self._real(evidencia.actividad, "", peso)
                if regla in ("mediana", "mas_alta") and peso == 0:
                    fuera.append(replace(nodo, peso=0.0))
                else:
                    dentro.append(
                        replace(nodo, peso=None if regla in ("mediana", "mas_alta") else peso)
                    )
                continue
            # Un resultado por criterio (B) o por fila (C): el elemento del aula y su calculado.
            resultado = self._resultado_id(evidencia.actividad.ruta, evidencia.clave)
            nombre = (
                nombre_de_fila(self.esquema, evidencia.fila)
                if evidencia.fila is not None
                else self.nombre_de_hoja[hoja]
            )
            dentro.append(Nodo(resultado, "resultado", nombre, "", 0.0))
            calculado = self._calc_id(evidencia.actividad.ruta, evidencia.clave, hoja, evaluacion)
            nombre_calc = (
                nombre if evidencia.fila is not None else f"{evidencia.actividad.nombre} ({hoja})"
            )
            dentro.append(
                Nodo(
                    calculado,
                    "resultado_calc",
                    nombre_calc,
                    "",
                    None if regla in ("mediana", "mas_alta") else peso,
                    resultado,
                    maximo=100.0,
                )
            )
        return _HojaPrimaria(tuple(dentro), tuple(fuera))

    def _copia_curso(self, hoja: str, evaluacion: int, padre: str, peso: float | None) -> None:
        idnumber = self._copia_curso_id(hoja, evaluacion)
        self._agregar(
            Nodo(
                idnumber,
                "copia",
                f"{self.codigo_o_nombre[hoja]} · {_ordinal(evaluacion + 1)} evaluación",
                padre,
                peso,
                f"TZ_V_{evaluacion + 1}_{hoja}",
                maximo=100.0,
            )
        )

    def _pieza_recuperacion(
        self, actividad: _Actividad, hoja: str, evaluacion: int, padre: str
    ) -> None:
        """La actividad de recuperación: real en su primer sitio, copia en los demás."""
        if actividad.ruta not in self.reales and self.sitio_real_recuperacion.get(
            actividad.ruta
        ) == (hoja, evaluacion + 1):
            self._agregar(self._real(actividad, padre, None))
            return
        idnumber = self._copia_recuperacion_id(actividad.ruta, hoja, evaluacion)
        self._agregar(
            Nodo(
                idnumber,
                "copia",
                f"{actividad.nombre} (copia)",
                padre,
                None,
                actividad.ruta,
            )
        )

    def _contenido_hoja_secundaria(self, hoja: str, padre: str) -> None:
        """Las copias de los trimestres con evidencia (y la recuperación) en la vista del curso."""
        regla = self.esquema.regla_de(hoja)
        for evaluacion, cuota in sorted(self.q[hoja].items()):
            recuperadoras = self._recuperadoras(hoja, evaluacion + 1)
            if not recuperadoras:
                self._copia_curso(hoja, evaluacion, padre, cuota)
                continue
            if regla == "mas_alta":
                self._copia_curso(hoja, evaluacion, padre, None)
                for actividad in recuperadoras:
                    self._pieza_recuperacion(actividad, hoja, evaluacion, padre)
                continue
            grupo = self._rm_id(hoja, evaluacion + 1)
            self._agregar(
                Nodo(
                    grupo,
                    "categoria",
                    f"Recuperación {_ordinal(evaluacion + 1)} evaluación · "
                    f"{self.codigo_o_nombre[hoja]}",
                    padre,
                    cuota,
                    None,
                    "porcentaje",
                    agregacion=AGREGACION_MAS_ALTA,
                )
            )
            self._copia_curso(hoja, evaluacion, grupo, None)
            for actividad in recuperadoras:
                self._pieza_recuperacion(actividad, hoja, evaluacion, grupo)

    def _vista_elementos(self, padre: str) -> None:
        elementos = [e for e in self.esquema.elementos if any(self.q[h] for h in _hojas_de(e))]
        if not elementos:
            return
        pesos = normalizar_pesos([e.peso for e in elementos])
        for elemento, peso in zip(elementos, pesos, strict=True):
            if elemento.criterios:
                self._agregar(
                    Nodo(
                        f"TZ_E_{elemento.id}",
                        "categoria",
                        _texto_de_hoja(elemento, None),
                        padre,
                        peso,
                        None,
                        "porcentaje",
                        agregacion=AGREGACION_MEDIA_PONDERADA,
                    )
                )
                criterios = [c for c in elemento.criterios if self.q[c.id]]
                pesos_criterios = normalizar_pesos(
                    [1.0 if c.peso is None else c.peso for c in criterios]
                )
                for criterio, peso_criterio in zip(criterios, pesos_criterios, strict=True):
                    idnumber = f"TZ_E_{criterio.id}"
                    self._agregar(
                        Nodo(
                            idnumber,
                            "categoria",
                            _texto_de_hoja(elemento, criterio),
                            f"TZ_E_{elemento.id}",
                            peso_criterio,
                            None,
                            "porcentaje",
                            agregacion=self._agregacion(criterio.id),
                        )
                    )
                    self._contenido_hoja_secundaria(criterio.id, idnumber)
                continue
            idnumber = f"TZ_E_{elemento.id}"
            self._agregar(
                Nodo(
                    idnumber,
                    "categoria",
                    _texto_de_hoja(elemento, None),
                    padre,
                    peso,
                    None,
                    "porcentaje",
                    agregacion=self._agregacion(elemento.id),
                )
            )
            self._contenido_hoja_secundaria(elemento.id, idnumber)

    def _vista_evaluaciones(self, padre: str, da_la_final: bool) -> None:
        evaluaciones = self.esquema.evaluaciones
        presentes = [
            n
            for n in range(len(evaluaciones))
            if any(self._presente(h, n) for h in self.elemento_de_hoja)
        ]
        if not presentes:
            return
        if da_la_final:
            crudos: list[float] = []
            for n in presentes:
                peso_evaluacion = evaluaciones[n].peso
                crudos.append(1.0 if peso_evaluacion is None else peso_evaluacion)
            pesos = normalizar_pesos(crudos)
        else:
            pesos = [0.0] * len(presentes)
        pendientes: list[tuple[int, float, list[_ElementoPrimario]]] = []
        for evaluacion, peso in zip(presentes, pesos, strict=True):
            elementos = [
                e
                for e in self.esquema.elementos
                if any(self._presente(h, evaluacion) for h in _hojas_de(e))
            ]
            if not elementos:
                continue
            pesos_elementos = self._pesos_de_elementos(elementos, evaluacion)
            pendientes_elementos: list[_ElementoPrimario] = []
            for elemento, peso_elemento in zip(elementos, pesos_elementos, strict=True):
                if elemento.criterios:
                    criterios = [c for c in elemento.criterios if self._presente(c.id, evaluacion)]
                    if not criterios:
                        continue
                    pesos_criterios = self._pesos_de_criterios(criterios, evaluacion)
                    hijos: list[_CriterioPrimario] = []
                    for criterio, peso_criterio in zip(criterios, pesos_criterios, strict=True):
                        hoja = self._hijos_hoja_primaria(criterio.id, evaluacion)
                        if not hoja.dentro and not hoja.fuera:
                            continue
                        hijos.append(_CriterioPrimario(criterio, peso_criterio, hoja))
                    if hijos:
                        pendientes_elementos.append(
                            _ElementoPrimario(elemento, peso_elemento, tuple(hijos))
                        )
                    continue
                hoja = self._hijos_hoja_primaria(elemento.id, evaluacion)
                if hoja.dentro or hoja.fuera:
                    pendientes_elementos.append(
                        _ElementoPrimario(elemento, peso_elemento, hoja=hoja)
                    )
            if pendientes_elementos:
                pendientes.append((evaluacion, peso, pendientes_elementos))
        for evaluacion, peso, pendientes_elementos in pendientes:
            id_evaluacion = f"TZ_V_{evaluacion + 1}"
            self._agregar(
                Nodo(
                    id_evaluacion,
                    "categoria",
                    evaluaciones[evaluacion].nombre,
                    padre,
                    peso,
                    None,
                    "porcentaje",
                    agregacion=AGREGACION_MEDIA_PONDERADA,
                )
            )
            for pendiente in pendientes_elementos:
                elemento = pendiente.elemento
                id_elemento = f"TZ_V_{evaluacion + 1}_{elemento.id}"
                if elemento.criterios:
                    self._agregar(
                        Nodo(
                            id_elemento,
                            "categoria",
                            _texto_de_hoja(elemento, None),
                            id_evaluacion,
                            pendiente.peso,
                            None,
                            "porcentaje",
                            agregacion=AGREGACION_MEDIA_PONDERADA,
                        )
                    )
                    for hijo in pendiente.criterios:
                        criterio = hijo.criterio
                        if hijo.hoja.dentro:
                            id_criterio = f"TZ_V_{evaluacion + 1}_{criterio.id}"
                            self._agregar(
                                Nodo(
                                    id_criterio,
                                    "categoria",
                                    _texto_de_hoja(elemento, criterio),
                                    id_elemento,
                                    hijo.peso,
                                    None,
                                    "porcentaje",
                                    agregacion=self._agregacion(criterio.id),
                                )
                            )
                            self._agregar_en(hijo.hoja.dentro, id_criterio)
                        self._agregar_en(hijo.hoja.fuera, id_elemento)
                    continue
                if pendiente.hoja is None:
                    continue
                if pendiente.hoja.dentro:
                    self._agregar(
                        Nodo(
                            id_elemento,
                            "categoria",
                            _texto_de_hoja(elemento, None),
                            id_evaluacion,
                            pendiente.peso,
                            None,
                            "porcentaje",
                            agregacion=self._agregacion(elemento.id),
                        )
                    )
                    self._agregar_en(pendiente.hoja.dentro, id_elemento)
                self._agregar_en(pendiente.hoja.fuera, id_evaluacion)

    # -- la final, el tope y el resultado ---------------------------------

    def _primera_evaluacion(self, elemento: Elemento) -> int | None:
        hojas = set(_hojas_de(elemento))
        evaluaciones = [
            actividad.evaluacion
            for actividad in self.actividades
            if not actividad.recupera
            and any(dict(actividad.evalua).get(hoja, 0) > 0 for hoja in hojas)
        ]
        return min(evaluaciones) if evaluaciones else None

    def _tope_de_elementos(
        self,
    ) -> tuple[tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]]:
        if self.tope is None:
            return (), ()
        activos: list[tuple[str, int]] = []
        pendientes: list[tuple[str, int]] = []
        for elemento in self.esquema.elementos:
            evaluacion = self._primera_evaluacion(elemento)
            if evaluacion is None:
                continue
            pareja = (elemento.id, evaluacion + 1)
            if self.esquema.evaluaciones[evaluacion].cerrada:
                activos.append(pareja)
            else:
                pendientes.append(pareja)
        return tuple(activos), tuple(pendientes)

    def montar(self) -> Deseado:
        esquema = self.esquema
        por_elementos = esquema.final.de == "elementos"
        activos, pendientes = self._tope_de_elementos()
        self._agregar(
            Nodo(
                RAIZ,
                "contenedor",
                "Calificador de tiza",
                None,
                0.0 if self.anterior else 100.0,
                None,
                "porcentaje",
                agregacion=AGREGACION_MEDIA_PONDERADA,
            )
        )
        self._agregar(
            Nodo(
                FINAL,
                "categoria",
                "Final",
                RAIZ,
                100.0,
                None,
                "porcentaje",
                agregacion=AGREGACION_MEDIA_PONDERADA,
            )
        )
        self._agregar(
            Nodo(
                VISTA,
                "contenedor",
                "Por evaluaciones"
                if por_elementos
                else ("Por RA" if esquema.etapa == "fp" else "Por competencias"),
                RAIZ,
                0.0,
                None,
                "porcentaje",
                agregacion=AGREGACION_MEDIA_PONDERADA,
            )
        )
        # El orden importa: primero la vista que da la final; la otra cuelga de TZ_VISTA.
        if por_elementos:
            self._vista_elementos(FINAL)
            self._vista_evaluaciones(VISTA, False)
        else:
            self._vista_evaluaciones(FINAL, True)
            self._vista_elementos(VISTA)
        if self.tope is not None:
            self._agregar(
                Nodo(
                    NOTA_FINAL,
                    "nota",
                    "Nota final (sobre 10)",
                    RAIZ,
                    0.0,
                    None,
                    None,
                    maximo=100.0,
                )
            )
        tope = None
        if self.tope is not None:
            tope = (
                self.tope.si_alguno_menor_que,
                self.tope.maximo,
                tuple(f"TZ_E_{id_}" for id_, _ in activos),
            )
        total_curso = None if self.anterior else (NOTA_FINAL if self.tope else "porcentaje")
        con_actividades = {
            self.elemento_de_hoja[hoja] for a in self.actividades for hoja, _ in a.evalua
        }
        comprobar_sin_circulares(tuple(self.nodos))
        return Deseado(
            nodos=tuple(self.nodos),
            total_curso=total_curso,
            tope=tope,
            cerradas=tuple(f"TZ_V_{n}" for n, e in enumerate(esquema.evaluaciones, 1) if e.cerrada),
            actividades=self._actividades_reales(),
            resultados=tuple(
                (a.ruta, clave, self._resultado_id(a.ruta, clave))
                for a in self.actividades
                if a.resultados
                for clave in (
                    [fila.clave for fila in a.filas] if a.filas else [hoja for hoja, _ in a.evalua]
                )
            ),
            niveles=len(esquema.niveles_rubrica),
            tope_activos=activos,
            tope_pendientes=pendientes,
            avisos=tuple(
                ("CRITERIOS_SIN_PESO", e.id)
                for e in esquema.elementos
                if e.criterios and e.criterios[0].peso is None
            )
            + tuple(
                ("ELEMENTO_SIN_ACTIVIDADES", e.id)
                for e in esquema.elementos
                if e.id not in con_actividades
            )
            + tuple(
                ("EVIDENCIA_COMPARTIDA", a.nombre)
                for a in self.actividades
                if a.evidencia_declarada is None and sum(1 for _, peso in a.evalua if peso > 0) >= 2
            )
            + tuple(
                ("PESOS_SIN_EFECTO", hoja)
                for hoja, _ in _hojas(esquema)
                if self._pesos_sin_efecto(hoja)
            )
            + tuple(
                ("RECUPERACION_EN_CERRADA", f"TZ_V_{n}")
                for n, evaluacion in enumerate(esquema.evaluaciones, 1)
                if evaluacion.cerrada and self._recuperada_en(n)
            ),
        )

    def _pesos_sin_efecto(self, hoja: str) -> bool:
        if self.esquema.regla_de(hoja) not in ("mediana", "mas_alta"):
            return False
        pesos = [dict(a.evalua)[hoja] for a in self.actividades if hoja in dict(a.evalua)]
        positivos = [peso for peso in pesos if peso > 0]
        return bool(positivos) and len(set(positivos)) > 1

    def _recuperada_en(self, evaluacion: int) -> bool:
        return any(evaluacion in a.recupera for a in self.actividades)

    def _actividades_reales(self) -> tuple[tuple[str, str], ...]:
        reales = {n.idnumber: n.padre for n in self.nodos if n.clase == "actividad"}
        return tuple((ruta, padre) for ruta, padre in sorted(reales.items()) if padre is not None)


def _codigo_o_nombre_de_hoja(esquema: Esquema, hoja: str) -> str:
    """El código de la hoja si lo tiene; si no, su nombre. Para las copias del curso."""
    for elemento in esquema.elementos:
        if elemento.criterios:
            for criterio in elemento.criterios:
                if criterio.id == hoja:
                    return criterio.codigo or criterio.nombre
        elif elemento.id == hoja:
            return elemento.codigo or elemento.nombre
    return hoja
