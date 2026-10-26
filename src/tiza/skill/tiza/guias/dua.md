# Guía: material y tests para toda la clase

Se aplica **siempre** que escribas una página, una tarea, un cuestionario, un H5P o una
unidad, aunque el docente no lo pida. Son buenas prácticas del Diseño Universal para el
Aprendizaje (DUA): el material se diseña desde el principio para toda la clase, en vez de
adaptarlo después. La maqueta y la accesibilidad del HTML siguen en `guias/estilo.md`.

## 1. Alcance

- Cambia **cómo escribes** lo que te piden, no añade piezas. Si piden un test, escribe un
  test. Lo demás (una práctica sin nota antes de un test que puntúa, un glosario, una versión
  de refuerzo) ofrécelo en una frase y no lo crees sin un sí.
- **Manda el docente.** Si pide algo que choca con la guía (un examen con el tiempo justo,
  sin retroalimentación), avísale una vez, con el motivo en llano, y hazlo como lo pide. Lo
  que no choca lo sigues aplicando.
- **Mandan los límites de `guias/estilo.md`.** Si con el glosario la página pasa de 600
  palabras, pártela y propónselo; no la estires.
- **Sin jerga.** No le hables al docente de «DUA» ni de pautas. Al proponer, cuenta en una
  frase tres o cuatro cosas que notará: «cada idea va con texto y con un dibujo, el
  cuestionario explica cada opción y la tarea se puede entregar de varias formas con los
  mismos criterios».

## 2. Para toda la clase, nunca para un alumno

- Si el docente te da un nombre o un diagnóstico («tengo un alumno con dislexia»), dile una
  vez que no te dé datos del alumnado. No los uses ni los escribas en ningún fichero (ni en
  `nombre`, ni en `retro`, ni en comentarios) y aplica medidas que sirvan a todos: frases
  cortas, una idea por pregunta, tiempo holgado.
- Lo de un alumno concreto (más tiempo en un cuestionario, otro plazo, otro formato) lo pone
  el docente a mano en el aula: tiza no toca nada por alumno.
- Refuerzo y ampliación son actividades distintas, con nombre por su contenido («Refuerzo:
  fracciones paso a paso»), nunca por alumnos ni por grupos. Se publican en todos los cursos
  reales; si el docente quiere que solo las vea un grupo, lo pone a mano en el aula.

## 3. Cada idea, de más de una forma

- Cada idea clave va con texto y con otra forma: una imagen o un esquema, un ejemplo
  resuelto, una tabla, un vídeo o una actividad H5P.
- Frases cortas, una idea por párrafo, vocabulario del nivel. Simplifica la forma, no el
  contenido: los términos de la materia se quedan y se explican.
- Bloque «Palabras de esta página» (`guias/estilo.md`) con los términos nuevos de esa
  página, de 2 a 6. Si la unidad suma más de 12, una página de glosario y un H5P `tarjetas`.
- Las imágenes, los vídeos y los audios los trae el docente: no inventes direcciones. Al
  proponer, pídele los que necesita cada página, con lo que debe mostrar cada uno en una
  línea («esquema del algoritmo: entrada, cálculo y salida»). Si no los tiene, deja el hueco
  visible (sección 7). Si vienen de otro sitio o no son del
  docente, sigue `guias/licencias.md`.
- **Vídeo**: solo en un iframe de los servidores permitidos y con el enlace que te dé el
  docente. Pídele que compruebe que tiene subtítulos (tú no puedes verlo) y escribe debajo
  un resumen en texto.
- **Audio**: no hay `<audio>`. Un fichero de audio de la carpeta se enlaza
  (`<a href="audio/lectura.mp3">Escucha la lectura (1 min)</a>`) y va con su transcripción.
  En una pregunta de cuestionario no cabe (`RECURSO_EN_PREGUNTA`).
- **Fórmulas** en LaTeX, nunca como imagen. Donde no caben (H5P, respuestas de un
  emparejamiento), escríbelas en texto: «1/2».

