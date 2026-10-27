# Guía: estilo de las páginas y las tareas

Se usa antes de escribir una página, una tarea o una etiqueta. Léela entera y escribe en
`.html`. El resultado debe verse cuidado, igual en todas las páginas del curso y bien en el
tema del aula, sin imitar ninguna marca. Lo que cuenta cada pieza (una idea de más de una
forma, glosario, tareas con varias formas de entrega, tests) sigue `guias/dua.md`.

## 1. Cuándo se usa

- Páginas y etiquetas: `.html` por defecto.
- Descripción de una tarea: `.html` si tiene **más de un párrafo, una lista o una tabla**.
  Si es una sola frase o un párrafo corto, `.md`.
- Cuestionarios y H5P: siguen en `.md`.
- Usa `.md` solo si el docente lo pide («prefiero editarlo yo en Markdown») o el texto es
  muy breve.
- Si vas a escribir una página o una tarea en `.html`, copia la plantilla de la sección 6
  y rellénala. No compongas la página bloque a bloque.

Un `.html` lleva el mismo bloque YAML (`---`) arriba que un `.md`. Después de ese bloque no
se interpreta Markdown: ni `**negrita**`, ni `#`, ni `-` de lista. Las fórmulas LaTeX se
escriben igual, con `\( … \)` y `\[ … \]`.

## 2. Principios

- **La anchura de lectura la pone el contenedor.** Toda página y toda descripción de tarea
  en `.html` va dentro de `<div style="max-width:52rem">`, alineada a la izquierda. Las
  etiquetas no lo llevan: se ven dentro de la página del curso.
- **El color lo pone el tema del aula.** Usa clases semánticas: `alert-info`, `alert-warning`,
  `alert-success`, `card` con `border-primary`, `text-primary`, `bg-light`. Así la página
  sigue el tema de cada aula.
- **El `style` en línea es para medidas**: márgenes, radios, rejilla, anchura máxima. Como
  mucho, un acento. Nunca fijes colores de texto sobre fondos inventados ni colores de marca.
- **Solo clases que existen en el aula** (Moodle 4.5 usa Bootstrap 4.6.2). Algunas del
  Bootstrap 5 pasan el filtro de tiza pero el aula no las conoce, y no hacen nada. Usa el
  equivalente:

  | No uses | Usa |
  |---|---|
  | `fw-bold` | `font-weight-bold` |
  | `fst-italic` | `font-italic` |
  | `text-bg-primary` | `bg-primary text-white` |
  | `rounded-3` | `rounded-lg` |
  | `gap-3` | márgenes (`mr-2`, `mb-3`) |
  | `g-3` | nada: la separación de las columnas ya viene hecha |
  | `d-grid` | `d-block` |
  | `ratio` | `style="aspect-ratio:16/9"` |
  | `fs-5` | `lead` o `small` |

  Tampoco existen `fw-*`, `fst-*`, `text-bg-*`, `gap-*`, `g-*` ni `fs-*` en general.
- **Un catálogo cerrado de bloques** (sección 5), siempre los mismos. Así las páginas de un
  curso se parecen entre sí. No inventes bloques nuevos.
- **Una idea por bloque.** Nada de decorar por decorar: como mucho un acento visual por bloque.
- **Si el concepto es visual** (un diagrama, un esquema, un montaje), no lo describas con una
  tabla ni con un párrafo interminable: si son formas y relaciones, dibuja un esquema sencillo
  con `tiza esquema` (`guias/esquemas.md`); si es una foto, un mapa real o material ajeno,
  pídelo al docente o deja un hueco marcado (`[RELLENA: imagen de …]`) y avísale. Las imágenes
  van con `alt` y `img-fluid`, y el `alt` de un esquema dice la relación, no solo el título. Si
  la imagen no es del docente ni tuya, sigue `guias/licencias.md` para la autoría y la licencia:
  su bloque de autoría (`<figure>` con `<figcaption>`) es la excepción autorizada a este
  catálogo.

## 3. Accesibilidad

