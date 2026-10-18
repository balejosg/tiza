"""Consultas exactas y salida con esquema cerrado (todo offline, sobre datos de juguete)."""

from __future__ import annotations

import copy
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from tiza.normativa import ErrorNormativa, cargar, consulta, limpiar_cache, salida

SINTETICOS = Path(__file__).parent / "datos_sinteticos"
MATERIA = "MAD.ESO.CCOMP.1"
HOY = date(2026, 10, 17)
SEPTIEMBRE_SIGUIENTE = date(2027, 9, 15)


@pytest.fixture(scope="module")
def indice():
    return cargar(SINTETICOS)


def fallo(llamada) -> ErrorNormativa:
    with pytest.raises(ErrorNormativa) as info:
        llamada()
    return info.value


def elemento_de(respuesta: salida.FichaSalida, codigo: str) -> salida.Fragmento:
    return next(e for e in respuesta.elementos if e.codigo == codigo)


# --- ficha -------------------------------------------------------------------


def test_ficha_lleva_texto_y_procedencia(indice):
    r = consulta.ficha(MATERIA, "2026-27", hoy=HOY, indice=indice)
    assert r.codigo == MATERIA
    assert r.desde == "2026-09-01"  # se informa; no filtra
    assert [e.orden for e in r.elementos] == sorted(e.orden for e in r.elementos)

    cr11 = elemento_de(r, f"{MATERIA}.CR.1.1")
    assert cr11.texto == "Nombra los componentes de un sistema de ejemplo."
    assert cr11.padre == f"{MATERIA}.CE.1"
    assert cr11.procedencia.ubicacion == "anexo II"
    assert cr11.procedencia.pagina == 12
    assert cr11.procedencia.norma.numero == "27/2025"
    assert cr11.procedencia.norma.fecha == "2025-01-01"
    assert cr11.procedencia.norma.boletin == "BOCM"
    assert cr11.procedencia.norma.url.startswith("https://www.bocm.es/")

    cr12 = elemento_de(r, f"{MATERIA}.CR.1.2")
    assert cr12.texto == "Describe cómo se conectan los componentes de un sistema de ejemplo."
    assert cr12.procedencia.ubicacion == "art. 1"
    assert cr12.procedencia.norma.numero == "5/2025"
    (via,) = cr12.procedencia.via
    assert (via.ubicacion, via.pagina, via.norma.numero) == ("anexo II", 13, "27/2025")


def test_ficha_resuelve_descriptores(indice):
    r = consulta.ficha(MATERIA, "2026-27", hoy=HOY, indice=indice)
    (cd1,) = elemento_de(r, f"{MATERIA}.CE.1").relaciones["descriptores"]
    assert cd1.codigo == "EST.ESO.DESC.CD1"
    assert cd1.ficha == "EST.ESO.DESC"
    assert cd1.tipo == "descriptor"
    assert cd1.texto == "Usa herramientas digitales de forma segura."


def test_datos_del_modulo_viajan_con_el_elemento(indice):
    r = consulta.ficha("MAD.DAM.0485", "2026-27", hoy=HOY, indice=indice)
    assert elemento_de(r, "MAD.DAM.0485").datos == {"horas": 160, "curso": "1"}
    assert r.desde is None
    assert r.normas[0].boletin == "CM"


def test_materia_fuera_del_lote(indice):
    error = fallo(lambda: consulta.ficha("MAD.ESO.MAT.1", "2026-27", hoy=HOY, indice=indice))
    assert error.codigo == "NORMATIVA_SIN_DATOS"
    assert MATERIA in error.disponibles
    documento = salida.error_a_dict(error)
    assert documento["error"] == "NORMATIVA_SIN_DATOS"
    assert MATERIA in documento["disponibles"]
    assert set(documento) == {"error", "detalle", "disponibles"}


