# Instrucciones del proyecto (para agentes)

`tiza` (paquete `tiza`) es una CLI + skill que publica páginas y tareas en
aulas virtuales Moodle. Todo el proyecto —código, mensajes, docs y tests— está
en español.

## Reglas que no se rompen

- **Ningún agente se conecta a un aula virtual real ni maneja su contraseña**: nada de
  `curl`, `fetch`, navegador ni MCP hacia el servidor del aula; no leas perfiles
  de navegador ni carpetas de descargas (salvo la carpeta de la asignatura, si
  está allí); no pidas ni manejes la contraseña. **Única excepción, para desarrollar
  tiza:** el agente que trabaja en este repositorio puede lanzar las espigas y pruebas
  contra el Moodle de pruebas propio del desarrollador (el CT de `192.168.1.43`: su
  curso de pruebas y el curso que hace de «real» en ese servidor, el 3) con el lanzador
  `en_moodle_pruebas.py`, que lee las credenciales de pruebas en su propio proceso;
  nunca las leas ni las imprimas. En el aula real (cualquier otro servidor) no entra
  ningún agente. Esta
  excepción no se copia a la skill ni a los documentos para los agentes de los docentes.
- **`tiza empezar`, `tiza sesion`, `tiza configurar`, `tiza autoprueba`,
  `tiza aislar`, `tiza actualizar` y `tiza-panel` son del docente** (tampoco lances `python -m tiza.ventana` ni `python -m tiza.panel`): no los ejecutes. El agente puede usar
  `tiza normativa`, `tiza leer`, `tiza documento`, `tiza rellenar`, `tiza importar` y `tiza comprobar` (offline) y, mientras el docente mantenga abierta
  `tiza sesion` en esa carpeta, `tiza publicar`, `tiza ordenar`, `tiza calificador`, `tiza estructura` y `tiza copia` dejan la
  petición en `.tiza/buzon/` y esperan un informe del esquema cerrado. Sin
  sesión fallan con `SIN_SESION`; pide al docente que ejecute `tiza empezar`
  en su terminal (o, en Windows, que abra «tiza» desde el menú Inicio).
- **Nunca uses datos del alumnado** (nombres, notas, salud, imágenes) en prompts,
  `.md` ni en nada que vea el agente.
- **Tests 100 % offline**: no añadas tests que hagan peticiones de red.
- Todo lo que sale hacia el agente (pantalla, `.tiza/informe.json` y `.tiza/estructura.json`) se
  construye con el esquema cerrado de `src/tiza/informe.py`; nunca con HTML ni
  texto devuelto por Moodle. **Excepción**: la copia de seguridad del curso, la haga el docente o la pida
  `tiza copia` (que la saca del aula a través de la sesión del docente y con su confirmación), y
  el HTML de `.tiza/copia/<cmid>.html`, que es la versión del aula para juntar cambios. Es dato
  para el agente (`guias/realinear.md`). Lo que tiza lee del aula en vivo sigue con su esquema
  cerrado.

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
  Al publicar una release, `.github/workflows/wheel.yml` le sube su wheel, que es
  lo que instalan los instaladores y `tiza actualizar` (con el `.zip` de respaldo).

## Dónde tocar

- `src/tiza/tipos/`: **un módulo por tipo de actividad** (página, etiqueta, tarea,
  cuestionario y H5P) con lo que sabe cada uno: campos del frontmatter, validación,
  fechas, finalización, payload, publicación, vista previa, nombre llano y
  aportación al hash. Lo común está en `base.py` y el registro en `__init__.py`
  (`TIPOS`, `obtener`, `de_modulo`): añadir un tipo o un subtipo es escribir un
  adapter. `contenido.py` y `publicar.py` no tienen tablas ni ramas por tipo; las
  fachadas (`contenido.TTIPOS`, `publicar.payload_*`) se mantienen por
  compatibilidad. Los adapters importan `contenido`/`publicar` solo para sus clases
  y errores, con import diferido donde haría ciclo. El orden de los tres huecos del
  hash (`hash_fechas`/`hash_contenido`/`hash_extra`) reproduce el formato de
  siempre: cambiarlo invalida `verificados.json`. El test de contrato es
  `tests/test_tipos.py`.
- `src/tiza/normativa/`: la fuente de normativa (`tiza normativa`), offline: modelo,
  datos con esquema cerrado en `datos/`, consultas y salida validada. Los datos se
  generan con `herramientas/normativa/`, nunca a mano; `comprobar` debe dar 0 antes
  de commitear datos.
