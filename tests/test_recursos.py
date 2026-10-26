"""Tests de ``tiza.recursos``: el logo y el icono viajan dentro del paquete."""

from __future__ import annotations

import struct

from tiza import recursos


def test_el_logo_es_un_png():
    datos = recursos.datos("logo.png")
    assert datos.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(datos) < 100_000  # la página lo incrusta: no engordar la wheel sin querer


def test_el_icono_es_un_ico_con_varios_tamanos():
    datos = recursos.datos("tiza.ico")
    assert datos[:4] == b"\x00\x00\x01\x00"
    (cuantos,) = struct.unpack("<H", datos[4:6])
    assert cuantos >= 4


def test_ruta_del_icono_es_un_fichero_de_verdad():
    ruta = recursos.ruta("tiza.ico")
    assert ruta is not None and ruta.is_file()


def test_un_recurso_que_no_existe_no_es_una_ruta():
    assert recursos.ruta("no-existe.png") is None
