"""CLI `tiza`: comandos offline y comandos autenticados de terminal."""

from __future__ import annotations

import argparse
import importlib.resources
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from . import (
    __version__,
    agente,
    aislamiento,
    buzon,
    config,
    contenido,
    informe,
    publicar,
    rutas,
    sesion,
    terminal,
)
from .config import ErrorConfig
from .contenido import ErrorContenido
from .informe import ErrorInforme
from .publicar import ErrorPublicacion
from .sesion import (
    AVISO_DEBUG,
    MAX_MINUTOS,
)
from .terminal import ErrorTerminal

__all__ = ["main", "instalar_skill"]

REPO_GIT = "https://github.com/balejosg/tiza"
_REF_VALIDA = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")  # etiqueta, rama o commit


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

    estructura = sub.add_parser("estructura", help="lee las secciones de los cursos (autenticado)")
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
    return parser


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
    if args.comando == "autoprueba":
        return _autoprueba(args)
    if args.comando == "sesion":
        return _sesion(args)
    if args.comando == "empezar":
        return _empezar(args)
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
    pasos: list[dict] | None = None,
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
    return terminal.texto_seguro(texto, 300)


def _imprimir_error(codigo: str, detalle: str = "") -> None:
    """Error de un comando sin informe: código, detalle y qué hacer."""
    terminal.imprimir_error(codigo, detalle)


# --------------------------------------------------------------------------- #
# Comandos offline
# --------------------------------------------------------------------------- #


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
    return _preguntar_configuracion()


def _preguntar_configuracion() -> int:
    entrada = input("URL del aula virtual (p. ej. https://aula.ejemplo.org/<centro>): ")
    try:
        base = config.preparar_url(entrada)
    except ErrorConfig as exc:
        _imprimir_error(exc.codigo, exc.detalle)
        return 1
    usuario = input("Usuario del aula: ").strip()
    ruta = config.guardar_global(base, usuario)
    print(f"Configuración guardada en {ruta}. No se ha guardado ninguna contraseña.")
    print(
        "Los cursos son de cada asignatura: se eligen por nombre al abrir la sesión "
        f"en su carpeta («tiza empezar») y se guardan en su {rutas.FICHERO_ASIGNATURA}."
    )
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
    if ref and (not _REF_VALIDA.match(ref) or ".." in ref):
        _imprimir_error(
            "REF_NO_VALIDA",
            "TIZA_REF solo admite letras, números, «.», «_», «-» y «/», y debe empezar por una "
            "letra o un número",
        )
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
        git = shutil.which("git")
        if git is None:
            _imprimir_error(
                "GIT_NO_ENCONTRADO",
                "no se encuentra git; vuelve a ejecutar el instalador del README.",
            )
            return 1
        ref = _ultima_etiqueta(git)
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
    origen = f"git+{REPO_GIT}@{ref}"
    if _tiene_ventana():  # sin el extra, la actualización dejaría sin tiza-ventana
        origen = f"tiza[ventana] @ {origen}"
    if subprocess.run([uv, "tool", "install", "--force", origen]).returncode != 0:
        _imprimir_error("ACTUALIZACION_FALLIDA", "no se pudo actualizar tiza.")
        return 1
    # La skill se reinstala con la versión nueva (este proceso aún es la antigua).
    nuevo = shutil.which("tiza") or sys.argv[0]
    if subprocess.run([nuevo, "instalar-skill"]).returncode != 0:
        _imprimir_error("SKILL_NO_INSTALADA", "no se pudo reinstalar la skill.")
        return 1
    print("Si tienes «tiza sesion» abierta, ciérrala (Ctrl+C) y vuelve a abrirla.")
    return 0


def _tiene_ventana() -> bool:
    """¿Está instalado el extra ``ventana`` (pywebview) junto a esta tiza?"""
    return importlib.util.find_spec("webview") is not None


