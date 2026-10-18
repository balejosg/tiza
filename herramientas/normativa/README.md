# Herramienta del mantenedor: extraer y comprobar la normativa

Convierte el texto oficial de los boletines (PDF del BOCM con `pdftotext -layout`, XML
consolidado del BOE) en los JSON que carga `tiza.normativa` y comprueba que cada texto
guardado aparece literal en la página que cita. **Es solo para quien mantiene los datos:
ni los docentes ni sus agentes la usan.** Necesita `pdftotext` (poppler) para los PDF.

Se ejecuta desde la raíz del repositorio, con `uv run python -m herramientas.normativa.<módulo>`.
La lista de normas (`fuentes.toml`: id, URL, `sha256`, correcciones, `recuentos`,
`sustituciones` y `cifrado`) vive en esta carpeta; sus comentarios explican cada decisión (qué toca
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
   - `extraer_fp transversal --ficha <código> --modulo <código> --ciclo <nombre> --madrid <id>
     --ubicacion-madrid <anexo> --horas <id> [--estatal <id>] --cursos-academicos … --cache
     <dir>` (Itinerario I y II, Inglés, Digitalización y Sostenibilidad: `MAD.DAM.1709`…).
     Resultados, criterios y contenidos salen de la orden de Madrid `--madrid` (Orden
     3537/2025, el currículo que se aplica allí): resultados «1. …», criterios «a) …» (a veces
     pegada al texto) y, tras «Contenidos:», apartados y letras, por orden y sin interpretar la
     sangría; cada uno con la página en que empieza y la orden como procedencia (sin `via`: es
     currículo propio, no una modificación). El mínimo estatal (RD 659/2023, que la orden
     reformula y en 1709 y 1710 amplía) no se guarda: `--estatal` solo lo cita en las normas de
     la ficha. Las horas y el curso, de la tabla de `--horas`, como en `modulo`.
   - `extraer_fp optativo --ficha <código> --modulo <código del catálogo> --madrid <id>
     --catalogo <id> --cursos-academicos … --cache <dir>` (Orden 3536/2025 en la redacción de
     la Orden 3822/2026; la ficha es `MAD.CMO.316`, `MAD.CMO.001I`…). El currículo (resultados
     «1.Reconoce», criterios y contenidos) es el anexo II de `--madrid`; el nombre y las horas
     salen del encabezado del módulo («CMO-316 Programación en Python (90 horas).», o sin horas
     en los transversales), y las horas se cruzan con la fila del catálogo (`--catalogo`), de
     donde sale también el curso de los transversales (`2º curso.`; «en cualquiera de los dos
     cursos» es sin curso). CMO-001, 002 y 003 son un único currículo para tres lenguas
     (`F`, `I`, `A`): una ficha por variante, con el mismo texto. Se aplican las
     `sustituciones` de `--madrid` (Phyton→Python); una diferencia entre las horas del catálogo
     y las del anexo, o un criterio fuera de orden, es un error.
   - `extraer_requisitos --cache <dir>` (las tres fichas `MAD.ESO.PROG`, `MAD.BACH.PROG` y
     `MAD.FP.PROG`, tipo `requisito_programacion`): declarativo. `requisitos.toml` lista por ficha
     cada requisito (código, norma, ubicación, página y dos anclas literales, de inicio y de fin,
     ambas incluidas en el texto) y el módulo saca el texto de la página del PDF (y la siguiente)
     o, si no lleva `pagina`, del XML consolidado, con la normalización de `comprobar`. Un ancla
     que no aparece, que se repite en la región o con el fin antes del inicio es un error; en
     el XML el apartado no puede cruzar de párrafo. Un apartado con letras es un elemento (la
     frase que las introduce) y un hijo por letra (`padre`, código `….PROG.5.a`), sin la marca
     «a)». Para elegir los apartados: «programación didáctica», «programaciones» y
     «programación del» en cada norma; solo entra el que dice qué debe incluir, recoger,
     concretar, tener en cuenta o integrar la programación (no el que la nombra de pasada:
     quién la elabora, cuándo se revisa, qué hace la inspección con ella). Los `recuentos`
     son los apartados de cada norma que entran en cada ficha. Un texto sin cabeceras de
     boletín (las instrucciones de la web de la Comunidad) numera sus páginas por los saltos de
     página y no cuenta el número del pie.

## La Orden 3537/2025 sale cifrada: `cifrado.py`

La fuente del cuerpo de su PDF (un subconjunto de Arial sin mapa `ToUnicode`) nombra cada
glifo por su número en la fuente original (`/g3`, `/g38`…), y `pdftotext` los saca como el
carácter U+00NN: «competencias» sale «FRPSHWHQFLDV» y los paréntesis desaparecen (los
glifos 11 y 12 son para Unicode un espacio). `fuentes.toml` lo declara con
`cifrado = "glifos-arial"` (clave solo del mantenedor) y `comun.convertir_pdf` /
`comun.texto_de_norma` hacen lo siguiente, sin tocar el PDF original:

1. `cifrado.parchear_pdf` añade al final una actualización incremental que redeclara la
   codificación de esa fuente con `/uniXXXX` (el carácter ya descifrado) y un xref nuevo;
2. `pdftotext -layout` lee la copia temporal como cualquier otro PDF;
3. `cifrado.comprobar_descifrado` rechaza el resultado si queda un carácter de control o un
   glifo sin tabla (se pone en el área privada de Unicode, U+E000 + glifo). Se aplica
   también a un `.txt` ya en la caché: uno sacado sin descifrar se rechaza (bórralo).

La tabla (`GLIFOS_ARIAL`) es una biyección: el ASCII imprimible es el glifo 3 (el espacio) a
97 (`carácter = glifo + 29`) y los demás son los de Arial en el orden «Macintosh» (con una
plaza menos desde las comillas, porque esta Arial no trae el espacio duro): á é í ñ ó ú ü
(105, 112, 116, 120, 121, 126, 129), ª « » (157, 169, 170), “ ” (179, 180) y Á (200). Solo
entran los glifos que se compararon con la imagen de la página (`pdftoppm -r 100`); un glifo
nuevo se añade tras mirar dónde se usa. Otro PDF del BOCM con el mismo problema solo
necesita la misma línea en `fuentes.toml`, y si su fuente usa más glifos, ampliar la tabla.

## Los fragmentos de `fuentes/`

`fuentes/*.txt` son trozos de texto de boletín ya extraído, con sus cabeceras de página,
`fuentes/*.xml` trozos del XML consolidado del BOE (tablas y anexos) y `bocm-20250827-6_cifrado.pdf`
un PDF mínimo con los objetos reales de la fuente cifrada, para los tests (`tests/normativa/test_herramienta.py`). Junto con los
datos de `src/tiza/normativa/datos/`, es el único sitio del repositorio donde puede aparecer
texto de boletín literal.
