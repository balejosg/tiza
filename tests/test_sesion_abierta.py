"""Tests de la sesión abierta (tiza.sesion_abierta): su estado y su interfaz.

La interfaz (``SesionAbierta.atender``) es la superficie de estos tests: no se
tocan los internos de ``sesion``. El buzón entero (``buzon.enviar`` →
``buzon.atender`` → ``SesionAbierta.atender``) se cruza con los dobles
``MoodleFalso`` y ``PresenciaFalsa``.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from dobles import (
    PAGINA,
    MoodleFalso,
    PresenciaFalsa,
    aula_con_tarea,
    dejar_peticion,
    enlace_simbolico,
    peticion,
    tarea_en,
)
from tiza import agente, buzon, config, contenido, estado, publicacion, sesion_abierta

CFG = config.Config(
    url="https://aula.ejemplo.org/centro",
    usuario="profe",
    cursos={"pruebas": 1234},
    reales=(5678,),
)
CFG_SIN_PRUEBAS = config.Config(
    url="https://aula.ejemplo.org/centro",
    usuario="profe",
    cursos={},
    reales=(5678,),
    sin_pruebas=True,
)


def preparar_carpeta(tmp_path) -> Path:
    carpeta = tmp_path / "asignatura"
    (carpeta / "img").mkdir(parents=True)
    (carpeta / "img" / "foto.png").write_bytes(b"png")
    (carpeta / "pagina.md").write_text(PAGINA, encoding="utf-8")
    return carpeta.resolve()


def verificar_en_pruebas(carpeta: Path, nombre: str = "pagina.md") -> dict[str, estado.Verificado]:
    """Marca el documento verificado en pruebas: en disco y en la memoria de la sesión."""
    doc = contenido.cargar(carpeta / nombre)
    estado.guardar_verificado(carpeta / ".tiza", contenido.hash_documento(doc), nombre, 100)
    return estado.cargar_verificados(carpeta / ".tiza")


def atender(datos: dict, moodle, cfg, carpeta: Path, presencia, **opciones) -> dict:
    """Atiende una petición con la interfaz real, el aula y la presencia doblados."""
    return sesion_abierta.SesionAbierta(moodle, cfg, carpeta, presencia, **opciones).atender(datos)


CUESTIONARIO = (
    '---\ntipo: cuestionario\nnombre: Repaso\nseccion: "Fracciones"\n'
    "preguntas:\n"
    "  - tipo: verdadero_falso\n"
    "    enunciado: El agua hierve a 100 °C.\n"
    "    respuesta: verdadero\n"
    "  - tipo: respuesta_corta\n"
    "    enunciado: Capital de Francia\n"
    "    aceptadas: [París]\n"
    "---\n\nDescripción del cuestionario.\n"
)


class TestAtender:
    def test_publica_un_cuestionario_en_pruebas(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        (carpeta / "cuestionario.md").write_text(CUESTIONARIO, encoding="utf-8")
        datos = peticion()
        datos["ficheros"] = ["cuestionario.md"]
        moodle = MoodleFalso()
        documento = atender(datos, moodle, CFG, carpeta, PresenciaFalsa())
        assert documento["resultado"] == "ok"
        [fichero] = documento["ficheros"]
        assert fichero["tipo"] == "cuestionario"
        assert fichero["url"].endswith("/mod/quiz/view.php?id=100")
        detalles = [paso["detalle"] for paso in documento["pasos"] if paso["codigo"] == "PUBLICAR"]
        assert detalles == ["cuestionario.md: 2 preguntas"]
        categoria = moodle.categorias[100]
        assert len(moodle.bancos[categoria]) == 2
        # Queda verificado para la puerta de real.
        assert estado.cargar_verificados(carpeta / ".tiza")

    def test_pruebas_avisa_y_publica_sin_preguntar(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        presencia = PresenciaFalsa()
        documento = atender(peticion(), MoodleFalso(), CFG, carpeta, presencia)
        assert documento["resultado"] == "ok"
        assert presencia.resumenes == []
        assert presencia.codigos()[0] == "PUBLICANDO_EN_PRUEBAS"
        assert presencia.codigos()[-1] == "RESULTADO"
        assert (carpeta / ".tiza" / "informe.json").is_file()

    def test_real_ensena_el_resumen_y_publica_si_confirma(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        verificados = verificar_en_pruebas(carpeta)
        datos = peticion("real")
        dejar_peticion(carpeta, datos)
        presencia = PresenciaFalsa(real=True)
        moodle = MoodleFalso()
        documento = atender(
            datos,
            moodle,
            CFG,
            carpeta,
            presencia,
            nombres={5678: "Matemáticas 2ºB"},
            verificados=verificados,
        )
        assert documento["resultado"] == "ok"
        [resumen] = presencia.resumenes
        assert (resumen.curso, resumen.nombre_curso, resumen.visible) == (
            5678,
            "Matemáticas 2ºB",
            None,
        )
        [doc] = resumen.documentos
        assert doc.fichero == "pagina.md"
        assert doc.recursos == ("img/foto.png",)
        assert doc.vista_previa is not None and doc.vista_previa.is_file()
        assert any(llamada[0] == "crear" for llamada in moodle.llamadas)

    def test_real_con_la_carpeta_preview_enlazada_no_escribe_fuera_ni_pregunta(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        verificados = verificar_en_pruebas(carpeta)
        fuera = tmp_path / "fuera"
        fuera.mkdir()
        enlace_simbolico(carpeta / ".tiza" / "preview", fuera)
        presencia = PresenciaFalsa(real=True)
        moodle = MoodleFalso()
        documento = atender(
            peticion("real"), moodle, CFG, carpeta, presencia, verificados=verificados
        )
        assert documento["errores"] == ["DIRECTORIO_NO_SEGURO"]
        assert presencia.resumenes == []
        assert list(fuera.iterdir()) == []
        assert not any(llamada[0] == "crear" for llamada in moodle.llamadas)

    def test_dos_documentos_con_el_mismo_nombre_de_fichero_no_se_pisan_la_vista(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        for subcarpeta, nombre, texto in (
            ("a", "Primero", "TEXTO DEL PRIMERO"),
            ("b", "Segundo", "TEXTO DEL SEGUNDO"),
        ):
            (carpeta / subcarpeta).mkdir()
            (carpeta / subcarpeta / "x.md").write_text(
                f"---\ntipo: pagina\nnombre: {nombre}\nseccion: 3\n---\n\n{texto}\n",
                encoding="utf-8",
            )
        datos = peticion("real")
        datos["ficheros"] = ["a/x.md", "b/x.md"]
        verificados: dict = {}
        atender(
            dict(datos, entorno="pruebas"),
            MoodleFalso(),
            CFG,
            carpeta,
            PresenciaFalsa(),
            verificados=verificados,
        )
        presencia = PresenciaFalsa(real=False)
        atender(datos, MoodleFalso(), CFG, carpeta, presencia, verificados=verificados)
        [resumen] = presencia.resumenes
        primero, segundo = resumen.documentos
        assert primero.vista_previa != segundo.vista_previa
        assert "TEXTO DEL PRIMERO" in primero.vista_previa.read_text(encoding="utf-8")
        assert "TEXTO DEL SEGUNDO" in segundo.vista_previa.read_text(encoding="utf-8")

    def test_lo_de_fuera_da_el_mismo_codigo_exista_o_no(self, tmp_path):
        """El agente no puede averiguar qué ficheros hay fuera de su carpeta."""
        carpeta = preparar_carpeta(tmp_path)
        (tmp_path / "secreto.xlsx").write_bytes(b"x")
        errores = []
        for nombre, destino in (("existe.md", "secreto.xlsx"), ("ninguno.md", "no_existe.xlsx")):
            (carpeta / nombre).write_text(
                f"---\ntipo: pagina\nnombre: P\nseccion: 3\n---\n\n[x](../{destino})\n",
                encoding="utf-8",
            )
            datos = peticion()
            datos["ficheros"] = [nombre]
            documento = atender(datos, MoodleFalso(), CFG, carpeta, PresenciaFalsa())
            errores.append(documento["errores"])
        assert errores == [["RUTA_FUERA_DE_CARPETA"], ["RUTA_FUERA_DE_CARPETA"]]

    def test_un_recurso_oculto_no_se_sube(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        (carpeta / ".git").mkdir()
        (carpeta / ".git" / "config").write_text("url = x", encoding="utf-8")
        (carpeta / "oculto.md").write_text(
            "---\ntipo: pagina\nnombre: P\nseccion: 3\n---\n\n[x](.git/config)\n",
            encoding="utf-8",
        )
        datos = peticion()
        datos["ficheros"] = ["oculto.md"]
        moodle = MoodleFalso()
        documento = atender(datos, moodle, CFG, carpeta, PresenciaFalsa())
        assert documento["errores"] == ["RECURSO_NO_PERMITIDO"]
        assert moodle.llamadas == []

    def test_real_rechazado_no_publica(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        verificados = verificar_en_pruebas(carpeta)
        moodle = MoodleFalso()
        documento = atender(
            peticion("real"),
            moodle,
            CFG,
            carpeta,
            PresenciaFalsa(real=False),
            verificados=verificados,
        )
        assert documento["errores"] == ["ABORTADO"]
        assert not any(llamada[0] == "crear" for llamada in moodle.llamadas)

    def test_otra_carpeta_no_toca_el_directorio_actual(self, tmp_path, monkeypatch):
        carpeta = preparar_carpeta(tmp_path)
        otro = tmp_path / "otro"
        otro.mkdir()
        monkeypatch.chdir(otro)
        documento = atender(peticion(), MoodleFalso(), CFG, carpeta, PresenciaFalsa())
        assert documento["resultado"] == "ok"
        assert (carpeta / ".tiza" / "verificados.json").is_file()
        assert list(otro.iterdir()) == []


class TestAtenderSinPruebas:
    def test_publica_oculto_con_confirmacion_corta(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        datos = peticion("real", visible=False)
        dejar_peticion(carpeta, datos)
        presencia = PresenciaFalsa(real=True)
        moodle = MoodleFalso()
        documento = atender(
            datos, moodle, CFG_SIN_PRUEBAS, carpeta, presencia, nombres={5678: "Matemáticas 2ºB"}
        )
        assert documento["resultado"] == "ok"
        assert presencia.resumenes == []  # la confirmación larga no se usa
        [corto] = presencia.resumenes_cortos
        assert (corto.curso, corto.nombre_curso) == (5678, "Matemáticas 2ºB")
        [doc] = corto.documentos
        assert set(vars(doc)) == {"fichero", "tipo", "nombre", "existe", "itinerario"}
        assert (doc.fichero, doc.tipo, doc.nombre) == ("pagina.md", "pagina", "Repaso")
        assert doc.existe is False  # el curso no tiene todavía esa página
        assert not (carpeta / ".tiza" / "preview").exists()  # no hay vista previa
        [fichero] = documento["ficheros"]
        assert fichero["oculto"] is True
        assert any(llamada[0] == "crear" for llamada in moodle.llamadas)

    def test_resumen_marca_los_documentos_que_ya_existen(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        datos = peticion("real", visible=False)
        dejar_peticion(carpeta, datos)
        moodle = MoodleFalso(
            secciones=[
                {
                    "numero": 3,
                    "nombre": "Tema 3",
                    "id": 30,
                    "modulos": [{"cmid": 100, "nombre": "Repaso", "tipo": "pagina"}],
                }
            ]
        )
        presencia = PresenciaFalsa(real=True)
        documento = atender(datos, moodle, CFG_SIN_PRUEBAS, carpeta, presencia)
        assert documento["resultado"] == "ok"
        [doc] = presencia.resumenes_cortos[0].documentos
        assert doc.existe is True

    def test_resumen_avisa_si_no_puede_comprobar_si_existe(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        datos = peticion("real", visible=False)
        dejar_peticion(carpeta, datos)
        moodle = MoodleFalso(secciones=[{"numero": 3, "nombre": "Tema 3", "id": 30}])
        presencia = PresenciaFalsa(real=False)  # solo interesa el resumen
        documento = atender(datos, moodle, CFG_SIN_PRUEBAS, carpeta, presencia)
        assert documento["errores"] == ["ABORTADO"]
        [doc] = presencia.resumenes_cortos[0].documentos
        assert doc.existe is None

    @pytest.mark.parametrize("visible", [True, None])
    def test_solo_se_publica_oculto(self, tmp_path, visible):
        carpeta = preparar_carpeta(tmp_path)
        moodle = MoodleFalso()
        documento = atender(
            peticion("real", visible=visible), moodle, CFG_SIN_PRUEBAS, carpeta, PresenciaFalsa()
        )
        assert documento["errores"] == ["SOLO_OCULTO_SIN_PRUEBAS"]
        assert not any(llamada[0] == "crear" for llamada in moodle.llamadas)

    def test_el_docente_rechaza_la_confirmacion(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        datos = peticion("real", visible=False)
        dejar_peticion(carpeta, datos)
        moodle = MoodleFalso()
        documento = atender(datos, moodle, CFG_SIN_PRUEBAS, carpeta, PresenciaFalsa(real=False))
        assert documento["resultado"] == "abortado"
        assert documento["errores"] == ["ABORTADO"]
        assert not any(llamada[0] == "crear" for llamada in moodle.llamadas)

    def test_peticion_retirada_tras_confirmar(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        presencia = PresenciaFalsa(real=True)
        documento = atender(
            peticion("real", visible=False), MoodleFalso(), CFG_SIN_PRUEBAS, carpeta, presencia
        )
        assert documento["errores"] == ["PETICION_RETIRADA"]
        assert "PETICION_RETIRADA" in presencia.codigos()

    def test_pruebas_sin_curso_devuelve_sin_curso_pruebas(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        documento = atender(
            peticion("pruebas"), MoodleFalso(), CFG_SIN_PRUEBAS, carpeta, PresenciaFalsa()
        )
        assert documento["errores"] == ["SIN_CURSO_PRUEBAS"]

    def test_estructura_sin_curso_de_pruebas(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        peticion_estructura = {
            "version": buzon.VERSION_PROTOCOLO,
            "id": "b" * 32,
            "comando": "estructura",
            "ficheros": [],
            "entorno": None,
            "visible": None,
            "solo_fechas": False,
        }
        documento = atender(
            peticion_estructura, MoodleFalso(), CFG_SIN_PRUEBAS, carpeta, PresenciaFalsa()
        )
        assert documento["resultado"] == "ok"
        datos = json.loads((carpeta / ".tiza" / "estructura.json").read_text(encoding="utf-8"))
        assert set(datos["cursos"]) == {"real"}
        assert datos["cursos"]["real"][0]["secciones"][0]["nombre"] == "Tema 3"

    def test_con_pruebas_la_puerta_y_la_vista_previa_siguen_igual(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        verificados = verificar_en_pruebas(carpeta)
        datos = peticion("real")
        dejar_peticion(carpeta, datos)
        presencia = PresenciaFalsa(real=True)
        documento = atender(datos, MoodleFalso(), CFG, carpeta, presencia, verificados=verificados)
        assert documento["resultado"] == "ok"
        assert presencia.resumenes_cortos == []
        [resumen] = presencia.resumenes
        [doc] = resumen.documentos
        assert doc.vista_previa is not None and doc.vista_previa.is_file()


class TestVistasPrivadas:
    def test_real_escribe_la_vista_en_el_directorio_privado_y_no_en_la_carpeta(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        verificados = verificar_en_pruebas(carpeta)
        privado = tmp_path / "privado"
        privado.mkdir()
        presencia = PresenciaFalsa(real=False)
        atender(
            peticion("real"),
            MoodleFalso(),
            CFG,
            carpeta,
            presencia,
            dir_vistas=privado,
            verificados=verificados,
        )
        [doc] = presencia.resumenes[0].documentos
        assert doc.vista_previa.is_relative_to(privado) and doc.vista_previa.is_file()
        assert not (carpeta / ".tiza" / "preview").exists()

    def test_cambiar_la_vista_de_la_carpeta_no_cambia_la_que_se_ensena(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        verificados = verificar_en_pruebas(carpeta)
        falsa = carpeta / ".tiza" / "preview" / "pagina.html"
        falsa.parent.mkdir(parents=True)
        falsa.write_text("VISTA FALSA DEL AGENTE", encoding="utf-8")
        privado = tmp_path / "privado"
        privado.mkdir()
        presencia = PresenciaFalsa(real=False)
        atender(
            peticion("real"),
            MoodleFalso(),
            CFG,
            carpeta,
            presencia,
            dir_vistas=privado,
            verificados=verificados,
        )
        [doc] = presencia.resumenes[0].documentos
        assert doc.vista_previa != falsa
        assert "FALSA" not in doc.vista_previa.read_text(encoding="utf-8")
        assert falsa.read_text(encoding="utf-8") == "VISTA FALSA DEL AGENTE"


class PresenciaQueRetira(PresenciaFalsa):
    """Confirma, pero antes retira la petición como si el agente hubiera dejado de esperar."""

    def __init__(self, ruta_peticion: Path) -> None:
        super().__init__(real=True)
        self._ruta = ruta_peticion

    def confirmar_real(self, resumen):
        self.resumenes.append(resumen)
        self._ruta.unlink()
        return True


class TestSoloFechas:
    def test_en_pruebas_cambia_la_fecha_sin_verificar_ni_pedir_nada(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        tarea_en(carpeta)
        datos = peticion()
        datos["ficheros"] = ["tarea.md"]
        datos["solo_fechas"] = True
        moodle = aula_con_tarea()
        presencia = PresenciaFalsa()
        documento = atender(datos, moodle, CFG, carpeta, presencia)
        assert documento["resultado"] == "ok"
        [fichero] = documento["ficheros"]
        assert (fichero["accion"], fichero["cmid"]) == ("actualizada", 55)
        assert moodle.leer_modulo(55)["fechas"]["duedate"] == (2026, 10, 12, 23, 59)
        assert presencia.resumenes == []
        assert estado.cargar_verificados(carpeta / ".tiza") == {}  # no es un contenido verificado
        assert not any(llamada[0] in ("crear", "subir") for llamada in moodle.llamadas)

    def test_en_real_ensena_antes_y_despues_y_publica_si_confirma(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        tarea_en(carpeta)
        datos = peticion("real")
        datos["ficheros"] = ["tarea.md"]
        datos["solo_fechas"] = True
        dejar_peticion(carpeta, datos)
        moodle = aula_con_tarea()
        presencia = PresenciaFalsa(real=True)
        documento = atender(
            datos, moodle, CFG, carpeta, presencia, nombres={5678: "Matemáticas 2ºB"}
        )
        assert documento["resultado"] == "ok"
        [resumen] = presencia.resumenes
        assert resumen.solo_fechas is True
        assert (resumen.visible, resumen.secciones_nuevas) == (None, ())
        [doc] = resumen.documentos
        assert doc.vista_previa is None
        estados = {c.campo: (c.estado, c.antes, c.despues) for c in doc.cambios}
        assert estados["entrega"] == (
            "cambia",
            (2026, 10, 10, 23, 59),
            (2026, 10, 12, 23, 59),
        )
        assert moodle.leer_modulo(55)["fechas"]["duedate"] == (2026, 10, 12, 23, 59)

    def test_en_real_rechazado_no_cambia_nada(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        tarea_en(carpeta)
        datos = peticion("real")
        datos["ficheros"] = ["tarea.md"]
        datos["solo_fechas"] = True
        dejar_peticion(carpeta, datos)
        moodle = aula_con_tarea()
        documento = atender(datos, moodle, CFG, carpeta, PresenciaFalsa(real=False))
        assert documento["resultado"] == "abortado"
        assert not any(llamada[0] == "actualizar" for llamada in moodle.llamadas)

    def test_en_real_sin_curso_de_pruebas_no_exige_oculto(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        tarea_en(carpeta)
        datos = peticion("real")
        datos["ficheros"] = ["tarea.md"]
        datos["solo_fechas"] = True
        dejar_peticion(carpeta, datos)
        presencia = PresenciaFalsa(real=True)
        documento = atender(datos, aula_con_tarea(), CFG_SIN_PRUEBAS, carpeta, presencia)
        assert documento["resultado"] == "ok"
        assert presencia.resumenes_cortos == []
        [resumen] = presencia.resumenes
        assert resumen.solo_fechas is True

    def test_una_pagina_no_admite_solo_fechas(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        datos = peticion()
        datos["solo_fechas"] = True
        moodle = MoodleFalso()
        documento = atender(datos, moodle, CFG, carpeta, PresenciaFalsa())
        assert documento["resultado"] == "error"
        assert documento["errores"] == ["SOLO_FECHAS_NO_APLICA"]
        assert not any(llamada[0] == "actualizar" for llamada in moodle.llamadas)

    def test_sin_el_modulo_no_cambia_nada(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        tarea_en(carpeta)
        datos = peticion()
        datos["ficheros"] = ["tarea.md"]
        datos["solo_fechas"] = True
        documento = atender(datos, MoodleFalso(), CFG, carpeta, PresenciaFalsa())
        assert documento["errores"] == ["MODULO_AUSENTE"]

    def test_publicar_con_es_todo_o_nada_aunque_no_pase_por_la_sesion(self, tmp_path):
        # La terminal del docente llama a publicar_con sin la validación previa de la sesión.
        carpeta = preparar_carpeta(tmp_path)
        tarea_en(carpeta)
        (carpeta / "otra.md").write_text(
            "---\ntipo: tarea\nnombre: Otra\nseccion: 3\napertura: 2026-10-01\n"
            "entrega: 2026-10-12\n---\n\nResuelve.\n",
            encoding="utf-8",
        )
        documentos = [contenido.cargar(carpeta / "tarea.md"), contenido.cargar(carpeta / "otra.md")]
        moodle = aula_con_tarea()  # «Problemas» existe; «Otra», no
        documento = publicacion.publicar_con(
            moodle, "pruebas", 1234, documentos, None, carpeta, PresenciaFalsa(), solo_fechas=True
        )
        assert documento["resultado"] == "error"
        assert documento["errores"] == ["MODULO_AUSENTE"]
        assert not any(llamada[0] == "actualizar" for llamada in moodle.llamadas)
        assert moodle.leer_modulo(55)["fechas"]["duedate"] == (2026, 10, 10, 23, 59)

    def test_si_se_retira_tras_confirmar_no_publica(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        tarea_en(carpeta)
        datos = peticion("real")
        datos["ficheros"] = ["tarea.md"]
        datos["solo_fechas"] = True
        dejar_peticion(carpeta, datos)
        ruta = buzon.carpeta_buzon(carpeta / ".tiza") / f"{datos['id']}{buzon.SUFIJO_PETICION}"
        moodle = aula_con_tarea()
        documento = atender(datos, moodle, CFG, carpeta, PresenciaQueRetira(ruta))
        assert documento["errores"] == ["PETICION_RETIRADA"]
        assert not any(llamada[0] == "actualizar" for llamada in moodle.llamadas)

    def test_el_informe_no_guarda_las_fechas_del_aula(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        tarea_en(carpeta)
        datos = peticion("real")
        datos["ficheros"] = ["tarea.md"]
        datos["solo_fechas"] = True
        dejar_peticion(carpeta, datos)
        atender(datos, aula_con_tarea(), CFG, carpeta, PresenciaFalsa(real=True))
        for ruta in (carpeta / ".tiza").rglob("*"):
            if ruta.is_file():
                texto = ruta.read_text(encoding="utf-8", errors="ignore")
                assert "duedate" not in texto and "2026-10-10" not in texto, ruta.name


class TestCalendarioEnLaConfirmacion:
    def test_un_calendario_invalido_se_dice_y_publicar_sigue(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        (carpeta / "calendario.toml").write_text("color = 'rojo'\n", encoding="utf-8")
        verificados = verificar_en_pruebas(carpeta)
        datos = peticion("real")
        dejar_peticion(carpeta, datos)
        presencia = PresenciaFalsa(real=True)
        documento = atender(datos, MoodleFalso(), CFG, carpeta, presencia, verificados=verificados)
        assert documento["resultado"] == "ok"
        [resumen] = presencia.resumenes
        assert resumen.aviso_calendario == "CALENDARIO_INVALIDO"
        assert resumen.solo_fechas is False

    def test_la_confirmacion_normal_lleva_los_cambios_de_fecha(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        tarea_en(carpeta)
        (carpeta / "calendario.toml").write_text("festivos = [2026-10-12]\n", encoding="utf-8")
        verificados = verificar_en_pruebas(carpeta, "tarea.md")
        datos = peticion("real")
        datos["ficheros"] = ["tarea.md"]
        dejar_peticion(carpeta, datos)
        presencia = PresenciaFalsa(real=True)
        atender(datos, aula_con_tarea(), CFG, carpeta, presencia, verificados=verificados)
        [resumen] = presencia.resumenes
        assert resumen.aviso_calendario is None
        [doc] = resumen.documentos
        entrega = next(c for c in doc.cambios if c.campo == "entrega")
        assert entrega.estado == "cambia"
        assert entrega.avisos == ("FECHA_FESTIVA",)


CFG_DOS = config.Config(
    url="https://aula.ejemplo.org/centro",
    usuario="profe",
    cursos={"pruebas": 1234},
    reales=(101, 102),
)
CFG_DOS_SIN_PRUEBAS = config.Config(
    url="https://aula.ejemplo.org/centro",
    usuario="profe",
    cursos={},
    reales=(101, 102),
    sin_pruebas=True,
)
NOMBRES_DOS = {101: "1º A", 102: "1º B"}


def aula_con_dos_cursos() -> MoodleFalso:
    def seccion(nombre):
        return [{"numero": 3, "nombre": nombre, "id": 30, "modulos": []}]

    return MoodleFalso(secciones_por_curso={101: seccion("Tema 3"), 102: seccion("Tema tres")})


def publicar_en_real(tmp_path, presencia, cfg=CFG_DOS, moodle=None, datos=None):
    carpeta = preparar_carpeta(tmp_path)
    verificados = verificar_en_pruebas(carpeta)
    datos = datos or peticion("real")
    dejar_peticion(carpeta, datos)
    moodle = moodle or aula_con_dos_cursos()
    documento = atender(
        datos, moodle, cfg, carpeta, presencia, nombres=NOMBRES_DOS, verificados=verificados
    )
    return carpeta, moodle, documento


class TestVariosCursosReales:
    def test_publica_en_los_dos_con_una_confirmacion_por_curso(self, tmp_path):
        presencia = PresenciaFalsa(real=(True, True))
        _, moodle, documento = publicar_en_real(tmp_path, presencia)
        assert documento["resultado"] == "ok"
        assert [(r.curso, r.nombre_curso, r.posicion, r.total) for r in presencia.resumenes] == [
            (101, "1º A", 1, 2),
            (102, "1º B", 2, 2),
        ]
        creados = [llamada[1] for llamada in moodle.llamadas if llamada[0] == "crear"]
        assert creados == [101, 102]
        assert documento["curso"] is None
        assert [(f["curso"], f["cmid"]) for f in documento["ficheros"]] == [(101, 100), (102, 101)]
        assert [p["detalle"] for p in documento["pasos"] if p["codigo"] == "CURSO"] == [
            "1 de 2: 101",
            "2 de 2: 102",
        ]
        assert [p["codigo"] for p in documento["pasos"]].count("LOGIN") == 1

    def test_la_puerta_y_las_vistas_se_hacen_una_vez(self, tmp_path):
        presencia = PresenciaFalsa(real=(True, True))
        _, _, _ = publicar_en_real(tmp_path, presencia)
        primera, segunda = presencia.resumenes
        assert primera.documentos[0].vista_previa == segunda.documentos[0].vista_previa
        assert primera.documentos[0].vista_previa is not None

    def test_sin_verificar_no_se_publica_en_ninguno(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        datos = peticion("real")
        dejar_peticion(carpeta, datos)
        presencia = PresenciaFalsa(real=(True, True))
        documento = atender(datos, aula_con_dos_cursos(), CFG_DOS, carpeta, presencia)
        assert documento["errores"] == ["VERIFICACION_PENDIENTE"]
        assert presencia.resumenes == []

    def test_no_en_el_primero_y_si_en_el_segundo(self, tmp_path):
        presencia = PresenciaFalsa(real=(False, True))
        _, moodle, documento = publicar_en_real(tmp_path, presencia)
        assert documento["resultado"] == "ok"
        assert [c for c in (ll[1] for ll in moodle.llamadas if ll[0] == "crear")] == [102]
        assert [(f["curso"]) for f in documento["ficheros"]] == [102]
        assert ("CURSO_OMITIDO", "101") in [(p["codigo"], p["detalle"]) for p in documento["pasos"]]

    def test_no_en_todos_es_abortado(self, tmp_path):
        presencia = PresenciaFalsa(real=False)
        _, moodle, documento = publicar_en_real(tmp_path, presencia)
        assert documento["resultado"] == "abortado"
        assert documento["errores"] == ["ABORTADO"]
        assert not any(llamada[0] == "crear" for llamada in moodle.llamadas)
        assert [p["codigo"] for p in documento["pasos"]] == ["CURSO_OMITIDO", "CURSO_OMITIDO"]

    def test_un_fallo_en_el_segundo_deja_hecho_el_primero(self, tmp_path):
        moodle = aula_con_dos_cursos()
        moodle.secciones_por_curso[102] = []  # sin la sección 3: no se puede publicar ahí
        presencia = PresenciaFalsa(real=(True, True))
        _, _, documento = publicar_en_real(tmp_path, presencia, moodle=moodle)
        assert documento["resultado"] == "error"
        assert [f["curso"] for f in documento["ficheros"]] == [101]
        assert documento["errores"]
        pasos = [(p["codigo"], p["resultado"]) for p in documento["pasos"]]
        assert ("CURSO", "ok") in pasos and ("CURSO", "fallo") in pasos

    def test_un_fallo_en_el_primero_no_sigue_con_el_segundo(self, tmp_path):
        moodle = aula_con_dos_cursos()
        moodle.secciones_por_curso[101] = []
        presencia = PresenciaFalsa(real=(True, True))
        _, _, documento = publicar_en_real(tmp_path, presencia, moodle=moodle)
        assert documento["resultado"] == "error"
        assert documento["ficheros"] == []
        assert [r.curso for r in presencia.resumenes] == [101]

    def test_retirada_entre_cursos(self, tmp_path, monkeypatch):
        respuestas = iter(
            [True, True, False]
        )  # antes del 1.º (tras confirmar), 2.º y tras confirmar
        monkeypatch.setattr(buzon, "peticion_pendiente", lambda *a, **k: next(respuestas))
        presencia = PresenciaFalsa(real=(True, True))
        _, moodle, documento = publicar_en_real(tmp_path, presencia)
        assert documento["resultado"] == "error"
        assert documento["errores"] == ["PETICION_RETIRADA"]
        assert [f["curso"] for f in documento["ficheros"]] == [101]
        assert "PETICION_RETIRADA" in presencia.codigos()

    def test_las_secciones_nuevas_se_avisan_solo_en_el_curso_que_las_necesita(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        (carpeta / "pagina.md").write_text(
            PAGINA.replace("seccion: 3", "seccion: Tema tres"), encoding="utf-8"
        )
        presencia = PresenciaFalsa(real=(True, True))
        verificados = verificar_en_pruebas(carpeta)
        datos = peticion("real")
        dejar_peticion(carpeta, datos)
        moodle = aula_con_dos_cursos()
        documento = atender(
            datos,
            moodle,
            CFG_DOS,
            carpeta,
            presencia,
            nombres=NOMBRES_DOS,
            verificados=verificados,
        )
        assert documento["resultado"] == "ok"
        primero, segundo = presencia.resumenes
        assert primero.secciones_nuevas == ("Tema tres",)
        assert segundo.secciones_nuevas == ()

    def test_sin_pruebas_exige_oculto_en_todos(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        datos = peticion("real")
        dejar_peticion(carpeta, datos)
        documento = atender(
            datos, aula_con_dos_cursos(), CFG_DOS_SIN_PRUEBAS, carpeta, PresenciaFalsa()
        )
        assert documento["errores"] == ["SOLO_OCULTO_SIN_PRUEBAS"]

    def test_sin_pruebas_con_oculto_confirma_cada_curso(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        datos = peticion("real", visible=False)
        dejar_peticion(carpeta, datos)
        presencia = PresenciaFalsa(real=(True, True))
        moodle = aula_con_dos_cursos()
        documento = atender(
            datos, moodle, CFG_DOS_SIN_PRUEBAS, carpeta, presencia, nombres=NOMBRES_DOS
        )
        assert documento["resultado"] == "ok"
        assert [(r.curso, r.posicion, r.total) for r in presencia.resumenes_cortos] == [
            (101, 1, 2),
            (102, 2, 2),
        ]

    def test_un_solo_curso_da_el_informe_de_siempre(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        verificados = verificar_en_pruebas(carpeta)
        datos = peticion("real")
        dejar_peticion(carpeta, datos)
        presencia = PresenciaFalsa(real=True)
        documento = atender(datos, MoodleFalso(), CFG, carpeta, presencia, verificados=verificados)
        assert documento["curso"] == 5678
        assert [f["curso"] for f in documento["ficheros"]] == [5678]
        assert all(p["codigo"] not in ("CURSO", "CURSO_OMITIDO") for p in documento["pasos"])
        [resumen] = presencia.resumenes
        assert (resumen.posicion, resumen.total) == (1, 1)

    def test_un_solo_curso_dicho_que_no_es_abortado_como_siempre(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        verificados = verificar_en_pruebas(carpeta)
        datos = peticion("real")
        dejar_peticion(carpeta, datos)
        documento = atender(
            datos,
            MoodleFalso(),
            CFG,
            carpeta,
            PresenciaFalsa(real=False),
            verificados=verificados,
        )
        assert (documento["resultado"], documento["errores"], documento["pasos"]) == (
            "abortado",
            ["ABORTADO"],
            [],
        )

    def test_solo_fechas_pregunta_en_cada_curso(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        tarea_en(carpeta)
        moodle = aula_con_dos_cursos()
        for curso, cmid in ((101, 55), (102, 56)):
            moodle.secciones_por_curso[curso][0]["modulos"] = [
                {"cmid": cmid, "nombre": "Problemas", "tipo": "tarea"}
            ]
            moodle.formularios[cmid] = aula_con_tarea().formularios[55]
        datos = {**peticion("real"), "ficheros": ["tarea.md"], "solo_fechas": True}
        dejar_peticion(carpeta, datos)
        presencia = PresenciaFalsa(real=(True, False))
        documento = atender(datos, moodle, CFG_DOS, carpeta, presencia, nombres=NOMBRES_DOS)
        assert documento["resultado"] == "ok"
        assert [(r.curso, r.solo_fechas, r.posicion) for r in presencia.resumenes] == [
            (101, True, 1),
            (102, True, 2),
        ]
        assert [f["curso"] for f in documento["ficheros"]] == [101]

    def test_ningun_nombre_de_curso_llega_al_informe_ni_a_tiza(self, tmp_path):
        presencia = PresenciaFalsa(real=(True, True))
        carpeta, _, documento = publicar_en_real(tmp_path, presencia)
        texto = json.dumps(documento, ensure_ascii=False)
        assert "1º A" not in texto and "1º B" not in texto
        for ruta in (carpeta / ".tiza").rglob("*"):
            if ruta.is_file() and ruta.suffix in {".json", ".html", ".md"}:
                assert "1º A" not in ruta.read_text(encoding="utf-8", errors="ignore")


class TestEstructuraConVariosReales:
    def test_escribe_la_version_2_con_una_lista_de_cursos_reales(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        documento = sesion_abierta.estructura_con(aula_con_dos_cursos(), CFG_DOS, carpeta)
        assert documento["resultado"] == "ok"
        datos = json.loads((carpeta / ".tiza" / "estructura.json").read_text(encoding="utf-8"))
        assert datos["version"] == 2
        assert datos["cursos"]["pruebas"]["id"] == 1234
        assert [c["id"] for c in datos["cursos"]["real"]] == [101, 102]
        assert datos["cursos"]["real"][1]["secciones"][0]["nombre"] == "Tema tres"
        assert "1º A" not in json.dumps(datos, ensure_ascii=False)

    def test_fuera_del_esquema_no_se_escribe(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        moodle = MoodleFalso(
            secciones=[{"numero": 1, "nombre": "<b>x</b>", "id": 9, "modulos": []}]
        )
        documento = sesion_abierta.estructura_con(moodle, CFG, carpeta)
        assert documento["errores"] == ["ESTRUCTURA_INVALIDA"]
        assert not (carpeta / ".tiza" / "estructura.json").exists()


def md_it(carpeta: Path, nombre: str, titulo: str, extra: str = "") -> None:
    (carpeta / nombre).write_text(
        f"---\ntipo: pagina\nnombre: {titulo}\nseccion: 3\n{extra}---\n\nHola\n", encoding="utf-8"
    )


def publicar_pruebas(carpeta, ficheros, moodle, cfg=CFG, presencia=None):
    datos = {**peticion("pruebas"), "ficheros": ficheros}
    return atender(datos, moodle, cfg, carpeta, presencia or PresenciaFalsa())


class TestItinerarioEnLaSesion:
    def test_se_publica_primero_la_dependencia_aunque_se_pida_despues(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        md_it(carpeta, "test.md", "Test", "finalizacion: ver\n")
        md_it(carpeta, "tarea.md", "Siguiente", "restricciones:\n  completar: [test.md]\n")
        moodle = MoodleFalso()
        documento = publicar_pruebas(carpeta, ["tarea.md", "test.md"], moodle)
        assert documento["resultado"] == "ok"
        assert [f["nombre"] for f in documento["ficheros"]] == ["test.md", "tarea.md"]
        cm_test, cm_tarea = (f["cmid"] for f in documento["ficheros"])
        texto = moodle.formularios[cm_tarea]["availabilityconditionsjson"]
        assert json.loads(texto)["c"] == [{"type": "completion", "cm": cm_test, "e": 1}]

    def test_una_dependencia_ya_publicada_se_resuelve_en_el_curso(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        md_it(carpeta, "test.md", "Test")
        md_it(carpeta, "tarea.md", "Siguiente", "restricciones:\n  completar: [test.md]\n")
        moodle = MoodleFalso()
        publicar_pruebas(carpeta, ["test.md"], moodle)
        documento = publicar_pruebas(carpeta, ["tarea.md"], moodle)
        assert documento["resultado"] == "ok"
        [fichero] = documento["ficheros"]
        texto = moodle.formularios[fichero["cmid"]]["availabilityconditionsjson"]
        assert json.loads(texto)["c"][0]["cm"] == 100

    def test_dependencia_no_publicada_no_escribe_nada(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        md_it(carpeta, "test.md", "Test")
        md_it(carpeta, "otra.md", "Otra")
        md_it(carpeta, "tarea.md", "Siguiente", "restricciones:\n  completar: [test.md]\n")
        moodle = MoodleFalso()
        documento = publicar_pruebas(carpeta, ["otra.md", "tarea.md"], moodle)
        assert documento["errores"] == ["DEPENDENCIA_NO_PUBLICADA"]
        assert not any(ll[0] in ("crear", "actualizar", "crear_seccion") for ll in moodle.llamadas)

    def test_dependencia_invalida(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        md_it(carpeta, "tarea.md", "Siguiente", "restricciones:\n  completar: [falta.md]\n")
        documento = publicar_pruebas(carpeta, ["tarea.md"], MoodleFalso())
        assert documento["errores"] == ["DEPENDENCIA_INVALIDA"]

    def test_ciclo_en_la_peticion_no_publica_nada(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        md_it(carpeta, "a.md", "A", "restricciones:\n  completar: [b.md]\n")
        md_it(carpeta, "b.md", "B", "restricciones:\n  completar: [a.md]\n")
        moodle = MoodleFalso()
        documento = publicar_pruebas(carpeta, ["a.md", "b.md"], moodle)
        assert documento["errores"] == ["DEPENDENCIA_CIRCULAR"]
        assert not any(ll[0] in ("crear", "actualizar") for ll in moodle.llamadas)

    def test_el_orden_sin_dependencias_se_conserva(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        for nombre in ("c.md", "a.md", "b.md"):
            md_it(carpeta, nombre, nombre)
        docs = [
            contenido.cargar(carpeta / n, raiz=carpeta.resolve()) for n in ("c.md", "a.md", "b.md")
        ]
        ordenados = publicacion.ordenar_por_dependencias(docs, carpeta.resolve())
        assert [d.ruta.name for d in ordenados] == ["c.md", "a.md", "b.md"]  # type: ignore[union-attr]

    def test_cada_curso_real_resuelve_sus_propias_dependencias(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        md_it(carpeta, "test.md", "Test")
        md_it(carpeta, "tarea.md", "Siguiente", "restricciones:\n  completar: [test.md]\n")
        moodle = aula_con_dos_cursos()
        # Solo el curso 101 tiene publicado el test.
        publicacion.publicar_con(
            moodle,
            "real",
            101,
            [contenido.cargar(carpeta / "test.md")],
            False,
            carpeta,
            PresenciaFalsa(),
        )
        verificados = verificar_en_pruebas(carpeta, "tarea.md")
        datos = {**peticion("real"), "ficheros": ["tarea.md"], "visible": False}
        dejar_peticion(carpeta, datos)
        presencia = PresenciaFalsa(real=(True, True))
        documento = atender(
            datos,
            moodle,
            CFG_DOS,
            carpeta,
            presencia,
            nombres=NOMBRES_DOS,
            verificados=verificados,
        )
        assert documento["resultado"] == "error"
        assert documento["errores"] == ["DEPENDENCIA_NO_PUBLICADA"]
        assert [f["curso"] for f in documento["ficheros"]] == [101]

    def test_el_informe_no_lleva_nada_de_finalizacion_ni_de_disponibilidad(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        md_it(carpeta, "a.md", "A", "finalizacion: ver\nrestricciones:\n  desde: 2026-10-12\n")
        moodle = MoodleFalso()
        moodle.bloqueadas.add(100)
        documento = publicar_pruebas(carpeta, ["a.md"], moodle)
        informe_json = json.dumps(documento) + (carpeta / ".tiza" / "informe.json").read_text(
            encoding="utf-8"
        )
        for palabra in ("completion", "availability", "disponibilidad", "itinerario"):
            assert palabra not in informe_json
        sesion_abierta.estructura_con(moodle, CFG, carpeta)
        estructura = (carpeta / ".tiza" / "estructura.json").read_text(encoding="utf-8")
        assert "completion" not in estructura and "availab" not in estructura

    def test_la_restriccion_ajena_es_un_codigo_sin_mas(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        md_it(carpeta, "a.md", "A", "restricciones:\n  desde: 2026-10-12\n")
        moodle = MoodleFalso()
        moodle.secciones[0]["modulos"] = [{"cmid": 55, "nombre": "A", "tipo": "pagina"}]
        moodle.formularios[55] = {
            "name": "A",
            "availabilityconditionsjson": '{"op":"&","c":[{"type":"group","id":7}],"showc":[true]}',
        }
        documento = publicar_pruebas(carpeta, ["a.md"], moodle)
        assert documento["errores"] == ["RESTRICCION_AJENA"]
        assert "group" not in json.dumps(documento) and "7" not in str(documento["pasos"])


class TestPeticionInvalida:
    """La interfaz valida el esquema del buzón antes de tocar el aula."""

    def test_una_version_vieja_no_llega_a_publicar(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        datos = peticion()
        datos["version"] = buzon.VERSION_PROTOCOLO - 1
        moodle = MoodleFalso()
        with pytest.raises(buzon.ErrorBuzon) as exc:
            atender(datos, moodle, CFG, carpeta, PresenciaFalsa())
        assert exc.value.codigo == "PETICION_INVALIDA"
        assert moodle.llamadas == []


def cruzar_el_buzon(dir_tiza: Path, atender_callback, peticion_agente: dict) -> dict:
    """Deja correr ``enviar`` y ``atender`` de verdad hasta la primera respuesta."""
    listo = threading.Event()

    def dormir(_segundos):
        listo.set()
        time.sleep(0.002)

    caduca = buzon.ahora_utc() + timedelta(minutes=5)
    with buzon.abrir_sesion(dir_tiza, caduca, intervalo=0.05) as sesion_viva:
        hilo = threading.Thread(
            target=lambda: buzon.atender(
                dir_tiza,
                atender_callback,
                sesion_viva.caduca,
                intervalo=0.005,
                dormir=dormir,
                terminar=lambda documento: True,
            ),
            daemon=True,
        )
        hilo.start()
        assert listo.wait(timeout=2)
        try:
            return buzon.enviar(dir_tiza, peticion_agente, espera=5, intervalo=0.005)
        finally:
            hilo.join(timeout=3)


class TestBuzonEntero:
    """Agente y sesión se hablan por el buzón real, sin vecinos parcheados."""

    def test_una_publicacion_en_pruebas_cruza_el_buzon_y_actualiza_la_sesion(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        dir_tiza = carpeta / ".tiza"
        presencia = PresenciaFalsa()
        abierta = sesion_abierta.SesionAbierta(MoodleFalso(), CFG, carpeta, presencia)

        respuesta = cruzar_el_buzon(
            dir_tiza, abierta.atender, agente.peticion_publicar(["pagina.md"], "pruebas")
        )

        assert respuesta["resultado"] == "ok"
        [fichero] = respuesta["ficheros"]
        assert (fichero["tipo"], fichero["nombre"], fichero["cmid"]) == ("pagina", "pagina.md", 100)
        doc = contenido.cargar(carpeta / "pagina.md")
        assert contenido.hash_documento(doc) in abierta.verificados
        assert abierta.cupo == {"pruebas": 1}
        assert "PUBLICANDO_EN_PRUEBAS" in presencia.codigos()
        assert (carpeta / ".tiza" / "informe.json").is_file()

    def test_una_publicacion_en_real_con_verificacion_cruza_el_buzon(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        dir_tiza = carpeta / ".tiza"
        verificados = verificar_en_pruebas(carpeta)
        presencia = PresenciaFalsa(real=True)
        abierta = sesion_abierta.SesionAbierta(
            MoodleFalso(), CFG, carpeta, presencia, verificados=verificados
        )

        respuesta = cruzar_el_buzon(
            dir_tiza, abierta.atender, agente.peticion_publicar(["pagina.md"], "real")
        )

        assert respuesta["resultado"] == "ok"
        [resumen] = presencia.resumenes
        assert (resumen.curso, resumen.posicion) == (5678, 1)
        assert [f["curso"] for f in respuesta["ficheros"]] == [5678]

    def test_el_agente_retira_la_peticion_y_la_sesion_no_publica(self, tmp_path):
        carpeta = preparar_carpeta(tmp_path)
        dir_tiza = carpeta / ".tiza"
        verificados = verificar_en_pruebas(carpeta)
        peticion_agente = agente.peticion_publicar(["pagina.md"], "real")
        ruta = buzon.carpeta_buzon(dir_tiza) / f"{peticion_agente['id']}{buzon.SUFIJO_PETICION}"
        presencia = PresenciaQueRetira(ruta)
        abierta = sesion_abierta.SesionAbierta(
            MoodleFalso(), CFG, carpeta, presencia, verificados=verificados
        )

        respuesta = cruzar_el_buzon(dir_tiza, abierta.atender, peticion_agente)

        assert respuesta["resultado"] == "error"
        assert respuesta["errores"] == ["PETICION_RETIRADA"]
        assert "PETICION_RETIRADA" in presencia.codigos()
        assert respuesta["ficheros"] == []
