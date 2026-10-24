"""Tests del modelo del panel (``tiza.panel.estado``): sin ventana, sin pywebview, sin red."""

from __future__ import annotations

import inspect
import json
import threading
import time
from datetime import UTC, datetime

import pytest

from tiza import aislamiento, config, mensajes, publicacion, publicar
from tiza.panel import estado as pe
from tiza.panel.estado import Panel, PresenciaPanel, Puente
from tiza.sesion import SIN_PRUEBAS, CursoSesion


class Reloj:
    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora

    def avanzar(self, segundos: float = 1.0) -> None:
        self.ahora += segundos


class Entorno:
    """Un panel, su presencia y su puente, con reloj falso."""

    def __init__(self, abrir_login=None, abrir=None) -> None:
        self.reloj = Reloj()
        self.panel = Panel(reloj=self.reloj)
        self.presencia = PresenciaPanel(self.panel, abrir_login=abrir_login, reloj=self.reloj)
        self.abiertas: list[str] = []
        self.puente = Puente(self.panel, abrir=abrir or self.abiertas.append)
        self.hilos: list[threading.Thread] = []

    def lanzar(self, funcion, *args, **kwargs):
        """Ejecuta la llamada de la presencia en un hilo; devuelve un lector del resultado."""
        resultado: dict = {}

        def correr() -> None:
            try:
                resultado["valor"] = funcion(*args, **kwargs)
            except BaseException as exc:  # pragma: no cover - se ve en el test
                resultado["error"] = exc

        hilo = threading.Thread(target=correr, daemon=True)
        hilo.start()
        self.hilos.append(hilo)

        def leer(timeout: float = 5.0):
            hilo.join(timeout)
            assert not hilo.is_alive(), "el hilo sigue bloqueado"
            if "error" in resultado:
                raise resultado["error"]
            return resultado["valor"]

        return leer

    def pantalla(self, ultimo: int = 0, tipo: str | None = None) -> dict:
        """Espera una pantalla nueva (con pregunta pendiente) y la devuelve."""
        limite = time.monotonic() + 5
        while time.monotonic() < limite:
            numero = self.panel.esperar_cambio(ultimo, 0.2)
            actual = self.puente.estado()["pantalla"]
            if numero != ultimo and actual["tipo"] != "reposo" and (tipo in (None, actual["tipo"])):
                return actual
            ultimo = numero if numero != ultimo and actual["tipo"] == "reposo" else ultimo
        raise AssertionError("no llegó la pantalla")

    def responder(self, pantalla: dict, respuesta, *, esperar: bool = True) -> bool:
        if esperar:
            self.reloj.avanzar(pe.RETARDO_RESPUESTA + 0.1)
        return self.puente.responder(pantalla["numero"], respuesta)

    def cerrar(self) -> None:
        self.panel.cerrar()
        for hilo in self.hilos:
            hilo.join(5)
            assert not hilo.is_alive()


@pytest.fixture
def entorno():
    e = Entorno()
    yield e
    e.cerrar()


CURSOS = [
    {"id": 11, "nombre": "Matemáticas 2ºB"},
    {"id": 22, "nombre": "Física"},
    {"id": 33, "nombre": "Dibujo"},
]


def _doc(**cambios):
    datos = {
        "fichero": "t.md",
        "tipo": "tarea",
        "nombre": "Problemas",
        "seccion": "Fracciones",
        "fechas": None,
        "vista_previa": None,
        "enlaces_externos": (),
        "incrustados": (),
        "recursos": (),
    }
    datos.update(cambios)
    return publicacion.DocumentoResumen(**datos)


def _resumen(doc=None, **cambios):
    datos = {
        "curso": 5678,
        "nombre_curso": "Matemáticas 2ºB",
        "documentos": (doc or _doc(),),
        "secciones_nuevas": ("Tema nuevo",),
        "visible": None,
    }
    datos.update(cambios)
    return publicacion.ResumenPublicacion(**datos)


# --- contrato ---------------------------------------------------------------------------


