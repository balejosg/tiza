"""Tests del lector de copias de seguridad de Moodle: todo con copias sintéticas."""

from __future__ import annotations

import dataclasses
import io
import os
import tarfile
import time
from datetime import UTC, datetime

import pytest

from copia import fabrica as f
from tiza import ayuda, copia
from tiza.copia import ErrorCopia, abrir_copia, leer_recurso

FORMATOS = ["tar.gz", "zip"]


def abrir(tmp_path, secciones, actividades, **opciones):
    ruta = f.escribir_mbz(tmp_path / "copia.mbz", secciones, actividades, **opciones)
    return abrir_copia(ruta)


def error_de(tmp_path, secciones, actividades, **opciones) -> ErrorCopia:
    with pytest.raises(ErrorCopia) as info:
        abrir(tmp_path, secciones, actividades, **opciones)
    return info.value


def con_extra(extras, formato="tar.gz"):
    secciones, actividades = f.copia_basica()
    return secciones, actividades, {"formato": formato, "extras": extras}


def textos(objeto):
    """Todos los textos que cuelgan de un objeto de la copia (dataclasses, tuplas, mapas)."""
    if isinstance(objeto, str):
        yield objeto
    elif dataclasses.is_dataclass(objeto):
        for campo in dataclasses.fields(objeto):
            if campo.repr:
                yield from textos(getattr(objeto, campo.name))
    elif isinstance(objeto, dict | type(copia.MappingProxyType({}))):
        for clave, valor in objeto.items():
            yield from textos(clave)
            yield from textos(valor)
    elif isinstance(objeto, tuple | list):
        for elemento in objeto:
            yield from textos(elemento)
    elif objeto is not None:
        yield str(objeto)


@pytest.mark.parametrize("formato", FORMATOS)
def test_copia_basica(tmp_path, formato):
    secciones, actividades = f.copia_basica()
    c = abrir(tmp_path, secciones, actividades, formato=formato, curso=42)
    assert c.curso_original == 42
    assert c.moodle.startswith("4.5")
    assert c.servidor == "https://aula.example.org"
    assert [(a.cmid, a.modulo, a.seccion_id) for a in c.actividades] == [
        (501, "page", 7),
        (502, "assign", 7),
        (503, "label", 7),
        (504, "forum", 7),
    ]
    pagina, tarea, etiqueta, foro = c.actividades
    assert (pagina.nombre, pagina.html, pagina.visible) == ("Una página", "<p>Hola</p>", True)
    assert (tarea.html, tarea.visible) == ("<p>Entrega</p>", False)
    assert etiqueta.html == "<p>Aviso</p>"
    assert foro.nombre == "Un foro"
    (seccion,) = c.secciones
    assert (seccion.id, seccion.numero, seccion.nombre) == (7, 1, "Tema 1")
    assert seccion.resumen_html == "<p>Resumen</p>"
    assert seccion.orden_actividades == (501, 502, 503, 504)


def test_copia_zip_antigua(tmp_path):
    secciones, actividades = f.copia_basica()
    tar = abrir(tmp_path, secciones, actividades, formato="tar.gz")
    zip_ = abrir(tmp_path, secciones, actividades, formato="zip")
    assert zip_.actividades == tar.actividades
    assert zip_.secciones == tar.secciones


def test_fechas_en_utc_y_cero_es_none(tmp_path):
    secciones, actividades = f.copia_basica()
    cuestionario = f.ActividadFalsa(
        505, "quiz", 7, "Un test", fechas={"timeopen": 1792447200, "timeclose": 0}
    )
    c = abrir(tmp_path, secciones, [*actividades, cuestionario])
    tarea = next(a for a in c.actividades if a.cmid == 502)
    assert tarea.fechas == {
        "allowsubmissionsfromdate": datetime.fromtimestamp(1792447200, tz=UTC),
        "duedate": datetime.fromtimestamp(1795215540, tz=UTC),
        "cutoffdate": None,
    }
    assert tarea.fechas["duedate"].tzinfo == UTC
    quiz = next(a for a in c.actividades if a.cmid == 505)
    assert quiz.fechas["timeclose"] is None
    assert quiz.fechas["timeopen"].year == 2026
    assert next(a for a in c.actividades if a.cmid == 501).fechas == {}


@pytest.mark.parametrize("formato", FORMATOS)
def test_copia_con_usuarios(tmp_path, formato):
    secciones, actividades = f.copia_basica()
    error = error_de(tmp_path, secciones, actividades, users=1, formato=formato)
    assert error.codigo == "COPIA_CON_USUARIOS"
    assert ayuda.explicar("COPIA_CON_USUARIOS")