def test_ficha_no_es_un_codigo_de_elemento(indice):
    # Un código de elemento no es una ficha: sigue siendo «sin datos», no «desconocido».
    error = fallo(lambda: consulta.ficha(f"{MATERIA}.CR.1.1", "2026-27", hoy=HOY, indice=indice))
    assert error.codigo == "NORMATIVA_SIN_DATOS"


# --- curso académico -----------------------------------------------------------


def test_curso_de_va_de_septiembre_a_agosto():
    assert consulta.curso_de(date(2026, 8, 31)) == "2025-26"
    assert consulta.curso_de(date(2026, 9, 1)) == "2026-27"
    assert consulta.curso_de(date(2026, 12, 31)) == "2026-27"
    assert consulta.curso_de(date(2027, 1, 1)) == "2026-27"
    assert consulta.curso_de(date(2099, 10, 1)) == "2099-00"


def test_hoy_en_madrid_es_una_fecha():
    assert isinstance(consulta.hoy_en_madrid(), date)


def test_curso_academico_sin_datos(indice):
    error = fallo(lambda: consulta.ficha("MAD.DAM.0485", "2027-28", hoy=HOY, indice=indice))
    assert error.codigo == "CURSO_SIN_DATOS"
    assert error.disponibles == ("2026-27",)
    assert salida.error_a_dict(error)["disponibles"] == ["2026-27"]


def test_curso_mal_formado_es_sin_datos(indice):
    error = fallo(lambda: consulta.ficha(MATERIA, "26/27", hoy=HOY, indice=indice))
    assert error.codigo == "CURSO_SIN_DATOS"
    assert error.disponibles == ("2025-26", "2026-27")
    salida.error_a_dict(error)


def test_curso_academico_por_defecto(indice):
    for hoy in (HOY, date(2027, 7, 31)):
        r = consulta.ficha("MAD.DAM.0485", None, hoy=hoy, indice=indice)
        assert r.curso_academico == "2026-27"
        assert r.curso_en_vigor is True


def test_curso_nuevo_sin_datos_no_cae_al_anterior(indice):
    error = fallo(
        lambda: consulta.ficha("MAD.DAM.0485", None, hoy=SEPTIEMBRE_SIGUIENTE, indice=indice)
    )
    assert error.codigo == "CURSO_SIN_DATOS"
    assert error.disponibles == ("2026-27",)


def test_curso_pedido_que_no_esta_en_vigor(indice):
    r = consulta.ficha("MAD.DAM.0485", "2026-27", hoy=SEPTIEMBRE_SIGUIENTE, indice=indice)
    assert r.curso_academico == "2026-27"
    assert r.curso_en_vigor is False
    assert r.a_dict()["curso_en_vigor"] is False
    r = consulta.ficha("MAD.DAM.0485", "2026-27", hoy=HOY, indice=indice)
    assert r.curso_en_vigor is True


def test_curso_anterior_existente_se_responde_sin_estar_en_vigor(indice):
    r = consulta.ficha(MATERIA, "2025-26", hoy=HOY, indice=indice)
    assert (r.curso_academico, r.curso_en_vigor) == ("2025-26", False)


def test_el_curso_se_comprueba_contra_la_ficha_pedida(indice):
    # Hay datos de 2025-26 en la ficha de la materia, pero no en la del módulo.
    error = fallo(lambda: consulta.ficha("MAD.DAM.0485", "2025-26", hoy=HOY, indice=indice))
    assert error.codigo == "CURSO_SIN_DATOS"
    assert error.disponibles == ("2026-27",)


def test_la_version_de_los_datos_es_la_revision_mas_reciente(indice):
    r = consulta.ficha(MATERIA, "2026-27", hoy=HOY, indice=indice)
    assert r.version_datos == "2025-06-20"
    assert r.aviso == "Texto literal del boletín. Cita siempre el código y la procedencia."


# --- elemento ----------------------------------------------------------------


