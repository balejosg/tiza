"""La sesión abierta: su estado y la interfaz que atiende las peticiones del buzón.

Tras el login, la sesión del docente no trabaja con variables sueltas: aquí vive
el aula ya autenticada, la configuración capturada al abrir (alterar ``tiza.toml``
después no puede redirigir la publicación), la presencia, los nombres de curso
(solo para la presencia, nunca a ``.tiza``) y lo que solo existe mientras la
sesión está abierta: el cupo de pruebas, el registro de verificados en memoria y
el directorio privado de las vistas previas.

``SesionAbierta.atender`` valida la petición con el esquema del buzón y devuelve
el informe del esquema cerrado de :mod:`tiza.informe`; es la superficie de la
sesión abierta, la usan ``tiza sesion`` (``sesion._servir``) y los tests.

Lo común con la terminal directa vive en
:func:`tiza.publicacion.publicar_en_cursos`; aquí quedan la lectura de la petición
y lo que solo existe en una sesión: la vigencia de la petición, el cupo y el
registro de verificados en memoria.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import buzon, contenido, estado, informe, publicacion, rutas
from .config import Config
from .contenido import Documento, ErrorContenido
from .publicacion import Presencia
from .publicar import AulaVirtual, ErrorPublicacion

__all__ = [
    "SesionAbierta",
    "estructura_con",
    "registrar",
]


def registrar(documento: dict, carpeta: Path, presencia: Presencia) -> dict:
    """Escribe ``.tiza/informe.json`` y se lo cuenta al docente."""
    try:
        informe.escribir(documento, Path(carpeta) / rutas.CARPETA_TRABAJO)
    except (informe.ErrorInforme, OSError):
        presencia.informar(publicacion.Aviso.informe_no_escrito())
    presencia.informar(publicacion.Aviso.resultado(documento))
    return documento


def estructura_con(aula: AulaVirtual, cfg: Config, carpeta: Path, *, debug: bool = False) -> dict:
    """Con el aula ya abierta: lee y guarda la estructura de los cursos configurados."""
    borrador = informe.Borrador("estructura")
    borrador.paso("LOGIN")
    cursos: dict[str, Any] = {}
    try:
        destinos: list[tuple[str, int]] = []
        if "pruebas" in cfg.cursos:
            destinos.append(("pruebas", cfg.cursos["pruebas"]))
        destinos += [("real", curso_id) for curso_id in cfg.reales]
        for nombre, curso_id in destinos:
            secciones = aula.estructura(curso_id)
            curso = {
                "id": curso_id,
                "secciones": [
                    {
                        "numero": seccion["numero"],
                        "nombre": seccion["nombre"],
                        "id": seccion["id"],
                    }
                    for seccion in secciones
                ],
            }
            if nombre == "real":
                cursos.setdefault("real", []).append(curso)
            else:
                cursos[nombre] = curso
            borrador.paso("ESTRUCTURA", detalle=f"{nombre}: {len(secciones)} secciones")
    except ErrorPublicacion as exc:
        borrador.fallo("ESTRUCTURA", exc.codigo)
        borrador.error(exc.codigo)
        publicacion.depurar(exc, debug)
        return borrador.documento("error")
    try:
        estado.escribir_estructura(Path(carpeta) / rutas.CARPETA_TRABAJO, cursos)
    except estado.ErrorEstado as exc:
        borrador.fallo("ESTRUCTURA", exc.codigo)
        borrador.error(exc.codigo)
        return borrador.documento("error")
    return borrador.documento()


def _ruta_dentro(base: Path, nombre: str) -> Path | None:
    try:
        ruta = (base / nombre).resolve()
    except (OSError, RuntimeError):
        return None
    if not ruta.is_relative_to(base):
        return None
    return ruta


@dataclass
class SesionAbierta:
    """El aula abierta y lo que se acumula entre peticiones de la misma sesión."""

    aula: AulaVirtual
    cfg: Config
    carpeta: Path
    presencia: Presencia
    nombres: Mapping[int, str] = field(default_factory=dict)
    dir_vistas: Path | None = None
    debug: bool = False
    # Solo lo publicado en pruebas en esta sesión: la puerta de real lo lee de aquí,
    # nunca de verificados.json (el agente puede escribir ese fichero).
    verificados: dict[str, estado.Verificado] = field(default_factory=dict)
    cupo: dict = field(default_factory=lambda: {"pruebas": 0})

    def atender(self, peticion: dict) -> dict:
        """Atiende una petición del buzón y devuelve su informe.

        Valida la petición con el esquema del buzón (``buzon.validar_peticion``):
        la interfaz solo acepta lo que garantiza el protocolo, también cuando la
        llama un test.
        """
        buzon.validar_peticion(peticion)
        comando = peticion["comando"]
        base = Path(self.carpeta).resolve()
        if comando == "estructura":
            if not self.cfg.reales:
                return informe.crear(comando, "error", [], [], ["CURSO_NO_CONFIGURADO"])
            documento = estructura_con(self.aula, self.cfg, base, debug=self.debug)
            return registrar(documento, base, self.presencia)
        entorno = peticion["entorno"]
        cursos_de_entorno: tuple[int, ...] = (
            (self.cfg.cursos["pruebas"],)
            if "pruebas" in self.cfg.cursos and entorno == "pruebas"
            else ()
        )
        if entorno == "real":
            cursos_de_entorno = self.cfg.reales
        if not cursos_de_entorno:
            codigo = "SIN_CURSO_PRUEBAS" if entorno == "pruebas" else "CURSO_NO_CONFIGURADO"
            return informe.crear(comando, "error", [], [], [codigo], entorno)
        # En el informe, el curso solo si es uno: con varios, cada fichero lleva el suyo.
        curso = cursos_de_entorno[0] if len(cursos_de_entorno) == 1 else None
        documentos: list[Documento] = []
        for nombre in peticion["ficheros"]:
            ruta = _ruta_dentro(base, nombre)
            if ruta is None:
                return informe.crear(
                    comando, "error", [], [], ["RUTA_FUERA_DE_CARPETA"], entorno, curso
                )
            try:
                doc = contenido.cargar(ruta, raiz=base)
            except ErrorContenido as exc:
                return informe.crear(comando, "error", [], [], [exc.codigo], entorno, curso)
            # Defensa en profundidad: ``cargar`` con ``raiz`` ya lo impide.
            if any(not recurso.ruta.resolve().is_relative_to(base) for recurso in doc.recursos):
                return informe.crear(
                    comando, "error", [], [], ["RUTA_FUERA_DE_CARPETA"], entorno, curso
                )
            documentos.append(doc)
        dir_tiza = base / rutas.CARPETA_TRABAJO
        if entorno == "real":
            documento = publicacion.publicar_en_cursos(
                self.aula,
                self.cfg,
                documentos,
                base,
                self.presencia,
                entorno="real",
                visible=peticion["visible"],
                solo_fechas=peticion["solo_fechas"],
                verificados=self.verificados,
                vigente=lambda: buzon.peticion_pendiente(dir_tiza, peticion["id"]),
                nombres=self.nombres,
                dir_vistas=self.dir_vistas,
                debug=self.debug,
            )
            return registrar(documento, base, self.presencia)
        documento = publicacion.publicar_en_cursos(
            self.aula,
            self.cfg,
            documentos,
            base,
            self.presencia,
            entorno="pruebas",
            visible=peticion["visible"],
            solo_fechas=peticion["solo_fechas"],
            cupo=self.cupo,
            avisar_en_pruebas=True,
            debug=self.debug,
        )
        if documento["resultado"] == "ok":
            for fichero in documento["ficheros"]:
                estado.anotar_verificado(
                    self.verificados, fichero["hash"], fichero["nombre"], fichero["cmid"]
                )
        return registrar(documento, base, self.presencia)
