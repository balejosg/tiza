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

Con criterios e instrumentos (por ejemplo, ESO), esto es lo que cambia sobre el ejemplo de arriba:

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
- `etapa` (`primaria`, `eso`, `bachillerato` o `fp`), `niveles_rubrica` (2–10 niveles `{id, nombre, porcentaje}`, con 0 y 100; por defecto 100/75/50/25/0) y `actividades_pesan_igual` (todas las actividades de un criterio pesan igual).
- `evaluaciones`: `nombre`, `secciones` (números o nombres) y `cerrada`; con la final por evaluaciones, cada una lleva `peso` (suman 100). Con la final de elementos, el `peso` es opcional: es el `q_n` con el que cada copia del curso pesa su trimestre; sin pesos, todos los trimestres con evidencias pesan igual.
- `final`: `de` (`elementos` o `evaluaciones`) y `tope` (solo con `de: elementos`):
  `si_alguno_menor_que` (>0 y hasta 10) y `maximo` (0–10, sin llegar).
- `agregacion` (opcional): `regla` (`media`, `mediana`, `mas_alta` o `progresiva`) y `factores` (uno por evaluación, solo con progresiva). Cada elemento sin criterios o cada criterio puede llevar su propia `regla`; sin `agregacion`, todo es `media`. Con `final.tope` valen todas las reglas y también `recupera`.
- Con criterios, recomienda `final: {de: elementos}` (acumula por criterio); la UD o situación de aprendizaje es una unidad de planificación, no de calificación. Propón la regla según la programación: `media` por defecto, `progresiva` si lo último pesa más, `mas_alta` para criterios que se demuestran una vez y `mediana` con muchas evidencias y alguna atípica. La decide el departamento y tú no la cambias.

Lo que el esquema no expresa (redondeos, la actitud, otros pesos dentro de una evaluación) **se lo dices al docente y no lo fuerzas**.

## 3. Las actividades: `evalua`

Cada tarea, cuestionario o contenido H5P declara en su cabecera con qué resultados se evalúa y
con qué peso: `evalua: {RA1: 40, RA3: 25}` (de 0 a 100). Sin `evidencia: resultados`, la
actividad real queda en su primer criterio de la vista por evaluaciones (en el orden del YAML) y
en los demás criterios aparece una copia oculta que refleja su nota. Con evidencia, la tarea real
queda con peso 0 y cada criterio lleva un resultado y su calculado (§6); la vista del curso copia
los totales trimestrales. Una actividad sin `evalua` no entra en el calificador, y una página o
etiqueta con `evalua` da `EVALUA_NO_CALIFICABLE` (también en `tiza comprobar`).

- Si el elemento tiene criterios, `evalua` nombra sus criterios (`CE1_1`, no `CE1`); nombrar el
  elemento da `ELEMENTO_CON_CRITERIOS`. Los pesos son **relativos** y se normalizan por hoja: no
  hace falta que sumen 100; un criterio (o elemento) cuyas actividades pesan todas 0 no cuenta.
- **Cuestionarios: uno por criterio.** Lo recomendable es que un cuestionario evalúe un solo criterio: así su nota llega entera a él. Si la prueba cubre varios, propón partirla en uno por criterio en la misma sección:
  la prueba de la UD3 con CE2.2 y CE3.1 se publica como «UD3 · Planificación» (CE2.2) y «UD3 · Construcción» (CE3.1), con al menos 3 preguntas cada uno (recomendado). Propón el criterio de cada pregunta a partir
  del texto literal (`tiza normativa ficha`) y confírmalo con el docente en una tabla de preguntas antes de escribir el fichero. Las calificaciones del cuestionario no crean elementos en el calificador: no
  reparten la nota entre criterios.
- **Casillas manuales** (`instrumentos`): tiza crea la casilla (sobre 10) en su primer criterio de
  la vista primaria y copias en los demás; en la vista del curso, la copia de su criterio. La
  nota la pone el docente a mano; tiza nunca la toca ni cambia su máximo. Una nota va a todos sus
  criterios; quitarlo con notas lo deja con coeficiente 0 (`ELEMENTO_CON_NOTAS_QUITADO`).
