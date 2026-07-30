"""Pruebas del armado de la flota desde el bloque 2 de la hoja BASE (rutas 1..18)."""

from decimal import Decimal
from pathlib import Path

import openpyxl

from planeacion.infraestructura.adaptadores.entrada.cli.sembrar import (
    _construir_carros,
    _municipio_de_ciudad,
)
from planeacion.infraestructura.adaptadores.salida.excel.lector_referencia import (
    FilaRutaBase,
    LectorReferenciaExcel,
)


def _fila(numero: str, facturas: int, ciudad: str | None = "TUNJA") -> FilaRutaBase:
    return FilaRutaBase(numero=numero, facturas=facturas, conductor="ALGUIEN", auxiliar=None, ciudad=ciudad)


def test_municipio_se_deduce_de_la_ciudad() -> None:
    assert _municipio_de_ciudad("CHIQUINQUIRA").nombre == "CHIQUINQUIRA"
    assert _municipio_de_ciudad("BARBOSA").nombre == "BARBOSA"
    assert _municipio_de_ciudad("TUNJA").nombre == "TUNJA"
    # Las cabeceras que no son municipio propio caen en OTROS.
    assert _municipio_de_ciudad("MUZO").nombre == "OTROS"
    assert _municipio_de_ciudad("VILLA DELEYVA").nombre == "OTROS"
    assert _municipio_de_ciudad(None).nombre == "OTROS"


def test_la_ruta_16_es_el_carro_externo() -> None:
    carros = _construir_carros([_fila("16", 53)])
    assert carros[0].es_externo
    assert carros[0].costo_diario == Decimal("160000")
    assert carros[0].activo


def test_solo_las_rutas_con_facturas_quedan_activas() -> None:
    carros = _construir_carros([_fila("1", 81), _fila("18", 0)])
    assert [(c.numero, c.activo) for c in carros] == [("1", True), ("18", False)]


def test_las_rutas_mayores_a_18_sin_facturas_no_se_siembran() -> None:
    carros = _construir_carros([_fila("19", 0), _fila("20", 5)])
    assert [c.numero for c in carros] == ["20"]


def test_la_placa_solo_se_copia_en_las_rutas_con_cruce_seguro() -> None:
    carros = _construir_carros([_fila("1", 81), _fila("3", 66)])
    assert carros[0].placa == "SZN374"  # cruce confirmado con el vehículo 820
    assert carros[1].placa is None  # cruce dudoso: sin placa a propósito


def test_leer_rutas_lee_solo_el_bloque_2(tmp_path: Path) -> None:
    libro = openpyxl.Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = "BASE"
    # Bloque 1: vehículos físicos (no debe salir de leer_rutas).
    hoja.append(["Codigo", "CONDUCTOR ", "Placa", "AUX ENTREGA", "ZONA"])
    hoja.append(["108", "ESTEBAN ROMERO", "LTL380", "JULIAN ROMERO", "RUTA MUZO"])
    hoja.append([])
    # Bloque 2: las rutas de reparto.
    hoja.append(["Ruta", "Facturas", "Clientes", "Pesos", "Kilos", "CONDUCTOR", "AUX", "CIUDAD"])
    hoja.append([1, 81, 70, 6724920.37, 207.06, "FABIAN ", None, "CHIQUINQUIRA"])
    hoja.append([18, 0, 0, 0, 0, None, None, None])
    hoja.append(["Total", 81, 70, 0, 0, None, None, None])  # cierre: corta la lectura
    ruta = tmp_path / "referencia.xlsx"
    libro.save(ruta)

    with LectorReferenciaExcel(ruta) as lector:
        rutas = list(lector.leer_rutas())

    assert [(r.numero, r.facturas, r.conductor, r.ciudad) for r in rutas] == [
        ("1", 81, "FABIAN", "CHIQUINQUIRA"),
        ("18", 0, None, None),
    ]
