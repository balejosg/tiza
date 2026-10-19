"""Tests de ``tiza importar``: todo con copias sintéticas, sin red y dentro de ``tmp_path``."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from copia import fabrica as f
from tiza import (
    agente,
    ayuda,
    cli,
    config,
    contenido,
    estado,
    importar,
    importar_cuestionario,
    informe,
)
from tiza.copia import ErrorCopia
from tiza.importar import ErrorImportar, nombre_de_recurso, nombre_seguro
from tiza.importar_cuestionario import html_como_markdown
from tiza.lectura.modelo import ErrorLectura
from tiza.tipos import huella_aula

PNG = b"\x89PNG\r\n\x1a\n" + b"datos de una imagen"


@pytest.fixture(autouse=True)
def _sin_aula_configurada(tmp_path, monkeypatch):
    """Por defecto no hay aula configurada (nunca la del usuario): el curso decide solo."""
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")


@pytest.fixture
def carpeta(tmp_path):
    asignatura = tmp_path / "asignatura"
    asignatura.mkdir()
    (asignatura / "tiza.toml").write_text("[cursos]\nreal = 3\n", encoding="utf-8")
    return asignatura


def pregunta(*args, **opciones):
    """Una pregunta del banco con un punto, que es lo que tiza escribe (la fábrica pone 2)."""
    opciones.setdefault("puntos", 1.0)
    return f.PreguntaFalsa(*args, **opciones)


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


def entrada_de(carpeta, curso=3, como_nuevas=False) -> dict:
    datos = estado.cargar_copia(carpeta / ".tiza")
    return datos["como_nuevas"] if como_nuevas else datos["cursos"][str(curso)]


def actividades_de(carpeta, curso=3, como_nuevas=False) -> dict[int, dict]:
    entrada = entrada_de(carpeta, curso, como_nuevas)
    return {a["cmid"]: a for a in entrada["actividades"]}


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
        pregunta(
            101,
            "P1",
            ((1, "<p>Uno es uno</p>"),),
            "truefalse",
            (("Verdadero", 1.0), ("Falso", 0.0)),
        ),
        pregunta(
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
        pregunta(
            101,
            "P1",
            ((1, "<p>Falso seguro</p>"),),
            "truefalse",
            (("Verdadero", 0.0), ("Falso", 1.0)),
            ajustes={"trueanswer": "1", "falseanswer": "2"},
        ),
        pregunta(
            102,
            "P2",
            ((1, "<p>Nombre del número de abajo</p>"),),
            "shortanswer",
            (("denominador", 1.0), ("el denominador", 1.0)),
            ajustes={"usecase": "1"},
        ),
        pregunta(
            103,
            "P3",
            ((1, "<p>3/4 en decimal</p>"),),
            "numerical",
            (("0.75", 1.0),),
            tolerancia=0.001,
        ),
        pregunta(
            104,
            "P4",
            ((1, "<p>Varias</p>"),),
            "multichoice",
            (("<p>A</p>", 0.5), ("<p>B</p>", 0.5), ("<p>C</p>", -0.5)),
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
    preguntas = [*preguntas_basicas(), pregunta(103, "P3", ((1, "Redacta"),), "essay", ())]
    importar_en(carpeta, [f.ActividadFalsa(510, "quiz", 7, "Con redacción", preguntas=preguntas)])
    entrada = actividades_de(carpeta)[510]
    assert entrada["estado"] == "PREGUNTAS_NO_ADMITIDAS"
    assert "essay" in entrada["detalle"] and entrada["fichero"] is None
    assert not (carpeta / "aula").exists() or not list((carpeta / "aula").rglob("*.md"))


def test_importar_cuestionario_aleatorio_o_sin_resolver(carpeta):
    preguntas = [
        pregunta(101, "A", modo="aleatoria"),
        pregunta(102, "B", modo="ausente"),
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
    assert estado.cargar_copia(carpeta / ".tiza")["cursos"]["3"]["moodle"]
    for cambio in (
        lambda d: d.update(extra=1),
        lambda d: d["cursos"]["3"].update(extra=1),
        lambda d: d["cursos"]["3"]["actividades"][0].update(extra=1),
        lambda d: d["cursos"]["3"]["secciones"][0].update(extra=1),
        lambda d: d["cursos"]["3"]["actividades"][0].update(estado="OTRO"),
        lambda d: d["cursos"]["3"]["actividades"][0].update(fichero="../fuera.html"),
        lambda d: d["cursos"]["3"]["actividades"][0].update(huella_aula="abc"),
        lambda d: d["cursos"]["3"].pop("moodle"),
        lambda d: d["cursos"].update({"tres": d["cursos"]["3"]}),
        lambda d: d.update(como_nuevas={"curso": 3}),
        lambda d: d.pop("cursos"),
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
    assert datos["cursos"]["3"]["secciones"][0]["resumen_html_presente"] is False


def test_importar_como_nuevas(carpeta):
    resumen = importar_en(carpeta, [pagina()], curso=9, como_nuevas=True)
    ruta = carpeta / "aula" / "02-tema-1-intro" / "una-pagina-501.html"
    assert "origen" not in frontmatter(ruta)
    assert contenido.cargar(ruta, raiz=carpeta.resolve()).origen is None
    datos = estado.cargar_copia(carpeta / ".tiza")
    assert resumen.como_nuevas is True and datos["cursos"] == {}
    assert datos["como_nuevas"]["curso"] == 9
    assert datos["como_nuevas"]["actividades"][0]["huella_aula"] is None
    assert datos["como_nuevas"]["actividades"][0]["estado"] == "IMPORTADA"


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


# --- Arreglos previos a la revisión ------------------------------------------------------


def quiz_con(ajustes, preguntas=None):
    return f.ActividadFalsa(
        510,
        "quiz",
        7,
        "Ajustes",
        "<p>i</p>",
        preguntas=preguntas or preguntas_basicas(),
        ajustes=ajustes,
    )


@pytest.mark.parametrize(
    ("ajustes", "intentos", "limite", "mezclar"),
    [
        ({"attempts_number": 3, "timelimit": 2700, "shuffleanswers": 0}, "3", "45", "0"),
        ({"attempts_number": 0, "timelimit": 0, "shuffleanswers": 1}, "0", None, "1"),
        ({"attempts_number": 1, "timelimit": 36000, "shuffleanswers": 1}, "1", "600", "1"),
    ],
)
def test_ajustes_del_cuestionario_ida_y_vuelta(carpeta, ajustes, intentos, limite, mezclar):
    """Lo que se importa, publicado con el payload de tiza, da los mismos valores que la copia."""
    from tiza import tipos

    importar_en(carpeta, [quiz_con(ajustes)])
    ruta = carpeta / "aula" / "02-tema-1-intro" / "ajustes-510.md"
    doc = contenido.cargar(ruta, raiz=carpeta.resolve())
    payload = tipos.obtener("cuestionario").payload(doc, "<p>i</p>", 1, None)
    assert payload["attempts"] == intentos
    assert payload["shuffleanswers"] == mezclar
    if limite is None:
        assert payload["timelimit[enabled]"] == "0"
    else:
        assert payload["timelimit[enabled]"] == "1"
        assert payload["timelimit[number]"] == limite and payload["timelimit[timeunit]"] == "60"
    assert actividades_de(carpeta)[510]["detalle"] is None


@pytest.mark.parametrize(
    ("ajustes", "dice"),
    [
        ({"attempts_number": 25}, "10 intentos"),
        ({"timelimit": 90}, "minutos enteros"),
        ({"timelimit": 36060}, "minutos enteros"),
        ({"timelimit": 30}, "minutos enteros"),
    ],
)
def test_ajustes_del_cuestionario_que_tiza_no_puede_decir(carpeta, ajustes, dice):
    importar_en(carpeta, [quiz_con(ajustes)])
    entrada = actividades_de(carpeta)[510]
    assert entrada["estado"] == "AJUSTES_NO_ADMITIDOS" and entrada["fichero"] is None
    assert dice in entrada["detalle"]
    assert not (carpeta / "aula").exists() or not list((carpeta / "aula").rglob("*.md"))
    assert ayuda.explicar("AJUSTES_NO_ADMITIDOS")


def test_dos_ajustes_no_admitidos_se_dicen_los_dos(carpeta):
    importar_en(carpeta, [quiz_con({"attempts_number": 25, "timelimit": 90})])
    detalle = actividades_de(carpeta)[510]["detalle"]
    assert "10 intentos" in detalle and "minutos enteros" in detalle


def test_cuestionario_sin_ajustes_en_la_copia_no_los_escribe(carpeta):
    importar_en(carpeta, [quiz_con({})])
    texto = (carpeta / "aula" / "02-tema-1-intro" / "ajustes-510.md").read_text(encoding="utf-8")
    cabecera = yaml.safe_load(texto.split("---\n")[1])
    assert not {"intentos", "tiempo_limite", "mezclar_respuestas"} & set(cabecera)


def test_otro_servidor_es_otra_copia(carpeta):
    config.guardar_global("https://aula.example.org/centro/", "profe")
    copia_en(carpeta, [pagina()], servidor="https://otra.example.org")
    with pytest.raises(ErrorImportar) as info:
        agente.importar("copia.mbz", carpeta)
    assert info.value.codigo == "COPIA_DE_OTRO_CURSO"
    assert not (carpeta / "aula").exists()
    # Con --como-nuevas no se comprueba.
    assert agente.importar("copia.mbz", carpeta, como_nuevas=True).estados["IMPORTADA"] == 1


@pytest.mark.parametrize(
    "servidor",
    ["https://aula.example.org", "https://AULA.example.org/", "https://aula.example.org:443/x/"],
)
def test_mismo_servidor_se_compara_por_esquema_y_host(carpeta, servidor):
    config.guardar_global("https://aula.example.org/centro", "profe")
    resumen = importar_en(carpeta, [pagina()], servidor=servidor)
    assert resumen.estados["IMPORTADA"] == 1


@pytest.mark.parametrize(
    "servidor", ["http://aula.example.org", "https://aula.example.org:8443", ""]
)
def test_distinto_esquema_o_puerto_es_otro_servidor(carpeta, servidor):
    config.guardar_global("https://aula.example.org", "profe")
    copia_en(carpeta, [pagina()], servidor=servidor)
    with pytest.raises(ErrorImportar) as info:
        agente.importar("copia.mbz", carpeta)
    assert info.value.codigo == "COPIA_DE_OTRO_CURSO"


def test_sin_aula_configurada_decide_solo_el_curso(carpeta):
    resumen = importar_en(carpeta, [pagina()], servidor="https://cualquiera.example.net")
    assert resumen.estados["IMPORTADA"] == 1


def quiz_de(preguntas):
    return f.ActividadFalsa(510, "quiz", 7, "Notas", preguntas=preguntas)


def multichoice(respuestas, **ajustes):
    return pregunta(
        101,
        "P",
        ((1, "<p>Elige</p>"),),
        "multichoice",
        tuple((f"<p>{n}</p>", x) for n, x in enumerate(respuestas)),
        ajustes=ajustes or None,
    )


@pytest.mark.parametrize(
    "respuestas",
    [
        (1.0, 0.0, 0.0),
        (0.5, 0.5, -0.5),
        (0.3333333, 0.3333333, 0.3333333, -0.3333333),
        (0.25, 0.25, 0.25, 0.25, -0.25),
    ],
)
def test_fracciones_que_tiza_generaria_se_aceptan(carpeta, respuestas):
    correctas = sum(1 for x in respuestas if x > 0)
    pregunta = multichoice(respuestas, single="1" if correctas == 1 else "0")
    importar_en(carpeta, [quiz_de([pregunta])])
    assert actividades_de(carpeta)[510]["estado"] == "IMPORTADA"


@pytest.mark.parametrize(
    ("respuestas", "single"),
    [
        ((0.5, 0.5, 0.0), "0"),  # el incorrecto debería valer -0.5
        ((0.7, 0.3, -0.3), "0"),  # no son las fracciones de tiza
        ((1.0, 0.5, 0.0), "1"),  # puntuación parcial en una de respuesta única
        ((1.0, 0.0, -0.25), "1"),
        ((1.0, 0.0, 0.0), "0"),  # una correcta pero sin «una sola respuesta»
        ((0.5, 0.5, -0.5), "1"),  # varias correctas marcadas como respuesta única
    ],
)
def test_fracciones_que_tiza_no_generaria_no_se_admiten(carpeta, respuestas, single):
    importar_en(carpeta, [quiz_de([multichoice(respuestas, single=single)])])
    entrada = actividades_de(carpeta)[510]
    assert entrada["estado"] == "PREGUNTAS_NO_ADMITIDAS" and entrada["fichero"] is None
    assert "fracciones parciales" in entrada["detalle"]


def test_fracciones_en_verdadero_falso_corta_y_numerica(carpeta):
    malas = [
        pregunta(1, "A", ((1, "<p>a</p>"),), "truefalse", (("V", 0.5), ("F", 0.0))),
        pregunta(2, "B", ((1, "<p>b</p>"),), "shortanswer", (("x", 0.5), ("y", 1.0))),
        pregunta(3, "C", ((1, "<p>c</p>"),), "numerical", (("2", 0.8), ("3", 1.0))),
    ]
    for n, mala in enumerate(malas):
        mala.entrada = 200 + n
        importar_en(carpeta, [quiz_de([mala])])
        assert actividades_de(carpeta)[510]["estado"] == "PREGUNTAS_NO_ADMITIDAS", mala.tipo
        shutil_rm(carpeta)


def shutil_rm(carpeta):
    import shutil

    shutil.rmtree(carpeta / ".tiza", ignore_errors=True)
    shutil.rmtree(carpeta / "aula", ignore_errors=True)


def test_republicar_no_cambia_la_puntuacion(carpeta):
    """Las fracciones del XML que tiza publicaría son las de la copia."""
    import xml.etree.ElementTree as ET

    from tiza.cuestionario import preguntas_xml

    for respuestas, single in (((1.0, 0.0, 0.0), "1"), ((0.5, 0.5, -0.5), "0")):
        shutil_rm(carpeta)
        importar_en(carpeta, [quiz_de([multichoice(respuestas, single=single)])])
        ruta = carpeta / "aula" / "02-tema-1-intro" / "notas-510.md"
        doc = contenido.cargar(ruta, raiz=carpeta.resolve())
        xml = ET.fromstring(preguntas_xml(doc))
        publicadas = [float(a.get("fraction")) / 100 for a in xml.iter("answer")]
        assert publicadas == pytest.approx(list(respuestas), abs=1e-6)


@pytest.mark.parametrize(
    "texto",
    [
        "Calcula 2*3*4 y a_b_c",
        "<p>Calcula 2*3*4 y a_b_c</p>",
        "<p>Primero</p>\n\n<p>Calcula 2*3*4 y a_b_c</p>",
        "<span>Calcula</span> 2*3*4 y a_b_c",
        "<div>Uno</div>\n\n  \n\nCalcula 2*3*4 y a_b_c",
        "<pre>x = 2*3*4\n\ny = a_b_c</pre>\n\nCalcula 2*3*4 y a_b_c",
        "<ul>\n<li>2*3*4</li>\n\n<li>a_b_c</li>\n</ul>",
    ],
)
def test_el_html_de_la_copia_llega_sin_que_un_asterisco_cambie_su_sentido(carpeta, texto):
    preguntas = [
        pregunta(
            101,
            "P1",
            ((1, texto),),
            "multichoice",
            ((texto, 1.0), ("<p>otra</p>", 0.0)),
        ),
        pregunta(102, "P2", ((1, texto),), "truefalse", (("V", 1.0), ("F", 0.0))),
    ]
    cuerpo = f.ActividadFalsa(510, "quiz", 7, "Marcas", texto, preguntas=preguntas)
    importar_en(carpeta, [cuerpo])
    ruta = carpeta / "aula" / "02-tema-1-intro" / "marcas-510.md"
    doc = contenido.cargar(ruta, raiz=carpeta.resolve())
    salidas = [
        doc.html,
        doc.cuestionario.preguntas[0].html,
        doc.cuestionario.preguntas[0].opciones[0].html,
    ]
    salidas.append(doc.cuestionario.preguntas[1].html)
    for html in salidas:
        assert "<em>" not in html and "<strong>" not in html
        if "2*3*4" in texto:
            assert "2*3*4" in html
        if "a_b_c" in texto:
            assert "a_b_c" in html
    if "<pre>" in texto:
        assert "x = 2*3*4\n\ny = a_b_c" in doc.html


# --- Ronda de arreglos 1 --------------------------------------------------------------------


def con_retro(tipo, respuestas, retros, **opciones):
    return pregunta(101, "P", ((1, "<p>q</p>"),), tipo, respuestas, retros=retros, **opciones)


@pytest.mark.parametrize(
    ("preguntas", "dice"),
    [
        (
            lambda: con_retro("truefalse", (("V", 1.0), ("F", 0.0)), ("", "Mal")),
            "retroalimentación",
        ),
        (lambda: con_retro("shortanswer", (("x", 1.0),), ("Bien",)), "retroalimentación"),
        (lambda: con_retro("numerical", (("2", 1.0),), ("Bien",)), "retroalimentación"),
        (
            lambda: pregunta(101, "P", ((1, "<p>q</p>"),), "shortanswer", (("x", 1.0), ("*", 0.0))),
            "fracción 0",
        ),
        (
            lambda: pregunta(101, "P", ((1, "<p>q</p>"),), "numerical", (("2", 1.0), ("3", 0.0))),
            "fracción 0",
        ),
        (
            lambda: pregunta(
                101, "P", ((1, "<p>q</p>"),), "shortanswer", (("x", 1.0),), puntos=2.0
            ),
            "puntos",
        ),
        (
            lambda: pregunta(
                101,
                "P",
                ((1, "<p>q</p>"),),
                "multichoice",
                (("a", 1.0), ("b", 0.0)),
                ajustes={"single": "1", "shuffleanswers": "0"},
            ),
            "sin mezclar",
        ),
        (
            lambda: pregunta(
                101,
                "P",
                ((1, "<p>q</p>"),),
                "multichoice",
                (("a", 1.0), ("b", 0.0)),
                penalizacion=0.5,
            ),
            "penalización",
        ),
        (
            lambda: pregunta(
                101,
                "P",
                ((1, "<p>q</p>"),),
                "truefalse",
                (("V", 1.0), ("F", 0.0)),
                penalizacion=0.3333333,
            ),
            "penalización",
        ),
        (
            lambda: pregunta(
                101, "P", ((1, "<p>q</p>"),), "numerical", (("2", 1.0),), unidades=True
            ),
            "unidades",
        ),
    ],
)
def test_preguntas_que_tiza_no_reescribiria_igual(carpeta, preguntas, dice):
    importar_en(carpeta, [quiz_de([preguntas()])])
    entrada = actividades_de(carpeta)[510]
    assert entrada["estado"] == "PREGUNTAS_NO_ADMITIDAS" and entrada["fichero"] is None
    assert dice in entrada["detalle"]


def test_penalizaciones_de_tiza_se_aceptan(carpeta):
    preguntas = [
        pregunta(
            101, "A", ((1, "<p>a</p>"),), "truefalse", (("V", 1.0), ("F", 0.0)), penalizacion=1.0
        ),
        pregunta(
            102,
            "B",
            ((1, "<p>b</p>"),),
            "multichoice",
            (("a", 1.0), ("b", 0.0)),
            penalizacion=0.3333333,
        ),
        pregunta(103, "C", ((1, "<p>c</p>"),), "numerical", (("2", 1.0),), penalizacion=0.3333333),
    ]
    importar_en(carpeta, [quiz_de(preguntas)])
    assert actividades_de(carpeta)[510]["estado"] == "IMPORTADA"


def test_ajustes_y_preguntas_se_cuentan_por_separado(carpeta):
    malo = quiz_con({"attempts_number": 25})
    importar_en(carpeta, [malo])
    assert actividades_de(carpeta)[510]["estado"] == "AJUSTES_NO_ADMITIDOS"


def test_formato_de_texto_no_html_en_la_actividad(carpeta):
    for formato in (0, 2, 4):
        shutil_rm(carpeta)
        importar_en(carpeta, [pagina("Texto *plano*", formato=formato)])
        entrada = actividades_de(carpeta)[501]
        assert entrada["estado"] == "HTML_NO_ADMITIDO" and entrada["fichero"]
        assert "formato de texto no HTML" in entrada["detalle"]
        assert (carpeta / entrada["fichero"]).is_file()
    shutil_rm(carpeta)
    importar_en(carpeta, [pagina("<p>x</p>", formato=1)])
    assert actividades_de(carpeta)[501]["estado"] == "IMPORTADA"


def test_formato_de_texto_no_html_en_una_pregunta(carpeta):
    mala = pregunta(101, "P", ((1, "Texto"),), "truefalse", (("V", 1.0), ("F", 0.0)), formato=4)
    importar_en(carpeta, [quiz_de([mala])])
    entrada = actividades_de(carpeta)[510]
    assert (
        entrada["estado"] == "PREGUNTAS_NO_ADMITIDAS" and "formato de texto" in entrada["detalle"]
    )
    shutil_rm(carpeta)
    # En una multichoice cuenta también el formato de cada respuesta.
    mala = pregunta(
        101, "P", ((1, "<p>q</p>"),), "multichoice", (("a", 1.0), ("b", 0.0)), formato=0
    )
    importar_en(carpeta, [quiz_de([mala])])
    assert actividades_de(carpeta)[510]["estado"] == "PREGUNTAS_NO_ADMITIDAS"
    shutil_rm(carpeta)
    buena = pregunta(
        101, "P", ((1, "<p>q</p>"),), "multichoice", (("a", 1.0), ("b", 0.0)), formato=1
    )
    importar_en(carpeta, [quiz_de([buena])])
    assert actividades_de(carpeta)[510]["estado"] == "IMPORTADA"


def test_tarea_con_adjuntos_no_se_importa(carpeta):
    tarea = f.ActividadFalsa(
        502,
        "assign",
        7,
        "Con adjunto",
        "<p>x</p>",
        fechas={"allowsubmissionsfromdate": 1792447200, "duedate": 1795215540},
        ficheros=[f.FicheroFalso("guia.pdf", b"%PDF", filearea="introattachment")],
    )
    importar_en(carpeta, [tarea])
    entrada = actividades_de(carpeta)[502]
    assert entrada["estado"] == "AJUSTES_NO_ADMITIDOS" and entrada["fichero"] is None
    assert "adjuntos de la tarea" in entrada["detalle"]


def test_los_avisos_se_acumulan(carpeta):
    tarea = f.ActividadFalsa(
        502,
        "assign",
        7,
        "Aviso <b>y</b> más",
        "<p>x</p><script>1</script>",
        formato=0,
        fechas={
            "allowsubmissionsfromdate": 1792447200,
            "duedate": 1795215540,
            "gradingduedate": 1795300000,
        },
    )
    importar_en(carpeta, [tarea])
    entrada = actividades_de(carpeta)[502]
    assert entrada["estado"] == "HTML_NO_ADMITIDO"
    for frase in ("formato de texto no HTML", "script", "recordatorio de calificar", "nombre"):
        assert frase in entrada["detalle"], frase


def test_tarea_con_recordatorio_avisa_pero_se_importa(carpeta):
    tarea = f.ActividadFalsa(
        502,
        "assign",
        7,
        "Recordada",
        "<p>x</p>",
        fechas={
            "allowsubmissionsfromdate": 1792447200,
            "duedate": 1795215540,
            "gradingduedate": 1795300000,
        },
    )
    importar_en(carpeta, [tarea])
    entrada = actividades_de(carpeta)[502]
    assert entrada["estado"] == "IMPORTADA" and "recordatorio" in entrada["detalle"]


def test_nombre_que_cambia_al_sanearlo_se_avisa(carpeta):
    importar_en(carpeta, [pagina(nombre="Uno <i>dos</i>"), pagina(nombre="Limpio", cmid=502)])
    actividades = actividades_de(carpeta)
    assert "nombre" in actividades[501]["detalle"]
    assert actividades[502]["detalle"] is None


def test_huella_aula_valor_fijo():
    madrid = datetime.fromisoformat("2026-10-20T23:59:00+02:00")
    esperada = "91b80b137b949583729f684be2c83e80f5c5e2b6f454f5034e34d841d5e95aa0"
    html = '<p>Haz <img src="@@PLUGINFILE@@/a.png"></p>'
    assert huella_aula("Entrega", html, {"duedate": madrid, "cutoffdate": None}) == esperada
    aula = html.replace(
        "@@PLUGINFILE@@/", "https://aula.example.org/pluginfile.php/9/mod_assign/intro/"
    )
    assert huella_aula("Entrega", aula, {"duedate": madrid}) == esperada


# --- Tiempo lineal ---


def test_huella_aula_y_html_como_markdown_no_son_cuadraticos():
    import time

    casos = [
        lambda: huella_aula("N", "a" * 300_000),
        lambda: huella_aula("N", "/pluginfile.php/1/" * 20_000),
        lambda: huella_aula("N", "x=" * 150_000),
        lambda: html_como_markdown("<pre" * 40_000),
        lambda: html_como_markdown("<pre>" * 40_000),
        lambda: html_como_markdown("\n \n" * 100_000),
        lambda: html_como_markdown("a" * 300_000),
    ]
    for caso in casos:
        inicio = time.perf_counter()
        caso()
        assert time.perf_counter() - inicio < 1.0


def test_html_como_markdown_conserva_los_pre():
    assert html_como_markdown("<pre>a\n\nb</pre>\n\n\nx") == "<div><pre>a\n\nb</pre>\nx</div>"
    assert html_como_markdown("<PRE>a</PRE>").startswith("<div>")
    sin_cierre = html_como_markdown("<pre>a\n\nb")
    assert "\n\n" not in sin_cierre


# --- copia.json: una entrada por curso ---


def test_dos_cursos_seguidos_conservan_las_dos_entradas(carpeta):
    (carpeta / "tiza.toml").write_text("[cursos]\nreal = [3, 4]\n", encoding="utf-8")
    importar_en(carpeta, [pagina()], curso=3)
    primera = entrada_de(carpeta, 3)
    importar_en(carpeta, [pagina(nombre="Otra", cmid=601)], curso=4, destino="otro")
    datos = estado.cargar_copia(carpeta / ".tiza")
    assert set(datos["cursos"]) == {"3", "4"}
    assert datos["cursos"]["3"] == primera
    assert [a["cmid"] for a in datos["cursos"]["4"]["actividades"]] == [601]
    # Volver a importar el curso 3 no toca el 4.
    cuatro = datos["cursos"]["4"]
    importar_en(carpeta, [pagina()], curso=3)
    assert entrada_de(carpeta, 4) == cuatro


def test_actividad_que_ya_no_esta_en_la_copia_conserva_su_entrada(carpeta):
    importar_en(carpeta, [pagina(), pagina(nombre="Dos", cmid=502)])
    antes = actividades_de(carpeta)[502]
    resumen = importar_en(carpeta, [pagina()])
    assert resumen.actividades == 1
    assert actividades_de(carpeta)[502] == antes
    assert set(actividades_de(carpeta)) == {501, 502}


def test_como_nuevas_va_aparte_y_no_toca_las_huellas(carpeta):
    importar_en(carpeta, [pagina()])
    antes = entrada_de(carpeta, 3)
    importar_en(carpeta, [pagina(nombre="Nueva", cmid=777)], curso=9, como_nuevas=True)
    datos = estado.cargar_copia(carpeta / ".tiza")
    assert datos["cursos"]["3"] == antes
    assert datos["como_nuevas"]["curso"] == 9
    assert [a["cmid"] for a in datos["como_nuevas"]["actividades"]] == [777]


def test_copia_json_corrupto_no_se_sobrescribe(carpeta):
    importar_en(carpeta, [pagina()])
    ruta = carpeta / ".tiza" / "copia.json"
    for contenido_malo in ("no es json", json.dumps({"version": 1, "cursos": {}, "extra": 1})):
        ruta.write_text(contenido_malo, encoding="utf-8")
        antes = ficheros_de(carpeta)
        copia_en(carpeta, [pagina(nombre="Nueva", cmid=888)])
        with pytest.raises(ErrorImportar) as info:
            agente.importar("copia.mbz", carpeta)
        assert info.value.codigo == "COPIA_INVALIDA"
        assert ruta.read_text(encoding="utf-8") == contenido_malo
        assert ficheros_de(carpeta) == antes  # tampoco se escribió ninguna actividad


def test_cli_copia_json_corrupto(carpeta, capsys, monkeypatch):
    monkeypatch.chdir(carpeta)
    (carpeta / ".tiza").mkdir()
    (carpeta / ".tiza" / "copia.json").write_text("{", encoding="utf-8")
    copia_en(carpeta, [pagina()])
    codigo, salida = ejecutar(capsys, ["importar", "copia.mbz"])
    assert (codigo, salida["error"]) == (2, "COPIA_INVALIDA")


# --- Recursos y nombres ---


def test_recursos_que_solo_difieren_en_mayusculas(carpeta):
    html = '<img src="@@PLUGINFILE@@/Foto.png" alt="a"><img src="@@PLUGINFILE@@/foto.png" alt="b">'
    ficheros = [f.FicheroFalso("Foto.png", PNG), f.FicheroFalso("foto.png", PNG + b"2")]
    importar_en(carpeta, [pagina(html, ficheros=ficheros)])
    carpeta_recursos = carpeta / "aula" / "02-tema-1-intro" / "recursos" / "501"
    nombres = [p.name for p in carpeta_recursos.iterdir()]
    assert len(nombres) == 2 and len({n.casefold() for n in nombres}) == 2
    assert sorted(p.read_bytes() for p in carpeta_recursos.iterdir()) == sorted([PNG, PNG + b"2"])
    assert actividades_de(carpeta)[501]["estado"] == "IMPORTADA"


def test_recurso_que_ya_existia_no_se_pisa_ni_se_calla(carpeta, monkeypatch):
    html = '<img src="@@PLUGINFILE@@/foto.png" alt="a">'
    original = importar._crear

    def crear(ruta, datos, base):
        if ruta.name == "foto.png":
            return False  # como si otro proceso (o un disco sin mayúsculas) ya la hubiera creado
        return original(ruta, datos, base)

    monkeypatch.setattr(importar, "_crear", crear)
    importar_en(carpeta, [pagina(html, ficheros=[f.FicheroFalso("foto.png", PNG)])])
    assert "ya existía otro" in actividades_de(carpeta)[501]["detalle"]


def test_nombres_reservados_con_varios_puntos():
    assert nombre_de_recurso("con.tar.gz") == "_con.tar.gz"
    assert nombre_de_recurso("NUL.backup.txt") == "_NUL.backup.txt"
    assert nombre_de_recurso("console.txt") == "console.txt"


def test_crear_comprueba_el_destino_antes_de_crear_carpetas(carpeta, tmp_path):
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    try:
        (carpeta / "enlace").symlink_to(fuera, target_is_directory=True)
    except OSError:
        pytest.skip("sin enlaces simbólicos")
    with pytest.raises(ErrorImportar):
        importar._crear(carpeta / "enlace" / "nueva" / "x.html", b"x", carpeta.resolve())
    assert list(fuera.iterdir()) == []


def test_moodle_de_copia_json_solo_lleva_caracteres_seguros(carpeta):
    copia_en(carpeta, [pagina()])
    mbz = carpeta / "copia.mbz"
    from copia import fabrica as fab

    entradas = fab.entradas_de_copia(una_seccion(), [pagina()], curso=3)
    entradas["moodle_backup.xml"] = entradas["moodle_backup.xml"].replace(
        b"4.5.15 (Build: 20261005)", f"4.5 {chr(0x202E)} &amp; {'a' * 200}".encode()
    )
    mbz.write_bytes(fab.empaquetar(entradas))
    agente.importar("copia.mbz", carpeta)
    moodle = entrada_de(carpeta)["moodle"]
    assert re.fullmatch(r"[0-9A-Za-z.() +-]{1,60}", moodle)


def test_fichero_previo_fuera_del_destino_se_ignora(carpeta):
    importar_en(carpeta, [pagina()])
    ruta = carpeta / ".tiza" / "copia.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    (carpeta / "otro.html").write_text("mío", encoding="utf-8")
    datos["cursos"]["3"]["actividades"][0]["fichero"] = "otro.html"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    resumen = importar_en(carpeta, [pagina()])
    # El fichero apuntado está fuera del destino: no cuenta; el de siempre ya existía.
    assert resumen.estados["YA_IMPORTADO"] == 1
    assert (carpeta / "otro.html").read_text(encoding="utf-8") == "mío"
    assert actividades_de(carpeta)[501]["fichero"] == "aula/02-tema-1-intro/una-pagina-501.html"


def test_cuestionario_ya_importado_que_ahora_no_se_admite_conserva_fichero_y_huella(carpeta):
    importar_en(carpeta, [quiz_de(preguntas_basicas())])
    antes = actividades_de(carpeta)[510]
    assert antes["fichero"] and antes["huella_aula"]
    malo = [*preguntas_basicas(), pregunta(103, "P3", ((1, "x"),), "essay", ())]
    importar_en(carpeta, [quiz_de(malo)])
    ahora = actividades_de(carpeta)[510]
    assert ahora["estado"] == "PREGUNTAS_NO_ADMITIDAS"
    assert ahora["fichero"] == antes["fichero"] and ahora["huella_aula"] == antes["huella_aula"]


# --- Ronda de arreglos 2 -----------------------------------------------------------------

_URL_ANTIGUA = re.compile(
    r"""[^\s"'<>=]*?/(?:draftfile|pluginfile)\.php/\d+/(?:[^\s"'<>?#]*/)?"""
    r"""([^\s"'<>?#/]+)(?:\?[^\s"'<>#]*)?"""
)