def test_presencia_panel_cumple_la_interfaz_de_presencia():
    metodos = [
        nombre
        for nombre, valor in vars(publicacion.Presencia).items()
        if callable(valor) and not nombre.startswith("_")
    ]
    assert len(metodos) == 21
    for nombre in metodos:
        esperado = list(inspect.signature(getattr(publicacion.Presencia, nombre)).parameters)
        obtenido = list(inspect.signature(getattr(PresenciaPanel, nombre)).parameters)
        assert obtenido == esperado, nombre


def test_el_puente_no_expone_atributos_publicos_que_sean_objetos(entorno):
    publicos = [n for n in dir(entorno.puente) if not n.startswith("_")]
    assert sorted(publicos) == ["estado", "responder", "ver_vista_previa"]
    assert all(callable(getattr(entorno.puente, n)) for n in publicos)
    assert not [n for n in vars(entorno.puente) if not n.startswith("_")]


def test_las_pantallas_son_json_y_de_tipo_cerrado(entorno):
    json.dumps(entorno.puente.estado())
    with pytest.raises(ValueError):
        pe.Pantalla(0, "inventada")


# --- una pregunta por método ---------------------------------------------------------------


def test_confirmar_real_coincide_con_detalle_real_y_responde(entorno):
    resumen = _resumen()
    leer = entorno.lanzar(entorno.presencia.confirmar_real, resumen)
    p = entorno.pantalla()
    detalle = mensajes.detalle_real(resumen)
    assert p["tipo"] == "confirmar"
    assert p["titulo"] == detalle.encabezado
    assert [(b["titulo"], tuple(b["lineas"])) for b in p["bloques"]] == [
        (d.titulo, d.lineas) for d in detalle.documentos
    ]
    for linea in detalle.finales:
        assert linea in p["lineas"]
    assert mensajes.linea_destino("real", 5678, "Matemáticas 2ºB") in p["lineas"]
    assert p["pregunta"] == mensajes.PREGUNTA_DESTINO
    assert entorno.responder(p, True)
    assert leer() is True


def test_confirmar_real_no(entorno):
    leer = entorno.lanzar(entorno.presencia.confirmar_real, _resumen())
    p = entorno.pantalla()
    assert entorno.responder(p, False)
    assert leer() is False


def test_vista_previa_solo_la_que_guarda_la_pantalla(tmp_path):
    vista = tmp_path / "v.html"
    vista.write_text("<p>x</p>", encoding="utf-8")
    e = Entorno()
    resumen = _resumen(_doc(vista_previa=vista))
    leer = e.lanzar(e.presencia.confirmar_real, resumen)
    p = e.pantalla()
    assert p["bloques"][0]["vista"] == 0
    assert not e.puente.ver_vista_previa(p["numero"], 1)
    assert not e.puente.ver_vista_previa(p["numero"] + 1, 0)
    assert not e.puente.ver_vista_previa(p["numero"], True)
    assert not e.puente.ver_vista_previa(p["numero"], "0")
    assert not e.puente.ver_vista_previa(None, None)
    assert e.puente.ver_vista_previa(p["numero"], 0)
    assert e.abiertas == [vista.resolve().as_uri()]
    e.responder(p, False)
    assert leer() is False
    assert not e.puente.ver_vista_previa(p["numero"], 0)  # ya no hay pregunta
    e.cerrar()


def test_vista_previa_que_ya_no_existe_no_se_abre(tmp_path):
    e = Entorno()
    resumen = _resumen(_doc(vista_previa=tmp_path / "no_existe.html"))
    leer = e.lanzar(e.presencia.confirmar_real, resumen)
    p = e.pantalla()
    assert not e.puente.ver_vista_previa(p["numero"], 0)
    e.responder(p, False)
    leer()
    e.cerrar()


def test_confirmar_real_sin_pruebas(entorno):
    resumen = publicacion.ResumenSinPruebas(
        curso=5678,
        nombre_curso="Mates",
        documentos=(publicacion.DocumentoBreve("t.md", "tarea", "Problemas"),),
        secciones_nuevas=(),
    )
    leer = entorno.lanzar(entorno.presencia.confirmar_real_sin_pruebas, resumen)
    p = entorno.pantalla()
    detalle = mensajes.detalle_corto(resumen)
    assert p["titulo"] == detalle.encabezado
    assert detalle.aviso in p["lineas"]
    assert [b["titulo"] for b in p["bloques"]] == [d.titulo for d in detalle.documentos]
    entorno.responder(p, True)
    assert leer() is True