def _ultima_etiqueta(git: str) -> str | None:
    """La etiqueta vX.Y.Z más alta del repositorio, o None si no se puede saber."""
    salida = subprocess.run(
        [git, "ls-remote", "--tags", "--refs", REPO_GIT], capture_output=True, text=True
    )
    if salida.returncode != 0:
        return None
    versiones = []
    for linea in salida.stdout.splitlines():
        etiqueta = linea.rpartition("refs/tags/")[2]
        if re.fullmatch(r"v\d+\.\d+\.\d+", etiqueta):
            versiones.append(tuple(int(n) for n in etiqueta[1:].split(".")))
    if not versiones:
        return None
    return "v" + ".".join(str(n) for n in max(versiones))


def instalar_skill(home: Path) -> list[Path]:
    """Copia la skill portable a los directorios de los agentes (Claude Code, Codex, opencode y Copilot)."""
    origen = importlib.resources.files("tiza").joinpath("skill", "tiza", "SKILL.md")
    texto = origen.read_text(encoding="utf-8")
    destinos = [
        home / ".claude" / "skills" / "tiza" / "SKILL.md",
        home / ".agents" / "skills" / "tiza" / "SKILL.md",
        home / ".codex" / "skills" / "tiza" / "SKILL.md",
        home / ".config" / "opencode" / "skills" / "tiza" / "SKILL.md",
    ]
    for destino in destinos:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
    return destinos


# --------------------------------------------------------------------------- #
# Aislamiento del agente
# --------------------------------------------------------------------------- #

_MARCAS = {"ok": "[ok]", "falta": "[FALTA]", "aviso": "[aviso]"}


def _home() -> Path:
    return Path.home()


def _sistema() -> str:
    return platform.system()


def _imprimir_comprobaciones(lista: list[aislamiento.Comprobacion]) -> bool:
    for comprobacion in lista:
        print(f"{_MARCAS[comprobacion.estado]} {comprobacion.agente}: {comprobacion.texto}")
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


def _copia_de_seguridad(ruta: Path) -> Path | None:
    if not ruta.is_file():
        return None
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    copia = ruta.with_name(f"{ruta.name}.antes-de-tiza-{marca}")
    shutil.copy2(ruta, copia)
    return copia


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
    if args.global_:
        return _aislar_global(args, servidor)
    carpeta = Path.cwd()
    if carpeta.resolve() == _home().resolve():
        _imprimir_error(
            "CARPETA_NO_VALIDA",
            "esta es tu carpeta personal; para aislar todos tus proyectos usa «tiza aislar --global»",
        )
        return 1
    if not _parece_asignatura(carpeta):
        print(
            f"{carpeta} no parece la carpeta de una asignatura "
            f"(no hay ficheros .md o .html ni {rutas.FICHERO_ASIGNATURA})."
        )
        if not terminal.confirmar("¿Aislar esta carpeta de todos modos?"):
            print("No se ha cambiado nada.", file=sys.stderr)
            return 1
    try:
        resultado = _aislar_carpeta(carpeta, servidor)
    except aislamiento.ErrorAislamiento as exc:
        _imprimir_error(exc.codigo, exc.detalle)
        return 1
    if resultado is None:
        return 1
    _avisar_copilot(servidor)
    return _revisar(args)


