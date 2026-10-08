"""Pruebas de la flota como rutas: orden numérico, clave de conductor y agrupación.

La operación de octubre de 2026 tiene 22 rutas y varias por conductor
(`FABIAN 1`/`FABIAN 2`), así que hay dos cosas que antes no existían: ordenar por
número de ruta de verdad —`numero` es texto— y volver a juntar las rutas de una
misma persona.
"""

from decimal import Decimal

from planeacion.domain.modelo import CargaCarro, Carro, Municipio, Zona, ZonaAgregada
from planeacion.domain.modelo.carro import clave_conductor, clave_orden_carro
from planeacion.domain.servicios.agrupacion_por_conductor import agrupar_por_conductor


def _carga(numero: str, conductor: str | None, clientes: int, pesos: str) -> CargaCarro:
    zona = ZonaAgregada(
        zona=Zona(nombre=f"ZONA {numero}", municipio=Municipio(nombre="TUNJA")),
        facturas=clientes,
        clientes=clientes,
        pesos=Decimal(pesos),
        kilos=Decimal("10"),
    )
    carro = Carro(numero=numero, conductor=conductor, conductor_clave=clave_conductor(conductor))
    return CargaCarro(carro=carro, zonas=[zona])


def test_las_rutas_se_ordenan_por_numero_y_no_alfabeticamente() -> None:
    assert sorted(["1", "2", "10", "11", "3"], key=clave_orden_carro) == ["1", "2", "3", "10", "11"]


def test_un_numero_que_no_es_numero_va_al_final_y_no_rompe_el_orden() -> None:
    """Una fila escrita a mano en la UI no puede desordenar toda la tabla."""
    assert sorted(["10", "EXTRA", "2"], key=clave_orden_carro) == ["2", "10", "EXTRA"]


def test_la_clave_del_conductor_quita_el_sufijo_de_ruta() -> None:
    assert clave_conductor("FABIAN 1") == "FABIAN"
    assert clave_conductor("ANGELICA ARIAS 2") == "ANGELICA ARIAS"


def test_un_conductor_sin_sufijo_queda_igual() -> None:
    """Solo se quita un número al final: 'JOSE JIMENEZ' no tiene sufijo que quitar."""
    assert clave_conductor("JOSE JIMENEZ") == "JOSE JIMENEZ"
    assert clave_conductor(None) is None


def test_las_dos_rutas_de_un_conductor_se_suman_en_una_fila() -> None:
    cargas = [
        _carga("1", "FABIAN 1", 31, "2896398"),
        _carga("2", "FABIAN 2", 42, "5960606"),
        _carga("5", "JULIAN COY", 61, "6251923"),
    ]

    agrupadas = agrupar_por_conductor(cargas)

    assert [g.conductor for g in agrupadas] == ["FABIAN", "JULIAN COY"]
    fabian = agrupadas[0]
    assert fabian.rutas == ("1", "2")
    assert fabian.clientes == 73
    assert fabian.pesos == Decimal("8857004")
    assert fabian.facturas == 73


def test_la_agrupacion_funciona_sin_la_columna_poblada() -> None:
    """Base recién migrada: `conductor_clave` vacía, la clave sale del nombre."""
    cargas = [
        CargaCarro(carro=Carro(numero="12", conductor="RAUL 1")),
        CargaCarro(carro=Carro(numero="13", conductor="RAUL 2")),
    ]

    agrupadas = agrupar_por_conductor(cargas)

    assert len(agrupadas) == 1
    assert agrupadas[0].rutas == ("12", "13")


def test_las_rutas_sin_conductor_no_desaparecen_del_resumen() -> None:
    agrupadas = agrupar_por_conductor([CargaCarro(carro=Carro(numero="23"))])

    assert [g.conductor for g in agrupadas] == ["sin conductor"]


def test_el_resumen_se_ordena_por_la_primera_ruta_de_cada_conductor() -> None:
    cargas = [_carga("10", "JUAN", 5, "10"), _carga("2", "ANA 1", 5, "10"), _carga("3", "ANA 2", 5, "10")]

    assert [g.conductor for g in agrupar_por_conductor(cargas)] == ["ANA", "JUAN"]
