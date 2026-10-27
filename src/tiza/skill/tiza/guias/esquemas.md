# Guía: esquemas que dibuja el agente

Se carga cuando una pieza necesita un esquema que puedes dibujar tú. No hace falta permiso
aparte: en la propuesta, marca cada imagen como «la dibujo yo (esquema)» o «la traes tú» y
dibuja las tuyas salvo que el docente diga otra cosa. El esquema es material tuyo: no lleva
bloque de autoría de `guias/licencias.md`, salvo que lo bases en una obra ajena (entonces cita
la fuente y respeta su licencia).

## 1. Cuándo sí y cuándo no

- **Sí**: un ciclo (el agua, el carbono), un algoritmo o un diagrama de flujo, las partes de un
  circuito o de una máquina, una línea de tiempo, una clasificación, una relación entre ideas,
  una fracción dibujada. Son formas, trazos y texto; no hace falta una foto.
- **No**: una foto, un mapa real, una obra de arte, un plano que debe ser fiel o cualquier
  material que el docente ya tenga. Eso lo trae él y se cita según `guias/licencias.md`.
- **Fórmulas**: siguen en LaTeX, nunca como imagen. Donde no caben (H5P o respuestas de un
  emparejamiento), escríbelas en texto: «1/2».
- Dibuja lo que el docente pidió, ni más ni menos. **Como mucho 8 cajas o etiquetas** por
  esquema: si salen más, pártelo en dos o propón en el chat cómo dividirlo.

## 2. Cómo se hace

1. Escribe el SVG en la carpeta, por ejemplo `img/ciclo-agua.svg`.
2. Conviértelo:

   ```bash
   tiza esquema img/ciclo-agua.svg
   ```

   Offline. Por defecto crea `img/ciclo-agua.png` a 1200 px de ancho; `--ancho` admite de 400
   a 2000. El SVG se queda en la carpeta y nunca se publica, tampoco como recurso enlazado:
   cita siempre el PNG.
3. **Abre el PNG y míralo** (si puedes ver imágenes, léelo como imagen). Busca texto que se
   sale de su caja o se corta, etiquetas que se pisan, flechas que no llegan o atraviesan una
   caja y mucho blanco sobrante. Si algo falla, corrige el SVG y vuelve al paso 2. Si no puedes
   ver imágenes, dile al docente que revise el esquema en la vista previa.
4. Cita el PNG en la página, como cualquier imagen, con un ancho máximo para que no ocupe toda
   la pantalla del ordenador:

   ```html
   <p><img class="img-fluid" src="img/ciclo-agua.png" style="max-width:36rem"
        alt="El agua líquida se convierte en vapor con el calor, y el vapor en nube con el frío"></p>
   ```

5. Si corriges el esquema, edita el SVG y repite el comando: sustituye su PNG porque lleva la
   marca de `tiza esquema` con ese mismo SVG. Si el PNG lo hizo otra persona o no lo hizo tiza,
   da `ESQUEMA_EXISTE`: elige otro nombre con `--salida`, no lo pises.

`tiza comprobar` y `tiza publicar` tratan el PNG como un recurso más.

## 3. Lo que admite el SVG

Solo formas, trazos, texto y sus definiciones: `svg g defs symbol use title desc rect circle
ellipse line polyline polygon path text tspan textPath marker linearGradient radialGradient stop
clipPath mask pattern style`.

- Sin `<image>` ni fotos incrustadas, tampoco `data:`.
- Sin `<script>`, `<foreignObject>`, `<filter>`, animaciones ni formularios.
- Las referencias (`href`, `xlink:href`, `url(…)`) solo valen dentro del esquema: `#id`.
  No valen direcciones externas, rutas locales, `file:` ni `data:`.
- Sin `@import` ni reglas `@` en el `<style>`.
- Como mucho 5000 elementos y 512 KB el SVG. La proporción tiene que estar entre 1:4 y 4:1
  (por ejemplo, 1200 × 4800 como máximo con el ancho por defecto). El PNG, como mucho 1 MB.