def _aplicar_escrituras(escrituras: list[tuple[Path, str, list[str]]]) -> bool:
    """Enseña los cambios, confirma y escribe con copia; True si se aplicaron o no había nada."""
    if not escrituras:
        print("No hay nada que añadir.")
        return True
    print("Se van a hacer estos cambios:")
    for ruta, _texto, cambios in escrituras:
        print(f"  En {ruta}:")
        for cambio in cambios:
            print(f"    - {cambio}")
    if not terminal.confirmar("¿Aplicarlos?"):
        print("No se ha cambiado nada.", file=sys.stderr)
        return False
    for ruta, texto, _cambios in escrituras:
        copia = _copia_de_seguridad(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(texto, encoding="utf-8")
        print(f"Guardado {ruta}" + (f" (copia: {copia.name})" if copia else ""))
    print("Reinicia tu agente para que lea la configuración nueva.")
    return True


def _opencode(
    escrituras: list[tuple[Path, str, list[str]]],
    carpeta: Path,
    home: Path,
    sistema: str,
    donde: str,
    servidor: str | None,
) -> None:
    """Propone crear opencode.jsonc, o avisa de lo que hay que copiar a mano."""
    propuesta = aislamiento.configuracion_opencode(carpeta, home, sistema)
    if propuesta is not None:
        escrituras.append(propuesta)
        return
    # La primera comprobación de revisar_opencode es siempre el webfetch.
    if aislamiento.revisar_opencode(home, carpeta, servidor=servidor)[0].estado != "ok":
        print(
            f"opencode: ya hay configuración {donde} y tiza no la edita; "
            "añade a mano lo que falte de docs/aislamiento.md."
        )


def _aislar_global(args, servidor: str | None) -> int:
    home, sistema = _home(), _sistema()
    escrituras: list[tuple[Path, str, list[str]]] = []
    try:
        if (home / ".claude").is_dir():
            ruta = aislamiento.ruta_claude(home)
            if ruta.exists() and not ruta.is_file():
                raise aislamiento.ErrorAislamiento("AJUSTES_ILEGIBLES", ruta.name)
            nuevo, cambios = aislamiento.fusionar_claude(
                aislamiento.leer_json(ruta), sistema, servidor=servidor
            )
            if cambios:
                texto = json.dumps(nuevo, ensure_ascii=False, indent=2) + "\n"
                escrituras.append((ruta, texto, cambios))
        if (home / ".codex").is_dir():
            ruta = aislamiento.ruta_codex(home)
            if ruta.exists() and not ruta.is_file():
                raise aislamiento.ErrorAislamiento("AJUSTES_ILEGIBLES", ruta.name)
            try:
                actual = ruta.read_text(encoding="utf-8") if ruta.is_file() else ""
            except (OSError, UnicodeDecodeError) as exc:
                raise aislamiento.ErrorAislamiento("AJUSTES_ILEGIBLES", ruta.name) from exc
            texto_codex, cambios, manuales = aislamiento.fusionar_codex(actual)
            for manual in manuales:
                print(f"Cambia a mano en {ruta}: {manual}")
            if texto_codex is not None:
                escrituras.append((ruta, texto_codex, cambios))
    except aislamiento.ErrorAislamiento as exc:
        _imprimir_error(exc.codigo, exc.detalle)
        return 1
    if (home / ".config" / "opencode").is_dir():
        _opencode(escrituras, home / ".config" / "opencode", home, sistema, "global", servidor)
    if not _aplicar_escrituras(escrituras):
        return 1
    _avisar_copilot(servidor)
    return _revisar(args)


def _aislar_carpeta(carpeta: Path, servidor: str | None) -> bool | None:
    """Aislamiento de esta carpeta; None si el docente cancela."""
    home, sistema = _home(), _sistema()
    if carpeta.resolve() == home.resolve():
        raise aislamiento.ErrorAislamiento(
            "CARPETA_NO_VALIDA",
            "no se aísla la propia carpeta personal; usa «tiza aislar --global» o entra en la carpeta de la asignatura",
        )
    escrituras: list[tuple[Path, str, list[str]]] = []
    if (home / ".claude").is_dir():
        ruta = aislamiento.ruta_claude_proyecto(carpeta)
        if ruta.exists() and not ruta.is_file():
            raise aislamiento.ErrorAislamiento("AJUSTES_ILEGIBLES", ruta.name)
        nuevo, cambios = aislamiento.fusionar_claude(
            aislamiento.leer_json(ruta),
            sistema,
            aislamiento.rutas_reabiertas(home, sistema, carpeta),
            servidor=servidor,
        )
        if cambios:
            texto = json.dumps(nuevo, ensure_ascii=False, indent=2) + "\n"
            escrituras.append((ruta, texto, cambios))
    if (home / ".codex").is_dir():
        ruta = aislamiento.ruta_codex_proyecto(carpeta)
        if ruta.exists() and not ruta.is_file():
            raise aislamiento.ErrorAislamiento("AJUSTES_ILEGIBLES", ruta.name)
        try:
            actual = ruta.read_text(encoding="utf-8") if ruta.is_file() else ""
        except (OSError, UnicodeDecodeError) as exc:
            raise aislamiento.ErrorAislamiento("AJUSTES_ILEGIBLES", ruta.name) from exc
        texto_codex, cambios, manuales = aislamiento.fusionar_codex(actual)
        for manual in manuales:
            print(f"Cambia a mano en {ruta}: {manual}")
        if texto_codex is not None:
            escrituras.append((ruta, texto_codex, cambios))
        global_ruta = aislamiento.ruta_codex(home)
        if global_ruta.exists() and not global_ruta.is_file():
            raise aislamiento.ErrorAislamiento("AJUSTES_ILEGIBLES", global_ruta.name)
        try:
            actual_global = global_ruta.read_text(encoding="utf-8") if global_ruta.is_file() else ""
        except (OSError, UnicodeDecodeError) as exc:
            raise aislamiento.ErrorAislamiento("AJUSTES_ILEGIBLES", global_ruta.name) from exc
        confianza, cambios_conf, manuales_conf = aislamiento.fusionar_confianza_codex(
            actual_global, carpeta
        )
        for manual in manuales_conf:
            print(f"Cambia a mano en {global_ruta}: {manual}")
        if confianza is not None:
            escrituras.append((global_ruta, confianza, cambios_conf))
    if (home / ".config" / "opencode").is_dir():
        _opencode(escrituras, carpeta, home, sistema, "en esta carpeta", servidor)
    rutas = [ruta.resolve() for ruta, _texto, _cambios in escrituras]
    if len(set(rutas)) != len(rutas):
        raise aislamiento.ErrorAislamiento(
            "AJUSTES_INESPERADOS", "el aislamiento apunta dos veces al mismo fichero"
        )
    if not _aplicar_escrituras(escrituras):
        return None
    return not any(c.estado == "falta" for c in aislamiento.revisar(home, sistema, carpeta))


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
            pasos: list[dict] = []
            pista = agente.pista_worktree(Path.cwd())
            if pista is not None:
                detalle = pista
                pasos.append({"codigo": "SIN_SESION", "resultado": "fallo", "detalle": pista})
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
    if entorno is not None and cfg.cursos.get(entorno) is None:
        if entorno == "pruebas":
            return None, _fallo(comando, "SIN_CURSO_PRUEBAS", entorno=entorno)
        return None, _fallo(comando, "CURSO_NO_CONFIGURADO", entorno, entorno=entorno)
    return cfg, None


def _mostrar_servidor(cfg) -> None:
    """El docente ve a qué servidor irá la contraseña antes de teclearla."""
    print(
        f"Vas a escribir la contraseña del aula de {urlsplit(cfg.url).hostname} "
        f"(usuario: {cfg.usuario})."
    )


def _estructura_directa(args) -> int:
    comando = "estructura"
    cfg, salida = _configuracion_inicial(args, comando, sin_sesion=True)
    if cfg is None:
        return salida
    if "real" not in cfg.cursos:
        return _fallo(comando, "CURSO_NO_CONFIGURADO", "real")
    for nombre in ("pruebas", "real"):
        curso = cfg.cursos.get(nombre)
        if curso is not None and not terminal.confirmar_destino(nombre, curso):
            return _abortado(comando, nombre, curso)
    _mostrar_servidor(cfg)
    password = terminal.pedir_password()
    try:
        moodle = publicar.autenticar(cfg.url, cfg.usuario, password)
    except ErrorPublicacion as exc:
        return _fallo(comando, exc.codigo, exc.detalle, exc=exc, debug=args.debug)
    documento = sesion.estructura_con(moodle, cfg, Path.cwd(), debug=args.debug)
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
    curso = cfg.cursos[entorno]
    visible = _visibilidad(args)
    solo_fechas = args.solo_fechas
    sin_pruebas = entorno == "real" and "pruebas" not in cfg.cursos
    # Con --solo-fechas no cambia la visibilidad: el aviso de «solo oculto» no aplica.
    if sin_pruebas and visible is not False and not solo_fechas:
        return _fallo(
            comando,
            "SOLO_OCULTO_SIN_PRUEBAS",
            "sin curso de pruebas solo se publica en real con --oculto",
            entorno=entorno,
            curso=curso,
        )
    documentos = []
    for nombre in args.ficheros:
        try:
            documentos.append(contenido.cargar(nombre, raiz=Path.cwd().resolve()))
        except ErrorContenido as exc:
            return _fallo(
                comando,
                exc.codigo,
                terminal.texto_seguro(f"{Path(nombre).name}: {exc.detalle}", 300),
                entorno=entorno,
                curso=curso,
                exc=exc,
                debug=args.debug,
            )
    if solo_fechas:
        # En real, la confirmación enseña las fechas antes y después: se pide tras leer el aula.
        if entorno == "pruebas" and not terminal.confirmar_destino(entorno, curso):
            return _abortado(comando, entorno, curso)
    elif sin_pruebas:
        print(
            "Sin curso de pruebas: no habrá verificación previa y en real solo se publicará oculto."
        )
        if not terminal.confirmar_destino("real", curso):
            return _abortado(comando, entorno, curso)
    else:
        if not terminal.confirmar_destino(entorno, curso):
            return _abortado(comando, entorno, curso)
        if entorno == "real":
            faltan = sesion.puerta_real(Path.cwd(), documentos)
            if faltan:
                return _fallo(
                    comando,
                    "VERIFICACION_PENDIENTE",
                    ", ".join(faltan),
                    entorno=entorno,
                    curso=curso,
                )
    _mostrar_servidor(cfg)
    password = terminal.pedir_password()
    try:
        moodle = publicar.autenticar(cfg.url, cfg.usuario, password)
    except ErrorPublicacion as exc:
        return _fallo(
            comando,
            exc.codigo,
            exc.detalle,
            entorno=entorno,
            curso=curso,
            exc=exc,
            debug=args.debug,
        )
    if solo_fechas and entorno == "real":
        try:
            secciones = moodle.estructura(curso)
        except ErrorPublicacion as exc:
            return _fallo(
                comando,
                exc.codigo,
                exc.detalle,
                entorno=entorno,
                curso=curso,
                exc=exc,
                debug=args.debug,
            )
        codigo = sesion.codigo_solo_fechas(secciones, documentos)
        if codigo is not None:
            return _fallo(comando, codigo, entorno=entorno, curso=curso)
        resumen_real = sesion.resumen_solo_fechas(
            moodle,
            curso,
            _nombre_del_curso(moodle, curso),
            documentos,
            Path.cwd().resolve(),
            secciones,
            debug=args.debug,
        )
        if not terminal.PresenciaTerminal().confirmar_real(resumen_real):
            return _abortado(comando, entorno, curso)
    elif sin_pruebas:
        try:
            secciones = moodle.estructura(curso)
        except ErrorPublicacion as exc:
            return _fallo(
                comando,
                exc.codigo,
                exc.detalle,
                entorno=entorno,
                curso=curso,
                exc=exc,
                debug=args.debug,
            )
        resumen = sesion.ResumenSinPruebas(
            curso=curso,
            nombre_curso=_nombre_del_curso(moodle, curso),
            documentos=tuple(
                sesion.DocumentoBreve(
                    fichero=doc.ruta.name,
                    tipo=doc.tipo,
                    nombre=doc.nombre,
                    existe=publicar.ya_existe(secciones, doc),
                )
                for doc in documentos
            ),
            secciones_nuevas=tuple(publicar.secciones_que_faltan(secciones, documentos)),
        )
        if not terminal.PresenciaTerminal().confirmar_real_sin_pruebas(resumen):
            return _abortado(comando, entorno, curso)
    documento = sesion.publicar_con(
        moodle,
        entorno,
        curso,
        documentos,
        visible,
        Path.cwd(),
        terminal.PresenciaTerminal(),
        debug=args.debug,
        solo_fechas=solo_fechas,
    )
    _escribir(documento)
    return 0 if documento["resultado"] == "ok" else 1


def _nombre_del_curso(moodle, curso: int) -> str | None:
    """Nombre del curso entre los del docente; None si no se puede leer la lista."""
    try:
        return next(
            (
                curso_.get("nombre")
                for curso_ in moodle.mis_cursos()
                if isinstance(curso_, dict) and curso_.get("id") == curso
            ),
            None,
        )
    except ErrorPublicacion:
        return None


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
    peticion = agente.peticion_estructura()
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
        terminal.PresenciaTerminal(),
        minutos=args.minutos,
        preparar=False,
        debug=args.debug,
    )


