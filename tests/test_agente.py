"""Tests de la API para agentes embebidos (tiza.agente)."""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime, timedelta

from dobles import enlace_simbolico
from tiza import agente, buzon, contenido, informe, publicar

PAGINA = "---\ntipo: pagina\nnombre: Repaso\nseccion: 3\n---\n\n## Repaso\n\nContenido.\n"
CUESTIONARIO = (
    "---\ntipo: cuestionario\nnombre: Repaso\nseccion: 3\n"
    "preguntas:\n"
    "  - tipo: verdadero_falso\n"
    "    enunciado: El agua hierve a 100 °C.\n"
    "    respuesta: verdadero\n"
    "---\n\nDescripción.\n"
)
ESTRUCTURA = {
    "version": 1,
    "generado": "2026-10-03T10:00:00+00:00",
    "cursos": {
        "pruebas": {"id": 1234, "secciones": [{"numero": 3, "nombre": "Tema 3", "id": 30}]},
    },
}


def escribir(carpeta, nombre, texto):
    (carpeta / nombre).write_text(texto, encoding="utf-8")


class TestComprobar:
    def test_pasa_sin_red_y_devuelve_la_vista_previa(self, tmp_path, capsys):
        escribir(tmp_path, "p.md", PAGINA)
        publicar.escribir_estructura(tmp_path / ".tiza", ESTRUCTURA)
        resultado = agente.comprobar(tmp_path, ["p.md"])
        assert resultado.informe["resultado"] == "ok"
        informe.validar(resultado.informe)
        [fichero] = resultado.ficheros
        assert fichero.codigo is None
        assert fichero.vista_previa is not None and fichero.vista_previa.is_file()
        assert capsys.readouterr() == ("", "")

    def test_explica_cada_fichero_sin_imprimir(self, tmp_path, capsys):
        escribir(tmp_path, "roto.md", "---\ntipo: pagina\nnombre: P\n---\n\nx\n")
        escribir(tmp_path, "id.md", PAGINA.replace("seccion: 3", "seccion: 30"))
        escribir(tmp_path, "bien.md", PAGINA)
        publicar.escribir_estructura(tmp_path / ".tiza", ESTRUCTURA)
        resultado = agente.comprobar(tmp_path, ["roto.md", "id.md", "bien.md"])
        roto, por_id, bien = resultado.ficheros
        assert (roto.fichero, roto.codigo) == ("roto.md", "CAMPO_FALTANTE")
        assert "seccion" in roto.detalle
        assert por_id.codigo == "SECCION_ES_ID"
        assert "escribe «seccion: 3»" in por_id.detalle
        assert bien.codigo is None
        assert resultado.informe["errores"] == ["CAMPO_FALTANTE", "SECCION_ES_ID"]
        assert capsys.readouterr() == ("", "")

    def test_seccion_por_nombre_que_falta_se_creara(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA.replace("seccion: 3", 'seccion: "Fracciones"'))
        publicar.escribir_estructura(tmp_path / ".tiza", ESTRUCTURA)
        [fichero] = agente.comprobar(tmp_path, ["p.md"]).ficheros
        assert fichero.codigo is None
        assert fichero.seccion_nueva == "Fracciones"

    def test_una_carpeta_preview_enlazada_da_codigo_y_no_escribe_fuera(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA)
        publicar.escribir_estructura(tmp_path / ".tiza", ESTRUCTURA)
        fuera = tmp_path / "fuera"
        fuera.mkdir()
        enlace_simbolico(tmp_path / ".tiza" / "preview", fuera)
        resultado = agente.comprobar(tmp_path, ["p.md"])
        [fichero] = resultado.ficheros
        assert fichero.codigo == "DIRECTORIO_NO_SEGURO"
        assert resultado.informe["errores"] == ["DIRECTORIO_NO_SEGURO"]
        assert list(fuera.iterdir()) == []

    def test_un_recurso_oculto_o_de_fuera_se_rechaza_como_en_la_sesion(self, tmp_path):
        carpeta = tmp_path / "asig"
        (carpeta / ".git").mkdir(parents=True)
        (carpeta / ".git" / "config").write_text("url = x", encoding="utf-8")
        (tmp_path / "secreto.xlsx").write_bytes(b"x")
        escribir(carpeta, "oculto.md", PAGINA + "\n[c](.git/config)\n")
        escribir(carpeta, "fuera.md", PAGINA + "\n[s](../secreto.xlsx)\n")
        publicar.escribir_estructura(carpeta / ".tiza", ESTRUCTURA)
        resultado = agente.comprobar(carpeta, ["oculto.md", "fuera.md"])
        assert [fichero.codigo for fichero in resultado.ficheros] == [
            "RECURSO_NO_PERMITIDO",
            "RUTA_FUERA_DE_CARPETA",
        ]

    def test_comprobar_un_cuestionario_genera_su_vista_previa(self, tmp_path):
        escribir(tmp_path, "q.md", CUESTIONARIO)
        publicar.escribir_estructura(tmp_path / ".tiza", ESTRUCTURA)
        resultado = agente.comprobar(tmp_path, ["q.md"])
        assert resultado.informe["resultado"] == "ok"
        [fichero] = resultado.ficheros
        assert fichero.codigo is None and fichero.vista_previa is not None
        texto = fichero.vista_previa.read_text(encoding="utf-8")
        assert "Preguntas del cuestionario" in texto
        assert "Respuesta correcta: <strong>Verdadero</strong>" in texto

    def test_seccion_ausente_lo_dice(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA.replace("seccion: 3", "seccion: 7"))
        publicar.escribir_estructura(tmp_path / ".tiza", ESTRUCTURA)
        [fichero] = agente.comprobar(tmp_path, ["p.md"]).ficheros
        assert fichero.codigo == "SECCION_AUSENTE"
        assert "no existe la sección 7" in fichero.detalle

    def test_sin_curso_de_pruebas_no_asume_que_existe(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA.replace("seccion: 3", 'seccion: "Fracciones"'))
        publicar.escribir_estructura(
            tmp_path / ".tiza",
            {
                "version": 1,
                "generado": "2026-10-03T10:00:00+00:00",
                "cursos": {
                    "real": {
                        "id": 5678,
                        "secciones": [{"numero": 3, "nombre": "Tema 3", "id": 30}],
                    }
                },
            },
        )
        resultado = agente.comprobar(tmp_path, ["p.md"])
        assert resultado.informe["resultado"] == "ok"
        [fichero] = resultado.ficheros
        assert fichero.codigo is None
        assert fichero.seccion_nueva == "Fracciones"

    def test_sin_curso_de_pruebas_la_pista_de_id_mira_en_real(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA.replace("seccion: 3", "seccion: 30"))
        publicar.escribir_estructura(
            tmp_path / ".tiza",
            {
                "version": 1,
                "generado": "2026-10-03T10:00:00+00:00",
                "cursos": {
                    "real": {
                        "id": 5678,
                        "secciones": [{"numero": 3, "nombre": "Tema 3", "id": 30}],
                    }
                },
            },
        )
        [fichero] = agente.comprobar(tmp_path, ["p.md"]).ficheros
        assert fichero.codigo == "SECCION_ES_ID"
        assert "escribe «seccion: 3»" in fichero.detalle

    def _solo_real(self, tmp_path, seccion):
        escribir(tmp_path, "p.md", PAGINA.replace("seccion: 3", f"seccion: {seccion}"))
        publicar.escribir_estructura(
            tmp_path / ".tiza",
            {
                "version": 1,
                "generado": "2026-10-03T10:00:00+00:00",
                "cursos": {
                    "real": {
                        "id": 5678,
                        "secciones": [{"numero": 3, "nombre": "Tema 3", "id": 30}],
                    }
                },
            },
        )
        return agente.comprobar(tmp_path, ["p.md"])

    def test_sin_curso_de_pruebas_el_numero_se_comprueba_en_real(self, tmp_path):
        resultado = self._solo_real(tmp_path, 3)
        assert resultado.informe["resultado"] == "ok"
        [fichero] = resultado.ficheros
        assert fichero.codigo is None
        assert resultado.informe["ficheros"][0]["seccion"] == "Tema 3"

    def test_sin_curso_de_pruebas_el_nombre_existente_en_real_no_es_nuevo(self, tmp_path):
        resultado = self._solo_real(tmp_path, '"Tema 3"')
        [fichero] = resultado.ficheros
        assert fichero.codigo is None
        assert fichero.seccion_nueva is None

    def test_sin_curso_de_pruebas_numero_inexistente_falla_nombrando_real(self, tmp_path):
        [fichero] = self._solo_real(tmp_path, 9).ficheros
        assert fichero.codigo == "SECCION_AUSENTE"
        assert "curso de real" in fichero.detalle