def test_confirmar_orden(entorno):
    resumen = publicacion.ResumenOrden(
        curso=5678,
        nombre_curso="Mates",
        secciones=(
            publicacion.SeccionOrden(
                "Tema 1",
                (
                    publicacion.ActividadOrden("A", "page", "a.md"),
                    publicacion.ActividadOrden("B", "assign", "b.md"),
                ),
            ),
        ),
        posicion=2,
        total=3,
    )
    leer = entorno.lanzar(entorno.presencia.confirmar_orden, resumen)
    p = entorno.pantalla()
    detalle = mensajes.detalle_orden(resumen)
    assert p["titulo"] == detalle.encabezado
    assert [(b["titulo"], tuple(b["lineas"])) for b in p["bloques"]] == [
        (t, ls) for t, ls in detalle.secciones
    ]
    assert p["lineas"][0] == f"Curso 2 de 3: {detalle.curso}"
    entorno.responder(p, True)
    assert leer() is True


def test_confirmar_calificador(entorno):
    resumen = publicacion.ResumenCalificador(
        curso=5678,
        nombre_curso="Mates",
        lineas_esquema=(),
        mueve=("Tarea 1",),
        bloquea=(),
        ids_nuevos=(),
        cerradas=(),
        avisos=(),
    )
    leer = entorno.lanzar(entorno.presencia.confirmar_calificador, resumen)
    p = entorno.pantalla()
    detalle = mensajes.detalle_calificador(resumen)
    assert p["titulo"] == detalle.encabezado
    assert tuple(p["lineas"][: len(detalle.lineas)]) == detalle.lineas
    entorno.responder(p, False)
    assert leer() is False


def test_confirmar_copia(entorno):
    resumen = publicacion.ResumenCopia(
        curso=5678, nombre_curso="Mates", entorno="real", actividades=("Problemas",)
    )
    leer = entorno.lanzar(entorno.presencia.confirmar_copia, resumen)
    p = entorno.pantalla()
    detalle = mensajes.detalle_copia(resumen)
    assert p["pregunta"] == detalle.pregunta
    assert mensajes.linea_de_copia(detalle) in p["lineas"]
    assert "· Problemas" in p["lineas"]
    entorno.responder(p, True)
    assert leer() is True


def test_confirmar_sobrescribir(entorno):
    resumen = publicacion.ResumenSobrescribir(
        curso=5678, nombre_curso="Mates", actividades=("Problemas",)
    )
    leer = entorno.lanzar(entorno.presencia.confirmar_sobrescribir, resumen)
    p = entorno.pantalla()
    detalle = mensajes.detalle_sobrescribir(resumen)
    assert p["titulo"] == detalle.encabezado
    assert p["pregunta"] == detalle.pregunta
    assert "  · Problemas" in p["lineas"]
    entorno.responder(p, True)
    assert leer() is True


def test_confirmar_cursos_y_texto_seguro(entorno):
    cursos = [
        CursoSesion("pruebas", 1, "Pruebas", False),
        CursoSesion("real", 2, "Mates\x1b[2K‮oculto", True),
    ]
    leer = entorno.lanzar(entorno.presencia.confirmar_cursos, cursos)
    p = entorno.pantalla()
    assert tuple(p["lineas"]) == mensajes.lineas_de_cursos(cursos)
    texto = json.dumps(p, ensure_ascii=False)
    assert "\x1b" not in texto and "‮" not in texto
    assert "Mates[2Koculto" in texto
    entorno.responder(p, True)
    assert leer() is True


@pytest.mark.parametrize(
    ("metodo", "args", "texto"),
    [
        ("confirmar_autoprueba", (), mensajes.AUTOPRUEBA_TEXTO),
        ("confirmar_sin_pruebas", (), mensajes.SIN_PRUEBAS_AVISO),
        ("confirmar_actualizacion", ("v0.30.0", "0.29.2"), "0.30.0"),
        ("confirmar_carpeta_dudosa", ("/tmp/nada",), "no parece la carpeta"),
        ("cerrar_sesion_anterior", (True,), mensajes.SESION_ANTERIOR_ATENDIENDO),
        (
            "seguir_sin_aislar",
            ([aislamiento.Comprobacion("Codex", "falta", "sin perfil")],),
            "Codex",
        ),
    ],
)
@pytest.mark.parametrize("valor", [True, False])
def test_preguntas_de_si_o_no(entorno, metodo, args, texto, valor):
    leer = entorno.lanzar(getattr(entorno.presencia, metodo), *args)
    p = entorno.pantalla()
    assert texto in " ".join(p["lineas"])
    assert p["pregunta"]
    assert entorno.responder(p, valor)
    assert leer() is valor


