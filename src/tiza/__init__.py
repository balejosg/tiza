"""CLI y biblioteca `tiza` para publicar en tu aula virtual Moodle."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tiza")  # la única fuente es pyproject.toml
except PackageNotFoundError:  # código sin instalar
    __version__ = "0+desconocida"
