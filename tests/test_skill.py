"""La skill nombra bien los comandos del agente y remite a su guía de unidad."""

from __future__ import annotations

from pathlib import Path

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
    for comando in ("tiza normativa", "tiza leer", "tiza documento"):
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