def antigua(html: str) -> str:
    """Lo que daba la expresión regular de antes (cuadrática, pero con el corte de URL exacto)."""
    return _URL_ANTIGUA.sub(lambda m: f"@@PLUGINFILE@@/{m.group(1)}", html)


@pytest.mark.parametrize(
    "separador",
    [" ", "\t", "\n", "\r", "\f", "\v", "\x1c", "\x1d", "\x1e", "\x1f", "\x85", "\xa0"]
    + [chr(0x2003), chr(0x2028), chr(0x3000), chr(0x1680), chr(0x202F)],
)
def test_la_url_del_aula_se_corta_como_antes_en_cualquier_espacio(separador):
    from tiza.tipos.base import _ficheros_del_aula

    html = f"texto{separador}https://x/pluginfile.php/1/f/a.png"
    assert _ficheros_del_aula(html) == antigua(html) == f"texto{separador}@@PLUGINFILE@@/a.png"


def test_la_url_del_aula_igual_que_la_expresion_antigua_en_azar():
    import random

    from tiza.tipos.base import _ficheros_del_aula

    azar = random.Random(20261019)
    trozos = [
        "https://x/pluginfile.php/1/mod/a.png",
        "/draftfile.php/5/user/draft/9/b.jpg?x=1",
        "pluginfile.php/2/",
        "/pluginfile.php/3/f/",
        "a",
        "b/",
        "?",
        "#",
        "=",
        '"',
        "'",
        "<",
        ">",
        " ",
        "\n",
        "\xa0",
        chr(0x2003),
        "\x1f",
        "\x85",
        "src=",
        "@@PLUGINFILE@@/c.png",
    ]
    for _ in range(3000):
        html = "".join(azar.choice(trozos) for _ in range(azar.randint(1, 12)))
        assert _ficheros_del_aula(html) == antigua(html), repr(html)


