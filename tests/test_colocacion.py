"""La regla pura que coloca la nota de una actividad según su sección."""

from __future__ import annotations

from tiza.colocacion import ArbolNotas, FilaNota, MovimientoNota, SinColocar, colocar
from tiza.estructura import Actividad, Estructura, Seccion

RAIZ = "cg1"


def curso(*secciones: tuple[int, ...]) -> Estructura:
    """Una estructura con una sección por tupla de cmids (secciones 1, 2, 3...)."""
    return Estructura(
        secciones=tuple(
            Seccion(
                numero=numero,
                nombre=f"UT{numero}",
                id=100 + numero,
                actividades=tuple(Actividad(cmid, f"A{cmid}", "tarea") for cmid in cmids),
            )
            for numero, cmids in enumerate(secciones, start=1)
        )
    )


def cat(eid: str, nombre: str, *, bloqueada: bool = False, de_tiza: bool = False) -> FilaNota:
    return FilaNota(eid, RAIZ, None, nombre, bloqueada=bloqueada, de_tiza=de_tiza)


def nota(cmid: int, padre: str) -> FilaNota:
    return FilaNota(f"ig{cmid}", padre, cmid, f"A{cmid}")


def arbol(*filas: FilaNota) -> ArbolNotas:
    return ArbolNotas((FilaNota(RAIZ, None, None, "Curso"), *filas))


def test_sigue_a_su_seccion() -> None:
    estructura = curso((1, 2, 3))
    notas = arbol(cat("cg10", "Ev1"), nota(1, "cg10"), nota(2, "cg10"), nota(3, RAIZ))
    movimientos, sin = colocar(estructura, notas, [3])
    assert movimientos == (
        MovimientoNota(cmid=3, eid="ig3", categoria="cg10", despues_de="ig2",
                       nombre_categoria="Ev1", desde=None),
    )  # fmt: skip
    assert sin == ()


def test_va_en_su_sitio_no_al_final() -> None:
    estructura = curso((1, 3, 2))
    notas = arbol(cat("cg10", "Ev1"), nota(1, "cg10"), nota(2, "cg10"), nota(3, RAIZ))
    movimientos, _ = colocar(estructura, notas, [3])
    assert [(m.categoria, m.despues_de) for m in movimientos] == [("cg10", "ig1")]


def test_va_al_principio_si_ninguna_va_antes() -> None:
    estructura = curso((3, 1, 2))
    notas = arbol(cat("cg10", "Ev1"), nota(1, "cg10"), nota(2, "cg10"), nota(3, RAIZ))
    movimientos, _ = colocar(estructura, notas, [3])
    assert [(m.categoria, m.despues_de) for m in movimientos] == [("cg10", None)]


def test_primera_de_su_seccion_sigue_a_la_anterior() -> None:
    estructura = curso((1, 2), (3,))
    notas = arbol(cat("cg10", "Ev1"), nota(1, "cg10"), nota(2, "cg10"), nota(3, RAIZ))
    movimientos, _ = colocar(estructura, notas, [3])
    assert [(m.categoria, m.despues_de) for m in movimientos] == [("cg10", "ig2")]


def test_varias_nuevas_en_seccion_vacia_siguen_a_la_anterior_en_orden() -> None:
    estructura = curso((1, 2), (4, 5))
    notas = arbol(
        cat("cg10", "Ev1"), nota(1, "cg10"), nota(2, "cg10"), nota(4, RAIZ), nota(5, RAIZ)
    )
    movimientos, sin = colocar(estructura, notas, [4, 5])
    assert [(m.cmid, m.categoria, m.despues_de) for m in movimientos] == [
        (4, "cg10", "ig2"),
        (5, "cg10", "ig4"),
    ]
    assert sin == ()


def test_las_nuevas_se_colocan_en_el_orden_del_curso_aunque_lleguen_al_reves() -> None:
    estructura = curso((1, 2), (4, 5))
    notas = arbol(
        cat("cg10", "Ev1"), nota(1, "cg10"), nota(2, "cg10"), nota(4, RAIZ), nota(5, RAIZ)
    )
    movimientos, _ = colocar(estructura, notas, [5, 4])
    assert [(m.cmid, m.despues_de) for m in movimientos] == [(4, "ig2"), (5, "ig4")]


