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

- `organizacion`: `elementos` (FP) o `evaluaciones` (ESO y Bachillerato, con sus elementos dentro).
- `elementos`: `id` (letra inicial y luego letras, cifras o `_`, 16 como mucho), `nombre`, `peso`
  (0–100, todos suman 100) y `codigo` opcional; `criterios` (opcional) es una lista de `{id, nombre, peso?, codigo?}` con pesos en todos o en ninguno, sumando 100 (sin pesos pesan igual y sale `CRITERIOS_SIN_PESO`); ids únicos y `codigo` legible.
- `instrumentos` (opcional): casillas manuales, `{id, nombre, seccion, evalua}` (ver §3).
- `etapa` (`primaria`, `eso`, `bachillerato` o `fp`), `niveles_rubrica` (2–10 niveles `{id, nombre, porcentaje}`, con 0 y 100; por defecto 100/75/50/25/0) y `actividades_pesan_igual` (todas las actividades de un criterio pesan igual); la rúbrica solo vale con `etapa: eso`.
- `evaluaciones`: `nombre`, `secciones` (números o nombres) y `cerrada`; con la final por evaluaciones, cada una lleva `peso` (suman 100).
- `final`: `de` (`elementos` o `evaluaciones`) y `tope` (solo con `de: elementos`):
  `si_alguno_menor_que` (>0 y hasta 10) y `maximo` (0–10, sin llegar).
- `agregacion` (opcional): `regla` (`media`, `mediana`, `mas_alta` o `progresiva`) y `factores` (uno por evaluación, solo con progresiva). Cada elemento sin criterios o cada criterio puede llevar su propia `regla`; sin `agregacion`, todo es `media`. Con `final.tope` solo valen `media` y `progresiva`, sin recuperaciones (`REGLA_CON_TOPE`).
- En ESO, recomienda `final: {de: elementos}` (acumula por criterio); la UD o situación de aprendizaje es una unidad de planificación, no de calificación. Propón la regla según la programación: `media` por defecto, `progresiva` si lo último pesa más, `mas_alta` para criterios que se demuestran una vez y `mediana` con muchas evidencias y alguna atípica. La decide el departamento y tú no la cambias.

Lo que el esquema no expresa (redondeos, la actitud, otros pesos dentro de una evaluación) **se lo dices al docente y no lo fuerzas**.

## 3. Las actividades: `evalua`

Cada tarea, cuestionario o contenido H5P declara en su cabecera con qué resultados se evalúa y
con qué peso: `evalua: {RA1: 40, RA3: 25}` (de 0 a 100). Sin `evidencia: resultados`, la
actividad real queda en el primer elemento de `evalua` (en el orden del YAML) y en los demás
aparece una copia que refleja su nota. Con evidencia, va un calculado del resultado por criterio
y la tarea real queda con peso 0 (§5). Una actividad sin `evalua` no entra en el calificador, y
una página o etiqueta con `evalua` da `EVALUA_NO_CALIFICABLE` (también en `tiza comprobar`).

- Si el elemento tiene criterios, `evalua` nombra sus criterios (`CE1_1`, no `CE1`); nombrar el
  elemento da `ELEMENTO_CON_CRITERIOS`. Los pesos son **relativos** y se normalizan por hoja: no
  hace falta que sumen 100; un criterio (o elemento) cuyas actividades pesan todas 0 no cuenta.
- **Cuestionarios: uno por criterio.** Lo recomendable es que un cuestionario evalúe un solo criterio: así su nota llega entera a él. Si la prueba cubre varios, propón partirla en uno por criterio en la misma sección:
  la prueba de la UD3 con CE2.2 y CE3.1 se publica como «UD3 · Planificación» (CE2.2) y «UD3 · Construcción» (CE3.1), con al menos 3 preguntas cada uno (recomendado). Propón el criterio de cada pregunta a partir
  del texto literal (`tiza normativa ficha`) y confírmalo con el docente en una tabla de preguntas antes de escribir el fichero. Las calificaciones del cuestionario no crean elementos en el calificador: no
  reparten la nota entre criterios.
- **Casillas manuales** (`instrumentos`): tiza crea la casilla (sobre 10) en su primer criterio y
  copias en los demás. La nota la pone el docente a mano; tiza nunca la toca ni cambia su
  máximo. Una nota va a todos sus criterios; quitarlo con notas lo deja con peso 0
  (`ELEMENTO_CON_NOTAS_QUITADO`).
