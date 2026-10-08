"""Tests hostiles del paquete .h5p subido: validación y reempaquetado."""

from __future__ import annotations

import io
import json
import warnings
import zipfile
from pathlib import Path

import pytest

from tiza.contenido import ErrorContenido

PAQUETE_MINIMO = {
    "h5p.json": {
        "title": "Paquete de prueba",
        "language": "es",
        "mainLibrary": "H5P.Blanks",
        "embedTypes": ["iframe"],
        "preloadedDependencies": [
            {"machineName": "H5P.Blanks", "majorVersion": 1, "minorVersion": 14}
        ],
    },
    "content/content.json": {"questions": ["El agua hierve a *100*."]},
}


def escribir_paquete(
    tmp_path: Path,
    ficheros: dict[str, str | bytes | dict],
    nombre: str = "paquete.h5p",
    *,
    cifrado: str | None = None,
    enlace: str | None = None,
    fecha_bomba: str | None = None,
) -> Path:
    ruta = tmp_path / nombre
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as zip_:
        for ruta_interna, datos in ficheros.items():
            if isinstance(datos, dict):
                datos = json.dumps(datos)
            if isinstance(datos, str):
                datos = datos.encode("utf-8")
            if ruta_interna == enlace:
                info = zipfile.ZipInfo(ruta_interna)
                info.external_attr = 0o120777 << 16  # S_IFLNK
                zip_.writestr(info, b"destino")
            elif ruta_interna == cifrado:
                info = zipfile.ZipInfo(ruta_interna)
                info.flag_bits |= 0x1
                zip_.writestr(info, b"cifrado")
            elif ruta_interna == fecha_bomba:
                info = zipfile.ZipInfo(ruta_interna)
                info.compress_type = zipfile.ZIP_DEFLATED
                zip_.writestr(info, b"\0" * (1024 * 1024))
            else:
                zip_.writestr(ruta_interna, datos)
    return ruta


def paquete_completo(tmp_path: Path, extra: dict | None = None) -> Path:
    ficheros: dict = {
        **{clave: valor for clave, valor in PAQUETE_MINIMO.items()},
        "content/img/figura.png": b"\x89PNG",
        "content/audio/voz.mp3": b"mp3",
        "H5P.Blanks-1.14/library.json": '{"machineName":"H5P.Blanks"}',
        "H5P.Blanks-1.14/js/blanks.js": b"console.log('x')",
        "FontAwesome-4.5/fonts/font.woff": b"woff",
    }
    ficheros.update(extra or {})
    return escribir_paquete(tmp_path, ficheros)


def test_paquete_valido_se_valida_y_descarta_librerias(tmp_path):
    from tiza.h5p import validar_paquete

    validado = validar_paquete(paquete_completo(tmp_path))
    assert validado.nombre == "paquete.h5p"
    assert validado.titulo == "Paquete de prueba"
    assert validado.libreria == "H5P.Blanks 1.14"
    assert set(validado.descartadas) == {"H5P.Blanks-1.14", "FontAwesome-4.5"}
    assert "content/content.json" in validado.ficheros
    assert "content/img/figura.png" in validado.ficheros
    assert all(not fichero.startswith("H5P.") for fichero in validado.ficheros)


def test_reempaquetar_quita_librerias_y_es_determinista(tmp_path):
    from tiza.h5p import reempaquetar

    ruta = paquete_completo(tmp_path)
    primero = reempaquetar(ruta)
    segundo = reempaquetar(ruta)
    assert primero == segundo
    with zipfile.ZipFile(io.BytesIO(primero)) as zip_:
        nombres = zip_.namelist()
        assert "H5P.Blanks-1.14/library.json" not in nombres
        assert "FontAwesome-4.5/fonts/font.woff" not in nombres
        assert nombres == [
            "content/audio/voz.mp3",
            "content/content.json",
            "content/img/figura.png",
            "h5p.json",
        ]
        h5p = json.loads(zip_.read("h5p.json"))
        assert h5p["mainLibrary"] == "H5P.Blanks"
        assert "license" not in h5p  # el esquema se reduce a lo necesario


def test_reempaquetar_desecha_campos_desconocidos_de_h5p_json(tmp_path):
    from tiza.h5p import reempaquetar

    h5p = dict(PAQUETE_MINIMO["h5p.json"])
    h5p["campo_raro"] = {"a": 1}
    h5p["license"] = "U"
    ruta = escribir_paquete(
        tmp_path, {"h5p.json": h5p, "content/content.json": PAQUETE_MINIMO["content/content.json"]}
    )
    with zipfile.ZipFile(io.BytesIO(reempaquetar(ruta))) as zip_:
        escrito = json.loads(zip_.read("h5p.json"))
    assert "campo_raro" not in escrito and "license" not in escrito
    assert escrito["title"] == "Paquete de prueba"