- **`evidencia: resultados`**: la tarea marca los resultados de sus criterios.
  Necesita `evalua` y `calificacion.yaml` con niveles equidistantes; tiza crea una
  escala de logro y un resultado por criterio, y el docente marca un nivel por criterio en
  Moodle. El resultado del aula no se puede ponderar directamente en media ponderada (S2):
  un calculado `TZ_R_` sobre 100 lleva el peso de `evalua` y el resultado queda con peso 0.
  Con un fichero de `filas`, hay un resultado con su propia escala y sus descriptores por cada
  fila (ver §6).
- **`recupera`**: `recupera: 1` o `recupera: [1, 3]` en una tarea, cuestionario o H5P. Recupera los criterios de su `evalua` y su nota sustituye a la del trimestre en la nota del curso si es mayor; la recuperación no es evidencia del trimestre y se monta en la vista del curso, envolviendo la copia del trimestre recuperado en una «más alta» (o suelta si la hoja ya es `mas_alta`). Necesita `final: {de: elementos}`; cada criterio recuperado debe tener evidencias normales en esa evaluación y no puede ser `mediana` (`RECUPERA_SIN_EVIDENCIAS`, `RECUPERACION_CON_MEDIANA`). En una evaluación cerrada no cambia su nota: `RECUPERACION_EN_CERRADA` y la recuperación cuenta en la final. Declara solo las que recoja la programación (art. 45.5).

## 4. Mapa de cobertura

`tiza comprobar calificacion.yaml` deja en `.tiza/cobertura.json` qué evalúa cada criterio o
elemento sin criterios: el instrumento, la actividad, la evaluación, el peso normalizado y la
regla. Es la fuente de la tabla de trazabilidad y de la página informativa; no la inventes de
memoria. Incluye `generado`: si el docente edita actividades o el esquema, vuelve a comprobar
antes de usarlo (tiza no vigila si el mapa se queda viejo).

Los avisos del informe no impiden montar el calificador:

- `HOJA_SIN_EVIDENCIAS`: ese criterio no tiene ninguna actividad ni casilla manual. Propón una
  actividad en la evaluación que toque o pregunta si el departamento lo evalúa con otro
  instrumento. Si la programación lo sitúa más adelante, dilo: es normal que en octubre aún no
  tenga evidencias y no hay que inventarlas.
- `HOJA_CON_UNA_EVIDENCIA`: solo una. Puede ser suficiente, pero díselo al docente y valora si
  conviene otra evidencia para que la nota no dependa de una sola entrega.
- `MEDIANA_CON_POCAS_EVIDENCIAS`: la regla `mediana` con dos evidencias; con dos, la mediana es
  la media. Con menos de tres, propón cambiar la regla o añadir evidencias.
- `PROGRESIVA_EN_UNA_EVALUACION`: la regla `progresiva` tiene todas sus evidencias en la misma
  evaluación, así que el factor de la evaluación no distingue nada. Propón repartirlas o cambiar
  la regla.

El `instrumento` es un valor cerrado que deduce tiza, no un campo nuevo:

| valor | qué es |
|---|---|
| `tarea_rubrica_criterios` | tarea con `rubrica: por_criterios` |
| `tarea_rubrica_filas` | tarea con una rúbrica de `filas` |
| `tarea_resultados` | tarea con `evidencia: resultados` |
| `tarea_resultados_filas` | tarea con `evidencia: resultados` y una rúbrica de `filas`: un resultado por fila, con sus descriptores |
| `tarea` | tarea sin rúbrica ni resultados |
| `cuestionario` | cuestionario |
| `h5p` | contenido H5P |
| `casilla_manual` | `instrumentos` de `calificacion.yaml` |

La marca `recupera: [n…]` dice qué evaluaciones recupera esa evidencia; una recuperación no cuenta
como evidencia para los avisos. Para la revisión de una familia, prepara una tabla
criterio → instrumento → actividad → evaluación → peso → regla con los datos del mapa, sin nombres
ni notas del alumnado, y conviértela con `tiza documento trazabilidad.md`; el ejemplo
`ejemplos/trazabilidad.md` muestra el formato. Si el centro pide la
mitad individual (la nota de un alumno), que la aporte el docente desde el aula: tiza no la tiene.