def test_elemento_por_codigo(indice):
    r = consulta.elemento(f"{MATERIA}.CR.1.2", "2026-27", hoy=HOY, indice=indice)
    assert r.ficha == MATERIA
    assert r.desde == "2026-09-01"
    assert r.elemento.codigo == f"{MATERIA}.CR.1.2"
    assert r.elemento.procedencia.via[0].pagina == 13
    assert r.a_dict()["consulta"] == "elemento"


def test_elemento_desconocido(indice):
    for codigo in (f"{MATERIA}.CR.9.9", "MAD.ESO.MAT.1.CR.1.1", "no es un codigo\n"):
        error = fallo(lambda c=codigo: consulta.elemento(c, "2026-27", hoy=HOY, indice=indice))
        assert error.codigo == "CODIGO_DESCONOCIDO"
        assert "\n" not in salida.error_a_dict(error)["detalle"]


def test_elemento_respeta_el_curso_de_su_ficha(indice):
    error = fallo(lambda: consulta.elemento("MAD.DAM.0485.RA.1", "2025-26", hoy=HOY, indice=indice))
    assert error.codigo == "CURSO_SIN_DATOS"


# --- norma -------------------------------------------------------------------


def test_norma_por_cita_con_errata(indice):
    r = consulta.norma("Decreto 21/2025", hoy=HOY, indice=indice)
    assert r.numero == "27/2025"
    assert r.cita_pedida == "Decreto 21/2025"
    assert r.cita_correcta == "Decreto 27/2025"
    ids = [c.norma.id for c in r.correcciones]
    assert ids == ["bocm-20250201-2", "boe-a-2024-100"]
    assert [c.fragmento for c in r.correcciones] == [None, "da-unica"]
    assert [m.id for m in r.modificada_por] == ["bocm-20250201-2"]
    assert r.derogaciones_parciales == ("Decreto 10/2020: capítulo II y art. 23",)
    assert (r.titulo, r.boletin, r.estado) == (
        "Decreto de juguete por el que se ordena una materia de ejemplo",
        "BOCM",
        "vigente",
    )
    assert r.url_pdf.startswith("https://www.bocm.es/")
    assert r.fecha == "2025-01-01"


@pytest.mark.parametrize(
    ("cita", "numero"),
    [
        ("Decreto 27/2025", "27/2025"),
        ("decreto 27/2025", "27/2025"),
        ("Orden 5/2025", "5/2025"),
        ("RD 1/2024", "1/2024"),
        ("Real Decreto 1/2024", "1/2024"),
        ("R.D. 1/2024", "1/2024"),
        ("Resolución 3/2025", "3/2025"),
    ],
)
def test_norma_por_cita_canonica_no_es_errata(indice, cita, numero):
    r = consulta.norma(cita, hoy=HOY, indice=indice)
    assert r.numero == numero
    assert (r.cita_pedida, r.cita_correcta) == (None, None)


def test_norma_con_errata_de_real_decreto_usa_el_estilo_oficial(tmp_path):
    raiz = tmp_path / "datos"
    shutil.copytree(SINTETICOS, raiz)
    ruta = raiz / "normas" / "boe-a-2024-100.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["citas"] = ["Real Decreto 2/2024"]
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    limpiar_cache()
    r = consulta.norma("Real Decreto 2/2024", hoy=HOY, indice=cargar(raiz))
    assert r.numero == "1/2024"
    assert r.cita_pedida == "Real Decreto 2/2024"
    assert r.cita_correcta == "Real Decreto 1/2024"


def con_correccion(tmp_path, **cambios):
    """Datos de juguete más una corrección de errores del decreto 27/2025."""
    raiz = tmp_path / "datos"
    shutil.copytree(SINTETICOS, raiz)
    correccion = {
        "id": "bocm-20250301-3",
        "rango": "correccion",
        "numero": "del Decreto 27/2025",
        "fecha": "2025-03-01",
        "titulo": "Corrección de errores de juguete del Decreto 27/2025",
        "boletin": "BOCM",
        "url_pdf": "https://www.bocm.es/boletin/ejemplo-correccion-27-2025.pdf",
        "sha256": "6" * 64,
        "estado": "vigente",
        "revisada": "2025-03-10",
    } | cambios
    ruta = raiz / "normas" / "bocm-20250301-3.json"
    ruta.write_text(json.dumps(correccion, ensure_ascii=False), encoding="utf-8")
    limpiar_cache()
    return cargar(raiz)


