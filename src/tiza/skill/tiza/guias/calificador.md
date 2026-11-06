# Guía: el calificador del aula, alineado con la programación

Se usa cuando el docente pide montar el calificador de su aula (las notas por resultados de
aprendizaje, criterios o evaluaciones) o cambiar cómo se calcula la nota final. Habla en su
lenguaje: resultados de aprendizaje, evaluaciones, ponderaciones.

tiza monta lo que dice el esquema y nada más. **No inventes pesos, fórmulas ni topes.**

## 1. De dónde sale cada cosa

- Los elementos (competencias o resultados), sus criterios y códigos: la programación (`tiza leer`)
  y `tiza normativa` (`programacion`, `ficha <codigo>`). En ESO/Bachillerato son
  `competencia_especifica` y `criterio`; en FP, `resultado_aprendizaje` y `criterio_fp`. No
  inventes códigos; el `codigo` estable (`NUMERACION_NO_OFICIAL` en Primaria) solo vale de `id`.
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

Con criterios e instrumentos (ESO), esto es lo que cambia sobre el ejemplo de arriba:

```yaml
elementos:
  - id: CE1
    nombre: "Competencia específica 1"
    peso: 60
    codigo: "CE1"
    criterios:
      - {id: CE1_1, nombre: "Criterio 1.1", peso: 40, codigo: "1.1"}
      - {id: CE1_2, nombre: "Criterio 1.2", peso: 60, codigo: "1.2"}
```

```yaml
instrumentos:
  - {id: EXAMEN1, nombre: "Examen escrito UD2", seccion: 2, evalua: {CE1_1: 50, CE2_1: 100}}
```

- `organizacion`: `elementos` (FP: la vista por resultados o criterios) o `evaluaciones`
  (ESO y Bachillerato: evaluación, con sus elementos dentro).
- `elementos`: `id` (letra inicial y luego letras, cifras o `_`, 16 como mucho), `nombre`, `peso`
  (entre 0 y 100, todos suman 100) y `codigo` opcional.
- `criterios` (opcional en cada elemento): lista de `{id, nombre, peso?, codigo?}`. Pesos en todos
  o en ninguno, sumando 100. Sin pesos pesan igual y sale `CRITERIOS_SIN_PESO`. Elementos y criterios
  no repiten `id`; el código legible («1.1», «RA1.a») va en `codigo`.
- `instrumentos` (opcional): casillas manuales de lo que no está en el aula (examen en papel,
  observación), `{id, nombre, seccion, evalua}`. Ver §3.
- `etapa` (`primaria`, `eso`, `bachillerato` o `fp`), `niveles_rubrica` (2–10 niveles
  `{id, nombre, porcentaje}`, con el 0 y el 100; por defecto 100/75/50/25/0) y
  `actividades_pesan_igual` (todas las actividades de un criterio pesan igual). La rúbrica por
  criterios solo vale con `etapa: eso`.
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
- Si el elemento tiene criterios, `evalua` nombra sus criterios (`CE1_1`, no `CE1`); nombrar el
  elemento da `ELEMENTO_CON_CRITERIOS`. Los pesos de lo que evalúa cada criterio suman 100.
  Un criterio (o elemento) cuyas actividades pesan todas 0 no cuenta en la nota.
- **Casillas manuales** (`instrumentos`): tiza crea la casilla (sobre 10) en su primer criterio y
  copias en los demás. La nota la pone el docente a mano en el calificador; tiza nunca la toca ni
  cambia su máximo. Un instrumento tiene una sola nota, que va a todos sus criterios. Quitar uno
  con notas lo deja con peso 0 (`ELEMENTO_CON_NOTAS_QUITADO`).

## 4. Rúbrica por criterios (solo ESO)

Una tarea con `evalua` puede llevar `rubrica: por_criterios`: tiza crea la rúbrica nativa de Moodle,
con una fila por criterio, los pesos fijos de la PD y 10 puntos que Moodle reescala a la nota máxima.

- Solo ESO (`etapa: eso`); fuera de ESO, `RUBRICA_SOLO_ESO`. Los pesos no se inventan: salen de
  `calificacion.yaml`; si todos son 0, `RUBRICA_SIN_PESOS`. Los niveles son los de `niveles_rubrica`
  y cada uno se redondea al mayor resto para que su suma sea exacta.
- Una tarea nueva recibe la rúbrica; una que ya existe solo si el docente confirma que ninguna de
  las tareas listadas tiene notas. Con «N» o con el campo de reescalado, `RUBRICA_NO_ACTIVADA` y se
  publica el resto sin tocar el método. Los cuestionarios no tienen rúbrica; las escritas a mano son
  de `tiza-privado` (una ruta en el público da `RUBRICA_NO_VALIDA`).