class TestBuzon:
    def test_sin_sesion(self, tmp_path):
        documento = agente.publicar(tmp_path, ["p.md"], "pruebas")
        assert documento["errores"] == ["SIN_SESION"]
        informe.validar(documento)

    def test_sin_sesion_en_worktree_lo_dice(self, tmp_path):
        (tmp_path / ".git").write_text("gitdir: /otra/.git/worktrees/asig\n", encoding="utf-8")
        documento = agente.publicar(tmp_path, ["p.md"], "pruebas")
        assert documento["errores"] == ["SIN_SESION"]
        assert "worktree de git" in documento["pasos"][0]["detalle"]
        informe.validar(documento)

    def test_sin_sesion_fuera_de_worktree_no_cambia(self, tmp_path):
        documento = agente.publicar(tmp_path, ["p.md"], "pruebas")
        assert documento["errores"] == ["SIN_SESION"]
        assert documento["pasos"] == []

    def test_pista_worktree_solo_con_git_fichero(self, tmp_path):
        assert agente.pista_worktree(tmp_path) is None
        (tmp_path / ".git").mkdir()
        assert agente.pista_worktree(tmp_path) is None
        (tmp_path / ".git").rmdir()
        (tmp_path / ".git").write_text("gitdir: /otra/.git/worktrees/asig\n", encoding="utf-8")
        assert "worktree" in agente.pista_worktree(tmp_path)

    def test_sesion_incompatible(self, tmp_path):
        dir_tiza = tmp_path / ".tiza"
        ruta = buzon.crear_sesion(dir_tiza, datetime.now(UTC) + timedelta(minutes=5))
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        datos["version"] = buzon.VERSION_PROTOCOLO + 1
        ruta.write_text(json.dumps(datos), encoding="utf-8")
        assert agente.estructura(tmp_path)["errores"] == ["SESION_INCOMPATIBLE"]
        assert agente.estado_sesion(tmp_path) == {
            "activa": True,
            "caduca": None,
            "compatible": False,
        }

    def test_publicar_envia_la_peticion_y_devuelve_la_respuesta(self, tmp_path, monkeypatch):
        monkeypatch.setattr(buzon, "sesion_activa", lambda *a, **k: True)
        enviadas: list = []

        def enviar(dir_tiza, peticion, espera, **_opciones):
            enviadas.append((dir_tiza, peticion, espera))
            return informe.crear("publicar", "ok", [], [], [], "pruebas", 1234)

        monkeypatch.setattr(buzon, "enviar", enviar)
        documento = agente.publicar(tmp_path, ["p.md"], "pruebas", visible=True, espera=30)
        assert documento["resultado"] == "ok"
        [(dir_tiza, peticion, espera)] = enviadas
        assert (dir_tiza, espera) == (tmp_path / ".tiza", 30)
        buzon.validar_peticion(peticion)
        assert (peticion["ficheros"], peticion["entorno"], peticion["visible"]) == (
            ["p.md"],
            "pruebas",
            True,
        )

    def test_cancelar_retira_la_peticion(self, tmp_path):
        dir_tiza = tmp_path / ".tiza"
        buzon.crear_sesion(dir_tiza, datetime.now(UTC) + timedelta(minutes=5))
        cancelar = threading.Event()
        cancelar.set()
        documento = agente.publicar(tmp_path, ["p.md"], "pruebas", cancelar=cancelar)
        assert (documento["resultado"], documento["errores"]) == ("abortado", ["ABORTADO"])
        assert not list(buzon.carpeta_buzon(dir_tiza).glob(f"*{buzon.SUFIJO_PETICION}"))

    def test_estado_sin_y_con_sesion(self, tmp_path):
        assert agente.estado_sesion(tmp_path) == {
            "activa": False,
            "caduca": None,
            "compatible": True,
        }
        buzon.crear_sesion(tmp_path / ".tiza", datetime.now(UTC) + timedelta(minutes=5))
        estado = agente.estado_sesion(tmp_path)
        assert (estado["activa"], estado["compatible"]) == (True, True)
        assert datetime.fromisoformat(estado["caduca"]) > datetime.now(UTC)

    def test_las_peticiones_son_validas(self):
        buzon.validar_peticion(agente.peticion_estructura())
        buzon.validar_peticion(agente.peticion_publicar(["a.md"], "real", None))


