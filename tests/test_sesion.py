"""Tests de la sesión del docente sin terminal (tiza.sesion)."""

from __future__ import annotations

import inspect
import json
import os
import shutil
import stat
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dobles import (
    PAGINA,
    MoodleFalso,
    PresenciaFalsa,
    configurar_aula,
    dejar_peticion,
    enlace_simbolico,
    peticion,
)
from tiza import buzon, config, contenido, informe, publicacion, publicar, sesion

TAREA = (
    '---\ntipo: tarea\nnombre: Problemas\nseccion: "Fracciones"\n'
    "apertura: 2026-10-01\nentrega: 2026-10-10\n---\n\n"
    "Mira ![foto](img/foto.png) y [esto](https://ejemplo.org/x).\n"
)


def test_aviso_desconocido_falla():
    with pytest.raises(ValueError):
        publicacion.Aviso("NO_EXISTE")


def test_aviso_conocido_guarda_sus_datos():
    aviso = publicacion.Aviso("CREANDO_SECCION", {"nombre": "Fracciones"})
    assert aviso.datos["nombre"] == "Fracciones"


def test_resumen_de_un_documento(tmp_path):
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "foto.png").write_bytes(b"png")
    (tmp_path / "tarea.md").write_text(TAREA, encoding="utf-8")
    doc = contenido.cargar(tmp_path / "tarea.md")
    resumen = publicacion.DocumentoResumen.de(doc, tmp_path.resolve())
    assert resumen.fichero == "tarea.md"
    assert (resumen.tipo, resumen.nombre, resumen.seccion) == ("tarea", "Problemas", "Fracciones")
    assert [fecha.campo for fecha in resumen.fechas] == ["apertura", "entrega"]
    assert resumen.recursos == ("img/foto.png",)
    assert resumen.enlaces_externos == ("https://ejemplo.org/x",)
    assert resumen.vista_previa is None


def test_el_resumen_lleva_los_iframes_aparte_de_los_enlaces(tmp_path):
    (tmp_path / "pagina.md").write_text(
        "---\ntipo: pagina\nnombre: P\nseccion: 1\n---\n\n"
        '<iframe src="https://www.youtube.com/embed/abc"></iframe>\n\n[web](https://ejemplo.org/x)\n',
        encoding="utf-8",
    )
    doc = contenido.cargar(tmp_path / "pagina.md")
    resumen = publicacion.DocumentoResumen.de(doc, tmp_path.resolve())
    assert resumen.incrustados == ("https://www.youtube-nocookie.com/embed/abc",)
    assert resumen.enlaces_externos == ("https://ejemplo.org/x",)


def test_el_resumen_de_una_actividad_h5p_lleva_sus_datos(tmp_path):
    (tmp_path / "actividad.md").write_text(
        "---\ntipo: h5p\nnombre: Repaso\nseccion: 1\nactividad:\n"
        "  tipo: marcar_palabras\n"
        "  enunciado: Marca los verbos.\n"
        '  texto: "El niño [[come]] pan."\n'
        "---\n\nDescripción.\n",
        encoding="utf-8",
    )
    doc = contenido.cargar(tmp_path / "actividad.md")
    resumen = publicacion.DocumentoResumen.de(doc, tmp_path.resolve())
    assert (resumen.tipo, resumen.nombre) == ("h5p", "Repaso")
    assert resumen.h5p == "Marcar palabras"
    assert resumen.h5p_libreria is None and resumen.h5p_descartadas == ()


def test_el_doble_cumple_la_interfaz_de_presencia():
    metodos = [
        nombre
        for nombre, valor in vars(publicacion.Presencia).items()
        if callable(valor) and not nombre.startswith("_")
    ]
    assert len(metodos) == 21
    for nombre in metodos:
        esperado = list(inspect.signature(getattr(publicacion.Presencia, nombre)).parameters)
        obtenido = list(inspect.signature(getattr(PresenciaFalsa, nombre)).parameters)
        assert obtenido == esperado, nombre


def preparar_abrir(tmp_path, monkeypatch, moodle=None, cursos=None):
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    configurar_aula(carpeta, {"pruebas": 1234, "real": 5678} if cursos is None else cursos)
    moodle = moodle or MoodleFalso()
    monkeypatch.setattr(publicar, "autenticar", lambda url, usuario, password: moodle)
    atendidas: list = []
    monkeypatch.setattr(buzon, "atender", lambda *a, **k: atendidas.append(a) or False)
    monkeypatch.setattr(
        publicar, "autoprueba", lambda m, c: {"resultado": "ok", "pasos": [], "errores": []}
    )
    return carpeta, atendidas


def leer_informe(carpeta: Path) -> dict:
    return json.loads((carpeta / ".tiza" / "informe.json").read_text(encoding="utf-8"))