## 4. Para qué sirve, práctica y elección

- El `lead` y «Qué vas a aprender» dicen para qué sirve lo que se aprende, con una situación
  cercana.
- Antes de lo que puntúa, práctica sin nota con retroalimentación (H5P, o cuestionario con
  `intentos: ilimitados`), sin `tiempo_limite`.
- Cuando se pueda, que el alumnado elija: el ejemplo, la forma de entrega, una ampliación.

## 5. Tareas: varias formas de demostrar lo aprendido

- En «Qué entregas», ofrece varias formas (texto, foto, esquema, audio, vídeo corto), con
  los mismos criterios para todas.
- tiza no fija ni ve los **tipos de entrega** de la tarea (texto en línea, ficheros, cuántos y
  de qué tamaño): los activa el docente en los ajustes de la tarea. No digas nunca lo que la
  tarea admite: pregúntale si lo tiene activado.
- «Cómo se califica» dice qué se demuestra, no con qué medio: «El reparto es en cuatro
  partes iguales», no «El dibujo reparte…».
- Andamiaje: pasos numerados, una lista «Antes de entregar, comprueba» y un ejemplo resuelto
  plegado, de otro caso distinto del que se pide.

## 6. Tests

- Una idea por pregunta, en positivo: sin «no», «excepto» ni dobles negaciones.
- Distractores que salen de errores reales del alumnado, no absurdos. Nada de «todas las
  anteriores» ni «ninguna de las anteriores».
- Opciones de longitud parecida: que la correcta no se adivine por ser la más larga.
- Retroalimentación que explique. En `opcion_multiple`, `retro` en **cada** opción (por qué
  vale o qué error es) y `retro` general que diga dónde repasar. Los demás tipos solo tienen
  `retro` general: pon ahí la explicación.
- Varias correctas: el enunciado dice cuántas hay que marcar y que las incorrectas restan.
  Si el docente no quiere penalizar, una sola correcta.
- Pregunta con imagen: el `alt` describe la figura sin dar la respuesta, y los datos que no
  son la respuesta van también en el enunciado, para que se pueda contestar sin verla. Si lo
  que se evalúa es justo leer la figura (una gráfica, un mapa), pregúntaselo al docente.
- Tiempo: una práctica no lleva `tiempo_limite`. En un examen, si propones un tiempo, di cómo
  lo has calculado.
- Las preguntas miden lo que dice el `evalua` de la actividad.
- tiza no ajusta cuándo se ve la retroalimentación: tras publicar en pruebas, pide al docente
  que compruebe que se ve al terminar el intento.

## 7. Huecos que faltan

tiza no detecta los `[RELLENA: …]`: un hueco olvidado se publica. Si falta una imagen, un
vídeo o un dato, deja un aviso que se vea:

```html
<div class="alert alert-warning">
  <p class="mb-0"><strong>Falta:</strong> [RELLENA: dibujo de una pizza partida en cuatro trozos iguales]</p>
</div>
```

Al terminar, dile al docente cuántos huecos quedan y en qué ficheros. Pueden ir al curso de pruebas;
al real, no, salvo que el docente lo decida.

## 8. Material ya publicado

Si el docente pide mejorar algo que ya está en el aula («hazlo más accesible»), sigue
`guias/juntar.md`. Propón una lista numerada en dos bloques, retoques y piezas nuevas, y
aplica solo los números que elija. Un cuestionario o un H5P con intentos ya no se cambia:
ofrece uno nuevo con otro `nombre`.

## 9. Normativa

No digas que la ley obliga a aplicar el DUA sin citarlo con `tiza normativa`. Busca
`tiza normativa buscar "diseño universal"` (no «DUA»: la búsqueda va por trozos de palabra y
saca «individual»). Si no sale para esa etapa, lo más cercano son las medidas de atención a la
diversidad de `tiza normativa programacion …`, que no son lo mismo. Lo que no salga de la
normativa es propuesta tuya: en la unidad y en la programación, su procedencia es «propuesta».