- Títulos desde `h3`: el aula ya pone el `h2` con el nombre de la actividad. No repitas ese
  nombre en un `h3` ni pongas un `badge` con la sesión. Una página empieza por un `p.lead`
  y el bloque «Qué vas a aprender»; los apartados son `h3` y los títulos de los bloques,
  `h4`. No saltes niveles (`h3`, luego `h4`; nunca `h3` y luego `h5`).
- Contraste suficiente (AA): no pongas colores propios al texto; deja los del tema.
- El color nunca es el único significado. El bloque «Importante» lleva la palabra
  «Importante», no solo el amarillo.
- Toda imagen lleva `alt` que diga lo que muestra. Vacío (`alt=""`) solo si es decorativa.
- Sin anchos fijos en píxeles para cajas e imágenes: que funcione en el móvil. Imágenes con
  `img-fluid`, `max-width` en `%` o `rem`, columnas `col-md-*` (se apilan en pantallas pequeñas).
- Enlaces con texto que diga adónde van: «Resumen de la unidad», no «pincha aquí».
- Tablas con `<th scope="col">` en la cabecera.

## 4. Iconos

Font Awesome 6 está cargado en el aula. Reglas:

- Solo en `<i>` o `<span>`, siempre con `aria-hidden="true"`.
- Siempre al lado de un texto que diga lo mismo: el icono adorna, no informa.
- Clases: `fa-solid` (o `fa-regular`), uno de la lista y, si quieres alinear, `fa-fw`.
- Lista cerrada (cualquier otro no pasa el filtro): `fa-circle-info`, `fa-lightbulb`,
  `fa-triangle-exclamation`, `fa-circle-check`, `fa-circle-question`, `fa-book`,
  `fa-book-open`, `fa-pen`, `fa-list-check`, `fa-bullseye`, `fa-clock`, `fa-calendar`,
  `fa-link`, `fa-video`, `fa-download`, `fa-star`, `fa-flag`, `fa-puzzle-piece`,
  `fa-graduation-cap`, `fa-arrow-right`.
- Sin animaciones ni tamaños. Un icono por bloque como mucho, en su título. Emojis: no.

```html
<h4><i class="fa-solid fa-fw fa-lightbulb" aria-hidden="true"></i> Recuerda</h4>
```

## 5. Catálogo de bloques

### Cabecera

Sin `h3` que repita el nombre de la actividad y sin `badge`. Empieza con una frase de
contexto y el bloque «Qué vas a aprender».

```html
<p class="lead">Qué son las fracciones, cómo se comparan y para qué sirven.</p>

<div class="alert alert-info">
  <h4><i class="fa-solid fa-fw fa-bullseye" aria-hidden="true"></i> Qué vas a aprender</h4>
  <ul class="mb-0">
    <li>Reconocer una fracción en una situación real.</li>
    <li>Comparar dos fracciones.</li>
  </ul>
</div>
```

### Explicación

Texto normal. `h3`/`h4` para los apartados, `<p>`, listas, `<strong>` para lo esencial y
`<mark>` para una palabra clave (poco).

```html
<h3>Qué es una fracción</h3>
<p>Una fracción reparte un todo en <strong>partes iguales</strong>. El número de abajo dice
en cuántas partes se divide; el de arriba, cuántas tomamos.</p>
<h4>Dos casos habituales</h4>
<ol>
  <li>Fracción propia: el numerador es menor que el denominador.</li>
  <li>Fracción impropia: es mayor y vale más que <mark>una unidad</mark>.</li>
</ol>
```

### Recuerda e Importante

«Recuerda» va en `alert-success` o en una tarjeta con `border-primary`. «Importante» va en
`alert-warning` y lleva siempre la palabra.

```html
<div class="alert alert-success">
  <h4><i class="fa-solid fa-fw fa-lightbulb" aria-hidden="true"></i> Recuerda</h4>
  <p class="mb-0">Dos fracciones son equivalentes si representan la misma cantidad.</p>
</div>
<div class="alert alert-warning">
  <h4><i class="fa-solid fa-fw fa-triangle-exclamation" aria-hidden="true"></i> Importante</h4>
  <p class="mb-0">El denominador nunca puede ser cero.</p>
</div>
```

```html
<div class="card border-primary mb-3">
  <div class="card-body">
    <h4 class="card-title text-primary">Recuerda</h4>
    <p class="card-text">Para comparar fracciones, busca primero un denominador común.</p>
  </div>
</div>
```