def test_ofrecer_aislamiento(entorno):
    leer = entorno.lanzar(entorno.presencia.ofrecer_aislamiento)
    p = entorno.pantalla()
    assert p["pregunta"] == mensajes.PREGUNTA_AISLAR_AQUI
    entorno.responder(p, True)
    assert leer() is True


def test_confirmar_aislamiento_con_cambios(entorno):
    resumen = publicacion.ResumenAislamiento(
        ficheros=(publicacion.FicheroAislamiento("/x/perfil.json", ("añade un permiso",)),),
        manuales=("Cambia esto a mano.",),
    )
    leer = entorno.lanzar(entorno.presencia.confirmar_aislamiento, resumen)
    p = entorno.pantalla()
    assert tuple(p["lineas"]) == mensajes.lineas_de_aislamiento(resumen)
    entorno.responder(p, False)
    assert leer() is False
    registro = entorno.puente.estado()["registro"]
    assert {"texto": "No se ha cambiado nada.", "error": True} in registro


def test_confirmar_aislamiento_sin_ficheros_no_pregunta(entorno):
    resumen = publicacion.ResumenAislamiento(ficheros=(), manuales=("Solo a mano.",))
    assert entorno.presencia.confirmar_aislamiento(resumen) is True
    assert entorno.puente.estado()["registro"] == [{"texto": "Solo a mano.", "error": False}]


def test_elegir_curso_por_indice_y_sin_curso(entorno):
    leer = entorno.lanzar(entorno.presencia.elegir_curso, "pruebas", CURSOS, 22)
    p = entorno.pantalla()
    assert [o["texto"] for o in p["opciones"]] == ["Matemáticas 2ºB", "Dibujo"]
    assert p["permite_sin_curso"] and p["texto_sin_curso"] == mensajes.SIN_CURSO_PRUEBAS_OPCION
    assert entorno.responder(p, 1)
    assert leer() == 33
    leer = entorno.lanzar(entorno.presencia.elegir_curso, "pruebas", CURSOS, None)
    p = entorno.pantalla(p["numero"])
    assert entorno.responder(p, {"sin_curso": True})
    assert leer() == SIN_PRUEBAS


def test_elegir_curso_real_no_admite_sin_curso(entorno):
    leer = entorno.lanzar(entorno.presencia.elegir_curso, "real", CURSOS, None)
    p = entorno.pantalla()
    assert not p["permite_sin_curso"]
    assert not entorno.responder(p, {"sin_curso": True})
    assert entorno.responder(p, 0)
    assert leer() == 11


def test_elegir_curso_sin_lista_admite_un_id_numerico(entorno):
    leer = entorno.lanzar(entorno.presencia.elegir_curso, "real", [], 5)
    p = entorno.pantalla()
    assert p["permite_id"]
    assert not entorno.responder(p, {"id": 5})  # el excluido
    assert not entorno.responder(p, {"id": "12"})
    assert not entorno.responder(p, {"id": -1})
    assert entorno.responder(p, {"id": 12})
    assert leer() == 12


def test_elegir_cursos_reales(entorno):
    leer = entorno.lanzar(entorno.presencia.elegir_cursos_reales, CURSOS, 22)
    p = entorno.pantalla()
    assert p["maximo"] == config.MAX_REALES
    assert entorno.responder(p, [1, 0])
    assert leer() == [33, 11]


def test_elegir_cursos_reales_sin_lista_con_ids(entorno):
    leer = entorno.lanzar(entorno.presencia.elegir_cursos_reales, [], 5)
    p = entorno.pantalla()
    assert not entorno.responder(p, {"ids": [5]})
    assert not entorno.responder(p, [0])
    assert entorno.responder(p, {"ids": [7, 8]})
    assert leer() == [7, 8]


