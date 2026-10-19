"""Tests del lector de copias de seguridad de Moodle: todo con copias sintéticas."""

from __future__ import annotations

import dataclasses
import io
import os
import stat
import struct
import tarfile
import time
import zipfile
import zlib
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


@pytest.mark.parametrize(
    "ajuste",
    [
        ("root", "role_assignments", "1"),
        ("root", "comments", "1"),
        ("root", "userscompletion", "1"),
        ("root", "logs", "1"),
        ("root", "grade_histories", "1"),
        ("root", "anonymize", "1"),
        ("root", "xapistate", "1"),
        ("activity", "page_1_userinfo", "1"),
        ("section", "section_7_userinfo", "1"),
        ("root", "logs", ""),
    ],
)
def test_un_ajuste_de_datos_de_usuario_que_no_vale_cero_es_una_copia_con_usuarios(tmp_path, ajuste):
    # Aunque ``users`` valga 0: cubre también la copia que el docente trae hecha a mano.
    secciones, actividades = f.copia_basica()
    error = error_de(tmp_path, secciones, actividades, users=0, ajustes=[ajuste])
    assert error.codigo == "COPIA_CON_USUARIOS"


def test_los_ajustes_a_cero_y_los_que_no_son_de_usuarios_no_molestan(tmp_path):
    secciones, actividades = f.copia_basica()
    ajustes = [
        ("root", "role_assignments", "0"),
        ("root", "logs", "0"),
        ("activity", "page_1_userinfo", "0"),
        # El formulario por defecto los trae a 1 y, sin ``users``, no llevan personas.
        ("root", "badges", "1"),
        ("root", "calendarevents", "1"),
        ("root", "groups", "1"),
    ]
    assert len(abrir(tmp_path, secciones, actividades, ajustes=ajustes).actividades) == 4


def test_los_ajustes_que_se_comprueban_estan_entre_los_que_publicar_fuerza_a_cero():
    from tiza import publicar

    assert copia.AJUSTES_CON_DATOS_DE_USUARIO <= publicar.AJUSTES_DE_USUARIO_COPIA


def test_users_xml_con_users_cero_tambien_se_rechaza(tmp_path):
    secciones, actividades, opciones = con_extra({"users.xml": b"<users/>"})
    assert error_de(tmp_path, secciones, actividades, **opciones).codigo == "COPIA_CON_USUARIOS"


def test_cmid_no_coincide(tmp_path):
    secciones, actividades = f.copia_basica()
    actividades[0].module_id = 777
    error = error_de(tmp_path, secciones, actividades)
    assert error.codigo == "COPIA_NO_VALIDA"
    assert "page_501" in error.detalle


@pytest.mark.parametrize("formato", FORMATOS)
def test_xml_con_entidades(tmp_path, formato):
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
    error = error_de(tmp_path, secciones, actividades, formato=formato)
    assert error.codigo == "COPIA_NO_VALIDA"
    assert "activities/page_501/page.xml" in error.detalle
    visible = f"{error.codigo} {error.detalle} {error!r} {error}"
    assert "SECRETO" not in visible and "lol" not in visible


@pytest.mark.parametrize(
    "doctype",
    [
        b'<!DOCTYPE a SYSTEM "http://example.invalid/a.dtd">',
        b"<!DOCTYPE a>",
        b'<!DOCTYPE a [<!ENTITY ll "lol">]>',
    ],
)
def test_cualquier_doctype_se_rechaza(tmp_path, doctype):
    secciones, actividades = f.copia_basica()
    actividades[0].xml_propio = (
        b'<?xml version="1.0"?>'
        + doctype
        + b'<activity id="9" moduleid="501" modulename="page" contextid="1501">'
        b'<page id="9"><name>X</name><content>y</content></page></activity>'
    )
    assert error_de(tmp_path, secciones, actividades).codigo == "COPIA_NO_VALIDA"