### Ejemplo resuelto

El enunciado se ve; la solución va plegada. El `summary` nombra lo que se despliega
(«Solución», «Los pasos», «Una mejora posible»), sin empezar por «Ver».

```html
<div class="card bg-light mb-3">
  <div class="card-body">
    <h4 class="card-title">Ejemplo</h4>
    <p class="card-text">¿Qué fracción es mayor, 2/3 o 3/5?</p>
    <details>
      <summary>Solución</summary>
      <p class="mt-2 mb-0">Con denominador 15: 10/15 y 9/15. Es mayor <strong>2/3</strong>.</p>
    </details>
  </div>
</div>
```

### Código

Título corto opcional (`h4`), el bloque de código y una frase que diga qué hace. El `pre`
lleva siempre estas clases y este estilo; el `code` conserva su `language-*`.

Regla del `<code>` en línea: solo lo que el alumno teclea (`print`, `int`, un nombre de
fichero). Nunca en títulos, en la primera columna de una tabla ni para nombrar un concepto:
«la clase String», no `String`.

```html
<h4>Código: sumar los números del 1 al 10</h4>
<p>Este bucle recorre los números y acumula el total en una variable.</p>
<pre class="bg-light border rounded p-3" style="line-height:1.5;font-size:0.9rem"><code class="language-java">int total = 0;
for (int i = 1; i != 11; i++) {
    total += i;
}</code></pre>
```

### Actividad o tarea

Lo que hace el alumnado ahora. El botón-enlace es solo para una dirección externa real (una
ficha en la web); `btn` solo vale en `<a>`. Nunca enlaces otra actividad del curso ni otro
fichero de la carpeta: nómbrala entre comillas («2. Comparar fracciones»), que el aula ya
lleva a la siguiente (enlazar un `.md` o `.html` de la carpeta da `ENLACE_A_DOCUMENTO`).

```html
<div class="card border-primary mb-3">
  <div class="card-body">
    <h4 class="card-title"><i class="fa-solid fa-fw fa-pen" aria-hidden="true"></i> Actividad</h4>
    <p class="card-text">Resuelve los ejercicios de la ficha y súbela a la tarea.</p>
    <a class="btn btn-primary" href="https://www.ejemplo.org/ficha">Abrir la ficha de ejercicios</a>
  </div>
</div>
```

### Para saber más

Lista de enlaces con texto descriptivo.

```html
<h4><i class="fa-solid fa-fw fa-book-open" aria-hidden="true"></i> Para saber más</h4>
<ul>
  <li><a href="https://www.ejemplo.org/fracciones">Teoría de las fracciones, con ejemplos</a></li>
  <li><a href="https://www.ejemplo.org/juego">Juego para practicar la comparación</a></li>
</ul>
```

### Tarjetas en dos columnas

`mb-3` en cada columna, para que en el móvil no se peguen. Como mucho dos columnas
(`col-md-6`).

```html
<div class="row">
  <div class="col-md-6 mb-3">
    <div class="card">
      <div class="card-body">
        <h4 class="card-title">Fracción propia</h4>
        <p class="card-text">El numerador es menor que el denominador: 3/4.</p>
      </div>
    </div>
  </div>
  <div class="col-md-6 mb-3">
    <div class="card">
      <div class="card-body">
        <h4 class="card-title">Fracción impropia</h4>
        <p class="card-text">El numerador es mayor que el denominador: 7/4.</p>
      </div>
    </div>
  </div>
</div>
```

### Tabla

`table table-striped`. Si es ancha, envuélvela en un `div` con `table-responsive`.

```html
<div class="table-responsive">
  <table class="table table-striped">
    <thead>
      <tr><th scope="col">Fracción</th><th scope="col">Decimal</th></tr>
    </thead>
    <tbody>
      <tr><td>1/2</td><td>0,5</td></tr>
      <tr><td>3/4</td><td>0,75</td></tr>
    </tbody>
  </table>
</div>
```

### Palabras de esta página

Los términos nuevos de la página, de 2 a 6, con una definición corta cada uno. Va antes del
«Resumen».

