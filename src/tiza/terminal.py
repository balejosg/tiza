"""Presencia humana: comprobación de terminal, confirmación y contraseña.

La contraseña solo puede llegar por ``getpass`` desde una terminal
interactiva. No existe ninguna opción, variable de entorno ni fichero que la
acepte.

El texto que ve el docente lo decide :mod:`tiza.mensajes`; aquí solo se
pregunta, se imprime (stdout lo normal, stderr las líneas de error) y se
comprueba que hay una terminal delante.
"""

from __future__ import annotations

import getpass
import queue
import sys
import threading
import time
from pathlib import Path

from . import mensajes
from .config import MAX_REALES
from .publicacion import Aviso, ResumenPublicacion, ResumenSinPruebas
from .sesion import SIN_PRUEBAS, CursoSesion

__all__ = [
    "ErrorTerminal",
    "PresenciaTerminal",
    "confirmar",
    "confirmar_destino",
    "elegir_curso",
    "elegir_cursos_reales",
    "enlace",
    "exigir_tty",
    "imprimir_error",
    "pedir_password",
    "preguntar_con_limite",
]


class ErrorTerminal(Exception):
    """Error de terminal con un código estable."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


def exigir_tty() -> None:
    """Aborta si la entrada o la salida no son una terminal interactiva."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ErrorTerminal(
            "SIN_TTY",
            "este comando se ejecuta en la terminal del docente",
        )


def confirmar_destino(entorno: str, curso: int, nombre: str | None = None) -> bool:
    """Muestra el destino y pide confirmación explícita ([s/N])."""
    print(f"Curso de destino: {mensajes.describir_curso(curso, nombre)} (entorno: {entorno})")
    return confirmar("¿Continuar con este curso?")


_SI = {"s", "si", "sí"}


def confirmar(pregunta: str) -> bool:
    """Pide confirmación explícita; cualquier cosa distinta de «s» es no."""
    try:
        respuesta = input(f"{pregunta} [s/N] ").strip().lower()
    except EOFError:
        return False
    return respuesta in _SI


def preguntar_con_limite(pregunta: str, segundos: float, *, tramo: float = 0.5) -> bool:
    """Como :func:`confirmar`, pero sin respuesta en ``segundos`` es «no».

    Espera en tramos cortos para que Ctrl+C funcione también en Windows. Si vence
    el plazo, el hilo lector se queda bloqueado en ``input``: úsala solo como
    última pregunta antes de cerrar.
    """
    respuestas: queue.Queue = queue.Queue()

    def leer() -> None:
        try:
            respuestas.put(input(pregunta))
        except EOFError:
            respuestas.put("")

    threading.Thread(target=leer, name="tiza-pregunta", daemon=True).start()
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        try:
            respuesta = respuestas.get(timeout=min(tramo, max(limite - time.monotonic(), 0)))
        except queue.Empty:
            continue
        return str(respuesta).strip().lower() in _SI
    print()
    return False


def _cabecera_de_curso(posicion: int, total: int, curso: str) -> None:
    """Con varios cursos reales, cada confirmación dice cuál es: «Curso 2 de 3: …»."""
    if total > 1:
        print(f"Curso {posicion} de {total}: {curso}")


def _numero(valor: str) -> int | None:
    """Convierte una entrada de teclado en número, o None si no lo es."""
    try:
        return int(valor)
    except ValueError:
        return None


