"""Tests de la ventana de sesión sin pywebview: estado, presencia y puente."""

from __future__ import annotations

import inspect
import sys
import threading
import time
from datetime import UTC, datetime
from importlib import resources

import pytest

from tiza import config, informe, sesion
from tiza import ventana as paquete_ventana
from tiza.ventana import pagina
from tiza.ventana.estado import PresenciaVentana, Puente, Ventana


def en_hilo(funcion):
    resultado: dict = {}
    hilo = threading.Thread(target=lambda: resultado.update(valor=funcion()), daemon=True)
    hilo.start()
    return hilo, resultado


def esperar_pantalla(ventana, tipo, segundos=5.0, despues_de=-1):
    """Espera una pantalla de ``tipo`` más nueva que la número ``despues_de``."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        pantalla = ventana.estado()["pantalla"]
        if pantalla["tipo"] == tipo and pantalla["numero"] > despues_de:
            return pantalla
        time.sleep(0.01)
    raise AssertionError(f"no apareció la pantalla {tipo}")


def preparar(tmp_path, abiertas=None):
    ventana = Ventana(tmp_path, abrir_url=(abiertas.append if abiertas is not None else print))
    return ventana, PresenciaVentana(ventana), Puente(ventana, al_cerrar=ventana.cerrar_todo)


def test_presencia_ventana_cumple_la_interfaz():
    metodos = [
        nombre
        for nombre, valor in vars(sesion.Presencia).items()
        if callable(valor) and not nombre.startswith("_")
    ]
    for nombre in metodos:
        esperado = list(inspect.signature(getattr(sesion.Presencia, nombre)).parameters)
        obtenido = list(inspect.signature(getattr(PresenciaVentana, nombre)).parameters)
        assert obtenido == esperado, nombre


def test_el_puente_solo_expone_acciones_del_docente(tmp_path):
    _ventana, _presencia, puente = preparar(tmp_path)
    publicos = sorted(nombre for nombre in dir(puente) if not nombre.startswith("_"))
    assert publicos == ["cerrar_ventana", "estado", "responder", "vista_previa"]
    for nombre in publicos:
        assert callable(getattr(puente, nombre))  # ningún objeto que pywebview exponga entero


def test_password_espera_la_respuesta_del_docente(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    hilo, resultado = en_hilo(lambda: presencia.pedir_password("aula\x1b.es", "profe"))
    pantalla = esperar_pantalla(ventana, "password")
    assert pantalla["servidor"] == "aula.es"
    assert puente.responder(pantalla["numero"], "secreta") is True
    hilo.join(5)
    assert resultado["valor"] == "secreta"
    assert ventana.estado()["pantalla"]["tipo"] == "conectando"


def test_respuesta_de_otra_pantalla_se_rechaza(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    hilo, resultado = en_hilo(presencia.confirmar_autoprueba)
    pantalla = esperar_pantalla(ventana, "autoprueba")
    assert puente.responder(pantalla["numero"] - 1, True) is False
    assert puente.responder(pantalla["numero"], "sí") is False  # solo true o false
    assert puente.responder(pantalla["numero"], True) is True
    hilo.join(5)
    assert resultado["valor"] is True
    assert puente.responder(pantalla["numero"], False) is False  # ya contestada


def test_cerrar_la_ventana_desbloquea_la_pregunta(tmp_path):
    ventana, presencia, _puente = preparar(tmp_path)
    hilo, resultado = en_hilo(lambda: presencia.pedir_password("aula", "profe"))
    esperar_pantalla(ventana, "password")
    ventana.cerrar_todo()
    hilo.join(5)
    assert resultado["valor"] is None
    assert ventana.cerrar.is_set()
    assert presencia.confirmar_autoprueba() is False  # cerrada: ni pregunta


def test_elegir_curso_por_indice_y_por_id(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    cursos = [{"id": 1234, "nombre": "Pruebas"}, {"id": 5678, "nombre": "Real <b>"}]
    hilo, resultado = en_hilo(lambda: presencia.elegir_curso("real", cursos, 1234))
    pantalla = esperar_pantalla(ventana, "elegir_curso")
    assert pantalla["opciones"] == ["Real <b>"]  # sin el excluido; la página lo pinta como texto
    assert puente.responder(pantalla["numero"], {"indice": 5}) is False
    assert puente.responder(pantalla["numero"], {"id": "1234"}) is False  # el excluido
    assert puente.responder(pantalla["numero"], {"id": "12a"}) is False
    assert puente.responder(pantalla["numero"], {"indice": 0}) is True
    hilo.join(5)
    assert resultado["valor"] == 5678
    hilo, resultado = en_hilo(lambda: presencia.elegir_curso("pruebas", [], None))
    pantalla = esperar_pantalla(ventana, "elegir_curso", despues_de=pantalla["numero"])
    assert puente.responder(pantalla["numero"], {"id": "4321"}) is True
    hilo.join(5)
    assert resultado["valor"] == 4321


def test_elegir_curso_de_pruebas_puede_quedarse_sin_curso(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    cursos = [{"id": 1234, "nombre": "Pruebas"}]
    hilo, resultado = en_hilo(lambda: presencia.elegir_curso("pruebas", cursos, None))
    pantalla = esperar_pantalla(ventana, "elegir_curso")
    assert pantalla["sin_pruebas"] is True
    assert puente.responder(pantalla["numero"], {"sin_curso": True}) is True
    hilo.join(5)
    assert resultado["valor"] == sesion.SIN_PRUEBAS


def test_elegir_curso_real_no_admite_quedarse_sin_curso(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    cursos = [{"id": 5678, "nombre": "Real"}]
    hilo, resultado = en_hilo(lambda: presencia.elegir_curso("real", cursos, None))
    pantalla = esperar_pantalla(ventana, "elegir_curso")
    assert pantalla["sin_pruebas"] is False
    assert puente.responder(pantalla["numero"], {"sin_curso": True}) is False
    assert puente.responder(pantalla["numero"], {"indice": 0}) is True
    hilo.join(5)
    assert resultado["valor"] == 5678


def test_elegir_cursos_reales_por_casillas_e_ids(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    cursos = [
        {"id": 1234, "nombre": "Pruebas"},
        {"id": 101, "nombre": "1º A <b>"},
        {"id": 102, "nombre": "1º B"},
    ]
    hilo, resultado = en_hilo(lambda: presencia.elegir_cursos_reales(cursos, 1234))
    pantalla = esperar_pantalla(ventana, "elegir_reales")
    assert pantalla["opciones"] == [
        "1º A <b>",
        "1º B",
    ]  # sin el de pruebas; la página lo pinta como texto
    n = pantalla["numero"]
    assert puente.responder(n, {"indices": []}) is False  # ninguno
    assert puente.responder(n, {"indices": [2]}) is False  # fuera de rango
    assert puente.responder(n, {"indices": [True]}) is False
    assert puente.responder(n, {"indices": [0, 0]}) is False  # repetido
    assert puente.responder(n, {"indices": [0], "ids": "101"}) is False  # repetido con el id
    assert puente.responder(n, {"indices": [0], "ids": "1234"}) is False  # el de pruebas
    assert puente.responder(n, {"indices": [0], "ids": "12a"}) is False
    assert puente.responder(n, {"indices": [0], "ids": "0"}) is False
    assert puente.responder(n, {"indices": [1, 0], "ids": " 300 , 400"}) is True
    hilo.join(5)
    assert resultado["valor"] == [102, 101, 300, 400]


def test_elegir_cursos_reales_no_pasa_del_maximo(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    hilo, resultado = en_hilo(lambda: presencia.elegir_cursos_reales([], None))
    pantalla = esperar_pantalla(ventana, "elegir_reales")
    n = pantalla["numero"]
    assert puente.responder(n, {"ids": "1,2,3,4,5,6,7"}) is False
    assert puente.responder(n, {"ids": "1,2,3,4,5,6"}) is True
    hilo.join(5)
    assert resultado["valor"] == [1, 2, 3, 4, 5, 6]


def test_elegir_cursos_reales_se_puede_cancelar(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    hilo, resultado = en_hilo(lambda: presencia.elegir_cursos_reales([], None))
    pantalla = esperar_pantalla(ventana, "elegir_reales")
    assert puente.responder(pantalla["numero"], None) is True
    hilo.join(5)
    assert resultado["valor"] is None


def test_la_confirmacion_de_real_lleva_la_posicion_del_curso(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    resumen = sesion.ResumenPublicacion(
        curso=102,
        nombre_curso="1º B",
        documentos=(),
        secciones_nuevas=(),
        visible=None,
        posicion=2,
        total=3,
    )
    hilo, _ = en_hilo(lambda: presencia.confirmar_real(resumen))
    pantalla = esperar_pantalla(ventana, "real")
    assert (pantalla["posicion"], pantalla["total"]) == (2, 3)
    puente.responder(pantalla["numero"], False)
    hilo.join(5)


def test_confirmar_cursos_avisa_si_no_hay_pruebas(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    cursos = [sesion.CursoSesion("real", 5678, "Matemáticas", False)]
    hilo, resultado = en_hilo(lambda: presencia.confirmar_cursos(cursos))
    pantalla = esperar_pantalla(ventana, "cursos")
    assert pantalla["sin_pruebas"] is True
    assert puente.responder(pantalla["numero"], True) is True
    hilo.join(5)
    assert resultado["valor"] is True


def test_confirmar_cursos_con_pruebas_no_avisa(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    cursos = [
        sesion.CursoSesion("pruebas", 1234, "Pruebas", False),
        sesion.CursoSesion("real", 5678, "Real", False),
    ]
    hilo, resultado = en_hilo(lambda: presencia.confirmar_cursos(cursos))
    pantalla = esperar_pantalla(ventana, "cursos")
    assert pantalla["sin_pruebas"] is False
    assert puente.responder(pantalla["numero"], True) is True
    hilo.join(5)
    assert resultado["valor"] is True


def test_confirmar_sin_pruebas_pantalla(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    hilo, resultado = en_hilo(presencia.confirmar_sin_pruebas)
    pantalla = esperar_pantalla(ventana, "sin_pruebas")
    assert "verificación previa" in pantalla["aviso"]
    assert puente.responder(pantalla["numero"], False) is True
    hilo.join(5)
    assert resultado["valor"] is False


def test_confirmar_real_sin_pruebas_no_ofrece_vista_previa(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    resumen = sesion.ResumenSinPruebas(
        curso=5678,
        nombre_curso="Mates",
        documentos=(
            sesion.DocumentoBreve("t.md", "tarea", "T", existe=True),
            sesion.DocumentoBreve("n.md", "pagina", "N", existe=False),
            sesion.DocumentoBreve("d.md", "pagina", "D", existe=None),
        ),
        secciones_nuevas=("Nueva",),
    )
    hilo, resultado = en_hilo(lambda: presencia.confirmar_real_sin_pruebas(resumen))
    pantalla = esperar_pantalla(ventana, "real_sin_pruebas")
    assert pantalla["documentos"][0]["fichero"] == "t.md"
    assert pantalla["documentos"][0]["existe"] is True
    assert pantalla["documentos"][1]["existe"] is False
    assert pantalla["documentos"][2]["existe"] is None
    assert "oculto" in pantalla["aviso"]
    assert puente.vista_previa(pantalla["numero"], 0) is False
    assert puente.responder(pantalla["numero"], True) is True
    hilo.join(5)
    assert resultado["valor"] is True


def test_real_ensena_el_resumen_saneado_y_abre_la_vista_previa(tmp_path):
    abiertas: list = []
    ventana, presencia, puente = preparar(tmp_path, abiertas)
    vista = tmp_path.resolve() / ".tiza" / "preview" / "t.html"
    vista.parent.mkdir(parents=True)
    vista.write_text("x", encoding="utf-8")
    fuera = tmp_path / "fuera.html"
    fuera.write_text("x", encoding="utf-8")
    doc = sesion.DocumentoResumen(
        fichero="t\N{RIGHT-TO-LEFT OVERRIDE}.md",
        tipo="pagina",
        nombre="Repaso\x1b[2K",
        seccion=3,
        fechas=None,
        vista_previa=vista,
        enlaces_externos=("https://ejemplo.org/x",),
        incrustados=("https://wordwall.net/embed/a\x1b",),
        recursos=("img/foto.png",),
    )
    otro = sesion.DocumentoResumen("o.md", "pagina", "Otro", 3, None, vista_previa=fuera)
    resumen = sesion.ResumenPublicacion(
        5678, "Mates\N{RIGHT-TO-LEFT OVERRIDE}", (doc, otro), ("Nueva",), True
    )
    hilo, resultado = en_hilo(lambda: presencia.confirmar_real(resumen))
    pantalla = esperar_pantalla(ventana, "real")
    texto = str(pantalla)
    assert "\x1b" not in texto and "\N{RIGHT-TO-LEFT OVERRIDE}" not in texto
    assert pantalla["documentos"][0]["recursos"] == ["img/foto.png"]
    assert pantalla["documentos"][0]["enlaces"] == ["https://ejemplo.org/x"]
    assert pantalla["documentos"][0]["incrustados"] == ["https://wordwall.net/embed/a"]
    assert "VISIBLE" in pantalla["visibilidad"]
    assert puente.vista_previa(pantalla["numero"], 0) is True
    assert abiertas == [vista.as_uri()]
    assert puente.vista_previa(pantalla["numero"], 1) is False  # fuera de .tiza/preview
    assert puente.vista_previa(pantalla["numero"], 7) is False
    assert puente.responder(pantalla["numero"], False) is True
    hilo.join(5)
    assert resultado["valor"] is False
    assert puente.vista_previa(pantalla["numero"], 0) is False  # la tarjeta ya no está


def test_con_directorio_privado_solo_se_abren_sus_vistas(tmp_path):
    abiertas: list = []
    privado = tmp_path / "privado"
    ventana = Ventana(tmp_path, abrir_url=abiertas.append, dir_vistas=privado)
    presencia = PresenciaVentana(ventana)
    puente = Puente(ventana, al_cerrar=ventana.cerrar_todo)
    dentro = privado.resolve() / "preview" / "t.html"
    de_la_carpeta = tmp_path.resolve() / ".tiza" / "preview" / "t.html"
    for vista in (dentro, de_la_carpeta):
        vista.parent.mkdir(parents=True)
        vista.write_text("x", encoding="utf-8")

    def documento(vista):
        return sesion.DocumentoResumen("t.md", "pagina", "T", 3, None, vista_previa=vista)

    resumen = sesion.ResumenPublicacion(
        5678, "Mates", (documento(dentro), documento(de_la_carpeta)), (), True
    )
    hilo, resultado = en_hilo(lambda: presencia.confirmar_real(resumen))
    pantalla = esperar_pantalla(ventana, "real")
    assert puente.vista_previa(pantalla["numero"], 0) is True
    assert abiertas == [dentro.as_uri()]
    assert puente.vista_previa(pantalla["numero"], 1) is False  # la de la carpeta ya no vale
    assert puente.responder(pantalla["numero"], False) is True
    hilo.join(5)
    assert resultado["valor"] is False


def test_el_flujo_pasa_a_la_sesion_el_directorio_privado_de_vistas(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
    config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    vistos: list = []
    monkeypatch.setattr(
        paquete_ventana.sesion, "abrir", lambda *a, **k: vistos.append(k["dir_vistas"]) or 0
    )
    privado = tmp_path / "privado"
    ventana = Ventana(tmp_path, dir_vistas=privado)
    presencia = PresenciaVentana(ventana)
    hilo, _resultado = en_hilo(
        lambda: paquete_ventana._flujo(ventana, presencia, minutos=60, debug=False)
    )
    esperar_pantalla(ventana, "cerrada")
    assert vistos == [privado.resolve()]
    ventana.cerrar_todo()
    hilo.join(5)


def test_ejecutar_borra_el_directorio_de_vistas_aunque_falle(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", object())  # sin pywebview real
    monkeypatch.setattr(paquete_ventana.webview2, "instalado", lambda: True)
    creados: list = []
    crear = paquete_ventana.sesion.crear_dir_vistas

    def espiar():
        creados.append(crear())
        return creados[-1]

    def romper(*_args, **_opciones):
        raise RuntimeError("boom")

    monkeypatch.setattr(paquete_ventana.sesion, "crear_dir_vistas", espiar)
    monkeypatch.setattr(paquete_ventana, "_abrir_ventana", romper)
    with pytest.raises(RuntimeError):
        paquete_ventana.ejecutar(tmp_path)
    [privado] = creados
    assert not privado.exists()


def test_ampliar_sin_respuesta_es_no(tmp_path):
    _ventana, presencia, _puente = preparar(tmp_path)
    assert presencia.ofrecer_ampliacion(30, 0.05) is False


def test_avisos_cambian_la_pantalla_y_el_registro(tmp_path):
    ventana, presencia, _puente = preparar(tmp_path)
    presencia.informar(
        sesion.Aviso("SESION_ABIERTA", {"caduca": datetime(2026, 10, 3, 10, 0, tzinfo=UTC)})
    )
    assert ventana.estado()["pantalla"]["tipo"] == "abierta"
    presencia.informar(
        sesion.Aviso(
            "RESULTADO", {"documento": informe.crear("publicar", "ok", [], [], [], "pruebas", 1)}
        )
    )
    assert any("ok" in linea for linea in ventana.estado()["registro"])
    presencia.informar(sesion.Aviso("FALLO", {"codigo": "LOGIN_FALLIDO", "detalle": ""}))
    assert "LOGIN_FALLIDO" in ventana.estado()["registro"][-1]
    assert ventana.motivo


def test_la_ventana_sabe_mostrar_todos_los_avisos(tmp_path):
    _ventana, presencia, _puente = preparar(tmp_path)
    doc = sesion.DocumentoResumen("t.md", "pagina", "T", 3, None)
    datos = {
        "CREANDO_SECCION": {"nombre": "Tema"},
        "CURSOS_GUARDADOS": {"ruta": tmp_path / "tiza.toml"},
        "ERROR_INTERNO": {"tipo": "RuntimeError"},
        "FALLO": {"codigo": "LOGIN_FALLIDO", "detalle": ""},
        "MAXIMO_ALCANZADO": {"horas": 8},
        "PUBLICANDO_EN_PRUEBAS": {"documentos": (doc,)},
        "QUEDAN_MINUTOS": {"minutos": 5},
        "RESULTADO": {"documento": informe.crear("publicar", "ok", [], [], [], "pruebas", 1)},
        "SESION_ABIERTA": {"caduca": datetime(2026, 10, 3, 10, 0, tzinfo=UTC)},
        "SESION_CERRADA": {"motivo": "desactualizada"},
    }
    for codigo in sorted(sesion.AVISOS):
        presencia.informar(sesion.Aviso(codigo, datos.get(codigo, {})))


def test_el_puente_no_responde_fuera_de_nuestra_pagina(tmp_path):
    ventana, presencia, puente = preparar(tmp_path)
    hilo, resultado = en_hilo(presencia.confirmar_autoprueba)
    pantalla = esperar_pantalla(ventana, "autoprueba")
    puente._enlazar(lambda: "https://ajeno.example.org/")
    assert puente.responder(pantalla["numero"], True) is False
    assert puente.estado()["pantalla"]["tipo"] == "cerrada"
    assert puente.estado()["registro"] == []
    ventana.cerrar_todo()
    hilo.join(5)
    assert resultado["valor"] is False


def _plantilla() -> str:
    return (resources.files("tiza.ventana") / "sesion.html").read_text(encoding="utf-8")


def test_la_pagina_no_usa_html_ni_eval():
    texto = _plantilla()
    for prohibido in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
        "<a ",
        "http://",
        "<link",
        "<iframe",
    ):
        assert prohibido not in texto, prohibido
    sin_ejemplo = texto.replace("https://aula.ejemplo.org/tu-centro", "")
    assert "https://" not in sin_ejemplo


def test_la_pagina_lleva_csp_con_nonce_nuevo():
    primera, segunda = pagina.html(), pagina.html()
    assert "__NONCE__" not in primera
    assert primera != segunda
    assert "default-src 'none'" in primera
    assert "script-src 'nonce-" in primera
    assert "'unsafe-inline'" not in primera


def test_la_pagina_pinta_todas_las_pantallas():
    texto = _plantilla()
    for tipo in (
        "cargando",
        "conectando",
        "configurar",
        "password",
        "elegir_curso",
        "elegir_reales",
        "cursos",
        "autoprueba",
        "sin_pruebas",
        "abierta",
        "real",
        "real_sin_pruebas",
        "ampliar",
        "cerrada",
    ):
        assert f"{tipo}: function" in texto, tipo


class WinregFalso:
    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, valores):
        self._valores = valores

    def OpenKey(self, raiz, ruta):
        if (raiz, ruta) not in self._valores:
            raise OSError("no existe")
        return _ClaveFalsa(self._valores[(raiz, ruta)])

    def QueryValueEx(self, clave, nombre):
        return clave.valor, 1


class _ClaveFalsa:
    def __init__(self, valor):
        self.valor = valor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_webview2_instalado_segun_el_registro(monkeypatch):
    from tiza.ventana import webview2

    cliente = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    monkeypatch.setitem(sys.modules, "winreg", WinregFalso({}))
    assert webview2.instalado() is False
    monkeypatch.setitem(
        sys.modules, "winreg", WinregFalso({("HKCU", rf"Software\{cliente}"): "0.0.0.0"})
    )
    assert webview2.instalado() is False
    monkeypatch.setitem(
        sys.modules,
        "winreg",
        WinregFalso({("HKLM", rf"SOFTWARE\WOW6432Node\{cliente}"): "141.0.3537.71"}),
    )
    assert webview2.instalado() is True


def test_flujo_configura_la_primera_vez_y_abre(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
    monkeypatch.setattr(config, "preparar_url", lambda entrada: "https://aula.ejemplo.org/centro")
    abiertas: list = []
    monkeypatch.setattr(
        paquete_ventana.sesion, "abrir", lambda *a, **k: abiertas.append(k["cerrar"]) or 0
    )
    ventana, presencia, puente = preparar(tmp_path)
    hilo, resultado = en_hilo(
        lambda: paquete_ventana._flujo(ventana, presencia, minutos=60, debug=False)
    )
    pantalla = esperar_pantalla(ventana, "configurar")
    assert puente.responder(pantalla["numero"], {"url": "aula", "usuario": "profe"}) is True
    pantalla = esperar_pantalla(ventana, "cerrada")
    assert config.cargar_global()["usuario"] == "profe"
    assert abiertas == [ventana.cerrar]
    assert puente.responder(pantalla["numero"], True) is True  # volver a conectar
    pantalla = esperar_pantalla(ventana, "cerrada", despues_de=pantalla["numero"])
    assert len(abiertas) == 2
    ventana.cerrar_todo()
    hilo.join(5)
    assert resultado["valor"] == 0


def test_flujo_sin_configurar_y_cancelado_no_abre(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")

    def no_abrir(*a, **k):
        raise AssertionError("sin configuración no se abre la sesión")

    monkeypatch.setattr(paquete_ventana.sesion, "abrir", no_abrir)
    ventana, presencia, puente = preparar(tmp_path)
    hilo, resultado = en_hilo(
        lambda: paquete_ventana._flujo(ventana, presencia, minutos=60, debug=False)
    )
    pantalla = esperar_pantalla(ventana, "configurar")
    assert puente.responder(pantalla["numero"], None) is True
    hilo.join(5)
    assert resultado["valor"] == 1


def test_main_valida_los_minutos():
    import pytest

    with pytest.raises(SystemExit):
        paquete_ventana.main(["--carpeta", ".", "--minutos", "0"])


def test_real_solo_fechas_pinta_las_fechas_y_no_el_contenido(tmp_path):
    abiertas: list = []
    ventana, presencia, puente = preparar(tmp_path, abiertas)
    cambio = sesion.CambioFecha("entrega", (2026, 10, 10, 23, 59), (2026, 10, 12, 23, 59), "cambia")
    doc = sesion.DocumentoResumen(
        "t.md",
        "tarea",
        "Problemas",
        3,
        None,
        enlaces_externos=("https://ejemplo.org/x",),
        recursos=("img/foto.png",),
        cambios=(cambio,),
    )
    resumen = sesion.ResumenPublicacion(5678, "Mates", (doc,), (), None, solo_fechas=True)
    hilo, resultado = en_hilo(lambda: presencia.confirmar_real(resumen))
    pantalla = esperar_pantalla(ventana, "real")
    assert pantalla["solo_fechas"] is True
    assert pantalla["excepciones"] is True
    assert pantalla["documentos"][0]["fechas"] == [
        "entrega antes 10/10/2026 23:59 → ahora 12/10/2026 23:59"
    ]
    assert pantalla["documentos"][0]["enlaces"] == []
    assert pantalla["documentos"][0]["recursos"] == []
    assert pantalla["visibilidad"] == ""
    assert puente.responder(pantalla["numero"], False) is True
    hilo.join(5)
    assert resultado["valor"] is False
