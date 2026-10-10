"""Tests del estado de trabajo de la asignatura (tiza.estado): lo que vive en `.tiza/`."""

from __future__ import annotations

import json

import pytest

from tiza import estado

CURSOS = {
    "pruebas": {"id": 1234, "secciones": [{"numero": 3, "nombre": "Tema 3", "id": 30}]},
    "real": {"id": 5678, "secciones": [{"numero": 3, "nombre": "Tema 3", "id": 31}]},
}


class TestEstructuraFichero:
    def test_escribe_la_v2_con_generado_y_se_lee(self, tmp_path):
        ruta = estado.escribir_estructura(tmp_path / ".tiza", CURSOS)
        assert ruta == tmp_path / ".tiza" / "estructura.json"
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
        assert crudo["version"] == 2
        assert crudo["generado"]
        assert list(crudo["cursos"]) == ["pruebas", "real"]
        estructura = estado.cargar_estructura(tmp_path / ".tiza")
        assert estructura.pruebas["id"] == 1234
        assert [curso["id"] for curso in estructura.reales] == [5678]
        assert estructura.cursos("pruebas")[0]["secciones"][0]["numero"] == 3

    def test_admite_real_como_lista(self, tmp_path):
        reales = [CURSOS["real"], {**CURSOS["real"], "id": 9}]
        estado.escribir_estructura(tmp_path, {"real": reales})
        estructura = estado.cargar_estructura(tmp_path)
        assert [curso["id"] for curso in estructura.reales] == [5678, 9]

    def test_un_entorno_desconocido_no_tiene_cursos(self, tmp_path):
        estado.escribir_estructura(tmp_path, CURSOS)
        estructura = estado.cargar_estructura(tmp_path)
        assert estructura.cursos("otro") == ()

    def test_lee_una_v1_como_si_fuera_v2(self, tmp_path):
        v1 = {
            "version": 1,
            "generado": "2026-10-03T10:00:00+00:00",
            "cursos": {"real": CURSOS["real"], "pruebas": CURSOS["pruebas"]},
        }
        (tmp_path / "estructura.json").write_text(json.dumps(v1), encoding="utf-8")
        estructura = estado.cargar_estructura(tmp_path)
        assert [curso["id"] for curso in estructura.reales] == [5678]
        assert estructura.pruebas["id"] == 1234

    def test_ausente_falla(self, tmp_path):
        with pytest.raises(estado.ErrorEstado) as exc:
            estado.cargar_estructura(tmp_path)
        assert exc.value.codigo == "ESTRUCTURA_AUSENTE"

    def test_ilegible_falla(self, tmp_path):
        (tmp_path / "estructura.json").write_text("{esto no es json", encoding="utf-8")
        with pytest.raises(estado.ErrorEstado) as exc:
            estado.cargar_estructura(tmp_path)
        assert exc.value.codigo == "ESTRUCTURA_ILEGIBLE"

    def test_fuera_del_esquema_falla_al_leer(self, tmp_path):
        datos = {
            "version": 2,
            "generado": "x",
            "cursos": {"real": [{"id": "uno", "secciones": []}]},
        }
        (tmp_path / "estructura.json").write_text(json.dumps(datos), encoding="utf-8")
        with pytest.raises(estado.ErrorEstado) as exc:
            estado.cargar_estructura(tmp_path)
        assert exc.value.codigo == "ESTRUCTURA_INVALIDA"

    def test_fuera_del_esquema_falla_al_escribir_sin_dejar_fichero(self, tmp_path):
        malos = {"pruebas": {"id": 1234, "secciones": [{"numero": 0, "nombre": "<b>", "id": 9}]}}
        with pytest.raises(estado.ErrorEstado) as exc:
            estado.escribir_estructura(tmp_path, malos)
        assert exc.value.codigo == "ESTRUCTURA_INVALIDA"
        assert not (tmp_path / "estructura.json").exists()