class TestVistasPrivadas:
    """Las vistas previas de la confirmación van a un directorio que el agente no escribe."""

    def test_el_directorio_esta_en_la_cache_y_fuera_de_la_carpeta(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        monkeypatch.setattr("platformdirs.user_cache_dir", lambda *_a, **_k: str(cache))
        privado = sesion.crear_dir_vistas()
        assert privado.is_dir() and privado.is_relative_to(cache)
        assert privado.name.startswith("sesion-")

    @pytest.mark.skipif(os.name == "nt", reason="los permisos 0700 son de POSIX")
    def test_el_directorio_es_solo_del_usuario(self):
        privado = sesion.crear_dir_vistas()
        assert stat.S_IMODE(privado.stat().st_mode) == 0o700

    def test_borra_las_viejas_y_respeta_las_recientes(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        monkeypatch.setattr("platformdirs.user_cache_dir", lambda *_a, **_k: str(cache))
        vieja = cache / "vistas" / "sesion-vieja"
        reciente = cache / "vistas" / "sesion-reciente"
        for ruta in (vieja, reciente):
            ruta.mkdir(parents=True)
            (ruta / "x.html").write_text("x", encoding="utf-8")
        hace_dos_dias = time.time() - 2 * 24 * 3600
        os.utime(vieja, (hace_dos_dias, hace_dos_dias))
        sesion.crear_dir_vistas()
        assert not vieja.exists()
        assert reciente.exists()

    def test_sin_cache_escribible_usa_el_temporal_del_sistema(self, tmp_path, monkeypatch):
        no_es_un_directorio = tmp_path / "fichero"
        no_es_un_directorio.write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            "platformdirs.user_cache_dir", lambda *_a, **_k: str(no_es_un_directorio)
        )
        privado = sesion.crear_dir_vistas()
        try:
            assert privado.is_dir() and not privado.is_relative_to(no_es_un_directorio)
        finally:
            shutil.rmtree(privado, ignore_errors=True)


class TestAbrir:
    def test_abrir_crea_su_directorio_de_vistas_y_lo_borra_al_cerrar(self, tmp_path, monkeypatch):
        carpeta, _atendidas = preparar_abrir(tmp_path, monkeypatch)
        usados: list = []
        servir = sesion._servir

        def espiar(*args, **opciones):
            assert opciones["dir_vistas"].is_dir()
            usados.append(opciones["dir_vistas"])
            return servir(*args, **opciones)

        monkeypatch.setattr(sesion, "_servir", espiar)
        assert sesion.abrir(carpeta, PresenciaFalsa(), minutos=60, preparar=False) == 0
        [privado] = usados
        assert not privado.exists()

    def test_abrir_no_borra_el_directorio_que_le_dan(self, tmp_path, monkeypatch):
        carpeta, _atendidas = preparar_abrir(tmp_path, monkeypatch)
        privado = tmp_path / "privado"
        privado.mkdir()
        resultado = sesion.abrir(
            carpeta, PresenciaFalsa(), minutos=60, preparar=False, dir_vistas=privado
        )
        assert resultado == 0
        assert privado.is_dir()

    def test_la_sesion_ensena_vistas_del_directorio_privado(self, tmp_path, monkeypatch):
        carpeta, _atendidas = preparar_abrir(tmp_path, monkeypatch)
        (carpeta / "img").mkdir()
        (carpeta / "img" / "foto.png").write_bytes(b"png")
        (carpeta / "pagina.md").write_text(PAGINA, encoding="utf-8")
        presencia = PresenciaFalsa(real=False)
        privados: list = []

        def atender(_dir_tiza, procesar, *_args, **_opciones):
            dejar_peticion(carpeta, peticion("real"))
            procesar(peticion("pruebas"))
            procesar(peticion("real"))
            privados.extend(doc.vista_previa for doc in presencia.resumenes[0].documentos)
            return False

        monkeypatch.setattr(buzon, "atender", atender)
        assert sesion.abrir(carpeta, presencia, minutos=60, preparar=False) == 0
        [vista] = privados
        assert not vista.is_relative_to(carpeta)
        assert vista.name == "pagina.html"

    def test_abre_en_otra_carpeta_sin_tocar_el_directorio_actual(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch)
        otro = tmp_path / "otro"
        otro.mkdir()
        monkeypatch.chdir(otro)
        presencia = PresenciaFalsa()
        assert sesion.abrir(carpeta, presencia, minutos=60) == 0
        assert len(atendidas) == 1
        assert atendidas[0][0] == carpeta.resolve() / ".tiza"
        assert (carpeta / ".tiza" / "estructura.json").is_file()
        assert list(otro.iterdir()) == []
        assert presencia.passwords_pedidas == [("aula.ejemplo.org", "profe")]

    def test_se_niega_si_tiza_es_un_enlace_y_no_pide_la_contrasena(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch)
        fuera = tmp_path / "fuera"
        fuera.mkdir()
        enlace_simbolico(carpeta / ".tiza", fuera)
        presencia = PresenciaFalsa()
        assert sesion.abrir(carpeta, presencia, minutos=60) == 1
        assert presencia.passwords_pedidas == []
        fallo = next(aviso for aviso in presencia.avisos if aviso.codigo == "FALLO")
        assert fallo.datos["codigo"] == "DIRECTORIO_NO_SEGURO"
        assert list(fuera.iterdir()) == []
        assert atendidas == []

    def test_sin_contrasena_no_conecta(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch)

        def no_conectar(*a, **k):
            raise AssertionError("sin contraseña no se conecta")

        monkeypatch.setattr(publicar, "autenticar", no_conectar)
        presencia = PresenciaFalsa(password=None)
        assert sesion.abrir(carpeta, presencia, minutos=60) == 1
        assert atendidas == []
        assert "CANCELADA" in presencia.codigos()
        assert leer_informe(carpeta)["errores"] == ["ABORTADO"]

    def test_login_fallido(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch)

        def falla(*a, **k):
            raise publicar.ErrorPublicacion("LOGIN_FALLIDO")

        monkeypatch.setattr(publicar, "autenticar", falla)
        presencia = PresenciaFalsa()
        assert sesion.abrir(carpeta, presencia, minutos=60) == 1
        fallo = next(aviso for aviso in presencia.avisos if aviso.codigo == "FALLO")
        assert fallo.datos["codigo"] == "LOGIN_FALLIDO"
        assert atendidas == []

    def test_ya_abierta_no_pide_contrasena(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch)
        buzon.crear_sesion(carpeta / ".tiza", datetime.now(UTC) + timedelta(minutes=5))
        presencia = PresenciaFalsa()
        assert sesion.abrir(carpeta, presencia, minutos=60) == 1
        assert presencia.passwords_pedidas == []
        fallo = next(aviso for aviso in presencia.avisos if aviso.codigo == "FALLO")
        assert fallo.datos["codigo"] == "SESION_YA_ABIERTA"
        assert atendidas == []

    def test_cursos_que_faltan_se_eligen_y_se_guardan_en_la_carpeta(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch, cursos={})
        presencia = PresenciaFalsa(cursos=(1234, 5678))
        assert sesion.abrir(carpeta, presencia, minutos=60, preparar=False) == 0
        assert config.cargar_carpeta(carpeta)["cursos"] == {"pruebas": 1234, "real": 5678}
        assert "CURSOS_GUARDADOS" in presencia.codigos()
        assert len(atendidas) == 1

    def test_los_nombres_de_curso_van_a_la_presencia_y_no_a_tiza(self, tmp_path, monkeypatch):
        carpeta, _atendidas = preparar_abrir(tmp_path, monkeypatch)
        presencia = PresenciaFalsa()
        sesion.abrir(carpeta, presencia, minutos=60)
        [cursos] = presencia.cursos_vistos
        assert [(c.entorno, c.id, c.nombre, c.ajeno) for c in cursos] == [
            ("pruebas", 1234, "Pruebas de Mates", False),
            ("real", 5678, "Matemáticas 2ºB", False),
        ]
        for ruta in (carpeta / ".tiza").rglob("*"):
            if ruta.is_file():
                texto = ruta.read_text(encoding="utf-8")
                assert "Matemáticas" not in texto and "Pruebas de Mates" not in texto

    def test_sin_preparar_no_lee_la_estructura(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch)
        assert sesion.abrir(carpeta, PresenciaFalsa(), minutos=60, preparar=False) == 0
        assert not (carpeta / ".tiza" / "estructura.json").exists()
        assert len(atendidas) == 1

    def test_autoprueba_fallida_no_abre(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch)
        monkeypatch.setattr(
            publicar,
            "autoprueba",
            lambda m, c: {"resultado": "error", "pasos": [], "errores": ["ERROR_CREACION"]},
        )
        presencia = PresenciaFalsa(autoprueba=True)
        assert sesion.abrir(carpeta, presencia, minutos=60) == 1
        assert "AUTOPRUEBA_FALLIDA" in presencia.codigos()
        assert atendidas == []

    def test_ampliar_desde_la_presencia(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch)
        presencia = PresenciaFalsa(ampliar=(True, False))
        assert sesion.abrir(carpeta, presencia, minutos=60, preparar=False) == 0
        assert len(atendidas) == 2
        assert presencia.codigos().count("SESION_ABIERTA") == 2
        assert presencia.avisos[-1] == publicacion.Aviso("SESION_CERRADA", {"motivo": "caducada"})

    def test_sin_curso_de_pruebas_solo_lee_y_confirma_el_real(self, tmp_path, monkeypatch):
        moodle = MoodleFalso()
        carpeta, _atendidas = preparar_abrir(
            tmp_path, monkeypatch, moodle=moodle, cursos={"real": 5678}
        )
        (carpeta / "tiza.toml").write_text(
            "[cursos]\nreal = 5678\nsin_pruebas = true\n", encoding="utf-8"
        )
        autopruebas: list = []
        monkeypatch.setattr(
            publicar,
            "autoprueba",
            lambda m, c: autopruebas.append(c) or {"resultado": "ok", "pasos": [], "errores": []},
        )
        presencia = PresenciaFalsa(autoprueba=True)
        assert sesion.abrir(carpeta, presencia, minutos=60) == 0
        assert autopruebas == []  # sin curso de pruebas no hay autoprueba
        assert "CURSOS_GUARDADOS" not in presencia.codigos()
        assert presencia.sin_pruebas_pedidas == 1  # el docente confirma que sigue sin pruebas
        [cursos] = presencia.cursos_vistos
        assert [(c.entorno, c.id) for c in cursos] == [("real", 5678)]
        datos = json.loads((carpeta / ".tiza" / "estructura.json").read_text(encoding="utf-8"))
        assert set(datos["cursos"]) == {"real"}
        assert ("estructura", 5678) in moodle.llamadas
        assert ("estructura", 1234) not in moodle.llamadas

    def test_el_docente_rechaza_la_confirmacion_sin_pruebas(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch, cursos={"real": 5678})
        (carpeta / "tiza.toml").write_text(
            "[cursos]\nreal = 5678\nsin_pruebas = true\n", encoding="utf-8"
        )
        presencia = PresenciaFalsa(sin_pruebas=False)
        assert sesion.abrir(carpeta, presencia, minutos=60, preparar=False) == 1
        assert atendidas == []
        assert presencia.sin_pruebas_pedidas == 1
        assert leer_informe(carpeta)["errores"] == ["ABORTADO"]

    def test_con_pruebas_no_pregunta_por_sin_pruebas(self, tmp_path, monkeypatch):
        carpeta, _atendidas = preparar_abrir(tmp_path, monkeypatch)
        presencia = PresenciaFalsa()
        assert sesion.abrir(carpeta, presencia, minutos=60, preparar=False) == 0
        assert presencia.sin_pruebas_pedidas == 0

    def test_elegir_sin_curso_de_pruebas_se_guarda_y_no_vuelve_a_preguntar(
        self, tmp_path, monkeypatch
    ):
        carpeta, _atendidas = preparar_abrir(tmp_path, monkeypatch, cursos={"real": 5678})
        presencia = PresenciaFalsa(cursos=(sesion.SIN_PRUEBAS,))
        assert sesion.abrir(carpeta, presencia, minutos=60, preparar=False) == 0
        assert config.cargar_carpeta(carpeta)["cursos"] == {"real": 5678, "sin_pruebas": True}
        assert "CURSOS_GUARDADOS" in presencia.codigos()
        # Se confirma siempre al abrir, también cuando lo acaba de elegir.
        assert presencia.sin_pruebas_pedidas == 1
        segunda = PresenciaFalsa()  # sin respuestas preparadas: si preguntara, cancelaría
        assert sesion.abrir(carpeta, segunda, minutos=60, preparar=False) == 0
        assert segunda.sin_pruebas_pedidas == 1
        [cursos] = segunda.cursos_vistos
        assert [(c.entorno, c.id) for c in cursos] == [("real", 5678)]


class TestCierreDeLaSesionDelAula:
    """La cookie deja de valer en cuanto se acaba la sesión, sea cual sea la salida."""

    def test_al_cerrarse_normalmente(self, tmp_path, monkeypatch):
        moodle = MoodleFalso()
        carpeta, _ = preparar_abrir(tmp_path, monkeypatch, moodle=moodle)
        assert sesion.abrir(carpeta, PresenciaFalsa(), minutos=60, preparar=False) == 0
        assert moodle.cerradas == 1

    def test_si_falla_la_preparacion(self, tmp_path, monkeypatch):
        moodle = MoodleFalso()
        carpeta, _ = preparar_abrir(tmp_path, monkeypatch, moodle=moodle)
        monkeypatch.setattr(
            publicar,
            "autoprueba",
            lambda m, c: {"resultado": "error", "pasos": [], "errores": ["ERROR_CREACION"]},
        )
        assert sesion.abrir(carpeta, PresenciaFalsa(autoprueba=True), minutos=60) == 1
        assert moodle.cerradas == 1

    def test_si_el_docente_abandona_tras_entrar(self, tmp_path, monkeypatch):
        moodle = MoodleFalso()
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch, moodle=moodle)
        presencia = PresenciaFalsa(confirmar_cursos=False)
        assert sesion.abrir(carpeta, presencia, minutos=60) == 1
        assert moodle.cerradas == 1 and atendidas == []

    def test_con_ctrl_c(self, tmp_path, monkeypatch):
        moodle = MoodleFalso()
        carpeta, _ = preparar_abrir(tmp_path, monkeypatch, moodle=moodle)

        def interrumpir(*a, **k):
            raise KeyboardInterrupt

        monkeypatch.setattr(buzon, "atender", interrumpir)
        assert sesion.abrir(carpeta, PresenciaFalsa(), minutos=60, preparar=False) == 0
        assert moodle.cerradas == 1

    def test_si_algo_inesperado_rompe_la_sesion(self, tmp_path, monkeypatch):
        moodle = MoodleFalso()
        carpeta, _ = preparar_abrir(tmp_path, monkeypatch, moodle=moodle)

        def rompe(*a, **k):
            raise RuntimeError("fallo interno")

        monkeypatch.setattr(sesion.publicacion, "nombres_de_cursos", rompe)
        with pytest.raises(RuntimeError):
            sesion.abrir(carpeta, PresenciaFalsa(), minutos=60)
        assert moodle.cerradas == 1

    def test_sin_entrar_no_hay_nada_que_cerrar(self, tmp_path, monkeypatch):
        moodle = MoodleFalso()
        carpeta, _ = preparar_abrir(tmp_path, monkeypatch, moodle=moodle)
        assert sesion.abrir(carpeta, PresenciaFalsa(password=None), minutos=60) == 1
        assert moodle.cerradas == 0