def test_norma_correccion_de_errores_se_cita_con_la_norma_corregida(tmp_path):
    datos = con_correccion(tmp_path)
    r = consulta.norma("corrección de errores del Decreto 27/2025", hoy=HOY, indice=datos)
    assert (r.id, r.rango, r.numero) == ("bocm-20250301-3", "correccion", "del Decreto 27/2025")
    assert (r.cita_pedida, r.cita_correcta) == (None, None)
    # la mayúscula inicial y «de»/«del» no cambian la cita
    r = consulta.norma("Corrección de errores del Decreto 27/2025", hoy=HOY, indice=datos)
    assert r.id == "bocm-20250301-3"


def test_norma_correccion_con_errata_no_se_pone_en_mayusculas_cada_palabra(tmp_path):
    datos = con_correccion(tmp_path, citas=["Corrección de errores del Decreto 21/2025"])
    r = consulta.norma("corrección de errores del decreto 21/2025", hoy=HOY, indice=datos)
    assert r.id == "bocm-20250301-3"
    assert r.cita_correcta == "Corrección de errores del Decreto 27/2025"


def test_norma_desconocida(indice):
    error = fallo(lambda: consulta.norma("Decreto 1/1999", hoy=HOY, indice=indice))
    assert error.codigo == "NORMA_DESCONOCIDA"
    salida.error_a_dict(error)


def test_norma_derogada_solo_metadatos(indice):
    r = consulta.norma("Real Decreto 9/2020", hoy=HOY, indice=indice)
    assert r.estado == "derogada"
    assert r.derogada_por is not None
    assert (r.derogada_por.id, r.derogada_por.numero) == ("boe-a-2024-100", "1/2024")
    assert r.desde == "2024-09-01"
    # Ninguna ficha la cita como fuente de texto.
    for f in indice.fichas.values():
        assert r.id not in f.normas
        for e in f.elementos:
            pendientes = [e.procedencia]
            while pendientes:
                p = pendientes.pop()
                assert p.norma != r.id
                pendientes.extend(p.via)
    # Y una norma vigente no lleva derogación.
    vigente = consulta.norma("RD 1/2024", hoy=HOY, indice=indice)
    assert (vigente.derogada_por, vigente.desde) == (None, None)
    assert vigente.url_api is not None


def test_norma_lleva_la_cabecera_comun(indice):
    r = consulta.norma("Orden 5/2025", hoy=HOY, indice=indice)
    assert (r.curso_academico, r.curso_en_vigor) == ("2026-27", True)
    assert [m.numero for m in r.modifica] == ["27/2025"]


# --- catálogo ----------------------------------------------------------------


def test_catalogo_lista_las_fichas_del_curso(indice):
    r = consulta.catalogo("2026-27", hoy=HOY, indice=indice)
    assert [f.codigo for f in r.fichas] == [
        "EST.ESO.DESC",
        "MAD.DAM.0485",
        MATERIA,
        "MAD.ESO.PROG",
    ]
    materia = next(f for f in r.fichas if f.codigo == MATERIA)
    assert (materia.nombre, materia.etapa, materia.curso) == (
        "Materia de juguete, primer curso",
        "eso",
        "1",
    )
    assert [n.numero for n in materia.normas] == ["27/2025", "5/2025"]
    antes = consulta.catalogo("2025-26", hoy=HOY, indice=indice)
    assert [f.codigo for f in antes.fichas] == ["EST.ESO.DESC", MATERIA]
    assert antes.curso_en_vigor is False


