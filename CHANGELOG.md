# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Mientras la versión mayor sea 0, un cambio de versión menor puede romper algo:
se avisa aquí con **Cambia**.

## 0.24.1 — 2026-10-20

### Añadido
- **`tiza rellenar` puede cambiar solo un trozo de texto con la operación `sustituir`** (`id`, `buscar`, `poner`): conserva el formato, los tabuladores, los campos y los controles, así que cambiar «2026/27» por «2027/28» en un encabezado no lo descoloca. El resumen dice cuántas apariciones cambió (`sustituciones`); si el texto no está, `TEXTO_NO_ENCONTRADO`, y si está repartido entre varios trozos, `TEXTO_PARTIDO` (se usa `reemplazar`).

### Corregido
- **`tiza rellenar` ya puede cambiar los encabezados y pies (por ejemplo, el curso): `tiza leer` los muestra con sus ids.** Salen al final de la lectura (`[e1.p1]`, `[pie1.p1]`) y se cambian con las mismas operaciones que el cuerpo; el número de página y lo que no cambies se conservan.
- **`tiza leer` ya no repite el texto de los cuadros de texto**: Word guarda cada cuadro dos veces (para versiones antiguas) y se leía duplicado; en un encabezado salía «C2 – Uso Restringido C2 – Uso Restringido» y en un pie con el número de página en un cuadro, «5454».

## 0.24.0 — 2026-10-19

### Añadido
- **`tiza leer` y `tiza documento`**: el agente lee, sin red, el Word o el PDF de tu programación y escribe un Word sencillo con la unidad. Nunca sobrescribe un Word tuyo.
- **`tiza rellenar`**: el agente rellena una copia de la plantilla Word de tu departamento sin tocar tus estilos, encabezados ni numeración, y el índice se puede actualizar al abrir el Word nuevo (Word pregunta si actualizar los campos; di que sí). Nunca sobrescribe un Word tuyo.
- **`tiza importar`**: convierte una copia de seguridad de tu curso (`.mbz`, hecha sin usuarios) en ficheros de tiza editables, uno por página, tarea, etiqueta, cuestionario (con preguntas de verdadero/falso, opción múltiple, respuesta corta y numérica) o actividad H5P, cada uno con su `origen`. Nunca sobrescribe un fichero tuyo; si la copia es de otro curso o de otra aula, `COPIA_DE_OTRO_CURSO` te dice que pidas `tiza copia real`, y `--como-nuevas` sirve solo para reutilizar otro curso como actividades nuevas, sin vínculo con el aula (con la copia de uno de tus cursos, `COPIA_DEL_MISMO_CURSO`: se importa sin ella). Una copia más antigua que la última importada no cambia nada y lo dice en el `detalle`. Conserva los intentos, el tiempo límite y el mezclado de un cuestionario, y no importa lo que tiza cambiaría al publicarlo (una pregunta con otra puntuación, orden o retroalimentación; un cuestionario con más de 10 intentos): lo marca con su motivo. Una tarea con archivos adicionales se importa, y te avisa de que esos archivos no van en el fichero pero se conservan en el aula (con `--como-nuevas`, el aviso dice que la tarea nueva no los tendrá). El `detalle` de una actividad no se pierde al reimportar. `.tiza/copia.json` guarda una entrada por curso y la fecha de cada copia.
- **`tiza copia`**: el agente le pide a tu sesión abierta que haga una copia de seguridad del curso, sin datos de alumnos, y tú la confirmas en tu terminal. La copia queda en `.tiza/copias/`, lista para `tiza importar`, y tiza la borra de tu zona de copias de Moodle (si no puede, te avisa). Si el aula no te deja hacer copias, la autoprueba lo dice y `tiza copia` responde `COPIA_NO_PERMITIDA`: la copia se hace a mano, como siempre. Máximo 3 copias por sesión.
- **Publicar una actividad importada por su origen**: una actividad que viene de `tiza importar` se actualiza en el aula por su identificador, aunque le hayas cambiado el nombre o la sección en su fichero (la confirmación te dice «Se cambia el nombre de…»), sin duplicarla y sin tocar sus demás ajustes. Si alguien cambió su nombre, su texto o sus fechas en el aula después de la copia, tiza no la publica (`CAMBIADA_EN_EL_AULA`), te avisa y sigue con las demás: pide una copia nueva del curso. Si ya la importaste y tu fichero sigue sin juntar esos cambios, tampoco se publica, y sin la huella de la copia (`ORIGEN_SIN_HUELLA`) tampoco, ni si tiza no puede leer tu fichero para comprobarlo (pide una copia nueva e impórtala). Tras publicar bien, su estado vuelve a `IMPORTADA`. No se comparan las preguntas ni los ajustes de un cuestionario ni el paquete de un H5P: esos se publican como estén en tu fichero. Si la actividad ya no existe en el aula, `ORIGEN_NO_ENCONTRADO`, y dos ficheros del mismo origen no se publican (`ORIGEN_DUPLICADO`). En el curso de pruebas o en otro curso, se busca por sección, tipo y nombre como siempre.
- **Guía del agente para realinear tu programación antigua**: el agente te pide tu copia del curso (la confirmas tú en tu terminal), contrasta la programación con la normativa vigente y con el aula, y te deja una sola lista de propuestas para aceptar por número. Si cambiaste en el aula el nombre, el texto o las fechas de una actividad, tiza no la publica hasta que juntes ese cambio; lo que tiza no compara (preguntas y ajustes de un cuestionario, paquete de un H5P) lo dice la guía.
- **Guía del agente para pasar de tu programación a la unidad**: pide lo que falta en un solo mensaje, contrasta tu programación con la normativa y dice de dónde sale cada referencia.