En Bachillerato y FP el mapa funciona igual: la rúbrica y la evidencia por resultados no dependen
de `etapa`. Los textos hablan de «criterio» y de «resultado de aprendizaje», no de «competencia»;
para los RA y CE, parte de `tiza normativa ficha`. Para la página de inicio de curso, sigue
`guias/informar-al-alumnado.md`.

## 5. Rúbrica de la tarea

Para una tarea con **varios criterios**, la recomendación es **B**: `evidencia: resultados` sin
filas, con los descriptores en el enunciado. **A** (`por_criterios` o rúbrica nativa) para un
criterio o un RA sin criterios. **C** (rúbrica de `filas`) solo si lo pide, sabiendo que los
descriptores no se cambian después de publicar.

Una tarea con `evalua` puede llevar `rubrica` de dos formas, en cualquier etapa (ESO,
Bachillerato, FP o Primaria). `rubrica: por_criterios` crea
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

- Con `evalua` (`RUBRICA_SIN_EVALUA`) y `calificacion.yaml` (`RUBRICA_SIN_ESQUEMA`);
  una fila fuera de `evalua` o que no es hoja da `FILA_FUERA_DE_EVALUA`; un criterio de `evalua` con peso >0 sin fila, `CRITERIO_SIN_FILA`.
  Un nivel que falta da `DESCRIPTOR_FALTA`; una clave con forma de id que no está en `niveles_rubrica`, `NIVEL_DESCONOCIDO`; una clave sin forma de id, `RUBRICA_NO_VALIDA` con la pista de la coma. Con `evidencia: resultados` los descriptores no pueden llevar comas (`DESCRIPTOR_CON_COMA`, con su línea); la rúbrica nativa (sin evidencia o con «por_criterios») sí las admite.
  Dos filas no repiten criterio e indicador; o todas llevan `peso` o ninguna (`PESOS_DE_FILA_INCOMPLETOS`); fuera de la carpeta, `RUBRICA_FUERA_DE_CARPETA`.
  La forma de las filas es `RUBRICA_NO_VALIDA`; el frontmatter mal escrito, `FRONTMATTER_INVALIDO`; el HTML peligroso, `HTML_PELIGROSO`; los ficheros, `FICHERO_AUSENTE`, `CODIFICACION_INVALIDA` o `FICHERO_DEMASIADO_GRANDE`.
- El peso de la fila reparte la nota visible de la tarea (los 10 puntos que Moodle reescala) y,
  con `evidencia: resultados`, el peso del calculado de cada fila. Sin pesos, todas pesan igual.
  Sin `evidencia: resultados`, la nota total de la tarea llega a todos sus criterios según
  `evalua`; con evidencia sin filas, cada criterio recibe su nivel; con evidencia y filas, cada
  fila tiene su resultado y su calculado directo en el criterio (sin subcategoría «Filas»), y no
  se crea la rúbrica nativa. En
  `tiza-privado`, `copiar-niveles` copia el nivel de cada fila al resultado de su criterio si no
  usas la combinación de descriptores.
- `EVIDENCIA_COMPARTIDA` avisa en `tiza calificador` de una actividad o casilla manual (una vez por cada una) con 2+ criterios con peso y sin `evidencia`: su nota total llega a todos según
  `evalua`, y el peso de las filas solo reparte esa nota de tarea. `tiza comprobar` avisa antes de publicar, sin red, solo en un cuestionario con 2+ criterios con peso, y propone partirlo en uno por criterio (§3).
- La rúbrica es visible antes de la entrega (`alwaysshowdefinition` y `showdescriptionstudent`).
  Una tarea que ya existe solo recibe la rúbrica si el docente confirma; si además tiene notas (`rescalegrades`), no se activa aunque confirme (`RUBRICA_NO_ACTIVADA`, y se publica lo demás).
- Un fichero con `criterios` o `indicaciones` es de `tiza-privado`: en el público da
  `RUBRICA_NO_VALIDA`. Los cuestionarios no tienen rúbrica.
