"""El arranque de ``tiza empezar`` como proceso común, antes de abrir la sesión.

Reproduce, en el mismo orden, lo que hace el docente al empezar: actualizar, configurar
tiza la primera vez, confirmar una carpeta dudosa y aislar el agente. Habla con el
docente solo a través de una :class:`~tiza.publicacion.Presencia`: no importa ``terminal``
ni ``cli``, de modo que la terminal y cualquier otra interfaz comparten el mismo flujo.

Lo que depende de quien arranca entra por parámetro (``version_nueva`` e ``instalar``,
``home`` y ``sistema``), igual que ``exigir_aislamiento``, que el panel pone a True: sin
agente aislado no se abre la sesión, ni se pregunta si se sigue sin aislar.
"""

from __future__ import annotations

import enum
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__, aislamiento, config, rutas
from .config import ErrorConfig
from .contenido import EXTENSIONES
from .publicacion import Aviso, FicheroAislamiento, Presencia, ResumenAislamiento

__all__ = [
    "Estado",
    "Resultado",
    "aplicar_plan",
    "configurar",
    "parece_asignatura",
    "preparar",
    "resumen_de",
]


class Estado(enum.Enum):
    SEGUIR = "seguir"  # se puede abrir la sesión
    ACTUALIZADA = "actualizada"  # se instaló una versión nueva: salir con 0 sin abrir la sesión
    ABORTADO = "abortado"  # el docente dijo que no (o canceló)
    FALLO = "fallo"  # ``codigo`` y ``detalle``


@dataclass(frozen=True)
class Resultado:
    """Cómo acabó el arranque. ``con_informe`` es False en los fallos de configuración, que
    la terminal siempre ha dado como un error suelto, sin ``.tiza/informe.json``."""

    estado: Estado
    codigo: str = ""
    detalle: str = ""
    con_informe: bool = True
    causa: BaseException | None = None  # para la traza de --debug; nunca se enseña tal cual


_SEGUIR = Resultado(Estado.SEGUIR)
_ABORTADO = Resultado(Estado.ABORTADO)


def parece_asignatura(carpeta: Path, home: Path) -> bool:
    """¿Parece la carpeta de una asignatura? (nunca la personal)."""
    if carpeta.resolve() == home.resolve():
        return False
    return (
        (carpeta / rutas.FICHERO_ASIGNATURA).is_file()
        or (carpeta / rutas.CARPETA_TRABAJO).is_dir()
        or any(ruta.suffix.lower() in EXTENSIONES for ruta in carpeta.iterdir() if ruta.is_file())
    )


def resumen_de(plan: aislamiento.Plan) -> ResumenAislamiento:
    """Lo que ve la presencia del plan: rutas y cambios, nunca el texto que se escribiría."""
    return ResumenAislamiento(
        tuple(FicheroAislamiento(e.ruta, e.cambios) for e in plan.escrituras), plan.manuales
    )


def aplicar_plan(plan: aislamiento.Plan, presencia: Presencia) -> bool:
    """Confirma el plan con el docente y lo escribe; True si se aplicó o no había nada.

    Sin escrituras no se pregunta (la presencia solo enseña los pasos manuales).
    """
    if not presencia.confirmar_aislamiento(resumen_de(plan)):
        return False
    if not plan.escrituras:
        presencia.informar(Aviso.nada_que_cambiar())
        return True
    for ruta, copia in aislamiento.aplicar(plan):
        presencia.informar(Aviso.aislamiento_guardado(ruta, copia.name if copia else None))
    presencia.informar(Aviso.reinicia_el_agente())
    return True


