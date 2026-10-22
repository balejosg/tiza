# Guía: el calificador del aula, alineado con la programación

Se usa cuando el docente pide montar el calificador de su aula (las notas por resultados de
aprendizaje, criterios o evaluaciones) o cambiar cómo se calcula la nota final. Habla en su
lenguaje: resultados de aprendizaje, evaluaciones, ponderaciones.

tiza monta lo que dice el esquema y nada más. **No inventes pesos, fórmulas ni topes.**

## 1. De dónde sale cada cosa

- Los elementos (resultados de aprendizaje o criterios) y sus códigos: la programación del
  docente (`tiza leer`, y abre su `.txt`) y `tiza normativa` (`programacion`, `ficha <codigo>`).
- Los pesos y las reglas (la ponderación y el tope): la programación o la del departamento.
  Si no los trae, haz **una sola pregunta** al docente y espera.
- Si las fuentes se contradicen, manda el docente: díselo y no elijas tú.
- El trimestre de cada actividad: la temporalización de la programación dice qué unidades van
  en cada evaluación. En el esquema, `secciones` son las de `seccion:` de los ficheros.

## 2. El esquema: `calificacion.yaml`

Va en la carpeta de la asignatura. Este es el ejemplo que los tests de tiza validan:

```yaml
# Módulo de FP: tres resultados de aprendizaje, tres evaluaciones y un tope en la final.
organizacion: elementos
elementos:
  - {id: RA1, nombre: "Redes locales", peso: 40, codigo: RA1}
  - {id: RA2, nombre: "Sistemas operativos", peso: 30, codigo: RA2}
  - {id: RA3, nombre: "Seguridad informática", peso: 30, codigo: RA3}
evaluaciones:
  - {nombre: "1.ª evaluación", secciones: [1, 2, 3]}
  - {nombre: "2.ª evaluación", secciones: [4, 5, 6]}
  - {nombre: "3.ª evaluación", secciones: [7, 8]}
final:
  de: elementos
  tope: {si_alguno_menor_que: 5, maximo: 4}
```

- `organizacion`: `elementos` (FP: la vista por resultados o criterios) o `evaluaciones`
  (ESO y Bachillerato: evaluación, con sus elementos dentro).
- `elementos`: `id` (empieza por letra, solo letras y cifras, 16 como mucho), `nombre`, `peso`
  (entre 0 y 100, todos suman 100) y `codigo` opcional.
- `evaluaciones`: `nombre`, `secciones` (números o nombres de sección) y `cerrada` (true o false).
  Con la final por evaluaciones, cada una lleva `peso` (suman 100).
- `final`: `de` (`elementos` o `evaluaciones`) y `tope` (solo con `de: elementos`):
  `si_alguno_menor_que` (mayor que 0 y hasta 10) y `maximo` (de 0 a 10, sin llegar).

Lo que el esquema no expresa (redondeos, la actitud, las recuperaciones, otros pesos dentro
de una evaluación) **se lo dices al docente y no lo fuerzas**.

## 3. Las actividades: `evalua`

Cada tarea, cuestionario o contenido H5P declara en su cabecera con qué resultados se
evalúa y con qué peso: `evalua: {RA1: 40, RA3: 25}` (de 0 a 100). La actividad real queda en el
primer elemento de `evalua` (en el orden del YAML); en los demás aparece una copia que refleja
su nota. Una actividad sin `evalua` no entra en el calificador. Una página o una etiqueta
no tienen nota en Moodle: con `evalua` dan `EVALUA_NO_CALIFICABLE`, también en `tiza comprobar`.

## 4. Cómo se ve la nota

- Todos los totales de tiza se ven en **porcentaje** (p. ej. «RA1: 40 %»).
- Solo si la final tiene tope, tiza monta además «Notas (sobre 10)», con la nota de cada elemento
  y la final sobre 10 con el tope. Sin tope, no hay notas sobre 10.
- **Límite del tope**: un elemento que todavía no tiene ninguna nota cuenta como 0 en la fórmula
  del tope. A mitad de curso, la final puede salir topada aunque el alumnado vaya bien. Díselo al
  docente cada vez que monte o revise el calificador en ese punto del curso.
- Con tope, el total del curso lleva una fórmula y Moodle deja desmarcado su ajuste «solo
  calificaciones no vacías». Es inocuo mientras haya fórmula; si el docente la quita, que lo
  vuelva a marcar en el total del curso.

## 5. Si el aula ya tiene un calificador

