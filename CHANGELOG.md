# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Mientras la versión mayor sea 0, un cambio de versión menor puede romper algo:
se avisa aquí con **Cambia**.

### Añadido
- **El agente recuerda tus preferencias.** Si dejas un `preferencias.txt` en la carpeta de la asignatura (tono, maqueta, tareas, material, lo que no quieres), el agente lo lee al empezar y lo aplica sin saltarse las reglas. Te propone la línea cuando corriges lo mismo dos veces y la apunta solo si dices que sí. `ejemplos/preferencias.txt` es un modelo.
- **Material de otros con su autoría.** Una guía nueva enseña al agente qué preguntar antes de usar una imagen, un texto, un vídeo o un ejercicio que no es suyo ni del docente: autor, fuente y licencia, cómo citarlos en el pie de la imagen y qué permite cada licencia. El material lo trae el docente; el agente no descarga ni inventa direcciones.

## 0.35.0 — 2026-10-26

### Añadido
- **Material y tests para toda la clase.** La skill trae una guía nueva que el agente sigue siempre: cada idea de más de una forma, glosario «Palabras de esta página», tareas con varias formas de entrega y los mismos criterios, preguntas que explican cada opción y nada pensado para un alumno concreto. Los ejemplos de la unidad la siguen.

## 0.34.0 — 2026-10-26

### Cambiado
- **Mejor maqueta al publicar Markdown.** Los títulos se adaptan al nombre de la actividad (`##` pasa a `h3`), las tablas salen con bordes y rayado, y los bloques de código, en un recuadro legible. Los `.html` no se tocan. La guía de la skill trae plantillas de página y de tarea para copiar y rellenar.

## 0.33.0 — 2026-10-26

### Añadido
- **Botones con verbo en el panel.** Cada confirmación dice lo que hace («Publicar en este curso», «Saltar este curso», «Conservar los cambios del aula»…) y las decisiones de riesgo se distinguen por color; en las peligrosas, la opción segura va primero.
- **Cuenta atrás y estado de la sesión en el panel.** La cabecera enseña una insignia con los minutos que quedan, los pasos del arranque y una cuenta atrás en la pantalla de ampliación.
- **Volver a empezar sin cerrar el panel.** Las pantallas finales ofrecen «Volver a empezar» y vuelven a la elección de carpeta en la misma ventana.
- **Recientes más claras.** Las carpetas con el mismo nombre llevan una pista de su carpeta madre y se pueden quitar con «Quitar».
- **Registro con hora y copia.** Cada línea lleva la hora, los errores dicen «Error:» y un botón copia el registro si el portapapeles está disponible.
- **Validación visible en el panel.** Los campos mal escritos o vacíos explican qué pasa y no se envía nada; Enter envía el formulario cuando los botones ya están habilitados.
- **Cierre de sesión en dos pasos.** «Cerrar la sesión y salir» pide confirmación en la cabecera.

### Cambiado
- El panel usa modo oscuro si Windows lo pide, respeta el movimiento reducido y cabe mejor en la ventana mínima.
- Las confirmaciones largas llevan la pregunta y los botones en una barra fija, y el registro se pliega mientras hay una pregunta pendiente.

## 0.32.0 — 2026-10-26

### Cambiado
- **Nueva imagen de tiza en el panel de Windows.** La cabecera es una pizarra oscura con el logo y el resto del panel usa papel claro, azul lápiz y coral; el acceso del menú Inicio, la ventana del panel y la ventana de entrada al aula llevan el icono de tiza.

## 0.31.0 — 2026-10-25

### Corregido
- Si un fichero con «:» en el nombre ya estaba en el registro de lo publicado y su actividad se vuelve a publicar (por ejemplo, porque se recreó en el aula), el registro apunta ahora a la actividad nueva en vez de quedarse con la anterior.
- Al publicar una actividad importada (con `origen`), el registro de lo publicado se queda con la versión que acaba de publicar tiza. Si luego quitas el `origen` del fichero, la siguiente publicación no te pregunta por un cambio del aula que ya no existe.
- Si tiza no puede guardar la huella de la copia tras publicar (por ejemplo, porque `copia.json` ya no está), ahora te avisa de que la próxima vez pedirá una copia nueva, en vez de callarse.