- `actividades_pesan_igual` hace que todas las actividades de un criterio pesen lo mismo.
- Si una tarea con notas no recibe rúbrica, explícale que su nota única cuenta igual para todos
  sus criterios y que no se puede desglosar sin volver a corregir.

## 5. Cómo se ve la nota

- Todos los totales se ven en **porcentaje** (p. ej. «RA1: 40 %»). La nota sale en cadena
  instrumento → criterio → competencia → final, con la nota visible en cada nivel; en la vista por
  evaluaciones, la misma cadena dentro de cada evaluación.
- Solo si la final tiene tope, tiza monta «Notas (sobre 10)» con la nota de cada elemento y la
  final. Un elemento sin notas cuenta como 0 en el tope: a mitad de curso la final puede salir
  topada aunque el alumnado vaya bien; díselo al docente.
- Con tope, el total del curso lleva una fórmula y Moodle deja desmarcado «solo calificaciones no
  vacías»; es inocuo mientras haya fórmula. Si el docente la quita, que lo vuelva a marcar.

## 6. Si el aula ya tiene un calificador

- Lo que tiza monta va a «Calificador de tiza», con peso 0 en el total si había otro: el total del
  curso sigue siendo el del docente. Las actividades que pasan a tiza dejan de sumar en él.
- Antes de sacar una actividad de una categoría ajena, tiza **bloquea** su total si tiene notas
  (`CALIFICADOR_BLOQUEAR`); nunca desbloquea. `CAMBIADO_A_MANO` y `BLOQUEO_FALLIDO` se resuelven
  a mano en el aula.
- Un elemento que ya no está en el esquema pero tiene notas se queda con peso 0
  (`ELEMENTO_CON_NOTAS_QUITADO`); no se borra nada con notas.

## 7. Cerrar una evaluación

Cerrar una evaluación es poner `cerrada: true` y volver a montar: tiza la completa y la bloquea.
Dentro de una evaluación bloqueada no se crea, cambia, mueve ni borra nada; una actividad nueva
sale como `ACTIVIDAD_EN_EVALUACION_CERRADA` y `EVALUACION_CERRADA_EN_EL_AULA` avisa de que ya
estaba bloqueada. **tiza no puede reabrirla**: si falla a medias, repite el comando.

## 8. Cómo se monta

1. `tiza comprobar calificacion.yaml` (offline) hasta que salga 0; también comprueba `evalua`.
2. Las actividades tienen que estar publicadas; una que falta sale como `ACTIVIDAD_PENDIENTE`.
3. `tiza calificador … --en pruebas`: sin pregunta, gasta cupo.
4. `tiza calificador … --en real`: el docente confirma `[s/N]` curso por curso.

Lánzalo en segundo plano (hasta una hora): si te corta, la sesión acaba lo empezado y lo hecho no
se repite. En el informe, cada actividad sale `colocada`, `ya_estaba`, `pendiente` o `sin_colocar`,
y los pasos `CALIFICADOR`, `CALIFICADOR_BLOQUEAR` y `CALIFICADOR_COLOCAR` dicen qué se hizo.
Sin sesión, `SIN_SESION`: pide `tiza empezar`.

## 9. Lo que tiza no hace

- **No lee ni escribe notas** del alumnado. Solo sabe si un elemento tiene notas o no. No pidas
  ni muestres notas de nadie. No desbloquea nada.
- Sin competencias clave ni descriptores, y sin las «competencias» de Moodle.
- **No admitido**: cambiar `organizacion` o `final.de` de un calificador ya montado, ni usar escalas.
- Con más de 500 ficheros `.md` o `.html`, `CARPETA_DEMASIADO_GRANDE`: saca los que no sean del curso.
- Si dos actividades del mismo tipo y nombre apuntan al mismo sitio (`ACTIVIDAD_AMBIGUA`), no
  adivines cuál es: el docente borra o renombra una.
- `ESQUEMA_INVALIDO`, `PESOS_NO_SUMAN_100`, `ID_REPETIDO`, `SECCION_REPETIDA`,
  `TOPE_SIN_ELEMENTOS` y `ESQUEMA_FUERA_DE_CARPETA` dicen la ruta y la línea: corrígelos.
  `EVALUA_INVALIDO` es un `evalua` mal escrito; `ELEMENTO_DESCONOCIDO` nombra algo que no está
  en el esquema, y `SECCION_SIN_EVALUACION` pone una actividad fuera de toda evaluación.
- `ELEMENTO_CON_CRITERIOS`: un `evalua` nombra un elemento con criterios; usa sus criterios.
  `CRITERIOS_SIN_PESO` es un aviso: tiza los pesa igual, y se lo dices al docente.
- Si `.tiza/calificador.json` da `CALIFICADOR_INVALIDO`, no lo edites ni lo borres: pide al
  docente que lo revise; si se borra, tiza deja de saber qué cambió el docente a mano.
