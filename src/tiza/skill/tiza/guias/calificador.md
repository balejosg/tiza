# Guía: el calificador del aula, alineado con la programación

Se usa cuando el docente pide montar el calificador de su aula (notas por competencias o
resultados de aprendizaje, criterios o evaluaciones) o cambiar cómo se calcula la nota final.
Habla en su lenguaje: competencias, resultados, criterios, evaluaciones, ponderaciones.

tiza monta lo que dice el esquema y nada más. **No inventes pesos, fórmulas ni topes.**

## 1. De dónde sale cada cosa

- Los elementos, sus criterios y sus códigos: la programación del docente (`tiza leer`, y abre
  su `.txt`) y `tiza normativa` (`programacion`, `ficha <codigo>`). En ESO y Bachillerato son
  `competencia_especifica` y `criterio`; en FP, `resultado_aprendizaje` y `criterio_fp`.
- Los pesos y las reglas (ponderación, criterios, tope): la programación o la del departamento.
  Si no los trae, haz **una sola pregunta** al docente y espera.
- Si las fuentes se contradicen, manda el docente: díselo y no elijas tú.
- `secciones` del esquema son las `seccion:` de los ficheros; la temporalización dice qué van en
  cada evaluación.

## 2. El esquema: `calificacion.yaml`

Va en la carpeta de la asignatura. Este es el ejemplo completo que validan los tests de tiza:

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

Con criterios e instrumentos (ESO), el ejemplo completo está en `ejemplos/calificacion-criterios.yaml`:

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

- `organizacion`: `elementos` (FP, por resultados o criterios) o `evaluaciones` (ESO y
  Bachillerato, con los elementos dentro).
- `elementos`: `id` (letra inicial y luego letras, cifras o `_`, 16 como mucho), `nombre`, `peso`
  (0 a 100, todos suman 100) y `codigo` opcional.
- `criterios` (opcional en cada elemento): `{id, nombre, peso?, codigo?}`. Pesos en todos o en
  ninguno, sumando 100. Sin pesos pesan igual y sale `CRITERIOS_SIN_PESO`. Los ids no se repiten.
  El código legible («1.1», «RA1.a») va en `codigo`.
- `instrumentos` (opcional): casillas manuales de lo que no está en el aula, `{id, nombre,
  seccion, evalua}`. Ver §3.
- `evaluaciones`: `nombre`, `secciones` (números o nombres de sección) y `cerrada` (true o false).
  Con la final por evaluaciones, cada una lleva `peso` (suman 100).
- `final`: `de` (`elementos` o `evaluaciones`) y `tope` (solo con `de: elementos`):
  `si_alguno_menor_que` (mayor que 0 y hasta 10) y `maximo` (de 0 a 10, sin llegar).

Lo que el esquema no expresa (redondeos, actitud, recuperaciones, otros pesos dentro de una
evaluación) **se lo dices al docente y no lo fuerzas**. Tampoco hay competencias clave,
descriptores ni las «competencias» de Moodle.

## 3. Las actividades: `evalua`

Cada tarea, cuestionario o H5P declara con qué elementos o criterios se evalúa y con qué peso:
`evalua: {RA1: 40, RA3: 25}` (de 0 a 100). La actividad real queda en el primer elemento de
`evalua`; en los demás hay una copia que refleja su nota. Sin `evalua`, no entra en el calificador.
Una página o una etiqueta no tienen nota: con `evalua` dan `EVALUA_NO_CALIFICABLE`.

- Si el elemento tiene criterios, `evalua` nombra sus criterios (`CE1_1`, no `CE1`). Nombrar el
  elemento da `ELEMENTO_CON_CRITERIOS`. Los pesos de lo que evalúa cada criterio suman 100.
- **Casillas manuales** (`instrumentos`): tiza crea la casilla (sobre 10) en su primer criterio y
  copias en los demás. La nota la pone el docente a mano; tiza nunca la toca ni cambia su máximo.
  Un instrumento tiene una sola nota, que va a todos sus criterios. Quitar uno con notas lo deja
  con peso 0 (`ELEMENTO_CON_NOTAS_QUITADO`).

## 4. Cómo se ve la nota

- Todos los totales se ven en **porcentaje** (p. ej. «RA1: 40 %»).
- La nota sale en cadena: instrumento → criterio → competencia (o resultado) → final, con la nota
  visible en cada nivel. En la vista por evaluaciones, la misma cadena dentro de cada evaluación.
  El tope sigue siendo por elemento.