def test_la_sesion_se_cierra_si_su_codigo_cambia(tmp_path, monkeypatch):
    carpeta, _atendidas = preparar_abrir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        buzon,
        "atender",
        lambda *a, **k: k["terminar"]({"errores": ["SESION_DESACTUALIZADA"]}),
    )
    presencia = PresenciaFalsa()
    assert sesion.abrir(carpeta, presencia, minutos=60, preparar=False) == 0
    assert presencia.avisos[-1] == publicacion.Aviso("SESION_CERRADA", {"motivo": "desactualizada"})


def test_cerrar_corta_el_buzon_sin_ofrecer_ampliar(tmp_path, monkeypatch):
    carpeta, _atendidas = preparar_abrir(tmp_path, monkeypatch)
    cerrar = threading.Event()
    vistos: list = []

    def atender(*args, **opciones):
        vistos.append(opciones["parar"])
        cerrar.set()  # el docente cierra la ventana mientras se atiende
        return False

    monkeypatch.setattr(buzon, "atender", atender)
    presencia = PresenciaFalsa(ampliar=(True,))
    assert sesion.abrir(carpeta, presencia, minutos=60, preparar=False, cerrar=cerrar) == 0
    assert vistos[0]() is True
    assert presencia.avisos[-1] == publicacion.Aviso("SESION_CERRADA", {"motivo": "docente"})
    assert not (buzon.carpeta_buzon(carpeta / ".tiza") / buzon.SESION).exists()