@pytest.mark.parametrize(
    "ruta_interna",
    ["../fuera.txt", "/absoluta.txt", "content/../../fuera.txt", "C:/windows.txt", "a\\b.txt"],
)
def test_rechaza_rutas_que_se_salen(tmp_path, ruta_interna):
    from tiza.h5p import validar_paquete

    ruta = escribir_paquete(
        tmp_path,
        {**PAQUETE_MINIMO, ruta_interna: b"x"},  # type: ignore[dict-item]
    )
    with pytest.raises(ErrorContenido) as exc:
        validar_paquete(ruta)
    assert exc.value.codigo == "PAQUETE_H5P_INVALIDO"


def test_rechaza_enlace_simbolico(tmp_path):
    from tiza.h5p import validar_paquete

    ruta = escribir_paquete(
        tmp_path, {**PAQUETE_MINIMO, "content/enlace": b"x"}, enlace="content/enlace"
    )
    with pytest.raises(ErrorContenido) as exc:
        validar_paquete(ruta)
    assert exc.value.codigo == "PAQUETE_H5P_INVALIDO"


def test_rechaza_cifrado(tmp_path):
    from tiza.h5p import validar_paquete

    ruta = escribir_paquete(
        tmp_path, {**PAQUETE_MINIMO, "content/secreto.bin": b"x"}, cifrado="content/secreto.bin"
    )
    with pytest.raises(ErrorContenido) as exc:
        validar_paquete(ruta)
    assert exc.value.codigo == "PAQUETE_H5P_INVALIDO"


def test_rechaza_bomba_zip(tmp_path):
    from tiza.h5p import validar_paquete

    ruta = escribir_paquete(
        tmp_path, {**PAQUETE_MINIMO, "content/relleno.bin": b"x"}, fecha_bomba="content/relleno.bin"
    )
    with pytest.raises(ErrorContenido) as exc:
        validar_paquete(ruta)
    assert exc.value.codigo == "PAQUETE_H5P_DEMASIADO_GRANDE"


def test_rechaza_duplicados(tmp_path, monkeypatch):
    from tiza import h5p

    monkeypatch.setattr(h5p, "MAX_ENTRADAS_H5P", 100)
    ruta = tmp_path / "duplicado.h5p"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # zipfile avisa del nombre duplicado
        with zipfile.ZipFile(ruta, "w") as zip_:
            zip_.writestr("h5p.json", json.dumps(PAQUETE_MINIMO["h5p.json"]))
            zip_.writestr(
                "content/content.json", json.dumps(PAQUETE_MINIMO["content/content.json"])
            )
            zip_.writestr(
                "content/content.json", json.dumps(PAQUETE_MINIMO["content/content.json"])
            )
    with pytest.raises(ErrorContenido) as exc:
        h5p.validar_paquete(ruta)
    assert exc.value.codigo == "PAQUETE_H5P_INVALIDO"


def test_rechaza_demasiadas_entradas(tmp_path, monkeypatch):
    from tiza import h5p

    monkeypatch.setattr(h5p, "MAX_ENTRADAS_H5P", 3)
    ficheros = dict(PAQUETE_MINIMO)
    for numero in range(4):
        ficheros[f"content/f{numero}.png"] = b"x"
    with pytest.raises(ErrorContenido) as exc:
        h5p.validar_paquete(escribir_paquete(tmp_path, ficheros))
    assert exc.value.codigo == "PAQUETE_H5P_DEMASIADO_GRANDE"


@pytest.mark.parametrize("falta", ["h5p.json", "content/content.json"])
def test_rechaza_sin_los_json_obligatorios(tmp_path, falta):
    from tiza.h5p import validar_paquete

    ficheros = dict(PAQUETE_MINIMO)
    ficheros.pop(falta)
    with pytest.raises(ErrorContenido) as exc:
        validar_paquete(escribir_paquete(tmp_path, ficheros))
    assert exc.value.codigo == "PAQUETE_H5P_INVALIDO"