def test_sigue_hacia_atras_hasta_encontrar() -> None:
    estructura = curso((1,), (), (), (4,))
    notas = arbol(cat("cg10", "Ev1"), nota(1, "cg10"), nota(4, RAIZ))
    movimientos, _ = colocar(estructura, notas, [4])
    assert [(m.categoria, m.despues_de) for m in movimientos] == [("cg10", "ig1")]


def test_ambigua() -> None:
    estructura = curso((1, 2, 3))
    notas = arbol(cat("cg10", "Ev1"), nota(1, "cg10"), nota(2, RAIZ), nota(3, RAIZ))
    movimientos, sin = colocar(estructura, notas, [3])
    assert movimientos == ()
    assert sin == (SinColocar(3, "AMBIGUA", None),)


def test_sin_patron() -> None:
    estructura = curso((1,), (2,))
    notas = arbol(nota(2, RAIZ))
    movimientos, sin = colocar(estructura, notas, [2])
    assert movimientos == ()
    assert sin == (SinColocar(2, "SIN_PATRON", None),)


def test_la_raiz_cuenta_como_categoria() -> None:
    estructura = curso((1, 3, 2))
    notas = arbol(nota(1, RAIZ), nota(2, RAIZ), nota(3, RAIZ))
    movimientos, sin = colocar(estructura, notas, [3])
    assert [(m.categoria, m.despues_de, m.desde) for m in movimientos] == [(RAIZ, "ig1", None)]
    assert movimientos[0].nombre_categoria == "Curso"
    assert sin == ()


def test_la_raiz_cuenta_como_categoria_y_ya_esta_en_su_sitio() -> None:
    estructura = curso((1, 2, 3))
    notas = arbol(nota(1, RAIZ), nota(2, RAIZ), nota(3, RAIZ))
    assert colocar(estructura, notas, [3]) == ((), ())


def test_destino_cerrado() -> None:
    estructura = curso((1, 2, 3))
    notas = arbol(
        cat("cg10", "Ev1", bloqueada=True), nota(1, "cg10"), nota(2, "cg10"), nota(3, RAIZ)
    )
    movimientos, sin = colocar(estructura, notas, [3])
    assert movimientos == ()
    assert sin == (SinColocar(3, "CERRADA", "Ev1"),)


def test_destino_cerrado_no_sigue_buscando_hacia_atras() -> None:
    estructura = curso((1,), (2,), (3,))
    notas = arbol(
        cat("cg10", "Ev1"),
        cat("cg20", "Ev2", bloqueada=True),
        nota(1, "cg10"),
        nota(2, "cg20"),
        nota(3, RAIZ),
    )
    movimientos, sin = colocar(estructura, notas, [3])
    assert movimientos == ()
    assert sin == (SinColocar(3, "CERRADA", "Ev2"),)


def test_no_saca_de_una_cerrada() -> None:
    estructura = curso((1,), (2, 3))
    notas = arbol(
        cat("cg10", "Ev1", bloqueada=True),
        cat("cg20", "Ev2"),
        nota(1, "cg10"),
        nota(2, "cg20"),
        nota(3, "cg10"),
    )
    movimientos, sin = colocar(estructura, notas, [3])
    assert movimientos == ()
    assert sin == (SinColocar(3, "CERRADA", "Ev1"),)


def test_ya_en_una_cerrada_y_en_su_sitio_no_da_nada() -> None:
    estructura = curso((1, 2, 3))
    notas = arbol(
        cat("cg10", "Ev1", bloqueada=True), nota(1, "cg10"), nota(2, "cg10"), nota(3, "cg10")
    )
    assert colocar(estructura, notas, [3]) == ((), ())


def test_ignora_las_de_tiza() -> None:
    estructura = curso((1, 2, 3))
    notas = arbol(
        cat("cg10", "Ev1"),
        cat("cg90", "TZ_RA1", de_tiza=True),
        nota(1, "cg10"),
        nota(2, "cg90"),
        nota(3, RAIZ),
    )
    movimientos, sin = colocar(estructura, notas, [3])
    assert [(m.categoria, m.despues_de) for m in movimientos] == [("cg10", "ig1")]
    assert sin == ()