CFG_DOS = config.Config(
    url="https://aula.ejemplo.org/centro",
    usuario="profe",
    cursos={"pruebas": 1234},
    reales=(101, 102),
)


class TestElegirCursosReales:
    def preparar(self, tmp_path, monkeypatch, presencia, cursos=None):
        carpeta = tmp_path / "asignatura"
        monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
        configurar_aula(carpeta, cursos)
        cfg = config.resolver(carpeta)
        return carpeta, cfg

    def test_pregunta_los_reales_de_golpe_y_los_guarda_en_lista(self, tmp_path, monkeypatch):
        carpeta, cfg = self.preparar(tmp_path, monkeypatch, None, {"pruebas": 9})
        presencia = PresenciaFalsa(reales=(101, 102))
        completa = sesion._completar_cursos(cfg, {101: "A", 102: "B"}, carpeta, presencia)
        assert completa is not None and completa.reales == (101, 102)
        assert config.cargar_carpeta(carpeta)["cursos"] == {"pruebas": 9, "real": [101, 102]}
        [(lista, excluir)] = presencia.reales_vistos
        assert excluir == 9 and [c["id"] for c in lista] == [101, 102]

    def test_cancelar_no_guarda_nada(self, tmp_path, monkeypatch):
        carpeta, cfg = self.preparar(tmp_path, monkeypatch, None, {"pruebas": 9})
        presencia = PresenciaFalsa(reales=())
        assert sesion._completar_cursos(cfg, {}, carpeta, presencia) is None

    def test_elegir_cursos_vuelve_a_preguntar_aunque_este_todo_configurado(
        self, tmp_path, monkeypatch
    ):
        carpeta, cfg = self.preparar(tmp_path, monkeypatch, None, {"pruebas": 9, "real": 3})
        presencia = PresenciaFalsa(cursos=(8,), reales=(4, 5))
        completa = sesion._completar_cursos(cfg, {}, carpeta, presencia, elegir=True)
        assert completa is not None
        assert completa.cursos == {"pruebas": 8} and completa.reales == (4, 5)

    def test_sin_elegir_no_pregunta_si_esta_todo(self, tmp_path, monkeypatch):
        carpeta, cfg = self.preparar(tmp_path, monkeypatch, None, {"pruebas": 9, "real": [3, 4]})
        presencia = PresenciaFalsa()
        assert sesion._completar_cursos(cfg, {}, carpeta, presencia) is cfg
        assert presencia.reales_vistos == []

    def test_confirmar_cursos_enseña_todos_los_reales(self, tmp_path):
        presencia = PresenciaFalsa()
        sesion._confirmar_cursos(CFG_DOS, {101: "1º A"}, presencia)
        [cursos] = presencia.cursos_vistos
        assert [(c.entorno, c.id, c.nombre, c.ajeno) for c in cursos] == [
            ("pruebas", 1234, None, True),
            ("real", 101, "1º A", False),
            ("real", 102, None, True),
        ]


