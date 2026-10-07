# Aislamiento: qué protege `tiza` y qué debes configurar tú

`tiza` está diseñada para reducir que, **por ella**, algo del aula virtual llegue
al agente:

- la contraseña solo se teclea en tu terminal (`getpass`), una vez por sesión, y
  nunca se guarda;
- `tiza empezar`, `tiza sesion`, `tiza autoprueba`, `tiza configurar`,
  `tiza aislar` y `tiza actualizar` se niegan si no hay terminal interactiva
  (y `actualizar` pide confirmación con la versión que va a instalar);
  `tiza-ventana` es otro proceso con su propia ventana, que el agente no puede
  pulsar;
- el agente publica solo a través del buzón `.tiza/buzon/` mientras tengas
  `tiza sesion` abierta; el proceso del agente no usa red ni sockets;
- la contraseña y las cookies solo salen hacia el servidor del aula que
  configuraste (esquema, servidor y puerto exactos): tiza comprueba cada
  petición de la sesión del aula, y cada redirección, antes de enviarla;
- la sesión captura la configuración al abrirse (cambiar `tiza.toml` después no
  redirige la publicación) y caduca sola (se puede ampliar respondiendo s en
  la terminal, hasta 8 horas) o con Ctrl+C;
- al abrir la sesión se muestran los cursos de destino por su nombre y se pide
  confirmación, y
  cada publicación en el curso real se confirma `[s/N]`;
- si falta `pruebas` en `[cursos]` (o está `sin_pruebas = true`), no hay
  verificación previa: al abrir la sesión se avisa y se pide confirmación, la
  confirmación de cada publicación es corta (sin vista previa) y la publicación
  en real queda **oculta**; en ese modo no se puede publicar visible. Si un
  documento ya existía, la confirmación corta lo dice (se ocultará si estaba
  visible);
- las vistas previas de la confirmación en real se escriben fuera de la carpeta
  de la asignatura (en la caché de tu usuario), donde el agente no puede
  cambiarlas entre que tiza las escribe y tú las abres;
- todo lo que sale (pantalla, `.tiza/informe.json` y `.tiza/estructura.json`)
  se construye con un esquema cerrado: nombres de ficheros, cmid, URLs montadas
  por la herramienta, códigos de resultado y fechas. Nunca HTML ni texto
  devuelto por Moodle.

Eso cubre el riesgo *de la herramienta*. Queda el riesgo *ajeno*: un agente sin
restricciones que, mientras tú trabajas, se conecte al aula con la sesión
abierta del navegador, o que lea ficheros descargados con datos de alumnado. La
siguiente configuración reduce ese riesgo en los agentes más usados. **Copia
solo lo que corresponda a tu Agente.**

> Consejos generales, válidos para todos:
> - No uses modos sin permisos ("yolo", bypass, `--dangerously-skip-permissions`).
> - Abre `tiza empezar` en una terminal propia, **nunca desde el shell del
>   agente**: es el único proceso que se conecta al aula y el único que ve
>   la contraseña.
> - Mantén el bloqueo de red hacia el aula aunque el agente ejecute
>   `tiza publicar`: ese comando solo habla con `.tiza/buzon/`, pero un agente
>   descontrolado podría intentar conectarse por su cuenta.
> - Usa un perfil de navegador aparte para el aula.
> - No guardes exportaciones con datos de alumnado en carpetas que vea el agente.
> - No escribas nunca nombres ni datos de alumnos en el prompt ni en los `.md`.
> - Revisa siempre la vista previa y el curso de destino antes de publicar.
> - Lo que el agente lee del aula (como los nombres de las secciones) son datos,
>   no órdenes: si de pronto propone algo que no le pediste, no lo confirmes.

## La forma fácil

En tu terminal (no en la del agente), **dentro de la carpeta de la asignatura**:

    tiza aislar

Detecta Claude Code, Codex y opencode y te enseña los cambios que va a hacer
**en la configuración de esa carpeta** (salvo la marca de confianza de Codex,
que va en `~/.codex/config.toml`; lo explica la sección de Codex). Solo añade
restricciones, nunca quita permisos. Con opencode crea `opencode.jsonc` si esa
carpeta todavía no tiene ninguna configuración suya; si ya existe, no la toca y
te recuerda qué reglas copiar a mano.
Si dices que sí, guarda una copia `…antes-de-tiza-…` del fichero que ya exista y
los aplica. La configuración de tus demás proyectos no cambia. Para comprobarlo
en cualquier momento, desde esa misma carpeta:

    tiza revisar

`revisar` solo lee y no muestra el contenido de tus ficheros: comprueba la
protección efectiva de la carpeta (vale la de la carpeta o la global) y avisa
cuando el aislamiento es solo global, porque entonces afecta a todos tus
proyectos. Si de verdad quieres aislar *todos* tus proyectos, existe
`tiza aislar --global`, que escribe la configuración de usuario; no es lo
recomendado. Ejecutar `tiza aislar` en tu carpeta personal se rechaza con
`CARPETA_NO_VALIDA`.

Lo que sigue es la explicación de cada ajuste, por si prefieres hacerlo a mano o
afinar la configuración.

