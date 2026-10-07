"""El CI corre con permisos mínimos y las dependencias y acciones se vigilan solas."""

from __future__ import annotations

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]


def _yaml(ruta: str) -> dict:
    return yaml.safe_load((RAIZ / ruta).read_text(encoding="utf-8"))


def test_el_ci_declara_permisos_minimos_y_ningun_trabajo_los_amplia():
    flujo = _yaml(".github/workflows/ci.yml")
    assert flujo["permissions"] == {"contents": "read"}
    for nombre, trabajo in flujo["jobs"].items():
        assert "permissions" not in trabajo, f"el trabajo «{nombre}» cambia los permisos"


def test_dependabot_vigila_las_acciones_y_las_dependencias():
    datos = _yaml(".github/dependabot.yml")
    assert datos["version"] == 2
    ecosistemas = {cambio["package-ecosystem"] for cambio in datos["updates"]}
    assert ecosistemas == {"github-actions", "uv"}
    for cambio in datos["updates"]:
        assert cambio["directory"] == "/"
        assert cambio["schedule"]["interval"] == "weekly"
