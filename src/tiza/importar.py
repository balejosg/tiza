"""``tiza importar``: convierte una copia de seguridad de Moodle en ficheros de tiza editables.

Lee la copia con :mod:`tiza.copia` (offline, en memoria) y escribe, por cada página, tarea,
etiqueta, cuestionario o actividad H5P, un fichero ``.html`` o ``.md`` con su frontmatter y el
campo ``origen: {curso, cmid}``, más el resumen ``.tiza/copia.json``. Reglas que no se rompen:

- Nunca sobrescribe nada del docente: cada fichero nuevo se crea con ``x`` y, si ya está, la
  actividad queda como ``YA_IMPORTADO`` sin tocarla.
- Todo lo que se decide (nombres, estados, avisos) se calcula con textos de tiza; de la copia
  solo salen a ``copia.json`` los nombres de actividades y secciones, ya saneados.
- Los nombres de carpetas y ficheros son válidos en Windows, únicos y estables entre
  importaciones (la actividad lleva su ``cmid`` en el nombre).
- Si el curso de la copia no es uno de los cursos reales de ``tiza.toml`` no se escribe nada
  (``COPIA_DE_OTRO_CURSO``), salvo con ``como_nuevas``: entonces los ficheros salen sin
  ``origen`` y se publican como cualquier ``.md`` nuevo.
"""

from __future__ import annotations

import math
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import yaml

from . import config, contenido, estado, filtro, rutas, tipos
from . import copia as lector
from .copia import ActividadCopia, Copia, ErrorCopia, FicheroCopia, PreguntaCopia, SeccionCopia
from .ficheros import fichero_en_carpeta
from .informe import ESTADOS_IMPORTACION, ResumenImportacion
from .lectura.modelo import ErrorLectura

__all__ = [
    "ErrorImportar",
    "ResumenImportacion",
    "importar",
    "nombre_de_recurso",
    "nombre_seguro",
]

ZONA = ZoneInfo("Europe/Madrid")
EXTENSION = {"pagina": ".html", "tarea": ".html", "etiqueta": ".html"}  # el resto, .md
MAX_NOMBRE = 50  # caracteres del nombre limpio en una carpeta o un fichero
MAX_RECURSO = 80  # caracteres del nombre limpio de un recurso (sin la extensión)
_RESERVADOS_WINDOWS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)
_NO_VALIDO_EN_WINDOWS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_REFERENCIA = re.compile(r"@@PLUGINFILE@@/([^\s\"'<>?#]+)")
_TIPOS_PREGUNTA = ("truefalse", "multichoice", "shortanswer", "numerical")
_MAX_PREGUNTAS = 100
_MAX_ENUNCIADO = 5000


class ErrorImportar(Exception):
    """Error de ``tiza importar`` con un código estable y un detalle escrito por tiza."""

    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.detalle = detalle


# --------------------------------------------------------------------------- #
# Nombres
# --------------------------------------------------------------------------- #


def nombre_seguro(texto: str, defecto: str = "sin-nombre", largo: int = MAX_NOMBRE) -> str:
    """Un nombre de carpeta o de fichero: minúsculas, sin tildes, solo letras, cifras y «-».

    Sirve en Windows, macOS y Linux (sin símbolos, sin nombres reservados, sin punto ni
    espacio final) y da lo mismo cada vez que se importa lo mismo.
    """
    limpio = unicodedata.normalize("NFKD", texto)
    limpio = "".join(c for c in limpio if not unicodedata.combining(c)).lower()
    limpio = re.sub(r"[^a-z0-9]+", "-", limpio).strip("-")
    if len(limpio) > largo:
        limpio = limpio[:largo].rstrip("-")
    return limpio or defecto