def test_autoprueba_sin_permiso_de_copia(tmp_path, monkeypatch):
    """Sin el formulario de copia la autoprueba sigue (es un aviso) y su línea lo dice."""
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    moodle = MoodleFalso(copia_permitida=False)
    presencia = PresenciaFalsa()
    assert sesion.autoprueba_con(moodle, 1234, carpeta, presencia) is True
    informe_ = json.loads((carpeta / ".tiza" / "informe.json").read_text(encoding="utf-8"))
    assert (informe_["comando"], informe_["resultado"]) == ("autoprueba", "ok")
    [paso] = [p for p in informe_["pasos"] if p["codigo"] == "COPIA_A_MANO"]
    assert "COPIA_NO_PERMITIDA" in paso["detalle"] and "a mano" in paso["detalle"]
    # La línea que ve el docente (y el agente en el resumen) lo cuenta.
    [resultado] = [a for a in presencia.avisos if a.codigo == "RESULTADO"]
    assert any(
        linea.startswith("Paso COPIA_A_MANO: ok") and "a mano" in linea
        for linea in informe.resumen(resultado.datos["documento"])
    )
    # Con permiso, ni rastro del aviso.
    otra = tmp_path / "otra"
    otra.mkdir()
    assert sesion.autoprueba_con(MoodleFalso(), 1234, otra, PresenciaFalsa()) is True
    texto = (otra / ".tiza" / "informe.json").read_text(encoding="utf-8")
    assert "COPIA_A_MANO" not in texto