- Lo que tiza monta va a «Calificador de tiza». Con un calificador anterior, ese grupo tiene
  peso 0 en el total del curso: el total del curso **sigue siendo el del docente** y tiza no lo toca.
  Díselo: las actividades que pasan a tiza dejan de sumar en su total.
- Antes de sacar una actividad de una categoría ajena, tiza **bloquea** el total de esa categoría
  si tiene notas (`CALIFICADOR_BLOQUEAR`). Nunca desbloquea: lo que haya que desbloquear lo hace el
  docente a mano en el aula.
- Lo que el docente cambió a mano en lo de tiza no se pisa: sale como `CAMBIADO_A_MANO` y decide
  él. Si `BLOQUEO_FALLIDO`, no se movió nada más en ese curso: vuelve a intentarlo, y si se repite,
  que el docente mire el calificador en el aula.
- Un elemento que ya no está en el esquema pero tiene notas se queda con peso 0
  (`ELEMENTO_CON_NOTAS_QUITADO`). No se borra nada con notas.

## 6. Cerrar una evaluación

Cerrar una evaluación es poner `cerrada: true` en su bloque del esquema y volver a montar. Dentro
de una evaluación cerrada nada se crea, cambia, mueve ni borra. `EVALUACION_CERRADA_EN_EL_AULA`
significa que el aula ya la tiene bloqueada y tiza no la toca. Una actividad nueva en una sección
de una evaluación cerrada sale como `ACTIVIDAD_EN_EVALUACION_CERRADA`: no se coloca, ni sus copias.
Si el esquema marca `cerrada: true` una evaluación que aún no existe en el aula (primer montaje),
tiza la crea entera y la bloquea al final. **tiza no puede reabrirla**: si el docente quiere
corregirla, lo hace a mano en el aula.

## 7. Cómo se monta

1. `tiza comprobar calificacion.yaml` (offline) hasta que salga 0. Con las actividades, la misma
   comprobación sirve para `evalua` (`EVALUA_INVALIDO`, `EVALUA_NO_CALIFICABLE`).
2. Las actividades tienen que estar publicadas en el aula. Una que aún no está sale como
   `ACTIVIDAD_PENDIENTE` (no es un error): vuelve a montar cuando esté publicada.
3. `tiza calificador calificacion.yaml --en pruebas`: sin pregunta, gasta uno del cupo de la
   sesión. Revisa el resultado en el curso de pruebas.
4. `tiza calificador calificacion.yaml --en real`: el docente confirma `[s/N]` curso por curso,
   con lo que va a pasar en lenguaje llano. Lanza el comando con el mayor tiempo de espera que
   permita tu herramienta, como en `tiza publicar`.

En el informe, cada actividad sale como `colocada`, `ya_estaba` o `pendiente`, y los pasos
`CALIFICADOR`, `CALIFICADOR_BLOQUEAR` y `CALIFICADOR_COLOCAR` dicen qué se hizo. Sin sesión, `SIN_SESION`:
pide al docente que ejecute `tiza empezar`.

## 8. Lo que tiza no hace

- **No lee ni escribe notas** del alumnado. Solo sabe si un elemento tiene notas o no. No pidas
  ni muestres notas de nadie.
- No desbloquea nada.
- Con más de 500 ficheros `.md` o `.html` en la carpeta, `CARPETA_DEMASIADO_GRANDE`: saca de la
  carpeta los que no sean de este curso.
- Si dos actividades del mismo tipo y nombre apuntan al mismo sitio (`ACTIVIDAD_AMBIGUA`), no
  adivines cuál es: el docente borra o renombra una en el aula.
- `ESQUEMA_INVALIDO`, `PESOS_NO_SUMAN_100`, `ID_REPETIDO`, `SECCION_REPETIDA`,
  `TOPE_SIN_ELEMENTOS` y `ESQUEMA_FUERA_DE_CARPETA` dicen la ruta y la línea: corrige eso y
  vuelve a comprobar. `EVALUA_INVALIDO` es un `evalua` mal escrito en un `.md`;
  `ELEMENTO_DESCONOCIDO` nombra un elemento que no está en el esquema, y `SECCION_SIN_EVALUACION`
  pone una actividad en una sección que no es de ninguna evaluación.
- Si `.tiza/calificador.json` da `CALIFICADOR_INVALIDO`, no lo edites ni lo borres: díselo al
  docente, porque borrarlo hace que tiza olvide lo que cambió a mano.
