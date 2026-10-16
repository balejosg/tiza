# Formato de los ficheros

Lo normal es que los escriba tu agente: la skill de `tiza` le enseña este
formato. Este documento sirve para revisarlos o escribirlos a mano. Hay ejemplos
completos en [`ejemplos/`](../ejemplos/).

Frontmatter YAML + Markdown (`.md`) o HTML (`.html`). En un `.md` la sangría no
crea bloques de código (el código va entre ```), así que el HTML sangrado se
publica como HTML. Los recursos locales se suben solos:

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
documento completo: solo se publica el `<body>`). Mira
[`ejemplos/maquetado.html`](../ejemplos/maquetado.html): estilos, clases de
Bootstrap y un iframe de cada grupo. Si algo no se admite, `tiza comprobar` da
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
- Si el `nombre` contiene `: ` (dos puntos y espacio), escríbelo entre comillas:
  `nombre: "Ejemplo: repaso"`.
- Las fechas aceptan `AAAA-MM-DD` o `AAAA-MM-DD HH:MM` (hora del aula, con
  `Europe/Madrid` por defecto; sin hora,
  `apertura` empieza a las 00:00 y `entrega` y `limite` acaban a las 23:59) y
  deben cumplir `apertura < entrega < limite`. `entrega` es la «Fecha de
  entrega» de Moodle: después se siguen admitiendo entregas, marcadas con
  retraso. `limite` es la «Fecha límite»: a partir de ella ya no se admiten
  entregas. Es opcional; sin ella, se admiten entregas con retraso sin fin.
- Un cuestionario admite además `apertura`, `cierre` y `mezclar_respuestas`, y
  de 1 a 100 preguntas de cinco tipos: `opcion_multiple` (de 2 a 10 opciones),
  `verdadero_falso`, `respuesta_corta`, `numerica` y `emparejamiento` (de 2 a 10
  parejas y `distractores` opcionales; la respuesta es texto plano y hacen falta al
  menos 3 respuestas distintas). Cada pregunta puede llevar `retro`
  (retroalimentación) y vale 1 punto (el emparejamiento lo reparte a partes iguales);
  tiza calcula las puntuaciones. No hay preguntas de ensayo: para respuestas abiertas,
  usa una tarea.
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

## Fórmulas

En un `.md` las fórmulas se escriben en LaTeX con `\( … \)` (en la línea) y `\[ … \]` o
`$$ … $$` (en bloque): tiza las publica tal cual (sin que `*`, `_` o `\\` se lean como
Markdown) y el aula las dibuja con su motor de fórmulas. Si el aula no lo carga, el informe
trae el paso `FORMULAS_NO_DIBUJADAS` (y la autoprueba lo dice). El `$x$`
simple no vale (`tiza comprobar` avisa con `FORMULA_DOLAR_SIMPLE`). Valen en páginas,
etiquetas, tareas y cuestionarios, no en las actividades H5P (`FORMULA_EN_H5P`). La vista
previa enseña la fuente LaTeX; el dibujo se revisa en el curso de pruebas. Mira
[`ejemplos/formulas.md`](../ejemplos/formulas.md).