def _parece_asignatura(carpeta: Path) -> bool:
    if carpeta.resolve() == _home().resolve():
        return False
    return (
        (carpeta / rutas.FICHERO_ASIGNATURA).is_file()
        or (carpeta / rutas.CARPETA_TRABAJO).is_dir()
        or any(
            ruta.suffix.lower() in contenido.EXTENSIONES
            for ruta in carpeta.iterdir()
            if ruta.is_file()
        )
    )


def _empezar(args) -> int:
    """Un solo comando para el docente, con una sola contraseña."""
    comando = "sesion"
    try:
        terminal.exigir_tty()
    except ErrorTerminal as exc:
        return _fallo(comando, exc.codigo, exc.detalle, exc=exc, debug=args.debug)
    try:
        configurado = config.cargar_global() is not None
    except ErrorConfig:
        configurado = False
    if not configurado:
        print("Es la primera vez: vamos a configurar tiza (no se pide la contraseña).")
        if _preguntar_configuracion() != 0:
            return 1
    carpeta = Path.cwd()
    if not _parece_asignatura(carpeta):
        print(
            f"{carpeta} no parece la carpeta de una asignatura "
            f"(no hay ficheros .md o .html ni {rutas.FICHERO_ASIGNATURA})."
        )
        if not terminal.confirmar("¿Abrir la sesión aquí de todos modos?"):
            return _abortado(comando)
    comprobaciones = aislamiento.revisar(_home(), _sistema(), carpeta)
    if not _imprimir_comprobaciones(comprobaciones):
        print("Esta carpeta no está aislada del aula.")
        aislada = False
        if terminal.confirmar("¿Aplicar ahora el aislamiento a esta carpeta?"):
            try:
                resultado = _aislar_carpeta(carpeta, aislamiento.servidor_configurado())
            except aislamiento.ErrorAislamiento as exc:
                return _fallo(comando, exc.codigo, exc.detalle, exc=exc, debug=args.debug)
            if resultado is None:
                return _abortado(comando)
            aislada = resultado
        if not aislada and not terminal.confirmar("¿Seguir sin aislar el agente?"):
            return _abortado(comando)
    return sesion.abrir(
        carpeta,
        terminal.PresenciaTerminal(),
        minutos=args.minutos,
        preparar=True,
        debug=args.debug,
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
    _mostrar_servidor(cfg)
    password = terminal.pedir_password()
    try:
        moodle = publicar.autenticar(cfg.url, cfg.usuario, password)
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
    presencia = terminal.PresenciaTerminal()
    return 0 if sesion.autoprueba_con(moodle, curso, Path.cwd(), presencia, debug=debug) else 1