def test_informar_anota_y_sesion_abierta_deja_reposo(entorno):
    entorno.presencia.informar(publicacion.Aviso.sesion_abierta(datetime(2030, 1, 1, tzinfo=UTC)))
    est = entorno.puente.estado()
    assert est["pantalla"]["tipo"] == "reposo"
    assert est["pantalla"]["titulo"]
    assert est["registro"][0]["texto"] == est["pantalla"]["titulo"]
    entorno.presencia.informar(publicacion.Aviso.fallo("algo"))
    assert len(entorno.puente.estado()["registro"]) == 2


# --- validación y reglas del puente --------------------------------------------------------


@pytest.mark.parametrize("mala", [None, 1, 0, "true", "s", [True], {"a": 1}, 1.0])
def test_confirmar_solo_acepta_un_bool(entorno, mala):
    leer = entorno.lanzar(entorno.presencia.confirmar_autoprueba)
    p = entorno.pantalla()
    assert not entorno.responder(p, mala)
    assert entorno.responder(p, True)
    assert leer() is True


@pytest.mark.parametrize(
    "mala",
    [None, True, -1, 3, 99, "0", 0.0, {}, {"indice": 0}, {"sin_curso": True}, {"id": 4}, [0]],
)
def test_elegir_curso_rechaza_lo_no_valido(entorno, mala):
    leer = entorno.lanzar(entorno.presencia.elegir_curso, "real", CURSOS, None)
    p = entorno.pantalla()
    assert not entorno.responder(p, mala)
    entorno.responder(p, 2)
    assert leer() == 33


@pytest.mark.parametrize(
    "mala",
    [
        None,
        [],
        [0, 0],
        [True],
        [3],
        [-1],
        ["0"],
        0,
        {"ids": [1]},
        list(range(3)) * 3,
    ],
)
def test_elegir_reales_rechaza_lo_no_valido(entorno, mala):
    leer = entorno.lanzar(entorno.presencia.elegir_cursos_reales, CURSOS, None)
    p = entorno.pantalla()
    assert not entorno.responder(p, mala)
    entorno.responder(p, [2])
    assert leer() == [33]


def test_elegir_reales_respeta_el_maximo(entorno):
    cursos = [{"id": i + 1, "nombre": f"C{i}"} for i in range(config.MAX_REALES + 1)]
    leer = entorno.lanzar(entorno.presencia.elegir_cursos_reales, cursos, None)
    p = entorno.pantalla()
    assert not entorno.responder(p, list(range(config.MAX_REALES + 1)))
    assert entorno.responder(p, list(range(config.MAX_REALES)))
    assert leer() == list(range(1, config.MAX_REALES + 1))


def test_numero_viejo_o_ajeno_se_rechaza(entorno):
    leer = entorno.lanzar(entorno.presencia.confirmar_autoprueba)
    primera = entorno.pantalla()
    entorno.responder(primera, True)
    leer()
    leer = entorno.lanzar(entorno.presencia.confirmar_sin_pruebas)
    segunda = entorno.pantalla(primera["numero"])
    assert segunda["numero"] > primera["numero"]
    entorno.reloj.avanzar(2)
    assert not entorno.puente.responder(primera["numero"], True)
    assert not entorno.puente.responder(segunda["numero"] + 5, True)
    assert not entorno.puente.responder(str(segunda["numero"]), True)
    assert not entorno.puente.responder(None, None)
    assert entorno.puente.responder(segunda["numero"], False)
    assert leer() is False


def test_respuesta_demasiado_pronto_no_cuenta(entorno):
    leer = entorno.lanzar(entorno.presencia.confirmar_autoprueba)
    p = entorno.pantalla()
    assert not entorno.responder(p, True, esperar=False)
    entorno.reloj.avanzar(pe.RETARDO_RESPUESTA - 0.1)
    assert not entorno.responder(p, True, esperar=False)
    entorno.reloj.avanzar(0.2)
    assert entorno.responder(p, True, esperar=False)
    assert leer() is True