def test_ruta_con_barra_invertida_ignorada_o_rechazada(tmp_path):
    """Con ``\\`` en el nombre: tar y zip en POSIX la ignoran. En Windows, ``zipfile`` convierte
    ``\\`` en ``/`` al leer el directorio central (``ZipInfo``), así que la entrada se lee como
    ruta normal: la copia puede abrirse o rechazarse con ``COPIA_NO_VALIDA``, según el contenido.
    En ambos casos nada se escribe fuera ni sale otra excepción."""
    secciones, actividades = f.copia_basica()
    cuerpo = f._seccion(f.SeccionFalsa(id=996, numero=9, nombre="Colada"), [])
    extras = {"sections\\section_996\\section.xml": cuerpo}
    for formato in FORMATOS:
        if formato == "zip" and os.sep == "\\":
            try:
                abrir(tmp_path, secciones, actividades, formato=formato, extras=extras)
            except ErrorCopia as e:
                assert e.codigo == "COPIA_NO_VALIDA"
        else:
            c = abrir(tmp_path, secciones, actividades, formato=formato, extras=extras)
            assert [s.id for s in c.secciones] == [7]
            assert "Colada" not in "".join(textos(c))


@pytest.mark.parametrize("formato", FORMATOS)
def test_ruta_con_puntos_ignorada(tmp_path, formato):
    secciones, actividades = f.copia_basica()
    cuerpo = f._seccion(f.SeccionFalsa(id=999, numero=9, nombre="Colada"), [])
    extras = {
        "../../sections/section_999/section.xml": cuerpo,
        "/sections/section_998/section.xml": cuerpo,
        "sections/../sections/section_997/section.xml": cuerpo,
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


# --- Ronda de arreglos 1 -------------------------------------------------------------


def _zip_con_directorio(n=300):
    entradas = f.entradas_de_copia(*f.copia_basica())
    entradas.update({f"extra/{i}.txt": b"" for i in range(n)})
    return f.empaquetar(entradas, "zip")


def _forjar_zip64(datos: bytes) -> bytes:
    """Un zip cuyo EOCD clásico miente (directorio de 10 bytes) y cuyo registro zip64 dice la verdad."""
    eocd = datos.rfind(b"PK\x05\x06")
    cd_size, cd_off = struct.unpack("<LL", datos[eocd + 12 : eocd + 20])
    entradas = struct.unpack("<H", datos[eocd + 10 : eocd + 12])[0]
    registro = struct.pack(
        "<LQHHLLQQQQ", 0x06064B50, 44, 45, 45, 0, 0, entradas, entradas, cd_size, cd_off
    )
    localizador = struct.pack("<LLQL", 0x07064B50, 0, cd_off + cd_size, 1)
    falso = bytearray(datos[eocd:])
    struct.pack_into("<L", falso, 12, 10)
    return datos[:eocd] + registro + localizador + bytes(falso)


def test_zip64_falso_no_salta_el_limite_del_directorio(tmp_path, monkeypatch):
    datos = _zip_con_directorio()
    monkeypatch.setattr(copia, "MAX_DIRECTORIO_ZIP", 1000)
    # El zip normal pasa del límite del directorio...
    ruta = tmp_path / "normal.mbz"
    ruta.write_bytes(datos)
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_DEMASIADO_GRANDE"
    # ...y el forjado, que lo esconde tras un localizador zip64, también se rechaza.
    forjado = tmp_path / "forjado.mbz"
    forjado.write_bytes(_forjar_zip64(datos))
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(forjado)
    assert info.value.codigo in ("COPIA_NO_VALIDA", "COPIA_DEMASIADO_GRANDE")
    assert type(info.value) is ErrorCopia


def test_zip64_se_rechaza_aunque_el_directorio_sea_pequeno(tmp_path):
    ruta = tmp_path / "forjado.mbz"
    ruta.write_bytes(_forjar_zip64(_zip_con_directorio(5)))
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_NO_VALIDA"


def test_zip_con_demasiadas_entradas_segun_el_eocd(tmp_path):
    datos = bytearray(_zip_con_directorio(5))
    eocd = datos.rfind(b"PK\x05\x06")
    struct.pack_into("<H", datos, eocd + 10, copia.MAX_ENTRADAS + 1)
    ruta = tmp_path / "mentira.mbz"
    ruta.write_bytes(bytes(datos))
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_DEMASIADO_GRANDE"


def _con_preguntas(tmp_path, preguntas, formato="tar.gz"):
    secciones, actividades = f.copia_basica()
    actividades.append(f.ActividadFalsa(505, "quiz", 7, "Un test", preguntas=preguntas))
    return abrir(tmp_path, secciones, actividades, formato=formato).actividades[-1].preguntas


@pytest.mark.parametrize("formato", FORMATOS)
def test_pregunta_aleatoria_queda_como_random(tmp_path, formato):
    normal = f.PreguntaFalsa(entrada=111)
    aleatoria = f.PreguntaFalsa(entrada=0, modo="aleatoria")
    primera, segunda = _con_preguntas(tmp_path, [normal, aleatoria], formato)
    assert primera.tipo == "truefalse"
    assert (segunda.tipo, segunda.hueco, segunda.texto, segunda.entrada) == ("random", 2, "", 0)
    assert segunda.puntos == 1.0


def test_pregunta_que_no_esta_en_el_banco_queda_como_desconocida(tmp_path):
    (p,) = _con_preguntas(tmp_path, [f.PreguntaFalsa(entrada=222, modo="ausente")])
    assert (p.tipo, p.hueco, p.puntos) == ("desconocida", 1, 2.0)


def test_pregunta_sin_version_elegible_queda_como_desconocida(tmp_path):
    borrador = f.PreguntaFalsa(entrada=111, estado="draft")
    fijada_inexistente = f.PreguntaFalsa(entrada=112, fijada=9)
    primera, segunda = _con_preguntas(tmp_path, [borrador, fijada_inexistente])
    assert (primera.tipo, segunda.tipo) == ("desconocida", "desconocida")
    assert (primera.hueco, segunda.hueco) == (1, 2)


def test_huecos_conservan_su_orden(tmp_path):
    preguntas = [
        f.PreguntaFalsa(entrada=111),
        f.PreguntaFalsa(entrada=0, modo="aleatoria"),
        f.PreguntaFalsa(entrada=333, modo="ausente"),
    ]
    resultado = _con_preguntas(tmp_path, preguntas)
    assert [(p.hueco, p.tipo) for p in resultado] == [
        (1, "truefalse"),
        (2, "random"),
        (3, "desconocida"),
    ]


def test_la_ultima_version_ready_gana_a_una_mas_nueva_en_borrador(tmp_path):
    pregunta = f.PreguntaFalsa(
        entrada=111, versiones=[(1, "Vieja"), (2, "Lista"), (3, "Borrador", "draft")]
    )
    (p,) = _con_preguntas(tmp_path, [pregunta])
    assert (p.version, p.texto) == (2, "Lista")


def test_version_fijada_aunque_sea_borrador(tmp_path):
    pregunta = f.PreguntaFalsa(
        entrada=111, versiones=[(1, "Vieja", "draft"), (2, "Lista")], fijada=1
    )
    (p,) = _con_preguntas(tmp_path, [pregunta])
    assert (p.version, p.texto) == (1, "Vieja")


@pytest.mark.parametrize("valor", ["nan", "inf", "-inf", "Infinity"])
def test_numeros_no_finitos_se_rechazan(tmp_path, valor):
    secciones, actividades = f.copia_basica()
    entradas = f.entradas_de_copia(
        secciones,
        [*actividades, f.ActividadFalsa(505, "quiz", 7, "T", preguntas=[f.PreguntaFalsa(111)])],
    )
    entradas["questions.xml"] = entradas["questions.xml"].replace(
        b"<fraction>1.0</fraction>", f"<fraction>{valor}</fraction>".encode()
    )
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(f.empaquetar(entradas))
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_NO_VALIDA"


def test_opciones_solo_de_la_lista_blanca(tmp_path):
    secciones, actividades = f.copia_basica()
    entradas = f.entradas_de_copia(
        secciones,
        [*actividades, f.ActividadFalsa(505, "quiz", 7, "T", preguntas=[f.PreguntaFalsa(111)])],
    )
    entradas["questions.xml"] = entradas["questions.xml"].replace(
        b"<single>1</single>",
        b"<single>1</single><usermodified>987654</usermodified><shuffleanswers>0</shuffleanswers>",
    )
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(f.empaquetar(entradas))
    (pregunta,) = abrir_copia(ruta).actividades[-1].preguntas
    assert dict(pregunta.opciones) == {"single": "1", "shuffleanswers": "0"}
    assert "987654" not in repr(pregunta)


def test_mismo_cmid_en_dos_carpetas(tmp_path):
    secciones, actividades = f.copia_basica()
    actividades.append(f.ActividadFalsa(501, "label", 7, "Repetida"))
    error = error_de(tmp_path, secciones, actividades)
    assert error.codigo == "COPIA_NO_VALIDA"
    assert "501" in error.detalle


@pytest.mark.parametrize("formato", FORMATOS)
def test_recurso_que_no_coincide_con_su_huella(tmp_path, formato):
    secciones, actividades = f.copia_basica()
    actividades[0].ficheros = [f.FicheroFalso("a.png", b"verdadero")]
    entradas = f.entradas_de_copia(secciones, actividades)
    ruta_entrada = next(n for n in entradas if n.startswith("files/"))
    entradas[ruta_entrada] = b"cambiado por el camino"
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(f.empaquetar(entradas, formato))
    c = abrir_copia(ruta)
    with pytest.raises(ErrorCopia) as info:
        leer_recurso(c, c.actividades[0].ficheros[0].contenthash)
    assert info.value.codigo == "COPIA_NO_VALIDA"


def test_enlace_simbolico_dentro_de_un_zip_se_ignora(tmp_path):
    secciones, actividades = f.copia_basica()
    entradas = f.entradas_de_copia(secciones, actividades)
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as archivo:
        for nombre, datos in entradas.items():
            archivo.writestr(nombre, datos)
        enlace = zipfile.ZipInfo("sections/section_55/section.xml")
        enlace.external_attr = (stat.S_IFLNK | 0o777) << 16
        archivo.writestr(enlace, entradas["sections/section_7/section.xml"])
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(salida.getvalue())
    assert [s.id for s in abrir_copia(ruta).secciones] == [7]


def test_zip_con_file_size_falso(tmp_path):
    secciones, actividades = f.copia_basica()
    datos = bytearray(f.construir_mbz(secciones, actividades, formato="zip"))
    nombre = b"activities/page_501/page.xml"
    cabecera = datos.index(b"PK\x01\x02", datos.index(nombre) - 1000)
    # Busca la cabecera central de esa entrada (la que lleva su nombre tras 46 bytes).
    while datos[cabecera + 46 : cabecera + 46 + len(nombre)] != nombre:
        cabecera = datos.index(b"PK\x01\x02", cabecera + 1)
    struct.pack_into("<L", datos, cabecera + 24, 10)  # file_size: dice 10 bytes
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(bytes(datos))
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_NO_VALIDA"
    assert type(info.value) is ErrorCopia


# --- cabeceras extendidas de tar --------------------------------------------------------


def _tar_con_cabecera_extendida(tipo: bytes, declarado: int, ruta) -> None:
    """Un tar.gz cuya primera cabecera es extendida y declara ``declarado`` bytes de relleno.

    El relleno son ceros, que comprimen casi a nada: el fichero ocupa unos cientos de KB aunque
    declare cientos de MB (como la copia maliciosa de la revisión).
    """
    cabecera = tarfile.TarInfo("PaxHeader/x")
    cabecera.type = tipo
    cabecera.size = declarado
    crudo = cabecera.tobuf(tarfile.USTAR_FORMAT, "utf-8", "surrogateescape")
    compresor = zlib.compressobj(1, zlib.DEFLATED, 31)  # gzip
    trozo = b"\0" * (1024 * 1024)
    with ruta.open("wb") as salida:
        salida.write(compresor.compress(crudo))
        for _ in range(declarado // len(trozo)):
            salida.write(compresor.compress(trozo))
        salida.write(compresor.flush())


@pytest.mark.parametrize(
    "tipo", [tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK]
)
def test_cabecera_extendida_enorme_se_rechaza_sin_leerla(tmp_path, monkeypatch, tipo):
    ruta = tmp_path / "copia.mbz"
    _tar_con_cabecera_extendida(tipo, 300 * 1024 * 1024, ruta)
    assert ruta.stat().st_size < 2 * 1024 * 1024  # el fichero es pequeño
    leidos = []
    original = copia._Acotado.read

    def contar(self, n=-1):
        datos = original(self, n)
        leidos.append(len(datos))
        return datos

    monkeypatch.setattr(copia._Acotado, "read", contar)
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_NO_VALIDA"
    assert "cabecera" in info.value.detalle
    assert sum(leidos) < 64 * 1024  # solo se leyó el bloque de cabecera, no los 300 MB


def test_cabecera_extendida_pequena_sigue_funcionando(tmp_path):
    # Una cabecera pax pequeña y legítima (nombre largo) sigue funcionando.
    secciones, actividades = f.copia_basica()
    datos = f.construir_mbz(secciones, actividades)
    salida = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(datos), mode="r:gz") as origen,
        tarfile.open(fileobj=salida, mode="w:gz", format=tarfile.PAX_FORMAT) as destino,
    ):
        for miembro in origen.getmembers():
            destino.addfile(miembro, origen.extractfile(miembro))
        largo = tarfile.TarInfo("extra/" + "n" * 300 + ".bin")
        largo.size = 3
        destino.addfile(largo, io.BytesIO(b"abc"))
    ruta = tmp_path / "copia.mbz"
    ruta.write_bytes(salida.getvalue())
    assert [s.id for s in abrir_copia(ruta).secciones] == [7]


