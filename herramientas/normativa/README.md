# Herramienta del mantenedor: extraer y comprobar la normativa

Convierte el texto oficial de los boletines (PDF del BOCM con `pdftotext -layout`, XML
consolidado del BOE) en los JSON que carga `tiza.normativa` y comprueba que cada texto
guardado aparece literal en la página que cita. **Es solo para quien mantiene los datos:
ni los docentes ni sus agentes la usan.** Necesita `pdftotext` (poppler) para los PDF.

Se ejecuta desde la raíz del repositorio, con `uv run python -m herramientas.normativa.<módulo>`.
La lista de normas (`fuentes.toml`: id, URL, `sha256`, correcciones, `recuentos` y
`sustituciones`) vive en esta carpeta; sus comentarios explican cada decisión (qué toca
cada corrección o modificación, de dónde sale el texto cuando el PDF no sirve).

## Orden de trabajo: descargar, extraer, comprobar

1. **Descargar**: `descargar --cache <dir>` baja cada `url_pdf` y comprueba su `sha256`; si
   no coincide, para y no sobrescribe nada. Las normas con `url_api` bajan también su XML
   consolidado. La caché (`<id>.pdf`, `<id>.txt`, `<id>.xml`) **va fuera del repositorio**
   y **nunca se commitean los PDF**.
2. **Normas**: `normas --revisada AAAA-MM-DD [--salida <datos>]` escribe `normas/<id>.json`
   de cada norma de `fuentes.toml` (sin `recuentos` ni `sustituciones`, con la fecha de la
   revisión). Se repite cuando cambia `fuentes.toml`.
3. **Extraer**, según la fuente (escriben `fichas/<código>.json` en `src/tiza/normativa/datos`,
   o donde diga `--salida`):
   - `extraer_descriptores --norma <id> --etapa <eso|bachillerato> --cursos-academicos …
     --cache <dir>` (toma de las tablas del anexo I la columna de la etapa):
     **primero**, antes de cualquier materia. Las relaciones entre fichas (los descriptores
     que cita cada competencia) se validan entre fichas al cargar, y una materia sin la
     ficha de descriptores de su etapa no carga.
   - `extraer_lomloe --norma <id> --materia <sigla> --curso <n> --nombre <nombre de la ficha>
     [--titulo <título en el boletín>] --etapa <eso|bachillerato> --cursos-academicos
     2023-24,2024-25 --cache <dir>`. El título que se busca en el boletín es el de la materia
     tal cual (en el decreto de la ESO, en mayúsculas: `--titulo "DIGITALIZACIÓN"`); si la ficha
     la nombra distinto (Bachillerato: «Ciencias de la Computación I»), `--nombre` es el de la
     ficha (si termina en un ordinal romano, «… II», no lleva el sufijo «, N curso»). La
     búsqueda acaba en el título de la materia siguiente: una línea solo en mayúsculas con al
     menos cinco letras (limitación: una línea así *dentro* de una materia la cortaría antes;
     `comprobar` y los recuentos lo delatarían). Una materia que no marca el curso
     (Digitalización, solo 4.º ESO) solo se extrae con `--curso-unico`: sus criterios y
     contenidos van tras las competencias y debe haber un único bloque de criterios; sin esa
     opción es un error.
   - `extraer_fp modulo --ficha <código> --modulo <código> --ciclo <nombre> --boe <id>
     --ubicacion-boe <lugar> [--via <id>] --madrid <id> --horas <id> --cursos-academicos …
     --cache <dir>` (la ficha es el módulo, p. ej. `MAD.DAM.0485`). Los resultados, criterios,
     contenidos básicos (estatales, `EST.…CB.n`) y orientaciones salen del **PDF** de la norma
     `--boe`, limitado a su `--articulo` (por defecto el «segundo»): el RD 450/2010 no tiene
     texto consolidado, su anexo I vigente es el que reescribe el artículo segundo del RD
     405/2023 («queda redactado como sigue»; el artículo tercero repite módulos para otro
     título y no se toca). La procedencia es esa norma y su página; `--via` pone el real
     decreto original y `--ubicacion-via` el lugar de su anexo. Los contenidos de Madrid salen
     de `--madrid`; `--sin-contenidos-madrid` es para el módulo que el decreto no desarrolla
     (el proyecto). Las horas y el curso, de la tabla de `--horas`; si la tabla no pone el
     curso (el proyecto intermodular se desarrolla en los dos), hay que decidirlo con
     `--curso` y explicar la decisión en `fuentes.toml`. Un módulo sin ficha en alguna de las
     fuentes, una letra de criterio fuera de orden o una línea sin lugar son errores, no se
     omiten.
   - `extraer_fp titulo --ficha <código> --nombre <nombre del título> --boe <id> --original
     <id> [--adicion <id>] --cursos-academicos … --cache <dir>` (la ficha es el título, p. ej.
     `MAD.DAM`): los datos de identificación (`TIT.n`, uno por dato), las competencias
     profesionales (`CP.a`…) y los objetivos generales (`OG.a`…) en la redacción de `--boe`,
     con `via` al real decreto original, y la competencia general (`CG`) del PDF de
     `--original`. `--adicion` es la norma que añade un párrafo final al artículo 2.
   - Quedan pendientes los módulos transversales y los optativos de FP: la Orden 3537/2025
     sale cifrada de `pdftotext` y hay que resolver antes cómo se lee.
4. **Comprobar**: `comprobar --cache <dir>` revisa todas las fichas. Sale con código distinto
   de 0 y una línea por discrepancia: `TEXTO`, `PROCEDENCIA`, `RELACION`, `CODIGO`,
   `VIGENCIA`, `FALTA`, `SOBRA` o `SIN_FUENTE`.

Lo extraído se revisa a mano antes de commitear: el PDF manda, así que el texto se guarda
tal como sale de `pdftotext` y un error del boletín se declara en `sustituciones` (la
corrección de errores que lo enmienda), no se arregla en el JSON.

## Los fragmentos de `fuentes/`

`fuentes/*.txt` son trozos de texto de boletín ya extraído, con sus cabeceras de página, y
`fuentes/*.xml` trozos del XML consolidado del BOE (una tabla del anexo I), para los tests (`tests/normativa/test_herramienta.py`). Junto con los
datos de `src/tiza/normativa/datos/`, es el único sitio del repositorio donde puede aparecer
texto de boletín literal.