def test_formato_documento_sale_de_la_skill():
    texto = agente.formato_documento()
    for campo in ("tipo", "nombre", "seccion", "apertura", "entrega", "limite", "preguntas"):
        assert f"{campo}:" in texto
    assert "cuestionario" in texto
    assert "formato:" not in texto
    assert texto == texto.strip()
    assert not texto.startswith(" ")


def test_formato_documento_cubre_todos_los_tipos_y_campos():
    # Si contenido.py gana un tipo o un campo, la skill debe enseñarlo al agente.
    texto = agente.formato_documento()
    for tipo in contenido.TTIPOS + contenido.TIPOS_PREGUNTA:
        assert f"tipo: {tipo}" in texto, tipo
    campos = (
        set(contenido.CAMPOS_CUESTIONARIO)
        | set(contenido._CAMPOS_OPCION)
        | set(contenido.CAMPOS_H5P)
    )
    for campos_pregunta in contenido._CAMPOS_PREGUNTA.values():
        campos |= campos_pregunta
    for campo in sorted(campos):
        assert f"{campo}:" in texto, campo


def test_los_ejemplos_del_formato_son_validos(tmp_path):
    texto = agente.formato_documento()
    ejemplos = re.findall(r"```markdown\n(.*?)```", texto, re.DOTALL)
    assert len(ejemplos) == len(contenido.TTIPOS)
    for ruta in ("apuntes.pdf", "img/foto.png", "img/figura1.png"):
        (tmp_path / ruta).parent.mkdir(exist_ok=True)
        (tmp_path / ruta).write_bytes(b"x")
    tipos = []
    for numero, ejemplo in enumerate(ejemplos):
        ruta = tmp_path / f"ejemplo{numero}.md"
        escribir(tmp_path, ruta.name, ejemplo)
        tipos.append(contenido.cargar(ruta).tipo)
    assert tipos == list(contenido.TTIPOS)


