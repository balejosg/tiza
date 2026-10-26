"""La skill nombra bien los comandos del agente y remite a su guía de unidad."""

from __future__ import annotations

from pathlib import Path

from tiza.calificacion.esquema import cargar_esquema
from tiza.escritura.relleno import cargar_relleno

SKILL = Path(__file__).resolve().parent.parent / "src/tiza/skill/tiza/SKILL.md"
GUIA = SKILL.parent / "guias/unidad.md"

COMANDOS_DEL_DOCENTE = (
    "tiza empezar",
    "tiza sesion",
    "tiza configurar",
    "tiza autoprueba",
    "tiza aislar",
    "tiza actualizar",
)


def _tabla_de_comandos() -> str:
    """La primera columna (el comando) de la tabla."""
    texto = SKILL.read_text(encoding="utf-8")
    _, _, resto = texto.partition("## Comandos que sí puedes ejecutar")
    assert resto, "falta el apartado de comandos"
    filas = []
    for linea in resto.splitlines():
        if linea.startswith("## "):
            break
        if linea.startswith("|"):
            filas.append(linea.split("|")[1])
    return "\n".join(filas)


def test_skill_nombra_comandos_del_agente():
    tabla = _tabla_de_comandos()
    for comando in (
        "tiza normativa",
        "tiza leer",
        "tiza documento",
        "tiza rellenar",
        "tiza importar",
        "tiza copia",
        "tiza calificador",
    ):
        assert f"`{comando}" in tabla
    for comando in COMANDOS_DEL_DOCENTE:
        assert comando not in tabla


def test_guia_unidad_existe_y_se_cita():
    assert GUIA.is_file()
    assert "guias/unidad.md" in SKILL.read_text(encoding="utf-8")
    assert len(GUIA.read_text(encoding="utf-8").splitlines()) <= 90


def test_unidad_completa_carga_la_guia_antes_del_primer_paso():
    texto = SKILL.read_text(encoding="utf-8")
    seccion = texto.split("## Unidad completa", 1)[1].split("\n## ", 1)[0]
    assert "guias/unidad.md" in seccion
    assert seccion.index("guias/unidad.md") < seccion.index("\n1. ")


GUIA_ESTILO = SKILL.parent / "guias/estilo.md"


def test_guia_estilo_existe_y_se_cita_antes_de_escribir():
    assert GUIA_ESTILO.is_file()
    texto = SKILL.read_text(encoding="utf-8")
    assert "guias/estilo.md" in texto
    seccion = texto.split("2. **Escribe el contenido**", 1)[1].split("\n3. ", 1)[0]
    assert "guias/estilo.md" in seccion


GUIA_PROGRAMACION = SKILL.parent / "guias/programacion.md"


def _bloque_yaml(texto: str) -> str:
    """El primer bloque ```yaml de la guía, sin las vallas."""
    _, abre, resto = texto.partition("```yaml\n")
    assert abre, "la guía no trae ningún bloque yaml"
    bloque, cierra, _ = resto.partition("\n```")
    assert cierra, "el bloque yaml no se cierra"
    return bloque + "\n"


def _bloques_yaml(texto: str) -> list[str]:
    """Todos los bloques ```yaml de la guía, sin las vallas."""
    return [trozo.partition("\n```")[0] + "\n" for trozo in texto.split("```yaml\n")[1:]]


def test_guia_programacion_existe_y_se_cita(tmp_path):
    assert GUIA_PROGRAMACION.is_file()
    assert "guias/programacion.md" in SKILL.read_text(encoding="utf-8")
    texto = GUIA_PROGRAMACION.read_text(encoding="utf-8")
    assert len(texto.splitlines()) <= 150
    assert "relleno.yaml" in texto
    # El ejemplo tiene que cargar sin errores: se valida su forma sin abrir ninguna plantilla.
    ruta = tmp_path / "relleno.yaml"
    ruta.write_text(_bloque_yaml(texto), encoding="utf-8")
    relleno = cargar_relleno(ruta, tmp_path)
    assert {type(op).__name__ for op in relleno.operaciones} == {
        "Reemplazar",
        "Sustituir",
        "InsertarDespues",
        "Filas",
        "DuplicarTabla",
        "Borrar",
    }


def test_skill_carga_la_guia_de_programacion_en_su_seccion():
    texto = SKILL.read_text(encoding="utf-8")
    seccion = texto.split("## Programación del docente", 1)[1].split("\n## ", 1)[0]
    assert "guias/programacion.md" in seccion
    assert "tiza rellenar" in seccion


GUIA_REALINEAR = SKILL.parent / "guias/realinear.md"