def test_users_xml_con_users_cero_tambien_se_rechaza(tmp_path):
    secciones, actividades, opciones = con_extra({"users.xml": b"<users/>"})
    assert error_de(tmp_path, secciones, actividades, **opciones).codigo == "COPIA_CON_USUARIOS"


def test_cmid_no_coincide(tmp_path):
    secciones, actividades = f.copia_basica()
    actividades[0].module_id = 777
    error = error_de(tmp_path, secciones, actividades)
    assert error.codigo == "COPIA_NO_VALIDA"
    assert "page_501" in error.detalle


def test_xml_con_entidades(tmp_path):
    secreto = tmp_path / "secreto.txt"
    secreto.write_text("CONTENIDO-SECRETO-DEL-FICHERO", encoding="utf-8")
    xml = (
        f'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY xxe SYSTEM "{secreto.as_uri()}">'
        '<!ENTITY ll "lol">]>'
        '<activity id="9" moduleid="501" modulename="page" contextid="1501"><page id="9">'
        "<name>Con entidad</name><content>&xxe; y &ll;</content></page></activity>"
    ).encode()
    secciones, actividades = f.copia_basica()
    actividades[0].xml_propio = xml
    c = abrir(tmp_path, secciones, actividades)
    pagina = c.actividades[0]
    assert pagina.nombre == "Con entidad"
    assert "CONTENIDO-SECRETO" not in "".join(textos(c))
    assert "lol" not in pagina.html


@pytest.mark.parametrize("formato", FORMATOS)
def test_ruta_con_puntos_ignorada(tmp_path, formato):
    secciones, actividades = f.copia_basica()
    cuerpo = f._seccion(f.SeccionFalsa(id=999, numero=9, nombre="Colada"), [])
    extras = {
        "../../sections/section_999/section.xml": cuerpo,
        "/sections/section_998/section.xml": cuerpo,
        "sections/../sections/section_997/section.xml": cuerpo,
        "sections\\section_996\\section.xml": cuerpo,
        "C:/sections/section_995/section.xml": cuerpo,
        "../../evil.xml": b"<evil/>",
    }
    c = abrir(tmp_path, secciones, actividades, formato=formato, extras=extras)
    assert [s.id for s in c.secciones] == [7]
    assert "Colada" not in "".join(textos(c))
    assert not any("evil" in n for n, _ in c.recursos.values())
    assert not (tmp_path.parent / "evil.xml").exists()


def test_no_extrae_nada_a_disco(tmp_path):
    carpeta = tmp_path / "solo-la-copia"
    carpeta.mkdir()
    secciones, actividades = f.copia_basica()
    actividades[0].ficheros = [f.FicheroFalso("a.png", b"png")]
    ruta = f.escribir_mbz(carpeta / "copia.mbz", secciones, actividades)
    antes = sorted(os.listdir(carpeta))
    c = abrir_copia(ruta)
    leer_recurso(c, c.actividades[0].ficheros[0].contenthash)
    assert sorted(os.listdir(carpeta)) == antes == ["copia.mbz"]


def test_enlaces_y_dispositivos_ignorados(tmp_path):
    secciones, actividades = f.copia_basica()
    datos = f.construir_mbz(secciones, actividades)
    salida = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(datos), mode="r:gz") as origen,
        tarfile.open(fileobj=salida, mode="w:gz") as destino,
    ):
        for miembro in origen.getmembers():
            destino.addfile(miembro, origen.extractfile(miembro))
        enlace = tarfile.TarInfo("sections/section_55/section.xml")
        enlace.type = tarfile.SYMTYPE
        enlace.linkname = "sections/section_7/section.xml"
        destino.addfile(enlace)
        dispositivo = tarfile.TarInfo("activities/page_600/module.xml")
        dispositivo.type = tarfile.CHRTYPE
        destino.addfile(dispositivo)
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(salida.getvalue())
    c = abrir_copia(ruta)
    assert [s.id for s in c.secciones] == [7]
    assert 600 not in [a.cmid for a in c.actividades]


@pytest.mark.parametrize("formato", FORMATOS)
def test_demasiadas_entradas(tmp_path, formato):
    secciones, actividades = f.copia_basica()
    extras = [(f"extra/{n}.txt", b"") for n in range(copia.MAX_ENTRADAS + 1)]
    inicio = time.monotonic()
    error = error_de(tmp_path, secciones, actividades, formato=formato, extras=extras)
    assert error.codigo == "COPIA_DEMASIADO_GRANDE"
    assert time.monotonic() - inicio < 30  # 20 001 entradas reales, sin tocar el límite


