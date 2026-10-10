"""Interfaz común de los tipos de actividad y lo que comparten los cinco.

Cada tipo de actividad (página, tarea, cuestionario, etiqueta y H5P) tiene su
módulo en este paquete, con lo que sabe hacer: campos del frontmatter, validación,
fechas, finalización, payload, vista previa y aportación al hash. Aquí vive solo
lo que no depende del tipo: la clase :class:`Tipo`, el modelo de fechas y los
constructores de payload genéricos.

Ningún módulo de aquí habla con el aula ni importa ``python-moodle``: los adapters
solo construyen datos y llaman a ``AulaVirtual`` a través de sus flujos, igual
que hace el resto de tiza por encima del protocolo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # solo para anotar; nunca en tiempo de ejecución (ciclo con contenido)
    from ..contenido import Documento

# Nombre llano del «recordarme calificar antes de» de una tarea: tiza nunca lo pone y
# toda publicación de una tarea lo desactiva, así que la confirmación de real tiene que
# poder enseñar que se quita.
CAMPO_RECORDATORIO = "recordatorio de calificación"

# Casilla del formulario de finalización que marca cada modo (confirmado en Moodle 4.5).
# «ninguna» y «manual» no usan casilla: van en el campo «completion».
BANDERA_DE_MODO = {
    "ver": "completionview",
    "entregar": "completionsubmit",
    "calificar": "completionusegrade",
}


@dataclass(frozen=True)
class FechaActividad:
    """Una fecha declarada por el documento, mire donde mire el tipo donde viva.

    Las de una tarea y las de un cuestionario se construyen igual, para que el
    resto de tiza (calendario, avisos, confirmación, payload y verificación) no
    tenga que saber de qué tipo es el documento.
    """

    campo: str  # «apertura», «entrega», «límite», «cierre» o CAMPO_RECORDATORIO
    momento: datetime | None  # None: la fecha no está puesta (se desactiva en el aula)
    campo_moodle: str  # «duedate», «timeopen»…
    exige_clase: bool = False  # el calendario avisa si el día no es de clase


class Tipo:
    """Lo que sabe un tipo de actividad. La base solo cumple la interfaz."""

    nombre: str = ""  # «pagina»
    llano: str = ""  # «Página»
    modulo: str = ""  # nombre del módulo de Moodle («page»)
    campos: frozenset[str] = frozenset()  # campos propios del frontmatter
    finalizaciones: tuple[str, ...] = ()  # modos de finalización admitidos
    banderas: tuple[str, ...] = ()  # casillas del formulario de «cuándo se completa»
    campos_fecha: tuple[str, ...] = ()  # campos del formulario de Moodle con fecha

    # --- Fechas -----------------------------------------------------------

    def fechas(self, doc: Documento) -> tuple[FechaActividad, ...]:
        """Las fechas que declara el documento, en el orden en que se enseñan."""
        return ()

    def payload_solo_fechas(self, doc: Documento) -> dict[str, str] | None:
        """Formulario mínimo para cambiar solo las fechas, o None si no aplica."""
        return None


# --------------------------------------------------------------------------- #
# Constructores genéricos de fechas (los usan todos los tipos por igual)
# --------------------------------------------------------------------------- #


def partes_fecha(momento: datetime) -> tuple[int, int, int, int, int]:
    """(año, mes, día, hora, minuto), como los lee y los escribe el formulario."""
    return (momento.year, momento.month, momento.day, momento.hour, momento.minute)


def payload_fecha(campo: str, momento: datetime) -> dict[str, str]:
    return {
        f"{campo}[enabled]": "1",
        f"{campo}[day]": str(momento.day),
        f"{campo}[month]": str(momento.month),
        f"{campo}[year]": str(momento.year),
        f"{campo}[hour]": str(momento.hour),
        f"{campo}[minute]": str(momento.minute),
    }


def fechas_payload(tipo: Tipo, doc: Documento) -> dict[str, str]:
    """Los campos de fecha del formulario; una fecha sin poner se desactiva."""
    payload: dict[str, str] = {}
    for fecha in tipo.fechas(doc):
        if fecha.momento is None:
            payload[f"{fecha.campo_moodle}[enabled]"] = "0"
        else:
            payload.update(payload_fecha(fecha.campo_moodle, fecha.momento))
    return payload


def fechas_esperadas(
    tipo: Tipo, doc: Documento
) -> dict[str, tuple[int, int, int, int, int] | None]:
    """Lo que debe mostrar el formulario de la actividad tras publicarla."""
    return {
        fecha.campo_moodle: (partes_fecha(fecha.momento) if fecha.momento is not None else None)
        for fecha in tipo.fechas(doc)
    }


# --------------------------------------------------------------------------- #
# Finalización: el payload y la lectura del formulario, genéricos por tipo
# --------------------------------------------------------------------------- #


def payload_finalizacion(
    tipo: Tipo, doc: Documento, *, solo_fecha_esperada: bool = False
) -> dict[str, str]:
    """Campos de finalización del formulario, o ``{}`` si el documento no la declara.

    Se envían todos los del tipo (los no usados a 0): la fusión conserva lo que no se
    envía, y un modo anterior dejaría su casilla marcada.
    """
    finalizacion = doc.finalizacion
    if finalizacion is None:
        return {}
    payload: dict[str, str] = {}
    esperada = finalizacion.esperada
    if esperada is None:
        payload["completionexpected[enabled]"] = "0"
    else:
        payload["completionexpected[enabled]"] = "1"
        for parte, valor in zip(
            ("year", "month", "day", "hour", "minute"), partes_fecha(esperada), strict=True
        ):
            payload[f"completionexpected[{parte}]"] = str(valor)
    if solo_fecha_esperada:
        return payload
    modo = finalizacion.modo
    payload["completion"] = {"ninguna": "0", "manual": "1"}.get(modo, "2")
    if modo in BANDERA_DE_MODO:
        elegida = BANDERA_DE_MODO[modo]
        for bandera in tipo.banderas:
            payload[bandera] = "1" if bandera == elegida else "0"
    return payload


def modo_leido(tipo: Tipo, campos: dict) -> str | None:
    """El modo de finalización que dice el formulario; None si no es uno de los de tiza."""
    completion = campos.get("completion")
    if completion == "0":
        return "ninguna"
    if completion == "1":
        return "manual"
    if completion != "2":
        return None
    marcadas = [
        modo
        for modo, bandera in BANDERA_DE_MODO.items()
        if bandera in tipo.banderas and campos.get(bandera) == "1"
    ]
    return marcadas[0] if len(marcadas) == 1 else None
