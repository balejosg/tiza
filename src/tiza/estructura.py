"""La estructura del aula: secciones, actividades y la localización de un documento.

Módulo puro: no habla con el aula ni importa python-moodle. La forma que llega sin validar
(la del aula y la de ``estructura.json``) se convierte una sola vez con los constructores
estrictos de :class:`Estructura`; a partir de ahí todo son tipos inmutables. ``Documento``
se importa solo para los tipos (``TYPE_CHECKING``) para no crear un ciclo con ``contenido``.

Vocabulario de dominio en ``CONTEXT.md``: estructura, sección, actividad, localización y
problema.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .contenido import Documento

# Código estable de la forma de la estructura que llega sin validar.
ESTRUCTURA_DEL_AULA_INVALIDA = "ESTRUCTURA_DEL_AULA_INVALIDA"

# La misma clase de caracteres que el resto de saneados del proyecto.
_NO_IMPRIMIBLE = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


class ErrorEstructura(Exception):
    """Error de la estructura del aula con un código estable."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


def nombre_de_seccion(texto: str) -> str:
    """Nombre de sección apto para el esquema cerrado: sin < > ni controles."""
    limpio = _NO_IMPRIMIBLE.sub(" ", texto).replace("<", "‹").replace(">", "›")
    return " ".join(limpio.split())[:255]


@dataclass(frozen=True)
class Actividad:
    """Lo que hay en una sección del aula: ``cmid``, nombre y tipo.

    En Moodle y en el código se llama *módulo*; en la prosa, actividad. ``tipo`` es el
    nombre interno de tiza (``pagina``, ``tarea``…) o el ``modname`` desconocido del aula.
    """

    cmid: int
    nombre: str
    tipo: str


@dataclass(frozen=True)
class Seccion:
    """Un apartado del curso: número, nombre, id y sus actividades en el orden del aula."""

    numero: int
    nombre: str
    id: int
    actividades: tuple[Actividad, ...] = ()

    @property
    def cmids(self) -> tuple[int, ...]:
        """Los ``cmid`` de sus actividades, en orden."""
        return tuple(actividad.cmid for actividad in self.actividades)

    def para_fichero(self) -> dict[str, int | str]:
        """El dict cerrado de tres claves con el que se guarda en ``estructura.json``."""
        return {"numero": self.numero, "nombre": self.nombre, "id": self.id}


