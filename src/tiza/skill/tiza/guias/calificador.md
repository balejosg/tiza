# Guía: el calificador del aula, alineado con la programación

Se usa cuando el docente pide montar el calificador de su aula (las notas por resultados de
aprendizaje, criterios o evaluaciones) o cambiar cómo se calcula la nota final. Habla en su
lenguaje: resultados de aprendizaje, evaluaciones, ponderaciones.

tiza monta lo que dice el esquema y nada más. **No inventes pesos, fórmulas ni topes.**

## 1. De dónde sale cada cosa

- Los elementos (competencias o resultados), sus criterios y códigos: la programación
  (`tiza leer`) y `tiza normativa` (`programacion`, `ficha <codigo>`). En ESO/Bachillerato son
  `competencia_especifica` y `criterio`; en FP, `resultado_aprendizaje` y `criterio_fp`. No
  inventes códigos; el `codigo` estable (`NUMERACION_NO_OFICIAL` en Primaria) solo vale de `id`.
- Los pesos y las reglas (ponderación y tope): la programación o la del departamento; si no los
  trae, haz **una sola pregunta** al docente y espera. Si las fuentes se contradicen, manda el
  docente: díselo y no elijas tú.
- El trimestre de cada actividad: la temporalización dice qué unidades van en cada evaluación;
  en el esquema, `secciones` son las de `seccion:` de los ficheros.

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

- `organizacion`: `elementos` (FP: la vista por resultados o criterios) o `evaluaciones` (ESO y
  Bachillerato: evaluación, con sus elementos dentro).
- `elementos`: `id` (letra inicial y luego letras, cifras o `_`, 16 como mucho), `nombre`, `peso`
  (entre 0 y 100, todos suman 100) y `codigo` opcional.
- `criterios` (opcional): lista de `{id, nombre, peso?, codigo?}`; pesos en todos o en ninguno,
  sumando 100 (sin pesos pesan igual y sale `CRITERIOS_SIN_PESO`); ids únicos y `codigo` legible.
- `instrumentos` (opcional): casillas manuales de lo que no está en el aula,
  `{id, nombre, seccion, evalua}` (ver §3).
- `etapa` (`primaria`, `eso`, `bachillerato` o `fp`), `niveles_rubrica` (2–10 niveles
  `{id, nombre, porcentaje}`, con el 0 y el 100; por defecto 100/75/50/25/0) y
  `actividades_pesan_igual` (todas las actividades de un criterio pesan igual); la rúbrica por
  criterios solo vale con `etapa: eso`.
- `evaluaciones`: `nombre`, `secciones` (números o nombres) y `cerrada`; con la final por
  evaluaciones, cada una lleva `peso` (suman 100).
- `final`: `de` (`elementos` o `evaluaciones`) y `tope` (solo con `de: elementos`):
  `si_alguno_menor_que` (mayor que 0 y hasta 10) y `maximo` (de 0 a 10, sin llegar).

Lo que el esquema no expresa (redondeos, la actitud, las recuperaciones, otros pesos dentro de
una evaluación) **se lo dices al docente y no lo fuerzas**.

## 3. Las actividades: `evalua`

Cada tarea, cuestionario o contenido H5P declara en su cabecera con qué resultados se evalúa y
con qué peso: `evalua: {RA1: 40, RA3: 25}` (de 0 a 100). Sin `evidencia: resultados`, la
actividad real queda en el primer elemento de `evalua` (en el orden del YAML) y en los demás
aparece una copia que refleja su nota. Con evidencia, va un calculado del resultado por criterio
y la tarea real queda con peso 0 (§5). Una actividad sin `evalua` no entra en el calificador, y
una página o etiqueta con `evalua` da `EVALUA_NO_CALIFICABLE` (también en `tiza comprobar`).

- Si el elemento tiene criterios, `evalua` nombra sus criterios (`CE1_1`, no `CE1`); nombrar el
  elemento da `ELEMENTO_CON_CRITERIOS`. Los pesos de lo que evalúa cada criterio suman 100; un
  criterio (o elemento) cuyas actividades pesan todas 0 no cuenta en la nota.
- **Casillas manuales** (`instrumentos`): tiza crea la casilla (sobre 10) en su primer criterio y
  copias en los demás. La nota la pone el docente a mano; tiza nunca la toca ni cambia su
  máximo. Una nota va a todos sus criterios; quitarlo con notas lo deja con peso 0
  (`ELEMENTO_CON_NOTAS_QUITADO`).