## 0.30.0 — 2026-10-24

### Añadido
- **Panel sin consola para Windows.** En Windows puedes abrir «tiza» desde el menú Inicio sin ninguna ventana de consola: elige la carpeta de la asignatura (las recientes o una nueva), configura el aula la primera vez, entra en la página de login de tu aula en una ventana propia, elige los cursos por nombre y pasa la autoprueba. Mientras trabajas, el panel queda abierto y, cuando el agente pide publicar en real, se pone delante con el mismo resumen que la terminal y los botones Sí/No.
- **Accesos «tiza».** `install.ps1` y `tiza actualizar` crean un acceso «tiza» en el menú Inicio y otro en el escritorio, sin permisos de administrador.
- **Actualizar desde el panel.** Si hay una versión nueva, el panel la ofrece, la instala en segundo plano, vuelve a abrirse y dice si se actualizó. Su log está en `%LOCALAPPDATA%\tiza\tiza\actualizar.log`.
- **El agente no puede abrir el panel.** El perfil de permisos de Windows de `tiza aislar` deniega lanzar el panel, y sin aislamiento de la carpeta el panel no abre la sesión.

### Cambia
- `tiza.sesion.Presencia` (la API pública) gana métodos para el arranque (configurar, confirmar la actualización, la carpeta y el aislamiento). `tiza empezar` usa el mismo flujo y su salida en la terminal no cambia.

## 0.29.2 — 2026-10-24

(La 0.29.1 no llegó a publicarse: sus cambios van aquí.)

### Corregido
- Con `--solo-fechas`, una actividad que tiza publicó y cuyas fechas ya estaban escritas en el aula (un intento anterior que no llegó a comprobarse) ya no te pregunta si sobrescribir.
- `tiza copia real --actividad` con dos ficheros que apuntan a la misma actividad hace una sola copia, la cuenta una sola vez y el informe lo dice.
- `tiza estructura --cambios` guarda la estructura del curso aunque el resumen de la importación (`.tiza/copia.json`) esté dañado.
- `tiza importar` reconoce el `origen` de un fichero guardado con finales de línea de Windows, y no toca el registro de lo publicado si no pudo escribir su resumen.
- La copia de lo último publicado se cambia entera de una vez: nunca queda una mitad nueva y otra vieja.
- El registro de lo publicado es más estricto con lo escrito a mano (cursos con ceros delante, `version` 1.0) y no anota rutas con «:»; los registros que escribió tiza se siguen leyendo igual.
- Si no se puede guardar la copia de lo último publicado (por ejemplo, un antivirus la bloquea un momento en Windows), no queda una de una publicación anterior que el agente pudiera tomar por la última.
- Una subcarpeta de la asignatura que sea un enlace a otro disco sigue usando el registro de lo publicado.
- `tiza copia real --actividad` rechaza al instante una petición que no cabe en el cupo, sin consultar el aula.

## 0.29.0 — 2026-10-24