- `por_criterios`: los pesos salen de `calificacion.yaml` y no se inventan; si todos son 0,
  `RUBRICA_SIN_PESOS`. `actividades_pesan_igual` iguala las actividades de un criterio. Una tarea
  con notas sin rúbrica cuenta igual para todos sus criterios y no se desglosa sin corregir otra vez.

## 6. Evidencia por criterio (resultados)

En una tarea con **más de un criterio** en `evalua`, propón **B**: `evidencia: resultados` sin
filas. El docente marca un nivel por criterio en Moodle; la tarea real queda con peso 0 y cada
criterio lleva su resultado `TZ_O_…` y un calculado `TZ_R_…` sobre 100 con el peso de `evalua`.
El resultado del aula no se puede ponderar directamente en media ponderada (su formulario no
tiene coeficiente): el peso va en el calculado. **La nota total de la tarea deja de contar para
los criterios.** Los descriptores van en el enunciado.

Sin fichero de filas, tiza crea la escala «Escala de logro (tiza)» con los niveles de
`niveles_rubrica` (equidistantes; si no, `NIVELES_NO_EQUIDISTANTES`) y un resultado `TZ_<criterio>`
por criterio; un calculado por criterio lleva el nivel a 0–100 con el peso de `evalua`.

Con `rubrica: rubricas/<tarea>.md` (**C**, solo si el docente lo pide):

- cada fila es un resultado con **su propia escala** «Nivel: descriptor», de menor a mayor; hay un
  desplegable por fila con el descriptor entero y **no se crea la rúbrica nativa**. Cada fila lleva
  su calculado directo en la categoría del criterio, con el peso `evalua × parte de la fila`; no
  hay subcategoría «Filas». Una fila sin marcar no cuenta y el criterio se renormaliza entre todas
  sus evidencias de ese trimestre, no solo entre las filas de la tarea.
- el valor es **continuo**, sin redondear al nivel. Para la programación: «La calificación de cada
  criterio es la media ponderada de sus evidencias, con el nivel alcanzado en cada fila (0–100),
  sin redondear al nivel».
- **sin comas**: la escala de Moodle separa niveles con comas. Un descriptor con coma da
  `DESCRIPTOR_CON_COMA` con fichero, fila, nivel y línea; la rúbrica nativa (sin evidencia o con «por_criterios») sí las admite.
- **fija los descriptores antes de publicar**: una escala ya usada no se cambia y tiza no sabe si
  tiene niveles puestos. Si existe con otros niveles, `DESCRIPTOR_PUBLICADO`: no se toca y se
  monta lo demás. Para cambiarlos, renombra el `indicador`: es una fila nueva y la vieja deja de contar.

Común: una tarea con notas pide confirmación (`EVIDENCIA_CAMBIADA_CON_NOTAS`); con «N», se publica sin resultados. `tiza calificador` también pregunta. Quitar `evidencia` deja el resultado con peso 0; `RESULTADO_CON_NOTAS_QUITADO` avisa si ya tenía niveles.

- Sin resultados en el sitio, `RESULTADOS_DESACTIVADOS` (no se escribe nada y se sigue). Sin filas, una escala común en uso con otros niveles da `ESCALA_EN_USO` y detiene la publicación (en el calificador, falla `CALIFICADOR`); con filas, `DESCRIPTOR_PUBLICADO` y se sigue.
- Con `tiza-privado`, `corregir` rellena los resultados y `copiar-niveles` copia el nivel de cada fila al resultado de su criterio; al agente solo le llegan recuentos. Con descriptores, usa los resultados como fuente y no dupliques la rúbrica nativa.

## 7. Cómo se ve la nota

- El árbol es **evaluación → RA o competencia → criterio → actividades** en la vista primaria (la
  que da la final). La otra vista, en `TZ_VISTA` con peso 0, es la del curso: una copia oculta por
  trimestre con evidencias, pesada con el `q_n` de la evaluación (`TZ_C_…`). La nota del RA es la
  media ponderada de sus trimestres; la del criterio, la de sus trimestres. Escríbelo en la
  programación: «La calificación de cada criterio es la media ponderada de la obtenida en él en
  cada evaluación, con el peso de cada evaluación; la del RA, la media ponderada de sus criterios».