def test_una_sola_respuesta_por_pantalla(entorno):
    leer = entorno.lanzar(entorno.presencia.confirmar_autoprueba)
    p = entorno.pantalla()
    assert entorno.responder(p, False)
    # El hilo puede no haber despertado aún: la segunda nunca cambia el resultado.
    entorno.puente.responder(p["numero"], True)
    assert leer() is False


def test_sin_pregunta_no_se_responde(entorno):
    assert not entorno.puente.responder(0, True)
    assert not entorno.puente.ver_vista_previa(0, 0)


@pytest.mark.parametrize(
    ("metodo", "args", "negativo"),
    [
        ("confirmar_autoprueba", (), False),
        ("confirmar_real", (_resumen(),), False),
        ("elegir_curso", ("real", CURSOS, None), None),
        ("elegir_cursos_reales", (CURSOS, None), None),
        ("configurar", (), None),
        ("ofrecer_ampliacion", (30, 600.0), False),
        ("seguir_sin_aislar", ([],), False),
    ],
)
def test_cerrar_mientras_se_espera_es_negativo(entorno, metodo, args, negativo):
    leer = entorno.lanzar(getattr(entorno.presencia, metodo), *args)
    entorno.pantalla()
    entorno.panel.cerrar()
    assert leer() is negativo
    # Tras el cierre, nada vuelve a bloquear.
    assert getattr(entorno.presencia, metodo)(*args) is negativo


def test_ampliacion_que_vence_el_plazo_es_no(entorno):
    leer = entorno.lanzar(entorno.presencia.ofrecer_ampliacion, 30, 60.0)
    p = entorno.pantalla()
    assert p["tipo"] == "ampliar" and p["plazo"] == 60.0
    assert mensajes.pregunta_ampliacion(30) == p["pregunta"]
    entorno.reloj.avanzar(61)
    assert leer() is False


def test_ampliacion_con_respuesta_a_tiempo(entorno):
    leer = entorno.lanzar(entorno.presencia.ofrecer_ampliacion, 30, 60.0)
    p = entorno.pantalla()
    assert entorno.responder(p, True)
    assert leer() is True


# --- configurar y acreditar ----------------------------------------------------------------


@pytest.mark.parametrize(
    "mala",
    [
        None,
        {},
        {"url": "https://a.es"},
        {"url": "https://a.es", "usuario": 5},
        {"url": "", "usuario": "ana"},
        {"url": "https://a.es", "usuario": "   "},
        {"url": "x" * 400, "usuario": "ana"},
        {"url": "https://a.es", "usuario": "ana", "ruta": "/etc"},
        ["https://a.es", "ana"],
    ],
)
def test_configurar_rechaza_lo_no_valido(entorno, mala):
    leer = entorno.lanzar(entorno.presencia.configurar)
    p = entorno.pantalla()
    assert not entorno.responder(p, mala)
    assert entorno.responder(p, {"url": " https://a.es/c ", "usuario": " ana "})
    assert leer() == ("https://a.es/c", "ana")


def test_configurar_vuelve_a_preguntar_si_la_url_no_vale(entorno):
    intentos: list[str] = []

    def validar(url: str) -> None:
        intentos.append(url)
        if url != "https://bien.es":
            raise config.ErrorConfig("URL_INVALIDA", "mala")

    leer = entorno.lanzar(entorno.presencia.configurar, validar)
    p1 = entorno.pantalla()
    assert p1["error"] == ""
    entorno.responder(p1, {"url": "http://mal", "usuario": "ana"})
    p2 = entorno.pantalla(p1["numero"], "configurar")
    assert p2["numero"] > p1["numero"]
    esperado = " ".join(l.texto for l in mensajes.lineas_de_error("URL_INVALIDA", "mala"))
    assert p2["error"] == esperado and "URL_INVALIDA" in p2["error"]
    assert (p2["url"], p2["usuario"]) == ("http://mal", "ana")
    entorno.responder(p2, {"url": "https://bien.es", "usuario": "ana"})
    assert leer() == ("https://bien.es", "ana")
    assert intentos == ["http://mal", "https://bien.es"]


def test_configurar_cerrado_tras_un_error_devuelve_none(entorno):
    def validar(url: str) -> None:
        raise config.ErrorConfig("URL_INVALIDA")

    leer = entorno.lanzar(entorno.presencia.configurar, validar)
    p1 = entorno.pantalla()
    entorno.responder(p1, {"url": "x", "usuario": "ana"})
    entorno.pantalla(p1["numero"], "configurar")
    entorno.panel.cerrar()
    assert leer() is None


