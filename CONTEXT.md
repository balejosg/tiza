# Contexto de dominio de tiza

Vocabulario del dominio para quien lee o cambia el código. Las reglas de trabajo están en
`AGENTS.md`; esto solo fija qué significa cada palabra.

## El aula

- **Estructura (del aula)**: las secciones de un curso con sus actividades, tal como tiza las lee
  del aula. Nace validada en la seam del aula (`AulaVirtual.estructura`): lo que no tiene la forma
  esperada se rechaza ahí, una vez, y no en cada consulta. Es inmutable. `estructura.json` guarda
  la misma estructura sin las actividades, para el agente.
- **Sección**: un apartado del curso (número, nombre, id). Es el mismo tipo en el aula y en
  `estructura.json`; en el segundo, sin actividades. Se busca por número o por nombre (sin
  distinguir mayúsculas y con el nombre saneado).
- **Actividad**: lo que hay en una sección (cmid, nombre, tipo). En el código y en Moodle se llama
  *módulo* (`modulo`, `cmid`); en la prosa, actividad, para no confundirlo con un módulo de Python.
- **Localización**: la respuesta a «¿qué actividad del aula es la de este documento?». Es la única
  búsqueda de tiza y es pura: origen, luego registro de lo publicado, luego tipo y nombre en su
  sección, luego en otra. Cuando no puede decidir no lanza: lleva un **problema** con su código
  (`ORIGEN_NO_ENCONTRADO`, `ACTIVIDAD_AMBIGUA`) y es quien escribe en el aula el que lo convierte
  en error.

## Lo que tiza recuerda de lo que dejó en el aula

- **Registro (de lo publicado)**: `publicados.json`, por curso: qué actividad (cmid, tipo) es cada
  fichero, para hallarla aunque se renombre o cambie de sección.
- **Huella**: sha256 del formulario de la actividad tal como lo dejó tiza al publicar (en el
  registro) o tal como vino en la copia del aula (en `copia.json`, para lo que tiene `origen`). Es
  aquello con lo que se compara el aula para saber si el docente la retocó. Solo sale el sha256:
  nunca el formulario.
- **Marca**: sha256 del fichero del docente en el momento en que tiza vio la actividad cambiada en el
  aula y le dio su versión para juntar. Mientras el fichero siga así, los cambios están **sin
  juntar** y no se publica. La marca ilegible bloquea siempre.
- **Base**: el material para juntar a tres bandas: el fichero fuente y el HTML que tiza envió, en
  `publicados/`. No se usa para comparar (eso es la huella). Si la actividad se recrea (cmid
  nuevo), la base vieja se olvida.
- **Retoque (a mano)**: un cambio que hizo el docente en el aula, fuera de tiza, sobre algo que tiza
  publicó o importó. Lo ilegible cuenta como retocado, para no pisar a ciegas. Con su sí, el
  docente puede **sobrescribir** un retoque. Al publicar entero, lo publicado pasa a ser la huella
  nueva; con `--solo-fechas` no se renueva (el texto del aula no se pisó) y el retoque sigue
  contando la próxima vez.
- **Vigilancia (de lo publicado)**: el módulo que responde, por documento y curso, si hay retoque
  (solo en cursos reales) y si hay que rechazarlo antes de confirmar, y que renueva registro,
  huella, marca y base tras publicar. Tiene dos almacenes detrás de la misma seam: el registro y
  `copia.json`. Los formatos de disco no cambian.
- **Actividad vigilada**: lo que la vigilancia entrega a publicar para un documento: con el
  formulario ya leído dice si hay retoque y, en solo-fechas, cuál es la huella nueva tras verificar.
  No hay actividad vigilada en pruebas sin `origen` ni cuando el docente decidió sobrescribir.
- **Anotar (lo publicado)**: lo que la vigilancia escribe tras publicar, en este orden: la huella de
  `copia.json`, la entrada del registro (con su marca) y la base. Si algo no se puede guardar, la
  publicación sigue siendo buena y lo dice con `HUELLA_NO_GUARDADA`, `REGISTRO_NO_GUARDADO` o
  `BASE_NO_GUARDADA`; la base no lleva aviso al docente.

## El recorrido por cursos

- **Recorrido (por cursos)**: lo que hace un comando que va a varios cursos. En pruebas, una visita
  con cupo y aviso; en real, una visita por curso real en el orden de `tiza.toml`, con una
  confirmación por curso y un informe con lo que pasó en cada uno. Siempre lo rigen las mismas
  reglas, y cada comando solo aporta su **trabajo**.
- **Trabajo (de un comando)**: lo que `publicar`, `ordenar` y `calificador` hacen en un curso y lo que
  aportan al recorrido: cuánto gastan del cupo, qué comprueban antes, qué anuncian en pruebas y
  qué preparan una vez.
- **Turno**: la visita del recorrido a un curso real: id, posición, total, nombre llano y la única vía
  para preguntar al docente.
- **Curso omitido**: el curso real que no se toca por decisión del docente: lo descartó antes
  (`omitidos`) o dijo que no a su confirmación. Sale como `CURSO_OMITIDO` y no corta los siguientes;
  si todos quedan omitidos, el informe es `ABORTADO`.
- **Petición vigente / retirada**: la petición del agente en el buzón es vigente mientras sigue allí;
  si el agente la retira, desde ese momento nada se escribe en el aula. Se comprueba antes de cada
  curso salvo el primero y tras cada «sí» del docente. En la terminal directa no hay nada que
  retirar.
- **Corte**: parar el recorrido en un curso para no tocar los siguientes. Cortan los fallos y la
  retirada; no corta que el docente diga que no (ni, en publicar, el «no» a sobrescribir).