- **`evidencia: resultados`** (solo ESO): la tarea marca los resultados de sus criterios.
  Necesita `evalua`, `calificacion.yaml` con `etapa: eso` y niveles equidistantes; tiza crea una
  escala de logro y un resultado por criterio, y el docente marca un nivel por criterio en
  Moodle (ver §5).
- **`recupera`**: `recupera: 1` o `recupera: [1, 3]` en una tarea, cuestionario o H5P. Recupera los criterios de su `evalua` y su nota sustituye a la de esa evaluación si es mayor. Necesita `final: {de: elementos}`; cada criterio recuperado debe tener evidencias normales en esa evaluación y no puede ser `mediana` (`RECUPERA_SIN_EVIDENCIAS`, `RECUPERACION_CON_MEDIANA`). En una evaluación cerrada no cambia su nota: `RECUPERACION_EN_CERRADA` y la recuperación cuenta en la final. Declara solo las que recoja la programación (art. 45.5).

## 4. Rúbrica de la tarea (solo ESO)

Una tarea de ESO con `evalua` puede llevar `rubrica` de dos formas. `rubrica: por_criterios` crea
una fila genérica por criterio, con los pesos de `calificacion.yaml` y los niveles de
`niveles_rubrica`; basta para una tarea sencilla. `rubrica: rubricas/<tarea>.md` concreta el
criterio para esa tarea: recomendado 1–3 indicadores por criterio, un descriptor observable por
nivel y pesos propios. Úsala cuando el alumnado tenga que saber exactamente qué se le pide.

Para concretar cada criterio: cada descriptor dice lo **observable** en la entrega; todos los
niveles de una fila miden la misma dimensión y gradúan **calidad**, no cantidad de errores; sin
adjetivos vacíos («bien», «regular»); en positivo salvo «No iniciado». No inventes criterios:
parte del texto oficial (`tiza normativa ficha`) y del enunciado de la tarea.

Antes de escribir, enseña al docente **una sola tabla** (criterio con `codigo · nombre`, indicador, peso y una columna por nivel) y espera su confirmación; sin ella no escribas el fichero:

| criterio | indicador | peso | Destacado | Avanzado | … | No iniciado |
|---|---|---|---|---|---|---|
| `1.1 · Criterio 1.1` | … | … | … | … | … | … |

El fichero lleva `tipo: rubrica`, `nombre` y `filas`: cada una con `criterio` (hoja de `evalua`),
`indicador` (1–100), `peso` opcional (>0, ≤100, dos decimales) y `niveles` con **exactamente** los
ids de `niveles_rubrica`. Máximo 20 filas en total y al menos una por criterio de `evalua` con
peso > 0. Para varias filas de un criterio, este necesita `codigo`; sin él, usa una sola fila.
Después hace falta el cuerpo: descripción para el alumnado, sin imágenes ni ficheros locales. No pases el fichero a `tiza comprobar` ni a `tiza publicar`: comprueba y publica la tarea, que lo enlaza con `rubrica:`.

- Solo ESO (`RUBRICA_SOLO_ESO`), con `evalua` (`RUBRICA_SIN_EVALUA`) y `calificacion.yaml` (`RUBRICA_SIN_ESQUEMA`);
  una fila fuera de `evalua` o que no es hoja da `FILA_FUERA_DE_EVALUA`; un criterio de `evalua` con peso >0 sin fila, `CRITERIO_SIN_FILA`.
  Un nivel que falta da `DESCRIPTOR_FALTA`; una clave con forma de id que no está en `niveles_rubrica`, `NIVEL_DESCONOCIDO`; una clave sin forma de id, `RUBRICA_NO_VALIDA` con la pista de la coma.
  Dos filas no repiten criterio e indicador; o todas llevan `peso` o ninguna (`PESOS_DE_FILA_INCOMPLETOS`); fuera de la carpeta, `RUBRICA_FUERA_DE_CARPETA`.
  La forma de las filas es `RUBRICA_NO_VALIDA`; el frontmatter mal escrito, `FRONTMATTER_INVALIDO`; el HTML peligroso, `HTML_PELIGROSO`; los ficheros, `FICHERO_AUSENTE`, `CODIFICACION_INVALIDA` o `FICHERO_DEMASIADO_GRANDE`.