def test_la_api_privada_de_tarfile_sigue_ahi(tmp_path, monkeypatch):
    """El límite de cabeceras se apoya en ``TarInfo._proc_member``: si cambia, este test falla."""
    assert callable(getattr(tarfile.TarInfo, "_proc_member", None))
    assert callable(getattr(tarfile.TarInfo, "_proc_pax", None))
    assert callable(getattr(tarfile.TarInfo, "_proc_gnulong", None))
    assert tarfile.TarInfo.fromtarfile.__func__ is not None
    # ``tarfile`` sigue llamando a ``_proc_member`` de la subclase que se le pasa en ``tarinfo``.
    llamadas = []
    original = copia._TarInfoAcotado._proc_member

    def espiar(self, tar):
        llamadas.append(self.type)
        return original(self, tar)

    monkeypatch.setattr(copia._TarInfoAcotado, "_proc_member", espiar)
    secciones, actividades = f.copia_basica()
    abrir(tmp_path, secciones, actividades)
    assert llamadas
    # Y una cabecera de 2 MiB (más del límite) se rechaza por el límite, no por casualidad.
    ruta = tmp_path / "grande.mbz"
    _tar_con_cabecera_extendida(tarfile.XHDTYPE, 2 * 1024 * 1024, ruta)
    with pytest.raises(ErrorCopia) as info:
        abrir_copia(ruta)
    assert info.value.codigo == "COPIA_NO_VALIDA"
    assert "cabecera de archivo demasiado grande" in info.value.detalle