- `src/tiza/lectura/`: `tiza leer`, offline: convierte un `.docx` o un `.pdf` de la carpeta
  en un texto con ids de bloque (`[p12]`, `[t4.f2.c1]`, `g<página>.<n>`), siempre igual, en
  `.tiza/lecturas/`. Un módulo por formato (`word.py`, `pdf.py`) sobre el modelo común
  (`modelo.py`); lee con los límites de `ficheros.leer_bytes_acotado` y el resumen que ve el
  agente pasa por `informe.py`.
- `src/tiza/escritura/`: `tiza documento`, offline: convierte el Markdown del agente en un Word
  sencillo (`word.py`). Solo admite el subconjunto documentado (`MARKDOWN_NO_ADMITIDO` con el
  número de línea) y nunca sobrescribe (`DOCUMENTO_EXISTE`). `tiza rellenar`, también offline:
  `relleno.py` valida el `relleno.yaml` (forma, ids, conflictos) sin abrir la plantilla, y
  `rellenar.py` aplica las operaciones sobre una copia de la plantilla con los ids de
  `lectura/word.py`, sin sobrescribir nunca.
- `src/tiza/calificacion/`: el calificador del aula, puro salvo `ejecutar.py`. `esquema.py`
  valida `calificacion.yaml` (esquema cerrado, con la línea del error); `carpeta.py` lee las
  actividades de la carpeta con su `evalua`; `deseado.py` calcula el árbol deseado (todo cuelga
  de `TZ_TIZA`, con los ids `TZ_`); `reconciliar.py` lo compara con el aula y con las huellas
  (`calificador.json`) y da las operaciones; `formulas.py` construye las fórmulas puras;
  `ejecutar.py` las traduce a llamadas de `Moodle`. `tiza calificador` (buzón v7) pasa por
  `publicacion.py`; la guía del agente es `guias/calificador.md`.
- `src/tiza/copia.py`: lector seguro de la copia de seguridad de Moodle (`.mbz`), offline y en
  memoria: sin extraer a disco, con todos los límites (también las cabeceras extendidas del
  tar, con un `TarInfo` propio que se apoya en la API privada `_proc_member`: lo vigila
  `test_la_api_privada_de_tarfile_sigue_ahi`), sin entidades ni DTD, sin usuarios
  (`COPIA_CON_USUARIOS`). Lo que viene de la copia es dato.
- `src/tiza/importar.py`: `tiza importar`, offline: escribe un fichero por actividad con su
  `origen`, nunca sobrescribe, y lleva `.tiza/copia.json` con una entrada por curso (la
  huella del aula de cada actividad y, si cambió en el aula, el sha256 del fichero del docente
  para no publicarlo sin juntar los cambios). `src/tiza/importar_cuestionario.py`: las preguntas y los
  ajustes de un cuestionario, y lo que tiza no admite (`PREGUNTAS_NO_ADMITIDAS`,
  `AJUSTES_NO_ADMITIDOS`). La petición de `tiza copia` pasa por `publicacion.py` (buzón v6; `ficheros` en `copia` y `estructura` desde la v8); la
  descarga de la copia del aula está solo en `publicar.py` (`Moodle.hacer_copia`). Reconoce lo
  que publicó tiza (`PUBLICADA_POR_TIZA[_CAMBIADA]`, con `publicados.json`, sin duplicarlo en
  `aula/`) y acepta las copias de una sola actividad (`COPIA_DE_ACTIVIDAD_DESCONOCIDA`).
- `herramientas/normativa/`: solo del mantenedor, fuera del paquete; con red y
  `pdftotext`; la caché vive fuera del repo.
- `src/tiza/estructura.py`: **la estructura del aula, tipada y pura**: `Actividad`, `Seccion` y
  `Estructura` inmutables, los constructores que validan la forma una sola vez
  (`ESTRUCTURA_DEL_AULA_INVALIDA`) y las operaciones que antes estaban repartidas: búsqueda de
  sección, `localizar`, `ya_existe`, `desde_donde_se_mueve`, `secciones_que_faltan` y
  `resolver_orden`. No habla con el aula ni importa python-moodle; `Documento` entra solo para los
  tipos. `localizar` es **la única búsqueda de «la actividad del aula de este documento»** (origen,
  luego `Documento.publicados` del curso —`.tiza/publicados.json`—, luego tipo + nombre en su
  sección y en otra): publicar, ordenar, solo-fechas y el calificador pasan por ella; no busques
  actividades por otro camino.
