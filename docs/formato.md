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
- Las fechas aceptan `AAAA-MM-DD` o `AAAA-MM-DD HH:MM` (hora del aula, con
  `Europe/Madrid` por defecto; una hora que el reloj se salta en el cambio de
  primavera, como las 02:30 del último domingo de marzo, no existe y da
  `FECHA_INEXISTENTE`; sin hora,
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

## Calificador: `evalua`

Cualquier actividad puede declarar con qué resultados de aprendizaje se evalúa y
con qué peso, para colocarla en el calificador del curso:

```yaml
evalua: {RA1: 40, RA3: 25}   # id: peso de 0 a 100, con hasta 2 decimales
```

- Los ids empiezan por letra, usan letras y cifras y tienen hasta 16 caracteres.
  Un peso de 0 deja la actividad sin peso, pero se queda en el calificador.
- Un id repetido o un mapa vacío dan error (`EVALUA_INVALIDO`). Que el id exista
  en el esquema del curso se comprueba al colocar la actividad, no al leer el `.md`.
- Cambiar `evalua` no cambia el hash de la actividad: no hace falta volver a
  verificarla.

## Calificador: `calificacion.yaml`

Lo escribe el agente en la carpeta de la asignatura, a partir de la programación, y lo monta
`tiza calificador`. Es un esquema cerrado, sin lenguaje de fórmulas: qué elementos (resultados
o criterios) hay, cuánto pesa cada uno, qué evaluaciones hay y un tope opcional de la final.

```yaml
organizacion: elementos            # o evaluaciones (ESO y Bachillerato)
elementos:                         # con organizacion elementos o final de elementos
  - {id: RA1, nombre: "Redes locales", peso: 40, codigo: RA1}   # peso 0-100; suman 100
evaluaciones:
  - {nombre: "1.ª evaluación", secciones: [1, 2, 3], cerrada: false}   # secciones de «seccion:»
final:
  de: elementos                    # o evaluaciones (entonces cada evaluación lleva peso)
  tope: {si_alguno_menor_que: 5, maximo: 4}   # opcional, solo con de: elementos
```

- `id`: empieza por letra, letras y cifras, 16 como mucho. Los ids repetidos dan `ID_REPETIDO`.
- Una sección solo puede estar en una evaluación (`SECCION_REPETIDA`). Una actividad con `evalua`
  en una sección que no es de ninguna evaluación da `SECCION_SIN_EVALUACION`.
- `cerrada: true` congela la evaluación en el aula: no se crea, cambia, mueve ni borra nada
  dentro. tiza no la reabre.
- Con tope, si alguna nota de elemento baja del umbral, la final no pasa del máximo. Un
  elemento que todavía no tiene ninguna nota cuenta como 0 en ese cálculo, así que a mitad de
  curso la final puede salir topada. Un error del esquema da `ESQUEMA_INVALIDO`, con la ruta y la línea.
- Lo que el esquema no expresa (redondeos, actitud, recuperaciones) se queda fuera: la
  guía del agente (`guias/calificador.md`) dice cómo tratarlo.

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
