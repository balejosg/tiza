"""CLI `tiza`: comandos offline y comandos autenticados de terminal."""

from __future__ import annotations

import argparse
import importlib.resources
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import traceback
import unicodedata
from collections.abc import Sequence
from pathlib import Path

from . import (
    __version__,
    actualizacion,
    agente,
    aislamiento,
    arranque,
    ayuda,
    buzon,
    config,
    contenido,
    ficheros,
    informe,
    mensajes,
    publicacion,
    publicar,
    rutas,
    sesion,
    sesion_abierta,
    terminal,
)
from .config import ErrorConfig
from .contenido import ErrorContenido
from .informe import ErrorInforme
from .publicacion import AVISO_DEBUG, Aviso
from .publicar import ErrorPublicacion
from .sesion import MAX_MINUTOS
from .terminal import ErrorTerminal

__all__ = ["main", "instalar_skill"]

REPO_GIT = actualizacion.REPO_GIT
PYTHON_INSTALADO = actualizacion.PYTHON_INSTALADO


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tiza",
        description="Publica páginas, etiquetas, tareas, cuestionarios y actividades H5P en tu aula virtual Moodle con rol de profesor.",
    )
    parser.add_argument("--version", action="version", version=f"tiza {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser(
        "configurar",
        help="guarda la URL y el usuario; los cursos son opcionales (nunca la contraseña)",
    )
    sub.add_parser("instalar-skill", help="copia la skill a los agentes instalados")
    sub.add_parser("actualizar", help="actualiza tiza y su skill a la última versión")
    sub.add_parser("revisar", help="comprueba que el agente está aislado del aula (solo lectura)")
    aislar = sub.add_parser(
        "aislar",
        help="añade el aislamiento a esta carpeta (Claude Code, Codex, opencode y Copilot)",
    )
    aislar.add_argument(
        "--global",
        dest="global_",
        action="store_true",
        help="aísla todos tus proyectos (configuración de usuario) en vez de solo esta carpeta",
    )

    comprobar = sub.add_parser(
        "comprobar", help="valida ficheros .md o .html y genera la vista previa (offline)"
    )
    comprobar.add_argument("ficheros", nargs="+")

    leer = sub.add_parser(
        "leer",
        help="convierte un Word (.docx) o un PDF de la carpeta en texto para el agente (offline)",
    )
    leer.add_argument("fichero", help="el .docx o .pdf, dentro de la carpeta de la asignatura")

    documento = sub.add_parser(
        "documento",
        help="convierte un .md en un Word sencillo (.docx) en la carpeta, sin sobrescribir (offline)",
    )
    documento.add_argument("fuente", help="el .md, dentro de la carpeta de la asignatura")
    documento.add_argument(
        "--salida", help="el .docx de salida (por defecto, el nombre del .md con .docx)"
    )

    rellenar = sub.add_parser(
        "rellenar",
        help="rellena una copia de una plantilla Word (.docx) según un relleno.yaml (offline)",
    )
    rellenar.add_argument("relleno", help="el relleno .yaml, dentro de la carpeta de la asignatura")

    importar = sub.add_parser(
        "importar",
        help="convierte una copia de seguridad de Moodle (.mbz) en ficheros de tiza (offline)",
    )
    importar.add_argument(
        "copia", help="el .mbz, dentro de la carpeta de la asignatura (o en .tiza/copias)"
    )
    importar.add_argument(
        "--destino",
        default="aula",
        help="carpeta donde se escriben los ficheros (por defecto, aula)",
    )
    importar.add_argument(
        "--como-nuevas",
        action="store_true",
        help="importa la copia de otro curso como actividades nuevas (sin vínculo con el aula)",
    )

    estructura = sub.add_parser("estructura", help="lee las secciones de los cursos (autenticado)")
    estructura.add_argument(
        "--cambios",
        nargs="+",
        default=[],
        metavar="FICHERO",
        help="dice, en cada curso real, si retocaste a mano en el aula esas actividades desde "
        "la última vez que tiza las publicó o importó",
    )
    estructura.add_argument("--debug", action="store_true")

    publicar_parser = sub.add_parser(
        "publicar",
        help="crea o actualiza páginas, etiquetas, tareas, cuestionarios y actividades H5P (autenticado)",
        description="Lo nuevo se crea oculto y lo que ya existe conserva su visibilidad, "
        "salvo con --visible u --oculto.",
    )
    publicar_parser.add_argument("ficheros", nargs="+")
    publicar_parser.add_argument(
        "--en", choices=("pruebas", "real"), required=True, help="curso de destino"
    )
    visibilidad = publicar_parser.add_mutually_exclusive_group()
    visibilidad.add_argument(
        "--visible", action="store_true", help="muestra al alumnado lo que se publica"
    )
    visibilidad.add_argument(
        "--oculto", action="store_true", help="oculta lo que se publica, aunque ya fuera visible"
    )
    publicar_parser.add_argument(
        "--solo-fechas",
        action="store_true",
        help="cambia solo las fechas de tareas y cuestionarios ya publicados; no toca el "
        "contenido, las preguntas, los intentos ni la visibilidad",
    )
    publicar_parser.add_argument("--debug", action="store_true")

    ordenar = sub.add_parser(
        "ordenar",
        help="deja las actividades de esos ficheros en ese orden dentro de su sección (autenticado)",
        description="Las actividades nombradas se reparten los huecos que ya ocupaban; lo que no "
        "se nombra no se mueve. Para cambiar una actividad de sección, edita «seccion:» y "
        "publica.",
    )
    ordenar.add_argument("ficheros", nargs="+")
    ordenar.add_argument(
        "--en", choices=("pruebas", "real"), required=True, help="curso de destino"
    )
    ordenar.add_argument("--debug", action="store_true")

    calificador = sub.add_parser(
        "calificador",
        help="monta el calificador del aula según un esquema .yaml y las actividades (autenticado)",
        description="Crea en el calificador las categorías y los totales que dice el esquema y "
        "coloca en ellos las actividades de la carpeta con «evalua». Lo hace la sesión abierta "
        "del docente; en real confirma, curso por curso, con lo que va a pasar. Nunca lee ni "
        "escribe notas, ni desbloquea nada. Para comprobar el esquema sin red: "
        "«tiza comprobar calificacion.yaml».",
    )
    calificador.add_argument(
        "esquema", help="el esquema .yaml, dentro de la carpeta de la asignatura"
    )
    calificador.add_argument(
        "--en", choices=("pruebas", "real"), required=True, help="curso de destino"
    )
    calificador.add_argument("--debug", action="store_true")

    copia = sub.add_parser(
        "copia",
        help="pide al docente una copia de seguridad del curso, sin usuarios (autenticado)",
        description="Pide a la sesión abierta del docente que haga una copia de seguridad del "
        "curso, sin datos de alumnos. El docente la confirma; queda en .tiza/copias/ lista "
        "para «tiza importar».",
    )
    copia.add_argument(
        "curso",
        help="«pruebas», «real» (si solo hay un curso real) o el id de un curso de tiza.toml",
    )
    copia.add_argument(
        "--actividad",
        action="append",
        default=[],
        metavar="FICHERO",
        help="copia solo de esta actividad (un fichero de la carpeta ya publicado en el curso "
        "real); se puede repetir. Sin ella, la copia es del curso entero",
    )
    copia.add_argument("--debug", action="store_true")

    autoprueba = sub.add_parser(
        "autoprueba", help="prueba de contrato en el curso de pruebas (autenticado)"
    )
    autoprueba.add_argument("--debug", action="store_true")

    sesion = sub.add_parser(
        "sesion",
        help="abre la sesión en la que el agente publica (autenticado, terminal del docente)",
    )
    sesion.add_argument(
        "--minutos",
        type=_minutos,
        default=60,
        help="minutos que dura la sesión (por defecto, 60)",
    )
    sesion.add_argument("--debug", action="store_true")
    sesion.add_argument(
        "--sin-ventana",
        action="store_true",
        help="escribe la contraseña en la terminal en vez de entrar en la ventana del aula",
    )
    sesion.add_argument(
        "--elegir-cursos",
        action="store_true",
        help="vuelve a preguntar el curso de pruebas y los reales y los guarda",
    )

    empezar = sub.add_parser(
        "empezar",
        help="todo en uno para el docente: configura, comprueba y abre la sesión (terminal del docente)",
    )
    empezar.add_argument(
        "--minutos",
        type=_minutos,
        default=60,
        help="minutos que dura la sesión (por defecto, 60; se puede ampliar)",
    )
    empezar.add_argument("--debug", action="store_true")
    empezar.add_argument(
        "--sin-ventana",
        action="store_true",
        help="escribe la contraseña en la terminal en vez de entrar en la ventana del aula",
    )
    empezar.add_argument(
        "--elegir-cursos",
        action="store_true",
        help="vuelve a preguntar el curso de pruebas y los reales y los guarda",
    )

    normativa = sub.add_parser(
        "normativa",
        help="consulta la normativa por código en JSON (sin aula y en cualquier carpeta)",
    )
    consultas = normativa.add_subparsers(dest="consulta", required=True, metavar="CONSULTA")
    catalogo = consultas.add_parser(
        "catalogo", help="materias y módulos del curso académico, con sus normas"
    )
    _anadir_curso(catalogo)
    ficha = consultas.add_parser(
        "ficha", help="todos los elementos de una materia o módulo, con su texto y su procedencia"
    )
    ficha.add_argument("codigo", help="código de la materia o módulo, p. ej. MAD.ESO.CCOMP.1")
    _anadir_curso(ficha)
    elemento = consultas.add_parser("elemento", help="un elemento por su código")
    elemento.add_argument("codigo", help="código del elemento")
    _anadir_curso(elemento)
    norma = consultas.add_parser("norma", help="una norma por su cita, p. ej. «Decreto 27/2025»")
    norma.add_argument("cita", help="la cita de la norma")
    buscar = consultas.add_parser("buscar", help="busca un texto en los elementos del curso")
    buscar.add_argument("texto", help="palabras que buscar (sin distinguir tildes ni mayúsculas)")
    buscar.add_argument(
        "--en",
        dest="en",
        metavar="CODIGO",
        help="limita la búsqueda a una materia o módulo",
    )
    _anadir_curso(buscar)
    programacion = consultas.add_parser(
        "programacion", help="lo que la normativa exige de la programación de una etapa"
    )
    programacion.add_argument("etapa", help="eso, bachillerato o fp")
    _anadir_curso(programacion)
    return parser