- Todos los totales se ven en **porcentaje** (p. ej. «RA1: 40 %»). La nota sale en cadena
  instrumento → criterio → competencia → final, con la nota visible en cada nivel; en la vista
  por evaluaciones, la misma cadena dentro de cada evaluación.
- **Qué ve el alumnado**: las actividades, las casillas manuales y los niveles por criterio, pero no las copias ni la nota final: tiza las crea ocultas y las vuelve a ocultar en cada pasada (`CALCULADOS_OCULTADOS`, u `OCULTAR_FALLIDO` si el aula no deja). El ajuste del curso debe estar en «Ocultar totales si contienen ítems ocultos»; si no, avisa con `TOTALES_VISIBLES` (Calificaciones → Configuración del calificador → Informe del usuario) y no lo cambia. Si el informe del usuario muestra «Ponderación» o «Contribución al total del curso», avisa con `PONDERACIONES_VISIBLES`: con las actividades en la vista que no da la final, el alumnado vería 0 % en esas columnas; tampoco cambia el ajuste.
- La regla `mediana` en el curso es la **mediana de las medianas trimestrales**, no la de todas las
  evidencias del año; es un cambio de definición y va junto a `MEDIANA_CON_POCAS_EVIDENCIAS`.
- Solo si la final tiene tope, tiza monta `TZ_NOTA_FINAL` («Nota final (sobre 10)»), oculta y sobre
  100; el total del curso la copia dividida por 10. El tope cuenta los elementos cuya evaluación ya
  está cerrada: antes no topa y, después, un elemento sin notas cuenta como 0. Con tope, el total
  lleva fórmula y Moodle deja desmarcado «solo calificaciones no vacías»; si el docente la quita,
  que lo vuelva a marcar.

## Juicio del docente

El total de cualquier categoría se puede sobrescribir a mano en el informe del calificador de Moodle; la media calculada queda a la vista. tiza no lo deshace ni escribe notas. Si la programación lo exige, el docente lo justifica (art. 46.4) y lo deja escrito en el aula.

## 8. Ponderar sin competencias

Cuando el docente quiere que una parte de la nota pese un porcentaje (por ejemplo, «el examen
pesa el 30 % de la primera evaluación») pero **no** quiere criterios ni competencias en Moodle,
no uses `calificacion.yaml`: escribe un `ponderacion.yaml` y pásalo por el mismo comando,
`tiza calificador ponderacion.yaml`. tiza retoca el calificador que el docente ya tiene en el
sitio; no monta el «Calificador de tiza».

```yaml
ponderacion:
  - id: EXAMEN_1EV
    nombre: "Examen 1.ª evaluación"
    dentro_de: "PRIMERA EVALUACIÓN"
    calculo: media_ponderada
    solo_no_vacias: false
    elementos:
      - {fichero: 1eva/test-1-hardware.md, peso: 16}
      - {fichero: 1eva/test-2-procesador-textos.md, peso: 8}
      - {fichero: 1eva/test-3-maquinas-virtuales-linux.md, peso: 6}
      - {fichero: 1eva/tarea-sheets-monta-tu-pc.html, peso: 45}

  - categoria: "PRIMERA EVALUACIÓN"
    elementos:
      - {categoria: EXAMEN_1EV, porcentaje: 30}
```

- **Pregunta siempre** el método (`media_ponderada` o `natural`), si la categoría nueva lleva
  «solo no vacías», y si el porcentaje es del total de esa categoría. En una categoría que ya
  existe, `porcentaje` es la parte del total; `peso` solo vale en las nuevas y es relativo.
- **Nombra lo que hay**, con los nombres exactos: `tiza estructura --calificador` deja en
  `.tiza/estructura.json` las categorías, sus métodos y sus hijos con el porcentaje efectivo.
  Si el fichero no trae el calificador, pide `tiza estructura --calificador`.
- **Solo se toca lo nombrado**: tiza crea la subcategoría nueva dentro de una que ya existe
  (`dentro_de`, nunca en la raíz), mete ahí las actividades y fija método y pesos. Lo que no
  nombras no cambia; lo que sale de una categoría se ve en el antes/después.
- **No se borra nada** y tiza no desbloquea. Una categoría `TZP_` que quitas del fichero se
  queda en el aula (`CATEGORIA_NO_DECLARADA`).
