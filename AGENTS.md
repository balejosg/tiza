# Instrucciones del proyecto (para agentes)

`tiza` (paquete `tiza`) es una CLI + skill que publica páginas y tareas en
aulas virtuales Moodle. Todo el proyecto —código, mensajes, docs y tests— está
en español.

## Reglas que no se rompen

- **Ningún agente se conecta al aula virtual ni maneja la contraseña**: nada de
  `curl`, `fetch`, navegador ni MCP hacia el servidor del aula; no leas perfiles
  de navegador ni carpetas de descargas (salvo la carpeta de la asignatura, si
  está allí); no pidas ni manejes la contraseña.
- **`tiza empezar`, `tiza sesion`, `tiza configurar`, `tiza autoprueba`,
  `tiza aislar`, `tiza actualizar` y `tiza-ventana` son del docente**: no los ejecutes. El agente puede usar
  `tiza comprobar` (offline) y, mientras el docente mantenga abierta
  `tiza sesion` en esa carpeta, `tiza publicar` y `tiza estructura` dejan la
  petición en `.tiza/buzon/` y esperan un informe del esquema cerrado. Sin
  sesión fallan con `SIN_SESION`; pide al docente que ejecute `tiza empezar`
  en su terminal.
- **Nunca uses datos del alumnado** (nombres, notas, salud, imágenes) en prompts,
  `.md` ni en nada que vea el agente.
- **Tests 100 % offline**: no añadas tests que hagan peticiones de red.
- Todo lo que sale hacia el agente (pantalla, `.tiza/informe.json` y `.tiza/estructura.json`) se
  construye con el esquema cerrado de `src/tiza/informe.py`; nunca con HTML ni
  texto devuelto por Moodle.

## Comandos

- `uv sync --extra dev` — dependencias (Python >= 3.11).
- `uv run pytest` — suite completa. **Obligatorio antes de commitear.**
- `uv run pytest tests/test_informe.py::test_rechaza_campo_no_permitido_en_la_raiz`
  — un solo test.
- `uv run tiza --help` — CLI desde el repo.
- `uvx ruff@0.16.10 check src tests && uvx ruff@0.16.10 format --check src tests` — lint y formato.
- `uv run --with mypy==2.4.0 --with types-PyYAML --with types-requests mypy` — tipos.
- CI (`.github/workflows/ci.yml`): `uv run pytest` en Ubuntu, Windows y macOS,
  más prueba de `install.sh`/`install.ps1`. Mantén el código portable (pathlib,
  sin señales POSIX) y sin red en los tests. El job `calidad` del CI pasa además
  ruff, mypy y una cobertura mínima del 80 %.

## Dónde tocar

- `src/tiza/publicar.py`: **único módulo que habla con el aula**
  (python-moodle). Reduce toda excepción a códigos propios y nunca deja pasar
  texto de Moodle. Al importar parchea APIs privadas de python-moodle (sin token
  móvil, sin `list_courses`, User-Agent): es intencionado, no lo quites sin
  tests. `python-moodle` está fijado a `1.0.2`; subirlo obliga a revisar esos
  parches.
- `src/tiza/filtro.py`: **única fuente de la política de HTML** (etiquetas,
  atributos, CSS, clases y servidores de iframe) sobre el árbol de html5lib.
  Lo que se publica es ese árbol validado, serializado con `filtro.serializar`
  (nunca con `str()` de un nodo de texto). Ampliar una lista exige un test que
  cubra el caso hostil en `tests/test_filtro.py` (incluido el de invariante) y
  cambiar `SKILL.md` y el README. Depende de `html5lib` y `tinycss2`.
- `src/tiza/contenido.py`: Markdown o HTML + frontmatter, recursos locales,
  vista previa y hash del documento; todo offline.
- `src/tiza/cuestionario.py` y `src/tiza/h5p.py`: construcción offline del XML de
  preguntas y del paquete `.h5p` (solo contenido, determinista), y validación y
  reempaquetado de los paquetes subidos. `h5p.LIBRERIAS` fija la mayor.menor
  confirmada en la espiga (CT 130); una actualización del aula dentro del mismo
  mayor sigue sirviendo. tiza nunca sube librerías ni JavaScript: los paquetes
  subidos se reconstruyen solo con `h5p.json` y `content/`.
