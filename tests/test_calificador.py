"""``tiza calificador`` de punta a punta: buzón, sesión, confirmación, aula doblada e informe.

El aula es ``AulaViva``: un ``MoodleFalso`` cuyo calificador reacciona a las escrituras (lo justo
para que lo montado converja), así que lo que se comprueba es el flujo completo: leer, reconciliar,
confirmar, ejecutar, releer, segunda pasada y huellas.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from dobles import MoodleFalso, PresenciaFalsa, dejar_peticion, estructura_de, peticion
from tiza import (
    agente,
    buzon,
    config,
    contenido,
    estado,
    informe,
    mensajes,
    publicacion,
    recorrido,
    sesion_abierta,
)
from tiza.calificacion.carpeta import cargar_calificacion, documentos_de_la_carpeta
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

    def __init__(
        self,
        extra: list[NodoAula] | None = None,
        *,
        perturbar: bool = False,
        reescalar: bool = False,
        ignorar_ocultar: bool = False,
        ignorar_alta_oculta: bool = False,
        **kw,
    ):
        super().__init__(secciones=kw.pop("secciones", secciones_de()), **kw)
        base = [nodo(CURSO_EID, "", "curso", None, nombre="Curso", agregacion=13)]
        self.nodos: dict[str, NodoAula] = {
            n.eid: n for n in [*base, *(nodos_de_actividades() if extra is None else extra)]
        }
        self.decimal = "."
        self.perturbar = perturbar  # Moodle reescala un peso hermano al guardar el de RA2
        # Moodle (agregación Natural): si los pesos propios de los hijos de una categoría suman
        # más de 100, los reescala para que sumen 100 cada vez que cambia uno
        self.reescalar = reescalar
        # Para probar la verificación: el aula acepta la orden pero no oculta, o crea visible.
        self.ignorar_ocultar = ignorar_ocultar
        self.ignorar_alta_oculta = ignorar_alta_oculta
        self.relecturas: list[set[str] | None] = []  # los ``tocados`` de cada lectura

    # -- lectura ----------------------------------------------------------

    def calificador(self, curso_id, tocados=None):
        self.llamadas.append(("calificador", curso_id))
        self.relecturas.append(None if tocados is None else set(tocados))
        for _ in range(6):
            for n in list(self.nodos.values()):
                if n.clase == "categoria":
                    if n.agregacion == 13:  # Natural: la suma de sus hijos
                        hijos = [h for h in self.nodos.values() if h.padre_eid == n.eid]
                        self.nodos[n.eid] = dataclasses.replace(
                            n, maximo=sum(h.maximo or 0.0 for h in hijos)
                        )
                    else:  # media ponderada, mediana y más alta: sobre 100
                        self.nodos[n.eid] = dataclasses.replace(n, maximo=100.0)
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

    def _reescalar(self, padre_eid: str | None) -> None:
        """Si todos los hijos llevan peso propio y no suman 100, Moodle los reescala a 100."""
        if not self.reescalar or padre_eid is None:
            return
        hijos = [h for h in self.nodos.values() if h.padre_eid == padre_eid]
        if not hijos or not all(h.sobrescrito and h.coeficiente is not None for h in hijos):
            return
        total = sum(h.peso for h in hijos)
        if total > 0 and abs(total - 100) > 0.001:
            for h in hijos:
                self.nodos[h.eid] = dataclasses.replace(h, peso=round(h.peso * 100 / total, 3))

    def _crear(
        self,
        eid,
        idnumber,
        clase,
        nombre,
        padre_eid,
        peso,
        maximo=None,
        agregacion=None,
        oculto=False,
        coeficiente=None,
    ) -> str:
        self.nodos[eid] = nodo(
            eid,
            idnumber,
            clase,
            padre_eid or CURSO_EID,
            nombre=nombre,
            peso=peso,
            coeficiente=coeficiente,
            sobrescrito=peso is not None,
            maximo=maximo,
            agregacion=agregacion,
            oculto=oculto,
        )
        return eid

    # -- escritura --------------------------------------------------------

    def crear_categoria(
        self,
        curso,
        nombre,
        idnumber,
        padre_eid,
        peso,
        visualizacion,
        agregacion=13,
        solo_no_vacias=True,
        coeficiente=None,
    ):
        eid = super().crear_categoria(
            curso,
            nombre,
            idnumber,
            padre_eid,
            peso,
            visualizacion,
            agregacion,
            solo_no_vacias,
            coeficiente,
        )
        return self._crear(
            eid,
            idnumber,
            "categoria",
            nombre,
            padre_eid,
            peso,
            agregacion=agregacion,
            coeficiente=coeficiente,
        )

    def crear_calculado(
        self, curso, nombre, idnumber, padre_eid, peso, maximo, oculto=False, coeficiente=None
    ):
        eid = super().crear_calculado(
            curso, nombre, idnumber, padre_eid, peso, maximo, oculto, coeficiente
        )
        clase = "manual" if idnumber.startswith("TZ_M_") else "calculado"  # sin fórmula: manual
        return self._crear(
            eid,
            idnumber,
            clase,
            nombre,
            padre_eid,
            peso,
            maximo,
            oculto=oculto and not self.ignorar_alta_oculta,
            coeficiente=coeficiente,
        )

    def fijar_maximo(self, curso, item_id, maximo):
        super().fijar_maximo(curso, item_id, maximo)
        self._cambiar(None, item_id, maximo=maximo)

    def fijar_coeficiente(self, curso, eid, valor, metodo_del_padre):
        super().fijar_coeficiente(curso, eid, valor, metodo_del_padre)
        self._cambiar(eid, None, coeficiente=valor)

    def fijar_peso(self, curso, eid, peso):
        super().fijar_peso(curso, eid, peso)
        self._cambiar(eid, None, peso=peso, sobrescrito=True)
        self._reescalar(self.nodos[eid].padre_eid)
        if self.perturbar and self.nodos[eid].idnumber == "TZ_E_RA2":
            self.perturbar = False  # una sola vez: Moodle reescala a RA1 al guardar RA2
            self._cambiar(self.por_id("TZ_E_RA1").eid, None, peso=1.0)

    def fijar_agregacion(self, curso, eid, agregacion, solo_no_vacias=None):
        super().fijar_agregacion(curso, eid, agregacion, solo_no_vacias)
        self._cambiar(eid, None, agregacion=agregacion)

    def fijar_formula(self, curso, item_id, formula, decimal):
        super().fijar_formula(curso, item_id, formula, decimal)
        self._cambiar(None, item_id, formula=formula)

    def bloquear_total(self, curso, item_id):
        super().bloquear_total(curso, item_id)
        self._cambiar(None, item_id, bloqueado=True)

    def ocultar(self, curso, item_id):
        super().ocultar(curso, item_id)
        if not self.ignorar_ocultar:
            self._cambiar(None, item_id, oculto=True)

    def ajuste_totales(self, curso):
        return self.ajustes_totales.get(curso, -1)

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

    def marcar_resultado_tarea(self, cmid, resultado_id):
        super().marcar_resultado_tarea(cmid, resultado_id)
        resultado = next(
            r
            for resultados in self.resultados.values()
            for r in resultados
            if r["id"] == resultado_id
        )
        eid = self._nuevo_eid("ig")
        self.nodos[eid] = nodo(
            eid,
            "",
            "actividad",
            CURSO_EID,
            nombre=resultado["nombre"],
            cmid=cmid,
            maximo=None,
        )

    def fijar_idnumber_resultado(self, curso, item_id, idnumber):
        super().fijar_idnumber_resultado(curso, item_id, idnumber)
        self._cambiar(None, item_id, idnumber=idnumber)

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
            if metodo in ("fijar_peso", "fijar_coeficiente", "borrar_nodo") and destino in dentro:
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
    assert metodos.count("crear_calculado") == 4  # copias del curso y de la rúbrica nativa
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
    pesados = {e[2] for e in moodle.escrituras if e[0] in ("fijar_peso", "fijar_coeficiente")}
    colocadas = {f"ig{n.item_id}" for n in moodle.nodos.values() if n.clase == "actividad"}
    assert pesados and pesados <= set().union(*relecturas)
    assert colocadas <= set().union(*relecturas)


def test_el_informe_desglosa_los_cambios_por_tipo(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    documento = atender(pedir(carpeta), moodle, carpeta)
    [paso] = pasos(documento, "CALIFICADOR_CAMBIOS")
    tipos = dict(parte.split(": ")[:2] for parte in paso["detalle"].split("; ") if ": " in parte)
    total = int(pasos(documento, "CALIFICADOR")[0]["detalle"].split()[0])
    assert {"crear_categoria", "fijar_coeficiente"} <= set(tipos)
    assert sum(int(v.split()[0]) for v in tipos.values()) == total
    # solo números de ID de tiza (TZ_…), nunca nombres ni textos del aula
    assert all(
        id_.startswith("TZ_")
        for id_ in re.findall(r"\(([^)]*)\)", paso["detalle"])
        for id_ in id_.split(", ")
        if id_ and id_ != "…"
    )
    segundo = atender(pedir(carpeta), moodle, carpeta)
    assert not pasos(segundo, "CALIFICADOR_CAMBIOS")


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
    assert moodle.por_id("TZ_E_RA1").coeficiente == 60.0
    assert moodle.por_id("TZ_E_RA2").coeficiente == 40.0
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
    assert moodle.nodos[CURSO_EID].formula == "=[[TZ_NOTA_FINAL]]/10"
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
    bloqueados = [e for e in moodle.escrituras if e[0] == "bloquear_total"]
    assert len(bloqueados) == 3
    assert ("bloquear_total", CURSO, v1.item_id) in bloqueados
    assert v1.bloqueado

    # otros pesos: nada de lo que cuelga de TZ_V_1 se crea, cambia, mueve ni borra
    moodle.escrituras.clear()
    otros = cerrada.replace("peso: 60", "peso: 50").replace("peso: 40", "peso: 50")
    (carpeta / "calificacion.yaml").write_text(otros, encoding="utf-8")
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "ok"
    assert moodle.escrituras  # algo cambió: los pesos de RA1 y RA2
    assert moodle.objetivos_en("TZ_V_1") == []
    assert moodle.por_id("TZ_E_RA1").coeficiente == 50.0


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
    # el desglose dice qué llegó a hacer antes de caer (sin fórmulas: cayó en la primera)
    [desglose] = pasos(primero, "CALIFICADOR_CAMBIOS")
    assert "crear_categoria" in desglose["detalle"] and "fijar_formula" not in desglose["detalle"]
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
    assert moodle.metodos().count("bloquear_total") == 3
    assert moodle.metodos()[-1] == "bloquear_total"  # lo último de todo
    assert acciones(documento) == {"a.md": "colocada", "c.md": "colocada", "d.md": "colocada"}
    assert pasos(documento, "CALIFICADOR_BLOQUEAR")[0]["detalle"] == "3"
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
        "Solo cuentan los elementos cuya evaluación ya está cerrada: "
        "mientras no cierres la primera, la final no topa"
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
    # se quita el tope: el total del curso vuelve al porcentaje y «Nota final (sobre 10)» se borra
    (carpeta / "calificacion.yaml").write_text(ESQUEMA, encoding="utf-8")
    presencia = PresenciaFalsa(real=True)
    atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    [segundo] = presencia.resumenes_calificador
    assert segundo.total_curso == "porcentaje" and segundo.tope is None
    assert "Nota final (sobre 10)" in segundo.quita
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
    fijar = moodle.fijar_coeficiente

    def fijar_y_falla_la_segunda(curso, eid, valor, metodo_del_padre):
        llamadas.append(eid)
        if len(llamadas) == 2:
            raise ErrorPublicacion("ESCRITURA_CALIFICADOR")
        fijar(curso, eid, valor, metodo_del_padre)

    moodle.fijar_coeficiente = fijar_y_falla_la_segunda
    primero = atender(pedir(carpeta), moodle, carpeta)
    assert primero["resultado"] == "error"
    moodle.fijar_coeficiente = fijar
    segundo = atender(pedir(carpeta), moodle, carpeta)
    assert segundo["resultado"] == "ok", segundo
    assert pasos(segundo, "CAMBIADO_A_MANO") == []
    assert moodle.por_id("TZ_E_RA1").coeficiente == 70.0
    assert moodle.por_id("TZ_E_RA2").coeficiente == 30.0
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


def test_un_fichero_con_evidencia_sin_evalua_no_se_ignora(tmp_path):
    from tiza.calificacion.carpeta import cargar_calificacion
    from tiza.calificacion.esquema import ErrorCalificacion

    carpeta = carpeta_fp(tmp_path)
    (carpeta / "evidencia.md").write_text(
        "---\ntipo: tarea\nnombre: evidencia\nseccion: 1\n"
        "apertura: 2026-10-01\nentrega: 2026-10-10\nevidencia: resultados\n---\n\nTexto\n",
        encoding="utf-8",
    )
    with pytest.raises(ErrorCalificacion) as exc:
        cargar_calificacion(carpeta / "calificacion.yaml", carpeta)
    assert exc.value.codigo == "EVIDENCIA_SIN_EVALUA"


def test_un_fichero_con_rubrica_sin_evalua_no_se_ignora(tmp_path):
    from tiza.calificacion.carpeta import cargar_calificacion
    from tiza.calificacion.esquema import ErrorCalificacion

    carpeta = carpeta_fp(tmp_path)
    (carpeta / "rubrica.md").write_text(
        "---\ntipo: tarea\nnombre: rubrica\nseccion: 1\n"
        "apertura: 2026-10-01\nentrega: 2026-10-10\nrubrica: por_criterios\n---\n\nTexto\n",
        encoding="utf-8",
    )
    with pytest.raises(ErrorCalificacion) as exc:
        cargar_calificacion(carpeta / "calificacion.yaml", carpeta)
    assert exc.value.codigo == "RUBRICA_SIN_EVALUA"


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


def test_las_preferencias_no_cuentan_como_actividad(tmp_path):
    # preferencias.txt es un .txt para que el calificador no lo mire: «evaluación» contiene
    # «evalua» y un fichero que no carga haría fallar `tiza calificador`.
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    (carpeta / "preferencias.txt").write_text(
        "Evaluación: tareas con criterios a la vista\n", encoding="utf-8"
    )
    assert documentos_de_la_carpeta(carpeta) == []


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
    moodle.nodos[ra1.eid] = dataclasses.replace(
        ra1, coeficiente=70.0
    )  # el docente lo cambia en Moodle
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


def test_comprobar_muestra_el_reparto(tmp_path):
    esquema = """\
