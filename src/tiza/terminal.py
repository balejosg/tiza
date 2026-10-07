"""Presencia humana: comprobación de terminal, confirmación y contraseña.

La contraseña solo puede llegar por ``getpass`` desde una terminal
interactiva. No existe ninguna opción, variable de entorno ni fichero que la
acepte.
"""

from __future__ import annotations

import getpass
import queue
import re
import sys
import threading
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from . import ayuda, informe
from .informe import ErrorInforme
from .sesion import (
    SIN_PRUEBAS,
    Aviso,
    CursoSesion,
    DocumentoResumen,
    ResumenPublicacion,
    ResumenSinPruebas,
)

__all__ = [
    "ErrorTerminal",
    "PresenciaTerminal",
    "describir_documento",
    "enlace",
    "imprimir_error",
    "confirmar",
    "confirmar_destino",
    "describir_curso",
    "elegir_curso",
    "exigir_tty",
    "pedir_password",
    "preguntar_con_limite",
    "texto_seguro",
]


class ErrorTerminal(Exception):
    """Error de terminal con un código estable."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


# Controles C0/C1 (incluido ESC y CSI) y controles bidireccionales (incluido
# U+061C, ARABIC LETTER MARK): con ellos un texto ajeno podría borrar o
# reescribir lo que el docente lee antes de confirmar. Misma clase de caracteres
# que informe._TEXTO_PROHIBIDO, contenido._CONTROL y publicar._NO_IMPRIMIBLE;
# mantén las cuatro sincronizadas.
_NO_IMPRIMIBLE = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def texto_seguro(texto: object, maximo: int = 120) -> str:
    """Texto del agente o de Moodle apto para la terminal del docente."""
    if maximo < 1:
        return ""
    limpio = _NO_IMPRIMIBLE.sub("", str(texto))
    if len(limpio) > maximo:
        limpio = limpio[: maximo - 1] + "…"
    return limpio


def exigir_tty() -> None:
    """Aborta si la entrada o la salida no son una terminal interactiva."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ErrorTerminal(
            "SIN_TTY",
            "este comando se ejecuta en la terminal del docente",
        )


def confirmar_destino(entorno: str, curso: int, nombre: str | None = None) -> bool:
    """Muestra el destino y pide confirmación explícita ([s/N])."""
    print(f"Curso de destino: {describir_curso(curso, nombre)} (entorno: {entorno})")
    return confirmar("¿Continuar con este curso?")


_SI = {"s", "si", "sí"}

_PARA_QUE = {
    "pruebas": "donde se publica primero; el alumnado no lo ve",
    "real": "el que usa tu alumnado",
}


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


def describir_curso(curso: int, nombre: str | None) -> str:
    if nombre:
        return f"«{texto_seguro(nombre, 80)}» (id {curso})"
    return f"id {curso}"


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
    print(f"¿Cuál es tu curso de {entorno.upper()}? ({_PARA_QUE[entorno]})")
    if not opciones:
        return _pedir_id(entorno, excluir)
    for indice, curso in enumerate(opciones, 1):
        print(f"  {indice}. {texto_seguro(curso['nombre'], 80)}")
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
    mensaje = f"ERROR [{codigo}]"
    if detalle:
        mensaje += f": {detalle}"
    print(mensaje, file=sys.stderr)
    texto = ayuda.explicar(codigo)
    if texto is not None:
        print(f"Qué hacer: {texto}", file=sys.stderr)


_TIPOS = {
    "pagina": "Página",
    "tarea": "Tarea",
    "cuestionario": "Cuestionario",
    "etiqueta": "Área de texto y medios",
}


def _fecha_llana(momento: datetime) -> str:
    return momento.strftime("%d/%m/%Y %H:%M")


def describir_documento(doc: DocumentoResumen) -> str:
    """Qué se va a publicar, en lenguaje llano y saneado para la terminal."""
    if isinstance(doc.seccion, str):
        seccion = f"sección «{texto_seguro(doc.seccion)}»"
    else:
        seccion = f"sección {doc.seccion}"
    texto = f"{_TIPOS.get(doc.tipo, doc.tipo)} «{texto_seguro(doc.nombre)}» → {seccion}"
    if doc.fechas is not None:
        texto += (
            f"; apertura {_fecha_llana(doc.fechas.apertura)}, "
            f"entrega {_fecha_llana(doc.fechas.entrega)}"
        )
        if doc.fechas.limite is not None:
            texto += f", límite {_fecha_llana(doc.fechas.limite)}"
    return texto