def elegir_curso(entorno: str, cursos: list[dict], excluir: int | None = None) -> int | None:
    """El docente elige un curso de la lista (o escribe su id); None si cancela.

    En ``pruebas`` también puede elegir no tener curso: devuelve ``SIN_PRUEBAS``
    y en real solo se publicará oculto.
    """
    opciones = [curso for curso in cursos if curso["id"] != excluir]
    print(f"¿Cuál es tu curso de {entorno.upper()}? ({mensajes.PARA_QUE[entorno]})")
    if not opciones:
        return _pedir_id(entorno, excluir)
    for indice, curso in enumerate(opciones, 1):
        print(f"  {indice}. {mensajes.texto_seguro(curso['nombre'], 80)}")
    opcion_sin = None
    if entorno == "pruebas":
        opcion_sin = len(opciones) + 1
        print(f"  {opcion_sin}. No tengo curso de pruebas (en real se publicará solo oculto)")
    print("  0. No está en la lista: escribiré su id")
    while True:
        try:
            valor = input("Número (Enter para cancelar): ").strip()
        except EOFError:
            return None
        if not valor:
            return None
        if valor == "0":
            return _pedir_id(entorno, excluir)
        numero = _numero(valor)
        if numero == opcion_sin:
            return SIN_PRUEBAS
        if numero is not None and 1 <= numero <= len(opciones):
            return opciones[numero - 1]["id"]
        print("Escribe uno de los números de la lista.")


def _ids_distintos(valor: str, excluir: int | None) -> list[int] | None:
    """Ids separados por comas, positivos, sin repetir, sin ``excluir`` y no más de MAX_REALES."""
    numeros = [_numero(trozo.strip()) for trozo in valor.split(",")]
    if (
        any(numero is None or numero <= 0 or numero == excluir for numero in numeros)
        or len(set(numeros)) != len(numeros)
        or len(numeros) > MAX_REALES
    ):
        return None
    return [numero for numero in numeros if numero is not None]


def elegir_cursos_reales(cursos: list[dict], excluir: int | None = None) -> list[int] | None:
    """El docente elige de 1 a MAX_REALES cursos reales con números separados por comas.

    Se publica en todos, en el orden en que los escribe; None si cancela.
    """
    opciones = [curso for curso in cursos if curso["id"] != excluir]
    print(f"¿Cuáles son tus cursos REALES? ({mensajes.PARA_QUE['real']}; hasta {MAX_REALES})")
    if not opciones:
        return _pedir_ids(excluir)
    for indice, curso in enumerate(opciones, 1):
        print(f"  {indice}. {mensajes.texto_seguro(curso['nombre'], 80)}")
    print("  0. No están en la lista: escribiré sus ids")
    while True:
        try:
            valor = input("Números separados por comas, por ejemplo 1,3 (Enter para cancelar): ")
        except EOFError:
            return None
        valor = valor.strip()
        if not valor:
            return None
        if valor == "0":
            return _pedir_ids(excluir)
        numeros = [_numero(trozo.strip()) for trozo in valor.split(",")]
        if (
            all(numero is not None and 1 <= numero <= len(opciones) for numero in numeros)
            and len(set(numeros)) == len(numeros)
            and len(numeros) <= MAX_REALES
        ):
            return [opciones[numero - 1]["id"] for numero in numeros if numero is not None]
        print(
            f"Escribe números de la lista separados por comas, sin repetir y como máximo {MAX_REALES}."
        )


def _pedir_ids(excluir: int | None) -> list[int] | None:
    while True:
        try:
            valor = input(
                "Ids de los cursos reales separados por comas (en la URL del curso: "
                "course/view.php?id=1234; Enter para cancelar): "
            ).strip()
        except EOFError:
            return None
        if not valor:
            return None
        ids = _ids_distintos(valor, excluir)
        if ids is not None:
            return ids
        print(
            "Escribe ids de curso válidos, sin repetir, distintos del curso de pruebas "
            f"y como máximo {MAX_REALES}."
        )


def _pedir_id(entorno: str, excluir: int | None) -> int | None:
    while True:
        try:
            valor = input(
                f"Id del curso de {entorno} (en la URL del curso: course/view.php?id=1234; "
                "Enter para cancelar): "
            ).strip()
        except EOFError:
            return None
        if not valor:
            return None
        numero = _numero(valor)
        if numero is not None and numero > 0 and numero != excluir:
            return numero
        print(
            "Escribe un número de curso válido."
            if excluir is None
            else "Escribe un número de curso válido y distinto del otro curso."
        )


def pedir_password() -> str:
    """Pide la contraseña por terminal; nunca la lee del entorno."""
    return getpass.getpass("Contraseña del aula virtual: ")