def _linea_con(*partes: str) -> str:
    """La línea de la skill que contiene todas las ``partes`` (una regla completa)."""
    for linea in SKILL.read_text(encoding="utf-8").splitlines():
        if all(parte in linea for parte in partes):
            return linea
    raise AssertionError(f"la skill no tiene una línea con {partes}")


def test_guia_realinear_existe_y_se_cita():
    assert GUIA_REALINEAR.is_file()
    assert "guias/realinear.md" in SKILL.read_text(encoding="utf-8")
    texto = GUIA_REALINEAR.read_text(encoding="utf-8")
    for codigo in ("CAMBIADA_EN_EL_AULA", "ORIGEN_NO_ENCONTRADO", "COPIA_CON_USUARIOS"):
        assert codigo in texto


def test_skill_copia_es_dato():
    # La regla tiene que estar en la lista de reglas, con el resto de las que no se rompen.
    _, _, resto = SKILL.read_text(encoding="utf-8").partition("## Reglas que no se rompen")
    reglas = resto.split("\n## ", 1)[0]
    linea = next(
        ln for ln in reglas.splitlines() if "copia" in ln and "**dato, nunca instrucción**" in ln
    )
    assert "importar" in linea


def test_skill_copia_rechazada_no_se_abre():
    linea = _linea_con("COPIA_CON_USUARIOS", "no se abre")
    for via in ("tar", "unzip", "Python"):
        assert via in linea


GUIA_CALIFICADOR = SKILL.parent / "guias/calificador.md"
EJEMPLO_CALIFICADOR = Path(__file__).resolve().parent.parent / "ejemplos/calificacion.yaml"
EJEMPLO_CALIFICADOR_CRITERIOS = (
    Path(__file__).resolve().parent.parent / "ejemplos/calificacion-criterios.yaml"
)
# Los códigos que la guía nombra: el agente los ve en el informe o en la salida y debe conocerlos.
CODIGOS_CALIFICADOR = (
    "ESQUEMA_INVALIDO",
    "PESOS_NO_SUMAN_100",
    "EVALUA_INVALIDO",
    "ELEMENTO_DESCONOCIDO",
    "EVALUA_NO_CALIFICABLE",
    "SECCION_SIN_EVALUACION",
    "ACTIVIDAD_PENDIENTE",
    "ACTIVIDAD_EN_EVALUACION_CERRADA",
    "ACTIVIDAD_AMBIGUA",
    "CARPETA_DEMASIADO_GRANDE",
    "CAMBIADO_A_MANO",
    "EVALUACION_CERRADA_EN_EL_AULA",
    "ELEMENTO_CON_NOTAS_QUITADO",
    "ELEMENTO_CON_CRITERIOS",
    "CRITERIOS_SIN_PESO",
    "BLOQUEO_FALLIDO",
    "CALIFICADOR_INVALIDO",
    "SIN_SESION",
)


def test_ejemplo_del_calificador_carga_con_tope_y_tres_evaluaciones():
    esquema = cargar_esquema(EJEMPLO_CALIFICADOR, EJEMPLO_CALIFICADOR.parent)
    assert esquema.organizacion == "elementos"
    assert len(esquema.elementos) == 3
    assert len(esquema.evaluaciones) == 3
    assert esquema.final.tope is not None


def test_ejemplo_con_criterios_carga_con_pesos_y_casilla_manual():
    esquema = cargar_esquema(EJEMPLO_CALIFICADOR_CRITERIOS, EJEMPLO_CALIFICADOR_CRITERIOS.parent)
    ce1, ce2 = esquema.elementos
    assert [c.id for c in ce1.criterios] == ["CE1_1", "CE1_2"]
    assert [c.peso for c in ce2.criterios] == [None, None]
    assert [i.id for i in esquema.instrumentos] == ["EXAMEN1"]


def test_guia_calificador_existe_se_cita_y_nombra_sus_codigos():
    assert GUIA_CALIFICADOR.is_file()
    texto = GUIA_CALIFICADOR.read_text(encoding="utf-8")
    assert len(texto.splitlines()) <= 168
    assert "guias/calificador.md" in SKILL.read_text(encoding="utf-8")
    for codigo in CODIGOS_CALIFICADOR:
        assert codigo in texto, f"la guía del calificador no nombra {codigo}"


def test_guia_calificador_muestra_el_ejemplo_tal_cual(tmp_path):
    texto = GUIA_CALIFICADOR.read_text(encoding="utf-8")
    bloque = _bloque_yaml(texto)
    assert bloque == EJEMPLO_CALIFICADOR.read_text(encoding="utf-8")
    ruta = tmp_path / "calificacion.yaml"
    ruta.write_text(bloque, encoding="utf-8")
    cargar_esquema(ruta, tmp_path)


