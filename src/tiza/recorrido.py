"""El recorrido por cursos: las reglas comunes a publicar, ordenar y calificador.

Un comando que va a varios cursos no repite el bucle: construye un **trabajo** (lo que
hace en un curso) y llama a :func:`recorrer`. Aquí viven, una sola vez, el curso de
pruebas con su cupo y su aviso, los cursos reales en el orden de ``tiza.toml``, los
omitidos, la vigencia de la petición, el corte y el informe por cursos.

El trabajo pregunta solo a través del :class:`Turno` que recibe. Así la vigencia se
comprueba en un único sitio: antes de cada curso salvo el primero y después de cada
respuesta tras la que tiza todavía escribe (cada «sí» y también el «no» a
sobrescribir). El «no» que declina un curso no la comprueba.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from . import informe

if TYPE_CHECKING:  # la sesión importa este módulo; no se carga publicacion al importarlo
    from .config import Config
    from .publicacion import Aviso, Presencia

__all__ = [
    "MAX_PUBLICACIONES_PRUEBAS",
    "PeticionRetirada",
    "Resultado",
    "Trabajo",
    "TrabajoBase",
    "Turno",
    "recorrer",
]

MAX_PUBLICACIONES_PRUEBAS = 50  # por sesión: frena a un agente en bucle


class PeticionRetirada(Exception):
    """El agente retiró la petición mientras el docente respondía.

    No hereda de los errores de dominio (``ErrorPublicacion``, ``ErrorCalificacion``,
    ``ErrorEstado``): los ``except`` de los trabajos no pueden tragársela. Solo la
    captura :func:`recorrer`.
    """


ClaseDeResultado = Literal["hecho", "declinado", "fallo"]


@dataclass(frozen=True)
class Resultado:
    """Lo que un trabajo hizo en un curso real.

    ``hecho`` lleva su informe y si corta los siguientes; ``declinado`` es el «no» del
    docente (se omite y se sigue); ``fallo`` lleva el código que corta.
    """

    clase: ClaseDeResultado
    informe: dict | None = None
    corta: bool = False
    codigo: str | None = None

    @classmethod
    def hecho(cls, documento: dict, *, corta: bool | None = None) -> Resultado:
        """Un curso hecho; por defecto corta si su informe no salió ``ok``."""
        return cls(
            "hecho",
            informe=documento,
            corta=documento["resultado"] != "ok" if corta is None else corta,
        )

    @classmethod
    def hecho_sin_cortar(cls, documento: dict) -> Resultado:
        """Un curso con informe no ``ok`` que no corta: el «no» a sobrescribir."""
        return cls.hecho(documento, corta=False)

    @classmethod
    def declinado(cls) -> Resultado:
        """El docente dijo que no a este curso: se registra omitido y se sigue."""
        return cls("declinado")

    @classmethod
    def fallo(cls, codigo: str) -> Resultado:
        """Un fallo del trabajo: se registra con su código y se para."""
        return cls("fallo", codigo=codigo, corta=True)


@dataclass(frozen=True)
class Turno:
    """La visita del recorrido a un curso real.

    El trabajo pregunta al docente solo con :meth:`preguntar`; no recibe la presencia.
    """

    curso: int
    posicion: int
    total: int
    nombre_curso: str | None
    _presencia: Presencia = field(repr=False, compare=False)
    _vigente: Callable[[], bool] | None = field(default=None, repr=False, compare=False)

    def preguntar(
        self,
        pregunta: Callable[[Presencia], bool],
        *,
        tras_no: bool = False,
    ) -> bool:
        """Hace una pregunta y devuelve el sí/no del docente.

        Tras un «sí» comprueba la vigencia. Tras un «no» solo si ``tras_no``: es el
        caso del «no» a sobrescribir, con el que todavía se publica el resto del lote.
        Si la petición se retiró, lanza :class:`PeticionRetirada`.
        """
        respuesta = pregunta(self._presencia)
        if (respuesta or tras_no) and self._vigente is not None and not self._vigente():
            raise PeticionRetirada
        return respuesta


class Trabajo(Protocol):
    """Lo que un comando aporta al recorrido: qué hace y cuándo corta."""

    comando: str

    def gasto_en_pruebas(self) -> int:
        """Cuánto cupo gasta en pruebas (entero ≥ 0)."""
        ...

    def comprobar_en_pruebas(self, curso: int) -> str | None:
        """Comprobación previa que no gasta cupo; su código o nada."""
        ...

    def aviso_en_pruebas(self) -> Aviso | None:
        """El aviso que la sesión enseña antes de publicar en pruebas, o nada."""
        ...

    def preparar_real(self) -> str | None:
        """Lo que se hace una vez antes de los cursos reales; su código o nada."""
        ...

    def en_pruebas(self, curso: int) -> dict:
        """El informe del curso de pruebas."""
        ...

    def en_curso(self, turno: Turno) -> Resultado:
        """Lo que se hace en un curso real; pregunta solo con ``turno.preguntar``."""
        ...


class TrabajoBase:
    """Los defectos neutros del trabajo; cada comando escribe solo lo suyo."""

    comando = ""

    def gasto_en_pruebas(self) -> int:
        return 1

    def comprobar_en_pruebas(self, curso: int) -> str | None:
        return None

    def aviso_en_pruebas(self) -> Aviso | None:
        return None

    def preparar_real(self) -> str | None:
        return None

    def en_pruebas(self, curso: int) -> dict:
        raise NotImplementedError

    def en_curso(self, turno: Turno) -> Resultado:
        raise NotImplementedError


def recorrer(
    trabajo: Trabajo,
    cfg: Config,
    presencia: Presencia,
    *,
    entorno: str,
    vigente: Callable[[], bool] | None = None,
    cupo: dict | None = None,
    avisar_en_pruebas: bool = False,
    omitidos: Collection[int] = (),
    nombres: Mapping[int, str] | None = None,
) -> dict:
    """Recorre los cursos de ``entorno`` con las reglas comunes y devuelve el informe.

    En pruebas hay una sola visita, con comprobación previa, cupo y aviso. En real hay
    una visita por curso en el orden de ``cfg.reales``, con una confirmación por curso;
    un fallo o una retirada cortan los siguientes y un «no» solo omite ese curso.
    """
    if entorno == "pruebas":
        return _en_pruebas(
            trabajo,
            cfg,
            presencia,
            entorno=entorno,
            cupo=cupo,
            avisar_en_pruebas=avisar_en_pruebas,
        )
    return _en_real(
        trabajo,
        cfg,
        presencia,
        entorno=entorno,
        vigente=vigente,
        omitidos=omitidos,
        nombres=nombres,
    )


def _en_pruebas(
    trabajo: Trabajo,
    cfg: Config,
    presencia: Presencia,
    *,
    entorno: str,
    cupo: dict | None,
    avisar_en_pruebas: bool,
) -> dict:
    comando = trabajo.comando
    curso = cfg.cursos.get("pruebas")
    if curso is None:
        return informe.crear(comando, "error", [], [], ["SIN_CURSO_PRUEBAS"], entorno)
    codigo = trabajo.comprobar_en_pruebas(curso)
    if codigo is not None:
        return informe.crear(comando, "error", [], [], [codigo], entorno, curso)
    if cupo is not None:
        gasto = trabajo.gasto_en_pruebas()
        if cupo["pruebas"] + gasto > MAX_PUBLICACIONES_PRUEBAS:
            return informe.crear(comando, "error", [], [], ["LIMITE_PUBLICACIONES"], entorno, curso)
        cupo["pruebas"] += gasto
    if avisar_en_pruebas:
        aviso = trabajo.aviso_en_pruebas()
        if aviso is not None:
            presencia.informar(aviso)
    return trabajo.en_pruebas(curso)


def _en_real(
    trabajo: Trabajo,
    cfg: Config,
    presencia: Presencia,
    *,
    entorno: str,
    vigente: Callable[[], bool] | None,
    omitidos: Collection[int],
    nombres: Mapping[int, str] | None,
) -> dict:
    comando = trabajo.comando
    reales = cfg.reales
    total = len(reales)
    unico = reales[0] if total == 1 else None
    codigo = trabajo.preparar_real()
    if codigo is not None:
        return informe.crear(comando, "error", [], [], [codigo], entorno, unico)
    vistos = nombres or {}
    registro: list[tuple[int, int, dict | None]] = []  # (posición, curso, informe o None)
    for posicion, curso in enumerate(reales, 1):
        if curso in omitidos:
            registro.append((posicion, curso, None))
            continue
        if vigente is not None and posicion > 1 and not vigente():
            _registrar_retirada(comando, entorno, presencia, registro, posicion, curso)
            break
        turno = Turno(
            curso=curso,
            posicion=posicion,
            total=total,
            nombre_curso=vistos.get(curso),
            _presencia=presencia,
            _vigente=vigente,
        )
        try:
            resultado = trabajo.en_curso(turno)
        except PeticionRetirada:
            _registrar_retirada(comando, entorno, presencia, registro, posicion, curso)
            break
        if resultado.clase == "declinado":
            registro.append((posicion, curso, None))
            continue
        if resultado.clase == "fallo":
            assert resultado.codigo is not None
            registro.append(
                (
                    posicion,
                    curso,
                    informe.crear(comando, "error", [], [], [resultado.codigo], entorno, curso),
                )
            )
            break
        assert resultado.informe is not None
        registro.append((posicion, curso, resultado.informe))
        if resultado.corta:
            break
    return _informe_de_cursos(comando, entorno, total, unico, registro)


def _registrar_retirada(
    comando: str,
    entorno: str,
    presencia: Presencia,
    registro: list[tuple[int, int, dict | None]],
    posicion: int,
    curso: int,
) -> None:
    from .publicacion import Aviso  # import diferido: publicacion importa este módulo

    presencia.informar(Aviso.peticion_retirada())
    registro.append(
        (
            posicion,
            curso,
            informe.crear(comando, "error", [], [], ["PETICION_RETIRADA"], entorno, curso),
        )
    )


def _informe_de_cursos(
    comando: str,
    entorno: str,
    total: int,
    unico: int | None,
    registro: list[tuple[int, int, dict | None]],
) -> dict:
    """Un informe con lo que pasó en cada curso real; con un solo curso, el de siempre."""
    if total == 1:
        informe_unico = registro[0][2]
        if informe_unico is None:
            return informe.crear(comando, "abortado", [], [], ["ABORTADO"], entorno, unico)
        return informe_unico
    borrador = informe.Borrador(comando, entorno=entorno)
    login = any(
        paso["codigo"] == "LOGIN"
        for _, _, doc in registro
        if doc is not None
        for paso in doc["pasos"]
    )
    if login:
        borrador.paso("LOGIN")
    publicados = 0
    for posicion, curso, doc in registro:
        if doc is None:
            borrador.paso("CURSO_OMITIDO", detalle=str(curso))
            continue
        fallido = doc["resultado"] != "ok"
        borrador.paso("CURSO", "fallo" if fallido else "ok", f"{posicion} de {total}: {curso}")
        borrador.agregar(doc, excluir={"LOGIN"})
        if fallido:
            continue
        publicados += 1
    if borrador.errores:
        return borrador.documento("error")
    if publicados == 0:
        borrador.error("ABORTADO")
        return borrador.documento("abortado")
    return borrador.documento()