def nombre_de_recurso(nombre: str) -> str:
    """El nombre de un fichero adjunto, conservando lo que se pueda (``foto.png`` no cambia).

    Letras (también con tilde), cifras, «.», «-» y «_»; lo demás pasa a «_». Nunca empieza por
    punto (sería oculto), ni acaba en punto o espacio, ni es un nombre reservado de Windows.
    """
    limpio = re.sub(r"[^\w.\-]", "_", unicodedata.normalize("NFC", nombre))
    limpio = re.sub(r"_+", "_", limpio)
    cuerpo, punto, extension = limpio.rpartition(".")
    if not punto:
        cuerpo, extension = limpio, ""
    cuerpo = cuerpo.strip("._-") or "recurso"
    if cuerpo.lower() in _RESERVADOS_WINDOWS:
        cuerpo = f"_{cuerpo}"
    extension = extension.strip("._-")[:10]
    return cuerpo[:MAX_RECURSO] + (f".{extension}" if extension else "")


def _texto_seguro(texto: str, defecto: str = "") -> str:
    """Un texto de la copia apto para ``copia.json``: sin controles ni ``<`` ``>``."""
    return estado.nombre_de_seccion(texto) or defecto


# --------------------------------------------------------------------------- #
# Entradas: la copia y la carpeta de destino
# --------------------------------------------------------------------------- #


def _ruta_de_copia(raiz: Path, ruta: str | Path) -> Path:
    """La copia: un ``.mbz`` de la carpeta o uno directamente en ``.tiza/copias/``."""
    try:
        candidata = (raiz / ruta).resolve()
        copias = (raiz / rutas.CARPETA_TRABAJO / estado.CARPETA_COPIAS).resolve()
    except (OSError, RuntimeError):
        raise ErrorLectura(
            "FICHERO_FUERA", "El fichero no está en la carpeta de la asignatura."
        ) from None
    # Única excepción a las carpetas ocultas; solo si ``.tiza/copias`` no es un enlace fuera.
    if (
        copias == raiz / rutas.CARPETA_TRABAJO / estado.CARPETA_COPIAS
        and candidata.parent == copias
    ):
        destino = candidata
    else:
        try:
            destino = fichero_en_carpeta(ruta, raiz, {".mbz"})
        except ErrorLectura as error:
            if error.codigo == "FORMATO_NO_ADMITIDO":
                raise ErrorImportar(
                    "COPIA_FORMATO", "La copia de seguridad de Moodle es un fichero .mbz."
                ) from None
            raise
    if destino.suffix.lower() != ".mbz":
        raise ErrorImportar("COPIA_FORMATO", "La copia de seguridad de Moodle es un fichero .mbz.")
    if not destino.is_file():
        raise ErrorImportar("COPIA_AUSENTE", f"No existe el fichero {_texto_seguro(destino.name)}.")
    return destino


def _carpeta_destino(raiz: Path, destino: str) -> Path:
    """La carpeta donde se escribe: relativa, dentro de la asignatura, ni oculta ni rara."""
    if not isinstance(destino, str) or not destino.strip() or "\\" in destino:
        raise ErrorImportar(
            "DESTINO_NO_VALIDO", "El destino debe ser una carpeta de la asignatura."
        )
    if destino.startswith("/"):
        raise ErrorImportar(
            "DESTINO_NO_VALIDO", "El destino debe ser una carpeta de la asignatura."
        )
    partes = [p for p in destino.split("/") if p not in ("", ".")]
    if not partes or any(
        p.startswith(".")
        or p != p.strip()
        or p.endswith(".")
        or _NO_VALIDO_EN_WINDOWS.search(p)
        or p.split(".")[0].lower() in _RESERVADOS_WINDOWS
        for p in partes
    ):
        raise ErrorImportar(
            "DESTINO_NO_VALIDO", "El destino no puede ser oculto ni llevar símbolos raros."
        )
    try:
        carpeta = raiz.joinpath(*partes).resolve()
        carpeta.relative_to(raiz)
    except (ValueError, OSError, RuntimeError):
        raise ErrorImportar(
            "DESTINO_NO_VALIDO", "El destino no está dentro de la carpeta de la asignatura."
        ) from None
    if carpeta == raiz or (carpeta.exists() and not carpeta.is_dir()):
        raise ErrorImportar("DESTINO_NO_VALIDO", "El destino debe ser una carpeta nueva o vacía.")
    return carpeta


