"""Dobles compartidos por los tests: un aula virtual en memoria, sin red."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tiza import config, rutas
from tiza.publicar import (
    CAMPOS_FECHA_CUESTIONARIO,
    CAMPOS_FECHA_TAREA,
    CAMPOS_FINALIZACION_LEIDOS,
    DETALLE_INTENTOS_REPUBLICAR,
    ErrorPublicacion,
)


def _fecha_del_formulario(formulario: dict, campo: str):
    if formulario.get(f"{campo}[enabled]") != "1":
        return None
    return tuple(
        int(formulario[f"{campo}[{parte}]"]) for parte in ("year", "month", "day", "hour", "minute")
    )


_CAMPOS_FECHA = CAMPOS_FECHA_TAREA + CAMPOS_FECHA_CUESTIONARIO


def enlace_simbolico(enlace: Path, destino: Path) -> None:
    """Crea un enlace simbólico; en Windows sin privilegios se salta el test."""
    try:
        enlace.symlink_to(destino)
    except (OSError, NotImplementedError):
        pytest.skip("este sistema no permite crear enlaces simbólicos")


class MoodleFalso:
    """Doble del adaptador del aula: registra llamadas y no toca la red."""

    def __init__(
        self,
        secciones=None,
        cmid_nuevo: int = 100,
        pluginfiles_ok=True,
        cursos=None,
        secciones_por_curso=None,
        sin_finalizacion=False,
    ):
        self.base_url = "https://aula.example.org/centro"
        self.secciones = (
            secciones
            if secciones is not None
            else [{"numero": 3, "nombre": "Tema 3", "id": 30, "modulos": []}]
        )
        self.cursos = (
            cursos
            if cursos is not None
            else [
                {"id": 5678, "nombre": "Matemáticas 2ºB"},
                {"id": 1234, "nombre": "Pruebas de Mates"},
            ]
        )
        # Con varios cursos reales: las secciones propias de cada curso (los demás usan ``secciones``).
        self.secciones_por_curso: dict[int, list] = dict(secciones_por_curso or {})
        # Moodle: un curso sin finalización ignora sus campos; con alumnos que ya completaron
        # una actividad, esta queda bloqueada y las actualizaciones ya no cambian su finalización.
        self.sin_finalizacion = sin_finalizacion
        self.bloqueadas: set[int] = set()
        self.cmid_nuevo = cmid_nuevo
        self.pluginfiles_ok = pluginfiles_ok
        self.llamadas: list[tuple] = []
        self.subidas: list[tuple[str, bytes]] = []
        # Formulario de cada módulo: como python-moodle, cada payload se fusiona
        # sobre lo que ya había y lo que no se envía se conserva.
        self.formularios: dict[int, dict] = {}
        self.pluginfiles: list[str] = []
        # Cuestionarios: banco por categoría («catid,contextid»), categoría e
        # instancia de cada módulo, huecos, intentos y XML importado.
        self.bancos: dict[str, dict[int, str]] = {}
        self.categorias: dict[int, str] = {}
        self.contextos: dict[int, int] = {}
        self.instancias: dict[int, int] = {}
        self.huecos_quiz: dict[int, list[tuple[int, int]]] = {}
        self.intentos: dict[int, bool] = {}
        self.importados: list[bytes] = []
        self._siguiente_pregunta = 500
        self._siguiente_hueco = 900
        # Actividades H5P: paquete subido, despliegue, librería e intentos.
        self.paquetes_h5p: dict[int, str] = {}
        self.despliegues_h5p: dict[int, bool] = {}
        self.librerias_ausentes: dict[int, bool] = {}
        self.intentos_h5p: dict[int, bool] = {}

    def _de(self, curso_id):
        return self.secciones_por_curso.get(curso_id, self.secciones)

    def crear_seccion(self, curso_id, nombre):
        self.llamadas.append(("crear_seccion", curso_id, nombre))
        secciones = self._de(curso_id)
        numero = max((s["numero"] for s in secciones), default=-1) + 1
        seccion_id = 1000 + numero
        secciones.append({"numero": numero, "nombre": nombre, "id": seccion_id, "modulos": []})
        return seccion_id

    def borrar_seccion(self, curso_id, seccion_id):
        self.llamadas.append(("borrar_seccion", curso_id, seccion_id))
        secciones = self._de(curso_id)
        secciones[:] = [s for s in secciones if s["id"] != seccion_id]

    def estructura(self, curso_id):
        self.llamadas.append(("estructura", curso_id))
        return self._de(curso_id)

    def mis_cursos(self):
        self.llamadas.append(("mis_cursos",))
        return list(self.cursos)

    def contexto(self, curso_id):
        self.llamadas.append(("contexto", curso_id))
        return 999

    def subir(self, curso_id, contexto, ruta, itemid):
        self.llamadas.append(("subir", Path(ruta).name, itemid))
        self.subidas.append((Path(ruta).name, Path(ruta).read_bytes()))
        return itemid, Path(ruta).name

    def crear(self, curso_id, seccion_id, tipo, payload):
        cmid = self.cmid_nuevo
        self.cmid_nuevo += 1
        self.llamadas.append(("crear", curso_id, seccion_id, tipo, payload))
        self.formularios[cmid] = {"visible": "1", **self._admitido(cmid, payload)}
        for seccion in self._de(curso_id):
            if seccion["id"] == seccion_id:
                seccion["modulos"].append({"cmid": cmid, "nombre": payload["name"], "tipo": tipo})
        if tipo == "cuestionario":
            self.categorias[cmid] = f"{cmid + 1000},{900 + cmid}"
            self.contextos[cmid] = 900 + cmid
            self.instancias[cmid] = 5000 + cmid
            self.bancos[self.categorias[cmid]] = {}
            self.huecos_quiz[cmid] = []
        if tipo == "h5p":
            self.contextos[cmid] = 900 + cmid
            self.instancias[cmid] = 5000 + cmid
            self.paquetes_h5p[cmid] = payload.get("packagefile", "")
            self.despliegues_h5p.setdefault(cmid, True)
        return cmid

    def actualizar(self, cmid, payload):
        self.llamadas.append(("actualizar", cmid, payload))
        self.formularios.setdefault(cmid, {"visible": "1"}).update(self._admitido(cmid, payload))

    def _campos_de_finalizacion(self, cmid, formulario):
        if self.sin_finalizacion:  # el formulario no trae ninguno de estos campos
            return dict.fromkeys(CAMPOS_FINALIZACION_LEIDOS)
        campos = {campo: formulario.get(campo) for campo in CAMPOS_FINALIZACION_LEIDOS}
        campos["completion"] = formulario.get("completion", "0")
        campos["completionunlocked"] = "0" if cmid in self.bloqueadas else "1"
        return campos

    def _admitido(self, cmid, payload):
        """Lo que Moodle guardaría: sin finalización o con ella bloqueada, la ignora en silencio."""
        if not (self.sin_finalizacion or cmid in self.bloqueadas):
            return payload
        return {k: v for k, v in payload.items() if not k.startswith("completion")}

    def leer_modulo(self, cmid):
        self.llamadas.append(("leer_modulo", cmid))
        formulario = self.formularios.get(cmid, {})
        return {
            "nombre": formulario.get("name", ""),
            "texto": formulario.get("page[text]") or formulario.get("introeditor[text]", ""),
            "instance": self.instancias.get(cmid, 77),
            "visible": formulario.get("visible"),
            "contexto": self.contextos.get(cmid, 999),
            "fechas": {campo: _fecha_del_formulario(formulario, campo) for campo in _CAMPOS_FECHA},
            "itinerario": {
                "campos": self._campos_de_finalizacion(cmid, formulario),
                "esperada": _fecha_del_formulario(formulario, "completionexpected"),
                "disponibilidad": formulario.get("availabilityconditionsjson", ""),
            },
        }

    def comprobar_pluginfile(self, url):
        self.llamadas.append(("pluginfile", url))
        self.pluginfiles.append(url)
        return self.pluginfiles_ok

    def borrar(self, curso_id, cmid):
        self.llamadas.append(("borrar", cmid))
        for seccion in [
            *self.secciones,
            *(x for l in self.secciones_por_curso.values() for x in l),
        ]:
            seccion["modulos"] = [m for m in seccion["modulos"] if m["cmid"] != cmid]
        categoria = self.categorias.pop(cmid, None)
        if categoria is not None:
            self.bancos.pop(categoria, None)  # las preguntas mueren con el cuestionario
        self.contextos.pop(cmid, None)
        self.instancias.pop(cmid, None)
        self.huecos_quiz.pop(cmid, None)
        self.intentos.pop(cmid, None)
        self.paquetes_h5p.pop(cmid, None)
        self.despliegues_h5p.pop(cmid, None)
        self.librerias_ausentes.pop(cmid, None)
        self.intentos_h5p.pop(cmid, None)

    # --- Cuestionarios: banco de preguntas y huecos -------------------------

    def categoria_cuestionario(self, cmid):
        self.llamadas.append(("categoria_cuestionario", cmid))
        categoria = self.categorias.get(cmid)
        if categoria is None:
            raise ErrorPublicacion("ERROR_IMPORTACION")
        return categoria

    def preguntas_en_categoria(self, cmid, categoria):
        self.llamadas.append(("preguntas_en_categoria", cmid, categoria))
        return set(self.bancos.get(categoria, {}))

    def importar_preguntas(self, curso_id, cmid, categoria, xml):
        self.llamadas.append(("importar_preguntas", cmid, categoria))
        if categoria != self.categorias.get(cmid):
            raise ErrorPublicacion("ERROR_IMPORTACION")
        self.importados.append(xml)
        banco = self.bancos.setdefault(categoria, {})
        nuevas = []
        for pregunta in ET.fromstring(xml).findall("question"):
            self._siguiente_pregunta += 1
            banco[self._siguiente_pregunta] = pregunta.findtext("name/text") or ""
            nuevas.append(self._siguiente_pregunta)
        return nuevas

    def anadir_preguntas(self, cmid, ids):
        self.llamadas.append(("anadir_preguntas", cmid, tuple(ids)))
        for identificador in ids:
            self._siguiente_hueco += 1
            self.huecos_quiz.setdefault(cmid, []).append((self._siguiente_hueco, identificador))

    def huecos(self, cmid):
        self.llamadas.append(("huecos", cmid))
        return list(self.huecos_quiz.get(cmid, []))

    def tiene_intentos(self, cmid):
        self.llamadas.append(("tiene_intentos", cmid))
        return self.intentos.get(cmid, False)

    def quitar_hueco(self, curso_id, quizid, hueco):
        self.llamadas.append(("quitar_hueco", curso_id, quizid, hueco))
        cmid = next((c for c, i in self.instancias.items() if i == quizid), None)
        if cmid is not None and self.intentos.get(cmid):
            raise ErrorPublicacion("CUESTIONARIO_CON_INTENTOS", DETALLE_INTENTOS_REPUBLICAR)
        self.huecos_quiz[cmid] = [par for par in self.huecos_quiz.get(cmid, []) if par[0] != hueco]

    def borrar_preguntas(self, cmid, ids):
        self.llamadas.append(("borrar_preguntas", cmid, tuple(ids)))
        banco = self.bancos.get(self.categorias.get(cmid), {})
        for identificador in ids:
            banco.pop(identificador, None)

    # --- Actividades H5P: despliegue e intentos ------------------------------

    def comprobar_h5p(self, cmid):
        self.llamadas.append(("comprobar_h5p", cmid))
        return self.despliegues_h5p.get(cmid, True)

    def libreria_h5p_ausente(self, cmid, machine_name):
        self.llamadas.append(("libreria_h5p_ausente", cmid, machine_name))
        return self.librerias_ausentes.get(cmid, False)

    def h5p_tiene_intentos(self, cmid):
        self.llamadas.append(("h5p_tiene_intentos", cmid))
        return self.intentos_h5p.get(cmid, False)


class PresenciaFalsa:
    """Doble de la presencia: responde lo que se le dice y anota lo que ve."""

    def __init__(
        self,
        *,
        password: str | None = "secreta",
        cursos: tuple[int, ...] = (),
        reales: tuple[int, ...] | None = None,
        confirmar_cursos: bool = True,
        autoprueba: bool = False,
        real: bool | tuple[bool, ...] = True,  # una respuesta por curso real, en orden
        sin_pruebas: bool = True,
        ampliar: tuple[bool, ...] = (),
    ) -> None:
        self.password = password
        self._cursos = list(cursos)
        self._reales = (
            reales  # lo que responde «elegir_cursos_reales»; None: lo que quede en cursos
        )
        self.reales_vistos: list[tuple[list, int | None]] = []
        self._confirmar_cursos = confirmar_cursos
        self._autoprueba = autoprueba
        self._real = list(real) if isinstance(real, tuple) else real
        self._sin_pruebas = sin_pruebas
        self._ampliar = list(ampliar)
        self.passwords_pedidas: list[tuple[str, str]] = []
        self.cursos_vistos: list[list] = []
        self.resumenes: list = []
        self.resumenes_cortos: list = []
        self.sin_pruebas_pedidas: int = 0
        self.avisos: list = []

    def pedir_password(self, servidor, usuario):
        self.passwords_pedidas.append((servidor, usuario))
        return self.password

    def elegir_curso(self, entorno, cursos, excluir):
        return self._cursos.pop(0) if self._cursos else None

    def elegir_cursos_reales(self, cursos, excluir):
        self.reales_vistos.append((list(cursos), excluir))
        if self._reales is not None:
            return list(self._reales)
        return [self._cursos.pop(0)] if self._cursos else None

    def confirmar_cursos(self, cursos):
        self.cursos_vistos.append(list(cursos))
        return self._confirmar_cursos

    def confirmar_autoprueba(self):
        return self._autoprueba

    def _respuesta_real(self):
        if isinstance(self._real, list):
            return self._real.pop(0) if self._real else False
        return self._real

    def confirmar_real(self, resumen):
        self.resumenes.append(resumen)
        return self._respuesta_real()

    def confirmar_real_sin_pruebas(self, resumen):
        self.resumenes_cortos.append(resumen)
        return self._respuesta_real()

    def confirmar_sin_pruebas(self):
        self.sin_pruebas_pedidas += 1
        return self._sin_pruebas

    def ofrecer_ampliacion(self, minutos, plazo):
        return self._ampliar.pop(0) if self._ampliar else False

    def informar(self, aviso):
        self.avisos.append(aviso)

    def codigos(self) -> list[str]:
        return [aviso.codigo for aviso in self.avisos]


def configurar_aula(carpeta: Path, cursos: dict | None) -> None:
    """Configuración global (aula y usuario) y, si hay cursos, el tiza.toml de la carpeta."""
    config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    if cursos:
        lineas = ["[cursos]"] + [
            f"{clave} = {str(valor).lower() if isinstance(valor, bool) else valor}"
            for clave, valor in cursos.items()
        ]
        Path(carpeta).mkdir(parents=True, exist_ok=True)
        (Path(carpeta) / rutas.FICHERO_ASIGNATURA).write_text(
            "\n".join(lineas) + "\n", encoding="utf-8"
        )
