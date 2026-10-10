"""Contrato del registro de tipos: un adapter por tipo y todos cumplen la interfaz.

Es el test que hace real el *seam* del issue #4: si un tipo nuevo no declara lo que
todos declaran, o si dos tipos se pisan un campo, se ve aquí y no en seis módulos.
"""

from __future__ import annotations

import pytest

from tiza import contenido, tipos
from tiza.tipos import BANDERA_DE_MODO, CAMPO_RECORDATORIO

# Un documento mínimo válido por tipo, para poder llamar a lo que depende del documento.
EJEMPLOS = {
    "pagina": "---\ntipo: pagina\nnombre: P\nseccion: 1\n---\n\nx\n",
    "tarea": (
        "---\ntipo: tarea\nnombre: T\nseccion: 1\n"
        "apertura: 2026-10-01\nentrega: 2026-10-10\n---\n\nx\n"
    ),
    "cuestionario": (
        "---\ntipo: cuestionario\nnombre: C\nseccion: 1\npreguntas:\n"
        "  - tipo: verdadero_falso\n    enunciado: x\n    respuesta: verdadero\n---\n\nx\n"
    ),
    "etiqueta": "---\ntipo: etiqueta\nnombre: E\nseccion: 1\n---\n\nx\n",
    "h5p": (
        "---\ntipo: h5p\nnombre: H\nseccion: 1\nactividad:\n"
        "  tipo: rellenar_huecos\n  textos:\n"
        '    - "Uno [[1]] y dos [[2]]."\n---\n\nx\n'
    ),
}


@pytest.fixture
def cargar(tmp_path):
    def _cargar(nombre: str) -> contenido.Documento:
        ruta = tmp_path / f"{nombre}.md"
        ruta.write_text(EJEMPLOS[nombre], encoding="utf-8")
        return contenido.cargar(ruta, raiz=tmp_path)

    return _cargar


class TestRegistro:
    def test_el_orden_canonico_no_cambia(self):
        assert tipos.TIPOS == ("pagina", "tarea", "cuestionario", "etiqueta", "h5p")
        assert tipos.TIPOS == contenido.TTIPOS

    def test_nombres_y_modulos_unicos_y_localizables(self):
        nombres = [tipo.nombre for tipo in tipos.TODOS]
        modulos = [tipo.modulo for tipo in tipos.TODOS]
        assert len(set(nombres)) == len(nombres)
        assert len(set(modulos)) == len(modulos)
        for tipo in tipos.TODOS:
            assert tipos.obtener(tipo.nombre) is tipo
            assert tipos.de_modulo(tipo.modulo) == tipo.nombre
        assert tipos.de_modulo("forum") is None

    def test_todos_declaran_nombre_llano_y_modulo(self):
        for tipo in tipos.TODOS:
            assert tipo.llano and tipo.llano == tipo.llano.strip()
            assert tipo.modulo and "/" not in tipo.modulo

    def test_los_campos_propios_no_invaden_los_comunes(self):
        for tipo in tipos.TODOS:
            assert not {"tipo", "nombre", "seccion"} & set(tipo.campos)
        con_campos = {tipo.nombre for tipo in tipos.TODOS if tipo.campos}
        assert con_campos == {"tarea", "cuestionario", "h5p"}

    def test_las_banderas_de_finalizacion_casan_con_los_modos(self):
        for tipo in tipos.TODOS:
            assert "ninguna" in tipo.finalizaciones and "manual" in tipo.finalizaciones
            for modo, bandera in BANDERA_DE_MODO.items():
                assert (bandera in tipo.banderas) == (modo in tipo.finalizaciones), (
                    tipo.nombre,
                    modo,
                )
            assert set(tipo.banderas) <= set(BANDERA_DE_MODO.values())