### Cambia
- **El protocolo entre el agente y la sesión pasa a la versión 6** (para `tiza copia`): una sesión abierta con una versión anterior de tiza responde `SESION_INCOMPATIBLE`; ciérrala y vuelve a abrirla con `tiza empezar`.
- **Publicar muchas imágenes seguidas ya no acaba en `ERROR_SUBIDA`.** Cuando el aula frena las subidas (su límite de ficheros subidos en poco tiempo), tiza espera y reintenta sola; si no basta, responde `AULA_PIDE_ESPERA` y dice que esperes unos minutos.

### Corregido
- **Una hora que no existe se rechaza al comprobar.** La que el reloj se salta en el cambio a la hora de verano (por ejemplo, las 02:30 del último domingo de marzo) da `FECHA_INEXISTENTE` antes de publicar; antes Moodle la movía a las 03:30 y la actividad quedaba creada con otro error. Las horas que se repiten en otoño siguen valiendo.
- **Actualizar una tarea ya no borra sus archivos adicionales.** Antes, publicar de nuevo una tarea que tenía archivos en «Archivos adicionales» los quitaba; ahora tiza reenvía los que ya tiene.
- **En Windows, tiza ya no sigue un enlace simbólico** al leer `calendario.toml`, los ficheros de la asignatura o los documentos de `tiza leer`: se rechaza igual que en Linux y macOS.

## 0.23.0 — 2026-10-18

### Añadido
- **`tiza normativa`**: el agente consulta, sin red, la normativa de la Comunidad de Madrid del curso 2026-27 (ESO, Bachillerato y FP de Desarrollo de Aplicaciones Multiplataforma) y lo que exige de la programación, con código, texto literal y procedencia. La skill le obliga a consultarla antes de citar el currículo. Lo que una norma posterior corrige o renombra (p. ej. STEM4, «Arquitecturas en la nube») cita esa norma y deja el original en `via`.

### Cambia
- **README más corto y pensado para docentes**: qué puedes pedir, cómo funciona y
  cómo empezar. El detalle pasa a `docs/guia.md` (comandos y opciones),
  `docs/formato.md` (formato de los ficheros) y `docs/seguridad.md` (medidas de
  diseño); la API de biblioteca, a `CONTRIBUTING.md`.
- El README y el nuevo `docs/del-curriculo-al-aula.md` explican cómo usar el agente
  para pasar del decreto y la programación didáctica al aula virtual.

## 0.22.0 — 2026-10-16

### Cambia
- **Instalar y actualizar ya no necesitan `git` ni construir nada.** Cada release lleva su
  wheel y los instaladores y `tiza actualizar` lo instalan directamente (si aún no está
  subido, usan el `.zip` de la etiqueta). La última versión se averigua con la redirección
  de la última release de GitHub, sin `git` ni la API (que limita las consultas por IP).