- `src/tiza/estado.py`: **único dueño del estado de trabajo de `.tiza`**: los
  nombres de los ficheros (`informe.json`, `estructura.json`, `verificados.json`,
  `calificador.json`, `publicados.json`, `publicados/` y `preview/`), sus formatos y su validación al leer. `cargar_estructura`
  devuelve un `CursosGuardados` (con `CursoGuardado`: id y una `Estructura` sin actividades) con v1
  y v2 ya unificados (el agente no reinterpreta
  versiones); un fichero fuera del esquema es `ESTRUCTURA_INVALIDA`, no se
  interpreta a medias. Los verificados usan una sola dataclass (`Verificado`)
  en disco y en memoria. No
  importa python-moodle: `agente` lo usa sin cargar el aula.
- `src/tiza/vigilancia.py`: **la vigilancia de lo publicado**, por curso: responde si un documento
  tiene un retoque antes de confirmar (`rechazos`, `retoques`), qué dice `tiza estructura --cambios`
  de cada uno (`estado_por_documento`) y qué actividad hay que comprobar justo antes de escribir
  (`actividad`). Es el único sitio que compara con la huella y la marca y el que anota tras publicar
  (`anotar_publicado`, `anotar_fechas`): huella de la copia, entrada del registro, marca y base, en
  ese orden. Los dos almacenes —el registro (`publicados.json` + `publicados/`) y `copia.json`— son
  los dos adapters de la misma seam; los formatos de disco no cambian. No habla con el aula salvo
  `leer_modulo` y no importa python-moodle al cargarse: `publicar` entra diferido solo por su error.
  No la importan `estado`, `agente` ni `importar`.
- `src/tiza/publicar.py`: **único módulo que habla con el aula**
  (python-moodle). Reduce toda excepción a códigos propios y nunca deja pasar
  texto de Moodle. Al importar parchea APIs privadas de python-moodle (sin token
  móvil, sin `list_courses`, User-Agent): es intencionado, no lo quites sin
  tests. `python-moodle` está fijado a `1.0.2`; subirlo obliga a revisar esos
  parches. `Moodle.estructura` lee con tolerancia la respuesta del aula y devuelve
  `estructura.Estructura` (un `ErrorEstructura` es `ERROR_ESTRUCTURA`).
  `publicar_documento` y `publicar_fechas` devuelven el
  `informe.Fichero` ya construido (nada de dicts con claves sueltas) y reciben la actividad
  vigilada (el `Protocol` que define este módulo): la comprueban justo antes de escribir, sin
  conocer la vigilancia ni importarla. También
  mueve y ordena: `Moodle.mover` (`cm_move`), `plan_de_orden` (pura),
  `ordenar_documentos` y `asegurar_secciones`; cambiar
  `seccion:` mueve la actividad existente (`movida`) en vez de duplicarla.
  `_convertir` es el único sitio que convierte un problema de `estructura` en
  `ErrorPublicacion`: quien escribe en el aula lo llama; quien solo lee, mira el problema.
- `src/tiza/filtro.py`: **única fuente de la política de HTML** (etiquetas,
  atributos, CSS, clases y servidores de iframe) sobre el árbol de html5lib.
  Lo que se publica es ese árbol validado, serializado con `filtro.serializar`
  (nunca con `str()` de un nodo de texto). Ampliar una lista exige un test que
  cubra el caso hostil en `tests/test_filtro.py` (incluido el de invariante) y
  cambiar `SKILL.md` y `docs/seguridad.md`. Depende de `html5lib` y `tinycss2`.
- `src/tiza/contenido.py`: Markdown o HTML + frontmatter, recursos locales,
  vista previa y hash del documento; todo offline. Valida lo común (nombre,
  sección, finalización, restricciones) y le pide los campos propios y los
  `Extras` al adapter del tipo; no conoce ningún tipo por su nombre. El formato
  de las fechas en el hash (`tipos.base.formato_fecha`) no se cambia sin avisar.
