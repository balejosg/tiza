"""Tests de la configuración local (sin contraseñas)."""

from __future__ import annotations

import json
from datetime import date

import pytest
import requests

from dobles import enlace_simbolico
from tiza import config
from tiza.config import ErrorConfig


def usar_directorio(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "prefs")


def test_global_roundtrip(tmp_path, monkeypatch):
    usar_directorio(tmp_path, monkeypatch)
    ruta = config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    resuelta = config.resolver(tmp_path / "contenido")
    assert resuelta.url == "https://aula.ejemplo.org/centro"
    assert resuelta.usuario == "profe"
    assert resuelta.cursos == {}  # los cursos son de cada carpeta
    assert "cursos" not in json.loads(ruta.read_text(encoding="utf-8"))


def test_los_cursos_salen_solo_de_la_carpeta(tmp_path, monkeypatch):
    """Unos «cursos» globales de versiones anteriores se ignoran y se descartan al guardar."""
    usar_directorio(tmp_path, monkeypatch)
    prefs = tmp_path / "prefs"
    prefs.mkdir()
    antigua = {
        "version": 1,
        "url": "https://aula.ejemplo.org/centro",
        "usuario": "profe",
        "cursos": {"pruebas": 1, "real": 2, "sin_pruebas": True},
    }
    (prefs / "config.json").write_text(json.dumps(antigua), encoding="utf-8")
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    (carpeta / "tiza.toml").write_text("[cursos]\npruebas = 10\n", encoding="utf-8")
    resuelta = config.resolver(carpeta)
    assert resuelta.cursos == {"pruebas": 10}
    assert resuelta.sin_pruebas is False
    assert config.resolver(tmp_path / "otra").cursos == {}
    config.guardar_global(resuelta.url, resuelta.usuario)
    assert "cursos" not in json.loads((prefs / "config.json").read_text(encoding="utf-8"))


def test_sin_configurar_falla(tmp_path, monkeypatch):
    usar_directorio(tmp_path, monkeypatch)
    with pytest.raises(ErrorConfig) as exc:
        config.resolver(tmp_path)
    assert exc.value.codigo == "SIN_CONFIGURAR"


def test_toml_invalido_falla(tmp_path, monkeypatch):
    usar_directorio(tmp_path, monkeypatch)
    config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    (carpeta / "tiza.toml").write_text("esto no es toml = = =", encoding="utf-8")
    with pytest.raises(ErrorConfig) as exc:
        config.resolver(carpeta)
    assert exc.value.codigo == "TIZA_TOML_INVALIDO"


def test_la_carpeta_no_puede_fijar_ni_cambiar_la_url(tmp_path, monkeypatch):
    """El fichero de la asignatura lo escribe el agente: la URL solo sale de la global."""
    usar_directorio(tmp_path, monkeypatch)
    config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    (carpeta / "tiza.toml").write_text(
        'url = "https://evil.example"\n[cursos]\nreal = 9\n', encoding="utf-8"
    )
    resuelta = config.resolver(carpeta)
    assert resuelta.url == "https://aula.ejemplo.org/centro"
    assert resuelta.reales == (9,)


def test_guardar_carpeta_no_puede_fijar_la_url(tmp_path):
    original = 'url = "https://evil.example"\n[cursos]\nreal = 2\n'
    (tmp_path / "tiza.toml").write_text(original, encoding="utf-8")
    with pytest.raises(ErrorConfig) as exc:
        config.guardar_carpeta(tmp_path, {"pruebas": 1234})
    assert exc.value.codigo == "TIZA_TOML_INVALIDO"
    assert (tmp_path / "tiza.toml").read_text(encoding="utf-8") == original


def test_curso_no_entero_falla(tmp_path, monkeypatch):
    usar_directorio(tmp_path, monkeypatch)
    config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    (tmp_path / "tiza.toml").write_text('[cursos]\npruebas = "uno"\nreal = 2\n', encoding="utf-8")
    with pytest.raises(ErrorConfig) as exc:
        config.resolver(tmp_path)
    assert exc.value.codigo == "CURSO_INVALIDO"


def test_el_fichero_no_contiene_password(tmp_path, monkeypatch):
    usar_directorio(tmp_path, monkeypatch)
    ruta = config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    texto = ruta.read_text(encoding="utf-8")
    assert "password" not in texto.lower()
    assert "contraseña" not in texto.lower()