- **`evidencia: resultados`** (solo ESO): la tarea marca los resultados de sus criterios.
  Necesita `evalua`, `calificacion.yaml` con `etapa: eso` y niveles equidistantes; tiza crea una
  escala de logro y un resultado por criterio, y el docente marca un nivel por criterio en
  Moodle (ver §5).

## 4. Rúbrica por criterios (solo ESO)

Una tarea con `evalua` puede llevar `rubrica: por_criterios`: tiza crea la rúbrica nativa de
Moodle, con una fila por criterio, los pesos fijos de la PD y 10 puntos que Moodle reescala a la
nota máxima.

- Solo ESO (`etapa: eso`); fuera de ESO, `RUBRICA_SOLO_ESO`. Los pesos salen de
  `calificacion.yaml` y no se inventan; si todos son 0, `RUBRICA_SIN_PESOS`. Los niveles son los
  de `niveles_rubrica`, redondeados al mayor resto para que su suma sea exacta.
- Una tarea nueva recibe la rúbrica; una que ya existe solo si el docente confirma que ninguna de
  las tareas listadas tiene notas. Con «N» o con el campo de reescalado, `RUBRICA_NO_ACTIVADA` y
  se publica el resto sin tocar el método. Los cuestionarios no tienen rúbrica; las escritas a
  mano son de `tiza-privado` (una ruta en el público da `RUBRICA_NO_VALIDA`).
- `actividades_pesan_igual` hace que todas las actividades de un criterio pesen lo mismo. Si una
  tarea con notas no recibe rúbrica, explícale que su nota única cuenta igual para todos sus
  criterios y que no se puede desglosar sin volver a corregir.

En `tiza`, elige una: no combines `evidencia: resultados` con `rubrica: por_criterios`. La
evidencia sustituye a la rúbrica en el flujo recomendado, así que el docente no marca dos veces.
Un fichero con las dos claves carga, pero el docente marcaría dos veces. La rúbrica por criterios
con la copia de niveles es el flujo de `tiza-privado` (§5).

## 5. Evidencia por criterio (resultados, solo ESO)

En una tarea de ESO con **más de un criterio** en `evalua`, propón `evidencia: resultados`: el
docente marca un nivel por criterio en Moodle, en vez de repartir la nota total. Con un solo
criterio no aporta: la nota de la tarea ya es su nivel.

- tiza crea la escala «Escala de logro (tiza)» con los niveles de `niveles_rubrica` (de menor a
  mayor y equidistantes; si no, `NIVELES_NO_EQUIDISTANTES`) y un resultado `TZ_<criterio>` por
  criterio. En el calificador pone un calculado por tarea y criterio que lleva el nivel a 0–10
  con el peso de `evalua`; **la nota total de la tarea deja de contar para los criterios**.
- Los descriptores de cada nivel van en el enunciado, para que el alumnado sepa qué se le pide.
- Una tarea con notas pide confirmación en `tiza publicar` (`EVIDENCIA_CAMBIADA_CON_NOTAS`):
  sus notas antiguas dejan de contar para los criterios; con «N», se publica sin resultados.
  `tiza calificador` también pregunta por las tareas pendientes con notas, aunque no emita ese
  paso. Quitar `evidencia` no borra el resultado: al volver a montar el calificador se queda con
  peso 0, y `tiza calificador` avisa con `RESULTADO_CON_NOTAS_QUITADO` solo si ya tenía niveles.
- Si el sitio no tiene resultados, `RESULTADOS_DESACTIVADOS` en `tiza publicar` (no se escribe
  nada de resultados y se publica el resto) o en `tiza calificador` (queda el paso
  `RESULTADOS_DESACTIVADOS` y el calificador sigue). Si la escala está en uso con otros niveles,
  `ESCALA_EN_USO`: no se toca la escala ni se escriben resultados. En `tiza publicar` detiene la
  publicación; en `tiza calificador`, el paso `CALIFICADOR` falla con `ESCALA_EN_USO`.
- Si usas `tiza-privado`, otra herramienta con su propia sesión, su corrector (`corregir`)
  rellena los resultados en el mismo envío al guardar y su orden `copiar-niveles` copia el nivel
  de cada fila de la rúbrica al resultado de su criterio; así no se marca dos veces. Al agente
  solo le llegan recuentos.

## 6. Cómo se ve la nota

- Todos los totales se ven en **porcentaje** (p. ej. «RA1: 40 %»). La nota sale en cadena
  instrumento → criterio → competencia → final, con la nota visible en cada nivel; en la vista
  por evaluaciones, la misma cadena dentro de cada evaluación.
