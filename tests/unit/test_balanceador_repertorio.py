"""Pruebas del Balanceador con repertorio de zonas por carro.

El repertorio (carro → zonas permitidas) restringe TODOS los puntos de
asignación: reparto inicial, warm-start y movimientos/intercambios de la mejora.
Vacío = comportamiento clásico (regresión).
"""

from decimal import Decimal

from planeacion.domain.modelo import Carro, ReglasBalanceo, ResultadoBalanceo, ZonaAgregada
from planeacion.domain.servicios.balanceador import Balanceador
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


def _carros(*numeros: str) -> list[Carro]:
    return [Carro(numero=n) for n in numeros]


def _carro_de(resultado: ResultadoBalanceo, nombre_zona: str) -> str | None:
    for cargas in resultado.cargas_por_municipio.values():
        for carga in cargas:
            if any(zona.zona.nombre == nombre_zona for zona in carga.zonas):
                return carga.carro.numero
    return None


def test_una_zona_exclusiva_nunca_sale_de_su_carro() -> None:
    # El carro 2 quedaría desbalanceadísimo, pero es el único que permite ambas zonas.
    zonas = [_zona("ZONA A", 50, "500"), _zona("ZONA B", 50, "500")]
    repertorio = {"2": {"ZONA A", "ZONA B"}}

    resultado = Balanceador().balancear(
        zonas, {"OTROS": _carros("1", "2", "3")}, None, ReglasBalanceo(), repertorio
    )

    assert _carro_de(resultado, "ZONA A") == "2"
    assert _carro_de(resultado, "ZONA B") == "2"
    assert resultado.metricas_finales["OTROS"].cv_clientes > 1.0  # y quedó desbalanceado, sí


def test_una_zona_compartida_termina_en_el_carro_que_mejora_el_balance() -> None:
    zonas = [_zona("ZONA GRANDE", 80, "800"), _zona("ZONA COMPARTIDA", 20, "200")]
    # GRANDE solo puede ir al 1; COMPARTIDA puede ir al 1 o al 3 → debe caer al 3.
    repertorio = {"1": {"ZONA GRANDE", "ZONA COMPARTIDA"}, "3": {"ZONA COMPARTIDA"}}

    resultado = Balanceador().balancear(
        zonas, {"OTROS": _carros("1", "3")}, None, ReglasBalanceo(), repertorio
    )

    assert _carro_de(resultado, "ZONA GRANDE") == "1"
    assert _carro_de(resultado, "ZONA COMPARTIDA") == "3"


def test_zona_sin_carro_elegible_queda_en_zonas_sin_carro() -> None:
    zonas = [_zona("ZONA HUERFANA", 10, "100"), _zona("ZONA A", 10, "100")]
    repertorio = {"1": {"ZONA A"}}

    resultado = Balanceador().balancear(
        zonas, {"OTROS": _carros("1", "2")}, None, SIN_MEJORA, repertorio
    )

    assert [z.zona.nombre for z in resultado.zonas_sin_carro] == ["ZONA HUERFANA"]
    assert _carro_de(resultado, "ZONA HUERFANA") is None
    assert _carro_de(resultado, "ZONA A") == "1"


def test_repertorio_vacio_es_el_comportamiento_clasico() -> None:
    zonas = [
        _zona(f"ZONA {letra}", 10, str(pesos))
        for letra, pesos in zip("ABCDEF", range(60, 0, -10), strict=True)
    ]
    carros = {"OTROS": _carros("1", "2", "3")}

    con_vacio = Balanceador().balancear(zonas, carros, None, SIN_MEJORA, repertorio={})
    sin_parametro = Balanceador().balancear(zonas, carros, None, SIN_MEJORA)

    # Mismo round-robin por peso descendente y sin zonas afuera.
    for resultado in (con_vacio, sin_parametro):
        assert resultado.zonas_sin_carro == []
        assert resultado.repertorio == {}
    reparto_a = {n: _carro_de(con_vacio, f"ZONA {n}") for n in "ABCDEF"}
    reparto_b = {n: _carro_de(sin_parametro, f"ZONA {n}") for n in "ABCDEF"}
    assert reparto_a == reparto_b == {"A": "1", "B": "2", "C": "3", "D": "1", "E": "2", "F": "3"}