```html
<div class="card bg-light mb-3">
  <div class="card-body">
    <h4 class="card-title"><i class="fa-solid fa-fw fa-book" aria-hidden="true"></i> Palabras de esta página</h4>
    <dl class="mb-0">
      <dt>Numerador</dt><dd>El número de arriba: cuántas partes tomamos.</dd>
      <dt>Denominador</dt><dd>El número de abajo: en cuántas partes iguales se reparte el todo.</dd>
    </dl>
  </div>
</div>
```

### Cierre o resumen

```html
<div class="alert alert-success">
  <h4><i class="fa-solid fa-fw fa-circle-check" aria-hidden="true"></i> Resumen</h4>
  <ul class="mb-0">
    <li>Una fracción reparte un todo en partes iguales.</li>
    <li>Para compararlas, usa un denominador común.</li>
  </ul>
</div>
```

### Qué bloques lleva cada cosa

- **Página de presentación**: contenedor, `lead`, «Qué vas a aprender», explicación breve,
  tarjetas con las partes de la unidad y «Para saber más».
- **Página de contenido**: contenedor, `lead`, «Qué vas a aprender», los apartados (`h3`),
  un ejemplo o un «Recuerda», «Palabras de esta página» si hay términos nuevos, «Resumen» y
  «Actividad». Añade tabla, código o tarjetas solo si el contenido lo pide.
- **Etiqueta**: se ve en la portada del curso. Corta: uno o dos bloques (un `alert` con un
  aviso, o un título y un párrafo). Sin contenedor, sin cabecera grande ni `h3` de página.
  El título va en `<strong>` dentro del `alert` (la portada del curso ya pone la sección como
  `h3`); sin `h3` ni `h4`:

  ```html
  <div class="alert alert-info">
    <strong>Bienvenida al tema 3</strong>
    <p class="mb-0">Empezamos con un repaso de fracciones.</p>
  </div>
  ```
- **Tarea**: siempre en `.html` si tiene más de un párrafo, una lista o una tabla. Lleva
  contexto en un `lead`, «Qué tienes que hacer» con los ejercicios en `h4`, «Qué entregas»
  en un `card` con `fa-download` (con varias formas de entregar), «Cómo se califica» con una
  tabla, «Antes de entregar, comprueba», un ejemplo resuelto y «Normas» en un `alert-warning`
  solo si las hay. Sin fechas en el texto: las pone Moodle.

## 6. Plantillas para copiar y rellenar

Copia la plantilla entera, rellena los huecos `[RELLENA: …]` y borra solo los bloques
marcados como opcionales. No cambies las clases ni añadas bloques nuevos.

Límites que se pueden contar:

- Una página de contenido tiene como mucho **600 palabras y 6 apartados `h3`**. Si pasa,
  pártela en dos páginas y propónselo al docente antes de publicar.
- Como mucho **dos columnas** (`col-md-6`).
- Toda página de contenido termina con «Resumen» y un bloque «Actividad» que lleva a lo
  siguiente.
- Sin fechas en el texto: las pone Moodle.

Todas llevan encima el bloque YAML de siempre, con `tipo`, `nombre` y `seccion`:

```yaml
---
tipo: pagina
nombre: "[RELLENA: nombre de la actividad]"
seccion: "[RELLENA: nombre de la sección]"
---
```

### Página de presentación

```html
<div style="max-width:52rem">
  <p class="lead">[RELLENA: una frase que diga qué es esta unidad y para qué sirve.]</p>

  <div class="alert alert-info">
    <h4><i class="fa-solid fa-fw fa-bullseye" aria-hidden="true"></i> Qué vas a aprender</h4>
    <ul class="mb-0">
      <li>[RELLENA: objetivo 1.]</li>
      <li>[RELLENA: objetivo 2.]</li>
    </ul>
  </div>

  <h3>[RELLENA: título del primer apartado]</h3>
  <p>[RELLENA: explicación breve, sin repetir la lista de objetivos.]</p>

  <div class="row">
    <div class="col-md-6 mb-3">
      <div class="card">
        <div class="card-body">
          <h4 class="card-title">[RELLENA: parte de la unidad]</h4>
          <p class="card-text">[RELLENA: qué se trabaja en esta parte.]</p>
        </div>
      </div>
    </div>
    <div class="col-md-6 mb-3">
      <div class="card">
        <div class="card-body">
          <h4 class="card-title">[RELLENA: otra parte de la unidad]</h4>
          <p class="card-text">[RELLENA: qué se trabaja en esta parte.]</p>
        </div>
      </div>
    </div>
  </div>

  <h4><i class="fa-solid fa-fw fa-book-open" aria-hidden="true"></i> Para saber más</h4>
  <ul>
    <li><a href="[RELLENA: dirección]">[RELLENA: qué encontrará el alumnado]</a></li>
  </ul>
</div>
```