- El fondo siempre es blanco y la fuente es la que trae tiza: cualquier `font-family` cae en
  ella. Así el PNG se ve igual en todos los equipos.

`ESQUEMA_NO_ADMITIDO` dice la línea y qué se ha rechazado; también es el código si faltan las
medidas o la proporción no está entre 1:4 y 4:1. `ESQUEMA_DEMASIADO_GRANDE` es pasar de tamaño,
elementos, ancho o del 1 MB del PNG. `ESQUEMA_EXISTE` es que el PNG no es de tiza: usa
`--salida`.

## 4. Medidas y estilo

- **Dibuja en un lienzo de 800 de ancho** (`viewBox="0 0 800 …"`) y cítalo con
  `max-width:36rem`. En un móvil se ve a unos 340 px: menos de la mitad.
- **Texto de 32 a 40** en ese lienzo (lo de menos, 28). Más pequeño no se lee en el móvil.
- **¿Cabe el texto?** Cada carácter ocupa unos 0,6 × el tamaño de letra: «Agua líquida» (12
  caracteres) a 40 ocupa unos 290; la caja necesita eso más 40 de margen a cada lado. Si no
  cabe, acorta la etiqueta, pártela en dos líneas (`tspan`) o ponla fuera de la caja.
- **Mejor en vertical** (de arriba abajo) o en una cuadrícula de dos columnas: cuatro cajas en
  fila no caben a ese tamaño.
- **Pocos colores**, los del tema: azul (`#0d6efd`), verde (`#198754`), ámbar (`#ffc107`), rojo
  (`#dc3545`), gris (`#6c757d`) y un relleno claro del mismo tono. Como mucho dos colores con
  significado y uno neutro; el color no puede ser el único que distinga algo.
- **Trazos de 4** y flechas con `marker-end`. Etiquetas cortas.
- **Márgenes de unos 40** alrededor y nada más: ajusta el alto del `viewBox` a lo dibujado,
  sin franjas vacías arriba ni abajo.
- Sin sombras, degradados decorativos ni filtros: se leen peor y algunos no están permitidos.
- `title` y `desc` ayudan a otros lectores; el `alt` de la página es obligatorio y describe la
  **relación** («qué va antes y qué después»), no solo el título.
- **En un cuestionario** el `alt` sigue `guias/dua.md`: describe la figura sin dar la
  respuesta. Si lo que se pregunta es justo la relación del esquema, el `alt` dice qué hay
  (las cajas y sus nombres), no cómo se relacionan.

## 5. Un ejemplo mínimo

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="800" height="760" viewBox="0 0 800 760">
  <defs>
    <marker id="flecha" viewBox="0 0 10 10" markerWidth="6" markerHeight="6" refX="9" refY="5" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#0d6efd"/>
    </marker>
  </defs>
  <rect x="180" y="40" width="440" height="120" rx="16" fill="#cfe2ff" stroke="#0d6efd" stroke-width="4"/>
  <text x="400" y="112" text-anchor="middle" font-size="40">Agua líquida</text>
  <line x1="400" y1="164" x2="400" y2="312" stroke="#0d6efd" stroke-width="4" marker-end="url(#flecha)"/>
  <text x="430" y="250" font-size="32" fill="#495057">calor</text>
  <rect x="180" y="320" width="440" height="120" rx="16" fill="#cfe2ff" stroke="#0d6efd" stroke-width="4"/>
  <text x="400" y="392" text-anchor="middle" font-size="40">Vapor</text>
  <line x1="400" y1="444" x2="400" y2="592" stroke="#0d6efd" stroke-width="4" marker-end="url(#flecha)"/>
  <text x="430" y="530" font-size="32" fill="#495057">frío</text>
  <rect x="180" y="600" width="440" height="120" rx="16" fill="#cfe2ff" stroke="#0d6efd" stroke-width="4"/>
  <text x="400" y="672" text-anchor="middle" font-size="40">Nube</text>
</svg>
```
