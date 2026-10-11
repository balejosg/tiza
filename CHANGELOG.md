# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Mientras la versión mayor sea 0, un cambio de versión menor puede romper algo:
se avisa aquí con **Cambia**.

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