organizacion: elementos
elementos:
  - {id: RA1, nombre: Redes, peso: 100}
evaluaciones:
  - {nombre: Primera, secciones: [1]}
final: {de: elementos}
"""
    carpeta = carpeta_fp(
        tmp_path,
        esquema=esquema,
        actividades=(("a", 1, 11, {"RA1": 1}), ("b", 1, 12, {"RA1": 3})),
    )
    resultado = agente.comprobar(carpeta, ["calificacion.yaml"])
    assert resultado.informe["errores"] == []
    assert pasos(resultado.informe, "COMPROBAR")[0]["detalle"] == "calificacion.yaml"
    reparto = pasos(resultado.informe, "REPARTO")
    assert [paso["detalle"] for paso in reparto] == ["RA1: a 25 %, b 75 %"]


def test_comprobar_no_muestra_porcentajes_con_regla_mas_alta(tmp_path):
    esquema = """\
organizacion: elementos
elementos:
  - id: RA1
    nombre: Redes
    peso: 100
    criterios:
      - {id: CE1_1, nombre: Configura, regla: mas_alta}
evaluaciones:
  - {nombre: Primera, secciones: [1]}
final: {de: elementos}
"""
    carpeta = carpeta_fp(
        tmp_path,
        esquema=esquema,
        actividades=(("a", 1, 11, {"CE1_1": 1}), ("b", 1, 12, {"CE1_1": 3})),
    )
    resultado = agente.comprobar(carpeta, ["calificacion.yaml"])
    assert resultado.informe["errores"] == []
    assert [paso["detalle"] for paso in pasos(resultado.informe, "REPARTO")] == [
        "CE1_1: a, b (regla mas_alta: los pesos no cuentan)"
    ]


def test_comprobar_avisa_de_que_la_final_normaliza_por_evaluacion(tmp_path):
    esquema = """\
organizacion: evaluaciones
elementos:
  - {id: RA1, nombre: Redes, peso: 100}
evaluaciones:
  - {nombre: Primera, secciones: [1], peso: 100}
