"""``tiza estructura --cambios``: ¿retocó el docente esas actividades a mano en el aula?

Se prueba por ``estructura_con`` y ``SesionAbierta.atender`` con los dobles; la regla de fondo
es la de la publicación (``vigilancia.estado_por_documento``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_buzon import peticion_valida
from test_sesion_abierta import atender

from dobles import MoodleFalso, PresenciaFalsa
from tiza import buzon, config, contenido, estado, informe, publicacion, sesion_abierta, tipos

CFG = config.Config(
    url="https://aula.ejemplo.org/centro",
    usuario="profe",
    cursos={"pruebas": 1234},
    reales=(5678,),
)
CFG_DOS = config.Config(
    url="https://aula.ejemplo.org/centro",
    usuario="profe",
    cursos={"pruebas": 1234},
    reales=(5678, 9999),
)


def _aula(cursos=(1234, 5678)) -> MoodleFalso:
    return MoodleFalso(
        secciones_por_curso={
            curso: [{"numero": 3, "nombre": "Tema 3", "id": curso + 1, "modulos": []}]
            for curso in cursos
        }
    )


def _pagina(carpeta: Path, fichero="p.md", nombre="A", texto="Texto.") -> None:
    (carpeta / fichero).write_text(
        f"---\ntipo: pagina\nnombre: {nombre}\nseccion: 3\n---\n\n{texto}\n", encoding="utf-8"
    )


def _publicar(carpeta: Path, moodle, cfg=CFG, ficheros=("p.md",)) -> dict:
    documentos = [contenido.cargar(carpeta / f, raiz=carpeta) for f in ficheros]
    verificados: dict = {}
    for doc in documentos:
        estado.anotar_verificado(verificados, contenido.hash_documento(doc), doc.ruta.name, 100)
    return publicacion.publicar_en_cursos(
        moodle, cfg, documentos, carpeta, PresenciaFalsa(), entorno="real", verificados=verificados
    )


def _retocar(moodle, cmid: int, *, nombre=None, texto=None, campos=None) -> None:
    formulario = moodle.formularios[cmid]
    if nombre is not None:
        formulario["name"] = nombre
    if texto is not None:
        formulario["page[text]"] = texto
    formulario.update(campos or {})


def _lecturas(moodle) -> int:
    return len([c for c in moodle.llamadas if c[0] == "leer_modulo"])


def _cambios(carpeta: Path, moodle, cfg=CFG, ficheros=("p.md",)) -> dict:
    documentos = [contenido.cargar(carpeta / f, raiz=carpeta) for f in ficheros]
    return sesion_abierta.estructura_con(moodle, cfg, carpeta, ficheros=documentos)


def _acciones(documento: dict) -> list[tuple]:
    return [(f["nombre"], f["accion"], f["curso"], f["cmid"]) for f in documento["ficheros"]]


@pytest.fixture
def publicada(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula()
    _pagina(carpeta)
    primero = _publicar(carpeta, moodle)
    return carpeta, moodle, primero["ficheros"][0]["cmid"]


def test_sin_cambios_no_lee_nada_de_mas_y_el_informe_es_el_de_siempre(publicada):
    carpeta, moodle, _ = publicada
    antes = _lecturas(moodle)
    documento = sesion_abierta.estructura_con(moodle, CFG, carpeta)
    informe.validar(documento)
    assert documento["ficheros"] == [] and documento["resultado"] == "ok"
    assert _lecturas(moodle) == antes
    assert (carpeta / ".tiza" / "estructura.json").is_file()


def test_sin_retoque_sin_cambios(publicada):
    carpeta, moodle, cmid = publicada
    documento = _cambios(carpeta, moodle)
    informe.validar(documento)
    assert _acciones(documento) == [("p.md", "sin_cambios", 5678, cmid)]
    assert documento["ficheros"][0]["tipo"] == "pagina"


@pytest.mark.parametrize(
    "retoque",
    [{"nombre": "Z"}, {"texto": "<p>A mano</p>"}],
)
def test_con_retoque_cambiada(publicada, retoque):
    carpeta, moodle, cmid = publicada
    _retocar(moodle, cmid, **retoque)
    assert _acciones(_cambios(carpeta, moodle)) == [("p.md", "cambiada", 5678, cmid)]


def test_un_cambio_de_fecha_de_tarea_es_cambiada(tmp_path):
    from dobles import fecha_en_formulario, tarea_en

    carpeta = tmp_path.resolve()
    moodle = _aula()
    tarea_en(carpeta)
    cmid = _publicar(carpeta, moodle, ficheros=("tarea.md",))["ficheros"][0]["cmid"]
    assert _acciones(_cambios(carpeta, moodle, ficheros=("tarea.md",)))[0][1] == "sin_cambios"
    _retocar(moodle, cmid, campos=fecha_en_formulario("duedate", (2026, 11, 3, 10, 0)))
    assert _acciones(_cambios(carpeta, moodle, ficheros=("tarea.md",)))[0][1] == "cambiada"


def test_la_marca_igual_al_sha_del_fichero_es_cambiada_sin_leer_el_aula(publicada):
    carpeta, moodle, cmid = publicada
    doc = contenido.cargar(carpeta / "p.md", raiz=carpeta)
    entrada = estado.cargar_publicados(carpeta / ".tiza", 5678)["p.md"]
    estado.guardar_publicado(
        carpeta / ".tiza",
        5678,
        "p.md",
        estado.Publicado(entrada.cmid, "pagina", huella=entrada.huella, marca=doc.sha256_fichero),
    )
    antes = _lecturas(moodle)
    assert _acciones(_cambios(carpeta, moodle)) == [("p.md", "cambiada", 5678, cmid)]
    assert _lecturas(moodle) == antes


def test_sin_entrada_en_el_registro_es_sin_registro(tmp_path):
    carpeta = tmp_path.resolve()
    _pagina(carpeta)
    assert _acciones(_cambios(carpeta, _aula())) == [("p.md", "sin_registro", 5678, None)]


def test_una_entrada_sin_huella_es_sin_registro_con_su_cmid(publicada):
    carpeta, moodle, cmid = publicada
    estado.guardar_publicado(
        carpeta / ".tiza", 5678, "p.md", estado.Publicado(cmid, "pagina", huella=None)
    )
    antes = _lecturas(moodle)
    assert _acciones(_cambios(carpeta, moodle)) == [("p.md", "sin_registro", 5678, cmid)]
    assert _lecturas(moodle) == antes


def test_si_la_lectura_del_formulario_falla_es_cambiada(publicada, monkeypatch):
    carpeta, moodle, cmid = publicada

    def falla(_cmid):
        raise publicacion.publicar.ErrorPublicacion("LECTURA_FALLIDA", "x")

    monkeypatch.setattr(moodle, "leer_modulo", falla)
    assert _acciones(_cambios(carpeta, moodle)) == [("p.md", "cambiada", 5678, cmid)]


def test_dos_cursos_reales_un_fichero_por_curso(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula((1234, 5678, 9999))
    _pagina(carpeta)
    _publicar(carpeta, moodle, CFG_DOS)
    cmid_9999 = estado.cargar_publicados(carpeta / ".tiza", 9999)["p.md"].cmid
    _retocar(moodle, cmid_9999, nombre="Z")
    documento = _cambios(carpeta, moodle, CFG_DOS)
    informe.validar(documento)
    assert [(f["curso"], f["accion"]) for f in documento["ficheros"]] == [
        (5678, "sin_cambios"),
        (9999, "cambiada"),
    ]


def test_el_curso_de_pruebas_no_se_comprueba(tmp_path):
    carpeta = tmp_path.resolve()
    moodle = _aula()
    _pagina(carpeta)
    publicacion.publicar_en_cursos(
        moodle,
        CFG,
        [contenido.cargar(carpeta / "p.md", raiz=carpeta)],
        carpeta,
        PresenciaFalsa(),
        entorno="pruebas",
    )
    antes = _lecturas(moodle)
    documento = _cambios(carpeta, moodle)
    assert _acciones(documento) == [("p.md", "sin_registro", 5678, None)]
    assert _lecturas(moodle) == antes


# --- Lo importado: la base está en copia.json ---------------------------------------------


def _escribir_copia(carpeta: Path, huella: str | None, huella_fichero: str | None = None) -> None:
    entrada = {
        "moodle": "https://aula.ejemplo.org/centro",
        "fecha_importacion": "2026-10-19T10:00:00+00:00",
        "secciones": [{"numero": 3, "nombre": "Tema 3", "resumen_html_presente": False}],
        "actividades": [
            {
                "cmid": 501,
                "modulo": "page",
                "seccion": 3,
                "nombre": "Viejo",
                "fichero": "i.md",
                "estado": "IMPORTADA",
                "detalle": None,
                "huella_aula": huella,
                "huella_fichero": huella_fichero,
            }
        ],
    }
    estado.escribir_copia(
        carpeta / ".tiza", {"version": 1, "cursos": {"5678": entrada}, "como_nuevas": None}
    )


def _importada(tmp_path, *, huella=True, marca=False):
    carpeta = tmp_path.resolve()
    moodle = MoodleFalso(
        secciones_por_curso={
            5678: [
                {
                    "numero": 3,
                    "nombre": "Tema 3",
                    "id": 30,
                    "modulos": [{"cmid": 501, "nombre": "Viejo", "tipo": "pagina"}],
                }
            ],
            1234: [{"numero": 3, "nombre": "Tema 3", "id": 31, "modulos": []}],
        }
    )
    moodle.formularios[501] = {"visible": "1", "name": "Viejo", "page[text]": "<p>Aula</p>"}
    (carpeta / "i.md").write_text(
        "---\ntipo: pagina\nnombre: Viejo\nseccion: 3\norigen:\n  curso: 5678\n  cmid: 501\n---\n\n"
        "Texto.\n",
        encoding="utf-8",
    )
    doc = contenido.cargar(carpeta / "i.md", raiz=carpeta)
    _escribir_copia(
        carpeta,
        tipos.huella_aula("Viejo", "<p>Aula</p>") if huella else None,
        huella_fichero=doc.sha256_fichero if marca else None,
    )
    return carpeta, moodle


def test_importado_sin_retoque_sin_cambios(tmp_path):
    carpeta, moodle = _importada(tmp_path)
    assert _acciones(_cambios(carpeta, moodle, ficheros=("i.md",))) == [
        ("i.md", "sin_cambios", 5678, 501)
    ]


def test_importado_con_retoque_cambiada(tmp_path):
    carpeta, moodle = _importada(tmp_path)
    _retocar(moodle, 501, texto="<p>A mano</p>")
    assert _acciones(_cambios(carpeta, moodle, ficheros=("i.md",))) == [
        ("i.md", "cambiada", 5678, 501)
    ]


def test_importado_sin_huella_en_copia_json_es_sin_registro(tmp_path):
    carpeta, moodle = _importada(tmp_path, huella=False)
    assert _acciones(_cambios(carpeta, moodle, ficheros=("i.md",))) == [
        ("i.md", "sin_registro", 5678, 501)
    ]


def test_importado_con_marca_sin_juntar_es_cambiada_sin_leer_el_aula(tmp_path):
    carpeta, moodle = _importada(tmp_path, marca=True)
    antes = _lecturas(moodle)
    assert _acciones(_cambios(carpeta, moodle, ficheros=("i.md",)))[0][1] == "cambiada"
    assert _lecturas(moodle) == antes


# --- Buzón y sesión -----------------------------------------------------------------------


def _peticion(ficheros):
    return peticion_valida(
        comando="estructura", ficheros=list(ficheros), entorno=None, visible=None
    )


def test_el_buzon_admite_ficheros_en_estructura():
    buzon.validar_peticion(_peticion(["a.md", "sub/b.html"]))


def test_el_buzon_rechaza_mas_de_veinte_ficheros():
    with pytest.raises(buzon.ErrorBuzon):
        buzon.validar_peticion(_peticion([f"{n}.md" for n in range(buzon.MAX_FICHEROS + 1)]))


def test_estructura_sigue_sin_admitir_entorno_ni_solo_fechas():
    with pytest.raises(buzon.ErrorBuzon):
        buzon.validar_peticion(
            peticion_valida(comando="estructura", ficheros=["a.md"], visible=None)
        )
    with pytest.raises(buzon.ErrorBuzon):
        buzon.validar_peticion(
            peticion_valida(
                comando="estructura",
                ficheros=["a.md"],
                entorno=None,
                visible=None,
                solo_fechas=True,
            )
        )


def test_atender_carga_los_ficheros_y_responde_por_curso(publicada):
    carpeta, moodle, cmid = publicada
    documento = atender(_peticion(["p.md"]), moodle, CFG, carpeta, PresenciaFalsa())
    informe.validar(documento)
    assert _acciones(documento) == [("p.md", "sin_cambios", 5678, cmid)]
    assert json.dumps(documento).count("Texto") == 0  # nada del aula ni del texto


def test_atender_con_una_ruta_fuera_de_la_carpeta_da_el_error_de_siempre(publicada):
    carpeta, moodle, _ = publicada
    fuera = carpeta.parent / "fuera.md"
    fuera.write_text("x", encoding="utf-8")
    enlace = carpeta / "enlace.md"
    try:
        enlace.symlink_to(fuera)
    except OSError:
        pytest.skip("sin enlaces simbólicos")
    documento = atender(_peticion(["enlace.md"]), moodle, CFG, carpeta, PresenciaFalsa())
    assert documento["resultado"] == "error" and documento["ficheros"] == []
    assert documento["errores"]


def test_atender_con_un_fichero_invalido_da_su_codigo_sin_seguir(publicada):
    carpeta, moodle, _ = publicada
    (carpeta / "mal.md").write_text("---\ntipo: nada\n---\n\nx\n", encoding="utf-8")
    antes = len(moodle.llamadas)
    documento = atender(_peticion(["mal.md"]), moodle, CFG, carpeta, PresenciaFalsa())
    assert documento["resultado"] == "error" and len(documento["errores"]) == 1
    assert len(moodle.llamadas) == antes


def test_atender_sin_ficheros_no_lee_formularios(publicada):
    carpeta, moodle, _ = publicada
    antes = _lecturas(moodle)
    documento = atender(_peticion([]), moodle, CFG, carpeta, PresenciaFalsa())
    assert documento["ficheros"] == [] and _lecturas(moodle) == antes


def test_con_cambios_y_copia_que_no_vale_escribe_la_estructura_y_da_su_error(tmp_path):
    carpeta, moodle = _importada(tmp_path)
    (carpeta / ".tiza" / "copia.json").write_text("{}", encoding="utf-8")
    documento = _cambios(carpeta, moodle, ficheros=("i.md",))
    informe.validar(documento)
    assert documento["resultado"] == "error" and documento["errores"] == ["COPIA_INVALIDA"]
    assert documento["ficheros"] == []
    datos = json.loads((carpeta / ".tiza" / "estructura.json").read_text(encoding="utf-8"))
    assert datos["cursos"]["real"][0]["id"] == 5678
