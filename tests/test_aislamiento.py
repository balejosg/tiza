"""Tests offline de tiza aislar / revisar. Nunca tocan el ~ real."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from tiza import aislamiento
from tiza.aislamiento import Comprobacion

SERVIDOR = "aula.ejemplo.org"


@pytest.fixture(autouse=True)
def _configuracion_del_usuario_aislada(tmp_path_factory, monkeypatch):
    """La configuración global real del usuario no se lee en los tests."""
    monkeypatch.setattr(
        aislamiento.config, "directorio_global", lambda: tmp_path_factory.mktemp("config")
    )


def faltas(comprobaciones: list[Comprobacion]) -> list[str]:
    return [c.texto for c in comprobaciones if c.estado == "falta"]


# Lo que un agente sin restricciones podría leer para entrar al aula con la sesión del docente
# o ver datos del alumnado: navegadores (y sus cachés), correo, descargas y almacenes de contraseñas.
PRIVADAS_ESPERADAS = {
    "Linux": [
        "~/.config/google-chrome",
        "~/.config/chromium",
        "~/.config/microsoft-edge",
        "~/.config/BraveSoftware",
        "~/.config/vivaldi",
        "~/.config/opera",
        "~/.mozilla",
        "~/.cache/mozilla",
        "~/.cache/google-chrome",
        "~/.cache/chromium",
        "~/snap/firefox",
        "~/snap/chromium",
        "~/.var/app/org.mozilla.firefox",
        "~/.var/app/com.google.Chrome",
        "~/.var/app/org.chromium.Chromium",
        "~/.var/app/com.brave.Browser",
        "~/.var/app/com.microsoft.Edge",
        "~/.thunderbird",
        "~/.var/app/org.mozilla.Thunderbird",
        "~/Descargas",
        "~/Downloads",
        "~/.local/share/keyrings",
        "~/.password-store",
    ],
    "Darwin": [
        "~/Library/Application Support/Google/Chrome",
        "~/Library/Application Support/Firefox",
        "~/Library/Application Support/Microsoft Edge",
        "~/Library/Application Support/BraveSoftware",
        "~/Library/Application Support/Vivaldi",
        "~/Library/Application Support/com.operasoftware.Opera",
        "~/Library/Safari",
        "~/Library/Cookies",
        "~/Library/Containers/com.apple.Safari",
        "~/Library/Caches/Google/Chrome",
        "~/Library/Caches/Firefox",
        "~/Library/Caches/com.apple.Safari",
        "~/Library/Thunderbird",
        "~/Library/Mail",
        "~/Library/Keychains",
        "~/Downloads",
    ],
    "Windows": [
        "~/AppData/Local/Google/Chrome",
        "~/AppData/Roaming/Mozilla",
        "~/AppData/Local/Mozilla",
        "~/AppData/Local/Microsoft/Edge",
        "~/AppData/Local/BraveSoftware",
        "~/AppData/Local/Vivaldi",
        "~/AppData/Roaming/Opera Software",
        "~/AppData/Roaming/Thunderbird",
        "~/AppData/Local/Thunderbird",
        "~/AppData/Roaming/Microsoft/Credentials",
        "~/AppData/Local/Microsoft/Credentials",
        "~/Downloads",
    ],
}


@pytest.mark.parametrize("sistema", sorted(PRIVADAS_ESPERADAS))
def test_las_rutas_privadas_cubren_navegadores_correo_y_almacenes_de_contrasenas(sistema):
    faltan = [
        r for r in PRIVADAS_ESPERADAS[sistema] if r not in aislamiento.rutas_privadas(sistema)
    ]
    assert faltan == []


@pytest.mark.parametrize("sistema", sorted(PRIVADAS_ESPERADAS))
def test_las_rutas_privadas_no_se_repiten(sistema):
    rutas = aislamiento.rutas_privadas(sistema)
    assert len(rutas) == len(set(rutas))


def test_las_rutas_de_tiza_son_la_configuracion_y_la_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(
        aislamiento.platformdirs, "user_config_dir", lambda app: str(tmp_path / "cfg" / app)
    )
    monkeypatch.setattr(
        aislamiento.platformdirs, "user_cache_dir", lambda app: str(tmp_path / "cache" / app)
    )
    assert aislamiento.rutas_tiza() == [
        str(tmp_path / "cfg" / "tiza"),
        str(tmp_path / "cache" / "tiza"),
    ]
    assert len(set(aislamiento.rutas_tiza())) == 2


@pytest.mark.parametrize("sistema", sorted(PRIVADAS_ESPERADAS))
def test_claude_niega_leer_y_escribir_las_rutas_de_tiza(sistema):
    nuevo, cambios = aislamiento.fusionar_claude({}, sistema, servidor=SERVIDOR)
    deny_read = nuevo["sandbox"]["filesystem"]["denyRead"]
    deny_write = nuevo["sandbox"]["filesystem"]["denyWrite"]
    assert set(aislamiento.rutas_tiza()) <= set(deny_read)
    assert set(aislamiento.rutas_tiza()) <= set(deny_write)
    assert any("escribir" in cambio for cambio in cambios)
    assert faltas(aislamiento.revisar_claude(nuevo, sistema, servidor=SERVIDOR)) == []
    # Si alguien quita las reglas, tiza revisar lo dice.
    debil = json.loads(json.dumps(nuevo))
    debil["sandbox"]["filesystem"]["denyRead"] = [
        ruta
        for ruta in debil["sandbox"]["filesystem"]["denyRead"]
        if ruta not in aislamiento.rutas_tiza()
    ]
    debil["sandbox"]["filesystem"]["denyWrite"] = []
    textos = faltas(aislamiento.revisar_claude(debil, sistema, servidor=SERVIDOR))
    assert any("tiza" in texto for texto in textos)
    assert len(textos) >= 2


def test_codex_avisa_de_que_no_puede_negar_las_rutas_de_tiza():
    texto, _, _ = aislamiento.fusionar_codex("")
    comprobaciones = aislamiento.revisar_codex(tomllib.loads(texto), confianza=True)
    assert any(c.estado == "aviso" and "configuración de tiza" in c.texto for c in comprobaciones)


def test_una_configuracion_con_la_lista_antigua_pide_repetir_tiza_aislar():
    antiguas = [
        "~/.config/google-chrome",
        "~/.config/chromium",
        "~/.config/microsoft-edge",
        "~/.mozilla",
        "~/snap/firefox",
        "~/Descargas",
        "~/Downloads",
    ]
    ajustes = {
        "sandbox": {
            "enabled": True,
            "allowUnsandboxedCommands": False,
            "network": {"deniedDomains": ["otro-servidor.example"]},
            "filesystem": {"denyRead": antiguas},
        },
        "permissions": {"deny": []},
    }
    pendientes = faltas(aislamiento.revisar_claude(ajustes, "Linux", servidor=SERVIDOR))
    assert [texto for texto in pendientes if "faltan" in texto]
    nuevo, _cambios = aislamiento.fusionar_claude(ajustes, "Linux", servidor=SERVIDOR)
    assert faltas(aislamiento.revisar_claude(nuevo, "Linux", servidor=SERVIDOR)) == []


def test_sin_servidor_configurado_la_red_queda_sin_comprobar():
    """El agente no puede leer la configuración: la red es aviso, no falta."""
    nuevo, _ = aislamiento.fusionar_claude({}, "Linux", servidor=SERVIDOR)
    comprobaciones = aislamiento.revisar_claude(nuevo, "Linux")
    assert faltas(comprobaciones) == []
    textos = [c.texto for c in comprobaciones if c.estado == "aviso"]
    assert sum("sin comprobar" in texto for texto in textos) == 2


def test_revisar_avisa_si_el_servidor_configurado_no_esta_bloqueado():
    nuevo, _ = aislamiento.fusionar_claude({}, "Linux", servidor=SERVIDOR)
    textos = faltas(aislamiento.revisar_claude(nuevo, "Linux", servidor="otro.example"))
    assert any("red bloqueada hacia otro.example" in texto for texto in textos)
    assert any("WebFetch bloqueado hacia otro.example" in texto for texto in textos)


def test_revisar_sin_acceso_a_la_configuracion_no_falla(tmp_path, monkeypatch):
    ajustes = tmp_path / "config" / "config.json"
    ajustes.parent.mkdir(parents=True)
    ajustes.write_text("{roto", encoding="utf-8")
    monkeypatch.setattr(aislamiento.config, "directorio_global", lambda: ajustes.parent)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    nuevo, _ = aislamiento.fusionar_claude({}, "Linux", servidor=SERVIDOR)
    (home / ".claude" / "settings.json").write_text(json.dumps(nuevo), encoding="utf-8")
    comprobaciones = aislamiento.revisar(home, "Linux", tmp_path / "asig")
    assert any("sin comprobar" in c.texto for c in comprobaciones)
    assert faltas(comprobaciones) == []


class TestClaude:
    def test_vacio_falta_todo(self):
        assert len(faltas(aislamiento.revisar_claude({}, "Linux"))) >= 5

    def test_fusionar_deja_todo_ok(self):
        nuevo, cambios = aislamiento.fusionar_claude({}, "Linux", servidor=SERVIDOR)
        assert cambios
        assert faltas(aislamiento.revisar_claude(nuevo, "Linux", servidor=SERVIDOR)) == []
        assert nuevo["sandbox"]["autoAllowBashIfSandboxed"] is True
        assert SERVIDOR in nuevo["sandbox"]["network"]["deniedDomains"]
        assert f"WebFetch(domain:{SERVIDOR})" in nuevo["permissions"]["deny"]

    def test_fusionar_conserva_lo_existente(self):
        ajustes = {
            "env": {"ANTHROPIC_API_KEY": "sk-secreta"},
            "permissions": {"deny": ["Bash(rm:*)"], "allow": ["Read"]},
            "sandbox": {"autoAllowBashIfSandboxed": False, "network": {"deniedDomains": ["x.org"]}},
        }
        nuevo, _ = aislamiento.fusionar_claude(ajustes, "Darwin")
        assert nuevo["env"] == {"ANTHROPIC_API_KEY": "sk-secreta"}
        assert "Bash(rm:*)" in nuevo["permissions"]["deny"]
        assert nuevo["permissions"]["allow"] == ["Read"]
        assert nuevo["sandbox"]["autoAllowBashIfSandboxed"] is False  # elección del docente
        assert "x.org" in nuevo["sandbox"]["network"]["deniedDomains"]
        assert ajustes["permissions"]["deny"] == ["Bash(rm:*)"]  # no muta la entrada

    def test_fusionar_es_idempotente(self):
        nuevo, _ = aislamiento.fusionar_claude({}, "Windows", servidor=SERVIDOR)
        otra, cambios = aislamiento.fusionar_claude(nuevo, "Windows", servidor=SERVIDOR)
        assert cambios == []
        assert otra == nuevo

    def test_fusionar_corrige_lo_que_debilita(self):
        ajustes = {
            "permissions": {"defaultMode": "bypassPermissions"},
            "sandbox": {"enabled": False, "allowUnsandboxedCommands": True},
        }
        nuevo, _ = aislamiento.fusionar_claude(ajustes, "Linux")
        assert nuevo["permissions"]["defaultMode"] == "default"
        assert nuevo["sandbox"]["enabled"] is True
        assert nuevo["sandbox"]["allowUnsandboxedCommands"] is False

    def test_forma_inesperada_no_se_toca(self):
        with pytest.raises(aislamiento.ErrorAislamiento) as exc:
            aislamiento.fusionar_claude({"sandbox": "sí"}, "Linux")
        assert exc.value.codigo == "AJUSTES_INESPERADOS"

    def test_revisar_detecta_ajustes_de_proyecto_que_debilitan(self):
        bueno, _ = aislamiento.fusionar_claude({}, "Linux")
        proyecto = [(".claude/settings.local.json", {"sandbox": {"enabled": False}})]
        textos = faltas(aislamiento.revisar_claude(bueno, "Linux", proyecto))
        assert any("settings.local.json" in texto for texto in textos)

    def test_rutas_por_sistema(self):
        assert "~/Downloads" in aislamiento.rutas_privadas("Darwin")
        assert any("AppData" in r for r in aislamiento.rutas_privadas("Windows"))
        assert "~/.mozilla" in aislamiento.rutas_privadas("Linux")

    def test_windows_avisa_del_sandbox(self):
        nuevo, _ = aislamiento.fusionar_claude({}, "Windows")
        assert any(c.estado == "aviso" for c in aislamiento.revisar_claude(nuevo, "Windows"))

    def test_revisar_tolera_listas_con_elementos_raros(self):
        ajustes = {
            "sandbox": {"network": {"deniedDomains": [["x"]]}},
            "permissions": {"deny": [{"no": "texto"}]},
        }
        assert faltas(aislamiento.revisar_claude(ajustes, "Linux"))


def test_leer_json(tmp_path):
    assert aislamiento.leer_json(tmp_path / "no.json") == {}
    (tmp_path / "roto.json").write_text("{", encoding="utf-8")
    with pytest.raises(aislamiento.ErrorAislamiento) as exc:
        aislamiento.leer_json(tmp_path / "roto.json")
    assert exc.value.codigo == "AJUSTES_ILEGIBLES"
    (tmp_path / "lista.json").write_text("[]", encoding="utf-8")
    with pytest.raises(aislamiento.ErrorAislamiento):
        aislamiento.leer_json(tmp_path / "lista.json")


class TestCodex:
    def test_vacio_se_completa_y_queda_ok(self):
        texto, cambios, manuales = aislamiento.fusionar_codex("")
        assert cambios and manuales == []
        datos = tomllib.loads(texto)
        assert datos["sandbox_mode"] == "workspace-write"
        assert datos["sandbox_workspace_write"]["network_access"] is False
        assert faltas(aislamiento.revisar_codex(datos)) == []

    def test_codex_inserta_claves_antes_de_las_tablas(self):
        original = '# mi config\nmodel = "gpt"\n\n[profiles.rapido]\nmodel = "mini"\n'
        texto, _, _ = aislamiento.fusionar_codex(original)
        datos = tomllib.loads(texto)
        assert datos["sandbox_mode"] == "workspace-write"
        assert "sandbox_mode" not in datos["profiles"]["rapido"]
        assert datos["profiles"]["rapido"]["model"] == "mini"
        assert "# mi config" in texto

    def test_valores_peligrosos_se_piden_a_mano(self):
        original = 'approval_policy = "never"\n[sandbox_workspace_write]\nnetwork_access = true\n'
        texto, _cambios, manuales = aislamiento.fusionar_codex(original)
        assert len(manuales) == 2
        datos = tomllib.loads(texto) if texto else tomllib.loads(original)
        assert datos["approval_policy"] == "never"  # no se reescribe en silencio

    def test_idempotente(self):
        texto, _, _ = aislamiento.fusionar_codex("")
        assert aislamiento.fusionar_codex(texto)[0] is None

    def test_toml_roto(self):
        with pytest.raises(aislamiento.ErrorAislamiento) as exc:
            aislamiento.fusionar_codex("[[[")
        assert exc.value.codigo == "AJUSTES_ILEGIBLES"


class TestOpencode:
    def preparar(self, tmp_path, contenido, nombre="opencode.json"):
        carpeta = tmp_path / ".config" / "opencode"
        carpeta.mkdir(parents=True)
        (carpeta / nombre).write_text(contenido, encoding="utf-8")

    def test_v1_bloquea_webfetch_pero_no_las_rutas_de_tiza(self, tmp_path):
        self.preparar(tmp_path, json.dumps({"permission": {"webfetch": "deny"}}))
        faltantes = faltas(aislamiento.revisar_opencode(tmp_path, servidor=SERVIDOR))
        assert len(faltantes) == 1 and "tiza" in faltantes[0]

    def test_v2_gana_la_ultima(self, tmp_path):
        reglas = [
            {"action": "webfetch", "resource": "*", "effect": "deny"},
            {"action": "*", "resource": "*", "effect": "allow"},
        ]
        self.preparar(tmp_path, json.dumps({"permissions": reglas}))
        assert faltas(aislamiento.revisar_opencode(tmp_path, servidor=SERVIDOR))

    def test_jsonc_es_aviso(self, tmp_path):
        self.preparar(tmp_path, '// comentario\n{"permission": {}}', "opencode.jsonc")
        estados = {c.estado for c in aislamiento.revisar_opencode(tmp_path, servidor=SERVIDOR)}
        assert "aviso" in estados and "falta" not in estados

    def test_v2_deny_despues_de_allow_general_es_ok(self, tmp_path):
        reglas = [{"action": "*", "resource": "*", "effect": "allow"}]
        reglas += json.loads(aislamiento.contenido_opencode("Linux"))["permissions"]
        self.preparar(tmp_path, json.dumps({"permissions": reglas}))
        assert faltas(aislamiento.revisar_opencode(tmp_path, servidor=SERVIDOR)) == []

    def test_v2_allow_especifico_posterior_no_se_ignora(self, tmp_path):
        reglas = [
            {"action": "*", "resource": "*", "effect": "allow"},
            {"action": "webfetch", "resource": "*", "effect": "deny"},
            {"action": "webfetch", "resource": SERVIDOR, "effect": "allow"},
        ]
        self.preparar(tmp_path, json.dumps({"permissions": reglas}))
        assert faltas(aislamiento.revisar_opencode(tmp_path, servidor=SERVIDOR))

    def test_sin_servidor_no_marca_falta_el_webfetch(self, tmp_path):
        reglas = [{"action": "*", "resource": "*", "effect": "allow"}]
        reglas += json.loads(aislamiento.contenido_opencode("Linux"))["permissions"]
        self.preparar(tmp_path, json.dumps({"permissions": reglas}))
        comprobaciones = aislamiento.revisar_opencode(tmp_path)
        assert faltas(comprobaciones) == []
        assert comprobaciones[0].estado == "aviso"
        assert "sin comprobar" in comprobaciones[0].texto

    def test_contenido_opencode_lo_acepta_revisar(self, tmp_path):
        carpeta = tmp_path / "asig"
        carpeta.mkdir()
        (carpeta / "opencode.jsonc").write_text(
            aislamiento.contenido_opencode("Linux"), encoding="utf-8"
        )
        assert faltas(aislamiento.revisar_opencode(tmp_path, carpeta, servidor=SERVIDOR)) == []

    def test_contenido_opencode_bloquea_webfetch_los_perfiles_y_tiza(self):
        datos = json.loads(aislamiento.contenido_opencode("Darwin"))
        reglas = {(r["action"], r["resource"]): r["effect"] for r in datos["permissions"]}
        assert reglas[("webfetch", "*")] == "deny"
        assert reglas[("websearch", "*")] == "deny"
        for ruta in aislamiento.rutas_privadas("Darwin"):
            assert reglas[("read", f"{ruta}/**")] == "deny"
        for ruta in aislamiento.rutas_tiza():
            patron = f"{Path(ruta).as_posix()}/**"
            assert reglas[("read", patron)] == "deny"
            assert reglas[("write", patron)] == "deny"

    def test_configuracion_opencode_crea_si_no_hay_reglas(self, tmp_path):
        home = tmp_path / "home"
        (home / ".config" / "opencode").mkdir(parents=True)
        (home / ".config" / "opencode" / "opencode.json").write_text("{}", encoding="utf-8")
        carpeta = tmp_path / "asig"
        carpeta.mkdir()
        propuesta = aislamiento.configuracion_opencode(carpeta, home, "Linux")
        assert propuesta is not None
        ruta, texto, cambios = propuesta
        assert ruta == carpeta / "opencode.jsonc"
        assert cambios
        ruta.write_text(texto, encoding="utf-8")
        assert faltas(aislamiento.revisar_opencode(home, carpeta, servidor=SERVIDOR)) == []

    def test_configuracion_opencode_no_pisa_la_de_la_carpeta(self, tmp_path):
        home = tmp_path / "home"
        (home / ".config" / "opencode").mkdir(parents=True)
        carpeta = tmp_path / "asig"
        carpeta.mkdir()
        (carpeta / "opencode.json").write_text("{}", encoding="utf-8")
        assert aislamiento.configuracion_opencode(carpeta, home, "Linux") is None

    def test_configuracion_opencode_respeta_reglas_globales(self, tmp_path):
        home = tmp_path / "home"
        global_ = home / ".config" / "opencode"
        global_.mkdir(parents=True)
        (global_ / "opencode.json").write_text(
            json.dumps({"permissions": [{"action": "shell", "resource": "*", "effect": "ask"}]}),
            encoding="utf-8",
        )
        carpeta = tmp_path / "asig"
        carpeta.mkdir()
        assert aislamiento.configuracion_opencode(carpeta, home, "Linux") is None

    def test_configuracion_opencode_con_global_ilegible_no_crea(self, tmp_path):
        home = tmp_path / "home"
        global_ = home / ".config" / "opencode"
        global_.mkdir(parents=True)
        (global_ / "opencode.json").write_text("{roto", encoding="utf-8")
        carpeta = tmp_path / "asig"
        carpeta.mkdir()
        assert aislamiento.configuracion_opencode(carpeta, home, "Linux") is None


class TestRevisar:
    def test_detecta_agentes_por_carpeta(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".copilot").mkdir()
        agentes = {c.agente for c in aislamiento.revisar(tmp_path, "Linux", tmp_path / "asig")}
        assert {"Claude Code", "Codex", "GitHub Copilot"} <= agentes

    def test_detecta_copilot_por_variable_de_entorno(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        datos = tmp_path / "copilot"
        datos.mkdir()
        monkeypatch.setenv("COPILOT_HOME", str(datos))
        agentes = {c.agente for c in aislamiento.revisar(home, "Linux", tmp_path / "asig")}
        assert "GitHub Copilot" in agentes

    def test_sin_agentes_avisa(self, tmp_path):
        comprobaciones = aislamiento.revisar(tmp_path, "Linux", tmp_path / "asig")
        assert [c.estado for c in comprobaciones] == ["aviso"]
        assert "GitHub Copilot" in comprobaciones[0].texto

    def test_revisar_carpeta_en_descargas_sin_agentes_no_falta(self, tmp_path):
        carpeta = tmp_path / "Downloads" / "mates"
        assert faltas(aislamiento.revisar(tmp_path, "Linux", carpeta)) == []

    def test_ajustes_ilegibles_es_falta(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{", encoding="utf-8")
        textos = faltas(aislamiento.revisar(tmp_path, "Linux", tmp_path))
        assert any("AJUSTES_ILEGIBLES" in t for t in textos)

    def test_copilot_solo_avisa(self, tmp_path):
        (tmp_path / ".copilot").mkdir()
        comprobaciones = aislamiento.revisar(tmp_path, "Linux", tmp_path / "asig")
        assert comprobaciones and all(c.estado == "aviso" for c in comprobaciones)

    def test_copilot_ajustes_ilegibles_es_falta(self, tmp_path):
        (tmp_path / ".copilot" / "settings.json").mkdir(parents=True)
        comprobaciones = aislamiento.revisar(tmp_path, "Linux", tmp_path / "asig")
        assert faltas(comprobaciones) == ["AJUSTES_ILEGIBLES: settings.json"]

    def test_copilot_no_muestra_el_contenido_de_los_ajustes(self, tmp_path):
        carpeta = tmp_path / ".copilot"
        carpeta.mkdir()
        (carpeta / "settings.json").write_text('{"api_key": "sk-secreta"}', encoding="utf-8")
        textos = [c.texto for c in aislamiento.revisar(tmp_path, "Linux", tmp_path / "asig")]
        assert all("sk-secreta" not in t for t in textos)


class TestCopilot:
    def test_ruta_por_defecto_y_con_variable(self, tmp_path, monkeypatch):
        monkeypatch.delenv("COPILOT_HOME", raising=False)
        assert aislamiento.ruta_copilot(tmp_path) == tmp_path / ".copilot"
        monkeypatch.setenv("COPILOT_HOME", str(tmp_path / "datos"))
        assert aislamiento.ruta_copilot(tmp_path) == tmp_path / "datos"

    def test_avisa_del_sandbox_y_del_host(self, tmp_path):
        comprobaciones = aislamiento.revisar_copilot(tmp_path, "Linux", servidor=SERVIDOR)
        textos = [c.texto for c in comprobaciones]
        assert any("sandbox" in t for t in textos)
        assert any(SERVIDOR in t for t in textos)

    def test_sin_servidor_avisa_y_no_inventa_host(self, tmp_path):
        textos = [c.texto for c in aislamiento.revisar_copilot(tmp_path, "Linux")]
        assert any("sin comprobar" in t for t in textos)
        assert all(SERVIDOR not in t for t in textos)

    def test_avisa_si_faltan_bwrap_o_slirp4netns(self, tmp_path, monkeypatch):
        monkeypatch.setattr(aislamiento.shutil, "which", lambda _nombre: None)
        textos = [c.texto for c in aislamiento.revisar_copilot(tmp_path, "Linux")]
        assert any("bwrap" in t and "slirp4netns" in t for t in textos)

    def test_no_avisa_si_esta_todo_instalado(self, tmp_path, monkeypatch):
        monkeypatch.setattr(aislamiento.shutil, "which", lambda nombre: f"/usr/bin/{nombre}")
        textos = [c.texto for c in aislamiento.revisar_copilot(tmp_path, "Linux")]
        assert all("bwrap" not in t for t in textos)

    def test_windows_avisa_de_requisitos(self, tmp_path):
        textos = [c.texto for c in aislamiento.revisar_copilot(tmp_path, "Windows")]
        assert any("25H2" in t for t in textos)


class TestProyecto:
    def test_rutas_de_proyecto(self, tmp_path):
        assert aislamiento.ruta_claude_proyecto(tmp_path) == tmp_path / ".claude" / "settings.json"
        assert aislamiento.ruta_codex_proyecto(tmp_path) == tmp_path / ".codex" / "config.toml"

    def test_confianza_codex_desde_vacio(self, tmp_path):
        texto, cambios, manuales = aislamiento.fusionar_confianza_codex("", tmp_path)
        assert cambios and manuales == []
        datos = tomllib.loads(texto)
        assert datos["projects"][str(tmp_path.resolve())]["trust_level"] == "trusted"

    def test_confianza_codex_conserva_otros_proyectos(self, tmp_path):
        original = '[projects."/otro"]\ntrust_level = "trusted"\n'
        texto, cambios, _ = aislamiento.fusionar_confianza_codex(original, tmp_path)
        datos = tomllib.loads(texto)
        assert datos["projects"]["/otro"]["trust_level"] == "trusted"
        assert datos["projects"][str(tmp_path.resolve())]["trust_level"] == "trusted"
        assert cambios

    def test_confianza_codex_ya_marcada(self, tmp_path):
        clave = str(tmp_path.resolve())
        original = f'[projects.{json.dumps(clave)}]\ntrust_level = "trusted"\n'
        assert aislamiento.fusionar_confianza_codex(original, tmp_path) == (None, [], [])

    def test_confianza_codex_untrusted_es_manual(self, tmp_path):
        clave = str(tmp_path.resolve())
        original = f'[projects.{json.dumps(clave)}]\ntrust_level = "untrusted"\n'
        texto, cambios, manuales = aislamiento.fusionar_confianza_codex(original, tmp_path)
        assert texto is None and cambios == [] and manuales

    def test_revisar_claude_acepta_solo_proyecto(self):
        nuevo, _ = aislamiento.fusionar_claude({}, "Linux")
        proyecto = [(".claude/settings.json", nuevo)]
        assert faltas(aislamiento.revisar_claude({}, "Linux", proyecto)) == []

    def test_revisar_claude_solo_global_avisa(self):
        nuevo, _ = aislamiento.fusionar_claude({}, "Linux")
        comprobaciones = aislamiento.revisar_claude(nuevo, "Linux")
        assert faltas(comprobaciones) == []
        assert any(c.estado == "aviso" and "todos tus proyectos" in c.texto for c in comprobaciones)

    def test_revisar_claude_proyecto_gana_al_global(self):
        malo = {"sandbox": {"enabled": False}, "permissions": {"defaultMode": "bypassPermissions"}}
        nuevo, _ = aislamiento.fusionar_claude({}, "Linux")
        proyecto = [(".claude/settings.json", nuevo)]
        assert faltas(aislamiento.revisar_claude(malo, "Linux", proyecto)) == []

    def test_confianza_codex_clave_equivalente(self, tmp_path):
        clave = str(tmp_path.resolve())
        untrusted = f'[projects.{json.dumps(clave + "/")}]\ntrust_level = "untrusted"\n'
        texto, cambios, manuales = aislamiento.fusionar_confianza_codex(untrusted, tmp_path)
        assert texto is None and cambios == [] and manuales
        trusted = f'[projects.{json.dumps(clave + "/")}]\ntrust_level = "trusted"\n'
        assert aislamiento.fusionar_confianza_codex(trusted, tmp_path) == (None, [], [])

    def test_confianza_codex_toml_roto(self, tmp_path):
        with pytest.raises(aislamiento.ErrorAislamiento) as exc:
            aislamiento.fusionar_confianza_codex("[[[", tmp_path)
        assert exc.value.codigo == "AJUSTES_ILEGIBLES"

    def test_confianza_codex_projects_no_tabla(self, tmp_path):
        with pytest.raises(aislamiento.ErrorAislamiento) as exc:
            aislamiento.fusionar_confianza_codex("projects = 5\n", tmp_path)
        assert exc.value.codigo == "AJUSTES_INESPERADOS"

    def test_revisar_claude_proyecto_vacio_avisa(self):
        nuevo, _ = aislamiento.fusionar_claude({}, "Linux")
        proyecto = [(".claude/settings.json", {})]
        comprobaciones = aislamiento.revisar_claude(nuevo, "Linux", proyecto)
        assert any(c.estado == "aviso" and "todos tus proyectos" in c.texto for c in comprobaciones)

    def test_revisar_claude_proyecto_que_revierte_no_penaliza(self):
        nuevo, _ = aislamiento.fusionar_claude({}, "Linux")
        proyecto = [
            (".claude/settings.json", {"sandbox": {"enabled": False}}),
            (
                ".claude/settings.local.json",
                {"sandbox": {"enabled": True}, "permissions": {"defaultMode": "default"}},
            ),
        ]
        assert faltas(aislamiento.revisar_claude(nuevo, "Linux", proyecto)) == []

    def test_revisar_proyecto_codex_sin_confianza_falla(self, tmp_path):
        home = tmp_path / "home"
        (home / ".codex").mkdir(parents=True)
        carpeta = tmp_path / "asig"
        (carpeta / ".codex").mkdir(parents=True)
        texto, _, _ = aislamiento.fusionar_codex("")
        (carpeta / ".codex" / "config.toml").write_text(texto, encoding="utf-8")
        textos = faltas(aislamiento.revisar(home, "Linux", carpeta))
        assert any("confianza" in t for t in textos)

    def test_revisar_codex_acepta_proyecto_confiado(self):
        texto, _, _ = aislamiento.fusionar_codex("")
        proyecto = [(".codex/config.toml", tomllib.loads(texto))]
        assert faltas(aislamiento.revisar_codex({}, proyecto, confianza=True)) == []

    def test_revisar_codex_proyecto_sin_confianza_falla(self):
        texto, _, _ = aislamiento.fusionar_codex("")
        proyecto = [(".codex/config.toml", tomllib.loads(texto))]
        textos = faltas(aislamiento.revisar_codex({}, proyecto, confianza=False))
        assert any("confianza" in texto for texto in textos)

    def test_revisar_codex_proyecto_gana_al_global(self):
        malo = {"sandbox_mode": "danger-full-access", "approval_policy": "never"}
        texto, _, _ = aislamiento.fusionar_codex("")
        proyecto = [(".codex/config.toml", tomllib.loads(texto))]
        assert faltas(aislamiento.revisar_codex(malo, proyecto, confianza=True)) == []

    def test_revisar_codex_solo_global_avisa(self):
        texto, _, _ = aislamiento.fusionar_codex("")
        comprobaciones = aislamiento.revisar_codex(tomllib.loads(texto))
        assert faltas(comprobaciones) == []
        assert any(c.estado == "aviso" and "todos tus proyectos" in c.texto for c in comprobaciones)

    def test_revisar_opencode_acepta_proyecto(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        carpeta = tmp_path / "asig"
        carpeta.mkdir()
        (carpeta / "opencode.json").write_text(
            aislamiento.contenido_opencode("Linux"), encoding="utf-8"
        )
        assert faltas(aislamiento.revisar_opencode(home, carpeta, servidor=SERVIDOR)) == []

    def test_revisar_opencode_solo_global_avisa(self, tmp_path):
        carpeta = tmp_path / ".config" / "opencode"
        carpeta.mkdir(parents=True)
        (carpeta / "opencode.json").write_text(
            aislamiento.contenido_opencode("Linux"), encoding="utf-8"
        )
        comprobaciones = aislamiento.revisar_opencode(tmp_path, servidor=SERVIDOR)
        assert faltas(comprobaciones) == []
        assert any(c.estado == "aviso" and "todos tus proyectos" in c.texto for c in comprobaciones)

    def test_revisar_acepta_aislamiento_de_proyecto(self, tmp_path):
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".codex").mkdir()
        carpeta = tmp_path / "asig"
        (carpeta / ".claude").mkdir(parents=True)
        nuevo, _ = aislamiento.fusionar_claude({}, "Linux")
        (carpeta / ".claude" / "settings.json").write_text(json.dumps(nuevo), encoding="utf-8")
        texto, _, _ = aislamiento.fusionar_codex("")
        (carpeta / ".codex").mkdir()
        (carpeta / ".codex" / "config.toml").write_text(texto, encoding="utf-8")
        confianza, _, _ = aislamiento.fusionar_confianza_codex("", carpeta)
        (home / ".codex" / "config.toml").write_text(confianza, encoding="utf-8")
        assert faltas(aislamiento.revisar(home, "Linux", carpeta)) == []

    def test_revisar_solo_global_avisa(self, tmp_path):
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        nuevo, _ = aislamiento.fusionar_claude({}, "Linux")
        (home / ".claude" / "settings.json").write_text(json.dumps(nuevo), encoding="utf-8")
        comprobaciones = aislamiento.revisar(home, "Linux", tmp_path / "asig")
        assert faltas(comprobaciones) == []
        assert any(c.estado == "aviso" and "todos tus proyectos" in c.texto for c in comprobaciones)


class TestCarpetaEnDescargas:
    """Descargas sigue bloqueada, salvo la carpeta de la asignatura si está dentro."""

    def preparar(self, tmp_path, *partes):
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        carpeta = home.joinpath(*partes)
        carpeta.mkdir(parents=True)
        return home, carpeta

    def aislar(self, home, carpeta, sistema="Linux"):
        reabrir = aislamiento.rutas_reabiertas(home, sistema, carpeta)
        nuevo, cambios = aislamiento.fusionar_claude({}, sistema, reabrir)
        ruta = aislamiento.ruta_claude_proyecto(carpeta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(nuevo), encoding="utf-8")
        return nuevo, cambios

    @pytest.mark.parametrize("descargas", ["Descargas", "Downloads"])
    def test_rutas_reabiertas_dentro_de_descargas(self, tmp_path, descargas):
        home, carpeta = self.preparar(tmp_path, descargas, "IABach")
        assert aislamiento.rutas_reabiertas(home, "Linux", carpeta) == [str(carpeta.resolve())]

    def test_rutas_reabiertas_fuera_de_descargas(self, tmp_path):
        home, carpeta = self.preparar(tmp_path, "Asignaturas", "IABach")
        assert aislamiento.rutas_reabiertas(home, "Linux", carpeta) == []
        _nuevo, cambios = self.aislar(home, carpeta)
        assert not any("permitir leer" in c for c in cambios)

    def test_sin_reabrir_la_carpeta_falta(self, tmp_path):
        home, carpeta = self.preparar(tmp_path, "Descargas", "IABach")
        nuevo, _ = aislamiento.fusionar_claude({}, "Linux")
        aislamiento.ruta_claude_proyecto(carpeta).parent.mkdir()
        aislamiento.ruta_claude_proyecto(carpeta).write_text(json.dumps(nuevo), encoding="utf-8")
        textos = faltas(aislamiento.revisar(home, "Linux", carpeta))
        assert textos == ["carpeta de la asignatura legible dentro de Descargas"]

    def test_aislar_en_descargas_deja_todo_ok(self, tmp_path):
        home, carpeta = self.preparar(tmp_path, "Descargas", "IABach")
        nuevo, cambios = self.aislar(home, carpeta)
        filesystem = nuevo["sandbox"]["filesystem"]
        assert "~/Descargas" in filesystem["denyRead"]
        assert filesystem["allowRead"] == [str(carpeta.resolve())]
        assert any("permitir leer solo esta carpeta" in c for c in cambios)
        assert faltas(aislamiento.revisar(home, "Linux", carpeta)) == []

    def test_aislar_dos_veces_no_duplica(self, tmp_path):
        home, carpeta = self.preparar(tmp_path, "Descargas", "IABach")
        nuevo, _ = self.aislar(home, carpeta)
        reabrir = aislamiento.rutas_reabiertas(home, "Linux", carpeta)
        assert aislamiento.fusionar_claude(nuevo, "Linux", reabrir) == (nuevo, [])

    def test_carpeta_movida_vuelve_a_faltar(self, tmp_path):
        home, carpeta = self.preparar(tmp_path, "Descargas", "IABach")
        self.aislar(home, carpeta)
        movida = carpeta.rename(home / "Descargas" / "IABach2")
        textos = faltas(aislamiento.revisar(home, "Linux", movida))
        assert "carpeta de la asignatura legible dentro de Descargas" in textos

    @pytest.mark.parametrize(
        "entrada", ["~/Descargas", "~", "~/Desc*", "/", "~/.mozilla/perfil", "..", "../otra"]
    )
    def test_allow_read_que_reabre_privadas_es_falta(self, tmp_path, entrada):
        home, carpeta = self.preparar(tmp_path, "Descargas", "IABach")
        nuevo, _ = self.aislar(home, carpeta)
        nuevo["sandbox"]["filesystem"]["allowRead"].append(entrada)
        aislamiento.ruta_claude_proyecto(carpeta).write_text(json.dumps(nuevo), encoding="utf-8")
        textos = faltas(aislamiento.revisar(home, "Linux", carpeta))
        assert any("allowRead vuelve a abrir 1 rutas" in t for t in textos)

    @pytest.mark.parametrize("entrada", [".", "./temas", "~/Asignaturas", "/opt/datos"])
    def test_allow_read_inofensivo_no_falta(self, tmp_path, entrada):
        home, carpeta = self.preparar(tmp_path, "Descargas", "IABach")
        nuevo, _ = self.aislar(home, carpeta)
        nuevo["sandbox"]["filesystem"]["allowRead"].append(entrada)
        aislamiento.ruta_claude_proyecto(carpeta).write_text(json.dumps(nuevo), encoding="utf-8")
        assert faltas(aislamiento.revisar(home, "Linux", carpeta)) == []

    def test_allow_read_global_que_reabre_descargas_es_falta(self, tmp_path):
        home, carpeta = self.preparar(tmp_path, "Asignaturas", "IABach")
        nuevo, _ = aislamiento.fusionar_claude({}, "Linux")
        nuevo["sandbox"]["filesystem"]["allowRead"] = ["~/Downloads/"]
        aislamiento.ruta_claude(home).write_text(json.dumps(nuevo), encoding="utf-8")
        textos = faltas(aislamiento.revisar(home, "Linux", carpeta))
        assert any("allowRead" in t for t in textos)

    def test_opencode_reabre_la_carpeta_al_final(self, tmp_path):
        home, carpeta = self.preparar(tmp_path, "Descargas", "IABach")
        (home / ".config" / "opencode").mkdir(parents=True)
        propuesta = aislamiento.configuracion_opencode(carpeta, home, "Linux")
        assert propuesta is not None
        reglas = json.loads(propuesta[1])["permissions"]
        assert {"action": "read", "resource": "~/Descargas/**", "effect": "deny"} in reglas
        assert reglas[-1] == {
            "action": "read",
            "resource": f"{carpeta.resolve().as_posix()}/**",
            "effect": "allow",
        }

    def test_opencode_fuera_de_descargas_no_reabre(self):
        reglas = json.loads(aislamiento.contenido_opencode("Linux"))["permissions"]
        assert all(r["effect"] != "allow" or r["action"] == "*" for r in reglas)