class TestCalendarioEnComprobar:
    TAREA = (
        "---\ntipo: tarea\nnombre: Problemas\nseccion: 3\n"
        "apertura: 2026-10-01\nentrega: 2026-10-12\n---\n\nResuelve.\n"
    )

    def test_un_festivo_avisa_y_el_fichero_pasa(self, tmp_path):
        escribir(tmp_path, "t.md", self.TAREA)
        escribir(tmp_path, "calendario.toml", "festivos = [2026-10-12]\n")
        publicar.escribir_estructura(tmp_path / ".tiza", ESTRUCTURA)
        resultado = agente.comprobar(tmp_path, ["t.md"])
        assert resultado.informe["resultado"] == "ok"
        informe.validar(resultado.informe)
        [fichero] = resultado.ficheros
        assert fichero.codigo is None
        assert fichero.avisos == ("FECHA_FESTIVA",)
        avisos = [p for p in resultado.informe["pasos"] if p["codigo"] == "FECHA_FESTIVA"]
        assert avisos == [
            {"codigo": "FECHA_FESTIVA", "resultado": "ok", "detalle": "t.md: entrega 2026-10-12"}
        ]

    def test_un_calendario_invalido_es_un_error_pero_los_documentos_se_comprueban(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA)
        escribir(tmp_path, "calendario.toml", "color = 'rojo'\n")
        publicar.escribir_estructura(tmp_path / ".tiza", ESTRUCTURA)
        resultado = agente.comprobar(tmp_path, ["p.md"])
        assert resultado.informe["resultado"] == "error"
        assert resultado.informe["errores"] == ["CALENDARIO_INVALIDO"]
        informe.validar(resultado.informe)
        [fichero] = resultado.ficheros
        assert fichero.codigo is None
        assert fichero.avisos == ()

    def test_un_calendario_con_marcas_no_rompe_comprobar(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA)
        escribir(tmp_path, "calendario.toml", 'dias_de_clase = ["<b>"]\n')
        publicar.escribir_estructura(tmp_path / ".tiza", ESTRUCTURA)
        resultado = agente.comprobar(tmp_path, ["p.md"])
        assert resultado.informe["errores"] == ["CALENDARIO_INVALIDO"]
        informe.validar(resultado.informe)
        [paso] = [p for p in resultado.informe["pasos"] if p["codigo"] == "CALENDARIO"]
        assert "<" not in paso["detalle"] and "b?" in paso["detalle"]

    def test_un_calendario_hostil_no_rompe_comprobar(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA)
        escribir(tmp_path, "calendario.toml", "festivos = " + "[" * 5000 + "]" * 5000 + "\n")
        publicar.escribir_estructura(tmp_path / ".tiza", ESTRUCTURA)
        resultado = agente.comprobar(tmp_path, ["p.md"])
        assert resultado.informe["errores"] == ["CALENDARIO_INVALIDO"]
        informe.validar(resultado.informe)
        [fichero] = resultado.ficheros
        assert fichero.codigo is None

    def test_sin_calendario_no_hay_avisos(self, tmp_path):
        escribir(tmp_path, "t.md", self.TAREA)
        publicar.escribir_estructura(tmp_path / ".tiza", ESTRUCTURA)
        [fichero] = agente.comprobar(tmp_path, ["t.md"]).ficheros
        assert fichero.avisos == ()


