# tiza — publica páginas, etiquetas, tareas y cuestionarios en tu aula virtual con ayuda de un agente de IA

> **Proyecto independiente y no oficial.** No está afiliado a Moodle ni a
> ninguna administración educativa, y su Delegación de Protección de Datos no lo
> ha evaluado ni autorizado. Úsalo bajo tu responsabilidad y respeta las normas
> de tu centro y las del aula virtual que uses.

`tiza` es una CLI y una skill portables para que docentes con un aula virtual
Moodle preparen y publiquen **páginas, etiquetas, tareas y cuestionarios** en sus propios
cursos con rol de profesor, usando cualquier agente (Claude Code, Codex,
opencode…). Está pensada con dos ideas:

1. **El agente no toca la sesión del aula**: escribe y comprueba el contenido;
   para publicar deja una petición en un buzón de ficheros que atiende la sesión
   que el docente abre con `tiza sesion`.
2. **Del aula solo sale lo mínimo hacia el agente**: el informe que lee solo
   contiene nombres de *tus* ficheros, cmid, códigos de resultado, fechas, URLs
   montadas por la herramienta y los nombres de las secciones. Nunca HTML ni
   otros textos de Moodle.

**¿Eres docente y empiezas?** Lee [docs/primeros-pasos.md](docs/primeros-pasos.md):
qué necesitas, cómo instalarlo y tu primer día, en una página.

Necesitas:

- al menos un curso en el que seas profesor: el **real**, con tu alumnado. Si
  además tienes un curso **de pruebas**, todo se prueba primero ahí y solo lo
  verificado se publica en real; si no lo tienes, también puedes trabajar: en
  real solo se publica **oculto** y cada publicación se confirma con un resumen
  corto. Si quieres un curso de pruebas, pídeselo a quien administra el aula
  virtual de tu centro;
- un agente de IA que trabaje en la terminal. Claude Code y Codex necesitan una
  suscripción de pago o una clave de API; opencode es gratuito, pero hay que
  conectarlo a un proveedor de modelos.

