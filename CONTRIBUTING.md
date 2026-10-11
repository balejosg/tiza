# Contribuir a tiza

Gracias por querer ayudar. Todo el proyecto (código, mensajes, docs y tests)
está en español.

## Antes de empezar

- Para algo más que un arreglo pequeño, abre antes una issue y cuéntanos qué
  quieres hacer.
- **Nunca pruebes contra un aula real** ni pongas en una issue, un test o un
  ejemplo datos del alumnado (nombres, notas, salud, imágenes).
- Los tests son **100 % offline**: no añadas ninguno que haga peticiones de red.
  Usa los dobles de `tests/dobles.py`.

## Entorno

Requiere Python 3.11 o superior y [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
uv run pytest
```

Antes de enviar cambios:

```bash
uv run pytest
uvx ruff@0.16.10 check src tests && uvx ruff@0.16.10 format --check src tests
uv run --with mypy==2.4.0 --with types-PyYAML --with types-requests mypy
```

El CI corre los tests en Ubuntu, Windows y macOS: usa `pathlib` y nada
específico de POSIX.

## Reglas del código

[`AGENTS.md`](AGENTS.md) explica qué módulo es dueño de qué. Lo más importante:

- Solo `publicar.py` habla con el aula, y nada que venga de Moodle llega al
  agente: todo lo que sale pasa por el esquema cerrado de `informe.py`.
- La política de HTML vive en `filtro.py`; ampliar una lista exige un test con
  el caso hostil.
- Los códigos de error (`MAYUSCULAS_CON_GUION`) son estables: la skill y el
  README los citan.
- Las reglas están duplicadas en `SKILL.md`, `INSTALAR_CON_AGENTE.md` y
  `docs/aislamiento.md`: si cambias una, cambia las demás.

## Commits y cambios

Conventional Commits en español (`feat:`, `fix:`, `docs:`, `test:`). Si el cambio
se nota para el docente, añade una línea a [`CHANGELOG.md`](CHANGELOG.md).
