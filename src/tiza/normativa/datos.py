"""Cargador de los datos de normativa: lee los JSON del paquete y los valida por completo.

Los datos viven en ``tiza/normativa/datos`` como un fichero por norma
(``normas/*.json``) y uno por materia o módulo (``fichas/*.json``). Se validan con
conjuntos cerrados de claves, como ``estado.py``: una clave desconocida, un campo
mal formado o una referencia a algo que no existe es ``DATOS_INVALIDOS`` (con el
fichero y el campo en el detalle) y no se carga nada a medias.

Aquí no hay red ni lógica de consulta: solo el modelo ya validado, en un
:class:`Indice`. La carga se cachea por raíz.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any
from urllib.parse import urlsplit

from .modelo import (
    BOLETINES,
    DATOS_POR_TIPO,
    ESTADOS,
    ETAPAS,
    RANGOS,
    TIPOS_ELEMENTO,
    Elemento,
    Ficha,
    Norma,
    Procedencia,
)

__all__ = [
    "ErrorNormativa",
    "Indice",
    "cargar",
    "limpiar_cache",
    "normalizar_cita",
]

_CACHE: dict[Traversable | None, Indice] = {}  # por raíz; solo guarda cargas completas

_DOMINIOS = frozenset({"www.boe.es", "www.bocm.es"})
_DOMINIO_COMUNIDAD = "www.comunidad.madrid"  # solo para las normas con boletín CM
_NOMBRE_DEL_RANGO = {
    "real_decreto": "real decreto",
    "decreto": "decreto",
    "orden": "orden",
    "resolucion": "resolución",
}
_ID_NORMA = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_FRAGMENTO = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_CODIGO = re.compile(r"[A-Z][A-Z0-9]*(?:\.[A-Za-z0-9]+)*")
_RELACION = re.compile(r"[a-z][a-z_]*")
_NUMERO = re.compile(r"[0-9A-Za-z.-]+/\d{4}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
_CURSO_ACADEMICO = re.compile(r"(\d{4})-(\d{2})")
_CURSO = re.compile(r"[1-9]")
_TEXTO = re.compile(r"\S+(?: \S+)*")  # sin espacios sobrantes ni saltos de línea ni tabuladores

_NORMA_OBLIGATORIAS = (
    "id",
    "rango",
    "numero",
    "fecha",
    "titulo",
    "boletin",
    "url_pdf",
    "sha256",
    "estado",
    "revisada",
)
_NORMA_OPCIONALES = (
    "url_api",
    "correcciones",
    "modifica",
    "modificada_por",
    "derogada_por",
    "desde",
    "derogaciones_parciales",
    "citas",
)
_FICHA_OBLIGATORIAS = (
    "codigo",
    "nombre",
    "etapa",
    "curso",
    "cursos_academicos",
    "normas",
    "elementos",
)
_FICHA_OPCIONALES = ("desde",)
_ELEMENTO_OBLIGATORIAS = ("codigo", "tipo", "texto", "procedencia", "orden")
_ELEMENTO_OPCIONALES = ("padre", "relaciones", "datos")
_PROCEDENCIA_OBLIGATORIAS = ("norma", "ubicacion")
_PROCEDENCIA_OPCIONALES = ("pagina", "via")


class ErrorNormativa(Exception):
    """Error de los datos de normativa con un código estable (``DATOS_INVALIDOS``)."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


@dataclass(frozen=True)
class Indice:
    """Los datos ya validados, indexados.

    ``alias`` lleva la cita normalizada de cada norma («decreto 27/2025», «rd
    1736/2023») y las que figuran en sus ``citas`` (erratas publicadas incluidas)
    hacia el id de la norma.
    """

    normas: dict[str, Norma]
    fichas: dict[str, Ficha]
    elementos: dict[str, tuple[Ficha, Elemento]]
    alias: dict[str, str]


