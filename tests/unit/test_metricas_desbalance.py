"""Pruebas de las métricas de desbalance y de la función de costo."""

from decimal import Decimal

import pytest

from planeacion.domain.modelo import (
    UMBRAL_CV_ACEPTABLE,
    UMBRAL_CV_ATENCION,
    CargaCarro,
    Carro,
    NivelDesbalance,
    ReglasBalanceo,
    ZonaAgregada,
    clasificar_cv,
)
from planeacion.domain.servicios.balanceador import calcular_costo, calcular_metricas
from planeacion.domain.servicios.parseo_zonas import crear_zona
from planeacion.infraestructura.adaptadores.entrada.cli.balancear import (
    _TEXTO_SEMAFORO,
    _semaforo,
)
from planeacion.infraestructura.adaptadores.entrada.web.estilos import (
    _COLOR_SEMAFORO,
    color_semaforo,
)


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


def test_clasificar_cv_en_los_bordes_exactos() -> None:
    """Los cortes son cerrados por arriba: 0,10 ya no es ACEPTABLE y 0,20 todavía es ATENCION."""
    assert clasificar_cv(0.0) is NivelDesbalance.ACEPTABLE
    assert clasificar_cv(0.0999) is NivelDesbalance.ACEPTABLE
    assert clasificar_cv(UMBRAL_CV_ACEPTABLE) is NivelDesbalance.ATENCION
    assert clasificar_cv(UMBRAL_CV_ATENCION) is NivelDesbalance.ATENCION
    assert clasificar_cv(0.2001) is NivelDesbalance.CRITICO


def test_el_nivel_del_municipio_lo_marca_su_peor_dimension() -> None:
    # Clientes perfectamente parejos (CV 0) pero pesos muy dispares (CV 0,5).
    metricas = calcular_metricas("OTROS", [_carga("1", 10, "100"), _carga("2", 10, "300")])

    assert metricas.cv_clientes == 0.0
    assert metricas.nivel is NivelDesbalance.CRITICO


def test_los_adaptadores_traducen_el_mismo_nivel_del_dominio() -> None:
    """La CLI y la UI no vuelven a decidir el criterio: solo le ponen nombre y color."""
    for cv in (0.05, UMBRAL_CV_ACEPTABLE, 0.15, UMBRAL_CV_ATENCION, 0.35):
        nivel = clasificar_cv(cv)
        assert _semaforo(cv) == _TEXTO_SEMAFORO[nivel]
        assert color_semaforo(cv) == _COLOR_SEMAFORO[nivel]


def test_el_costo_pondera_con_w_clientes_y_w_pesos() -> None:
    # cv_clientes = 0 (parejos), cv_pesos = 0.5
    cargas = [_carga("1", 10, "100"), _carga("2", 10, "300")]

    solo_clientes = calcular_costo(cargas, ReglasBalanceo(w_clientes=1.0, w_pesos=0.0))
    solo_pesos = calcular_costo(cargas, ReglasBalanceo(w_clientes=0.0, w_pesos=1.0))
    mitad = calcular_costo(cargas, ReglasBalanceo(w_clientes=0.5, w_pesos=0.5))

    assert solo_clientes == pytest.approx(0.0)
    assert solo_pesos == pytest.approx(0.5)
    assert mitad == pytest.approx(0.25)