def configurar(presencia: Presencia) -> Resultado:
    """Pide URL y usuario del aula, valida la URL y guarda la configuración global.

    La presencia puede validar la URL antes de pedir el usuario (``validar``); lo que valida
    se recuerda para no volver a conectar con el aula al guardar.
    """
    validadas: dict[str, str] = {}

    def validar(entrada: str) -> None:
        validadas[entrada] = config.preparar_url(entrada)

    try:
        datos = presencia.configurar(validar)
        if datos is None:
            return _ABORTADO
        entrada, usuario = datos
        base = validadas[entrada] if entrada in validadas else config.preparar_url(entrada)
        ruta = config.guardar_global(base, usuario.strip())
    except ErrorConfig as exc:
        return Resultado(Estado.FALLO, exc.codigo, exc.detalle, con_informe=False, causa=exc)
    presencia.informar(Aviso.configuracion_guardada(ruta))
    return _SEGUIR


def _actualizar(
    presencia: Presencia,
    version_nueva: Callable[[], str | None],
    instalar: Callable[[str], bool],
) -> bool:
    """Ofrece la versión nueva; True si se instaló (hay que volver a abrir)."""
    nueva = version_nueva()
    if nueva is None:
        return False
    if not presencia.confirmar_actualizacion(nueva, __version__):
        return False
    if not instalar(nueva):
        presencia.informar(Aviso.sigue_la_version_actual())
        return False
    # La instalación sigue en otra ventana cuando tiza corre en Windows (``sys.platform``,
    # como en ``cli._instalar_version``), no según el ``sistema`` que se revisa para aislar.
    presencia.informar(Aviso.tiza_actualizada(sys.platform == "win32"))
    return True


def _aislar(
    carpeta: Path, presencia: Presencia, home: Path, sistema: str
) -> Resultado | list[aislamiento.Comprobacion]:
    """Aísla la carpeta; devuelve lo que sigue faltando, o el resultado si no se puede seguir."""
    servidor = aislamiento.servidor_configurado()
    try:
        plan = aislamiento.planear_carpeta(carpeta, home, sistema, servidor)
    except aislamiento.ErrorAislamiento as exc:
        return Resultado(Estado.FALLO, exc.codigo, exc.detalle, causa=exc)
    if not aplicar_plan(plan, presencia):
        return _ABORTADO
    faltas = [c for c in aislamiento.revisar(home, sistema, carpeta) if c.estado == "falta"]
    if faltas:
        presencia.informar(Aviso.sigue_faltando(faltas))
    return faltas


def preparar(
    carpeta: Path,
    presencia: Presencia,
    *,
    home: Path,
    sistema: str,
    version_nueva: Callable[[], str | None],
    instalar: Callable[[str], bool],
    exigir_aislamiento: bool = False,
) -> Resultado:
    """Todo lo que ``tiza empezar`` resuelve antes de abrir la sesión.

    ``version_nueva`` da la etiqueta más alta si es posterior a la instalada (o None) e
    ``instalar`` la instala. Con ``exigir_aislamiento`` no se ofrece seguir sin aislar:
    si el agente no queda aislado, el resultado es ``ABORTADO``.
    """
    if _actualizar(presencia, version_nueva, instalar):
        return Resultado(Estado.ACTUALIZADA)
    try:
        configurado = config.cargar_global() is not None
    except ErrorConfig:
        configurado = False
    if not configurado:
        presencia.informar(Aviso.primera_vez())
        resultado = configurar(presencia)
        if resultado.estado is not Estado.SEGUIR:
            return resultado
    if not parece_asignatura(carpeta, home) and not presencia.confirmar_carpeta_dudosa(carpeta):
        return _ABORTADO
    comprobaciones = aislamiento.revisar(home, sistema, carpeta)
    presencia.informar(Aviso.comprobaciones_de_aislamiento(comprobaciones))
    faltas = [c for c in comprobaciones if c.estado == "falta"]
    if not faltas:
        return _SEGUIR
    presencia.informar(Aviso.carpeta_no_aislada())
    if exigir_aislamiento or presencia.ofrecer_aislamiento():
        hecho = _aislar(carpeta, presencia, home, sistema)
        if isinstance(hecho, Resultado):
            return hecho
        faltas = hecho
    if not faltas:
        return _SEGUIR
    if exigir_aislamiento or not presencia.seguir_sin_aislar(faltas):
        return _ABORTADO
    return _SEGUIR