def _comprobar_curso(raiz: Path, curso: int) -> None:
    reales = config.reales_de_carpeta(raiz)
    if curso not in reales:
        raise ErrorImportar(
            "COPIA_DE_OTRO_CURSO",
            "La copia no es de ninguno de los cursos reales de tiza.toml. "
            "Si quieres reutilizarla en otro curso, impórtala con --como-nuevas.",
        )


# --------------------------------------------------------------------------- #
# Escritura sin sobrescribir
# --------------------------------------------------------------------------- #


def _dentro(ruta: Path, base: Path) -> None:
    """Que lo que se va a escribir sigue dentro de ``base`` (por si hay enlaces en el camino)."""
    try:
        ruta.parent.resolve().relative_to(base)
    except (ValueError, OSError, RuntimeError):
        raise ErrorImportar(
            "DESTINO_NO_VALIDO", "El destino no está dentro de la carpeta de la asignatura."
        ) from None


def _crear(ruta: Path, datos: bytes, base: Path) -> bool:
    """Crea ``ruta`` con ``datos``. ``False`` si ya existe: nunca se sobrescribe nada."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    _dentro(ruta, base)
    try:
        fichero = open(ruta, "xb")  # noqa: SIM115
    except FileExistsError:
        return False
    try:
        with fichero:
            fichero.write(datos)
    except BaseException:
        try:
            ruta.unlink()
        except OSError:
            pass
        raise
    return True


# --------------------------------------------------------------------------- #
# Del HTML de la copia al fichero de tiza
# --------------------------------------------------------------------------- #


@dataclass
class _Recurso:
    contenthash: str
    nombre: str  # el nombre ya saneado


def _recursos(actividad: ActividadCopia, html: str) -> tuple[str, list[_Recurso], bool]:
    """Cambia ``@@PLUGINFILE@@/<f>`` por ``recursos/<cmid>/<f limpio>`` y lista lo que extraer.

    Lo que la actividad no trae en la copia se deja sin cambiar (tercer valor ``True``): el
    docente lo verá al comprobar el fichero.
    """
    propios: dict[str, FicheroCopia] = {}
    for fichero in actividad.ficheros:
        if fichero.filearea == "package" or fichero.componente not in (
            "",
            f"mod_{actividad.modulo}",
        ):
            continue
        carpeta = fichero.ruta.strip("/")
        propios.setdefault(f"{carpeta}/{fichero.nombre}" if carpeta else fichero.nombre, fichero)
    usados: dict[str, str] = {}  # clave -> nombre limpio
    ocupados: dict[str, str] = {}  # nombre limpio -> contenthash
    recursos: list[_Recurso] = []
    faltan = False

    def cambiar(m: re.Match[str]) -> str:
        nonlocal faltan
        clave = unquote(m.group(1))
        fichero = propios.get(clave)
        if fichero is None:
            faltan = True
            return m.group(0)
        if clave not in usados:
            base = nombre_de_recurso(fichero.nombre)
            nombre, n = base, 1
            while ocupados.get(nombre, fichero.contenthash) != fichero.contenthash:
                n += 1
                cuerpo, punto, extension = base.rpartition(".")
                nombre = f"{cuerpo}-{n}.{extension}" if punto else f"{base}-{n}"
            usados[clave] = nombre
            if nombre not in ocupados:
                ocupados[nombre] = fichero.contenthash
                recursos.append(_Recurso(fichero.contenthash, nombre))
        return f"recursos/{actividad.cmid}/{usados[clave]}"

    return _REFERENCIA.sub(cambiar, html), recursos, faltan


class _Volcado(yaml.SafeDumper):
    """YAML del frontmatter: los textos de varias líneas, en bloque literal."""


def _texto_yaml(volcado: yaml.SafeDumper, dato: str) -> yaml.ScalarNode:
    estilo = "|" if "\n" in dato else None
    return volcado.represent_scalar("tag:yaml.org,2002:str", dato, style=estilo)


_Volcado.add_representer(str, _texto_yaml)


def _documento(frontmatter: Mapping[str, Any], cuerpo: str) -> str:
    cabecera = yaml.dump(
        dict(frontmatter),
        Dumper=_Volcado,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1_000_000,
    )
    return f"---\n{cabecera}---\n{cuerpo.strip(chr(10))}\n"


def _fecha(momento: datetime | None) -> str | None:
    return momento.astimezone(ZONA).strftime("%Y-%m-%d %H:%M") if momento is not None else None


def _sin_vacios(datos: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in datos.items() if v is not None}


# --- Cuestionarios ---------------------------------------------------------------------


def _motivo(pregunta: PreguntaCopia, que: str = "") -> str:
    tipo = re.sub(r"[^a-z0-9_]", "", pregunta.tipo.lower())[:30] or "desconocida"
    return f"{tipo}({que})" if que else tipo


def _convertir(pregunta: PreguntaCopia) -> dict[str, Any] | str:
    """La pregunta en el formato de tiza, o el motivo (texto de tiza) por el que no se puede."""
    tipo = pregunta.tipo
    if tipo not in _TIPOS_PREGUNTA:
        return _motivo(pregunta)
    textos = [pregunta.texto, pregunta.retroalimentacion] + [
        r.retroalimentacion for r in pregunta.respuestas
    ]
    if any("@@PLUGINFILE@@" in t for t in textos):
        return _motivo(pregunta, "con ficheros")
    if not pregunta.texto.strip() or len(pregunta.texto) > _MAX_ENUNCIADO:
        return _motivo(pregunta, "enunciado")
    resultado: dict[str, Any] = {"enunciado": pregunta.texto}
    respuestas = pregunta.respuestas
    if tipo == "truefalse":
        if len(respuestas) != 2:
            return _motivo(pregunta, "respuestas")
        verdadera, falsa = respuestas
        por_id = {r.id: r for r in respuestas if r.id}
        if (
            pregunta.opciones.get("trueanswer", "").isdigit()
            and pregunta.opciones.get("falseanswer", "").isdigit()
        ):
            verdadera = por_id.get(int(pregunta.opciones["trueanswer"]), verdadera)
            falsa = por_id.get(int(pregunta.opciones["falseanswer"]), falsa)
        if verdadera.fraccion == falsa.fraccion:
            return _motivo(pregunta, "respuestas")
        resultado = {
            "tipo": "verdadero_falso",
            "enunciado": pregunta.texto,
            "respuesta": "verdadero" if verdadera.fraccion > falsa.fraccion else "falso",
        }
    elif tipo == "multichoice":
        if not 2 <= len(respuestas) <= 10 or any(not r.texto.strip() for r in respuestas):
            return _motivo(pregunta, "opciones")
        correctas = sum(1 for r in respuestas if r.fraccion > 0)
        if correctas == 0 or (pregunta.opciones.get("single", "1") == "1" and correctas != 1):
            return _motivo(pregunta, "puntuación parcial")
        opciones = []
        for r in respuestas:
            opcion: dict[str, Any] = {"texto": r.texto}
            if r.fraccion > 0:
                opcion["correcta"] = True
            if r.retroalimentacion.strip():
                opcion["retro"] = r.retroalimentacion
            opciones.append(opcion)
        resultado = {"tipo": "opcion_multiple", "enunciado": pregunta.texto, "opciones": opciones}
    else:
        buenas = [r for r in respuestas if r.fraccion >= 0.9999]
        if any(0 < r.fraccion < 0.9999 for r in respuestas) or not buenas:
            return _motivo(pregunta, "puntuación parcial")
        if tipo == "shortanswer":
            if any(not r.texto.strip() for r in buenas):
                return _motivo(pregunta, "respuestas")
            resultado = {
                "tipo": "respuesta_corta",
                "enunciado": pregunta.texto,
                "aceptadas": [r.texto.strip() for r in buenas],
            }
            if pregunta.opciones.get("usecase") == "1":
                resultado["mayusculas"] = True
        else:
            if len(buenas) != 1:
                return _motivo(pregunta, "respuestas")
            try:
                valor = float(buenas[0].texto.strip())
            except ValueError:
                return _motivo(pregunta, "valor")
            if not math.isfinite(valor):
                return _motivo(pregunta, "valor")
            resultado = {"tipo": "numerica", "enunciado": pregunta.texto, "valor": valor}
            if buenas[0].tolerancia > 0:
                resultado["tolerancia"] = buenas[0].tolerancia
    if pregunta.retroalimentacion.strip():
        resultado["retro"] = pregunta.retroalimentacion
    return resultado


def _preguntas(actividad: ActividadCopia) -> tuple[list[dict[str, Any]], list[str]]:
    """Las preguntas convertidas y los motivos (sin repetir, en orden) de las que no se pueden."""
    convertidas: list[dict[str, Any]] = []
    motivos: list[str] = []
    for pregunta in actividad.preguntas:
        resultado = _convertir(pregunta)
        if isinstance(resultado, str):
            if resultado not in motivos:
                motivos.append(resultado)
        else:
            convertidas.append(resultado)
    if not actividad.preguntas:
        motivos.append("sin_preguntas")
    elif len(actividad.preguntas) > _MAX_PREGUNTAS:
        motivos.append(f"más_de_{_MAX_PREGUNTAS}_preguntas")
    return convertidas, motivos


# --------------------------------------------------------------------------- #
# El plan de cada actividad
# --------------------------------------------------------------------------- #


@dataclass
class _Entrada:
    """Una actividad de ``copia.json`` mientras se importa."""

    cmid: int
    modulo: str
    seccion: int
    nombre: str
    fichero: str | None = None
    estado: str = "IMPORTADA"
    detalle: str | None = None
    huella_aula: str | None = None

    def a_dict(self) -> dict[str, Any]:
        return {
            "cmid": self.cmid,
            "modulo": self.modulo,
            "seccion": self.seccion,
            "nombre": self.nombre,
            "fichero": self.fichero,
            "estado": self.estado,
            "detalle": self.detalle,
            "huella_aula": self.huella_aula,
        }


def _frontmatter(
    actividad: ActividadCopia,
    tipo: str,
    seccion: SeccionCopia,
    curso: int,
    como_nuevas: bool,
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    nombre = _texto_seguro(actividad.nombre, f"Actividad {actividad.cmid}")
    datos: dict[str, Any] = {
        "tipo": tipo,
        "nombre": nombre,
        "seccion": _texto_seguro(seccion.nombre) or seccion.numero,
    }
    if not como_nuevas:
        datos["origen"] = {"curso": curso, "cmid": actividad.cmid}
    if tipo == "tarea":
        fechas = actividad.fechas
        datos.update(
            _sin_vacios(
                {
                    "apertura": _fecha(fechas.get("allowsubmissionsfromdate")),
                    "entrega": _fecha(fechas.get("duedate")),
                    "limite": _fecha(fechas.get("cutoffdate")),
                }
            )
        )
    elif tipo == "cuestionario":
        fechas = actividad.fechas
        datos.update(
            _sin_vacios(
                {
                    "apertura": _fecha(fechas.get("timeopen")),
                    "cierre": _fecha(fechas.get("timeclose")),
                }
            )
        )
    datos.update(extra)
    return datos


def _detalle_de_carga(ruta: Path, raiz: Path) -> tuple[str, str | None]:
    """(estado, detalle) de un fichero recién escrito, según lo que diga ``contenido.cargar``."""
    try:
        contenido.cargar(ruta, raiz=raiz)
    except contenido.ErrorContenido as error:
        if error.codigo == "HTML_PELIGROSO":
            return "HTML_NO_ADMITIDO", _texto_seguro(
                f"El filtro de tiza no admite: {error.detalle}"
            )
        texto = _texto_seguro(error.detalle)
        return "IMPORTADA", f"Al comprobarlo, tiza avisa de {error.codigo}: {texto}"[:255]
    return "IMPORTADA", None


def _previa(dir_tiza: Path, curso: int, como_nuevas: bool) -> dict[int, dict]:
    """Las actividades de la importación anterior de este mismo curso, por cmid."""
    if como_nuevas:
        return {}
    try:
        anterior = estado.cargar_copia(dir_tiza)
    except estado.ErrorEstado:
        return {}
    if anterior["curso"] != curso or anterior["como_nuevas"]:
        return {}
    return {a["cmid"]: a for a in anterior["actividades"]}


# --------------------------------------------------------------------------- #
# La importación
# --------------------------------------------------------------------------- #


def importar(
    carpeta: str | Path,
    copia: str | Path,
    destino: str = "aula",
    como_nuevas: bool = False,
) -> ResumenImportacion:
    """Importa la copia ``copia`` a ficheros de tiza en ``<carpeta>/<destino>/``.

    Offline. Devuelve el resumen validado; el detalle de cada actividad queda en
    ``.tiza/copia.json``. Lanza ``ErrorImportar``, ``ErrorCopia`` (la copia no vale),
    ``ErrorLectura`` (la ruta de la copia no vale) o ``ErrorConfig`` (``tiza.toml`` no vale).
    Todo lo que se comprueba antes de escribir (copia, curso, destino) falla sin escribir nada.
    """
    raiz = Path(carpeta).resolve()
    ruta_copia = _ruta_de_copia(raiz, copia)
    base = _carpeta_destino(raiz, destino)
    datos = lector.abrir_copia(ruta_copia)
    if not como_nuevas:
        _comprobar_curso(raiz, datos.curso_original)
    secciones = {s.id: s for s in datos.secciones}
    for actividad in datos.actividades:
        if actividad.seccion_id not in secciones:
            raise ErrorCopia("COPIA_NO_VALIDA", "Una actividad apunta a una sección que no está.")

    dir_tiza = raiz / rutas.CARPETA_TRABAJO
    previa = _previa(dir_tiza, datos.curso_original, como_nuevas)
    entradas = []
    try:
        for actividad in datos.actividades:
            entradas.append(
                _importar_actividad(
                    datos,
                    actividad,
                    secciones[actividad.seccion_id],
                    raiz,
                    base,
                    dir_tiza,
                    previa.get(actividad.cmid),
                    como_nuevas,
                )
            )
        escrito = estado.escribir_copia(
            dir_tiza,
            {
                "version": 1,
                "curso": datos.curso_original,
                "moodle": _texto_seguro(datos.moodle),
                "fecha_importacion": datetime.now(UTC).isoformat(timespec="seconds"),
                "como_nuevas": como_nuevas,
                "secciones": [
                    {
                        "numero": s.numero,
                        "nombre": _texto_seguro(s.nombre),
                        "resumen_html_presente": bool(s.resumen_html.strip()),
                    }
                    for s in datos.secciones
                ],
                "actividades": [e.a_dict() for e in entradas],
            },
        )
    except (OSError, estado.ErrorEstado):
        raise ErrorImportar(
            "IMPORTACION_NO_ESCRIBIBLE", "No se pudo escribir en la carpeta de la asignatura."
        ) from None
    recuento = {e: 0 for e in ESTADOS_IMPORTACION}
    for entrada in entradas:
        recuento[entrada.estado] += 1
    return ResumenImportacion(
        copia=escrito.relative_to(raiz).as_posix(),
        curso=datos.curso_original,
        como_nuevas=como_nuevas,
        actividades=len(entradas),
        estados=recuento,
    )


def _importar_actividad(
    datos: Copia,
    actividad: ActividadCopia,
    seccion: SeccionCopia,
    raiz: Path,
    base: Path,
    dir_tiza: Path,
    previa: dict | None,
    como_nuevas: bool,
) -> _Entrada:
    entrada = _Entrada(
        cmid=actividad.cmid,
        modulo=actividad.modulo,
        seccion=seccion.numero,
        nombre=_texto_seguro(actividad.nombre, f"Actividad {actividad.cmid}"),
    )
    tipo = tipos.de_modulo(actividad.modulo)
    if tipo is None:
        entrada.estado = "TIPO_NO_GESTIONADO"
        entrada.detalle = "tiza no gestiona este tipo de actividad: no se importa."
        return entrada
    extension = EXTENSION.get(tipo, ".md")
    carpeta_seccion = base / f"{seccion.numero:02d}-{nombre_seguro(seccion.nombre)}"
    ruta = carpeta_seccion / f"{nombre_seguro(actividad.nombre)}-{actividad.cmid}{extension}"
    anterior = previa["fichero"] if previa and previa["fichero"] else None
    if anterior is not None and os.path.lexists(raiz / anterior):
        ruta = raiz / anterior
    existe = os.path.lexists(ruta)

    html, recursos, faltan = _recursos(actividad, actividad.html)
    extra: dict[str, Any] = {}
    if tipo == "cuestionario":
        preguntas, motivos = _preguntas(actividad)
        if motivos:
            entrada.estado = "PREGUNTAS_NO_ADMITIDAS"
            entrada.detalle = _texto_seguro(
                "Tipos de pregunta que tiza no admite: " + ", ".join(motivos)
            )
            return entrada
        extra["preguntas"] = preguntas
    elif tipo == "h5p":
        paquete = next(
            (f for f in actividad.ficheros if f.contenthash == actividad.paquete_h5p), None
        )
        if paquete is None or actividad.paquete_h5p not in datos.recursos:
            entrada.estado = "TIPO_NO_GESTIONADO"
            entrada.detalle = "La actividad H5P no trae su paquete .h5p en la copia."
            return entrada
        nombre_paquete = nombre_de_recurso(paquete.nombre)
        if not nombre_paquete.lower().endswith(".h5p"):
            nombre_paquete += ".h5p"
        recursos.append(_Recurso(paquete.contenthash, nombre_paquete))
        extra["paquete"] = f"recursos/{actividad.cmid}/{nombre_paquete}"

    # Lo que hay en el aula según esta copia (para detectar cambios hechos después).
    huella = None
    if not como_nuevas:
        huella = tipos.huella_aula(actividad.nombre, actividad.html, actividad.fechas)
    entrada.huella_aula = huella
    entrada.fichero = ruta.relative_to(raiz).as_posix() if existe else None
    if existe:
        entrada.estado = "YA_IMPORTADO"
        guardada = previa["huella_aula"] if previa else None
        if huella is not None and guardada is not None and guardada != huella:
            entrada.estado = "CAMBIADA_DESDE_LA_IMPORTACION"
            _extraer(datos, recursos, ruta.parent, actividad.cmid, raiz)
            estado.guardar_version_de_copia(dir_tiza, actividad.cmid, html)
            entrada.detalle = (
                "El nombre, el texto o las fechas cambiaron en el aula desde la importación. "
                "Tu fichero no se ha tocado; la versión nueva está en "
                f".tiza/copia/{actividad.cmid}.html."
            )
        return entrada

    frontmatter = _frontmatter(actividad, tipo, seccion, datos.curso_original, como_nuevas, extra)
    aviso = None
    try:
        filtro.analizar(html)
    except filtro.HtmlPeligroso as exc:
        aviso = _texto_seguro(f"El filtro de tiza no admite: {exc.detalle}")
    sin_fichero = _extraer(datos, recursos, ruta.parent, actividad.cmid, base)
    entrada.fichero = ruta.relative_to(raiz).as_posix()
    if not _crear(ruta, _documento(frontmatter, html).encode("utf-8"), base):
        entrada.estado = "YA_IMPORTADO"
        return entrada
    if aviso is not None:
        entrada.estado, entrada.detalle = "HTML_NO_ADMITIDO", aviso
    else:
        entrada.estado, entrada.detalle = _detalle_de_carga(ruta, raiz)
    if (faltan or sin_fichero) and entrada.detalle is None:
        entrada.detalle = "Falta en la copia algún fichero que la actividad usa."
    return entrada


def _extraer(
    datos: Copia, recursos: list[_Recurso], carpeta: Path, cmid: int, limite: Path
) -> bool:
    """Escribe en ``recursos/<cmid>/`` lo que falte; un fichero que ya está no se toca.

    Devuelve ``True`` si algún recurso no viene en la copia.
    """
    faltan = False
    for recurso in recursos:
        if recurso.contenthash not in datos.recursos:
            faltan = True
            continue
        destino = carpeta / "recursos" / str(cmid) / recurso.nombre
        if os.path.lexists(destino):
            continue
        _crear(destino, lector.leer_recurso(datos, recurso.contenthash), limite)
    return faltan
