"""Smoke tests de la UI: la app arranca y los 4 pasos se navegan sin excepciones.

Con credenciales reales muestra el paso 1; sin ellas muestra el error de
configuración y se detiene. La navegación se prueba con datos falsos inyectados
en session_state (sin tocar Supabase ni leer archivos): tanto los botones
"Continuar" como los de la sidebar escriben el paso con ``estado.ir_a``.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from planeacion.application.dto.pivote import PivotePorZonaDTO
from planeacion.application.dto.planeacion import PlaneacionCompleta
from planeacion.config import contenedor as contenedor_mod
from planeacion.config.contenedor import Contenedor
from planeacion.domain.modelo import (
    CargaCarro,
    Carro,
    MetricasDesbalance,
    Municipio,
    ResultadoBalanceo,
    Zona,
    ZonaAgregada,
)
from planeacion.infraestructura.adaptadores.entrada.web import estado

_RUTA_APP = (
    Path(__file__).parents[2]
    / "src"
    / "planeacion"
    / "infraestructura"
    / "adaptadores"
    / "entrada"
    / "web"
    / "app.py"
)


def _pivote_falso() -> PivotePorZonaDTO:
    return PivotePorZonaDTO(
        fecha=date(2026, 7, 8),
        zonas=(),
        total_facturas=4,
        total_clientes=4,
        total_pesos=Decimal("1600.50"),
        total_kilos=Decimal("16.5"),
        no_resueltos=(),  # paso 2 muestra "todos con zona" y el botón Continuar
        facturas_no_resueltas=0,
        pesos_no_resueltos=Decimal("0"),
        kilos_no_resueltos=Decimal("0"),
        pedidos_excluidos_por_fecha=0,
        fechas_excluidas=(),
    )


def _planeacion_falsa() -> PlaneacionCompleta:
    municipio = Municipio(nombre="BARBOSA")
    cargas = [
        CargaCarro(
            carro=Carro(numero="10", conductor="ANA", municipio=municipio),
            zonas=[
                ZonaAgregada(
                    zona=Zona(nombre="(BARBOSA):  UNO", municipio=municipio),
                    facturas=2,
                    clientes=2,
                    pesos=Decimal("1000"),
                    kilos=Decimal("12"),
                )
            ],
        ),
        CargaCarro(carro=Carro(numero="20", municipio=municipio)),
    ]
    metricas = MetricasDesbalance(
        municipio="BARBOSA",
        rango_clientes=2,
        rango_pesos=Decimal("1000"),
        cv_clientes=0.5,
        cv_pesos=0.5,
    )
    resultado = ResultadoBalanceo(
        cargas_por_municipio={"BARBOSA": cargas},
        metricas_iniciales={"BARBOSA": metricas},
        metricas_finales={"BARBOSA": metricas},
        desde_historico=False,
    )
    return PlaneacionCompleta(
        fecha=date(2026, 7, 8),
        dia_semana="miercoles",
        resultado=resultado,
        total_facturas=4,
        total_clientes=4,
        total_pesos=Decimal("1600.50"),
        total_kilos=Decimal("16.5"),
        no_resueltos=(),
        pedidos_excluidos_por_fecha=0,
    )


def _clic(aplicacion: AppTest, clave: str) -> None:
    aplicacion.button(key=clave).click().run()
    assert not aplicacion.exception, aplicacion.exception


def test_la_app_arranca_sin_excepciones() -> None:
    aplicacion = AppTest.from_file(str(_RUTA_APP), default_timeout=60)
    aplicacion.run()
    assert not aplicacion.exception, aplicacion.exception


def test_navegar_los_cuatro_pasos_con_los_botones() -> None:
    aplicacion = AppTest.from_file(str(_RUTA_APP), default_timeout=60)
    aplicacion.session_state[estado.CLAVE_PIVOTE] = _pivote_falso()
    aplicacion.session_state[estado.CLAVE_PLANEACION] = _planeacion_falsa()
    aplicacion.run()
    assert not aplicacion.exception, aplicacion.exception

    _clic(aplicacion, "continuar_paso1")  # paso 1 → paso 2
    assert aplicacion.session_state[estado.CLAVE_PASO] == estado.PASO_CLIENTES

    _clic(aplicacion, "continuar_paso2")  # paso 2 (sin pendientes) → paso 3
    assert aplicacion.session_state[estado.CLAVE_PASO] == estado.PASO_REPARTO

    _clic(aplicacion, "continuar_paso3")  # paso 3 → paso 4
    assert aplicacion.session_state[estado.CLAVE_PASO] == estado.PASO_EXPORTAR

    # Y de vuelta al inicio por el botón de navegación de la sidebar.
    _clic(aplicacion, "nav_0")
    assert aplicacion.session_state[estado.CLAVE_PASO] == estado.PASO_CARGAR


def _contenedor_caido(excepcion: Exception) -> Contenedor:
    """Un contenedor cuyos repositorios revientan apenas se los toca."""

    class _RepoCaido:
        def __getattr__(self, _nombre: str) -> Any:
            def _reventar(*_args: Any, **_kwargs: Any) -> Any:
                raise excepcion

            return _reventar

    caido = cast(Any, _RepoCaido())
    return Contenedor(
        municipios=caido,
        zonas=caido,
        carros=caido,
        carro_zonas=caido,
        clientes=caido,
        correcciones=caido,
        overrides=caido,
        planeaciones=caido,
        parametros=caido,
    )


def _app_con_contenedor(monkeypatch: pytest.MonkeyPatch, contenedor: Contenedor) -> AppTest:
    st.cache_resource.clear()  # si no, la app reusa el contenedor real de otra prueba
    monkeypatch.setattr(contenedor_mod, "crear_contenedor", lambda *_a, **_k: contenedor)
    return AppTest.from_file(str(_RUTA_APP), default_timeout=60)


def test_sin_conexion_la_pagina_muestra_el_mensaje_amigable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supabase pausado: en vez del traceback, las instrucciones para reactivarlo."""
    aplicacion = _app_con_contenedor(monkeypatch, _contenedor_caido(httpx.ConnectError("sin red")))
    aplicacion.session_state[estado.CLAVE_PASO] = estado.PAGINA_CONFIGURACION
    aplicacion.run()

    assert not aplicacion.exception, aplicacion.exception
    assert any("No se pudo conectar con la base de datos" in e.value for e in aplicacion.error)
    assert any("Restore" in e.value for e in aplicacion.error)


def test_sin_conexion_al_cablear_tampoco_revienta(monkeypatch: pytest.MonkeyPatch) -> None:
    """La caída puede ser antes de la página, al crear el cliente de Supabase."""
    st.cache_resource.clear()

    def _reventar(*_args: Any, **_kwargs: Any) -> Contenedor:
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(contenedor_mod, "crear_contenedor", _reventar)
    aplicacion = AppTest.from_file(str(_RUTA_APP), default_timeout=60)
    aplicacion.run()

    assert not aplicacion.exception, aplicacion.exception
    assert any("No se pudo conectar con la base de datos" in e.value for e in aplicacion.error)


def test_un_error_que_no_es_de_conexion_sigue_propagandose(monkeypatch: pytest.MonkeyPatch) -> None:
    """Solo los errores de red muestran «puede estar pausado»; los de datos, no."""
    aplicacion = _app_con_contenedor(monkeypatch, _contenedor_caido(ValueError("dato inválido")))
    aplicacion.session_state[estado.CLAVE_PASO] = estado.PAGINA_CONFIGURACION
    aplicacion.run()

    assert aplicacion.exception, "el error de datos tenía que propagarse como antes"
    assert not any("No se pudo conectar" in e.value for e in aplicacion.error)