def test_justo_en_el_limite_de_entradas_se_abre(tmp_path, monkeypatch):
    secciones, actividades = f.copia_basica()
    total = len(f.entradas_de_copia(secciones, actividades))
    monkeypatch.setattr(copia, "MAX_ENTRADAS", total + 3)
    extras = [(f"extra/{n}.txt", b"") for n in range(3)]
    assert len(abrir(tmp_path, secciones, actividades, extras=extras).actividades) == 4
    extras.append(("extra/4.txt", b""))
    assert error_de(tmp_path, secciones, actividades, extras=extras).codigo == (
        "COPIA_DEMASIADO_GRANDE"
    )


@pytest.mark.parametrize("formato", FORMATOS)
def test_preguntas_ultima_version(tmp_path, formato):
    secciones, actividades = f.copia_basica()
    pregunta = f.PreguntaFalsa(
        entrada=111,
        versiones=[(1, "Texto viejo"), (2, "Texto nuevo")],
        tipo="multichoice",
        respuestas=[("Sí", 1.0), ("No", 0.0)],
    )
    actividades.append(f.ActividadFalsa(505, "quiz", 7, "Un test", preguntas=[pregunta]))
    c = abrir(tmp_path, secciones, actividades, formato=formato)
    (p,) = next(a for a in c.actividades if a.cmid == 505).preguntas
    assert (p.entrada, p.version, p.texto, p.tipo) == (111, 2, "Texto nuevo", "multichoice")
    assert p.puntos == 2.0 and p.hueco == 1
    assert [(r.texto, r.fraccion) for r in p.respuestas] == [("Sí", 1.0), ("No", 0.0)]
    assert p.opciones["single"] == "1"


def test_pregunta_con_version_fijada(tmp_path):
    secciones, actividades = f.copia_basica()
    pregunta = f.PreguntaFalsa(111, versiones=[(1, "Fijada"), (2, "Nueva")], fijada=1)
    actividades.append(f.ActividadFalsa(505, "quiz", 7, "Un test", preguntas=[pregunta]))
    c = abrir(tmp_path, secciones, actividades)
    assert c.actividades[-1].preguntas[0].texto == "Fijada"


def test_no_lee_datos_de_usuario(tmp_path):
    secciones, actividades = f.copia_basica()
    actividades[0].ficheros = [f.FicheroFalso("a.png", b"png")]
    actividades.append(
        f.ActividadFalsa(505, "quiz", 7, "Un test", preguntas=[f.PreguntaFalsa(entrada=111)])
    )
    ruta = f.escribir_mbz(tmp_path / "copia.mbz", secciones, actividades)
    c = abrir_copia(ruta)
    todo = "\n".join(textos(c))
    for valor in f.DATOS_DE_USUARIO:
        assert valor not in todo
        assert valor not in repr(c)
    nombres = {
        campo.name
        for clase in (
            copia.Copia,
            copia.ActividadCopia,
            copia.SeccionCopia,
            copia.FicheroCopia,
            copia.PreguntaCopia,
            copia.RespuestaCopia,
        )
        for campo in dataclasses.fields(clase)
    }
    assert not nombres & {"author", "userid", "createdby", "modifiedby"}


def test_la_fabrica_si_pone_datos_de_usuario():
    # Sin esto, el test anterior pasaría en falso.
    secciones, actividades = f.copia_basica()
    entradas = f.entradas_de_copia(secciones, actividades)
    assert f.AUTOR.encode() in entradas["activities/assign_502/assign.xml"]
    assert f.USUARIO.encode() in entradas["activities/assign_502/assign.xml"]


def test_dataclasses_inmutables(tmp_path):
    secciones, actividades = f.copia_basica()
    c = abrir(tmp_path, secciones, actividades)
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.actividades[0].nombre = "otro"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.secciones[0].nombre = "otro"  # type: ignore[misc]
    with pytest.raises(TypeError):
        c.actividades[1].fechas["duedate"] = None  # type: ignore[index]