@pytest.mark.parametrize(
    "h5p",
    [
        {},  # sin nada
        {"title": "x", "mainLibrary": "H5P.Blanks"},  # sin dependencias
        {
            "mainLibrary": "H5P.Blanks",
            "preloadedDependencies": [
                {"machineName": "H5P.Otra", "majorVersion": 1, "minorVersion": 0}
            ],
        },  # la principal no está en las dependencias
        {
            "mainLibrary": "H5P.Blanks",
            "preloadedDependencies": [
                {"machineName": "<script>", "majorVersion": 1, "minorVersion": 0}
            ],
        },
        {
            "mainLibrary": "H5P.Blanks",
            "preloadedDependencies": [
                {"machineName": "H5P.Blanks", "majorVersion": "uno", "minorVersion": 0}
            ],
        },
        {
            "mainLibrary": "H5P.Blanks",
            "preloadedDependencies": [
                {"machineName": "H5P.Blanks", "majorVersion": 1, "minorVersion": 9999}
            ],
        },
        {
            "mainLibrary": "H5P.Blanks",
            "preloadedDependencies": "no-es-lista",
        },
    ],
)
def test_h5p_json_con_esquema_cerrado(tmp_path, h5p):
    from tiza.h5p import validar_paquete

    ruta = escribir_paquete(
        tmp_path, {"h5p.json": h5p, "content/content.json": PAQUETE_MINIMO["content/content.json"]}
    )
    with pytest.raises(ErrorContenido) as exc:
        validar_paquete(ruta)
    assert exc.value.codigo == "PAQUETE_H5P_INVALIDO"


def test_rechaza_content_json_demasiado_grande(tmp_path, monkeypatch):
    from tiza import h5p

    monkeypatch.setattr(h5p, "MAX_CONTENT_JSON_H5P", 10)
    with pytest.raises(ErrorContenido) as exc:
        h5p.validar_paquete(paquete_completo(tmp_path))
    assert exc.value.codigo == "PAQUETE_H5P_DEMASIADO_GRANDE"


@pytest.mark.parametrize(
    "fichero",
    ["content/dibujo.svg", "content/pagina.html", "content/script.js", "content/juego.swf"],
)
def test_rechaza_medios_fuera_de_la_lista_blanca(tmp_path, fichero):
    from tiza.h5p import validar_paquete

    ruta = escribir_paquete(tmp_path, {**PAQUETE_MINIMO, fichero: b"x"})
    with pytest.raises(ErrorContenido) as exc:
        validar_paquete(ruta)
    assert exc.value.codigo == "PAQUETE_H5P_INVALIDO"


def test_rechaza_javascript_en_los_textos(tmp_path):
    from tiza.h5p import validar_paquete

    contenido = {"questions": ["<a href='javascript:alert(1)'>x</a>"]}
    ruta = escribir_paquete(
        tmp_path, {"h5p.json": PAQUETE_MINIMO["h5p.json"], "content/content.json": contenido}
    )
    with pytest.raises(ErrorContenido) as exc:
        validar_paquete(ruta)
    assert exc.value.codigo == "PAQUETE_H5P_INVALIDO"


def test_recoge_los_enlaces_https_para_el_docente(tmp_path):
    from tiza.h5p import validar_paquete

    contenido = {
        "questions": ["Mira https://ejemplo.org/apoyo y https://otra.example/x."],
        "media": {"url": "https://ejemplo.org/apoyo"},
    }
    ruta = escribir_paquete(
        tmp_path, {"h5p.json": PAQUETE_MINIMO["h5p.json"], "content/content.json": contenido}
    )
    validado = validar_paquete(ruta)
    assert validado.externos == ("https://ejemplo.org/apoyo", "https://otra.example/x")


def test_el_contenido_json_debe_ser_un_mapa(tmp_path):
    from tiza.h5p import validar_paquete

    ruta = escribir_paquete(
        tmp_path, {"h5p.json": PAQUETE_MINIMO["h5p.json"], "content/content.json": "[1, 2]"}
    )
    with pytest.raises(ErrorContenido) as exc:
        validar_paquete(ruta)
    assert exc.value.codigo == "PAQUETE_H5P_INVALIDO"


def test_un_zip_que_no_es_h5p_no_se_puede_validar(tmp_path):
    from tiza.h5p import validar_paquete

    ruta = tmp_path / "paquete.h5p"
    ruta.write_bytes(b"esto no es un zip")
    with pytest.raises(ErrorContenido) as exc:
        validar_paquete(ruta)
    assert exc.value.codigo == "PAQUETE_H5P_INVALIDO"


def test_medios_con_el_mismo_nombre_en_rutas_distintas_se_aceptan(tmp_path):
    from tiza.h5p import validar_paquete

    ruta = escribir_paquete(
        tmp_path,
        {
            **PAQUETE_MINIMO,
            "content/a/figura.png": b"a",
            "content/b/figura.png": b"b",
        },
    )
    validado = validar_paquete(ruta)
    assert "content/a/figura.png" in validado.ficheros
    assert "content/b/figura.png" in validado.ficheros