### Página de contenido

```html
<div style="max-width:52rem">
  <p class="lead">[RELLENA: una frase de contexto: qué se aprende y para qué sirve.]</p>

  <div class="alert alert-info">
    <h4><i class="fa-solid fa-fw fa-bullseye" aria-hidden="true"></i> Qué vas a aprender</h4>
    <ul class="mb-0">
      <li>[RELLENA: objetivo 1.]</li>
      <li>[RELLENA: objetivo 2.]</li>
    </ul>
  </div>

  <h3>[RELLENA: apartado 1]</h3>
  <p>[RELLENA: explicación.]</p>

  <h3>[RELLENA: apartado 2]</h3>
  <p>[RELLENA: explicación.]</p>

  <div class="card bg-light mb-3">
    <div class="card-body">
      <h4 class="card-title">Ejemplo</h4>
      <p class="card-text">[RELLENA: enunciado del ejemplo.]</p>
      <details>
        <summary>Solución</summary>
        <p class="mt-2 mb-0">[RELLENA: solución paso a paso.]</p>
      </details>
    </div>
  </div>

  <div class="card bg-light mb-3">
    <div class="card-body">
      <h4 class="card-title"><i class="fa-solid fa-fw fa-book" aria-hidden="true"></i> Palabras de esta página</h4>
      <dl class="mb-0">
        <dt>[RELLENA: término nuevo]</dt><dd>[RELLENA: definición corta.]</dd>
        <dt>[RELLENA: término nuevo]</dt><dd>[RELLENA: definición corta.]</dd>
      </dl>
    </div>
  </div>

  <div class="alert alert-success">
    <h4><i class="fa-solid fa-fw fa-lightbulb" aria-hidden="true"></i> Resumen</h4>
    <ul class="mb-0">
      <li>[RELLENA: idea que hay que recordar.]</li>
      <li>[RELLENA: otra idea que hay que recordar.]</li>
    </ul>
  </div>

  <div class="card border-primary mb-3">
    <div class="card-body">
      <h4 class="card-title"><i class="fa-solid fa-fw fa-pen" aria-hidden="true"></i> Actividad</h4>
      <p class="card-text">[RELLENA: qué tiene que hacer el alumnado ahora y con qué actividad sigue, por su nombre.]</p>
    </div>
  </div>
</div>
```

«Palabras de esta página» es opcional: bórralo entero si la página no trae términos nuevos.
Si el contenido pide código, añade un bloque «Código» (sección 5). Si pide una imagen,
déjala con `alt` y `img-fluid`. Si es un esquema, dibújalo con `tiza esquema`
(`guias/esquemas.md`); si es una foto o material ajeno y no la tienes, deja el aviso «Falta:»
de `guias/dua.md` y avisa al docente.

### Tarea

```yaml
---
tipo: tarea
nombre: "[RELLENA: nombre de la tarea]"
seccion: "[RELLENA: nombre de la sección]"
apertura: 2026-11-03   # [RELLENA: fecha de apertura]
entrega: 2026-11-10    # [RELLENA: fecha de entrega]
limite: 2026-11-13     # [RELLENA: fecha límite; opcional]
---
```

