"""Rúbrica de una tarea a partir de filas: indicadores, descriptores y pesos propios.

La construcción de la rúbrica es pura y todo el trabajo, también la lectura del
fichero, es local y offline: no hay ninguna petición de red. Cada fila concreta un
criterio del esquema con un indicador y un descriptor por nivel de
``niveles_rubrica``. Los puntos de la tarea (10) se reparten por el peso de cada
fila con el mayor resto, y los de cada nivel son los de la fila por el porcentaje
del nivel, también con el mayor resto, para que cada suma sea exacta.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from . import contenido, filtro
from .calificacion.esquema import ErrorCalificacion, Esquema, NivelRubrica
from .contenido import ErrorContenido
from .ficheros import FicheroNoSeguro, leer_bytes_acotado
from .filtro import CONTROL
from .rubrica import (
    MAX_CRITERIOS,
    MAX_NOMBRE_CRITERIO,
    MAX_NOMBRE_RUBRICA,
    MAX_TEXTO,
    CriterioRubrica,
    Nivel,
    RubricaCargada,
    validar_rubrica,
)
from .rubrica_criterios import _hoja, mayor_resto

__all__ = ["FilaRubrica", "cargar_rubrica_de_tarea", "rubrica_de_filas"]

MAX_INDICADOR = 100
MAX_PESO_FILA = 100

_CAMPOS = {"tipo", "nombre", "filas"}
_CAMPOS_FILA = {"criterio", "indicador", "peso", "niveles"}
_CAMPOS_PRIVADOS = {
    "criterios": "las rúbricas escritas a mano con «criterios»",
    "indicaciones": "las indicaciones para el corrector",
}


@dataclass(frozen=True)
class FilaRubrica:
    """Una fila de la rúbrica: un indicador concreto de un criterio y sus descriptores."""

    criterio: str
    indicador: str
    peso: float | None
    descriptores: dict[str, str]


def _error(codigo: str, detalle: str) -> ErrorCalificacion:
    return ErrorCalificacion(codigo, detalle)


def _texto(valor: Any, donde: str, maximo: int) -> str:
    if (
        not isinstance(valor, str)
        or not valor.strip()
        or len(valor) > maximo
        or CONTROL.search(valor)
    ):
        raise _error(
            "RUBRICA_NO_VALIDA",
            f"{donde}: texto de 1 a {maximo} caracteres, sin caracteres de control",
        )
    return valor


def _peso(valor: Any, donde: str) -> float:
    if (
        isinstance(valor, bool)
        or not isinstance(valor, (int, float))
        or not 0 < valor <= MAX_PESO_FILA
        or not math.isfinite(valor)
        or round(float(valor), 2) != float(valor)
    ):
        raise _error(
            "RUBRICA_NO_VALIDA",
            f"{donde}: «peso» debe ser un número mayor que 0 y hasta {MAX_PESO_FILA}, "
            "con dos decimales como mucho",
        )
    return float(valor)


def _pesos(filas: tuple[FilaRubrica, ...]) -> list[float]:
    """El peso de cada fila: el suyo o 1 si ninguna lleva peso."""
    con_peso = [fila.peso is not None for fila in filas]
    if any(con_peso) and not all(con_peso):
        raise _error(
            "PESOS_DE_FILA_INCOMPLETOS",
            "o todas las filas llevan «peso» o ninguna",
        )
    if not any(con_peso):
        return [1.0] * len(filas)
    return [_peso(fila.peso, f"fila {numero}") for numero, fila in enumerate(filas, 1)]


def _descriptores(
    niveles: tuple[NivelRubrica, ...], descriptores: Any, donde: str
) -> dict[str, str]:
    """Los descriptores de una fila, uno por nivel, validados y en el orden del esquema."""
    if not isinstance(descriptores, dict):
        raise _error(
            "RUBRICA_NO_VALIDA",
            f"{donde}: «descriptores» debe ser un mapa de nivel a texto",
        )
    ids = {nivel.id for nivel in niveles}
    for clave in descriptores:
        if clave not in ids:
            if not contenido.id_evalua_valido(str(clave)):
                raise _error("RUBRICA_NO_VALIDA", _detalle_campo_no_permitido(donde, clave))
            raise _error(
                "NIVEL_DESCONOCIDO",
                f"{donde}: el nivel «{clave}» no está en niveles_rubrica",
            )
    salida: dict[str, str] = {}
    for nivel in niveles:
        if nivel.id not in descriptores:
            raise _error(
                "DESCRIPTOR_FALTA",
                f"{donde}: falta el descriptor del nivel «{nivel.id}»",
            )
        texto = _texto(descriptores[nivel.id], f"{donde}, nivel «{nivel.id}»", MAX_TEXTO)
        limite = MAX_TEXTO - len(nivel.nombre) - 2
        if len(texto) > limite:
            raise _error(
                "RUBRICA_NO_VALIDA",
                f"{donde}: el descriptor del nivel «{nivel.id}» no puede pasar de "
                f"{limite} caracteres, porque «{nivel.nombre}: » ocupa el resto "
                f"de los {MAX_TEXTO} de la definición",
            )
        salida[nivel.id] = texto
    return salida


def rubrica_de_filas(
    esquema: Esquema,
    filas: tuple[FilaRubrica, ...],
    nombre: str,
    descripcion: str,
    html: str,
) -> RubricaCargada:
    """Construye la rúbrica de una tarea a partir de sus filas por criterio."""
    if not isinstance(filas, tuple) or not 1 <= len(filas) <= MAX_CRITERIOS:
        raise _error("RUBRICA_NO_VALIDA", f"«filas» debe ser una tupla de 1 a {MAX_CRITERIOS}")
    for numero, fila in enumerate(filas, 1):
        if not isinstance(fila, FilaRubrica):
            raise _error("RUBRICA_NO_VALIDA", f"fila {numero}: debe ser una FilaRubrica")

    pesos = _pesos(filas)
    total = 10.0
    puntos = mayor_resto([peso / sum(pesos) * total for peso in pesos], total)
    puntos_por_nivel = [
        mayor_resto(
            [punto * nivel.porcentaje / 100 for punto in puntos],
            total * nivel.porcentaje / 100,
        )
        for nivel in esquema.niveles_rubrica
    ]
    for indice in range(len(filas)):
        puntos_fila = [nivel[indice] for nivel in puntos_por_nivel]
        if len(set(puntos_fila)) != len(puntos_fila):
            raise _error(
                "RUBRICA_NO_VALIDA",
                f"fila {indice + 1}: el peso es demasiado pequeño frente a las demás "
                "filas y sus niveles no reparten puntos distintos",
            )

    criterios_rubrica: list[CriterioRubrica] = []
    vistas: set[tuple[str, str]] = set()
    repeticiones: dict[str, int] = {}
    for indice, fila in enumerate(filas):
        donde = f"fila {indice + 1}"
        elemento, criterio = _hoja(esquema, fila.criterio)
        indicador = _texto(fila.indicador, f"{donde} (indicador)", MAX_INDICADOR)
        clave = (fila.criterio, indicador)
        if clave in vistas:
            raise _error(
                "RUBRICA_NO_VALIDA",
                f"{donde}: el criterio «{fila.criterio}» ya tiene una fila con el "
                f"indicador «{indicador}»",
            )
        vistas.add(clave)
        descriptores = _descriptores(esquema.niveles_rubrica, fila.descriptores, donde)

        repeticion = repeticiones.get(fila.criterio, 0) + 1
        repeticiones[fila.criterio] = repeticion
        id_ = fila.criterio.lower() if repeticion == 1 else f"{fila.criterio.lower()}_{repeticion}"
        codigo = elemento.codigo if criterio is None else criterio.codigo
        nombre_fila = f"{codigo} · {indicador}" if codigo else fila.criterio
        if len(nombre_fila) > MAX_NOMBRE_CRITERIO:
            raise _error(
                "RUBRICA_NO_VALIDA",
                f"{donde}: el título de la fila no puede pasar de {MAX_NOMBRE_CRITERIO} "
                "caracteres (código e indicador)",
            )
        texto = elemento.nombre if criterio is None else criterio.nombre
        niveles = tuple(
            Nivel(
                id=nivel.id,
                puntos=puntos_por_nivel[posicion][indice],
                descripcion=f"{nivel.nombre}: {descriptores[nivel.id]}",
            )
            for posicion, nivel in enumerate(esquema.niveles_rubrica)
        )
        criterios_rubrica.append(
            CriterioRubrica(
                id=id_,
                nombre=nombre_fila,
                descripcion=texto,
                niveles=niveles,
                criterio=fila.criterio,
            )
        )

    cargada = RubricaCargada(
        nombre=nombre,
        descripcion=descripcion,
        html=html,
        criterios=tuple(criterios_rubrica),
    )
    validar_rubrica(cargada)
    return cargada


def _detalle_campo_no_permitido(donde: str, campo: object) -> str:
    """Detalle de un campo desconocido, con la pista de la coma cuando lo parece."""
    texto = str(campo)
    detalle = f"{donde}: campo «{texto}» no permitido" if donde else f"campo «{texto}» no permitido"
    if not re.fullmatch(r"[a-z_]+", texto):
        detalle += " (¿una coma dentro de una descripción? Pon la descripción entre comillas)"
    return detalle


def _campo_no_permitido(donde: str, campo: object) -> ErrorContenido:
    return ErrorContenido("RUBRICA_NO_VALIDA", _detalle_campo_no_permitido(donde, campo))


def _nombre(datos: dict[str, Any]) -> str:
    valor = datos.get("nombre")
    if (
        not isinstance(valor, str)
        or not valor.strip()
        or len(valor) > MAX_NOMBRE_RUBRICA
        or CONTROL.search(valor)
    ):
        raise ErrorContenido(
            "RUBRICA_NO_VALIDA",
            f"nombre: texto de 1 a {MAX_NOMBRE_RUBRICA} caracteres, sin caracteres de control",
        )
    return valor.strip()


def _criterio(valor: Any, donde: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorContenido(
            "RUBRICA_NO_VALIDA",
            f"{donde}: «criterio» debe ser el id de un criterio de calificacion.yaml",
        )
    return valor.strip()


def _comprobar_criterios(
    esquema: Esquema, filas: tuple[FilaRubrica, ...], evalua: tuple[tuple[str, float], ...]
) -> None:
    """Cada fila es una hoja de ``evalua`` y cada criterio con peso tiene su fila."""
    en_evalua = {id_ for id_, _ in evalua}
    for numero, fila in enumerate(filas, 1):
        donde = f"fila {numero}"
        if fila.criterio not in en_evalua:
            raise ErrorContenido(
                "FILA_FUERA_DE_EVALUA",
                f"{donde}: el criterio «{fila.criterio}» no está en «evalua» de la tarea",
            )
        try:
            _hoja(esquema, fila.criterio)
        except ErrorCalificacion:
            raise ErrorContenido(
                "FILA_FUERA_DE_EVALUA",
                f"{donde}: «{fila.criterio}» no es un criterio hoja de calificacion.yaml",
            ) from None
    presentes = {fila.criterio for fila in filas}
    faltan = [id_ for id_, peso in evalua if peso > 0 and id_ not in presentes]
    if faltan:
        raise ErrorContenido(
            "CRITERIO_SIN_FILA",
            "faltan filas para los criterios con peso: " + ", ".join(faltan),
        )


def _filas_de_tarea(
    valor: Any, esquema: Esquema, evalua: tuple[tuple[str, float], ...]
) -> tuple[FilaRubrica, ...]:
    if not isinstance(valor, list) or not 1 <= len(valor) <= MAX_CRITERIOS:
        raise ErrorContenido(
            "RUBRICA_NO_VALIDA", f"«filas» debe ser una lista de 1 a {MAX_CRITERIOS}"
        )
    filas: list[FilaRubrica] = []
    for numero, item in enumerate(valor, 1):
        donde = f"fila {numero}"
        if not isinstance(item, dict):
            raise ErrorContenido("RUBRICA_NO_VALIDA", f"{donde}: debe ser un mapa")
        for campo in item:
            if campo not in _CAMPOS_FILA:
                raise _campo_no_permitido(donde, campo)
        niveles = item.get("niveles")
        if not isinstance(niveles, dict):
            raise ErrorContenido(
                "RUBRICA_NO_VALIDA",
                f"{donde}: «niveles» debe ser un mapa de nivel a texto",
            )
        filas.append(
            FilaRubrica(
                criterio=_criterio(item.get("criterio"), donde),
                indicador=cast(str, item.get("indicador")),
                peso=cast(float | None, item.get("peso")),
                descriptores=cast(dict[str, str], niveles),
            )
        )
    resultado = tuple(filas)
    _comprobar_criterios(esquema, resultado, evalua)
    return resultado


def _html_descripcion(ruta: Path, cuerpo: str) -> str:
    if not cuerpo.strip():
        raise ErrorContenido(
            "RUBRICA_NO_VALIDA",
            "la rúbrica necesita una descripción para el alumnado después del frontmatter: "
            "el alumnado tiene que leerla",
        )
    try:
        analisis = filtro.analizar(contenido._a_html(ruta, cuerpo))
    except filtro.HtmlPeligroso as exc:
        raise ErrorContenido("HTML_PELIGROSO", f"rúbrica: {exc.detalle}") from None
    if analisis.locales:
        raise ErrorContenido(
            "RUBRICA_NO_VALIDA",
            "la descripción de la rúbrica no admite imágenes ni ficheros locales",
        )
    return filtro.serializar(analisis.cuerpo)


def _detalle_con_fichero(detalle: str, ruta: Path) -> str:
    prefijo = f"{ruta.name}: "
    return detalle if detalle.startswith(prefijo) else prefijo + detalle


def _validar_rubrica_de_tarea(
    datos: dict[str, Any],
    cuerpo: str,
    ruta: Path,
    esquema: Esquema,
    evalua: tuple[tuple[str, float], ...],
) -> RubricaCargada:
    try:
        for campo in datos:
            if campo in _CAMPOS_PRIVADOS:
                raise ErrorContenido(
                    "RUBRICA_NO_VALIDA",
                    f"campo «{campo}» no permitido: {_CAMPOS_PRIVADOS[campo]} son de "
                    "tiza-privado; en el público escribe la rúbrica con «filas»",
                )
            if campo not in _CAMPOS:
                raise _campo_no_permitido("", campo)
        if datos.get("tipo") != "rubrica":
            raise ErrorContenido("RUBRICA_NO_VALIDA", "tipo debe ser rubrica")
        nombre = _nombre(datos)
        filas = _filas_de_tarea(datos.get("filas"), esquema, evalua)
        html = _html_descripcion(ruta, cuerpo)
        return rubrica_de_filas(esquema, filas, nombre, cuerpo, html)
    except ErrorCalificacion as exc:
        raise ErrorContenido(exc.codigo, _detalle_con_fichero(exc.detalle, ruta)) from None
    except ErrorContenido as exc:
        raise ErrorContenido(exc.codigo, _detalle_con_fichero(exc.detalle, ruta)) from None


def cargar_rubrica_de_tarea(
    ruta: Path,
    raiz: Path | None,
    esquema: Esquema,
    evalua: tuple[tuple[str, float], ...],
) -> RubricaCargada:
    """Carga el fichero de filas de una rúbrica enlazada desde una tarea.

    ``raiz`` es la carpeta de la asignatura: con ella, el fichero tiene que estar
    dentro (``RUBRICA_FUERA_DE_CARPETA``). Los problemas de formato son
    ``RUBRICA_NO_VALIDA``, salvo el frontmatter ilegible (``FRONTMATTER_INVALIDO``)
    y el HTML peligroso (``HTML_PELIGROSO``); el detalle va en español.
    """
    ruta = Path(ruta)
    try:
        resuelta = ruta.resolve()
    except (OSError, RuntimeError):
        raise ErrorContenido("FICHERO_AUSENTE", f"no existe la rúbrica {ruta.name}") from None
    if raiz is not None:
        try:
            resuelta.relative_to(Path(raiz).resolve())
        except ValueError:
            raise ErrorContenido(
                "RUBRICA_FUERA_DE_CARPETA", f"«{ruta.name}» está fuera de la carpeta"
            ) from None
    if not resuelta.is_file():
        raise ErrorContenido("FICHERO_AUSENTE", f"no existe la rúbrica {ruta.name}")
    try:
        texto = leer_bytes_acotado(resuelta, contenido.MAX_DOCUMENTO_BYTES).decode("utf-8")
    except FicheroNoSeguro as exc:
        if exc.motivo == "grande":
            raise ErrorContenido(
                "FICHERO_DEMASIADO_GRANDE",
                f"«{ruta.name}» pesa más de {contenido.MAX_DOCUMENTO_BYTES // 2**20} MB",
            ) from None
        raise ErrorContenido("FICHERO_AUSENTE", f"no existe la rúbrica {ruta.name}") from None
    except OSError:
        raise ErrorContenido("FICHERO_AUSENTE", f"no se pudo leer {ruta.name}") from None
    except UnicodeDecodeError:
        raise ErrorContenido("CODIFICACION_INVALIDA", "la rúbrica no es UTF-8") from None
    datos, cuerpo = contenido._separar_frontmatter(texto)
    return _validar_rubrica_de_tarea(datos, cuerpo, ruta, esquema, evalua)
