"""``tiza calificador`` de punta a punta: buzón, sesión, confirmación, aula doblada e informe.

El aula es ``AulaViva``: un ``MoodleFalso`` cuyo calificador reacciona a las escrituras (lo justo
para que lo montado converja), así que lo que se comprueba es el flujo completo: leer, reconciliar,
confirmar, ejecutar, releer, segunda pasada y huellas.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from dobles import MoodleFalso, PresenciaFalsa, dejar_peticion, peticion
from tiza import agente, buzon, config, estado, informe, mensajes, publicacion, sesion_abierta
from tiza.calificacion.carpeta import documentos_de_la_carpeta
from tiza.publicar import CalificadorAula, ErrorPublicacion, NodoAula

URL = "https://aula.ejemplo.org/centro"
CFG = config.Config(url=URL, usuario="profe", cursos={"pruebas": 1234}, reales=(5678,))
CFG_DOS = config.Config(url=URL, usuario="profe", cursos={"pruebas": 1234}, reales=(101, 102))
CURSO = 1234

ESQUEMA = """\
organizacion: elementos
elementos:
  - {id: RA1, nombre: Redes, peso: 60}
  - {id: RA2, nombre: Sistemas, peso: 40}
evaluaciones:
  - {nombre: 1.ª evaluación, secciones: [1]}
  - {nombre: 2.ª evaluación, secciones: [2]}
