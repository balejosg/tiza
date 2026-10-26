"""Modelo del panel de escritorio: lo que ve el docente y lo que responde.

Sin interfaz gráfica y sin pywebview: aquí solo hay estado. Tres piezas sobre él:

- ``Panel``: la pantalla actual, el registro de avisos y el cierre, protegidos por un
  cerrojo para hablar entre hilos.
- ``PresenciaPanel``: la ``Presencia`` que usan ``sesion.abrir`` y ``arranque.preparar``
  desde su hilo de trabajo. Cada pregunta publica una pantalla y bloquea hasta la respuesta
  o hasta el cierre del panel (que cuenta como negativo).
- ``Puente``: lo que será el ``js_api`` de la ventana. Solo acciones; todo lo interno
  empieza por ``_`` (pywebview expone también los atributos públicos que sean objetos).

Las operaciones de ventana (``on_top``, ``restore``, ``show``, ``destroy``, el diálogo de
carpeta) nunca van dentro de una llamada del ``js_api``: cuelgan la ventana. Este módulo no
toca ventanas: el ``Puente`` solo deja peticiones (``buscar_carpeta``, ``terminar``) y la capa
de ventana las atiende en su propio hilo con ``Panel.esperar_cambio``. La acreditación del
aula (cookies) nunca pasa por el ``Puente``: entra por ``abrir_login``, un callable inyectado.
Las rutas reales de las carpetas recientes se quedan en el ``Panel``: JavaScript solo ve el
índice y el nombre visible, y la carpeta que sale del diálogo la valida el ``Panel``.
"""

from __future__ import annotations

import dataclasses
import threading
import time
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .. import config, mensajes, publicar
from ..config import MAX_REALES
from ..publicacion import (
    Aviso,
    ResumenAislamiento,
    ResumenCalificador,
    ResumenCopia,
    ResumenOrden,
    ResumenPublicacion,
    ResumenSinPruebas,
    ResumenSobrescribir,
)
from ..sesion import AVISO_MINUTOS, SIN_PRUEBAS, CursoSesion
from . import recientes

__all__ = [
    "MAX_REGISTRO",
    "PASOS_DE_ARRANQUE",
    "RETARDO_RESPUESTA",
    "TIPOS_DE_PANTALLA",
    "Bloque",
    "Opcion",
    "Panel",
    "Pantalla",
    "PresenciaPanel",
    "Puente",
]

MAX_REGISTRO = 200
MAX_TEXTO = 300
MAX_URL = 300
MAX_USUARIO = 100
MAX_ID = 10**12

# Un clic que llega antes no confirma nada: el primero sobre un panel sin foco solo lo
# activa, y un clic que ya venía en camino no es una decisión.
RETARDO_RESPUESTA = 0.7

TIPOS_DE_PANTALLA = frozenset(
    {
        "reposo",
        "confirmar",
        "elegir_curso",
        "elegir_cursos_reales",
        "configurar",
        "entrando",
        "ampliar",
        "carpeta",
        "final",
    }
)

# Los pasos del arranque que enseña el panel, en orden. ``fijar_paso`` rechaza otros.
PASOS_DE_ARRANQUE = ("carpeta", "aula", "cursos", "sesion")

# Los avisos que además dejan su texto como pantalla de reposo.
_CIERRAN = frozenset({"AUTOPRUEBA_FALLIDA", "CANCELADA", "FALLO", "SESION_CERRADA"})

_INVALIDA = object()


def _t(valor: object, maximo: int = MAX_TEXTO) -> str:
    return mensajes.texto_seguro(valor, maximo)


@dataclass(frozen=True)
class Bloque:
    """Un documento (o sección) de una confirmación; ``vista`` indexa su vista previa."""

    titulo: str
    lineas: tuple[str, ...] = ()
    vista: int | None = None


@dataclass(frozen=True)
class Opcion:
    indice: int
    texto: str
    pista: str = ""  # solo cuando dos recientes comparten nombre visible


@dataclass(frozen=True)
class Pantalla:
    """Lo que enseña el panel. Solo datos serializables a JSON, ya saneados."""

    numero: int
    tipo: str
    titulo: str = ""
    lineas: tuple[str, ...] = ()
    bloques: tuple[Bloque, ...] = ()
    pregunta: str = ""
    opciones: tuple[Opcion, ...] = ()
    permite_sin_curso: bool = False
    texto_sin_curso: str = ""
    permite_id: bool = False  # sin lista de cursos: se puede escribir el id (un número)
    maximo: int = 0
    plazo: float = 0.0
    error: str = ""
    servidor: str = ""
    url: str = ""
    usuario: str = ""
    texto_si: str = ""  # vacío = «Sí»
    texto_no: str = ""  # vacío = «No»
    riesgo: str = ""  # "", "real" o "peligro": decide el estilo de los botones

    def __post_init__(self) -> None:
        if self.tipo not in TIPOS_DE_PANTALLA:
            raise ValueError(f"tipo de pantalla desconocido: {self.tipo}")
        if self.riesgo not in ("", "real", "peligro"):
            raise ValueError(f"riesgo de pantalla desconocido: {self.riesgo}")

    def a_dict(self) -> dict:
        return dataclasses.asdict(self)