def normalizar_cita(cita: str) -> str:
    """La cita en NFC, en minúsculas, sin puntos ni «de»/«del» y con espacios simples."""
    texto = unicodedata.normalize("NFC", cita).lower().replace(".", "")
    return " ".join(p for p in texto.split() if p not in ("de", "del"))


def limpiar_cache() -> None:
    """Olvida las cargas hechas (para los tests, que cambian ficheros bajo la misma ruta)."""
    _CACHE.clear()


def cargar(raiz: Traversable | None = None) -> Indice:
    """Lee y valida ``normas/*.json`` y ``fichas/*.json`` de ``raiz`` (por defecto, el paquete).

    Cualquier fallo es ``ErrorNormativa("DATOS_INVALIDOS", <fichero y campo>)``; un
    fallo no se cachea y nunca queda una carga a medias.
    """
    if raiz not in _CACHE:
        carpeta = files("tiza.normativa").joinpath("datos") if raiz is None else raiz
        _CACHE[raiz] = _Cargador().cargar(carpeta)
    return _CACHE[raiz]


# --- lectura y validación de un fichero ----------------------------------------


class _Lector:
    """Las comprobaciones de un fichero: cada fallo nombra el fichero y el campo."""

    def __init__(self, fichero: str) -> None:
        self.fichero = fichero

    def fallo(self, campo: str, motivo: str) -> ErrorNormativa:
        return ErrorNormativa("DATOS_INVALIDOS", f"{self.fichero}: {campo}: {motivo}")

    def objeto(
        self, valor: Any, campo: str, obligatorias: tuple[str, ...], opcionales: tuple[str, ...]
    ) -> dict[str, Any]:
        if not isinstance(valor, dict):
            raise self.fallo(campo, "debe ser un objeto")
        punto = f"{campo}." if campo else ""
        for clave in valor:
            if clave not in obligatorias and clave not in opcionales:
                raise self.fallo(f"{punto}{clave}", "clave no permitida")
        for clave in obligatorias:
            if clave not in valor:
                raise self.fallo(f"{punto}{clave}", "falta la clave")
        return valor

    def texto(self, valor: Any, campo: str) -> str:
        if not isinstance(valor, str) or not _TEXTO.fullmatch(valor):
            raise self.fallo(campo, "debe ser un texto no vacío, sin espacios sobrantes")
        if unicodedata.normalize("NFC", valor) != valor:
            raise self.fallo(campo, "el texto debe estar en forma NFC")
        return valor

    def patron(self, valor: Any, campo: str, patron: re.Pattern[str]) -> str:
        if not isinstance(valor, str) or not patron.fullmatch(valor):
            raise self.fallo(campo, "formato no válido")
        return valor

    def una_de(self, valor: Any, campo: str, permitidos: tuple[str, ...]) -> str:
        if not isinstance(valor, str) or valor not in permitidos:
            raise self.fallo(campo, f"debe ser una de {', '.join(permitidos)}")
        return valor

    def fecha(self, valor: Any, campo: str) -> date:
        if not isinstance(valor, str) or not _FECHA.fullmatch(valor):
            raise self.fallo(campo, "debe ser una fecha ISO (AAAA-MM-DD)")
        try:
            return date.fromisoformat(valor)
        except ValueError:
            raise self.fallo(campo, "la fecha no existe") from None

    def lista(self, valor: Any, campo: str) -> list[Any]:
        if not isinstance(valor, list):
            raise self.fallo(campo, "debe ser una lista")
        return valor

    def textos(self, valor: Any, campo: str) -> tuple[str, ...]:
        return tuple(self.texto(v, f"{campo}[{i}]") for i, v in enumerate(self.lista(valor, campo)))

    def url(self, valor: Any, campo: str, boletin: str) -> str:
        permitidos = _DOMINIOS | ({_DOMINIO_COMUNIDAD} if boletin == "CM" else set())
        if not isinstance(valor, str) or not _TEXTO.fullmatch(valor):
            raise self.fallo(campo, "debe ser una URL")
        partes = urlsplit(valor)
        try:
            puerto = partes.port
        except ValueError:
            puerto = -1
        if (
            partes.scheme != "https"
            or partes.hostname not in permitidos
            or partes.username is not None
            or partes.password is not None
            or puerto is not None
        ):
            raise self.fallo(campo, f"solo https en {', '.join(sorted(permitidos))}")
        return valor

    def referencia(self, valor: Any, campo: str, *, fragmento: bool = False) -> str:
        """Un id de norma; con ``fragmento``, admite el sufijo ``#fragmento``."""
        if not isinstance(valor, str):
            raise self.fallo(campo, "debe ser un id de norma")
        id_, separador, resto = valor.partition("#")
        if not _ID_NORMA.fullmatch(id_) or (
            separador and (not fragmento or not _FRAGMENTO.fullmatch(resto))
        ):
            raise self.fallo(campo, "id de norma no válido")
        return valor

    def referencias(self, valor: Any, campo: str, *, fragmento: bool = False) -> tuple[str, ...]:
        return tuple(
            self.referencia(v, f"{campo}[{i}]", fragmento=fragmento)
            for i, v in enumerate(self.lista(valor, campo))
        )


