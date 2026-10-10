"""Estado de la ventana de sesión: lo que ve el docente y lo que responde.

Hay dos caras sobre el mismo estado:

- ``PresenciaVentana``: la ``Presencia`` que usa ``sesion.abrir`` desde su
  hilo. Cada pregunta publica una pantalla y espera la respuesta del docente.
- ``Puente``: el objeto que pywebview expone a JavaScript (``js_api``). Solo
  tiene acciones del docente y solo recibe el número de la pantalla y
  respuestas simples (texto, sí o no, un índice): nunca rutas ni URL.

pywebview expone también los atributos públicos que sean objetos (y sus
métodos), así que en ``Puente`` todo lo interno empieza por ``_``.
"""

from __future__ import annotations

import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import estado, mensajes, rutas
from ..config import MAX_REALES
from ..publicacion import Aviso, ResumenPublicacion, ResumenSinPruebas
from ..sesion import SIN_PRUEBAS, CursoSesion

__all__ = ["PresenciaVentana", "Puente", "Ventana"]

MAX_REGISTRO = 200
MAX_TEXTO = 300

_SIN_RESPUESTA = object()
_INVALIDA = object()

# Los avisos que cierran la ventana: además de anotarse, dejan el texto de la
# pantalla final. Lo demás solo se anota.
_CIERRAN = frozenset({"AUTOPRUEBA_FALLIDA", "CANCELADA", "FALLO", "SESION_CERRADA"})


def _texto(valor: object) -> str:
    return mensajes.texto_seguro(valor, MAX_TEXTO)


def _password(respuesta: Any, _opciones: Any) -> Any:
    if respuesta is None:
        return None
    if isinstance(respuesta, str) and 0 < len(respuesta) <= 200:
        return respuesta
    return _INVALIDA


def _configurar(respuesta: Any, _opciones: Any) -> Any:
    if respuesta is None:
        return None
    if not isinstance(respuesta, dict):
        return _INVALIDA
    url, usuario = respuesta.get("url"), respuesta.get("usuario")
    if not isinstance(url, str) or not isinstance(usuario, str):
        return _INVALIDA
    if not 0 < len(url.strip()) <= MAX_TEXTO or not 0 < len(usuario.strip()) <= 100:
        return _INVALIDA
    return {"url": url.strip(), "usuario": usuario.strip()}


def _elegir_curso(respuesta: Any, opciones: Any) -> Any:
    if respuesta is None:
        return None
    if not isinstance(respuesta, dict):
        return _INVALIDA
    if respuesta.get("sin_curso") is True:
        return SIN_PRUEBAS if opciones.get("sin_pruebas") else _INVALIDA
    ids: list[int] = opciones["ids"]
    indice = respuesta.get("indice")
    if isinstance(indice, int) and not isinstance(indice, bool) and 0 <= indice < len(ids):
        return ids[indice]
    texto = respuesta.get("id")
    if isinstance(texto, str) and texto.strip().isdigit() and len(texto.strip()) <= 12:
        numero = int(texto.strip())
        if numero > 0 and numero != opciones["excluir"]:
            return numero
    return _INVALIDA


def _elegir_reales(respuesta: Any, opciones: Any) -> Any:
    """Casillas marcadas (índices, en orden) y/o ids escritos: de 1 a MAX_REALES, sin repetir."""
    if respuesta is None:
        return None
    if not isinstance(respuesta, dict):
        return _INVALIDA
    ids: list[int] = opciones["ids"]
    elegidos: list[int] = []
    indices = respuesta.get("indices", [])
    if not isinstance(indices, list):
        return _INVALIDA
    for indice in indices:
        if not isinstance(indice, int) or isinstance(indice, bool) or not 0 <= indice < len(ids):
            return _INVALIDA
        elegidos.append(ids[indice])
    texto = respuesta.get("ids", "")
    if not isinstance(texto, str) or len(texto) > 100:
        return _INVALIDA
    for trozo in texto.split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        if not trozo.isdigit() or len(trozo) > 12 or int(trozo) <= 0:
            return _INVALIDA
        elegidos.append(int(trozo))
    if (
        not 1 <= len(elegidos) <= MAX_REALES
        or len(set(elegidos)) != len(elegidos)
        or opciones["excluir"] in elegidos
    ):
        return _INVALIDA
    return elegidos