def _bool(respuesta: Any, _opciones: Any) -> Any:
    return respuesta if isinstance(respuesta, bool) else _INVALIDA


def _entero(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _id_valido(valor: Any, excluir: int | None) -> bool:
    return _entero(valor) and 0 < valor <= MAX_ID and valor != excluir


def _elegir(respuesta: Any, opciones: dict) -> Any:
    ids: list[int] = opciones["ids"]
    if _entero(respuesta):
        return ids[respuesta] if 0 <= respuesta < len(ids) else _INVALIDA
    if isinstance(respuesta, dict) and len(respuesta) == 1:
        if respuesta.get("sin_curso") is True and opciones["sin_curso"]:
            return SIN_PRUEBAS
        if opciones["permite_id"] and _id_valido(respuesta.get("id"), opciones["excluir"]):
            return respuesta["id"]
    return _INVALIDA


def _elegir_reales(respuesta: Any, opciones: dict) -> Any:
    ids: list[int] = opciones["ids"]
    if isinstance(respuesta, dict) and set(respuesta) == {"ids"} and opciones["permite_id"]:
        elegidos = respuesta["ids"]
        if not isinstance(elegidos, list) or not all(
            _id_valido(i, opciones["excluir"]) for i in elegidos
        ):
            return _INVALIDA
    elif isinstance(respuesta, list):
        if not all(_entero(i) and 0 <= i < len(ids) for i in respuesta):
            return _INVALIDA
        elegidos = [ids[i] for i in respuesta]
        if len(set(respuesta)) != len(respuesta):
            return _INVALIDA
    else:
        return _INVALIDA
    if not 1 <= len(elegidos) <= MAX_REALES or len(set(elegidos)) != len(elegidos):
        return _INVALIDA
    return list(elegidos)


def _configurar(respuesta: Any, _opciones: Any) -> Any:
    if not isinstance(respuesta, dict) or set(respuesta) != {"url", "usuario"}:
        return _INVALIDA
    url, usuario = respuesta["url"], respuesta["usuario"]
    if not isinstance(url, str) or not isinstance(usuario, str):
        return _INVALIDA
    url, usuario = url.strip(), usuario.strip()
    if not 0 < len(url) <= MAX_URL or not 0 < len(usuario) <= MAX_USUARIO:
        return _INVALIDA
    return (url, usuario)


class Panel:
    """Pantalla actual, pregunta pendiente, registro y cierre, con un cerrojo."""

    def __init__(
        self,
        *,
        reloj: Callable[[], float] = time.monotonic,
        ahora: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._reloj = reloj
        self._ahora = ahora
        self._cv = threading.Condition()
        self._cierre = threading.Event()
        self._numero = 0
        self._base = Pantalla(0, "reposo")
        self._pantalla = self._base
        self._publicada = reloj()
        self._validar: Callable[[Any], Any] | None = None
        self._respuesta: Any = _INVALIDA
        self._vistas: tuple[Path | None, ...] = ()
        self._registro: list[tuple[str, bool, str]] = []
        self._carpeta = ""
        self._servidor = ""
        self._sesion_abierta = False
        self._caduca = ""
        self._paso = ""
        self._rutas_carpeta: list[Path] = []
        self._dialogo = False  # el docente pidió el diálogo de carpeta y nadie lo ha atendido
        self._dialogo_en_curso = False
        self._salir = False  # el docente pidió cerrar la sesión

    # --- lo que lee la capa de ventana y el Puente ---

    @property
    def cerrado(self) -> bool:
        return self._cierre.is_set()

    @property
    def pregunta_pendiente(self) -> bool:
        """¿Hay una pregunta esperando respuesta? (la ventana se pone delante y parpadea)."""
        with self._cv:
            return self._validar is not None

    @property
    def dialogo_pedido(self) -> bool:
        """¿Pidió el docente el diálogo de carpeta y falta atenderlo? (hilo de la ventana)."""
        with self._cv:
            return self._dialogo

    @property
    def salida_pedida(self) -> bool:
        """¿Pidió el docente cerrar la sesión? (el hilo de la ventana la destruye)."""
        with self._cv:
            return self._salir

    def estado(self) -> dict:
        with self._cv:
            return {
                "pantalla": self._pantalla.a_dict(),
                "registro": [{"texto": t, "error": e, "hora": h} for t, e, h in self._registro],
                "cerrado": self._cierre.is_set(),
                "carpeta": self._carpeta,
                "servidor": self._servidor,
                "sesion_abierta": self._sesion_abierta,
                "caduca": self._caduca,
                "aviso_minutos": AVISO_MINUTOS,
                "paso": self._paso,
                "pregunta": self._validar is not None,
            }

    def esperar_cambio(self, ultimo_numero: int, timeout: float) -> int:
        """Espera a que haya algo que atender: otra pantalla que la ``ultimo_numero``, un
        diálogo o una salida pedidos, o el cierre del panel. Devuelve el número actual."""
        with self._cv:
            self._cv.wait_for(
                lambda: (
                    self._numero != ultimo_numero
                    or self._cierre.is_set()
                    or self._dialogo
                    or self._salir
                ),
                timeout,
            )
            return self._numero

    def fijar_carpeta(self, nombre: str) -> None:
        with self._cv:
            self._carpeta = _t(nombre, 100)

    def fijar_servidor(self, servidor: str) -> None:
        with self._cv:
            self._servidor = _t(servidor, 100)

    def fijar_caducidad(self, caduca: datetime | None) -> None:
        """Cuándo caduca la sesión abierta, en ISO 8601 UTC (vacío si no hay sesión)."""
        with self._cv:
            self._caduca = _iso_utc(caduca)
            self._cv.notify_all()

    def fijar_paso(self, nombre: str) -> None:
        """El paso del arranque que se está dando (``""`` lo oculta)."""
        if nombre not in ("", *PASOS_DE_ARRANQUE):
            raise ValueError(f"paso de arranque desconocido: {nombre}")
        with self._cv:
            self._paso = nombre
            self._cv.notify_all()

    def reposo(self, titulo: str, lineas: Sequence[str] = ()) -> None:
        """Deja una pantalla de reposo saneada y marca la sesión como cerrada."""
        self.marcar_sesion(False)
        self.fijar_paso("")
        self.mostrar(Pantalla(0, "reposo", titulo=_t(titulo), lineas=_lineas(lineas)))

    def marcar_sesion(self, abierta: bool) -> None:
        """La sesión está abierta (se enseña «Cerrar la sesión») o ya no lo está."""
        with self._cv:
            self._sesion_abierta = bool(abierta)
            if not abierta:
                self._caduca = ""
            self._cv.notify_all()

    def nueva_vuelta(self) -> None:
        """Limpia lo que dependía de la vuelta anterior y separa el registro."""
        with self._cv:
            self._carpeta = ""
            self._servidor = ""
            self._sesion_abierta = False
            self._caduca = ""
            self._paso = ""
            self._rutas_carpeta = []
            self._anotar_con_cerrojo(mensajes.SEPARADOR_NUEVA_SESION)
            self._cv.notify_all()

    def cerrar(self) -> None:
        """El docente cierra el panel: desbloquea toda pregunta (como un no)."""
        self._cierre.set()
        with self._cv:
            self._cv.notify_all()

    def responder(self, numero: Any, respuesta: Any) -> bool:
        with self._cv:
            if self._validar is None or not _entero(numero) or numero != self._numero:
                return False
            if self._respuesta is not _INVALIDA:
                return False
            if self._reloj() - self._publicada < RETARDO_RESPUESTA:
                return False
            try:
                valor = self._validar(respuesta)
            except (TypeError, ValueError, KeyError, IndexError):
                return False
            if valor is _INVALIDA:
                return False
            self._respuesta = valor
            self._cv.notify_all()
            return True

    def _atendible(self, numero: Any) -> bool:  # con el cerrojo tomado
        """¿Es ``numero`` la pantalla actual y ha pasado el retardo? (las mismas reglas que
        una respuesta, para peticiones que no son respuestas)."""
        return (
            _entero(numero)
            and numero == self._numero
            and self._reloj() - self._publicada >= RETARDO_RESPUESTA
        )

    def pedir_dialogo(self, numero: Any) -> bool:
        """El docente pide el diálogo de carpeta (solo con la pantalla ``carpeta`` pendiente).

        No abre nada: deja la petición para el hilo de la ventana (``atender_dialogo``).
        """
        with self._cv:
            if (
                self._validar is None
                or self._pantalla.tipo != "carpeta"
                or not self._atendible(numero)
                or self._dialogo
                or self._dialogo_en_curso
            ):
                return False
            self._dialogo = True
            self._cv.notify_all()
            return True

    def atender_dialogo(self, elegir: Callable[[], object]) -> bool:
        """Atiende la petición de diálogo: ``elegir()`` lo abre y devuelve la ruta (o None).

        Lo llama el hilo de la ventana. La carpeta elegida solo vale si es una ruta absoluta
        que existe; entonces responde a la pregunta pendiente. Devuelve si se respondió.
        """
        with self._cv:
            if not self._dialogo:
                return False
            self._dialogo = False
            self._dialogo_en_curso = True
        try:
            elegida = elegir()
        finally:
            with self._cv:
                self._dialogo_en_curso = False
        carpeta = recientes.carpeta_valida(elegida)
        if carpeta is None:
            return False
        with self._cv:
            if self._validar is None or self._pantalla.tipo != "carpeta":
                return False
            try:
                valor = self._validar(("dialogo", carpeta))
            except (TypeError, ValueError, KeyError, IndexError):
                return False
            if valor is _INVALIDA or self._respuesta is not _INVALIDA:
                return False
            self._respuesta = valor
            self._cv.notify_all()
            return True

    def pedir_salida(self, numero: Any) -> bool:
        """El docente pide cerrar la sesión: marca la salida y cierra el panel (todo lo
        pendiente cuenta como un no). La ventana la destruye el hilo de la ventana."""
        with self._cv:
            if not self._atendible(numero):
                return False
        self.salir()
        return True

    def salir(self) -> None:
        """Cierra el panel por decisión propia (sin pregunta): la ventana la destruye el hilo
        de la ventana y la sesión se recoge. Lo usa el flujo tras lanzar la actualización."""
        with self._cv:
            self._salir = True
            self._cv.notify_all()
        self.cerrar()

    def esperar_carpeta(self, usadas: Sequence[Path] = ()) -> Path | None:
        """Pregunta la carpeta de la asignatura; None si se cierra el panel.

        Las ``usadas`` se ofrecen por índice y nombre visible; sus rutas se quedan aquí.
        La respuesta es ``("reciente", índice)`` (la da el ``Puente``) o ``("dialogo", ruta)``
        (la da ``atender_dialogo``): JSON nunca produce una tupla, así que
        ``Puente.responder`` no puede contestar esta pantalla.
        """
        rutas = [Path(r) for r in usadas][: recientes.MAXIMO]

        def validar(respuesta: Any) -> Any:
            if not isinstance(respuesta, tuple) or len(respuesta) != 2:
                return _INVALIDA
            tipo, valor = respuesta
            if tipo == "reciente" and _entero(valor) and 0 <= valor < len(rutas):
                return recientes.carpeta_valida(str(rutas[valor])) or _INVALIDA
            if tipo == "dialogo" and isinstance(valor, Path):
                return valor
            return _INVALIDA

        pantalla = Pantalla(
            0,
            "carpeta",
            titulo="Elige la carpeta de la asignatura",
            lineas=_lineas(["Aquí trabajará tu asistente. Elige una reciente o busca otra."]),
            opciones=_opciones_de_carpetas(rutas),
        )
        with self._cv:
            self._rutas_carpeta = rutas
        try:
            return self.preguntar(pantalla, validar)
        finally:
            with self._cv:
                self._rutas_carpeta = []

    def quitar_reciente(self, numero: Any, indice: Any) -> bool:
        """Quita una reciente de la lista y vuelve a publicar la pantalla sin ella.

        El índice es el de la pantalla actual (nunca una ruta); la ruta real no sale del Panel.
        """
        with self._cv:
            if (
                self._validar is None
                or self._pantalla.tipo != "carpeta"
                or not self._atendible(numero)
                or not _entero(indice)
                or not 0 <= indice < len(self._rutas_carpeta)
            ):
                return False
            carpeta = self._rutas_carpeta.pop(indice)
            nueva = dataclasses.replace(
                self._pantalla, opciones=_opciones_de_carpetas(self._rutas_carpeta)
            )
            self._publicar(nueva)
        recientes.quitar(carpeta)
        return True

    def vista(self, numero: Any, indice: Any) -> Path | None:
        """La vista previa ``indice`` de la pantalla actual, que fijó tiza; None si no hay."""
        with self._cv:
            if self._validar is None or not _entero(numero) or numero != self._numero:
                return None
            if not _entero(indice) or not 0 <= indice < len(self._vistas):
                return None
            elegida = self._vistas[indice]
        if elegida is None or not Path(elegida).is_file():
            return None
        return Path(elegida).resolve()

    # --- lo que escribe la presencia ---

    def _publicar(self, pantalla: Pantalla) -> None:  # con el cerrojo tomado
        self._numero += 1
        self._pantalla = dataclasses.replace(pantalla, numero=self._numero)
        self._publicada = self._reloj()
        self._cv.notify_all()

    def mostrar(self, pantalla: Pantalla) -> None:
        """Cambia la pantalla de fondo (la que se ve cuando no se pregunta nada)."""
        with self._cv:
            self._base = pantalla
            if self._validar is None:
                self._publicar(pantalla)

    def _anotar_con_cerrojo(self, texto: str, error: bool = False) -> None:
        self._registro.append((_t(texto), error, self._ahora().strftime("%H:%M")))
        del self._registro[:-MAX_REGISTRO]

    def anotar(self, texto: str, error: bool = False) -> None:
        with self._cv:
            self._anotar_con_cerrojo(texto, error)
            self._cv.notify_all()

    def preguntar(
        self,
        pantalla: Pantalla,
        validar: Callable[[Any], Any],
        *,
        vistas: tuple[Path | None, ...] = (),
        plazo: float | None = None,
        reloj: Callable[[], float] | None = None,
    ) -> Any:
        """Publica la pantalla y espera una respuesta válida; None si se cierra o vence el plazo."""
        reloj = reloj or self._reloj
        with self._cv:
            if self._cierre.is_set():
                return None
            self._validar = validar
            self._respuesta = _INVALIDA
            self._vistas = vistas
            self._publicar(pantalla)
            limite = None if plazo is None else reloj() + plazo
            while self._respuesta is _INVALIDA and not self._cierre.is_set():
                resto = 0.05 if limite is None else min(0.05, limite - reloj())
                if resto <= 0:
                    break
                self._cv.wait(resto)
            respuesta = None if self._respuesta is _INVALIDA else self._respuesta
            self._validar = None
            self._respuesta = _INVALIDA
            self._vistas = ()
            self._publicar(self._base)
            return respuesta

    def preguntar_final(self) -> bool:
        """Ofrece volver a empezar sobre la pantalla de reposo actual; True si lo pide."""
        with self._cv:
            base = self._base
        pantalla = dataclasses.replace(
            base,
            tipo="final",
            texto_si=mensajes.VOLVER_A_EMPEZAR,
        )
        return self.preguntar(pantalla, lambda r: _bool(r, None)) is True


def _opciones_de_carpetas(rutas: Sequence[Path]) -> tuple[Opcion, ...]:
    return tuple(
        Opcion(i, texto, pista) for i, (texto, pista) in enumerate(recientes.etiquetas(rutas))
    )


def _lineas(*grupos: Sequence[str | None]) -> tuple[str, ...]:
    return tuple(_t(linea) for grupo in grupos for linea in grupo if linea is not None)


def _iso_utc(caduca: datetime | None) -> str:
    if caduca is None:
        return ""
    if caduca.tzinfo is None:
        caduca = caduca.replace(tzinfo=UTC)
    return caduca.astimezone(UTC).isoformat()


def _servidor(url: str) -> str:
    try:
        return _t(urlsplit(url).hostname or url, 100)
    except ValueError:
        return _t(url, 100)


class PresenciaPanel:
    """La presencia del panel: cumple ``publicacion.Presencia``.

    ``abrir_login(url)``: lo inyecta la capa de ventana; abre la ventana de entrada al aula
    en el mismo proceso y devuelve la ``publicar.Acreditacion`` (o None si se cierra). Sin él,
    ``acreditar`` devuelve None.
    """

    def __init__(
        self,
        panel: Panel,
        *,
        abrir_login: Callable[[str], publicar.Acreditacion | None] | None = None,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._panel = panel
        self._abrir_login = abrir_login
        self._reloj = reloj
        self.sin_entrar = False  # ¿se pidió entrar en el aula y la acreditación no llegó?

    # --- helpers ---

    def _si(
        self,
        titulo: str,
        lineas: Sequence[str],
        pregunta: str,
        *,
        bloques: tuple[Bloque, ...] = (),
        vistas: tuple[Path | None, ...] = (),
        plazo: float | None = None,
        tipo: str = "confirmar",
        texto_si: str = "",
        texto_no: str = "",
        riesgo: str = "",
    ) -> bool:
        pantalla = Pantalla(
            0,
            tipo,
            titulo=_t(titulo),
            lineas=_lineas(lineas),
            bloques=bloques,
            pregunta=_t(pregunta),
            plazo=plazo or 0.0,
            texto_si=_t(texto_si),
            texto_no=_t(texto_no),
            riesgo=riesgo,
        )
        respuesta = self._panel.preguntar(
            pantalla, lambda r: _bool(r, None), vistas=vistas, plazo=plazo, reloj=self._reloj
        )
        return respuesta is True

    # --- acreditación y cursos ---

    def acreditar(self, url: str, usuario: str) -> publicar.Acreditacion | None:
        servidor = _servidor(url)
        self._panel.fijar_paso("aula")
        self._panel.fijar_servidor(servidor)
        self._panel.mostrar(
            Pantalla(
                0,
                "entrando",
                titulo="Entrar en el aula",
                lineas=_lineas(
                    [
                        f"Se abre una ventana con la página de entrada de {servidor}. "
                        "Entra como siempre: tiza no verá tu contraseña.",
                    ]
                ),
                servidor=servidor,
                usuario=_t(usuario, MAX_USUARIO),
            )
        )
        self.sin_entrar = True
        if self._abrir_login is None or self._panel.cerrado:
            return None
        try:
            acreditacion = self._abrir_login(url)
        finally:
            self._panel.mostrar(Pantalla(0, "reposo", titulo="Conectando…"))
        self.sin_entrar = acreditacion is None  # la ventana se cerró o pasó el tiempo
        return acreditacion

    def elegir_curso(self, entorno: str, cursos: list[dict], excluir: int | None) -> int | None:
        self._panel.fijar_paso("cursos")
        validos = [curso for curso in cursos if curso["id"] != excluir]
        sin_curso = entorno == "pruebas"
        pantalla = Pantalla(
            0,
            "elegir_curso",
            titulo=_t(f"¿Cuál es tu curso de {entorno.upper()}?"),
            lineas=_lineas([mensajes.PARA_QUE.get(entorno)]),
            opciones=tuple(Opcion(i, _t(c["nombre"], 80)) for i, c in enumerate(validos)),
            permite_sin_curso=sin_curso,
            texto_sin_curso=mensajes.SIN_CURSO_PRUEBAS_OPCION if sin_curso else "",
            permite_id=not validos,
        )
        opciones = {
            "ids": [c["id"] for c in validos],
            "sin_curso": sin_curso,
            "permite_id": not validos,
            "excluir": excluir,
        }
        return self._panel.preguntar(pantalla, lambda r: _elegir(r, opciones), reloj=self._reloj)

    def elegir_cursos_reales(self, cursos: list[dict], excluir: int | None) -> list[int] | None:
        self._panel.fijar_paso("cursos")
        validos = [curso for curso in cursos if curso["id"] != excluir]
        pantalla = Pantalla(
            0,
            "elegir_cursos_reales",
            titulo=_t("¿Cuáles son tus cursos REALES?"),
            lineas=_lineas([mensajes.PARA_QUE["real"], f"Hasta {MAX_REALES}."]),
            opciones=tuple(Opcion(i, _t(c["nombre"], 80)) for i, c in enumerate(validos)),
            maximo=MAX_REALES,
            permite_id=not validos,
        )
        opciones = {
            "ids": [c["id"] for c in validos],
            "permite_id": not validos,
            "excluir": excluir,
        }
        return self._panel.preguntar(
            pantalla, lambda r: _elegir_reales(r, opciones), reloj=self._reloj
        )

    def confirmar_cursos(self, cursos: list[CursoSesion]) -> bool:
        self._panel.fijar_paso("cursos")
        return self._si(
            "Abrir la sesión",
            mensajes.lineas_de_cursos(cursos),
            mensajes.PREGUNTA_CURSOS,
            **mensajes.rotulos("confirmar_cursos"),
        )

    def confirmar_autoprueba(self) -> bool:
        return self._si(
            "Autoprueba",
            [mensajes.AUTOPRUEBA_TEXTO],
            mensajes.PREGUNTA_AUTOPRUEBA,
            **mensajes.rotulos("confirmar_autoprueba"),
        )

    def confirmar_sin_pruebas(self) -> bool:
        return self._si(
            "Sin curso de pruebas",
            [mensajes.SIN_PRUEBAS_AVISO],
            mensajes.PREGUNTA_SIN_PRUEBAS,
            **mensajes.rotulos("confirmar_sin_pruebas"),
        )

    # --- confirmaciones de real ---

    def confirmar_real(self, resumen: ResumenPublicacion) -> bool:
        detalle = mensajes.detalle_real(resumen)
        bloques = tuple(
            Bloque(
                _t(doc.titulo),
                _lineas(doc.lineas),
                indice if doc.vista_previa is not None else None,
            )
            for indice, doc in enumerate(detalle.documentos)
        )
        lineas = _lineas(
            [mensajes.cabecera_de_curso(detalle.posicion, detalle.total, detalle.curso)],
            [detalle.aviso_calendario],
            detalle.finales,
            [mensajes.linea_destino("real", resumen.curso, resumen.nombre_curso)],
        )
        return self._si(
            detalle.encabezado,
            lineas,
            mensajes.PREGUNTA_DESTINO,
            bloques=bloques,
            vistas=tuple(doc.vista_previa for doc in detalle.documentos),
            **mensajes.rotulos("confirmar_real"),
        )

    def confirmar_real_sin_pruebas(self, resumen: ResumenSinPruebas) -> bool:
        detalle = mensajes.detalle_corto(resumen)
        bloques = tuple(Bloque(_t(d.titulo), _lineas(d.lineas)) for d in detalle.documentos)
        lineas = _lineas(
            [mensajes.cabecera_de_curso(detalle.posicion, detalle.total, detalle.curso)],
            [detalle.aviso],
            detalle.finales,
            [mensajes.linea_destino("real", resumen.curso, resumen.nombre_curso)],
        )
        return self._si(
            detalle.encabezado,
            lineas,
            mensajes.PREGUNTA_DESTINO,
            bloques=bloques,
            **mensajes.rotulos("confirmar_real_sin_pruebas"),
        )

    def confirmar_orden(self, resumen: ResumenOrden) -> bool:
        detalle = mensajes.detalle_orden(resumen)
        bloques = tuple(Bloque(_t(titulo), _lineas(lineas)) for titulo, lineas in detalle.secciones)
        lineas = _lineas(
            [mensajes.cabecera_de_curso(detalle.posicion, detalle.total, detalle.curso)],
            detalle.finales,
            [mensajes.linea_destino("real", resumen.curso, resumen.nombre_curso)],
        )
        return self._si(
            detalle.encabezado,
            lineas,
            mensajes.PREGUNTA_DESTINO,
            bloques=bloques,
            **mensajes.rotulos("confirmar_orden"),
        )

    def confirmar_calificador(self, resumen: ResumenCalificador) -> bool:
        detalle = mensajes.detalle_calificador(resumen)
        lineas = _lineas(
            [mensajes.cabecera_de_curso(detalle.posicion, detalle.total, detalle.curso)],
            detalle.lineas,
            [mensajes.linea_destino("real", resumen.curso, resumen.nombre_curso)],
        )
        return self._si(
            detalle.encabezado,
            lineas,
            mensajes.PREGUNTA_DESTINO,
            **mensajes.rotulos("confirmar_calificador"),
        )

    def confirmar_copia(self, resumen: ResumenCopia) -> bool:
        detalle = mensajes.detalle_copia(resumen)
        lineas = _lineas(
            [mensajes.linea_de_copia(detalle)],
            [f"· {actividad}" for actividad in detalle.actividades],
        )
        return self._si(
            "Copia de seguridad",
            lineas,
            detalle.pregunta,
            **mensajes.rotulos("confirmar_copia"),
        )

    def confirmar_sobrescribir(self, resumen: ResumenSobrescribir) -> bool:
        detalle = mensajes.detalle_sobrescribir(resumen)
        lineas = _lineas(
            [mensajes.cabecera_de_curso(detalle.posicion, detalle.total, detalle.curso)],
            detalle.lineas,
        )
        return self._si(
            detalle.encabezado,
            lineas,
            detalle.pregunta,
            **mensajes.rotulos("confirmar_sobrescribir"),
        )

    # --- arranque ---

    def configurar(self, validar: Callable[[str], None] | None = None) -> tuple[str, str] | None:
        error, url, usuario = "", "", ""
        while True:
            pantalla = Pantalla(
                0,
                "configurar",
                titulo="URL del aula virtual y usuario",
                lineas=_lineas(
                    ["URL del aula virtual (p. ej. https://aula.ejemplo.org/<centro>)."]
                ),
                error=error,
                url=url,
                usuario=usuario,
            )
            respuesta = self._panel.preguntar(
                pantalla, lambda r: _configurar(r, None), reloj=self._reloj
            )
            if respuesta is None:
                return None
            url, usuario = respuesta
            if validar is None:
                return respuesta
            try:
                validar(url)
            except config.ErrorConfig as exc:
                error = " ".join(
                    linea.texto for linea in mensajes.lineas_de_error(exc.codigo, exc.detalle)
                )
                error = _t(error)
                continue
            return respuesta

    def confirmar_actualizacion(self, nueva: str, actual: str) -> bool:
        return self._si(
            "Actualizar tiza",
            [mensajes.texto_actualizacion(nueva, actual)],
            mensajes.PREGUNTA_ACTUALIZAR,
            **mensajes.rotulos("confirmar_actualizacion"),
        )

    def confirmar_carpeta_dudosa(self, carpeta: Path) -> bool:
        return self._si(
            "Carpeta dudosa",
            [mensajes.texto_carpeta_dudosa(carpeta)],
            mensajes.PREGUNTA_CARPETA_DUDOSA,
            **mensajes.rotulos("confirmar_carpeta_dudosa"),
        )

    def ofrecer_aislamiento(self) -> bool:
        return self._si(
            "Aislamiento",
            [],
            mensajes.PREGUNTA_AISLAR_AQUI,
            **mensajes.rotulos("ofrecer_aislamiento"),
        )

    def confirmar_aislamiento(self, resumen: ResumenAislamiento) -> bool:
        lineas = mensajes.lineas_de_aislamiento(resumen)
        if not resumen.ficheros:
            for linea in lineas:
                self._panel.anotar(linea)
            return True
        if self._si(
            "Aislamiento",
            lineas,
            mensajes.PREGUNTA_AISLAMIENTO,
            **mensajes.rotulos("confirmar_aislamiento"),
        ):
            return True
        self._panel.anotar("No se ha cambiado nada.", error=True)
        return False

    def seguir_sin_aislar(self, faltas: list) -> bool:
        lineas = [
            f"- {getattr(falta, 'agente', '')}: {getattr(falta, 'texto', '')}" for falta in faltas
        ]
        return self._si(
            "Sin aislar",
            lineas,
            mensajes.PREGUNTA_SEGUIR_SIN_AISLAR,
            **mensajes.rotulos("seguir_sin_aislar"),
        )

    def cerrar_sesion_anterior(self, atendiendo: bool) -> bool:
        lineas = [mensajes.SESION_ANTERIOR_TEXTO]
        if atendiendo:
            lineas.append(mensajes.SESION_ANTERIOR_ATENDIENDO)
        return self._si(
            "Sesión anterior",
            lineas,
            mensajes.PREGUNTA_SESION_ANTERIOR,
            **mensajes.rotulos("cerrar_sesion_anterior"),
        )

    # --- sesión abierta ---

    def ofrecer_ampliacion(self, minutos: int, plazo: float) -> bool:
        return self._si(
            "Se acabó el tiempo",
            [],
            mensajes.pregunta_ampliacion(minutos),
            plazo=plazo,
            tipo="ampliar",
            **mensajes.rotulos_ampliacion(minutos),
        )

    def informar(self, aviso: Aviso) -> None:
        if aviso.codigo == "TIZA_ACTUALIZADA":
            # El actualizador del panel no abre otra ventana: el panel se reabre solo.
            self._panel.anotar(mensajes.ACTUALIZANDO_TEXTO)
            return
        if (
            aviso.codigo == "RESULTADO"
            and self.sin_entrar
            and aviso.datos["documento"].get("resultado") == "abortado"
        ):
            return  # «Has respondido que no»: lo cuenta el aviso siguiente, con lo que pasó
        if aviso.codigo == "CANCELADA" and self.sin_entrar:
            # «Has respondido que no» confunde cuando lo que pasó es que no se entró.
            self._panel.anotar(f"{mensajes.NO_SE_ENTRO_TITULO}. {mensajes.NO_SE_ENTRO_TEXTO}", True)
            self._panel.marcar_sesion(False)
            self._panel.fijar_paso("")
            self._panel.mostrar(
                Pantalla(
                    0,
                    "reposo",
                    titulo=mensajes.NO_SE_ENTRO_TITULO,
                    lineas=_lineas([mensajes.NO_SE_ENTRO_TEXTO, mensajes.NO_SE_ENTRO_QUE_HACER]),
                )
            )
            return
        lineas = mensajes.lineas_de_aviso(aviso)
        for linea in lineas:
            self._panel.anotar(linea.texto, linea.error)
        if aviso.codigo == "SESION_ABIERTA" or aviso.codigo in _CIERRAN:
            if aviso.codigo == "SESION_ABIERTA":
                self._panel.fijar_caducidad(aviso.datos["caduca"])
                self._panel.fijar_paso("sesion")
            self._panel.marcar_sesion(aviso.codigo == "SESION_ABIERTA")
            self._panel.mostrar(
                Pantalla(
                    0,
                    "reposo",
                    titulo=_t(lineas[0].texto) if lineas else "",
                    lineas=_lineas([linea.texto for linea in lineas[1:]]),
                )
            )


class Puente:
    """Lo único que JavaScript puede llamar (el ``js_api``): solo acciones.

    Todo lo interno empieza por «_» y no hay atributos públicos. Un argumento ``undefined``
    de JavaScript llega como ``None``: es una respuesta no válida, nunca un error.
    """

    def __init__(
        self,
        panel: Panel,
        *,
        abrir: Callable[[str], object] = webbrowser.open,
    ) -> None:
        self._panel = panel
        self._abrir = abrir

    def estado(self) -> dict:
        return self._panel.estado()

    def responder(self, numero: Any = None, respuesta: Any = None) -> bool:
        return self._panel.responder(numero, respuesta)

    def elegir_reciente(self, numero: Any = None, indice: Any = None) -> bool:
        """Elige la carpeta reciente número ``indice`` (la ruta real no sale del ``Panel``)."""
        return self._panel.responder(numero, ("reciente", indice))

    def quitar_reciente(self, numero: Any = None, indice: Any = None) -> bool:
        """Quita la reciente ``indice`` de la pantalla actual (la ruta no sale del ``Panel``)."""
        return self._panel.quitar_reciente(numero, indice)

    def buscar_carpeta(self, numero: Any = None) -> bool:
        """Pide el diálogo de carpeta. No lo abre: lo atiende el hilo de la ventana."""
        return self._panel.pedir_dialogo(numero)

    def terminar(self, numero: Any = None) -> bool:
        """Pide cerrar la sesión. No cierra nada aquí: el hilo de la ventana la destruye."""
        return self._panel.pedir_salida(numero)

    def ver_vista_previa(self, numero: Any = None, indice: Any = None) -> bool:
        ruta = self._panel.vista(numero, indice)
        if ruta is None:
            return False
        self._abrir(ruta.as_uri())
        return True
