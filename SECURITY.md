# Seguridad

tiza maneja la contraseña de un aula virtual y publica contenido ante alumnado,
así que los fallos de seguridad se toman en serio.

## Cómo avisar

**No abras una issue pública** para una vulnerabilidad. Usa el aviso privado de
GitHub: pestaña *Security* › *Report a vulnerability* de
<https://github.com/balejosg/tiza>.

Cuéntanos qué has visto, cómo reproducirlo y qué versión de tiza usas
(`tiza --version`). No adjuntes contraseñas, capturas del aula ni datos del
alumnado.

## Qué consideramos una vulnerabilidad

- Que el agente pueda ver o usar la contraseña, o conectarse al aula por su cuenta.
- Que se publique en el curso real algo que el docente no ha confirmado.
- Que llegue al aula HTML, CSS o JavaScript fuera de la lista blanca de
  `src/tiza/filtro.py`.
- Que la contraseña o una petición de sesión salga hacia un servidor distinto
  del aula configurada.
- Que el agente lea o escriba fuera de la carpeta de la asignatura a través de
  tiza.

El modelo de seguridad y sus límites están en el [README](README.md#medidas-de-diseño)
y en [docs/proteccion-de-datos.md](docs/proteccion-de-datos.md). Son medidas para
reducir riesgos, no garantías absolutas.

## Versiones con soporte

Solo la última versión publicada.