- Solo con tope, tiza monta además «Notas (sobre 10)».
- **Límite del tope**: un elemento sin ninguna nota cuenta como 0 en la fórmula. A mitad de curso,
  la final puede salir topada aunque el alumnado vaya bien. Díselo al docente en ese punto.
- Con tope, el total del curso lleva una fórmula y Moodle deja desmarcado «solo calificaciones no
  vacías». Es inocuo mientras haya fórmula.

## 5. Si el aula ya tiene un calificador

- Lo que tiza monta va a «Calificador de tiza». Con uno anterior, ese grupo tiene peso 0 en el
  total del curso, que **sigue siendo el del docente**: tiza no lo toca. Díselo.
- Antes de sacar una actividad de una categoría ajena, tiza **bloquea** el total de esa categoría
  si tiene notas (`CALIFICADOR_BLOQUEAR`). Nunca desbloquea: lo hace el docente en el aula.
- Lo que el docente cambió a mano no se pisa: sale como `CAMBIADO_A_MANO` y decide él. Si
  `BLOQUEO_FALLIDO`, vuelve a intentarlo; si se repite, que el docente mire el aula.
- Un elemento fuera del esquema con notas se queda con peso 0 (`ELEMENTO_CON_NOTAS_QUITADO`).

## 6. Cerrar una evaluación

Poner `cerrada: true` y volver a montar: tiza la completa y la bloquea. Dentro de una evaluación
bloqueada nada se crea, cambia, mueve ni borra (`EVALUACION_CERRADA_EN_EL_AULA`: ya lo estaba). Una actividad nueva en sus secciones sale como
`ACTIVIDAD_EN_EVALUACION_CERRADA`: no se coloca. **tiza no puede reabrirla**; lo hace el docente a mano.

## 7. Cómo se monta

1. `tiza comprobar calificacion.yaml` (offline) hasta que salga 0. Vale también para `evalua`
   (`EVALUA_INVALIDO`, `EVALUA_NO_CALIFICABLE`).
2. Las actividades tienen que estar publicadas. Una que no lo está sale como `ACTIVIDAD_PENDIENTE`
   (no es un error): vuelve a montar cuando lo esté.
3. `tiza calificador calificacion.yaml --en pruebas`: sin pregunta, gasta uno del cupo de la sesión.
4. `tiza calificador calificacion.yaml --en real`: el docente confirma `[s/N]` curso por curso.

Lánzalo en segundo plano o con el mayor tiempo de espera (hasta una hora; un curso grande la
primera vez pasa de 10 minutos). Si te lo corta, vuelve a lanzarlo. Sin sesión, `SIN_SESION`: pide
`tiza empezar`.

## 8. Lo que tiza no hace

- **No lee ni escribe notas** del alumnado. Solo sabe si un elemento tiene notas o no. No pidas
  ni muestres notas de nadie. No desbloquea nada.
- **No admitido**: cambiar `organizacion` o `final.de` de un calificador ya montado ni usar
  escalas (solo notas numéricas). Díselo al docente.
- Con más de 500 ficheros `.md` o `.html` en la carpeta, `CARPETA_DEMASIADO_GRANDE`: saca los que
  no sean de este curso.
- Si dos actividades del mismo tipo y nombre apuntan al mismo sitio (`ACTIVIDAD_AMBIGUA`), no
  adivines cuál es: el docente borra o renombra una en el aula.
- `ESQUEMA_INVALIDO`, `PESOS_NO_SUMAN_100`, `ID_REPETIDO`, `SECCION_REPETIDA`,
  `TOPE_SIN_ELEMENTOS` y `ESQUEMA_FUERA_DE_CARPETA` dicen la ruta y la línea: corrige y vuelve a
  comprobar. `EVALUA_INVALIDO` es un `evalua` mal escrito; `ELEMENTO_DESCONOCIDO` nombra un
  elemento o criterio que no está en el esquema; `SECCION_SIN_EVALUACION` pone una actividad en
  una sección sin evaluación.
- `ELEMENTO_CON_CRITERIOS`: un `evalua` nombra un elemento con criterios; corrígelo con sus
  criterios. `CRITERIOS_SIN_PESO` es un aviso: tiza pesa esos criterios igual, y se lo dices al docente.
- Si `.tiza/calificador.json` da `CALIFICADOR_INVALIDO`, no lo edites ni lo borres: pide al
  docente que lo revise. Si se borra, tiza deja de saber qué cambió el docente a mano y podría
  pisarlo.