def test_url_de_cualquier_aula_https_se_acepta():
    for url in [
        "https://aula.ejemplo.org/centro",
        "https://aula.ejemplo.org",
        "https://Aula.EJEMPLO.org/centro",
        "https://aula.ejemplo.org:443/centro",
        "https://aula.ejemplo.org:8443/centro",
        "https://aula.ejemplo.org/centro/login/index.php?a=1&b=2#ancla",
        "https://aula.ejemplo.org/a%20b",
    ]:
        assert config.validar_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://aula.ejemplo.org/centro",
        "https://user:pass@aula.ejemplo.org/centro",
        # urlsplit y requests pueden leer servidores distintos con estos trucos
        "https://evil.example\\aula.ejemplo.org/centro",
        "https://evil.example\\@aula.ejemplo.org/",
        "https://aula.ejemplo.org\\@evil.example/",
        "https://evil.example%2f.aula.ejemplo.org/",
        "https://evil.example:443\\.aula.ejemplo.org/",
        # espacios, tabuladores y caracteres no ASCII (incluida una «а» cirílica)
        "https://aula.ejemplo.org/centro con espacio",
        "https://aula.ejemplo.org/\tcentro",
        "https://aula.ejemplo.org/ñ",
        "https://аula.ejemplo.org/",
        # puertos y formas raras
        "https://aula.ejemplo.org:abc/",
        "https://aula.ejemplo.org:99999/",
        "https://[::1]/",
        "//aula.ejemplo.org/centro",
        "https://",
        "",
    ],
)
def test_url_que_se_lee_distinto_o_con_trucos_se_rechaza(url):
    with pytest.raises(config.ErrorConfig) as exc:
        config.validar_url(url)
    assert exc.value.codigo == "URL_NO_PERMITIDA"


@pytest.mark.parametrize("url", [None, 5, b"https://aula.ejemplo.org"])
def test_lo_que_no_es_texto_se_rechaza(url):
    with pytest.raises(config.ErrorConfig) as exc:
        config.validar_url(url)
    assert exc.value.codigo == "URL_NO_PERMITIDA"


class TestAdaptadorAula:
    """La sesión del aula no deja salir nada hacia otro servidor, redirecciones incluidas."""

    SERVIDOR = "https://aula.ejemplo.org/centro"

    @pytest.fixture
    def enviadas(self, monkeypatch):
        """Sustituye el envío real de requests (nada sale a la red) y anota lo que saldría."""
        enviadas: list[str] = []

        def enviar(self, request, *args, **opciones):
            enviadas.append(request.url)
            respuesta = requests.Response()
            respuesta.status_code = 302 if request.url.endswith("/salto") else 200
            respuesta.url = request.url
            respuesta.request = request
            if respuesta.status_code == 302:
                respuesta.headers["Location"] = "https://evil.example/robo"
            return respuesta

        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", enviar)
        return enviadas

    def sesion(self, servidor=None):
        sesion = requests.Session()
        adaptador = config.AdaptadorAula(servidor or self.SERVIDOR)
        sesion.mount("https://", adaptador)
        sesion.mount("http://", adaptador)
        return sesion

    def test_deja_pasar_el_aula(self, enviadas):
        respuesta = self.sesion().get("https://aula.ejemplo.org/centro")
        assert respuesta.status_code == 200
        assert enviadas == ["https://aula.ejemplo.org/centro"]

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example/",
            "http://aula.ejemplo.org/",
            "https://aula.ejemplo.org:8443/",
            "https://otro.aula.ejemplo.org/",
            "https://evil.example\\.aula.ejemplo.org/x",
        ],
    )
    def test_bloquea_otros_destinos_antes_de_enviar(self, enviadas, url):
        with pytest.raises(config.DestinoNoPermitido):
            self.sesion().post(url, data={"password": "secreta"})
        assert enviadas == []

    def test_bloquea_una_redireccion_hacia_fuera(self, enviadas):
        with pytest.raises(config.DestinoNoPermitido):
            self.sesion().post("https://aula.ejemplo.org/salto", data={"password": "secreta"})
        assert enviadas == ["https://aula.ejemplo.org/salto"]  # el salto no salió

    def test_acepta_el_puerto_configurado(self, enviadas):
        sesion = self.sesion("https://aula.ejemplo.org:8443/centro")
        assert sesion.get("https://aula.ejemplo.org:8443/centro").status_code == 200
        with pytest.raises(config.DestinoNoPermitido):
            sesion.get("https://aula.ejemplo.org/centro")
        assert enviadas == ["https://aula.ejemplo.org:8443/centro"]

    def test_el_error_dice_a_que_servidor_iba(self, enviadas):
        """Para que el docente pueda contarlo (con --debug): solo el servidor, saneado."""
        with pytest.raises(config.DestinoNoPermitido) as exc:
            self.sesion().get("https://evil.example/robo?token=secreto")
        assert "https://evil.example" in str(exc.value)
        assert "secreto" not in str(exc.value)
        assert "https://aula.ejemplo.org" in str(exc.value)

    def test_reenvia_a_requests_el_plazo_y_el_proxy(self, monkeypatch):
        """Con el proxy de un centro, la guardia no puede quitarle sus argumentos a requests."""
        vistos: list[dict] = []

        def enviar(self, request, *args, **opciones):
            vistos.append(opciones)
            respuesta = requests.Response()
            respuesta.status_code = 200
            respuesta.url = request.url
            respuesta.request = request
            return respuesta

        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", enviar)
        proxys = {"https": "http://proxy.centro:3128"}
        self.sesion().get("https://aula.ejemplo.org/centro", timeout=7, proxies=proxys)
        assert vistos[0]["timeout"] == 7
        assert vistos[0]["proxies"] == proxys

    def test_es_un_error_de_requests(self):
        assert issubclass(config.DestinoNoPermitido, requests.RequestException)