class TestValidacion:
    def test_cada_tipo_rellena_sus_extras_y_solo_los_suyos(self, cargar):
        esperado = {
            "pagina": (False, False, False, False),
            "etiqueta": (False, False, False, False),
            "tarea": (True, False, False, False),
            "cuestionario": (False, True, False, False),
            "h5p": (False, False, True, False),
        }
        for tipo in tipos.TODOS:
            doc = cargar(tipo.nombre)
            tenidos = (
                doc.fechas is not None,
                doc.cuestionario is not None,
                doc.h5p is not None,
                doc.paquete is not None,
            )
            assert tenidos == esperado[tipo.nombre], tipo.nombre

    def test_un_paquete_subido_llega_sin_actividad(self, tmp_path):
        import json
        import zipfile

        h5p_json = {
            "mainLibrary": "H5P.Blanks",
            "preloadedDependencies": [
                {"machineName": "H5P.Blanks", "majorVersion": 1, "minorVersion": 14}
            ],
            "embedTypes": ["iframe"],
        }
        with zipfile.ZipFile(tmp_path / "paquete.h5p", "w") as paquete:
            paquete.writestr("h5p.json", json.dumps(h5p_json))
            paquete.writestr("content/content.json", json.dumps({"questions": []}))
        ruta = tmp_path / "h.md"
        ruta.write_text(
            "---\ntipo: h5p\nnombre: H\nseccion: 1\npaquete: paquete.h5p\n---\n\nx\n",
            encoding="utf-8",
        )
        doc = contenido.cargar(ruta, raiz=tmp_path)
        assert doc.h5p is None
        assert doc.paquete is not None and doc.paquete.machine_name == "H5P.Blanks"

    def test_la_validacion_sigue_siendo_la_de_siempre(self, tmp_path):
        """Los códigos estables no cambian al mudarse al adapter."""
        casos = {
            "CAMPO_FALTANTE": "---\ntipo: tarea\nnombre: T\nseccion: 1\n---\n\nx\n",
            "FECHAS_INCOHERENTES": (
                "---\ntipo: tarea\nnombre: T\nseccion: 1\n"
                "apertura: 2026-10-10\nentrega: 2026-10-01\n---\n\nx\n"
            ),
            "ACTIVIDAD_H5P_INVALIDA": (
                "---\ntipo: h5p\nnombre: H\nseccion: 1\nactividad:\n"
                '  tipo: rellenar_huecos\n  textos:\n    - "sin huecos"\n---\n\nx\n'
            ),
            "PREGUNTAS_INVALIDAS": (
                "---\ntipo: cuestionario\nnombre: C\nseccion: 1\npreguntas: []\n---\n\nx\n"
            ),
        }
        ruta = tmp_path / "caso.md"
        for codigo, contenido_md in casos.items():
            ruta.write_text(contenido_md, encoding="utf-8")
            with pytest.raises(contenido.ErrorContenido) as exc:
                contenido.cargar(ruta)
            assert exc.value.codigo == codigo, codigo


class TestFechas:
    def test_cada_tipo_declara_sus_campos_de_fecha_en_orden(self, cargar):
        for tipo in tipos.TODOS:
            fechas = tipo.fechas(cargar(tipo.nombre))
            assert [fecha.campo_moodle for fecha in fechas] == list(tipo.campos_fecha)
            assert len({fecha.campo for fecha in fechas}) == len(fechas)

    def test_una_tarea_ve_sus_cuatro_campos_y_un_cuestionario_dos(self, cargar):
        tarea = tipos.obtener("tarea")
        assert [fecha.campo for fecha in tarea.fechas(cargar("tarea"))] == [
            "apertura",
            "entrega",
            "límite",
            CAMPO_RECORDATORIO,
        ]
        cuestionario = tipos.obtener("cuestionario")
        assert [fecha.campo for fecha in cuestionario.fechas(cargar("cuestionario"))] == [
            "apertura",
            "cierre",
        ]

    def test_los_tipos_sin_fechas_no_tienen_campos_de_fecha(self, cargar):
        for nombre in ("pagina", "etiqueta", "h5p"):
            tipo = tipos.obtener(nombre)
            assert tipo.campos_fecha == ()
            assert tipo.fechas(cargar(nombre)) == ()

    def test_una_fecha_sin_poner_se_desactiva_en_el_payload(self, cargar):
        cuestionario = tipos.obtener("cuestionario")
        assert tipos.fechas_payload(cuestionario, cargar("cuestionario")) == {
            "timeopen[enabled]": "0",
            "timeclose[enabled]": "0",
        }
        tarea = tipos.obtener("tarea")
        payload = tipos.fechas_payload(tarea, cargar("tarea"))
        assert payload["duedate[day]"] == "10"
        assert payload["cutoffdate[enabled]"] == "0"
        assert payload["gradingduedate[enabled]"] == "0"

    def test_solo_tarea_y_cuestionario_admiten_cambiar_solo_fechas(self, cargar):
        for tipo in tipos.TODOS:
            doc = cargar(tipo.nombre)
            payload = tipo.payload_solo_fechas(doc)
            if tipo.nombre in ("tarea", "cuestionario"):
                assert payload is not None
                for campo in tipo.campos_fecha:
                    assert any(clave.startswith(f"{campo}[") for clave in payload)
            else:
                assert payload is None