def test_mismo_contenido_con_otras_mayusculas_apunta_a_un_fichero_que_existe(carpeta):
    html = '<img src="@@PLUGINFILE@@/Foto.png" alt="a"><img src="@@PLUGINFILE@@/foto.png" alt="b">'
    ficheros = [f.FicheroFalso("Foto.png", PNG), f.FicheroFalso("foto.png", PNG)]
    importar_en(carpeta, [pagina(html, ficheros=ficheros)])
    seccion = carpeta / "aula" / "02-tema-1-intro"
    cuerpo = (seccion / "una-pagina-501.html").read_text(encoding="utf-8")
    referencias = re.findall(r'src="(recursos/501/[^"]+)"', cuerpo)
    assert len(referencias) == 2 and referencias[0] == referencias[1]
    for referencia in referencias:
        assert (
            seccion / referencia
        ).is_file()  # el nombre exacto, también donde importan las mayúsculas
    assert len(list((seccion / "recursos" / "501").iterdir())) == 1
    assert actividades_de(carpeta)[501]["estado"] == "IMPORTADA"
    contenido.cargar(seccion / "una-pagina-501.html", raiz=carpeta.resolve())


def hacer_copia_json_raro(tipo, carpeta, tmp_path):
    ruta = carpeta / ".tiza" / "copia.json"
    ruta.parent.mkdir(exist_ok=True)
    if tipo == "directorio":
        ruta.mkdir()
    elif tipo == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("sin FIFO")
        os.mkfifo(ruta)
    else:
        destino = tmp_path / "carpeta"
        destino.mkdir()
        try:
            ruta.symlink_to(destino, target_is_directory=True)
        except OSError:
            pytest.skip("sin enlaces simbólicos")