# --------------------------------------------------------------------------- #
# Cerrar la sesión anterior (su terminal se cerró y siguió viva)
# --------------------------------------------------------------------------- #


def sesion_anterior(carpeta: Path, *, atendiendo: bool = False) -> Path:
    """Una sesión viva en la carpeta con su directorio privado; devuelve este directorio.

    Es de este mismo proceso: el pid de ``sesion.json`` y el de la marca coinciden.
    """
    buzon.crear_sesion(carpeta / ".tiza", datetime.now(UTC) + timedelta(minutes=30))
    if atendiendo:
        ruta = buzon.carpeta_buzon(carpeta / ".tiza") / buzon.SESION
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        ruta.write_text(json.dumps({**datos, "atendiendo": "a" * 32}), encoding="utf-8")
    return sesion.crear_dir_vistas(carpeta)


def soltar_al_pedirlo(carpeta: Path, privado: Path) -> threading.Thread:
    """La sesión anterior se va en cuanto otra le pide cerrarse."""

    def esperar() -> None:
        limite = time.monotonic() + 5
        while not (privado / sesion.PEDIR_CIERRE).exists() and time.monotonic() < limite:
            time.sleep(0.01)
        buzon.soltar(carpeta / ".tiza")

    hilo = threading.Thread(target=esperar, daemon=True)
    hilo.start()
    return hilo


class TestMarcaPrivada:
    def test_la_marca_lleva_carpeta_y_pid(self, tmp_path):
        privado = sesion.crear_dir_vistas(tmp_path)
        marca = json.loads((privado / "sesion.json").read_text(encoding="utf-8"))
        assert marca == {"carpeta": str(tmp_path.resolve()), "pid": os.getpid()}

    def test_encuentra_la_de_su_carpeta_y_pid_salvo_la_propia(self, tmp_path):
        otra_carpeta = tmp_path / "otra"
        otra_carpeta.mkdir()
        anterior = sesion_anterior(tmp_path)  # viva: crear otro no la borra
        propio = sesion.crear_dir_vistas(tmp_path)
        sesion.crear_dir_vistas(otra_carpeta)
        assert sesion._privados_de(tmp_path, os.getpid(), propio) == [anterior]
        assert sesion._privados_de(tmp_path, os.getpid() + 1, propio) == []

    def test_una_marca_con_pid_que_no_es_entero_no_vale(self, tmp_path):
        privado = sesion.crear_dir_vistas(tmp_path)
        (privado / "sesion.json").write_text(
            json.dumps({"carpeta": str(tmp_path.resolve()), "pid": True}), encoding="utf-8"
        )
        assert sesion._privados_de(tmp_path, 1, None) == []