- **La exclusión es por curso**: un curso con el «Calificador de tiza» (`TZ_TIZA`) da
  `PONDERACION_CON_CALIFICADOR_DE_TIZA`; uno con categorías `TZP_` no admite `calificacion.yaml`
  (`CALIFICADOR_CON_PONDERACION`). Si están los dos ficheros en la carpeta, `tiza comprobar`
  avisa con `CALIFICACION_Y_PONDERACION`. Elige un solo modo por curso.
- Si el aula no ofrece «media ponderada» (`CALCULO_NO_DISPONIBLE`), propón `natural`; con
  porcentajes da el mismo reparto si las piezas están sobre la misma escala.
- Los códigos del esquema (`PONDERACION_INVALIDA`, `PESOS_MEZCLADOS`, `PESO_EN_EXISTENTE`,
  `ELEMENTO_REPETIDO`, `CICLO_DE_CATEGORIAS`, `PORCENTAJES_SUPERAN_100`, `NO_CALIFICABLE`) llevan
  ruta y línea. Los del aula (`CATEGORIA_AUSENTE`/`AMBIGUA`, `ACTIVIDAD_AUSENTE`/`AMBIGUA`,
  `ELEMENTO_AUSENTE`/`AMBIGUO`, `PORCENTAJES_SIN_RESTO`, `PORCENTAJE_IMPOSIBLE`,
  `CALCULO_SIN_PESOS`, `CATEGORIA_BLOQUEADA`) dicen qué corregir antes de volver a pedirlo.
- `CAMBIADO_A_MANO` se pregunta aparte, después del «sí» al curso; con «no», se conserva el
  cambio del aula. `PESOS_CON_NOTAS` avisa de la categoría cuyo total cambia porque ya tiene
  notas. tiza nunca lee ni escribe notas del alumnado.

## 9. Si el aula ya tiene un calificador

- Lo que tiza monta va a «Calificador de tiza», con peso 0 en el total si había otro: el total
  del curso sigue siendo el del docente. Las actividades que pasan a tiza dejan de sumar en él.
- Antes de sacar una actividad de una categoría ajena, tiza **bloquea** su total si tiene notas
  (`CALIFICADOR_BLOQUEAR`); nunca lo desbloquea. `CAMBIADO_A_MANO` y `BLOQUEO_FALLIDO` se resuelven a mano.
- Un elemento que ya no está en el esquema pero tiene notas se queda con peso 0
  (`ELEMENTO_CON_NOTAS_QUITADO`); no se borra nada con notas.
- **No se mezcla con `ponderacion.yaml` en el mismo curso.** Si el aula ya tiene categorías
  `TZP_`, montar `calificacion.yaml` da `CALIFICADOR_CON_PONDERACION`; elige el modo por
  categorías de la §8 o quita antes esas categorías a mano.
- **Árbol de la generación anterior.** `TZ_NOTAS`, `TZ_K_TIZA`, `TZ_AG_*`, `TZ_RP_*`, `TZ_F_*` o
  copias `TZ_C_` en una vista con actividades dan `CALIFICADOR_ANTIGUO`, sin escribir nada. Borra a
  mano «Calificador de tiza» en Calificaciones → Configuración del calificador (sus hijos suben al
  curso) y repite; tiza quita la entrada vieja de `calificador.json`.

## 10. Cerrar una evaluación

Cerrar una evaluación es poner `cerrada: true` y volver a montar: tiza la completa y la bloquea.
Dentro de una evaluación bloqueada no se crea, cambia, mueve ni borra nada; una actividad nueva
sale como `ACTIVIDAD_EN_EVALUACION_CERRADA` y `EVALUACION_CERRADA_EN_EL_AULA` avisa de que ya
estaba bloqueada. **tiza no puede reabrirla**: si falla a medias, repite el comando.

## 11. Cómo se monta

1. `tiza comprobar calificacion.yaml` (offline) hasta que salga 0; también comprueba `evalua`.
2. Las actividades tienen que estar publicadas; una que falta sale como `ACTIVIDAD_PENDIENTE`.
3. `tiza calificador … --en pruebas` (sin pregunta, gasta cupo) o `--en real` (el docente
   confirma `[s/N]` curso por curso).

