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
# Los códigos que la guía nombra: el agente los ve en el informe o en la salida y debe conocerlos.
CODIGOS_CALIFICADOR = (
    "ESQUEMA_INVALIDO",
    "PESOS_NO_SUMAN_100",
    "EVALUA_INVALIDO",
    "ELEMENTO_DESCONOCIDO",
    "SECCION_SIN_EVALUACION",
    "ACTIVIDAD_PENDIENTE",
    "ACTIVIDAD_AMBIGUA",
    "CARPETA_DEMASIADO_GRANDE",
    "CAMBIADO_A_MANO",
    "EVALUACION_CERRADA_EN_EL_AULA",
    "ELEMENTO_CON_NOTAS_QUITADO",
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


def test_guia_calificador_existe_se_cita_y_nombra_sus_codigos():
    assert GUIA_CALIFICADOR.is_file()
    texto = GUIA_CALIFICADOR.read_text(encoding="utf-8")
    assert len(texto.splitlines()) <= 130
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


def test_skill_carga_la_guia_del_calificador_en_su_seccion():
    texto = SKILL.read_text(encoding="utf-8")
    seccion = texto.split("## Calificador", 1)[1].split("\n## ", 1)[0]
    assert "guias/calificador.md" in seccion
    assert "tiza calificador" in seccion