class TestCerrarSesionAnterior:
    """El «tiza empezar» nuevo: ofrece cerrar la anterior antes de pedir la contraseña."""

    def test_sin_directorio_privado_no_ofrece_cerrarla(self, tmp_path, monkeypatch):
        # Una sesión de una versión anterior, o un sesion.json que escribió el agente.
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch)
        buzon.crear_sesion(carpeta / ".tiza", datetime.now(UTC) + timedelta(minutes=5))
        presencia = PresenciaFalsa(cerrar_anterior=True)
        assert sesion.abrir(carpeta, presencia, minutos=60) == 1
        assert presencia.anteriores_vistas == []
        assert presencia.passwords_pedidas == []
        fallo = next(aviso for aviso in presencia.avisos if aviso.codigo == "FALLO")
        assert fallo.datos["codigo"] == "SESION_YA_ABIERTA"
        assert "no se puede cerrar desde aquí" in fallo.datos["detalle"]
        assert atendidas == []

    def test_un_pid_que_no_es_el_de_la_marca_no_vale(self, tmp_path, monkeypatch):
        carpeta, _atendidas = preparar_abrir(tmp_path, monkeypatch)
        privado = sesion_anterior(carpeta)
        buzon.crear_sesion(
            carpeta / ".tiza", datetime.now(UTC) + timedelta(minutes=5), pid=os.getpid() + 1
        )
        presencia = PresenciaFalsa(cerrar_anterior=True)
        assert sesion.abrir(carpeta, presencia, minutos=60) == 1
        assert presencia.anteriores_vistas == []
        assert not (privado / sesion.PEDIR_CIERRE).exists()

    def test_si_el_docente_dice_que_no_sigue_como_antes(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch)
        privado = sesion_anterior(carpeta)
        presencia = PresenciaFalsa(cerrar_anterior=False)
        assert sesion.abrir(carpeta, presencia, minutos=60) == 1
        assert presencia.anteriores_vistas == [False]
        assert presencia.passwords_pedidas == []
        assert not (privado / sesion.PEDIR_CIERRE).exists()
        assert "SESION_YA_ABIERTA" in leer_informe(carpeta)["errores"]
        assert atendidas == []

    def test_le_dice_al_docente_si_atiende_una_peticion(self, tmp_path, monkeypatch):
        carpeta, _atendidas = preparar_abrir(tmp_path, monkeypatch)
        sesion_anterior(carpeta, atendiendo=True)
        presencia = PresenciaFalsa(cerrar_anterior=False)
        sesion.abrir(carpeta, presencia, minutos=60)
        assert presencia.anteriores_vistas == [True]

    def test_la_cierra_y_abre_la_nueva(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch)
        privado = sesion_anterior(carpeta)
        hilo = soltar_al_pedirlo(carpeta, privado)
        presencia = PresenciaFalsa(cerrar_anterior=True)
        assert sesion.abrir(carpeta, presencia, minutos=60, preparar=False) == 0
        hilo.join(5)
        assert (privado / sesion.PEDIR_CIERRE).exists()
        codigos = presencia.codigos()
        assert codigos.index("CERRANDO_SESION_ANTERIOR") < codigos.index("SESION_ANTERIOR_CERRADA")
        assert presencia.passwords_pedidas  # después, el login de siempre
        assert len(atendidas) == 1

    def test_si_no_se_va_a_tiempo_deja_la_peticion(self, tmp_path, monkeypatch):
        carpeta, atendidas = preparar_abrir(tmp_path, monkeypatch)
        privado = sesion_anterior(carpeta)
        monkeypatch.setattr(sesion, "ESPERA_CIERRE_SEGUNDOS", 0.2)
        presencia = PresenciaFalsa(cerrar_anterior=True)
        assert sesion.abrir(carpeta, presencia, minutos=60) == 1
        assert (privado / sesion.PEDIR_CIERRE).exists()  # se irá sola al acabar
        assert presencia.passwords_pedidas == []
        assert "SESION_ANTERIOR_OCUPADA" in leer_informe(carpeta)["errores"]
        assert atendidas == []


class AulaQueSeCierra:
    def __init__(self) -> None:
        self.cerradas = 0

    def cerrar(self) -> None:
        self.cerradas += 1


class TestCierrePedido:
    """La sesión anterior, cuando otra de su carpeta le pide irse."""

    def preparar(self, tmp_path):
        dir_tiza = tmp_path / ".tiza"
        privado = sesion.crear_dir_vistas(tmp_path)
        salidas: list[tuple[int, bool, bool]] = []
        aula = AulaQueSeCierra()

        def salir(codigo):
            carpeta = buzon.carpeta_buzon(dir_tiza)
            salidas.append(
                (codigo, (carpeta / buzon.SESION).exists(), (carpeta / buzon.RESERVA).exists())
            )

        cierre = sesion._Cierre(dir_tiza, privado, aula, threading.Event(), salir=salir)
        return cierre, privado, salidas, aula

    def test_sin_peticion_no_hace_nada(self, tmp_path):
        cierre, _privado, salidas, _aula = self.preparar(tmp_path)
        assert cierre.revisar() is True
        assert not cierre.pedido.is_set() and not cierre.cerrar.is_set()
        assert salidas == []

    def test_sin_pregunta_en_curso_para_el_buzon(self, tmp_path):
        cierre, privado, salidas, _aula = self.preparar(tmp_path)
        (privado / sesion.PEDIR_CIERRE).touch()
        assert cierre.revisar() is True
        assert cierre.pedido.is_set() and cierre.cerrar.is_set()
        assert salidas == []

    def test_a_media_pregunta_se_va_en_el_acto(self, tmp_path):
        cierre, privado, salidas, aula = self.preparar(tmp_path)
        with buzon.abrir_sesion(tmp_path / ".tiza", datetime.now(UTC) + timedelta(minutes=5)):
            cierre.esperando.set()  # la terminal se cerró en un «input»
            (privado / sesion.PEDIR_CIERRE).touch()
            assert cierre.revisar() is False
        assert salidas == [(0, False, False)]  # ya había soltado la carpeta
        assert aula.cerradas == 1
        assert not privado.exists()

    def test_la_pregunta_que_llega_tarde_tambien_sale(self, tmp_path):
        # Pedido el cierre cuando ya estaba en marcha, la sesión se va en el latido siguiente.
        cierre, privado, salidas, _aula = self.preparar(tmp_path)
        (privado / sesion.PEDIR_CIERRE).touch()
        assert cierre.revisar() is True
        cierre.esperando.set()
        assert cierre.revisar() is False
        assert [codigo for codigo, *_ in salidas] == [0]


