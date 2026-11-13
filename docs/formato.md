# Formato de los ficheros

Lo normal es que los escriba tu agente: la skill de `tiza` le enseña este
formato. Este documento sirve para revisarlos o escribirlos a mano. Hay ejemplos
completos en [`ejemplos/`](../ejemplos/).

Frontmatter YAML + Markdown (`.md`) o HTML (`.html`). En un `.md` la sangría no
crea bloques de código (el código va entre ```), así que el HTML sangrado se
publica como HTML. Los recursos locales se suben solos; un SVG no (`RECURSO_NO_PERMITIDO`): se convierte con `tiza esquema` y se cita el PNG.

Al convertir un `.md`, tiza adapta los títulos al nombre de la actividad: el nivel más alto del
documento pasa a `h3` y los demás bajan lo mismo, con tope en `h6`; así, `## Repaso` se publica
como `h3` y `### Ejercicio` como `h4`. Las tablas salen con `table table-striped` dentro de un
`div` con `table-responsive`, y los bloques de código, en un recuadro con fondo, borde e
interlineado holgado. Un `.html` no se toca: se publica tal como pasa el filtro.

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
evalua: {CE1_1: 100, CE2_1: 100}   # criterios de calificacion.yaml
# rubrica: por_criterios   # o rubricas/tarea.md (con evidencia: resultados, descriptores)
evidencia: resultados      # un resultado por criterio, o por fila con rúbrica de filas
---

Resuelve los problemas.
```

Para un cuestionario, las preguntas van en la cabecera y el cuerpo es la
descripción (mira [`ejemplos/cuestionario.md`](../ejemplos/cuestionario.md)):

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
(mira [`ejemplos/etiqueta.md`](../ejemplos/etiqueta.md)):

```markdown
---
tipo: etiqueta
nombre: Bienvenida al tema 3
seccion: 3
---

## Bienvenida

Este tema empieza hoy: ![foto](img/foto.png)
```

Para una **actividad H5P** generada por tiza, la actividad va en la cabecera
(`actividad:`) y el cuerpo es la descripción. Las respuestas se escriben entre
`[[...]]` y las alternativas con `[[a|b]]` (mira
[`ejemplos/h5p-huecos.md`](../ejemplos/h5p-huecos.md) y
[`ejemplos/h5p-tarjetas.md`](../ejemplos/h5p-tarjetas.md)):

```markdown
---
tipo: h5p
nombre: Repaso de vocabulario
seccion: 3
actividad:
  tipo: rellenar_huecos
  textos:
    - "El agua hierve a [[100]] grados."
    - "La capital de Francia es [[París|Paris]]."
  mayusculas: true            # opcional; por defecto false
  calificacion: 10            # opcional; por defecto 10
  reintentar: true            # opcional; por defecto true
  ver_solucion: true          # opcional; por defecto true
---

Descripción de la actividad.
```

Los cuatro tipos generados son `rellenar_huecos` (`textos:`),
`arrastrar_palabras` (`texto:` y `distractores:` opcional), `marcar_palabras`
(`enunciado:` y `texto:`) y `tarjetas` (`tarjetas:` con `anverso:` y `reverso:`;
no califican y no llevan seguimiento). Para subir un paquete hecho fuera
(h5p.org, Lumi, otro Moodle), usa `paquete: paquete.h5p` en vez de `actividad:`:
tiza lo valida y lo reempaqueta **sin librerías ni JavaScript** antes de
subirlo, y los enlaces `https` que lleve el paquete te los enseña al confirmar.

Para maquetar con estilo, o para pegar HTML hecho en otra herramienta, usa un
fichero `.html` con el mismo bloque YAML y, debajo, HTML (un fragmento o un
documento completo: solo se publica el `<body>`). Para páginas y etiquetas, el
`.html` con estilo es lo normal: el agente sigue la guía de estilo de la skill,
con clases de Bootstrap 4 que toman los colores del aula y iconos de Font Awesome
de una lista cerrada (solo en `<i>` o `<span>`, con `aria-hidden="true"`). Mira
la plantilla [`ejemplos/pagina-con-estilo.html`](../ejemplos/pagina-con-estilo.html)
y [`ejemplos/maquetado.html`](../ejemplos/maquetado.html): estilos, clases de
Bootstrap y un iframe de cada grupo. En Moodle 4.5 algunas clases de Bootstrap 5
(`fw-bold`, `fst-italic`…) no hacen nada: usa su equivalente de
Bootstrap 4 (`font-weight-bold`, `font-italic`). Si algo no se admite, `tiza comprobar` da
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
- `origen: {curso: 3, cmid: 501}` (opcional, en cualquier tipo) vincula el fichero con
  la actividad del aula de la que salió (`tiza importar` lo escribe; no lo cambies a mano).
  Los dos son enteros positivos; si no, `ORIGEN_INVALIDO`. Al publicar en ese curso, la
  actividad se busca por su `cmid`, así que sigue siendo la misma aunque cambies su nombre
  o su sección. Si no está en el aula, `ORIGEN_NO_ENCONTRADO`; solo con el sí del docente se
  quita `origen:` para publicarla como nueva. Si alguien cambió su nombre, su texto o
  sus fechas después de la copia, `CAMBIADA_EN_EL_AULA` (no se publica; las preguntas y
  los ajustes de un cuestionario y el paquete H5P no se comparan). Sin la huella de la
  copia en `.tiza/copia.json`, `ORIGEN_SIN_HUELLA` (tampoco se publica). En otro curso o en pruebas, se busca
  por sección, tipo y nombre, como cualquier fichero.
- Si el `nombre` contiene `: ` (dos puntos y espacio), escríbelo entre comillas:
  `nombre: "Ejemplo: repaso"`.
- Cambiar `nombre:` de un fichero ya publicado en un curso renombra esa misma actividad en ese
  curso (con sus entregas y notas) en vez de crear otra. Si la actividad ya no está en el aula, se
  crea de nuevo, y la confirmación de real te lo dice antes.
- Las fechas aceptan `AAAA-MM-DD` o `AAAA-MM-DD HH:MM` (hora del aula, con
  `Europe/Madrid` por defecto; una hora que el reloj se salta en el cambio de
  primavera, como las 02:30 del último domingo de marzo, no existe y da
  `FECHA_INEXISTENTE`; sin hora,
  `apertura` empieza a las 00:00 y `entrega` y `limite` acaban a las 23:59) y
  deben cumplir `apertura < entrega < limite`. `entrega` es la «Fecha de
  entrega» de Moodle: después se siguen admitiendo entregas, marcadas con
  retraso. `limite` es la «Fecha límite»: a partir de ella ya no se admiten
  entregas. Es opcional; sin ella, se admiten entregas con retraso sin fin.
- Un cuestionario admite además `apertura`, `cierre`, `mezclar_respuestas` y
  `penalizar`, y
  de 1 a 100 preguntas de cinco tipos: `opcion_multiple` (de 2 a 10 opciones),
  `verdadero_falso`, `respuesta_corta`, `numerica` y `emparejamiento` (de 2 a 10
  parejas y `distractores` opcionales; la respuesta es texto plano y hacen falta al
  menos 3 respuestas distintas). Cada pregunta puede llevar `retro`
  (retroalimentación) y vale 1 punto (el emparejamiento lo reparte a partes iguales);
  tiza calcula las puntuaciones. No hay preguntas de ensayo: para respuestas abiertas,
  usa una tarea.
- Por defecto, en `opcion_multiple` con una correcta y n opciones, **cada
  incorrecta resta** 1/(n−1) (con 4 opciones, 1/3): contestar al azar da 0. En
  blanco vale 0. Una pregunta puede quedar en negativo y restar de las demás, pero
  la nota del cuestionario no baja de 0. Con `penalizar: false` no restan en todo
  el cuestionario. Con varias correctas, cada incorrecta marcada resta su parte
  siempre (si no, marcarlo todo daría la pregunta entera). `verdadero_falso` no
  resta nunca (Moodle no lo permite); respuesta corta, numérica y emparejamiento
  tampoco.
- Las preguntas admiten **imágenes locales** (PNG, JPEG, GIF o WebP, hasta 1 MB cada
  una y 10 MB por cuestionario) en el enunciado, las opciones, las parejas y la
  retroalimentación, con **texto alternativo obligatorio** (`IMAGEN_SIN_ALT`). tiza las
  envía dentro de las preguntas y comprueba en el aula que las guardó y las sirve
  (`VERIFICACION_IMAGENES`). Cualquier otro fichero local da `RECURSO_EN_PREGUNTA`.
  Mira [`ejemplos/cuestionario.md`](../ejemplos/cuestionario.md).
- Cuando un alumno empieza un intento, tiza ya no cambia ese cuestionario
  (`CUESTIONARIO_CON_INTENTOS`): revisa bien las respuestas correctas antes de
  publicarlo en el curso real y, para corregirlo después, crea otro con un
  `nombre` distinto.
- Una actividad H5P generada lleva `actividad:` con uno de los cuatro tipos.
  Los huecos y las palabras se marcan con `[[respuesta]]`; las alternativas
  (`[[a|b]]`) solo valen en `rellenar_huecos`. Dentro de una respuesta no se
  admiten `*`, `/` ni `:` (H5P les da otro significado). El texto admite negrita
  y cursiva, sin imágenes ni ficheros locales. Con `paquete:` tiza valida el
  `.h5p` (estructura, medios y tamaño) y lo reempaqueta sin librerías antes de
  subirlo: debe estar dentro de la carpeta de la asignatura y tiza nunca sube
  JavaScript. Las tarjetas no califican ni llevan seguimiento.
- Cuando la actividad H5P ya tiene intentos, tiza no la cambia
  (`H5P_CON_INTENTOS`): crea otra con otro `nombre` si necesitas modificarla.
- Si ya existe una página, etiqueta, tarea, cuestionario o actividad H5P con el
  mismo `nombre`
  en esa sección, se actualiza (mismo cmid) **y conserva su visibilidad**; si no,
  se crea oculto. `--visible` lo muestra al alumnado y `--oculto` lo oculta,
  exista o no.
- Hay ejemplos completos en [`ejemplos/`](../ejemplos/).

## Itinerario: finalización y restricciones

Cualquier actividad puede declarar cuándo cuenta como completada y cuándo se
abre; sin estos campos, lo que ya haya en el aula se conserva:

```yaml
finalizacion: ver          # ninguna | manual | ver | entregar (tarea) | calificar
fecha_esperada: 2026-11-20 # opcional: «completar antes de» (informativa)
restricciones:
  desde: 2026-10-20        # opcional; también hasta
  completar: [test.md]     # hasta 10 .md de la carpeta: se abre al completarlos
  ocultar_si_no_cumple: false   # por defecto se ve en gris con la condición
```

- La etiqueta solo admite `ninguna` y `manual`. Todas las condiciones se exigen
  a la vez, y `restricciones: {}` quita las de tiza. Las restricciones por
  grupo, perfil o nota no existen: tiza no toca datos ni grupos del alumnado.
- Una carpeta entera (página → test → tarea) se publica en una petición: tiza
  ordena los ficheros por sus dependencias y cada curso real resuelve las suyas.
- Si la actividad ya tiene una restricción puesta a mano en el aula, tiza no la
  toca (`RESTRICCION_AJENA`); si algún alumno ya la completó, tampoco cambia cómo
  se completa (`FINALIZACION_BLOQUEADA`), porque el aula borraría ese estado; y
  si el curso no tiene activada la finalización, lo dice
  (`FINALIZACION_DESACTIVADA`) sin cambiar los ajustes del curso.
- tiza nunca lee el estado de finalización ni informes del alumnado. La
  confirmación del curso real enseña el itinerario en lenguaje llano.

## Calificador: `evalua`

Las tareas, los cuestionarios y los contenidos H5P pueden declarar con qué resultados
de aprendizaje o criterios se evalúan y con qué peso relativo, para colocarlos en el calificador
del curso. Una página o un área de texto y medios no tienen nota en Moodle: con `evalua` dan
error (`EVALUA_NO_CALIFICABLE`), también en `tiza comprobar`.

```yaml
evalua: {RA1: 40, RA3: 25}   # id: peso relativo de 0 a 100, con hasta 2 decimales
```

- Los ids empiezan por letra, siguen con letras, cifras o `_`, y tienen hasta 16 caracteres.
  Los pesos son **relativos** y no tienen que sumar 100: tiza los normaliza por hoja. Un peso de
  0 deja la actividad sin peso, pero se queda en el calificador. Si todo lo que evalúa un criterio
  (un elemento o una evaluación) pesa 0, ese criterio no cuenta: sus hermanos se reparten el 100.
- `recupera` (opcional) declara que la actividad recupera una o varias evaluaciones:
  `recupera: 1` o `recupera: [1, 3]`. Recupera los criterios de su `evalua`; su nota sustituye a
  la del trimestre en la vista del curso si es mayor; no es evidencia del trimestre y en
  `mas_alta` va suelta. Necesita `evalua` y `final: {de: elementos}`; cada criterio recuperado
  debe tener evidencias normales en esa evaluación y no puede usar la regla `mediana`.
  No cambia el hash de la actividad.
- Si el elemento tiene criterios, `evalua` nombra sus criterios (`CE1_1`, no `CE1`); nombrar el
  elemento da `ELEMENTO_CON_CRITERIOS`.
- Un id repetido o un mapa vacío dan error (`EVALUA_INVALIDO`). Que el id exista
  en el esquema del curso se comprueba al colocar la actividad, no al leer el `.md`.
- Cambiar `evalua` no cambia el hash de la actividad: no hace falta volver a
  verificarla.

### Cuestionarios: uno por criterio

Para que cada criterio reciba su propia nota, lo recomendable es que un cuestionario declare un
solo criterio en `evalua`, por ejemplo `evalua: {CE2_2: 100}`; si es la única actividad que evalúa
ese criterio, su nota total llega entera a él. Si una prueba cubre varios, se parte en un
cuestionario por criterio en la misma sección: la prueba de la UD3 con CE2.2 y CE3.1 se publica
como dos cuestionarios, «UD3 · Planificación» (CE2.2) y «UD3 · Construcción» (CE3.1). Recomendado
al menos 3 preguntas en cada uno para que su nota sea fiable. El agente propone el criterio de cada
pregunta a partir del texto literal del criterio (`tiza normativa ficha`) y el docente confirma la
tabla de preguntas antes de escribir el fichero.

Un cuestionario con 2+ criterios con peso sigue siendo válido y se publica igual, pero
`tiza comprobar` avisa con `EVIDENCIA_COMPARTIDA` sin impedir la publicación y `tiza calificador`
también. Las calificaciones del cuestionario no crean elementos en el calificador: no reparten la
nota entre criterios.

## Calificador: `calificacion.yaml`

Lo escribe el agente en la carpeta de la asignatura, a partir de la programación, y lo monta
`tiza calificador`. Es un esquema cerrado, sin lenguaje de fórmulas: qué elementos (resultados
o criterios) hay, cuánto pesa cada uno, qué evaluaciones hay y un tope opcional de la final.

```yaml
organizacion: elementos            # o evaluaciones (ESO y Bachillerato)
elementos:                         # con organizacion elementos o final de elementos
  - {id: RA1, nombre: "Redes locales", peso: 40, codigo: RA1}   # peso 0-100; suman 100
    # con criterios: criterios: [{id: CE1_1, nombre: "Criterio 1.1", peso: 40, codigo: "1.1"}, ...]
evaluaciones:
  - {nombre: "1.ª evaluación", secciones: [1, 2, 3], cerrada: false}   # secciones de «seccion:»
final:
  de: elementos                    # o evaluaciones (entonces cada evaluación lleva peso)
  tope: {si_alguno_menor_que: 5, maximo: 4}   # opcional, solo con de: elementos
```

Con `final: {de: elementos}`, el `peso` de cada evaluación es opcional: es el `q_n` con el que
cada copia del curso pesa su trimestre, normalizado entre los trimestres con evidencias de la
hoja; sin pesos, todos pesan igual.

- `id`: letra inicial y luego letras, cifras o `_`, 16 como mucho. Los ids repetidos dan `ID_REPETIDO`.
- `criterios` (opcional en cada elemento): `{id, nombre, peso?, codigo?}`. Con pesos, van en todos
  o en ninguno y suman 100; sin pesos pesan igual y sale `CRITERIOS_SIN_PESO`. Elementos y criterios
  no repiten `id`. `codigo` es el código legible (`1.1`, `RA1.a`).
- `instrumentos` (opcional): casillas manuales para lo que no está en el aula (examen en papel,
  observación), `{id, nombre, seccion, evalua}`. tiza crea la casilla (sobre 10) en su primer
  criterio y copias en los demás; la nota la pone el docente a mano y tiza nunca la toca. También
  admite `recupera`.
- `agregacion` (opcional): cómo se combinan las evidencias de cada hoja. `regla` es `media`
  (por defecto), `mediana`, `mas_alta` o `progresiva`; con `progresiva` hacen falta
  `factores: [1, 2, 3]`, uno por evaluación y mayores que 0. Cada elemento sin criterios o cada
  criterio puede llevar su propia `regla`. La regla se puede cambiar a mitad de curso; las evaluaciones cerradas
  no se tocan y el informe lo avisa con `REGLA_CAMBIADA`. Con `final.tope` valen todas las reglas y
  también `recupera`.
- Una sección solo puede estar en una evaluación (`SECCION_REPETIDA`). Una actividad con `evalua`
  en una sección que no es de ninguna evaluación da `SECCION_SIN_EVALUACION`.
- `cerrada: true` bloquea la evaluación en el aula al terminar de montar (si no estaba completa,
  primero la completa). Una vez bloqueada, no se crea, cambia, mueve ni borra nada dentro, y una
  actividad nueva de sus secciones queda sin colocar (`ACTIVIDAD_EN_EVALUACION_CERRADA`). tiza no
  la reabre.
- No se admite cambiar `organizacion` o `final.de` de un calificador ya montado (habría que
  borrar a mano lo de tiza en el aula y volver a montar), ni usar escalas configuradas por el
  docente: tiza solo usa la escala de logro que crea para la evidencia por criterio (ver más abajo).
- Un árbol de la generación anterior (`TZ_NOTAS`, `TZ_K_TIZA`, `TZ_AG_*`, `TZ_RP_*`, `TZ_F_*` o
  copias `TZ_C_` dentro de una vista con actividades) da `CALIFICADOR_ANTIGUO` antes de escribir;
  hay que borrar a mano «Calificador de tiza» y volver a pedirlo. Si el aula no ofrece «Media
  ponderada de calificaciones», `CALCULO_NO_DISPONIBLE`. Si el informe del usuario muestra
  «Ponderación» o «Contribución al total del curso», `PONDERACIONES_VISIBLES` solo avisa.
- Con tope, si alguna nota de elemento baja del umbral, la final no pasa del máximo. Solo
  cuentan los elementos cuya evaluación ya está cerrada: antes de cerrar la primera, la final
  no topa; después, un elemento sin notas cuenta como 0. Un error del esquema da
  `ESQUEMA_INVALIDO`, con la ruta y la línea.
- Lo que el esquema no expresa (redondeos, actitud) se queda fuera: la guía del agente
  (`guias/calificador.md`) dice cómo tratarlo. El juicio del docente se aplica sobrescribiendo
  a mano el total de la categoría en Moodle; tiza no escribe notas ni lo deshace.

`tiza comprobar calificacion.yaml` deja, además, `.tiza/cobertura.json` (versión 1): una entrada
por criterio o elemento sin criterios, también los vacíos, con el instrumento deducido
(`tarea_rubrica_criterios`, `tarea_rubrica_filas`, `tarea_resultados`, `tarea`, `cuestionario`,
`h5p` o `casilla_manual`), la actividad, la evaluación, el peso normalizado, la regla y
`recupera`. Los nombres vienen de los ficheros del docente y se sanean al escribirlos. El mapa
lleva `generado`; si el esquema es inválido, se borra el anterior para que no parezca bueno, y
tiza no vigila si se queda viejo. Los avisos del informe (`HOJA_SIN_EVIDENCIAS`,
`HOJA_CON_UNA_EVIDENCIA`, `MEDIANA_CON_POCAS_EVIDENCIAS`, `PROGRESIVA_EN_UNA_EVALUACION`) no
impiden montar el calificador.

## Calificador: reglas de agregación y recuperación

Por defecto, la nota de cada hoja (un criterio o un elemento sin criterios) es la media ponderada
de sus evidencias con los pesos de `evalua`. El esquema puede pedir otra regla:

| `regla` | Qué hace |
|---|---|
| `media` | Media ponderada; es la de siempre y la que se usa si no se dice otra. |
| `mediana` | Mediana de las evidencias; los pesos de `evalua` no cuentan. |
| `mas_alta` | La mejor evidencia; los pesos no cuentan. |
| `progresiva` | Media ponderada con el peso de cada evaluación multiplicado por su factor. |

```yaml
agregacion:
  regla: media
  factores: [1, 2, 3]   # solo con progresiva; uno por evaluación
elementos:
  - id: CE3
    nombre: "Competencia 3"
    peso: 100
    criterios:
      - {id: CE3_1, nombre: "Construye", regla: mas_alta}
```

- La regla general es `agregacion.regla`; un elemento sin criterios o un criterio puede
  sobrescribirla con `regla`. Un valor desconocido da `ESQUEMA_INVALIDO` con su ruta.
- Con `progresiva`, `factores` tiene un número mayor que 0 por evaluación; si falta o no cuadra,
  `PROGRESIVA_SIN_FACTORES` o `ESQUEMA_INVALIDO`.
- En `mediana` y `mas_alta`, los pesos de `evalua` no cuentan; si no son todos iguales,
  `PESOS_SIN_EFECTO` lo avisa. La tarea real de B/C y las actividades de peso 0 suben al
  antepasado de media ponderada (el elemento, o la evaluación si la hoja es un elemento sin
  criterios); el calculado del resultado y el resultado del aula se quedan en la hoja.
- Una actividad con `recupera` sustituye la nota de las evidencias de la evaluación recuperada
  cuando es mayor. La recuperación vive en la vista del curso y envuelve la copia del trimestre
  recuperado en una categoría «más alta»; si la hoja es `mas_alta`, va suelta. Cerrar la
  evaluación no impide corregirla, pero una evaluación ya bloqueada no cambia su nota:
  `RECUPERACION_EN_CERRADA` avisa y la recuperación cuenta en la final. La `mediana` del curso es
  la mediana de las medianas trimestrales.
- Una actividad de recuperación no es evidencia de su propia sección ni de su propia evaluación.
  Cada criterio recuperado necesita evidencias normales en esa evaluación
  (`RECUPERA_SIN_EVIDENCIAS`) y no puede usar `mediana` (`RECUPERACION_CON_MEDIANA`). Con
  `final: {de: evaluaciones}` no se admite `recupera`
  (`RECUPERACION_SOLO_FINAL_DE_ELEMENTOS`).
- Cambiar `regla` no pide confirmación: es una decisión de la programación. tiza cambia la
  agregación de la categoría y avisa con `REGLA_CAMBIADA`; una evaluación cerrada no se toca.
  Para el juicio del docente, sobrescribe a mano el total de la categoría en el informe del
  calificador: tiza no lo deshace y la media calculada queda a la vista.

## Calificador: rúbrica de la tarea

Una tarea con `evalua` puede llevar `rubrica` de dos formas: `por_criterios`, con una fila
genérica por criterio y los pesos de la programación, o la ruta de un fichero con `filas`, que
concreta cada criterio para esa tarea. Las dos crean la rúbrica nativa de Moodle, reparten 10
puntos que Moodle reescala a la nota máxima y valen en cualquier etapa. La excepción es la
combinación de un fichero de `filas` con `evidencia: resultados`: entonces no se crea la rúbrica
nativa, sino un resultado del aula por fila con sus descriptores (mira «Calificador: evidencia
por criterio»).

Reglas comunes:

- Con `evalua` (`RUBRICA_SIN_EVALUA`) y `calificacion.yaml`
  (`RUBRICA_SIN_ESQUEMA`).
- La rúbrica se ve antes de la entrega (`alwaysshowdefinition=1` y `showdescriptionstudent=1`).
  Una tarea **nueva** la recibe al publicarse; una que **ya existe** solo la recibe si el docente
  confirma. Si además tiene notas (`rescalegrades`), no se activa aunque confirme: sale
  `RUBRICA_NO_ACTIVADA` y se publica el resto sin tocar el método de calificación.
- En el público valen `por_criterios` y un fichero con `filas`. Un fichero con `criterios`
  (rúbrica libre) o `indicaciones` es de `tiza-privado`: da `RUBRICA_NO_VALIDA` con la pista de
  usar `filas`.
- Los cuestionarios no tienen rúbrica en Moodle.
- El fichero de rúbrica no es una actividad: no lo pases a `tiza comprobar` ni a `tiza publicar`.
  Comprueba y publica la tarea, que lo enlaza con `rubrica:`.

### Con `rubrica: por_criterios`

`rubrica: por_criterios` construye la rúbrica con `evalua` y `calificacion.yaml`: una fila por
criterio de evaluación, con los puntos repartidos según los pesos fijos de la programación
didáctica.

```yaml
rubrica: por_criterios   # con evalua y calificacion.yaml
```

- Los pesos salen de `calificacion.yaml` (el del elemento y el del criterio). No se inventan ni
  se ajustan por tarea. Un criterio con peso absoluto 0 no genera fila; si todos pesan 0,
  `RUBRICA_SIN_PESOS`.
- Los niveles salen de `niveles_rubrica` (por defecto, 5: 100, 75, 50, 25 y 0 %). Cada nivel se
  redondea con el mayor resto para que su suma sea exacta (el 50 % de 10 son 5,00).
- `actividades_pesan_igual: true` hace que todas las actividades de un criterio pesen lo mismo,
  aunque sus números de `evalua` sean distintos; no tienen que sumar 100.

### Con un fichero de filas

`rubrica: rubricas/<tarea>.md` enlaza un fichero `tipo: rubrica` que concreta el criterio:
recomendado 1–3 indicadores por criterio, un descriptor observable por nivel y pesos propios de la
tarea. Máximo 20 filas en total y al menos una por cada criterio de `evalua` con peso > 0. Es el
formato que conviene cuando el alumnado tiene que saber exactamente qué se le pide.

```yaml
---
tipo: rubrica
nombre: Rúbrica del montaje
filas:
  - criterio: CE1_1
    indicador: Planifica las fases y los materiales
    peso: 2
    niveles:
      destacado: Secuencia completa, con tiempos y materiales justificados.
      avanzado: Secuencia completa; justifica solo los materiales.
      adecuado: Secuencia con alguna fase desordenada o sin tiempos.
      inicial: Enumera fases sueltas, sin orden ni materiales.
      no_iniciado: No presenta planificación.
  - criterio: CE1_1
    indicador: Justifica la elección de materiales
    peso: 1
    niveles:
      destacado: Justifica cada material por su función y su coste.
      avanzado: Justifica cada material por su función.
      adecuado: Justifica algunos materiales.
      inicial: Nombra materiales sin justificarlos.
      no_iniciado: No elige ni justifica materiales.
  - criterio: CE1_2
    indicador: Precisión del montaje
    peso: 1
    niveles:
      destacado: Monta sin errores y comprueba el resultado.
      avanzado: Monta con un error menor que corrige.
      adecuado: Monta con algún error que no corrige.
      inicial: Monta solo con ayuda.
      no_iniciado: No monta.
---

Descripción de la rúbrica para el alumnado: qué se valora en el montaje y qué se espera en cada nivel.
```

- Campos: `tipo` (`rubrica`), `nombre` (hasta 255 caracteres) y `filas` (de 1 a 20). Después del
  frontmatter hace falta el cuerpo: la descripción que lee el alumnado, sin imágenes ni ficheros
  locales (`RUBRICA_NO_VALIDA`).
- Cada fila: `criterio` (un criterio hoja de `calificacion.yaml` que esté en `evalua`),
  `indicador` (1–100 caracteres), `peso` opcional (mayor que 0 y hasta 100, dos decimales como
  mucho) y `niveles` con **exactamente** los ids de `niveles_rubrica`. Dos filas no pueden repetir
  criterio e indicador.
- **Para varias filas de un mismo criterio, el criterio necesita `codigo` en `calificacion.yaml`;
  sin él, todas las filas se llamarían igual y Moodle no las emparejaría. Si un criterio no tiene
  `codigo`, usa una sola fila.**
- Pesos: si ninguna fila lleva `peso`, todas pesan igual; si unas sí y otras no,
  `PESOS_DE_FILA_INCOMPLETOS`. El peso de la fila solo reparte la **nota visible de la tarea**: los
  10 puntos se reparten entre las filas con el mayor resto, y los de cada nivel son los de la fila
  por el porcentaje del nivel, también con el mayor resto. No sustituye al peso de `evalua` de cada
  criterio: sin `evidencia`, la nota total de la tarea llega a todos sus criterios según `evalua`;
  con evidencia, cada criterio recibe su propio nivel.
- En Moodle, la primera fila de un criterio tiene el id del criterio en minúsculas (`ce1_1`) y
  las siguientes `_2`, `_3`…; el título es «`codigo` · `indicador`» (o el id si no hay `codigo`).
  **Moodle recibe el criterio como «título: nombre oficial»** y cada nivel se define «`Nombre del
  nivel`: descriptor». El título y los puntos de los niveles permiten a tiza emparejar las filas
  al volver a publicar.
- Límites: el título de la fila (código e indicador) no pasa de 120 caracteres; cada descriptor,
  de 1000 menos el prefijo «`Nombre del nivel`: ». Un peso de fila muy pequeño frente a los demás
  puede dar `RUBRICA_NO_VALIDA` si sus niveles no reciben puntos distintos.
- Validación: una fila con un criterio que no está en `evalua` o que no es hoja da
  `FILA_FUERA_DE_EVALUA`; un criterio de `evalua` con peso mayor que 0 sin fila, `CRITERIO_SIN_FILA`;
  un nivel que falta, `DESCRIPTOR_FALTA`. Una clave con forma de id que no está en `niveles_rubrica`
  da `NIVEL_DESCONOCIDO`; una clave sin forma de id da `RUBRICA_NO_VALIDA` con la pista de la
  coma. Con `evidencia: resultados` los descriptores no pueden llevar comas
  (`DESCRIPTOR_CON_COMA`, con la línea); la rúbrica nativa (sin evidencia o con «por_criterios») sí las admite. La forma de las filas es
  `RUBRICA_NO_VALIDA`; el frontmatter mal escrito, `FRONTMATTER_INVALIDO`; el HTML
  peligroso, `HTML_PELIGROSO`; una ruta fuera de la carpeta, `RUBRICA_FUERA_DE_CARPETA`; y los
  problemas de fichero, `FICHERO_AUSENTE`, `CODIFICACION_INVALIDA` o `FICHERO_DEMASIADO_GRANDE`.

## Calificador: evidencia por criterio (resultados)

Una tarea puede declarar `evidencia: resultados` en su cabecera. En lugar de que su nota
total se reparta entre los criterios, cada criterio de `evalua` recibe **su propio nivel**, que el
docente marca en la pantalla de calificación de Moodle. Es útil cuando la tarea trabaja más de un
criterio; con uno solo, la nota de la tarea ya es su nivel.

En `tiza` puedes usar `evidencia: resultados` sola o con un fichero `rubrica: rubricas/<tarea>.md`.
La combinación es la que pone los descriptores en los desplegables del docente y en el informe del
alumnado:

- **Sola**, como siempre: tiza crea la escala «Escala de logro (tiza)» con los niveles de
  `niveles_rubrica` y un resultado por criterio. El docente marca un nivel por criterio y no hay
  rúbrica nativa.
- **Con un fichero de `filas`**: cada fila es un resultado del curso con **su propia escala**
  «Nivel: descriptor», ordenada de menor a mayor. En la tarea hay un desplegable por fila y cada
  opción muestra el descriptor entero. **No se crea la rúbrica nativa de Moodle**: no se marca dos
  veces.
  - En el calificador, cada fila lleva su resultado y un calculado directo en la categoría del
    criterio, con el peso `evalua × parte de la fila`; no hay subcategoría «Filas». Una fila sin
    marcar no cuenta y el criterio se renormaliza entre todas sus evidencias de ese trimestre, no
    solo entre las filas de la tarea.
  - El valor es **continuo**, sin redondear al nivel: la nota del criterio es la media ponderada de
    sus evidencias. Para la programación: «La calificación de cada criterio es la media ponderada
    de sus evidencias, con el nivel alcanzado en cada fila (0–100), sin redondear al nivel».
- **Sin comas en los descriptores** de esa combinación: la escala de Moodle separa sus niveles con
  comas. Un descriptor con coma da `DESCRIPTOR_CON_COMA` con el fichero, la fila, el nivel y la
  línea. La rúbrica nativa (sin `evidencia` o con `por_criterios`) sí admite comas.
- **Fija los descriptores antes de publicar.** Moodle no deja cambiar la escala de un resultado ya
  usado y tiza no puede saber si tiene niveles puestos. Si la escala existe con otros niveles, avisa
  `DESCRIPTOR_PUBLICADO`, no la toca y monta lo demás. Para cambiar un descriptor, renombra el
  `indicador` de la fila: crea una fila nueva, con su resultado y su escala; la fila anterior deja
  de contar y se queda con peso 0.
- Si usas `tiza-privado`, su corrector (`corregir`) y su orden `copiar-niveles` copian el nivel de
  cada fila al resultado de su criterio; con la combinación de descriptores, usa los resultados
  como fuente y no dupliques la rúbrica nativa. `tiza calificador` avisa con `EVIDENCIA_COMPARTIDA`
  de una actividad o casilla manual (una vez por cada una) que evalúa 2+ criterios con peso y no
  declara `evidencia`: su nota total llega a todos sus criterios según `evalua`; el peso de las
  filas solo reparte esa nota de tarea, no cambia lo que llega a cada criterio. `tiza comprobar`
  avisa antes de publicar, sin red, solo en un cuestionario con 2+ criterios con peso; el aviso
  propone publicar uno por criterio.

```yaml
evidencia: resultados   # con evalua y calificacion.yaml
```

- Necesita `evalua` (`EVIDENCIA_SIN_EVALUA`) y `calificacion.yaml` en la carpeta de la asignatura
  (`EVIDENCIA_SIN_ESQUEMA`). Los porcentajes de
  `niveles_rubrica` deben estar igual de separados, como los de por defecto (0, 25, 50, 75 y 100);
  si no, `NIVELES_NO_EQUIDISTANTES`.
- **Sin fichero de filas**, tiza crea en el curso la escala «Escala de logro (tiza)» con los
  niveles de `niveles_rubrica`, ordenados de menor a mayor, y un resultado por criterio con nombre
  corto `TZ_<criterio>`, nombre completo «código · nombre» (o solo el nombre si el criterio no tiene
  `codigo`) y una descripción con los niveles. En el calificador pone un calculado por tarea y
  criterio que reescala el nivel a 0–100 y lleva el peso de `evalua`; el resultado del aula queda
  con peso 0, porque su formulario no admite coeficiente. **La nota total de la tarea deja de
  contar para los criterios**. Los descriptores de cada nivel van en el enunciado de la tarea, para
  que el alumnado sepa qué se le pide.
- **Con fichero de filas**, crea una escala y un resultado por fila (nombre corto estable
  `TZ_<criterio>_<huella>` y nombre completo «código · indicador»), con la escala «Nivel:
  descriptor». El resultado y su escala se reutilizan al volver a publicar; la definición de las
  filas entra en el hash de la tarea, así que un cambio de descriptor o de indicador se publica.
- Si la tarea ya tiene notas, `tiza publicar` pide confirmación antes de activar los resultados
  (`EVIDENCIA_CAMBIADA_CON_NOTAS`): sus notas antiguas dejan de contar para los criterios. Con «N»,
  la tarea se publica sin resultados. `tiza calificador` también pregunta por las tareas pendientes
  con notas, aunque no emita ese paso.
- Quitar `evidencia` no borra el resultado: al volver a montar el calificador se queda con
  coeficiente 0. En `tiza calificador`, `RESULTADO_CON_NOTAS_QUITADO` solo avisa si el resultado ya
  tenía niveles puestos.
- Si el sitio tiene los resultados desactivados, `RESULTADOS_DESACTIVADOS` en `tiza publicar` (no
  se escribe nada de resultados y se publica el resto) o en `tiza calificador` (queda el paso
  `RESULTADOS_DESACTIVADOS` y el calificador sigue). Sin filas, si la escala común ya está en uso
  con otros niveles, `ESCALA_EN_USO`: no se toca la escala ni se escriben resultados. En `tiza
  publicar` detiene la publicación; en `tiza calificador`, el paso `CALIFICADOR` falla con
  `ESCALA_EN_USO`. Con filas, la escala es de cada fila y el aviso es `DESCRIPTOR_PUBLICADO`: se
  deja como está y se sigue con lo demás.
- tiza **no lee los niveles**: los marca el docente en Moodle. Una tarea sin `evidencia` se publica
  y calcula su hash exactamente como siempre; con `evidencia` y filas, el hash incluye la definición
  de las filas, y solo en ese caso cambia.

## Fórmulas

En un `.md` las fórmulas se escriben en LaTeX con `\( … \)` (en la línea) y `\[ … \]` o
`$$ … $$` (en bloque): tiza las publica tal cual (sin que `*`, `_` o `\\` se lean como
Markdown) y el aula las dibuja con su motor de fórmulas. Si el aula no lo carga, el informe
trae el paso `FORMULAS_NO_DIBUJADAS` (y la autoprueba lo dice). El `$x$`
simple no vale (`tiza comprobar` avisa con `FORMULA_DOLAR_SIMPLE`). Valen en páginas,
etiquetas, tareas y cuestionarios, no en las actividades H5P (`FORMULA_EN_H5P`). La vista
previa enseña la fuente LaTeX; el dibujo se revisa en el curso de pruebas. Mira
[`ejemplos/formulas.md`](../ejemplos/formulas.md).

## Programación en Word: `relleno.yaml`

Lo escribe el agente para `tiza rellenar`, que cambia una **copia** de una plantilla Word
(`.docx`) sin tocar sus estilos ni su numeración, y con sus encabezados y pies tal cual salvo los que se cambien con sus ids. Los ids vienen de
`tiza leer` sobre esa misma plantilla, y `tiza leer` da también su `sha256`. El fichero va
en la carpeta de la asignatura, no en `.tiza/`, y sus rutas son relativas a esa carpeta.

```yaml
plantilla: Plantilla departamento.docx
sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
salida: Programacion DAM1 2027-28.docx
operaciones:
  - op: reemplazar
    id: p3
    texto: Programación didáctica, curso 2027-28
```

Cabecera, toda obligatoria:

- `plantilla`: el `.docx` de origen. Se lee y no se modifica. Si cambió desde la lectura,
  `PLANTILLA_CAMBIADA`.
- `sha256`: 64 caracteres hexadecimales en minúscula.
- `salida`: el `.docx` nuevo. Si ya existe, o si es la plantilla, `DOCUMENTO_EXISTE`.
- `operaciones`: una lista de 1 a 2000 operaciones, que se aplican en ese orden.

Operaciones (`op`):

| `op` | Claves | Qué hace |
|---|---|---|
| `reemplazar` | `id`, `texto` | Cambia el texto de un párrafo o de una celda |
| `sustituir` | `id`, `buscar`, `poner` | Cambia un trozo de texto dentro de un párrafo o de una celda, sin tocar nada más |
| `insertar_despues` | `id`, `parrafos`, `estilo` (opcional) | Añade párrafos tras un párrafo o una tabla |
| `filas` | `tabla`, `modelo`, `antes_de`, `contenido` | Añade filas a una tabla, copiando el formato de una fila modelo |
| `duplicar_tabla` | `tabla`, `despues_de`, `veces`, `celdas` | Copia una tabla tras un párrafo o tabla, una vez por copia |
| `borrar` | `id` | Borra un párrafo, una tabla o una fila |

Textos: una cadena es un párrafo; una lista de cadenas son varios párrafos. Una cadena no
admite saltos de línea ni caracteres de control (`RELLENO_INVALIDO`): para varios
párrafos, usa una lista. `duplicar_tabla` admite hasta 40 copias.

Ids (los de `tiza leer`): `p<n>` párrafo, `t<n>` tabla, `t<n>.f<i>` fila y `t<n>.f<i>.c<j>`
celda. Los encabezados y pies de página llevan el prefijo `e<n>.` (encabezado) o `pie<n>.`
(pie) delante de esos mismos ids: `e1.p1`, `pie2.t1.f1.c1`. `n` cuenta desde 1 por la primera
aparición de cada parte en el documento; una parte que usan varias secciones sale una vez, y
una parte sin texto no sale (pero su número se reserva). `e1` a secas no es un id válido. En una tabla anidada, la ruta completa (`t1.f1.c1.t1.f2.c1.p1`). Filas y celdas
empiezan en 1 y las combinadas desplazan los números. En `duplicar_tabla.celdas` las celdas
van relativas a la tabla copiada (`f1.c1`), solo las de primer nivel.

Detalles por operación:

- **`reemplazar`** en un párrafo: el texto nuevo toma el formato del primer trozo de texto
  del párrafo; el resto de trozos y los campos se quitan. Si el párrafo es un control de
  contenido («Haga clic aquí…»), el control se conserva y deja de mostrar el texto de
  ejemplo. En una celda se sustituye todo su contenido, incluida una tabla anidada: para
  conservarla, usa sus ids. Para cambiar el texto de un control y conservarlo, reemplaza el
  id del párrafo, no el de la celda.
- **`sustituir`**: cambia `buscar` por `poner` en el párrafo o la celda `id` y no toca nada más:
  runs, formato, tabuladores, saltos, campos y controles se quedan como están. Es la
  operación para cambiar solo el curso o una fecha dentro de un texto con formato
  (`Programación del Departamento<tab>Curso 2026/27`), donde `reemplazar` lo dejaría en un
  solo run sin el tabulador. `buscar` y `poner` son textos no vacíos, sin saltos de línea ni
  caracteres de control. `buscar` se compara con cada trozo de texto (`w:t`) por separado,
  distinguiendo mayúsculas: en la lectura un tabulador o un salto salen como un espacio, pero
  cortan el texto, así que busca dentro de uno solo de los lados. Si `buscar` aparece más de
  una vez en el bloque, se cambian todas y `sustituciones` en la salida dice cuántas en
  total. Sin apariciones, `TEXTO_NO_ENCONTRADO`; si alguna está repartida entre varios
  trozos (por un cambio de formato o un campo), `TEXTO_PARTIDO`: usa entonces `reemplazar`.
  En una celda se miran sus párrafos, no las tablas anidadas. Varias `sustituir` sobre el
  mismo id se aplican en orden, cada una sobre el texto que dejó la anterior. Se ignora el
  texto de respaldo de un cuadro de texto y lo borrado con el control de cambios. Si un
  cuadro de texto solo tiene texto de respaldo (`mc:Fallback`, sin `mc:Choice`), `tiza leer`
  lo muestra, pero `sustituir` y `reemplazar` no lo cambian y dan `TEXTO_NO_ENCONTRADO`.
  En un pie con número de página, `sustituir` y no `reemplazar`: `reemplazar` quita el campo
  del número.
- **`insertar_despues`**: tras un párrafo copia su estilo y su formato; tras una tabla, el
  estilo de párrafo normal. Con `estilo` (el nombre que ves en Word o su identificador)
  usa ese estilo; si la plantilla no lo tiene, `ESTILO_INEXISTENTE` con la lista.
- **`filas`**: `modelo` es el número de una fila normal, la que se copia; nunca la del
  total. `antes_de` es el número de la fila ante la que se inserta, o `final`. `contenido`
  es una lista de filas; cada fila, una lista de celdas, con el mismo número de celdas que
  la fila modelo (`CELDAS_NO_COINCIDEN`). Cada celda es un texto o una lista de párrafos.
  La fila modelo no puede tener celdas fusionadas (`FILA_MODELO_FUSIONADA`), ni `antes_de`
  ser la continuación de una fusión vertical (`FILA_FUSIONADA`): insertar ahí la partiría.
- **`duplicar_tabla`**: copia la tabla tras `despues_de`, una copia por elemento de
  `celdas`. `veces` debe coincidir con el número de elementos (`{}` es una copia sin
  cambios). Cada copia sale como está la tabla en ese momento.
- **`borrar`**: un párrafo, una tabla o una fila (`t<n>.f<i>`). Una fila con celdas
  fusionadas en vertical no se borra (`FILA_FUSIONADA`): reemplaza su texto.

Orden y conflictos:

- Las operaciones se aplican en el orden del fichero, pero todos los ids se resuelven
  contra la plantilla original. Así, un `duplicar_tabla` copia lo que le hayas cambiado
  antes en esa tabla. Varias operaciones que insertan tras la misma ancla (`insertar_despues`
  y `duplicar_tabla`) quedan en el orden del fichero: la segunda va detrás de la primera.
- `OPERACIONES_EN_CONFLICTO`, con las dos posiciones (p. ej. `operaciones[1]` y
  `operaciones[4]`), si: se borra un bloque y otra operación lo toca, lo usa como
  referencia (`tabla`, `despues_de`, `modelo`, `antes_de`) o lo tiene dentro; se borra un
  bloque que está dentro de uno que otra operación reemplaza, sustituye o borra; se repite
  un `reemplazar` o un `borrar` del mismo id; o se sustituye texto en un bloque que otra
  operación reemplaza (el mismo, uno que lo contiene o uno que está dentro). Añadir filas a una tabla cuya fila se borra no
  es conflicto, siempre que la fila modelo y la de `antes_de` sean otras.

Límites: el YAML pesa como mucho 2 MB, no admite anclas ni alias
(`&` y `*`) ni claves repetidas. Una clave desconocida da `RELLENO_INVALIDO` con su ruta y las
claves válidas (`operaciones[2].colour: clave desconocida; válidas: id, texto`). Los índices de las rutas empiezan en 0.

Cosas que tiza no hace o no comprueba: «nunca la fila de total» es un consejo para elegir la
fila modelo, no una comprobación. Un salto de línea final en un texto se quita. Al reemplazar
no se admiten los campos que cruzan párrafos ni el texto dentro de cuadros de texto.

Salida: `tiza rellenar relleno.yaml` imprime un JSON en la pantalla. Si sale bien (código 0):
`plantilla`, `salida`, `operaciones` (cuántas se aplicaron), `sustituciones` (cuántas
apariciones cambiaron las `sustituir`, 0 si no hay) y `avisos`. Si falla (código 2):
`error`, `detalle` y `que_hacer`. El Word solo se crea al final: si algo falla antes, no queda
nada escrito, y la plantilla nunca se toca.

Códigos de error:

| Código | Qué pasa |
|---|---|
| `RELLENO_INVALIDO` | El YAML no tiene la forma descrita; el mensaje dice dónde |
| `OPERACIONES_EN_CONFLICTO` | Dos operaciones se contradicen sobre el mismo bloque |
| `DOCUMENTO_EXISTE` | La salida ya existe o es la plantilla |
| `DOCUMENTO_AUSENTE` | No existe la plantilla |
| `FICHERO_FUERA`, `FICHERO_TEMPORAL`, `FORMATO_NO_ADMITIDO` | Una ruta sale de la carpeta, es oculta o un temporal de Word (`~$`), o no tiene la extensión que toca |
| `PLANTILLA_CAMBIADA` | El `sha256` no coincide: vuelve a `tiza leer` |
| `ID_DESCONOCIDO` | Un id no existe o no es del tipo que pide la operación |
| `TEXTO_NO_ENCONTRADO`, `TEXTO_PARTIDO` | `sustituir` no encuentra `buscar` en el bloque, o lo encuentra repartido entre varios trozos de texto (usa `reemplazar`) |
| `CELDAS_NO_COINCIDEN` | Una fila nueva no tiene las celdas de la fila modelo |
| `FILA_MODELO_FUSIONADA`, `FILA_FUSIONADA` | Una fila con celdas fusionadas no se puede copiar ni borrar |
| `ESTILO_INEXISTENTE` | La plantilla no tiene ese estilo de párrafo |
| `DOCUMENTO_PROTEGIDO`, `DOCUMENTO_DEMASIADO_GRANDE` | Vienen de la lectura de la plantilla (la misma de `tiza leer`): cifrada con contraseña, o descomprimida o de más de 30 MB. (`tiza documento` usa `FICHERO_DEMASIADO_GRANDE` para su `.md`; aquí no sale) |
| `FICHERO_BLOQUEADO` | La plantilla o el YAML están abiertos o bloqueados |
| `DOCUMENTO_NO_ESCRIBIBLE` | No se pudo crear o escribir el Word de salida (el mismo código que `tiza documento`) |
| `NOMBRE_NO_VALIDO` | Un nombre de fichero lleva símbolos que tiza no admite en su informe |

Avisos: `INDICE_SE_ACTUALIZA_AL_ABRIR` (la plantilla tiene índice: al abrir la copia, Word
pregunta si actualizar los campos y, si se dice que no, el índice queda sin actualizar) y `CAMBIOS_SIN_ACEPTAR` (la plantilla tiene cambios
sin aceptar, que se leen como aceptados).