Lánzalo en segundo plano (hasta una hora): si te corta, la sesión acaba lo empezado y lo hecho no
se repite. En el informe, cada actividad sale `colocada`, `ya_estaba`, `pendiente` o `sin_colocar`,
y los pasos `CALIFICADOR`, `CALIFICADOR_BLOQUEAR` y `CALIFICADOR_COLOCAR` dicen qué se hizo; `CALIFICADOR_CAMBIOS` desglosa los cambios por tipo (también `fijar_coeficiente`), con los primeros números de ID `TZ_…`. Si un segundo montaje sin tocar nada vuelve a dar cambios, copia al docente ese desglose: es lo que hace falta para saber qué no se queda en el aula; sin sesión, `SIN_SESION`: pide `tiza empezar`. `CALCULADOS_OCULTADOS` cuenta las copias y calculados que se han vuelto a ocultar, `OCULTAR_FALLIDO` avisa de los que el aula no dejó ocultar (no corta el montaje), `TOTALES_VISIBLES` de que el curso deja ver los totales con ítems ocultos y `PONDERACIONES_VISIBLES` de que el informe del usuario muestra ponderaciones o contribución. `CALCULO_NO_DISPONIBLE` corta antes de escribir si el aula no ofrece «Media ponderada de calificaciones»; `CALIFICADOR_ANTIGUO`, si el árbol es de la generación anterior.

## 12. Lo que tiza no hace

- **No lee ni escribe notas** del alumnado: solo sabe si un elemento tiene notas. No pidas ni muestres notas de nadie y no desbloquees nada. En la ponderación (§8) solo se usa `tiene_notas` para avisar de que el total de una categoría cambiará.
- **Los dos modos no conviven en un curso**: `calificacion.yaml` (por criterios, con `TZ_TIZA`) y `ponderacion.yaml` (por categorías, con `TZP_`) son excluyentes. Si están los dos ficheros, `tiza comprobar` avisa; elige uno por curso.
- No usa los descriptores de las competencias de Moodle, pero **sí** sus «resultados»
  (*outcomes*) para la evidencia por criterio. No usa las «competencias» de Moodle.
- **No admitido**: cambiar `organizacion` o `final.de` de un calificador ya montado, ni configurar escalas propias (tiza crea la escala de logro de §6).
- Con más de 500 ficheros `.md` o `.html`, `CARPETA_DEMASIADO_GRANDE`: saca los que no sean del curso.
- Si dos actividades del mismo tipo y nombre apuntan al mismo sitio (`ACTIVIDAD_AMBIGUA`), no adivines cuál es: el docente borra o renombra una.
- `ESQUEMA_INVALIDO`, `PESOS_NO_SUMAN_100`, `ID_REPETIDO`, `SECCION_REPETIDA`, `TOPE_SIN_ELEMENTOS`
  y `ESQUEMA_FUERA_DE_CARPETA` dicen la ruta y la línea. `EVALUA_INVALIDO` es un `evalua` mal escrito; `ELEMENTO_DESCONOCIDO` nombra algo que no está; `SECCION_SIN_EVALUACION` deja una actividad fuera; `PROGRESIVA_SIN_FACTORES`, `RECUPERA_INVALIDO`, `RECUPERA_SIN_EVIDENCIAS`, `RECUPERACION_CON_MEDIANA`, `RECUPERACION_SOLO_FINAL_DE_ELEMENTOS` y `ACTIVIDAD_SIN_EVALUACION` completan el diagnóstico. `CALCULO_NO_DISPONIBLE` y `CALIFICADOR_ANTIGUO` cortan antes de escribir; no los rodees con otro montaje.
- `ELEMENTO_CON_CRITERIOS`: un `evalua` nombra un elemento con criterios; usa sus criterios.
  `CRITERIOS_SIN_PESO` es un aviso: tiza los pesa igual, y se lo dices al docente.
- Si `.tiza/calificador.json` da `CALIFICADOR_INVALIDO`, no lo edites ni lo borres: pide al docente que lo revise; si se borra, tiza deja de saber qué cambió el docente a mano.