def _leer_norma(lector: _Lector, bruto: Any) -> Norma:
    d = lector.objeto(bruto, "", _NORMA_OBLIGATORIAS, _NORMA_OPCIONALES)
    boletin = lector.una_de(d["boletin"], "boletin", BOLETINES)
    estado = lector.una_de(d["estado"], "estado", ESTADOS)
    derogada_por = d.get("derogada_por")
    desde = d.get("desde")
    if estado == "derogada":
        if derogada_por is None:
            raise lector.fallo("derogada_por", "una norma derogada la necesita")
        if desde is None:
            raise lector.fallo("desde", "una norma derogada la necesita")
        derogada_por = lector.referencia(derogada_por, "derogada_por")
        desde = lector.fecha(desde, "desde")
    elif derogada_por is not None or desde is not None:
        clave = "derogada_por" if derogada_por is not None else "desde"
        raise lector.fallo(clave, "solo una norma derogada la lleva")
    url_api = d.get("url_api")
    if url_api is not None:
        if boletin != "BOE":
            raise lector.fallo("url_api", "solo las normas del BOE tienen API")
        url_api = lector.url(url_api, "url_api", boletin)
    numero = lector.patron(d["numero"], "numero", _NUMERO)
    return Norma(
        id=lector.patron(d["id"], "id", _ID_NORMA),
        rango=lector.una_de(d["rango"], "rango", RANGOS),
        numero=numero,
        fecha=lector.fecha(d["fecha"], "fecha"),
        titulo=lector.texto(d["titulo"], "titulo"),
        boletin=boletin,
        url_pdf=lector.url(d["url_pdf"], "url_pdf", boletin),
        url_api=url_api,
        sha256=lector.patron(d["sha256"], "sha256", _SHA256),
        correcciones=lector.referencias(d.get("correcciones", []), "correcciones", fragmento=True),
        modifica=lector.referencias(d.get("modifica", []), "modifica"),
        modificada_por=lector.referencias(d.get("modificada_por", []), "modificada_por"),
        estado=estado,
        derogada_por=derogada_por,
        desde=desde,
        derogaciones_parciales=lector.textos(
            d.get("derogaciones_parciales", []), "derogaciones_parciales"
        ),
        citas=lector.textos(d.get("citas", []), "citas"),
        revisada=lector.fecha(d["revisada"], "revisada"),
    )


