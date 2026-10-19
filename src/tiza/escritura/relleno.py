"""Formato de ``relleno.yaml`` y su validación (``tiza rellenar``).

El agente describe en un YAML qué cambiar en una copia de una plantilla Word: la plantilla, el
``sha256`` de la lectura (``tiza leer``) en la que se basa, el Word de salida y una lista de
operaciones que se aplican en orden. Aquí se valida la forma del fichero, los ids y los
conflictos entre operaciones. No se abre la plantilla: que los ids existan y que las filas
casen con la tabla lo comprueba la aplicación. Todo offline.

Los errores de forma son ``RELLENO_INVALIDO`` con la ruta YAML de lo que falla
(``operaciones[2].colour``). Los índices de las listas empiezan en 0.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import yaml

from tiza import ficheros
from tiza.agente import fichero_en_carpeta
from tiza.escritura import ErrorEscritura
from tiza.lectura.modelo import ErrorLectura

__all__ = [
    "Borrar",
    "DuplicarTabla",
    "Filas",
    "InsertarDespues",
    "Operacion",
    "Relleno",
    "Reemplazar",
    "cargar_relleno",
]

MAX_BYTES = 2 * 1024 * 1024
MAX_OPERACIONES = 2000
MAX_VECES = 40
EXTENSIONES_RELLENO = frozenset({".yaml", ".yml"})
EXTENSIONES_PLANTILLA = frozenset({".docx"})

_N = r"[1-9][0-9]*"
_RE_PARRAFO = re.compile(rf"p{_N}|t{_N}\.f{_N}\.c{_N}\.p{_N}")
_RE_CELDA = re.compile(rf"t{_N}\.f{_N}\.c{_N}")
_RE_TABLA = re.compile(rf"t{_N}")
_RE_FILA = re.compile(rf"t{_N}\.f{_N}")
_RE_CELDA_RELATIVA = re.compile(rf"f{_N}\.c{_N}")
_RE_HASH = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Reemplazar:
    """Sustituye el texto de un párrafo o de una celda por sus párrafos nuevos."""

    id: str
    texto: tuple[str, ...]
    op: ClassVar[str] = "reemplazar"


@dataclass(frozen=True)
class InsertarDespues:
    """Añade párrafos tras un párrafo o una tabla. ``estilo`` None: el del bloque de referencia."""

    id: str
    parrafos: tuple[str, ...]
    estilo: str | None = None
    op: ClassVar[str] = "insertar_despues"


@dataclass(frozen=True)
class Filas:
    """Añade filas a una tabla copiando el formato de la fila ``modelo``.

    ``antes_de`` es el número de la fila ante la que se insertan, o ``None`` para ``final``.
    ``contenido`` tiene una tupla de celdas por fila; cada celda, sus párrafos.
    """

    tabla: str
    modelo: int
    antes_de: int | None
    contenido: tuple[tuple[tuple[str, ...], ...], ...]
    op: ClassVar[str] = "filas"


@dataclass(frozen=True)
class DuplicarTabla:
    """Copia una tabla tras ``despues_de``, una vez por elemento de ``celdas``.

    Cada elemento de ``celdas`` es un diccionario de id de celda relativo (``f1.c1``) a su
    contenido nuevo; ``{}`` es una copia sin cambios.
    """

    tabla: str
    despues_de: str
    veces: int
    celdas: tuple[dict[str, tuple[str, ...]], ...]
    op: ClassVar[str] = "duplicar_tabla"


@dataclass(frozen=True)
class Borrar:
    """Borra un párrafo, una tabla o una fila (``t<n>.f<i>``)."""

    id: str
    op: ClassVar[str] = "borrar"


Operacion = Reemplazar | InsertarDespues | Filas | DuplicarTabla | Borrar


@dataclass(frozen=True)
class Relleno:
    """Un ``relleno.yaml`` validado. ``plantilla`` y ``salida`` son rutas absolutas dentro de la carpeta."""

    plantilla: Path
    sha256: str
    salida: Path
    operaciones: tuple[Operacion, ...]


def _error(ruta: str, motivo: str) -> ErrorEscritura:
    return ErrorEscritura("RELLENO_INVALIDO", f"{ruta}: {motivo}" if ruta else motivo)


def _clave(ruta: str, clave: str) -> str:
    return f"{ruta}.{clave}" if ruta else clave


def _texto(valor: Any, ruta: str) -> str:
    """Un párrafo: cadena sin saltos de línea ni caracteres de control (salvo el final)."""
    if not isinstance(valor, str):
        raise _error(ruta, "debe ser un texto")
    if valor.endswith("\n"):
        valor = valor[:-1]
    if any(unicodedata.category(caracter) == "Cc" for caracter in valor):
        raise _error(
            ruta,
            "no admite saltos de línea ni caracteres de control; si son varios párrafos, usa una lista de párrafos",
        )
    return valor


def _textos(valor: Any, ruta: str) -> tuple[str, ...]:
    """Una cadena (un párrafo) o una lista no vacía de párrafos."""
    if isinstance(valor, str):
        return (_texto(valor, ruta),)
    if isinstance(valor, list):
        if not valor:
            raise _error(ruta, "la lista de párrafos está vacía")
        return tuple(_texto(parrafo, f"{ruta}[{i}]") for i, parrafo in enumerate(valor))
    raise _error(ruta, "debe ser un texto o una lista de párrafos")


def _lista(valor: Any, ruta: str) -> list[Any]:
    if not isinstance(valor, list):
        raise _error(ruta, "debe ser una lista")
    if not valor:
        raise _error(ruta, "la lista está vacía")
    return valor


def _entero(valor: Any, ruta: str, maximo: int | None = None) -> int:
    fuera = isinstance(valor, bool) or not isinstance(valor, int) or valor < 1
    if not fuera and maximo is not None:
        fuera = valor > maximo
    if fuera:
        rango = f"de 1 a {maximo}" if maximo is not None else "de 1 o más"
        raise _error(ruta, f"debe ser un número entero {rango}")
    return valor


def _antes_de(valor: Any, ruta: str) -> int | None:
    if isinstance(valor, str) and valor == "final":
        return None
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
        raise _error(ruta, "debe ser un número de fila (1 o más) o «final»")
    return valor


def _id(valor: Any, ruta: str, formas: tuple[re.Pattern[str], ...], ejemplo: str) -> str:
    if not isinstance(valor, str) or not any(forma.fullmatch(valor) for forma in formas):
        raise _error(ruta, f"no es un id válido (se espera {ejemplo})")
    return valor


def _mapa(
    valor: Any, ruta: str, permitidas: frozenset[str], requeridas: frozenset[str]
) -> dict[str, Any]:
    if not isinstance(valor, dict):
        raise _error(ruta, "debe ser un bloque de claves («clave: valor»)")
    for clave in valor:
        if not isinstance(clave, str):
            raise _error(ruta, "tiene una clave que no es texto")
        if clave not in permitidas:
            raise _error(_clave(ruta, clave), "clave desconocida")
    for clave in sorted(requeridas):
        if clave not in valor:
            raise _error(ruta, f"falta la clave «{clave}»")
    return valor


_CAMPOS: dict[str, frozenset[str]] = {
    "reemplazar": frozenset({"id", "texto"}),
    "insertar_despues": frozenset({"id", "parrafos", "estilo"}),
    "filas": frozenset({"tabla", "modelo", "antes_de", "contenido"}),
    "duplicar_tabla": frozenset({"tabla", "despues_de", "veces", "celdas"}),
    "borrar": frozenset({"id"}),
}
_FORMAS_REEMPLAZO = (_RE_PARRAFO, _RE_CELDA)
_FORMAS_INSERTAR = (_RE_PARRAFO, _RE_TABLA)
_FORMAS_BORRAR = (_RE_PARRAFO, _RE_TABLA, _RE_FILA)
_FORMAS_DESPUES = (_RE_PARRAFO, _RE_TABLA)


def _fila(valor: Any, ruta: str) -> tuple[tuple[str, ...], ...]:
    celdas = _lista(valor, ruta)
    return tuple(_textos(celda, f"{ruta}[{j}]") for j, celda in enumerate(celdas))


def _copia(valor: Any, ruta: str) -> dict[str, tuple[str, ...]]:
    if not isinstance(valor, dict):
        raise _error(
            ruta, "debe ser un bloque de celdas («f1.c1: texto») o {} si la copia no cambia"
        )
    copia: dict[str, tuple[str, ...]] = {}
    for clave, contenido in valor.items():
        if not isinstance(clave, str) or not _RE_CELDA_RELATIVA.fullmatch(clave):
            raise _error(ruta, "el id de celda debe ir relativo a la tabla, como f1.c1")
        copia[clave] = _textos(contenido, _clave(ruta, clave))
    return copia


def _operacion(valor: Any, ruta: str) -> Operacion:
    if not isinstance(valor, dict):
        raise _error(ruta, "debe ser un bloque de claves («clave: valor»)")
    nombre = valor.get("op")
    if not isinstance(nombre, str) or nombre not in _CAMPOS:
        raise _error(
            _clave(ruta, "op"),
            "operación no admitida: usa reemplazar, insertar_despues, filas, duplicar_tabla o borrar",
        )
    datos = _mapa(valor, ruta, _CAMPOS[nombre] | {"op"}, (_CAMPOS[nombre] - {"estilo"}) | {"op"})

    def campo(clave: str) -> str:
        return _clave(ruta, clave)

    if nombre == "reemplazar":
        return Reemplazar(
            _id(
                datos["id"],
                campo("id"),
                _FORMAS_REEMPLAZO,
                "un párrafo (p3) o una celda (t2.f1.c1)",
            ),
            _textos(datos["texto"], campo("texto")),
        )
    if nombre == "insertar_despues":
        estilo = None
        if "estilo" in datos:
            estilo = _texto(datos["estilo"], campo("estilo"))
            if not estilo:
                raise _error(campo("estilo"), "el estilo no puede estar vacío")
        return InsertarDespues(
            _id(datos["id"], campo("id"), _FORMAS_INSERTAR, "un párrafo (p3) o una tabla (t2)"),
            _textos(datos["parrafos"], campo("parrafos")),
            estilo,
        )
    if nombre == "filas":
        contenido = _lista(datos["contenido"], campo("contenido"))
        ruta_contenido = campo("contenido")
        return Filas(
            _id(datos["tabla"], campo("tabla"), (_RE_TABLA,), "una tabla (t2)"),
            _entero(datos["modelo"], campo("modelo")),
            _antes_de(datos["antes_de"], campo("antes_de")),
            tuple(_fila(fila, f"{ruta_contenido}[{i}]") for i, fila in enumerate(contenido)),
        )
    if nombre == "duplicar_tabla":
        veces = _entero(datos["veces"], campo("veces"), MAX_VECES)
        celdas = _lista(datos["celdas"], campo("celdas"))
        if len(celdas) != veces:
            raise _error(
                campo("celdas"),
                f"debe tener {veces} elementos, uno por copia ({{}} si una copia no cambia)",
            )
        ruta_celdas = campo("celdas")
        return DuplicarTabla(
            _id(datos["tabla"], campo("tabla"), (_RE_TABLA,), "una tabla (t2)"),
            _id(
                datos["despues_de"],
                campo("despues_de"),
                _FORMAS_DESPUES,
                "un párrafo (p3) o una tabla (t2)",
            ),
            veces,
            tuple(_copia(copia, f"{ruta_celdas}[{k}]") for k, copia in enumerate(celdas)),
        )
    return Borrar(
        _id(
            datos["id"],
            campo("id"),
            _FORMAS_BORRAR,
            "un párrafo, una tabla (t2) o una fila (t2.f1)",
        )
    )


def _relacionados(a: str, b: str) -> bool:
    """¿Son el mismo id, o uno contiene al otro? («t3» contiene a «t3.f2», no a «t31»)."""
    return a == b or a.startswith(b + ".") or b.startswith(a + ".")


def _referencias(operacion: Operacion) -> tuple[str, ...]:
    """Los ids de la lectura original que una operación toca o usa como referencia."""
    if isinstance(operacion, Filas):
        refs = [operacion.tabla, f"{operacion.tabla}.f{operacion.modelo}"]
        if operacion.antes_de is not None:
            refs.append(f"{operacion.tabla}.f{operacion.antes_de}")
        return tuple(refs)
    if isinstance(operacion, DuplicarTabla):
        return (operacion.tabla, operacion.despues_de)
    if isinstance(operacion, InsertarDespues | Reemplazar | Borrar):
        return (operacion.id,)
    raise TypeError(operacion)


def _conflicto(operaciones: tuple[Operacion, ...]) -> tuple[int, int, str] | None:
    """El primer choque (por la operación más tardía): índices de las dos y el id en disputa."""
    hallados: list[tuple[int, int, str]] = []
    primeros: dict[str, int] = {}
    for j, operacion in enumerate(operaciones):
        if isinstance(operacion, Reemplazar):
            if operacion.id in primeros:
                hallados.append((primeros[operacion.id], j, operacion.id))
            else:
                primeros[operacion.id] = j
    refs = [_referencias(operacion) for operacion in operaciones]
    for i, operacion in enumerate(operaciones):
        if not isinstance(operacion, Borrar):
            continue
        for j in range(len(operaciones)):
            if j != i and any(_relacionados(operacion.id, ref) for ref in refs[j]):
                hallados.append((min(i, j), max(i, j), operacion.id))
    if not hallados:
        return None
    return min(hallados, key=lambda hallado: (hallado[1], hallado[0]))


class _SinAlias(yaml.YAMLError):
    """Un ancla o un alias: se rechaza para que lo que se valida sea exactamente su texto."""


class _CargadorSinAlias(yaml.SafeLoader):
    def compose_node(self, parent, index):  # type: ignore[no-untyped-def]
        if self.check_event(yaml.AliasEvent):
            raise _SinAlias()
        return super().compose_node(parent, index)


def _cargar_yaml(origen: Path) -> Any:
    try:
        bruto = ficheros.leer_bytes_acotado(origen, MAX_BYTES)
    except FileNotFoundError:
        raise ErrorEscritura("DOCUMENTO_AUSENTE", f"No existe el fichero {origen.name}.") from None
    except ficheros.FicheroNoSeguro as exc:
        if exc.motivo == "grande":
            raise _error("", f"{origen.name} pesa más de 2 MB.") from None
        raise ErrorEscritura("FICHERO_BLOQUEADO", f"No se puede leer {origen.name}.") from None
    except OSError:
        raise ErrorEscritura("FICHERO_BLOQUEADO", f"No se puede leer {origen.name}.") from None
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _error("", f"{origen.name} no está en UTF-8.") from None
    try:
        datos = yaml.load(texto, Loader=_CargadorSinAlias)  # noqa: S506 - cargador seguro
    except _SinAlias:
        raise _error("", "no admite anclas ni alias (&… o *…)") from None
    except yaml.YAMLError as exc:
        marca = getattr(exc, "problem_mark", None)
        donde = f" (línea {marca.line + 1})" if marca is not None else ""
        raise _error("", f"no es YAML válido{donde}") from None
    except RecursionError:
        raise _error("", "está anidado demasiado") from None
    if datos is None:
        raise _error("", "el fichero está vacío")
    return datos


def _dentro(valor: str | Path, base: Path, extensiones: frozenset[str]) -> Path:
    try:
        return fichero_en_carpeta(valor, base, extensiones)
    except ErrorLectura as error:
        raise ErrorEscritura(error.codigo, error.detalle) from None


_CLAVES_RAIZ = frozenset({"plantilla", "sha256", "salida", "operaciones"})


def cargar_relleno(ruta: Path, carpeta: Path) -> Relleno:
    """Lee y valida un ``relleno.yaml`` de la carpeta de la asignatura.

    ``ruta`` es el YAML y debe estar dentro de ``carpeta``; ``plantilla`` y ``salida`` se
    resuelven desde ``carpeta`` y no pueden salirse de ella (``FICHERO_FUERA``). Lanza
    ``ErrorEscritura`` con un código estable. No abre la plantilla ni mira si la salida existe.
    """
    base = Path(carpeta)
    origen = _dentro(Path(ruta), base, EXTENSIONES_RELLENO)
    datos = _mapa(_cargar_yaml(origen), "", _CLAVES_RAIZ, _CLAVES_RAIZ)
    if not isinstance(datos["plantilla"], str):
        raise _error("plantilla", "debe ser la ruta de un .docx")
    if not isinstance(datos["salida"], str):
        raise _error("salida", "debe ser la ruta del .docx de salida")
    plantilla = _dentro(datos["plantilla"], base, EXTENSIONES_PLANTILLA)
    salida = _dentro(datos["salida"], base, EXTENSIONES_PLANTILLA)
    if plantilla == salida:
        raise ErrorEscritura(
            "DOCUMENTO_EXISTE",
            "La salida no puede ser la plantilla: tiza nunca sobrescribe un Word.",
        )
    if not isinstance(datos["sha256"], str) or not _RE_HASH.fullmatch(datos["sha256"]):
        raise _error("sha256", "debe ser el sha256 de 64 caracteres hexadecimales en minúscula")
    bruto = _lista(datos["operaciones"], "operaciones")
    if len(bruto) > MAX_OPERACIONES:
        raise _error("operaciones", f"admite como mucho {MAX_OPERACIONES} operaciones")
    operaciones = tuple(_operacion(op, f"operaciones[{i}]") for i, op in enumerate(bruto))
    choque = _conflicto(operaciones)
    if choque is not None:
        i, j, id_en_disputa = choque
        raise ErrorEscritura(
            "OPERACIONES_EN_CONFLICTO",
            f"operaciones[{i}] y operaciones[{j}] chocan sobre «{id_en_disputa}»: un borrado no puede "
            "convivir con otra operación sobre el mismo bloque (ni dentro de él ni por encima), "
            "y no se reemplaza dos veces el mismo id.",
        )
    return Relleno(
        plantilla=plantilla,
        sha256=datos["sha256"],
        salida=salida,
        operaciones=operaciones,
    )