def test_peticion_con_solo_fechas_viaja_en_el_buzon():
    assert agente.peticion_publicar(["a.md"], "real", solo_fechas=True)["solo_fechas"] is True
    peticion = agente.peticion_publicar(["a.md"], "real")
    assert peticion["solo_fechas"] is False
    assert peticion["visible"] is None


class TestVariosCursosReales:
    def estructura(self, tmp_path, nombres):
        publicar.escribir_estructura(
            tmp_path / ".tiza",
            {
                "version": 2,
                "generado": "2026-10-03T10:00:00+00:00",
                "cursos": {
                    "real": [
                        {
                            "id": 100 + n,
                            "secciones": [{"numero": 3, "nombre": nombre, "id": 30 + n}],
                        }
                        for n, nombre in enumerate(nombres)
                    ]
                },
            },
        )

    def test_el_numero_se_comprueba_en_el_primer_curso_real(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA)
        self.estructura(tmp_path, ["Tema 3", "Tema 3"])
        resultado = agente.comprobar(tmp_path, ["p.md"])
        assert resultado.informe["resultado"] == "ok"
        assert resultado.informe["ficheros"][0]["seccion"] == "Tema 3"
        assert resultado.informe["ficheros"][0]["curso"] is None
        assert not any(
            p["codigo"] == "SECCION_DISTINTA_ENTRE_CURSOS" for p in resultado.informe["pasos"]
        )

    def test_avisa_si_el_numero_tiene_nombres_distintos(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA)
        self.estructura(tmp_path, ["Tema 3", "Tercer tema"])
        informe_ = agente.comprobar(tmp_path, ["p.md"]).informe
        assert informe_["resultado"] == "ok"
        [aviso] = [p for p in informe_["pasos"] if p["codigo"] == "SECCION_DISTINTA_ENTRE_CURSOS"]
        assert aviso["resultado"] == "ok"
        assert aviso["detalle"] == "p.md: sección 3"  # sin los nombres de las secciones
        assert "Tercer tema" not in str(informe_)

    def test_por_nombre_no_avisa(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA.replace("seccion: 3", 'seccion: "Tema 3"'))
        self.estructura(tmp_path, ["Tema 3", "Tercer tema"])
        informe_ = agente.comprobar(tmp_path, ["p.md"]).informe
        assert not any(p["codigo"] == "SECCION_DISTINTA_ENTRE_CURSOS" for p in informe_["pasos"])

    def test_un_curso_donde_falta_el_numero_cuenta_como_distinto(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA)
        self.estructura(tmp_path, ["Tema 3"])
        publicar.escribir_estructura(
            tmp_path / ".tiza",
            {
                "version": 2,
                "generado": "2026-10-03T10:00:00+00:00",
                "cursos": {
                    "real": [
                        {"id": 101, "secciones": [{"numero": 3, "nombre": "Tema 3", "id": 33}]},
                        {"id": 102, "secciones": [{"numero": 0, "nombre": "General", "id": 1}]},
                    ]
                },
            },
        )
        informe_ = agente.comprobar(tmp_path, ["p.md"]).informe
        assert any(p["codigo"] == "SECCION_DISTINTA_ENTRE_CURSOS" for p in informe_["pasos"])

    def test_la_pista_de_id_mira_en_todos_los_cursos_reales(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA.replace("seccion: 3", "seccion: 31"))
        self.estructura(tmp_path, ["Tema 3", "Tema 3"])
        [fichero] = agente.comprobar(tmp_path, ["p.md"]).ficheros
        assert fichero.codigo == "SECCION_ES_ID"
        assert "escribe «seccion: 3»" in fichero.detalle

    def test_una_estructura_manipulada_no_rompe_comprobar(self, tmp_path):
        escribir(tmp_path, "p.md", PAGINA)
        publicar.escribir_estructura(
            tmp_path / ".tiza",
            {
                "version": 2,
                "generado": "x",
                "cursos": {
                    "real": [
                        {"id": 1, "secciones": [{"numero": 3, "nombre": "Tema 3", "id": 1}]},
                        {"id": 2, "secciones": [{"numero": 3, "nombre": {"a": 1}, "id": 2}]},
                        "basura",
                        {"id": 3, "secciones": "no"},
                    ]
                },
            },
        )
        informe_ = agente.comprobar(tmp_path, ["p.md"]).informe
        assert informe_["resultado"] == "ok"
        assert any(p["codigo"] == "SECCION_DISTINTA_ENTRE_CURSOS" for p in informe_["pasos"])