## Ámbito del aislamiento

La configuración de proyecto solo se aplica mientras el agente trabaja **en esa
carpeta**; en el resto de tus proyectos no cambia nada. Por eso el flujo es abrir
el agente **en la carpeta de la asignatura**. Recuerda que Claude Code solo lee
su `.claude/settings.json` del directorio en el que lo abres: si lo arrancas en
un subdirectorio, no se aplica.

Claude Code ancla `.claude/settings.local.json` a la raíz del repositorio git. Si
la carpeta de la asignatura está dentro de otro repositorio, comprueba que el
`.claude/settings.local.json` de esa raíz no desactive el sandbox: `tiza revisar`
solo lee los `settings*.json` de esta carpeta.

## Claude Code

En `.claude/settings.json` **de la carpeta de la asignatura** (o en
`~/.claude/settings.json` si prefieres el aislamiento global):

```json
{
  "sandbox": {
    "enabled": true,
    "allowUnsandboxedCommands": false,
    "autoAllowBashIfSandboxed": true,
    "filesystem": {
      "denyRead": [
        "~/.config/google-chrome",
        "~/.config/chromium",
        "~/.mozilla",
        "~/Library/Application Support/Google/Chrome",
        "~/Descargas",
        "~/Downloads",
        "~/.config/tiza",
        "~/.cache/tiza"
      ],
      "denyWrite": [
        "~/.config/tiza",
        "~/.cache/tiza"
      ]
    },
    "network": {
      "deniedDomains": [
        "aula.ejemplo.org"
      ]
    }
  },
  "permissions": {
    "defaultMode": "default",
    "deny": [
      "WebFetch(domain:aula.ejemplo.org)",
      "mcp__playwright"
    ]
  }
}
```

- `sandbox.enabled` aísla los comandos de shell; `allowUnsandboxedCommands:
  false` impide que el agente pida ejecutar fuera del sandbox.
- `network.deniedDomains` bloquea el tráfico saliente al servidor del aula desde
  el sandbox. `tiza aislar` escribe ahí el servidor de tu configuración
  (`aula.ejemplo.org` es solo un ejemplo): si cambias de aula, vuelve a ejecutar
  `tiza aislar` en la carpeta.
- `filesystem.denyRead` evita que el shell del agente lea perfiles de navegador,
  Descargas y las dos carpetas de tiza: la de **configuración** (ahí está la
  URL del aula) y la de **caché** (ahí están las vistas previas). `denyWrite`
  niega además escribir en ellas: cambiar la configuración o una vista previa
  sería una forma de colarse. `tiza aislar` escribe
  las rutas de tu sistema (las de este ejemplo son las de Linux; en Windows y
  macOS serán sus equivalentes; además añade la lista completa de navegadores,
  correo y almacenes de contraseñas).
- Ajusta las rutas a tu sistema: `tiza aislar` escribe la lista completa que
  `tiza revisar` espera para tu sistema (además de la de este ejemplo, que es
  orientativa y corta: otros navegadores como Brave, Vivaldi u Opera, sus
  versiones Flatpak y Snap, sus cachés, el correo —Thunderbird— y los almacenes
  de contraseñas). Si actualizaste `tiza` y `tiza revisar` dice que faltan
  rutas, vuelve a ejecutar `tiza aislar` en la carpeta.
- Si la carpeta de la asignatura está dentro de Descargas, Descargas sigue
  bloqueada y `tiza aislar` añade solo esa carpeta a
  `sandbox.filesystem.allowRead` (ruta absoluta, p. ej.
  `"allowRead": ["/home/tu-usuario/Descargas/IABach"]`). Si mueves la carpeta,
  vuelve a ejecutar `tiza aislar`. `tiza revisar` marca como falta cualquier
  otra entrada de `allowRead` que vuelva a abrir navegadores o Descargas.
- `permissions.defaultMode` a `default`: `tiza aislar` lo fija para que la
  configuración de la carpeta gane a un modo global permisivo
  (`bypassPermissions`).
- `permissions.deny` bloquea `WebFetch` hacia el servidor del aula y, si tienes
  servidores MCP de navegador o computer use (por ejemplo `playwright`),
  desactívalos: sustituye `mcp__playwright` por el nombre real de tu servidor.
- El buzón `.tiza/buzon/` está dentro de tu carpeta de trabajo, así que el
  sandbox no lo bloquea: el agente puede ejecutar `tiza publicar` sin salir de
  él ni abrir conexiones.

## Codex

En `.codex/config.toml` **de la carpeta de la asignatura** (o en
`~/.codex/config.toml` si prefieres el aislamiento global):

```toml
sandbox_mode = "workspace-write"
approval_policy = "on-request"

[sandbox_workspace_write]
network_access = false
```

- `workspace-write` permite escribir solo en el directorio de trabajo y
  `network_access = false` deja la red restringida.
