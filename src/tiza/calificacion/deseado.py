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
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from tiza.calificacion.esquema import (
    TOLERANCIA_PESOS,
    Criterio,
    Elemento,
    ErrorCalificacion,
    Esquema,
)
from tiza.contenido import Documento

__all__ = ["Deseado", "Nodo", "comprobar_sin_circulares", "deseado"]

CLASES = (
    "contenedor",
    "categoria",
    "actividad",
    "manual",
    "copia",
    "contador",
    "indicador",
    "nota",
)
RAIZ = "TZ_TIZA"
FINAL = "TZ_FINAL"
VISTA = "TZ_VISTA"
NOTAS = "TZ_NOTAS"
K_TIZA = "TZ_K_TIZA"
NOTA_FINAL = "TZ_NOTA_FINAL"
_VISTA_ELEMENTOS = "E"
_VISTA_EVALUACIONES = "V"


@dataclass(frozen=True)
class Nodo:
    """Un nodo del calificador deseado.

    ``peso`` es el peso sobrescrito en su padre (``None``: sin peso sobrescrito, los hijos de un
    ``contador``). ``formula_de`` es, en una ``copia`` y un ``indicador``, el ``idnumber`` (o la
    ruta de la actividad) que reflejan; en una ``nota``, la pareja (total, contador). La clase
    ``manual`` es la casilla de calificación manual de un instrumento (``TZ_M_<id>``, sin
    ``formula_de``); sus copias llevan ``formula_de="TZ_M_<id>"``. Las categorías son
    ``TZ_E_<elem>``, ``TZ_E_<crit>``, ``TZ_V_<n>``, ``TZ_V_<n>_<elem>`` y ``TZ_V_<n>_<crit>``.
    """

    idnumber: str
    clase: str
    nombre: str
    padre: str | None
    peso: float | None
    formula_de: str | tuple[str, str] | None = None
    visualizacion: str | None = None


@dataclass(frozen=True)
class Deseado:
    """El calificador deseado.

    ``nodos`` va en orden de creación (los padres antes que los hijos). ``tope`` es ``None`` o
    ``(umbral, maximo, idnumbers de las notas de los elementos)``. ``total_curso`` es ``None``
    (no se toca), ``"TZ_NOTA_FINAL"`` (calculado con esa nota) o ``"porcentaje"`` (solo la
    visualización). ``cerradas`` son los ``TZ_V_<n>`` de las evaluaciones cerradas;
    ``actividades`` empareja cada ruta con el ``idnumber`` de su padre real; ``avisos`` son
    pares ``(codigo, id del elemento)``.
    """

    nodos: tuple[Nodo, ...]
    total_curso: str | None
    tope: tuple[float, float, tuple[str, ...]] | None
    cerradas: tuple[str, ...]
    actividades: tuple[tuple[str, str], ...]
    avisos: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class _Actividad:
    ruta: str
    nombre: str
    evaluacion: int  # índice (desde 0) de la evaluación en la que cae su sección
    evalua: tuple[tuple[str, float], ...]
    manual: bool = False  # un instrumento: su ruta es el idnumber ``TZ_M_<id>`` de la casilla


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


def _normalizar(pesos: list[float]) -> list[float]:
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


def _validar(
    esquema: Esquema,
    ruta: str,
    evalua: tuple[tuple[str, float], ...],
    seccion: int | str,
) -> int:
    """Comprueba el ``evalua`` y la sección de una actividad o instrumento; da su evaluación."""
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
    evaluacion = next(
        (
            i
            for i, ev in enumerate(esquema.evaluaciones)
            if any(_misma_seccion(seccion, s) for s in ev.secciones)
        ),
        None,
    )
    if evaluacion is None:
        raise ErrorCalificacion(
            "SECCION_SIN_EVALUACION",
            f"{ruta}: la sección «{seccion}» no está en ninguna evaluación de calificacion.yaml",
        )
    return evaluacion


def _actividades(esquema: Esquema, documentos: list[Documento], carpeta: Path) -> list[_Actividad]:
    """Las actividades que cuentan, validadas una a una.

    Primero las de fichero, ordenadas por ruta, y luego los instrumentos, en el orden del esquema.
    """
    resultado: list[_Actividad] = []
    for documento in sorted(documentos, key=lambda d: _ruta_relativa(d.ruta, carpeta)):
        if documento.evalua is None:
            continue
        ruta = _ruta_relativa(documento.ruta, carpeta)
        evaluacion = _validar(esquema, ruta, documento.evalua, documento.seccion)
        resultado.append(_Actividad(ruta, documento.nombre, evaluacion, documento.evalua))
    for i, instrumento in enumerate(esquema.instrumentos):
        evaluacion = _validar(
            esquema, f"instrumentos[{i}]", instrumento.evalua, instrumento.seccion
        )
        resultado.append(
            _Actividad(
                f"TZ_M_{instrumento.id}",
                instrumento.nombre,
                evaluacion,
                instrumento.evalua,
                manual=True,
            )
        )
    return resultado


