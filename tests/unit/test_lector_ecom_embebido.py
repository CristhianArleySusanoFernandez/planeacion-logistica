"""Pruebas del lector del bloque de ECOM embebido en la hoja PEDIDOS de un .xlsm.

Lo que hay que demostrar no es que sepa leer un ECOM —eso ya lo prueba
``test_lector_ecom``— sino que se ancla en el bloque correcto: a la izquierda del
bloque real hay una tabla de trabajo manual con encabezados homónimos (``Fecha``,
``Kilos`` y dos ``Total`` más) que ganarían el match por estar primero.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import ColumnasEcomFaltantes
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom_embebido import (
    HOJA_PEDIDOS,
    LectorEcomEmbebido,
)

# Columnas A-P del archivo real: la tabla que Rudy trabaja a mano. Q y R quedan
# vacías y en la S arranca el bloque pegado de ECOM.
_BLOQUE_IZQUIERDO: list[object] = [
    "Fecha", "R. Social", "CODIGO", "CLIENTES", "Barrio", "Barrio", "Direccion",
    "Total", "Asesor", "Total", "Kilos", "CUADRANTE", "RUTA", "CLASIFICACIÓN",
    "COORDENADAS", "MUNICIPIO, DEPARTAMENTO", None, None,
]  # fmt: skip

# Encabezados reales del bloque de ECOM, idénticos a los del .xlsx suelto.
_BLOQUE_ECOM: list[object] = [
    "Tipo", "Pedido", "Est", "Fecha", "Hora", "Sku", "nit/ced", "R. Social",
    "Cliente", "Ciudad", "Barrio", "Zona", "Direccion", "Telefono", "Total",
    "Asesor", "No Compra", "Bodega", "Bodega Transf", "Observaciones",
    "Cod.Prod", "Producto", "Cantidad", "Unidad", "Inventario", "Rotacion",
    "Precio U.", "Descuento", "Descuento_2", "Iva", "Total", None, "Tip Pro",
    "Comentario", "Kilos", "Fecha Entrega", "Pedidos Pideky", "Pedidos Pideky",
]  # fmt: skip

_COLUMNA_S = len(_BLOQUE_IZQUIERDO)

# Valores señuelo del bloque izquierdo: si el lector se equivoca de bloque, estos
# aparecen en el resultado y la prueba falla con un número reconocible.
_KILOS_SENUELO = 888888
_TOTAL_SENUELO = 777777.77


def _fila(
    pedido: str, razon_social: str | None, cliente: str | None, fecha: object, total: str, kilos: object
) -> list[object]:
    izquierda: list[object] = [None] * len(_BLOQUE_IZQUIERDO)
    izquierda[0] = datetime(2026, 7, 7)
    izquierda[7] = _TOTAL_SENUELO
    izquierda[9] = _TOTAL_SENUELO
    izquierda[10] = _KILOS_SENUELO

    ecom: list[object] = [None] * len(_BLOQUE_ECOM)
    ecom[0] = "PEDIDO"
    ecom[1] = pedido
    ecom[3] = fecha
    ecom[7] = razon_social
    ecom[8] = cliente
    ecom[9] = "15001 - TUNJA"
    ecom[10] = "SUAREZ"
    ecom[14] = "999999.99" if razon_social is not None else None  # Total de FACTURA
    ecom[21] = "SALCH. VIENA ZENU X 150 G"
    ecom[22] = 4
    ecom[30] = total  # Total de LÍNEA (después de "Iva")
    ecom[34] = kilos  # en gramos
    return izquierda + ecom


def _guardar(
    ruta: Path,
    filas: list[list[object]] | None = None,
    titulo: str = HOJA_PEDIDOS,
    encabezados: list[object] | None = None,
) -> Path:
    libro = openpyxl.Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = titulo
    hoja.append(encabezados if encabezados is not None else _BLOQUE_IZQUIERDO + _BLOQUE_ECOM)
    for fila in filas if filas is not None else _filas_de_prueba():
        hoja.append(fila)
    libro.save(ruta)
    return ruta


def _filas_de_prueba() -> list[list[object]]:
    return [
        _fila(
            "5898188",
            "200002016717-TIENDA LUXOR",
            "200002016717-DALLY",
            datetime(2026, 7, 7),
            "20277.60",
            600,
        ),
        # Segunda línea del mismo pedido: R. Social vacía, como en el archivo real.
        _fila("5898188", None, "200002016717-DALLY", datetime(2026, 7, 7), "8639.40", "229.5"),
        _fila(
            "5894443",
            "000372835-LEIDY VARGAS",
            "000372835-LEIDY MARCELA",
            datetime(2026, 7, 7),
            "10002.30",
            72,
        ),
    ]


def test_lee_las_lineas_del_bloque_pegado_desde_la_s(tmp_path: Path) -> None:
    lineas = LectorEcomEmbebido().leer(_guardar(tmp_path / "planeacion.xlsm"))

    assert len(lineas) == 3
    assert [linea.pedido for linea in lineas] == ["5898188", "5898188", "5894443"]
    assert [linea.codigo_cliente for linea in lineas] == ["200002016717", "200002016717", "000372835"]
    assert all(linea.fecha == date(2026, 7, 7) for linea in lineas)


def test_no_toma_los_totales_ni_los_kilos_de_la_tabla_de_la_izquierda(tmp_path: Path) -> None:
    """El riesgo real del formato: A-P trae otros 'Total' y otro 'Kilos'.

    Los valores de la izquierda son señuelos gigantes a propósito. Si el lector
    mapeara la fila 1 completa en vez de rebanar desde la S, el primer 'Kilos'
    que encontraría sería el de la columna K y los totales saldrían de H/J.
    """
    lineas = LectorEcomEmbebido().leer(_guardar(tmp_path / "planeacion.xlsm"))

    assert sum(linea.total_linea for linea in lineas) == Decimal("38919.30")
    # 600 + 229,5 + 72 gramos, ya convertidos a kilos por el parseo compartido.
    assert sum(linea.kilos for linea in lineas) == Decimal("0.9015")
    assert all(linea.kilos < Decimal(_KILOS_SENUELO) for linea in lineas)


def test_el_bloque_puede_estar_mas_a_la_derecha_de_la_s(tmp_path: Path) -> None:
    """El ancla es el encabezado 'Tipo'/'Pedido', no la letra S fija."""
    relleno: list[object] = [None] * 4
    encabezados = _BLOQUE_IZQUIERDO + relleno + _BLOQUE_ECOM
    filas = [fila[:_COLUMNA_S] + [None] * 4 + fila[_COLUMNA_S:] for fila in _filas_de_prueba()]

    lineas = LectorEcomEmbebido().leer(
        _guardar(tmp_path / "corrido.xlsm", filas=filas, encabezados=encabezados)
    )

    assert len(lineas) == 3
    assert sum(linea.kilos for linea in lineas) == Decimal("0.9015")


def test_sin_hoja_pedidos_el_error_dice_que_hojas_hay(tmp_path: Path) -> None:
    ruta = _guardar(tmp_path / "otro.xlsm", titulo="OTRA COSA")

    with pytest.raises(ColumnasEcomFaltantes, match=r"no tiene hoja PEDIDOS.*OTRA COSA"):
        LectorEcomEmbebido().leer(ruta)


def test_sin_bloque_de_ecom_el_error_lo_explica(tmp_path: Path) -> None:
    """Un .xlsm al que solo le pegaron la tabla de trabajo, sin los pedidos crudos."""
    ruta = _guardar(tmp_path / "vacio.xlsm", filas=[], encabezados=_BLOQUE_IZQUIERDO)

    with pytest.raises(ColumnasEcomFaltantes, match=r"no trae el bloque de ECOM"):
        LectorEcomEmbebido().leer(ruta)