class TestPresenciaVigilada:
    def test_anota_que_espera_al_docente_mientras_pregunta(self, tmp_path):
        cierre, *_ = TestCierrePedido().preparar(tmp_path)
        vistos: list[bool] = []

        class Presencia(PresenciaFalsa):
            def confirmar_copia(self, resumen):
                vistos.append(cierre.esperando.is_set())
                return True

        vigilada = sesion._PresenciaVigilada(Presencia(), cierre)
        assert vigilada.confirmar_copia(None) is True
        assert vistos == [True]
        assert not cierre.esperando.is_set()

    def test_pedido_el_cierre_responde_no_sin_preguntar(self, tmp_path):
        cierre, *_ = TestCierrePedido().preparar(tmp_path)
        presencia = PresenciaFalsa(real=True, ampliar=(True,))
        vigilada = sesion._PresenciaVigilada(presencia, cierre)
        cierre.pedido.set()
        assert vigilada.confirmar_real("resumen") is False
        assert vigilada.ofrecer_ampliacion(30, 300) is False
        assert presencia.resumenes == []

    def test_un_si_que_llega_despues_del_cierre_es_no(self, tmp_path):
        cierre, *_ = TestCierrePedido().preparar(tmp_path)

        class Presencia(PresenciaFalsa):
            def confirmar_orden(self, resumen):
                cierre.pedido.set()  # mientras el docente contestaba
                return True

        assert sesion._PresenciaVigilada(Presencia(), cierre).confirmar_orden(None) is False

    def test_la_pregunta_de_sobrescribir_tambien_se_vigila(self, tmp_path):
        cierre, *_ = TestCierrePedido().preparar(tmp_path)
        vistos: list[bool] = []

        class Presencia(PresenciaFalsa):
            def confirmar_sobrescribir(self, resumen):
                vistos.append(cierre.esperando.is_set())
                return True

        vigilada = sesion._PresenciaVigilada(Presencia(), cierre)
        assert vigilada.confirmar_sobrescribir(None) is True
        assert vistos == [True] and not cierre.esperando.is_set()
        cierre.pedido.set()  # pedido el cierre, responde no sin preguntar
        assert vigilada.confirmar_sobrescribir(None) is False
        assert vistos == [True]

    def test_cumple_la_interfaz_de_presencia(self):
        metodos = [
            nombre
            for nombre, valor in vars(publicacion.Presencia).items()
            if callable(valor) and not nombre.startswith("_")
        ]
        for nombre in metodos:
            esperado = list(inspect.signature(getattr(publicacion.Presencia, nombre)).parameters)
            obtenido = list(
                inspect.signature(getattr(sesion._PresenciaVigilada, nombre)).parameters
            )
            assert obtenido == esperado, nombre


def test_la_sesion_abierta_se_cierra_cuando_otra_se_lo_pide(tmp_path, monkeypatch):
    carpeta, _atendidas = preparar_abrir(tmp_path, monkeypatch)
    original = buzon.abrir_sesion
    monkeypatch.setattr(
        buzon, "abrir_sesion", lambda *a, **k: original(*a, **{**k, "intervalo": 0.01})
    )
    vistos: list[bool] = []

    def atender(*args, **opciones):
        privado = next(
            ruta
            for ruta in sesion._raiz_vistas().glob("sesion-*")
            if sesion._marca(ruta) == {"carpeta": str(carpeta.resolve()), "pid": os.getpid()}
        )
        (privado / sesion.PEDIR_CIERRE).touch()  # otro «tiza empezar» de la carpeta
        limite = time.monotonic() + 5
        while not opciones["parar"]() and time.monotonic() < limite:
            time.sleep(0.01)
        vistos.append(opciones["parar"]())
        return False

    monkeypatch.setattr(buzon, "atender", atender)
    presencia = PresenciaFalsa(ampliar=(True,))
    assert sesion.abrir(carpeta, presencia, minutos=60, preparar=False) == 0
    assert vistos == [True]
    assert presencia.avisos[-1] == publicacion.Aviso("SESION_CERRADA", {"motivo": "otra"})
    assert buzon.carpeta_libre(carpeta / ".tiza")


def test_no_borra_el_directorio_de_una_sesion_viva_de_otro_protocolo(tmp_path):
    anterior = sesion_anterior(tmp_path)
    ruta = buzon.carpeta_buzon(tmp_path / ".tiza") / buzon.SESION
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    ruta.write_text(json.dumps({**datos, "version": 1}), encoding="utf-8")
    sesion.crear_dir_vistas(tmp_path)
    assert anterior.is_dir()
