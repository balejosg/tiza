# Guía: informar al alumnado de cómo se le evalúa

Se usa cuando el docente pide una página de inicio de curso para que el alumnado y las familias
sepan cómo se evalúa la materia. Es una página corriente: tiza no genera el texto; lo escribes tú
a partir de la programación y del mapa de cobertura, sin inventar criterios, pesos ni
recuperaciones.

## 1. De dónde sale

- De `.tiza/cobertura.json`, que deja `tiza comprobar calificacion.yaml`: criterio, instrumento,
  actividad, evaluación, peso y regla. Si no existe o es viejo, pide al docente que vuelva a
  comprobar el esquema antes de escribir.
- De la programación (`tiza leer` y `tiza normativa`), para las competencias específicas o los
  resultados de aprendizaje, los criterios y los contenidos.
- De la normativa. En ESO, la obligación de informar al inicio de la actividad lectiva (competencias
  específicas, criterios de evaluación y calificación, contenidos y procedimientos de recuperación
  y apoyo) se atribuye a la Orden 1712/2023, art. 45.5, y al Decreto 65/2022, art. 19.2, pero esos
  artículos **no están en `tiza normativa`**: no los cites sin ver su texto (pide al docente el PDF
  o la programación que los recoja). En Bachillerato y FP, busca la norma equivalente con `tiza
  normativa` (`norma`, `programacion`, `ficha`). No cites nunca un artículo de memoria.

## 2. Qué lleva la página

1. **Qué se evalúa**: las competencias específicas o resultados de aprendizaje, con sus criterios.
   En FP habla de «resultado de aprendizaje» y «criterio», no de «competencia».
2. **Cómo cuenta**: una tabla por criterio con el instrumento (tarea, cuestionario, H5P, casilla
   manual), la evaluación en que se trabaja y el peso normalizado. Si la regla no es la media,
   dilo en una frase: mediana, más alta o progresiva.
3. **Cómo se recupera**: qué actividades recuperan qué evaluación y con qué regla; si una
   recuperación solo cuenta en la final o no cambia una evaluación cerrada, se dice.
4. **Dónde verá su nivel**: en las actividades, en las casillas manuales y en los resultados por
   criterio. **No prometas totales ni notas calculadas**: tiza las crea ocultas al alumnado.
   Si el centro enseña un total, lo decide el docente en el aula, no esta página.
5. **Apoyo**: los procedimientos de apoyo previstos en la programación, sin datos de ningún
   alumno.

No copies la programación entera ni inventes una tabla que no salga del mapa. Frases cortas,
lenguaje del curso y ejemplos de lo que se pedirá en una tarea; nada de códigos internos de tiza
(`TZ_`, `cmid`, ids de Moodle).

## 3. Cómo se publica

1. Escribe `00-como-se-evalua.md` con `tipo: pagina`, `nombre` claro y `seccion: 0` (o la de
   inicio que use el docente). Sigue `guias/estilo.md` para el texto y `docs/formato.md` para la
   cabecera.
2. `tiza comprobar 00-como-se-evalua.md` hasta que salga bien; enseña la vista previa al docente.
3. Si le encaja, se publica con `tiza publicar` por la sesión del docente. Tú no entras en el
   aula.
4. Después de cambiar el esquema o las actividades, vuelve a comprobar y actualiza la página si
   cambió lo que cuenta.

El ejemplo `ejemplos/como-se-evalua.md` muestra el tono y la tabla; adáptalo a la etapa y a la
programación del docente.