```html
<div style="max-width:52rem">
  <p class="lead">[RELLENA: contexto en una frase: qué van a practicar y para qué.]</p>

  <h3>Qué tienes que hacer</h3>
  <h4>Ejercicio 1. [RELLENA: título corto]</h4>
  <p>[RELLENA: enunciado del ejercicio.]</p>
  <h4>Ejercicio 2. [RELLENA: título corto]</h4>
  <ul>
    <li>[RELLENA: apartado del ejercicio.]</li>
    <li>[RELLENA: apartado del ejercicio.]</li>
  </ul>

  <div class="card border-primary mb-3">
    <div class="card-body">
      <h4 class="card-title"><i class="fa-solid fa-fw fa-download" aria-hidden="true"></i> Qué entregas</h4>
      <p>Elige la forma que prefieras. Se califica igual:</p>
      <ul class="mb-0">
        <li>[RELLENA: una forma de entregar, por ejemplo un texto.]</li>
        <li>[RELLENA: otra forma, por ejemplo una foto o un audio.]</li>
      </ul>
    </div>
  </div>

  <h3>Cómo se califica</h3>
  <div class="table-responsive">
    <table class="table table-striped">
      <thead>
        <tr><th scope="col">Criterio</th><th scope="col">Puntos</th></tr>
      </thead>
      <tbody>
        <tr><td>[RELLENA: criterio: qué se demuestra, no con qué medio]</td><td>[RELLENA: puntos]</td></tr>
        <tr><td>[RELLENA: criterio]</td><td>[RELLENA: puntos]</td></tr>
      </tbody>
    </table>
  </div>

  <h3>Antes de entregar, comprueba</h3>
  <ul>
    <li>[RELLENA: algo que el alumnado puede comprobar por sí mismo.]</li>
    <li>[RELLENA: otra comprobación.]</li>
  </ul>

  <div class="card bg-light mb-3">
    <div class="card-body">
      <h4 class="card-title">Ejemplo resuelto</h4>
      <p class="card-text">[RELLENA: un caso parecido, pero distinto del que se pide.]</p>
      <details>
        <summary>Cómo se resuelve</summary>
        <p class="mt-2 mb-0">[RELLENA: el ejemplo resuelto.]</p>
      </details>
    </div>
  </div>

  <div class="alert alert-warning">
    <h4><i class="fa-solid fa-fw fa-triangle-exclamation" aria-hidden="true"></i> Normas</h4>
    <ul class="mb-0">
      <li>[RELLENA: plazo, penalización o copia.]</li>
    </ul>
  </div>
</div>
```

El bloque «Normas» y los ejercicios que no necesites son opcionales: bórralos enteros. No
borres el contenedor, la tabla de calificación, «Qué entregas», «Antes de entregar,
comprueba» ni el ejemplo resuelto. tiza no fija los tipos de entrega de la tarea: pregunta
al docente si tiene activadas las formas que ofreces (`guias/dua.md`).

`ejemplos/tarea-con-estilo.html` de esta skill muestra la tarea entera rellena.
`ejemplos/pagina-con-estilo.html` de esta skill muestra una página de contenido con estos
bloques.

## 7. Repaso antes de `tiza comprobar`

Revisa tu `.html`:

- ¿Hay algún `h2`?
- ¿Alguna `<table>` sin `class="table table-striped"` o sin `table-responsive`?
- ¿Algún `<pre>` sin el bloque «Código» (`bg-light border rounded p-3` y
  `style="line-height:1.5;font-size:0.9rem"`)?
- ¿Falta el contenedor `<div style="max-width:52rem">`?
- ¿Pasa de 600 palabras?
- ¿Solo clases de este catálogo y ninguna de Bootstrap 5 (`fw-*`, `fst-*`, `gap-*`…)?
- ¿Títulos desde `h3`, sin saltos de nivel y sin repetir el nombre de la actividad?
- ¿`alt` en todas las imágenes?
- ¿Iconos con `aria-hidden="true"` y con texto al lado?
- ¿Colores solo por clase y `style` solo para medidas?
- ¿Sin anchos fijos en píxeles?
- ¿Solo bloques del catálogo?

Si la respuesta es sí a cualquiera de las cinco primeras, no lo retoques: rehazlo con la
plantilla. Después ejecuta `tiza comprobar <fichero>.html`. Si da `HTML_PELIGROSO`, corrige
lo que diga y repite: tiza no limpia nada en silencio.

## 8. Si el aula limpia los estilos

Si el docente dice que la página se ve sin columnas ni fondos, su aula limpia el CSS en
línea. Las clases siguen funcionando y la página se lee igual: no lo «arregles» con más CSS.
