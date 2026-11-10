"""REFERENCIA_ROTA: citas «…» que se parecen al nombre de otra pieza sin coincidir."""

from __future__ import annotations

from tiza import agente, estado, referencias, rutas

CURSOS = {
    "pruebas": {"id": 1234, "secciones": [{"numero": 3, "nombre": "Tema 3", "id": 30}]},
}


def pagina(nombre: str, cuerpo: str = "Hola.") -> str:
    return f'---\ntipo: pagina\nnombre: "{nombre}"\nseccion: 3\n---\n\n{cuerpo}\n'


def escribir(carpeta, nombre, texto):
    ruta = carpeta / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")


class TestRotas:
    NOMBRES = {"2. Comparar fracciones", "Práctica: vocabulario de fracciones"}

    def test_la_cita_exacta_no_avisa(self):
        assert referencias.rotas("Sigue con «2. Comparar fracciones».", self.NOMBRES) == []

    def test_un_numero_cambiado_al_renombrar_avisa(self):
        assert referencias.rotas("Sigue con «3. Comparar fracciones».", self.NOMBRES) == [
            ("3. Comparar fracciones", "2. Comparar fracciones")
        ]

    def test_sin_el_numero_o_con_otras_mayusculas_avisa(self):
        texto = "Mira «Comparar fracciones» y «práctica: Vocabulario de fracciones»."
        assert referencias.rotas(texto, self.NOMBRES) == [
            ("Comparar fracciones", "2. Comparar fracciones"),
            ("práctica: Vocabulario de fracciones", "Práctica: vocabulario de fracciones"),
        ]

    def test_lo_que_no_se_parece_a_ningun_nombre_no_avisa(self):
        texto = "Contesta «sí» o «no». El bucle sigue en «no». Lee «El Quijote»."
        assert referencias.rotas(texto, self.NOMBRES) == []

    def test_cada_cita_rota_se_cuenta_una_vez(self):
        texto = "«Comparar fracciones» y otra vez «Comparar fracciones»."
        assert len(referencias.rotas(texto, self.NOMBRES)) == 1

    def test_una_cita_con_simbolos_no_permitidos_se_ignora(self):
        texto = "«2. Comparar <b>fracciones</b>»"
        assert referencias.rotas(texto, self.NOMBRES) == []


class TestNombresDeLaCarpeta:
    def test_lee_los_nombres_de_los_documentos_y_salta_lo_oculto(self, tmp_path):
        escribir(tmp_path, "a.md", pagina("Uno"))
        escribir(tmp_path, "sub/b.html", pagina("Dos"))
        escribir(tmp_path, "apuntes.md", "# Sin frontmatter\n")
        escribir(tmp_path, ".tiza/c.md", pagina("Oculto"))
        escribir(tmp_path, "roto.md", "---\nnombre: [sin cerrar\n---\n")
        assert referencias.nombres_de_la_carpeta(tmp_path) == {"Uno", "Dos"}


class TestComprobar:
    def test_avisa_sin_bloquear(self, tmp_path):
        escribir(tmp_path, "1.md", pagina("1. Qué es una fracción", "Sigue con «2. Comparar»."))
        escribir(tmp_path, "2.md", pagina("3. Comparar"))
        estado.escribir_estructura(tmp_path / rutas.CARPETA_TRABAJO, CURSOS)
        informe_ = agente.comprobar(tmp_path, ["1.md"]).informe
        assert informe_["errores"] == []
        assert {
            "codigo": "REFERENCIA_ROTA",
            "resultado": "ok",
            "detalle": "1.md: «2. Comparar» no coincide con «3. Comparar»",
        } in informe_["pasos"]

    def test_no_avisa_si_la_cita_coincide(self, tmp_path):
        escribir(tmp_path, "1.md", pagina("Uno", "Sigue con «3. Comparar»."))
        escribir(tmp_path, "2.md", pagina("3. Comparar"))
        estado.escribir_estructura(tmp_path / rutas.CARPETA_TRABAJO, CURSOS)
        pasos = agente.comprobar(tmp_path, ["1.md"]).informe["pasos"]
        assert not any(p["codigo"] == "REFERENCIA_ROTA" for p in pasos)

    def test_los_ejemplos_no_tienen_referencias_rotas(self):
        from pathlib import Path

        raiz = Path(__file__).resolve().parent.parent / "ejemplos"
        for carpeta in (raiz / "unidad", raiz / "explicar"):
            nombres = referencias.nombres_de_la_carpeta(carpeta)
            for fichero in sorted(carpeta.glob("*.*")):
                texto = fichero.read_text(encoding="utf-8")
                assert referencias.rotas(texto, nombres) == [], fichero.name
