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

El CI corre los tests en Ubuntu, Windows y macOS sin ninguna petición de red:
usa `pathlib` y nada específico de POSIX. La integración real con el aula la
comprueba el docente con `tiza autoprueba`.

## Reglas del código

[`AGENTS.md`](AGENTS.md) explica qué módulo es dueño de qué. Lo más importante:

- Solo `publicar.py` habla con el aula, y nada que venga de Moodle llega al
  agente: todo lo que sale pasa por el esquema cerrado de `informe.py`.
- La política de HTML vive en `filtro.py`; ampliar una lista exige un test con
  el caso hostil.
- Los códigos de error (`MAYUSCULAS_CON_GUION`) son estables: la skill y la
  documentación (`docs/`) los citan.
- Las reglas están duplicadas en `SKILL.md`, `INSTALAR_CON_AGENTE.md` y
  `docs/aislamiento.md`: si cambias una, cambia las demás.

## Uso como biblioteca

Además de la CLI, `tiza` ofrece dos módulos para quien construye una interfaz
propia (por ejemplo, una app con un asistente embebido):

- `tiza.agente`, el lado del agente, sin consola ni conexión con el aula:
  - `comprobar(carpeta, ficheros)` valida sin red;
  - `estructura(carpeta)`, `publicar(carpeta, ficheros, entorno)` y
    `ordenar(carpeta, ficheros, entorno)` piden por el
    buzón a la sesión del docente y devuelven el informe del esquema cerrado;
    aceptan `cancelar`, un `threading.Event`;
  - `estado_sesion(carpeta)` dice si hay sesión y hasta cuándo;
  - `formato_documento()` devuelve el formato de los `.md`.
- `tiza.sesion`, el lado del docente. `abrir(carpeta, presencia, minutos=60)`
  abre la sesión y atiende el buzón. `presencia` es cualquier objeto que cumpla
  `tiza.sesion.Presencia`; la CLI usa `tiza.terminal.PresenciaTerminal`.

La acreditación (contraseña o cookies de la ventana de entrada) solo la pide la presencia (`acreditar`) y solo la usa `tiza.sesion`. Cambiar
la firma de una de estas funciones obliga a subir la versión menor y a contarlo
en el [CHANGELOG](CHANGELOG.md).

## Commits y cambios

Conventional Commits en español (`feat:`, `fix:`, `docs:`, `test:`). Si el cambio
se nota para el docente, añade una línea a [`CHANGELOG.md`](CHANGELOG.md).
