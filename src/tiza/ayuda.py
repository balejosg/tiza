"""Qué hacer ante cada código de error, en lenguaje llano.

Son textos fijos de la herramienta: nunca llevan nada devuelto por Moodle. Se
muestran en pantalla junto al código; ``.tiza/informe.json`` solo guarda el
código.
"""

from __future__ import annotations

__all__ = ["MENSAJES", "explicar"]

MENSAJES: dict[str, str] = {
    # Sesión y buzón
    "SIN_SESION": "No hay ninguna sesión abierta. En tu terminal, dentro de la carpeta de la asignatura, ejecuta «tiza empezar» y déjala abierta.",
    "SESION_CERRADA": "La sesión del docente se ha cerrado. Vuelve a abrir «tiza empezar» en la carpeta de la asignatura.",
    "SESION_INCOMPATIBLE": "La sesión abierta usa una versión de tiza que habla otro protocolo. Actualiza la más antigua con «tiza actualizar» y vuelve a abrir la sesión.",
    "SESION_YA_ABIERTA": "Ya hay una sesión de tiza abierta en esta carpeta, en otra terminal: usa esa. Si acabas de cerrarla, espera 20 segundos y vuelve a intentarlo.",
    "SESION_CADUCADA": "El aula ha cerrado la sesión: caducó o entraste con el mismo usuario desde otro sitio, como el navegador. Cierra el aula en el navegador y vuelve a abrir «tiza empezar».",
    "SESION_DESACTUALIZADA": "tiza ha cambiado después de abrir la sesión y la sesión se ha cerrado sola para no publicar con el código viejo. Vuelve a abrirla con «tiza empezar».",
    "SIN_RESPUESTA": "La sesión no respondió a tiempo. Mira la terminal de la sesión: puede estar esperando tu confirmación.",
    "RESPUESTA_INVALIDA": "La respuesta de la sesión no es válida. Cierra la sesión con Ctrl+C y vuelve a abrirla con «tiza empezar».",
    "PETICION_INVALIDA": "La petición no es válida. Usa solo «tiza publicar» y «tiza estructura», con rutas dentro de la carpeta; «--solo-fechas» no admite «--visible» ni «--oculto».",
    "PETICION_RETIRADA": "Confirmaste cuando el agente ya había dejado de esperar. No se ha publicado nada; pide al agente que lo repita.",
    "LIMITE_PUBLICACIONES": "Se ha llegado al máximo de publicaciones en pruebas de esta sesión. Revisa qué está haciendo el agente y abre una sesión nueva.",
    "ABORTADO": "Has respondido que no. No se ha publicado nada.",
    "ERROR_INTERNO": "Fallo inesperado de tiza. Repite con --debug en la terminal del docente para ver el detalle y no compartas esa salida.",
    # Terminal y configuración
    "SIN_TTY": "Este comando es del docente: ejecútalo tú en tu propia terminal, no desde el agente.",
    "SIN_CONFIGURAR": "Aún no has configurado tiza. En tu terminal, dentro de la carpeta de la asignatura, ejecuta «tiza empezar».",
    "CONFIG_INCOMPLETA": "Falta la URL o el usuario del aula. Ejecuta «tiza configurar» en tu terminal.",
    "CONFIG_ILEGIBLE": "El fichero de configuración está dañado. Ejecuta «tiza configurar» para crearlo de nuevo.",
    "TIZA_TOML_INVALIDO": "El fichero tiza.toml de esta carpeta tiene un error. Corrígelo o bórralo y vuelve a elegir los cursos.",
    "CURSO_INVALIDO": "Un id de curso no es válido: debe ser un número entero positivo (y «real» admite una lista de 1 a 6 sin repetidos).",
    "CURSOS_IGUALES": "El curso de pruebas y el real no pueden ser el mismo. Elige un curso de pruebas distinto.",
    "CURSO_NO_CONFIGURADO": "Falta el curso de destino. El real es obligatorio; el de pruebas es opcional (sin él solo se publica oculto en real).",
    "SIN_CURSO_PRUEBAS": "No hay curso de pruebas configurado. Para tenerlo, añade «pruebas = 1234» al tiza.toml de la carpeta y borra «sin_pruebas»; sin él, en real solo se publica oculto.",
    "SOLO_OCULTO_SIN_PRUEBAS": "Esta carpeta no tiene curso de pruebas: en real solo se publica oculto. Repite con «tiza publicar … --en real --oculto»; el agente debe pedirlo con visible=false.",
    "URL_NO_PERMITIDA": "La URL debe empezar por https:// y ser la dirección del aula, sin usuario ni contraseña. Cópiala tal como la ves en el navegador.",
    "URL_REDIRIGE_FUERA": "El aula ha redirigido a otro servidor o puerto. Copia en la configuración la dirección final a la que llega el navegador y vuelve a intentarlo.",
    "DESTINO_NO_PERMITIDO": "La petición iba a un servidor que no es el del aula configurada y no ha salido nada. Ejecuta «tiza configurar» y escribe la dirección final del aula.",
    "URL_INACCESIBLE": "No se pudo abrir la URL del aula. Comprueba la conexión a internet y que la URL esté bien escrita.",
    "URL_INVALIDA": "La URL del aula no responde bien. Copia la dirección del aula tal como la ves en el navegador.",
    # Login
    "LOGIN_FALLIDO": "Usuario o contraseña incorrectos. Comprueba el usuario con «tiza configurar» y vuelve a intentarlo una sola vez.",
    "SESION_NO_INICIADA": "El aula no abrió la sesión. Espera unos minutos y vuelve a intentarlo.",
    "ERROR_LOGIN": "No se pudo entrar al aula. Comprueba la conexión y vuelve a intentarlo más tarde.",
    "SESION_SIN_SESSKEY": "El aula no entregó una sesión utilizable. Vuelve a intentarlo; si se repite, pasa «tiza autoprueba».",
    # Contenido (.md o .html)
    "FICHERO_AUSENTE": "No existe ese fichero (.md o .html). Revisa el nombre y que esté dentro de la carpeta de la asignatura.",
    "CODIFICACION_INVALIDA": "El fichero no está en UTF-8. Guárdalo de nuevo como UTF-8.",
    "FRONTMATTER_INVALIDO": "La cabecera del fichero (entre las líneas ---) tiene un error. Si el nombre lleva dos puntos, ponlo entre comillas.",
    "TIPO_INVALIDO": "En la cabecera, tipo debe ser pagina, tarea, cuestionario, etiqueta o h5p.",
    "CAMPO_FALTANTE": "Falta un campo obligatorio de la cabecera del fichero. Añade el campo que indica el mensaje.",
    "CAMPO_DESCONOCIDO": "La cabecera lleva un campo que tiza no conoce. Usa solo los campos del tipo de fichero; mira el formato en la skill o el README.",
    "NOMBRE_INVALIDO": "El nombre debe tener entre 1 y 255 caracteres.",
    "SECCION_INVALIDA": "La sección debe ser su nombre (recomendado) o su número en .tiza/estructura.json.",
    "FECHA_INVALIDA": "Escribe las fechas como AAAA-MM-DD o AAAA-MM-DD HH:MM.",
    "FECHAS_INCOHERENTES": "Las fechas deben cumplir apertura antes que entrega y entrega antes que limite; en un cuestionario, apertura antes que cierre.",
    # Itinerario: finalización y restricciones
    "FINALIZACION_NO_ADMITIDA": "«finalizacion» no vale para este tipo de actividad (o «fecha_esperada» no tiene finalización). Valores: ninguna, manual, ver, entregar (tarea) y calificar (tarea, cuestionario y H5P); la etiqueta solo admite ninguna y manual.",
    "RESTRICCION_INVALIDA": "«restricciones» solo admite desde, hasta, completar (hasta 10 ficheros .md de la carpeta, sin repetir) y ocultar_si_no_cumple (true o false). Las restricciones por grupo o por datos del alumnado se ponen a mano en el aula.",
    "DEPENDENCIA_CIRCULAR": "Los ficheros de «completar» se piden unos a otros (o uno a sí mismo). Quita la dependencia que cierra el círculo.",
    "DEPENDENCIA_INVALIDA": "Un fichero de «completar» no existe o no es válido. Corrígelo y repite «tiza comprobar».",
    "DEPENDENCIA_NO_PUBLICADA": "Un fichero de «completar» aún no está publicado en este curso. Publícalo antes (o en la misma petición) y repite.",
    "RESTRICCION_AJENA": "Esa actividad ya tiene una restricción puesta a mano en el aula (de grupo u otra clase) que tiza no gestiona. No se ha tocado nada: quítala en el aula o deja de declarar «restricciones» en el .md.",
    "FINALIZACION_BLOQUEADA": "Algún alumno ya ha completado esa actividad y el aula no deja cambiar cómo se completa sin borrar ese estado. No se ha tocado nada: quita «finalizacion» del .md o déjala como está en el aula.",
    "FINALIZACION_DESACTIVADA": "El curso no tiene activada la finalización. Actívala en los ajustes del curso («Finalización de actividad») y repite; tiza no cambia los ajustes del curso.",
    "ITINERARIO_NO_APLICADO": "El aula no guardó la finalización o las restricciones tal como se pidieron. Revisa la actividad en el aula y repite la publicación.",
    # Preguntas de un cuestionario
    "PREGUNTAS_INVALIDAS": "El cuestionario necesita una lista «preguntas» de 1 a 100, y cada entrada debe ser un mapa.",
    "TIPO_PREGUNTA_INVALIDO": "Una pregunta usa un tipo que tiza no conoce. Usa opcion_multiple, verdadero_falso, respuesta_corta o numerica.",
    "ENUNCIADO_INVALIDO": "Cada pregunta necesita un enunciado de texto, de 1 a 5000 caracteres.",
    "OPCIONES_INVALIDAS": "Una pregunta de opción múltiple necesita entre 2 y 10 opciones no vacías y al menos una marcada como correcta.",
    "RESPUESTA_PREGUNTA_INVALIDA": "La respuesta de una pregunta no es válida: revisa el campo que indica el mensaje (respuesta, aceptadas, mayusculas, valor o tolerancia).",
    "AJUSTE_INVALIDO": "Un ajuste del cuestionario está fuera de rango: intentos (del 1 al 10 o «ilimitados»), tiempo_limite (1 a 600 minutos) o mezclar_respuestas (true o false).",
    "RECURSO_EN_PREGUNTA": "Las preguntas no admiten imágenes ni ficheros locales; escribe el enunciado, las opciones y la retroalimentación como Markdown.",
    "HTML_PELIGROSO": "El contenido lleva HTML que tiza no admite. Quita o cambia lo que diga el mensaje: scripts, comentarios, estilos o clases fuera de la lista, o iframes de webs que no están permitidas.",
    "RECURSO_AUSENTE": "Falta una imagen o un fichero enlazado desde el fichero. Cópialo a la carpeta o corrige la ruta.",
    "RECURSO_DUPLICADO": "Dos recursos distintos tienen el mismo nombre de fichero. Cambia el nombre de uno.",
    "RECURSO_ILEGIBLE": "No se pudo leer un recurso del fichero. Comprueba que el fichero existe y no está abierto en otro programa.",
    "FICHERO_MODIFICADO": "El fichero o un recurso cambió durante la publicación. Vuelve a comprobarlo y publícalo de nuevo.",
    "RUTA_FUERA_DE_CARPETA": "Solo se publica lo que está dentro de la carpeta de la asignatura. Mueve ahí el fichero o el recurso.",
    "RECURSO_NO_PERMITIDO": "Un recurso es un fichero oculto (su nombre o su carpeta empiezan por punto, como .git/config) o es tiza.toml. No se sube: usa solo imágenes y ficheros de la asignatura.",
    "RECURSO_DEMASIADO_GRANDE": "Un recurso pesa más de 200 MB. Reduce su tamaño o enlázalo desde un servicio de vídeo o de ficheros permitido.",
    "FICHERO_DEMASIADO_GRANDE": "El fichero .md o .html pesa más de 2 MB. Divídelo en varios; las imágenes y los demás ficheros van aparte, como recursos.",
    "DIRECTORIO_NO_SEGURO": "Una carpeta de trabajo de tiza (.tiza o una de sus subcarpetas) es un enlace en vez de una carpeta normal y tiza no escribe a través de enlaces. Bórrala y deja que tiza la cree.",
    # Estructura y secciones
    "ESTRUCTURA_AUSENTE": "Falta .tiza/estructura.json. Con la sesión abierta, ejecuta «tiza estructura».",
    "ESTRUCTURA_ILEGIBLE": "El fichero .tiza/estructura.json está dañado. Con la sesión abierta, ejecuta «tiza estructura».",
    "ESTRUCTURA_VACIA": "El curso de pruebas no tiene secciones. Añade al menos una en el aula y repite.",
    "SECCION_AUSENTE": "Esa sección no existe en el curso. Usa el nombre de la sección o un número de .tiza/estructura.json.",
    "SECCION_ES_ID": "Ese número es el id de la URL del aula, no el número de la sección. Usa el número que indica el mensaje.",
    "SECCION_SIN_NOMBRE": "No se pudo poner nombre a la sección nueva. Pasa «tiza autoprueba» para comprobar el formato del curso.",
    "SECCION_NO_CREADA": "No se pudo crear la sección. Créala a mano en el aula o usa una que ya exista.",
    "ESTRUCTURA_INVALIDA": "Las secciones del curso tienen nombres que tiza no puede guardar. Renombra en el aula las secciones con símbolos raros y repite «tiza estructura».",
    # Publicación (respuestas del aula reducidas a códigos)
    "VERIFICACION_PENDIENTE": "Solo se publica en real lo que esta sesión ya publicó en pruebas sin cambios. Publícalo antes en pruebas.",
    "ERROR_ESTRUCTURA": "No se pudieron leer las secciones del curso. Comprueba que eres profesor de ese curso y vuelve a intentarlo.",
    "ERROR_SECCION": "El aula rechazó un cambio en las secciones. Vuelve a intentarlo; si se repite, pasa «tiza autoprueba».",
    "ERROR_CONTEXTO": "No se pudo preparar la subida de ficheros. Vuelve a intentarlo; si se repite, pasa «tiza autoprueba».",
    "ERROR_SUBIDA": "No se pudo subir un recurso. Comprueba su tamaño y vuelve a intentarlo.",
    "ERROR_CREACION": "El aula no creó la actividad. Vuelve a intentarlo; si se repite, pasa «tiza autoprueba».",
    "ERROR_ACTUALIZACION": "El aula no actualizó la actividad. Vuelve a intentarlo; si se repite, pasa «tiza autoprueba».",
    "ERROR_CONSULTA": "No se pudo leer la actividad publicada. Vuelve a intentarlo más tarde.",
    "ERROR_PLUGINFILE": "No se pudo comprobar un fichero subido. Vuelve a intentarlo más tarde.",
    "ERROR_BORRADO": "No se pudo borrar contenido temporal de la autoprueba. Bórralo a mano en el curso de pruebas.",
    "TIPO_DESCONOCIDO": "Tipo de actividad desconocido. Usa pagina, tarea, cuestionario o etiqueta.",
    # Cuestionarios
    "ERROR_IMPORTACION": "No se pudieron importar las preguntas en el banco del cuestionario. Comprueba que eres profesor del curso y que el aula no ha cambiado; si se repite, pasa «tiza autoprueba».",
    "ERROR_ANADIR_PREGUNTAS": "Las preguntas se importaron, pero no se pudieron añadir al cuestionario. Vuelve a intentarlo; si se repite, pasa «tiza autoprueba».",
    "ERROR_QUITAR_PREGUNTAS": "No se pudieron quitar las preguntas viejas del cuestionario. Revísalo en el aula antes de reintentar.",
    "ERROR_BORRAR_PREGUNTAS": "No se pudieron borrar las preguntas viejas del banco del cuestionario. Revísalo en el aula.",
    "CUESTIONARIO_CON_INTENTOS": "El cuestionario ya tiene intentos o empezó uno durante la publicación y no se puede editar. Si necesita cambios, crea otro cuestionario con otro nombre.",
    "VERIFICACION_PREGUNTAS": "El cuestionario se publicó, pero el aula muestra otras preguntas u otro orden. Revísalo en el curso de pruebas y avisa a quien mantiene tiza.",
    # Actividades H5P
    "ACTIVIDAD_H5P_INVALIDA": "La actividad H5P del fichero no es válida. Revisa el campo que indica el mensaje: las respuestas van entre [[...]], sin «*», «/» ni «:», y los ajustes y las tarjetas deben ser los del formato. Mira el formato en la skill o el README.",
    "CAMPOS_INCOMPATIBLES": "El fichero lleva campos que no pueden ir juntos. En una actividad H5P usa «actividad» (generada por tiza) o «paquete» (un .h5p de la carpeta), pero no los dos.",
    "PAQUETE_H5P_INVALIDO": "El campo «paquete» debe ser la ruta de un fichero .h5p que esté dentro de la carpeta de la asignatura. Revisa la ruta.",
    "PAQUETE_H5P_DEMASIADO_GRANDE": "El paquete .h5p pesa más de 64 MB. Reduce su tamaño o vuelve a exportarlo desde la herramienta con la que lo hiciste.",
    "H5P_LIBRERIA_AUSENTE": "El aula no tiene la librería que necesita la actividad H5P. Pide a quien administra el aula que la instale en la página de librerías de H5P y vuelve a intentarlo.",
    "H5P_NO_DESPLEGADO": "La actividad H5P se publicó, pero no llegó a arrancar. Revísala en el curso de pruebas: si sigue sin verse, avisa a quien mantiene tiza.",
    "H5P_CON_INTENTOS": "La actividad H5P ya tiene intentos de alumnado y cambiarla los rompería. No se ha tocado nada; si necesitas cambios, crea otra actividad con otro nombre.",
    "VERIFICACION_PAQUETE": "La actividad H5P se publicó, pero el paquete no se puede descargar del aula. Revísala en el curso de pruebas.",
    "VERIFICACION_NOMBRE": "La actividad se publicó, pero el aula muestra otro nombre. Revísala en el curso de pruebas.",
    "VERIFICACION_TEXTO": "La actividad se publicó, pero el texto no coincide. Revísala en el curso de pruebas.",
    "VERIFICACION_FICHERO": "La actividad se publicó, pero falta un fichero. Revísala en el curso de pruebas.",
    "REPUBLICAR_CMID_DISTINTO": "Al republicar se creó una actividad nueva en vez de actualizar la existente. El aula ha cambiado: avisa a quien mantiene tiza.",
    "FECHAS_NO_APLICADAS": "El aula no guardó las fechas de la tarea tal como se enviaron. Revisa las fechas a mano en el aula y avisa a quien mantiene tiza con este código.",
    "MODULO_AUSENTE": "«--solo-fechas» solo cambia las fechas de una tarea o de un cuestionario que ya está en el aula, con el mismo tipo, nombre y sección. Publica antes el contenido completo.",
    "SOLO_FECHAS_NO_APLICA": "«--solo-fechas» solo sirve para tareas y cuestionarios. Para páginas, etiquetas o H5P, publica el contenido completo sin ese flag.",
    "CALENDARIO_INVALIDO": "calendario.toml no se puede usar: no es TOML válido, tiene un campo desconocido, una fecha mal escrita, un día de clase que no existe o pesa más de 64 KB. Corrígelo o bórralo; los documentos se comprueban igual, sin avisos de festivos.",
    "VISIBILIDAD_NO_CONSERVADA": "Al republicar, el aula cambió la visibilidad de la actividad. Revisa en el aula si debe verse y avisa a quien mantiene tiza con este código.",
    "ERROR_CURSOS": "No se pudo leer la lista de tus cursos. Puedes escribir el id del curso; lo ves en su URL: course/view.php?id=1234.",
    # Instalación
    "REF_NO_VALIDA": "La variable TIZA_REF no es una etiqueta, rama o commit válidos: solo admite letras, números, «.», «_», «-» y «/». Corrígela o bórrala para instalar la última versión.",
    "UV_NO_ENCONTRADO": "No se encuentra uv. Vuelve a ejecutar el instalador del README.",
    "GIT_NO_ENCONTRADO": "No se encuentra git, que hace falta para saber cuál es la última versión. Vuelve a ejecutar el instalador del README.",
    "ACTUALIZACION_FALLIDA": "No se pudo actualizar tiza. Comprueba la conexión y vuelve a ejecutar el instalador del README.",
    "SKILL_NO_INSTALADA": "No se pudo copiar la skill a los agentes. Ejecuta «tiza instalar-skill».",
    # Aislamiento
    "AJUSTES_ILEGIBLES": "El fichero de ajustes del agente no es JSON o TOML válido. No se ha tocado: corrígelo o renómbralo y repite «tiza aislar».",
    "AJUSTES_INESPERADOS": "El fichero de ajustes del agente tiene una forma que tiza no esperaba. No se ha tocado: aplica a mano lo de docs/aislamiento.md.",
    "CARPETA_NO_VALIDA": "No se aísla la propia carpeta personal. Entra en la carpeta de la asignatura o usa «tiza aislar --global» para todos tus proyectos.",
}


def explicar(codigo: str) -> str | None:
    """Texto «Qué hacer» de un código, o ``None`` si no hay."""
    return MENSAJES.get(codigo)
