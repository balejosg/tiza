"""La estructura deseada del calificador: pura, sin aula y sin cmids.

A partir del esquema (``esquema.py``) y del ``evalua`` de cada actividad, calcula qué árbol de
categorías, copias y calculados debe tener el calificador, con los pesos ya normalizados a 100
entre los hermanos que cuentan. Las actividades se identifican por su ruta relativa a la carpeta
(en POSIX); poner los cmids y comparar con el aula es cosa de las tareas siguientes.

Todo cuelga de ``TZ_TIZA``, que tiene siempre dos hijos (y un tercero con tope): ``TZ_FINAL``
(peso 100) y ``TZ_VISTA`` (peso 0). Hay dos vistas de lo mismo: «por elementos» (``TZ_E_<id>``, con
todo el curso) y «por evaluaciones» (``TZ_V_<n>``, con ``TZ_V_<n>_<id>`` dentro). La que da la
final cuelga de ``TZ_FINAL``; la otra, de ``TZ_VISTA``. Ningún calculado referencia a un
antepasado suyo (Moodle deja vacía una referencia circular): la nota final usa ``TZ_FINAL``, no
``TZ_TIZA``. La actividad real vive en su primera hoja de ``evalua``, en la vista de
``organizacion``; en los demás sitios va una copia ``TZ_C_<huella>``. Solo si la final tiene tope
hay ``TZ_NOTAS`` (peso 0), con las notas sobre 10 de los elementos y de la final calculadas con
contadores.

Una **hoja** es un criterio o un elemento sin criterios: ``evalua`` solo nombra hojas. Un elemento
con criterios tiene un nivel más: ``TZ_E_<elem>`` contiene ``TZ_E_<crit>`` (y esa, lo suyo) y
``TZ_V_<n>_<elem>`` contiene ``TZ_V_<n>_<crit>``. Un instrumento del esquema (``instrumentos``)
es una actividad sin fichero en el aula: su pieza real es una casilla manual ``TZ_M_<id>`` (clase
``manual``) y en los demás sitios va una copia suya. Un esquema sin criterios ni instrumentos da el
mismo árbol de siempre.

Una tarea con ``evidencia: resultados`` cambia su parte: en lugar de copias, cada criterio lleva un
elemento de resultado del aula (``TZ_O_<huella(ruta|criterio)>``, clase ``resultado``, peso 0, solo
en la vista real) y un calculado por vista (``TZ_R_<huella(ruta|criterio|vista)>``, clase
``resultado_calc``) con el peso de ``evalua``; la tarea real se queda con peso 0 en su primer
criterio. ``Deseado.resultados`` da las tripletas ``(ruta, criterio, TZ_O_…)`` para colocarlos.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from tiza.calificacion.esquema import (
    Criterio,
    Elemento,
    ErrorCalificacion,
    Esquema,
)
from tiza.contenido import Documento

__all__ = [
    "Deseado",
    "EvidenciaDeHoja",
    "Nodo",
    "comprobar_sin_circulares",
    "deseado",
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
    "contador",
    "indicador",
    "nota",
    "resultado",
    "resultado_calc",
)
RAIZ = "TZ_TIZA"
FINAL = "TZ_FINAL"
VISTA = "TZ_VISTA"
NOTAS = "TZ_NOTAS"
K_TIZA = "TZ_K_TIZA"
NOTA_FINAL = "TZ_NOTA_FINAL"
_VISTA_ELEMENTOS = "E"
_VISTA_EVALUACIONES = "V"
# Las agregaciones de Moodle que usa tiza (D1): Natural, Mediana y Calificación más alta.
AGREGACION_NATURAL = 13
AGREGACION_MEDIANA = 2
AGREGACION_MAS_ALTA = 6


@dataclass(frozen=True)
class Nodo:
    """Un nodo del calificador deseado.

    ``peso`` es el peso sobrescrito en su padre (``None``: sin peso sobrescrito, los hijos de un
    ``contador``). ``formula_de`` es, en una ``copia`` y un ``indicador``, el ``idnumber`` (o la
    ruta de la actividad) que reflejan; en una ``nota``, la pareja (total, contador); en un
    ``resultado_calc``, el ``idnumber`` del ``resultado`` del aula que reescala. La clase
    ``manual`` es la casilla de calificación manual de un instrumento (``TZ_M_<id>``, sin
    ``formula_de``); sus copias llevan ``formula_de="TZ_M_<id>"``. El ``resultado`` es el
    elemento del aula (``TZ_O_…``, peso 0, sin ``formula_de``). Las categorías son
    ``TZ_E_<elem>``, ``TZ_E_<crit>``, ``TZ_V_<n>``, ``TZ_V_<n>_<elem>`` y ``TZ_V_<n>_<crit>``.
    ``maximo`` es el máximo del calculado (10 en un ``resultado_calc``); ``None`` lo deja como
    lo decide el aula. ``agregacion`` es la de Moodle (13 Natural, 2 Mediana y 6 Calificación
    más alta): solo las subcategorías de una regla nativa o de una recuperación se apartan del
    valor de siempre.
    """

    idnumber: str
    clase: str
    nombre: str
    padre: str | None
    peso: float | None
    formula_de: str | tuple[str, str] | None = None
    visualizacion: str | None = None
    maximo: float | None = None
    agregacion: int = AGREGACION_NATURAL


@dataclass(frozen=True)
class Deseado:
    """El calificador deseado.

    ``nodos`` va en orden de creación (los padres antes que los hijos). ``tope`` es ``None`` o
    ``(umbral, maximo, idnumbers de las notas de los elementos)``. ``total_curso`` es ``None``
    (no se toca), ``"TZ_NOTA_FINAL"`` (calculado con esa nota) o ``"porcentaje"`` (solo la
    visualización). ``cerradas`` son los ``TZ_V_<n>`` de las evaluaciones cerradas;
    ``actividades`` empareja cada ruta con el ``idnumber`` de su padre real; ``avisos`` son
    pares ``(codigo, clave)``, con el id del elemento o, en ``EVIDENCIA_COMPARTIDA``, el nombre
    de la actividad o casilla manual; ``resultados`` son las tripletas ``(ruta, id del criterio,
    idnumber TZ_O_…)`` de las tareas con ``evidencia: resultados``. ``niveles`` es cuántos
    niveles tiene la escala de logro (``niveles_rubrica``), para la fórmula del calculado.
    """

    nodos: tuple[Nodo, ...]
    total_curso: str | None
    tope: tuple[float, float, tuple[str, ...]] | None
    cerradas: tuple[str, ...]
    actividades: tuple[tuple[str, str], ...]
    avisos: tuple[tuple[str, str], ...] = ()
    resultados: tuple[tuple[str, str, str], ...] = ()
    niveles: int = 5


@dataclass(frozen=True)
class _Actividad:
    ruta: str
    nombre: str
    evaluacion: int  # índice (desde 0) de la evaluación en la que cae su sección
    evalua: tuple[tuple[str, float], ...]
    manual: bool = False  # un instrumento: su ruta es el idnumber ``TZ_M_<id>`` de la casilla
    resultados: bool = False  # la tarea recoge la evidencia con resultados del aula
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
        resultado.append(
            _Actividad(
                ruta,
                documento.nombre,
                evaluacion,
                evalua,
                resultados=documento.evidencia == "resultados"
                and (resultados is None or ruta in resultados),
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


class _Montaje:
    def __init__(self, esquema: Esquema, actividades: list[_Actividad], anterior: bool) -> None:
        self.esquema = esquema
        self.actividades = actividades
        self.anterior = anterior
        self.tope = esquema.final.tope
        self.vista_real = (
            _VISTA_ELEMENTOS if esquema.organizacion == "elementos" else _VISTA_EVALUACIONES
        )
        self.elemento_de_hoja = dict(_hojas(esquema))
        self.nombre_de_hoja = {hoja: nombre_de_hoja(esquema, hoja) for hoja, _ in _hojas(esquema)}
        self.nodos: list[Nodo] = []
        self.copias = self._numerar_copias()
        # elemento -> hijos de sus hojas (en TZ_E_...) que cuentan (peso > 0), en orden: los
        # indicadores del contador
        self.hijos_de_elemento: dict[str, list[tuple[str, str]]] = {}

    def _lugares(self, actividad: _Actividad) -> list[tuple[str, str]]:
        """Los sitios (hoja, vista) donde va la actividad, real o copia."""
        return [
            (h, v) for h, _ in actividad.evalua for v in (_VISTA_ELEMENTOS, _VISTA_EVALUACIONES)
        ]

    def _numerar_copias(self) -> dict[tuple[str, str, str], str]:
        """``TZ_C_<huella>`` por (ruta, hoja, vista): estable al añadir o quitar actividades."""
        return {
            (a.ruta, hoja, vista): f"TZ_C_{_huella(f'{a.ruta}|{hoja}|{vista}')}"
            for a in self.actividades
            for hoja, vista in self._lugares(a)
            if not self._es_real(a, hoja, vista)
        }

    def _resultado_id(self, ruta: str, hoja: str) -> str:
        """``TZ_O_<huella>``: el elemento de resultado del aula de una tarea y un criterio."""
        return f"TZ_O_{_huella(f'{ruta}|{hoja}')}"

    def _calc_id(self, ruta: str, hoja: str, vista: str, grupo: int | None = None) -> str:
        """``TZ_R_<huella>``: el calculado que reescala el resultado en una vista.

        Una recuperación de una tarea con resultados puede aparecer en varias evaluaciones:
        cada grupo lleva su propio calculado del criterio, no una copia del calculado.
        """
        if grupo is None:
            return f"TZ_R_{_huella(f'{ruta}|{hoja}|{vista}')}"
        return f"TZ_R_{_huella(f'{ruta}|{hoja}|{vista}|recupera|{grupo}')}"

    def _es_real(self, actividad: _Actividad, hoja: str, vista: str) -> bool:
        return hoja == actividad.evalua[0][0] and vista == self.vista_real

    def _agregar(self, nodo: Nodo) -> None:
        self.nodos.append(nodo)

    def _de_hoja(self, hoja: str, evaluacion: int | None = None) -> list[_Actividad]:
        """Lo que evalúa la hoja (en una evaluación, si se da), en el orden de ``actividades``."""
        return [
            a
            for a in self.actividades
            if hoja in dict(a.evalua) and (evaluacion is None or a.evaluacion == evaluacion)
        ]

    def _nula(self, hojas: list[str], evaluacion: int | None = None) -> bool:
        """Tiene actividades (en la evaluación, si se da) pero ninguna pesa > 0 en su ``evalua``.

        Moodle daría por completa una categoría así (máximo 0): no aporta a su padre, como la
        que no tiene actividades, y sus hermanos se renormalizan sin ella. Una recuperación no
        es evidencia de la evaluación de su sección: su peso no la saca de ``nula``.
        """
        hay = False
        pesos: list[float] = []
        for h in hojas:
            regla = self.esquema.regla_de(h)
            for a in self._de_hoja(h, evaluacion):
                hay = True
                if not a.recupera:
                    pesos.append(dict(a.evalua)[h])
                elif regla == "mas_alta" and (evaluacion is None or evaluacion + 1 in a.recupera):
                    # En «más alta» la recuperación es una evidencia más, con su valor.
                    pesos.append(1.0)
        return hay and not any(p > 0 for p in pesos)

    def _pesos_de_elementos(
        self, elementos: list[Elemento], evaluacion: int | None = None
    ) -> list[float]:
        """Los pesos de unos elementos, normalizados a 100 sin los que no aportan."""
        return normalizar_pesos(
            [0.0 if self._nula(_hojas_de(e), evaluacion) else e.peso for e in elementos]
        )

    def _pesos_de_criterios(
        self, criterios: list[Criterio], evaluacion: int | None = None
    ) -> list[float]:
        """Los pesos de unos criterios del elemento, normalizados a 100 (iguales si no llevan).

        Un criterio que no aporta (``_nula``) pesa 0 y los demás se reparten el 100.
        """
        return normalizar_pesos(
            [
                0.0 if self._nula([c.id], evaluacion) else 1.0 if c.peso is None else c.peso
                for c in criterios
            ]
        )

    def _pieza_real(
        self, actividad: _Actividad, hoja: str, vista: str, grupo: int | None = None
    ) -> bool:
        """La pieza real de una recuperación vive siempre en la vista por elementos (D9)."""
        if actividad.recupera:
            return (
                hoja == actividad.evalua[0][0]
                and vista == _VISTA_ELEMENTOS
                and (grupo is None or grupo == min(actividad.recupera))
            )
        return self._es_real(actividad, hoja, vista)

    def _copia_id(self, actividad: _Actividad, hoja: str, vista: str, grupo: int | None) -> str:
        if actividad.recupera:
            # Una recuperación puede repetirse en varias evaluaciones: cada copia necesita su id.
            return f"TZ_C_{_huella(f'{actividad.ruta}|{hoja}|{vista}|recupera|{grupo or 0}')}"
        return self.copias[(actividad.ruta, hoja, vista)]

    def _evidencia(
        self,
        padre: str,
        hoja: str,
        vista: str,
        actividad: _Actividad,
        peso: float | None,
        grupo: int | None = None,
    ) -> str:
        """La evidencia de una actividad en un contenedor (calculado, actividad real o copia)."""
        if actividad.resultados:
            calculado = self._calc_id(
                actividad.ruta, hoja, vista, grupo if actividad.recupera else None
            )
            self._agregar(
                Nodo(
                    calculado,
                    "resultado_calc",
                    f"{actividad.nombre} ({hoja})",
                    padre,
                    peso,
                    self._resultado_id(actividad.ruta, hoja),
                    maximo=10.0,
                )
            )
            return calculado
        if self._pieza_real(actividad, hoja, vista, grupo):
            clase = "manual" if actividad.manual else "actividad"
            self._agregar(Nodo(actividad.ruta, clase, actividad.nombre, padre, peso))
            return actividad.ruta
        idnumber = self._copia_id(actividad, hoja, vista, grupo)
        self._agregar(
            Nodo(idnumber, "copia", f"{actividad.nombre} (copia)", padre, peso, actividad.ruta)
        )
        return idnumber

    def _pieza_completa(
        self, padre: str, hoja: str, vista: str, actividad: _Actividad, peso: float
    ) -> str:
        """La actividad entera en el contenedor: real, resultado del aula y calculado o copia."""
        if actividad.resultados:
            if self._pieza_real(actividad, hoja, vista):
                clase = "manual" if actividad.manual else "actividad"
                self._agregar(Nodo(actividad.ruta, clase, actividad.nombre, padre, 0.0))
            if vista == self.vista_real:
                self._agregar(
                    Nodo(
                        self._resultado_id(actividad.ruta, hoja),
                        "resultado",
                        self.nombre_de_hoja[hoja],
                        padre,
                        0.0,
                    )
                )
        return self._evidencia(padre, hoja, vista, actividad, peso)

    def _base_resultados(self, padre: str, hoja: str, vista: str, actividad: _Actividad) -> None:
        """Lo que no es evidencia de una tarea con resultados: su actividad real y su resultado.

        Lo que va dentro de una regla o de una recuperación es el calculado del criterio; la
        tarea real y el elemento de resultado del aula se quedan fuera, con peso 0 (D10/D9).
        """
        if self._pieza_real(actividad, hoja, vista):
            clase = "manual" if actividad.manual else "actividad"
            self._agregar(Nodo(actividad.ruta, clase, actividad.nombre, padre, 0.0))
        if vista == self.vista_real:
            self._agregar(
                Nodo(
                    self._resultado_id(actividad.ruta, hoja),
                    "resultado",
                    self.nombre_de_hoja[hoja],
                    padre,
                    0.0,
                )
            )

    def _peso_base(self, actividad: _Actividad, hoja: str, vista: str, regla: str) -> float:
        """El peso de ``evalua``, con el factor de su evaluación si la hoja es progresiva."""
        peso = dict(actividad.evalua)[hoja]
        if regla == "progresiva" and vista == _VISTA_ELEMENTOS:
            return peso * self.esquema.agregacion.factores[actividad.evaluacion]
        return peso

    def _recuperadas(self, hoja: str) -> list[int]:
        """Las evaluaciones (1-based) que alguna actividad recupera en esta hoja."""
        return sorted({n for a in self.actividades if hoja in dict(a.evalua) for n in a.recupera})

    def _recuperadoras(self, hoja: str, evaluacion: int) -> list[_Actividad]:
        """Las actividades que recuperan esa evaluación (1-based) en esta hoja."""
        return [
            a
            for a in self.actividades
            if hoja in dict(a.evalua) and a.recupera and evaluacion in a.recupera
        ]

    def _contenido_hoja(
        self,
        padre: str,
        hoja: str,
        vista: str,
        evaluacion: int | None,
        cuenta: bool = True,
    ) -> None:
        """Lo que cuelga de la categoría de una hoja, según su regla y sus recuperaciones."""
        regla = self.esquema.regla_de(hoja)
        if regla in ("mediana", "mas_alta"):
            self._contenido_regla(padre, hoja, vista, evaluacion, regla, cuenta)
        else:
            self._contenido_media(padre, hoja, vista, evaluacion, regla, cuenta)

    def _contenido_regla(
        self,
        padre: str,
        hoja: str,
        vista: str,
        evaluacion: int | None,
        regla: str,
        cuenta: bool,
    ) -> None:
        """Mediana o más alta: la subcategoría con lo que cuenta; fuera, lo que pesa 0."""
        dentro: list[_Actividad] = []
        for a in self.actividades:
            if hoja not in dict(a.evalua):
                continue
            if a.recupera:
                if evaluacion is None or (
                    evaluacion + 1 in a.recupera
                    and not self.esquema.evaluaciones[evaluacion].cerrada
                ):
                    dentro.append(a)
            elif evaluacion is not None and a.evaluacion != evaluacion:
                continue
            elif dict(a.evalua)[hoja] > 0:
                dentro.append(a)
        sufijo = "E" if evaluacion is None else f"V_{evaluacion + 1}"
        agregacion = AGREGACION_MEDIANA if regla == "mediana" else AGREGACION_MAS_ALTA
        nombre_regla = "Mediana" if regla == "mediana" else "Calificación más alta"
        ag_id = f"TZ_AG_{sufijo}_{hoja}"
        self._agregar(
            Nodo(
                ag_id,
                "categoria",
                f"{self.nombre_de_hoja[hoja]} ({nombre_regla})",
                padre,
                100.0,
                None,
                "porcentaje",
                agregacion=agregacion,
            )
        )
        for a in dentro:
            grupo = None if evaluacion is None else evaluacion + 1
            self._evidencia(ag_id, hoja, vista, a, None, grupo=grupo)
        # Con tope, el contador cuenta la subcategoría entera (máximo 100), no sus evidencias:
        # una regla no Natural no suma los máximos de dentro.
        if vista == _VISTA_ELEMENTOS and cuenta and dentro:
            self.hijos_de_elemento.setdefault(self.elemento_de_hoja[hoja], []).append(
                (ag_id, f"{self.nombre_de_hoja[hoja]} ({nombre_regla})")
            )
        # Lo de peso 0 se queda fuera de la regla, como hoy.
        for a in self.actividades:
            if hoja not in dict(a.evalua) or a.recupera:
                continue
            if evaluacion is not None and a.evaluacion != evaluacion:
                continue
            if dict(a.evalua)[hoja] == 0:
                self._pieza_completa(padre, hoja, vista, a, 0.0)
        # La tarea real con resultados y su elemento del aula, fuera de la regla.
        for a in self.actividades:
            if not a.resultados or hoja not in dict(a.evalua):
                continue
            if evaluacion is not None and a.evaluacion != evaluacion:
                continue
            if a.recupera or dict(a.evalua)[hoja] > 0:
                self._base_resultados(padre, hoja, vista, a)

    def _contenido_media(
        self,
        padre: str,
        hoja: str,
        vista: str,
        evaluacion: int | None,
        regla: str,
        cuenta: bool,
    ) -> None:
        """Media o progresiva: los pesos de ``evalua``, con la recuperación si la hay (D9)."""
        normales = [
            a
            for a in self.actividades
            if hoja in dict(a.evalua)
            and not a.recupera
            and (evaluacion is None or a.evaluacion == evaluacion)
        ]
        base = [self._peso_base(a, hoja, vista, regla) for a in normales]
        pesos = normalizar_pesos(base)
        recuperadas = self._recuperadas(hoja)
        if evaluacion is None:
            grupos = recuperadas
        else:
            grupos = (
                [evaluacion + 1]
                if evaluacion + 1 in recuperadas
                and not self.esquema.evaluaciones[evaluacion].cerrada
                else []
            )
        en_grupo: dict[int, int] = {}
        for r in grupos:
            for i, a in enumerate(normales):
                if a.evaluacion == r - 1 and dict(a.evalua)[hoja] > 0:
                    en_grupo[i] = r
        for r in grupos:
            indices = [i for i, a in enumerate(normales) if en_grupo.get(i) == r]
            evidencias = [normales[i] for i in indices]
            pesos_grupo = normalizar_pesos([base[i] for i in indices])
            peso_rm = 100.0 if evaluacion is not None else round(sum(pesos[i] for i in indices), 2)
            sufijo = "E" if evaluacion is None else "V"
            rm_id = f"TZ_RM_{sufijo}_{r}_{hoja}"
            rp_id = f"TZ_RP_{sufijo}_{r}_{hoja}"
            nombre_eval = self.esquema.evaluaciones[r - 1].nombre
            self._agregar(
                Nodo(
                    rm_id,
                    "categoria",
                    f"Recuperación · {self.nombre_de_hoja[hoja]} ({nombre_eval})",
                    padre,
                    peso_rm,
                    None,
                    "porcentaje",
                    agregacion=AGREGACION_MAS_ALTA,
                )
            )
            self._agregar(
                Nodo(
                    rp_id,
                    "categoria",
                    f"Evidencias · {self.nombre_de_hoja[hoja]} ({nombre_eval})",
                    rm_id,
                    None,
                    None,
                    "porcentaje",
                    agregacion=AGREGACION_NATURAL,
                )
            )
            for a, p in zip(evidencias, pesos_grupo, strict=True):
                self._evidencia(rp_id, hoja, vista, a, p, grupo=r)
            for a in self._recuperadoras(hoja, r):
                self._evidencia(rm_id, hoja, vista, a, None, grupo=r)
            # Con tope, la recuperación cuenta como una subcategoría (máximo 100).
            if vista == _VISTA_ELEMENTOS and cuenta:
                self.hijos_de_elemento.setdefault(self.elemento_de_hoja[hoja], []).append(
                    (rm_id, f"Recuperación · {self.nombre_de_hoja[hoja]} ({nombre_eval})")
                )
        # Fuera de las recuperaciones: lo que no va en ningún TZ_RM.
        for i, (a, peso) in enumerate(zip(normales, pesos, strict=True)):
            if i in en_grupo:
                if a.resultados:
                    self._base_resultados(padre, hoja, vista, a)
                continue
            referencia = self._pieza_completa(padre, hoja, vista, a, peso)
            if vista == _VISTA_ELEMENTOS and peso > 0 and cuenta:
                self.hijos_de_elemento.setdefault(self.elemento_de_hoja[hoja], []).append(
                    (referencia, a.nombre)
                )
        # La parte real de una recuperación con resultados, fuera de su TZ_RM.
        for a in self.actividades:
            if not a.resultados or not a.recupera or hoja not in dict(a.evalua):
                continue
            if evaluacion is not None and a.evaluacion != evaluacion:
                continue
            self._base_resultados(padre, hoja, vista, a)

    def _vista_elementos(self, padre: str) -> None:
        pesos = self._pesos_de_elementos(list(self.esquema.elementos))
        for elemento, peso in zip(self.esquema.elementos, pesos, strict=True):
            idnumber = f"TZ_E_{elemento.id}"
            self._agregar(
                Nodo(idnumber, "categoria", elemento.nombre, padre, peso, None, "porcentaje")
            )
            if not elemento.criterios:
                self._contenido_hoja(idnumber, elemento.id, _VISTA_ELEMENTOS, None)
                continue
            criterios = list(elemento.criterios)
            for criterio, peso_criterio in zip(
                criterios, self._pesos_de_criterios(criterios), strict=True
            ):
                interior = f"TZ_E_{criterio.id}"
                self._agregar(
                    Nodo(
                        interior,
                        "categoria",
                        criterio.nombre,
                        idnumber,
                        peso_criterio,
                        None,
                        "porcentaje",
                    )
                )
                self._contenido_hoja(
                    interior,
                    criterio.id,
                    _VISTA_ELEMENTOS,
                    None,
                    cuenta=peso_criterio > 0,
                )

    def _vista_evaluaciones(self, padre: str, da_la_final: bool) -> None:
        evaluaciones = self.esquema.evaluaciones
        if da_la_final:
            # una evaluación cuyo contenido pesa todo 0 no aporta (``_nula``), como un criterio
            pesos = normalizar_pesos(
                [
                    0.0
                    if self._nula([h for e in self.esquema.elementos for h in _hojas_de(e)], n)
                    else evaluacion.peso or 0.0
                    for n, evaluacion in enumerate(evaluaciones)
                ]
            )
        else:
            pesos = [0.0] * len(evaluaciones)
        for n, (evaluacion, peso) in enumerate(zip(evaluaciones, pesos, strict=True), 1):
            idnumber = f"TZ_V_{n}"
            self._agregar(
                Nodo(idnumber, "categoria", evaluacion.nombre, padre, peso, None, "porcentaje")
            )
            presentes = [
                e
                for e in self.esquema.elementos
                if any(self._de_hoja(hoja, n - 1) for hoja in _hojas_de(e))
            ]
            for elemento, peso_elemento in zip(
                presentes, self._pesos_de_elementos(presentes, n - 1), strict=True
            ):
                interior = f"TZ_V_{n}_{elemento.id}"
                self._agregar(
                    Nodo(
                        interior,
                        "categoria",
                        elemento.nombre,
                        idnumber,
                        peso_elemento,
                        None,
                        "porcentaje",
                    )
                )
                if not elemento.criterios:
                    self._contenido_hoja(interior, elemento.id, _VISTA_EVALUACIONES, n - 1)
                    continue
                con_algo = [c for c in elemento.criterios if self._de_hoja(c.id, n - 1)]
                for criterio, peso_criterio in zip(
                    con_algo, self._pesos_de_criterios(con_algo, n - 1), strict=True
                ):
                    dentro = f"TZ_V_{n}_{criterio.id}"
                    self._agregar(
                        Nodo(
                            dentro,
                            "categoria",
                            criterio.nombre,
                            interior,
                            peso_criterio,
                            None,
                            "porcentaje",
                        )
                    )
                    self._contenido_hoja(dentro, criterio.id, _VISTA_EVALUACIONES, n - 1)

    def _notas(self) -> None:
        self._agregar(Nodo(NOTAS, "contenedor", "Notas (sobre 10)", RAIZ, 0.0, None, "porcentaje"))
        for elemento in self.esquema.elementos:
            id_ = elemento.id
            self._agregar(Nodo(f"TZ_K_{id_}", "contador", f"Contador {id_}", NOTAS, 0.0))
            for hijo, nombre in self.hijos_de_elemento.get(id_, []):
                self._agregar(
                    Nodo(
                        f"TZ_I_{_huella(f'{id_}|{hijo}')}",
                        "indicador",
                        f"Indicador {nombre}",
                        f"TZ_K_{id_}",
                        None,
                        hijo,
                    )
                )
            self._agregar(
                Nodo(
                    f"TZ_NOTA_E_{id_}",
                    "nota",
                    f"{elemento.nombre} (sobre 10)",
                    NOTAS,
                    0.0,
                    (f"TZ_E_{id_}", f"TZ_K_{id_}"),
                )
            )
        self._agregar(Nodo(K_TIZA, "contador", "Contador final", NOTAS, 0.0))
        for elemento in self.esquema.elementos:
            self._agregar(
                Nodo(
                    f"TZ_KC_{elemento.id}",
                    "copia",
                    f"Contador {elemento.id} (copia)",
                    K_TIZA,
                    None,
                    f"TZ_K_{elemento.id}",
                )
            )
        self._agregar(
            Nodo(NOTA_FINAL, "nota", "Nota final (sobre 10)", NOTAS, 0.0, (FINAL, K_TIZA))
        )

    def montar(self) -> Deseado:
        esquema = self.esquema
        por_elementos = esquema.final.de == "elementos"
        raiz = 0.0 if self.anterior else 100.0
        self._agregar(
            Nodo(RAIZ, "contenedor", "Calificador de tiza", None, raiz, None, "porcentaje")
        )
        # los hijos de TZ_TIZA van en orden: TZ_FINAL (la vista que da la final), TZ_VISTA, TZ_NOTAS
        self._agregar(Nodo(FINAL, "categoria", "Final", RAIZ, 100.0, None, "porcentaje"))
        if por_elementos:
            self._vista_elementos(FINAL)
        else:
            self._vista_evaluaciones(FINAL, True)
        nombre_vista = "Vista por evaluaciones" if por_elementos else "Vista por elementos"
        self._agregar(Nodo(VISTA, "contenedor", nombre_vista, RAIZ, 0.0, None, "porcentaje"))
        if por_elementos:
            self._vista_evaluaciones(VISTA, False)
        else:
            self._vista_elementos(VISTA)
        if self.tope is not None:
            self._notas()
        tope = None
        if self.tope is not None:
            tope = (
                self.tope.si_alguno_menor_que,
                self.tope.maximo,
                tuple(f"TZ_NOTA_E_{e.id}" for e in esquema.elementos),
            )
        total_curso = None if self.anterior else (NOTA_FINAL if self.tope else "porcentaje")
        con_actividades = {self.elemento_de_hoja[h] for a in self.actividades for h, _ in a.evalua}
        comprobar_sin_circulares(tuple(self.nodos))
        return Deseado(
            nodos=tuple(self.nodos),
            total_curso=total_curso,
            tope=tope,
            cerradas=tuple(f"TZ_V_{n}" for n, e in enumerate(esquema.evaluaciones, 1) if e.cerrada),
            actividades=self._actividades_reales(),
            resultados=tuple(
                (a.ruta, hoja, self._resultado_id(a.ruta, hoja))
                for a in self.actividades
                if a.resultados
                for hoja, _ in a.evalua
            ),
            niveles=len(esquema.niveles_rubrica),
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
        """La regla ignora los pesos de ``evalua`` y no son todos iguales (D6)."""
        if self.esquema.regla_de(hoja) not in ("mediana", "mas_alta"):
            return False
        pesos = [dict(a.evalua)[hoja] for a in self.actividades if hoja in dict(a.evalua)]
        positivos = [peso for peso in pesos if peso > 0]
        return bool(positivos) and len(set(positivos)) > 1

    def _recuperada_en(self, evaluacion: int) -> bool:
        """Alguna actividad recupera esa evaluación (1-based)."""
        return any(evaluacion in a.recupera for a in self.actividades)

    def _actividades_reales(self) -> tuple[tuple[str, str], ...]:
        reales = {n.idnumber: n.padre for n in self.nodos if n.clase == "actividad"}
        return tuple((ruta, padre) for ruta, padre in sorted(reales.items()) if padre is not None)