def test_warm_start_reubica_la_zona_cuyo_carro_previo_ya_no_la_permite() -> None:
    zonas = [_zona("ZONA A", 10, "100"), _zona("ZONA B", 10, "90")]
    previa = {"ZONA A": "1", "ZONA B": "1"}  # la semana pasada todo iba en el 1
    repertorio = {"1": {"ZONA A"}, "2": {"ZONA A", "ZONA B"}}  # Rudy le quitó B al 1

    resultado = Balanceador().balancear(
        zonas, {"OTROS": _carros("1", "2")}, previa, SIN_MEJORA, repertorio
    )

    assert resultado.desde_historico is True
    assert _carro_de(resultado, "ZONA A") == "1"  # la previa sigue valiendo donde se puede
    assert _carro_de(resultado, "ZONA B") == "2"  # reubicada al elegible menos cargado


def test_zona_viajera_se_balancea_en_el_pool_de_su_carro_elegible() -> None:
    # RAQUIRA es de OTROS pero solo la permite el carro 2 (pool de CHIQUINQUIRA).
    zonas = [_zona("RAQUIRA", 10, "100"), _zona("ZONA OTROS", 10, "100")]
    carros = {"CHIQUINQUIRA": _carros("1", "2"), "OTROS": _carros("6")}
    repertorio = {"2": {"RAQUIRA"}, "6": {"ZONA OTROS"}}

    resultado = Balanceador().balancear(zonas, carros, None, ReglasBalanceo(), repertorio)

    assert _carro_de(resultado, "RAQUIRA") == "2"
    nombres_chiquinquira = {
        zona.zona.nombre
        for carga in resultado.cargas_por_municipio["CHIQUINQUIRA"]
        for zona in carga.zonas
    }
    assert "RAQUIRA" in nombres_chiquinquira  # viajó al pool de su carro elegible
    assert resultado.zonas_sin_carro == []


def test_la_regla_dura_de_chiquinquira_prevalece_sobre_el_repertorio() -> None:
    zonas = [_zona("(CHIQUINQUIRA):  CHIQUIN RUTA SUR 1", 10, "100")]
    # El repertorio dice que la SUR solo la permite el carro 2, pero la regla
    # dura la fija al primer carro del pool (documentado en el balanceador).
    repertorio = {"2": {"(CHIQUINQUIRA): CHIQUIN RUTA SUR 1"}}

    resultado = Balanceador().balancear(
        zonas, {"CHIQUINQUIRA": _carros("1", "2")}, None, ReglasBalanceo(), repertorio
    )

    assert _carro_de(resultado, "(CHIQUINQUIRA): CHIQUIN RUTA SUR 1") == "1"


def test_la_mejora_iterativa_nunca_viola_el_repertorio() -> None:
    # Carga muy dispareja para provocar muchos movimientos e intercambios.
    zonas = [_zona(f"ZONA {i}", 5 * i, str(100 * i)) for i in range(1, 13)]
    repertorio = {
        "1": {f"ZONA {i}" for i in range(1, 9)},
        "2": {f"ZONA {i}" for i in range(5, 13)},
        "3": {f"ZONA {i}" for i in (1, 12)},
    }

    resultado = Balanceador().balancear(
        zonas, {"OTROS": _carros("1", "2", "3")}, None, ReglasBalanceo(), repertorio
    )

    for carga in resultado.cargas_por_municipio["OTROS"]:
        for zona in carga.zonas:
            assert zona.zona.nombre in repertorio[carga.carro.numero], (
                f"{zona.zona.nombre} quedó en el carro {carga.carro.numero} sin permiso"
            )
    assert resultado.zonas_sin_carro == []