final: {de: elementos}
"""

# nombre, sección, cmid, evalua
ACTIVIDADES = (
    ("a", 1, 11, {"RA1": 60}),
    ("d", 1, 12, {"RA1": 40, "RA2": 50}),
    ("c", 2, 13, {"RA2": 50}),
)
CURSO_EID = "cg1"


def carpeta_fp(tmp_path: Path, esquema: str = ESQUEMA, actividades=ACTIVIDADES) -> Path:
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir(exist_ok=True)
    for nombre, seccion, _cmid, evalua in actividades:
        mapa = ", ".join(f"{clave}: {peso}" for clave, peso in evalua.items())
        (carpeta / f"{nombre}.md").write_text(
            f"---\ntipo: tarea\nnombre: {nombre}\nseccion: {seccion}\n"
            f"apertura: 2026-10-01\nentrega: 2026-10-10\nevalua: {{{mapa}}}\n---\n\nTexto\n",
            encoding="utf-8",
        )
    (carpeta / "calificacion.yaml").write_text(esquema, encoding="utf-8")
    return carpeta.resolve()


def nodo(eid, idnumber, clase, padre, **kw) -> NodoAula:
    base = dict(
        eid=eid,
        item_id=int(eid[2:]),
        idnumber=idnumber,
        clase=clase,
        nombre=kw.pop("nombre", idnumber or "sin nombre"),
        padre_eid=padre,
        peso=None,
        sobrescrito=False,
        bloqueado=False,
        tiene_notas=False,
        formula=None,
        maximo=None,
        cmid=None,
    )
    base.update(kw)
    return NodoAula(**base)  # type: ignore[arg-type]


def nodos_de_actividades(actividades=ACTIVIDADES, padre: str = CURSO_EID, **kw) -> list[NodoAula]:
    return [
        nodo(f"ig{100 + cmid}", "", "actividad", padre, cmid=cmid, maximo=10.0, **kw)
        for _, _, cmid, _ in actividades
    ]


def secciones_de(actividades=ACTIVIDADES) -> list[dict]:
    secciones = []
    for numero in sorted({seccion for _, seccion, _, _ in actividades}):
        secciones.append(
            {
                "numero": numero,
                "nombre": f"Tema {numero}",
                "id": 10 * numero,
                "modulos": [
                    {"cmid": cmid, "nombre": nombre, "tipo": "tarea"}
                    for nombre, seccion, cmid, _ in actividades
                    if seccion == numero
                ],
            }
        )
    return secciones


class AulaViva(MoodleFalso):
    """El calificador de un curso, que cambia con lo que se le escribe."""

    def __init__(self, extra: list[NodoAula] | None = None, *, perturbar: bool = False, **kw):
        super().__init__(secciones=kw.pop("secciones", secciones_de()), **kw)
        base = [nodo(CURSO_EID, "", "curso", None, nombre="Curso")]
        self.nodos: dict[str, NodoAula] = {
            n.eid: n for n in [*base, *(nodos_de_actividades() if extra is None else extra)]
        }
        self.decimal = "."
        self.perturbar = perturbar  # Moodle reescala un peso hermano al guardar el de RA2
        self.relecturas: list[set[str] | None] = []  # los ``tocados`` de cada lectura

    # -- lectura ----------------------------------------------------------

    def calificador(self, curso_id, tocados=None):
        self.llamadas.append(("calificador", curso_id))
        self.relecturas.append(None if tocados is None else set(tocados))
        for _ in range(6):  # el máximo de una categoría Natural es la suma de sus hijos
            for n in list(self.nodos.values()):
                if n.clase == "categoria":
                    hijos = [h for h in self.nodos.values() if h.padre_eid == n.eid]
                    self.nodos[n.eid] = dataclasses.replace(
                        n, maximo=sum(h.maximo or 0.0 for h in hijos)
                    )
        return CalificadorAula(nodos=tuple(self.nodos.values()), decimal=self.decimal)

    def por_id(self, idnumber: str) -> NodoAula:
        return next(n for n in self.nodos.values() if n.idnumber == idnumber)

    def _cambiar(self, eid: str | None, item_id: int | None, **kw) -> None:
        n = next(
            n
            for n in self.nodos.values()
            if (eid is not None and n.eid == eid) or (item_id is not None and n.item_id == item_id)
        )
        self.nodos[n.eid] = dataclasses.replace(n, **kw)

    def _crear(self, eid, idnumber, clase, nombre, padre_eid, peso, maximo=None) -> str:
        self.nodos[eid] = nodo(
            eid,
            idnumber,
            clase,
            padre_eid or CURSO_EID,
            nombre=nombre,
            peso=peso,
            sobrescrito=peso is not None,
            maximo=maximo,
        )
        return eid

    # -- escritura --------------------------------------------------------

    def crear_categoria(self, curso, nombre, idnumber, padre_eid, peso, visualizacion):
        eid = super().crear_categoria(curso, nombre, idnumber, padre_eid, peso, visualizacion)
        return self._crear(eid, idnumber, "categoria", nombre, padre_eid, peso)

    def crear_calculado(self, curso, nombre, idnumber, padre_eid, peso, maximo):
        eid = super().crear_calculado(curso, nombre, idnumber, padre_eid, peso, maximo)
        return self._crear(eid, idnumber, "calculado", nombre, padre_eid, peso, maximo)

    def fijar_maximo(self, curso, item_id, maximo):
        super().fijar_maximo(curso, item_id, maximo)
        self._cambiar(None, item_id, maximo=maximo)

    def fijar_peso(self, curso, eid, peso):
        super().fijar_peso(curso, eid, peso)
        self._cambiar(eid, None, peso=peso, sobrescrito=True)
        if self.perturbar and self.nodos[eid].idnumber == "TZ_E_RA2":
            self.perturbar = False  # una sola vez: Moodle reescala a RA1 al guardar RA2
            self._cambiar(self.por_id("TZ_E_RA1").eid, None, peso=1.0)

    def fijar_formula(self, curso, item_id, formula, decimal):
        super().fijar_formula(curso, item_id, formula, decimal)
        self._cambiar(None, item_id, formula=formula)

    def bloquear_total(self, curso, item_id):
        super().bloquear_total(curso, item_id)
        self._cambiar(None, item_id, bloqueado=True)

    def colocar_actividad(self, curso, cmid, categoria_id, idnumber):
        super().colocar_actividad(curso, cmid, categoria_id, idnumber)
        actual = next(n for n in self.nodos.values() if n.cmid == cmid)
        self.nodos[actual.eid] = dataclasses.replace(
            actual,
            padre_eid=f"cg{categoria_id}",
            peso=None,
            sobrescrito=False,
            idnumber=idnumber or actual.idnumber,
        )

    def mover_manual(self, curso, item_id, categoria_eid):
        super().mover_manual(curso, item_id, categoria_eid)
        self._cambiar(None, item_id, padre_eid=categoria_eid)

    def borrar_nodo(self, curso, eid):
        super().borrar_nodo(curso, eid)
        del self.nodos[eid]

    def fijar_total_curso(self, curso, formula, decimal):
        super().fijar_total_curso(curso, formula, decimal)
        self._cambiar(CURSO_EID, None, formula=formula)

    # -- para mirar -------------------------------------------------------

    def metodos(self) -> list[str]:
        return [e[0] for e in self.escrituras]

    def objetivos_en(self, raiz: str) -> list[tuple]:
        """Las escrituras que tocan algo de dentro de ``raiz`` (él y todo lo que cuelga)."""
        dentro = {self.por_id(raiz).eid}
        cambio = True
        while cambio:
            cambio = False
            for n in self.nodos.values():
                if n.padre_eid in dentro and n.eid not in dentro:
                    dentro.add(n.eid)
                    cambio = True
        ids = {int(e[2:]) for e in dentro}
        tocadas = []
        for escritura in self.escrituras:
            metodo, destino = escritura[0], escritura[2] if len(escritura) > 2 else None
            if metodo in ("fijar_peso", "borrar_nodo") and destino in dentro:
                tocadas.append(escritura)
            elif metodo in ("fijar_maximo", "fijar_formula", "bloquear_total", "mover_manual"):
                if destino in ids:
                    tocadas.append(escritura)
            elif (
                metodo in ("crear_categoria", "crear_calculado")
                and escritura[4] in dentro
                or metodo == "colocar_actividad"
                and f"cg{escritura[3]}" in dentro
            ):
                tocadas.append(escritura)
        return tocadas


def pedir(carpeta: Path, entorno: str = "pruebas", fichero: str = "calificacion.yaml") -> dict:
    datos = peticion(entorno, None, comando="calificador", ficheros=[fichero])
    if entorno == "real":
        dejar_peticion(carpeta, datos)
    return datos


def atender(datos, moodle, carpeta, presencia=None, cfg=CFG, **opciones) -> dict:
    sesion = sesion_abierta.SesionAbierta(
        moodle, cfg, carpeta, presencia or PresenciaFalsa(), **opciones
    )
    return sesion.atender(datos)


def acciones(documento: dict) -> dict[str, str | None]:
    return {f["nombre"]: f["accion"] for f in documento["ficheros"]}


def pasos(documento: dict, codigo: str) -> list[dict]:
    return [p for p in documento["pasos"] if p["codigo"] == codigo]


# --------------------------------------------------------------------------- #
# Escena 1: un curso vacío
# --------------------------------------------------------------------------- #


def test_calificador_fp_curso_vacio(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    documento = atender(pedir(carpeta), moodle, carpeta)

    assert documento["comando"] == "calificador"
    assert documento["resultado"] == "ok"
    assert documento["curso"] == CURSO
    assert acciones(documento) == {"a.md": "colocada", "c.md": "colocada", "d.md": "colocada"}
    metodos = moodle.metodos()
    creadas = [e[3] for e in moodle.escrituras if e[0] in ("crear_categoria", "crear_calculado")]
    assert {"TZ_TIZA", "TZ_E_RA1", "TZ_E_RA2", "TZ_VISTA", "TZ_V_1", "TZ_V_2"} <= set(creadas)
    assert metodos.count("crear_calculado") == 5  # las copias
    assert metodos.count("colocar_actividad") == 3
    # TZ_TIZA cuelga del curso y pesa 100 (no había calificador anterior)
    [tiza] = [e for e in moodle.escrituras if e[0] == "crear_categoria" and e[3] == "TZ_TIZA"]
    assert tiza[4] == CURSO_EID and tiza[5] == 100.0
    # las fórmulas van después de crear todo
    assert max(i for i, m in enumerate(metodos) if m.startswith("crear_")) < min(
        i for i, m in enumerate(metodos) if m == "fijar_formula"
    )
    assert all(e[4] == "." for e in moodle.escrituras if e[0] == "fijar_formula")
    assert all(n.formula for n in moodle.nodos.values() if n.clase == "calculado")
    assert "fijar_total_curso" in metodos  # sin anterior, el total del curso en porcentaje
    # el informe lo cuenta con códigos y recuentos
    assert pasos(documento, "CALIFICADOR")[0]["resultado"] == "ok"
    assert pasos(documento, "CALIFICADOR_COLOCAR")[0]["detalle"] == "3"


def test_las_relecturas_tras_escribir_dicen_lo_tocado(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva(perturbar=True)
    atender(pedir(carpeta), moodle, carpeta)
    primera, *relecturas = moodle.relecturas
    assert primera is None  # la lectura inicial es completa
    assert relecturas and all(r is not None for r in relecturas)
    pesados = {e[2] for e in moodle.escrituras if e[0] == "fijar_peso"}
    colocadas = {f"ig{n.item_id}" for n in moodle.nodos.values() if n.clase == "actividad"}
    assert pesados and pesados <= set().union(*relecturas)
    assert colocadas <= set().union(*relecturas)


def test_calificador_vuelve_a_dejarlo_igual_sin_tocar_nada(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    atender(pedir(carpeta), moodle, carpeta)
    moodle.escrituras.clear()
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert moodle.escrituras == []
    assert documento["resultado"] == "ok"
    assert acciones(documento) == {"a.md": "ya_estaba", "c.md": "ya_estaba", "d.md": "ya_estaba"}
    assert pasos(documento, "CALIFICADOR")[0]["detalle"] == "sin cambios"


def test_las_huellas_se_guardan_tras_montar(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    atender(pedir(carpeta), moodle, carpeta)
    huellas = estado.cargar_huellas(carpeta / ".tiza", CURSO)
    assert {"TZ_TIZA", "TZ_E_RA1", "TZ_V_1", "TZ_CURSO"} <= set(huellas)
    assert estado.cargar_huellas(carpeta / ".tiza", 9999) == {}


# --------------------------------------------------------------------------- #
# Dos pasadas
# --------------------------------------------------------------------------- #


def test_calificador_segunda_pasada(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva(perturbar=True)  # Moodle reescala el peso de RA1 al guardar el de RA2
    moodle.fallos["fijar_formula"] = ["FORMULA_NO_VALIDA"]  # y rechaza la primera fórmula
    documento = atender(pedir(carpeta), moodle, carpeta)

    assert documento["resultado"] == "ok", documento
    assert moodle.por_id("TZ_E_RA1").peso == 60.0
    assert moodle.por_id("TZ_E_RA2").peso == 40.0
    assert all(n.formula for n in moodle.nodos.values() if n.clase == "calculado")
    # la fórmula rechazada se repitió en la segunda pasada
    por_item: dict[int, int] = {}
    for e in moodle.escrituras:
        if e[0] == "fijar_formula":
            por_item[e[2]] = por_item.get(e[2], 0) + 1
    assert max(por_item.values()) == 2
    # y lo que quedó está como se pidió: volver a montar no cambia nada
    moodle.escrituras.clear()
    atender(pedir(carpeta), moodle, carpeta)
    assert moodle.escrituras == []


def test_una_formula_rechazada_dos_veces_es_un_error(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    moodle.fallos["fijar_formula"] = ["FORMULA_NO_VALIDA"] * 40
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "error"
    assert documento["errores"] == ["FORMULA_NO_VALIDA"]
    assert pasos(documento, "CALIFICADOR")[0]["resultado"] == "fallo"


def test_quitar_el_tope_deja_el_total_del_curso_en_porcentaje_sin_la_formula_vieja(tmp_path):
    con_tope = ESQUEMA.replace(
        "final: {de: elementos}",
        "final: {de: elementos, tope: {si_alguno_menor_que: 5, maximo: 4}}",
    )
    carpeta = carpeta_fp(tmp_path, con_tope)
    moodle = AulaViva()
    atender(pedir(carpeta), moodle, carpeta)
    assert moodle.nodos[CURSO_EID].formula == "=[[TZ_NOTA_FINAL]]"
    (carpeta / "calificacion.yaml").write_text(ESQUEMA, encoding="utf-8")
    moodle.escrituras.clear()
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "ok", documento
    assert ("fijar_total_curso", CURSO, None, ".") in moodle.escrituras
    assert moodle.nodos[CURSO_EID].formula is None
    moodle.escrituras.clear()
    atender(pedir(carpeta), moodle, carpeta)  # y a la siguiente, sin cambios
    assert moodle.escrituras == []


# --------------------------------------------------------------------------- #
# Escena 2: cerrar una evaluación
# --------------------------------------------------------------------------- #


def test_calificador_cierra_evaluacion(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    atender(pedir(carpeta), moodle, carpeta)
    moodle.escrituras.clear()

    cerrada = ESQUEMA.replace(
        "{nombre: 1.ª evaluación, secciones: [1]}",
        "{nombre: 1.ª evaluación, secciones: [1], cerrada: true}",
    )
    (carpeta / "calificacion.yaml").write_text(cerrada, encoding="utf-8")
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "ok"
    v1 = moodle.por_id("TZ_V_1")
    assert moodle.escrituras == [("bloquear_total", CURSO, v1.item_id)]
    assert v1.bloqueado

    # otros pesos: nada de lo que cuelga de TZ_V_1 se crea, cambia, mueve ni borra
    moodle.escrituras.clear()
    otros = cerrada.replace("peso: 60", "peso: 50").replace("peso: 40", "peso: 50")
    (carpeta / "calificacion.yaml").write_text(otros, encoding="utf-8")
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "ok"
    assert moodle.escrituras  # algo cambió: los pesos de RA1 y RA2
    assert moodle.objetivos_en("TZ_V_1") == []
    assert moodle.por_id("TZ_E_RA1").peso == 50.0


def test_montaje_cerrado_que_falla_a_medias_se_completa_antes_de_bloquearse(tmp_path):
    cerrada = ESQUEMA.replace(
        "{nombre: 1.ª evaluación, secciones: [1]}",
        "{nombre: 1.ª evaluación, secciones: [1], cerrada: true}",
    )
    carpeta = carpeta_fp(tmp_path, cerrada)
    moodle = AulaViva()
    moodle.fallos["fijar_formula"] = ["ESCRITURA_CALIFICADOR"]  # cae al empezar con las fórmulas
    primero = atender(pedir(carpeta), moodle, carpeta)
    assert primero["resultado"] == "error"
    assert "bloquear_total" not in moodle.metodos()
    assert moodle.por_id("TZ_V_1").bloqueado is False  # creada a medias y sin bloquear
    assert not any(n.formula for n in moodle.nodos.values() if n.clase == "calculado")
    # la siguiente ejecución la completa (fórmulas) y después la bloquea
    moodle.escrituras.clear()
    segundo = atender(pedir(carpeta), moodle, carpeta)
    assert segundo["resultado"] == "ok", segundo
    assert "fijar_formula" in moodle.metodos()
    assert moodle.metodos()[-1] == "bloquear_total"
    assert moodle.por_id("TZ_V_1").bloqueado is True
    assert all(n.formula for n in moodle.nodos.values() if n.clase == "calculado")
    # y una vez bloqueada no se toca más
    moodle.escrituras.clear()
    atender(pedir(carpeta), moodle, carpeta)
    assert moodle.escrituras == []


def test_primer_montaje_con_una_evaluacion_cerrada_la_crea_y_la_bloquea_al_final(tmp_path):
    carpeta = carpeta_fp(
        tmp_path,
        ESQUEMA.replace(
            "{nombre: 1.ª evaluación, secciones: [1]}",
            "{nombre: 1.ª evaluación, secciones: [1], cerrada: true}",
        ),
    )
    moodle = AulaViva()
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "ok", documento
    v1 = moodle.por_id("TZ_V_1")
    assert v1.bloqueado and moodle.por_id("TZ_V_1_RA1").padre_eid == v1.eid
    assert not moodle.por_id("TZ_V_2").bloqueado
    assert moodle.metodos().count("bloquear_total") == 1
    assert moodle.metodos()[-1] == "bloquear_total"  # lo último de todo
    assert acciones(documento) == {"a.md": "colocada", "c.md": "colocada", "d.md": "colocada"}
    assert pasos(documento, "CALIFICADOR_BLOQUEAR")[0]["detalle"] == "1"
    moodle.escrituras.clear()
    otra = atender(pedir(carpeta), moodle, carpeta)
    assert moodle.escrituras == [] and otra["resultado"] == "ok"


# --------------------------------------------------------------------------- #
# Escena 3: ya había un calificador
# --------------------------------------------------------------------------- #


def aula_con_anterior() -> AulaViva:
    trabajos = nodo("cg50", "", "categoria", CURSO_EID, nombre="Trabajos", tiene_notas=True)
    a, d, c = nodos_de_actividades()
    a = dataclasses.replace(a, padre_eid="cg50", tiene_notas=True)
    total = nodo(CURSO_EID, "", "curso", None, nombre="Curso", formula="=[[X]]")
    aula = AulaViva([trabajos, a, d, c])
    aula.nodos[CURSO_EID] = total
    return aula


def test_calificador_con_anterior(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = aula_con_anterior()
    presencia = PresenciaFalsa(real=True)
    documento = atender(
        pedir(carpeta, "real"), moodle, carpeta, presencia, cfg=CFG, nombres={5678: "Mates"}
    )
    assert documento["resultado"] == "ok", documento

    metodos = moodle.metodos()
    assert metodos[0] == "bloquear_total"
    assert moodle.escrituras[0] == ("bloquear_total", 5678, 50)
    assert metodos.index("bloquear_total") < metodos.index("colocar_actividad")
    [tiza] = [e for e in moodle.escrituras if e[0] == "crear_categoria" and e[3] == "TZ_TIZA"]
    assert tiza[5] == 0.0  # TZ_TIZA pesa 0 en el total del curso
    assert "fijar_total_curso" not in metodos  # el total del curso es del docente
    assert moodle.nodos[CURSO_EID].formula == "=[[X]]"
    [resumen] = presencia.resumenes_calificador
    assert resumen.anterior is True
    assert resumen.bloquea == ("Trabajos",)
    assert resumen.nombre_curso == "Mates"


def test_resumen_llano():
    resumen = publicacion.ResumenCalificador(
        curso=5678,
        nombre_curso="Mates",
        lineas_esquema=(
            publicacion.ElementoCalificador(
                "RA1", 40.0, (("práctica 1", 40.0), ("examen 1", 60.0))
            ),
        ),
        mueve=("Examen tema 1",),
        bloquea=("Trabajos",),
        ids_nuevos=("Examen tema 1",),
        cerradas=(publicacion.EvaluacionCerrada("1.ª evaluación", (1, 2, 3, 4)),),
        avisos=(),
        posicion=1,
        total=1,
        anterior=True,
        notas_cambian=("2.ª evaluación",),
    )
    detalle = mensajes.detalle_calificador(resumen)
    assert detalle.lineas == (
        "RA1 (40 % de la final): práctica 1 40 %, examen 1 60 %",
        "1.ª evaluación: unidades 1-4 (cerrada, no cambia)",
        "Se bloquean los totales de: Trabajos (tienen notas)",
        "Pasan al calificador de tiza: Examen tema 1",
        "Se añade número de ID a: Examen tema 1",
        "Lo de tiza es informativo: el total del curso sigue siendo el tuyo, y las actividades "
        "que pasan a tiza dejan de sumar en él",
        "La nota de la 2.ª evaluación puede cambiar para quien ya tenga notas",
    )
    assert "Mates" in detalle.encabezado and "5678" in detalle.encabezado


def _resumen(**campos) -> publicacion.ResumenCalificador:
    base = dict(
        curso=5678,
        nombre_curso=None,
        lineas_esquema=(),
        mueve=(),
        bloquea=(),
        ids_nuevos=(),
        cerradas=(),
        avisos=(),
    )
    return publicacion.ResumenCalificador(**{**base, **campos})


def test_resumen_dice_que_el_total_del_curso_pasa_a_ser_el_de_tiza():
    sin_tope = mensajes.detalle_calificador(_resumen(total_curso="porcentaje")).lineas
    assert (
        "El total del curso pasa a ser el de tiza (el porcentaje del calificador), "
        "también para quien ya tenga notas"
    ) in sin_tope
    con_tope = mensajes.detalle_calificador(_resumen(total_curso="nota_final")).lineas
    assert (
        "El total del curso pasa a ser el de tiza (la nota final sobre 10), "
        "también para quien ya tenga notas"
    ) in con_tope
    # con un calificador anterior el total sigue siendo del docente: no se dice
    anterior = mensajes.detalle_calificador(_resumen(anterior=True)).lineas
    assert not any("pasa a ser el de tiza" in x for x in anterior)
    # y si el plan no toca el total del curso, tampoco
    assert not any(
        "pasa a ser el de tiza" in x for x in mensajes.detalle_calificador(_resumen()).lineas
    )


def test_resumen_con_tope_dice_la_regla_y_su_limite():
    lineas = mensajes.detalle_calificador(_resumen(tope=(5.0, 4.5))).lineas
    [regla] = [x for x in lineas if x.startswith("Regla de la final")]
    assert "por debajo de 5, la final no pasa de 4,5" in regla
    assert (
        "Mientras un RA no tenga ninguna nota, cuenta como 0 en esa regla: "
        "la final puede salir topada a mitad de curso"
    ) in regla
    assert not any(
        x.startswith("Regla de la final") for x in mensajes.detalle_calificador(_resumen()).lineas
    )


def test_resumen_dice_que_se_quita_del_calificador_de_tiza():
    lineas = mensajes.detalle_calificador(_resumen(quita=("Notas (sobre 10)", "RA3\x1b[2J"))).lineas
    assert lineas[0].startswith(
        "Se quitan del calificador de tiza (no tienen notas): Notas (sobre 10), RA3"
    )
    assert "\x1b" not in lineas[0]
    largas = tuple(f"copia {i}" for i in range(12))
    [linea] = [
        x
        for x in mensajes.detalle_calificador(_resumen(quita=largas)).lineas
        if x.startswith("Se quitan")
    ]
    assert linea.endswith("copia 7 y 4 más")
    assert not any(
        x.startswith("Se quitan") for x in mensajes.detalle_calificador(_resumen()).lineas
    )


def test_resumen_de_una_evaluacion_cerrada_que_se_bloquea_ahora():
    nueva = publicacion.EvaluacionCerrada("1.ª evaluación", (1, 2), por_bloquear=True)
    [linea] = mensajes.detalle_calificador(_resumen(cerradas=(nueva,))).lineas
    assert linea == (
        "1.ª evaluación: unidades 1-2 (cerrada: se completa y se bloquea al terminar, y ya no cambia)"
    )


def test_el_resumen_sale_del_plan_con_el_total_del_curso_la_regla_y_lo_que_se_quita(tmp_path):
    con_tope = ESQUEMA.replace(
        "final: {de: elementos}",
        "final: {de: elementos, tope: {si_alguno_menor_que: 5, maximo: 4}}",
    )
    carpeta = carpeta_fp(tmp_path, con_tope)
    moodle = AulaViva()
    presencia = PresenciaFalsa(real=True)
    atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    [primero] = presencia.resumenes_calificador
    assert primero.total_curso == "nota_final" and primero.tope == (5.0, 4.0)
    assert primero.quita == ()
    # se quita el tope: el total del curso vuelve al porcentaje y «Notas (sobre 10)» se borra
    (carpeta / "calificacion.yaml").write_text(ESQUEMA, encoding="utf-8")
    presencia = PresenciaFalsa(real=True)
    atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    [segundo] = presencia.resumenes_calificador
    assert segundo.total_curso == "porcentaje" and segundo.tope is None
    assert "Notas (sobre 10)" in segundo.quita
    # la tercera vez ya no hay nada que cambiar ni que preguntar
    presencia = PresenciaFalsa(real=True)
    atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert presencia.resumenes_calificador == []


def test_el_resumen_distingue_la_cerrada_por_bloquear_de_la_ya_bloqueada(tmp_path):
    cerrada = ESQUEMA.replace(
        "{nombre: 1.ª evaluación, secciones: [1]}",
        "{nombre: 1.ª evaluación, secciones: [1], cerrada: true}",
    )
    carpeta = carpeta_fp(tmp_path, cerrada)
    moodle = AulaViva()
    presencia = PresenciaFalsa(real=True)
    atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert [c.por_bloquear for c in presencia.resumenes_calificador[0].cerradas] == [True]
    # montada y cerrada, un cambio de pesos vuelve a preguntar, y ya no es nueva
    (carpeta / "calificacion.yaml").write_text(
        cerrada.replace("peso: 60", "peso: 50").replace("peso: 40", "peso: 50"), encoding="utf-8"
    )
    presencia = PresenciaFalsa(real=True)
    atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert [c.por_bloquear for c in presencia.resumenes_calificador[0].cerradas] == [False]


def test_una_actividad_nueva_en_una_evaluacion_cerrada_sale_como_sin_colocar(tmp_path):
    cerrada = ESQUEMA.replace(
        "{nombre: 1.ª evaluación, secciones: [1]}",
        "{nombre: 1.ª evaluación, secciones: [1], cerrada: true}",
    )
    carpeta = carpeta_fp(tmp_path, cerrada)
    moodle = AulaViva()
    atender(pedir(carpeta), moodle, carpeta)
    atender(pedir(carpeta), moodle, carpeta)  # ya cerrada (la 1.ª vez la bloquea)
    assert moodle.por_id("TZ_V_1").bloqueado
    # llega e.md, de la sección 1 (cerrada): está en el aula pero tiza no puede colocarla
    carpeta_fp(tmp_path, cerrada, (*ACTIVIDADES, ("e", 1, 14, {"RA1": 0})))
    moodle.nodos["ig114"] = nodo("ig114", "", "actividad", CURSO_EID, cmid=14, maximo=10.0)
    moodle.secciones[0]["modulos"].append({"cmid": 14, "nombre": "e", "tipo": "tarea"})
    moodle.escrituras.clear()
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "ok", documento
    assert acciones(documento)["e.md"] == "sin_colocar"
    assert acciones(documento)["a.md"] == "ya_estaba"
    assert pasos(documento, "ACTIVIDAD_EN_EVALUACION_CERRADA")[0]["detalle"] == "1"
    assert moodle.escrituras == []  # ni ella ni sus copias: nada de FORMULA_NO_VALIDA
    assert moodle.nodos["ig114"].padre_eid == CURSO_EID
    informe.validar(documento)


def test_una_actividad_cambiada_a_mano_sale_como_sin_colocar(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    atender(pedir(carpeta), moodle, carpeta)
    a = next(n for n in moodle.nodos.values() if n.cmid == 11)
    # el docente saca «a» de su categoría a otra de tiza
    moodle.nodos[a.eid] = dataclasses.replace(a, padre_eid=moodle.por_id("TZ_VISTA").eid)
    moodle.escrituras.clear()
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert acciones(documento)["a.md"] == "sin_colocar"
    assert pasos(documento, "CAMBIADO_A_MANO")[0]["detalle"] == "1"
    assert moodle.escrituras == []


def test_resumen_sin_anterior_ni_bloqueos_no_dice_lo_que_no_hace():
    resumen = publicacion.ResumenCalificador(
        curso=5678,
        nombre_curso=None,
        lineas_esquema=(publicacion.ElementoCalificador("RA2", None, ()),),
        mueve=(),
        bloquea=(),
        ids_nuevos=(),
        cerradas=(),
        avisos=(publicacion.Aviso.actividad_pendiente("c.md"),),
        posicion=1,
        total=1,
    )
    lineas = mensajes.detalle_calificador(resumen).lineas
    assert lineas[0] == "RA2: todavía sin actividades"
    assert not any("bloquean" in x or "informativo" in x or "puede cambiar" in x for x in lineas)
    assert any("c.md" in x for x in lineas)


def test_el_resumen_sale_del_plan_con_los_nombres_de_los_ficheros(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = aula_con_anterior()
    presencia = PresenciaFalsa(real=True)
    atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    [resumen] = presencia.resumenes_calificador
    assert resumen.mueve == ("a", "d", "c")
    assert resumen.ids_nuevos == ("a", "d", "c")
    assert [(e.id, e.peso) for e in resumen.lineas_esquema] == [("RA1", 60.0), ("RA2", 40.0)]
    ra1 = resumen.lineas_esquema[0]
    assert ra1.actividades == (("a", 60.0), ("d", 40.0))


# --------------------------------------------------------------------------- #
# Confirmación y paradas
# --------------------------------------------------------------------------- #


def test_docente_dice_no(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, PresenciaFalsa(real=False))
    assert moodle.escrituras == []
    # Como en «ordenar»: un no es un informe «abortado» (el esquema no tiene «cancelado»)
    assert documento["resultado"] == "abortado"
    assert documento["errores"] == ["ABORTADO"]
    assert estado.cargar_huellas(carpeta / ".tiza", 5678) == {}


def test_sin_operaciones_no_pregunta(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    atender(pedir(carpeta, "real"), moodle, carpeta, PresenciaFalsa(real=True))  # lo monta
    moodle.escrituras.clear()
    presencia = PresenciaFalsa(real=False)
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert presencia.resumenes_calificador == []
    assert moodle.escrituras == []
    assert documento["resultado"] == "ok"
    assert pasos(documento, "CALIFICADOR")[0]["detalle"] == "sin cambios"


def test_bloqueo_fallido_para_el_curso(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = aula_con_anterior()
    moodle.fallos["bloquear_total"] = ["ESCRITURA_CALIFICADOR"]
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, PresenciaFalsa(real=True))
    assert documento["resultado"] == "error"
    assert "BLOQUEO_FALLIDO" in documento["errores"]
    assert moodle.metodos() == ["bloquear_total"]  # nada más en ese curso
    assert pasos(documento, "CALIFICADOR_BLOQUEAR")[0]["resultado"] == "fallo"
    assert estado.cargar_huellas(carpeta / ".tiza", 5678) == {}


def bloqueo_que_no_bloquea(moodle: MoodleFalso) -> None:
    """El aula acepta la orden de bloquear (303) y no bloquea nada."""
    moodle.bloquear_total = lambda curso, item_id: MoodleFalso.bloquear_total(
        moodle, curso, item_id
    )


def test_un_bloqueo_ajeno_que_el_aula_acepta_sin_bloquear_es_bloqueo_fallido(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = aula_con_anterior()
    bloqueo_que_no_bloquea(moodle)
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, PresenciaFalsa(real=True))
    assert documento["resultado"] == "error"
    assert "BLOQUEO_FALLIDO" in documento["errores"]
    # se comprobó con una relectura y no se movió nada antes de que el total estuviera bloqueado
    assert moodle.metodos() == ["bloquear_total"]
    assert pasos(documento, "CALIFICADOR_BLOQUEAR")[0]["resultado"] == "fallo"
    assert moodle.nodos["cg50"].bloqueado is False


def test_un_cierre_que_el_aula_acepta_sin_bloquear_es_un_error_del_curso(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    atender(pedir(carpeta), moodle, carpeta)
    moodle.escrituras.clear()
    cerrada = ESQUEMA.replace(
        "{nombre: 1.ª evaluación, secciones: [1]}",
        "{nombre: 1.ª evaluación, secciones: [1], cerrada: true}",
    )
    (carpeta / "calificacion.yaml").write_text(cerrada, encoding="utf-8")
    bloqueo_que_no_bloquea(moodle)
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "error"
    assert "BLOQUEO_FALLIDO" in documento["errores"]
    assert pasos(documento, "CALIFICADOR_BLOQUEAR")[0]["resultado"] == "fallo"


def test_un_fallo_a_medias_guarda_las_huellas_de_lo_hecho_y_se_cuenta(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    moodle.fallos["colocar_actividad"] = ["ERROR_ACTUALIZAR"]
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["errores"] == ["ERROR_ACTUALIZAR"]
    huellas = estado.cargar_huellas(carpeta / ".tiza", CURSO)
    assert "TZ_TIZA" in huellas  # lo que se creó antes del fallo ya tiene huella
    assert pasos(documento, "CALIFICADOR")[0]["resultado"] == "fallo"


def test_un_fallo_a_medias_y_la_segunda_ejecucion_convergen(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    assert atender(pedir(carpeta), moodle, carpeta)["resultado"] == "ok"
    # El docente cambia los pesos del esquema; el segundo cambio de peso falla a medias.
    nuevo = ESQUEMA.replace("peso: 60", "peso: 70").replace("peso: 40", "peso: 30")
    (carpeta / "calificacion.yaml").write_text(nuevo, encoding="utf-8")
    llamadas = []
    fijar = moodle.fijar_peso

    def fijar_y_falla_la_segunda(curso, eid, peso):
        llamadas.append(eid)
        if len(llamadas) == 2:
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        fijar(curso, eid, peso)

    moodle.fijar_peso = fijar_y_falla_la_segunda
    primero = atender(pedir(carpeta), moodle, carpeta)
    assert primero["resultado"] == "error"
    moodle.fijar_peso = fijar
    segundo = atender(pedir(carpeta), moodle, carpeta)
    assert segundo["resultado"] == "ok", segundo
    assert pasos(segundo, "CAMBIADO_A_MANO") == []
    assert moodle.por_id("TZ_E_RA1").peso == 70.0
    assert moodle.por_id("TZ_E_RA2").peso == 30.0
    tercero = atender(pedir(carpeta), moodle, carpeta)
    assert pasos(tercero, "CALIFICADOR")[0]["detalle"] == "sin cambios"


def test_pruebas_gasta_un_cupo_y_avisa(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    presencia = PresenciaFalsa()
    sesion = sesion_abierta.SesionAbierta(AulaViva(), CFG, carpeta, presencia)
    sesion.atender(pedir(carpeta))
    assert sesion.cupo["pruebas"] == 1
    assert presencia.codigos()[0] == "CALIFICANDO_EN_PRUEBAS"
    assert presencia.resumenes_calificador == []  # en pruebas no se pregunta


def test_el_cupo_se_agota(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    sesion = sesion_abierta.SesionAbierta(AulaViva(), CFG, carpeta, PresenciaFalsa())
    sesion.cupo["pruebas"] = publicacion.MAX_PUBLICACIONES_PRUEBAS
    assert sesion.atender(pedir(carpeta))["errores"] == ["LIMITE_PUBLICACIONES"]


def test_peticion_retirada_tras_confirmar(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    datos = pedir(carpeta, "real")
    ruta = buzon.carpeta_buzon(carpeta / ".tiza") / f"{datos['id']}{buzon.SUFIJO_PETICION}"

    class Retira(PresenciaFalsa):
        def confirmar_calificador(self, resumen):
            ruta.unlink()
            return super().confirmar_calificador(resumen)

    moodle = AulaViva()
    documento = atender(datos, moodle, carpeta, Retira(real=True))
    assert documento["errores"] == ["PETICION_RETIRADA"]
    assert moodle.escrituras == []


def test_varios_cursos_reales_se_confirman_uno_a_uno(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()  # el doble tiene un solo calificador: el curso 102 lo encuentra como esté
    presencia = PresenciaFalsa(real=(False, True))
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, presencia, cfg=CFG_DOS)
    assert [(r.curso, r.posicion, r.total) for r in presencia.resumenes_calificador] == [
        (101, 1, 2),
        (102, 2, 2),
    ]
    assert documento["resultado"] == "ok"
    assert [p["detalle"] for p in pasos(documento, "CURSO_OMITIDO")] == ["101"]
    assert moodle.metodos().count("colocar_actividad") == 3  # solo el 102


def test_varios_cursos_reales_paran_en_el_primer_fallo(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    moodle.fallos["colocar_actividad"] = ["ERROR_ACTUALIZAR"]
    presencia = PresenciaFalsa(real=(True, True))
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, presencia, cfg=CFG_DOS)
    assert documento["resultado"] == "error"
    assert [r.curso for r in presencia.resumenes_calificador] == [101]  # al 102 ni se le pregunta


def test_sin_curso_de_pruebas(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    sin = config.Config(url=URL, usuario="profe", cursos={}, reales=(5678,), sin_pruebas=True)
    documento = atender(pedir(carpeta), AulaViva(), carpeta, cfg=sin)
    assert documento["errores"] == ["SIN_CURSO_PRUEBAS"]


# --------------------------------------------------------------------------- #
# Lo que no depende del aula
# --------------------------------------------------------------------------- #


def test_actividad_que_aun_no_esta_en_el_aula_es_pendiente(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva(secciones=secciones_de(ACTIVIDADES[:2]))
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "ok"
    assert acciones(documento) == {"a.md": "colocada", "c.md": "pendiente", "d.md": "colocada"}
    assert pasos(documento, "ACTIVIDAD_PENDIENTE")[0]["detalle"] == "1"


def test_un_error_del_esquema_sale_antes_de_tocar_el_aula(tmp_path):
    carpeta = carpeta_fp(tmp_path, ESQUEMA.replace("peso: 40", "peso: 30"))
    moodle = AulaViva()
    sesion = sesion_abierta.SesionAbierta(moodle, CFG, carpeta, PresenciaFalsa())
    documento = sesion.atender(pedir(carpeta))
    assert documento["errores"] == ["PESOS_NO_SUMAN_100"]
    assert moodle.llamadas == []
    assert sesion.cupo["pruebas"] == 0


def test_un_error_de_las_actividades_sale_antes_de_tocar_el_aula(tmp_path):
    carpeta = carpeta_fp(tmp_path, actividades=(("a", 1, 11, {"RA9": 60}),))
    moodle = AulaViva()
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["errores"] == ["ELEMENTO_DESCONOCIDO"]
    assert moodle.llamadas == []


def test_evalua_en_una_pagina_o_una_etiqueta_es_un_error_antes_de_tocar_el_aula(tmp_path):
    for tipo in ("pagina", "etiqueta"):
        (tmp_path / tipo).mkdir()
        carpeta = carpeta_fp(tmp_path / tipo)
        (carpeta / "nota.md").write_text(
            f"---\ntipo: {tipo}\nnombre: nota\nseccion: 1\nevalua: {{RA1: 0}}\n---\n\nX\n",
            encoding="utf-8",
        )
        moodle = AulaViva()
        documento = atender(pedir(carpeta), moodle, carpeta)
        assert documento["errores"] == ["EVALUA_NO_CALIFICABLE"], tipo
        assert moodle.llamadas == []
        resultado = agente.comprobar(carpeta, ["nota.md"])  # y también en «tiza comprobar»
        assert "EVALUA_NO_CALIFICABLE" in resultado.informe["errores"]
        assert [f.codigo for f in resultado.ficheros if f.fichero == "nota.md"] == [
            "EVALUA_NO_CALIFICABLE"
        ]


def test_un_fichero_con_evalua_que_no_carga_no_se_ignora(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    (carpeta / "roto.md").write_text(
        "---\ntipo: pagina\nnombre: roto\nseccion: 1\nevalua: {RA1: 200}\n---\n\nX\n",
        encoding="utf-8",
    )
    moodle = AulaViva()
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["errores"] == ["EVALUA_INVALIDO"]
    assert moodle.llamadas == []


def test_la_carpeta_se_lee_sin_carpetas_ocultas_ni_ficheros_que_no_son_de_tiza(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    (carpeta / "README.md").write_text("# Notas del curso\n", encoding="utf-8")
    (carpeta / ".oculta").mkdir()
    (carpeta / ".oculta" / "x.md").write_text(
        "---\ntipo: pagina\nnombre: x\nseccion: 1\nevalua: {RA1: 100}\n---\n\nX\n", encoding="utf-8"
    )
    (carpeta / "unidad").mkdir()
    (carpeta / "unidad" / "e.html").write_text(
        "---\ntipo: pagina\nnombre: e\nseccion: 1\n---\n\n<p>Hola</p>\n", encoding="utf-8"
    )
    nombres = sorted(
        d.ruta.relative_to(carpeta).as_posix() for d in documentos_de_la_carpeta(carpeta)
    )
    assert nombres == ["a.md", "c.md", "d.md", "unidad/e.html"]


def test_demasiados_ficheros(tmp_path, monkeypatch):
    from tiza.calificacion import carpeta as modulo
    from tiza.calificacion.esquema import ErrorCalificacion

    carpeta = carpeta_fp(tmp_path)
    monkeypatch.setattr(modulo, "MAX_FICHEROS", 2)
    with pytest.raises(ErrorCalificacion) as exc:
        documentos_de_la_carpeta(carpeta)
    assert exc.value.codigo == "CARPETA_DEMASIADO_GRANDE"


def test_un_cambio_a_mano_se_respeta_y_se_sigue_respetando(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    atender(pedir(carpeta), moodle, carpeta)
    huellas = estado.cargar_huellas(carpeta / ".tiza", CURSO)
    ra1 = moodle.por_id("TZ_E_RA1")
    moodle.nodos[ra1.eid] = dataclasses.replace(ra1, peso=70.0)  # el docente lo cambia en Moodle
    moodle.escrituras.clear()
    for _ in range(2):  # la segunda vez, igual: no «adopta» el cambio
        documento = atender(pedir(carpeta), moodle, carpeta)
        assert moodle.escrituras == []
        assert pasos(documento, "CAMBIADO_A_MANO")[0]["detalle"] == "1"
    assert estado.cargar_huellas(carpeta / ".tiza", CURSO)["TZ_E_RA1"] == huellas["TZ_E_RA1"]


def test_un_calificador_invalido_en_disco_sale_antes_de_tocar_el_aula(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    (carpeta / ".tiza").mkdir()
    (carpeta / ".tiza" / "calificador.json").write_text("[]", encoding="utf-8")
    moodle = AulaViva()
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["errores"] == ["CALIFICADOR_INVALIDO"]
    assert moodle.escrituras == []


def test_la_huella_que_no_se_guarda_se_cuenta_pero_no_es_un_error(tmp_path, monkeypatch):
    carpeta = carpeta_fp(tmp_path)

    def falla(*_a, **_k):
        raise estado.ErrorEstado("CALIFICADOR_INVALIDO")

    monkeypatch.setattr(estado, "guardar_huellas", falla)
    documento = atender(pedir(carpeta), AulaViva(), carpeta)
    assert documento["resultado"] == "ok"
    assert pasos(documento, "HUELLA_NO_GUARDADA")[0]["resultado"] == "fallo"


# --------------------------------------------------------------------------- #
# El informe
# --------------------------------------------------------------------------- #


def test_informe_sin_texto_del_aula(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = aula_con_anterior()
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, PresenciaFalsa(real=True))
    informe.validar(documento)
    texto = json.dumps(documento, ensure_ascii=False)
    assert "Trabajos" not in texto
    for n in moodle.nodos.values():
        if n.nombre and n.clase != "actividad":
            assert f'"{n.nombre}"' not in texto
    escrito = (carpeta / ".tiza" / "informe.json").read_text("utf-8")
    assert "Trabajos" not in escrito


def test_los_avisos_de_la_reconciliacion_salen_como_recuentos(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = aula_con_anterior()
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, PresenciaFalsa(real=True))
    assert pasos(documento, "TOTAL_AJENO_BLOQUEADO")[0]["detalle"] == "1"
    assert pasos(documento, "CALIFICADOR_BLOQUEAR")[0]["detalle"] == "1"


# --------------------------------------------------------------------------- #
# Agente: buzón, sin sesión y comprobación offline
# --------------------------------------------------------------------------- #


def test_calificador_sin_sesion(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    documento = agente.calificador(carpeta, "calificacion.yaml", "pruebas")
    assert documento["comando"] == "calificador"
    assert documento["resultado"] == "error"
    assert documento["errores"] == ["SIN_SESION"]


def test_peticion_calificador():
    datos = agente.peticion_calificador("calificacion.yaml", "real")
    assert datos["comando"] == "calificador"
    assert datos["ficheros"] == ["calificacion.yaml"]
    assert datos["entorno"] == "real"
    assert datos["visible"] is None and datos["solo_fechas"] is False
    assert datos["version"] == buzon.VERSION_PROTOCOLO
    buzon.validar_peticion(datos)


def test_comprobar_valida_el_esquema_sin_red(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    resultado = agente.comprobar(carpeta, ["calificacion.yaml"])
    assert resultado.informe["errores"] == []
    assert pasos(resultado.informe, "COMPROBAR")[0]["detalle"] == "calificacion.yaml"
    assert resultado.ficheros[0].codigo is None


def test_comprobar_da_el_error_del_esquema_con_su_linea(tmp_path):
    carpeta = carpeta_fp(tmp_path, ESQUEMA.replace("peso: 40", "peso: -3"))
    resultado = agente.comprobar(carpeta, ["calificacion.yaml"])
    assert resultado.informe["errores"] == ["ESQUEMA_INVALIDO"]
    assert "línea" in resultado.ficheros[0].detalle


def test_comprobar_da_el_error_de_las_actividades(tmp_path):
    carpeta = carpeta_fp(tmp_path, actividades=(("a", 1, 11, {"RA9": 60}),))
    resultado = agente.comprobar(carpeta, ["calificacion.yaml"])
    assert resultado.informe["errores"] == ["ELEMENTO_DESCONOCIDO"]


def test_el_buzon_entero_con_el_calificador(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    sesion = sesion_abierta.SesionAbierta(moodle, CFG, carpeta, PresenciaFalsa())
    datos = agente.peticion_calificador("calificacion.yaml", "pruebas")
    sesion.atender(datos)
    assert moodle.metodos().count("colocar_actividad") == 3


def test_tras_un_fallo_lo_tocado_que_esta_a_mano_conserva_su_huella_antigua():
    from types import SimpleNamespace

    from tiza.calificacion.reconciliar import Operacion

    final = CalificadorAula(
        nodos=(nodo("cg1", "", "curso", None), nodo("cg3", "TZ_X", "categoria", "cg1", peso=5.0)),
        decimal=".",
    )
    antigua = "a" * 64
    plan = SimpleNamespace(
        huellas={"TZ_X": antigua, "TZ_Y": "b" * 64},
        cmids={},
        reconciliacion=SimpleNamespace(a_mano=frozenset({"TZ_X"})),
    )
    nuevas = publicacion._huellas_tras_fallo(
        final, plan, [Operacion("fijar_peso", idnumber="TZ_X")]
    )
    assert nuevas["TZ_X"] == antigua and nuevas["TZ_Y"] == "b" * 64