def test_pruebas_y_real_no_pueden_coincidir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path / "g")
    config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    (tmp_path / "tiza.toml").write_text("[cursos]\npruebas = 2\nreal = 2\n", encoding="utf-8")
    with pytest.raises(config.ErrorConfig) as exc:
        config.resolver(tmp_path)
    assert exc.value.codigo == "CURSOS_IGUALES"


def test_guardar_carpeta_crea_tiza_toml(tmp_path):
    ruta = config.guardar_carpeta(tmp_path, {"pruebas": 1234, "real": 5678})
    assert ruta == tmp_path / "tiza.toml"
    assert config.cargar_carpeta(tmp_path) == {"cursos": {"pruebas": 1234, "real": 5678}}


def test_un_tiza_toml_enlazado_se_sigue_leyendo(tmp_path):
    """Quien enlaza a propósito un tiza.toml compartido no pierde su configuración."""
    compartido = tmp_path / "compartido.toml"
    compartido.write_text("[cursos]\nreal = 5678\n", encoding="utf-8")
    carpeta = tmp_path / "asig"
    carpeta.mkdir()
    enlace_simbolico(carpeta / "tiza.toml", compartido)
    assert config.cargar_carpeta(carpeta) == {"cursos": {"real": 5678}}


def test_guardar_carpeta_se_niega_con_un_tiza_toml_enlazado(tmp_path):
    ajeno = tmp_path / "ajeno.toml"
    ajeno.write_text("[cursos]\nreal = 1\n", encoding="utf-8")  # un TOML válido de otro sitio
    enlace_simbolico(tmp_path / "tiza.toml", ajeno)
    with pytest.raises(ErrorConfig) as exc:
        config.guardar_carpeta(tmp_path, {"real": 5678})
    assert exc.value.codigo == "TIZA_TOML_INVALIDO"
    assert ajeno.read_text(encoding="utf-8") == "[cursos]\nreal = 1\n"


def test_guardar_carpeta_no_crea_nada_a_traves_de_un_enlace_roto(tmp_path):
    destino = tmp_path / "no_existe.txt"
    enlace_simbolico(tmp_path / "tiza.toml", destino)
    with pytest.raises(ErrorConfig) as exc:
        config.guardar_carpeta(tmp_path, {"real": 5678})
    assert exc.value.codigo == "TIZA_TOML_INVALIDO"
    assert not destino.exists()


