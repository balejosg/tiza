# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Mientras la versión mayor sea 0, un cambio de versión menor puede romper algo:
se avisa aquí con **Cambia**.

## 0.20.1 — 2026-10-16

### Corregido
- La ventana de entrada ahora se abre: el hijo exigía una terminal en stderr y `tiza` se la
  quitaba al capturarla, así que siempre caía a pedir la contraseña.
- La ventana se da por terminada en `/my` y todo lo que cuelga de él (con el panel
  desactivado, Moodle vuelve a `/my/courses.php`) en vez de esperar hasta el límite.
- Se aceptan las cookies del dominio padre del aula (`sessioncookiedomain`), por
  coincidencia de dominio; la tubería lleva el dominio de cada cookie.
- El resultado de la ventana va por un canal propio: lo que escriban pywebview o el motor ya
  no lo estropea. El título de la ventana enseña el servidor que se está viendo.

### Añadido
- Al terminar, `tiza` cierra la sesión del aula (`Moodle.cerrar`, `publicar.cerrar_aula`,
  `publicar.sesion_del_aula`): la cookie deja de valer. Vale con contraseña y con ventana,
  en `tiza sesion` y en `estructura`, `publicar`, `ordenar` y `autoprueba` directos.

## 0.20.0 — 2026-10-11

### Cambia
- La entrada al aula pasa a ser una ventana con la página de login del aula (Windows y
  macOS): el docente escribe la contraseña allí, tiza no la ve y solo recoge las cookies
  de sesión del servidor del aula. Sin ventana (Linux, sin WebView2, `--sin-ventana` o si
  falla), se pide la contraseña en la terminal como hasta ahora.
- `tiza.sesion.Presencia.pedir_password` se sustituye por `acreditar(url, usuario)`, que
  devuelve `publicar.Contrasena`, `publicar.Cookies` o `None`.
- Se retira `tiza-ventana` (la ventana de sesión con cursos y confirmaciones): esas
  preguntas siguen en la terminal.
- Los instaladores y `tiza actualizar` instalan el extra `ventana` en Windows y macOS
  (con caída a la instalación sin él).

### Añadido
- `--sin-ventana` en `tiza empezar` y `tiza sesion`.
- `publicar.autenticar_con_cookies` y `publicar.autenticar_con`.

## 0.19.1 — 2026-10-11

### Añadido
- Documentación de lanzamiento: `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`,
  plantillas de issue y `docs/proteccion-de-datos.md` (para coordinadores TIC y DPD).

### Corregido
- `primeros-pasos.md` menciona las actividades H5P; la versión de ruff coincide
  con la del CI.

## 0.19.0 — 2026-10-11

### Añadido
- `tiza ordenar <md>… --en pruebas|real` y `agente.ordenar`: dejan las
  actividades en ese orden dentro de su sección sin mover nada más.
- Cambiar `seccion:` en el `.md` y publicar **mueve** la actividad (mismo cmid,
  visibilidad, intentos y restricciones) en vez de duplicarla.
- La autoprueba comprueba ordenar y mover entre secciones.
- Protocolo del buzón 5.

### Corregido
- La finalización se lee del botón de opción marcado, no del primero.

## 0.18.0 — 2026-10-11

### Añadido
- Preguntas de emparejamiento en los cuestionarios.
- Imágenes locales dentro de las preguntas (con texto alternativo obligatorio).

## 0.17.0 — 2026-10-11

### Añadido
- Avisos de fórmulas y comprobación de que el aula las dibuja
  (`FORMULAS_NO_DIBUJADAS`); las fórmulas se rechazan en H5P (`FORMULA_EN_H5P`).

## 0.16.1 — 2026-10-10

### Añadido
- Fórmulas LaTeX en el contenido y ejemplo de unidad completa de seis piezas.

### Corregido
- Los iframes de Educaplay se publican (el dominio era un resto del renombrado).

## 0.16.0 — 2026-10-10

### Añadido
- Finalización de actividades y restricciones de acceso en el frontmatter
  (itinerario).

## 0.15.0 — 2026-10-10

### Añadido
- Publicar la misma carpeta en varios cursos reales, con confirmación por curso.

## 0.14.0 — 2026-10-10

### Añadido
- Calendario escolar (`calendario.toml`) con avisos de festivos y fines de semana.
- Fechas antes y después en la confirmación y `publicar --solo-fechas`.

## 0.13.0 — 2026-10-08

### Añadido
- Actividades H5P: generadas desde el `.md` (huecos, arrastrar palabras, marcar
  palabras y tarjetas) y paquetes `.h5p` subidos sin librerías ni JavaScript.
- La autoprueba cubre H5P.

## 0.12.0 — 2026-10-08

### Añadido
- La app de GitHub Copilot como agente de tiza (`tiza aislar` y `tiza revisar`).
- `SIN_SESION` avisa cuando el agente trabaja en un worktree.

### Corregido
- El instalador de uv ya no cierra la ventana de PowerShell; los instaladores
  no necesitan `git`.

## 0.11.0 — 2026-10-07

### Cambia
- Los cursos viven solo en el `tiza.toml` de cada carpeta; la configuración
  global guarda únicamente la URL del aula y el usuario.

## 0.10.1 — 2026-10-07

### Corregido
- La URL del aula funciona aunque redirija a la barra final por http.
- La ventana se instala desde GitHub y `tiza actualizar` la conserva.

## 0.10.0 — 2026-10-07

Primera versión pública: páginas, etiquetas, tareas y cuestionarios; sesión del
docente con buzón de ficheros; puerta de real; filtro de HTML en lista blanca;
`tiza aislar`.
