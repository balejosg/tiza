# Primeros pasos con `tiza` (para docentes)

`tiza` deja que un agente de IA te prepare páginas, etiquetas, tareas y cuestionarios y
los publique en tu aula virtual. Tú mantienes el control: el
agente nunca ve tu contraseña y nada llega al curso real sin que lo confirmes.

Esta guía es la versión corta. Los detalles están en el [README](../README.md).

## Antes de empezar: qué necesitas

- **Un ordenador con Windows, macOS o Linux** en el que puedas instalar
  programas, y unos 30 minutos la primera vez.
- **Saber abrir una terminal** (en Windows, «PowerShell»; en macOS, «Terminal»).
  Solo tendrás que pegar un par de órdenes.
- **Un agente de IA que trabaje en la terminal**: Claude Code, Codex, opencode
  o la app de GitHub Copilot. Claude Code, Codex y Copilot necesitan una
  suscripción de pago o una clave de API. opencode es gratuito, pero hay que
  conectarlo a un proveedor de modelos, que también puede ser de pago.
- **Un curso real en el aula virtual en el que seas profesor**, con tu alumnado.
  Si además tienes uno **de pruebas**, vacío, todo se publica primero ahí. Si no
  lo tienes, también puedes trabajar: en real solo se publica oculto y lo
  revisarás en el propio curso. Si quieres un curso de pruebas, pídeselo a quien
  administra el aula virtual de tu centro (normalmente, el coordinador TIC).

## Instalar

1. Abre una terminal y pega la línea de tu sistema:

   ```bash
   # macOS / Linux
   curl -LsSf https://raw.githubusercontent.com/balejosg/tiza/main/install.sh | sh
   ```

   ```powershell
   # Windows (PowerShell)
   irm https://raw.githubusercontent.com/balejosg/tiza/main/install.ps1 | iex
   ```

2. Cierra la terminal y abre otra nueva.
3. Escribe `tiza --help`. Si sale la ayuda, ya está instalado.

## El primer día

1. **Crea una carpeta para la asignatura** (por ejemplo, `Matemáticas 2ºB`).
   Ahí guardará el agente lo que escriba.
2. **Abre la sesión.** En una terminal, entra en esa carpeta y escribe:

   ```bash
   tiza empezar
   ```

   Te irá preguntando, por este orden:
   - la dirección de tu aula virtual y tu usuario;
   - si quieres **aislar** al agente en esta carpeta: responde `s`. Así no
     puede entrar en el aula ni leer tu navegador. Con la app de GitHub
     Copilot, `tiza aislar` no puede escribir su configuración: te dirá qué
     activar en Ajustes › Proyectos › Sandbox y en qué carpeta debe quedar la
     sesión del agente;
   - tu contraseña (solo aquí, nunca en el chat del agente);
   - cuál es tu curso real y, si lo tienes, el de pruebas, por su nombre (puedes
     elegir «No tengo curso de pruebas»: entonces en real solo se publicará
     oculto y la sesión te lo recordará y pedirá confirmarlo cada vez que la
     abras);
   - si tienes curso de pruebas, si quieres pasar la **autoprueba**: responde
     `s`. Publica unas actividades de ejemplo, comprueba que todo funciona y las
     borra. Te la vuelve a ofrecer con cada versión nueva y cada septiembre.

   **Deja esta terminal abierta** mientras trabajes: es la sesión. Dura una
   hora; poco antes de que acabe te pregunta si quieres ampliarla.
3. **Pídele el contenido al agente.** Abre tu agente en la **misma carpeta**,
   en otra terminal, y pídele lo que necesites. Por ejemplo: «Prepara una página
   de repaso de fracciones para la sección Fracciones y publícala en pruebas».
4. **Revísalo en el curso de pruebas** con el enlace «Ver en el aula» que te
   dará el agente. Se publica oculto para el alumnado.
5. **Pásalo al curso real.** Cuando te guste, pídele que lo publique en real.
   En la terminal de la sesión verás qué se va a publicar, dónde y con qué
   fechas. Escribe `s` para confirmar o pulsa Intro para cancelar.
   Sin curso de pruebas, pídele que lo publique «oculto»: verás un resumen
   corto y quedará oculto para el alumnado.

Los días siguientes solo tienes que repetir los pasos 2 a 5. `tiza empezar` ya
no te preguntará la dirección ni el usuario: solo la contraseña y que confirmes
los cursos.

## Tres avisos importantes

- **No entres en el aula desde el navegador mientras la sesión está abierta.**
  el aula cierra una de las dos sesiones y verás `SESION_CADUCADA`. Si te
  pasa, cierra el aula en el navegador y vuelve a ejecutar `tiza empezar`.
- **Revisa los cuestionarios antes de publicarlos en real.** En cuanto un alumno
  empieza un intento, `tiza` ya no puede cambiar ese cuestionario
  (`CUESTIONARIO_CON_INTENTOS`). Para corregirlo tendrás que crear otro con un
  nombre distinto.
- **Nunca uses datos del alumnado** (nombres, notas, salud, fotos) en lo que le
  pides al agente ni en la carpeta de la asignatura. Lo que escribes al agente
  llega a una empresa de IA que no está autorizada para tratar esos datos.

## Si algo falla

`tiza` muestra un código de error, por ejemplo `SIN_SESION`, y una línea
«Qué hacer» con el siguiente paso. Prueba primero lo que dice esa línea.

Si no se arregla, avisa a quien te pasó `tiza`, o abre una *issue* en
[GitHub](https://github.com/balejosg/tiza/issues) si tienes cuenta. Indica:

- qué orden ejecutaste y en qué sistema (Windows, macOS o Linux);
- el código de error y la línea «Qué hacer», copiados tal cual.

No mandes capturas del aula virtual (pueden salir alumnos), ni tu contraseña.

## Desinstalar

1. En una terminal: `uv tool uninstall tiza`.
2. Borra la skill: la carpeta `tiza` dentro de `~/.claude/skills`,
   `~/.agents/skills`, `~/.codex/skills` y `~/.config/opencode/skills` (`~` es
   tu carpeta personal; en Windows, `C:\Users\<tu usuario>`).
3. Si quieres borrar también la dirección del aula y tu usuario, borra la
   carpeta `tiza` de la configuración: `~/.config/tiza` en Linux,
   `~/Library/Application Support/tiza` en macOS y
   `%LOCALAPPDATA%\tiza` en Windows.

El aislamiento vive en la carpeta de cada asignatura (`.claude/`, `.codex/` y
`opencode.jsonc`) y se va con ella (en la app de GitHub Copilot se configura a
mano en la propia app y no deja ficheros). Si aplicaste `tiza aislar`, `tiza`
guardó una copia `…antes-de-tiza-…` de cada fichero que ya existía. Codex
guarda además una marca de confianza de esa carpeta en `~/.codex/config.toml`,
que puedes borrar a mano.