def test_catalogo_sin_datos_del_curso(indice):
    error = fallo(lambda: consulta.catalogo(None, hoy=SEPTIEMBRE_SIGUIENTE, indice=indice))
    assert error.codigo == "CURSO_SIN_DATOS"
    assert error.disponibles == ("2025-26", "2026-27")


def test_sin_datos_no_inventa_nada(tmp_path):
    vacio = tmp_path / "datos"
    (vacio / "normas").mkdir(parents=True)
    (vacio / "fichas").mkdir()
    sin = cargar(vacio)
    for llamada in (
        lambda: consulta.catalogo("2026-27", hoy=HOY, indice=sin),
        lambda: consulta.ficha(MATERIA, "2026-27", hoy=HOY, indice=sin),
        lambda: consulta.buscar("x", None, "2026-27", hoy=HOY, indice=sin),
        lambda: consulta.programacion("eso", "2026-27", hoy=HOY, indice=sin),
        lambda: consulta.norma("Decreto 27/2025", hoy=HOY, indice=sin),
    ):
        error = fallo(llamada)
        assert error.codigo == "NORMATIVA_SIN_DATOS"
        assert salida.error_a_dict(error)["disponibles"] == []


# --- búsqueda ----------------------------------------------------------------


def test_buscar_sin_tildes(indice):
    r = consulta.buscar("COMO SE CONECTAN", MATERIA, "2026-27", hoy=HOY, indice=indice)
    assert [x.codigo for x in r.resultados] == [f"{MATERIA}.CR.1.2"]  # «cómo» casa con «como»
    assert r.resultados[0].ficha == MATERIA
    assert r.resultados[0].procedencia.norma.numero == "5/2025"
    r = consulta.buscar("disena solucion", MATERIA, "2026-27", hoy=HOY, indice=indice)
    assert [x.codigo for x in r.resultados] == [f"{MATERIA}.CE.2"]  # y «disena» con «Diseña»
    r = consulta.buscar("DISEÑA SOLUCIÓN", MATERIA, "2026-27", hoy=HOY, indice=indice)
    assert r.total == 1


def test_buscar_exige_todas_las_palabras_y_recorre_el_curso(indice):
    r = consulta.buscar("sistema ejemplo", None, "2026-27", hoy=HOY, indice=indice)
    assert [x.codigo for x in r.resultados] == [
        "MAD.DAM.0485.RA.1",
        f"{MATERIA}.CE.1",
        f"{MATERIA}.CR.1.1",
        f"{MATERIA}.CR.1.2",
    ]
    assert r.total == 4
    assert (
        consulta.buscar("sistema inexistente", None, "2026-27", hoy=HOY, indice=indice).total == 0
    )


def test_buscar_acota_a_veinte_resultados(tmp_path):
    raiz = tmp_path / "datos"
    shutil.copytree(SINTETICOS, raiz)
    ruta = raiz / "fichas" / "materia_ccomp_1.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    modelo = copy.deepcopy(datos["elementos"][2])
    for i in range(25):
        nuevo = copy.deepcopy(modelo)
        nuevo["codigo"] = f"{MATERIA}.CR.7.{i}"
        nuevo["texto"] = f"Texto repetido número {i}."
        nuevo["orden"] = 100 + i
        datos["elementos"].append(nuevo)
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    limpiar_cache()
    r = consulta.buscar("repetido", None, "2026-27", hoy=HOY, indice=cargar(raiz))
    assert r.total == 25
    assert len(r.resultados) == consulta.MAX_RESULTADOS == 20
    assert r.resultados[0].codigo == f"{MATERIA}.CR.7.0"


def test_buscar_errores(indice):
    assert fallo(lambda: consulta.buscar("  ", None, "2026-27", hoy=HOY, indice=indice)).codigo == (
        "TEXTO_VACIO"
    )
    assert fallo(
        lambda: consulta.buscar("x", "MAD.ESO.MAT.1", "2026-27", hoy=HOY, indice=indice)
    ).codigo == ("NORMATIVA_SIN_DATOS")
    assert fallo(
        lambda: consulta.buscar("x", MATERIA, "2027-28", hoy=HOY, indice=indice)
    ).codigo == ("CURSO_SIN_DATOS")
    assert fallo(
        lambda: consulta.buscar("x", None, "2027-28", hoy=HOY, indice=indice)
    ).disponibles == (
        "2025-26",
        "2026-27",
    )