@dataclass(frozen=True)
class Estructura:
    """Las secciones de un curso en el orden en que se construyeron.

    No ordena (el orden por ``numero`` lo pone el adapter del aula) y no impone unicidad de
    ``numero``, ``id`` ni ``cmid``. Admite ``len`` y recorrido.
    """

    secciones: tuple[Seccion, ...] = ()

    def __iter__(self) -> Iterator[Seccion]:
        return iter(self.secciones)

    def __len__(self) -> int:
        return len(self.secciones)

    @classmethod
    def de_dicts(cls, secciones: Sequence[Mapping[str, Any]]) -> Estructura:
        """Construye la estructura del aula desde ``numero``, ``nombre``, ``id`` y ``modulos``.

        Estricto: no repara nada. La lectura tolerante de lo que devuelve Moodle es del
        adapter del aula; aquí, lo que no tiene la forma esperada es
        ``ESTRUCTURA_DEL_AULA_INVALIDA``. El nombre de la sección se sanea con
        :func:`nombre_de_seccion`.
        """
        return cls._construir(secciones, con_actividades=True)

    @classmethod
    def de_dicts_guardada(cls, secciones: Sequence[Mapping[str, Any]]) -> Estructura:
        """Construye la estructura de ``estructura.json``: sin actividades.

        Si una sección trae ``modulos``, se rechaza: el fichero guarda la misma estructura
        sin las actividades.
        """
        return cls._construir(secciones, con_actividades=False)

    @classmethod
    def _construir(
        cls, secciones: Sequence[Mapping[str, Any]], *, con_actividades: bool
    ) -> Estructura:
        if not isinstance(secciones, (list, tuple)):
            raise ErrorEstructura(
                ESTRUCTURA_DEL_AULA_INVALIDA, "las secciones deben ser una lista o una tupla"
            )
        salida: list[Seccion] = []
        for posicion, bruta in enumerate(secciones, start=1):
            donde = f"sección {posicion}"
            if not isinstance(bruta, Mapping):
                raise ErrorEstructura(ESTRUCTURA_DEL_AULA_INVALIDA, f"{donde}: no es un mapa")
            numero = _campo_entero(bruta, "numero", donde)
            nombre = _campo_texto(bruta, "nombre", donde)
            identificador = _campo_entero(bruta, "id", donde)
            if con_actividades:
                actividades = _actividades_de(bruta, donde)
            else:
                if "modulos" in bruta:
                    raise ErrorEstructura(
                        ESTRUCTURA_DEL_AULA_INVALIDA,
                        f"{donde}: «modulos» no está permitido en la estructura guardada",
                    )
                actividades = ()
            salida.append(
                Seccion(
                    numero=numero,
                    nombre=nombre_de_seccion(nombre),
                    id=identificador,
                    actividades=actividades,
                )
            )
        return cls(tuple(salida))

    def buscar_seccion(self, clave: int | str) -> Seccion | None:
        """Sección por número (entero) o por nombre (texto, sin distinguir mayúsculas).

        El nombre se compara saneado con :func:`nombre_de_seccion` en los dos lados. Nunca
        lanza: una clave que no está devuelve nada.
        """
        indice = self._indice_de_seccion(clave)
        return self.secciones[indice] if indice is not None else None

    def seccion_con_id(self, id: int) -> Seccion | None:
        """La primera sección con ese ``id``, o nada."""
        return next((seccion for seccion in self.secciones if seccion.id == id), None)

    def _indice_de_seccion(self, clave: int | str) -> int | None:
        """Posición de la sección que :meth:`buscar_seccion` devolvería, o nada."""
        if isinstance(clave, int):
            for indice, seccion in enumerate(self.secciones):
                if seccion.numero == clave:
                    return indice
            return None
        normalizada = nombre_de_seccion(clave).casefold()
        for indice, seccion in enumerate(self.secciones):
            if nombre_de_seccion(seccion.nombre).casefold() == normalizada:
                return indice
        return None

    def localizar(self, doc: Documento, curso: int | None) -> Localizacion:
        """La actividad del aula que corresponde a ``doc``: la única búsqueda de tiza. Pura.

        En este orden:

        1. El ``origen`` de ``doc`` en su curso: manda sobre el registro. Si ya no está o es
           de otro tipo, ``ORIGEN_NO_ENCONTRADO``.
        2. El registro de lo publicado (``doc.publicados`` de ``curso``): el módulo de ese
           ``cmid`` y del tipo de ``doc``, se llame como se llame y esté donde esté. Si se
           llama distinto que ``doc`` y la sección de ``doc`` ya tiene otro del mismo tipo
           con su nombre, ``ACTIVIDAD_AMBIGUA``.
        3. Mismo tipo y nombre en la sección de ``doc`` (el primero; ``varios`` si hay más).
        4. Mismo tipo y nombre en otra sección: uno es ``otra_seccion``; varios quedan sin
           módulo y con ``varios``, y quien escribe decide.
        5. Nada: actividad nueva (``por`` vacío), con ``borrada`` si el registro la daba por
           publicada.

        Con ``curso`` desconocido no se usan ni el ``origen`` ni el registro. No lanza: los
        dos problemas posibles van en ``problema``.
        """
        if aplica_origen(doc, curso):
            hallado = self._por_origen(doc)
            if hallado is None:
                return Localizacion(
                    seccion=None,
                    modulo=None,
                    por=None,
                    problema="ORIGEN_NO_ENCONTRADO",
                )
            seccion, actividad = hallado
            return Localizacion(seccion=seccion, modulo=actividad, por="origen")

        entrada = doc.publicados.get(curso) if curso is not None else None
        if entrada is not None:
            hallado = self._por_registro(entrada.cmid, doc.tipo)
            if hallado is not None:
                seccion, actividad = hallado
                if actividad.nombre != doc.nombre and self._modulos_de(doc):
                    return Localizacion(
                        seccion=None,
                        modulo=None,
                        por=None,
                        problema="ACTIVIDAD_AMBIGUA",
                    )
                return Localizacion(seccion=seccion, modulo=actividad, por="registro")

        propia = self.buscar_seccion(doc.seccion)
        en_su_seccion = self._modulos_de(doc)
        if en_su_seccion:
            return Localizacion(
                seccion=propia,
                modulo=en_su_seccion[0][1],
                por="nombre",
                varios=len(en_su_seccion) > 1,
            )
        fuera = self._modulos_fuera(doc)
        if len(fuera) == 1:
            return Localizacion(seccion=fuera[0][0], modulo=fuera[0][1], por="otra_seccion")
        if fuera:
            return Localizacion(seccion=None, modulo=None, por="otra_seccion", varios=True)
        return Localizacion(seccion=propia, modulo=None, por=None, borrada=entrada is not None)

    def _por_origen(self, doc: Documento) -> tuple[Seccion, Actividad] | None:
        """La actividad del ``origen`` de ``doc``, con el bucle de siempre.

        Ante un ``cmid`` de otro tipo sigue mirando las secciones siguientes (el ``break``
        sale solo del bucle de actividades), como hoy.
        """
        assert doc.origen is not None
        for seccion in self.secciones:
            for actividad in seccion.actividades:
                if actividad.cmid == doc.origen.cmid:
                    if actividad.tipo == doc.tipo:
                        return seccion, actividad
                    break
        return None

    def _por_registro(self, cmid: int, tipo: str) -> tuple[Seccion, Actividad] | None:
        """La actividad de ese ``cmid`` y tipo, o nada; a la primera coincidencia de ``cmid``.

        Si la primera con ese ``cmid`` es de otro tipo, no sigue buscando: es el bucle de hoy
        del registro, que difiere del del origen solo en el caso patológico de un ``cmid``
        repetido en dos secciones.
        """
        for seccion in self.secciones:
            for actividad in seccion.actividades:
                if actividad.cmid == cmid:
                    return (seccion, actividad) if actividad.tipo == tipo else None
        return None

    def _modulos_de(self, doc: Documento) -> list[tuple[Seccion, Actividad]]:
        """Actividades de la sección de ``doc`` con su tipo y su nombre (casi siempre una o ninguna)."""
        indice = self._indice_de_seccion(doc.seccion)
        if indice is None:
            return []
        seccion = self.secciones[indice]
        return [
            (seccion, actividad)
            for actividad in seccion.actividades
            if actividad.tipo == doc.tipo and actividad.nombre == doc.nombre
        ]

    def _modulos_fuera(self, doc: Documento) -> list[tuple[Seccion, Actividad]]:
        """Actividades con el tipo y nombre de ``doc`` en las demás secciones, por posición.

        La sección propia se salta por su posición en la tupla, no por igualdad: dos
        secciones iguales en valor no se ocultan entre sí.
        """
        propia = self._indice_de_seccion(doc.seccion)
        salida: list[tuple[Seccion, Actividad]] = []
        for indice, seccion in enumerate(self.secciones):
            if indice == propia:
                continue
            salida += [
                (seccion, actividad)
                for actividad in seccion.actividades
                if actividad.tipo == doc.tipo and actividad.nombre == doc.nombre
            ]
        return salida

    def ya_existe(self, doc: Documento, curso: int | None = None) -> bool | None:
        """Si al publicar ``doc`` se actualizaría una actividad que ya existe.

        Solo lectura, con el criterio de :meth:`localizar`: por el ``origen`` o el registro,
        verdadero; sin sección propia, falso; si no, si se halló por nombre. Nada solo si hay
        problema (el ``origen`` ya no está o el nombre es ambiguo): quien lo muestre debe
        avisar de que puede existir, sin abortar.
        """
        loc = self.localizar(doc, curso)
        if loc.problema is not None:
            return None
        if loc.por in ("origen", "registro"):
            return True
        if self.buscar_seccion(doc.seccion) is None:
            return False
        return loc.por == "nombre"

    def desde_donde_se_mueve(self, doc: Documento, curso: int | None = None) -> str | None:
        """Nombre de la sección de la que se movería ``doc`` al publicarlo, o nada.

        Solo lectura, sobre :meth:`localizar`: se mueve la actividad de su ``origen`` o de su
        registro si no está en su sección, y la única del mismo tipo y nombre que haya en otra
        si no existe en la suya. Lo que no se puede resolver (problema, varias en otras
        secciones, nombre ambiguo) no se mueve.
        """
        loc = self.localizar(doc, curso)
        if loc.problema is not None:
            return None
        if loc.modulo is None or loc.seccion is None or loc.por not in _SE_MUEVE:
            return None
        if loc.por != "otra_seccion":
            propia = self.buscar_seccion(doc.seccion)
            if propia is not None and propia.id == loc.seccion.id:
                return None
        return str(loc.seccion.nombre or "")

    def secciones_que_faltan(self, documentos: Sequence[Documento]) -> list[str]:
        """Nombres de sección pedidos por los documentos que aún no existen, sin duplicar."""
        faltan: list[str] = []
        for doc in documentos:
            if isinstance(doc.seccion, str) and self.buscar_seccion(doc.seccion) is None:
                if doc.seccion.casefold() not in {nombre.casefold() for nombre in faltan}:
                    faltan.append(doc.seccion)
        return faltan

    def resolver_orden(
        self, docs: Sequence[Documento], curso: int | None = None
    ) -> ResolucionOrden:
        """Cada sección con sus documentos en el orden pedido y la actividad de cada uno.

        Cada actividad se halla con :meth:`localizar` (``curso``: el del aula, para el
        ``origen`` y el registro) y se ordena en la sección en la que está. ``FICHERO_REPETIDO``,
        ``ACTIVIDAD_AUSENTE``, ``ACTIVIDAD_AMBIGUA`` y ``ORIGEN_NO_ENCONTRADO`` (el ``origen``
        ya no está) se dan antes de mover nada, el primero en el orden de los documentos. Con
        problema, ``grupos`` va vacío.
        """
        vistos: set[Path] = set()
        cmids: set[int] = set()
        grupos: dict[int, tuple[Seccion, list[tuple[Documento, Actividad]]]] = {}
        for doc in docs:
            ruta = doc.ruta.resolve()
            if ruta in vistos:
                return ResolucionOrden(problema=("FICHERO_REPETIDO", doc.ruta.name))
            vistos.add(ruta)
            loc = self.localizar(doc, curso)
            if loc.problema is not None:
                return ResolucionOrden(problema=(loc.problema, doc.ruta.name))
            actividad = loc.actividad
            if actividad is None:
                return ResolucionOrden(problema=("ACTIVIDAD_AUSENTE", doc.ruta.name))
            # Dos ficheros que apuntan a la misma actividad: no hay orden entre ellos.
            if loc.varios or actividad.cmid in cmids:
                return ResolucionOrden(problema=("ACTIVIDAD_AMBIGUA", doc.ruta.name))
            cmids.add(actividad.cmid)
            seccion = loc.seccion
            assert seccion is not None  # ``localizar`` la dio con la actividad
            grupos.setdefault(seccion.id, (seccion, []))[1].append((doc, actividad))
        return ResolucionOrden(
            grupos=tuple((seccion, tuple(pares)) for seccion, pares in grupos.values())
        )

    def sin_actividades(self) -> Estructura:
        """La misma estructura sin actividades, para ``estructura.json``."""
        return Estructura(
            tuple(
                Seccion(numero=seccion.numero, nombre=seccion.nombre, id=seccion.id)
                for seccion in self.secciones
            )
        )