@pytest.mark.parametrize("tipo", ["directorio", "fifo", "enlace_a_directorio"])
def test_copia_json_que_no_es_un_fichero_normal_es_invalido(carpeta, tmp_path, tipo):
    hacer_copia_json_raro(tipo, carpeta, tmp_path)
    with pytest.raises(estado.ErrorEstado) as info:
        estado.cargar_copia(carpeta / ".tiza")
    assert info.value.codigo == "COPIA_INVALIDA"
    copia_en(carpeta, [pagina()])
    with pytest.raises(ErrorImportar) as info:
        agente.importar("copia.mbz", carpeta)
    assert info.value.codigo == "COPIA_INVALIDA"
    assert not (carpeta / "aula").exists()


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
        "AJUSTES_NO_ADMITIDOS": 0,
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
    patron = re.compile(
        r"^\s*(?:from\s+\S*\bpublicar\b\S*\s+import|import\s+.*\bpublicar\b|from\s+\.\s+import\s+.*\bpublicar\b)",
        re.M,
    )
    for modulo in (importar, importar_cuestionario):
        assert not patron.search(Path(modulo.__file__).read_text(encoding="utf-8"))
    for ejemplo in (
        "from .publicar import X",
        "from tiza.publicar import X",
        "import tiza.publicar",
        "from . import config, publicar",
    ):
        assert patron.search(ejemplo)
