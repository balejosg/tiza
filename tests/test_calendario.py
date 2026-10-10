"""Tests del calendario escolar (tiza.calendario): lectura, validación y avisos, sin red."""

from __future__ import annotations

from datetime import date

import pytest

from dobles import enlace_simbolico
from tiza import calendario, contenido

COMPLETO = """\
inicio = 2026-09-08
fin = 2027-06-22
dias_de_clase = ["lunes", "miércoles", "viernes"]
festivos = [
  2026-10-12,
  {desde = 2026-12-21, hasta = 2027-01-07, motivo = "Navidad"},
]
"""


def escribir(carpeta, texto: str) -> None:
    (carpeta / "calendario.toml").write_text(texto, encoding="utf-8")


class TestCargar:
    def test_sin_fichero_no_hay_calendario(self, tmp_path):
        assert calendario.cargar(tmp_path) is None

    def test_lee_el_curso_los_festivos_y_los_dias_de_clase(self, tmp_path):
        escribir(tmp_path, COMPLETO)
        cal = calendario.cargar(tmp_path)
        assert cal.inicio == date(2026, 9, 8)
        assert cal.fin == date(2027, 6, 22)
        assert cal.festivos == (
            (date(2026, 10, 12), date(2026, 10, 12)),
            (date(2026, 12, 21), date(2027, 1, 7)),
        )
        assert cal.dias_de_clase == frozenset({0, 2, 4})

    def test_acepta_los_dias_sin_tilde_y_en_mayusculas(self, tmp_path):
        escribir(tmp_path, 'dias_de_clase = ["Miercoles", "SÁBADO"]\n')
        assert calendario.cargar(tmp_path).dias_de_clase == frozenset({2, 5})

    def test_un_calendario_vacio_es_valido_y_no_avisa(self, tmp_path):
        escribir(tmp_path, "")
        cal = calendario.cargar(tmp_path)
        assert cal == calendario.Calendario()

    @pytest.mark.parametrize(
        "texto",
        [
            'color = "rojo"\n',  # campo desconocido
            'inicio = "2026-09-08"\n',  # texto en vez de fecha
            "inicio = 2026-09-08T10:00:00\n",  # fecha con hora: no vale
            "inicio = 2026-10-01\nfin = 2026-09-01\n",  # al revés
            'festivos = "2026-10-12"\n',  # no es una lista
            "festivos = [{desde = 2026-10-12}]\n",  # rango sin hasta
            "festivos = [{desde = 2026-10-12, hasta = 2026-10-10}]\n",  # rango al revés
            'festivos = [{desde = 2026-10-12, hasta = 2026-10-12, color = "x"}]\n',
            'festivos = [{desde = 2026-10-12, hasta = 2026-10-12, motivo = "a\\u0007"}]\n',
            "festivos = [42]\n",
            "dias_de_clase = []\n",  # lista vacía: ¿ningún día?
            'dias_de_clase = ["domingoo"]\n',
            "dias_de_clase = [1]\n",
            "inicio = \n",  # TOML mal formado
        ],
    )
    def test_rechaza_un_calendario_invalido(self, tmp_path, texto):
        escribir(tmp_path, texto)
        with pytest.raises(calendario.ErrorCalendario) as exc:
            calendario.cargar(tmp_path)
        assert exc.value.codigo == "CALENDARIO_INVALIDO"

    def test_rechaza_un_fichero_que_no_es_utf8(self, tmp_path):
        (tmp_path / "calendario.toml").write_bytes(b"\xff\xfe inicio = 2026-09-08\n")
        with pytest.raises(calendario.ErrorCalendario) as exc:
            calendario.cargar(tmp_path)
        assert exc.value.codigo == "CALENDARIO_INVALIDO"

    @pytest.mark.parametrize(
        "texto",
        [
            pytest.param("festivos = " + "[" * 5000 + "]" * 5000 + "\n", id="listas-anidadas"),
            pytest.param(
                "festivos = [" + "{a=" * 3000 + "1" + "}" * 3000 + "]\n", id="tablas-anidadas"
            ),
            pytest.param("inicio = " + "9" * 5000 + "\n", id="entero-enorme"),
        ],
    )
    def test_un_toml_hostil_se_rechaza_sin_romper(self, tmp_path, texto):
        # Lo escribe el agente: ni la pila ni un entero de miles de cifras pueden tumbar la sesión.
        escribir(tmp_path, texto)
        with pytest.raises(calendario.ErrorCalendario) as exc:
            calendario.cargar(tmp_path)
        assert exc.value.codigo == "CALENDARIO_INVALIDO"

    def test_rechaza_un_fichero_demasiado_grande(self, tmp_path):
        escribir(tmp_path, "# " + "x" * calendario.MAX_BYTES + "\n")
        with pytest.raises(calendario.ErrorCalendario) as exc:
            calendario.cargar(tmp_path)
        assert exc.value.codigo == "CALENDARIO_INVALIDO"
        assert "64 KB" in exc.value.detalle

    def test_no_sigue_un_enlace_simbolico(self, tmp_path):
        destino = tmp_path / "fuera.toml"
        destino.write_text(COMPLETO, encoding="utf-8")
        enlace_simbolico(tmp_path / "calendario.toml", destino)
        with pytest.raises(calendario.ErrorCalendario) as exc:
            calendario.cargar(tmp_path)
        assert exc.value.codigo == "CALENDARIO_INVALIDO"
        assert "enlace" in exc.value.detalle

    def test_un_enlace_roto_tambien_cuenta_como_calendario(self, tmp_path):
        enlace_simbolico(tmp_path / "calendario.toml", tmp_path / "no_existe.toml")
        with pytest.raises(calendario.ErrorCalendario):
            calendario.cargar(tmp_path)

    def test_el_detalle_no_repite_marcas_del_fichero(self, tmp_path):
        escribir(tmp_path, 'dias_de_clase = ["<script>"]\n')
        with pytest.raises(calendario.ErrorCalendario) as exc:
            calendario.cargar(tmp_path)
        assert "<" not in exc.value.detalle and ">" not in exc.value.detalle

    def test_demasiados_festivos(self, tmp_path):
        entradas = ", ".join("2026-10-12" for _ in range(calendario.MAX_FESTIVOS + 1))
        escribir(tmp_path, f"festivos = [{entradas}]\n")
        with pytest.raises(calendario.ErrorCalendario):
            calendario.cargar(tmp_path)

    def test_el_motivo_no_puede_llevar_caracteres_de_control(self, tmp_path):
        escribir(
            tmp_path,
            'festivos = [{desde = 2026-10-12, hasta = 2026-10-12, motivo = "a\\u202eb"}]\n',
        )
        with pytest.raises(calendario.ErrorCalendario):
            calendario.cargar(tmp_path)