final: {de: evaluaciones}
"""
    carpeta = carpeta_fp(
        tmp_path,
        esquema=esquema,
        actividades=(("a", 1, 11, {"RA1": 1}), ("b", 1, 12, {"RA1": 3})),
    )
    resultado = agente.comprobar(carpeta, ["calificacion.yaml"])
    assert resultado.informe["errores"] == []
    assert [paso["detalle"] for paso in pasos(resultado.informe, "REPARTO")] == [
        "RA1: a 25 %, b 75 % (en la final, cada evaluación normaliza por separado)"
    ]


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


# --------------------------------------------------------------------------- #
# Criterios e instrumentos: avisos y errores hasta el informe y el docente
# --------------------------------------------------------------------------- #

ESQUEMA_CRITERIOS = """\
organizacion: elementos
elementos:
  - id: CE1
    nombre: Redes
    peso: 60
    criterios: [{id: CE1_1, nombre: Configura}, {id: CE1_2, nombre: Documenta}]
  - {id: CE2, nombre: Sistemas, peso: 40}
evaluaciones:
  - {nombre: 1.ª evaluación, secciones: [1]}
  - {nombre: 2.ª evaluación, secciones: [2]}
final: {de: elementos}
"""
ESQUEMA_CON_MANUAL = (
    ESQUEMA_CRITERIOS
    + "instrumentos: [{id: EXAMEN1, nombre: Examen, seccion: 2, evalua: {CE2: 50}}]\n"
)
ACTIVIDADES_CRITERIOS = (
    ("a", 1, 11, {"CE1_1": 100}),
    ("d", 1, 12, {"CE1_2": 100}),
    ("c", 2, 13, {"CE2": 100}),
)
ACTIVIDADES_CON_MANUAL = (
    ("a", 1, 11, {"CE1_1": 100}),
    ("d", 1, 12, {"CE1_2": 100}),
    ("c", 2, 13, {"CE2": 50}),
)


def test_criterio_sin_peso_avisa_y_el_docente_lo_lee(tmp_path):
    carpeta = carpeta_fp(tmp_path, ESQUEMA_CRITERIOS, ACTIVIDADES_CRITERIOS)
    moodle = AulaViva(secciones=secciones_de(ACTIVIDADES_CRITERIOS))
    presencia = PresenciaFalsa(real=True)
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert documento["resultado"] == "ok"
    assert pasos(documento, "CRITERIOS_SIN_PESO")[0]["detalle"] == "1"
    avisos = [a for r in presencia.resumenes_calificador for a in r.avisos]
    assert publicacion.Aviso.criterios_sin_peso("CE1") in avisos
    textos = [
        linea.texto
        for aviso in avisos
        if aviso.codigo == "CRITERIOS_SIN_PESO"
        for linea in mensajes.lineas_de_aviso(aviso)
    ]
    assert textos == ["Los criterios de CE1 no llevan peso: tiza los pesa igual."]


ACTIVIDADES_COMPARTIDAS = (
    ("a", 1, 11, {"CE1_1": 100, "CE1_2": 100}),
    ("c", 2, 13, {"CE2": 100}),
)


def test_evidencia_compartida_avisa_y_el_docente_lo_lee(tmp_path):
    carpeta = carpeta_fp(tmp_path, ESQUEMA_CRITERIOS, ACTIVIDADES_COMPARTIDAS)
    moodle = AulaViva(secciones=secciones_de(ACTIVIDADES_COMPARTIDAS))
    presencia = PresenciaFalsa(real=True)
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert documento["resultado"] == "ok"
    assert pasos(documento, "EVIDENCIA_COMPARTIDA")[0]["detalle"] == "1"
    avisos = [a for r in presencia.resumenes_calificador for a in r.avisos]
    assert publicacion.Aviso.evidencia_compartida("a", tipo="tarea") in avisos
    textos = [
        linea.texto
        for aviso in avisos
        if aviso.codigo == "EVIDENCIA_COMPARTIDA"
        for linea in mensajes.lineas_de_aviso(aviso)
    ]
    assert textos == [
        "«a» evalúa varios criterios y su nota total llega a todos. Para que cada criterio "
        "reciba su propio nivel, usa «evidencia: resultados» si es una tarea o separa la "
        "actividad por criterio."
    ]


def test_evalua_que_nombra_un_elemento_con_criterios_es_error(tmp_path):
    actividades = (("a", 1, 11, {"CE1": 100}), *ACTIVIDADES_CRITERIOS[1:])
    carpeta = carpeta_fp(tmp_path, ESQUEMA_CRITERIOS, actividades)
    resultado = agente.comprobar(carpeta, ["calificacion.yaml"])
    assert resultado.informe["errores"] == ["ELEMENTO_CON_CRITERIOS"]
    moodle = AulaViva()
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["errores"] == ["ELEMENTO_CON_CRITERIOS"]
    assert moodle.llamadas == []


def test_montaje_con_criterios_y_casilla_manual_termina_sin_errores(tmp_path):
    carpeta = carpeta_fp(tmp_path, ESQUEMA_CON_MANUAL, ACTIVIDADES_CON_MANUAL)
    moodle = AulaViva(secciones=secciones_de(ACTIVIDADES_CON_MANUAL))
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, PresenciaFalsa(real=True))
    assert documento["resultado"] == "ok"
    assert documento["errores"] == []
    assert moodle.por_id("TZ_E_CE1_1").clase == "categoria"
    assert moodle.por_id("TZ_E_CE1_2").clase == "categoria"
    assert moodle.por_id("TZ_M_EXAMEN1").clase == "manual"


def test_el_resumen_real_cuenta_las_hojas_y_nombra_las_casillas_manuales(tmp_path):
    carpeta = carpeta_fp(tmp_path, ESQUEMA_CON_MANUAL, ACTIVIDADES_CON_MANUAL)
    moodle = AulaViva(secciones=secciones_de(ACTIVIDADES_CON_MANUAL))
    presencia = PresenciaFalsa(real=True)
    atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    detalle = mensajes.detalle_calificador(presencia.resumenes_calificador[0])
    linea_ce1 = next(x for x in detalle.lineas if x.startswith("CE1"))
    assert "todavía sin actividades" not in linea_ce1
    assert "a 100" in linea_ce1.replace(" %", "") and "d 100" in linea_ce1.replace(" %", "")
    linea_ce2 = next(x for x in detalle.lineas if x.startswith("CE2"))
    assert "Examen" in linea_ce2 and "c " in linea_ce2
    assert any(
        x.startswith("Se crean casillas de calificación manual") and "Examen" in x
        for x in detalle.lineas
    )


def test_un_esquema_sin_instrumentos_no_menciona_casillas(tmp_path):
    carpeta = carpeta_fp(tmp_path, ESQUEMA_CRITERIOS, ACTIVIDADES_CRITERIOS)
    moodle = AulaViva(secciones=secciones_de(ACTIVIDADES_CRITERIOS))
    presencia = PresenciaFalsa(real=True)
    atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    resumen = presencia.resumenes_calificador[0]
    assert resumen.casillas == ()
    assert not [x for x in mensajes.detalle_calificador(resumen).lineas if "casillas" in x]


# --------------------------------------------------------------------------- #
# Un calificador ya montado que gana criterios y una casilla converge enseguida
# --------------------------------------------------------------------------- #

ESQUEMA_CRITERIOS_CON_PESO = ESQUEMA_CRITERIOS.replace(
    "{id: CE1_1, nombre: Configura}, {id: CE1_2, nombre: Documenta}",
    "{id: CE1_1, nombre: Configura, peso: 40}, {id: CE1_2, nombre: Documenta, peso: 60}",
)


def test_cambiar_los_pesos_de_un_calificador_montado_converge_en_el_segundo_montaje(tmp_path):
    carpeta = carpeta_fp(tmp_path, ESQUEMA_CRITERIOS, ACTIVIDADES_CRITERIOS)
    moodle = AulaViva(secciones=secciones_de(ACTIVIDADES_CRITERIOS), reescalar=True)
    atender(pedir(carpeta), moodle, carpeta)
    moodle.escrituras.clear()
    atender(pedir(carpeta), moodle, carpeta)
    assert moodle.escrituras == []  # montado desde cero converge a la primera
    # los criterios, que pesaban igual (50/50), pasan a 40/60: Moodle reescala los hermanos
    carpeta_fp(tmp_path, ESQUEMA_CRITERIOS_CON_PESO, ACTIVIDADES_CRITERIOS)
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "ok", documento
    # a la precisión con que el aula devuelve el peso (un decimal): ver _peso_correcto
    assert moodle.por_id("TZ_E_CE1_1").coeficiente == pytest.approx(40.0, abs=0.05)
    assert moodle.por_id("TZ_E_CE1_2").coeficiente == pytest.approx(60.0, abs=0.05)
    moodle.escrituras.clear()
    atender(pedir(carpeta), moodle, carpeta)
    assert moodle.escrituras == []


ESQUEMA_PLANO_TOPE = ESQUEMA.replace(
    "final: {de: elementos}", "final: {de: elementos, tope: {si_alguno_menor_que: 5, maximo: 4}}"
)
ESQUEMA_AMPLIADO = """\
organizacion: elementos
elementos:
  - id: RA1
    nombre: Redes
    peso: 60
    criterios: [{id: CE1, nombre: Configura, peso: 40}, {id: CE2, nombre: Documenta, peso: 60}]
  - {id: RA2, nombre: Sistemas, peso: 40}