_VISIBILIDAD: dict[bool | None, str] = {
    True: "ATENCIÓN: se publicará VISIBLE para el alumnado.",
    False: "Se publicará oculto (también lo que ya fuera visible).",
    None: "Lo que ya exista conserva su visibilidad; lo nuevo se crea oculto.",
}

_CIERRE = {
    "aula": (
        "El aula ha cerrado la sesión (caducó, o entraste con este usuario "
        "desde otro sitio, como el navegador). Vuelve a abrirla con «tiza empezar»."
    ),
    "caducada": "La sesión ha caducado; se cierra.",
    "desactualizada": (
        "tiza ha cambiado mientras la sesión estaba abierta; se cierra. "
        "Vuelve a abrirla con «tiza empezar»."
    ),
    "docente": "\nSesión cerrada.",
}


class PresenciaTerminal:
    """La presencia de ``tiza sesion`` y ``tiza empezar``: la terminal del docente."""

    def pedir_password(self, servidor: str, usuario: str) -> str | None:
        print(f"Vas a escribir la contraseña del aula de {servidor} (usuario: {usuario}).")
        return pedir_password()

    def elegir_curso(self, entorno: str, cursos: list[dict], excluir: int | None) -> int | None:
        return elegir_curso(entorno, cursos, excluir=excluir)

    def confirmar_cursos(self, cursos: list[CursoSesion]) -> bool:
        print("Cursos de esta sesión:")
        for curso in cursos:
            linea = f"  {curso.entorno + ':':8} {describir_curso(curso.id, curso.nombre)}"
            if curso.ajeno:
                linea += " — no aparece entre tus cursos: comprueba el id"
            if curso.entorno == "real":
                linea += " — cada publicación en real se confirmará aquí"
            print(linea)
        if not any(curso.entorno == "pruebas" for curso in cursos):
            print(
                "AVISO: Sin curso de pruebas: no habrá verificación previa y en real "
                "solo se publicará oculto."
            )
        return confirmar("¿Abrir la sesión con estos cursos?")

    def confirmar_sin_pruebas(self) -> bool:
        print(
            "Sin curso de pruebas: no habrá verificación previa y en real solo se publicará oculto."
        )
        return confirmar("¿Abrir la sesión sin curso de pruebas?")

    def confirmar_autoprueba(self) -> bool:
        print(
            "Conviene pasar la autoprueba: crea y borra contenido temporal en el curso de "
            "pruebas para comprobar que todo funciona (1-2 minutos)."
        )
        return confirmar("¿Pasarla ahora?")

    def confirmar_real(self, resumen: ResumenPublicacion) -> bool:
        curso = describir_curso(resumen.curso, resumen.nombre_curso)
        print(f"El agente pide publicar en el curso REAL {curso}:")
        for doc in resumen.documentos:
            print(f"  - {describir_documento(doc)}")
            print(f"      fichero {texto_seguro(doc.fichero)}, verificado en pruebas")
            if doc.vista_previa is not None:
                print(f"      vista previa: {enlace(doc.vista_previa)}")
            for url in doc.enlaces_externos:
                print(f"      enlace externo: {texto_seguro(url)}")
            for url in doc.incrustados:
                print(f"      incrusta: {texto_seguro(url)}")
            for ruta in doc.recursos:
                print(f"      se sube el fichero {texto_seguro(ruta)}")
        for nombre in resumen.secciones_nuevas:
            print(f"  Se creará la sección «{texto_seguro(nombre)}» (oculta).")
        print(f"  {_VISIBILIDAD[resumen.visible]}")
        return confirmar_destino("real", resumen.curso, nombre=resumen.nombre_curso)

    def confirmar_real_sin_pruebas(self, resumen: ResumenSinPruebas) -> bool:
        curso = describir_curso(resumen.curso, resumen.nombre_curso)
        print(f"Sin curso de pruebas: se publicará solo en oculto en el curso {curso}.")
        print("El agente pide publicar en el curso REAL, sin verificación previa:")
        for doc in resumen.documentos:
            print(
                f"  - {_TIPOS.get(doc.tipo, doc.tipo)} «{texto_seguro(doc.nombre)}»"
                f" (fichero {texto_seguro(doc.fichero)})"
            )
            if doc.existe is True:
                print("      Ya existe en el aula: se ocultará si estaba visible.")
            elif doc.existe is None:
                print("      Puede que ya exista en el aula: se ocultará si estaba visible.")
        for nombre in resumen.secciones_nuevas:
            print(f"  Se creará la sección «{texto_seguro(nombre)}» (oculta).")
        return confirmar_destino("real", resumen.curso, nombre=resumen.nombre_curso)

    def ofrecer_ampliacion(self, minutos: int, plazo: float) -> bool:
        return preguntar_con_limite(
            f"Se ha acabado el tiempo de la sesión. ¿Ampliar {minutos} minutos más? [s/N] ",
            plazo,
        )

    def informar(self, aviso: Aviso) -> None:
        getattr(self, f"_aviso_{aviso.codigo.lower()}")(aviso.datos)

    def _aviso_autoprueba_fallida(self, _datos: Mapping[str, Any]) -> None:
        print("No se abre la sesión porque la autoprueba ha fallado.", file=sys.stderr)

    def _aviso_cancelada(self, _datos: Mapping[str, Any]) -> None:
        print("Operación cancelada.", file=sys.stderr)

    def _aviso_creando_seccion(self, datos: Mapping[str, Any]) -> None:
        print(f"Creando la sección «{texto_seguro(datos['nombre'])}» (oculta)...")

    def _aviso_cursos_guardados(self, datos: Mapping[str, Any]) -> None:
        print(f"Cursos guardados en {datos['ruta']}.")

    def _aviso_error_interno(self, datos: Mapping[str, Any]) -> None:
        imprimir_error(
            "ERROR_INTERNO",
            f"al atender una petición ({datos['tipo']}); "
            "repite con «tiza sesion --debug» para ver el detalle.",
        )

    def _aviso_estructura_no_leida(self, _datos: Mapping[str, Any]) -> None:
        print("No se pudo leer la estructura; el agente podrá pedirla con «tiza estructura».")

    def _aviso_fallo(self, datos: Mapping[str, Any]) -> None:
        mensaje = f"ERROR [{datos['codigo']}]"
        if datos.get("detalle"):
            mensaje += f": {datos['detalle']}"
        print(mensaje, file=sys.stderr)

    def _aviso_informe_no_escrito(self, _datos: Mapping[str, Any]) -> None:
        print("AVISO: no se pudo escribir .tiza/informe.json.", file=sys.stderr)

    def _aviso_maximo_alcanzado(self, datos: Mapping[str, Any]) -> None:
        print(
            f"La sesión ha llegado al máximo de {datos['horas']} horas. "
            "Abre otra cuando la necesites."
        )

    def _aviso_nombres_no_disponibles(self, _datos: Mapping[str, Any]) -> None:
        print("No se pudo leer la lista de tus cursos; se mostrarán solo los ids.")

    def _aviso_peticion_retirada(self, _datos: Mapping[str, Any]) -> None:
        print("El agente ya no espera esta petición; no se publica.")

    def _aviso_publicando_en_pruebas(self, datos: Mapping[str, Any]) -> None:
        print("El agente pide publicar en pruebas:")
        for doc in datos["documentos"]:
            print(f"  - {describir_documento(doc)}")

    def _aviso_quedan_minutos(self, datos: Mapping[str, Any]) -> None:
        print(
            f"Quedan menos de {datos['minutos']} minutos de sesión. "
            "Al llegar la hora podrás ampliarla aquí."
        )

    def _aviso_resultado(self, datos: Mapping[str, Any]) -> None:
        try:
            lineas = informe.resumen(datos["documento"])
        except ErrorInforme:
            return
        for linea in lineas:
            print(linea)

    def _aviso_sesion_abierta(self, datos: Mapping[str, Any]) -> None:
        hora = datos["caduca"].astimezone().strftime("%Y-%m-%d %H:%M")
        print(
            f"Sesión abierta hasta {hora}. Deja esta terminal abierta; pulsa Ctrl+C para cerrarla."
        )

    def _aviso_sesion_cerrada(self, datos: Mapping[str, Any]) -> None:
        print(_CIERRE[datos["motivo"]])