def test_guardar_carpeta_fusiona(tmp_path):
    (tmp_path / "tiza.toml").write_text("[cursos]\nreal = 5678\n", encoding="utf-8")
    config.guardar_carpeta(tmp_path, {"pruebas": 1234})
    assert config.cargar_carpeta(tmp_path)["cursos"] == {"pruebas": 1234, "real": 5678}


def test_guardar_carpeta_rechaza_iguales(tmp_path):
    with pytest.raises(config.ErrorConfig) as exc:
        config.guardar_carpeta(tmp_path, {"pruebas": 1, "real": 1})
    assert exc.value.codigo == "CURSOS_IGUALES"


def test_guardar_carpeta_no_pisa_otros_datos(tmp_path):
    original = "# mis notas\n[cursos]\npruebas = 1\n[otra]\nx = 2\n"
    (tmp_path / "tiza.toml").write_text(original, encoding="utf-8")
    with pytest.raises(config.ErrorConfig) as exc:
        config.guardar_carpeta(tmp_path, {"real": 5678})
    assert exc.value.codigo == "TIZA_TOML_INVALIDO"
    assert (tmp_path / "tiza.toml").read_text(encoding="utf-8") == original


def test_guardar_carpeta_rechaza_tabla_extra_sin_comentario(tmp_path):
    original = "[otra]\nx = 2\n"
    (tmp_path / "tiza.toml").write_text(original, encoding="utf-8")
    with pytest.raises(config.ErrorConfig) as exc:
        config.guardar_carpeta(tmp_path, {"pruebas": 1234, "real": 5678})
    assert exc.value.codigo == "TIZA_TOML_INVALIDO"
    assert (tmp_path / "tiza.toml").read_text(encoding="utf-8") == original


def test_guardar_carpeta_rechaza_toml_no_utf8(tmp_path):
    (tmp_path / "tiza.toml").write_bytes(b"\xff\xfe")
    with pytest.raises(config.ErrorConfig) as exc:
        config.guardar_carpeta(tmp_path, {"pruebas": 1234, "real": 5678})
    assert exc.value.codigo == "TIZA_TOML_INVALIDO"


def test_guardar_carpeta_rechaza_cursos_no_tabla(tmp_path):
    (tmp_path / "tiza.toml").write_text("cursos = 5\n", encoding="utf-8")
    with pytest.raises(config.ErrorConfig) as exc:
        config.guardar_carpeta(tmp_path, {"pruebas": 1234, "real": 5678})
    assert exc.value.codigo == "CURSO_INVALIDO"


def test_resolver_acepta_solo_el_curso_real(tmp_path, monkeypatch):
    usar_directorio(tmp_path, monkeypatch)
    config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    (tmp_path / "tiza.toml").write_text("[cursos]\nreal = 5678\n", encoding="utf-8")
    resuelta = config.resolver(tmp_path)
    assert resuelta.cursos == {}
    assert resuelta.reales == (5678,)
    assert resuelta.sin_pruebas is False


def test_sin_pruebas_en_la_carpeta_quita_el_curso_de_pruebas(tmp_path, monkeypatch):
    usar_directorio(tmp_path, monkeypatch)
    config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    (carpeta / "tiza.toml").write_text(
        "[cursos]\nreal = 5678\nsin_pruebas = true\n", encoding="utf-8"
    )
    resuelta = config.resolver(carpeta)
    assert resuelta.cursos == {}
    assert resuelta.reales == (5678,)
    assert resuelta.sin_pruebas is True


def test_un_curso_de_pruebas_explicito_vuelve_a_ganar(tmp_path, monkeypatch):
    usar_directorio(tmp_path, monkeypatch)
    config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    (carpeta / "tiza.toml").write_text(
        "[cursos]\npruebas = 9999\nreal = 5678\nsin_pruebas = true\n", encoding="utf-8"
    )
    resuelta = config.resolver(carpeta)
    assert resuelta.cursos == {"pruebas": 9999}
    assert resuelta.reales == (5678,)
    assert resuelta.sin_pruebas is False


def test_sin_pruebas_tiene_que_ser_booleano(tmp_path, monkeypatch):
    usar_directorio(tmp_path, monkeypatch)
    config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    (carpeta / "tiza.toml").write_text("[cursos]\nsin_pruebas = 1\n", encoding="utf-8")
    with pytest.raises(ErrorConfig) as exc:
        config.resolver(carpeta)
    assert exc.value.codigo == "CURSO_INVALIDO"