- El peso de la fila **solo reparte la nota visible de la tarea**: los 10 puntos (y los de cada
  nivel) que Moodle reescala; no sustituye al peso de `evalua` de cada criterio. Sin pesos, todas
  pesan igual. Sin `evidencia: resultados`, la nota total de la tarea llega a todos sus criterios
  según `evalua`; con evidencia, cada criterio recibe su nivel (en `tiza-privado`, `copiar-niveles`). Elige una: no combines `rubrica` con `evidencia`.
- `EVIDENCIA_COMPARTIDA` avisa en `tiza calificador` de una actividad o casilla manual (una vez por cada una) con 2+ criterios con peso y sin `evidencia`: su nota total llega a todos según
  `evalua`, y el peso de las filas solo reparte esa nota de tarea. `tiza comprobar` avisa antes de publicar, sin red, solo en un cuestionario con 2+ criterios con peso, y propone partirlo en uno por criterio (§3).
- La rúbrica es visible antes de la entrega (`alwaysshowdefinition` y `showdescriptionstudent`).
  Una tarea que ya existe solo recibe la rúbrica si el docente confirma; si además tiene notas (`rescalegrades`), no se activa aunque confirme (`RUBRICA_NO_ACTIVADA`, y se publica lo demás).
- Un fichero con `criterios` o `indicaciones` es de `tiza-privado`: en el público da
  `RUBRICA_NO_VALIDA`. Los cuestionarios no tienen rúbrica.
- `por_criterios`: los pesos salen de `calificacion.yaml` y no se inventan; si todos son 0,
  `RUBRICA_SIN_PESOS`. `actividades_pesan_igual` iguala las actividades de un criterio. Una tarea
  con notas sin rúbrica cuenta igual para todos sus criterios y no se desglosa sin corregir otra vez.

## 5. Evidencia por criterio (resultados, solo ESO)

En una tarea de ESO con **más de un criterio** en `evalua`, propón `evidencia: resultados`: el
docente marca un nivel por criterio en Moodle en vez de repartir la nota total. Con un solo
criterio no aporta: la nota de la tarea ya es su nivel.

- tiza crea la escala «Escala de logro (tiza)» con los niveles de `niveles_rubrica` (de menor a
  mayor y equidistantes; si no, `NIVELES_NO_EQUIDISTANTES`) y un resultado `TZ_<criterio>` por
  criterio. En el calificador pone un calculado por tarea y criterio que lleva el nivel a 0–10
  con el peso de `evalua`; **la nota total de la tarea deja de contar para los criterios**. Los
  descriptores de cada nivel van en el enunciado, para que el alumnado sepa qué se le pide.
- Una tarea con notas pide confirmación en `tiza publicar` (`EVIDENCIA_CAMBIADA_CON_NOTAS`):
  sus notas antiguas dejan de contar; con «N», se publica sin resultados. `tiza calificador`
  también pregunta por las tareas pendientes con notas. Quitar `evidencia` no borra el resultado:
  al volver a montar queda con peso 0, y `RESULTADO_CON_NOTAS_QUITADO` avisa solo si ya tenía niveles.
- Sin resultados en el sitio, `RESULTADOS_DESACTIVADOS` en `tiza publicar` (no se escribe nada y se publica el resto) o en `tiza calificador` (queda el paso y sigue).
  Si la escala está en uso con otros niveles, `ESCALA_EN_USO`: no se toca ni se escriben resultados; en `tiza publicar` detiene la publicación y en
  `tiza calificador` falla el paso `CALIFICADOR`.
- Con `tiza-privado`, su corrector (`corregir`) rellena los resultados al guardar y su orden
  `copiar-niveles` copia el nivel de cada fila al resultado de su criterio; al agente solo le llegan recuentos.

## 6. Cómo se ve la nota

- Todos los totales se ven en **porcentaje** (p. ej. «RA1: 40 %»). La nota sale en cadena
  instrumento → criterio → competencia → final, con la nota visible en cada nivel; en la vista
  por evaluaciones, la misma cadena dentro de cada evaluación.
- **Qué ve el alumnado**: las actividades, las casillas manuales y los niveles por criterio, pero no las notas calculadas que monta tiza (copias, indicadores, notas sobre 10 y la final): las crea ocultas y las vuelve a ocultar en cada pasada (`CALCULADOS_OCULTADOS`, u `OCULTAR_FALLIDO` si el aula no deja). El ajuste del curso debe estar en «Ocultar totales si contienen ítems ocultos»; si no, avisa con `TOTALES_VISIBLES` (Calificaciones → Configuración del calificador → Informe del usuario) y no lo cambia.
- Solo si la final tiene tope, tiza monta «Notas (sobre 10)» con la nota de cada elemento y la
  final. Un elemento sin notas cuenta como 0: a mitad de curso la final puede salir topada aunque
  el alumnado vaya bien; díselo. Con tope, el total lleva fórmula y Moodle deja desmarcado «solo
  calificaciones no vacías»; si el docente la quita, que lo vuelva a marcar.