### Añadido
- **Renombrar una actividad no la duplica.** Tras publicar, tiza anota en `.tiza/publicados.json` qué actividad es cada fichero en cada curso. Si cambias `nombre:` y vuelves a publicar, se actualiza la misma actividad (mismas entregas y notas) y la confirmación de real dice «Se cambia el nombre de «A» a «B»». Si la actividad ya no está en el aula, la confirmación avisa («Ya no está en el aula: se creará de nuevo.») y se crea otra. Si no se puede anotar, tiza avisa de que renombrar podría crear otra.
- **tiza no pisa lo que retocas a mano en el aula.** Al publicar en un curso real, tiza guarda cómo quedó cada actividad (nombre, texto y fechas). Si la próxima vez ha cambiado en el aula, después de tu sí a la confirmación de siempre te pregunta, con la lista de esas actividades, «¿Sobrescribirlas y perder esos cambios? [s/N]» (por defecto no). Con no, esas no se publican y el resto del lote sigue; con sí se publican y el informe lo deja anotado. Solo en cursos reales, también con `--solo-fechas`; el agente no puede pedir sobrescribir. Si tiza no puede releer el aula tras publicar, avisa de que no podrá comparar la próxima vez.
- **`tiza importar` reconoce lo que publicó tiza.** Una actividad que tiza ya publicó y cuyo fichero sigue ahí ya no se duplica en `aula/`: si no ha cambiado en el aula queda como publicada por tiza, y si ha cambiado, la versión del aula queda en `.tiza/copia/<cmid>.html` para juntar los cambios (y, hasta que toques tu fichero, publicar en real pregunta antes de pisarla). Con un registro dañado, `PUBLICADOS_INVALIDO` y no se escribe nada; `--como-nuevas` no mira el registro.
- **`tiza estructura --cambios <fichero>…`** dice, en cada curso real, si retocaste a mano en el aula esas actividades desde la última vez que tiza las publicó o importó (`cambiada`, `sin_cambios` o `sin_registro`, si tiza no tiene con qué comparar). Solo lee. Sin `--cambios` no cambia nada.
- **`tiza copia real --actividad <fichero>`** pide una copia de seguridad de una sola actividad (repite la opción para varias): más rápida que la del curso entero, con una confirmación que lista las actividades y hasta 20 por sesión. Solo en cursos reales y de actividades que tiza ya conoce. `tiza importar` acepta esa copia y solo cambia la entrada de esa actividad.
- **Guía del agente para mejorar lo ya publicado.** Antes de editar algo que ya está en el aula, el agente mira si lo retocaste a mano, trae la versión del aula si hace falta y la junta con lo que tiza publicó, sin descartar nada tuyo sin tu sí.

### Cambia
- El campo `copia` del informe de `tiza copia` es ahora una lista: cada copia dice de qué actividad es (nula si es la del curso entero).
- El protocolo entre el agente y tu sesión sube a la versión 8. Una sesión abierta con 0.28.0 o anterior hay que cerrarla y abrir otra con `tiza empezar`: el agente de esta versión no la atiende.

## 0.28.0 — 2026-10-23

### Añadido
- **Criterios de evaluación y casillas manuales en el calificador.** Cada competencia o resultado puede llevar criterios con peso, y la nota sale de instrumento → criterio → competencia → final, visible en cada nivel. Los `instrumentos` (examen en papel, observación) son casillas sobre 10 que pones tú a mano; tiza nunca las toca. Un criterio, un elemento o una evaluación cuyas actividades pesan todas 0 no cuenta, como el que no tiene actividades.

## 0.27.0 — 2026-10-23

### Añadido
- **`tiza empezar` cierra la sesión que se quedó sin terminal.** Si la terminal de la sesión se cerraba (por ejemplo, el panel de terminal de Claude Desktop en Windows), la sesión seguía viva sin poder contestarle y un `tiza empezar` nuevo solo decía `SESION_YA_ABIERTA`. Ahora ofrece cerrarla y abrir otra. Si estaba esperando tu respuesta, no publica nada; si estaba publicando, termina antes de cerrarse (`SESION_ANTERIOR_OCUPADA` si tarda más de 30 segundos). Una sesión de una versión anterior hay que cerrarla todavía a mano, en el Administrador de tareas.

## 0.26.1 — 2026-10-23

### Corregido
- **`tiza calificador` en un curso grande.** Medido en un módulo de 60 actividades: montar el calificador la primera vez tardaba 30 minutos y el agente dejaba de esperar a los 10 (`SIN_RESPUESTA`), o daba la sesión por cerrada si caducaba a medias. Ahora cada alta lee el árbol del calificador una vez en vez de dos, y tras escribir solo se vuelven a abrir los formularios de lo que se ha tocado. El agente espera hasta una hora, y la sesión no se da por cerrada mientras atiende una petición: la termina antes de cerrarse.
- **`tiza aislar` en Windows quita los permisos de más.** Si Claude Code permitía comandos que el agente no debe ejecutar (por ejemplo, aprobados con «no volver a preguntar»), la revisión lo marcaba como falta pero `tiza aislar` y `tiza empezar` respondían «No hay nada que añadir» y la carpeta seguía sin aislar. Ahora se quitan de `.claude/settings.json` y `.claude/settings.local.json`, la falta dice en qué fichero están, los del perfil global se indican para quitarlos a mano y `tiza empezar` dice qué sigue faltando.
- **`tiza actualizar` funciona en Windows.** Fallaba siempre con «Access is denied (os error 5)»: Windows no deja reemplazar tiza mientras está en marcha. Ahora la instalación sigue en otra ventana, en cuanto se cierra tiza; lo mismo al aceptar la actualización que ofrece `tiza empezar`.

