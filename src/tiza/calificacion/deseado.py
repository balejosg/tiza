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
``TZ_TIZA``. La actividad real vive en su primer elemento de
``evalua``, en la vista de ``organizacion``; en los demás sitios va una copia ``TZ_C_<huella>``. Solo
si la final tiene tope hay ``TZ_NOTAS`` (peso 0), con las notas sobre 10 de los elementos y de la
final calculadas con contadores.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from tiza.calificacion.esquema import TOLERANCIA_PESOS, ErrorCalificacion, Esquema
from tiza.contenido import Documento

__all__ = ["Deseado", "Nodo", "comprobar_sin_circulares", "deseado"]

CLASES = ("contenedor", "categoria", "actividad", "copia", "contador", "indicador", "nota")
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
    ruta de la actividad) que reflejan; en una ``nota``, la pareja (total, contador).
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


def _actividades(esquema: Esquema, documentos: list[Documento], carpeta: Path) -> list[_Actividad]:
    """Las actividades que cuentan, ordenadas por ruta y validadas una a una."""
    ids = {e.id for e in esquema.elementos}
    resultado: list[_Actividad] = []
    for documento in sorted(documentos, key=lambda d: _ruta_relativa(d.ruta, carpeta)):
        if documento.evalua is None:
            continue
        ruta = _ruta_relativa(documento.ruta, carpeta)
        for id_, _ in documento.evalua:
            if id_ not in ids:
                raise ErrorCalificacion(
                    "ELEMENTO_DESCONOCIDO",
                    f"{ruta}: evalua nombra «{id_}», que no está entre los elementos de "
                    "calificacion.yaml",
                )
        evaluacion = next(
            (
                i
                for i, ev in enumerate(esquema.evaluaciones)
                if any(_misma_seccion(documento.seccion, s) for s in ev.secciones)
            ),
            None,
        )
        if evaluacion is None:
            raise ErrorCalificacion(
                "SECCION_SIN_EVALUACION",
                f"{ruta}: la sección «{documento.seccion}» no está en ninguna evaluación de "
                "calificacion.yaml",
            )
        resultado.append(_Actividad(ruta, documento.nombre, evaluacion, documento.evalua))
    return resultado


def _comprobar_pesos(esquema: Esquema, actividades: list[_Actividad]) -> None:
    for elemento in esquema.elementos:
        pesos = [
            (a.ruta, dict(a.evalua)[elemento.id])
            for a in actividades
            if elemento.id in dict(a.evalua)
        ]
        total = round(sum(p for _, p in pesos), 2)
        if total != 0 and round(abs(total - 100), 2) > TOLERANCIA_PESOS:
            rutas = ", ".join(r for r, _ in pesos[:5]) + (", …" if len(pesos) > 5 else "")
            raise ErrorCalificacion(
                "PESOS_NO_SUMAN_100",
                f"{elemento.id}: los pesos de sus actividades suman {total:g} y deben sumar "
                f"100 ({rutas})",
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
        self.nombres = {e.id: e.nombre for e in esquema.elementos}
        self.nodos: list[Nodo] = []
        self.copias = self._numerar_copias()
        # elemento -> hijos de TZ_E_<id> que cuentan (peso > 0), en orden: los indicadores del contador
        self.hijos_de_elemento: dict[str, list[tuple[str, str]]] = {}

    def _lugares(self, actividad: _Actividad) -> list[tuple[str, str]]:
        """Los sitios (elemento, vista) donde va la actividad, real o copia."""
        return [
            (e, v) for e, _ in actividad.evalua for v in (_VISTA_ELEMENTOS, _VISTA_EVALUACIONES)
        ]

    def _numerar_copias(self) -> dict[tuple[str, str, str], str]:
        """``TZ_C_<huella>`` por (ruta, elemento, vista): estable al añadir o quitar actividades."""
        return {
            (a.ruta, elemento, vista): f"TZ_C_{_huella(f'{a.ruta}|{elemento}|{vista}')}"
            for a in self.actividades
            for elemento, vista in self._lugares(a)
            if not self._es_real(a, elemento, vista)
        }

    def _es_real(self, actividad: _Actividad, elemento: str, vista: str) -> bool:
        return elemento == actividad.evalua[0][0] and vista == self.vista_real

    def _agregar(self, nodo: Nodo) -> None:
        self.nodos.append(nodo)

    def _hijos_actividad(
        self, padre: str, elemento: str, vista: str, actividades: list[_Actividad]
    ) -> None:
        """Las actividades (reales o copias) de un contenedor, con el peso renormalizado."""
        pesos = _normalizar([dict(a.evalua)[elemento] for a in actividades])
        for a, peso in zip(actividades, pesos, strict=True):
            if self._es_real(a, elemento, vista):
                hijo = Nodo(a.ruta, "actividad", a.nombre, padre, peso)
            else:
                idnumber = self.copias[(a.ruta, elemento, vista)]
                hijo = Nodo(idnumber, "copia", f"{a.nombre} (copia)", padre, peso, a.ruta)
            self._agregar(hijo)
            if vista == _VISTA_ELEMENTOS and peso > 0:
                self.hijos_de_elemento.setdefault(elemento, []).append((hijo.idnumber, a.nombre))

    def _vista_elementos(self, padre: str) -> None:
        pesos = _normalizar([e.peso for e in self.esquema.elementos])
        for elemento, peso in zip(self.esquema.elementos, pesos, strict=True):
            idnumber = f"TZ_E_{elemento.id}"
            self._agregar(
                Nodo(idnumber, "categoria", elemento.nombre, padre, peso, None, "porcentaje")
            )
            propias = [a for a in self.actividades if elemento.id in dict(a.evalua)]
            self._hijos_actividad(idnumber, elemento.id, _VISTA_ELEMENTOS, propias)

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
                if any(a.evaluacion == n - 1 and e.id in dict(a.evalua) for a in self.actividades)
            ]
            for elemento, peso_elemento in zip(
                presentes, _normalizar([e.peso for e in presentes]), strict=True
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
                propias = [
                    a
                    for a in self.actividades
                    if a.evaluacion == n - 1 and elemento.id in dict(a.evalua)
                ]
                self._hijos_actividad(interior, elemento.id, _VISTA_EVALUACIONES, propias)

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
        self._agregar(Nodo(NOTA_FINAL, "nota", "Nota final (sobre 10)", NOTAS, 0.0, (FINAL, K_TIZA)))

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
        con_actividades = {e for a in self.actividades for e, _ in a.evalua}
        comprobar_sin_circulares(tuple(self.nodos))
        return Deseado(
            nodos=tuple(self.nodos),
            total_curso=total_curso,
            tope=tope,
            cerradas=tuple(f"TZ_V_{n}" for n, e in enumerate(esquema.evaluaciones, 1) if e.cerrada),
            actividades=self._actividades_reales(),
            avisos=tuple(
                ("ELEMENTO_SIN_ACTIVIDADES", e.id)
                for e in esquema.elementos
                if e.id not in con_actividades
            ),
        )

    def _actividades_reales(self) -> tuple[tuple[str, str], ...]:
        reales = {n.idnumber: n.padre for n in self.nodos if n.clase == "actividad"}
        return tuple((ruta, padre) for ruta, padre in sorted(reales.items()) if padre is not None)