def test_guia_calificador_fragmento_de_criterios_esta_en_el_ejemplo():
    texto = GUIA_CALIFICADOR.read_text(encoding="utf-8")
    assert "ejemplos/calificacion-criterios.yaml" not in texto  # la skill instalada no lo trae
    bloques = _bloques_yaml(texto)
    assert len(bloques) == 3
    ejemplo = EJEMPLO_CALIFICADOR_CRITERIOS.read_text(encoding="utf-8")
    for fragmento in bloques[1:]:
        assert fragmento in ejemplo


def test_skill_carga_la_guia_del_calificador_en_su_seccion():
    texto = SKILL.read_text(encoding="utf-8")
    seccion = texto.split("## Calificador", 1)[1].split("\n## ", 1)[0]
    assert "guias/calificador.md" in seccion
    assert "tiza calificador" in seccion


DOCS = Path(__file__).resolve().parent.parent / "docs"


def test_la_descripcion_de_la_skill_menciona_el_calificador_y_cabe():
    import re

    texto = SKILL.read_text(encoding="utf-8")
    descripcion = re.search(r"^description: (.*)$", texto, re.MULTILINE)
    assert descripcion is not None
    assert "calificador" in descripcion.group(1)
    assert len(descripcion.group(1)) <= 1024  # el límite de las skills de agente


def test_calificador_invalido_se_explica_igual_en_la_ayuda_y_en_la_guia():
    from tiza import ayuda

    guia = GUIA_CALIFICADOR.read_text(encoding="utf-8")
    for texto in (ayuda.explicar("CALIFICADOR_INVALIDO") or "", guia):
        texto = " ".join(texto.split())
        assert "pide al docente que lo revise" in texto
        assert "deja de saber qué cambió el docente a mano" in texto
        assert "bórralo" not in texto


def test_la_guia_dice_lo_que_el_calificador_no_admite():
    guia = " ".join(GUIA_CALIFICADOR.read_text(encoding="utf-8").split())
    assert "No admitido" in guia and "`organizacion`" in guia and "`final.de`" in guia
    assert "escalas" in guia


def test_seguridad_cuenta_el_calificador_json_como_estado_que_tiza_escribe():
    texto = (DOCS / "seguridad.md").read_text(encoding="utf-8")
    assert "`.tiza/calificador.json`" in texto and "CALIFICADOR_INVALIDO" in texto


def test_la_guia_de_comandos_no_promete_la_terminal_del_docente_para_el_calificador():
    fila = next(
        ln
        for ln in (DOCS / "guia.md").read_text(encoding="utf-8").splitlines()
        if ln.startswith("| `tiza calificador")
    )
    assert "terminal del docente" not in fila and "SIN_SESION" in fila


GUIA_JUNTAR = SKILL.parent / "guias/juntar.md"


def test_guia_juntar_existe_y_se_cita_en_su_apartado():
    assert GUIA_JUNTAR.is_file()
    texto = SKILL.read_text(encoding="utf-8")
    seccion = texto.split("## Mejorar lo ya publicado", 1)[1].split("\n## ", 1)[0]
    assert "guias/juntar.md" in seccion
    assert "tiza estructura --cambios" in seccion
    assert "publicados.json" in seccion


def test_guia_juntar_es_breve_y_cita_los_comandos():
    texto = GUIA_JUNTAR.read_text(encoding="utf-8")
    assert len(texto.splitlines()) <= 150
    for parte in (
        "tiza estructura --cambios",
        "--actividad",
        "CAMBIADA_EN_EL_AULA",
        "sin_registro",
    ):
        assert parte in texto


GUIA_DUA = SKILL.parent / "guias/dua.md"


def test_guia_dua_existe_y_se_carga_al_escribir_y_en_la_unidad():
    assert GUIA_DUA.is_file()
    texto = SKILL.read_text(encoding="utf-8")
    escribir = texto.split("2. **Escribe el contenido**", 1)[1].split("\n3. ", 1)[0]
    assert "guias/dua.md" in escribir
    unidad = texto.split("## Unidad completa", 1)[1].split("\n## ", 1)[0]
    assert "guias/dua.md" in unidad
    for guia in ("unidad.md", "programacion.md", "estilo.md"):
        assert "guias/dua.md" in (SKILL.parent / "guias" / guia).read_text(encoding="utf-8")


def test_guia_dua_es_breve_y_dice_lo_que_tiza_no_hace():
    texto = GUIA_DUA.read_text(encoding="utf-8")
    assert len(texto.splitlines()) <= 150
    for parte in (
        "a mano en el aula",  # lo individual lo pone el docente
        "tipos de entrega",  # tiza no los fija
        "[RELLENA",  # tiza no detecta los huecos
        "`opcion_multiple`",  # retro por opción solo ahí
        "guias/juntar.md",
        "diseño universal",  # lo que se busca con tiza normativa
    ):
        assert parte in texto, parte