# --- programación ------------------------------------------------------------


def test_programacion_de_eso(indice):
    r = consulta.programacion("eso", "2026-27", hoy=HOY, indice=indice)
    assert (r.etapa, r.ficha) == ("eso", "MAD.ESO.PROG")
    assert [(x.codigo, x.procedencia.ubicacion) for x in r.requisitos] == [
        ("MAD.ESO.PROG.REQ.1", "art. 4.1"),
        ("MAD.ESO.PROG.REQ.2", "art. 4.2"),
    ]
    assert r.indice == (
        "Cuando ninguna norma fija el índice de la programación, lo fija la plantilla del centro."
    )
    assert consulta.programacion(" ESO ", None, hoy=HOY, indice=indice).etapa == "eso"


def test_programacion_sin_requisitos_no_responde_vacio(tmp_path):
    raiz = tmp_path / "datos"
    shutil.copytree(SINTETICOS, raiz)
    ruta = raiz / "fichas" / "programacion_eso.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["elementos"] = []
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    limpiar_cache()
    error = fallo(lambda: consulta.programacion("eso", "2026-27", hoy=HOY, indice=cargar(raiz)))
    assert error.codigo == "NORMATIVA_SIN_DATOS"
    salida.error_a_dict(error)


def test_programacion_etapas(indice):
    error = fallo(lambda: consulta.programacion("primaria", "2026-27", hoy=HOY, indice=indice))
    assert error.codigo == "ETAPA_DESCONOCIDA"
    assert error.disponibles == ("eso", "bachillerato", "fp")
    for etapa in ("bachillerato", "fp"):
        error = fallo(lambda e=etapa: consulta.programacion(e, "2026-27", hoy=HOY, indice=indice))
        assert error.codigo == "NORMATIVA_SIN_DATOS"
        assert "MAD.ESO.PROG" in error.disponibles
    error = fallo(lambda: consulta.programacion("eso", "2025-26", hoy=HOY, indice=indice))
    assert error.codigo == "CURSO_SIN_DATOS"


# --- esquema cerrado -----------------------------------------------------------


def todas_las_respuestas(indice) -> list[salida.Respuesta]:
    return [
        consulta.catalogo("2026-27", hoy=HOY, indice=indice),
        consulta.ficha(MATERIA, "2026-27", hoy=HOY, indice=indice),
        consulta.ficha("MAD.DAM.0485", "2026-27", hoy=HOY, indice=indice),
        consulta.elemento(f"{MATERIA}.CE.1", "2026-27", hoy=HOY, indice=indice),
        consulta.norma("Decreto 21/2025", hoy=HOY, indice=indice),
        consulta.norma("Real Decreto 9/2020", hoy=HOY, indice=indice),
        consulta.buscar("sistema", None, "2026-27", hoy=HOY, indice=indice),
        consulta.programacion("eso", "2026-27", hoy=HOY, indice=indice),
    ]


def test_salida_valida_esquema(indice):
    for respuesta in todas_las_respuestas(indice):
        documento = respuesta.a_dict()
        salida.validar(documento)
        # Es JSON de verdad: sin tuplas, fechas ni dataclasses sueltos.
        assert json.loads(json.dumps(documento)) == documento
        assert {"consulta", "version_datos", "curso_academico", "curso_en_vigor", "aviso"} <= set(
            documento
        )


def rechaza(documento: dict, codigo: str | None = None) -> None:
    with pytest.raises(salida.ErrorSalida) as info:
        salida.validar(documento)
    if codigo is not None:
        assert info.value.codigo == codigo


