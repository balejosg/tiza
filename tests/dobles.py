"""Dobles y datos compartidos por los tests: un aula virtual en memoria, sin red."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tiza import aislamiento, buzon, config, informe, publicacion, rutas
from tiza.estructura import Estructura
from tiza.publicar import (
    CAMPOS_FECHA_CUESTIONARIO,
    CAMPOS_FECHA_TAREA,
    CAMPOS_FINALIZACION_LEIDOS,
    DETALLE_INTENTOS_REPUBLICAR,
    CalificadorAula,
    Contrasena,
    CopiaDescargada,
    ErrorPublicacion,
)

PAGINA = (
    "---\ntipo: pagina\nnombre: Repaso\nseccion: 3\n---\n\n## Repaso\n\n![foto](img/foto.png)\n"
)


def estructura_de(
    secciones: list[dict] | Estructura | MoodleFalso,
) -> Estructura:
    """La estructura tipada del aula, desde las secciones como dicts (o un doble ya montado).

    Si a una sección le falta ``modulos``, se rellena vacía: los tests antiguos no la escriben
    porque les daba igual. No toca las secciones recibidas: el resultado es inmutable.
    """
    if isinstance(secciones, Estructura):
        return secciones
    if isinstance(secciones, MoodleFalso):
        secciones = secciones.secciones
    return Estructura.de_dicts(
        [
            {**seccion, "modulos": seccion.get("modulos", [])}
            if isinstance(seccion, dict)
            else seccion
            for seccion in secciones
        ]
    )


def peticion(entorno: str = "pruebas", visible: bool | None = None, **cambios) -> dict:
    """Una petición del buzón válida; cada test cambia solo lo que mira."""
    datos = {
        "version": buzon.VERSION_PROTOCOLO,
        "id": "b" * 32,
        "comando": "publicar",
        "ficheros": ["pagina.md"],
        "entorno": entorno,
        "visible": visible,
        "solo_fechas": False,
    }
    datos.update(cambios)
    return datos


def dejar_peticion(carpeta: Path, datos: dict) -> Path:
    """Deja una petición en el buzón de la carpeta, como haría el agente."""
    carpeta_buzon = buzon.carpeta_buzon(Path(carpeta) / ".tiza")
    carpeta_buzon.mkdir(parents=True, exist_ok=True)
    ruta = carpeta_buzon / f"{datos['id']}{buzon.SUFIJO_PETICION}"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return ruta


def fecha_en_formulario(campo: str, valor: tuple[int, int, int, int, int]) -> dict:
    anio, mes, dia, hora, minuto = valor
    return {
        f"{campo}[enabled]": "1",
        f"{campo}[year]": str(anio),
        f"{campo}[month]": str(mes),
        f"{campo}[day]": str(dia),
        f"{campo}[hour]": str(hora),
        f"{campo}[minute]": str(minuto),
    }


def tarea_en(carpeta: Path, entrega: str = "2026-10-12", nombre: str = "tarea.md") -> None:
    (carpeta / nombre).write_text(
        "---\ntipo: tarea\nnombre: Problemas\nseccion: 3\napertura: 2026-10-01\n"
        f"entrega: {entrega}\n---\n\nResuelve.\n",
        encoding="utf-8",
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

    def cerrar(self):
        self.cerradas += 1

    def __init__(
        self,
        secciones=None,
        cmid_nuevo: int = 100,
        pluginfiles_ok=True,
        cursos=None,
        secciones_por_curso=None,
        sin_finalizacion=False,
        motor_formulas=True,
        imagenes_servidas=True,
        copia_permitida=True,
        copia=None,
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
        self.motor_formulas = motor_formulas
        self.mover_falla = False
        self.mover_sin_efecto = False
        self.imagenes_servidas = imagenes_servidas
        self.imagenes_esperadas: dict[int, int] = {}
        self.llamadas: list[tuple] = []
        # Calificador por curso (``publicar.CalificadorAula``); sin configurar, uno vacío.
        self.calificadores: dict[int, CalificadorAula] = {}
        # Escrituras en el calificador: (método, *argumentos), en orden, para mirarlas en los tests.
        self.escrituras: list[tuple] = []
        # Fallos simulados: método -> códigos de error; cada llamada gasta el primero.
        self.fallos: dict[str, list[str]] = {}
        self._siguiente_eid = 1000
        self.cerradas = 0  # veces que se cerró la sesión del aula
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
        # Copia de seguridad del curso: sin permiso, ``hacer_copia`` da COPIA_NO_PERMITIDA; los
        # bytes de la copia son los de ``copia`` (por defecto, una sintética sin usuarios).
        self.copia_permitida = copia_permitida
        self.copia = copia
        self.copias_hechas: list[tuple[int, str]] = []  # (curso, nombre en el aula)
        self.copias_de_actividad: list[tuple[int, int]] = []  # (curso, cm) de cada copia de una
        self.copias_en_el_aula: list[str] = []
        self.borradas: list[tuple[str, int]] = []  # lo que ``borrar_copia`` recibió
        self.borrar_copia_falla = False
        self.copia_falla: str | None = None  # código con el que falla ``hacer_copia``
        self.copia_falla_queda = False  # y, al fallar, la copia ya estaba en el aula

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
        return Estructura.de_dicts(self._de(curso_id))

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
        if payload.get("name"):  # como Moodle: el nombre nuevo se ve ya en la estructura del curso
            for secciones in (self.secciones, *self.secciones_por_curso.values()):
                for seccion in secciones:
                    for modulo in seccion["modulos"]:
                        if modulo.get("cmid") == cmid:
                            modulo["nombre"] = payload["name"]

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
            "adjuntos": int(formulario["introattachments"])
            if str(formulario.get("introattachments", "")).isdigit()
            else None,
            "visible": formulario.get("visible"),
            "contexto": self.contextos.get(cmid, 999),
            "fechas": {campo: _fecha_del_formulario(formulario, campo) for campo in _CAMPOS_FECHA},
            "itinerario": {
                "campos": self._campos_de_finalizacion(cmid, formulario),
                "esperada": _fecha_del_formulario(formulario, "completionexpected"),
                "disponibilidad": formulario.get("availabilityconditionsjson", ""),
            },
        }

    def imagenes_de_pregunta(self, cmid, pregunta_id):
        self.llamadas.append(("imagenes_de_pregunta", cmid, pregunta_id))
        encontradas = self.imagenes_esperadas.get(pregunta_id, 0)
        return encontradas, (encontradas if self.imagenes_servidas else 0)

    def calificador(self, curso_id, tocados=None):
        self.llamadas.append(("calificador", curso_id))
        if curso_id in self.calificadores:
            return self.calificadores[curso_id]
        return CalificadorAula(nodos=(), decimal=".")

    def _escribir_calificador(self, metodo, *args):
        self.llamadas.append((metodo, *args))
        self.escrituras.append((metodo, *args))
        pendientes = self.fallos.get(metodo)
        if pendientes:
            raise ErrorPublicacion(pendientes.pop(0))

    def _nuevo_eid(self, prefijo):
        self._siguiente_eid += 1
        return f"{prefijo}{self._siguiente_eid}"

    def crear_categoria(self, curso, nombre, idnumber, padre_eid, peso, visualizacion):
        self._escribir_calificador(
            "crear_categoria", curso, nombre, idnumber, padre_eid, peso, visualizacion
        )
        return self._nuevo_eid("cg")

    def crear_calculado(self, curso, nombre, idnumber, padre_eid, peso, maximo):
        self._escribir_calificador(
            "crear_calculado", curso, nombre, idnumber, padre_eid, peso, maximo
        )
        return self._nuevo_eid("ig")

    def fijar_maximo(self, curso, item_id, maximo):
        self._escribir_calificador("fijar_maximo", curso, item_id, maximo)

    def fijar_peso(self, curso, eid, peso):
        self._escribir_calificador("fijar_peso", curso, eid, peso)

    def fijar_formula(self, curso, item_id, formula, decimal):
        self._escribir_calificador("fijar_formula", curso, item_id, formula, decimal)

    def bloquear_total(self, curso, item_id):
        self._escribir_calificador("bloquear_total", curso, item_id)

    def colocar_actividad(self, curso, cmid, categoria_id, idnumber):
        self._escribir_calificador("colocar_actividad", curso, cmid, categoria_id, idnumber)

    def mover_manual(self, curso, item_id, categoria_eid):
        self._escribir_calificador("mover_manual", curso, item_id, categoria_eid)

    def borrar_nodo(self, curso, eid):
        self._escribir_calificador("borrar_nodo", curso, eid)

    def fijar_total_curso(self, curso, formula, decimal):
        self._escribir_calificador("fijar_total_curso", curso, formula, decimal)

    def motor_de_formulas(self, curso_id):
        self.llamadas.append(("motor_de_formulas", curso_id))
        return self.motor_formulas

    def comprobar_pluginfile(self, url):
        self.llamadas.append(("pluginfile", url))
        self.pluginfiles.append(url)
        return self.pluginfiles_ok

    def mover(self, curso_id, cmid, seccion_id, antes_de):
        """Imita ``cm_move``: antes de ``antes_de`` o al final de la sección; conserva el cmid."""
        self.llamadas.append(("mover", curso_id, cmid, seccion_id, antes_de))
        if self.mover_falla:
            raise ErrorPublicacion("ERROR_MOVER")
        if self.mover_sin_efecto:  # un aula que responde bien y no cambia nada
            return
        secciones = self._de(curso_id)
        origen = next((s for s in secciones for m in s["modulos"] if m["cmid"] == cmid), None)
        destino = next((s for s in secciones if s["id"] == seccion_id), None)
        if origen is None or destino is None:
            raise ErrorPublicacion("ERROR_MOVER")
        modulo = next(m for m in origen["modulos"] if m["cmid"] == cmid)
        origen["modulos"] = [m for m in origen["modulos"] if m["cmid"] != cmid]
        posicion = len(destino["modulos"])
        if antes_de is not None:
            posicion = next(
                (i for i, m in enumerate(destino["modulos"]) if m["cmid"] == antes_de), None
            )
            if posicion is None:
                raise ErrorPublicacion("ERROR_MOVER")
        destino["modulos"].insert(posicion, modulo)

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
            # Lo que la vista previa de la pregunta enseña: enunciado, opciones y parejas.
            self.imagenes_esperadas[self._siguiente_pregunta] = (
                len(pregunta.findall("questiontext/file"))
                + len(pregunta.findall("answer/file"))
                + len(pregunta.findall("subquestion/file"))
            )
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

    # --- Copia de seguridad del curso ---------------------------------------

    def puede_copiar(self, curso_id):
        self.llamadas.append(("puede_copiar", curso_id))
        return self.copia_permitida

    def hacer_copia(self, curso_id, destino, maximo, cmid=None):
        self.llamadas.append(("hacer_copia", curso_id, Path(destino).name))
        if cmid is not None:
            self.copias_de_actividad.append((curso_id, cmid))
        if not self.copia_permitida:
            raise ErrorPublicacion("COPIA_NO_PERMITIDA")
        if self.copia_falla is not None:
            error = ErrorPublicacion(self.copia_falla)
            error.queda_en_el_aula = self.copia_falla_queda
            raise error
        if self.copia is not None:
            datos = self.copia
        elif cmid is not None:
            datos = copia_sintetica_de_actividad(cmid)  # sin secciones y con solo esa actividad
        else:
            datos = copia_sintetica()
        if len(datos) > maximo:
            raise ErrorPublicacion("COPIA_DEMASIADO_GRANDE")
        Path(destino).write_bytes(datos)
        parte = f"{curso_id}" if cmid is None else f"{curso_id}-c{cmid}"
        nombre = f"tiza-{parte}-{1792000000 + len(self.copias_hechas)}-nu.mbz"
        self.copias_hechas.append((curso_id, nombre))
        self.copias_en_el_aula.append(nombre)
        return CopiaDescargada(len(datos), nombre)

    def borrar_copia(self, nombre, curso_id):
        self.llamadas.append(("borrar_copia", nombre, curso_id))
        self.borradas.append((nombre, curso_id))
        if self.borrar_copia_falla:
            raise ErrorPublicacion("ERROR_BORRADO")
        self.copias_en_el_aula.remove(nombre)


def copia_sintetica_de_actividad(
    cmid: int, *, modulo: str = "page", nombre: str = "Una página", curso: int = 1234
) -> bytes:
    """Los bytes de la copia de una sola actividad: 0 secciones y esa actividad."""
    from copia import fabrica

    actividad = fabrica.ActividadFalsa(cmid, modulo, 7, nombre, "<p>Hola</p>")
    return fabrica.construir_mbz([], [actividad], curso=curso)


def copia_sintetica(
    *, users: int = 0, curso: int = 1234, servidor: str = "https://aula.example.org"
) -> bytes:
    """Los bytes de una copia ``.mbz`` válida (una página, una tarea, una etiqueta y un foro)."""
    from copia import fabrica

    secciones, actividades = fabrica.copia_basica()
    return fabrica.construir_mbz(
        secciones, actividades, users=users, curso=curso, servidor=servidor
    )


def aula_con_tarea(entrega_antes=(2026, 10, 10, 23, 59)) -> MoodleFalso:
    """Un aula donde la tarea ya está publicada con otra fecha de entrega."""
    moodle = MoodleFalso()
    moodle.secciones[0]["modulos"] = [{"cmid": 55, "nombre": "Problemas", "tipo": "tarea"}]
    moodle.formularios[55] = {
        "name": "Problemas",
        "visible": "1",
        "introeditor[text]": "<p>Resuelve.</p>",
        **fecha_en_formulario("allowsubmissionsfromdate", (2026, 10, 1, 0, 0)),
        **fecha_en_formulario("duedate", entrega_antes),
    }
    return moodle


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
        copia: bool = True,
        sobrescribir: bool | tuple[bool, ...] = False,  # una respuesta por curso con cambios
        sin_pruebas: bool = True,
        ampliar: tuple[bool, ...] = (),
        cerrar_anterior: bool = False,
        configuracion: tuple[str, str] | None = ("https://aula.ejemplo.org/centro", "profe"),
        actualizar: bool = False,
        carpeta_dudosa: bool = True,
        aislar: bool = True,
        aplicar_aislamiento: bool = True,
        sin_aislar: bool = False,
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
        self._copia = copia
        self._sobrescribir = list(sobrescribir) if isinstance(sobrescribir, tuple) else sobrescribir
        self._sin_pruebas = sin_pruebas
        self._ampliar = list(ampliar)
        self._cerrar_anterior = cerrar_anterior
        self.anteriores_vistas: list[bool] = []  # «atendiendo» de cada sesión anterior
        self.passwords_pedidas: list[tuple[str, str]] = []
        self.cursos_vistos: list[list] = []
        self.resumenes: list = []
        self.resumenes_cortos: list = []
        self.resumenes_orden: list = []
        self.resumenes_calificador: list = []
        self.resumenes_copia: list = []
        self.resumenes_sobrescribir: list = []
        self.sin_pruebas_pedidas: int = 0
        self.avisos: list = []
        self._configuracion = configuracion
        self._actualizar = actualizar
        self._carpeta_dudosa = carpeta_dudosa
        self._aislar = aislar
        self._aplicar_aislamiento = aplicar_aislamiento
        self._sin_aislar = sin_aislar
        self.configuraciones_pedidas: int = 0
        self.actualizaciones_vistas: list[tuple[str, str]] = []
        self.carpetas_dudosas: list[Path] = []
        self.ofertas_de_aislamiento: int = 0
        self.resumenes_aislamiento: list = []
        self.faltas_vistas: list[list] = []

    def acreditar(self, url, usuario):
        self.passwords_pedidas.append((urlsplit(url).hostname, usuario))
        return None if self.password is None else Contrasena(self.password)

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

    def confirmar_orden(self, resumen):
        self.resumenes_orden.append(resumen)
        return self._respuesta_real()

    def confirmar_calificador(self, resumen):
        self.resumenes_calificador.append(resumen)
        return self._respuesta_real()

    def confirmar_copia(self, resumen):
        self.resumenes_copia.append(resumen)
        return self._copia

    def confirmar_sobrescribir(self, resumen):
        self.resumenes_sobrescribir.append(resumen)
        if isinstance(self._sobrescribir, list):
            return self._sobrescribir.pop(0) if self._sobrescribir else False
        return self._sobrescribir

    def confirmar_sin_pruebas(self):
        self.sin_pruebas_pedidas += 1
        return self._sin_pruebas

    def configurar(self, validar=None):
        self.configuraciones_pedidas += 1
        if self._configuracion is not None and validar is not None:
            validar(self._configuracion[0])
        return self._configuracion

    def confirmar_actualizacion(self, nueva, actual):
        self.actualizaciones_vistas.append((nueva, actual))
        return self._actualizar

    def confirmar_carpeta_dudosa(self, carpeta):
        self.carpetas_dudosas.append(carpeta)
        return self._carpeta_dudosa

    def ofrecer_aislamiento(self):
        self.ofertas_de_aislamiento += 1
        return self._aislar

    def confirmar_aislamiento(self, resumen):
        self.resumenes_aislamiento.append(resumen)
        return self._aplicar_aislamiento

    def seguir_sin_aislar(self, faltas):
        self.faltas_vistas.append(list(faltas))
        return self._sin_aislar

    def cerrar_sesion_anterior(self, atendiendo):
        self.anteriores_vistas.append(atendiendo)
        return self._cerrar_anterior

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


def avisos_de_ejemplo() -> dict[str, publicacion.Aviso]:
    """Un aviso de cada código de ``publicacion.AVISOS``, con datos de juguete.

    Lo usan los tests que barren todos los avisos (texto y presencias) para no
    dejar ninguno sin cubrir.
    """
    doc = publicacion.DocumentoResumen("t.md", "pagina", "T", 3, None)
    return {
        "AISLAMIENTO_GUARDADO": publicacion.Aviso.aislamiento_guardado(
            Path("settings.json"), "settings.json.antes-de-tiza-20261024-100000"
        ),
        "AUTOPRUEBA_FALLIDA": publicacion.Aviso.autoprueba_fallida(),
        "ACTIVIDAD_EN_EVALUACION_CERRADA": publicacion.Aviso.actividad_en_evaluacion_cerrada(
            "t.md"
        ),
        "ACTIVIDAD_PENDIENTE": publicacion.Aviso.actividad_pendiente("t.md"),
        "CALIFICANDO_EN_PRUEBAS": publicacion.Aviso.calificando_en_pruebas("calificacion.yaml"),
        "CAMBIADA_EN_EL_AULA": publicacion.Aviso.cambiada_en_el_aula("T"),
        "CAMBIADA_DESDE_LA_PUBLICACION": publicacion.Aviso.cambiada_desde_la_publicacion("T"),
        "CAMBIADO_A_MANO": publicacion.Aviso.cambiado_a_mano("T"),
        "CANCELADA": publicacion.Aviso.cancelada(),
        "CARPETA_NO_AISLADA": publicacion.Aviso.carpeta_no_aislada(),
        "CERRANDO_SESION_ANTERIOR": publicacion.Aviso.cerrando_sesion_anterior(),
        "COMPROBACIONES_DE_AISLAMIENTO": publicacion.Aviso.comprobaciones_de_aislamiento(
            (aislamiento.Comprobacion("Claude Code", "falta", "sin sandbox"),)
        ),
        "CONFIGURACION_GUARDADA": publicacion.Aviso.configuracion_guardada(Path("config.json")),
        "COPIA_QUEDA_EN_EL_AULA": publicacion.Aviso.copia_queda_en_el_aula(),
        "CREANDO_SECCION": publicacion.Aviso.creando_seccion("Tema"),
        "CURSOS_GUARDADOS": publicacion.Aviso.cursos_guardados(Path("tiza.toml")),
        "ELEMENTO_CON_NOTAS_QUITADO": publicacion.Aviso.elemento_con_notas_quitado("T"),
        "ELEMENTO_SIN_ACTIVIDADES": publicacion.Aviso.elemento_sin_actividades("RA1"),
        "CRITERIOS_SIN_PESO": publicacion.Aviso.criterios_sin_peso("RA1"),
        "ERROR_INTERNO": publicacion.Aviso.error_interno("RuntimeError"),
        "ESTRUCTURA_NO_LEIDA": publicacion.Aviso.estructura_no_leida(),
        "EVALUACION_CERRADA_EN_EL_AULA": publicacion.Aviso.evaluacion_cerrada_en_el_aula("T"),
        "FALLO": publicacion.Aviso.fallo("LOGIN_FALLIDO", ""),
        "HUELLA_NO_GUARDADA": publicacion.Aviso.huella_no_guardada("T"),
        "INFORME_NO_ESCRITO": publicacion.Aviso.informe_no_escrito(),
        "MAXIMO_ALCANZADO": publicacion.Aviso.maximo_alcanzado(8),
        "NADA_QUE_CAMBIAR": publicacion.Aviso.nada_que_cambiar(),
        "NOMBRES_NO_DISPONIBLES": publicacion.Aviso.nombres_no_disponibles(),
        "ORDENANDO_EN_PRUEBAS": publicacion.Aviso.ordenando_en_pruebas(
            (publicacion.DocumentoBreve("t.md", "pagina", "T"),)
        ),
        "PANEL_ACTUALIZADO": publicacion.Aviso.panel_actualizado("0.30.0"),
        "PANEL_NO_ACTUALIZADO": publicacion.Aviso.panel_no_actualizado("0.29.2", "actualizar.log"),
        "PETICION_RETIRADA": publicacion.Aviso.peticion_retirada(),
        "PRIMERA_VEZ": publicacion.Aviso.primera_vez(),
        "PUBLICANDO_EN_PRUEBAS": publicacion.Aviso.publicando_en_pruebas((doc,)),
        "QUEDAN_MINUTOS": publicacion.Aviso.quedan_minutos(5),
        "REGISTRO_NO_GUARDADO": publicacion.Aviso.registro_no_guardado("T"),
        "REINICIA_EL_AGENTE": publicacion.Aviso.reinicia_el_agente(),
        "RESULTADO": publicacion.Aviso.resultado(
            informe.crear("publicar", "ok", [], [], [], "pruebas", 1234)
        ),
        "SESION_ABIERTA": publicacion.Aviso.sesion_abierta(
            datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
        ),
        "SESION_ANTERIOR_CERRADA": publicacion.Aviso.sesion_anterior_cerrada(),
        "SESION_CERRADA": publicacion.Aviso.sesion_cerrada("caducada"),
        "SIGUE_FALTANDO": publicacion.Aviso.sigue_faltando(
            (aislamiento.Comprobacion("Claude Code", "falta", "sin sandbox"),)
        ),
        "SIGUE_LA_VERSION_ACTUAL": publicacion.Aviso.sigue_la_version_actual(),
        "TIZA_ACTUALIZADA": publicacion.Aviso.tiza_actualizada(False),
    }
