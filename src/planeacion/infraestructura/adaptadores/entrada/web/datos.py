"""Lecturas cacheadas para la interfaz. Nada de lógica: solo leer y recordar.

Streamlit vuelve a ejecutar el script entero en **cada interacción**, y
``st.tabs`` dibuja el cuerpo de las siete pestañas en cada pasada. Medido con
``AppTest``: un solo render de Configuración hacía **13 lecturas**, entre ellas
la maestra completa (9.200 clientes = 10 viajes a Supabase ≈ 4,4 s) y el catálogo
de zonas tres veces. Así, marcar una casilla del repertorio costaba volver a
traer toda la maestra.

El cache vive **acá y no en los repositorios**: el dominio y los casos de uso no
tienen por qué saber que existe una pantalla que se repinta. Con TTL corto por si
alguien edita la base por fuera, y con invalidación **explícita** en cada
escritura, porque lo que pide la usuaria es que cambiar la zona de un cliente se
vea al instante, no en cinco minutos.
"""

from collections.abc import Callable
from decimal import Decimal

import streamlit as st

from planeacion.application.puertos.salida.repositorios import ParRepertorio
from planeacion.config.contenedor import Contenedor
from planeacion.domain.modelo import Carro, Cliente, CorreccionUbicacion, Municipio, OverrideZona, Zona

# Cinco minutos: suficiente para que una sesión de trabajo no vuelva a pedir lo
# mismo, y corto para que un cambio hecho por fuera (SQL en Supabase, otra
# pestaña del navegador) aparezca solo sin tener que reiniciar nada.
TTL_SEGUNDOS = 300

# El argumento del contenedor va con guion bajo para que Streamlit NO intente
# hacerle hash: es un objeto con clientes de red adentro. Como hay un solo
# contenedor por proceso (``@st.cache_resource`` en app.py), no hace falta que
# forme parte de la clave.


@st.cache_data(ttl=TTL_SEGUNDOS, show_spinner=False)
def maestra(_contenedor: Contenedor) -> list[Cliente]:
    return _contenedor.clientes.listar()


@st.cache_data(ttl=TTL_SEGUNDOS, show_spinner=False)
def zonas(_contenedor: Contenedor) -> list[Zona]:
    return _contenedor.zonas.listar()


@st.cache_data(ttl=TTL_SEGUNDOS, show_spinner=False)
def municipios(_contenedor: Contenedor) -> list[Municipio]:
    return _contenedor.municipios.listar()


@st.cache_data(ttl=TTL_SEGUNDOS, show_spinner=False)
def flota(_contenedor: Contenedor) -> list[Carro]:
    return _contenedor.carros.listar()


@st.cache_data(ttl=TTL_SEGUNDOS, show_spinner=False)
def matriz_repertorio(_contenedor: Contenedor) -> dict[str, dict[str, set[str]]]:
    return _contenedor.carro_zonas.obtener_matriz()


@st.cache_data(ttl=TTL_SEGUNDOS, show_spinner=False)
def frecuencias(_contenedor: Contenedor) -> dict[ParRepertorio, int]:
    return _contenedor.carro_zonas.frecuencias()


@st.cache_data(ttl=TTL_SEGUNDOS, show_spinner=False)
def correcciones(_contenedor: Contenedor) -> list[CorreccionUbicacion]:
    return _contenedor.correcciones.listar()


@st.cache_data(ttl=TTL_SEGUNDOS, show_spinner=False)
def overrides(_contenedor: Contenedor) -> list[OverrideZona]:
    return _contenedor.overrides.listar()


@st.cache_data(ttl=TTL_SEGUNDOS, show_spinner=False)
def parametros(_contenedor: Contenedor) -> dict[str, Decimal]:
    return _contenedor.parametros.obtener()


# Qué invalidar después de escribir cada cosa. Es explícito y no "borrar todo"
# porque la pantalla más pesada —la matriz del repertorio— escribe en cada clic:
# si cada casilla tirara el cache de la maestra, el arreglo no serviría de nada.
# Al revés, de menos: tocar zonas también invalida la matriz, porque sus filas
# son las zonas.
_LECTURAS = (
    maestra,
    zonas,
    municipios,
    flota,
    matriz_repertorio,
    frecuencias,
    correcciones,
    overrides,
    parametros,
)


def _limpiar(*lecturas: Callable[..., object]) -> None:
    for lectura in lecturas:
        lectura.clear()  # type: ignore[attr-defined]


def invalidar_clientes() -> None:
    """Tras guardar un cliente o aprobar uno nuevo en el Paso 2."""
    _limpiar(maestra)


def invalidar_zonas() -> None:
    """Tras crear, editar, borrar o fusionar una zona."""
    _limpiar(zonas, matriz_repertorio, maestra)


def invalidar_flota() -> None:
    _limpiar(flota, matriz_repertorio)


def invalidar_repertorio() -> None:
    _limpiar(matriz_repertorio, frecuencias)


def invalidar_correcciones() -> None:
    _limpiar(correcciones)


def invalidar_overrides() -> None:
    _limpiar(overrides)


def invalidar_parametros() -> None:
    _limpiar(parametros)


def invalidar_todo() -> None:
    """Para el botón de recargar: tira todo y vuelve a leer de la base."""
    _limpiar(*_LECTURAS)
