# Del currículo al aula: una conversación de ejemplo

Este documento muestra cómo un agente con `tiza` puede ayudarte a llevar el
currículo oficial y tu programación didáctica hasta el aula virtual. La
conversación y los códigos de los criterios son **inventados** y solo sirven de
ilustración. En tu caso, saldrán de tus documentos.

## Antes de empezar: qué dejar en la carpeta

En la carpeta de la asignatura, la misma donde abres `tiza empezar`, deja:

- **El currículo de tu materia**: el decreto de tu comunidad autónoma o el real
  decreto de enseñanzas mínimas, en PDF o en texto. Basta con la parte de tu
  materia. Si tu agente no lee PDF, pásalo antes a texto.
- **Tu programación didáctica**, sin ningún dato del alumnado: nada de nombres,
  listas de clase, notas, informes ni adaptaciones de alumnos concretos. Si la
  tuya los tiene, guarda una copia sin ellos y deja solo esa.
- **Opcional**: tu calendario escolar en `calendario.toml` (mira la
  [guía de uso](guia.md#calendario-y-cambio-de-fechas)) y el material propio que
  quieras reutilizar (apuntes, imágenes, fichas).

El agente solo lee lo que hay en esa carpeta. No consulta el aula ni ve el
trabajo de tu alumnado.

## La conversación

> **Docente:** Lee la programación y el decreto y prepárame la unidad de
> fracciones de 1.º de ESO.

> **Agente:** He leído `programacion-mates-1eso.pdf` y `decreto-matematicas.pdf`.
> Antes de proponerte nada, necesito saber:
> 1. ¿Cuántas sesiones tiene la unidad y a partir de qué fecha?
> 2. ¿En qué sección del aula va? ¿Te vale «Fracciones»?
> 3. Tu programación sitúa esta unidad en la situación de aprendizaje 3 (SA 3),
>    «El mercado del barrio». ¿Quieres que el producto final sea el presupuesto de
>    una compra, como allí se propone?

> **Docente:** Seis sesiones desde el 3 de noviembre, sección «Fracciones», y sí
> al presupuesto.

> **Agente:** Te propongo esta secuencia. Indico de dónde sale cada referencia
> curricular:
>
> | # | Actividad | Tipo | Criterios | De dónde sale |
> |---|---|---|---|---|
> | 1 | Presentación: «El mercado del barrio» | etiqueta | — | Programación, SA 3 |
> | 2 | Qué es una fracción | página | CE 1.1 | Decreto, anexo II; programación, pág. 14 |
> | 3 | Fracciones equivalentes y comparación | página | CE 1.1, CE 2.2 | Decreto, anexo II |
> | 4 | Práctica: completa las frases (numerador, denominador…) | H5P | CE 1.1 | — (práctica sin nota) |
> | 5 | Comprobación | cuestionario, 10 preguntas | CE 1.1, CE 2.2 | Programación, instrumentos de evaluación |
> | 6 | Producto final: presupuesto de la compra | tarea con rúbrica | CE 2.2, CE 6.1 | Programación, SA 3 |
> | 7 | Refuerzo y ampliación | 2 H5P opcionales | CE 1.1 | Programación, atención a la diversidad |
>
> Cada actividad se abre al completar la anterior. La tarea se abre el 12 de
> noviembre y se entrega el 17. No cae en festivo según tu calendario. Revisa
> sobre todo los códigos de criterio: los he copiado de tus documentos, pero
> `tiza` no los comprueba. ¿Lo preparo así?

> **Docente:** Sí, pero en la tarea pon la rúbrica en lenguaje para alumnos de
> 12 años.

> **Agente:** Hecho. He escrito los siete ficheros, los he comprobado con
> `tiza comprobar` y los he publicado en tu curso de pruebas. Tienes el enlace
> «Ver en el aula» de cada uno. Cuando lo revises, dime si los publico en el
> curso real.

Tú revisas la unidad en el curso de pruebas igual que la verá tu alumnado. Si
algo no te convence, se lo pides al agente y vuelve a publicarla en pruebas.
Cuando te guste, se la pides para el curso real: en tu terminal ves qué se
publica, en qué cursos y con qué fechas, y confirmas con `s`.

## Más cosas que puedes pedirle

- *«¿Qué criterios de la programación del primer trimestre no tienen todavía
  ninguna actividad en esta carpeta?»* Te devuelve los huecos para que decidas
  qué preparar.
- *«Haz una tabla con cada actividad de la unidad y los criterios que trabaja.»*
  Te sirve para tu programación o tu memoria, sin tocar el aula.
- *«Añade a cada página un recuadro con lo que vamos a aprender, en lenguaje
  sencillo.»* Los objetivos de aprendizaje, visibles para tu alumnado.
- *«Retrasa una semana la unidad: hemos perdido dos sesiones.»* Solo cambian las
  fechas de tareas y cuestionarios. Lo demás, y los intentos ya hechos, quedan
  como estaban.
- *«Copia la unidad a los tres grupos de 1.º.»* Si tienes varios cursos reales,
  una petición llega a todos y la confirmas curso a curso.

## Lo que conviene tener presente

- **Revisa lo curricular tú.** El agente parte de tus documentos y no debe
  inventar criterios, pero puede equivocarse al leerlos o al relacionarlos.
  `tiza` comprueba el formato y la seguridad de lo que se publica, no el
  currículo.
- **Nada de datos del alumnado.** Las medidas de atención a la diversidad se
  convierten en actividades de refuerzo o ampliación para quien las necesite,
  nunca en actividades con nombres de alumnos o grupos. Mira
  [Protección de datos](proteccion-de-datos.md).
- **La rúbrica es texto.** La rúbrica va en la descripción de la tarea para que
  tu alumnado la lea. `tiza` no configura la calificación avanzada de Moodle.
- **Un cuestionario con intentos ya no se cambia.** Revisa bien las respuestas
  correctas en pruebas antes de publicarlo en real.