def _si_o_no(respuesta: Any, _opciones: Any) -> Any:
    return respuesta if isinstance(respuesta, bool) else _INVALIDA


_VALIDAR: dict[str, Callable[[Any, Any], Any]] = {
    "password": _password,
    "configurar": _configurar,
    "elegir_curso": _elegir_curso,
    "elegir_reales": _elegir_reales,
    "cursos": _si_o_no,
    "autoprueba": _si_o_no,
    "sin_pruebas": _si_o_no,
    "real": _si_o_no,
    "real_sin_pruebas": _si_o_no,
    "ampliar": _si_o_no,
    "cerrada": _si_o_no,
}


class Ventana:
    """Pantalla actual, pregunta pendiente y registro, con un cerrojo."""

    def __init__(
        self,
        carpeta: Path,
        *,
        abrir_url: Callable[[str], object] = webbrowser.open,
        dir_vistas: Path | None = None,
    ) -> None:
        self.carpeta = Path(carpeta).resolve()
        # Dónde escribe la sesión las vistas previas (sesion.crear_dir_vistas); sin él, la carpeta.
        self.dir_vistas = Path(dir_vistas).resolve() if dir_vistas is not None else None
        self.cerrar = threading.Event()  # el docente cerró la ventana
        self.motivo = ""  # último texto de cierre o de fallo, para la pantalla final
        self._abrir_url = abrir_url
        self._cerrojo = threading.Condition()
        self._numero = 0
        self._base: dict[str, Any] = {"tipo": "cargando"}
        self._pantalla: dict[str, Any] = {"numero": 0, "tipo": "cargando"}
        self._pregunta: str | None = None
        self._opciones: Any = None
        self._respuesta: Any = _SIN_RESPUESTA
        self._registro: list[str] = []
        self._anotadas = 0
        self._vistas: tuple[Path | None, ...] = ()

    def estado(self) -> dict:
        with self._cerrojo:
            return {
                "pantalla": dict(self._pantalla),
                "registro": list(self._registro),
                "anotadas": self._anotadas,
                "carpeta": _texto(self.carpeta),
            }

    def _poner(self, pantalla: dict) -> None:  # con el cerrojo tomado
        self._numero += 1
        self._pantalla = {**pantalla, "numero": self._numero}

    def mostrar(self, pantalla: dict) -> None:
        """Cambia la pantalla de fondo (la que se ve cuando no hay pregunta)."""
        with self._cerrojo:
            self._base = pantalla
            if self._pregunta is None:
                self._poner(pantalla)

    def anotar(self, texto: str) -> None:
        with self._cerrojo:
            self._registro.append(_texto(texto))
            del self._registro[:-MAX_REGISTRO]
            self._anotadas += 1

    def preguntar(self, pantalla: dict, *, opciones: Any = None, plazo: float | None = None) -> Any:
        """Enseña una pregunta y espera la respuesta; None si se cierra o vence el plazo."""
        with self._cerrojo:
            if self.cerrar.is_set():
                return None
            self._pregunta = pantalla["tipo"]
            self._opciones = opciones
            self._respuesta = _SIN_RESPUESTA
            self._poner(pantalla)
            limite = None if plazo is None else time.monotonic() + plazo
            while self._respuesta is _SIN_RESPUESTA and not self.cerrar.is_set():
                restante = 0.5 if limite is None else min(0.5, limite - time.monotonic())
                if restante <= 0:
                    break
                self._cerrojo.wait(restante)
            respuesta = None if self._respuesta is _SIN_RESPUESTA else self._respuesta
            self._pregunta = None
            self._opciones = None
            self._respuesta = _SIN_RESPUESTA
            self._poner(self._base)
            return respuesta

    def responder(self, numero: Any, respuesta: Any) -> bool:
        with self._cerrojo:
            if self._pregunta is None or numero != self._pantalla["numero"]:
                return False
            if self._respuesta is not _SIN_RESPUESTA:
                return False
            valor = _VALIDAR[self._pregunta](respuesta, self._opciones)
            if valor is _INVALIDA:
                return False
            self._respuesta = valor
            self._cerrojo.notify_all()
            return True

    def preparar_vistas(self, vistas: tuple[Path | None, ...]) -> None:
        with self._cerrojo:
            self._vistas = vistas

    def abrir_vista(self, numero: Any, indice: Any) -> bool:
        """Abre en el navegador la vista previa ``indice`` de la tarjeta de real."""
        with self._cerrojo:
            if self._pregunta != "real" or numero != self._pantalla["numero"]:
                return False
            if not isinstance(indice, int) or isinstance(indice, bool):
                return False
            if not 0 <= indice < len(self._vistas):
                return False
            elegida = self._vistas[indice]
        if elegida is None:
            return False
        vista = Path(elegida).resolve()
        raiz = (
            self.dir_vistas if self.dir_vistas is not None else self.carpeta / rutas.CARPETA_TRABAJO
        )
        if not vista.is_relative_to(raiz / estado.CARPETA_PREVIEW) or not vista.is_file():
            return False
        self._abrir_url(vista.as_uri())
        return True

    def cerrar_todo(self) -> None:
        """El docente cerró la ventana: corta la sesión y desbloquea las preguntas."""
        self.cerrar.set()
        with self._cerrojo:
            self._cerrojo.notify_all()