## Juicio del docente

El total de cualquier categoría se puede sobrescribir a mano en el informe del calificador de Moodle; la media calculada queda a la vista. tiza no lo deshace ni escribe notas. Si la programación lo exige, el docente lo justifica (art. 46.4) y lo deja escrito en el aula.

## 7. Si el aula ya tiene un calificador

- Lo que tiza monta va a «Calificador de tiza», con peso 0 en el total si había otro: el total
  del curso sigue siendo el del docente. Las actividades que pasan a tiza dejan de sumar en él.
- Antes de sacar una actividad de una categoría ajena, tiza **bloquea** su total si tiene notas
  (`CALIFICADOR_BLOQUEAR`); nunca lo desbloquea. `CAMBIADO_A_MANO` y `BLOQUEO_FALLIDO` se resuelven a mano.
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
3. `tiza calificador … --en pruebas` (sin pregunta, gasta cupo) o `--en real` (el docente
   confirma `[s/N]` curso por curso).

Lánzalo en segundo plano (hasta una hora): si te corta, la sesión acaba lo empezado y lo hecho no
se repite. En el informe, cada actividad sale `colocada`, `ya_estaba`, `pendiente` o `sin_colocar`,
y los pasos `CALIFICADOR`, `CALIFICADOR_BLOQUEAR` y `CALIFICADOR_COLOCAR` dicen qué se hizo; sin sesión, `SIN_SESION`: pide `tiza empezar`. `CALCULADOS_OCULTADOS` cuenta las notas calculadas que se han vuelto a ocultar, `OCULTAR_FALLIDO` avisa de las que el aula no dejó ocultar (no corta el montaje) y `TOTALES_VISIBLES` de que el curso deja ver los totales con ítems ocultos.

## 10. Lo que tiza no hace

- **No lee ni escribe notas** del alumnado: solo sabe si un elemento tiene notas. No pidas ni muestres notas de nadie y no desbloquees nada.
- No usa los descriptores de las competencias de Moodle, pero **sí** sus «resultados»
  (*outcomes*) para la evidencia por criterio. No usa las «competencias» de Moodle.
- **No admitido**: cambiar `organizacion` o `final.de` de un calificador ya montado, ni configurar escalas propias (tiza crea la escala de logro de §5).
- Con más de 500 ficheros `.md` o `.html`, `CARPETA_DEMASIADO_GRANDE`: saca los que no sean del curso.
- Si dos actividades del mismo tipo y nombre apuntan al mismo sitio (`ACTIVIDAD_AMBIGUA`), no adivines cuál es: el docente borra o renombra una.
- `ESQUEMA_INVALIDO`, `PESOS_NO_SUMAN_100`, `ID_REPETIDO`, `SECCION_REPETIDA`, `TOPE_SIN_ELEMENTOS`
  y `ESQUEMA_FUERA_DE_CARPETA` dicen la ruta y la línea. `EVALUA_INVALIDO` es un `evalua` mal escrito; `ELEMENTO_DESCONOCIDO` nombra algo que no está; `SECCION_SIN_EVALUACION` deja una actividad fuera; `PROGRESIVA_SIN_FACTORES`, `RECUPERA_INVALIDO`, `RECUPERA_SIN_EVIDENCIAS`, `RECUPERACION_CON_MEDIANA`, `RECUPERACION_SOLO_FINAL_DE_ELEMENTOS`, `ACTIVIDAD_SIN_EVALUACION` y `REGLA_CON_TOPE` completan el diagnóstico.
- `ELEMENTO_CON_CRITERIOS`: un `evalua` nombra un elemento con criterios; usa sus criterios.
  `CRITERIOS_SIN_PESO` es un aviso: tiza los pesa igual, y se lo dices al docente.
- Si `.tiza/calificador.json` da `CALIFICADOR_INVALIDO`, no lo edites ni lo borres: pide al docente que lo revise; si se borra, tiza deja de saber qué cambió el docente a mano.