def test_validar_rechaza_una_clave_mas_en_cualquier_nivel(indice):
    base = consulta.ficha(MATERIA, "2026-27", hoy=HOY, indice=indice).a_dict()

    raiz = copy.deepcopy(base)
    raiz["extra"] = "x"
    rechaza(raiz, "CLAVE_NO_PERMITIDA")

    elemento = copy.deepcopy(base)
    elemento["elementos"][0]["extra"] = 1
    rechaza(elemento, "CLAVE_NO_PERMITIDA")

    procedencia = copy.deepcopy(base)
    procedencia["elementos"][0]["procedencia"]["norma"]["extra"] = "x"
    rechaza(procedencia, "CLAVE_NO_PERMITIDA")

    via = copy.deepcopy(base)
    cr12 = next(e for e in via["elementos"] if e["codigo"].endswith("CR.1.2"))
    cr12["procedencia"]["via"][0]["extra"] = "x"
    rechaza(via, "CLAVE_NO_PERMITIDA")

    relacion = copy.deepcopy(base)
    ce1 = next(e for e in relacion["elementos"] if e["codigo"].endswith("CE.1"))
    ce1["relaciones"]["descriptores"][0]["extra"] = "x"
    rechaza(relacion, "CLAVE_NO_PERMITIDA")

    faltante = copy.deepcopy(base)
    del faltante["elementos"][0]["texto"]
    rechaza(faltante, "FALTA_CLAVE")


def test_validar_rechaza_tipos_y_textos_fijos_cambiados(indice):
    base = consulta.programacion("eso", "2026-27", hoy=HOY, indice=indice).a_dict()
    for clave, valor in (
        ("aviso", "Otro texto."),
        ("indice", "Haz lo que quieras."),
        ("curso_en_vigor", 1),
        ("curso_academico", "2026"),
        ("version_datos", "ayer"),
        ("consulta", "otra"),
        ("etapa", None),
        ("requisitos", {}),
    ):
        mala = copy.deepcopy(base)
        mala[clave] = valor
        rechaza(mala)
    mala = copy.deepcopy(base)
    mala["requisitos"][0]["orden"] = True  # un booleano no es un entero
    rechaza(mala, "TIPO_INCORRECTO")
    mala = copy.deepcopy(base)
    mala["requisitos"][0]["texto"] = "línea\nsecreta"
    rechaza(mala, "VALOR_NO_PERMITIDO")
    rechaza([], "TIPO_INCORRECTO")  # type: ignore[arg-type]


def test_el_error_es_un_documento_cerrado(indice):
    error = fallo(lambda: consulta.ficha("MAD.ESO.MAT.1", None, hoy=HOY, indice=indice))
    documento = salida.error_a_dict(error)
    salida.validar(documento)
    for mala in (
        {**documento, "extra": 1},
        {**documento, "error": "OTRO_CODIGO"},
        {**documento, "detalle": "a\nb"},
        {**documento, "disponibles": "MAD"},
        {"error": "NORMATIVA_SIN_DATOS", "detalle": "x"},
    ):
        rechaza(mala)
    # Un código que no es de las consultas no sale impreso.
    with pytest.raises(salida.ErrorSalida):
        salida.error_a_dict(ErrorNormativa("ERROR_INTERNO", "x"))
    # Un detalle largo se recorta en vez de romper la salida.
    largo = salida.error_a_dict(ErrorNormativa("DATOS_INVALIDOS", "x" * 1000))
    assert len(largo["detalle"]) == salida.MAX_DETALLE


def test_el_detalle_no_repite_lo_pedido_si_es_raro(indice):
    error = fallo(lambda: consulta.norma("Decreto <script>\n1/1999", hoy=HOY, indice=indice))
    assert "script" not in error.detalle
    assert "script" not in salida.error_a_dict(error)["detalle"]
    error = fallo(lambda: consulta.norma("Decreto 1/1999", hoy=HOY, indice=indice))
    assert "Decreto 1/1999" in error.detalle