@pytest.mark.parametrize("formato", FORMATOS)
def test_ficheros_y_recursos(tmp_path, formato):
    secciones, actividades = f.copia_basica()
    actividades[0].ficheros = [
        f.FicheroFalso("punto.png", b"PNG-de-prueba"),
        f.FicheroFalso("otro.pdf", b"%PDF-1.4 falso", filearea="attachment"),
    ]
    actividades.append(
        f.ActividadFalsa(
            506,
            "h5pactivity",
            7,
            "Interactivo",
            ficheros=[f.FicheroFalso("a.h5p", b"paquete", filearea="package")],
        )
    )
    c = abrir(tmp_path, secciones, actividades, formato=formato)
    pagina = c.actividades[0]
    assert [(x.nombre, x.filearea) for x in pagina.ficheros] == [
        ("otro.pdf", "attachment"),
        ("punto.png", "content"),
    ]
    h5p = c.actividades[-1]
    assert h5p.paquete_h5p == h5p.ficheros[0].contenthash
    assert pagina.paquete_h5p is None
    punto = next(x for x in pagina.ficheros if x.nombre == "punto.png")
    assert leer_recurso(c, punto.contenthash) == b"PNG-de-prueba"
    assert leer_recurso(c, h5p.paquete_h5p) == b"paquete"
    # El directorio ('.') y los vacíos no cuentan como ficheros.
    assert all(x.nombre != "." for a in c.actividades for x in a.ficheros)


@pytest.mark.parametrize("formato", FORMATOS)
def test_leer_recurso_desconocido(tmp_path, formato):
    secciones, actividades = f.copia_basica()
    c = abrir(tmp_path, secciones, actividades, formato=formato)
    for hash_ in ("0" * 40, "../../etc/passwd", ""):
        with pytest.raises(ErrorCopia) as info:
            leer_recurso(c, hash_)
        assert info.value.codigo == "COPIA_NO_VALIDA"


@pytest.mark.parametrize("formato", FORMATOS)
def test_recurso_demasiado_grande(tmp_path, formato, monkeypatch):
    secciones, actividades = f.copia_basica()
    actividades[0].ficheros = [f.FicheroFalso("video.mp4", b"x" * 5000)]
    c = abrir(tmp_path, secciones, actividades, formato=formato)
    monkeypatch.setattr(copia, "MAX_RECURSO", 1000)
    with pytest.raises(ErrorCopia) as info:
        leer_recurso(c, c.actividades[0].ficheros[0].contenthash)
    assert info.value.codigo == "COPIA_DEMASIADO_GRANDE"
    # Abrir la copia con un vídeo enorme no falla: solo falla pedirlo.
    assert len(abrir(tmp_path, secciones, actividades, formato=formato).actividades) == 4


@pytest.mark.parametrize("formato", FORMATOS)
def test_recurso_que_crece_mientras_se_lee(tmp_path, formato, monkeypatch):
    # El tamaño declarado en la cabecera no es de fiar: se vuelve a comprobar al leer.
    secciones, actividades = f.copia_basica()
    actividades[0].ficheros = [f.FicheroFalso("v.mp4", b"x" * 5000)]
    c = abrir(tmp_path, secciones, actividades, formato=formato)
    nombre, _ = c.recursos[c.actividades[0].ficheros[0].contenthash]
    falsa = dataclasses.replace(
        c, recursos={c.actividades[0].ficheros[0].contenthash: (nombre, 10)}
    )
    monkeypatch.setattr(copia, "MAX_RECURSO", 1000)
    with pytest.raises(ErrorCopia) as info:
        leer_recurso(falsa, c.actividades[0].ficheros[0].contenthash)
    assert info.value.codigo == "COPIA_DEMASIADO_GRANDE"


@pytest.mark.parametrize("formato", FORMATOS)
def test_xml_demasiado_grande(tmp_path, formato, monkeypatch):
    secciones, actividades = f.copia_basica()
    monkeypatch.setattr(copia, "MAX_XML", 400)
    error = error_de(tmp_path, secciones, actividades, formato=formato)
    assert error.codigo == "COPIA_DEMASIADO_GRANDE"


def test_demasiado_descomprimido(tmp_path, monkeypatch):
    secciones, actividades = f.copia_basica()
    extras = {"extra/relleno.bin": b"\0" * 200_000}
    monkeypatch.setattr(copia, "MAX_DESCOMPRIMIDO", 100_000)
    assert error_de(tmp_path, secciones, actividades, extras=extras).codigo == (
        "COPIA_DEMASIADO_GRANDE"
    )
    assert error_de(tmp_path, secciones, actividades, extras=extras, formato="zip").codigo == (
        "COPIA_DEMASIADO_GRANDE"
    )


def test_fichero_demasiado_grande(tmp_path, monkeypatch):
    secciones, actividades = f.copia_basica()
    ruta = f.escribir_mbz(tmp_path / "copia.mbz", secciones, actividades)
    monkeypatch.setattr(copia, "MAX_COPIA", 100)
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_DEMASIADO_GRANDE"