def _leer_procedencia(lector: _Lector, bruto: Any, campo: str) -> Procedencia:
    d = lector.objeto(bruto, campo, _PROCEDENCIA_OBLIGATORIAS, _PROCEDENCIA_OPCIONALES)
    pagina = d.get("pagina")
    if pagina is not None and (type(pagina) is not int or pagina < 1):
        raise lector.fallo(f"{campo}.pagina", "debe ser un entero positivo o null")
    via = tuple(
        _leer_procedencia(lector, v, f"{campo}.via[{i}]")
        for i, v in enumerate(lector.lista(d.get("via", []), f"{campo}.via"))
    )
    return Procedencia(
        norma=lector.referencia(d["norma"], f"{campo}.norma"),
        ubicacion=lector.texto(d["ubicacion"], f"{campo}.ubicacion"),
        pagina=pagina,
        via=via,
    )


def _leer_datos(lector: _Lector, bruto: Any, campo: str, tipo: str) -> dict[str, int | str]:
    permitidos = DATOS_POR_TIPO[tipo]
    d = lector.objeto(bruto, campo, (), tuple(permitidos))
    for clave, valor in d.items():
        if type(valor) is not permitidos[clave]:
            raise lector.fallo(f"{campo}.{clave}", f"debe ser {permitidos[clave].__name__}")
        if type(valor) is int and valor < 1:
            raise lector.fallo(f"{campo}.{clave}", "debe ser un entero positivo")
    return dict(d)


def _leer_relaciones(lector: _Lector, bruto: Any, campo: str) -> dict[str, tuple[str, ...]]:
    if not isinstance(bruto, dict):
        raise lector.fallo(campo, "debe ser un objeto")
    relaciones: dict[str, tuple[str, ...]] = {}
    for nombre, valor in bruto.items():
        lector.patron(nombre, f"{campo}.{nombre}", _RELACION)
        codigos = lector.lista(valor, f"{campo}.{nombre}")
        relaciones[nombre] = tuple(
            lector.patron(c, f"{campo}.{nombre}[{i}]", _CODIGO) for i, c in enumerate(codigos)
        )
    return relaciones


def _leer_elemento(lector: _Lector, bruto: Any, posicion: int) -> Elemento:
    codigo = bruto.get("codigo") if isinstance(bruto, dict) else None
    campo = f"elementos[{codigo if isinstance(codigo, str) else posicion}]"
    d = lector.objeto(bruto, campo, _ELEMENTO_OBLIGATORIAS, _ELEMENTO_OPCIONALES)
    tipo = lector.una_de(d["tipo"], f"{campo}.tipo", TIPOS_ELEMENTO)
    orden = d["orden"]
    if type(orden) is not int or orden < 0:
        raise lector.fallo(f"{campo}.orden", "debe ser un entero no negativo")
    padre = d.get("padre")
    if padre is not None:
        padre = lector.patron(padre, f"{campo}.padre", _CODIGO)
    return Elemento(
        codigo=lector.patron(d["codigo"], f"{campo}.codigo", _CODIGO),
        tipo=tipo,
        texto=lector.texto(d["texto"], f"{campo}.texto"),
        procedencia=_leer_procedencia(lector, d["procedencia"], f"{campo}.procedencia"),
        padre=padre,
        relaciones=_leer_relaciones(lector, d.get("relaciones", {}), f"{campo}.relaciones"),
        orden=orden,
        datos=_leer_datos(lector, d.get("datos", {}), f"{campo}.datos", tipo),
    )