- **En Linux la ventana de entrada ya no se instala por defecto**: trae Qt, que ocupa
  cientos de MB. Para tenerla, ejecuta el instalador con `TIZA_VENTANA=1`; sin ella, la
  contraseña se pide en la terminal. `tiza actualizar` la conserva si ya la tenías.
- `tzdata` solo se instala en Windows (macOS y Linux traen la base de zonas horarias).

## 0.21.0 — 2026-10-16

### Añadido
- **`tiza empezar` ofrece la versión nueva.** Si hay una versión publicada posterior a la
  tuya, lo dice y pregunta si instalarla (`[s/N]`); al terminar, vuelve a abrir la sesión.
  Sin conexión, o si no se puede saber, sigue como siempre. Así, para el día a día basta
  con `tiza empezar` (el aislamiento ya lo ofrecía).

### Cambia
- `tiza actualizar` ya no necesita `git`: instala desde el `.zip` de GitHub, como los
  instaladores, y sin `git` consulta la última versión a la API de GitHub. Desaparece el
  código `GIT_NO_ENCONTRADO`.

## 0.20.3 — 2026-10-16

### Corregido
- **La ventana de entrada en Linux (Qt) ya no cuelga.** `clear_cookies()` mataba el proceso de
  la ventana con SIGTRAP en QtWebEngine y `tiza` caía siempre a la contraseña; se quita (la
  ventana es privada y el proceso termina justo después). Desde 0.20.1; en Windows no se notaba.
- La ventana entrega la sesión antes de cerrarse y, en Linux, el proceso sale entonces mismo
  sin esperar al desmontaje del motor. `tiza` acepta una respuesta válida aunque el proceso
  termine mal.
- Cuando no se puede abrir la ventana, el mensaje dice el motivo (por ejemplo, «la ventana
  terminó con el código -5»).

### Medido
- De principio a fin con el padre y el hijo reales, Qt sin pantalla y un Moodle 4.5 de pruebas:
  el hijo termina con 0 y `tiza` recibe `MoodleSession`. Sin probar: pantalla real y GTK.

## 0.20.2 — 2026-10-16

### Cambia
- En **Linux con escritorio** la entrada al aula también es una ventana (Qt, o GTK si ya
  está), no solo en Windows y macOS. Si no hay escritorio (una sesión por SSH), no hay
  motor o la ventana falla, `tiza` sigue pidiendo la contraseña en la terminal.
- El extra `ventana` trae `pywebview[qt]` en Linux. Los instaladores y `tiza actualizar`
  lo instalan en Linux solo si hay escritorio (`DISPLAY` o `WAYLAND_DISPLAY`); en un
  servidor sin pantalla no se descarga Qt.

### Medido
- Con Qt sin pantalla (`QT_QPA_PLATFORM=offscreen`) contra un Moodle 4.5 de pruebas:
  `get_cookies()` devuelve `MoodleSession` con `HttpOnly`, la cookie abre `/my/` y el cierre
  de sesión la mata. Sin probar: una pantalla real y GTK.

## 0.20.1 — 2026-10-16

### Corregido
- La ventana de entrada ahora se abre: el hijo exigía una terminal en stderr y `tiza` se la
  quitaba al capturarla, así que siempre caía a pedir la contraseña.
- La ventana se da por terminada en `/my` y todo lo que cuelga de él (con el panel
  desactivado, Moodle vuelve a `/my/courses.php`) en vez de esperar hasta el límite.
- Se aceptan las cookies del dominio padre del aula (`sessioncookiedomain`), por
  coincidencia de dominio; la tubería lleva el dominio de cada cookie.
- El resultado de la ventana va por un canal propio: lo que escriban pywebview o el motor ya
  no lo estropea. El título de la ventana enseña el servidor que se está viendo.

### Añadido
- Al terminar, `tiza` cierra la sesión del aula (`Moodle.cerrar`, `publicar.cerrar_aula`,
  `publicar.sesion_del_aula`): la cookie deja de valer. Vale con contraseña y con ventana,
  en `tiza sesion` y en `estructura`, `publicar`, `ordenar` y `autoprueba` directos.

## 0.20.0 — 2026-10-11

