# Guía de uso de `tiza`

Todo lo que `tiza` sabe hacer, con sus opciones. Para empezar desde cero, lee
antes [primeros-pasos.md](primeros-pasos.md); el formato de los ficheros está en
[formato.md](formato.md) y las medidas de seguridad en [seguridad.md](seguridad.md).

## Comandos

| Comando | Quién | Qué hace |
|---|---|---|
| `tiza empezar [--minutos 60] [--elegir-cursos] [--sin-ventana]` | docente | Todo en uno: ofrece la versión nueva si la hay, configura si hace falta, revisa el aislamiento, abre la sesión, autoprueba si toca y lee la estructura |
| `tiza configurar` | docente | Guarda la URL y el usuario (nada más); los cursos se eligen por nombre al abrir la sesión en cada carpeta y se guardan en su `tiza.toml` |
| `tiza instalar-skill` | docente | Instala la skill portable en los agentes |
| `tiza actualizar` | docente | Instala la última versión publicada de `tiza` y reinstala la skill |
| `tiza normativa <consulta>` | agente o docente | Offline: consulta la normativa que trae tiza y devuelve un JSON con código, texto literal y procedencia. Consultas: `catalogo`, `ficha <codigo>`, `elemento <codigo>`, `norma "<cita>"`, `buscar "<texto>" [--en <codigo>]` y `programacion eso\|bachillerato\|fp`; todas menos `norma` aceptan `--curso-academico AAAA-AA` (por defecto, el de hoy) |
| `tiza leer <fichero>` | agente o docente | Offline: convierte un `.docx` o `.pdf` de la carpeta en `.tiza/lecturas/<ruta>.txt` (la ruta con `__` en vez de `/`: `1DAM/Prog.docx` queda en `1DAM__Prog.docx.txt`), con una marca por bloque (`[p12]`, `[t4.f2.c1]`; los encabezados y pies de un Word salen al final, `[e1.p1]`, `[pie1.p1]`; en PDF, `g<página>.<n>`), y da un resumen JSON. Avisos: `CAMBIOS_SIN_ACEPTAR`, `PDF_SIN_TABLAS`. Errores: `FICHERO_FUERA`, `FICHERO_TEMPORAL`, `FORMATO_NO_ADMITIDO`, `DOCUMENTO_PROTEGIDO`, `PDF_PROTEGIDO`, `PDF_SIN_TEXTO`, `DOCUMENTO_DEMASIADO_GRANDE`, `FICHERO_BLOQUEADO`, `DOCUMENTO_AUSENTE`, `NOMBRE_NO_VALIDO`, `LECTURA_NO_ESCRIBIBLE` |
| `tiza documento <fuente.md> [--salida <x.docx>]` | agente o docente | Offline: convierte un `.md` en un Word sencillo (títulos 1-4, negrita, cursiva, listas de hasta 3 niveles, tablas, enlaces y `\pagebreak`); por defecto, el nombre del `.md` con `.docx`. Nunca sobrescribe. Errores: `MARKDOWN_NO_ADMITIDO` (HTML, imágenes, bloques de código, citas, frontmatter, títulos 5-6; dice la línea), `DOCUMENTO_EXISTE` (usa `--salida` con otro nombre), `DOCUMENTO_NO_ESCRIBIBLE`, `DOCUMENTO_AUSENTE`, `FICHERO_DEMASIADO_GRANDE`, `FICHERO_BLOQUEADO`, `FORMATO_NO_ADMITIDO` (no es `.md`/`.docx` o no está en UTF-8), `NOMBRE_NO_VALIDO`, `FICHERO_FUERA`, `FICHERO_TEMPORAL` |
| `tiza rellenar <relleno.yaml>` | agente o docente | Offline: aplica un `relleno.yaml` de la carpeta sobre una copia de la plantilla Word (`.docx`) del departamento o de una programación de referencia, con los ids de `tiza leer` (también los de encabezados y pies); conserva estilos y numeración, y lo que no cambies de encabezados y pies, y el índice se puede actualizar al abrir el Word (Word pregunta si actualizar los campos). Nunca sobrescribe (`DOCUMENTO_EXISTE`). Formato y errores en [formato.md](formato.md) |
| `tiza importar <copia.mbz> [--como-nuevas] [--destino aula]` | agente o docente | Offline: convierte una copia de seguridad del curso, hecha sin usuarios, en un fichero de tiza por actividad (con `origen`) en la carpeta de destino, y deja el resumen en `.tiza/copia.json` (una entrada por curso). Nunca sobrescribe (`YA_IMPORTADO`). `--como-nuevas` importa una copia de otro curso como actividades nuevas (con un curso de `tiza.toml`, `COPIA_DEL_MISMO_CURSO`: se importa sin ella). Errores: `COPIA_CON_USUARIOS`, `COPIA_NO_VALIDA`, `COPIA_DEMASIADO_GRANDE`, `COPIA_DE_OTRO_CURSO`, `COPIA_DEL_MISMO_CURSO` |
| `tiza copia <curso>` | agente o docente | Con `tiza sesion` abierta: pide al docente una copia de seguridad del curso sin usuarios (`pruebas`, `real` o el id de `tiza.toml`), que confirmas `[s/N]` en tu terminal; queda en `.tiza/copias/`, lista para `tiza importar`. Máximo 3 por sesión. Sin sesión, `SIN_SESION` |
| `tiza comprobar <fichero>…` | agente | Offline: valida `.md` o `.html`, genera `.tiza/preview/*.html` y comprueba la sección en `.tiza/estructura.json` |
| `tiza sesion [--minutos 60] [--elegir-cursos] [--sin-ventana]` | docente | Autenticado: abre la sesión (un único login) para que el agente publique mientras siga abierta |
| `tiza ordenar <md>… --en pruebas\|real` | agente o docente | Con `tiza sesion` abierta (o terminal del docente): deja las actividades de esos ficheros en ese orden dentro de su sección, sin mover nada más; en real, el docente confirma el orden curso a curso. Cambiar `seccion:` y publicar mueve la actividad en vez de duplicarla |
| `tiza calificador <calificacion.yaml> --en pruebas\|real` | agente o docente | Con `tiza sesion` abierta (sin sesión da `SIN_SESION`): monta en el calificador del aula las categorías y totales que dice el esquema, y coloca las actividades con `evalua`. Nunca lee ni escribe notas ni desbloquea nada; en real confirmas cada curso. Guía del agente en [formato.md](formato.md#calificador-calificacionyaml) |
| `tiza estructura` | agente o docente | Con `tiza sesion` abierta (o terminal del docente): guarda las secciones de los cursos configurados |
| `tiza publicar <md>… --en pruebas` | agente o docente | Con `tiza sesion` abierta (o terminal del docente): crea (oculto) o actualiza (conserva la visibilidad), verifica y registra el hash |
| `tiza publicar <md>… --en real` | agente o docente | Igual, pero cada petición se confirma `[s/N]` en la terminal del docente y solo publica lo verificado; sin curso de pruebas, exige `--oculto` y la confirmación es corta |
| `tiza publicar <md>… --en pruebas\|real --solo-fechas` | agente o docente | Cambia solo las fechas de tareas y cuestionarios ya publicados (ni contenido, ni preguntas, ni intentos, ni visibilidad); en real, la confirmación enseña cada fecha antes y después |
| `tiza autoprueba` | docente | Prueba de contrato completa en el curso de pruebas: publica, republica, verifica y borra (si no hay curso de pruebas, responde `SIN_CURSO_PRUEBAS`) |
| `tiza aislar` | docente | Añade el aislamiento a esta carpeta: Claude Code, Codex y opencode (con `--global`, a todos tus proyectos), con copia de seguridad. En Windows aísla Claude Code con permisos (el agente solo ejecuta los comandos de tiza que le tocan), y `--global` no lo hace en Windows; con la app de Copilot no escribe nada y muestra la receta de su sandbox |
| `tiza revisar` | agente o docente | Solo lectura: comprueba el aislamiento de esta carpeta y avisa si es global |

Cuando algo falla, `tiza` muestra el código (por ejemplo `SESION_CADUCADA`) y
una línea «Qué hacer» con el siguiente paso. Si no se arregla, abre una
[*issue*](https://github.com/balejosg/tiza/issues) con la orden que
ejecutaste, tu sistema y el código y la línea «Qué hacer» copiados tal cual.
No adjuntes capturas del aula (pueden salir alumnos) ni tu contraseña.

## Normativa

`tiza normativa` trae la normativa de la Comunidad de Madrid del curso 2026-27:
en ESO, Ciencias de la Computación (1.º y 2.º), Tecnología y Digitalización (2.º y
3.º) y Digitalización (4.º); en Bachillerato, Ciencias de la Computación I y II; en
FP, el título y los módulos de Desarrollo de Aplicaciones Multiplataforma (técnicos,
transversales y los optativos del catálogo que caben en él, como `MAD.CMO.316`);
los descriptores del perfil de salida; y lo que la normativa exige de la programación
(`tiza normativa programacion eso|bachillerato|fp`). El texto es el literal del
boletín, con las correcciones de errores oficiales de su norma ya aplicadas
(`tiza normativa norma "<cita>"` las lista), y cada elemento lleva su código y su
procedencia; si una norma posterior lo corrige o lo renombra, la procedencia nombra esa
corrección y `via` el texto original. Lo que no está responde
`NORMATIVA_SIN_DATOS`; un curso sin datos, `CURSO_SIN_DATOS` (prueba `tiza actualizar`).
El agente no busca normativa en internet: si necesitas una norma que no está,
déjale su PDF en la carpeta.

## Flujo con un agente

1. En **tu** terminal, dentro de la carpeta de la asignatura:

   ```bash
   tiza empezar
   ```

   La primera vez te pregunta la URL del aula y tu usuario. Después comprueba
   que el agente está aislado; si falta, te ofrece aplicar el aislamiento a esta
   carpeta ahí mismo. Luego se abre la página de entrada de tu aula (entra como
   siempre; sin ventana, te pide la contraseña una vez), te deja elegir tus
   cursos de pruebas y real por su nombre, pasa la autoprueba cuando toca (al
   estrenar versión o cada septiembre) y lee las secciones. Déjala abierta.
2. En la terminal del agente, pídele el contenido. El agente lo escribe, lo
   comprueba con `tiza comprobar` y lo publica en pruebas.
3. Revisa el enlace «Ver en el aula» en el curso de pruebas.
4. Cuando te guste, pídele que lo publique en real. En tu terminal verás qué se
   publica, dónde y con qué fechas, y confirmarás con `s`. Si no tienes curso de
   pruebas, pídele que lo publique «oculto» (`tiza publicar … --en real
   --oculto`): verás un resumen corto y quedará oculto para el alumnado.

`tiza sesion`, `tiza configurar`, `tiza autoprueba`, `tiza ordenar` y `tiza estructura`
siguen disponibles para hacer cada paso por separado.

Mientras la sesión esté abierta, no entres al aula con el mismo usuario desde el
navegador: el aula puede cerrar la sesión anterior. Si ocurre, `tiza`
responde `SESION_CADUCADA` y la sesión se cierra; vuelve a abrirla.

El buzón `.tiza/buzon/` solo usa ficheros (ni red ni sockets), así que funciona
dentro de los sandboxes de los agentes. Sin sesión abierta, `publicar` y
`estructura` fallan con `SIN_SESION` y nunca piden la contraseña.

La skill contiene el flujo completo y las reglas (no conectarse al servidor del
aula, no manejar la contraseña, no leer perfiles de navegador…).

## Preparar un tema entero

Pide al agente «prepárame el tema 3 de fracciones»: la skill le indica que primero
pregunte en un solo mensaje lo que falte (curso, sesiones, fechas, sección, documento
curricular), que te proponga la secuencia antes de escribir nada y que encadene las
piezas con el itinerario. `ejemplos/unidad/` es una unidad de seis piezas (presentación,
dos páginas, práctica H5P, cuestionario y tarea). tiza comprueba el formato y la
seguridad y la publica en una petición; el contenido y los criterios curriculares los
revisas tú en la vista previa y en el curso de pruebas.

## `tiza.toml` por asignatura

Los cursos son de cada asignatura y solo se guardan en el `tiza.toml` de su
carpeta; la configuración global (`tiza configurar`) guarda únicamente la URL
del aula y tu usuario. Lo crean `tiza empezar` o `tiza sesion` la primera vez,
al elegir los cursos por nombre; también puedes escribirlo a mano:

```toml
[cursos]
pruebas = 1234
real = 5678
```

Si esa asignatura no tiene curso de pruebas (no hay `pruebas` en `[cursos]` y no
quieres que la sesión lo vuelva a preguntar), borra `pruebas` y añade
`sin_pruebas`:

```toml
[cursos]
real = 5678
sin_pruebas = true
```

Para recuperar el curso de pruebas, cambia esa línea por `pruebas = 1234`.

## Programación en Word

Pide al agente «prepárame la programación de DAM1 para el curso que viene a partir de la
plantilla del departamento». La skill le indica que pida en un solo mensaje la plantilla,
la programación de referencia y lo que falte; que lea ambos con `tiza leer`; que te señale
lo que está desfasado y de dónde sale; y que te pregunte solo lo que decides tú (grupos,
horas, temporalización y los criterios si el departamento no los da).

El resultado es un Word nuevo en la carpeta, con los estilos y el encabezado de tu
plantilla. Al abrirlo, di que sí a actualizar los campos: así el índice queda al día.
Si tu plantilla es un PDF, el agente la rehace en Markdown y usa `tiza documento`.

## Realinear con una copia del curso

Pide al agente «revisa mi programación antigua con la normativa y con mi aula». Te pedirá la
programación antigua y una copia del curso. Esa copia, con `tiza sesion` abierta, la pide el
agente con `tiza copia` y la confirmas tú en tu terminal. Si el aula no te deja hacer copias,
verás `COPIA_NO_PERMITIDA`: hazla a mano.

A mano: en el curso, «Copia de seguridad» (en «Más»), **sin marcar usuarios**. Guárdala en la
carpeta de la asignatura. Si queda también en tu zona de copias de Moodle, bórrala en
«Restaurar» → «Zona de copias de seguridad privadas de usuario». Una copia con datos de alumnos
se rechaza (`COPIA_CON_USUARIOS`).

La copia de un curso que no está en `tiza.toml` (el del año pasado, por ejemplo) no la pide
`tiza copia`: hazla a mano. Si quieres reutilizarla en este curso, el agente la importa con
`--como-nuevas`; sus actividades salen sin vínculo con el aula y se publican como nuevas. Con la
copia de un curso de `tiza.toml`, `--como-nuevas` da `COPIA_DEL_MISMO_CURSO`: se importa sin ella,
para que se publique sobre sus actividades y se avise de lo que cambió en el aula.

Lo que el agente propone llega en una sola lista, agrupada en ley, programación y aula. Tú
aceptas o rechazas por número.

Qué vigila tiza al publicar una actividad que viene de la copia: si su **nombre, su texto o sus
fechas** cambiaron en el aula después de la copia, no la publica (`CAMBIADA_EN_EL_AULA`), te avisa
y sigue con las demás; el agente pide una copia nueva para juntar los cambios. Si ya la importaste
pero tu fichero sigue sin los cambios del aula, tampoco se publica (`CAMBIADA_EN_EL_AULA`): junta
antes lo de `.tiza/copia/<cmid>.html`. Y sin saber cómo estaba (por ejemplo, sin
`.tiza/copia.json`) tampoco (`ORIGEN_SIN_HUELLA`): pide una copia nueva e impórtala.

Qué **no** vigila: las preguntas y los ajustes de un cuestionario (intentos, tiempo, mezclar
respuestas) ni el paquete de una actividad H5P. Si los cambiaste en el aula, díselo al agente: lo
que publique saldrá del fichero. Los archivos adicionales de una tarea no están en el fichero, pero
se conservan en el aula. Si tiza no puede guardar lo que acaba de publicar (`HUELLA_NO_GUARDADA`),
la próxima vez saltará `CAMBIADA_EN_EL_AULA`: pide una copia nueva.

## Varios cursos reales

Si das la misma asignatura en varios cursos de Moodle (1º A, 1º B, 1º C),
`real` admite una lista de 1 a 6 ids, todos distintos y distintos del de
pruebas:

```toml
[cursos]
pruebas = 1234
real = [101, 102, 103]
```

`tiza empezar` y `tiza sesion` te dejan elegirlos de la lista con números
separados por comas (`1,3`), y `--elegir-cursos` (`tiza empezar` y `tiza sesion`)
vuelve a preguntar los cursos aunque ya estén guardados. Una petición de
`publicar --en real` llega a **todos**, en el orden de `tiza.toml`, y te pide una
confirmación **por curso** («Curso 2 de 3: «1º B»»): si dices que no a uno, se
omite y se sigue con el siguiente; si uno falla, se para y el informe dice
cuáles quedaron hechos. Los nombres de los cursos solo los ves tú: el agente
recibe ids, y en `.tiza/estructura.json` (versión 2) una lista con las secciones
de cada curso real. Un `real = 5678` con un solo id funciona como siempre.
Un `.md` puede quedar con un `cmid` distinto en cada curso.

## Calendario y cambio de fechas

Si tienes el calendario escolar, puedes dejarlo en `calendario.toml` de la
carpeta de la asignatura. Todos los campos son opcionales, y no hace falta
ponerlo:

```toml
inicio = 2026-09-08
fin = 2027-06-22
dias_de_clase = ["lunes", "miércoles", "viernes"]
festivos = [
  2026-10-12,
  {desde = 2026-12-21, hasta = 2027-01-07, motivo = "Navidad"},
]
```

Con él, `tiza comprobar` y la confirmación de real avisan cuando una fecha cae en
festivo, en fin de semana, fuera del curso o en un día sin clase. Solo avisan:
un festivo puede ser intencionado. Un calendario que no se puede leer da
`CALENDARIO_INVALIDO` y los documentos se comprueban igual.

Para cambiar solo las fechas de tareas y cuestionarios que ya están en el aula,
usa `--solo-fechas` (con `--en pruebas` o `--en real`). No toca el contenido, las
preguntas, los intentos ni la visibilidad; por eso también sirve para un
cuestionario que ya tiene intentos. En real, la confirmación enseña cada fecha
antes y después. No admite `--visible` ni `--oculto`. Las fechas de un alumno
concreto (prórrogas, excepciones) no las toca tiza.

En una tarea, tiza desactiva siempre «Recordarme calificar antes de» (Moodle
rechaza una entrega posterior a ese recordatorio, y esto también ocurre al
publicar la tarea sin `--solo-fechas`). Si lo tenías puesto, la confirmación de
real lo enseña antes de aplicarlo.

## Ordenar y mover actividades

Lo nuevo se crea al final de su sección. `tiza ordenar <md>… --en pruebas|real` coloca las
actividades de esos ficheros en ese orden: se reparten **los huecos que ya ocupaban**
y lo que no nombras (foros, archivos subidos a mano) no se mueve. Con la sección
`[Foro, test, Archivo, intro, tarea]`, `tiza ordenar intro.md tarea.md test.md` la deja en
`[Foro, intro, Archivo, tarea, test]`. No cambia contenido, visibilidad ni intentos, así
que no exige pasar por pruebas; repetirlo no hace nada. Con varios cursos reales se confirma
curso a curso, enseñando la sección entera; si una actividad falta en un curso, ese curso
falla con `ACTIVIDAD_AUSENTE` antes de mover nada.

Para pasar una actividad a otra sección, cambia `seccion:` en el `.md` y publica: tiza la
**mueve** (mismo cmid, visibilidad, intentos y restricciones) en vez de duplicarla, y la
confirmación de real dice de qué sección a cuál. Si hay dos actividades con el mismo tipo
y nombre, tiza no adivina (`ACTIVIDAD_AMBIGUA`). La confirmación avisa si el orden deja una
actividad encima de otra que debe completarse antes; el orden en pantalla no cambia las
restricciones.

## Prueba de contrato

`tiza autoprueba` publica una página, una tarea, un cuestionario, una
etiqueta y una actividad H5P (de rellenar huecos) temporales en el curso de
pruebas, comprueba que se crean, que H5P arranca, que republicar reutiliza el
mismo cmid, que ordenar y mover entre secciones funcionan y que las imágenes responden, y que las
preguntas del cuestionario quedan en el banco de su propia categoría; después
lo borra todo (también si algo falla). Así se detecta si el aula pierde alguna
librería H5P. Conviene ejecutarla:

- tras instalar `tiza` o actualizar python-moodle;
- al empezar el curso (cada septiembre), por si el aula cambió.

## Instalación: opciones

¿Prefieres que te guíe tu agente de IA? Pásale
[INSTALAR_CON_AGENTE.md](../INSTALAR_CON_AGENTE.md): separa lo que hace el agente
de lo que haces tú en tu terminal, y no avanza sin que el aislamiento esté
resuelto (aplicado o descartado a propósito).

La instalación normal es la línea del [README](../README.md#empezar). Después,
`tiza empezar` hace todo lo demás la primera vez: te pregunta la URL del aula y
tu usuario (no pide contraseña), comprueba el aislamiento, te abre la página de
entrada de tu aula (o, sin ventana, te pide la contraseña una vez), te deja
elegir tus cursos por nombre (se guardan en `tiza.toml`) y lee las secciones. Si
prefieres hacerlo por pasos, `tiza configurar` guarda la URL y el usuario, y
`tiza sesion` abre la sesión.

Aísla tu agente del aula **en la carpeta de la asignatura** (lo explica
[aislamiento.md](aislamiento.md)); `tiza empezar` te ofrece aplicarlo
si detecta que falta:

```bash
tiza aislar     # añade las restricciones a esta carpeta (Claude Code, Codex y opencode; con Copilot, muestra la receta)
tiza revisar    # comprueba que todo está bien (solo lectura)
```

La skill se copia a `~/.claude/skills`, `~/.agents/skills`, `~/.codex/skills` y
`~/.config/opencode/skills` (la app de Copilot la descubre desde
`~/.agents/skills`). Si prefieres leer antes lo que ejecutas, abre
`install.sh` o `install.ps1` en este repositorio; son unas pocas líneas.

Los instaladores instalan la versión etiquetada que indica el
[README](../README.md#empezar); con `TIZA_REF=main`
(o con otra etiqueta) antes de ejecutarlos eliges cuál. No necesitan `git`: una
versión publicada se instala desde el wheel de su release (sin construir nada) y
una rama o un commit, desde el `.zip` de GitHub. Lo único que se instala aparte es
[uv](https://docs.astral.sh/uv/), que trae Python si tu equipo no lo tiene.

En Linux la ventana de entrada trae Qt (cientos de MB), así que no se instala por
defecto: si la quieres, ejecuta el instalador con `TIZA_VENTANA=1` delante
(`curl … | TIZA_VENTANA=1 sh`). Sin ella, `tiza` te pide la contraseña en la
terminal.

Para actualizar, `tiza actualizar` instala la última versión publicada (o la de
`TIZA_REF`, si la defines) y reinstala la skill; conserva la ventana si la tenías. En
Windows la instalación sigue en otra ventana, cuando `tiza` ya se ha cerrado (Windows no deja
reemplazar un programa en marcha): espera a que diga que ha terminado. Además, `tiza empezar` te
avisa cuando hay una versión nueva y te ofrece instalarla. Hasta la
0.5.1, `tiza actualizar` no salía de la etiqueta instalada: desde esas
versiones, vuelve a ejecutar el instalador una vez.

Alternativa desde una copia local, con [uv](https://docs.astral.sh/uv/) ya
instalado:

```bash
git clone https://github.com/balejosg/tiza
cd tiza
uv tool install .
tiza instalar-skill
```

## Desinstalar

1. `uv tool uninstall tiza`.
2. Borra la carpeta `tiza` de `~/.claude/skills`, `~/.agents/skills`,
   `~/.codex/skills` y `~/.config/opencode/skills`.
3. Si quieres borrar también la URL y el usuario guardados, borra la carpeta de
   configuración `tiza` (`~/.config/tiza` en Linux,
   `~/Library/Application Support/tiza` en macOS y
   `%LOCALAPPDATA%\tiza` en Windows).

El aislamiento vive en la carpeta de cada asignatura (`.claude/`, `.codex/`,
`opencode.jsonc`); `tiza aislar` dejó una copia `…antes-de-tiza-…` de cada
fichero que ya existía. En la app de GitHub Copilot, el sandbox se activa a mano
en cada proyecto (Ajustes › Proyectos › Sandbox) y no deja ficheros en la
carpeta. La marca de confianza de Codex está en
`~/.codex/config.toml` y se borra a mano.
