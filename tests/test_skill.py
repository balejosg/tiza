"""La skill nombra bien los comandos del agente y remite a su guía de unidad."""

from __future__ import annotations

from pathlib import Path

from tiza.escritura.relleno import cargar_relleno

SKILL = Path(__file__).resolve().parent.parent / "src/tiza/skill/tiza/SKILL.md"
GUIA = SKILL.parent / "guias/unidad.md"

COMANDOS_DEL_DOCENTE = (
    "tiza empezar",
    "tiza sesion",
    "tiza configurar",
    "tiza autoprueba",
    "tiza aislar",
    "tiza actualizar",
)


def _tabla_de_comandos() -> str:
    """La primera columna (el comando) de la tabla."""
    texto = SKILL.read_text(encoding="utf-8")
    _, _, resto = texto.partition("## Comandos que sí puedes ejecutar")
    assert resto, "falta el apartado de comandos"
    filas = []
    for linea in resto.splitlines():
        if linea.startswith("## "):
            break
        if linea.startswith("|"):
            filas.append(linea.split("|")[1])
    return "\n".join(filas)


def test_skill_nombra_comandos_del_agente():
    tabla = _tabla_de_comandos()
    for comando in ("tiza normativa", "tiza leer", "tiza documento", "tiza rellenar"):
        assert f"`{comando}" in tabla
    for comando in COMANDOS_DEL_DOCENTE:
        assert comando not in tabla


def test_guia_unidad_existe_y_se_cita():
    assert GUIA.is_file()
    assert "guias/unidad.md" in SKILL.read_text(encoding="utf-8")
    assert len(GUIA.read_text(encoding="utf-8").splitlines()) <= 90


def test_unidad_completa_carga_la_guia_antes_del_primer_paso():
    texto = SKILL.read_text(encoding="utf-8")
    seccion = texto.split("## Unidad completa", 1)[1].split("\n## ", 1)[0]
    assert "guias/unidad.md" in seccion
    assert seccion.index("guias/unidad.md") < seccion.index("\n1. ")


GUIA_PROGRAMACION = SKILL.parent / "guias/programacion.md"


def _bloque_yaml(texto: str) -> str:
    """El primer bloque ```yaml de la guía, sin las vallas."""
    _, abre, resto = texto.partition("```yaml\n")
    assert abre, "la guía no trae ningún bloque yaml"
    bloque, cierra, _ = resto.partition("\n```")
    assert cierra, "el bloque yaml no se cierra"
    return bloque + "\n"


def test_guia_programacion_existe_y_se_cita(tmp_path):
    assert GUIA_PROGRAMACION.is_file()
    assert "guias/programacion.md" in SKILL.read_text(encoding="utf-8")
    texto = GUIA_PROGRAMACION.read_text(encoding="utf-8")
    assert len(texto.splitlines()) <= 150
    assert "relleno.yaml" in texto
    # El ejemplo tiene que cargar sin errores: se valida su forma sin abrir ninguna plantilla.
    ruta = tmp_path / "relleno.yaml"
    ruta.write_text(_bloque_yaml(texto), encoding="utf-8")
    relleno = cargar_relleno(ruta, tmp_path)
    assert {type(op).__name__ for op in relleno.operaciones} == {
        "Reemplazar",
        "InsertarDespues",
        "Filas",
        "DuplicarTabla",
        "Borrar",
    }


def test_skill_carga_la_guia_de_programacion_en_su_seccion():
    texto = SKILL.read_text(encoding="utf-8")
    seccion = texto.split("## Programación del docente", 1)[1].split("\n## ", 1)[0]
    assert "guias/programacion.md" in seccion
    assert "tiza rellenar" in seccion