- `src/tiza/cuestionario.py` y `src/tiza/h5p.py`: construcción offline del XML de
  preguntas y del paquete `.h5p` (solo contenido, determinista); la validación de
  las preguntas vive en `tipos/cuestionario.py` y la de las actividades y paquetes
  en `tipos/h5p.py`. `h5p.LIBRERIAS` fija la mayor.menor
  confirmada en la espiga (CT 130); una actualización del aula dentro del mismo
  mayor sigue sirviendo. tiza nunca sube librerías ni JavaScript: los paquetes
  subidos se reconstruyen solo con `h5p.json` y `content/`.
- `src/tiza/buzon.py`: protocolo de ficheros agente↔docente (escrituras
  atómicas, latido, huella del código). La compatibilidad entre agente y sesión
  es la versión del protocolo (`buzon.VERSION_PROTOCOLO`), no la huella. Editar
  cualquier `*.py` del paquete (también los subpaquetes) hace que la sesión
  abierta responda `SESION_DESACTUALIZADA` a la siguiente petición y se cierre:
  hay que reabrirla.
- `src/tiza/informe.py`: esquema cerrado **y construcción del informe**:
  `Paso`, `Fichero` y `Borrador` (la acumulación de pasos, ficheros y errores),
  y el registro `PASOS`. Ningún otro módulo arma pasos ni ficheros a mano (un
  test lo vigila); cualquier campo nuevo de la salida se añade aquí y a sus
  tests. `validar` sigue corriendo en las salidas hacia el agente: `escribir`
  (informe.json) y la respuesta del buzón al escribirla y al leerla.
- `src/tiza/publicacion.py`: **la publicación como proceso**, común a la terminal
  directa y a la sesión: puertas (`puerta_real`, `SOLO_OCULTO_SIN_PRUEBAS`),
  resúmenes y confirmación por curso, flujo de solo-fechas, `publicar_con` (devuelve el
  resultado del curso: el informe y si corta) y los tres **trabajos** que ejecuta el
  recorrido (`_TrabajoPublicar`, `_TrabajoOrdenar` y `_TrabajoCalificador`, con
  `ordenar_con`, `resumen_orden`, `preparar_calificador`, `resumen_calificador` y
  `calificador_con`), y los tipos que ve la `Presencia` (`Aviso` —con un
  constructor tipado por aviso—, resúmenes, vistas previas). Recibe la estructura
  del aula ya tipada (`estructura.Estructura`): los problemas de `localizar` se
  leen, no se capturan. Lo que distingue a
  cada llamador entra como decisión explícita
  y documentada (`verificados` en memoria o disco, `vigente` solo en la sesión,
  `cupo` solo en la sesión, `omitidos` de la terminal directa). Los retoques a mano del docente en lo que tiza
  publicó (solo cursos reales, por el registro `publicados.json`): construye una `Vigilancia` por
  curso y le pide los retoques (`Vigilancia.retoques`) antes de confirmar; `Presencia.confirmar_sobrescribir`
  pregunta tras el sí normal y `publicar_con` recibe lo decidido (`sobrescribir`, `no_publicar`), que
  pasa a publicar como la actividad vigilada. `cambios_en_el_aula` (`tiza estructura --cambios`) y
  `copiar_actividades` (`tiza copia --actividad`) son la otra mitad de lo mismo. La petición del agente no lleva nada de esto.
- `src/tiza/recorrido.py`: **el recorrido por cursos**, común a publicar, ordenar y
  calificador: en pruebas, `SIN_CURSO_PRUEBAS`, cupo (`MAX_PUBLICACIONES_PRUEBAS`),
  comprobación previa que no gasta cupo y aviso; en real, una visita por curso real en el
  orden de `tiza.toml`, `omitidos`, vigencia, corte e informe por cursos. Cada comando
  aporta un `Trabajo` con lo suyo; las preguntas pasan solo por `Turno.preguntar`, que
  comprueba la vigencia tras cada respuesta con la que tiza sigue escribiendo (cada «sí» y
  el «no» a sobrescribir) y lanza `PeticionRetirada`, que solo captura el recorrido. No
  importa `publicacion` al cargarse: el `Aviso` de retirada entra diferido.
- `src/tiza/sesion.py`: el lado del docente sin terminal (login, cursos,
  autoprueba y el ciclo de la sesión). Solo habla con el docente a través de una
  `Presencia` y no importa `terminal` ni `cli`; todo recibe la carpeta de la
  asignatura, nunca usa el directorio actual. Una sesión nueva puede pedir a la
  anterior de la misma carpeta que se cierre (`_cerrar_anterior` y `_Cierre`): el
  aviso va por un fichero en el directorio privado de vistas de esa sesión, nunca por
  el buzón, y es ella la que se va; tiza no mata procesos.
