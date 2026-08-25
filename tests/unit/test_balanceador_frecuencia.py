"""Pruebas del desempate por costumbre: la frecuencia histórica del par (carro, zona).

La frecuencia entra como un tercer término de la función de costo, con peso bajo:
rompe empates y sesga decisiones marginales, pero el balance sigue mandando.
"""

from decimal import Decimal

from planeacion.domain.modelo import Carro, ReglasBalanceo, ResultadoBalanceo, ZonaAgregada
from planeacion.domain.modelo.balanceo import penalizaciones_por_frecuencia
from planeacion.domain.servicios.balanceador import Balanceador
from planeacion.domain.servicios.parseo_zonas import crear_zona


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


def test_la_penalizacion_es_cero_para_el_dominante_y_crece_para_el_minoritario() -> None:
    repertorio = {"3": {"ZONA A"}, "5": {"ZONA A"}}
    frecuencias = {("3", "ZONA A"): 8, ("5", "ZONA A"): 1}

    penalizaciones = penalizaciones_por_frecuencia(repertorio, frecuencias)

    assert penalizaciones[("3", "ZONA A")] == 0.0
    assert penalizaciones[("5", "ZONA A")] == 1 - 1 / 8


def test_la_frecuencia_cero_es_neutra_y_no_peor_que_la_frecuencia_uno() -> None:
    # El par del carro 5 se configuró a mano y nunca se observó: no hay evidencia
    # en contra, así que no paga nada. El del 4 sí se vio, pero una sola vez.
    repertorio = {"3": {"ZONA A"}, "4": {"ZONA A"}, "5": {"ZONA A"}}
    frecuencias = {("3", "ZONA A"): 8, ("4", "ZONA A"): 1}

    penalizaciones = penalizaciones_por_frecuencia(repertorio, frecuencias)

    assert penalizaciones.get(("5", "ZONA A"), 0.0) == 0.0
    assert penalizaciones[("4", "ZONA A")] > penalizaciones.get(("5", "ZONA A"), 0.0)


def test_sin_evidencia_de_ninguna_opcion_no_hay_preferencia() -> None:
    repertorio = {"3": {"ZONA A"}, "5": {"ZONA A"}}

    assert penalizaciones_por_frecuencia(repertorio, {("3", "OTRA ZONA"): 9}) == {}


def test_a_igual_balance_gana_el_carro_que_historicamente_atiende_la_zona() -> None:
    # Los dos carros arrancan iguales y la zona viajera cabe en cualquiera: el
    # balance no distingue, así que decide la costumbre.
    zonas = [
        _zona("ZONA DEL 1", 30, "300"),
        _zona("ZONA DEL 2", 30, "300"),
        _zona("ZONA COMPARTIDA", 10, "100"),
    ]
    repertorio = {
        "1": {"ZONA DEL 1", "ZONA COMPARTIDA"},
        "2": {"ZONA DEL 2", "ZONA COMPARTIDA"},
    }
    carros = {"OTROS": _carros("1", "2")}
    frecuencias = {("2", "ZONA COMPARTIDA"): 8, ("1", "ZONA COMPARTIDA"): 1}

    sin_frecuencia = Balanceador().balancear(
        zonas, carros, None, ReglasBalanceo(w_frecuencia=0.0), repertorio, frecuencias
    )
    con_frecuencia = Balanceador().balancear(zonas, carros, None, ReglasBalanceo(), repertorio, frecuencias)

    assert _carro_de(sin_frecuencia, "ZONA COMPARTIDA") == "1"  # el menos cargado, por orden
    assert _carro_de(con_frecuencia, "ZONA COMPARTIDA") == "2"


def test_la_costumbre_no_atropella_al_balance() -> None:
    # Respetar la costumbre dejaría al carro 1 con TODO: gana el balance.
    zonas = [_zona("ZONA GRANDE", 90, "900"), _zona("ZONA COMPARTIDA", 80, "800")]
    repertorio = {"1": {"ZONA GRANDE", "ZONA COMPARTIDA"}, "2": {"ZONA COMPARTIDA"}}
    frecuencias = {("1", "ZONA COMPARTIDA"): 9, ("2", "ZONA COMPARTIDA"): 1}

    resultado = Balanceador().balancear(
        zonas, {"OTROS": _carros("1", "2")}, None, ReglasBalanceo(), repertorio, frecuencias
    )

    assert _carro_de(resultado, "ZONA COMPARTIDA") == "2"


def test_sin_frecuencias_el_reparto_es_identico_al_de_antes() -> None:
    zonas = [
        _zona("ZONA DEL 1", 30, "300"),
        _zona("ZONA DEL 2", 30, "300"),
        _zona("ZONA COMPARTIDA", 10, "100"),
    ]
    repertorio = {
        "1": {"ZONA DEL 1", "ZONA COMPARTIDA"},
        "2": {"ZONA DEL 2", "ZONA COMPARTIDA"},
    }
    carros = {"OTROS": _carros("1", "2")}

    sin_parametro = Balanceador().balancear(zonas, carros, None, ReglasBalanceo(), repertorio)
    con_peso_cero = Balanceador().balancear(
        zonas, carros, None, ReglasBalanceo(w_frecuencia=0.0), repertorio, {("2", "ZONA COMPARTIDA"): 8}
    )

    assert _carro_de(sin_parametro, "ZONA COMPARTIDA") == _carro_de(con_peso_cero, "ZONA COMPARTIDA")