def _comprobar_pesos(esquema: Esquema, actividades: list[_Actividad]) -> None:
    """Los pesos de lo que evalúa cada hoja suman 0 o 100."""
    for hoja, _ in _hojas(esquema):
        pesos = [(a.ruta, dict(a.evalua)[hoja]) for a in actividades if hoja in dict(a.evalua)]
        total = round(sum(p for _, p in pesos), 2)
        if total != 0 and round(abs(total - 100), 2) > TOLERANCIA_PESOS:
            rutas = ", ".join(r for r, _ in pesos[:5]) + (", …" if len(pesos) > 5 else "")
            raise ErrorCalificacion(
                "PESOS_NO_SUMAN_100",
                f"{hoja}: los pesos de sus actividades suman {total:g} y deben sumar 100 ({rutas})",
            )


def deseado(
    esquema: Esquema, documentos: list[Documento], anterior: bool, carpeta: Path
) -> Deseado:
    """Calcula el calificador deseado. Lanza ``ErrorCalificacion`` si las actividades no cuadran.

    Solo cuentan los documentos con ``evalua``. ``anterior`` es que el curso ya tenía un
    calificador ajeno: entonces ``TZ_TIZA`` pesa 0 en el total del curso y este no se toca.
    """
    actividades = _actividades(esquema, documentos, carpeta)
    _comprobar_pesos(esquema, actividades)
    return _Montaje(esquema, actividades, anterior).montar()


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
        que no tiene actividades, y sus hermanos se renormalizan sin ella.
        """
        pesos = [dict(a.evalua)[h] for h in hojas for a in self._de_hoja(h, evaluacion)]
        return bool(pesos) and not any(p > 0 for p in pesos)

    def _pesos_de_elementos(
        self, elementos: list[Elemento], evaluacion: int | None = None
    ) -> list[float]:
        """Los pesos de unos elementos, normalizados a 100 sin los que no aportan."""
        return _normalizar(
            [0.0 if self._nula(_hojas_de(e), evaluacion) else e.peso for e in elementos]
        )

    def _pesos_de_criterios(
        self, criterios: list[Criterio], evaluacion: int | None = None
    ) -> list[float]:
        """Los pesos de unos criterios del elemento, normalizados a 100 (iguales si no llevan).

        Un criterio que no aporta (``_nula``) pesa 0 y los demás se reparten el 100.
        """
        return _normalizar(
            [
                0.0 if self._nula([c.id], evaluacion) else 1.0 if c.peso is None else c.peso
                for c in criterios
            ]
        )

    def _hijos_actividad(
        self, padre: str, hoja: str, vista: str, actividades: list[_Actividad], cuenta: bool = True
    ) -> None:
        """Las actividades (reales o copias) de un contenedor, con el peso renormalizado.

        ``cuenta`` es que el contenedor pesa algo para su elemento: si no, sus hijos no dan
        indicador al contador.
        """
        pesos = _normalizar([dict(a.evalua)[hoja] for a in actividades])
        for a, peso in zip(actividades, pesos, strict=True):
            if self._es_real(a, hoja, vista):
                clase = "manual" if a.manual else "actividad"
                hijo = Nodo(a.ruta, clase, a.nombre, padre, peso)
            else:
                idnumber = self.copias[(a.ruta, hoja, vista)]
                hijo = Nodo(idnumber, "copia", f"{a.nombre} (copia)", padre, peso, a.ruta)
            self._agregar(hijo)
            if vista == _VISTA_ELEMENTOS and peso > 0 and cuenta:
                self.hijos_de_elemento.setdefault(self.elemento_de_hoja[hoja], []).append(
                    (hijo.idnumber, a.nombre)
                )

    def _vista_elementos(self, padre: str) -> None:
        pesos = self._pesos_de_elementos(list(self.esquema.elementos))
        for elemento, peso in zip(self.esquema.elementos, pesos, strict=True):
            idnumber = f"TZ_E_{elemento.id}"
            self._agregar(
                Nodo(idnumber, "categoria", elemento.nombre, padre, peso, None, "porcentaje")
            )
            if not elemento.criterios:
                self._hijos_actividad(
                    idnumber, elemento.id, _VISTA_ELEMENTOS, self._de_hoja(elemento.id)
                )
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
                self._hijos_actividad(
                    interior,
                    criterio.id,
                    _VISTA_ELEMENTOS,
                    self._de_hoja(criterio.id),
                    cuenta=peso_criterio > 0,
                )

    def _vista_evaluaciones(self, padre: str, da_la_final: bool) -> None:
        evaluaciones = self.esquema.evaluaciones
        if da_la_final:
            pesos = _normalizar([e.peso or 0.0 for e in evaluaciones])
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
                    self._hijos_actividad(
                        interior,
                        elemento.id,
                        _VISTA_EVALUACIONES,
                        self._de_hoja(elemento.id, n - 1),
                    )
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
                    self._hijos_actividad(
                        dentro,
                        criterio.id,
                        _VISTA_EVALUACIONES,
                        self._de_hoja(criterio.id, n - 1),
                    )

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
            avisos=tuple(
                ("CRITERIOS_SIN_PESO", e.id)
                for e in esquema.elementos
                if e.criterios and e.criterios[0].peso is None
            )
            + tuple(
                ("ELEMENTO_SIN_ACTIVIDADES", e.id)
                for e in esquema.elementos
                if e.id not in con_actividades
            ),
        )

    def _actividades_reales(self) -> tuple[tuple[str, str], ...]:
        reales = {n.idnumber: n.padre for n in self.nodos if n.clase == "actividad"}
        return tuple((ruta, padre) for ruta, padre in sorted(reales.items()) if padre is not None)
