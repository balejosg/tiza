"""La versión vive en varios ficheros (AGENTS.md): tienen que coincidir."""

from __future__ import annotations

import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _leer(nombre: str) -> str:
    return (RAIZ / nombre).read_text(encoding="utf-8")


def test_la_version_es_la_misma_en_todos_los_ficheros():
    version = tomllib.loads(_leer("pyproject.toml"))["project"]["version"]
    assert f":-v{version}}}" in _leer("install.sh")
    assert f'"v{version}"' in _leer("install.ps1")
    assert f"`v{version}`" in _leer("README.md")
    assert f"(`{version}`)" in _leer("AGENTS.md")
    assert f'name = "tiza"\nversion = "{version}"\n' in _leer("uv.lock")