def test_acreditar_publica_entrando_y_devuelve_lo_de_abrir_login():
    cookies = publicar.Cookies((("MoodleSession", "valor", "aula.ejemplo.org"),))
    vistas: list = []
    e: Entorno

    def abrir_login(url: str):
        vistas.append((url, e.puente.estado()["pantalla"]))
        return cookies

    e = Entorno(abrir_login=abrir_login)
    acreditacion = e.presencia.acreditar("https://aula.ejemplo.org/centro?x=1", "ana")
    assert acreditacion is cookies
    url, pantalla = vistas[0]
    assert url == "https://aula.ejemplo.org/centro?x=1"
    assert pantalla["tipo"] == "entrando"
    assert pantalla["servidor"] == "aula.ejemplo.org"
    assert "x=1" not in json.dumps(pantalla)
    assert "valor" not in json.dumps(e.puente.estado())
    assert e.puente.estado()["pantalla"]["tipo"] == "reposo"


def test_acreditar_sin_abrir_login_o_cancelado_es_none():
    assert Entorno().presencia.acreditar("https://aula.ejemplo.org", "ana") is None
    e = Entorno(abrir_login=lambda url: None)
    assert e.presencia.acreditar("https://aula.ejemplo.org", "ana") is None


def test_acreditar_con_el_panel_cerrado_no_abre_el_login():
    llamadas: list[str] = []
    e = Entorno(abrir_login=lambda url: llamadas.append(url))
    e.panel.cerrar()
    assert e.presencia.acreditar("https://aula.ejemplo.org", "ana") is None
    assert llamadas == []


# --- registro y esperar_cambio -------------------------------------------------------------


def test_el_registro_tiene_limite_y_marca_los_errores(entorno):
    for i in range(pe.MAX_REGISTRO + 25):
        entorno.panel.anotar(f"línea {i}", error=i % 2 == 0)
    registro = entorno.puente.estado()["registro"]
    assert len(registro) == pe.MAX_REGISTRO
    assert registro[-1] == {"texto": f"línea {pe.MAX_REGISTRO + 24}", "error": True}
    assert registro[0]["texto"] == "línea 25"


def test_el_registro_saneado_y_acotado(entorno):
    entorno.panel.anotar("a\x1b[31m" + "x" * 1000)
    texto = entorno.puente.estado()["registro"][0]["texto"]
    assert "\x1b" not in texto and len(texto) <= pe.MAX_TEXTO


def test_esperar_cambio_despierta_con_una_pantalla_nueva(entorno):
    inicial = entorno.puente.estado()["pantalla"]["numero"]
    assert entorno.panel.esperar_cambio(inicial, 0.05) == inicial  # nada cambia
    resultado: list[int] = []
    hilo = threading.Thread(
        target=lambda: resultado.append(entorno.panel.esperar_cambio(inicial, 5)), daemon=True
    )
    hilo.start()
    leer = entorno.lanzar(entorno.presencia.confirmar_autoprueba)
    hilo.join(5)
    assert resultado and resultado[0] > inicial
    p = entorno.pantalla(inicial)
    entorno.responder(p, True)
    leer()


def test_esperar_cambio_despierta_al_cerrar(entorno):
    actual = entorno.puente.estado()["pantalla"]["numero"]
    hilo = threading.Thread(target=lambda: entorno.panel.esperar_cambio(actual, 5), daemon=True)
    hilo.start()
    entorno.panel.cerrar()
    hilo.join(2)
    assert not hilo.is_alive()
    assert entorno.puente.estado()["cerrado"] is True


def test_los_numeros_de_pantalla_solo_crecen(entorno):
    numeros = [entorno.puente.estado()["pantalla"]["numero"]]
    for _ in range(3):
        leer = entorno.lanzar(entorno.presencia.confirmar_autoprueba)
        p = entorno.pantalla(numeros[-1])
        numeros.append(p["numero"])
        entorno.responder(p, True)
        leer()
        numeros.append(entorno.puente.estado()["pantalla"]["numero"])
    assert numeros == sorted(set(numeros))