class TestDependencias:
    def md(self, tmp_path, nombre, completar=()):
        lista = "[" + ", ".join(completar) + "]"
        escribir(
            tmp_path,
            nombre,
            f"---\ntipo: pagina\nnombre: {nombre}\nseccion: 3\nrestricciones:\n  completar: {lista}\n---\n\nx\n",
        )

    def comprobar(self, tmp_path, ficheros):
        publicar.escribir_estructura(tmp_path / ".tiza", ESTRUCTURA)
        return agente.comprobar(tmp_path, ficheros)

    def test_dependencias_validas(self, tmp_path):
        self.md(tmp_path, "a.md")
        self.md(tmp_path, "b.md", ["a.md"])
        informe_ = self.comprobar(tmp_path, ["b.md", "a.md"]).informe
        assert informe_["resultado"] == "ok"

    def test_dependencia_que_no_existe(self, tmp_path):
        self.md(tmp_path, "b.md", ["falta.md"])
        resultado = self.comprobar(tmp_path, ["b.md"])
        assert resultado.informe["errores"] == ["DEPENDENCIA_INVALIDA"]
        assert resultado.ficheros[0].detalle == "falta.md"

    def test_dependencia_con_un_error_propio_no_es_error_interno(self, tmp_path):
        escribir(tmp_path, "a.md", "sin frontmatter")
        self.md(tmp_path, "b.md", ["a.md"])
        assert self.comprobar(tmp_path, ["b.md"]).informe["errores"] == ["DEPENDENCIA_INVALIDA"]

    def test_ciclo_directo_e_indirecto(self, tmp_path):
        self.md(tmp_path, "a.md", ["b.md"])
        self.md(tmp_path, "b.md", ["c.md"])
        self.md(tmp_path, "c.md", ["a.md"])
        informe_ = self.comprobar(tmp_path, ["a.md"]).informe
        assert informe_["errores"] == ["DEPENDENCIA_CIRCULAR"]

    def test_un_ciclo_que_no_incluye_al_fichero_pedido_tambien_se_detecta(self, tmp_path):
        self.md(tmp_path, "a.md", ["b.md"])
        self.md(tmp_path, "b.md", ["c.md"])
        self.md(tmp_path, "c.md", ["b.md"])
        assert self.comprobar(tmp_path, ["a.md"]).informe["errores"] == ["DEPENDENCIA_CIRCULAR"]

    def test_cadena_larga_sin_ciclo_no_se_desborda(self, tmp_path):
        for n in range(40):
            self.md(tmp_path, f"f{n}.md", [f"f{n + 1}.md"])
        self.md(tmp_path, "f40.md")
        informe_ = self.comprobar(tmp_path, ["f0.md"]).informe
        assert informe_["errores"] == ["DEPENDENCIA_CIRCULAR"]  # más profundo que el máximo

    def test_el_detalle_no_cuenta_lo_que_hay_fuera(self, tmp_path):
        self.md(tmp_path, "b.md", ["../fuera.md"])
        informe_ = self.comprobar(tmp_path, ["b.md"]).informe
        assert informe_["errores"] == ["RUTA_FUERA_DE_CARPETA"]

    def test_avisa_si_la_dependencia_no_declara_finalizacion(self, tmp_path):
        self.md(tmp_path, "a.md")
        self.md(tmp_path, "b.md", ["a.md"])
        pasos = self.comprobar(tmp_path, ["b.md"]).informe["pasos"]
        aviso = [p for p in pasos if p["codigo"] == "DEPENDENCIA_SIN_FINALIZACION"]
        assert aviso == [
            {"codigo": "DEPENDENCIA_SIN_FINALIZACION", "resultado": "ok", "detalle": "b.md: a.md"}
        ]

    def test_no_avisa_si_la_dependencia_se_completa(self, tmp_path):
        escribir(
            tmp_path,
            "a.md",
            "---\ntipo: pagina\nnombre: A\nseccion: 3\nfinalizacion: ver\n---\n\nx\n",
        )
        self.md(tmp_path, "b.md", ["a.md"])
        pasos = self.comprobar(tmp_path, ["b.md"]).informe["pasos"]
        assert not any(p["codigo"] == "DEPENDENCIA_SIN_FINALIZACION" for p in pasos)