def test_directorio_central_de_zip_enorme(tmp_path, monkeypatch):
    secciones, actividades = f.copia_basica()
    monkeypatch.setattr(copia, "MAX_DIRECTORIO_ZIP", 100)
    assert error_de(tmp_path, secciones, actividades, formato="zip").codigo == (
        "COPIA_DEMASIADO_GRANDE"
    )


def test_formato_desconocido(tmp_path):
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(b"esto no es una copia, ni de lejos")
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_NO_VALIDA"


def test_fichero_que_no_existe_o_es_una_carpeta(tmp_path):
    for ruta in (tmp_path / "no-existe.mbz", tmp_path):
        with pytest.raises(ErrorCopia) as info:
            abrir_copia(ruta)
        assert info.value.codigo == "COPIA_NO_VALIDA"


def test_enlace_simbolico_rechazado(tmp_path):
    secciones, actividades = f.copia_basica()
    real = f.escribir_mbz(tmp_path / "real.mbz", secciones, actividades)
    enlace = tmp_path / "enlace.mbz"
    try:
        enlace.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("sin enlaces simbólicos")
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(enlace)
    assert info.value.codigo == "COPIA_NO_VALIDA"


@pytest.mark.parametrize("formato", FORMATOS)
def test_copia_truncada_sin_excepciones_de_libreria(tmp_path, formato):
    secciones, actividades = f.copia_basica()
    datos = f.construir_mbz(secciones, actividades, formato=formato)
    for corte in (len(datos) // 2, len(datos) - 10, 30):
        ruta = tmp_path / "corta.mbz"
        ruta.write_bytes(datos[:corte])
        with pytest.raises(ErrorCopia) as info:
            abrir_copia(ruta)
        assert info.value.codigo == "COPIA_NO_VALIDA"
        assert type(info.value) is ErrorCopia


def test_gzip_corrupto_en_mitad(tmp_path):
    secciones, actividades = f.copia_basica()
    datos = bytearray(f.construir_mbz(secciones, actividades))
    for n in range(len(datos) // 3, len(datos) // 3 + 40):
        datos[n] ^= 0xFF
    ruta = tmp_path / "rota.mbz"
    ruta.write_bytes(bytes(datos))
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_NO_VALIDA"
    assert "gzip" not in info.value.detalle.lower()


def test_sin_moodle_backup(tmp_path):
    datos = f.empaquetar({"otra-cosa.xml": b"<a/>"})
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(datos)
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_NO_VALIDA"
    assert "moodle_backup.xml" in info.value.detalle


def test_xml_mal_formado_nombra_la_entrada(tmp_path):
    secciones, actividades, opciones = con_extra({})
    entradas = f.entradas_de_copia(secciones, actividades)
    entradas["activities/page_501/page.xml"] = b"<activity><page>sin cerrar"
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(f.empaquetar(entradas))
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_NO_VALIDA"
    assert "activities/page_501/page.xml" in info.value.detalle
    assert "line" not in info.value.detalle.lower()


def test_sin_ajuste_de_usuarios_no_se_abre(tmp_path):
    secciones, actividades = f.copia_basica()
    entradas = f.entradas_de_copia(secciones, actividades)
    entradas["moodle_backup.xml"] = entradas["moodle_backup.xml"].replace(b"users", b"otra")
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(f.empaquetar(entradas))
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_NO_VALIDA"


def test_nombre_de_entrada_hostil_no_llega_al_detalle(tmp_path):
    secciones, actividades = f.copia_basica()
    entradas = f.entradas_de_copia(secciones, actividades)
    entradas["sections/section_7/section.xml"] = b"<a>"
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(f.empaquetar(entradas))
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert all(c.isprintable() for c in info.value.detalle)


def test_nombre_hostil_se_sanea():
    assert copia._nombre_para_mensaje("a/<b>\n\u202e.xml") == "a/?b???.xml"
    assert len(copia._nombre_para_mensaje("x" * 500)) == 80


def test_los_codigos_tienen_explicacion():
    for codigo in ("COPIA_NO_VALIDA", "COPIA_DEMASIADO_GRANDE", "COPIA_CON_USUARIOS"):
        assert ayuda.explicar(codigo)


def test_actividad_sin_xml_propio_usa_el_titulo_de_la_copia(tmp_path):
    secciones, actividades = f.copia_basica()
    entradas = f.entradas_de_copia(secciones, actividades)
    del entradas["activities/forum_504/forum.xml"]
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(f.empaquetar(entradas))
    foro = next(a for a in abrir_copia(ruta).actividades if a.cmid == 504)
    assert (foro.nombre, foro.html) == ("Un foro", "")
