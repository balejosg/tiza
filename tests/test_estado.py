"""Tests del estado de trabajo de la asignatura (tiza.estado): lo que vive en `.tiza/`."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime

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


class TestCopiasDeTiza:
    """``.tiza/copias/``: el nombre y el sitio de las copias que deja ``tiza copia``."""

    MOMENTO = datetime(2026, 10, 19, 10, 30)

    def test_el_nombre_lleva_curso_y_fecha_y_las_repeticiones_un_sufijo(self):
        assert estado.nombre_de_copia("real", self.MOMENTO) == "real-20261019-1030.mbz"
        assert estado.nombre_de_copia("real", self.MOMENTO, 1) == "real-20261019-1030-2.mbz"
        assert estado.nombre_de_copia("5678", self.MOMENTO, 2) == "5678-20261019-1030-3.mbz"

    def test_reservar_da_su_nombre_sin_pisar_nada(self, tmp_path):
        dir_tiza = tmp_path / ".tiza"
        nombres = []
        for contenido in (b"uno", b"dos", b"tres"):
            temporal = estado.temporal_de_copia(dir_tiza)
            temporal.write_bytes(contenido)
            destino = estado.reservar_copia(dir_tiza, "pruebas", self.MOMENTO, temporal)
            assert not temporal.exists() and destino.read_bytes() == contenido
            nombres.append(destino.name)
        assert nombres == [
            "pruebas-20261019-1030.mbz",
            "pruebas-20261019-1030-2.mbz",
            "pruebas-20261019-1030-3.mbz",
        ]

    def test_un_fichero_del_docente_con_ese_nombre_se_respeta(self, tmp_path):
        carpeta = tmp_path / ".tiza" / estado.CARPETA_COPIAS
        carpeta.mkdir(parents=True)
        (carpeta / "pruebas-20261019-1030.mbz").write_bytes(b"suyo")
        temporal = estado.temporal_de_copia(tmp_path / ".tiza")
        temporal.write_bytes(b"nueva")
        destino = estado.reservar_copia(tmp_path / ".tiza", "pruebas", self.MOMENTO, temporal)
        assert destino.name == "pruebas-20261019-1030-2.mbz"
        assert (carpeta / "pruebas-20261019-1030.mbz").read_bytes() == b"suyo"

    def test_el_temporal_no_pisa_otro_y_nace_en_la_carpeta_de_copias(self, tmp_path):
        uno = estado.temporal_de_copia(tmp_path / ".tiza")
        otro = estado.temporal_de_copia(tmp_path / ".tiza")
        assert uno != otro and uno.parent == tmp_path / ".tiza" / estado.CARPETA_COPIAS

    def test_al_reservar_un_temporal_borra_los_de_mas_de_un_dia(self, tmp_path):
        carpeta = tmp_path / ".tiza" / estado.CARPETA_COPIAS
        carpeta.mkdir(parents=True)
        viejo, reciente = carpeta / ".descarga-viejo.tmp", carpeta / ".descarga-reciente.tmp"
        copia, ajeno = carpeta / "pruebas-20260101-1000.mbz", carpeta / "notas.tmp"
        for ruta in (viejo, reciente, copia, ajeno):
            ruta.write_bytes(b"x")
        hace_dos_dias = time.time() - 2 * 24 * 3600
        for ruta in (viejo, copia, ajeno):
            os.utime(ruta, (hace_dos_dias, hace_dos_dias))
        nuevo = estado.temporal_de_copia(tmp_path / ".tiza")
        # Solo desaparece el temporal de una descarga vieja: nada de lo demás.
        assert not viejo.exists()
        assert reciente.exists() and copia.exists() and ajeno.exists() and nuevo.exists()

    def test_no_escribe_si_tiza_o_copias_son_enlaces(self, tmp_path):
        from dobles import enlace_simbolico
        from tiza.ficheros import FicheroNoSeguro

        fuera = tmp_path / "fuera"
        fuera.mkdir()
        enlace_simbolico(tmp_path / ".tiza", fuera)
        with pytest.raises(FicheroNoSeguro):
            estado.temporal_de_copia(tmp_path / ".tiza")
        assert list(fuera.iterdir()) == []
        otra = tmp_path / "otra"
        (otra / ".tiza").mkdir(parents=True)
        enlace_simbolico(otra / ".tiza" / estado.CARPETA_COPIAS, fuera)
        with pytest.raises(FicheroNoSeguro):
            estado.temporal_de_copia(otra / ".tiza")
        assert list(fuera.iterdir()) == []


class TestHuellasDelCalificador:
    """``.tiza/calificador.json``: la huella de cada nodo que montó tiza, por curso."""

    HUELLA = "a" * 64

    def test_sin_fichero_no_hay_huellas(self, tmp_path):
        assert estado.cargar_huellas(tmp_path, 7) == {}

    def test_guarda_y_lee_por_curso(self, tmp_path):
        ruta = estado.guardar_huellas(tmp_path / ".tiza", 7, {"TZ_TIZA": self.HUELLA})
        assert ruta == tmp_path / ".tiza" / "calificador.json"
        estado.guardar_huellas(tmp_path / ".tiza", 8, {"TZ_E_RA1": "b" * 64})
        assert estado.cargar_huellas(tmp_path / ".tiza", 7) == {"TZ_TIZA": self.HUELLA}
        assert estado.cargar_huellas(tmp_path / ".tiza", 8) == {"TZ_E_RA1": "b" * 64}
        assert estado.cargar_huellas(tmp_path / ".tiza", 9) == {}

    def test_guardar_reemplaza_las_del_curso(self, tmp_path):
        estado.guardar_huellas(tmp_path, 7, {"TZ_TIZA": self.HUELLA, "TZ_E_RA1": self.HUELLA})
        estado.guardar_huellas(tmp_path, 7, {"TZ_TIZA": "c" * 64})
        assert estado.cargar_huellas(tmp_path, 7) == {"TZ_TIZA": "c" * 64}

    def test_huellas_esquema_cerrado(self, tmp_path):
        (tmp_path / "calificador.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "cursos": {"7": {"nodos": {"TZ_TIZA": self.HUELLA}}},
                    "extra": 1,
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(estado.ErrorEstado) as error:
            estado.cargar_huellas(tmp_path, 7)
        assert error.value.codigo == "CALIFICADOR_INVALIDO"

    @pytest.mark.parametrize(
        "datos",
        [
            [],
            {"version": 2, "cursos": {}},
            {"version": 1},
            {"version": 1, "cursos": []},
            {"version": 1, "cursos": {"siete": {"nodos": {}}}},
            {"version": 1, "cursos": {"7": {"nodos": {}, "otro": 1}}},
            {"version": 1, "cursos": {"7": {}}},
            {"version": 1, "cursos": {"7": {"nodos": []}}},
            {"version": 1, "cursos": {"7": {"nodos": {"TZ_TIZA": "corta"}}}},
            {"version": 1, "cursos": {"7": {"nodos": {"TZ_TIZA": "A" * 64}}}},
            {"version": 1, "cursos": {"7": {"nodos": {"TZ_TIZA": 5}}}},
            {"version": 1, "cursos": {"7": {"nodos": {"": "a" * 64}}}},
            {"version": 1, "cursos": {"7": {"nodos": {"x\ny": "a" * 64}}}},
        ],
    )
    def test_fuera_del_esquema_es_invalido(self, tmp_path, datos):
        (tmp_path / "calificador.json").write_text(json.dumps(datos), encoding="utf-8")
        with pytest.raises(estado.ErrorEstado) as error:
            estado.cargar_huellas(tmp_path, 7)
        assert error.value.codigo == "CALIFICADOR_INVALIDO"

    CLAVES_PELIGROSAS = [
        "TZ_A1\u202eevil",  # bidi
        "TZ_A1\u200b",  # invisible de ancho cero
        "TZ_A1\u2066",  # aislamiento bidi
        "TZ A1",  # espacio
        "EX\u00f1",  # letra no ASCII
        "TZ_A1\ufeff",
        "a" * 101,
        "",
    ]

    @pytest.mark.parametrize("clave", CLAVES_PELIGROSAS)
    def test_una_clave_con_bidi_o_invisibles_es_invalida_al_leer(self, tmp_path, clave):
        datos = {"version": 1, "cursos": {"7": {"nodos": {clave: self.HUELLA}}}}
        (tmp_path / "calificador.json").write_text(json.dumps(datos), encoding="utf-8")
        with pytest.raises(estado.ErrorEstado) as error:
            estado.cargar_huellas(tmp_path, 7)
        assert error.value.codigo == "CALIFICADOR_INVALIDO"

    def test_las_claves_peligrosas_no_se_guardan_y_las_demas_si(self, tmp_path):
        buenas = {"TZ_TIZA": self.HUELLA, "EX1": self.HUELLA, "a.b:c-d_9": self.HUELLA}
        malas = {clave: self.HUELLA for clave in self.CLAVES_PELIGROSAS}
        estado.guardar_huellas(tmp_path, 7, {**buenas, **malas})
        assert estado.cargar_huellas(tmp_path, 7) == buenas
        texto = (tmp_path / "calificador.json").read_text(encoding="utf-8")
        assert not any(c in texto for c in "\u202e\u200b\u2066\ufeff")

    def test_clave_de_huella_valida(self):
        assert estado.clave_de_huella_valida("TZ_E_RA1")
        assert estado.clave_de_huella_valida("EX-1.2:3")
        assert not estado.clave_de_huella_valida("TZ\u202e")
        assert not estado.clave_de_huella_valida("")

    def test_no_json_es_invalido(self, tmp_path):
        (tmp_path / "calificador.json").write_text("{no es json", encoding="utf-8")
        with pytest.raises(estado.ErrorEstado) as error:
            estado.cargar_huellas(tmp_path, 7)
        assert error.value.codigo == "CALIFICADOR_INVALIDO"

    def test_no_se_guarda_lo_invalido(self, tmp_path):
        with pytest.raises(estado.ErrorEstado) as error:
            estado.guardar_huellas(tmp_path, 7, {"TZ_TIZA": "no es un sha256"})
        assert error.value.codigo == "CALIFICADOR_INVALIDO"
        assert not (tmp_path / "calificador.json").exists()

    def test_un_directorio_no_es_el_fichero(self, tmp_path):
        (tmp_path / "calificador.json").mkdir()
        with pytest.raises(estado.ErrorEstado) as error:
            estado.cargar_huellas(tmp_path, 7)
        assert error.value.codigo == "CALIFICADOR_INVALIDO"


H = "a" * 64
M = "b" * 64


def _valor(**cambios):
    """Una entrada válida de ``publicados.json`` con los cambios dados."""
    base = {"cmid": 5, "tipo": "pagina", "huella": H, "marca": None}
    base.update(cambios)
    return base


def _doc(valor=None, ruta="a.md", curso="7"):
    """Un ``publicados.json`` de versión 1 con una sola entrada."""
    valor = _valor() if valor is None else valor
    return {"version": 1, "cursos": {curso: {"ficheros": {ruta: valor}}}}


class TestPublicados:
    """``.tiza/publicados.json``: qué actividad del aula corresponde a cada fichero, por curso."""

    def test_ida_y_vuelta_en_publicados_json(self, tmp_path):
        dir_tiza = tmp_path / ".tiza"
        publicado = estado.Publicado(cmid=812, tipo="pagina", huella=H, marca=M)
        ruta = estado.guardar_publicado(dir_tiza, 7, "aula/u2/guia.html", publicado)
        assert ruta == dir_tiza / "publicados.json"
        assert estado.cargar_publicados(dir_tiza, 7) == {"aula/u2/guia.html": publicado}

    def test_sin_fichero_o_sin_curso_es_un_mapa_vacio(self, tmp_path):
        assert estado.cargar_publicados(tmp_path, 7) == {}
        estado.guardar_publicado(tmp_path, 8, "a.md", estado.Publicado(cmid=1, tipo="pagina"))
        assert estado.cargar_publicados(tmp_path, 7) == {}

    def test_cada_curso_guarda_lo_suyo(self, tmp_path):
        uno = estado.Publicado(cmid=1, tipo="pagina")
        otro = estado.Publicado(cmid=2, tipo="tarea")
        estado.guardar_publicado(tmp_path, 7, "a.md", uno)
        estado.guardar_publicado(tmp_path, 8, "b.md", otro)
        assert estado.cargar_publicados(tmp_path, 7) == {"a.md": uno}
        assert estado.cargar_publicados(tmp_path, 8) == {"b.md": otro}

    def test_la_misma_ruta_se_sustituye(self, tmp_path):
        estado.guardar_publicado(tmp_path, 7, "a.md", estado.Publicado(cmid=1, tipo="pagina"))
        nueva = estado.Publicado(cmid=1, tipo="pagina", marca=M)
        estado.guardar_publicado(tmp_path, 7, "a.md", nueva)
        assert estado.cargar_publicados(tmp_path, 7) == {"a.md": nueva}

    def test_mismo_cmid_en_otra_ruta_del_curso_quita_la_vieja(self, tmp_path):
        vieja = estado.Publicado(cmid=5, tipo="pagina")
        estado.guardar_publicado(tmp_path, 7, "viejo.md", vieja)
        estado.guardar_publicado(tmp_path, 8, "viejo.md", vieja)
        nuevo = estado.Publicado(cmid=5, tipo="pagina")
        estado.guardar_publicado(tmp_path, 7, "nuevo.md", nuevo)
        assert estado.cargar_publicados(tmp_path, 7) == {"nuevo.md": nuevo}
        assert estado.cargar_publicados(tmp_path, 8) == {"viejo.md": vieja}

    def test_olvidar_quita_la_entrada_y_el_curso_vacio(self, tmp_path):
        estado.guardar_publicado(tmp_path, 7, "a.md", estado.Publicado(cmid=1, tipo="pagina"))
        estado.guardar_publicado(tmp_path, 7, "b.md", estado.Publicado(cmid=2, tipo="tarea"))
        assert estado.olvidar_publicado(tmp_path, 7, "a.md") is True
        assert list(estado.cargar_publicados(tmp_path, 7)) == ["b.md"]
        assert estado.olvidar_publicado(tmp_path, 7, "a.md") is False
        assert estado.olvidar_publicado(tmp_path, 7, "b.md") is True
        assert estado.cargar_publicados(tmp_path, 7) == {}
        datos = json.loads((tmp_path / "publicados.json").read_text(encoding="utf-8"))
        assert datos == {"version": 1, "cursos": {}}

    def test_olvidar_lo_que_no_estaba_no_escribe_nada(self, tmp_path):
        assert estado.olvidar_publicado(tmp_path, 7, "a.md") is False
        assert not (tmp_path / "publicados.json").exists()
        estado.guardar_publicado(tmp_path, 7, "a.md", estado.Publicado(cmid=1, tipo="pagina"))
        antes = (tmp_path / "publicados.json").read_text(encoding="utf-8")
        assert estado.olvidar_publicado(tmp_path, 7, "otro.md") is False
        assert (tmp_path / "publicados.json").read_text(encoding="utf-8") == antes

    def test_publicados_de_fichero_reune_los_cursos_que_lo_tienen(self, tmp_path):
        uno = estado.Publicado(cmid=1, tipo="pagina", huella=H)
        otro = estado.Publicado(cmid=9, tipo="pagina")
        estado.guardar_publicado(tmp_path, 7, "aula/a.md", uno)
        estado.guardar_publicado(tmp_path, 8, "aula/a.md", otro)
        estado.guardar_publicado(tmp_path, 8, "aula/b.md", estado.Publicado(cmid=2, tipo="tarea"))
        assert estado.publicados_de_fichero(tmp_path, "aula/a.md") == {7: uno, 8: otro}
        assert estado.publicados_de_fichero(tmp_path, "aula/b.md") == {
            8: estado.Publicado(cmid=2, tipo="tarea")
        }

    def test_publicados_de_fichero_sin_la_ruta_o_sin_fichero_es_vacio(self, tmp_path):
        assert estado.publicados_de_fichero(tmp_path, "a.md") == {}
        estado.guardar_publicado(tmp_path, 7, "a.md", estado.Publicado(cmid=1, tipo="pagina"))
        assert estado.publicados_de_fichero(tmp_path, "otro.md") == {}
        assert estado.publicados_de_fichero(tmp_path, "../a.md") == {}

    def test_publicados_de_fichero_valida_como_cargar_publicados(self, tmp_path):
        (tmp_path / "publicados.json").write_text('{"version": 2, "cursos": {}}', encoding="utf-8")
        with pytest.raises(estado.ErrorEstado) as error:
            estado.publicados_de_fichero(tmp_path, "a.md")
        assert error.value.codigo == "PUBLICADOS_INVALIDO"

    def test_fichero_de_cmid(self, tmp_path):
        estado.guardar_publicado(tmp_path, 7, "a.md", estado.Publicado(cmid=5, tipo="pagina"))
        assert estado.fichero_de_cmid(tmp_path, 7, 5) == "a.md"
        assert estado.fichero_de_cmid(tmp_path, 7, 6) is None
        assert estado.fichero_de_cmid(tmp_path, 8, 5) is None

    def test_publicado_es_inmutable(self):
        publicado = estado.Publicado(cmid=1, tipo="pagina")
        with pytest.raises(AttributeError):
            publicado.cmid = 2

    def test_guardar_con_ruta_invalida_no_escribe_nada(self, tmp_path):
        publicado = estado.Publicado(cmid=1, tipo="pagina")
        with pytest.raises(estado.ErrorEstado) as error:
            estado.guardar_publicado(tmp_path, 7, "../fuera.md", publicado)
        assert error.value.codigo == "PUBLICADOS_INVALIDO"
        assert not (tmp_path / "publicados.json").exists()

    @pytest.mark.parametrize(
        "cambios",
        [
            {"cmid": 0},
            {"cmid": True},
            {"tipo": "Pagina"},
            {"huella": "xyz"},
        ],
    )
    def test_guardar_no_escribe_lo_que_no_case(self, tmp_path, cambios):
        base = {"cmid": 1, "tipo": "pagina"}
        publicado = estado.Publicado(**{**base, **cambios})
        with pytest.raises(estado.ErrorEstado) as error:
            estado.guardar_publicado(tmp_path, 7, "a.md", publicado)
        assert error.value.codigo == "PUBLICADOS_INVALIDO"
        assert not (tmp_path / "publicados.json").exists()

    def test_guardar_no_pisa_un_fichero_invalido(self, tmp_path):
        (tmp_path / "publicados.json").write_text("{no es json", encoding="utf-8")
        with pytest.raises(estado.ErrorEstado) as error:
            estado.guardar_publicado(tmp_path, 7, "a.md", estado.Publicado(cmid=1, tipo="pagina"))
        assert error.value.codigo == "PUBLICADOS_INVALIDO"
        assert (tmp_path / "publicados.json").read_text(encoding="utf-8") == "{no es json"

    def test_ruta_publicada_valida(self):
        for ruta in ["aula/u2/guia.html", "a.md", "a" * 1024]:
            assert estado.ruta_publicada_valida(ruta), ruta
        for ruta in [
            "",
            "/a",
            "a//b",
            "./a",
            "a/../b",
            "a/",
            "a\\b",
            "a\u202eb",
            "a\u200bb",
            "a\x07b",
            "a" * 1025,
        ]:
            assert not estado.ruta_publicada_valida(ruta), repr(ruta)
        assert not estado.ruta_publicada_valida(None)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "datos",
        [
            pytest.param({"version": 1, "cursos": {}, "extra": 1}, id="clave_de_mas_en_la_raiz"),
            pytest.param({"version": 2, "cursos": {}}, id="version_2"),
            pytest.param({"version": True, "cursos": {}}, id="version_bool"),
            pytest.param({"version": 1, "cursos": {"siete": {"ficheros": {}}}}, id="curso_str"),
            pytest.param(
                {"version": 1, "cursos": {"7": {"ficheros": {}, "otro": 1}}}, id="curso_extra"
            ),
            pytest.param(_doc(_valor(cmid=0)), id="cmid_cero"),
            pytest.param(_doc(_valor(cmid=-3)), id="cmid_negativo"),
            pytest.param(_doc(_valor(cmid=True)), id="cmid_bool"),
            pytest.param(_doc(_valor(cmid="5")), id="cmid_str"),
            pytest.param(_doc(_valor(tipo="Pagina")), id="tipo_con_mayusculas"),
            pytest.param(_doc(_valor(huella="g" * 64)), id="huella_no_hex"),
            pytest.param(_doc(_valor(marca="corta")), id="marca_corta"),
            pytest.param(_doc(_valor(extra=1)), id="clave_de_mas_en_una_entrada"),
            pytest.param(
                {"version": 1, "cursos": {"7": {"ficheros": {"a.md": _valor(), "b.md": _valor()}}}},
                id="dos_rutas_con_el_mismo_cmid",
            ),
            pytest.param(_doc(ruta="/a.md"), id="ruta_absoluta"),
            pytest.param(_doc(ruta="a/../b.md"), id="ruta_con_punto_punto"),
            pytest.param(_doc(ruta="a\\b.md"), id="ruta_con_barra_invertida"),
        ],
    )
    def test_fuera_del_esquema_es_invalido(self, tmp_path, datos):
        (tmp_path / "publicados.json").write_text(json.dumps(datos), encoding="utf-8")
        with pytest.raises(estado.ErrorEstado) as error:
            estado.cargar_publicados(tmp_path, 7)
        assert error.value.codigo == "PUBLICADOS_INVALIDO"

    def test_json_roto_es_invalido(self, tmp_path):
        (tmp_path / "publicados.json").write_text("{no es json", encoding="utf-8")
        with pytest.raises(estado.ErrorEstado) as error:
            estado.cargar_publicados(tmp_path, 7)
        assert error.value.codigo == "PUBLICADOS_INVALIDO"

    def test_un_directorio_no_es_el_fichero(self, tmp_path):
        (tmp_path / "publicados.json").mkdir()
        with pytest.raises(estado.ErrorEstado) as error:
            estado.cargar_publicados(tmp_path, 7)
        assert error.value.codigo == "PUBLICADOS_INVALIDO"

    def test_un_enlace_no_es_el_fichero(self, tmp_path):
        from dobles import enlace_simbolico

        destino = tmp_path / "otro.json"
        destino.write_text(json.dumps(_doc()), encoding="utf-8")
        enlace_simbolico(tmp_path / "publicados.json", destino)
        with pytest.raises(estado.ErrorEstado) as error:
            estado.cargar_publicados(tmp_path, 7)
        assert error.value.codigo == "PUBLICADOS_INVALIDO"