def test_guardar_carpeta_guarda_sin_pruebas(tmp_path):
    ruta = config.guardar_carpeta(tmp_path, {"real": 5678}, sin_pruebas=True)
    assert ruta.read_text(encoding="utf-8") == "[cursos]\nreal = 5678\nsin_pruebas = true\n"
    assert config.cargar_carpeta(tmp_path) == {"cursos": {"real": 5678, "sin_pruebas": True}}


def test_guardar_carpeta_borra_sin_pruebas_al_elegir_curso(tmp_path):
    (tmp_path / "tiza.toml").write_text(
        "[cursos]\nreal = 5678\nsin_pruebas = true\n", encoding="utf-8"
    )
    config.guardar_carpeta(tmp_path, {"pruebas": 1234})
    assert config.cargar_carpeta(tmp_path)["cursos"] == {"pruebas": 1234, "real": 5678}


def test_guardar_carpeta_sin_pruebas_quita_el_curso_de_pruebas(tmp_path):
    (tmp_path / "tiza.toml").write_text("[cursos]\npruebas = 1234\nreal = 5678\n", encoding="utf-8")
    config.guardar_carpeta(tmp_path, {"real": 5678}, sin_pruebas=True)
    assert config.cargar_carpeta(tmp_path) == {"cursos": {"real": 5678, "sin_pruebas": True}}


def test_inicio_de_curso():
    assert config.inicio_de_curso(date(2026, 10, 3)) == date(2026, 9, 1)
    assert config.inicio_de_curso(date(2027, 2, 1)) == date(2026, 9, 1)
    assert config.inicio_de_curso(date(2026, 9, 1)) == date(2026, 9, 1)


def test_necesita_autoprueba(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path)
    hoy = date(2026, 10, 3)
    assert config.necesita_autoprueba(1234, hoy, "0.3.0") is True
    config.registrar_autoprueba(1234, hoy, "0.3.0")
    assert config.necesita_autoprueba(1234, hoy, "0.3.0") is False
    assert config.necesita_autoprueba(1234, hoy, "0.4.0") is True  # versión nueva
    assert config.necesita_autoprueba(9999, hoy, "0.3.0") is True  # otro curso
    assert config.necesita_autoprueba(1234, date(2027, 9, 2), "0.3.0") is True  # curso nuevo


def test_registrar_conserva_otros_cursos(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path)
    config.registrar_autoprueba(1, date(2026, 10, 3), "v")
    config.registrar_autoprueba(2, date(2026, 10, 3), "v")
    assert config.necesita_autoprueba(1, date(2026, 10, 3), "v") is False


def test_estado_roto_pide_autoprueba(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "directorio_global", lambda: tmp_path)
    for contenido in ("{", "[]", '{"autoprueba": {"1234": {"fecha": "ayer", "version": "v"}}}'):
        (tmp_path / "estado.json").write_text(contenido, encoding="utf-8")
        assert config.necesita_autoprueba(1234, date(2026, 10, 3), "v") is True
    config.registrar_autoprueba(1234, date(2026, 10, 3), "v")  # sobrescribe el roto
    assert config.necesita_autoprueba(1234, date(2026, 10, 3), "v") is False


class _Respuesta:
    def __init__(self, url, status_code=200, location=None):
        self.url = url
        self.status_code = status_code
        self.headers = {"Location": location} if location else {}


def test_preparar_url_normaliza(monkeypatch):
    pedidas: list = []

    def obtener(url, **opciones):
        pedidas.append((url, opciones))
        return _Respuesta(url)

    monkeypatch.setattr(config.requests, "get", obtener)
    assert config.preparar_url(" http://aula.ejemplo.org/centro ") == (
        "https://aula.ejemplo.org/centro"
    )
    assert [url for url, _ in pedidas] == ["https://aula.ejemplo.org/centro"]
    assert pedidas[0][1]["allow_redirects"] is False


def test_preparar_url_quita_el_login(monkeypatch):
    monkeypatch.setattr(config.requests, "get", lambda url, **k: _Respuesta(url))
    assert config.preparar_url("https://aula.ejemplo.org/centro/login/index.php") == (
        "https://aula.ejemplo.org/centro"
    )


