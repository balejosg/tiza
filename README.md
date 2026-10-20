# tiza

**Pide a tu asistente de IA el material de clase y publícalo en tu aula Moodle,
revisándolo tú antes.**

`tiza` conecta un agente de IA (Claude Code, Codex, opencode o la app de GitHub
Copilot) con tu aula virtual Moodle. El agente prepara páginas, tareas,
cuestionarios autocorregibles y actividades H5P; tú los revisas y decides qué
llega a tu alumnado. Funciona en Windows, macOS y Linux.

> Proyecto independiente y no oficial, sin relación con Moodle ni con ninguna
> administración educativa. Úsalo respetando las normas de tu centro
> ([aviso completo](#aviso-y-licencia)).

## Qué puedes pedirle

- *«Prepárame el tema 3 de fracciones para dos semanas.»* El agente te pregunta
  lo que le falta y te propone una secuencia. Cuando le das el visto bueno,
  prepara una presentación, dos páginas de teoría, una práctica H5P, un test y
  una tarea, encadenados para que se abran en orden.
- *«Hazme un test de repaso de 10 preguntas con imágenes.»* Las preguntas pueden
  ser de opción múltiple, verdadero o falso, respuesta corta, numéricas o de
  emparejar. Se corrigen solas.
- *«Retrasa una semana las entregas del tema 2.»* Solo cambian las fechas. El
  contenido y los intentos del alumnado quedan como estaban.
- *«Pon esta tarea en el tema 4 y ordénalo: primero la teoría, luego el test.»*

Si das la misma asignatura en varios grupos, una sola petición llega a todos tus
cursos.

## Del currículo a tu aula virtual

El decreto de tu materia, tu programación didáctica y tu aula virtual suelen ser
tres mundos aparte. Con el agente puedes conectarlos en una conversación. Solo
tienes que dejar en la carpeta de la asignatura los documentos que ya tienes: el
decreto de tu comunidad o el real decreto de enseñanzas mínimas, y tu
programación, sin datos del alumnado.

- *«Lee la programación y el decreto y prepárame la situación de aprendizaje del
  segundo trimestre.»* El agente te propone la secuencia de actividades e indica
  de qué competencias específicas, criterios de evaluación y saberes básicos sale
  cada una, citando el documento y el apartado. Antes de escribir nada, te
  pregunta lo que le falta: sesiones, fechas o producto final.
- *«En la tarea final, pon los criterios que evalúa y cuatro niveles de
  logro.»* Tu alumnado ve en el aula qué se le pide y cómo se valora, con el
  lenguaje del currículo traducido a su edad.
- *«¿Qué criterios de mi programación del primer trimestre aún no tienen ninguna
  actividad en esta carpeta?»* El agente cruza tu programación con lo que ya ha
  preparado y te señala los huecos.
- *«Haz una versión de refuerzo y otra de ampliación de la práctica.»* Son
  actividades distintas, descritas por su contenido y nunca por alumnos
  concretos. Encajan con las medidas de atención a la diversidad de tu
  programación.
- *«Ajusta las fechas de la unidad al calendario escolar.»* Si dejas el
  calendario en la carpeta, `tiza` avisa cuando una fecha cae en festivo o en un
  día sin clase.
- *«Prepárame la programación del curso que viene a partir de la plantilla del
  departamento.»* El agente rellena una copia de tu plantilla en Word, con tus
  estilos y tu encabezado, y te señala lo que de la anterior está desfasado.
- *«Revisa mi programación antigua con la normativa y con mi aula.»* El agente
  contrasta las tres cosas, con una copia del curso que confirmas tú, y te
  deja una lista de propuestas para aceptar por número.

El agente trabaja con tus documentos y no se inventa criterios. Aun así, la
última palabra es tuya: revisa que lo citado coincide con el decreto y con tu
programación antes de publicarlo en el curso real. `tiza` comprueba el formato y
la seguridad de lo que se publica, pero no comprueba el currículo. Tienes una
conversación de ejemplo, de principio a fin, en
[Del currículo al aula](docs/del-curriculo-al-aula.md).

## Cómo funciona

1. **Abres tu aula.** En la carpeta de la asignatura escribes `tiza empezar` y
   entras con tu usuario, como siempre. Esa ventana se queda abierta mientras
   trabajas.
2. **El agente prepara el contenido** y lo publica en tu curso de pruebas, donde
   lo ves igual que lo verá tu alumnado.
3. **Tú confirmas.** Cuando te guste, se lo pides para el curso real: `tiza` te
   enseña qué se publica, dónde y con qué fechas, y solo sigue si respondes `s`.

¿No tienes curso de pruebas? También puedes trabajar: en el curso real se
publica oculto hasta que tú decidas mostrarlo.

## Tú mantienes el control

- **El agente nunca ve tu contraseña** ni entra en el aula: solo deja peticiones
  que atiende la sesión que tú abres, y que se cierra cuando quieras.
- **Nada llega al curso real sin tu confirmación.**
- **Solo se publica contenido seguro**: nada de scripts ni formularios, y los
  vídeos y actividades incrustados solo pueden venir de servicios conocidos
  (YouTube, Genially, Wordwall, GeoGebra…).
- **No necesita datos de tu alumnado.** Nunca escribas nombres, notas ni datos
  de salud de tus alumnos en lo que lee el agente.

Los detalles están en [Cómo protege tiza tu aula](docs/seguridad.md). Si tu
centro te pide información sobre protección de datos, pásale
[este resumen](docs/proteccion-de-datos.md).

## Qué necesitas

- **Un curso en tu aula Moodle en el que seas profesor.** Si además tienes uno
  vacío de pruebas, mejor. Si no lo tienes, puedes pedírselo a quien administra
  el aula de tu centro.
- **Un agente de IA que trabaje en la terminal.** Claude Code, Codex y Copilot
  necesitan una suscripción o una clave de pago. opencode es gratuito, pero hay
  que conectarlo a un proveedor de modelos.
- **Saber abrir una terminal y pegar una línea.** Nada más.

## Empezar

Pega la línea de tu sistema en una terminal. Instala `tiza` y lo que necesita:

```bash
# macOS / Linux
curl -LsSf https://raw.githubusercontent.com/balejosg/tiza/main/install.sh | sh
```

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/balejosg/tiza/main/install.ps1 | iex
```

Después, en la carpeta de tu asignatura:

```bash
tiza empezar
```

La guía [Primeros pasos](docs/primeros-pasos.md) te acompaña en tu primer día,
paso a paso. Si prefieres que te guíe tu propio agente, pásale
[INSTALAR_CON_AGENTE.md](INSTALAR_CON_AGENTE.md).

Los instaladores instalan la versión `v0.24.1`. Las opciones de instalación, la
actualización y la desinstalación están en la [guía de uso](docs/guia.md#instalación-opciones).

## Más información

- [Primeros pasos](docs/primeros-pasos.md): instalar y tu primer día.
- [Guía de uso](docs/guia.md): todos los comandos, varios cursos, calendario
  escolar, cambio de fechas y orden de las actividades.
- [Formato de los ficheros](docs/formato.md): lo que escribe el agente, por si
  quieres revisarlo o escribirlo tú.
- [Del currículo al aula](docs/del-curriculo-al-aula.md): una conversación de
  ejemplo, del decreto y la programación a la unidad publicada.
- [Ejemplos](ejemplos/): una unidad completa y un ejemplo de cada tipo.
- [Cómo protege tiza tu aula](docs/seguridad.md) y [cómo aislar a tu
  agente](docs/aislamiento.md).
- [Protección de datos](docs/proteccion-de-datos.md): para tu coordinador TIC o
  tu Delegación de Protección de Datos.
- ¿Algo falla? Abre una [*issue*](https://github.com/balejosg/tiza/issues) con
  la orden que ejecutaste, tu sistema y el mensaje de error copiado tal cual. No
  adjuntes capturas del aula (pueden salir alumnos) ni tu contraseña.

## Aviso y licencia

Proyecto independiente y no oficial: no está afiliado a Moodle ni a ninguna
administración educativa, y ninguna Delegación de Protección de Datos lo ha
evaluado ni autorizado. Úsalo bajo tu responsabilidad y respetando las normas de
tu centro y del aula virtual que uses. No compartas tu contraseña y no incluyas
datos del alumnado en lo que publicas ni en lo que ve el agente.

La base es [python-moodle](https://pypi.org/project/python-moodle/) (MIT).
Licencia [MIT](LICENSE). Cambios en el [CHANGELOG](CHANGELOG.md); para
colaborar, [CONTRIBUTING.md](CONTRIBUTING.md); vulnerabilidades,
[SECURITY.md](SECURITY.md).
