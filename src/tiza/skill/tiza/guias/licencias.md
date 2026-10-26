# Guía: material de otros

Se carga al escribir una pieza cuando lleva algo que no habéis hecho ni el docente ni
tú —una imagen, un vídeo, un audio, un texto, un ejercicio o una actividad interactiva—
o cuando el docente te pide buscar imágenes.

## 1. El material lo trae el docente

- No descargues nada (imágenes, vídeos, audios, textos o ejercicios) ni inventes
  direcciones. Tampoco sustituyas un archivo que no encuentres por otro: deja el hueco y
  avisa.
- Puedes sugerirle dónde buscar: Wikimedia Commons, ARASAAC o el banco de imágenes del
  INTEF. Sin direcciones: que la elija y la traiga él. Que venga de ahí no basta: cada
  archivo tiene su licencia.
- Si te da el archivo, úsalo tal cual, salvo que su licencia permita cambiarlo (ver
  «Licencias en llano»).

## 2. Qué preguntar antes de usarlo

Para cada pieza ajena, pregunta al docente:

- **Autor**: quién la hizo.
- **Fuente**: dónde la encontró (la página, el libro, el servicio).
- **Licencia**: qué permite hacer con ella.

Si falta alguno de los tres, no lo des por bueno: deja la atribución
`[RELLENA: autor, fuente y licencia]` y avísale de lo que falta. En un curso real, no
publiques sin recordárselo. El hueco es para cuando no sabes la licencia; si ya sabes que
es «todos los derechos reservados» o que no hay licencia, no la uses: pide permiso o busca
otra.

## 3. Licencias en llano

- **CC0 o dominio público**: se puede usar sin condiciones; aun así, es buena idea citar.
- **BY**: se puede usar citando al autor, enlazando la licencia e indicando si cambiaste
  algo.
- **BY-SA**: se puede usar citando, enlazando la licencia e indicando cambios. Afecta a la
  versión que hagas con ella, no a toda la página: esa versión lleva la misma licencia.
- **BY-NC**: se puede usar citando y sin uso comercial. Usar en clase no es lo mismo que no
  comercial: una academia que cobra, un curso con matrícula o una página con anuncios no
  son el aula. Si no lo tiene claro, que pregunte en el centro.
- **BY-ND**: se puede usar citando y sin cambios: ni recortar, ni traducir, ni montar
  nada encima.
- **Todos los derechos reservados o sin licencia**: no se reutiliza sin permiso.
- La licencia se mira archivo a archivo.

## 4. Imagen con autoría

Copia este bloque, cambia `img/foto.png` por el archivo que traiga el docente y el `alt`
por lo que se ve. Sustituye los tres `https://example.org/...` (autor, fuente y licencia)
por direcciones reales; si no hay dirección, quita el `<a>` y deja el nombre en texto.

```html
<figure class="mb-3">
  <img class="img-fluid" src="img/foto.png" alt="[RELLENA: qué se ve]">
  <figcaption class="small text-muted">
    <strong>[RELLENA: título de la imagen]</strong>.
    Autor: <a href="https://example.org/autor">[RELLENA: autor]</a>.
    Fuente: <a href="https://example.org/fuente">[RELLENA: fuente]</a>.
    Licencia: <a href="https://example.org/licencia">[RELLENA: licencia]</a>.
  </figcaption>
</figure>
```

No inventes una atribución que no te hayan dado.

## 5. Textos y ejercicios ajenos

- Reelabora con tus palabras y cita la fuente: no copies páginas, ejercicios ni
  enunciados enteros.
- Si el docente insiste en copiar un texto entero, avísale una vez de lo que implica y
  hazlo como lo pide si dice que tiene permiso o licencia. Cita la fuente.
- Un ejercicio entero sigue la misma regla: se puede adaptar con tus palabras; si pide
  copiar el enunciado entero, avísale una vez y hazlo como lo pide si tiene permiso o
  licencia. Cita la fuente.

## 6. Vídeos y actividades interactivas

- Incrustar con `iframe`; no lo bajes ni lo resubas. No hay `<video>`: si trae un archivo
  de vídeo, pídele el enlace del servicio.
- Usa solo los servidores permitidos y el enlace que te dé el docente. Debajo, deja un
  resumen en texto para quien no pueda verlo.
- En una actividad interactiva, pídele al docente que compruebe que el enlace abre sin
  pedir cuenta.

## 7. Material propio del docente

- Si quiere ponerle una licencia a su material, se apunta en `preferencias.txt` (por
  ejemplo, una línea «Licencia de mi material: …»). Cuando publiques su material, pon esa
  licencia en el pie.
- No inventes la licencia ni la pongas si no lo ha dicho.

## 8. La ley

- No cites artículos, leyes ni tratados de memoria. `tiza normativa` no trae la norma que
  dice qué permite cada licencia.
- El aula cerrada ayuda, pero no lo permite todo.
- Ante la duda, que pregunte en el centro o a la administración.