def _leer_ficha(lector: _Lector, bruto: Any) -> Ficha:
    d = lector.objeto(bruto, "", _FICHA_OBLIGATORIAS, _FICHA_OPCIONALES)
    curso = d["curso"]
    if curso is not None:
        curso = lector.patron(curso, "curso", _CURSO)
    cursos = lector.lista(d["cursos_academicos"], "cursos_academicos")
    if not cursos:
        raise lector.fallo("cursos_academicos", "debe llevar al menos un curso")
    for i, c in enumerate(cursos):
        campo = f"cursos_academicos[{i}]"
        partes = _CURSO_ACADEMICO.fullmatch(c) if isinstance(c, str) else None
        if partes is None or int(partes[2]) != (int(partes[1]) + 1) % 100:
            raise lector.fallo(campo, "debe ser un curso como «2026-27»")
    desde = d.get("desde")
    elementos = tuple(
        _leer_elemento(lector, e, i)
        for i, e in enumerate(lector.lista(d["elementos"], "elementos"))
    )
    vistos: dict[int, str] = {}
    for e in elementos:
        if e.orden in vistos:
            raise lector.fallo(
                f"elementos[{e.codigo}].orden",
                f"el orden {e.orden} ya lo tiene {vistos[e.orden]}",
            )
        vistos[e.orden] = e.codigo
    return Ficha(
        codigo=lector.patron(d["codigo"], "codigo", _CODIGO),
        nombre=lector.texto(d["nombre"], "nombre"),
        etapa=lector.una_de(d["etapa"], "etapa", ETAPAS),
        curso=curso,
        cursos_academicos=tuple(cursos),
        normas=lector.referencias(d["normas"], "normas"),
        elementos=tuple(sorted(elementos, key=lambda e: e.orden)),
        desde=None if desde is None else lector.fecha(desde, "desde"),
    )


# --- carga de la carpeta y comprobaciones entre ficheros ---------------------


def _sin_repetidas(pares: list[tuple[str, Any]]) -> dict[str, Any]:
    d: dict[str, Any] = {}
    for clave, valor in pares:
        if clave in d:
            raise ValueError(f"clave repetida «{clave}»")
        d[clave] = valor
    return d


def _sin_constantes(constante: str) -> Any:
    raise ValueError(f"valor no permitido «{constante}»")