def test_preparar_url_sin_esquema(monkeypatch):
    monkeypatch.setattr(config.requests, "get", lambda url, **k: _Respuesta(url + "/"))
    assert config.preparar_url("aula.ejemplo.org/centro") == ("https://aula.ejemplo.org/centro")


def test_preparar_url_sigue_redirecciones_del_mismo_servidor(monkeypatch):
    respuestas = iter(
        [
            _Respuesta("https://aula.ejemplo.org/centro", 302, "/centro/moodle"),
            _Respuesta("https://aula.ejemplo.org/centro/moodle"),
        ]
    )
    monkeypatch.setattr(config.requests, "get", lambda url, **k: next(respuestas))
    assert config.preparar_url("https://aula.ejemplo.org/centro") == (
        "https://aula.ejemplo.org/centro/moodle"
    )


def test_preparar_url_no_conecta_con_urls_invalidas(monkeypatch):
    def no_conectar(*a, **k):
        raise AssertionError("no se conecta con una URL inválida")

    monkeypatch.setattr(config.requests, "get", no_conectar)
    with pytest.raises(config.ErrorConfig) as exc:
        config.preparar_url("https://evil.example\\aula.ejemplo.org/centro")
    assert exc.value.codigo == "URL_NO_PERMITIDA"


@pytest.mark.parametrize(
    "destino",
    [
        "http://aula.ejemplo.org/centro/",  # Apache detrás de un proxy: barra por http
        "http://aula.ejemplo.org:8080/centro/",  # o por el puerto interno
        "https://aula.ejemplo.org:8443/centro/",
    ],
)
def test_preparar_url_admite_la_barra_final_aunque_redirija_por_http(monkeypatch, destino):
    pedidas: list = []

    def obtener(url, **opciones):
        pedidas.append(url)
        if url == "https://aula.ejemplo.org/centro":
            return _Respuesta(url, 301, destino)
        return _Respuesta(url)

    monkeypatch.setattr(config.requests, "get", obtener)
    assert config.preparar_url("https://aula.ejemplo.org/centro") == (
        "https://aula.ejemplo.org/centro"
    )
    # Nunca se pide nada por http ni a otro puerto: la barra se pide por https.
    assert pedidas == ["https://aula.ejemplo.org/centro", "https://aula.ejemplo.org/centro/"]


def test_preparar_url_pasa_a_https_una_redireccion_http_del_mismo_servidor(monkeypatch):
    pedidas: list = []

    def obtener(url, **opciones):
        pedidas.append(url)
        if url == "https://aula.ejemplo.org/centro":
            return _Respuesta(url, 303, "http://aula.ejemplo.org/centro/login/index.php")
        return _Respuesta(url)

    monkeypatch.setattr(config.requests, "get", obtener)
    assert config.preparar_url("https://aula.ejemplo.org/centro") == (
        "https://aula.ejemplo.org/centro"
    )
    assert pedidas[1] == "https://aula.ejemplo.org/centro/login/index.php"


@pytest.mark.parametrize(
    "destino",
    [
        "https://evil.example/",
        "https://evil.example/centro/",
        "http://evil.example/centro/",
        "https://aula.ejemplo.org:8443/",
        "http://aula.ejemplo.org:8080/otra",
        "http://usuario@aula.ejemplo.org/centro/",
    ],
)
def test_preparar_url_que_redirige_fuera_se_rechaza(monkeypatch, destino):
    monkeypatch.setattr(config.requests, "get", lambda url, **k: _Respuesta(url, 302, destino))
    with pytest.raises(config.ErrorConfig) as exc:
        config.preparar_url("https://aula.ejemplo.org/centro")
    assert exc.value.codigo == "URL_REDIRIGE_FUERA"


def test_preparar_url_que_encadena_demasiadas_redirecciones(monkeypatch):
    monkeypatch.setattr(
        config.requests,
        "get",
        lambda url, **k: _Respuesta(url, 302, "https://aula.ejemplo.org/otra"),
    )
    with pytest.raises(config.ErrorConfig) as exc:
        config.preparar_url("https://aula.ejemplo.org/centro")
    assert exc.value.codigo == "URL_INVALIDA"


