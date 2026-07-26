"""Lectura de los archivos reales de ECOM: regresión de totales exactos.

Los de junio traen la hoja "Hoja1" y el total de línea como "Total2"; el de
julio llegó con la hoja "Informe" y los dos "Total" con el mismo nombre (el
caso que destapó el mapeo por encabezado). Los totales esperados de junio son
los que producía el lector por posiciones fijas antes del cambio.
"""

from decimal import Decimal
from pathlib import Path

import pytest

_CASOS = [
    ("datos/pedidos24-26Junio.xlsx", 5078, 1341, Decimal("160717282.37"), Decimal("5862.41495")),
    ("datos/pedidos12-14Junio.xlsx", 4169, 1184, Decimal("128155706.00"), Decimal("4326.83938")),
    ("datos/PEDIDOS_9_JULIO.xlsx", 4642, 1269, Decimal("130558850.57"), Decimal("17072.68008")),
]


@pytest.mark.integration
@pytest.mark.parametrize(("ruta", "lineas", "pedidos", "pesos", "kilos"), _CASOS)
def test_lee_el_archivo_real_con_los_totales_exactos(
    ruta: str, lineas: int, pedidos: int, pesos: Decimal, kilos: Decimal
) -> None:
    archivo = Path(ruta)
    if not archivo.exists():
        pytest.skip(f"sin {ruta}")
    from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import LectorEcomExcel

    leidas = LectorEcomExcel().leer(archivo)

    assert len(leidas) == lineas
    assert len({linea.pedido for linea in leidas}) == pedidos
    assert sum(linea.total_linea for linea in leidas) == pesos
    assert sum(linea.kilos for linea in leidas) == kilos
