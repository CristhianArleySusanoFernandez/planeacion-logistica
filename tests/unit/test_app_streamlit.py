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
from postgrest.exceptions import APIError
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
from planeacion.infraestructura.adaptadores.entrada.web import datos, errores, estado
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import (
    ColumnasEcomFaltantes,
    LectorEcomExcel,
)

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


def _codigos_en_pantalla(aplicacion: AppTest) -> list[str]:
    """Los códigos de error que el panel dejó en sus captions."""
    marca = "Código del error: "
    return [c.value.removeprefix(marca) for c in aplicacion.caption if c.value.startswith(marca)]


def _textos(aplicacion: AppTest) -> str:
    """Todo el texto visible, para buscar un dato puntual sin atarse al elemento."""
    partes = [elemento.value for elemento in aplicacion.markdown]
    partes += [elemento.value for elemento in aplicacion.caption]
    partes += [elemento.value for elemento in aplicacion.error]
    partes += [elemento.value for elemento in aplicacion.warning]
    return "\n".join(str(parte) for parte in partes)


def test_la_base_pausada_muestra_el_panel_con_enlace_y_reintentar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El caso real: Supabase se pausó. En vez del traceback, qué hacer y a dónde ir."""
    datos.invalidar_todo()
    aplicacion = _app_con_contenedor(monkeypatch, _contenedor_caido(httpx.ConnectError("sin red")))
    aplicacion.session_state[estado.CLAVE_PASO] = estado.PAGINA_CONFIGURACION
    aplicacion.run()

    assert not aplicacion.exception, aplicacion.exception
    assert errores.BD_SIN_CONEXION in _codigos_en_pantalla(aplicacion)
    texto = _textos(aplicacion)
    assert "Restore" in texto  # el paso concreto, no una frase genérica
    enlaces = [e for e in aplicacion.get("link_button")]
    assert any(e.proto.url.startswith("https://supabase.com/dashboard/project/") for e in enlaces)
    assert any(boton.label == "🔄 Reintentar" for boton in aplicacion.button)


def test_reintentar_vuelve_a_intentar_sin_recargar_la_pagina(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Es el punto del botón: que la usuaria no tenga que recargar el navegador."""
    datos.invalidar_todo()
    aplicacion = _app_con_contenedor(monkeypatch, _contenedor_caido(httpx.ConnectError("sin red")))
    aplicacion.session_state[estado.CLAVE_PASO] = estado.PAGINA_CONFIGURACION
    aplicacion.run()

    reintentar = next(b for b in aplicacion.button if b.label == "🔄 Reintentar")
    reintentar.click().run()

    # Sigue caída, así que el panel vuelve a salir; lo que importa es que el clic
    # no deja la app en un estado roto.
    assert not aplicacion.exception, aplicacion.exception
    assert errores.BD_SIN_CONEXION in _codigos_en_pantalla(aplicacion)


def test_sin_conexion_al_cablear_tampoco_revienta(monkeypatch: pytest.MonkeyPatch) -> None:
    """La caída puede ser antes de la página, al crear el cliente de Supabase."""
    st.cache_resource.clear()
    datos.invalidar_todo()

    def _reventar(*_args: Any, **_kwargs: Any) -> Contenedor:
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(contenedor_mod, "crear_contenedor", _reventar)
    aplicacion = AppTest.from_file(str(_RUTA_APP), default_timeout=60)
    aplicacion.run()

    assert not aplicacion.exception, aplicacion.exception
    assert errores.BD_SIN_CONEXION in _codigos_en_pantalla(aplicacion)


def test_la_tabla_que_falta_nombra_su_migracion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una migración sin aplicar: el panel dice cuál, para que el aviso sea útil."""
    datos.invalidar_todo()
    sin_tabla = APIError(
        {"code": "42P01", "message": 'relation "public.zonas" does not exist', "hint": "", "details": ""}
    )
    aplicacion = _app_con_contenedor(monkeypatch, _contenedor_caido(sin_tabla))
    aplicacion.session_state[estado.CLAVE_PASO] = estado.PAGINA_CONFIGURACION
    aplicacion.run()

    assert not aplicacion.exception, aplicacion.exception
    assert errores.BD_MIGRACION_FALTANTE in _codigos_en_pantalla(aplicacion)
    texto = _textos(aplicacion)
    assert "001" in texto  # la migración que crea `zonas`
    assert "zonas" in texto


def test_un_archivo_que_no_es_de_ecom_lista_las_columnas_que_trae(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Paso 1 con el reporte equivocado: se dice qué se esperaba y qué llegó."""
    datos.invalidar_todo()
    ruta = tmp_path / "reporte_equivocado.xls"
    ruta.write_bytes(
        b"<html><body><table>"
        b"<tr><td>Cliente</td><td>Ciudad</td><td>Vendedor</td></tr>"
        b"<tr><td>200001</td><td>TUNJA</td><td>ANA</td></tr>"
        b"</table></body></html>"
    )
    aplicacion = _app_con_contenedor(monkeypatch, _contenedor_caido(AssertionError("no se usa")))
    aplicacion.run()

    # El Paso 1 no pega a la base para leer el archivo, así que el contenedor
    # caído no estorba: lo que se prueba es el camino del archivo.
    with pytest.raises(ColumnasEcomFaltantes) as capturada:
        LectorEcomExcel().leer(ruta)
    error = errores.clasificar(capturada.value)

    assert error is not None
    assert error.codigo == errores.ARCHIVO_NO_RECONOCIDO
    assert "Vendedor" in error.que_paso
    assert not error.reintentable


def test_un_error_que_no_se_reconoce_sigue_propagandose(monkeypatch: pytest.MonkeyPatch) -> None:
    """El control: un panel para todo esconderia los bugs, así que no lo hay."""
    datos.invalidar_todo()
    aplicacion = _app_con_contenedor(monkeypatch, _contenedor_caido(ValueError("dato inválido")))
    aplicacion.session_state[estado.CLAVE_PASO] = estado.PAGINA_CONFIGURACION
    aplicacion.run()

    assert aplicacion.exception, "el error desconocido tenía que propagarse"
    assert _codigos_en_pantalla(aplicacion) == []