@dataclass(frozen=True)
class Localizacion:
    """Dónde está en el aula la actividad de un documento (resultado de :meth:`Estructura.localizar`).

    ``por`` dice cómo se halló: ``origen``, ``registro``, ``nombre``, ``otra_seccion`` o nada
    (no está: se creará). ``seccion`` es la sección en la que está la ``actividad`` (o la del
    documento, si es nueva y existe). ``borrada``: el registro la daba por publicada pero ya
    no está en el aula (o es de otro tipo). ``varios``: en el paso que decidió había más de un
    candidato del mismo tipo y nombre; con ``por="otra_seccion"`` y sin ``modulo``, son varios
    en otras secciones y no se sabe cuál es. ``problema`` lleva el código cuando no se puede
    decidir (``ORIGEN_NO_ENCONTRADO``, ``ACTIVIDAD_AMBIGUA``): no es una excepción.
    """

    seccion: Seccion | None
    modulo: Actividad | None
    por: str | None
    borrada: bool = False
    varios: bool = False
    problema: str | None = None

    @property
    def actividad(self) -> Actividad | None:
        """La actividad que actualizaría el documento: la hallada por origen, registro o nombre.

        La de otra sección no cuenta: solo publicar la mueve. Es lo que usan las funciones de
        solo lectura y las que ordenan o cambian fechas, que no mueven nada de sección.
        """
        return self.modulo if self.por in ("origen", "registro", "nombre") else None