def _anadir_curso(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--curso-academico",
        dest="curso_academico",
        metavar="AAAA-AA",
        help="curso académico, p. ej. 2026-27 (por defecto, el de hoy)",
    )


def _minutos(valor: str) -> int:
    if not valor.isdigit() or not 0 < int(valor) <= MAX_MINUTOS:
        raise argparse.ArgumentTypeError(
            f"los minutos deben ser un número entero entre 1 y {MAX_MINUTOS}"
        )
    return int(valor)


def _visibilidad(args) -> bool | None:
    """--visible, --oculto o None: conservar (lo nuevo se crea oculto)."""
    if args.visible:
        return True
    if args.oculto:
        return False
    return None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _despachar(args)
    except KeyboardInterrupt:
        print("\nOperación cancelada.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - último cortafuegos
        if getattr(args, "debug", False):
            print(AVISO_DEBUG, file=sys.stderr)
            traceback.print_exception(exc)
        else:
            _imprimir_error(
                "ERROR_INTERNO", "fallo inesperado; repite con --debug para ver el detalle."
            )
        return 1


def _despachar(args) -> int:
    if args.comando == "configurar":
        return _configurar()
    if args.comando == "instalar-skill":
        return _instalar_skill_cmd()
    if args.comando == "actualizar":
        return _actualizar()
    if args.comando == "revisar":
        return _revisar(args)
    if args.comando == "aislar":
        return _aislar(args)
    if args.comando == "comprobar":
        return _comprobar(args)
    if args.comando == "estructura":
        return _estructura(args)
    if args.comando == "publicar":
        return _publicar(args)
    if args.comando == "ordenar":
        return _ordenar(args)
    if args.comando == "calificador":
        return _calificador(args)
    if args.comando == "copia":
        return _copia(args)
    if args.comando == "autoprueba":
        return _autoprueba(args)
    if args.comando == "sesion":
        return _sesion(args)
    if args.comando == "empezar":
        return _empezar(args)
    if args.comando == "normativa":
        return _normativa(args)
    if args.comando == "leer":
        return _leer(args)
    if args.comando == "documento":
        return _documento(args)
    if args.comando == "rellenar":
        return _rellenar(args)
    if args.comando == "importar":
        return _importar(args)
    return 2


# --------------------------------------------------------------------------- #
# Informe
# --------------------------------------------------------------------------- #


def _dir_tiza() -> Path:
    return Path.cwd() / rutas.CARPETA_TRABAJO


def _escribir(documento: dict) -> None:
    try:
        informe.escribir(documento, _dir_tiza())
    except (ErrorInforme, OSError):
        print(
            f"AVISO: no se pudo escribir {rutas.CARPETA_TRABAJO}/informe.json.",
            file=sys.stderr,
        )
    try:
        for linea in informe.resumen(documento):
            print(linea)
    except ErrorInforme:
        return


def _fallo(
    comando: str,
    codigo: str,
    detalle: str = "",
    *,
    pasos: Sequence[informe.Paso | dict] | None = None,
    ficheros: list[dict] | None = None,
    entorno: str | None = None,
    curso: int | None = None,
    exc: BaseException | None = None,
    debug: bool = False,
) -> int:
    _escribir(informe.crear(comando, "error", pasos or [], ficheros, [codigo], entorno, curso))
    mensaje = f"ERROR [{codigo}]"
    if detalle:
        mensaje += f": {detalle}"
    print(mensaje, file=sys.stderr)
    if debug and exc is not None:
        print(AVISO_DEBUG, file=sys.stderr)
        traceback.print_exception(exc.__cause__ or exc)
    return 1


def _abortado(comando: str, entorno: str | None = None, curso: int | None = None) -> int:
    _escribir(informe.crear(comando, "abortado", [], [], ["ABORTADO"], entorno, curso))
    print("Operación cancelada.", file=sys.stderr)
    return 1


def _explicar(nombre: str, codigo: str, detalle: str = "") -> str:
    """Línea para quien corrige el fichero: texto local de tiza, nunca de Moodle."""
    texto = f"{nombre}: {codigo}" + (f": {detalle}" if detalle else "")
    return mensajes.texto_seguro(texto, 300)


def _imprimir_error(codigo: str, detalle: str = "") -> None:
    """Error de un comando sin informe: código, detalle y qué hacer."""
    terminal.imprimir_error(codigo, detalle)


# --------------------------------------------------------------------------- #
# Comandos offline
# --------------------------------------------------------------------------- #


def _normativa(args) -> int:
    """Una consulta de normativa: un único JSON en stdout y 0, o 2 si falla. Nunca toca .tiza/."""
    from .normativa import ErrorNormativa, consulta, salida  # carga diferida: solo datos y textos

    try:
        try:
            documento = _consulta_normativa(args, consulta).a_dict()
            salida.validar(documento)
            codigo = 0
        except ErrorNormativa as error:
            limpio = ErrorNormativa(
                error.codigo,
                _sin_control(error.detalle),
                tuple(_sin_control(d) for d in error.disponibles),
            )
            documento = salida.error_a_dict(limpio)
            codigo = 2
    except salida.ErrorSalida:
        documento = {"error": "SALIDA_INVALIDA", "detalle": "", "disponibles": []}
        codigo = 2
    _escribir_json(documento)
    return codigo


def _error_json(codigo: str, detalle: str) -> dict:
    """El error de ``leer`` y ``documento``: código, detalle y qué hacer (texto de tiza)."""
    return {
        "error": codigo,
        "detalle": _sin_control(detalle),
        "que_hacer": _sin_control(ayuda.explicar(codigo) or ""),
    }


def _leer(args) -> int:
    """Lee un Word o PDF: un único JSON en stdout (resumen o error) y 0 o 2. No escribe informe."""
    from .lectura.modelo import ErrorLectura  # carga diferida: sin python-docx ni pypdf

    try:
        documento = agente.leer(args.fichero, Path.cwd()).a_dict()
        codigo = 0
    except ErrorLectura as error:
        documento = _error_json(error.codigo, error.detalle)
        codigo = 2
    except ErrorInforme:  # un nombre de fichero con símbolos no permitidos
        documento = _error_json("NOMBRE_NO_VALIDO", "El nombre del fichero no vale.")
        codigo = 2
    _escribir_json(documento)
    return codigo


def _documento(args) -> int:
    """Escribe un Word desde un .md: un único JSON en stdout (resumen o error) y 0 o 2."""
    from .escritura import ErrorEscritura  # carga diferida

    try:
        resultado = agente.documento(args.fuente, Path.cwd(), args.salida).a_dict()
        codigo = 0
    except ErrorEscritura as error:
        resultado = _error_json(error.codigo, error.detalle)
        codigo = 2
    except ErrorInforme:  # un nombre de fichero con símbolos no permitidos
        resultado = _error_json("NOMBRE_NO_VALIDO", "El nombre del fichero no vale.")
        codigo = 2
    _escribir_json(resultado)
    return codigo


def _rellenar(args) -> int:
    """Rellena una plantilla Word: un único JSON en stdout (resumen o error) y 0 o 2."""
    from .escritura import ErrorEscritura  # carga diferida
    from .lectura.modelo import ErrorLectura

    try:
        resultado = agente.rellenar(args.relleno, Path.cwd()).a_dict()
        codigo = 0
    except (ErrorEscritura, ErrorLectura) as error:
        resultado = _error_json(error.codigo, error.detalle)
        codigo = 2
    except ErrorInforme:  # un nombre de fichero con símbolos no permitidos
        resultado = _error_json("NOMBRE_NO_VALIDO", "El nombre del fichero no vale.")
        codigo = 2
    _escribir_json(resultado)
    return codigo


def _importar(args) -> int:
    """Importa una copia de Moodle: un único JSON en stdout (resumen o error) y 0 o 2."""
    from .config import ErrorConfig
    from .copia import ErrorCopia  # carga diferida: sin lxml
    from .estado import ErrorEstado
    from .importar import ErrorImportar
    from .lectura.modelo import ErrorLectura

    try:
        resultado = agente.importar(args.copia, Path.cwd(), args.destino, args.como_nuevas).a_dict()
        codigo = 0
    except (ErrorImportar, ErrorCopia, ErrorLectura, ErrorConfig, ErrorEstado) as error:
        resultado = _error_json(error.codigo, error.detalle)
        codigo = 2
    except ErrorInforme:  # un nombre con símbolos no permitidos
        resultado = _error_json("NOMBRE_NO_VALIDO", "El nombre del fichero no vale.")
        codigo = 2
    _escribir_json(resultado)
    return codigo


def _consulta_normativa(args, consulta):
    if args.consulta == "catalogo":
        return consulta.catalogo(args.curso_academico)
    if args.consulta == "ficha":
        return consulta.ficha(args.codigo, args.curso_academico)
    if args.consulta == "elemento":
        return consulta.elemento(args.codigo, args.curso_academico)
    if args.consulta == "norma":
        return consulta.norma(args.cita)
    if args.consulta == "buscar":
        return consulta.buscar(args.texto, args.en, args.curso_academico)
    return consulta.programacion(args.etapa, args.curso_academico)


def _sin_control(texto: str) -> str:
    """Quita los caracteres de control y de formato: un detalle no rompe el esquema de salida."""
    return "".join(c for c in texto if not unicodedata.category(c).startswith("C"))


def _escribir_json(documento: dict) -> None:
    """El documento en stdout como UTF-8, aunque la consola sea cp1252 (Windows)."""
    texto = json.dumps(documento, ensure_ascii=False, indent=1) + "\n"
    flujo = sys.stdout
    buffer = getattr(flujo, "buffer", None)
    if buffer is None:
        flujo.write(texto)
        return
    flujo.flush()
    buffer.write(texto.encode("utf-8"))
    buffer.flush()


def _comprobar(args) -> int:
    resultado = agente.comprobar(Path.cwd(), args.ficheros)
    for fichero in resultado.ficheros:
        if fichero.codigo == "SECCION_ES_ID":
            print(f"{fichero.fichero}: {fichero.detalle}", file=sys.stderr)
        elif fichero.codigo is not None:
            print(_explicar(fichero.fichero, fichero.codigo, fichero.detalle), file=sys.stderr)
        else:
            if fichero.seccion_nueva is not None:
                print(
                    f"{fichero.fichero}: la sección «{fichero.seccion_nueva}» no existe; "
                    "se creará oculta al publicar."
                )
            if fichero.vista_previa is not None:
                print(f"Vista previa: {terminal.enlace(fichero.vista_previa)}")
    _escribir(resultado.informe)
    return 1 if resultado.informe["errores"] else 0


def _configurar() -> int:
    try:
        terminal.exigir_tty()
    except ErrorTerminal as exc:
        _imprimir_error(exc.codigo, exc.detalle)
        return 1
    resultado = arranque.configurar(terminal.PresenciaTerminal())
    if resultado.estado is arranque.Estado.FALLO:
        _imprimir_error(resultado.codigo, resultado.detalle)
        return 1
    if resultado.estado is arranque.Estado.ABORTADO:
        print("Operación cancelada.", file=sys.stderr)
        return 1
    return 0


def _instalar_skill_cmd() -> int:
    destinos = instalar_skill(Path.home())
    for destino in destinos:
        print(f"Skill instalada: {destino}")
    return 0


def _actualizar() -> int:
    """Instala otra versión de tiza: es del docente (terminal y confirmación), no del agente."""
    try:
        terminal.exigir_tty()
    except ErrorTerminal as exc:
        _imprimir_error(exc.codigo, exc.detalle)
        return 1
    ref = os.environ.get("TIZA_REF")
    if ref:
        try:
            actualizacion.validar_ref(ref)
        except actualizacion.ErrorActualizacion as exc:
            _imprimir_error(exc.codigo, exc.detalle)
            return 1
    uv = shutil.which("uv")
    if uv is None:
        _imprimir_error(
            "UV_NO_ENCONTRADO", "no se encuentra uv; vuelve a ejecutar el instalador del README."
        )
        return 1
    # Los instaladores fijan una etiqueta y «uv tool upgrade» nunca sale de ella: se
    # reinstala la última etiqueta publicada (o la de TIZA_REF, como en el instalador).
    if not ref:
        ref = actualizacion.ultima_etiqueta()
        if ref is None:
            _imprimir_error(
                "ACTUALIZACION_FALLIDA", "no se pudo consultar la última versión publicada."
            )
            return 1
        if ref == f"v{__version__}":
            print(f"Ya tienes la última versión ({__version__}).")
            return 0
    if not terminal.confirmar(f"Se va a instalar tiza «{ref}» desde {REPO_GIT}. ¿Continuar?"):
        print("No se ha cambiado nada.", file=sys.stderr)
        return 1
    return 0 if _instalar_version(uv, ref) else 1


def _instalar_version(uv: str, ref: str) -> bool:
    """Instala tiza ``ref`` con uv y reinstala la skill; False (con el error impreso) si falla.

    En Windows no se puede: uv borra el entorno de tiza y Windows no deja borrar el
    ``python.exe`` ni el ``tiza.exe`` que están en marcha (os error 5). Allí la instalación
    sigue en otra consola, cuando esta tiza ya ha terminado (``_instalar_aparte``).
    """
    con_ventana = (
        actualizacion.quiere_ventana()
    )  # sin el extra, la actualización dejaría sin ventana
    paquetes = actualizacion.paquetes(ref, con_ventana)
    if sys.platform == "win32":
        return _instalar_aparte(uv, ref, paquetes, con_ventana)
    instalado = False
    for paquete in paquetes:
        if actualizacion.uv_instala(uv, paquete):
            if con_ventana and not paquete.startswith("tiza[ventana]"):
                print("No se pudo instalar la ventana de entrada: se entrará con la contraseña.")
            instalado = True
            break
    if not instalado:
        _imprimir_error("ACTUALIZACION_FALLIDA", "no se pudo actualizar tiza.")
        return False
    # La skill se reinstala con la versión nueva (este proceso aún es la antigua).
    nuevo = shutil.which("tiza") or sys.argv[0]
    if subprocess.run([nuevo, "instalar-skill"]).returncode != 0:
        _imprimir_error("SKILL_NO_INSTALADA", "no se pudo reinstalar la skill.")
        return False
    print("Si tienes «tiza sesion» abierta, ciérrala (Ctrl+C) y vuelve a abrirla.")
    return True


def _instalar_aparte(uv: str, ref: str, paquetes: list[str], con_ventana: bool) -> bool:
    """Windows: lanza la actualización en otra consola, que espera a que esta tiza termine."""
    try:
        actualizacion.lanzar_consola(uv, ref, paquetes, con_ventana)
    except OSError:
        _imprimir_error("ACTUALIZACION_FALLIDA", "no se pudo abrir la ventana de la actualización.")
        return False
    print(
        "La actualización sigue en otra ventana, en cuanto se cierre tiza: ahí verás cuándo "
        "termina. Si tienes «tiza sesion» abierta, ciérrala (Ctrl+C) antes."
    )
    return True


def _version_nueva() -> str | None:
    """La etiqueta publicada más alta si es posterior a esta tiza; None si no, o si no se sabe."""
    return actualizacion.version_nueva()


def _instalar_ultima(nueva: str) -> bool:
    """Instala la versión ``nueva`` con uv; False si no hay uv o la instalación falla."""
    uv = shutil.which("uv")
    return uv is not None and _instalar_version(uv, nueva)


_REGISTRO_SKILL = ".tiza-instalado"


def _ficheros_de_la_skill(carpeta, prefijo: tuple[str, ...] = ()) -> dict[str, bytes]:
    """Lista recursiva (ruta relativa con «/» -> contenido) de la skill empaquetada."""
    lista: dict[str, bytes] = {}
    for hijo in sorted(carpeta.iterdir(), key=lambda h: h.name):
        if hijo.name == "__pycache__" or hijo.name == _REGISTRO_SKILL:
            continue
        if hijo.is_dir():
            lista.update(_ficheros_de_la_skill(hijo, (*prefijo, hijo.name)))
        else:
            lista["/".join((*prefijo, hijo.name))] = hijo.read_bytes()
    return lista


def _retirar_instalados_antes(carpeta: Path, nuevos: set[str]) -> None:
    """Borra lo que tiza instaló antes (según el registro) y ya no está en la skill.

    Solo toca rutas relativas del registro que caen dentro de ``carpeta``; nada más.
    """
    registro = carpeta / _REGISTRO_SKILL
    try:
        lineas = registro.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return
    raiz = carpeta.resolve()
    for linea in lineas:
        ruta = linea.strip()
        if not ruta or ruta in nuevos:
            continue
        partes = ruta.split("/")
        if ruta.startswith("/") or ".." in partes or "\\" in ruta or ":" in ruta:
            continue
        candidato = carpeta.joinpath(*partes)
        try:
            if candidato.is_symlink() or candidato.is_file():
                if candidato.parent.resolve().is_relative_to(raiz):
                    candidato.unlink()
        except OSError:
            continue
        padre = candidato.parent
        while padre != carpeta and padre.is_relative_to(carpeta):
            try:
                padre.rmdir()  # solo si quedó vacía
            except OSError:
                break
            padre = padre.parent


def instalar_skill(home: Path) -> list[Path]:
    """Copia la carpeta de la skill (SKILL.md y guías) a los directorios de los agentes.

    En cada destino apunta lo instalado en ``.tiza-instalado`` y, en la siguiente
    instalación, retira lo que tiza instaló antes y ya no existe; nunca borra un fichero
    que no esté en esa lista.
    """
    origen = importlib.resources.files("tiza").joinpath("skill", "tiza")
    contenidos = _ficheros_de_la_skill(origen)
    carpetas = [
        home / ".claude" / "skills" / "tiza",
        home / ".agents" / "skills" / "tiza",
        home / ".codex" / "skills" / "tiza",
        home / ".config" / "opencode" / "skills" / "tiza",
    ]
    for carpeta in carpetas:
        carpeta.mkdir(parents=True, exist_ok=True)
        _retirar_instalados_antes(carpeta, set(contenidos))
        for ruta, datos in contenidos.items():
            destino = carpeta.joinpath(*ruta.split("/"))
            destino.parent.mkdir(parents=True, exist_ok=True)
            ficheros.escribir_texto(destino, datos.decode("utf-8"))
        ficheros.escribir_texto(
            carpeta / _REGISTRO_SKILL, "".join(f"{ruta}\n" for ruta in sorted(contenidos))
        )
    return [carpeta / "SKILL.md" for carpeta in carpetas]


# --------------------------------------------------------------------------- #
# Aislamiento del agente
# --------------------------------------------------------------------------- #


def _home() -> Path:
    return Path.home()


def _sistema() -> str:
    return platform.system()


def _imprimir_comprobaciones(lista: list[aislamiento.Comprobacion]) -> bool:
    terminal.PresenciaTerminal().informar(Aviso.comprobaciones_de_aislamiento(lista))
    return not any(c.estado == "falta" for c in lista)


def _revisar(args) -> int:
    lista = aislamiento.revisar(_home(), _sistema(), Path.cwd())
    if _imprimir_comprobaciones(lista):
        print("Aislamiento correcto.")
        return 0
    print("Falta aislar el agente: ejecuta «tiza aislar» en tu terminal (no en la del agente).")
    if any(c.agente == aislamiento.OPENCODE and c.estado == "falta" for c in lista):
        print(
            "Si ya tienes opencode.jsonc en esta carpeta, tiza no lo edita: "
            "copia a mano las reglas que falten de docs/aislamiento.md."
        )
    return 1


def _avisar_copilot(servidor: str | None) -> None:
    """Receta de la app de Copilot: su configuración no se escribe, solo se guía."""
    if not aislamiento.ruta_copilot(_home()).is_dir():
        return
    print()
    for linea in aislamiento.receta_copilot(_sistema(), _home(), servidor=servidor):
        print(linea)


def _aislar(args) -> int:
    try:
        terminal.exigir_tty()
    except ErrorTerminal as exc:
        _imprimir_error(exc.codigo, exc.detalle)
        return 1
    servidor = aislamiento.servidor_configurado()
    if servidor is None:
        print(
            "AVISO: no se pudo leer el servidor del aula configurado; no se añadirá el "
            "bloqueo de red hacia el aula. Ejecuta «tiza configurar» y repite «tiza aislar»."
        )
    presencia = terminal.PresenciaTerminal()
    home, sistema = _home(), _sistema()
    if args.global_:
        planear = lambda: aislamiento.planear_global(home, sistema, servidor)  # noqa: E731
    else:
        carpeta = Path.cwd()
        if carpeta.resolve() == home.resolve():
            _imprimir_error(
                "CARPETA_NO_VALIDA",
                "esta es tu carpeta personal; para aislar todos tus proyectos usa «tiza aislar --global»",
            )
            return 1
        if not _parece_asignatura(carpeta) and not presencia.confirmar_aislar_carpeta_dudosa(
            carpeta
        ):
            print("No se ha cambiado nada.", file=sys.stderr)
            return 1
        planear = lambda: aislamiento.planear_carpeta(carpeta, home, sistema, servidor)  # noqa: E731
    try:
        plan = planear()
    except aislamiento.ErrorAislamiento as exc:
        _imprimir_error(exc.codigo, exc.detalle)
        return 1
    if not arranque.aplicar_plan(plan, presencia):
        return 1
    _avisar_copilot(servidor)
    return _revisar(args)


# --------------------------------------------------------------------------- #
# Comandos autenticados
# --------------------------------------------------------------------------- #


def _configuracion_inicial(
    args, comando: str, entorno: str | None = None, *, sin_sesion: bool = False
) -> tuple:
    """TTY y configuración comunes; devuelve (cfg, None) o (None, código de salida)."""
    debug = getattr(args, "debug", False)
    try:
        terminal.exigir_tty()
        cfg = config.resolver(Path.cwd())
    except ErrorTerminal as exc:
        if sin_sesion:
            detalle = "pide al docente que ejecute «tiza empezar» en su terminal, en esta carpeta"
            pasos: list[informe.Paso] = []
            pista = agente.pista_worktree(Path.cwd())
            if pista is not None:
                detalle = pista
                pasos.append(informe.Paso("SIN_SESION", "fallo", pista))
            return None, _fallo(
                comando,
                "SIN_SESION",
                detalle,
                pasos=pasos,
                entorno=entorno,
                exc=exc,
                debug=debug,
            )
        return None, _fallo(comando, exc.codigo, exc.detalle, entorno=entorno, exc=exc, debug=debug)
    except ErrorConfig as exc:
        return None, _fallo(comando, exc.codigo, exc.detalle, entorno=entorno, exc=exc, debug=debug)
    if entorno is not None and not (cfg.reales if entorno == "real" else cfg.cursos.get(entorno)):
        if entorno == "pruebas":
            return None, _fallo(comando, "SIN_CURSO_PRUEBAS", entorno=entorno)
        return None, _fallo(comando, "CURSO_NO_CONFIGURADO", entorno, entorno=entorno)
    return cfg, None


def _estructura_directa(args) -> int:
    comando = "estructura"
    cfg, salida = _configuracion_inicial(args, comando, sin_sesion=True)
    if cfg is None:
        return salida
    if not cfg.reales:
        return _fallo(comando, "CURSO_NO_CONFIGURADO", "real")
    base = Path.cwd().resolve()
    documentos = []
    for nombre in args.cambios:
        try:
            documentos.append(contenido.cargar(nombre, raiz=base))
        except ErrorContenido as exc:
            return _fallo(
                comando,
                exc.codigo,
                mensajes.texto_seguro(f"{Path(nombre).name}: {exc.detalle}", 300),
                exc=exc,
                debug=args.debug,
            )
    destinos = [("pruebas", cfg.cursos["pruebas"])] if "pruebas" in cfg.cursos else []
    destinos += [("real", curso) for curso in cfg.reales]
    for nombre, curso in destinos:
        if not terminal.confirmar_destino(nombre, curso):
            return _abortado(comando, nombre, curso)
    acreditacion = terminal.acreditar(cfg.url, cfg.usuario)
    if acreditacion is None:
        return _abortado(comando)
    try:
        moodle = publicar.autenticar_con(cfg.url, cfg.usuario, acreditacion)
    except ErrorPublicacion as exc:
        return _fallo(comando, exc.codigo, exc.detalle, exc=exc, debug=args.debug)
    with publicar.sesion_del_aula(moodle):
        documento = sesion_abierta.estructura_con(
            moodle, cfg, Path.cwd(), ficheros=documentos, debug=args.debug
        )
        _escribir(documento)
        return 0 if documento["resultado"] == "ok" else 1


def _estructura(args) -> int:
    dir_tiza = _dir_tiza()
    if buzon.sesion_activa(dir_tiza):
        return _estructura_por_buzon(args, dir_tiza)
    version = buzon.sesion_incompatible(dir_tiza)
    if version is not None:
        return _fallo(
            "estructura",
            "SESION_INCOMPATIBLE",
            f"la sesión abierta usa tiza {version}; esta terminal, tiza {__version__}",
        )
    return _estructura_directa(args)


def _publicar_directa(args) -> int:
    comando = "publicar"
    entorno = args.en
    cfg, salida = _configuracion_inicial(args, comando, entorno, sin_sesion=True)
    if cfg is None:
        return salida
    cursos = list(cfg.reales) if entorno == "real" else [cfg.cursos["pruebas"]]
    total = len(cursos)
    unico = cursos[0] if total == 1 else None  # en el informe, el curso solo si es uno
    visible = _visibilidad(args)
    solo_fechas = args.solo_fechas
    sin_pruebas = entorno == "real" and "pruebas" not in cfg.cursos
    # Sin curso de pruebas solo se publica oculto (o solo fechas): se rechaza antes de
    # pedir la contraseña.
    if publicacion.exige_oculto_sin_pruebas(cfg, visible, solo_fechas=solo_fechas):
        return _fallo(
            comando,
            "SOLO_OCULTO_SIN_PRUEBAS",
            "sin curso de pruebas solo se publica en real con --oculto",
            entorno=entorno,
            curso=unico,
        )
    base = Path.cwd().resolve()
    documentos = []
    for nombre in args.ficheros:
        try:
            documentos.append(contenido.cargar(nombre, raiz=base))
        except ErrorContenido as exc:
            return _fallo(
                comando,
                exc.codigo,
                mensajes.texto_seguro(f"{Path(nombre).name}: {exc.detalle}", 300),
                entorno=entorno,
                curso=unico,
                exc=exc,
                debug=args.debug,
            )
    if sin_pruebas and not solo_fechas:
        print(mensajes.SIN_PRUEBAS_AVISO)
    # La puerta de real se comprueba antes de la contraseña; el flujo unificado la repite
    # con la misma regla (es gratis: el hash ya está calculado).
    if entorno == "real" and not solo_fechas and not sin_pruebas:
        faltan = publicacion.puerta_real(base, documentos)
        if faltan:
            return _fallo(
                comando, "VERIFICACION_PENDIENTE", ", ".join(faltan), entorno=entorno, curso=unico
            )
    # La terminal del docente descarta cursos antes de pedir la contraseña; después, la
    # confirmación de lo que cambia (y el resto del flujo) es la misma que la de la sesión.
    omitidos: set[int] = set()
    for curso in cursos:
        if not (solo_fechas and entorno == "real") and not terminal.confirmar_destino(
            entorno, curso
        ):
            omitidos.add(curso)
    if len(omitidos) == total:
        return _abortado(comando, entorno, unico)
    acreditacion = terminal.acreditar(cfg.url, cfg.usuario)
    if acreditacion is None:
        return _abortado(comando, entorno, unico)
    try:
        moodle = publicar.autenticar_con(cfg.url, cfg.usuario, acreditacion)
    except ErrorPublicacion as exc:
        return _fallo(
            comando,
            exc.codigo,
            exc.detalle,
            entorno=entorno,
            curso=unico,
            exc=exc,
            debug=args.debug,
        )
    with publicar.sesion_del_aula(moodle):
        presencia = terminal.PresenciaTerminal()
        nombres = (
            publicacion.nombres_de_cursos(moodle, presencia, args.debug)
            if entorno == "real"
            else {}
        )
        necesita_vistas = entorno == "real" and not solo_fechas and not sin_pruebas
        dir_vistas = sesion.crear_dir_vistas() if necesita_vistas else None
        try:
            documento = publicacion.publicar_en_cursos(
                moodle,
                cfg,
                documentos,
                base,
                presencia,
                entorno=entorno,
                visible=visible,
                solo_fechas=solo_fechas,
                omitidos=omitidos,
                nombres=nombres,
                dir_vistas=dir_vistas,
                debug=args.debug,
            )
        finally:
            if dir_vistas is not None:
                shutil.rmtree(dir_vistas, ignore_errors=True)
        _escribir(documento)
        return 0 if documento["resultado"] == "ok" else 1


def _publicar(args) -> int:
    if args.solo_fechas and _visibilidad(args) is not None:
        return _fallo(
            "publicar",
            "PETICION_INVALIDA",
            "--solo-fechas no admite --visible ni --oculto: las fechas no cambian la visibilidad",
            entorno=args.en,
        )
    dir_tiza = _dir_tiza()
    if buzon.sesion_activa(dir_tiza):
        return _publicar_por_buzon(args, dir_tiza)
    version = buzon.sesion_incompatible(dir_tiza)
    if version is not None:
        return _fallo(
            "publicar",
            "SESION_INCOMPATIBLE",
            f"la sesión abierta usa tiza {version}; esta terminal, tiza {__version__}",
            entorno=args.en,
        )
    return _publicar_directa(args)


def _ordenar_directa(args) -> int:
    comando = "ordenar"
    entorno = args.en
    cfg, salida = _configuracion_inicial(args, comando, entorno, sin_sesion=True)
    if cfg is None:
        return salida
    cursos = list(cfg.reales) if entorno == "real" else [cfg.cursos["pruebas"]]
    unico = cursos[0] if len(cursos) == 1 else None
    base = Path.cwd().resolve()
    documentos = []
    for nombre in args.ficheros:
        try:
            documentos.append(contenido.cargar(nombre, raiz=base))
        except ErrorContenido as exc:
            return _fallo(
                comando,
                exc.codigo,
                mensajes.texto_seguro(f"{Path(nombre).name}: {exc.detalle}", 300),
                entorno=entorno,
                curso=unico,
                exc=exc,
                debug=args.debug,
            )
    # En pruebas se confirma el destino; en real lo confirma cada curso, con el orden a la vista.
    if entorno == "pruebas" and not terminal.confirmar_destino(entorno, cursos[0]):
        return _abortado(comando, entorno, unico)
    acreditacion = terminal.acreditar(cfg.url, cfg.usuario)
    if acreditacion is None:
        return _abortado(comando, entorno, unico)
    try:
        moodle = publicar.autenticar_con(cfg.url, cfg.usuario, acreditacion)
    except ErrorPublicacion as exc:
        return _fallo(
            comando,
            exc.codigo,
            exc.detalle,
            entorno=entorno,
            curso=unico,
            exc=exc,
            debug=args.debug,
        )
    with publicar.sesion_del_aula(moodle):
        presencia = terminal.PresenciaTerminal()
        nombres = (
            publicacion.nombres_de_cursos(moodle, presencia, args.debug)
            if entorno == "real"
            else {}
        )
        documento = publicacion.ordenar_en_cursos(
            moodle,
            cfg,
            documentos,
            base,
            presencia,
            entorno=entorno,
            nombres=nombres,
            debug=args.debug,
        )
        _escribir(documento)
        return 0 if documento["resultado"] == "ok" else 1


def _ordenar(args) -> int:
    dir_tiza = _dir_tiza()
    if buzon.sesion_activa(dir_tiza):
        return _responder_buzon(
            "ordenar", agente.peticion_ordenar(args.ficheros, args.en), dir_tiza, debug=args.debug
        )
    version = buzon.sesion_incompatible(dir_tiza)
    if version is not None:
        return _fallo(
            "ordenar",
            "SESION_INCOMPATIBLE",
            f"la sesión abierta usa tiza {version}; esta terminal, tiza {__version__}",
            entorno=args.en,
        )
    return _ordenar_directa(args)


def _calificador(args) -> int:
    """El calificador lo monta la sesión del docente: sin sesión no hay modo directo."""
    dir_tiza = _dir_tiza()
    if buzon.sesion_activa(dir_tiza):
        return _responder_buzon(
            "calificador",
            agente.peticion_calificador(args.esquema, args.en),
            dir_tiza,
            espera=buzon.ESPERA_CALIFICADOR,
            debug=args.debug,
        )
    version = buzon.sesion_incompatible(dir_tiza)
    if version is not None:
        return _fallo(
            "calificador",
            "SESION_INCOMPATIBLE",
            f"la sesión abierta usa tiza {version}; esta terminal, tiza {__version__}",
            entorno=args.en,
        )
    return _fallo(
        "calificador",
        "SIN_SESION",
        "el calificador lo monta la sesión del docente",
        entorno=args.en,
    )


def _copia(args) -> int:
    """La copia del curso la hace la sesión del docente: sin sesión no hay modo directo."""
    dir_tiza = _dir_tiza()
    if buzon.sesion_activa(dir_tiza):
        return _responder_buzon(
            "copia", agente.peticion_copia(args.curso, args.actividad), dir_tiza, debug=args.debug
        )
    version = buzon.sesion_incompatible(dir_tiza)
    if version is not None:
        return _fallo(
            "copia",
            "SESION_INCOMPATIBLE",
            f"la sesión abierta usa tiza {version}; esta terminal, tiza {__version__}",
        )
    return _fallo("copia", "SIN_SESION", "la copia del curso la hace la sesión del docente")


# --------------------------------------------------------------------------- #
# Buzón: lado del agente
# --------------------------------------------------------------------------- #


def _responder_buzon(
    comando: str,
    peticion: dict,
    dir_tiza: Path,
    *,
    espera: float = buzon.ESPERA_POR_DEFECTO,
    debug: bool = False,
) -> int:
    try:
        respuesta = buzon.enviar(dir_tiza, peticion, espera)
    except buzon.ErrorBuzon as exc:
        return _fallo(
            comando, exc.codigo, exc.detalle, entorno=peticion["entorno"], exc=exc, debug=debug
        )
    for linea in informe.resumen(respuesta):
        print(linea)
    return 0 if respuesta["resultado"] == "ok" else 1


def _publicar_por_buzon(args, dir_tiza: Path) -> int:
    peticion = agente.peticion_publicar(
        args.ficheros, args.en, _visibilidad(args), solo_fechas=args.solo_fechas
    )
    return _responder_buzon("publicar", peticion, dir_tiza, debug=args.debug)


def _estructura_por_buzon(args, dir_tiza: Path) -> int:
    peticion = agente.peticion_estructura(args.cambios)
    return _responder_buzon("estructura", peticion, dir_tiza, debug=args.debug)


# --------------------------------------------------------------------------- #
# Buzón: lado del docente (`tiza sesion`)
# --------------------------------------------------------------------------- #


def _sesion(args) -> int:
    try:
        terminal.exigir_tty()
    except ErrorTerminal as exc:
        return _fallo("sesion", exc.codigo, exc.detalle, exc=exc, debug=args.debug)
    return sesion.abrir(
        Path.cwd(),
        terminal.PresenciaTerminal(usar_ventana=not args.sin_ventana),
        minutos=args.minutos,
        preparar=False,
        debug=args.debug,
        elegir_cursos=args.elegir_cursos,
    )


def _parece_asignatura(carpeta: Path) -> bool:
    return arranque.parece_asignatura(carpeta, _home())


def _empezar(args) -> int:
    """Un solo comando para el docente, con una sola contraseña."""
    comando = "sesion"
    try:
        terminal.exigir_tty()
    except ErrorTerminal as exc:
        return _fallo(comando, exc.codigo, exc.detalle, exc=exc, debug=args.debug)
    presencia = terminal.PresenciaTerminal(usar_ventana=not args.sin_ventana)
    carpeta = Path.cwd()
    resultado = arranque.preparar(
        carpeta,
        presencia,
        home=_home(),
        sistema=_sistema(),
        version_nueva=lambda: _version_nueva(),
        instalar=_instalar_ultima,
    )
    if resultado.estado is arranque.Estado.ACTUALIZADA:
        return 0
    if resultado.estado is arranque.Estado.ABORTADO:
        return _abortado(comando)
    if resultado.estado is arranque.Estado.FALLO:
        if not resultado.con_informe:
            _imprimir_error(resultado.codigo, resultado.detalle)
            return 1
        return _fallo(
            comando, resultado.codigo, resultado.detalle, exc=resultado.causa, debug=args.debug
        )
    return sesion.abrir(
        carpeta,
        presencia,
        minutos=args.minutos,
        preparar=True,
        debug=args.debug,
        elegir_cursos=args.elegir_cursos,
    )


def _autoprueba(args) -> int:
    comando = "autoprueba"
    debug = args.debug
    cfg, salida = _configuracion_inicial(args, comando, "pruebas")
    if cfg is None:
        return salida
    curso = cfg.cursos["pruebas"]
    if not terminal.confirmar_destino("pruebas", curso):
        return _abortado(comando, "pruebas", curso)
    acreditacion = terminal.acreditar(cfg.url, cfg.usuario)
    if acreditacion is None:
        return _abortado(comando, "pruebas", curso)
    try:
        moodle = publicar.autenticar_con(cfg.url, cfg.usuario, acreditacion)
    except ErrorPublicacion as exc:
        return _fallo(
            comando,
            exc.codigo,
            exc.detalle,
            entorno="pruebas",
            curso=curso,
            exc=exc,
            debug=debug,
        )
    with publicar.sesion_del_aula(moodle):
        presencia = terminal.PresenciaTerminal()
        return 0 if sesion.autoprueba_con(moodle, curso, Path.cwd(), presencia, debug=debug) else 1
