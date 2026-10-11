"""Fixtures comunes: ningún test escribe en la caché real del usuario."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _cache_del_usuario_aislada(tmp_path_factory, monkeypatch):
    """Las vistas previas de la sesión van a la caché del usuario; en los tests, a una temporal."""
    cache = tmp_path_factory.mktemp("cache")
    monkeypatch.setattr("platformdirs.user_cache_dir", lambda *_args, **_opciones: str(cache))


@pytest.fixture(autouse=True)
def _sin_ventana_de_entrada(monkeypatch):
    """Los tests no abren ventanas: la entrada es siempre la contraseña de la terminal."""
    monkeypatch.setattr("tiza.ventana.disponible", lambda: False)
