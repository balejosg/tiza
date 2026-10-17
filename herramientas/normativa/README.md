# Herramienta del mantenedor: extraer y comprobar la normativa

Convierte el texto oficial de los boletines (PDF del BOCM con `pdftotext -layout`, XML
consolidado del BOE) en los JSON que carga `tiza.normativa` y comprueba que cada texto
guardado aparece literal en la página que cita. **Es solo para quien mantiene los datos:
ni los docentes ni sus agentes la usan.** Necesita `pdftotext` (poppler) para los PDF.

Se ejecuta desde la raíz del repositorio, con `uv run python -m herramientas.normativa.<módulo>`.
La lista de normas (`fuentes.toml`: id, URL, `sha256`, correcciones, `recuentos` y
`sustituciones`) está en esta carpeta.

## Orden de trabajo: descargar, extraer, comprobar

1. **Descargar**: `descargar --cache <dir>` baja cada `url_pdf` y comprueba su `sha256`; si
   no coincide, para y no sobrescribe nada. Las normas con `url_api` bajan también su XML
   consolidado. La caché (`<id>.pdf`, `<id>.txt`, `<id>.xml`) **va fuera del repositorio**
   y **nunca se commitean los PDF**.
2. **Extraer**, según la fuente (escriben `fichas/<código>.json` en `src/tiza/normativa/datos`,
   o donde diga `--salida`):
   - `extraer_lomloe --norma <id> --materia <sigla> --curso <n> --nombre <título> --etapa
     <eso|bachillerato> --cursos-academicos 2023-24,2024-25 --cache <dir>`
   - `extraer_descriptores --norma <id> --etapa <…> --cursos-academicos … --cache <dir>`
   - `extraer_fp --ficha <código> --modulo <código> --ciclo <nombre> --boe <id> --madrid <id>
     --horas <id> --cursos-academicos … --cache <dir>`
3. **Comprobar**: `comprobar --cache <dir>` revisa todas las fichas. Sale con código distinto
   de 0 y una línea por discrepancia: `TEXTO`, `PROCEDENCIA`, `RELACION`, `CODIGO`,
   `VIGENCIA`, `FALTA`, `SOBRA` o `SIN_FUENTE`.

Lo extraído se revisa a mano antes de commitear: el PDF manda, así que el texto se guarda
tal como sale de `pdftotext` y un error del boletín se declara en `sustituciones` (la
corrección de errores que lo enmienda), no se arregla en el JSON.

## Los fragmentos de `fuentes/`

`fuentes/*.txt` son trozos de texto de boletín ya extraído, con sus cabeceras de página,
para los tests (`tests/normativa/test_herramienta.py`). Es el único sitio del repositorio
donde puede aparecer texto de boletín literal.
