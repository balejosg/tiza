# Guía: explicar para que se entienda a la primera

Se aplica **siempre**, junto a `guias/dua.md`, al escribir una página, una tarea, un
cuestionario, un H5P o una unidad. `guias/dua.md` dice cómo llegar a toda la clase y
`guias/estilo.md` cómo se maqueta. Esta guía dice cómo se explica, y cada regla se puede
comprobar: está hecha o no está. Manda el docente: si pide otra cosa, avísale una vez y hazlo
como lo pide.

## 1. Antes de proponer nada: el aula

Lo que no sabes del aula cambia el material. No lo supongas. Mira antes `preferencias.txt` y
la carpeta, y pregunta **en un solo mensaje** lo que falte y condicione lo que vas a escribir:

- **Con qué trabaja el alumnado**: dispositivos y sistema operativo, programas, material,
  libro de texto, espacios (aula, laboratorio, patio).
- **Qué saben ya y qué no**, y qué les suele costar.
- **Cuánto dura de verdad la sesión** y qué dinámicas de aula acepta el docente.

Vale también para una pieza suelta si te falta ese contexto. Si ya está en `preferencias.txt`,
no lo vuelvas a preguntar. Lo estable (equipos, programas, duración de la sesión, dinámicas)
ofrécele guardarlo en `preferencias.txt` y escríbelo solo si dice que sí; nunca datos del
alumnado.

## 2. Reglas al explicar

1. **Primero el porqué.** Cada concepto va en este orden: qué problema resuelve o para qué
   sirve, después qué es y después cómo funciona.
2. **Un concepto nuevo por apartado** (`h3`). Si una página introduce más de 3, pártela.
3. **Nada antes de explicarlo.** Ningún término, símbolo, fórmula o procedimiento se usa antes
   de explicarlo en esa página o en una anterior, citada por su `nombre` exacto entre «».
4. **Cada actividad dice tres cosas**: qué hace el alumno, qué debería obtener u observar
   («Deberías obtener…», «Comprueba que…») y qué aprende con ello.
5. **Ejemplo resuelto paso a paso** de cada procedimiento que el alumnado tenga que ejecutar
   (un cálculo, un experimento, usar una herramienta, un comentario de texto…). Cada paso dice
   qué se hace y qué cambia. Una lista de pasos sueltos no basta.
6. **Prerrequisitos enseñados.** Si una tarea exige una destreza, una pieza anterior la enseña
   con un ejemplo resuelto distinto del que se pide. Nada de pistas que solo entiende quien ya
   sabe hacerlo.
7. **Andamiaje gradual**: primero un ejemplo resuelto, después un ejercicio guiado (con huecos o
   con los pasos dados) y por último uno autónomo.
8. **Enlaza con lo ya visto**, nombrando la pieza anterior: «En «1. Qué es la densidad» viste…».
9. **Lenguaje llano y del nivel**: frases cortas, ejemplos de la vida del alumnado y **una sola
   comparación cotidiana mantenida** a lo largo de la página, mejor que varias sueltas.
10. **Si se entiende mejor viéndolo, dibújalo.** Un proceso, una estructura o un cambio de estado
    van con un esquema (`guias/esquemas.md`). Para una secuencia, repite la misma maqueta (un
    esquema o una tabla) en cada paso y resalta lo que cambia (`<mark>` o `<strong>`).

`ejemplos/explicar/` de esta skill lo muestra en tres materias: una página de concepto con el
porqué, una comparación mantenida y un ejemplo paso a paso (`concepto-densidad.html`), una de
procedimiento con la misma tabla repetida y lo que cambia resaltado (`procedimiento-traza.html`)
y una tarea que va de ejemplo resuelto a guiado y a autónomo (`tarea-andamiaje.html`).

El límite de palabras de `guias/estilo.md` sirve para decidir **cuándo partir** una página,
nunca para quitar explicación. Planifica las páginas por concepto, no por sesión: una sesión
puede tener varias páginas cortas.

## 3. Dinámicas de aula

La propuesta por defecto es individual o por parejas. Lo que exige manejar a todo el grupo a la
vez (juegos de rol, desplazamientos, material compartido escaso, debates de toda la clase) va
como alternativa marcada «exige gestión de aula», salvo que el docente diga que lo quiere.

## 4. Verifica antes de `tiza comprobar`

`tiza comprobar` mira el formato, no si lo que dices es verdad. Antes de pasarlo:

1. **Rehaz cada ejemplo resuelto, cada solución y cada respuesta de cuestionario** por otra
   vía: recalcula, ejecuta el código si puedes o razona de nuevo desde el principio, sin mirar
   lo que escribiste.
2. **Prueba cada criterio de calificación y cada instrucción de tarea** con casos límite y con
   respuestas inesperadas (una entrega en blanco, una correcta por otro camino, una que acierta
   a medias): ¿sigue siendo justo y se puede aplicar?
3. **No afirmes de memoria lo que se puede comprobar**: cómo se ve o se comporta un programa o
   una web, fechas, cifras, citas. Compruébalo en una fuente o escríbelo de forma genérica y
   pide al docente que lo confirme. La normativa, solo con `tiza normativa`.
4. **Herramienta externa en clase**: avisa al docente de si pide cuenta, si tiene límites de uso
   o publicidad, y pregunta si su centro la permite.
5. **Las instrucciones de uso** de dispositivos y programas son las de lo que tiene el alumnado
   (sección 1): ni otro sistema ni otra versión.

## 5. Autorrevisión antes de enseñarle nada al docente

Relee cada pieza como un alumno de ese nivel que no conoce el tema y repasa esta lista:

- ¿Cada concepto empieza por su para qué? ¿Más de 3 conceptos nuevos? Pártela.
- ¿Algún término, símbolo o paso usado antes de explicarlo?
- ¿Cada actividad dice qué hacer, qué debería obtener y para qué?
- ¿Cada procedimiento tiene su ejemplo resuelto paso a paso, y la tarea va de ejemplo a guiado
  y a autónomo?
- ¿Lo que pide la tarea lo enseña alguna página, con otro ejemplo?
- ¿Una sola comparación, mantenida? ¿Esquema donde hay un proceso o un cambio?
- ¿Ejemplos, soluciones y criterios rehechos (sección 4)? ¿Datos de herramientas comprobados o
  pendientes de que los confirme el docente?
- ¿Las referencias «…» a otras piezas coinciden con su `nombre` (también tras renombrar)?
  `tiza comprobar` avisa de las que se parecen sin coincidir (`REFERENCIA_ROTA`).
- ¿La suma de tiempos cabe en las sesiones? ¿La dinámica por defecto es individual o por
  parejas?

Después dile al docente en el chat, en pocas líneas, qué encontraste y qué corregiste. No le
enseñes una pieza con un fallo de esta lista sin decírselo.
