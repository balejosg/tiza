"""Tests de ``tiza importar``: todo con copias sintéticas, sin red y dentro de ``tmp_path``."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from copia import fabrica as f
from tiza import agente, ayuda, cli, contenido, estado, importar, informe
from tiza.copia import ErrorCopia
from tiza.importar import ErrorImportar, nombre_de_recurso, nombre_seguro
from tiza.lectura.modelo import ErrorLectura
from tiza.tipos import huella_aula

PNG = b"\x89PNG\r\n\x1a\n" + b"datos de una imagen"


@pytest.fixture
def carpeta(tmp_path):
    asignatura = tmp_path / "asignatura"
    asignatura.mkdir()
    (asignatura / "tiza.toml").write_text("[cursos]\nreal = 3\n", encoding="utf-8")
    return asignatura


def una_seccion():
    return [f.SeccionFalsa(id=7, numero=2, nombre="Tema 1: Intro", resumen="<p>Resumen</p>")]


def pagina(html="<p>Hola</p>", nombre="Una página", cmid=501, **opciones):
    return f.ActividadFalsa(cmid, "page", 7, nombre, html, **opciones)


def copia_en(carpeta, actividades, secciones=None, nombre="copia.mbz", **opciones):
    opciones.setdefault("curso", 3)
    return f.escribir_mbz(carpeta / nombre, secciones or una_seccion(), actividades, **opciones)


def importar_en(carpeta, actividades, secciones=None, **opciones):
    como_nuevas = opciones.pop("como_nuevas", False)
    destino = opciones.pop("destino", "aula")
    copia_en(carpeta, actividades, secciones, **opciones)
    return agente.importar("copia.mbz", carpeta, destino, como_nuevas)


def actividades_de(carpeta) -> dict[int, dict]:
    datos = estado.cargar_copia(carpeta / ".tiza")
    return {a["cmid"]: a for a in datos["actividades"]}


def frontmatter(ruta: Path) -> dict:
    texto = ruta.read_text(encoding="utf-8")
    return yaml.safe_load(texto.split("---\n")[1])


def sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def ficheros_de(carpeta) -> set[str]:
    return {p.relative_to(carpeta).as_posix() for p in carpeta.rglob("*") if p.is_file()}


# --- Los 12 del brief ------------------------------------------------------------------


def test_importar_crea_ficheros_con_origen(carpeta):
    resumen = importar_en(carpeta, [pagina()])
    ruta = carpeta / "aula" / "02-tema-1-intro" / "una-pagina-501.html"
    assert ruta.is_file()
    assert frontmatter(ruta)["origen"] == {"curso": 3, "cmid": 501}
    doc = contenido.cargar(ruta, raiz=carpeta.resolve())
    assert doc.origen == contenido.Origen(curso=3, cmid=501)
    assert doc.seccion == "Tema 1: Intro"
    assert doc.tipo == "pagina"
    assert resumen.estados["IMPORTADA"] == 1
    assert resumen.copia == ".tiza/copia.json"
    assert actividades_de(carpeta)[501]["fichero"] == "aula/02-tema-1-intro/una-pagina-501.html"


def test_importar_reescribe_pluginfile(carpeta):
    html = '<p><img src="@@PLUGINFILE@@/foto.png" alt="Una foto"></p>'
    actividad = pagina(html, ficheros=[f.FicheroFalso("foto.png", PNG)])
    importar_en(carpeta, [actividad])
    seccion = carpeta / "aula" / "02-tema-1-intro"
    assert (seccion / "recursos" / "501" / "foto.png").read_bytes() == PNG
    cuerpo = (seccion / "una-pagina-501.html").read_text(encoding="utf-8")
    assert "recursos/501/foto.png" in cuerpo and "@@PLUGINFILE@@" not in cuerpo
    doc = contenido.cargar(seccion / "una-pagina-501.html", raiz=carpeta.resolve())
    assert [r.nombre for r in doc.recursos] == ["foto.png"]
    assert "@@PLUGINFILE@@/foto.png" in contenido.html_para_moodle(doc)


def test_importar_otro_curso(carpeta):
    antes = ficheros_de(carpeta)
    copia_en(carpeta, [pagina()], curso=9)
    antes = ficheros_de(carpeta)
    with pytest.raises(ErrorImportar) as info:
        agente.importar("copia.mbz", carpeta)
    assert info.value.codigo == "COPIA_DE_OTRO_CURSO"
    assert ficheros_de(carpeta) == antes
    assert not (carpeta / "aula").exists() and not (carpeta / ".tiza").exists()


def test_otro_curso_sin_cursos_reales(carpeta):
    # Sin tiza.toml, o con solo un curso de pruebas, también es COPIA_DE_OTRO_CURSO.
    copia_en(carpeta, [pagina()])
    (carpeta / "tiza.toml").write_text("[cursos]\npruebas = 3\n", encoding="utf-8")
    with pytest.raises(ErrorImportar) as info:
        agente.importar("copia.mbz", carpeta)
    assert info.value.codigo == "COPIA_DE_OTRO_CURSO"
    (carpeta / "tiza.toml").unlink()
    with pytest.raises(ErrorImportar) as info:
        agente.importar("copia.mbz", carpeta)
    assert info.value.codigo == "COPIA_DE_OTRO_CURSO"
    assert "--como-nuevas" in ayuda.explicar("COPIA_DE_OTRO_CURSO")
    assert not (carpeta / "aula").exists()


def test_importar_dos_veces(carpeta):
    actividades = [
        pagina(
            ficheros=[f.FicheroFalso("a.png", PNG)], html='<img src="@@PLUGINFILE@@/a.png" alt="a">'
        )
    ]
    importar_en(carpeta, actividades)
    ruta = carpeta / "aula" / "02-tema-1-intro" / "una-pagina-501.html"
    antes = ficheros_de(carpeta) - {".tiza/copia.json"}
    huellas = {p: sha(carpeta / p) for p in antes}
    resumen = importar_en(carpeta, actividades)
    assert resumen.estados["YA_IMPORTADO"] == 1 and resumen.estados["IMPORTADA"] == 0
    assert ficheros_de(carpeta) - {".tiza/copia.json"} == antes
    assert {p: sha(carpeta / p) for p in antes} == huellas
    assert actividades_de(carpeta)[501]["estado"] == "YA_IMPORTADO"
    assert actividades_de(carpeta)[501]["fichero"] == ruta.relative_to(carpeta).as_posix()


def test_importar_no_pisa_lo_editado_por_el_docente(carpeta):
    importar_en(carpeta, [pagina()])
    ruta = carpeta / "aula" / "02-tema-1-intro" / "una-pagina-501.html"
    ruta.write_text(ruta.read_text(encoding="utf-8") + "\n<p>Mi cambio</p>\n", encoding="utf-8")
    antes = sha(ruta)
    resumen = importar_en(carpeta, [pagina()])
    assert resumen.estados["YA_IMPORTADO"] == 1
    assert sha(ruta) == antes


def test_importar_html_no_admitido(carpeta):
    importar_en(carpeta, [pagina("<p>Hola</p><script>alert(1)</script>")])
    ruta = carpeta / "aula" / "02-tema-1-intro" / "una-pagina-501.html"
    assert ruta.is_file() and "<script>" in ruta.read_text(encoding="utf-8")
    entrada = actividades_de(carpeta)[501]
    assert entrada["estado"] == "HTML_NO_ADMITIDO"
    assert "script" in entrada["detalle"]
    assert not re.search(r"[<>]", entrada["detalle"])


def preguntas_basicas():
    return [
        f.PreguntaFalsa(
            101,
            "P1",
            ((1, "<p>Uno es uno</p>"),),
            "truefalse",
            (("Verdadero", 1.0), ("Falso", 0.0)),
        ),
        f.PreguntaFalsa(
            102,
            "P2",
            ((1, "<p>¿Qué fracción es 1/2?</p>"),),
            "multichoice",
            (("<p>2/4</p>", 1.0), ("<p>1/4</p>", 0.0), ("<p>2/3</p>", 0.0)),
        ),
    ]


def test_importar_cuestionario_admitido(carpeta):
    quiz = f.ActividadFalsa(
        510,
        "quiz",
        7,
        "Repaso",
        "<p>Intro</p>",
        preguntas=preguntas_basicas(),
        fechas={"timeopen": 1792447200, "timeclose": 1795215540},
    )
    importar_en(carpeta, [quiz])
    ruta = carpeta / "aula" / "02-tema-1-intro" / "repaso-510.md"
    doc = contenido.cargar(ruta, raiz=carpeta.resolve())
    assert doc.tipo == "cuestionario" and doc.origen == contenido.Origen(3, 510)
    assert [p.tipo for p in doc.cuestionario.preguntas] == ["verdadero_falso", "opcion_multiple"]
    assert doc.cuestionario.preguntas[0].respuesta == "verdadero"
    assert [o.correcta for o in doc.cuestionario.preguntas[1].opciones] == [True, False, False]
    assert doc.cuestionario.apertura is not None and doc.cuestionario.cierre is not None
    comprobado = agente.comprobar(carpeta, ["aula/02-tema-1-intro/repaso-510.md"])
    assert [r.codigo for r in comprobado.ficheros] == [None]
    assert actividades_de(carpeta)[510]["estado"] == "IMPORTADA"


def test_importar_cuestionario_otros_tipos_admitidos(carpeta):
    preguntas = [
        f.PreguntaFalsa(
            101,
            "P1",
            ((1, "<p>Falso seguro</p>"),),
            "truefalse",
            (("Verdadero", 0.0), ("Falso", 1.0)),
            ajustes={"trueanswer": "1", "falseanswer": "2"},
        ),
        f.PreguntaFalsa(
            102,
            "P2",
            ((1, "<p>Nombre del número de abajo</p>"),),
            "shortanswer",
            (("denominador", 1.0), ("el denominador", 1.0), ("*", 0.0)),
            ajustes={"usecase": "1"},
        ),
        f.PreguntaFalsa(
            103,
            "P3",
            ((1, "<p>3/4 en decimal</p>"),),
            "numerical",
            (("0.75", 1.0),),
            tolerancia=0.001,
        ),
        f.PreguntaFalsa(
            104,
            "P4",
            ((1, "<p>Varias</p>"),),
            "multichoice",
            (("<p>A</p>", 0.5), ("<p>B</p>", 0.5), ("<p>C</p>", 0.0)),
            ajustes={"single": "0"},
        ),
    ]
    importar_en(carpeta, [f.ActividadFalsa(510, "quiz", 7, "Mixto", preguntas=preguntas)])
    ruta = carpeta / "aula" / "02-tema-1-intro" / "mixto-510.md"
    doc = contenido.cargar(ruta, raiz=carpeta.resolve())
    p1, p2, p3, p4 = doc.cuestionario.preguntas
    assert p1.respuesta == "falso"
    assert p2.aceptadas == ("denominador", "el denominador") and p2.mayusculas
    assert p3.valor == 0.75 and p3.tolerancia == 0.001
    assert [o.correcta for o in p4.opciones] == [True, True, False]


def test_importar_cuestionario_no_admitido(carpeta):
    preguntas = [*preguntas_basicas(), f.PreguntaFalsa(103, "P3", ((1, "Redacta"),), "essay", ())]
    importar_en(carpeta, [f.ActividadFalsa(510, "quiz", 7, "Con redacción", preguntas=preguntas)])
    entrada = actividades_de(carpeta)[510]
    assert entrada["estado"] == "PREGUNTAS_NO_ADMITIDAS"
    assert "essay" in entrada["detalle"] and entrada["fichero"] is None
    assert not (carpeta / "aula").exists() or not list((carpeta / "aula").rglob("*.md"))


def test_importar_cuestionario_aleatorio_o_sin_resolver(carpeta):
    preguntas = [
        f.PreguntaFalsa(101, "A", modo="aleatoria"),
        f.PreguntaFalsa(102, "B", modo="ausente"),
    ]
    importar_en(carpeta, [f.ActividadFalsa(510, "quiz", 7, "Raro", preguntas=preguntas)])
    entrada = actividades_de(carpeta)[510]
    assert entrada["estado"] == "PREGUNTAS_NO_ADMITIDAS"
    assert "random" in entrada["detalle"] and "desconocida" in entrada["detalle"]


def test_importar_foro_no_gestionado(carpeta):
    secciones, actividades = f.copia_basica()
    secciones[0].numero = 2
    copia_en(carpeta, actividades, secciones)
    agente.importar("copia.mbz", carpeta)
    foro = actividades_de(carpeta)[504]
    assert foro["estado"] == "TIPO_NO_GESTIONADO" and foro["fichero"] is None
    assert foro["huella_aula"] is None
    assert not [p for p in ficheros_de(carpeta) if "foro" in p]


def test_nombres_de_fichero_windows(carpeta):
    actividades = [
        pagina("<p>a</p>", "¿Qué es: A/B?", 601),
        pagina("<p>b</p>", "Igual", 602),
        pagina("<p>c</p>", "Igual", 603),
        pagina("<p>d</p>", "CON", 604),
        pagina("<p>e</p>", "???", 605),
    ]
    importar_en(carpeta, actividades)
    nombres = [Path(a["fichero"]).name for a in actividades_de(carpeta).values()]
    assert nombres[0] == "que-es-a-b-601.html"
    assert len(set(nombres)) == 5
    assert {"igual-602.html", "igual-603.html"} <= set(nombres)
    for ruta in ficheros_de(carpeta / "aula"):
        for parte in Path(ruta).parts:
            assert not re.search(r'[<>:"/\\|?*]', parte)
            assert not parte.endswith((".", " "))
            assert parte.split(".")[0].upper() not in {"CON", "NUL", "PRN", "AUX"}


def test_nombres_son_estables_y_validos():
    assert nombre_seguro("Tema 1: Intro") == "tema-1-intro"
    assert nombre_seguro("Año Ñandú: ¿qué?") == "ano-nandu-que"
    assert nombre_seguro("") == "sin-nombre" and nombre_seguro("???") == "sin-nombre"
    assert len(nombre_seguro("a" * 300)) <= 50
    assert nombre_de_recurso("foto.png") == "foto.png"
    assert nombre_de_recurso("mi foto (1).png") == "mi_foto_1.png"
    assert nombre_de_recurso("a:b?c.png") == "a_b_c.png"
    assert nombre_de_recurso("CON.txt") == "_CON.txt"
    assert nombre_de_recurso(".oculto") == "recurso.oculto"
    assert nombre_de_recurso("../../x.png") == "x.png"
    assert nombre_de_recurso("informe.") == "informe"
    assert nombre_de_recurso("áé.png") == "áé.png"


def test_recursos_con_nombres_raros_y_repetidos(carpeta):
    html = (
        '<p><img src="@@PLUGINFILE@@/mi%20foto%20%281%29.png" alt="a">'
        '<img src="@@PLUGINFILE@@/mi_foto_1_.png" alt="b"></p>'
    )
    ficheros = [
        f.FicheroFalso("mi foto (1).png", PNG),
        f.FicheroFalso("mi_foto_1_.png", PNG + b"2"),
    ]
    importar_en(carpeta, [pagina(html, ficheros=ficheros)])
    seccion = carpeta / "aula" / "02-tema-1-intro"
    guardados = sorted(p.name for p in (seccion / "recursos" / "501").iterdir())
    assert guardados == ["mi_foto_1-2.png", "mi_foto_1.png"]
    doc = contenido.cargar(seccion / "una-pagina-501.html", raiz=carpeta.resolve())
    assert sorted(r.nombre for r in doc.recursos) == guardados


def test_copia_json_esquema_cerrado(carpeta):
    importar_en(carpeta, [pagina()])
    ruta = carpeta / ".tiza" / "copia.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert estado.cargar_copia(carpeta / ".tiza")["curso"] == 3
    for cambio in (
        lambda d: d.update(extra=1),
        lambda d: d["actividades"][0].update(extra=1),
        lambda d: d["secciones"][0].update(extra=1),
        lambda d: d["actividades"][0].update(estado="OTRO"),
        lambda d: d["actividades"][0].update(fichero="../fuera.html"),
        lambda d: d["actividades"][0].update(huella_aula="abc"),
        lambda d: d.pop("curso"),
        lambda d: d.update(nombre_raro="<b>"),
    ):
        malo = json.loads(json.dumps(datos))
        cambio(malo)
        ruta.write_text(json.dumps(malo), encoding="utf-8")
        with pytest.raises(estado.ErrorEstado) as info:
            estado.cargar_copia(carpeta / ".tiza")
        assert info.value.codigo == "COPIA_INVALIDA"
    ruta.write_text("no es json", encoding="utf-8")
    with pytest.raises(estado.ErrorEstado) as info:
        estado.cargar_copia(carpeta / ".tiza")
    assert info.value.codigo == "IMPORTACION_ILEGIBLE"
    ruta.unlink()
    with pytest.raises(estado.ErrorEstado) as info:
        estado.cargar_copia(carpeta / ".tiza")
    assert info.value.codigo == "IMPORTACION_AUSENTE"


def test_copia_json_nombres_con_simbolos(carpeta):
    secciones = [f.SeccionFalsa(id=7, numero=2, nombre="Tema <b>1</b>")]
    importar_en(carpeta, [pagina(nombre="Una <i>cosa</i>")], secciones)
    datos = estado.cargar_copia(carpeta / ".tiza")
    assert "<" not in json.dumps(datos, ensure_ascii=False)
    assert datos["secciones"][0]["resumen_html_presente"] is False


def test_importar_como_nuevas(carpeta):
    resumen = importar_en(carpeta, [pagina()], curso=9, como_nuevas=True)
    ruta = carpeta / "aula" / "02-tema-1-intro" / "una-pagina-501.html"
    assert "origen" not in frontmatter(ruta)
    assert contenido.cargar(ruta, raiz=carpeta.resolve()).origen is None
    datos = estado.cargar_copia(carpeta / ".tiza")
    assert datos["como_nuevas"] is True and resumen.como_nuevas is True
    assert datos["actividades"][0]["huella_aula"] is None
    assert datos["actividades"][0]["estado"] == "IMPORTADA"


def test_reimportar_cambiada(carpeta):
    importar_en(carpeta, [pagina("<p>Hola</p>")])
    ruta = carpeta / "aula" / "02-tema-1-intro" / "una-pagina-501.html"
    antes = sha(ruta)
    primera = actividades_de(carpeta)[501]["huella_aula"]
    resumen = importar_en(carpeta, [pagina("<p>Hola, mundo</p>")])
    assert sha(ruta) == antes
    assert (carpeta / ".tiza" / "copia" / "501.html").read_text(encoding="utf-8") == (
        "<p>Hola, mundo</p>"
    )
    entrada = actividades_de(carpeta)[501]
    assert entrada["estado"] == "CAMBIADA_DESDE_LA_IMPORTACION"
    assert entrada["huella_aula"] == huella_aula("Una página", "<p>Hola, mundo</p>") != primera
    assert resumen.estados["CAMBIADA_DESDE_LA_IMPORTACION"] == 1
    # Con la huella nueva guardada, repetir la misma copia ya no cuenta como cambio.
    assert importar_en(carpeta, [pagina("<p>Hola, mundo</p>")]).estados["YA_IMPORTADO"] == 1


def test_reimportar_con_la_seccion_renombrada(carpeta):
    importar_en(carpeta, [pagina()])
    ruta = carpeta / "aula" / "02-tema-1-intro" / "una-pagina-501.html"
    nuevas = [f.SeccionFalsa(id=7, numero=2, nombre="Otro nombre")]
    resumen = importar_en(carpeta, [pagina()], nuevas)
    assert resumen.estados["YA_IMPORTADO"] == 1
    assert not (carpeta / "aula" / "02-otro-nombre").exists()
    assert ruta.is_file()


def test_huella_guarda_nombre_y_fechas_de_la_tarea(carpeta):
    tarea = f.ActividadFalsa(
        502,
        "assign",
        7,
        "Entrega",
        "<p>Haz esto</p>",
        fechas={"allowsubmissionsfromdate": 1792447200, "duedate": 1795215540, "cutoffdate": 0},
    )
    importar_en(carpeta, [tarea])
    ruta = carpeta / "aula" / "02-tema-1-intro" / "entrega-502.html"
    doc = contenido.cargar(ruta, raiz=carpeta.resolve())
    assert doc.tipo == "tarea" and doc.fechas.limite is None
    esperadas = {
        "allowsubmissionsfromdate": datetime.fromtimestamp(1792447200).astimezone(),
        "duedate": datetime.fromtimestamp(1795215540).astimezone(),
        "cutoffdate": None,
    }
    assert actividades_de(carpeta)[502]["huella_aula"] == huella_aula(
        "Entrega", "<p>Haz esto</p>", esperadas
    )
    # Cambiar solo la fecha de entrega en el aula también cuenta como cambio.
    otra = f.ActividadFalsa(
        502,
        "assign",
        7,
        "Entrega",
        "<p>Haz esto</p>",
        fechas={"allowsubmissionsfromdate": 1792447200, "duedate": 1795301940, "cutoffdate": 0},
    )
    resumen = importar_en(carpeta, [otra])
    assert resumen.estados["CAMBIADA_DESDE_LA_IMPORTACION"] == 1


def test_tarea_sin_fechas_avisa_al_comprobar(carpeta):
    tarea = f.ActividadFalsa(502, "assign", 7, "Sin fechas", "<p>x</p>")
    importar_en(carpeta, [tarea])
    entrada = actividades_de(carpeta)[502]
    assert entrada["estado"] == "IMPORTADA" and "CAMPO_FALTANTE" in entrada["detalle"]


def test_etiqueta_y_h5p(carpeta):
    paquete = b"PK\x03\x04no es un paquete valido"
    h5p = f.ActividadFalsa(
        520,
        "h5pactivity",
        7,
        "Interactivo",
        "<p>Mira</p>",
        ficheros=[f.FicheroFalso("mi juego.h5p", paquete, filearea="package")],
    )
    etiqueta = f.ActividadFalsa(521, "label", 7, "Aviso", "<p>Atención</p>")
    importar_en(carpeta, [h5p, etiqueta])
    seccion = carpeta / "aula" / "02-tema-1-intro"
    assert (seccion / "recursos" / "520" / "mi_juego.h5p").read_bytes() == paquete
    assert frontmatter(seccion / "interactivo-520.md")["paquete"] == "recursos/520/mi_juego.h5p"
    assert contenido.cargar(seccion / "aviso-521.html", raiz=carpeta.resolve()).tipo == "etiqueta"


def test_h5p_sin_paquete_no_se_importa(carpeta):
    h5p = f.ActividadFalsa(520, "h5pactivity", 7, "Vacío", "<p>Mira</p>")
    importar_en(carpeta, [h5p])
    assert actividades_de(carpeta)[520]["estado"] == "TIPO_NO_GESTIONADO"


# --- La copia y el destino ---------------------------------------------------------------


def test_copia_en_tiza_copias(carpeta):
    copias = carpeta / ".tiza" / "copias"
    copias.mkdir(parents=True)
    f.escribir_mbz(copias / "hecha.mbz", una_seccion(), [pagina()], curso=3)
    resumen = agente.importar(".tiza/copias/hecha.mbz", carpeta)
    assert resumen.estados["IMPORTADA"] == 1


def test_copia_en_otra_carpeta_oculta_no_vale(carpeta):
    for ruta in (".tiza/otra/hecha.mbz", ".tiza/copias/sub/hecha.mbz", ".git/hecha.mbz"):
        destino = carpeta / ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        f.escribir_mbz(destino, una_seccion(), [pagina()], curso=3)
        with pytest.raises(ErrorLectura) as info:
            agente.importar(ruta, carpeta)
        assert info.value.codigo == "FICHERO_TEMPORAL"
    assert not (carpeta / "aula").exists()


def test_copia_fuera_de_la_carpeta_o_mal_formato(carpeta, tmp_path):
    fuera = tmp_path / "fuera.mbz"
    f.escribir_mbz(fuera, una_seccion(), [pagina()], curso=3)
    with pytest.raises(ErrorLectura) as info:
        agente.importar("../fuera.mbz", carpeta)
    assert info.value.codigo == "FICHERO_FUERA"
    (carpeta / "datos.zip").write_bytes(b"x")
    with pytest.raises(ErrorImportar) as info:
        agente.importar("datos.zip", carpeta)
    assert info.value.codigo == "COPIA_FORMATO"
    with pytest.raises(ErrorImportar) as info:
        agente.importar("no-existe.mbz", carpeta)
    assert info.value.codigo == "COPIA_AUSENTE"


def test_copia_con_usuarios_no_se_importa(carpeta):
    copia_en(carpeta, [pagina()], users=1)
    with pytest.raises(ErrorCopia) as info:
        agente.importar("copia.mbz", carpeta)
    assert info.value.codigo == "COPIA_CON_USUARIOS"
    assert not (carpeta / "aula").exists()


@pytest.mark.parametrize(
    "destino", ["../fuera", "/tmp/x", ".oculto", "a/../../b", "a\\b", "a:b", "", "."]
)
def test_destino_no_valido(carpeta, destino):
    copia_en(carpeta, [pagina()])
    with pytest.raises(ErrorImportar) as info:
        agente.importar("copia.mbz", carpeta, destino)
    assert info.value.codigo == "DESTINO_NO_VALIDO"
    assert not (carpeta / ".tiza").exists()


def test_destino_propio(carpeta):
    importar_en(carpeta, [pagina()], destino="programacion/importado")
    assert (
        carpeta / "programacion" / "importado" / "02-tema-1-intro" / "una-pagina-501.html"
    ).is_file()


def test_destino_enlace_a_fuera_no_vale(carpeta, tmp_path):
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    try:
        (carpeta / "aula").symlink_to(fuera, target_is_directory=True)
    except OSError:
        pytest.skip("sin enlaces simbólicos")
    copia_en(carpeta, [pagina()])
    with pytest.raises(ErrorImportar) as info:
        agente.importar("copia.mbz", carpeta)
    assert info.value.codigo == "DESTINO_NO_VALIDO"
    assert list(fuera.iterdir()) == []


def test_actividad_en_una_seccion_que_no_existe(carpeta):
    actividad = f.ActividadFalsa(501, "page", 99, "Perdida", "<p>x</p>")
    copia_en(carpeta, [actividad])
    with pytest.raises(ErrorCopia) as info:
        agente.importar("copia.mbz", carpeta)
    assert info.value.codigo == "COPIA_NO_VALIDA" and not (carpeta / "aula").exists()


def test_nunca_lleva_datos_de_personas(carpeta):
    actividades = [pagina(), f.ActividadFalsa(502, "assign", 7, "T", "<p>x</p>")]
    importar_en(carpeta, actividades)
    for ruta in ficheros_de(carpeta):
        texto = (carpeta / ruta).read_text(encoding="utf-8", errors="ignore")
        for dato in f.DATOS_DE_USUARIO:
            assert dato not in texto


# --- Huella --------------------------------------------------------------------------------


def test_huella_aula_normaliza_urls_de_ficheros():
    copia = '<p><img src="@@PLUGINFILE@@/foto.png" alt="a"></p>'
    for url in (
        "https://aula.example.org/pluginfile.php/259/mod_page/content/0/foto.png",
        "https://aula.example.org/draftfile.php/5/user/draft/123456/foto.png",
        "http://otro:8080/moodle/pluginfile.php/7/mod_label/intro/foto.png?forcedownload=1",
        "/pluginfile.php/7/mod_label/intro/foto.png",
    ):
        aula = copia.replace("@@PLUGINFILE@@/foto.png", url)
        assert huella_aula("N", aula) == huella_aula("N", copia), url
    assert huella_aula("N", copia.replace("foto", "otra")) != huella_aula("N", copia)


def test_huella_aula_nombre_html_y_fechas():
    madrid = datetime.fromisoformat("2026-10-20T08:00:00+02:00")
    utc = datetime.fromisoformat("2026-10-20T06:00:00+00:00")
    assert huella_aula("N", "<p>x</p>", {"duedate": madrid}) == huella_aula(
        "N", "<p>x</p>", {"duedate": utc}
    )
    assert (
        huella_aula("N", "x", {"duedate": None})
        == huella_aula("N", "x")
        == huella_aula("N", "x", {})
    )
    assert huella_aula("N", "x", {"duedate": madrid}) != huella_aula("N", "x")
    assert huella_aula("N", "x") != huella_aula("M", "x")
    assert re.fullmatch(r"[0-9a-f]{64}", huella_aula("N", "x"))
    # Los segundos no cuentan: el formulario del aula no los tiene.
    assert huella_aula("N", "x", {"d": madrid.replace(second=30)}) == huella_aula(
        "N", "x", {"d": madrid}
    )


# --- La CLI ---------------------------------------------------------------------------------


def ejecutar(capsys, argv):
    codigo = cli.main(argv)
    return codigo, json.loads(capsys.readouterr().out)


def test_cli_importar_resumen(carpeta, capsys, monkeypatch):
    monkeypatch.chdir(carpeta)
    copia_en(carpeta, [pagina(), f.ActividadFalsa(504, "forum", 7, "Foro")])
    codigo, resumen = ejecutar(capsys, ["importar", "copia.mbz"])
    assert codigo == 0
    assert resumen["copia"] == ".tiza/copia.json" and resumen["curso"] == 3
    assert resumen["como_nuevas"] is False and resumen["actividades"] == 2
    assert resumen["estados"] == {
        "IMPORTADA": 1,
        "YA_IMPORTADO": 0,
        "CAMBIADA_DESDE_LA_IMPORTACION": 0,
        "HTML_NO_ADMITIDO": 0,
        "PREGUNTAS_NO_ADMITIDAS": 0,
        "TIPO_NO_GESTIONADO": 1,
    }
    informe.validar_importacion(resumen)
    # Nada de la copia (nombres ni textos) sale por stdout.
    assert "Una página" not in json.dumps(resumen)


def test_cli_importar_errores(carpeta, capsys, monkeypatch):
    monkeypatch.chdir(carpeta)
    copia_en(carpeta, [pagina()], curso=9)
    codigo, salida = ejecutar(capsys, ["importar", "copia.mbz"])
    assert codigo == 2
    assert set(salida) == {"error", "detalle", "que_hacer"}
    assert salida["error"] == "COPIA_DE_OTRO_CURSO" and "--como-nuevas" in salida["que_hacer"]
    codigo, salida = ejecutar(capsys, ["importar", "copia.mbz", "--destino", "../x"])
    assert (codigo, salida["error"]) == (2, "DESTINO_NO_VALIDO")
    codigo, salida = ejecutar(capsys, ["importar", "copia.mbz", "--como-nuevas"])
    assert codigo == 0 and salida["como_nuevas"] is True


def test_cli_copia_danada(carpeta, capsys, monkeypatch):
    monkeypatch.chdir(carpeta)
    (carpeta / "mala.mbz").write_bytes(b"no es una copia")
    codigo, salida = ejecutar(capsys, ["importar", "mala.mbz"])
    assert (codigo, salida["error"]) == (2, "COPIA_NO_VALIDA")


def test_resumen_importacion_esquema_cerrado():
    bueno = {
        "copia": ".tiza/copia.json",
        "curso": 3,
        "como_nuevas": False,
        "actividades": 0,
        "estados": {e: 0 for e in informe.ESTADOS_IMPORTACION},
    }
    informe.validar_importacion(bueno)
    for malo in (
        {**bueno, "extra": 1},
        {**bueno, "copia": "/etc/copia.json"},
        {**bueno, "estados": {**bueno["estados"], "OTRO": 1}},
        {**bueno, "como_nuevas": "no"},
    ):
        with pytest.raises(informe.ErrorInforme):
            informe.validar_importacion(malo)


def test_importar_no_importa_nada_del_aula():
    texto = Path(importar.__file__).read_text(encoding="utf-8")
    assert "publicar" not in texto.replace("publicar como", "")