class _Cargador:
    def __init__(self) -> None:
        self.normas: dict[str, Norma] = {}
        self.fichas: dict[str, Ficha] = {}
        self.elementos: dict[str, tuple[Ficha, Elemento]] = {}
        self.de_norma: dict[str, str] = {}  # id de norma -> fichero
        self.de_ficha: dict[str, str] = {}  # código de ficha -> fichero
        self.de_elemento: dict[str, str] = {}  # código de elemento -> fichero

    def cargar(self, raiz: Traversable) -> Indice:
        for fichero, bruto in self._ficheros(raiz, "normas"):
            self._anadir_norma(fichero, bruto)
        for fichero, bruto in self._ficheros(raiz, "fichas"):
            self._anadir_ficha(fichero, bruto)
        for norma in self.normas.values():
            self._comprobar_referencias_de_norma(norma)
        for ficha in self.fichas.values():
            self._comprobar_referencias_de_ficha(ficha)
        return Indice(
            normas=self.normas,
            fichas=self.fichas,
            elementos=self.elementos,
            alias=self._alias(),
        )

    @staticmethod
    def _ficheros(raiz: Traversable, carpeta: str) -> list[tuple[str, Any]]:
        directorio = raiz.joinpath(carpeta)
        if not directorio.is_dir():
            raise ErrorNormativa("DATOS_INVALIDOS", f"{carpeta}: falta la carpeta")
        rutas = sorted(
            (r for r in directorio.iterdir() if r.name.endswith(".json") and r.is_file()),
            key=lambda r: r.name,
        )
        leidos = []
        for ruta in rutas:
            fichero = f"{carpeta}/{ruta.name}"
            try:
                bruto = json.loads(
                    ruta.read_text(encoding="utf-8"),
                    object_pairs_hook=_sin_repetidas,
                    parse_constant=_sin_constantes,
                )
            except (OSError, ValueError) as exc:
                raise ErrorNormativa(
                    "DATOS_INVALIDOS", f"{fichero}: no es un JSON legible ({exc})"
                ) from exc
            leidos.append((fichero, bruto))
        return leidos

    def _anadir_norma(self, fichero: str, bruto: Any) -> None:
        lector = _Lector(fichero)
        norma = _leer_norma(lector, bruto)
        if norma.id in self.normas:
            raise lector.fallo("id", f"«{norma.id}» ya está en {self.de_norma[norma.id]}")
        self.normas[norma.id] = norma
        self.de_norma[norma.id] = fichero

    def _anadir_ficha(self, fichero: str, bruto: Any) -> None:
        lector = _Lector(fichero)
        ficha = _leer_ficha(lector, bruto)
        if ficha.codigo in self.fichas:
            raise lector.fallo(
                "codigo", f"la ficha «{ficha.codigo}» ya está en {self.de_ficha[ficha.codigo]}"
            )
        self.fichas[ficha.codigo] = ficha
        self.de_ficha[ficha.codigo] = fichero
        for elemento in ficha.elementos:
            if elemento.codigo in self.elementos:
                raise lector.fallo(
                    f"elementos[{elemento.codigo}].codigo",
                    f"el código ya está en {self.de_elemento[elemento.codigo]}",
                )
            self.elementos[elemento.codigo] = (ficha, elemento)
            self.de_elemento[elemento.codigo] = fichero

    def _existe(self, lector: _Lector, id_: str, campo: str) -> None:
        if id_.partition("#")[0] not in self.normas:
            raise lector.fallo(campo, f"la norma «{id_.partition('#')[0]}» no existe")

    def _comprobar_referencias_de_norma(self, norma: Norma) -> None:
        lector = _Lector(self.de_norma[norma.id])
        for campo in ("correcciones", "modifica", "modificada_por"):
            for i, id_ in enumerate(getattr(norma, campo)):
                self._existe(lector, id_, f"{campo}[{i}]")
        if norma.derogada_por is not None:
            self._existe(lector, norma.derogada_por, "derogada_por")

    def _comprobar_procedencia(self, lector: _Lector, procedencia: Procedencia, campo: str) -> None:
        self._existe(lector, procedencia.norma, f"{campo}.norma")
        for i, via in enumerate(procedencia.via):
            self._comprobar_procedencia(lector, via, f"{campo}.via[{i}]")

    def _comprobar_referencias_de_ficha(self, ficha: Ficha) -> None:
        lector = _Lector(self.de_ficha[ficha.codigo])
        for i, id_ in enumerate(ficha.normas):
            self._existe(lector, id_, f"normas[{i}]")
        propios = {e.codigo: e for e in ficha.elementos}
        for e in ficha.elementos:
            campo = f"elementos[{e.codigo}]"
            self._comprobar_procedencia(lector, e.procedencia, f"{campo}.procedencia")
            if e.padre is not None and e.padre not in propios:
                raise lector.fallo(f"{campo}.padre", f"«{e.padre}» no es un elemento de esta ficha")
            for nombre, codigos in e.relaciones.items():
                for i, codigo in enumerate(codigos):
                    if codigo not in self.elementos:
                        raise lector.fallo(
                            f"{campo}.relaciones.{nombre}[{i}]", f"«{codigo}» no existe"
                        )
            # Sin ciclos: subiendo por los padres se llega siempre a una raíz.
            visto = {e.codigo}
            actual = e.padre
            while actual is not None:
                if actual in visto:
                    raise lector.fallo(f"{campo}.padre", "los padres forman un ciclo")
                visto.add(actual)
                actual = propios[actual].padre

    def _alias(self) -> dict[str, str]:
        alias: dict[str, str] = {}
        for norma in self.normas.values():
            nombres = [f"{_NOMBRE_DEL_RANGO[norma.rango]} {norma.numero}"]
            if norma.rango == "real_decreto":
                nombres.append(f"rd {norma.numero}")
            nombres.extend(norma.citas)
            for nombre in nombres:
                clave = normalizar_cita(nombre)
                previo = alias.setdefault(clave, norma.id)
                if previo != norma.id:
                    raise _Lector(self.de_norma[norma.id]).fallo(
                        "citas", f"«{clave}» ya es la cita de {previo}"
                    )
        return alias