def test_preparar_url_inaccesible_o_rota(monkeypatch):
    def sin_red(*a, **k):
        raise config.requests.ConnectionError("sin red")

    monkeypatch.setattr(config.requests, "get", sin_red)
    with pytest.raises(config.ErrorConfig) as exc:
        config.preparar_url("https://aula.ejemplo.org/centro")
    assert exc.value.codigo == "URL_INACCESIBLE"
    monkeypatch.setattr(config.requests, "get", lambda url, **k: _Respuesta(url, 404))
    with pytest.raises(config.ErrorConfig) as exc:
        config.preparar_url("https://aula.ejemplo.org/centro")
    assert exc.value.codigo == "URL_INVALIDA"


# --- varios cursos reales -------------------------------------------------- #


def _resolver_con(tmp_path, monkeypatch, toml: str):
    usar_directorio(tmp_path, monkeypatch)
    config.guardar_global("https://aula.ejemplo.org/centro", "profe")
    carpeta = tmp_path / "asignatura"
    carpeta.mkdir()
    (carpeta / "tiza.toml").write_text(toml, encoding="utf-8")
    return config.resolver(carpeta)


def test_real_entero_sigue_funcionando(tmp_path, monkeypatch):
    resuelta = _resolver_con(tmp_path, monkeypatch, "[cursos]\npruebas = 9\nreal = 3\n")
    assert resuelta.reales == (3,)
    assert resuelta.cursos == {"pruebas": 9}


def test_real_admite_una_lista_en_orden(tmp_path, monkeypatch):
    resuelta = _resolver_con(tmp_path, monkeypatch, "[cursos]\nreal = [7, 3, 5]\n")
    assert resuelta.reales == (7, 3, 5)
    assert resuelta.cursos == {}


def test_sin_real_no_hay_reales(tmp_path, monkeypatch):
    assert _resolver_con(tmp_path, monkeypatch, "[cursos]\npruebas = 9\n").reales == ()


@pytest.mark.parametrize(
    "valor",
    [
        "[]",
        "[1, 2, 3, 4, 5, 6, 7]",
        "[1, 1]",
        "[true]",
        "[1, true]",
        "[0]",
        "[-1]",
        '["1"]',
        "[[1]]",
    ],
)
def test_real_con_una_lista_no_valida_falla(tmp_path, monkeypatch, valor):
    with pytest.raises(ErrorConfig) as exc:
        _resolver_con(tmp_path, monkeypatch, f"[cursos]\nreal = {valor}\n")
    assert exc.value.codigo == "CURSO_INVALIDO"


def test_seis_reales_es_el_maximo(tmp_path, monkeypatch):
    resuelta = _resolver_con(tmp_path, monkeypatch, "[cursos]\nreal = [1, 2, 3, 4, 5, 6]\n")
    assert resuelta.reales == (1, 2, 3, 4, 5, 6)


def test_pruebas_no_puede_estar_entre_los_reales(tmp_path, monkeypatch):
    with pytest.raises(ErrorConfig) as exc:
        _resolver_con(tmp_path, monkeypatch, "[cursos]\npruebas = 4\nreal = [3, 4]\n")
    assert exc.value.codigo == "CURSOS_IGUALES"


def test_guardar_carpeta_escribe_uno_como_entero_y_varios_como_lista(tmp_path):
    ruta = config.guardar_carpeta(tmp_path, {"pruebas": 1, "real": [101]})
    assert ruta.read_text(encoding="utf-8") == "[cursos]\npruebas = 1\nreal = 101\n"
    config.guardar_carpeta(tmp_path, {"real": (101, 102)})
    assert ruta.read_text(encoding="utf-8") == "[cursos]\npruebas = 1\nreal = [101, 102]\n"
    assert config.cargar_carpeta(tmp_path)["cursos"]["real"] == [101, 102]


def test_guardar_carpeta_rechaza_pruebas_entre_los_reales(tmp_path):
    with pytest.raises(ErrorConfig) as exc:
        config.guardar_carpeta(tmp_path, {"pruebas": 2, "real": [1, 2]})
    assert exc.value.codigo == "CURSOS_IGUALES"


def test_guardar_carpeta_rechaza_una_lista_no_valida(tmp_path):
    with pytest.raises(ErrorConfig) as exc:
        config.guardar_carpeta(tmp_path, {"real": [1, 1]})
    assert exc.value.codigo == "CURSO_INVALIDO"
