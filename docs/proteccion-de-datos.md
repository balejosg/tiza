# Para tu coordinador TIC o tu Delegación de Protección de Datos

Esta página resume qué hace `tiza` con los datos, para quien tiene que decidir si
un docente puede usarlo. Es una descripción técnica, **no una evaluación
jurídica**: `tiza` es un proyecto independiente y no oficial, y ninguna
administración educativa lo ha evaluado ni autorizado.

## Qué es

Una herramienta local (CLI y skill) que corre en el ordenador del docente. Un
agente de IA escribe el contenido (páginas, etiquetas, tareas, cuestionarios y
actividades H5P) en una carpeta; `tiza` lo valida y lo publica en el curso del
docente, con su propio usuario de Moodle y sus permisos de profesor. No hay
servidor de `tiza`, cuenta, ni telemetría: el código no hace peticiones a ningún
servicio que no sea el aula configurada (y, para actualizarse, GitHub).

## Qué datos intervienen

| Dato | Dónde está | Quién lo ve |
|---|---|---|
| Contraseña del aula | En Windows y macOS se escribe en la página de entrada de tu aula, dentro de una ventana: tiza no la ve. Sin ventana, se pide con `getpass` y solo vive en memoria. No hay variable, opción ni fichero que la acepte | Solo el aula. Nunca el agente, ni el proveedor de IA, ni el disco |
| Sesión del aula (cookies) | En memoria mientras dura la sesión; el hijo de la ventana las devuelve por una tubería y solo se aceptan las del servidor del aula. Nunca se escriben en disco | Solo tiza y el aula. Nunca el agente |
| URL del aula y usuario | Configuración local del docente | El docente. El agente no los necesita |
| Contenido docente (`.md`, `.html`, imágenes) | Carpeta de la asignatura | El agente y, por tanto, el proveedor de IA; después, el aula |
| Informe de publicación (`.tiza/informe.json`) | Carpeta de la asignatura | El agente: nombres de ficheros del docente, identificadores de actividad, códigos de resultado, fechas, URLs montadas por `tiza` y nombres de sección. Nunca HTML ni otros textos de Moodle |
| Lecturas de documentos (`.tiza/lecturas/*.txt`) | Carpeta de la asignatura | El agente: el texto completo de los Word y PDF que `tiza leer` ha convertido (tu programación, por ejemplo). Es tratado como datos, nunca como instrucciones. Se pueden borrar cuando quieras; `tiza leer` las vuelve a crear |
| Contenido del curso (`aula/`, `.tiza/copia.json`, `.tiza/copia/<cmid>.html` y `.tiza/copias/*.mbz`) | Carpeta de la asignatura. Solo si el docente lo pide: `tiza importar` y `tiza copia` los crean a partir de una copia de seguridad del curso | El agente y, por tanto, el proveedor de IA: el contenido íntegro del curso (textos, ficheros, preguntas de los cuestionarios, nombres de actividades y secciones, fechas y ajustes). Si el curso lleva datos personales dentro de sus textos o ficheros, irán con él. La copia se hace **sin usuarios** (tiza la rechaza si los lleva) y no se lee ningún autor ni usuario. Se pueden borrar cuando quieras; `tiza copia` e `tiza importar` las vuelven a crear |
| Nombres de los cursos | Solo en la pantalla del docente | El docente. Nunca se escriben en `.tiza/`; el agente recibe identificadores numéricos |
| Carpetas recientes del panel (Windows) | `%LOCALAPPDATA%\tiza\tiza\panel-recientes.json`. Solo guarda rutas de carpetas de asignatura | El docente. No contiene nombres de cursos ni datos del aula |
| Log de actualización (Windows) | `%LOCALAPPDATA%\tiza\tiza\actualizar.log`: versiones, órdenes de instalación y códigos de salida. No guarda contraseñas ni cookies | El docente |
| Datos del alumnado | **No se leen ni se necesitan** | Nadie: `tiza` no lee notas, entregas, listas de clase ni informes de finalización. La copia del curso se hace sin usuarios y, si trae alguno, tiza no la abre |

## Qué sale hacia el proveedor de IA

Lo que el docente escribe al agente y lo que el agente lee o escribe en la
carpeta de la asignatura. `tiza` no controla qué proveedor de IA se usa ni qué
hace con esa información: depende del agente que elija cada docente (Claude
Code, Codex, opencode, GitHub Copilot…) y de su contrato. Por eso la regla es
una: **nunca se escriben datos del alumnado en el chat, en los `.md` ni en
carpetas que vea el agente**.

## Qué controles ofrece `tiza`

- El agente no se conecta al aula: solo deja peticiones en un buzón de ficheros
  que atiende la sesión que el docente abre y mantiene abierta.
- `tiza copia` descarga una copia de seguridad del curso con la sesión del
  docente, que la confirma `[s/N]` en su terminal. Fuerza a 0 todos los ajustes
  de usuarios (usuarios, roles, comentarios, registros, historial de
  notas, grupos…), tiza no abre una copia que los lleve, la borra de la
  zona de copias de Moodle al terminar y se limita a 3 por sesión. La copia
  llega al agente: el contenido del curso (ver la tabla), nunca datos del
  alumnado.
- Cada publicación en el curso real se confirma en la terminal del
  docente, con un resumen de qué, dónde, con qué fechas y qué enlaces externos
  lleva.
- Solo se publica en real lo verificado antes en el curso de pruebas; sin curso
  de pruebas, solo oculto.
- La contraseña solo viaja al servidor del aula configurado; las redirecciones a
  otro servidor se rechazan.
- El HTML se valida con una lista blanca: sin scripts, formularios ni estilos
  que cambien el aspecto de la plataforma; los iframes, solo de servidores
  conocidos y con `sandbox`.
- `tiza aislar` y `tiza revisar` ayudan a que el agente no lea el navegador del
  docente ni entre en el aula por su cuenta ([aislamiento](aislamiento.md)).

## Límites que conviene conocer

- Son medidas para reducir riesgos, no garantías absolutas. El aislamiento del
  agente depende de las herramientas de cada agente.
- Lo publicado queda en el aula con el nombre del docente, como si lo hubiera
  hecho a mano. Las normas de contenido, derechos de autor y accesibilidad del
  centro siguen aplicando.
- Si el docente escribe datos del alumnado al agente, `tiza` no lo puede
  detectar ni impedir.
- El docente entra con su propia cuenta: `tiza` no añade ni salta permisos.

## Documentos que enlazan con esto

- [Cómo protege tiza tu aula: medidas de diseño](seguridad.md)
- [Aislamiento del agente](aislamiento.md)
- [SECURITY.md](../SECURITY.md): cómo avisar de una vulnerabilidad