# --- tolerancia de las numéricas (estructura real de Moodle 4.5) ------------------------


@pytest.mark.parametrize("antigua", [False, True])
def test_la_tolerancia_numerica_se_lee_de_numerical_records(tmp_path, antigua):
    numerica = f.PreguntaFalsa(
        entrada=111,
        tipo="numerical",
        respuestas=(("3.14", 1.0), ("3.1416", 0.5)),
        tolerancia=0.005,
        tolerancia_antigua=antigua,
    )
    (p,) = _con_preguntas(tmp_path, [numerica])
    assert [r.tolerancia for r in p.respuestas] == [0.005, 0.005]


def test_la_fabrica_escribe_la_estructura_real_de_la_numerica(tmp_path):
    numerica = f.PreguntaFalsa(entrada=111, tipo="numerical", tolerancia=0.005)
    secciones, actividades = f.copia_basica()
    actividades.append(f.ActividadFalsa(505, "quiz", 7, "Un test", preguntas=[numerica]))
    xml = f.construir_mbz(secciones, actividades)
    with tarfile.open(fileobj=io.BytesIO(xml), mode="r:gz") as tar:
        preguntas = tar.extractfile("questions.xml").read().decode()
    assert "<numerical_records><numerical_record" in preguntas
    assert "<numerical_answers>" not in preguntas
    assert "<numerical_units></numerical_units>" in preguntas


def test_una_numerica_sin_tolerancia_en_la_copia_vale_cero(tmp_path):
    numerica = f.PreguntaFalsa(entrada=111, tipo="numerical", respuestas=(("2", 1.0),))
    (p,) = _con_preguntas(tmp_path, [numerica])
    assert [r.tolerancia for r in p.respuestas] == [0.0]


def test_la_fecha_de_la_copia_sale_de_backup_date(tmp_path):
    secciones, actividades = f.copia_basica()
    datos = abrir(tmp_path, secciones, actividades, fecha=1792800000)
    assert datos.fecha == datetime.fromtimestamp(1792800000, tz=UTC)
    assert abrir(tmp_path, secciones, actividades).fecha is None