- Solo si la final tiene tope, tiza monta «Notas (sobre 10)» con la nota de cada elemento y la
  final. Un elemento sin notas cuenta como 0 en el tope: a mitad de curso la final puede salir
  topada aunque el alumnado vaya bien; díselo al docente. Con tope, el total del curso lleva una
  fórmula y Moodle deja desmarcado «solo calificaciones no vacías»; si el docente la quita, que
  lo vuelva a marcar.

## 7. Si el aula ya tiene un calificador

- Lo que tiza monta va a «Calificador de tiza», con peso 0 en el total si había otro: el total
  del curso sigue siendo el del docente. Las actividades que pasan a tiza dejan de sumar en él.
- Antes de sacar una actividad de una categoría ajena, tiza **bloquea** su total si tiene notas
  (`CALIFICADOR_BLOQUEAR`); nunca desbloquea. `CAMBIADO_A_MANO` y `BLOQUEO_FALLIDO` se resuelven
  a mano en el aula.
- Un elemento que ya no está en el esquema pero tiene notas se queda con peso 0
  (`ELEMENTO_CON_NOTAS_QUITADO`); no se borra nada con notas.

## 8. Cerrar una evaluación

Cerrar una evaluación es poner `cerrada: true` y volver a montar: tiza la completa y la bloquea.
Dentro de una evaluación bloqueada no se crea, cambia, mueve ni borra nada; una actividad nueva
sale como `ACTIVIDAD_EN_EVALUACION_CERRADA` y `EVALUACION_CERRADA_EN_EL_AULA` avisa de que ya
estaba bloqueada. **tiza no puede reabrirla**: si falla a medias, repite el comando.

## 9. Cómo se monta

1. `tiza comprobar calificacion.yaml` (offline) hasta que salga 0; también comprueba `evalua`.
2. Las actividades tienen que estar publicadas; una que falta sale como `ACTIVIDAD_PENDIENTE`.
3. `tiza calificador … --en pruebas`: sin pregunta, gasta cupo.
4. `tiza calificador … --en real`: el docente confirma `[s/N]` curso por curso.

Lánzalo en segundo plano (hasta una hora): si te corta, la sesión acaba lo empezado y lo hecho
no se repite. En el informe, cada actividad sale `colocada`, `ya_estaba`, `pendiente` o
`sin_colocar`, y los pasos `CALIFICADOR`, `CALIFICADOR_BLOQUEAR` y `CALIFICADOR_COLOCAR` dicen
qué se hizo. Sin sesión, `SIN_SESION`: pide `tiza empezar`.

## 10. Lo que tiza no hace

- **No lee ni escribe notas** del alumnado. Solo sabe si un elemento tiene notas o no. No pidas
  ni muestres notas de nadie y no desbloquees nada.
- No usa los descriptores de las competencias de Moodle, pero **sí** sus «resultados»
  (*outcomes*) para la evidencia por criterio. No usa las «competencias» de Moodle.
- **No admitido**: cambiar `organizacion` o `final.de` de un calificador ya montado, ni
  configurar escalas propias (tiza crea la escala de logro de §5).
- Con más de 500 ficheros `.md` o `.html`, `CARPETA_DEMASIADO_GRANDE`: saca los que no sean del
  curso.
- Si dos actividades del mismo tipo y nombre apuntan al mismo sitio (`ACTIVIDAD_AMBIGUA`), no
  adivines cuál es: el docente borra o renombra una.
- `ESQUEMA_INVALIDO`, `PESOS_NO_SUMAN_100`, `ID_REPETIDO`, `SECCION_REPETIDA`,
  `TOPE_SIN_ELEMENTOS` y `ESQUEMA_FUERA_DE_CARPETA` dicen la ruta y la línea: corrígelos.
  `EVALUA_INVALIDO` es un `evalua` mal escrito; `ELEMENTO_DESCONOCIDO` nombra algo que no está en
  el esquema, y `SECCION_SIN_EVALUACION` pone una actividad fuera de toda evaluación.
- `ELEMENTO_CON_CRITERIOS`: un `evalua` nombra un elemento con criterios; usa sus criterios.
  `CRITERIOS_SIN_PESO` es un aviso: tiza los pesa igual, y se lo dices al docente.
- Si `.tiza/calificador.json` da `CALIFICADOR_INVALIDO`, no lo edites ni lo borres: pide al
  docente que lo revise; si se borra, tiza deja de saber qué cambió el docente a mano.