evaluaciones:
  - {nombre: 1.ª evaluación, secciones: [1]}
  - {nombre: 2.ª evaluación, secciones: [2]}
final: {de: elementos, tope: {si_alguno_menor_que: 5, maximo: 4}}
instrumentos: [{id: EXAMEN, nombre: Examen, seccion: 2, evalua: {CE2: 20, RA2: 20}}]
"""
ACTIVIDADES_AMPLIADAS = (
    ("a", 1, 11, {"CE1": 60, "CE2": 50}),
    ("d", 1, 12, {"CE1": 40, "CE2": 30, "RA2": 50}),
    ("c", 2, 13, {"RA2": 30}),
)


def test_ampliar_un_calificador_montado_converge_en_el_segundo_montaje(tmp_path):
    carpeta = carpeta_fp(tmp_path, ESQUEMA_PLANO_TOPE)
    moodle = AulaViva(reescalar=True)
    atender(pedir(carpeta), moodle, carpeta)
    moodle.escrituras.clear()
    assert atender(pedir(carpeta), moodle, carpeta)["resultado"] == "ok"
    assert moodle.escrituras == []
    carpeta_fp(tmp_path, ESQUEMA_AMPLIADO, ACTIVIDADES_AMPLIADAS)
    moodle.escrituras.clear()
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "ok", documento
    assert moodle.escrituras
    moodle.escrituras.clear()
    atender(pedir(carpeta), moodle, carpeta)
    assert moodle.escrituras == []


def test_el_calificador_encuentra_por_el_registro_la_actividad_que_cambio_de_nombre(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    secciones = secciones_de()
    secciones[0]["modulos"][0]["nombre"] = "Otro nombre en el aula"  # a.md, cmid 11
    documentos = documentos_de_la_carpeta(carpeta)
    esperado = {"d.md": 12, "c.md": 13}
    assert publicacion._cmids_de(estructura_de(secciones), documentos, CURSO, carpeta) == esperado

    estado.guardar_publicado(
        carpeta / ".tiza", CURSO, "a.md", estado.Publicado(cmid=11, tipo="tarea")
    )
    documentos = documentos_de_la_carpeta(carpeta)
    assert publicacion._cmids_de(estructura_de(secciones), documentos, CURSO, carpeta) == {
        "a.md": 11,
        **esperado,
    }
    # En otro curso el registro no cuenta.
    assert (
        publicacion._cmids_de(estructura_de(secciones), documentos, CURSO + 1, carpeta) == esperado
    )


def test_el_calificador_no_adivina_si_el_registro_y_el_nombre_apuntan_a_actividades_distintas(
    tmp_path,
):
    carpeta = carpeta_fp(tmp_path)
    secciones = secciones_de()
    secciones[0]["modulos"][0]["nombre"] = "Otro nombre en el aula"  # a.md, cmid 11
    secciones[0]["modulos"].append({"cmid": 99, "nombre": "a", "tipo": "tarea"})
    estado.guardar_publicado(
        carpeta / ".tiza", CURSO, "a.md", estado.Publicado(cmid=11, tipo="tarea")
    )
    with pytest.raises(ErrorPublicacion) as exc:
        publicacion._cmids_de(
            estructura_de(secciones), documentos_de_la_carpeta(carpeta), CURSO, carpeta
        )
    assert exc.value.codigo == "ACTIVIDAD_AMBIGUA"


def _con_origen(carpeta: Path, nombre: str, cmid: int, *, origen_curso: int = CURSO) -> None:
    (carpeta / nombre).write_text(
        f"---\ntipo: tarea\nnombre: Problemas\nseccion: 1\n"
        f"apertura: 2026-10-01\nentrega: 2026-10-10\nevalua: {{RA1: 100}}\n"
        f"origen: {{curso: {origen_curso}, cmid: {cmid}}}\n---\n\nTexto\n",
        encoding="utf-8",
    )


def test_actividad_importada_con_origen_y_evalua_se_coloca(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    _con_origen(carpeta, "a.md", 11)
    assert publicacion._cmids_de(
        estructura_de(secciones_de()), documentos_de_la_carpeta(carpeta), CURSO, carpeta
    ) == {"a.md": 11, "d.md": 12, "c.md": 13}


def test_actividad_importada_renombrada_en_el_aula_se_sigue_colocando(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    _con_origen(carpeta, "a.md", 11)
    secciones = secciones_de()
    secciones[0]["modulos"][0]["nombre"] = "Nombre cambiado en el aula"
    assert (
        publicacion._cmids_de(
            estructura_de(secciones), documentos_de_la_carpeta(carpeta), CURSO, carpeta
        )["a.md"]
        == 11
    )


def test_dos_ficheros_mismo_origen_dan_actividad_ambigua(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    _con_origen(carpeta, "a.md", 11)
    _con_origen(carpeta, "b.md", 11)
    with pytest.raises(ErrorPublicacion) as exc:
        publicacion._cmids_de(
            estructura_de(secciones_de()), documentos_de_la_carpeta(carpeta), CURSO, carpeta
        )
    assert exc.value.codigo == "ACTIVIDAD_AMBIGUA"


def test_origen_que_ya_no_esta_en_el_aula_es_pendiente(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    _con_origen(carpeta, "a.md", 99)
    secciones = secciones_de()
    documentos = documentos_de_la_carpeta(carpeta)
    assert publicacion._cmids_de(estructura_de(secciones), documentos, CURSO, carpeta) == {
        "d.md": 12,
        "c.md": 13,
    }
    doc = next(d for d in documentos if d.ruta.name == "a.md")
    assert estructura_de(secciones).localizar(doc, CURSO).problema == "ORIGEN_NO_ENCONTRADO"


def test_cmids_de_ve_una_tarea_en_otra_seccion(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    secciones = secciones_de()
    for seccion in secciones:
        seccion["modulos"] = [m for m in seccion["modulos"] if m["cmid"] != 11]
    secciones[1]["modulos"].append({"cmid": 11, "nombre": "a", "tipo": "tarea"})
    assert (
        publicacion._cmids_de(
            estructura_de(secciones), documentos_de_la_carpeta(carpeta), CURSO, carpeta
        )["a.md"]
        == 11
    )


# --------------------------------------------------------------------------- #
# Evidencia por resultados (Tarea 4)
# --------------------------------------------------------------------------- #

ESQUEMA_RESULTADOS = """\
organizacion: elementos
etapa: eso
elementos:
  - id: RA1
    nombre: Redes
    peso: 100
    codigo: RA1
    criterios:
      - {id: CE2_2, nombre: Mantiene, peso: 50, codigo: "2.2"}
      - {id: CE3_1, nombre: Instala, peso: 50, codigo: "3.1"}
evaluaciones:
  - {nombre: 1.ª evaluación, secciones: [1]}
final: {de: elementos}
"""

TAREA_RESULTADOS = """\
---
tipo: tarea
nombre: grua
seccion: 1
apertura: 2026-10-01
entrega: 2026-10-10
evalua: {CE2_2: 100, CE3_1: 100}
evidencia: resultados
---

