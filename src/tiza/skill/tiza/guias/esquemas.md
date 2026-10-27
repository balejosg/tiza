# Guía: esquemas que dibuja el agente

Se carga cuando una página necesita un esquema y el docente te deja dibujarlo. El esquema es
material tuyo: no lleva bloque de autoría de `guias/licencias.md`, salvo que lo bases en una
obra ajena (entonces cita la fuente y respeta su licencia).

## 1. Cuándo sí y cuándo no

- **Sí**: un ciclo (el agua, el carbono), un algoritmo o un diagrama de flujo, las partes de un
  circuito o de una máquina, una línea de tiempo, una clasificación, una relación entre ideas.
  Son formas, trazos y texto; no hace falta una foto.
- **No**: una foto, un mapa real, una obra de arte, un plano que debe ser fiel o cualquier
  material que el docente ya tenga. Eso lo trae él y se cita según `guias/licencias.md`.
- **Fórmulas**: siguen en LaTeX, nunca como imagen. Donde no caben (H5P o respuestas de un
  emparejamiento), escríbelas en texto: «1/2».
- Dibuja lo que el docente pidió, ni más ni menos. Si el esquema necesita otra idea, propónla
  en el chat antes de ampliarlo.

## 2. Cómo se hace

1. Escribe el SVG en la carpeta, por ejemplo `img/ciclo-agua.svg`.
2. Conviértelo:

   ```bash
   tiza esquema img/ciclo-agua.svg
   ```

   Offline. Por defecto crea `img/ciclo-agua.png` a 1200 px de ancho; `--ancho` admite de 400
   a 2000. El SVG se queda en la carpeta y nunca se publica, tampoco como recurso enlazado:
   cita siempre el PNG.
3. Cita el PNG en la página, como cualquier imagen:

   ```html
   <img class="img-fluid" src="img/ciclo-agua.png"
        alt="Del agua líquida al vapor por el calor y vuelta a la nube por la lluvia">
   ```

4. Si corriges el esquema, edita el SVG y repite el comando: sustituye su PNG porque lleva la
   marca de `tiza esquema` con ese mismo SVG. Si el PNG lo hizo otra persona o no lo hizo tiza,
   da `ESQUEMA_EXISTE`: elige otro nombre con `--salida`, no lo pises.

`tiza comprobar` y `tiza publicar` tratan el PNG como un recurso más. Comprueba que se ve bien
en la vista previa antes de publicar.

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

## 4. Estilo

- **Pocos colores**, los del tema: azul (`#0d6efd`), verde (`#198754`), ámbar (`#ffc107`), rojo
  (`#dc3545`), gris (`#6c757d`) y un relleno claro del mismo tono. Como mucho dos colores con
  significado y uno neutro; el color no puede ser el único que distinga algo.
- **Texto legible**: 18 px o más con 1200 px de ancho; en un esquema que se ve en el móvil,
  mejor 22-28 px. No metas texto dentro de formas pequeñas: si no cabe, ponlo al lado.
- **Trazos de 3-5 px** con 1200 px de ancho; flechas claras (`marker-end`) y etiquetas cortas.
- Deja márgenes y aire: el esquema no debe tocar los bordes. Alinea las formas a una rejilla
  mental; no amontones.
- Sin sombras, degradados decorativos ni filtros: se leen peor y algunos no están permitidos.
- `title` y `desc` ayudan a otros lectores; el `alt` de la página es obligatorio y describe la
  **relación** («qué va antes y qué después»), no solo el título.

## 5. Un ejemplo mínimo

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="500" viewBox="0 0 1200 500">
  <defs>
    <marker id="flecha" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#0d6efd"/>
    </marker>
  </defs>
  <rect x="70" y="180" width="240" height="120" rx="12" fill="#cfe2ff" stroke="#0d6efd" stroke-width="4"/>
  <text x="190" y="248" text-anchor="middle" font-size="28">Agua líquida</text>
  <line x1="320" y1="240" x2="520" y2="240" stroke="#0d6efd" stroke-width="4" marker-end="url(#flecha)"/>
  <text x="420" y="215" text-anchor="middle" font-size="22" fill="#495057">calor</text>
  <rect x="530" y="180" width="240" height="120" rx="12" fill="#cfe2ff" stroke="#0d6efd" stroke-width="4"/>
  <text x="650" y="248" text-anchor="middle" font-size="28">Vapor</text>
  <line x1="780" y1="240" x2="980" y2="240" stroke="#0d6efd" stroke-width="4" marker-end="url(#flecha)"/>
  <text x="880" y="215" text-anchor="middle" font-size="22" fill="#495057">frío</text>
  <rect x="990" y="180" width="140" height="120" rx="12" fill="#cfe2ff" stroke="#0d6efd" stroke-width="4"/>
  <text x="1060" y="248" text-anchor="middle" font-size="28">Nube</text>
</svg>
```