@dataclass(frozen=True)
class ResolucionOrden:
    """El orden resuelto de :meth:`Estructura.resolver_orden`: grupos y el primer problema.

    ``grupos``: por sección en orden de primera aparición, la sección y sus documentos con su
    actividad. ``problema``: ``(código, fichero)`` del primer fallo, o nada.
    """

    grupos: tuple[tuple[Seccion, tuple[tuple[Documento, Actividad], ...]], ...] = ()
    problema: tuple[str, str] | None = None


_SE_MUEVE = ("origen", "registro", "otra_seccion")  # por qué se halla fuera de su sección


def aplica_origen(doc: Documento, curso: int | None) -> bool:
    """Si ``doc`` se busca en el aula por su ``origen``: solo en el curso del que viene.

    En el curso de pruebas o en otro curso real (``curso`` distinto o desconocido) se busca
    como siempre: sección, tipo y nombre.
    """
    return doc.origen is not None and curso is not None and doc.origen.curso == curso


def _campo_entero(datos: Mapping[str, Any], campo: str, donde: str) -> int:
    if campo not in datos:
        raise ErrorEstructura(ESTRUCTURA_DEL_AULA_INVALIDA, f"{donde}: falta «{campo}»")
    valor = datos[campo]
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErrorEstructura(
            ESTRUCTURA_DEL_AULA_INVALIDA, f"{donde}: «{campo}» debe ser un entero"
        )
    return valor