- `src/tiza/buzon.py`: protocolo de ficheros agente↔docente (escrituras
  atómicas, latido, huella del código). La compatibilidad entre agente y sesión
  es la versión del protocolo (`buzon.VERSION_PROTOCOLO`), no la huella. Editar
  cualquier `*.py` del paquete (también los subpaquetes) hace que la sesión
  abierta responda `SESION_DESACTUALIZADA` a la siguiente petición y se cierre:
  hay que reabrirla.
- `src/tiza/informe.py`: esquema cerrado. Cualquier campo nuevo de la salida
  debe añadirse aquí y a sus tests.
- `src/tiza/publicacion.py`: **la publicación como proceso**, común a la terminal
  directa y a la sesión: puertas (`puerta_real`, `SOLO_OCULTO_SIN_PRUEBAS`),
  resúmenes y confirmación por curso, flujo de solo-fechas, `publicar_con` e
  `informe_de_cursos`, y los tipos que ve la `Presencia` (`Aviso`, resúmenes,
  vistas previas). Lo que distingue a cada llamador entra como decisión explícita
  y documentada (`verificados` en memoria o disco, `vigente` solo en la sesión,
  `cupo` solo en la sesión, `omitidos` de la terminal directa).
- `src/tiza/sesion.py`: el lado del docente sin terminal (login, cursos,
  autoprueba, estructura y buzón). Solo habla con el docente a través de una
  `Presencia` y no importa `terminal` ni `cli`; todo recibe la carpeta de la
  asignatura, nunca usa el directorio actual. `procesar_peticion` despacha al
  módulo de publicación con lo que solo existe en una sesión: la vigencia de la
  petición, el cupo y el registro de verificados en memoria.
- `src/tiza/agente.py`: API pública del lado del agente para interfaces
  propias (`comprobar`, `estructura`, `publicar`, `estado_sesion`,
  `formato_documento`). Sin consola: todo lo que devuelve pasa por
  `informe.py` o son textos de tiza. El formato de los `.md` vive solo en la
  skill, entre los marcadores `formato:inicio` y `formato:fin`. Cambiar una
  firma obliga a subir la versión menor.
- `src/tiza/cli.py`, `config.py` y `terminal.py`: despacho, configuración sin
  contraseña (la global solo guarda URL y usuario; los cursos viven solo en el
  `tiza.toml` de cada carpeta) y presencia humana en la terminal (`terminal.PresenciaTerminal`:
  TTY, `getpass`, confirmación `[s/N]`); `cli.instalar_skill` copia la skill a
  Claude Code, Codex, opencode y `~/.agents/skills`.
- `src/tiza/ventana/`: la ventana de sesión (extra `[ventana]`, pywebview).
  `estado.py` no importa pywebview y es lo que se prueba; `Puente` es lo único
  que ve JavaScript (todo lo interno empieza por `_`, porque pywebview expone
  también los atributos públicos que sean objetos). La página
  (`sesion.html`) no usa `innerHTML` ni nada remoto y lleva CSP con nonce.
- Estado de trabajo en `.tiza/` (`informe.json`, `estructura.json`,
  `verificados.json`, `preview/`, `buzon/`). `.tiza/`, `planes/` y `dist/` están
  en `.gitignore`: no los commitees (`dist/` contiene artefactos obsoletos).

## Convenciones

- Errores con `ErrorX(codigo, detalle)` y códigos `MAYUSCULAS_CON_GUION`
  estables: los usan la skill y el README, no los renombres a la ligera.
- Los tests usan los dobles `MoodleFalso` y `PresenciaFalsa` de `tests/dobles.py` y los helpers
  `simular_terminal`, `responder` y `configurar` de `tests/test_cli.py`.
- Las reglas están duplicadas en `src/tiza/skill/tiza/SKILL.md` (la skill
  que se instala en los agentes), `INSTALAR_CON_AGENTE.md` y
  `docs/aislamiento.md`: si cambias una, cambia las demás.
- La versión (`0.16.1`) vive en `pyproject.toml`, `install.sh`, `install.ps1` y el
  README: actualízalos juntos. `tiza.__version__` la lee de los metadatos del
  paquete.
- `educaplay` es el único resultado legítimo al buscar restos del renombrado con
  `educa` antes de commitear en el público (el dominio de Educaplay): no lo «arregles».
- Commits en `main`, estilo Conventional Commits en español (`feat:`, `fix:`,
  `docs:`, `test:`).
