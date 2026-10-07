"""Tests offline del buzón de ficheros entre el agente y la sesión del docente."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dobles import enlace_simbolico
from tiza import buzon


def ahora() -> datetime:
    return datetime.now(UTC)


def peticion_valida(**cambios) -> dict:
    base = {
        "version": buzon.VERSION_PROTOCOLO,
        "id": "a" * 32,
        "comando": "publicar",
        "ficheros": ["pagina.md"],
        "entorno": "pruebas",
        "visible": False,
    }
    base.update(cambios)
    return base


def informe_ok(peticion: dict) -> dict:
    publicar = peticion["comando"] == "publicar"
    return {
        "version": 1,
        "comando": peticion["comando"],
        "entorno": peticion["entorno"],
        "curso": 1234 if publicar else None,
        "resultado": "ok",
        "pasos": [],
        "ficheros": [],
        "errores": [],
    }


def crear_peticion(carpeta: Path, peticion: dict) -> Path:
    ruta = carpeta / f"{peticion['id']}{buzon.SUFIJO_PETICION}"
    ruta.write_text(json.dumps(peticion), encoding="utf-8")
    return ruta


def esperar(ruta: Path, intentos: int = 400) -> None:
    for _ in range(intentos):
        if ruta.exists():
            return
        time.sleep(0.005)
    raise AssertionError(f"no apareció {ruta}")


class TestValidarPeticion:
    def test_publicar_valida(self):
        buzon.validar_peticion(peticion_valida())

    def test_estructura_valida(self):
        buzon.validar_peticion(peticion_valida(comando="estructura", ficheros=[], entorno=None))

    def test_rechaza_un_comando_que_no_existe(self):
        with pytest.raises(buzon.ErrorBuzon) as exc:
            buzon.validar_peticion(peticion_valida(comando="borrar"))
        assert exc.value.codigo == "PETICION_INVALIDA"

    def test_rechaza_campo_extra(self):
        with pytest.raises(buzon.ErrorBuzon) as exc:
            buzon.validar_peticion(peticion_valida(html="<div>Moodle</div>"))
        assert exc.value.codigo == "PETICION_INVALIDA"

    def test_rechaza_campo_faltante(self):
        peticion = peticion_valida()
        del peticion["visible"]
        with pytest.raises(buzon.ErrorBuzon):
            buzon.validar_peticion(peticion)

    def test_rechaza_version(self):
        with pytest.raises(buzon.ErrorBuzon):
            buzon.validar_peticion(peticion_valida(version=buzon.VERSION_PROTOCOLO + 1))

    @pytest.mark.parametrize("id_", ["A" * 32, "a" * 31, "g" * 32, "", 123, None])
    def test_rechaza_id_invalido(self, id_):
        with pytest.raises(buzon.ErrorBuzon):
            buzon.validar_peticion(peticion_valida(id=id_))

    @pytest.mark.parametrize("comando", ["borrar", "PUBLICAR", "", None, 1])
    def test_rechaza_comando(self, comando):
        with pytest.raises(buzon.ErrorBuzon):
            buzon.validar_peticion(peticion_valida(comando=comando))

    @pytest.mark.parametrize("entorno", ["otro", "REAL", "", 1, True])
    def test_rechaza_entorno(self, entorno):
        with pytest.raises(buzon.ErrorBuzon):
            buzon.validar_peticion(peticion_valida(entorno=entorno))

    def test_publicar_exige_entorno(self):
        with pytest.raises(buzon.ErrorBuzon):
            buzon.validar_peticion(peticion_valida(entorno=None))

    def test_publicar_exige_ficheros(self):
        with pytest.raises(buzon.ErrorBuzon):
            buzon.validar_peticion(peticion_valida(ficheros=[]))

    def test_estructura_no_admite_ficheros(self):
        with pytest.raises(buzon.ErrorBuzon):
            buzon.validar_peticion(
                peticion_valida(comando="estructura", ficheros=["pagina.md"], entorno=None)
            )

    def test_estructura_no_admite_entorno(self):
        with pytest.raises(buzon.ErrorBuzon):
            buzon.validar_peticion(
                peticion_valida(comando="estructura", ficheros=[], entorno="pruebas")
            )

    def test_rechaza_visible_no_booleano(self):
        with pytest.raises(buzon.ErrorBuzon):
            buzon.validar_peticion(peticion_valida(visible="si"))

    def test_visible_admite_nulo(self):
        buzon.validar_peticion(peticion_valida(visible=None))

    def test_rechaza_demasiados_ficheros(self):
        muchos = [f"f{i}.md" for i in range(buzon.MAX_FICHEROS + 1)]
        with pytest.raises(buzon.ErrorBuzon):
            buzon.validar_peticion(peticion_valida(ficheros=muchos))

    def test_admite_el_maximo_de_ficheros(self):
        muchos = [f"f{i}.md" for i in range(buzon.MAX_FICHEROS)]
        buzon.validar_peticion(peticion_valida(ficheros=muchos))

    @pytest.mark.parametrize(
        "ruta",
        [
            "/etc/passwd",
            "\\etc\\passwd",
            r"C:\Windows\win.ini",
            "..",
            "../fuera.md",
            "a/../../b.md",
            "a\\..\\..\\b.md",
            "",
            "a\x01b",
            None,
            7,
        ],
    )
    def test_rechaza_rutas_fuera_de_carpeta(self, ruta):
        with pytest.raises(buzon.ErrorBuzon) as exc:
            buzon.validar_peticion(peticion_valida(ficheros=[ruta]))
        assert exc.value.codigo == "PETICION_INVALIDA"

    def test_admite_subcarpetas_relativas(self):
        buzon.validar_peticion(peticion_valida(ficheros=["tema/./pagina.md", "img/foto.png"]))


class TestLecturaDelBuzon:
    """Lo que hay en el buzón lo escribe el agente: se lee sin bloquear, con tope y sin enlaces."""

    def test_un_json_normal_se_lee(self, tmp_path):
        ruta = tmp_path / "a.json"
        ruta.write_text('{"a": 1}', encoding="utf-8")
        assert buzon._leer_json(ruta) == {"a": 1}

    def test_lo_que_pasa_del_tope_se_ignora(self, tmp_path):
        ruta = tmp_path / "grande.json"
        ruta.write_text('{"a": "' + "x" * buzon.MAX_PETICION_BYTES + '"}', encoding="utf-8")
        assert buzon._leer_json(ruta) is None

    def test_una_peticion_de_veinte_ficheros_largos_cabe_en_el_tope(self, tmp_path):
        ficheros = [f"tema{n:02d}/" + "x" * 240 + ".md" for n in range(buzon.MAX_FICHEROS)]
        ruta = tmp_path / "grande.json"
        ruta.write_text(json.dumps(peticion_valida(ficheros=ficheros)), encoding="utf-8")
        assert buzon._leer_json(ruta)["ficheros"] == ficheros

    def test_un_json_demasiado_anidado_no_tumba_la_sesion(self, tmp_path):
        ruta = tmp_path / "anidado.json"
        ruta.write_text("[" * 60000, encoding="utf-8")  # cabe en el tope, pero no en la pila
        assert buzon._leer_json(ruta) is None

    @pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="sin O_NOFOLLOW en este sistema")
    def test_un_enlace_simbolico_no_se_sigue(self, tmp_path):
        real = tmp_path / "real.json"
        real.write_text("{}", encoding="utf-8")
        enlace = tmp_path / "enlace.json"
        enlace_simbolico(enlace, real)
        assert buzon._leer_json(enlace) is None

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="sin FIFO en este sistema")
    def test_una_fifo_no_bloquea(self, tmp_path):
        fifo = tmp_path / "a.peticion.json"
        os.mkfifo(fifo)
        resultado: dict = {}
        hilo = threading.Thread(
            target=lambda: resultado.update(valor=buzon._leer_json(fifo)), daemon=True
        )
        hilo.start()
        hilo.join(5)
        assert not hilo.is_alive(), "se quedó esperando a que alguien escribiera en la FIFO"
        assert resultado == {"valor": None}


class TestCarpetasPropias:
    """``.tiza`` y ``.tiza/buzon`` son del docente: si son enlaces, no se usan."""

    def preparar(self, tmp_path):
        fuera = tmp_path / "fuera"
        fuera.mkdir()
        (fuera / "ajeno.tmp").write_text("del docente", encoding="utf-8")
        return fuera, tmp_path / ".tiza"

    def comprobar_intacto(self, fuera):
        assert [ruta.name for ruta in fuera.iterdir()] == ["ajeno.tmp"]

    def test_un_buzon_enlazado_no_abre_la_sesion(self, tmp_path):
        fuera, dir_tiza = self.preparar(tmp_path)
        dir_tiza.mkdir()
        enlace_simbolico(dir_tiza / "buzon", fuera)
        caduca = ahora() + timedelta(minutes=5)
        with pytest.raises(buzon.ErrorBuzon) as exc, buzon.abrir_sesion(dir_tiza, caduca):
            pass
        assert exc.value.codigo == "DIRECTORIO_NO_SEGURO"
        self.comprobar_intacto(fuera)

    def test_un_buzon_enlazado_no_se_limpia_al_atender(self, tmp_path):
        fuera, dir_tiza = self.preparar(tmp_path)
        dir_tiza.mkdir()
        enlace_simbolico(dir_tiza / "buzon", fuera)
        with pytest.raises(buzon.ErrorBuzon) as exc:
            buzon.atender(dir_tiza, lambda peticion: {}, ahora() + timedelta(seconds=5))
        assert exc.value.codigo == "DIRECTORIO_NO_SEGURO"
        self.comprobar_intacto(fuera)

    def test_una_carpeta_tiza_enlazada_no_abre_la_sesion(self, tmp_path):
        fuera, dir_tiza = self.preparar(tmp_path)
        enlace_simbolico(dir_tiza, fuera)
        caduca = ahora() + timedelta(minutes=5)
        with pytest.raises(buzon.ErrorBuzon) as exc, buzon.abrir_sesion(dir_tiza, caduca):
            pass
        assert exc.value.codigo == "DIRECTORIO_NO_SEGURO"
        self.comprobar_intacto(fuera)


class TestSesionActiva:
    def test_sin_fichero(self, tmp_path):
        assert buzon.sesion_activa(tmp_path) is False

    def test_vigente(self, tmp_path):
        momento = ahora()
        buzon.crear_sesion(tmp_path, momento + timedelta(minutes=5), ahora=lambda: momento)
        assert buzon.sesion_activa(tmp_path, ahora=lambda: momento) is True

    def test_caducada(self, tmp_path):
        momento = ahora()
        buzon.crear_sesion(tmp_path, momento - timedelta(seconds=1), ahora=lambda: momento)
        assert buzon.sesion_activa(tmp_path, ahora=lambda: momento + timedelta(seconds=1)) is False

    def test_latido_viejo(self, tmp_path):
        momento = ahora()
        buzon.crear_sesion(tmp_path, momento + timedelta(minutes=5), ahora=lambda: momento)
        assert (
            buzon.sesion_activa(
                tmp_path, ahora=lambda: momento + timedelta(seconds=buzon.LATIDO_MAX + 1)
            )
            is False
        )

    def test_fichero_corrupto(self, tmp_path):
        carpeta = buzon.carpeta_buzon(tmp_path)
        carpeta.mkdir(parents=True)
        (carpeta / "sesion.json").write_text("{no es json", encoding="utf-8")
        assert buzon.sesion_activa(tmp_path) is False

    def test_version_y_pid_invalidos(self, tmp_path):
        carpeta = buzon.carpeta_buzon(tmp_path)
        carpeta.mkdir(parents=True)
        ruta = carpeta / "sesion.json"
        ruta.write_text(
            json.dumps(
                {
                    "version": buzon.VERSION_PROTOCOLO + 1,
                    "pid": 1,
                    "caduca": ahora().isoformat(),
                    "latido": ahora().isoformat(),
                }
            ),
            encoding="utf-8",
        )
        assert buzon.sesion_activa(tmp_path) is False
        ruta.write_text(
            json.dumps(
                {
                    "version": buzon.VERSION_PROTOCOLO,
                    "pid": "uno",
                    "caduca": ahora().isoformat(),
                    "latido": ahora().isoformat(),
                }
            ),
            encoding="utf-8",
        )
        assert buzon.sesion_activa(tmp_path) is False

    def test_borrar_sesion(self, tmp_path):
        buzon.crear_sesion(tmp_path, ahora() + timedelta(minutes=5))
        assert buzon.sesion_activa(tmp_path) is True
        buzon.borrar_sesion(tmp_path)
        assert buzon.sesion_activa(tmp_path) is False


class TestAbrirSesion:
    def test_abre_late_y_borra(self, tmp_path):
        ruta = buzon.carpeta_buzon(tmp_path) / "sesion.json"
        with buzon.abrir_sesion(tmp_path, ahora() + timedelta(minutes=1), intervalo=0.01):
            assert buzon.sesion_activa(tmp_path) is True

            def latido() -> str:
                # En Windows, leer justo cuando el latido reemplaza el fichero da
                # PermissionError: se reintenta, como hace buzon._leer_json.
                for _ in range(100):
                    try:
                        return json.loads(ruta.read_text(encoding="utf-8"))["latido"]
                    except (OSError, ValueError):
                        time.sleep(0.002)
                raise AssertionError("no se pudo leer sesion.json")

            primero = latido()
            segundo = primero
            for _ in range(400):
                segundo = latido()
                if segundo != primero:
                    break
                time.sleep(0.005)
            assert primero != segundo
        assert not ruta.exists()


class TestLatidoResistente:
    def test_un_fallo_de_escritura_no_mata_el_latido(self, tmp_path, monkeypatch):
        real = buzon.os.replace
        fallos = []

        def replace(origen, destino):
            if str(destino).endswith("sesion.json") and not fallos and Path(destino).exists():
                fallos.append(1)
                raise PermissionError(13, "acceso denegado")
            return real(origen, destino)

        monkeypatch.setattr(buzon.os, "replace", replace)
        with buzon.abrir_sesion(tmp_path, ahora() + timedelta(minutes=1), intervalo=0.01):
            for _ in range(400):
                if fallos and buzon.sesion_activa(tmp_path, latido_max=0.1):
                    break
                time.sleep(0.005)
            time.sleep(0.05)
            assert fallos
            assert buzon.sesion_activa(tmp_path, latido_max=0.1) is True


class TestAmpliar:
    def test_ampliar_actualiza_sesion_json(self, tmp_path):
        inicio = ahora() + timedelta(minutes=1)
        with buzon.abrir_sesion(tmp_path, inicio, intervalo=0.01) as sesion:
            nueva = inicio + timedelta(minutes=30)
            sesion.ampliar(nueva)
            datos = json.loads((buzon.carpeta_buzon(tmp_path) / "sesion.json").read_text("utf-8"))
            assert datetime.fromisoformat(datos["caduca"]) == nueva
            time.sleep(0.05)  # el latido no debe volver a la caducidad antigua
            datos = json.loads((buzon.carpeta_buzon(tmp_path) / "sesion.json").read_text("utf-8"))
            assert datetime.fromisoformat(datos["caduca"]) == nueva

    def test_ampliar_reactiva_una_sesion_caducada(self, tmp_path):
        momento = ahora()
        with buzon.abrir_sesion(tmp_path, momento - timedelta(seconds=1)) as sesion:
            assert buzon.sesion_activa(tmp_path) is False
            sesion.ampliar(momento + timedelta(minutes=30))
            assert buzon.sesion_activa(tmp_path) is True

    def test_ampliar_exige_alargar(self, tmp_path):
        inicio = ahora() + timedelta(minutes=5)
        with buzon.abrir_sesion(tmp_path, inicio) as sesion, pytest.raises(ValueError):
            sesion.ampliar(inicio)

    def test_ampliar_tolera_fallo_de_escritura(self, tmp_path, monkeypatch):
        inicio = ahora() + timedelta(minutes=1)
        with buzon.abrir_sesion(tmp_path, inicio, intervalo=3600) as sesion:
            monkeypatch.setattr(buzon.os, "replace", lambda *a: (_ for _ in ()).throw(OSError()))
            sesion.ampliar(inicio + timedelta(minutes=30))  # no lanza
            assert sesion.caduca == inicio + timedelta(minutes=30)


class TestPeticionPendiente:
    def test_pendiente_mientras_exista_el_fichero(self, tmp_path):
        carpeta = buzon.carpeta_buzon(tmp_path)
        carpeta.mkdir(parents=True)
        peticion = peticion_valida()
        assert buzon.peticion_pendiente(tmp_path, peticion["id"]) is False
        ruta = crear_peticion(carpeta, peticion)
        assert buzon.peticion_pendiente(tmp_path, peticion["id"]) is True
        ruta.unlink()
        assert buzon.peticion_pendiente(tmp_path, peticion["id"]) is False


class TestEnviar:
    def test_sin_sesion_falla(self, tmp_path):
        with pytest.raises(buzon.ErrorBuzon) as exc:
            buzon.enviar(tmp_path, peticion_valida(), espera=0.01)
        assert exc.value.codigo == "SESION_CERRADA"
        assert list(buzon.carpeta_buzon(tmp_path).glob("*.peticion.json")) == []

    def test_recibe_respuesta_y_limpia(self, tmp_path):
        buzon.crear_sesion(tmp_path, ahora() + timedelta(minutes=5))
        ruta_peticion = buzon.carpeta_buzon(tmp_path) / f"{'a' * 32}{buzon.SUFIJO_PETICION}"
        recibidas: dict = {}

        def docente():
            esperar(ruta_peticion)
            recibidas["peticion"] = json.loads(ruta_peticion.read_text(encoding="utf-8"))
            respuesta = ruta_peticion.with_name(f"{'a' * 32}{buzon.SUFIJO_RESPUESTA}")
            respuesta.write_text(json.dumps(informe_ok(recibidas["peticion"])), encoding="utf-8")

        hilo = threading.Thread(target=docente)
        hilo.start()
        respuesta = buzon.enviar(tmp_path, peticion_valida(), espera=5, intervalo=0.005)
        hilo.join()
        assert respuesta["resultado"] == "ok"
        assert recibidas["peticion"]["id"] == "a" * 32
        assert not ruta_peticion.exists()
        assert not ruta_peticion.with_name(f"{'a' * 32}{buzon.SUFIJO_RESPUESTA}").exists()

    def test_sin_respuesta(self, tmp_path):
        buzon.crear_sesion(tmp_path, ahora() + timedelta(minutes=5))
        with pytest.raises(buzon.ErrorBuzon) as exc:
            buzon.enviar(tmp_path, peticion_valida(), espera=0.05, intervalo=0.005)
        assert exc.value.codigo == "SIN_RESPUESTA"
        assert list(buzon.carpeta_buzon(tmp_path).glob("*.peticion.json")) == []

    def test_sesion_cerrada_durante_la_espera(self, tmp_path):
        buzon.crear_sesion(tmp_path, ahora() + timedelta(minutes=5))

        def cerrar():
            time.sleep(0.02)
            buzon.borrar_sesion(tmp_path)

        hilo = threading.Thread(target=cerrar)
        hilo.start()
        with pytest.raises(buzon.ErrorBuzon) as exc:
            buzon.enviar(tmp_path, peticion_valida(), espera=5, intervalo=0.005)
        hilo.join()
        assert exc.value.codigo == "SESION_CERRADA"
        assert list(buzon.carpeta_buzon(tmp_path).glob("*.peticion.json")) == []

    def test_respuesta_invalida(self, tmp_path):
        buzon.crear_sesion(tmp_path, ahora() + timedelta(minutes=5))
        ruta_peticion = buzon.carpeta_buzon(tmp_path) / f"{'a' * 32}{buzon.SUFIJO_PETICION}"

        def docente():
            esperar(ruta_peticion)
            respuesta = ruta_peticion.with_name(f"{'a' * 32}{buzon.SUFIJO_RESPUESTA}")
            respuesta.write_text(
                json.dumps({"version": 1, "html": "<div>Moodle</div>"}),
                encoding="utf-8",
            )

        hilo = threading.Thread(target=docente)
        hilo.start()
        with pytest.raises(buzon.ErrorBuzon) as exc:
            buzon.enviar(tmp_path, peticion_valida(), espera=5, intervalo=0.005)
        hilo.join()
        assert exc.value.codigo == "RESPUESTA_INVALIDA"
        assert list(buzon.carpeta_buzon(tmp_path).glob("*.respuesta.json")) == []


class TestAtender:
    def servir(self, tmp_path, procesar, *, segundos=0.3):
        """Arranca ``atender`` en un hilo y espera a que termine su limpieza."""
        listo = threading.Event()
        paso = threading.Event()
        primera = [True]

        def dormir(segundos):
            listo.set()
            if primera[0]:
                primera[0] = False
                paso.wait(timeout=2)
            else:
                time.sleep(min(segundos, 0.01))

        caduca = ahora() + timedelta(seconds=segundos)
        hilo = threading.Thread(
            target=lambda: buzon.atender(tmp_path, procesar, caduca, intervalo=0.01, dormir=dormir),
            daemon=True,
        )
        hilo.start()
        assert listo.wait(timeout=2)
        return hilo, paso

    def test_procesa_en_orden_y_escribe_respuestas(self, tmp_path):
        carpeta = buzon.carpeta_buzon(tmp_path)
        vistas: list[str] = []

        def procesar(peticion):
            vistas.append(peticion["id"])
            return informe_ok(peticion)

        hilo, paso = self.servir(tmp_path, procesar)
        crear_peticion(carpeta, peticion_valida(id="b" * 32))
        crear_peticion(carpeta, peticion_valida(id="a" * 32))
        paso.set()
        for id_ in ("a" * 32, "b" * 32):
            esperar(carpeta / f"{id_}{buzon.SUFIJO_RESPUESTA}")
        hilo.join(timeout=3)
        assert vistas == ["a" * 32, "b" * 32]
        for id_ in ("a" * 32, "b" * 32):
            assert not (carpeta / f"{id_}{buzon.SUFIJO_PETICION}").exists()
            datos = json.loads(
                (carpeta / f"{id_}{buzon.SUFIJO_RESPUESTA}").read_text(encoding="utf-8")
            )
            assert datos["resultado"] == "ok"

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="sin FIFO en este sistema")
    def test_una_fifo_en_el_buzon_no_cuelga_la_sesion(self, tmp_path):
        carpeta = buzon.carpeta_buzon(tmp_path)
        hilo, paso = self.servir(tmp_path, informe_ok)
        os.mkfifo(carpeta / f"{'a' * 32}{buzon.SUFIJO_PETICION}")  # va antes que la buena
        crear_peticion(carpeta, peticion_valida(id="b" * 32))
        paso.set()
        esperar(carpeta / f"{'b' * 32}{buzon.SUFIJO_RESPUESTA}")
        hilo.join(timeout=3)
        assert not (carpeta / f"{'a' * 32}{buzon.SUFIJO_PETICION}").exists()

    def test_una_peticion_demasiado_anidada_no_tumba_la_sesion(self, tmp_path):
        carpeta = buzon.carpeta_buzon(tmp_path)
        hilo, paso = self.servir(tmp_path, informe_ok)
        (carpeta / f"{'a' * 32}{buzon.SUFIJO_PETICION}").write_text("[" * 60000, encoding="utf-8")
        crear_peticion(carpeta, peticion_valida(id="b" * 32))
        paso.set()
        esperar(carpeta / f"{'b' * 32}{buzon.SUFIJO_RESPUESTA}")
        hilo.join(timeout=3)

    def test_limpia_lo_que_queda_al_arrancar(self, tmp_path):
        carpeta = buzon.carpeta_buzon(tmp_path)
        carpeta.mkdir(parents=True)
        crear_peticion(carpeta, peticion_valida(id="a" * 32))
        (carpeta / f"{'b' * 32}{buzon.SUFIJO_RESPUESTA}").write_text("{}", encoding="utf-8")
        (carpeta / "resto.tmp").write_text("basura", encoding="utf-8")

        def procesar(peticion):
            raise AssertionError("no debe procesar una petición caducada")

        buzon.atender(tmp_path, procesar, ahora() - timedelta(seconds=1), intervalo=0.01)
        assert list(carpeta.iterdir()) == []

    def test_error_del_procesador_no_rompe(self, tmp_path):
        def procesar(peticion):
            raise RuntimeError("boom")

        hilo, paso = self.servir(tmp_path, procesar)
        crear_peticion(buzon.carpeta_buzon(tmp_path), peticion_valida(id="a" * 32))
        paso.set()
        ruta = buzon.carpeta_buzon(tmp_path) / f"{'a' * 32}{buzon.SUFIJO_RESPUESTA}"
        esperar(ruta)
        hilo.join(timeout=3)
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        assert datos["resultado"] == "error"
        assert datos["errores"] == ["ERROR_INTERNO"]
        assert "boom" not in json.dumps(datos)

    def test_respuesta_fuera_del_esquema_se_sustituye(self, tmp_path):
        def procesar(peticion):
            return {"html_moodle": "<div>secreto</div>"}

        hilo, paso = self.servir(tmp_path, procesar)
        crear_peticion(buzon.carpeta_buzon(tmp_path), peticion_valida(id="a" * 32))
        paso.set()
        ruta = buzon.carpeta_buzon(tmp_path) / f"{'a' * 32}{buzon.SUFIJO_RESPUESTA}"
        esperar(ruta)
        hilo.join(timeout=3)
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        assert datos["errores"] == ["ERROR_INTERNO"]
        assert "<" not in json.dumps(datos)

    def test_descarta_peticiones_invalidas(self, tmp_path):
        def procesar(peticion):
            raise AssertionError("no debe procesar una petición inválida")

        hilo, paso = self.servir(tmp_path, procesar)
        carpeta = buzon.carpeta_buzon(tmp_path)
        (carpeta / f"{'a' * 32}{buzon.SUFIJO_PETICION}").write_text("no es json", encoding="utf-8")
        crear_peticion(carpeta, peticion_valida(id="b" * 32, ficheros=["/etc/passwd"]))
        paso.set()
        for id_ in ("a" * 32, "b" * 32):
            ruta = carpeta / f"{id_}{buzon.SUFIJO_PETICION}"
            for _ in range(400):
                if not ruta.exists():
                    break
                time.sleep(0.005)
            assert not ruta.exists()
        hilo.join(timeout=3)


def test_atender_termina_cuando_lo_pide_la_respuesta(tmp_path):
    carpeta = buzon.carpeta_buzon(tmp_path)
    carpeta.mkdir(parents=True)
    vistas = []

    def procesar(peticion):
        vistas.append(peticion["id"])
        documento = informe_ok(peticion)
        documento["resultado"] = "error"
        documento["errores"] = ["SESION_CADUCADA"]
        return documento

    def dormir(_segundos):
        if not vistas:
            crear_peticion(carpeta, peticion_valida())

    terminada = buzon.atender(
        tmp_path,
        procesar,
        ahora() + timedelta(seconds=5),
        intervalo=0.01,
        dormir=dormir,
        terminar=lambda documento: "SESION_CADUCADA" in documento["errores"],
    )
    assert terminada is True
    assert vistas == ["a" * 32]
    assert (carpeta / f"{'a' * 32}{buzon.SUFIJO_RESPUESTA}").is_file()


def test_atender_llama_al_esperar(tmp_path):
    llamadas: list = []
    momentos = iter([ahora(), ahora() + timedelta(hours=1)])  # una vuelta y fin
    buzon.atender(
        tmp_path,
        lambda peticion: {},
        ahora() + timedelta(minutes=1),
        dormir=lambda _s: None,
        ahora=lambda: next(momentos),
        al_esperar=lambda: llamadas.append(1),
    )
    assert llamadas == [1]


def test_enviar_ya_no_compara_huellas(tmp_path):
    buzon.crear_sesion(tmp_path, ahora() + timedelta(minutes=5))
    ruta = buzon.carpeta_buzon(tmp_path) / buzon.SESION
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["huella"] = "0" * 64  # otra instalación u otra versión de tiza
    datos["tiza"] = "0.0.1"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    carpeta = buzon.carpeta_buzon(tmp_path)

    def responder(_segundos):
        (carpeta / f"{'a' * 32}{buzon.SUFIJO_RESPUESTA}").write_text(
            json.dumps(informe_ok(peticion_valida())), encoding="utf-8"
        )

    respuesta = buzon.enviar(tmp_path, peticion_valida(), espera=5, dormir=responder)
    assert respuesta["resultado"] == "ok"


def test_atender_avisa_al_docente_del_error_interno(tmp_path):
    carpeta = buzon.carpeta_buzon(tmp_path)
    carpeta.mkdir(parents=True)
    fallos = []

    def procesar(peticion):
        raise KeyError("x")

    def dormir(_segundos):
        if not fallos and not list(carpeta.glob("*.respuesta.json")):
            crear_peticion(carpeta, peticion_valida())

    buzon.atender(
        tmp_path,
        procesar,
        ahora() + timedelta(seconds=0.3),
        intervalo=0.01,
        dormir=dormir,
        al_fallar=fallos.append,
        terminar=lambda documento: True,
    )
    assert len(fallos) == 1 and isinstance(fallos[0], KeyError)
    respuesta = json.loads(next(carpeta.glob("*.respuesta.json")).read_text(encoding="utf-8"))
    assert respuesta["errores"] == ["ERROR_INTERNO"]


def test_atender_avisa_si_la_respuesta_no_cumple_el_esquema(tmp_path):
    carpeta = buzon.carpeta_buzon(tmp_path)
    carpeta.mkdir(parents=True)
    fallos = []

    def procesar(peticion):
        documento = informe_ok(peticion)
        documento["curso"] = "838"  # texto donde el esquema exige un entero
        return documento

    def dormir(_segundos):
        if not list(carpeta.glob("*.respuesta.json")):
            crear_peticion(carpeta, peticion_valida())

    buzon.atender(
        tmp_path,
        procesar,
        ahora() + timedelta(seconds=0.3),
        intervalo=0.01,
        dormir=dormir,
        al_fallar=fallos.append,
        terminar=lambda documento: True,
    )
    assert len(fallos) == 1


class TestUnaSolaSesion:
    def test_no_se_abren_dos_sesiones_en_la_misma_carpeta(self, tmp_path):
        caduca = ahora() + timedelta(minutes=1)
        with buzon.abrir_sesion(tmp_path, caduca, intervalo=0.01):
            with (
                pytest.raises(buzon.ErrorBuzon) as exc,
                buzon.abrir_sesion(tmp_path, caduca, intervalo=0.01),
            ):
                pass
            assert exc.value.codigo == "SESION_YA_ABIERTA"
            assert "20 segundos" in exc.value.detalle
            assert buzon.sesion_activa(tmp_path) is True  # la primera sigue viva
        assert not (buzon.carpeta_buzon(tmp_path) / buzon.RESERVA).exists()

    def test_una_reserva_reciente_bloquea_aunque_aun_no_lata(self, tmp_path):
        carpeta = buzon.carpeta_buzon(tmp_path)
        carpeta.mkdir(parents=True)
        (carpeta / buzon.RESERVA).write_text("1\n", encoding="utf-8")
        with (
            pytest.raises(buzon.ErrorBuzon) as exc,
            buzon.abrir_sesion(tmp_path, ahora() + timedelta(minutes=1)),
        ):
            pass
        assert exc.value.codigo == "SESION_YA_ABIERTA"

    def test_una_reserva_abandonada_no_bloquea(self, tmp_path):
        carpeta = buzon.carpeta_buzon(tmp_path)
        carpeta.mkdir(parents=True)
        reserva = carpeta / buzon.RESERVA
        reserva.write_text("999999\n", encoding="utf-8")
        viejo = time.time() - buzon.LATIDO_MAX - 5
        os.utime(reserva, (viejo, viejo))
        with buzon.abrir_sesion(tmp_path, ahora() + timedelta(minutes=1), intervalo=0.01):
            assert buzon.sesion_activa(tmp_path) is True
        assert not reserva.exists()


class TestPeticionRenovada:
    def test_peticion_sin_renovar_ya_no_esta_pendiente(self, tmp_path):
        carpeta = buzon.carpeta_buzon(tmp_path)
        carpeta.mkdir(parents=True)
        ruta = crear_peticion(carpeta, peticion_valida())
        assert buzon.peticion_pendiente(tmp_path, "a" * 32) is True
        viejo = time.time() - buzon.LATIDO_MAX - 1
        os.utime(ruta, (viejo, viejo))
        assert buzon.peticion_pendiente(tmp_path, "a" * 32) is False

    def test_enviar_renueva_su_peticion_mientras_espera(self, tmp_path):
        buzon.crear_sesion(tmp_path, ahora() + timedelta(minutes=5))
        carpeta = buzon.carpeta_buzon(tmp_path)
        ruta = carpeta / f"{'a' * 32}{buzon.SUFIJO_PETICION}"
        vistas: list[bool] = []

        def dormir(_segundos):
            vistas.append(buzon.peticion_pendiente(tmp_path, "a" * 32))
            if len(vistas) == 1:
                viejo = time.time() - buzon.LATIDO_MAX - 1
                os.utime(ruta, (viejo, viejo))  # como si el agente se hubiera colgado
            else:
                (carpeta / f"{'a' * 32}{buzon.SUFIJO_RESPUESTA}").write_text(
                    json.dumps(informe_ok(peticion_valida())), encoding="utf-8"
                )

        respuesta = buzon.enviar(tmp_path, peticion_valida(), espera=5, dormir=dormir)
        assert respuesta["resultado"] == "ok"
        assert vistas == [True, True]  # la segunda vuelta la volvió a renovar


class TestProtocolo:
    def test_sesion_json_dice_la_version_de_tiza(self, tmp_path):
        from tiza import __version__

        ruta = buzon.crear_sesion(tmp_path, ahora() + timedelta(minutes=5))
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        assert datos["tiza"] == __version__
        assert datos["version"] == buzon.VERSION_PROTOCOLO

    def test_sesion_de_otro_protocolo_es_incompatible(self, tmp_path):
        ruta = buzon.crear_sesion(tmp_path, ahora() + timedelta(minutes=5))
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        datos["version"] = buzon.VERSION_PROTOCOLO + 1
        datos["tiza"] = "9.0.0"
        ruta.write_text(json.dumps(datos), encoding="utf-8")
        assert buzon.sesion_activa(tmp_path) is False
        assert buzon.sesion_incompatible(tmp_path) == "9.0.0"
        assert buzon.caducidad(tmp_path) is None

    def test_sin_sesion_no_hay_incompatible_ni_caducidad(self, tmp_path):
        assert buzon.sesion_incompatible(tmp_path) is None
        assert buzon.caducidad(tmp_path) is None

    def test_caducidad_de_la_sesion_activa(self, tmp_path):
        caduca = ahora() + timedelta(minutes=5)
        buzon.crear_sesion(tmp_path, caduca)
        assert buzon.caducidad(tmp_path) == caduca

    def test_la_sesion_responde_desactualizada_si_su_codigo_cambia(self, tmp_path, monkeypatch):
        carpeta = buzon.carpeta_buzon(tmp_path)
        monkeypatch.setattr(buzon, "huella_codigo", lambda: "f" * 64)
        procesadas: list = []
        dejadas: list = []

        def dejar_peticion():  # atender vacía el buzón al empezar: la petición llega después
            if not dejadas:
                dejadas.append(crear_peticion(carpeta, peticion_valida()))

        cerrada = buzon.atender(
            tmp_path,
            lambda peticion: procesadas.append(peticion) or informe_ok(peticion),
            ahora() + timedelta(seconds=5),
            dormir=lambda _segundos: None,
            terminar=lambda documento: True,
            al_esperar=dejar_peticion,
        )
        assert cerrada is True
        assert procesadas == []
        respuesta = json.loads(
            (carpeta / f"{'a' * 32}{buzon.SUFIJO_RESPUESTA}").read_text(encoding="utf-8")
        )
        assert respuesta["errores"] == ["SESION_DESACTUALIZADA"]

    def test_empaquetada_no_mira_los_ficheros(self, monkeypatch):
        monkeypatch.setattr(buzon.sys, "frozen", True, raising=False)
        monkeypatch.setattr(buzon, "huella_codigo", lambda: "f" * 64)
        assert buzon.codigo_intacto() is True

    def test_la_huella_cubre_los_subpaquetes(self, tmp_path, monkeypatch):
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.py").write_text("y = 1\n", encoding="utf-8")
        monkeypatch.setattr(buzon, "__file__", str(tmp_path / "buzon.py"))
        antes = buzon.huella_codigo()
        (tmp_path / "sub" / "b.py").write_text("y = 2\n", encoding="utf-8")
        assert buzon.huella_codigo() != antes


def test_atender_para_cuando_se_le_pide(tmp_path):
    procesadas: list = []
    cerrada = buzon.atender(
        tmp_path,
        lambda peticion: procesadas.append(peticion) or informe_ok(peticion),
        ahora() + timedelta(minutes=5),
        dormir=lambda _segundos: None,
        parar=lambda: True,
    )
    assert cerrada is False
    assert procesadas == []
