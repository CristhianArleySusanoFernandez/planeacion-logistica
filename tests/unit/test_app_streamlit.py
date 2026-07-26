"""Smoke tests de la UI: la app arranca y los 4 pasos se navegan sin excepciones.

Con credenciales reales muestra el paso 1; sin ellas muestra el error de
configuración y se detiene. La navegación se prueba con datos falsos inyectados
en session_state (sin tocar Supabase ni leer archivos): tanto los botones
"Continuar" como los de la sidebar escriben el paso con ``estado.ir_a``.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

from streamlit.testing.v1 import AppTest

from planeacion.application.dto.pivote import PivotePorZonaDTO
from planeacion.application.dto.planeacion import PlaneacionCompleta
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
