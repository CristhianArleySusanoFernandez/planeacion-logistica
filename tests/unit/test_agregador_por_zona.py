"""Pruebas del AgregadorPorZona: facturas = pedidos distintos, orden y no resueltos."""

from datetime import date
from decimal import Decimal

from planeacion.domain.modelo import LineaPedido, MotivoNoResuelto
from planeacion.domain.servicios.agregador_por_zona import AgregadorPorZona
from planeacion.domain.servicios.parseo_zonas import crear_zona
from planeacion.domain.servicios.resolutor_zona import ResolutorDeZona

ZONA_TUNJA = crear_zona("(TUNJA):  NIEVES")
ZONA_BARBOSA = crear_zona("(BARBOSA):  BARBOSA-PUENTE")
FECHA = date(2026, 6, 24)


def _linea(
    pedido: str,
    codigo: str,
    pesos: str = "100",
    kilos: str = "1",
    nombre: str | None = None,
) -> LineaPedido:
    return LineaPedido(
        pedido=pedido,
        codigo_cliente=codigo,
        fecha=FECHA,
        total_linea=Decimal(pesos),
        kilos=Decimal(kilos),
        nombre_cliente=nombre,
        ciudad="15001 - TUNJA",
        barrio="CENTRO",
    )


def _resolutor() -> ResolutorDeZona:
    return ResolutorDeZona(
        zonas_maestra={"c1": ZONA_TUNJA, "c2": ZONA_TUNJA, "c3": ZONA_BARBOSA, "c5": None},
        zonas_override={},
    )


def test_un_pedido_de_tres_lineas_es_una_sola_factura() -> None:
    lineas = [
        _linea("100", "c1", pesos="10.50", kilos="0.5"),
        _linea("100", "c1", pesos="20.25", kilos="1.5"),
        _linea("100", "c1", pesos="30.25", kilos="2"),
    ]

    resultado = AgregadorPorZona().agregar(lineas, _resolutor())

    assert len(resultado.zonas) == 1
    zona = resultado.zonas[0]
    assert zona.facturas == 1  # no 3: las líneas no son facturas
    assert zona.clientes == 1
    assert zona.pesos == Decimal("61.00")
    assert zona.kilos == Decimal("4.0")


def test_agrupa_por_zona_y_ordena_por_municipio_y_nombre() -> None:
    lineas = [
        _linea("100", "c1"),
        _linea("101", "c2"),
        _linea("102", "c3"),  # BARBOSA debe salir antes que TUNJA
    ]

    resultado = AgregadorPorZona().agregar(lineas, _resolutor())

    assert [(z.zona.municipio.nombre, z.facturas, z.clientes) for z in resultado.zonas] == [
        ("BARBOSA", 1, 1),
        ("TUNJA", 2, 2),
    ]


def test_no_resueltos_se_reportan_con_motivo_y_entran_al_total() -> None:
    lineas = [
        _linea("100", "c1", pesos="100", kilos="1"),
        _linea("200", "c4", pesos="40", kilos="0.4", nombre="TIENDA NUEVA"),  # no está en maestra
        _linea("201", "c5", pesos="60", kilos="0.6"),  # en maestra pero sin RUTA
    ]

    resultado = AgregadorPorZona().agregar(lineas, _resolutor())

    assert resultado.total_facturas == 3
    assert resultado.total_clientes == 3
    assert resultado.total_pesos == Decimal("200")
    assert resultado.total_kilos == Decimal("2.0")

    assert resultado.facturas_no_resueltas == 2
    assert resultado.pesos_no_resueltos == Decimal("100")
    assert resultado.kilos_no_resueltos == Decimal("1.0")

    por_codigo = {c.codigo: c for c in resultado.no_resueltos}
    assert por_codigo["c4"].motivo == MotivoNoResuelto.NO_ESTA_EN_MAESTRA
    assert por_codigo["c4"].nombre == "TIENDA NUEVA"
    assert por_codigo["c5"].motivo == MotivoNoResuelto.EN_MAESTRA_SIN_ZONA


def test_un_cliente_no_resuelto_aparece_una_sola_vez_aunque_tenga_varias_lineas() -> None:
    lineas = [
        _linea("200", "c4"),
        _linea("200", "c4"),
        _linea("201", "c4"),
    ]

    resultado = AgregadorPorZona().agregar(lineas, _resolutor())

    assert len(resultado.no_resueltos) == 1
    assert resultado.facturas_no_resueltas == 2
