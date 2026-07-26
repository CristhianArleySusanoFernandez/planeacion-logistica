"""Pruebas de la siembra del repertorio: lectura de la hoja PLANEACION y cruce con la base."""

from pathlib import Path

import openpyxl

from planeacion.infraestructura.adaptadores.entrada.cli.sembrar_repertorio import cruzar_pares
from planeacion.infraestructura.adaptadores.salida.excel.lector_referencia import (
    LectorReferenciaExcel,
)


def _libro_con_planeacion(ruta: Path) -> None:
    libro = openpyxl.Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = "PLANEACION"
    hoja.append(["PLANEACION DEL DIA"])  # fila 1: título
    hoja.append([None, None, 1247, 143746644.81])  # fila 2: Promedio Vh
    hoja.append([None, "Ventas Totales", 1247])  # fila 3
    hoja.append(["CARROS", "CUADRANTE", "FACTURAS", "PESOS"])  # fila 4: encabezados
    hoja.append([1, "(CHIQUINQUIRA):   CHIQUIN RUTA  SUR 1", 40, 100.0])
    hoja.append([16, "(TUNJA):  ARCABUCO-MOTAVITA", 30, 90.0])
    hoja.append(["#N/D", "#N/D", 0, 0])  # cliente sin zona: no es un par real
    hoja.append([None, "(en blanco)", 0, 0])  # cierre del pivote viejo
    hoja.append([None, "Total general", 1247, 143746644.81])
    libro.save(ruta)


def test_leer_asignaciones_planeacion_filtra_lo_que_no_es_un_par(tmp_path: Path) -> None:
    ruta = tmp_path / "referencia.xlsx"
    _libro_con_planeacion(ruta)

    with LectorReferenciaExcel(ruta) as lector:
        pares = [(fila.carro, fila.zona) for fila in lector.leer_asignaciones_planeacion()]

    assert pares == [
        ("1", "(CHIQUINQUIRA):   CHIQUIN RUTA  SUR 1"),
        ("16", "(TUNJA):  ARCABUCO-MOTAVITA"),
    ]


def test_cruzar_pares_separa_carros_y_zonas_desconocidos() -> None:
    pares = {
        ("1", "(TUNJA): NIEVES"),
        ("18", "RAQUIRA"),
        ("99", "(TUNJA): NIEVES"),  # carro que no está en la base
        ("1", "ZONA FANTASMA"),  # zona que no casa con zonas.nombre
    }

    validos, carros_desconocidos, zonas_desconocidas = cruzar_pares(
        pares, numeros_carros={"1", "18"}, nombres_zonas={"(TUNJA): NIEVES", "RAQUIRA"}
    )

    assert validos == {("1", "(TUNJA): NIEVES"), ("18", "RAQUIRA")}
    assert carros_desconocidos == {"99"}
    assert zonas_desconocidas == {"ZONA FANTASMA"}