- `src/tiza/sesion_abierta.py`: la sesión ya abierta: su estado (aula,
  configuración capturada, presencia, nombres, vistas y lo que solo vive en
  memoria: cupo y verificados) y la interfaz que atiende una petición del buzón
  y devuelve el informe. `SesionAbierta.atender` valida la petición con el
  esquema del buzón y la despacha a `publicacion` con lo que solo existe en una
  sesión: la vigencia de la petición, el cupo y el registro de verificados en
  memoria. Es la superficie de los tests de la petición (test_sesion_abierta.py),
  y `estructura_con` y `registrar` viven aquí, con ella.
- `src/tiza/arranque.py`: el arranque de `tiza empezar` como proceso común, antes de abrir la
  sesión (actualizar, configurar la primera vez, carpeta dudosa, aislar y seguir sin aislar).
  `preparar` habla con el docente solo por `publicacion.Presencia` y no importa `terminal` ni
  `cli`; `version_nueva` e `instalar` llegan inyectados. Devuelve un `Resultado` (`SEGUIR`,
  `ACTUALIZADA`, `ABORTADO`, `FALLO`); con `exigir_aislamiento` no ofrece seguir sin aislar.
  `cli._empezar` lo traduce a los códigos de salida de siempre. La planificación del
  aislamiento (`Plan`, `planear_carpeta`, `planear_global`, `aplicar`) vive en `aislamiento.py`,
  sin consola: los pasos a mano van en `Plan.manuales`.
- `src/tiza/agente.py`: API pública del lado del agente para interfaces
  propias (`comprobar`, `estructura`, `publicar`, `estado_sesion`,
  `formato_documento`). Sin consola: todo lo que devuelve pasa por
  `informe.py` o son textos de tiza. No importa `publicar`: el estado vive en
  `estado.py`, así que `tiza comprobar` no carga python-moodle. El formato de
  los `.md` vive solo en la skill, entre los marcadores `formato:inicio` y
  `formato:fin`. Cambiar una firma obliga a subir la versión menor.
- `src/tiza/mensajes.py`: **el texto llano que ve el docente**, venga de la
  terminal o de la ventana: `texto_seguro`, el nombre llano del tipo, las tablas
  (`PARA_QUE`, `VISIBILIDAD`, `CIERRE`), los avisos (una conversión por código,
  registrada) y los resúmenes de confirmación (`detalle_real`/`detalle_corto`).
  Las presencias solo adaptan: `terminal.py` imprime (stdout lo normal, stderr
  las líneas de error). Las
  claves de `Aviso.datos` las fija cada constructor tipado de `publicacion.Aviso`
  y solo se leen aquí.
- `src/tiza/cli.py`, `config.py` y `terminal.py`: despacho, configuración sin
  contraseña (la global solo guarda URL y usuario; los cursos viven solo en el
  `tiza.toml` de cada carpeta) y presencia humana en la terminal (`terminal.PresenciaTerminal`:
  TTY, `getpass`, confirmación `[s/N]`, con el texto de `mensajes`); `cli.instalar_skill`
  copia la skill a Claude Code, Codex, opencode y `~/.agents/skills`.
- `src/tiza/actualizacion.py`: **versiones e instalación de tiza**, sin `print`: la última etiqueta
  publicada (`ultima_etiqueta`, `version_nueva`), la validación de `TIZA_REF` (`validar_ref`),
  los orígenes y paquetes de uv, `quiere_ventana`, y en Windows los guiones de PowerShell y su
  entorno (`TIZA_ACT_*`; funciones puras, el `Popen` se inyecta): `GUION_WINDOWS` (`tiza actualizar`,
  en otra consola) y `GUION_PANEL` (el panel, PowerShell oculto con `CREATE_NO_WINDOW`: espera al
  PID, instala solo `tiza[ventana]`, reinstala la skill, recrea los accesos, escribe
  `actualizar.log` en la carpeta global y reabre `tiza-panel.exe` en ventana normal). `ACCESOS_PS`
  (los accesos «tiza» del menú Inicio y el escritorio) está **duplicado a propósito en
  `install.ps1`** (se ejecuta con `irm | iex`): un test los mantiene iguales. En PowerShell
  `"$var:"` es un error de sintaxis (`"${var}:"`). `cli.py` conserva la salida y usa estas piezas.
