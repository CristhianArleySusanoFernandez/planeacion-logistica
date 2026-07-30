"""Pruebas del Balanceador: inicialización, warm-start, reglas duras y mejora de costo."""

from decimal import Decimal

import pytest

from planeacion.domain.errores import SinCarrosParaMunicipio
from planeacion.domain.modelo import Carro, ReglasBalanceo, ResultadoBalanceo, ZonaAgregada
from planeacion.domain.servicios.balanceador import Balanceador
from planeacion.domain.servicios.parseo_zonas import crear_zona

SIN_MEJORA = ReglasBalanceo(max_iteraciones=0)  # deja ver el estado inicial tal cual


def _zona(nombre: str, clientes: int, pesos: str) -> ZonaAgregada:
    return ZonaAgregada(
        zona=crear_zona(nombre),
        facturas=clientes,  # irrelevante para el balanceo; se conserva y ya
        clientes=clientes,
        pesos=Decimal(pesos),
        kilos=Decimal("1"),
    )


def _carros(*numeros: str) -> list[Carro]:
    return [Carro(numero=n) for n in numeros]


def _zonas_de(resultado: ResultadoBalanceo, municipio: str, numero_carro: str) -> set[str]:
    cargas = resultado.cargas_por_municipio[municipio]
    carga = next(c for c in cargas if c.carro.numero == numero_carro)
    return {zona.zona.nombre for zona in carga.zonas}


def test_sin_previa_reparte_round_robin_por_peso_descendente() -> None:
    zonas = [
        _zona("ZONA A", 10, "60"),
        _zona("ZONA B", 10, "50"),
        _zona("ZONA C", 10, "40"),
        _zona("ZONA D", 10, "30"),
        _zona("ZONA E", 10, "20"),
        _zona("ZONA F", 10, "10"),
    ]
    resultado = Balanceador().balancear(zonas, {"OTROS": _carros("1", "2", "3")}, None, SIN_MEJORA)

    # Orden por pesos desc (A..F) alternando: carro1={A,D}, carro2={B,E}, carro3={C,F}.
    assert _zonas_de(resultado, "OTROS", "1") == {"ZONA A", "ZONA D"}
    assert _zonas_de(resultado, "OTROS", "2") == {"ZONA B", "ZONA E"}
    assert _zonas_de(resultado, "OTROS", "3") == {"ZONA C", "ZONA F"}
    assert resultado.desde_historico is False


def test_warm_start_respeta_la_previa_y_acomoda_lo_nuevo() -> None:
    zonas = [
        _zona("ZONA A", 10, "100"),
        _zona("ZONA B", 10, "90"),
        _zona("ZONA NUEVA", 5, "10"),  # no estaba la semana pasada
    ]
    previa = {
        "ZONA A": "2",
        "ZONA B": "1",
        "ZONA DESAPARECIDA": "1",  # hoy no tiene carga: se ignora
        "ZONA NUEVA": "99",  # el carro 99 ya no existe: se trata como nueva
    }
    resultado = Balanceador().balancear(zonas, {"OTROS": _carros("1", "2")}, previa, SIN_MEJORA)

    assert resultado.desde_historico is True
    assert _zonas_de(resultado, "OTROS", "2") == {"ZONA A"}
    # B quedó en el 1 por la previa; la NUEVA va al carro menos cargado (el 1 tiene
    # 90 vs 100 del 2) -> también al 1.
    assert _zonas_de(resultado, "OTROS", "1") == {"ZONA B", "ZONA NUEVA"}


def test_previa_que_no_casa_nada_equivale_a_arrancar_de_cero() -> None:
    zonas = [_zona("ZONA A", 10, "60"), _zona("ZONA B", 10, "50")]
    previa = {"OTRA COSA": "1"}

    resultado = Balanceador().balancear(zonas, {"OTROS": _carros("1", "2")}, previa, SIN_MEJORA)

    assert resultado.desde_historico is False