class PresenciaVentana:
    """La presencia de la ventana de sesión: cumple ``publicacion.Presencia``."""

    def __init__(self, ventana: Ventana) -> None:
        self._ventana = ventana
        self._cursos: list[dict] = []  # los confirmados, para la pantalla «abierta»

    def pedir_password(self, servidor: str, usuario: str) -> str | None:
        respuesta = self._ventana.preguntar(
            {"tipo": "password", "servidor": _texto(servidor), "usuario": _texto(usuario)}
        )
        if respuesta is not None:
            self._ventana.mostrar({"tipo": "conectando"})
        return respuesta

    def elegir_curso(self, entorno: str, cursos: list[dict], excluir: int | None) -> int | None:
        opciones = [curso for curso in cursos if curso["id"] != excluir]
        permite_sin = entorno == "pruebas"
        return self._ventana.preguntar(
            {
                "tipo": "elegir_curso",
                "entorno": entorno,
                "para_que": mensajes.PARA_QUE.get(entorno, ""),
                "opciones": [mensajes.texto_seguro(curso["nombre"], 80) for curso in opciones],
                "sin_pruebas": permite_sin,
            },
            opciones={
                "ids": [curso["id"] for curso in opciones],
                "excluir": excluir,
                "sin_pruebas": permite_sin,
            },
        )

    def elegir_cursos_reales(self, cursos: list[dict], excluir: int | None) -> list[int] | None:
        opciones = [curso for curso in cursos if curso["id"] != excluir]
        return self._ventana.preguntar(
            {
                "tipo": "elegir_reales",
                "para_que": mensajes.PARA_QUE.get("real", ""),
                "maximo": MAX_REALES,
                "opciones": [mensajes.texto_seguro(curso["nombre"], 80) for curso in opciones],
            },
            opciones={"ids": [curso["id"] for curso in opciones], "excluir": excluir},
        )

    def confirmar_cursos(self, cursos: list[CursoSesion]) -> bool:
        filas = [
            {
                "entorno": curso.entorno,
                "curso": mensajes.describir_curso(curso.id, curso.nombre),
                "aviso": mensajes.AVISO_AJENO if curso.ajeno else "",
            }
            for curso in cursos
        ]
        self._cursos = filas
        sin_pruebas = not any(curso.entorno == "pruebas" for curso in cursos)
        return (
            self._ventana.preguntar(
                {
                    "tipo": "cursos",
                    "cursos": filas,
                    "sin_pruebas": sin_pruebas,
                    "aviso": mensajes.SIN_PRUEBAS_AVISO,
                }
            )
            is True
        )

    def confirmar_autoprueba(self) -> bool:
        return (
            self._ventana.preguntar({"tipo": "autoprueba", "texto": mensajes.AUTOPRUEBA_TEXTO})
            is True
        )

    def confirmar_sin_pruebas(self) -> bool:
        return (
            self._ventana.preguntar({"tipo": "sin_pruebas", "aviso": mensajes.SIN_PRUEBAS_AVISO})
            is True
        )

    def confirmar_real(self, resumen: ResumenPublicacion) -> bool:
        detalle = mensajes.detalle_real(resumen)
        pantalla = {
            "tipo": "real",
            "solo_fechas": detalle.solo_fechas,
            "curso": detalle.curso,
            "posicion": detalle.posicion,
            "total": detalle.total,
            "aviso_calendario": detalle.aviso_calendario or "",
            "documentos": [
                {
                    "titulo": doc.titulo,
                    "lineas": list(doc.lineas),
                    "vista": doc.vista_previa is not None,
                }
                for doc in detalle.documentos
            ],
            "finales": list(detalle.finales),
        }
        self._ventana.preparar_vistas(tuple(doc.vista_previa for doc in resumen.documentos))
        try:
            return self._ventana.preguntar(pantalla) is True
        finally:
            self._ventana.preparar_vistas(())

    def confirmar_real_sin_pruebas(self, resumen: ResumenSinPruebas) -> bool:
        detalle = mensajes.detalle_corto(resumen)
        pantalla = {
            "tipo": "real_sin_pruebas",
            "curso": detalle.curso,
            "posicion": detalle.posicion,
            "total": detalle.total,
            "aviso": detalle.aviso,
            "documentos": [
                {"titulo": doc.titulo, "lineas": list(doc.lineas)} for doc in detalle.documentos
            ],
            "finales": list(detalle.finales),
        }
        return self._ventana.preguntar(pantalla) is True

    def ofrecer_ampliacion(self, minutos: int, plazo: float) -> bool:
        return self._ventana.preguntar({"tipo": "ampliar", "minutos": minutos}, plazo=plazo) is True

    def informar(self, aviso: Aviso) -> None:
        lineas = mensajes.lineas_de_aviso(aviso)
        if aviso.codigo == "SESION_ABIERTA":
            self._ventana.mostrar(
                {"tipo": "abierta", "texto": lineas[0].texto, "cursos": self._cursos}
            )
        if aviso.codigo in _CIERRAN:
            self._ventana.motivo = " ".join(linea.texto for linea in lineas)
        for linea in lineas:
            self._ventana.anotar(linea.texto)