class TestVerificados:
    def test_guarda_y_carga_con_fecha(self, tmp_path):
        ruta = estado.guardar_verificado(tmp_path, "a" * 64, "pagina.md", 100)
        assert ruta == tmp_path / "verificados.json"
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
        assert crudo["version"] == 1
        assert crudo["ficheros"]["a" * 64]["fecha"]
        registro = estado.cargar_verificados(tmp_path)
        assert registro["a" * 64].nombre == "pagina.md"
        assert registro["a" * 64].cmid == 100

    def test_ausente_es_un_mapa_vacio(self, tmp_path):
        assert estado.cargar_verificados(tmp_path) == {}

    def test_fichero_corrupto_se_ignora(self, tmp_path):
        (tmp_path / "verificados.json").write_text("{esto no es json", encoding="utf-8")
        assert estado.cargar_verificados(tmp_path) == {}

    def test_sin_mapa_de_ficheros_se_ignora(self, tmp_path):
        (tmp_path / "verificados.json").write_text(
            json.dumps({"version": 1, "ficheros": ["x"]}), encoding="utf-8"
        )
        assert estado.cargar_verificados(tmp_path) == {}

    def test_una_entrada_que_no_encaja_no_cuenta(self, tmp_path):
        datos = {
            "version": 1,
            "ficheros": {
                "a" * 64: "basura",
                "b" * 64: {"nombre": "x", "cmid": True},
                "d" * 64: {"nombre": "z", "cmid": 4, "fecha": 5},
                "c" * 64: {"nombre": "y", "cmid": 3},
            },
        }
        (tmp_path / "verificados.json").write_text(json.dumps(datos), encoding="utf-8")
        assert list(estado.cargar_verificados(tmp_path)) == ["c" * 64]

    def test_anotar_en_memoria_usa_el_mismo_formato(self):
        registro: dict = {}
        estado.anotar_verificado(registro, "a" * 64, "pagina.md", 100)
        verificado = registro["a" * 64]
        assert isinstance(verificado, estado.Verificado)
        assert (verificado.nombre, verificado.cmid) == ("pagina.md", 100)
        assert verificado.fecha

    def test_puerta_real(self):
        registro = {"a" * 64: estado.Verificado("pagina.md", 1, "2026-10-10T10:00:00+00:00")}
        assert estado.comprobar_puerta_real(registro, [("pagina.md", "a" * 64)]) == []
        assert estado.comprobar_puerta_real(registro, [("tarea.md", "b" * 64)]) == ["tarea.md"]


class TestSecciones:
    def test_buscar_por_numero_y_por_nombre(self):
        secciones = [{"numero": 1, "nombre": "Proyecto", "id": 9}]
        assert estado.buscar_seccion(secciones, 1)["id"] == 9
        assert estado.buscar_seccion(secciones, "proyecto")["id"] == 9
        assert estado.buscar_seccion(secciones, "Otra") is None

    def test_una_entrada_que_no_es_seccion_se_salta(self):
        secciones = ["basura", {"numero": 1, "nombre": "Proyecto", "id": 9}]
        assert estado.buscar_seccion(secciones, 1)["id"] == 9

    def test_la_busqueda_normaliza_como_la_estructura(self):
        # La estructura guarda los nombres ya saneados (nombre_de_seccion colapsa
        # los espacios); la búsqueda debe normalizar igual para encontrarlos.
        saneada = [{"numero": 3, "nombre": "Tema 1", "id": 30}]
        assert estado.buscar_seccion(saneada, "Tema  1")["id"] == 30
        # Simétrico: también si el nombre guardado llevara espacios de más.
        bruta = [{"numero": 3, "nombre": "Tema  1", "id": 30}]
        assert estado.buscar_seccion(bruta, "Tema 1")["id"] == 30
        assert estado.buscar_seccion(saneada, "Tema 2") is None

    def test_nombre_de_seccion_sanea_angulos_y_controles(self):
        assert estado.nombre_de_seccion("Tema <1>\x07  repaso") == "Tema ‹1› repaso"
