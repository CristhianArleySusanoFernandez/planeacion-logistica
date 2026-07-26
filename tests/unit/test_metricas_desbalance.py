"""Pruebas de las métricas de desbalance y de la función de costo."""

from decimal import Decimal

import pytest

from planeacion.domain.modelo import CargaCarro, Carro, ReglasBalanceo, ZonaAgregada
from planeacion.domain.servicios.balanceador import calcular_costo, calcular_metricas
from planeacion.domain.servicios.parseo_zonas import crear_zona


def _carga(numero: str, clientes: int, pesos: str) -> CargaCarro:
    carga = CargaCarro(carro=Carro(numero=numero))
    carga.agregar(
        ZonaAgregada(
            zona=crear_zona(f"ZONA {numero}"),
            facturas=clientes,
            clientes=clientes,
            pesos=Decimal(pesos),
            kilos=Decimal("1"),
        )
    )
    return carga


def test_cv_y_rango_calculados_a_mano() -> None:
    # clientes [10, 20, 30]: media 20, desv. poblacional sqrt(200/3) -> cv 0.40825
    cargas = [_carga("1", 10, "10"), _carga("2", 20, "20"), _carga("3", 30, "30")]

    metricas = calcular_metricas("OTROS", cargas)

    assert metricas.municipio == "OTROS"
    assert metricas.rango_clientes == 20
    assert metricas.rango_pesos == Decimal("20")
    assert metricas.cv_clientes == pytest.approx(0.408248, abs=1e-5)
    assert metricas.cv_pesos == pytest.approx(0.408248, abs=1e-5)


def test_cargas_identicas_dan_cv_cero() -> None:
    cargas = [_carga("1", 15, "100"), _carga("2", 15, "100")]

    metricas = calcular_metricas("OTROS", cargas)

    assert metricas.cv_clientes == 0.0
    assert metricas.cv_pesos == 0.0
    assert metricas.rango_clientes == 0


def test_media_cero_no_divide_por_cero() -> None:
    cargas = [CargaCarro(carro=Carro(numero="1")), CargaCarro(carro=Carro(numero="2"))]

    metricas = calcular_metricas("OTROS", cargas)

    assert metricas.cv_clientes == 0.0
    assert metricas.cv_pesos == 0.0


def test_es_aceptable_compara_contra_el_peor_cv() -> None:
    cargas = [_carga("1", 10, "100"), _carga("2", 10, "300")]  # clientes parejos, pesos no
    metricas = calcular_metricas("OTROS", cargas)

    assert metricas.cv_clientes == 0.0
    assert metricas.cv_pesos == pytest.approx(0.5)
    assert metricas.es_aceptable(0.5)
    assert not metricas.es_aceptable(0.2)


def test_el_costo_pondera_con_w_clientes_y_w_pesos() -> None:
    # cv_clientes = 0 (parejos), cv_pesos = 0.5
    cargas = [_carga("1", 10, "100"), _carga("2", 10, "300")]

    solo_clientes = calcular_costo(cargas, ReglasBalanceo(w_clientes=1.0, w_pesos=0.0))
    solo_pesos = calcular_costo(cargas, ReglasBalanceo(w_clientes=0.0, w_pesos=1.0))
    mitad = calcular_costo(cargas, ReglasBalanceo(w_clientes=0.5, w_pesos=0.5))

    assert solo_clientes == pytest.approx(0.0)
    assert solo_pesos == pytest.approx(0.5)
    assert mitad == pytest.approx(0.25)
