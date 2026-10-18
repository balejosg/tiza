# Cómo protege `tiza` tu aula

Este documento detalla las medidas de diseño de `tiza`. Si solo quieres saber
cómo empezar, lee [primeros-pasos.md](primeros-pasos.md); si tu centro o tu
Delegación de Protección de Datos te pide un resumen, pásale
[proteccion-de-datos.md](proteccion-de-datos.md).

## Las dos ideas de partida

1. **El agente no toca la sesión del aula**: escribe y comprueba el contenido;
   para publicar deja una petición en un buzón de ficheros que atiende la sesión
   que el docente abre con `tiza sesion` (o `tiza empezar`).
2. **Del aula solo sale lo mínimo hacia el agente**: el informe que lee solo
   contiene nombres de *tus* ficheros, cmid, códigos de resultado, fechas, URLs
   montadas por la herramienta y los nombres de las secciones. Nunca HTML ni
   otros textos de Moodle.

La base es [python-moodle](https://pypi.org/project/python-moodle/) (MIT), que
crea y edita actividades con la misma sesión web que usas en el navegador.

## Medidas de diseño

Son medidas para reducir riesgos, no garantías absolutas. Si tu centro o tu
Delegación de Protección de Datos te pide un resumen, pásale
[proteccion-de-datos.md](proteccion-de-datos.md).

- **`tiza normativa` es offline**: solo lee los datos que trae el paquete, no usa la red ni el aula, y su salida pasa por un esquema cerrado como el resto de lo que ve el agente.
- **Sin secretos persistentes**: en Windows y macOS (y en Linux, si la instalas), `tiza` abre una ventana con la
  página de entrada de tu aula y la contraseña la escribes allí: `tiza` no la ve y
  solo recoge las cookies de sesión del servidor del aula (las de cualquier otro
  dominio, como un proveedor de identidad, se descartan). Sin ventana (sin escritorio,
  como en una sesión por SSH; sin WebView2 en Windows; sin motor en Linux; con
  `--sin-ventana`; o si la ventana falla), la contraseña se pide con `getpass` una vez. En
  ningún caso hay variable de entorno, opción ni fichero que la acepte, y la sesión
  vive en memoria y se descarta al cerrar `tiza sesion`; además, al terminar `tiza`
  cierra la sesión en el aula, así que la cookie deja de valer (cierra la sesión con Ctrl+C: si cierras
  la consola con la X, `tiza` no llega a limpiar y la sesión del aula sigue abierta hasta que
  caduque). La ventana solo la abre
  `tiza` con una terminal delante: un agente sin terminal no puede lanzarla.
- **Aulas con SSO o doble factor**: como el login ocurre en la página real de tu aula,
  sirve cualquier forma de entrar que tu aula admita en el navegador (proveedor de
  identidad, código de una app…). Medido con contraseña y con el código TOTP de Moodle
  en Windows, y con contraseña en Linux (Qt, sin pantalla); un SSO real, macOS y Linux con
  GTK o con pantalla real no se han probado todavía. Si tu aula te pide registrar
  el segundo factor, hazlo antes en tu navegador de siempre: la ventana de `tiza` solo
  cubre la entrada con el factor ya registrado. La ventana se da por terminada al llegar
  a «Área personal» o «Mis cursos»; si tu aula te lleva antes a una página obligatoria
  (política de uso, completar el perfil), acéptala en el navegador una vez.
- **Presencia humana**: el agente solo publica mientras el docente mantiene
  abierta `tiza sesion` en esa carpeta; la sesión caduca sola (se puede ampliar
  respondiendo en la terminal, hasta 8 horas) y puede cerrarse
  con Ctrl+C. Al abrirla se muestran los cursos de destino **por su nombre** y
  se pide confirmación `[s/N]`, y **cada publicación en el curso real se
  confirma** en la terminal del docente.
- **Contraseña solo hacia tu aula**: escribes la URL al configurar (por ejemplo
  `https://aula.ejemplo.org/<centro>`) y queda fijada: se rechazan las URLs que
  `urlsplit` y `requests` leen distinto, y una redirección a otro servidor o
  puerto falla con `URL_REDIRIGE_FUERA`. Se muestra el servidor antes de entrar,
  la contraseña (si se pide en la terminal) se envía una sola vez (sin token móvil) y cada petición de la
  sesión del aula, redirecciones incluidas, se comprueba antes de salir: nada va
  a otro servidor. Los cursos de pruebas y real no pueden coincidir.
- **Puerta de real**: dentro de `tiza sesion`, solo se publica en real lo que
  esa misma sesión ha publicado antes en pruebas (`verificados.json` lo puede
  escribir el agente, así que no se fía de él). La confirmación `[s/N]` lista
  también los enlaces externos del contenido.
- **Sin curso de pruebas**: si falta `pruebas` en `[cursos]`, no hay
  verificación previa ni vista que enseñar. Al abrir la sesión se avisa y se
  pide confirmación (para que la marca `sin_pruebas` no pase en silencio); se
  compensa publicando en real solo **oculto** (la petición debe pedir
  `--oculto`; lo demás se rechaza con `SOLO_OCULTO_SIN_PRUEBAS`) y con una
  confirmación corta: curso, documentos, tipo y secciones nuevas, sin vista
  previa (si un documento ya existe, avisa de que se ocultará si estaba
  visible). Tampoco hay autoprueba (`SIN_CURSO_PRUEBAS`).
- **Salida en lista blanca**: el informe `.tiza/informe.json` pasa por un
  esquema cerrado; las excepciones de python-moodle se reducen a códigos.
- **Pantalla del docente saneada**: los textos que vienen del agente o del aula
  (títulos, secciones, enlaces, nombres de curso) se muestran sin caracteres de
  control, para que nadie pueda reescribir la confirmación. Los nombres de curso
  nunca se escriben en `.tiza/`.
- **Carpeta de trabajo hostil**: lo que `tiza sesion` lee y escribe en `.tiza/`
  se trata como escrito por el agente. No abre FIFO ni sigue enlaces simbólicos,
  no lee peticiones de más de 64 KiB, descarta un JSON anidado en exceso en vez
  de caerse y se niega a usar `.tiza` o `.tiza/buzon` si son enlaces
  (`DIRECTORIO_NO_SEGURO`).
- **Vista previa fiable**: la vista previa de la confirmación en real la escribe
  la sesión en un directorio privado de la caché de tu usuario (permisos 0700),
  no en la carpeta donde escribe el agente, y cada documento tiene la suya (dos
  con el mismo nombre de fichero no se pisan): lo que revisas es lo que se
  publica. La de `tiza comprobar` sigue en `.tiza/preview/`, pero tampoco se
  escribe a través de enlaces simbólicos.
- **Contenido seguro**: el HTML se valida con una lista blanca sobre el árbol que
  construye un navegador (html5lib), y lo que se publica es ese árbol validado.
  Se admiten las etiquetas de texto, listas, tablas, enlaces, imágenes y
  estructura; `style` solo con propiedades de maquetación (sin `position`,
  `url()`, valores negativos…); `class` solo de una lista cerrada de Bootstrap; e
  `<iframe>` solo por `https` desde una lista cerrada de servidores (YouTube,
  Vimeo, Genially, Canva, Wordwall, Educaplay, LearningApps, GeoGebra y PhET),
  que se publican con `sandbox` y, el de YouTube, sin cookies.
  Se rechaza el resto —scripts, formularios, SVG, `<style>`, `<meta>`,
  comentarios, atributos `on*`— y cualquier URL que no sea `http(s)`, una ruta
  local, un ancla, `mailto:` o una imagen `data:` PNG, JPEG, GIF o WebP. La
  confirmación de real lista todas las URL externas y todo lo incrustado.
- **Recursos acotados**: solo se suben ficheros de dentro de la carpeta de la
  asignatura, que no sean ocultos (`.git/config`, `.env`…) ni `tiza.toml`, de
  hasta 200 MB (el `.md` o `.html`, hasta 2 MB). Se comprueba antes de mirar si
  el fichero existe, así que el agente no puede averiguar qué hay fuera de su
  carpeta (`RUTA_FUERA_DE_CARPETA` en los dos casos).
- **Límite en pruebas**: como mucho 50 documentos publicados en pruebas por sesión
  (`LIMITE_PUBLICACIONES`); los recursos se copian una vez y se comprueba su hash,
  así que cambiarlos después de la confirmación da `FICHERO_MODIFICADO`.
- **Respeto al aula**: un único intento de login por ejecución, sin reintentos,
  y peticiones secuenciales con una pausa corta.

El riesgo ajeno a la herramienta (un agente leyendo el perfil del navegador o
Descargas) se cubre con [aislamiento.md](aislamiento.md), con
configuración lista para copiar en Claude Code, Codex y opencode, y la receta
para el sandbox de la app de GitHub Copilot (que se activa a mano por
proyecto). Con Copilot usa una sesión local abierta en la carpeta de la
asignatura: las sesiones en la nube de la app no ven tu `tiza sesion`, y su
«computer use» queda fuera por las mismas reglas.

## Datos del alumnado: regla de oro

**Nunca escribas nombres, notas, datos de salud ni ninguna información de
alumnos en el prompt, en los `.md` ni en carpetas que vea el agente.** Para
publicar, `tiza` no necesita esos datos, y los proveedores de IA no están
autorizados por tu administración educativa para tratarlos. Tampoco hagas
capturas o vídeos de la herramienta donde aparezcan alumnos. Si dudas, consulta
antes con la dirección de tu centro o con la Delegación de Protección de Datos
de tu administración educativa.