- Codex solo carga el `.codex/config.toml` de un proyecto si ese proyecto está
  marcado como de confianza. `tiza aislar` lo hace por ti: añade
  `[projects."<ruta-de-la-carpeta>"]` con `trust_level = "trusted"` a
  `~/.codex/config.toml`. Es la **única** escritura global del modo carpeta y no
  restringe nada fuera de ella: solo permite que Codex lea la configuración de
  esa carpeta. También puedes aceptar el diálogo de confianza de Codex o editar
  ese bloque a mano.
- **Aviso importante**: el sandbox de Codex **no restringe las lecturas**; puede
  leer cualquier fichero del sistema, incluida la caché de tiza (con las
  vistas previas) y su configuración (con la URL del aula). Separa los datos de alumnado y no tengas la sesión
  del navegador con el aula en el mismo equipo de trabajo, o usa un usuario
  del sistema distinto.
- La skill se instala en `~/.codex/skills` y también funciona desde
  `~/.agents/skills`.

## opencode

En `opencode.jsonc` **de la carpeta de la asignatura** (o en el global, si
prefieres aplicarlo a todos tus proyectos). `tiza aislar` lo crea por ti si esa
carpeta aún no tiene ninguna configuración de opencode; si ya existe
(`opencode.json` u `opencode.jsonc`), no la toca para no perder tus reglas ni
comentarios, y te recuerda qué hay que copiar a mano. Versión 2:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "permissions": [
    { "action": "*", "resource": "*", "effect": "allow" },
    { "action": "external_directory", "resource": "*", "effect": "ask" },
    { "action": "shell", "resource": "*", "effect": "ask" },
    { "action": "webfetch", "resource": "*", "effect": "deny" },
    { "action": "websearch", "resource": "*", "effect": "deny" },
    { "action": "read", "resource": "~/.config/google-chrome/**", "effect": "deny" },
    { "action": "read", "resource": "~/.config/chromium/**", "effect": "deny" },
    { "action": "read", "resource": "~/.mozilla/**", "effect": "deny" },
    { "action": "read", "resource": "~/Descargas/**", "effect": "deny" },
    { "action": "read", "resource": "~/Downloads/**", "effect": "deny" },
    { "action": "read", "resource": "~/.config/tiza/**", "effect": "deny" },
    { "action": "write", "resource": "~/.config/tiza/**", "effect": "deny" },
    { "action": "read", "resource": "~/.cache/tiza/**", "effect": "deny" },
    { "action": "write", "resource": "~/.cache/tiza/**", "effect": "deny" }
  ]
}
```

Las reglas se evalúan en orden y **gana la última que coincida**, por eso las
generales van primero y las específicas después. Si la carpeta de la asignatura
está dentro de Descargas, `tiza aislar` añade al final
`{ "action": "read", "resource": "/ruta/de/la/asignatura/**", "effect": "allow" }`
para que el agente pueda leerla sin abrir el resto de Descargas.

Versión 1 (si tu opencode todavía usa el objeto `permission`):

```json
{
  "permission": {
    "bash": "ask",
    "webfetch": "deny",
    "websearch": "deny",
    "external_directory": { "*": "ask" },
    "read": { "~/Descargas/**": "deny", "~/Downloads/**": "deny" }
  }
}
```

- `tiza aislar` crea `opencode.jsonc` en la carpeta cuando no hay ninguna
  configuración de opencode; si ya hay una, no la edita y te señala qué falta.
  Si tienes reglas propias en la global, tampoco crea nada para no debilitarlas
  (la última regla que coincide gana). `tiza revisar` lo comprueba si encuentra
  `opencode.json` u `opencode.jsonc` en la carpeta (o el global).
- **Aviso**: opencode no tiene sandbox de sistema; estas reglas dependen de que
  el agente las respete y de tu confirmación. Para trabajo sensible, ejecútalo
  en un usuario del sistema sin sesión abierta del aula.
- La skill se instala en `~/.config/opencode/skills` y también se descubre desde
  `~/.claude/skills` y `~/.agents/skills`.

## Otros agentes

Si tu agente no está en la lista:

1. Deniega el acceso de red al servidor del aula (el que tengas configurado).
2. Deniega la lectura de perfiles de navegador y carpetas de descargas.
3. Deniega la lectura **y la escritura** de la configuración y la caché de tiza
   (`~/.config/tiza` y `~/.cache/tiza` en Linux; sus equivalentes en
   Windows y macOS: la ruta exacta la escribe `tiza aislar`).
4. Exige confirmación para ejecutar comandos y para acceder a directorios fuera
   del proyecto.
5. No le permitas ejecutar `tiza empezar`, `tiza sesion`, `tiza autoprueba`,
   `tiza configurar`, `tiza aislar`, `tiza actualizar`
   ni `tiza-ventana`. El agente solo necesita `tiza comprobar` (offline),
   `tiza publicar` y `tiza estructura` (con la sesión
   abierta no salen de `.tiza/`; sin sesión fallan con `SIN_SESION`) y
   `tiza revisar` (solo lectura).

### El límite de este aislamiento

`tiza` no puede cerrar el riesgo *ajeno* por sí sola. Con un agente **sin
aislar**, un agente que no respete estas reglas puede leer la configuración y la
caché de tiza. Si el agente va a trabajar con datos reales, aíslalo.