def enlace(ruta: Path) -> str:
    """URI file:// que las terminales permiten pulsar (también en Windows)."""
    return Path(ruta).resolve().as_uri()


def imprimir_error(codigo: str, detalle: str = "") -> None:
    """Error para el docente: código, detalle y qué hacer (textos de tiza)."""
    for linea in mensajes.lineas_de_error(codigo, detalle):
        print(linea.texto, file=sys.stderr)


class PresenciaTerminal:
    """La presencia de ``tiza sesion`` y ``tiza empezar``: la terminal del docente."""

    def pedir_password(self, servidor: str, usuario: str) -> str | None:
        print(f"Vas a escribir la contraseña del aula de {servidor} (usuario: {usuario}).")
        return pedir_password()

    def elegir_curso(self, entorno: str, cursos: list[dict], excluir: int | None) -> int | None:
        return elegir_curso(entorno, cursos, excluir=excluir)

    def elegir_cursos_reales(self, cursos: list[dict], excluir: int | None) -> list[int] | None:
        return elegir_cursos_reales(cursos, excluir=excluir)

    def confirmar_cursos(self, cursos: list[CursoSesion]) -> bool:
        print("Cursos de esta sesión:")
        for curso in cursos:
            linea = f"  {curso.entorno + ':':8} {mensajes.describir_curso(curso.id, curso.nombre)}"
            if curso.ajeno:
                linea += f" — {mensajes.AVISO_AJENO}"
            if curso.entorno == "real":
                linea += " — cada publicación en real se confirmará aquí"
            print(linea)
        if not any(curso.entorno == "pruebas" for curso in cursos):
            print(f"AVISO: {mensajes.SIN_PRUEBAS_AVISO}")
        return confirmar("¿Abrir la sesión con estos cursos?")

    def confirmar_sin_pruebas(self) -> bool:
        print(mensajes.SIN_PRUEBAS_AVISO)
        return confirmar("¿Abrir la sesión sin curso de pruebas?")

    def confirmar_autoprueba(self) -> bool:
        print(mensajes.AUTOPRUEBA_TEXTO)
        return confirmar("¿Pasarla ahora?")

    def confirmar_real(self, resumen: ResumenPublicacion) -> bool:
        detalle = mensajes.detalle_real(resumen)
        _cabecera_de_curso(detalle.posicion, detalle.total, detalle.curso)
        print(detalle.encabezado)
        if detalle.aviso_calendario is not None:
            print(f"  {detalle.aviso_calendario}")
        for doc in detalle.documentos:
            print(f"  - {doc.titulo}")
            for linea in doc.lineas:
                print(f"      {linea}")
            if doc.vista_previa is not None:
                print(f"      vista previa: {enlace(doc.vista_previa)}")
        for linea in detalle.finales:
            print(f"  {linea}")
        return confirmar_destino("real", resumen.curso, nombre=resumen.nombre_curso)

    def confirmar_real_sin_pruebas(self, resumen: ResumenSinPruebas) -> bool:
        detalle = mensajes.detalle_corto(resumen)
        _cabecera_de_curso(detalle.posicion, detalle.total, detalle.curso)
        print(detalle.aviso)
        print(detalle.encabezado)
        for doc in detalle.documentos:
            print(f"  - {doc.titulo}")
            for linea in doc.lineas:
                print(f"      {linea}")
        for linea in detalle.finales:
            print(f"  {linea}")
        return confirmar_destino("real", resumen.curso, nombre=resumen.nombre_curso)

    def ofrecer_ampliacion(self, minutos: int, plazo: float) -> bool:
        return preguntar_con_limite(
            f"Se ha acabado el tiempo de la sesión. ¿Ampliar {minutos} minutos más? [s/N] ",
            plazo,
        )

    def informar(self, aviso: Aviso) -> None:
        for linea in mensajes.lineas_de_aviso(aviso):
            print(linea.texto, file=sys.stderr if linea.error else sys.stdout)
