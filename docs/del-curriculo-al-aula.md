# Del currículo al aula: una conversación de ejemplo

Cómo un agente con `tiza` te ayuda a pasar de tu programación didáctica a una unidad
en el aula virtual. La conversación, el centro y los códigos son **inventados**: en tu
caso saldrán de tus documentos.

## Qué hace cada pieza

- **`tiza normativa`** trae la normativa de la Comunidad de Madrid del curso 2026-27 (mira
  `tiza normativa catalogo`). El agente cita de ahí, con código, texto literal y procedencia.
  No busca normativa en internet.
- **`tiza leer`** convierte tu programación (Word o PDF) en un texto que el agente puede
  leer sin errores. El Word se lee mejor que el PDF, sobre todo si tiene tablas.
- **`tiza documento`** escribe la unidad como un Word sencillo, para que la revises o la
  incorpores a tu programación. Nunca sobrescribe un Word tuyo: si el nombre existe, crea otro.

El agente solo lee lo que hay en la carpeta de la asignatura. No consulta el aula ni ve el
trabajo de tu alumnado.

## Antes de empezar: qué dejar en la carpeta

- **Tu programación**, en Word si puedes, **sin datos del alumnado**: nada de nombres,
  listas de clase, notas ni adaptaciones de alumnos concretos. Si la tuya los tiene,
  guarda una copia sin ellos y deja solo esa. Si el agente encuentra alguno, no lo usa,
  borra su lectura y te pide la copia.
- **Si existen**: el currículo de tu optativa de centro, cómo evalúa y pondera tu
  departamento y la programación del ciclo (en FP). El agente te los pedirá todos a la vez.
- **Opcional**: tu calendario en `calendario.toml` (mira la
  [guía de uso](guia.md#calendario-y-cambio-de-fechas)) y tu material propio.

## La conversación

> **Docente:** Toca la unidad de trabajo 3 de mi programación de Sistemas Informáticos.

> **Agente:** Para empezar necesito, de una vez: tu programación en Word (de ella sale lo que
> ya decidiste para la UT 3) y la programación del ciclo, si la tienes. Sin nombres de
> alumnado, por favor.

> **Docente:** Te dejo `programacion-SI.docx`. Lo otro no lo tengo.

> **Agente:** He leído tu programación. La UT 3 está en la tabla de la pág. 12, con 18 horas,
> 3 RA y sus criterios. Dos cosas: la tabla cita un criterio del RA 2 que en la normativa de
> este curso tiene otro texto, y hay cambios sin aceptar en el apartado de evaluación (los
> he leído como aceptados). ¿Mantengo tu redacción del criterio o uso la de la norma?

> **Docente:** Mantén la mía.

> **Agente:** Te propongo la unidad:
>
> | Código | Texto literal | Procedencia |
> |---|---|---|
> | RA2 | (texto de la norma) | Normativa (tiza) |
> | CE 2.c | (texto de tu programación) | Tu programación, tabla de la UT 3 |
>
> Tus instrumentos y ponderaciones los he copiado de tu programación; la secuencia de
> actividades es propuesta mía. Te dejo `unidad-3.docx`. ¿Preparo las actividades en el
> curso de pruebas?

Después, el camino de siempre: el agente escribe las actividades, las publica **ocultas** en
tu curso de pruebas, las revisas y, cuando te guste, se la pides para el curso real. En tu
terminal ves qué se publica y confirmas con `s`.

## Lo que conviene tener presente

- **Revisa lo curricular tú.** El agente dice de dónde sale cada referencia: normativa de
  tiza, tus documentos (que tiza no comprueba) o propuesta suya. No debe inventar criterios,
  pero puede equivocarse al leer o relacionar.
- **Si tu programación y la normativa no coinciden**, el agente te enseña las dos versiones
  y decides tú. Antes de hablar de error, comprueba si hay una corrección de errores.
- **Nada de datos del alumnado.** Las medidas de atención a la diversidad se convierten en
  actividades de refuerzo o ampliación para quien las necesite, nunca con nombres. Mira
  [Protección de datos](proteccion-de-datos.md).
- **Un cuestionario con intentos ya no se cambia.** Revisa las respuestas correctas en
  pruebas antes de publicarlo en real.