## 0.26.0 — 2026-10-22

### Añadido
- **Campo `evalua` en el frontmatter**: `evalua: {RA1: 40, RA3: 25}` declara con qué resultados de aprendizaje y pesos se evalúa una actividad.
- **`tiza calificador <calificacion.yaml> --en pruebas|real`**: monta el calificador del aula según la programación (resultados o criterios, evaluaciones, pesos y un tope opcional) y coloca en él las actividades con `evalua`. Nunca lee ni escribe notas ni desbloquea nada; en real, el docente confirma cada curso. Su guía para el agente es `guias/calificador.md`.
- **`evalua` solo en actividades con nota**: tareas, cuestionarios y H5P. Una página o una etiqueta con `evalua` da `EVALUA_NO_CALIFICABLE` (también en `tiza comprobar`).
- **Evaluaciones cerradas**: una actividad nueva en una evaluación cerrada se queda sin colocar, con sus copias (`ACTIVIDAD_EN_EVALUACION_CERRADA`, y `sin_colocar` en el informe). Una evaluación `cerrada: true` que aún no existe se crea entera y se bloquea al final. tiza comprueba con una relectura que cada bloqueo se ha hecho (`BLOQUEO_FALLIDO`).
- **Quitar el tope** vacía también la fórmula del total del curso, y la confirmación del curso real dice el total del curso, la regla de la final con su límite y lo que se quita del calificador de tiza.

## 0.25.0 — 2026-10-20

### Añadido
- **Iconos de Font Awesome en las páginas y etiquetas**: una lista cerrada de iconos en `<i>` o `<span>`, sin animaciones. El aula ya carga Font Awesome.
- **Plantilla de página con estilo** (`ejemplos/pagina-con-estilo.html`) y unidad de ejemplo rehecha con páginas `.html` con estilo.

### Cambia
- **El agente escribe las páginas y las etiquetas en `.html` por defecto**, con la guía de estilo (`guias/estilo.md`): se ven cuidadas en el aula sin tocar nada y sus colores los pone el tema del aula. Tareas, cuestionarios y H5P siguen igual; el `.md` sigue valiendo si lo pides.

### Corregido
- **`ejemplos/maquetado.html` ya no usa `fw-bold`**: esa clase de Bootstrap 5 no existe en Moodle 4.5 y no hacía nada.

## 0.24.3 — 2026-10-20

### Corregido
- **En Windows, `tiza aislar` ya no deja a Claude Code sin poder ejecutar comandos**: Claude Code no tiene sandbox en Windows y el bloque que escribía bloqueaba todos los comandos, también en la pestaña Code de Claude Desktop. Ahora aísla con permisos: el agente solo ejecuta los comandos de tiza que necesita y escribe en la carpeta de la asignatura. `tiza revisar` lo comprueba. Sustituye el modo de permisos de la carpeta por `dontAsk`, quita el sandbox y no deja al agente reescribir `.claude/`.

### Cambia
- **`tiza aislar --global` en Windows ya no aplica el aislamiento de Claude Code**: un modo global sin preguntas afectaría a todos tus proyectos. Hazlo en la carpeta de la asignatura.

## 0.24.2 — 2026-10-20

### Corregido
- **El instalador vuelve a funcionar en Windows sin Visual C++**: uv elegía Python 3.15, recién salido, y PyYAML aún no trae versión preparada para él, así que intentaba compilarlo y fallaba. Los instaladores y `tiza actualizar` usan ahora Python 3.13.

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