- `src/tiza/panel/`: el panel sin consola de Windows (`tiza-panel`, `[project.gui-scripts]`).
  **`tiza-panel` es del docente, como `tiza empezar`: ningún agente lo lanza** (ni con
  `Start-Process`, `explorer` ni `pythonw -m tiza.panel`); sin consola, lo que lo impide es el
  perfil de permisos de `tiza aislar`, y por eso el panel no abre la sesión con el agente sin
  aislar. **El perfil de Windows lo deniega expresamente** (`aislamiento.reglas_panel_windows`:
  `tiza-panel`, `tiza-panel.exe`, `python -m tiza.panel` y `pythonw -m tiza.panel`, con y sin
  argumentos, en PowerShell y Bash); `aislamiento.revisar` las exige y un `allow` que permita el
  panel es «de más» (`shell_de_mas`, `quitar_permisos_de_mas`). Piezas:
  - `estado.py`, el modelo: `Pantalla` (datos JSON), `Panel` (estado entre hilos), `PresenciaPanel`
    (cumple `publicacion.Presencia`; cada pregunta bloquea hasta la respuesta o el cierre, que
    cuenta como no) y `Puente` (el `js_api`: solo acciones, respuestas simples, con retardo mínimo
    y número de pantalla). Las rutas reales de las carpetas recientes se quedan en el `Panel`
    (`esperar_carpeta`): JS ve el índice y el nombre visible. `buscar_carpeta` y `terminar` no
    hacen nada de ventana, solo dejan una petición (`pedir_dialogo`, `pedir_salida`) que atiende
    el hilo de la ventana. La acreditación del aula no pasa por el `Puente`, entra por `abrir_login`.
  - `recientes.py` (puro): hasta 8 carpetas en `panel-recientes.json` junto a la configuración
    global; un fichero roto es una lista vacía y un fallo al escribir se ignora.
  - `flujo.py` (puro): carpeta, `arranque.preparar(exigir_aislamiento=True)`, `sesion.abrir` y una
    pantalla final de reposo. `version_nueva` e `instalar` se inyectan (por defecto,
    `actualizacion.version_nueva` e `instalar_con_actualizador`, que lanza el actualizador oculto);
    tras `ACTUALIZADA` deja el reposo «Se está actualizando» y pide la salida (`Panel.salir`) para
    que el proceso termine y el actualizador siga. Si la ventana de entrada al aula se cierra o
    caduca (`PresenciaPanel.sin_entrar`), el final dice «No se entró en el aula». Al reabrirse
    tras actualizar, `contar_actualizacion` lee `TIZA_PANEL_ACTUALIZACION` (`ok:X.Y.Z` o `fallo`)
    y lo cuenta con `Aviso.panel_actualizado` / `Aviso.panel_no_actualizado`.
  - `sesion.html`: la página (dato del paquete), cargada con `html=`. Mismas reglas que la de la
    ventana de sesión antigua: ni `<a>`, ni `innerHTML`/`outerHTML`/`insertAdjacentHTML`/`document.write`
    /`eval`/`new Function`; todo con `createElement` + `textContent`; CSP con nonce por arranque y
    `'unsafe-eval'` (lo exige el puente de pywebview) pero sin `'unsafe-inline'`; sondeo de
    `estado()` cada 300 ms; nunca llama al puente con argumentos sobrantes (pywebview pasa
    `undefined` como `None`). La única imagen es el logo del paquete, que `pagina` incrusta
    como `data:`. Lo vigila `tests/test_panel_pagina.py`.
  - `__init__.py`: la capa de ventana y **el único módulo del subpaquete que importa `webview`**,
    solo dentro de `main()` (el CI no instala el extra; `import tiza.panel` no lo carga). Lo
    comprobable va en funciones puras (`que_falta`, `galletas_de`, `ya_dentro`, `ruta_del_dialogo`…).
    `vigilar` es el hilo de la ventana: pone el panel delante y lo hace parpadear cuando hay una
    pregunta, abre el diálogo de carpeta y destruye la ventana al cerrar la sesión. Las
    operaciones de ventana (`on_top`, `restore`, `show`, `destroy`, el diálogo) van siempre desde
    ese hilo, nunca dentro de una llamada del `js_api`: cuelgan la ventana. Al arrancar, `vigilar`
    muestra la ventana una vez (con reintentos si aún no hay HWND) por si nació oculta. `abrir_login` crea la
    ventana de entrada en el mismo proceso, sin `js_api`; la cookie nunca sale del proceso.
