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
from tiza import buzon, config, contenido, publicacion, publicar, sesion

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
    assert len(metodos) == 10
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
