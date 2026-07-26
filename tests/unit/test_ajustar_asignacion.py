"""Pruebas del ajuste manual: mover zonas entre carros con validación de reglas."""

from decimal import Decimal

import pytest

from planeacion.domain.errores import MovimientoInvalido
from planeacion.domain.modelo import Carro, ReglasBalanceo, ResultadoBalanceo, ZonaAgregada
from planeacion.domain.servicios.balanceador import AjustadorDeAsignacion, Balanceador
from planeacion.domain.servicios.parseo_zonas import crear_zona

SIN_MEJORA = ReglasBalanceo(max_iteraciones=0)


def _zona(nombre: str, clientes: int, pesos: str) -> ZonaAgregada:
    return ZonaAgregada(
        zona=crear_zona(nombre),
        facturas=clientes,
        clientes=clientes,
        pesos=Decimal(pesos),
        kilos=Decimal("1"),
    )


def _resultado() -> ResultadoBalanceo:
    zonas = [
        _zona("(TUNJA):  NIEVES", 30, "300"),
        _zona("(TUNJA):  PATRIOTAS", 10, "100"),
        _zona("(BARBOSA):  CENTRO", 20, "200"),
        _zona("(CHIQUINQUIRA):  CHIQUIN SUR 1", 15, "150"),
        _zona("(CHIQUINQUIRA):  CHIQUIN NORTE 1", 15, "150"),
    ]
    carros = {
        "TUNJA": [Carro(numero="t1"), Carro(numero="t2")],
        "BARBOSA": [Carro(numero="b1"), Carro(numero="b2")],
        "CHIQUINQUIRA": [Carro(numero="c1"), Carro(numero="c2")],
    }
    return Balanceador().balancear(zonas, carros, None, SIN_MEJORA)


def _carga_de(resultado: ResultadoBalanceo, municipio: str, numero: str) -> set[str]:
    carga = next(c for c in resultado.cargas_por_municipio[municipio] if c.carro.numero == numero)
    return {zona.zona.nombre for zona in carga.zonas}


def test_mover_una_zona_valida_recalcula_las_metricas() -> None:
    resultado = _resultado()
    # Round-robin dejó NIEVES en t1 y PATRIOTAS en t2 -> cv > 0.
    cv_antes = resultado.metricas_finales["TUNJA"].cv_clientes
    assert cv_antes > 0

    AjustadorDeAsignacion().mover(resultado, "(TUNJA): PATRIOTAS", "t1")

    assert _carga_de(resultado, "TUNJA", "t1") == {"(TUNJA): NIEVES", "(TUNJA): PATRIOTAS"}
    assert _carga_de(resultado, "TUNJA", "t2") == set()
    # Todo en un carro y el otro vacío: el desbalance empeoró y quedó registrado.
    assert resultado.metricas_finales["TUNJA"].cv_clientes == pytest.approx(1.0)


def test_mover_a_un_carro_de_otro_municipio_es_invalido() -> None:
    resultado = _resultado()

    with pytest.raises(MovimientoInvalido, match="mismo municipio"):
        AjustadorDeAsignacion().mover(resultado, "(TUNJA): NIEVES", "b1")


def test_mover_una_zona_con_regla_dura_es_invalido() -> None:
    resultado = _resultado()

    with pytest.raises(MovimientoInvalido, match="regla dura"):
        AjustadorDeAsignacion().mover(resultado, "(CHIQUINQUIRA): CHIQUIN SUR 1", "c2")


def test_mover_una_zona_inexistente_es_invalido() -> None:
    resultado = _resultado()

    with pytest.raises(MovimientoInvalido, match="no está en la planeación"):
        AjustadorDeAsignacion().mover(resultado, "(TUNJA): FANTASMA", "t1")


def test_mover_al_mismo_carro_es_invalido() -> None:
    resultado = _resultado()

    with pytest.raises(MovimientoInvalido, match="ya está"):
        AjustadorDeAsignacion().mover(resultado, "(TUNJA): NIEVES", "t1")


def _resultado_con_repertorio() -> ResultadoBalanceo:
    zonas = [
        _zona("(TUNJA):  NIEVES", 30, "300"),
        _zona("(TUNJA):  PATRIOTAS", 10, "100"),
        _zona("RAQUIRA", 20, "200"),  # viajera de OTROS que solo permite un carro de TUNJA
        _zona("VENTAQUEMADA", 5, "50"),
    ]
    carros = {"TUNJA": [Carro(numero="t1"), Carro(numero="t2")], "OTROS": [Carro(numero="o1")]}
    repertorio = {
        "t1": {"(TUNJA): NIEVES", "(TUNJA): PATRIOTAS", "RAQUIRA"},
        "t2": {"(TUNJA): NIEVES"},
        "o1": {"(TUNJA): PATRIOTAS", "VENTAQUEMADA"},
    }
    return Balanceador().balancear(zonas, carros, None, SIN_MEJORA, repertorio)


def test_mover_a_un_carro_que_no_permite_la_zona_es_invalido() -> None:
    resultado = _resultado_con_repertorio()

    with pytest.raises(MovimientoInvalido, match="no tiene permitida la zona"):
        AjustadorDeAsignacion().mover(resultado, "(TUNJA): PATRIOTAS", "t2")


def test_con_repertorio_se_puede_mover_a_un_carro_permitido_de_otro_municipio() -> None:
    resultado = _resultado_con_repertorio()
    assert _carga_de(resultado, "OTROS", "o1") == {"VENTAQUEMADA"}

    AjustadorDeAsignacion().mover(resultado, "(TUNJA): PATRIOTAS", "o1")

    assert _carga_de(resultado, "OTROS", "o1") == {"VENTAQUEMADA", "(TUNJA): PATRIOTAS"}
    # Las métricas de AMBOS municipios quedaron recalculadas.
    assert resultado.metricas_finales["OTROS"].cv_clientes == 0.0  # un solo carro: cv 0
    assert "(TUNJA): PATRIOTAS" not in _carga_de(resultado, "TUNJA", "t1")