Texto.
"""


def carpeta_resultados(tmp_path: Path) -> Path:
    carpeta = tmp_path / "resultados"
    carpeta.mkdir()
    (carpeta / "calificacion.yaml").write_text(ESQUEMA_RESULTADOS, encoding="utf-8")
    (carpeta / "grua.md").write_text(TAREA_RESULTADOS, encoding="utf-8")
    return carpeta.resolve()


def secciones_resultados() -> list[dict]:
    return [
        {
            "numero": 1,
            "nombre": "Tema 1",
            "id": 10,
            "modulos": [{"cmid": 11, "nombre": "grua", "tipo": "tarea"}],
        }
    ]


def calificar_resultados(carpeta: Path, moodle, **opciones) -> dict:
    esquema, documentos = cargar_calificacion(carpeta / "calificacion.yaml", carpeta)
    return publicacion.calificador_con(
        moodle,
        "pruebas",
        CURSO,
        esquema,
        documentos,
        carpeta / ".tiza",
        evidencia_confirmada=True,
        **opciones,
    )


def resultados_del_aula(moodle) -> list[NodoAula]:
    return [n for n in moodle.nodos.values() if n.idnumber.startswith("TZ_O_")]


def test_preparar_calificador_ve_resultado_borrado_y_no_escribe(tmp_path):
    carpeta = carpeta_resultados(tmp_path)
    moodle = AulaViva(
        extra=[nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0)],
        secciones=secciones_resultados(),
    )
    montado = calificar_resultados(carpeta, moodle)
    assert montado["resultado"] == "ok", montado
    borrado = next(
        n
        for n in moodle.nodos.values()
        if n.idnumber.startswith("TZ_O_") and n.nombre == "2.2 · Mantiene"
    )
    del moodle.nodos[borrado.eid]
    moodle.escrituras.clear()

    esquema, documentos = cargar_calificacion(carpeta / "calificacion.yaml", carpeta)
    plan = publicacion.preparar_calificador(moodle, CURSO, esquema, documentos, carpeta / ".tiza")
    assert set(plan.resultados) == {"CE2_2", "CE3_1"}
    assert plan.resultados_pendientes is False
    assert plan.reconciliacion.hay_trabajo is True
    tipos = [op.tipo for op in plan.reconciliacion.operaciones]
    assert "marcar_resultado" in tipos
    assert any(codigo == "RESULTADO_RECREADO" for codigo, _ in plan.reconciliacion.avisos)
    assert moodle.escrituras == []

    presencia = PresenciaFalsa(real=False)
    antes = len(moodle.llamadas)
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert documento["resultado"] == "abortado"
    assert presencia.resumenes_calificador
    assert moodle.escrituras == []
    assert not [
        llamada
        for llamada in moodle.llamadas[antes:]
        if llamada[0] in ("asegurar_escala", "asegurar_resultado", "marcar_resultado_tarea")
    ]


def test_definicion_de_resultado_ausente_se_pregunta_y_con_si_se_monta(tmp_path):
    carpeta = carpeta_resultados(tmp_path)
    moodle = AulaViva(
        extra=[nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0)],
        secciones=secciones_resultados(),
        resultados_activos=False,
    )
    primero = calificar_resultados(carpeta, moodle)
    assert primero["resultado"] == "ok", primero
    moodle.resultados_activos_por_curso[CURSO] = True
    moodle.resultados_activos_por_curso[5678] = True
    moodle.escrituras.clear()

    esquema, documentos = cargar_calificacion(carpeta / "calificacion.yaml", carpeta)
    plan = publicacion.preparar_calificador(moodle, CURSO, esquema, documentos, carpeta / ".tiza")
    assert plan.resultados_pendientes is True
    assert plan.reconciliacion.hay_trabajo is False
    assert moodle.escrituras == []

    presencia = PresenciaFalsa(real=False)
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert documento["resultado"] == "abortado"
    assert presencia.resumenes_calificador
    assert moodle.escrituras == []
    assert not [
        llamada
        for llamada in moodle.llamadas
        if llamada[0] in ("asegurar_escala", "asegurar_resultado")
    ]

    montado = atender(pedir(carpeta, "real"), moodle, carpeta, PresenciaFalsa(real=True))
    assert montado["resultado"] == "ok", montado
    metodos = {llamada[0] for llamada in moodle.llamadas}
    assert "asegurar_escala" in metodos and "asegurar_resultado" in metodos
    assert len(resultados_del_aula(moodle)) == 2


def test_calificador_coloca_resultado_y_calculado(tmp_path):
    moodle = AulaViva(
        extra=[
            nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0),
            nodo(
                "ig201",
                "",
                "actividad",
                CURSO_EID,
                cmid=11,
                nombre="2.2 · Mantiene",
                maximo=None,
            ),
            nodo(
                "ig202",
                "",
                "actividad",
                CURSO_EID,
                cmid=11,
                nombre="3.1 · Instala",
                maximo=None,
            ),
        ],
        secciones=secciones_resultados(),
    )
    documento = calificar_resultados(carpeta_resultados(tmp_path), moodle)
    assert documento["resultado"] == "ok", documento
    resultados = resultados_del_aula(moodle)
    assert len(resultados) == 2
    por_criterio = {resultado.padre_eid: resultado for resultado in resultados}
    assert set(por_criterio) == {
        moodle.por_id("TZ_V_1_CE2_2").eid,
        moodle.por_id("TZ_V_1_CE3_1").eid,
    }
    for resultado in resultados:
        assert resultado.cmid == 11
        assert resultado.peso in (None, 0.0)
    calculados = [
        n
        for n in moodle.nodos.values()
        if n.clase == "calculado" and n.idnumber.startswith("TZ_R_")
    ]
    assert len(calculados) == 2  # un calculado por criterio en la vista primaria
    for calculado in calculados:
        fuente = next(
            resultado.idnumber
            for resultado in resultados
            if f"[[{resultado.idnumber}]]" in (calculado.formula or "")
        )
        assert calculado.formula == f"=([[{fuente}]]-1)/4*100"


def test_resultado_borrado_a_mano_se_recrea(tmp_path):
    moodle = AulaViva(
        extra=[
            nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0),
        ],
        secciones=secciones_resultados(),
    )
    documento = calificar_resultados(carpeta_resultados(tmp_path), moodle)
    assert documento["resultado"] == "ok", documento
    assert "RESULTADO_RECREADO" in [paso["codigo"] for paso in documento["pasos"]]
    resultados = resultados_del_aula(moodle)
    assert len(resultados) == 2
    assert {resultado.padre_eid for resultado in resultados} == {
        moodle.por_id("TZ_V_1_CE2_2").eid,
        moodle.por_id("TZ_V_1_CE3_1").eid,
    }


def test_montaje_idempotente(tmp_path):
    carpeta = carpeta_resultados(tmp_path)
    moodle = AulaViva(
        extra=[
            nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0),
        ],
        secciones=secciones_resultados(),
    )
    primero = calificar_resultados(carpeta, moodle)
    assert primero["resultado"] == "ok", primero
    escrituras = list(moodle.escrituras)
    segundo = calificar_resultados(carpeta, moodle)
    assert segundo["resultado"] == "ok", segundo
    assert pasos(segundo, "CALIFICADOR")[0]["detalle"] == "sin cambios"
    assert moodle.escrituras == escrituras


def test_calificador_con_no_no_asegura_resultados(tmp_path):
    carpeta = carpeta_resultados(tmp_path)
    moodle = AulaViva(
        extra=[nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0)],
        secciones=secciones_resultados(),
    )
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, PresenciaFalsa(real=False))
    assert documento["resultado"] == "abortado"
    assert not [
        llamada
        for llamada in moodle.llamadas
        if llamada[0] in ("asegurar_escala", "asegurar_resultado")
    ]


def test_calificador_con_resultados_desactivados_monta_el_resto(tmp_path):
    carpeta = carpeta_resultados(tmp_path)
    moodle = AulaViva(
        extra=[nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0)],
        secciones=secciones_resultados(),
        resultados_activos=False,
    )
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, PresenciaFalsa(real=True))
    assert documento["resultado"] == "ok", documento
    assert "RESULTADOS_DESACTIVADOS" in [paso["codigo"] for paso in documento["pasos"]]
    assert not [
        llamada
        for llamada in moodle.llamadas
        if llamada[0] in ("asegurar_escala", "asegurar_resultado")
    ]
    assert moodle.por_id("TZ_E_CE2_2")


def calificar_sin_evidencia(carpeta: Path, moodle) -> dict:
    esquema, documentos = cargar_calificacion(carpeta / "calificacion.yaml", carpeta)
    return publicacion.calificador_con(
        moodle, "pruebas", CURSO, esquema, documentos, carpeta / ".tiza"
    )


def test_calificador_sin_evidencia_no_consulta_resultados_desactivados(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva(resultados_activos=False)
    documento = calificar_sin_evidencia(carpeta, moodle)
    assert documento["resultado"] == "ok", documento
    assert "resultados_activos" not in {llamada[0] for llamada in moodle.llamadas}
    assert "RESULTADOS_DESACTIVADOS" not in [paso["codigo"] for paso in documento["pasos"]]
    assert "CALIFICADOR" in [paso["codigo"] for paso in documento["pasos"]]


def test_calificador_sin_evidencia_tampoco_consulta_resultados_activos(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()  # el aula tiene los resultados activos
    documento = calificar_sin_evidencia(carpeta, moodle)
    assert documento["resultado"] == "ok", documento
    assert "resultados_activos" not in {llamada[0] for llamada in moodle.llamadas}


def test_preguntar_evidencia_sin_evidencia_no_consulta_resultados(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    _esquema, documentos = cargar_calificacion(carpeta / "calificacion.yaml", carpeta)
    trabajo = publicacion._TrabajoPublicar(
        moodle,
        CFG,
        documentos,
        carpeta,
        PresenciaFalsa(),
        visible=True,
        solo_fechas=False,
        verificados=None,
        dir_vistas=None,
        debug=False,
    )
    turno = recorrido.Turno(
        curso=CURSO, posicion=1, total=1, nombre_curso=None, _presencia=PresenciaFalsa()
    )
    assert trabajo._preguntar_evidencia(turno, estructura_de(moodle), documentos) is False
    assert "resultados_activos" not in {llamada[0] for llamada in moodle.llamadas}


def test_calificador_con_si_asegura_resultados(tmp_path):
    carpeta = carpeta_resultados(tmp_path)
    moodle = AulaViva(
        extra=[nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0)],
        secciones=secciones_resultados(),
    )
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, PresenciaFalsa(real=True))
    assert documento["resultado"] == "ok", documento
    metodos = {llamada[0] for llamada in moodle.llamadas}
    assert "asegurar_escala" in metodos and "asegurar_resultado" in metodos
    assert len(resultados_del_aula(moodle)) == 2


def test_calificador_d11_con_no_deja_arbol_normal(tmp_path):
    carpeta = carpeta_resultados(tmp_path)
    moodle = AulaViva(
        extra=[nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0)],
        secciones=secciones_resultados(),
    )
    moodle.tareas_con_notas.add(11)
    presencia = PresenciaFalsa(real=True, evidencia=False)
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert documento["resultado"] == "ok", documento
    assert presencia.resumenes_evidencia == [
        publicacion.ResumenEvidencia(5678, None, ("grua",), 1, 1)
    ]
    assert not [
        llamada
        for llamada in moodle.llamadas
        if llamada[0] in ("asegurar_escala", "asegurar_resultado", "marcar_resultado_tarea")
    ]
    real = next(
        n
        for n in moodle.nodos.values()
        if n.cmid == 11 and n.clase == "actividad" and not n.idnumber.startswith("TZ_O_")
    )
    assert real.coeficiente is not None and real.coeficiente > 0
    assert [n for n in moodle.nodos.values() if n.idnumber.startswith("TZ_C_")]


def test_calificador_d11_con_si_marca_resultados(tmp_path):
    carpeta = carpeta_resultados(tmp_path)
    moodle = AulaViva(
        extra=[nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0)],
        secciones=secciones_resultados(),
    )
    moodle.tareas_con_notas.add(11)
    presencia = PresenciaFalsa(real=True, evidencia=True)
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert documento["resultado"] == "ok", documento
    assert presencia.resumenes_evidencia == [
        publicacion.ResumenEvidencia(5678, None, ("grua",), 1, 1)
    ]
    assert len(resultados_del_aula(moodle)) == 2
    real = next(
        n
        for n in moodle.nodos.values()
        if n.cmid == 11 and n.clase == "actividad" and not n.idnumber.startswith("TZ_O_")
    )
    assert real.coeficiente == 0.0
    assert len([n for n in moodle.nodos.values() if n.idnumber.startswith("TZ_R_")]) == 2
    assert not [n for n in moodle.nodos.values() if n.idnumber.startswith("TZ_CR_")]


def test_calificador_resultados_desactivados_deja_arbol_normal(tmp_path):
    carpeta = carpeta_resultados(tmp_path)
    moodle = AulaViva(
        extra=[nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0)],
        secciones=secciones_resultados(),
        resultados_activos=False,
    )
    presencia = PresenciaFalsa(real=True)
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert documento["resultado"] == "ok", documento
    assert "RESULTADOS_DESACTIVADOS" in [paso["codigo"] for paso in documento["pasos"]]
    assert any(aviso.codigo == "RESULTADOS_DESACTIVADOS" for aviso in presencia.avisos)
    assert not [
        llamada
        for llamada in moodle.llamadas
        if llamada[0] in ("asegurar_escala", "asegurar_resultado", "marcar_resultado_tarea")
    ]
    assert not [n for n in moodle.nodos.values() if n.idnumber.startswith("TZ_R_")]
    real = next(
        n
        for n in moodle.nodos.values()
        if n.cmid == 11 and n.clase == "actividad" and not n.idnumber.startswith("TZ_O_")
    )
    assert real.coeficiente is not None and real.coeficiente > 0
    assert [n for n in moodle.nodos.values() if n.idnumber.startswith("TZ_C_")]


def test_calificador_por_defecto_no_activa_resultados(tmp_path):
    carpeta = carpeta_resultados(tmp_path)
    moodle = AulaViva(
        extra=[nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0)],
        secciones=secciones_resultados(),
    )
    esquema, documentos = cargar_calificacion(carpeta / "calificacion.yaml", carpeta)
    documento = publicacion.calificador_con(
        moodle, "pruebas", CURSO, esquema, documentos, carpeta / ".tiza"
    )
    assert documento["resultado"] == "ok", documento
    assert not [
        llamada
        for llamada in moodle.llamadas
        if llamada[0] in ("asegurar_escala", "asegurar_resultado", "marcar_resultado_tarea")
    ]
    assert not resultados_del_aula(moodle)


def test_calificador_niega_solo_la_tarea_con_notas(tmp_path):
    carpeta = tmp_path / "mixta"
    carpeta.mkdir()
    (carpeta / "calificacion.yaml").write_text(ESQUEMA_RESULTADOS, encoding="utf-8")
    (carpeta / "grua.md").write_text(
        TAREA_RESULTADOS.replace("evalua: {CE2_2: 100, CE3_1: 100}", "evalua: {CE2_2: 100}"),
        encoding="utf-8",
    )
    (carpeta / "nueva.md").write_text(
        TAREA_RESULTADOS.replace("nombre: grua", "nombre: nueva").replace(
            "evalua: {CE2_2: 100, CE3_1: 100}", "evalua: {CE3_1: 100}"
        ),
        encoding="utf-8",
    )
    carpeta = carpeta.resolve()
    moodle = AulaViva(
        extra=[
            nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0),
            nodo("ig12", "", "actividad", CURSO_EID, cmid=12, nombre="nueva", maximo=10.0),
        ],
        secciones=[
            {
                "numero": 1,
                "nombre": "Tema 1",
                "id": 10,
                "modulos": [
                    {"cmid": 11, "nombre": "grua", "tipo": "tarea"},
                    {"cmid": 12, "nombre": "nueva", "tipo": "tarea"},
                ],
            }
        ],
    )
    moodle.tareas_con_notas.add(11)
    presencia = PresenciaFalsa(real=True, evidencia=False)
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert documento["resultado"] == "ok", documento
    assert presencia.resumenes_evidencia == [
        publicacion.ResumenEvidencia(5678, None, ("grua",), 1, 1)
    ]
    cortos = {r["corto"] for r in moodle.resultados.get(5678, [])}
    assert "TZ_CE3_1" in cortos and "TZ_CE2_2" not in cortos
    resultados = resultados_del_aula(moodle)
    assert len(resultados) == 1 and resultados[0].cmid == 12
    real_grua = next(
        n
        for n in moodle.nodos.values()
        if n.cmid == 11 and n.clase == "actividad" and not n.idnumber.startswith("TZ_O_")
    )
    real_nueva = next(
        n
        for n in moodle.nodos.values()
        if n.cmid == 12 and n.clase == "actividad" and not n.idnumber.startswith("TZ_O_")
    )
    assert real_grua.coeficiente is not None and real_grua.coeficiente > 0
    assert real_nueva.coeficiente == 0.0
    assert any(n.idnumber.startswith("TZ_C_") for n in moodle.nodos.values())
    assert not any(n.idnumber.startswith("TZ_O_") and n.cmid == 11 for n in moodle.nodos.values())


def test_calificador_sin_estructura_no_activa_resultados(tmp_path):
    carpeta = carpeta_resultados(tmp_path)
    moodle = AulaViva(
        extra=[nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0)],
        secciones=secciones_resultados(),
    )
    moodle.tareas_con_notas.add(11)
    original = moodle.estructura
    llamadas = {"n": 0}

    def estructura(curso):
        llamadas["n"] += 1
        if llamadas["n"] >= 2:
            raise ErrorPublicacion("ERROR_ESTRUCTURA")
        return original(curso)

    moodle.estructura = estructura
    presencia = PresenciaFalsa(real=True, evidencia=True)
    documento = atender(pedir(carpeta, "real"), moodle, carpeta, presencia)
    assert documento["resultado"] == "ok", documento
    assert not presencia.resumenes_evidencia
    assert not [
        llamada
        for llamada in moodle.llamadas
        if llamada[0] in ("asegurar_escala", "asegurar_resultado", "marcar_resultado_tarea")
    ]
    assert not resultados_del_aula(moodle)
    real = next(
        n
        for n in moodle.nodos.values()
        if n.cmid == 11 and n.clase == "actividad" and not n.idnumber.startswith("TZ_O_")
    )
    assert real.coeficiente is not None and real.coeficiente > 0


def test_publicar_con_no_y_calificador_no_marca_resultados(tmp_path):
    carpeta = carpeta_resultados(tmp_path)
    normal = carpeta / "grua_normal.md"
    normal.write_text(TAREA_RESULTADOS.replace("evidencia: resultados\n", ""), encoding="utf-8")
    moodle = AulaViva(secciones=secciones_resultados(), extra=[])
    creado = publicacion.publicar_con(
        moodle,
        "pruebas",
        CURSO,
        [contenido.cargar(normal, raiz=carpeta)],
        False,
        carpeta,
        PresenciaFalsa(),
    )
    assert creado.informe is not None and creado.informe["resultado"] == "ok"
    cmid = creado.informe["ficheros"][0]["cmid"]
    moodle.nodos[f"ig{cmid}"] = nodo(
        f"ig{cmid}", "", "actividad", CURSO_EID, cmid=cmid, nombre="grua", maximo=10.0
    )
    moodle.tareas_con_notas.add(cmid)
    normal.unlink()

    publicado = publicacion.publicar_con(
        moodle,
        "pruebas",
        CURSO,
        [contenido.cargar(carpeta / "grua.md", raiz=carpeta)],
        False,
        carpeta,
        PresenciaFalsa(evidencia=False),
    )
    assert publicado.informe is not None and publicado.informe["resultado"] == "ok"
    assert "EVIDENCIA_CAMBIADA_CON_NOTAS" in [paso["codigo"] for paso in publicado.informe["pasos"]]
    antes = len(moodle.llamadas)
    esquema, documentos = cargar_calificacion(carpeta / "calificacion.yaml", carpeta)
    documento = publicacion.calificador_con(
        moodle,
        "pruebas",
        CURSO,
        esquema,
        documentos,
        carpeta / ".tiza",
        evidencia_confirmada=False,
    )
    assert documento["resultado"] == "ok", documento
    assert not [
        llamada
        for llamada in moodle.llamadas[antes:]
        if llamada[0] in ("asegurar_escala", "asegurar_resultado", "marcar_resultado_tarea")
    ]
    assert not [n for n in moodle.nodos.values() if n.idnumber.startswith("TZ_O_")]
    real = next(n for n in moodle.nodos.values() if n.cmid == cmid and n.clase == "actividad")
    assert real.coeficiente is not None and real.coeficiente > 0
    assert [n for n in moodle.nodos.values() if n.idnumber.startswith("TZ_C_")]


ESQUEMA_MAS_ALTA = ESQUEMA_CRITERIOS.replace(
    "{id: CE1_2, nombre: Documenta}", "{id: CE1_2, nombre: Documenta, regla: mas_alta}"
)
ESQUEMA_MEDIANA = ESQUEMA_MAS_ALTA.replace("regla: mas_alta", "regla: mediana")


def test_el_calificador_monta_una_regla_mas_alta(tmp_path):
    carpeta = carpeta_fp(tmp_path, ESQUEMA_MAS_ALTA, ACTIVIDADES_CRITERIOS)
    moodle = AulaViva(secciones=secciones_de(ACTIVIDADES_CRITERIOS))
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "ok", documento
    ag = moodle.por_id("TZ_E_CE1_2")
    assert (ag.clase, ag.agregacion) == ("categoria", 6)
    assert moodle.por_id("TZ_V_1_CE1_2").agregacion == 6
    hijos = [n for n in moodle.nodos.values() if n.padre_eid == ag.eid]
    assert hijos
    assert all(not n.sobrescrito for n in hijos)


def test_cambiar_la_regla_en_el_aula_avisa_y_la_cambia(tmp_path):
    carpeta = carpeta_fp(tmp_path, ESQUEMA_MAS_ALTA, ACTIVIDADES_CRITERIOS)
    moodle = AulaViva(secciones=secciones_de(ACTIVIDADES_CRITERIOS))
    atender(pedir(carpeta), moodle, carpeta)
    assert moodle.por_id("TZ_E_CE1_2").agregacion == 6
    carpeta_fp(tmp_path, ESQUEMA_MEDIANA, ACTIVIDADES_CRITERIOS)
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "ok", documento
    assert moodle.por_id("TZ_E_CE1_2").agregacion == 2
    assert moodle.por_id("TZ_V_1_CE1_2").agregacion == 2
    assert int(pasos(documento, "REGLA_CAMBIADA")[0]["detalle"]) >= 1


# --------------------------------------------------------------------------- #
# R1: el alumnado no ve los calculados
# --------------------------------------------------------------------------- #


def un_calculado_visible(moodle: AulaViva) -> NodoAula:
    calculado = next(n for n in moodle.nodos.values() if n.clase == "calculado")
    moodle.nodos[calculado.eid] = dataclasses.replace(calculado, oculto=False)
    return calculado


def test_ocultar_marca_tocado(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    atender(pedir(carpeta), moodle, carpeta)
    calculado = un_calculado_visible(moodle)
    moodle.relecturas.clear()
    presencia = PresenciaFalsa()
    documento = atender(pedir(carpeta), moodle, carpeta, presencia)
    assert documento["resultado"] == "ok", documento
    assert moodle.por_id(calculado.idnumber).oculto is True
    assert any(f"ig{calculado.item_id}" in (tocados or set()) for tocados in moodle.relecturas)
    assert pasos(documento, "CALCULADOS_OCULTADOS")[0]["detalle"] == "1"
    assert "CALCULADOS_OCULTADOS" in presencia.codigos()


def test_ocultar_sin_efecto_avisa_ocultar_fallido_sin_reintentar(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    atender(pedir(carpeta), moodle, carpeta)
    un_calculado_visible(moodle)
    moodle.ignorar_ocultar = True
    moodle.escrituras.clear()
    presencia = PresenciaFalsa()
    documento = atender(pedir(carpeta), moodle, carpeta, presencia)
    assert documento["resultado"] == "ok", documento
    assert moodle.metodos().count("ocultar") == 1  # ni las 8 pasadas ni otra vuelta
    assert [p["detalle"] for p in pasos(documento, "OCULTAR_FALLIDO")] == ["1"]
    assert pasos(documento, "CALCULADOS_OCULTADOS")[0]["detalle"] == "1"
    assert "OCULTAR_FALLIDO" in presencia.codigos()


def test_ocultar_rechazado_por_el_aula_no_corta_el_curso(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    atender(pedir(carpeta), moodle, carpeta)
    un_calculado_visible(moodle)

    def rechazar(curso, item_id):
        raise ErrorPublicacion("ESCRITURA_CALIFICADOR")

    moodle.ocultar = rechazar
    presencia = PresenciaFalsa()
    documento = atender(pedir(carpeta), moodle, carpeta, presencia)
    assert documento["resultado"] == "ok", documento
    assert not [
        p for p in documento["pasos"] if p["resultado"] == "fallo" and p["codigo"] == "CALIFICADOR"
    ]
    assert [p["detalle"] for p in pasos(documento, "OCULTAR_FALLIDO")] == ["1"]
    assert not pasos(documento, "CALCULADOS_OCULTADOS")
    assert "OCULTAR_FALLIDO" in presencia.codigos()


def test_alta_que_no_queda_oculta_avisa_ocultar_fallido(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva(ignorar_alta_oculta=True)
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "ok", documento
    creados = len([e for e in moodle.escrituras if e[0] == "crear_calculado"])
    assert creados == 4  # copias del curso y de la rúbrica nativa (ninguna casilla manual)
    assert "ocultar" not in moodle.metodos()  # eran altas: no se reintenta ocultándolas
    assert [p["detalle"] for p in pasos(documento, "OCULTAR_FALLIDO")] == [str(creados)]
    assert not pasos(documento, "CALCULADOS_OCULTADOS")


def test_el_resumen_dice_cuantos_calculados_ocultara(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    atender(pedir(carpeta), moodle, carpeta)
    un_calculado_visible(moodle)
    presencia = PresenciaFalsa(real=True)
    documento = atender(
        pedir(carpeta, "real"), moodle, carpeta, presencia, cfg=CFG, nombres={5678: "Mates"}
    )
    assert documento["resultado"] == "ok", documento
    [resumen] = presencia.resumenes_calificador
    assert resumen.ocultadas == 1
    assert "Ocultaré a tu alumnado 1 nota calculada" in mensajes.detalle_calificador(resumen).lineas


def test_el_resumen_avisa_si_el_curso_muestra_los_totales(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    moodle.ajustes_totales[5678] = 1  # «mostrar incluyendo los ítems ocultos»
    presencia = PresenciaFalsa(real=True)
    atender(pedir(carpeta, "real"), moodle, carpeta, presencia, cfg=CFG, nombres={5678: "Mates"})
    [resumen] = presencia.resumenes_calificador
    assert "TOTALES_VISIBLES" in [aviso.codigo for aviso in resumen.avisos]
    lineas = mensajes.detalle_calificador(resumen).lineas
    assert any("«Ocultar los totales si contienen ítems ocultos»" in linea for linea in lineas)


def test_totales_visibles_deja_paso_en_pruebas_y_no_avisa_con_ocultar(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    moodle.ajustes_totales[CURSO] = 2  # «mostrar excluyendo los ítems ocultos»
    presencia = PresenciaFalsa()
    documento = atender(pedir(carpeta), moodle, carpeta, presencia)
    assert documento["resultado"] == "ok", documento
    assert pasos(documento, "TOTALES_VISIBLES")
    assert "TOTALES_VISIBLES" in presencia.codigos()
    # Con el ajuste por defecto (o ilegible) no se avisa.
    moodle.ajustes_totales[CURSO] = -1
    otro = atender(pedir(carpeta), moodle, carpeta)
    assert not pasos(otro, "TOTALES_VISIBLES")


# --- Descriptores en los resultados: una escala y un resultado por fila --------


def carpeta_filas(tmp_path: Path) -> Path:
    carpeta = tmp_path / "filas"
    carpeta.mkdir()
    (carpeta / "calificacion.yaml").write_text(ESQUEMA_RESULTADOS, encoding="utf-8")
    (carpeta / "rubricas").mkdir()
    (carpeta / "rubricas" / "grua.md").write_text(
        "---\ntipo: rubrica\nnombre: Rúbrica de la grúa\nfilas:\n"
        "  - criterio: CE2_2\n    indicador: Planifica\n    peso: 1\n    niveles:\n"
        "      destacado: Lo hace muy bien.\n      avanzado: Lo hace bien.\n"
        "      adecuado: Lo hace.\n      inicial: Lo intenta.\n"
        "      no_iniciado: No lo hace.\n"
        "  - criterio: CE2_2\n    indicador: Materiales\n    peso: 2\n    niveles:\n"
        "      destacado: Lo hace muy bien.\n      avanzado: Lo hace bien.\n"
        "      adecuado: Lo hace.\n      inicial: Lo intenta.\n"
        "      no_iniciado: No lo hace.\n"
        "  - criterio: CE3_1\n    indicador: Instala\n    peso: 1\n    niveles:\n"
        "      destacado: Lo hace muy bien.\n      avanzado: Lo hace bien.\n"
        "      adecuado: Lo hace.\n      inicial: Lo intenta.\n"
        "      no_iniciado: No lo hace.\n"
        "---\n\nDescripción de la rúbrica para el alumnado.\n",
        encoding="utf-8",
    )
    (carpeta / "grua.md").write_text(
        TAREA_RESULTADOS.replace(
            "evidencia: resultados\n", "evidencia: resultados\nrubrica: rubricas/grua.md\n"
        ),
        encoding="utf-8",
    )
    return carpeta.resolve()


def test_montaje_con_filas_converge_y_oculta_los_calculados(tmp_path):
    carpeta = carpeta_filas(tmp_path)
    moodle = AulaViva(
        extra=[nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0)],
        secciones=secciones_resultados(),
    )
    esquema, documentos = cargar_calificacion(carpeta / "calificacion.yaml", carpeta)
    primero = publicacion.calificador_con(
        moodle, "pruebas", CURSO, esquema, documentos, carpeta / ".tiza", evidencia_confirmada=True
    )
    assert primero["resultado"] == "ok", primero
    resultados = resultados_del_aula(moodle)
    assert len(resultados) == 3
    calculados = [n for n in moodle.nodos.values() if n.idnumber.startswith("TZ_R_")]
    assert len(calculados) == 3
    assert all(n.oculto for n in calculados)
    assert not any(n.idnumber.startswith("TZ_F_") for n in moodle.nodos.values())
    escrituras = list(moodle.escrituras)
    segundo = publicacion.calificador_con(
        moodle, "pruebas", CURSO, esquema, documentos, carpeta / ".tiza", evidencia_confirmada=True
    )
    assert segundo["resultado"] == "ok", segundo
    assert pasos(segundo, "CALIFICADOR")[0]["detalle"] == "sin cambios"
    assert moodle.escrituras == escrituras


def test_calificador_avisa_descriptor_publicado_y_no_cambia_la_escala(tmp_path):
    from tiza.rubrica_tarea import clave_de_fila

    carpeta = carpeta_filas(tmp_path)
    clave = clave_de_fila("grua.md", "CE2_2", "Planifica")
    nombre_escala = f"Escala · CE2_2 · Planifica · {clave}"
    moodle = AulaViva(
        extra=[nodo("ig11", "", "actividad", CURSO_EID, cmid=11, nombre="grua", maximo=10.0)],
        secciones=secciones_resultados(),
        escalas=[{"id": 88, "nombre": nombre_escala, "niveles": ("Uno", "Dos")}],
        resultados=[
            {
                "id": 71,
                "corto": "TZ_OTRO",
                "nombre": "Otro resultado",
                "descripcion": "",
                "escala": 88,
            }
        ],
    )
    documento = calificar_resultados(carpeta, moodle)
    assert documento["resultado"] == "ok", documento
    assert "DESCRIPTOR_PUBLICADO" in [paso["codigo"] for paso in documento["pasos"]]
    escala = next(e for e in moodle._escalas_de(5678) if e["id"] == 88)
    assert tuple(escala["niveles"]) == ("Uno", "Dos")


def test_calificador_antiguo_no_escribe_nada(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva(
        extra=[
            *nodos_de_actividades(),
            nodo("ig99", "TZ_NOTAS", "calculado", CURSO_EID, maximo=10.0),
        ]
    )
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "error"
    assert documento["errores"] == ["CALIFICADOR_ANTIGUO"]
    assert moodle.escrituras == []


def test_calificador_sin_media_ponderada_no_escribe_nada(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    moodle.nodos[CURSO_EID] = dataclasses.replace(
        moodle.nodos[CURSO_EID], opciones_agregacion=(13, 2, 6)
    )
    documento = atender(pedir(carpeta), moodle, carpeta)
    assert documento["resultado"] == "error"
    assert documento["errores"] == ["CALCULO_NO_DISPONIBLE"]
    assert moodle.escrituras == []


def test_ponderaciones_visibles_avisa(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    moodle = AulaViva()
    moodle.ponderaciones[CURSO] = True
    presencia = PresenciaFalsa()
    documento = atender(pedir(carpeta), moodle, carpeta, presencia)
    assert documento["resultado"] == "ok", documento
    assert pasos(documento, "PONDERACIONES_VISIBLES")
    assert "PONDERACIONES_VISIBLES" in presencia.codigos()


def test_un_calificador_json_version_1_sin_arbol_antiguo_se_olvida(tmp_path):
    carpeta = carpeta_fp(tmp_path)
    estado.guardar_huellas(carpeta / ".tiza", CURSO, {"TZ_VIEJO": "a" * 64})
    ruta = carpeta / ".tiza" / "calificador.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["version"] = 1
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    assert estado.version_de_calificador(carpeta / ".tiza") == 1

    documento = atender(pedir(carpeta), AulaViva(), carpeta)
    assert documento["resultado"] == "ok", documento
    assert estado.version_de_calificador(carpeta / ".tiza") == 2
    assert estado.cargar_huellas(carpeta / ".tiza", CURSO) != {}
