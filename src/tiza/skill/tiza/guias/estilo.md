# Guía: estilo de las páginas y las etiquetas

Se usa antes de escribir una página o una etiqueta. Léela entera y escribe en `.html`.
El resultado debe verse cuidado, igual en todas las páginas del curso y bien en el tema
del aula, sin imitar ninguna marca.

## 1. Cuándo se usa

- Páginas y etiquetas: `.html` por defecto.
- Descripción de una tarea: `.html` solo si es larga. Si es corta, `.md`.
- Cuestionarios y H5P: siguen en `.md`.
- Usa `.md` solo si el docente lo pide («prefiero editarlo yo en Markdown») o el texto es
  muy breve.

Un `.html` lleva el mismo bloque YAML (`---`) arriba que un `.md`. Después de ese bloque no
se interpreta Markdown: ni `**negrita**`, ni `#`, ni `-` de lista. Las fórmulas LaTeX se
escriben igual, con `\( … \)` y `\[ … \]`.

## 2. Principios

- **El color lo pone el tema del aula.** Usa clases semánticas: `alert-info`, `alert-warning`,
  `alert-success`, `card` con `border-primary`, `text-primary`, `bg-light`,
  `badge badge-primary`. Así la página sigue el tema de cada aula.
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

## 3. Accesibilidad

- Títulos desde `h3`: el aula ya pone el `h2` con el nombre de la actividad. No saltes
  niveles (`h3`, luego `h4`; nunca `h3` y luego `h5`). Una página empieza por la cabecera
  (`h3`); los títulos de los bloques del catálogo (`alert`, `card`) son `h4`.
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

Título (`h3`), después un `badge` con la sesión, si ayuda, y el subtítulo.

```html
<h3>Las fracciones</h3>
<p><span class="badge badge-primary">Sesión 1</span></p>
<p class="lead">Qué son, cómo se comparan y para qué sirven.</p>
```

### Qué vas a aprender

```html
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

El enunciado se ve; la solución va plegada.

```html
<div class="card bg-light mb-3">
  <div class="card-body">
    <h4 class="card-title">Ejemplo</h4>
    <p class="card-text">¿Qué fracción es mayor, 2/3 o 3/5?</p>
    <details>
      <summary>Ver la solución</summary>
      <p class="mt-2 mb-0">Con denominador 15: 10/15 y 9/15. Es mayor <strong>2/3</strong>.</p>
    </details>
  </div>
</div>
```

### Actividad o tarea

Un botón-enlace. `btn` solo vale en `<a>`.

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

`mb-3` en cada columna, para que en el móvil no se peguen.

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

- **Página de presentación**: cabecera, «Qué vas a aprender», explicación breve, tarjetas
  con las partes de la unidad y «Para saber más».
- **Página de contenido**: cabecera corta, explicación, ejemplo resuelto, «Recuerda» o
  «Importante», actividad y cierre. Añade tabla o tarjetas solo si el contenido lo pide.
- **Etiqueta**: se ve en la portada del curso. Corta: uno o dos bloques (un `alert` con un
  aviso, o un título y un párrafo). Sin cabecera grande ni `h3` de página. El título va en
  `<strong>` dentro del `alert` (la portada del curso ya pone la sección como `h3`); sin
  `h3` ni `h4`:

  ```html
  <div class="alert alert-info">
    <strong>Bienvenida al tema 3</strong>
    <p class="mb-0">Empezamos con un repaso de fracciones.</p>
  </div>
  ```

## 6. Plantilla completa

`ejemplos/pagina-con-estilo.html` del repositorio de tiza muestra una página entera con
estos bloques. Ábrela si dudas de cómo se combinan y copia su estructura.

## 7. Repaso antes de `tiza comprobar`

Revisa tu `.html`:

- ¿Solo clases de este catálogo y ninguna de Bootstrap 5 (`fw-*`, `fst-*`, `gap-*`…)?
- ¿Títulos desde `h3`, sin saltos de nivel?
- ¿`alt` en todas las imágenes?
- ¿Iconos con `aria-hidden="true"` y con texto al lado?
- ¿Colores solo por clase y `style` solo para medidas?
- ¿Sin anchos fijos en píxeles?
- ¿Solo bloques del catálogo?

Después ejecuta `tiza comprobar <fichero>.html`. Si da `HTML_PELIGROSO`, corrige lo que
diga y repite: tiza no limpia nada en silencio.

## 8. Si el aula limpia los estilos

Si el docente dice que la página se ve sin columnas ni fondos, su aula limpia el CSS en
línea. Las clases siguen funcionando y la página se lee igual: no lo «arregles» con más CSS.