class Puente:
    """Lo único que JavaScript puede llamar; todo lo interno empieza por «_»."""

    def __init__(self, ventana: Ventana, *, al_cerrar: Callable[[], None]) -> None:
        self._ventana = ventana
        self._al_cerrar = al_cerrar
        self._url_actual: Callable[[], str | None] = lambda: None

    def _enlazar(self, url_actual: Callable[[], str | None]) -> None:
        """Tras crear la ventana: para saber si sigue en nuestra página."""
        self._url_actual = url_actual

    def _en_nuestra_pagina(self) -> bool:
        # pywebview no da URL a la página cargada con html=; si la hay, se navegó fuera.
        return self._url_actual() is None

    def estado(self) -> dict:
        if not self._en_nuestra_pagina():
            return {
                "pantalla": {"numero": -1, "tipo": "cerrada", "texto": ""},
                "registro": [],
                "anotadas": 0,
                "carpeta": "",
            }
        return self._ventana.estado()

    def responder(self, numero: Any, respuesta: Any) -> bool:
        return self._en_nuestra_pagina() and self._ventana.responder(numero, respuesta)

    def vista_previa(self, numero: Any, indice: Any) -> bool:
        return self._en_nuestra_pagina() and self._ventana.abrir_vista(numero, indice)

    def cerrar_ventana(self) -> None:
        self._al_cerrar()