Funciona en Windows, macOS y Linux. La base es
[python-moodle](https://pypi.org/project/python-moodle/) (MIT), que crea y
edita actividades con la misma sesión web que usas en el navegador.

## Medidas de diseño

Son medidas para reducir riesgos, no garantías absolutas.

- **Sin secretos persistentes**: la contraseña se pide con `getpass` una vez por
  sesión. No hay variable de entorno, opción ni fichero que la acepte, y la
  sesión vive en memoria y se descarta al cerrar `tiza sesion`.
- **Presencia humana**: el agente solo publica mientras el docente mantiene
  abierta `tiza sesion` en esa carpeta; la sesión caduca sola (se puede ampliar
  respondiendo en la terminal, hasta 8 horas) y puede cerrarse
  con Ctrl+C. Al abrirla se muestran los cursos de destino **por su nombre** y
  se pide confirmación `[s/N]`, y **cada publicación en el curso real se
  confirma** en la terminal del docente.
- **Contraseña solo hacia tu aula**: escribes la URL al configurar (por ejemplo
  `https://aula.ejemplo.org/<centro>`) y queda fijada: se rechazan las URLs que
  `urlsplit` y `requests` leen distinto, y una redirección a otro servidor o
  puerto falla con `URL_REDIRIGE_FUERA`. Se muestra el servidor antes de pedir
  la contraseña, se envía una sola vez (sin token móvil) y cada petición de la
  sesión del aula, redirecciones incluidas, se comprueba antes de salir: nada va
  a otro servidor. Los cursos de pruebas y real no pueden coincidir.
- **Puerta de real**: dentro de `tiza sesion`, solo se publica en real lo que
  esa misma sesión ha publicado antes en pruebas (`verificados.json` lo puede
  escribir el agente, así que no se fía de él). La confirmación `[s/N]` lista
  también los enlaces externos del contenido.
- **Sin curso de pruebas**: si falta `pruebas` en `[cursos]`, no hay
  verificación previa ni vista que enseñar. Al abrir la sesión se avisa y se
  pide confirmación (para que la marca `sin_pruebas` no pase en silencio); se
  compensa publicando en real solo **oculto** (la petición debe pedir
  `--oculto`; lo demás se rechaza con `SOLO_OCULTO_SIN_PRUEBAS`) y con una
  confirmación corta: curso, documentos, tipo y secciones nuevas, sin vista
  previa (si un documento ya existe, avisa de que se ocultará si estaba
  visible). Tampoco hay autoprueba (`SIN_CURSO_PRUEBAS`).
- **Salida en lista blanca**: el informe `.tiza/informe.json` pasa por un
  esquema cerrado; las excepciones de python-moodle se reducen a códigos.
- **Pantalla del docente saneada**: los textos que vienen del agente o del aula
  (títulos, secciones, enlaces, nombres de curso) se muestran sin caracteres de
  control, para que nadie pueda reescribir la confirmación. Los nombres de curso
  nunca se escriben en `.tiza/`.
- **Carpeta de trabajo hostil**: lo que `tiza sesion` lee y escribe en `.tiza/`
  se trata como escrito por el agente. No abre FIFO ni sigue enlaces simbólicos,
  no lee peticiones de más de 64 KiB, descarta un JSON anidado en exceso en vez
  de caerse y se niega a usar `.tiza` o `.tiza/buzon` si son enlaces
  (`DIRECTORIO_NO_SEGURO`).
- **Vista previa fiable**: la vista previa de la confirmación en real la escribe
  la sesión en un directorio privado de la caché de tu usuario (permisos 0700),
  no en la carpeta donde escribe el agente, y cada documento tiene la suya (dos
  con el mismo nombre de fichero no se pisan): lo que revisas es lo que se
  publica. La de `tiza comprobar` sigue en `.tiza/preview/`, pero tampoco se
  escribe a través de enlaces simbólicos.
- **Contenido seguro**: el HTML se valida con una lista blanca sobre el árbol que
  construye un navegador (html5lib), y lo que se publica es ese árbol validado.
  Se admiten las etiquetas de texto, listas, tablas, enlaces, imágenes y
  estructura; `style` solo con propiedades de maquetación (sin `position`,
  `url()`, valores negativos…); `class` solo de una lista cerrada de Bootstrap; e
  `<iframe>` solo por `https` desde una lista cerrada de servidores (YouTube,
  Vimeo, Genially, Canva, Wordwall, Educaplay, LearningApps, GeoGebra y PhET),
  que se publican con `sandbox` y, el de YouTube, sin cookies.
  Se rechaza el resto —scripts, formularios, SVG, `<style>`, `<meta>`,
  comentarios, atributos `on*`— y cualquier URL que no sea `http(s)`, una ruta
  local, un ancla, `mailto:` o una imagen `data:` PNG, JPEG, GIF o WebP. La
  confirmación de real lista todas las URL externas y todo lo incrustado.
- **Recursos acotados**: solo se suben ficheros de dentro de la carpeta de la
  asignatura, que no sean ocultos (`.git/config`, `.env`…) ni `tiza.toml`, de
  hasta 200 MB (el `.md` o `.html`, hasta 2 MB). Se comprueba antes de mirar si
  el fichero existe, así que el agente no puede averiguar qué hay fuera de su
  carpeta (`RUTA_FUERA_DE_CARPETA` en los dos casos).
- **Límite en pruebas**: como mucho 50 documentos publicados en pruebas por sesión
  (`LIMITE_PUBLICACIONES`); los recursos se copian una vez y se comprueba su hash,
  así que cambiarlos después de la confirmación da `FICHERO_MODIFICADO`.
- **Respeto al aula**: un único intento de login por ejecución, sin reintentos,
  y peticiones secuenciales con una pausa corta.

El riesgo ajeno a la herramienta (un agente leyendo el perfil del navegador o
Descargas) se cubre con [docs/aislamiento.md](docs/aislamiento.md), con
configuración lista para copiar en Claude Code, Codex y opencode.

## Datos del alumnado: regla de oro

**Nunca escribas nombres, notas, datos de salud ni ninguna información de
alumnos en el prompt, en los `.md` ni en carpetas que vea el agente.** Para
publicar, `tiza` no necesita esos datos, y los proveedores de IA no están
autorizados por tu administración educativa para tratarlos. Tampoco hagas
capturas o vídeos de la herramienta donde aparezcan alumnos. Si dudas, consulta
antes con la dirección de tu centro o con la Delegación de Protección de Datos
de tu administración educativa.

## Instalación

¿Prefieres que te guíe tu agente de IA? Pásale
[INSTALAR_CON_AGENTE.md](INSTALAR_CON_AGENTE.md): separa lo que hace el agente de lo
que haces tú en tu terminal, y no avanza sin que el aislamiento esté resuelto
(aplicado o descartado a propósito).

Pega una línea en tu terminal (instala `uv` si falta, `tiza` y la skill):

```bash
# macOS / Linux
curl -LsSf https://raw.githubusercontent.com/balejosg/tiza/main/install.sh | sh
```

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/balejosg/tiza/main/install.ps1 | iex
```

Para trabajar, en la carpeta de la asignatura ejecuta:

```bash
tiza empezar
```

La primera vez te pregunta la URL del aula y tu usuario (no pide contraseña);
después comprueba el aislamiento, te pide la contraseña una vez, te deja elegir
tus cursos por nombre (se guardan en `tiza.toml`) y lee las secciones. Si
prefieres hacerlo por pasos, `tiza configurar` guarda la URL y el usuario, y
`tiza sesion` abre la sesión.

Y aísla tu agente del aula **en la carpeta de la asignatura** (lo explica
[docs/aislamiento.md](docs/aislamiento.md)); `tiza empezar` te ofrece aplicarlo
si detecta que falta:

```bash
tiza aislar     # añade las restricciones a esta carpeta (Claude Code, Codex y opencode)
tiza revisar    # comprueba que todo está bien (solo lectura)
```

La skill se copia a `~/.claude/skills`, `~/.agents/skills`, `~/.codex/skills` y
`~/.config/opencode/skills`. Si prefieres leer antes lo que ejecutas, abre
`install.sh` o `install.ps1` en este repositorio; son unas pocas líneas.

Los instaladores instalan la versión etiquetada `v0.10.1`; con `TIZA_REF=main`
(o con otra etiqueta) antes de ejecutarlos eliges cuál. Para actualizar,
`tiza actualizar` instala la última versión publicada (o la de `TIZA_REF`, si
la defines) y reinstala la skill; necesita `git`, como el instalador. Hasta la
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

### Desinstalar

1. `uv tool uninstall tiza`.
2. Borra la carpeta `tiza` de `~/.claude/skills`, `~/.agents/skills`,
   `~/.codex/skills` y `~/.config/opencode/skills`.
3. Si quieres borrar también la URL y el usuario guardados, borra la carpeta de
   configuración `tiza` (`~/.config/tiza` en Linux,
   `~/Library/Application Support/tiza` en macOS y
   `%LOCALAPPDATA%\tiza` en Windows).

El aislamiento vive en la carpeta de cada asignatura (`.claude/`, `.codex/`,
`opencode.jsonc`); `tiza aislar` dejó una copia `…antes-de-tiza-…` de cada
fichero que ya existía. La marca de confianza de Codex está en
`~/.codex/config.toml` y se borra a mano.

## Uso

| Comando | Quién | Qué hace |
|---|---|---|
| `tiza empezar [--minutos 60]` | docente | Todo en uno: configura si hace falta, revisa el aislamiento, abre la sesión, autoprueba si toca y lee la estructura |
| `tiza configurar` | docente | Guarda la URL y el usuario; los cursos (opcionales) se eligen por nombre al abrir `tiza sesion` |
| `tiza instalar-skill` | docente | Instala la skill portable en los agentes |
| `tiza actualizar` | docente | Instala la última versión publicada de `tiza` y reinstala la skill |
| `tiza comprobar <fichero>…` | agente | Offline: valida `.md` o `.html`, genera `.tiza/preview/*.html` y comprueba la sección en `.tiza/estructura.json` |
| `tiza sesion [--minutos 60]` | docente | Autenticado: abre la sesión (un único login) para que el agente publique mientras siga abierta |
| `tiza estructura` | agente o docente | Con `tiza sesion` abierta (o terminal del docente): guarda las secciones de los cursos configurados |
| `tiza publicar <md>… --en pruebas` | agente o docente | Con `tiza sesion` abierta (o terminal del docente): crea (oculto) o actualiza (conserva la visibilidad), verifica y registra el hash |
| `tiza publicar <md>… --en real` | agente o docente | Igual, pero cada petición se confirma `[s/N]` en la terminal del docente y solo publica lo verificado; sin curso de pruebas, exige `--oculto` y la confirmación es corta |
| `tiza-ventana --carpeta <carpeta>` | docente | Abre la sesión en una ventana en lugar de en la terminal (extra `ventana`: `uv tool install --force "tiza[ventana] @ git+https://github.com/balejosg/tiza@v0.10.1"`; `tiza actualizar` lo conserva). La contraseña solo se escribe ahí; cada publicación en real se confirma con un botón |
| `tiza autoprueba` | docente | Prueba de contrato completa en el curso de pruebas: publica, republica, verifica y borra (si no hay curso de pruebas, responde `SIN_CURSO_PRUEBAS`) |
| `tiza aislar` | docente | Añade el aislamiento a esta carpeta: Claude Code y Codex (con `--global`, a todos tus proyectos); con copia de seguridad |
| `tiza revisar` | agente o docente | Solo lectura: comprueba el aislamiento de esta carpeta y avisa si es global |

Cuando algo falla, `tiza` muestra el código (por ejemplo `SESION_CADUCADA`) y
una línea «Qué hacer» con el siguiente paso. Si no se arregla, abre una
[*issue*](https://github.com/balejosg/tiza/issues) con la orden que
ejecutaste, tu sistema y el código y la línea «Qué hacer» copiados tal cual.
No adjuntes capturas del aula (pueden salir alumnos) ni tu contraseña.

### Flujo con un agente

1. En **tu** terminal, dentro de la carpeta de la asignatura:

   ```bash
   tiza empezar
   ```

   La primera vez te pregunta la URL del aula y tu usuario. Después comprueba
   que el agente está aislado; si falta, te ofrece aplicar el aislamiento a esta
   carpeta ahí mismo. Luego te pide la contraseña (una vez), te deja elegir tus
   cursos de pruebas y real por su nombre, pasa la autoprueba cuando toca (al
   estrenar versión o cada septiembre) y lee las secciones. Déjala abierta.
2. En la terminal del agente, pídele el contenido. El agente lo escribe, lo
   comprueba con `tiza comprobar` y lo publica en pruebas.
3. Revisa el enlace «Ver en el aula» en el curso de pruebas.
4. Cuando te guste, pídele que lo publique en real. En tu terminal verás qué se
   publica, dónde y con qué fechas, y confirmarás con `s`. Si no tienes curso de
   pruebas, pídele que lo publique «oculto» (`tiza publicar … --en real
   --oculto`): verás un resumen corto y quedará oculto para el alumnado.

`tiza sesion`, `tiza configurar`, `tiza autoprueba` y `tiza estructura`
siguen disponibles para hacer cada paso por separado.

Mientras la sesión esté abierta, no entres al aula con el mismo usuario desde el
navegador: el aula puede cerrar la sesión anterior. Si ocurre, `tiza`
responde `SESION_CADUCADA` y la sesión se cierra; vuelve a abrirla.

El buzón `.tiza/buzon/` solo usa ficheros (ni red ni sockets), así que funciona
dentro de los sandboxes de los agentes. Sin sesión abierta, `publicar` y
`estructura` fallan con `SIN_SESION` y nunca piden la contraseña.

La skill contiene el flujo completo y las reglas (no conectarse al servidor del
aula, no manejar la contraseña, no leer perfiles de navegador…).

## Formato de los ficheros

Frontmatter YAML + Markdown (`.md`) o HTML (`.html`). En un `.md` la sangría no
crea bloques de código (el código va entre ```), así que el HTML sangrado se
publica como HTML. Los recursos locales se suben solos:

```markdown
---
tipo: pagina
nombre: Repaso de fracciones
seccion: 3
---

## Repaso

Practica con **fracciones**: ![foto](img/foto.png) o [apuntes](apuntes.pdf).
```

Para una tarea:

```markdown
---
tipo: tarea
nombre: Problemas de fracciones
seccion: 3
apertura: 2026-10-01
entrega: 2026-10-10
limite: 2026-10-15
---

Resuelve los problemas.
```

Para un cuestionario, las preguntas van en la cabecera y el cuerpo es la
descripción (mira [`ejemplos/cuestionario.md`](ejemplos/cuestionario.md)):

```markdown
---
tipo: cuestionario
nombre: Repaso tema 3
seccion: 3
intentos: 2            # opcional: de 1 a 10 o «ilimitados»; por defecto 1
tiempo_limite: 30      # opcional, en minutos
preguntas:
  - tipo: opcion_multiple
    enunciado: ¿Cuánto es **2 + 2**?
    opciones:
      - {texto: "4", correcta: true}
      - {texto: "5"}
  - tipo: verdadero_falso
    enunciado: El agua hierve a 100 °C a nivel del mar.
    respuesta: verdadero
  - tipo: respuesta_corta
    enunciado: Capital de Francia
    aceptadas: [París, Paris]
  - tipo: numerica
    enunciado: π con dos decimales
    valor: 3.14
    tolerancia: 0.005
---

Cuestionario de repaso del tema 3.
```

Para un texto o una imagen breve que se vea directamente en la página del
curso, sin abrirse aparte, usa una **etiqueta** (el «Área de texto y medios» de
Moodle). Admite el mismo Markdown/HTML y los mismos recursos que una página
(mira [`ejemplos/etiqueta.md`](ejemplos/etiqueta.md)):

```markdown
---
tipo: etiqueta
nombre: Bienvenida al tema 3
seccion: 3
---

## Bienvenida

Este tema empieza hoy: ![foto](img/foto.png)
```

Para maquetar con estilo, o para pegar HTML hecho en otra herramienta, usa un
fichero `.html` con el mismo bloque YAML y, debajo, HTML (un fragmento o un
documento completo: solo se publica el `<body>`). Mira
[`ejemplos/maquetado.html`](ejemplos/maquetado.html): estilos, clases de
Bootstrap y un iframe de cada grupo. Si algo no se admite, `tiza comprobar` da
`HTML_PELIGROSO` y dice qué sobra. Los iframes de Genially, Canva o LearningApps
suelen traer `position:absolute` o atributos antiguos; sustitúyelos por:

```html
<iframe src="https://view.genially.com/…" title="Descripción"
        style="width:100%;aspect-ratio:16/9;border:0" allowfullscreen></iframe>
```

- `seccion` es el **nombre** de la sección (`seccion: "Fracciones"`) o su número en
  `.tiza/estructura.json`. Por nombre es lo recomendable: sirve igual en el
  curso de pruebas y en el real aunque tengan secciones distintas, y si no existe
  se **crea oculta** al publicar (en el real, el docente lo confirma `[s/N]`).
  No uses el id que aparece en la URL del aula: `tiza comprobar` lo detecta.
  El nombre se pone con el editor del formato del curso (Temas, Semanas…);
  `tiza autoprueba` comprueba que funciona en tu curso de pruebas.
- Si el `nombre` contiene `: ` (dos puntos y espacio), escríbelo entre comillas:
  `nombre: "Ejemplo: repaso"`.
- Las fechas aceptan `AAAA-MM-DD` o `AAAA-MM-DD HH:MM` (hora del aula, con
  `Europe/Madrid` por defecto; sin hora,
  `apertura` empieza a las 00:00 y `entrega` y `limite` acaban a las 23:59) y
  deben cumplir `apertura < entrega < limite`. `entrega` es la «Fecha de
  entrega» de Moodle: después se siguen admitiendo entregas, marcadas con
  retraso. `limite` es la «Fecha límite»: a partir de ella ya no se admiten
  entregas. Es opcional; sin ella, se admiten entregas con retraso sin fin.
- Un cuestionario admite además `apertura`, `cierre` y `mezclar_respuestas`, y
  de 1 a 100 preguntas de cuatro tipos: `opcion_multiple` (de 2 a 10 opciones),
  `verdadero_falso`, `respuesta_corta` y `numerica`. Cada pregunta puede llevar
  `retro` (retroalimentación) y vale 1 punto; tiza calcula las puntuaciones.
  No hay preguntas de ensayo ni de emparejamiento: para respuestas abiertas,
  usa una tarea. Las preguntas no admiten imágenes ni ficheros locales
  (`RECURSO_EN_PREGUNTA`); ponlos en la descripción.
- Cuando un alumno empieza un intento, tiza ya no cambia ese cuestionario
  (`CUESTIONARIO_CON_INTENTOS`): revisa bien las respuestas correctas antes de
  publicarlo en el curso real y, para corregirlo después, crea otro con un
  `nombre` distinto.
- Si ya existe una página, etiqueta, tarea o cuestionario con el mismo `nombre`
  en esa sección, se actualiza (mismo cmid) **y conserva su visibilidad**; si no,
  se crea oculto. `--visible` lo muestra al alumnado y `--oculto` lo oculta,
  exista o no.
- Hay ejemplos completos en [`ejemplos/`](ejemplos/).

### `tiza.toml` por asignatura

Cada carpeta de contenido puede tener un `tiza.toml` con los ids de curso de
esa asignatura, que sobreescriben la configuración global (lo crean `tiza
empezar` o `tiza sesion` la primera vez; también puedes escribirlo a mano):

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

## Prueba de contrato

`tiza autoprueba` publica una página, una tarea, un cuestionario y una
etiqueta temporales en el curso de pruebas, comprueba que se crean, que
republicar reutiliza el mismo cmid y que las imágenes responden, y que las
preguntas del cuestionario quedan en el banco de su propia categoría; después
lo borra todo (también si algo falla). Conviene ejecutarla:

- tras instalar `tiza` o actualizar python-moodle;
- al empezar el curso (cada septiembre), por si el aula cambió.

## Uso como biblioteca

Además de la CLI, `tiza` ofrece dos módulos para quien construye una interfaz
propia (por ejemplo, una app con un asistente embebido):

- `tiza.agente`, el lado del agente, sin consola ni conexión con el aula:
  - `comprobar(carpeta, ficheros)` valida sin red;
  - `estructura(carpeta)` y `publicar(carpeta, ficheros, entorno)` piden por el
    buzón a la sesión del docente y devuelven el informe del esquema cerrado;
    aceptan `cancelar`, un `threading.Event`;
  - `estado_sesion(carpeta)` dice si hay sesión y hasta cuándo;
  - `formato_documento()` devuelve el formato de los `.md`.
- `tiza.sesion`, el lado del docente. `abrir(carpeta, presencia, minutos=60)`
  abre la sesión y atiende el buzón. `presencia` es cualquier objeto que cumpla
  `tiza.sesion.Presencia`; la CLI usa `tiza.terminal.PresenciaTerminal`.

La contraseña solo la pide la presencia y solo la usa `tiza.sesion`. Cambiar
la firma de una de estas funciones obliga a subir la versión menor y a contarlo
en las notas de la versión.

## Desarrollo

Requiere Python 3.11 o superior:

```bash
uv sync --extra dev
uv run pytest        # tests 100 % offline, nunca contactan con un aula real
uv run tiza --help
```

Antes de subir cambios: `uvx ruff@0.16.10 check src tests`,
`uvx ruff@0.16.10 format --check src tests` y
`uv run --with mypy==2.4.0 --with types-PyYAML --with types-requests mypy`.

La integración real con el aula la comprueba el docente con `tiza autoprueba`.
El CI (`.github/workflows/ci.yml`) corre los tests en Ubuntu, Windows y macOS
sin ninguna petición de red.

## Aviso y licencia

Proyecto independiente y no oficial: no está afiliado a Moodle ni a ninguna
administración educativa; úsalo bajo tu responsabilidad y respetando las normas
de tu centro y del aula virtual que uses. No compartas tu contraseña y no
incluyas datos del alumnado en lo que publicas ni en lo que ve el agente.
Licencia [MIT](LICENSE).
