"""El arranque de «tiza empezar» como proceso común: solo habla con la presencia."""

from __future__ import annotations

import json

import pytest

from dobles import PresenciaFalsa
from tiza import aislamiento, arranque, config, publicacion
from tiza.arranque import Estado


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Una carpeta de asignatura, un home con Claude Code y la configuración en tmp."""
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")
    monkeypatch.setattr(config, "preparar_url", lambda entrada: entrada.strip())
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    (carpeta / "tema.md").write_text("x", encoding="utf-8")
    return home, carpeta


def configurado() -> None:
    config.guardar_global("https://aula.ejemplo.org/centro", "profe")


def preparar(carpeta, presencia, home, *, nueva=None, instalar=None, **opciones):
    return arranque.preparar(
        carpeta,
        presencia,
        home=home,
        sistema="Linux",
        version_nueva=lambda: nueva,
        instalar=instalar or (lambda _nueva: True),
        **opciones,
    )


def test_sin_configuracion_configura_y_guarda(entorno):
    home, carpeta = entorno
    presencia = PresenciaFalsa(aislar=False, sin_aislar=True)
    resultado = preparar(carpeta, presencia, home)
    assert resultado.estado is Estado.SEGUIR
    assert presencia.configuraciones_pedidas == 1
    assert presencia.codigos()[:2] == ["PRIMERA_VEZ", "CONFIGURACION_GUARDADA"]
    datos = config.cargar_global()
    assert datos is not None and datos["usuario"] == "profe"


def test_con_configuracion_no_pregunta_por_ella(entorno):
    home, carpeta = entorno
    configurado()
    presencia = PresenciaFalsa(aislar=False, sin_aislar=True)
    preparar(carpeta, presencia, home)
    assert presencia.configuraciones_pedidas == 0
    assert "PRIMERA_VEZ" not in presencia.codigos()


def test_url_no_valida_es_un_fallo_sin_informe(entorno, monkeypatch):
    home, carpeta = entorno

    def rechazar(entrada):
        raise config.ErrorConfig("URL_NO_PERMITIDA", "no")

    monkeypatch.setattr(config, "preparar_url", rechazar)
    resultado = preparar(carpeta, PresenciaFalsa(), home)
    assert resultado.estado is Estado.FALLO
    assert (resultado.codigo, resultado.con_informe) == ("URL_NO_PERMITIDA", False)
    assert config.cargar_global() is None


def test_configurar_cancelado_aborta(entorno):
    home, carpeta = entorno
    resultado = preparar(carpeta, PresenciaFalsa(configuracion=None), home)
    assert resultado.estado is Estado.ABORTADO


def test_actualizacion_aceptada_no_sigue(entorno):
    home, carpeta = entorno
    instaladas: list = []
    presencia = PresenciaFalsa(actualizar=True)
    resultado = preparar(
        carpeta, presencia, home, nueva="v9.0.0", instalar=lambda n: instaladas.append(n) or True
    )
    assert resultado.estado is Estado.ACTUALIZADA
    assert instaladas == ["v9.0.0"]
    assert presencia.actualizaciones_vistas[0][0] == "v9.0.0"
    assert presencia.codigos() == ["TIZA_ACTUALIZADA"]
    assert presencia.configuraciones_pedidas == 0


def test_actualizacion_que_falla_sigue_con_la_actual(entorno):
    home, carpeta = entorno
    configurado()
    presencia = PresenciaFalsa(actualizar=True, aislar=False, sin_aislar=True)
    resultado = preparar(carpeta, presencia, home, nueva="v9.0.0", instalar=lambda _n: False)
    assert resultado.estado is Estado.SEGUIR
    assert "SIGUE_LA_VERSION_ACTUAL" in presencia.codigos()


def test_actualizacion_rechazada_sigue(entorno):
    home, carpeta = entorno
    configurado()
    presencia = PresenciaFalsa(actualizar=False, aislar=False, sin_aislar=True)
    resultado = preparar(carpeta, presencia, home, nueva="v9.0.0")
    assert resultado.estado is Estado.SEGUIR
    assert presencia.codigos().count("TIZA_ACTUALIZADA") == 0


def test_carpeta_dudosa_rechazada_aborta(entorno, tmp_path):
    home, _ = entorno
    configurado()
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    presencia = PresenciaFalsa(carpeta_dudosa=False)
    resultado = preparar(vacia, presencia, home)
    assert resultado.estado is Estado.ABORTADO
    assert presencia.carpetas_dudosas == [vacia]


def test_carpeta_dudosa_aceptada_sigue(entorno, tmp_path):
    home, _ = entorno
    configurado()
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    presencia = PresenciaFalsa(carpeta_dudosa=True, aislar=False, sin_aislar=True)
    assert preparar(vacia, presencia, home).estado is Estado.SEGUIR


def test_aislamiento_aceptado_escribe_y_sigue(entorno):
    home, carpeta = entorno
    configurado()
    presencia = PresenciaFalsa()
    resultado = preparar(carpeta, presencia, home)
    assert resultado.estado is Estado.SEGUIR
    ajustes = json.loads((carpeta / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert ajustes["sandbox"]["enabled"] is True
    assert presencia.codigos() == [
        "COMPROBACIONES_DE_AISLAMIENTO",
        "CARPETA_NO_AISLADA",
        "AISLAMIENTO_GUARDADO",
        "REINICIA_EL_AGENTE",
    ]
    resumen = presencia.resumenes_aislamiento[0]
    assert [f.ruta for f in resumen.ficheros] == [carpeta / ".claude" / "settings.json"]
    assert all(f.cambios for f in resumen.ficheros)
    assert presencia.faltas_vistas == []


def test_aislamiento_rechazado_aborta_y_no_escribe(entorno):
    home, carpeta = entorno
    configurado()
    presencia = PresenciaFalsa(aplicar_aislamiento=False)
    resultado = preparar(carpeta, presencia, home)
    assert resultado.estado is Estado.ABORTADO
    assert not (carpeta / ".claude").exists()


def test_no_aplicar_ahora_pregunta_si_se_sigue_sin_aislar(entorno):
    home, carpeta = entorno
    configurado()
    presencia = PresenciaFalsa(aislar=False, sin_aislar=False)
    assert preparar(carpeta, presencia, home).estado is Estado.ABORTADO
    assert presencia.resumenes_aislamiento == []
    assert presencia.faltas_vistas and presencia.faltas_vistas[0][0].estado == "falta"
    presencia = PresenciaFalsa(aislar=False, sin_aislar=True)
    assert preparar(carpeta, presencia, home).estado is Estado.SEGUIR


def test_agente_aislado_no_pregunta_nada(entorno):
    home, carpeta = entorno
    configurado()
    plan = aislamiento.planear_carpeta(carpeta, home, "Linux", aislamiento.servidor_configurado())
    aislamiento.aplicar(plan)
    presencia = PresenciaFalsa()
    assert preparar(carpeta, presencia, home).estado is Estado.SEGUIR
    assert presencia.ofertas_de_aislamiento == 0 and presencia.faltas_vistas == []


def _con_codex(home):
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text("", encoding="utf-8")


def test_sigue_faltando_sin_exigir_pregunta_si_se_sigue(entorno):
    home, carpeta = entorno
    configurado()
    _con_codex(home)  # hay algo que tiza no puede dejar aislado del todo sin la confianza global
    plan = aislamiento.planear_carpeta(carpeta, home, "Linux", None)
    assert plan.escrituras
    presencia = PresenciaFalsa(aplicar_aislamiento=True, sin_aislar=True)
    resultado = preparar(carpeta, presencia, home)
    assert resultado.estado is Estado.SEGUIR
    if presencia.faltas_vistas:  # sigue faltando algo tras aplicar
        assert "SIGUE_FALTANDO" in presencia.codigos()


def test_exigir_aislamiento_no_ofrece_seguir_sin_aislar(entorno, monkeypatch):
    home, carpeta = entorno
    configurado()
    # Lo aplicado no basta: la revisión sigue viendo faltas.
    falta = aislamiento.Comprobacion("Claude Code", "falta", "sin sandbox")
    monkeypatch.setattr(aislamiento, "revisar", lambda *_a: [falta])
    presencia = PresenciaFalsa(sin_aislar=True)
    resultado = preparar(carpeta, presencia, home, exigir_aislamiento=True)
    assert resultado.estado is Estado.ABORTADO
    assert presencia.ofertas_de_aislamiento == 0  # va directo al plan
    assert presencia.faltas_vistas == []  # y no pregunta si seguir sin aislar
    assert "SIGUE_FALTANDO" in presencia.codigos()


def test_exigir_aislamiento_con_agente_aislado_sigue(entorno):
    home, carpeta = entorno
    configurado()
    plan = aislamiento.planear_carpeta(carpeta, home, "Linux", aislamiento.servidor_configurado())
    aislamiento.aplicar(plan)
    resultado = preparar(carpeta, PresenciaFalsa(), home, exigir_aislamiento=True)
    assert resultado.estado is Estado.SEGUIR


def test_sin_exigir_sigue_faltando_pregunta_y_respeta_la_respuesta(entorno, monkeypatch):
    home, carpeta = entorno
    configurado()
    falta = aislamiento.Comprobacion("Claude Code", "falta", "sin sandbox")
    monkeypatch.setattr(aislamiento, "revisar", lambda *_a: [falta])
    rechaza = PresenciaFalsa(sin_aislar=False)
    assert preparar(carpeta, rechaza, home).estado is Estado.ABORTADO
    assert rechaza.faltas_vistas == [[falta]]
    acepta = PresenciaFalsa(sin_aislar=True)
    assert preparar(carpeta, acepta, home).estado is Estado.SEGUIR


def test_los_manuales_llegan_en_el_resumen(entorno):
    home, carpeta = entorno
    configurado()
    (home / ".config" / "opencode").mkdir(parents=True)
    existente = carpeta / "opencode.json"
    existente.write_text("{}", encoding="utf-8")
    presencia = PresenciaFalsa()
    preparar(carpeta, presencia, home)
    manuales = [m for r in presencia.resumenes_aislamiento for m in r.manuales]
    assert any("opencode: ya hay configuración en esta carpeta" in m for m in manuales)


def test_el_resumen_no_lleva_el_texto_que_se_escribira(entorno):
    home, carpeta = entorno
    plan = aislamiento.planear_carpeta(carpeta, home, "Linux", None)
    resumen = arranque.resumen_de(plan)
    assert isinstance(resumen, publicacion.ResumenAislamiento)
    assert all(not hasattr(f, "texto") for f in resumen.ficheros)


def test_error_de_ajustes_es_un_fallo_con_su_codigo(entorno):
    home, carpeta = entorno
    configurado()
    (carpeta / ".claude").mkdir()
    (carpeta / ".claude" / "settings.json").mkdir()  # no es un fichero
    resultado = preparar(carpeta, PresenciaFalsa(), home)
    assert resultado.estado is Estado.FALLO
    assert resultado.codigo == "AJUSTES_ILEGIBLES" and resultado.con_informe


def test_planear_global_avisa_en_windows(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    plan = aislamiento.planear_global(home, "Windows", None)
    assert plan.escrituras == () and "En Windows" in plan.manuales[0]


def test_aplicar_hace_copia_de_lo_que_existia(tmp_path):
    destino = tmp_path / "a" / "ajustes.json"
    destino.parent.mkdir()
    destino.write_text("viejo", encoding="utf-8")
    nuevo = tmp_path / "b" / "otro.json"
    plan = aislamiento.Plan(
        (aislamiento.Escritura(destino, "nuevo", ("x",)), aislamiento.Escritura(nuevo, "y", ()))
    )
    hechas = aislamiento.aplicar(plan)
    assert destino.read_text(encoding="utf-8") == "nuevo"
    assert hechas[0][1] is not None and hechas[0][1].read_text(encoding="utf-8") == "viejo"
    assert hechas[1] == (nuevo, None)