def _campo_texto(datos: Mapping[str, Any], campo: str, donde: str) -> str:
    if campo not in datos:
        raise ErrorEstructura(ESTRUCTURA_DEL_AULA_INVALIDA, f"{donde}: falta «{campo}»")
    valor = datos[campo]
    if not isinstance(valor, str):
        raise ErrorEstructura(ESTRUCTURA_DEL_AULA_INVALIDA, f"{donde}: «{campo}» debe ser texto")
    return valor


def _actividades_de(datos: Mapping[str, Any], donde: str) -> tuple[Actividad, ...]:
    if "modulos" not in datos:
        raise ErrorEstructura(ESTRUCTURA_DEL_AULA_INVALIDA, f"{donde}: falta «modulos»")
    modulos = datos["modulos"]
    if not isinstance(modulos, (list, tuple)):
        raise ErrorEstructura(
            ESTRUCTURA_DEL_AULA_INVALIDA, f"{donde}: «modulos» debe ser una lista o una tupla"
        )
    salida: list[Actividad] = []
    for posicion, bruto in enumerate(modulos, start=1):
        suyo = f"{donde}, módulo {posicion}"
        if not isinstance(bruto, Mapping):
            raise ErrorEstructura(ESTRUCTURA_DEL_AULA_INVALIDA, f"{suyo}: no es un mapa")
        cmid = _campo_entero(bruto, "cmid", suyo)
        nombre = _campo_texto(bruto, "nombre", suyo)
        tipo = _campo_texto(bruto, "tipo", suyo)
        salida.append(Actividad(cmid=cmid, nombre=nombre, tipo=tipo))
    return tuple(salida)
