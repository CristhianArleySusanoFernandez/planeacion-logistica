"""Pruebas del cotejo entre la propuesta automática y la planeación manual."""

from decimal import Decimal

from planeacion.domain.modelo import AsignacionZona, Carro
from planeacion.domain.servicios.comparador_asignaciones import comparar_asignaciones
from planeacion.domain.servicios.parseo_zonas import crear_zona


def _asignacion(nombre_zona: str, numero_carro: str, clientes: int = 10) -> AsignacionZona:
    return AsignacionZona(
        zona=crear_zona(nombre_zona),
        carro=Carro(numero=numero_carro),
        facturas=clientes,
        clientes=clientes,
        pesos=Decimal("1000"),
        kilos=Decimal("5"),
    )


def test_cuenta_coincidencias_y_diferencias() -> None:
    manual = {"(TUNJA):  NIEVES": "14", "(TUNJA):  PATRIOTAS": "12", "(BARBOSA):  CENTRO": "3"}
    propuesta = [
        _asignacion("(TUNJA):  NIEVES", "14"),
        _asignacion("(TUNJA):  PATRIOTAS", "13"),
        _asignacion("(BARBOSA):  CENTRO", "3"),
    ]

    comparacion = comparar_asignaciones(manual, propuesta)

    assert comparacion.coincidencias == 2
    assert comparacion.comparables == 3
    assert comparacion.porcentaje == 2 / 3
    assert [d.zona for d in comparacion.diferencias] == ["(TUNJA): PATRIOTAS"]


def test_la_diferencia_trae_los_dos_carros_y_el_municipio() -> None:
    """Es la fila del CSV: sin el municipio y los dos carros no se puede analizar
    si una zona difiere siempre por la misma razón."""
    comparacion = comparar_asignaciones(
        {"(BARBOSA):  CENTRO": "3"}, [_asignacion("(BARBOSA):  CENTRO", "5", clientes=26)]
    )

    diferencia = comparacion.diferencias[0]
    assert (diferencia.municipio, diferencia.carro_manual, diferencia.carro_propuesto) == (
        "BARBOSA",
        "3",
        "5",
    )
    assert (diferencia.clientes, diferencia.pesos) == (26, Decimal("1000"))


def test_los_espacios_multiples_no_cuentan_como_zona_distinta() -> None:
    """El mismo nombre aparece con distinta cantidad de espacios entre las hojas
    del Excel; sin normalizar, ninguna zona cruzaría y todo daría 0 %."""
    comparacion = comparar_asignaciones(
        {"(TUNJA):     NIEVES": "14"}, [_asignacion("(TUNJA):  NIEVES", "14")]
    )

    assert comparacion.coincidencias == 1
    assert comparacion.sin_propuesta == ()


def test_las_zonas_que_la_app_no_asigno_van_aparte_y_no_cuentan_como_diferencia() -> None:
    """Una zona del manual que la app no produjo (cliente fuera de la maestra) es
    un hueco de cobertura, no un desacuerdo de reparto: mezclarlas escondería
    cuál de los dos problemas hay que atacar."""
    manual = {"(TUNJA):  NIEVES": "14", "(TUNJA):  DESCONOCIDA": "12"}

    comparacion = comparar_asignaciones(manual, [_asignacion("(TUNJA):  NIEVES", "14")])

    assert comparacion.diferencias == ()
    assert comparacion.sin_propuesta == ("(TUNJA): DESCONOCIDA",)
    assert comparacion.comparables == 1


def test_los_dos_porcentajes_se_separan_cuando_hay_zonas_sin_propuesta() -> None:
    """Principal sobre la intersección (1 de 1); pesimista sobre todo el manual
    (1 de 2), contando lo no cubierto como fallo."""
    manual = {"(TUNJA):  NIEVES": "14", "(TUNJA):  DESCONOCIDA": "12"}

    comparacion = comparar_asignaciones(manual, [_asignacion("(TUNJA):  NIEVES", "14")])

    assert comparacion.porcentaje == 1.0
    assert comparacion.porcentaje_pesimista == 0.5


def test_sin_zonas_comparables_los_porcentajes_son_cero_y_no_revientan() -> None:
    comparacion = comparar_asignaciones({}, [])

    assert (comparacion.porcentaje, comparacion.porcentaje_pesimista) == (0.0, 0.0)


def test_las_zonas_que_la_app_asigno_de_mas_no_afectan_el_conteo() -> None:
    """El denominador siempre es lo que Rudy planeó: si la app propone una zona
    que ese día no estaba en PLANEACION, no hay contra qué compararla."""
    comparacion = comparar_asignaciones(
        {"(TUNJA):  NIEVES": "14"},
        [_asignacion("(TUNJA):  NIEVES", "14"), _asignacion("(TUNJA):  EXTRA", "12")],
    )

    assert (comparacion.zonas_manuales, comparacion.comparables, comparacion.coincidencias) == (1, 1, 1)