### Cambia
- La entrada al aula pasa a ser una ventana con la página de login del aula (Windows y
  macOS): el docente escribe la contraseña allí, tiza no la ve y solo recoge las cookies
  de sesión del servidor del aula. Sin ventana (Linux, sin WebView2, `--sin-ventana` o si
  falla), se pide la contraseña en la terminal como hasta ahora.
- `tiza.sesion.Presencia.pedir_password` se sustituye por `acreditar(url, usuario)`, que
  devuelve `publicar.Contrasena`, `publicar.Cookies` o `None`.
- Se retira `tiza-ventana` (la ventana de sesión con cursos y confirmaciones): esas
  preguntas siguen en la terminal.
- Los instaladores y `tiza actualizar` instalan el extra `ventana` en Windows y macOS
  (con caída a la instalación sin él).

### Añadido
- `--sin-ventana` en `tiza empezar` y `tiza sesion`.
- `publicar.autenticar_con_cookies` y `publicar.autenticar_con`.

## 0.19.1 — 2026-10-11

### Añadido
- Documentación de lanzamiento: `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`,
  plantillas de issue y `docs/proteccion-de-datos.md` (para coordinadores TIC y DPD).

### Corregido
- `primeros-pasos.md` menciona las actividades H5P; la versión de ruff coincide
  con la del CI.

## 0.19.0 — 2026-10-11

### Añadido
- `tiza ordenar <md>… --en pruebas|real` y `agente.ordenar`: dejan las
  actividades en ese orden dentro de su sección sin mover nada más.
- Cambiar `seccion:` en el `.md` y publicar **mueve** la actividad (mismo cmid,
  visibilidad, intentos y restricciones) en vez de duplicarla.
- La autoprueba comprueba ordenar y mover entre secciones.
- Protocolo del buzón 5.

### Corregido
- La finalización se lee del botón de opción marcado, no del primero.

## 0.18.0 — 2026-10-11

### Añadido
- Preguntas de emparejamiento en los cuestionarios.
- Imágenes locales dentro de las preguntas (con texto alternativo obligatorio).

## 0.17.0 — 2026-10-11

### Añadido
- Avisos de fórmulas y comprobación de que el aula las dibuja
  (`FORMULAS_NO_DIBUJADAS`); las fórmulas se rechazan en H5P (`FORMULA_EN_H5P`).

## 0.16.1 — 2026-10-10

### Añadido
- Fórmulas LaTeX en el contenido y ejemplo de unidad completa de seis piezas.

### Corregido
- Los iframes de Educaplay se publican (el dominio era un resto del renombrado).

## 0.16.0 — 2026-10-10

### Añadido
- Finalización de actividades y restricciones de acceso en el frontmatter
  (itinerario).

## 0.15.0 — 2026-10-10

### Añadido
- Publicar la misma carpeta en varios cursos reales, con confirmación por curso.

## 0.14.0 — 2026-10-10

### Añadido
- Calendario escolar (`calendario.toml`) con avisos de festivos y fines de semana.
- Fechas antes y después en la confirmación y `publicar --solo-fechas`.

## 0.13.0 — 2026-10-08

### Añadido
- Actividades H5P: generadas desde el `.md` (huecos, arrastrar palabras, marcar
  palabras y tarjetas) y paquetes `.h5p` subidos sin librerías ni JavaScript.
- La autoprueba cubre H5P.

## 0.12.0 — 2026-10-08

### Añadido
- La app de GitHub Copilot como agente de tiza (`tiza aislar` y `tiza revisar`).
- `SIN_SESION` avisa cuando el agente trabaja en un worktree.

### Corregido
- El instalador de uv ya no cierra la ventana de PowerShell; los instaladores
  no necesitan `git`.

## 0.11.0 — 2026-10-07

### Cambia
- Los cursos viven solo en el `tiza.toml` de cada carpeta; la configuración
  global guarda únicamente la URL del aula y el usuario.

## 0.10.1 — 2026-10-07

### Corregido
- La URL del aula funciona aunque redirija a la barra final por http.
- La ventana se instala desde GitHub y `tiza actualizar` la conserva.

## 0.10.0 — 2026-10-07

Primera versión pública: páginas, etiquetas, tareas y cuestionarios; sesión del
docente con buzón de ficheros; puerta de real; filtro de HTML en lista blanca;
`tiza aislar`.
