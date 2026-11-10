"""Formato de ``ponderacion.yaml`` y su validación (esquema cerrado, offline).

El agente describe cómo se ponderan notas que ya existen en el calificador del docente: crea
subcategorías nuevas, mete en ellas actividades y fija método y pesos, o ajusta con porcentajes
una categoría que ya existe. No habla con el aula: aquí solo se comprueban la forma, las líneas,
los ciclos, las repeticiones y los ficheros de la carpeta. Resolver las referencias contra el
calificador es cosa de ``comprobar_contra_calificador`` y de la sesión.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tiza import contenido, tipos
from tiza.contenido import Documento, ErrorContenido
from tiza.escritura import ErrorEscritura
from tiza.escritura.relleno import cargar_yaml_sin_alias, dentro_de_la_carpeta

from .esquema import EXTENSIONES_ESQUEMA, ErrorCalificacion, _Lector

__all__ = [
    "CALCULOS",
    "CLAVE_RAIZ",
    "CalificadorAula",
    "CategoriaAula",
    "ElementoPonderacion",
    "EntradaPonderacion",
    "ErrorPonderacion",
    "EsquemaPonderacion",
    "Hallazgo",
    "MAX_ENTRADAS",
    "Referencia",
    "cargar_ponderacion",
    "comprobar_contra_calificador",
    "es_ponderacion",
]

CLAVE_RAIZ = "ponderacion"
CALCULOS = ("media_ponderada", "natural")
MAX_ENTRADAS = 20
EXTENSIONES_FICHERO = frozenset({".md", ".html"})
TOLERANCIA_PORCENTAJES = 0.005
_CLAVES_REFERENCIA = ("fichero", "actividad", "elemento", "categoria")
_PERMITIDAS_NUEVA = ("id", "nombre", "dentro_de", "calculo", "solo_no_vacias", "elementos")
_REQUERIDAS_NUEVA = ("id", "nombre", "dentro_de", "calculo", "solo_no_vacias", "elementos")
_PERMITIDAS_EXISTENTE = ("categoria", "calculo", "solo_no_vacias", "elementos")
_REQUERIDAS_EXISTENTE = ("categoria", "elementos")
_PERMITIDAS_ELEMENTO = (*_CLAVES_REFERENCIA, "tipo", "seccion", "peso", "porcentaje")


class ErrorPonderacion(ErrorCalificacion):
    """Error de ``ponderacion.yaml`` con un código estable; el detalle es texto de tiza.

    Es un ``ErrorCalificacion``: quien captura el del calificador captura también este.
    """


@dataclass(frozen=True)
class Referencia:
    """Lo que nombra un elemento: exactamente una de las cuatro clases."""

    clase: str  # fichero | actividad | elemento | categoria
    nombre: str  # la ruta del fichero, el nombre de la actividad o del elemento, o la categoría
    tipo: str | None = None  # solo en «actividad»
    seccion: int | str | None = None  # solo en «actividad»


@dataclass(frozen=True)
class ElementoPonderacion:
    referencia: Referencia
    peso: float | None
    porcentaje: float | None
    documento: Documento | None = None  # solo en «fichero»
    ruta: str = ""  # ruta YAML, para los errores de quien resuelva después


@dataclass(frozen=True)
class EntradaPonderacion:
    nueva: bool
    id: str | None  # solo en las nuevas
    nombre: str | None  # solo en las nuevas
    dentro_de: str | None  # solo en las nuevas: id de otra nueva o nombre de una existente
    calculo: str | None
    solo_no_vacias: bool | None
    categoria: str | None  # solo en las existentes: su nombre exacto
    elementos: tuple[ElementoPonderacion, ...]
    ruta: str = ""


@dataclass(frozen=True)
class EsquemaPonderacion:
    entradas: tuple[EntradaPonderacion, ...]


class _LectorPonderacion(_Lector):
    """El lector del calificador con los errores de la ponderación."""

    def error(self, codigo: str, ruta: str, motivo: str) -> ErrorPonderacion:  # type: ignore[override]
        linea = self.lineas.get(ruta)
        donde = f" (línea {linea})" if linea is not None else ""
        return ErrorPonderacion(codigo, f"{ruta}: {motivo}{donde}" if ruta else f"{motivo}{donde}")

    def invalido(self, ruta: str, motivo: str) -> ErrorPonderacion:  # type: ignore[override]
        return self.error("PONDERACION_INVALIDA", ruta, motivo)


def es_ponderacion(ruta: Path, carpeta: Path) -> bool:
    """¿La raíz del ``.yaml`` es ``ponderacion``? Sirve para despachar sin validar nada.

    Un fichero fuera de la carpeta, ilegible o raro devuelve ``False`` (no se lee fuera): el
    esquema de calificación, que ya sabe fallar con su código, se queda con él.
    """
    try:
        origen = dentro_de_la_carpeta(Path(ruta), Path(carpeta).resolve(), EXTENSIONES_ESQUEMA)
        datos = cargar_yaml_sin_alias(origen)
    except (ErrorEscritura, OSError):
        return False
    return isinstance(datos, dict) and CLAVE_RAIZ in datos


def cargar_ponderacion(ruta: Path, carpeta: Path) -> EsquemaPonderacion:
    """Lee y valida un ``ponderacion.yaml`` de la carpeta de la asignatura.

    Lanza ``ErrorPonderacion`` con un código estable y, cuando hay, la ruta YAML y la línea.
    No habla con el aula ni lee nada fuera de la carpeta.
    """
    raiz = Path(carpeta).resolve()
    try:
        origen = dentro_de_la_carpeta(Path(ruta), raiz, EXTENSIONES_ESQUEMA)
    except ErrorEscritura as error:
        codigo = "ESQUEMA_FUERA_DE_CARPETA" if error.codigo == "FICHERO_FUERA" else error.codigo
        raise ErrorPonderacion(codigo, error.detalle) from None
    lineas: dict[str, int] = {}
    try:
        datos = cargar_yaml_sin_alias(origen, lineas)
    except ErrorEscritura as error:
        codigo = "PONDERACION_INVALIDA" if error.codigo == "RELLENO_INVALIDO" else error.codigo
        raise ErrorPonderacion(codigo, error.detalle) from None
    lector = _LectorPonderacion(lineas)
    datos = lector.mapa(datos, "", (CLAVE_RAIZ,), (CLAVE_RAIZ,))
    brutas = lector.lista(datos[CLAVE_RAIZ], CLAVE_RAIZ)
    if len(brutas) > MAX_ENTRADAS:
        raise lector.invalido(CLAVE_RAIZ, f"admite como mucho {MAX_ENTRADAS} entradas")
    cabeceras = _cabeceras(lector, brutas)
    nuevos = {c.id for c in cabeceras if c.id is not None}
    entradas: list[EntradaPonderacion] = []
    for i, (cabecera, bruta) in enumerate(zip(cabeceras, brutas, strict=True)):
        ruta_entrada = f"{CLAVE_RAIZ}[{i}]"
        elementos = _elementos(lector, bruta["elementos"], ruta_entrada, cabecera, nuevos, raiz)
        entradas.append(
            EntradaPonderacion(
                cabecera.nueva,
                cabecera.id,
                cabecera.nombre,
                cabecera.dentro_de,
                cabecera.calculo,
                cabecera.solo_no_vacias,
                cabecera.categoria,
                elementos,
                ruta_entrada,
            )
        )
    esquema = EsquemaPonderacion(tuple(entradas))
    _sin_repeticiones(lector, esquema)
    _sin_ciclos(lector, esquema)
    return esquema


@dataclass(frozen=True)
class _Cabecera:
    nueva: bool
    id: str | None
    nombre: str | None
    dentro_de: str | None
    calculo: str | None
    solo_no_vacias: bool | None
    categoria: str | None


def _cabeceras(lector: _LectorPonderacion, brutas: list[Any]) -> list[_Cabecera]:
    resultado: list[_Cabecera] = []
    ids: dict[str, str] = {}
    existentes: dict[str, str] = {}
    for i, bruta in enumerate(brutas):
        ruta = f"{CLAVE_RAIZ}[{i}]"
        if not isinstance(bruta, dict):
            raise lector.invalido(ruta, "debe ser un bloque de claves («clave: valor»)")
        if "id" in bruta and "categoria" in bruta:
            raise lector.invalido(
                ruta, "lleva «id» (categoría nueva) y «categoria» (existente): solo una de las dos"
            )
        if "id" not in bruta and "categoria" not in bruta:
            raise lector.invalido(
                ruta, "debe llevar «id» (categoría nueva) o «categoria» (una que ya existe)"
            )
        nueva = "id" in bruta
        datos = lector.mapa(
            bruta,
            ruta,
            _PERMITIDAS_NUEVA if nueva else _PERMITIDAS_EXISTENTE,
            _REQUERIDAS_NUEVA if nueva else _REQUERIDAS_EXISTENTE,
        )
        calculo = _calculo(lector, datos, ruta)
        solo = (
            lector.booleano(datos["solo_no_vacias"], f"{ruta}.solo_no_vacias")
            if "solo_no_vacias" in datos
            else None
        )
        if not nueva:
            nombre = lector.texto(datos["categoria"], f"{ruta}.categoria")
            if nombre in existentes:
                raise lector.invalido(
                    f"{ruta}.categoria",
                    f"la categoría «{nombre}» ya tiene su entrada en {existentes[nombre]}",
                )
            existentes[nombre] = ruta
            resultado.append(_Cabecera(False, None, None, None, calculo, solo, nombre))
            continue
        id_ = lector.id_(datos["id"], f"{ruta}.id")
        if id_ in ids:
            raise lector.invalido(f"{ruta}.id", f"el id «{id_}» ya está en {ids[id_]}")
        ids[id_] = ruta
        resultado.append(
            _Cabecera(
                True,
                id_,
                lector.texto(datos["nombre"], f"{ruta}.nombre"),
                lector.texto(datos["dentro_de"], f"{ruta}.dentro_de"),
                calculo,
                solo,
                None,
            )
        )
    return resultado


def _calculo(lector: _LectorPonderacion, datos: dict[str, Any], ruta: str) -> str | None:
    if "calculo" not in datos:
        return None
    valor = datos["calculo"]
    if not isinstance(valor, str) or valor not in CALCULOS:
        raise lector.invalido(f"{ruta}.calculo", f"debe ser uno de {', '.join(CALCULOS)}")
    return valor


def _elementos(
    lector: _LectorPonderacion,
    bruto: Any,
    ruta_entrada: str,
    cabecera: _Cabecera,
    nuevos: set[str],
    raiz: Path,
) -> tuple[ElementoPonderacion, ...]:
    ruta_lista = f"{ruta_entrada}.elementos"
    resultado: list[ElementoPonderacion] = []
    for j, crudo in enumerate(lector.lista(bruto, ruta_lista)):
        ruta = f"{ruta_lista}[{j}]"
        if isinstance(crudo, dict) and "peso" in crudo and not cabecera.nueva:
            raise lector.error(
                "PESO_EN_EXISTENTE",
                f"{ruta}.peso",
                "«peso» solo vale en una categoría nueva; en una que ya existe usa «porcentaje»",
            )
        datos = lector.mapa(crudo, ruta, _PERMITIDAS_ELEMENTO, ())
        referencia, documento = _referencia(lector, datos, ruta, raiz)
        tiene_peso, tiene_porcentaje = "peso" in datos, "porcentaje" in datos
        if tiene_peso == tiene_porcentaje:
            raise lector.invalido(ruta, "debe llevar «peso» o «porcentaje», y solo uno de los dos")
        peso = lector.peso(datos["peso"], f"{ruta}.peso") if tiene_peso else None
        porcentaje = None
        if tiene_porcentaje:
            porcentaje = lector.numero(datos["porcentaje"], f"{ruta}.porcentaje")
            if not 0 <= porcentaje <= 100:
                raise lector.invalido(f"{ruta}.porcentaje", "debe estar entre 0 y 100")
        resultado.append(ElementoPonderacion(referencia, peso, porcentaje, documento, ruta))
    con_peso = [e for e in resultado if e.peso is not None]
    if con_peso and len(con_peso) != len(resultado):
        raise lector.error(
            "PESOS_MEZCLADOS",
            ruta_lista,
            "en una misma lista no se mezclan «peso» y «porcentaje»",
        )
    total = sum(e.porcentaje or 0.0 for e in resultado)
    if total > 100 + TOLERANCIA_PORCENTAJES:
        raise lector.error(
            "PORCENTAJES_SUPERAN_100",
            ruta_lista,
            f"los porcentajes suman {total:g} y no pueden pasar de 100",
        )
    return tuple(resultado)


def _referencia(
    lector: _LectorPonderacion, datos: dict[str, Any], ruta: str, raiz: Path
) -> tuple[Referencia, Documento | None]:
    presentes = [clave for clave in _CLAVES_REFERENCIA if clave in datos]
    if len(presentes) != 1:
        raise lector.invalido(
            ruta,
            "debe nombrar exactamente una cosa: "
            "«fichero», «actividad» (con «tipo» y «seccion»), «elemento» o «categoria»",
        )
    clase = presentes[0]
    if clase != "actividad":
        for sobrante in ("tipo", "seccion"):
            if sobrante in datos:
                raise lector.invalido(f"{ruta}.{sobrante}", "solo vale junto a «actividad»")
    nombre = lector.texto(datos[clase], f"{ruta}.{clase}")
    if clase == "fichero":
        return _fichero(lector, nombre, f"{ruta}.fichero", raiz)
    if clase != "actividad":
        return Referencia(clase, nombre), None
    for obligatoria in ("tipo", "seccion"):
        if obligatoria not in datos:
            raise lector.invalido(ruta, f"«actividad» necesita también «{obligatoria}»")
    tipo = lector.texto(datos["tipo"], f"{ruta}.tipo")
    if tipo not in tipos.TIPOS:
        raise lector.invalido(f"{ruta}.tipo", f"debe ser uno de {', '.join(sorted(tipos.TIPOS))}")
    if not tipos.obtener(tipo).calificable:
        raise lector.error("NO_CALIFICABLE", f"{ruta}.tipo", f"un tipo «{tipo}» no tiene nota")
    seccion = lector.seccion(datos["seccion"], f"{ruta}.seccion")[1]
    return Referencia("actividad", nombre, tipo, seccion), None


def _fichero(
    lector: _LectorPonderacion, valor: str, ruta: str, raiz: Path
) -> tuple[Referencia, Documento]:
    try:
        destino = dentro_de_la_carpeta(valor, raiz, EXTENSIONES_FICHERO)
    except ErrorEscritura as error:
        raise lector.error(error.codigo, ruta, error.detalle) from None
    try:
        documento = contenido.cargar(destino, raiz=raiz)
    except ErrorContenido as error:
        raise lector.error(error.codigo, ruta, error.detalle) from None
    if not tipos.obtener(documento.tipo).tiene_nota(documento):
        raise lector.error(
            "NO_CALIFICABLE",
            ruta,
            f"«{valor}» es de tipo {documento.tipo} y no tiene nota en el aula",
        )
    return Referencia("fichero", destino.relative_to(raiz).as_posix()), documento


def _identidad(
    referencia: Referencia, documento: Documento | None, nuevos: set[str]
) -> tuple[str, ...]:
    if documento is not None:
        return ("actividad", documento.tipo, str(documento.seccion), documento.nombre)
    if referencia.clase == "actividad":
        return ("actividad", str(referencia.tipo), str(referencia.seccion), referencia.nombre)
    if referencia.clase == "categoria" and referencia.nombre in nuevos:
        return ("categoria_nueva", referencia.nombre)
    return (referencia.clase, referencia.nombre)


def _sin_repeticiones(lector: _LectorPonderacion, esquema: EsquemaPonderacion) -> None:
    nuevos = {e.id for e in esquema.entradas if e.id is not None}
    vistos: dict[tuple[str, ...], str] = {}
    for entrada in esquema.entradas:
        for elemento in entrada.elementos:
            clave = _identidad(elemento.referencia, elemento.documento, nuevos)
            if clave in vistos:
                raise lector.error(
                    "ELEMENTO_REPETIDO",
                    elemento.ruta,
                    f"«{elemento.referencia.nombre}» ya está en {vistos[clave]}; "
                    "un elemento solo puede estar en una lista",
                )
            vistos[clave] = elemento.ruta


def _sin_ciclos(lector: _LectorPonderacion, esquema: EsquemaPonderacion) -> None:
    """Una categoría nueva no puede estar dentro de sí misma, ni con pasos intermedios."""
    nuevos = {e.id for e in esquema.entradas if e.id is not None}
    # id -> [(id del padre, ruta YAML que lo dice)]
    padres: dict[str, list[tuple[str, str]]] = {id_: [] for id_ in nuevos}
    for entrada in esquema.entradas:
        if entrada.id is not None and entrada.dentro_de in nuevos:
            padres[entrada.id].append((str(entrada.dentro_de), f"{entrada.ruta}.dentro_de"))
        if entrada.id is None:
            continue
        for elemento in entrada.elementos:
            referencia = elemento.referencia
            if referencia.clase == "categoria" and referencia.nombre in nuevos:
                padres[referencia.nombre].append((entrada.id, elemento.ruta))
    estado: dict[str, int] = {}  # 1 en curso, 2 hecho
    for inicio in sorted(nuevos):
        if estado.get(inicio):
            continue
        pila = [(inicio, iter(padres[inicio]))]
        estado[inicio] = 1
        while pila:
            actual, siguientes = pila[-1]
            avance = next(siguientes, None)
            if avance is None:
                estado[actual] = 2
                pila.pop()
                continue
            padre, ruta = avance
            if estado.get(padre) == 1:
                raise lector.error(
                    "CICLO_DE_CATEGORIAS",
                    ruta,
                    f"la categoría «{actual}» acabaría dentro de sí misma (pasa por «{padre}»)",
                )
            if not estado.get(padre):
                estado[padre] = 1
                pila.append((padre, iter(padres[padre])))


# --- Lo que solo se sabe con el calificador del aula (lo conectará T8 al fichero de estado) ---


@dataclass(frozen=True)
class CategoriaAula:
    """Una categoría del calificador del aula, sin notas: lo que hace falta para comprobar."""

    nombre: str
    calculo: str  # «media_ponderada», «natural» u «otro»
    actividades: tuple[tuple[str, str, str], ...] = ()  # (tipo, nombre, sección)
    elementos: tuple[str, ...] = ()  # elementos manuales, por nombre
    subcategorias: tuple[str, ...] = ()  # por nombre


@dataclass(frozen=True)
class CalificadorAula:
    categorias: tuple[CategoriaAula, ...]


@dataclass(frozen=True)
class Hallazgo:
    """Algo que ``comprobar_contra_calificador`` encuentra: un error, o un aviso si no corta."""

    codigo: str
    detalle: str
    error: bool = True


def _coincide(actividad: tuple[str, str, str], tipo: str, nombre: str, seccion: Any) -> bool:
    if actividad[0] != tipo or actividad[1] != nombre:
        return False
    return not isinstance(seccion, str) or actividad[2] == seccion


def comprobar_contra_calificador(
    esquema: EsquemaPonderacion, calificador: CalificadorAula
) -> tuple[Hallazgo, ...]:
    """Comprueba el esquema contra el calificador leído del aula. Pura: no habla con el aula.

    ``CATEGORIA_AUSENTE`` y ``CATEGORIA_AMBIGUA``, ``ACTIVIDAD_AUSENTE`` y ``ACTIVIDAD_AMBIGUA``,
    ``ELEMENTO_AUSENTE`` y ``ELEMENTO_AMBIGUO``, ``PORCENTAJES_SIN_RESTO`` y ``CALCULO_SIN_PESOS``.
    Un fichero que aún no está publicado es un aviso (``ACTIVIDAD_PENDIENTE``), no un error.
    """
    nuevos = {e.id for e in esquema.entradas if e.id is not None}
    hallazgos: list[Hallazgo] = []

    def categoria(nombre: str, ruta: str) -> CategoriaAula | None:
        if nombre in nuevos:
            return None
        coincidencias = [c for c in calificador.categorias if c.nombre == nombre]
        if not coincidencias:
            hallazgos.append(Hallazgo("CATEGORIA_AUSENTE", f"{ruta}: no hay «{nombre}» en el aula"))
        elif len(coincidencias) > 1:
            hallazgos.append(
                Hallazgo("CATEGORIA_AMBIGUA", f"{ruta}: hay varias «{nombre}» en el aula")
            )
        else:
            return coincidencias[0]
        return None

    for entrada in esquema.entradas:
        if entrada.nueva:
            categoria(str(entrada.dentro_de), f"{entrada.ruta}.dentro_de")
            destino = None
        else:
            destino = categoria(str(entrada.categoria), f"{entrada.ruta}.categoria")
        for elemento in entrada.elementos:
            _comprobar_elemento(elemento, calificador, categoria, hallazgos)
        if destino is None:
            continue
        porcentajes = [e.porcentaje for e in entrada.elementos if e.porcentaje is not None]
        if porcentajes and entrada.calculo is None and destino.calculo not in CALCULOS:
            hallazgos.append(
                Hallazgo(
                    "CALCULO_SIN_PESOS",
                    f"{entrada.ruta}: «{destino.nombre}» no tiene pesos por elemento; "
                    "declara «calculo» para cambiarlo",
                )
            )
        if porcentajes and abs(sum(porcentajes) - 100) <= TOLERANCIA_PORCENTAJES:
            if _quedan_sin_nombrar(destino, entrada.elementos):
                hallazgos.append(
                    Hallazgo(
                        "PORCENTAJES_SIN_RESTO",
                        f"{entrada.ruta}.elementos: los porcentajes suman 100 y en "
                        f"«{destino.nombre}» quedan elementos sin nombrar",
                    )
                )
    return tuple(hallazgos)


def _comprobar_elemento(
    elemento: ElementoPonderacion,
    calificador: CalificadorAula,
    categoria: Any,
    hallazgos: list[Hallazgo],
) -> None:
    referencia, ruta = elemento.referencia, elemento.ruta
    if referencia.clase == "categoria":
        categoria(referencia.nombre, f"{ruta}.categoria")
    elif referencia.clase == "elemento":
        cuenta = sum(c.elementos.count(referencia.nombre) for c in calificador.categorias)
        if cuenta == 0:
            hallazgos.append(
                Hallazgo("ELEMENTO_AUSENTE", f"{ruta}: no hay un elemento «{referencia.nombre}»")
            )
        elif cuenta > 1:
            hallazgos.append(
                Hallazgo("ELEMENTO_AMBIGUO", f"{ruta}: hay varios elementos «{referencia.nombre}»")
            )
    else:
        documento = elemento.documento
        tipo = documento.tipo if documento is not None else str(referencia.tipo)
        nombre = documento.nombre if documento is not None else referencia.nombre
        seccion = documento.seccion if documento is not None else referencia.seccion
        cuenta = sum(
            1
            for c in calificador.categorias
            for a in c.actividades
            if _coincide(a, tipo, nombre, seccion)
        )
        if cuenta == 0 and documento is not None:
            hallazgos.append(
                Hallazgo(
                    "ACTIVIDAD_PENDIENTE",
                    f"{ruta}: «{referencia.nombre}» aún no está en el calificador del aula",
                    error=False,
                )
            )
        elif cuenta == 0:
            hallazgos.append(
                Hallazgo("ACTIVIDAD_AUSENTE", f"{ruta}: no hay una actividad así en el aula")
            )
        elif cuenta > 1:
            hallazgos.append(
                Hallazgo("ACTIVIDAD_AMBIGUA", f"{ruta}: hay varias actividades así en el aula")
            )


def _quedan_sin_nombrar(destino: CategoriaAula, elementos: Sequence[ElementoPonderacion]) -> bool:
    def nombrada_actividad(actividad: tuple[str, str, str]) -> bool:
        for e in elementos:
            ref, doc = e.referencia, e.documento
            if doc is not None:
                if _coincide(actividad, doc.tipo, doc.nombre, doc.seccion):
                    return True
            elif ref.clase == "actividad" and _coincide(
                actividad, str(ref.tipo), ref.nombre, ref.seccion
            ):
                return True
        return False

    def nombrado(clase: str, nombre: str) -> bool:
        return any(e.referencia.clase == clase and e.referencia.nombre == nombre for e in elementos)

    return (
        any(not nombrada_actividad(a) for a in destino.actividades)
        or any(not nombrado("elemento", n) for n in destino.elementos)
        or any(not nombrado("categoria", n) for n in destino.subcategorias)
    )