def test_reglas_duras_fijan_sur_al_primer_carro_y_norte_al_segundo() -> None:
    zonas = [
        _zona("(CHIQUINQUIRA):  CHIQUIN RUTA SUR 1", 80, "800"),
        _zona("(CHIQUINQUIRA):  CHIQUIN RUTA SUR 2", 70, "700"),
        _zona("(CHIQUINQUIRA):  CHIQUIN NORTE 1", 5, "50"),
    ]
    # Con muchas iteraciones: aunque mover el SUR al carro vacío mejoraría el
    # balance, la regla dura lo prohíbe.
    resultado = Balanceador().balancear(
        zonas, {"CHIQUINQUIRA": _carros("820", "985", "986")}, None, ReglasBalanceo()
    )

    assert _zonas_de(resultado, "CHIQUINQUIRA", "820") == {
        "(CHIQUINQUIRA): CHIQUIN RUTA SUR 1",
        "(CHIQUINQUIRA): CHIQUIN RUTA SUR 2",
    }
    assert _zonas_de(resultado, "CHIQUINQUIRA", "985") == {"(CHIQUINQUIRA): CHIQUIN NORTE 1"}
    assert _zonas_de(resultado, "CHIQUINQUIRA", "986") == set()


def test_la_mejora_baja_el_cv_de_un_reparto_muy_desbalanceado() -> None:
    # La previa mete el 80% de la carga en el carro 1 a propósito.
    zonas = [_zona(f"ZONA {i}", 20, "100") for i in range(1, 9)] + [
        _zona("ZONA 9", 4, "20"),
        _zona("ZONA 10", 4, "20"),
    ]
    previa = {f"ZONA {i}": "1" for i in range(1, 9)} | {"ZONA 9": "2", "ZONA 10": "3"}
    carros = {"OTROS": _carros("1", "2", "3")}

    resultado = Balanceador().balancear(zonas, carros, previa, ReglasBalanceo())

    iniciales = resultado.metricas_iniciales["OTROS"]
    finales = resultado.metricas_finales["OTROS"]
    assert iniciales.cv_clientes > 0.8  # el punto de partida era un desastre
    assert finales.cv_clientes < 0.15  # y quedó casi parejo
    assert finales.cv_pesos < 0.15
    assert finales.cv_clientes <= iniciales.cv_clientes


def test_el_balanceo_conserva_los_totales_del_municipio() -> None:
    zonas = [_zona(f"ZONA {i}", 7 * i, str(100 * i)) for i in range(1, 10)]
    carros = {"OTROS": _carros("1", "2", "3")}

    resultado = Balanceador().balancear(zonas, carros, None, ReglasBalanceo())

    cargas = resultado.cargas_por_municipio["OTROS"]
    assert sum(carga.clientes for carga in cargas) == sum(z.clientes for z in zonas)
    assert sum((carga.pesos for carga in cargas), Decimal("0")) == sum((z.pesos for z in zonas), Decimal("0"))
    assert sum(len(carga.zonas) for carga in cargas) == len(zonas)


def test_municipio_con_zonas_pero_sin_carros_lanza_error() -> None:
    zonas = [_zona("(TUNJA):  NIEVES", 10, "100")]

    with pytest.raises(SinCarrosParaMunicipio):
        Balanceador().balancear(zonas, {"OTROS": _carros("1")}, None, SIN_MEJORA)


def test_municipios_se_balancean_por_separado() -> None:
    zonas = [
        _zona("(TUNJA):  NIEVES", 10, "100"),
        _zona("(BARBOSA):  CENTRO", 20, "200"),
    ]
    carros = {"TUNJA": _carros("t1"), "BARBOSA": _carros("b1")}

    resultado = Balanceador().balancear(zonas, carros, None, ReglasBalanceo())

    assert _zonas_de(resultado, "TUNJA", "t1") == {"(TUNJA): NIEVES"}
    assert _zonas_de(resultado, "BARBOSA", "b1") == {"(BARBOSA): CENTRO"}