- `src/tiza/recursos/`: los recursos gráficos que viajan en la wheel: `logo.png` (la marca con
  transparencia que la página del panel incrusta como `data:`) y `tiza.ico` (el icono de varias
  medidas de las ventanas y del acceso de Windows). `ruta` solo sirve para ficheros reales;
  `datos` también dentro de un paquete comprimido.
- `src/tiza/ventana/`: la ventana de entrada al aula (extra `[ventana]`, pywebview;
  Windows, macOS y Linux con escritorio, con Qt o GTK). **Solo enseña la página de login del aula y devuelve las cookies de
  sesión del servidor del aula**: nada más pasa por ella (cursos, aislamiento y
  confirmaciones siguen en la terminal). `entrada.py` no importa pywebview y es lo que se
  prueba (cuándo se está dentro, qué cookies se aceptan, esquema y límites de la tubería);
  `__init__.py` lanza `python -m tiza.ventana <url>` como proceso hijo (`entrar`), que es
  el único que importa `webview`, no tiene `js_api` y exige una terminal delante. Las
  cookies viajan por la salida estándar del hijo: nunca por disco, argumentos ni entorno.
  La acreditación (`publicar.Contrasena` o `publicar.Cookies`) entra por
  `Presencia.acreditar`, y `publicar.autenticar_con` elige el login.
- `src/tiza/skill/tiza/`: la skill que `cli.instalar_skill` copia a los agentes. `ejemplos/` es
  una copia de texto (`.md`, `.html` y `.txt`) de `ejemplos/` de la raíz, sin las imágenes ni los
  ejemplos que no enseña la skill; `test_skill.test_los_ejemplos_de_la_skill_son_los_del_repositorio`
  exige que las dos copias coincidan.
- Estado de trabajo en `.tiza/` (`informe.json`, `estructura.json`,
  `verificados.json`, `publicados.json`, `publicados/`, `preview/`, `buzon/`): los nombres y formatos de lo que
  no es buzón viven en `estado.py`. `.tiza/`, `planes/` y `dist/` están
  en `.gitignore`: no los commitees (`dist/` contiene artefactos obsoletos).

## Convenciones

- Errores con `ErrorX(codigo, detalle)` y códigos `MAYUSCULAS_CON_GUION`
  estables: los usan la skill y `docs/`, no los renombres a la ligera.
- Los tests usan los dobles `MoodleFalso` y `PresenciaFalsa` de `tests/dobles.py` (con
  `peticion`, `dejar_peticion`, `tarea_en`, `aula_con_tarea` y `enlace_simbolico`) y los
  helpers `simular_terminal`, `responder` y `configurar` de `tests/test_cli.py`.
- Las reglas están duplicadas en `src/tiza/skill/tiza/SKILL.md` (la skill
  que se instala en los agentes), `INSTALAR_CON_AGENTE.md` y
  `docs/aislamiento.md`: si cambias una, cambia las demás.
- El README es la portada para docentes: corto y sin detalle técnico. Los
  comandos y opciones van en `docs/guia.md`, el formato en `docs/formato.md`
  y las medidas de seguridad en `docs/seguridad.md`.
- La versión (`0.36.1`) vive en `pyproject.toml`, `install.sh`, `install.ps1` y el
  README: actualízalos juntos. `tiza.__version__` la lee de los metadatos del
  paquete.
- El Python con el que se instala tiza (`3.13`) vive en `install.sh`, `install.ps1` y
  `cli.PYTHON_INSTALADO`: súbelo junto y solo cuando todas las dependencias (también las de
  `[ventana]`) traigan wheels para la versión nueva en Windows, macOS y Linux.
- `educaplay` es el único resultado legítimo al buscar restos del renombrado con
  `educa` antes de commitear en el público (el dominio de Educaplay): no lo «arregles».
  La búsqueda excluye `src/tiza/normativa/datos/`, `herramientas/normativa/fuentes/`,
  `herramientas/normativa/fuentes.toml` y `herramientas/normativa/requisitos.toml`
  (texto literal de boletín: «Consejería de Educación», «calificación»).
- Al cambiar algo visible para el docente, añade una línea a `CHANGELOG.md`.
- Commits en `main`, estilo Conventional Commits en español (`feat:`, `fix:`,
  `docs:`, `test:`).