def test_solo_de_tiza_no_hace_patron() -> None:
    estructura = curso((1, 2))
    notas = arbol(cat("cg90", "TZ_RA1", de_tiza=True), nota(1, "cg90"), nota(2, RAIZ))
    assert colocar(estructura, notas, [2]) == ((), (SinColocar(2, "SIN_PATRON", None),))


def test_ya_en_su_sitio_no_mueve() -> None:
    estructura = curso((1, 2, 3))
    notas = arbol(cat("cg10", "Ev1"), nota(1, "cg10"), nota(2, "cg10"), nota(3, "cg10"))
    assert colocar(estructura, notas, [3]) == ((), ())


def test_en_su_categoria_pero_fuera_de_sitio_se_recoloca() -> None:
    estructura = curso((1, 2, 3))
    notas = arbol(cat("cg10", "Ev1"), nota(3, "cg10"), nota(1, "cg10"), nota(2, "cg10"))
    movimientos, _ = colocar(estructura, notas, [3])
    assert [(m.categoria, m.despues_de, m.desde) for m in movimientos] == [("cg10", "ig2", "Ev1")]


def test_un_elemento_manual_entre_medias_no_cuenta_como_fuera_de_sitio() -> None:
    estructura = curso((1, 2))
    manual = FilaNota("ig900", "cg10", None, "Manual")
    notas = arbol(cat("cg10", "Ev1"), nota(1, "cg10"), manual, nota(2, "cg10"))
    assert colocar(estructura, notas, [2]) == ((), ())


def test_actividad_sin_nota_no_da_nada() -> None:
    estructura = curso((1, 2))
    notas = arbol(cat("cg10", "Ev1"), nota(1, "cg10"))
    assert colocar(estructura, notas, [2]) == ((), ())


def test_cmid_fuera_de_la_estructura_no_da_nada() -> None:
    estructura = curso((1,))
    notas = arbol(cat("cg10", "Ev1"), nota(1, "cg10"), nota(7, RAIZ))
    assert colocar(estructura, notas, [7]) == ((), ())


def test_cambio_de_seccion_sigue_a_la_nueva() -> None:
    estructura = curso((1, 2), (), (), (5, 3))
    notas = arbol(
        cat("cg10", "Ev1"),
        cat("cg20", "Ev2"),
        nota(1, "cg10"),
        nota(2, "cg10"),
        nota(3, "cg10"),
        nota(5, "cg20"),
    )
    movimientos, sin = colocar(estructura, notas, [3])
    assert movimientos == (
        MovimientoNota(cmid=3, eid="ig3", categoria="cg20", despues_de="ig5",
                       nombre_categoria="Ev2", desde="Ev1"),
    )  # fmt: skip
    assert sin == ()


def test_las_demas_de_cmids_no_colocadas_aun_no_hacen_patron() -> None:
    # 2 y 3 llegan juntas: ninguna es patrón de la otra hasta que se coloca.
    estructura = curso((1,), (2, 3))
    notas = arbol(
        cat("cg10", "Ev1"), cat("cg20", "Ev2"), nota(1, "cg10"), nota(2, RAIZ), nota(3, "cg20")
    )
    movimientos, _ = colocar(estructura, notas, [2, 3])
    assert [(m.cmid, m.categoria) for m in movimientos] == [(2, "cg10"), (3, "cg10")]


def test_una_sin_colocar_no_hace_patron_para_la_siguiente() -> None:
    estructura = curso((1, 2))
    notas = arbol(nota(1, RAIZ), nota(2, RAIZ))
    _, sin = colocar(estructura, notas, [1, 2])
    assert sin == (SinColocar(1, "SIN_PATRON", None), SinColocar(2, "SIN_PATRON", None))


def test_de_cmid_y_raiz_del_arbol() -> None:
    notas = arbol(cat("cg10", "Ev1"), nota(1, "cg10"))
    assert notas.raiz() == RAIZ
    assert notas.fila("cg10") is not None and notas.fila("nada") is None
    fila = notas.de_cmid(1)
    assert fila is not None and fila.eid == "ig1"
    assert notas.de_cmid(99) is None