class TestAvisos:
    def cal(self, tmp_path) -> calendario.Calendario:
        escribir(tmp_path, COMPLETO)
        return calendario.cargar(tmp_path)

    def test_sin_calendario_no_hay_avisos(self):
        assert calendario.avisos(None, date(2026, 10, 10), clase=True) == ()

    def test_un_festivo_avisa(self, tmp_path):
        assert calendario.avisos(self.cal(tmp_path), date(2026, 10, 12), clase=False) == (
            "FECHA_FESTIVA",
        )

    def test_un_rango_festivo_avisa_en_todos_sus_dias(self, tmp_path):
        cal = self.cal(tmp_path)
        assert calendario.avisos(cal, date(2027, 1, 7), clase=False) == ("FECHA_FESTIVA",)
        assert calendario.avisos(cal, date(2027, 1, 8), clase=False) == ()

    def test_el_fin_de_semana_avisa_aunque_no_haya_dias_de_clase(self):
        cal = calendario.Calendario()
        assert calendario.avisos(cal, date(2026, 10, 10), clase=False) == ("FECHA_FIN_DE_SEMANA",)

    def test_fuera_del_curso_avisa(self, tmp_path):
        assert calendario.avisos(self.cal(tmp_path), date(2026, 9, 1), clase=False) == (
            "FECHA_FUERA_DE_CURSO",
        )

    def test_sin_clase_solo_si_se_pide_y_hay_dias_de_clase(self, tmp_path):
        cal = self.cal(tmp_path)  # lunes, miércoles y viernes
        martes = date(2026, 10, 13)
        assert calendario.avisos(cal, martes, clase=True) == ("FECHA_SIN_CLASE",)
        assert calendario.avisos(cal, martes, clase=False) == ()
        assert calendario.avisos(cal, date(2026, 10, 14), clase=True) == ()  # miércoles

    def test_los_avisos_salen_en_un_orden_fijo(self, tmp_path):
        escribir(
            tmp_path, 'inicio = 2026-10-01\nfestivos = [2026-10-10]\ndias_de_clase = ["lunes"]\n'
        )
        cal = calendario.cargar(tmp_path)
        assert calendario.avisos(cal, date(2026, 10, 10), clase=True) == (
            "FECHA_FESTIVA",
            "FECHA_FIN_DE_SEMANA",
            "FECHA_SIN_CLASE",
        )


class TestFechasDelDocumento:
    def test_una_tarea_revisa_apertura_entrega_y_limite(self, tmp_path):
        ruta = tmp_path / "t.md"
        ruta.write_text(
            "---\ntipo: tarea\nnombre: T\nseccion: 1\n"
            "apertura: 2026-10-01\nentrega: 2026-10-10\nlimite: 2026-10-15\n---\n\nx\n",
            encoding="utf-8",
        )
        doc = contenido.cargar(ruta)
        assert calendario.fechas_del_documento(doc) == (
            ("apertura", date(2026, 10, 1), False),
            ("entrega", date(2026, 10, 10), True),
            ("límite", date(2026, 10, 15), False),
        )

    def test_un_cuestionario_revisa_apertura_y_cierre(self, tmp_path):
        ruta = tmp_path / "c.md"
        ruta.write_text(
            "---\ntipo: cuestionario\nnombre: C\nseccion: 1\n"
            "apertura: 2026-10-01\ncierre: 2026-10-10\n"
            "preguntas:\n  - tipo: verdadero_falso\n    enunciado: x\n    respuesta: verdadero\n"
            "---\n\nx\n",
            encoding="utf-8",
        )
        doc = contenido.cargar(ruta)
        assert calendario.fechas_del_documento(doc) == (
            ("apertura", date(2026, 10, 1), False),
            ("cierre", date(2026, 10, 10), True),
        )

    def test_una_pagina_no_tiene_fechas(self, tmp_path):
        ruta = tmp_path / "p.md"
        ruta.write_text("---\ntipo: pagina\nnombre: P\nseccion: 1\n---\n\nx\n", encoding="utf-8")
        assert calendario.fechas_del_documento(contenido.cargar(ruta)) == ()
