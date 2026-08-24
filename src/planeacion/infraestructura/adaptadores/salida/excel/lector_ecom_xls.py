"""Traductor del .xls binario viejo de Excel a un libro de openpyxl en memoria.

Algunos días el ECOM se descarga (o se guarda desde Excel) como .xls, el formato
BIFF anterior a 2007, que openpyxl no sabe abrir. En vez de duplicar el mapeo de
columnas y el parseo de celdas para ese formato, aquí solo se copian los valores
a un ``Workbook`` normal y se lo entrega a ``leer_libro_ecom``: el lector de
siempre no se entera de por dónde entró el archivo.

Se usa ``xlrd`` y no LibreOffice: convertir con ``soffice --convert-to xlsx``
funcionaría en una máquina con LibreOffice instalado, pero el despliegue es
Streamlit Community Cloud, donde no está y meterlo por ``packages.txt`` son
cientos de megas de paquetes apt en cada build. ``xlrd`` es Python puro, sin
dependencias, y desde la 2.0 lee exclusivamente .xls (el soporte de .xlsx se
quitó por seguridad), que es justo lo que hace falta acá.
"""

from pathlib import Path

import xlrd
from openpyxl.workbook import Workbook
from xlrd.book import Book
from xlrd.sheet import Sheet
from xlrd.xldate import XLDateError, xldate_as_datetime

from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import FormatoEcomInvalido

_MENSAJE_ILEGIBLE = (
    "No pudimos leer este archivo .xls. Probá abrirlo en Excel y guardarlo "
    "como .xlsx (Archivo → Guardar como → Libro de Excel), y subilo de nuevo."
)


def abrir_xls_como_libro(ruta: Path) -> Workbook:
    """Abre un .xls y devuelve sus hojas copiadas a un libro de openpyxl."""
    try:
        original = xlrd.open_workbook(str(ruta), on_demand=False)
    except Exception as error:  # xlrd tira XLRDError, CompDocError y otras propias
        raise FormatoEcomInvalido(f"{_MENSAJE_ILEGIBLE} (detalle: {error})") from error

    try:
        libro = Workbook()
        vacia = libro.active  # openpyxl crea una hoja por defecto que acá estorba
        if vacia is not None:
            libro.remove(vacia)
        for hoja_original in original.sheets():
            _copiar_hoja(original, hoja_original, libro)
        return libro
    finally:
        original.release_resources()


def _copiar_hoja(original: Book, hoja_original: Sheet, destino: Workbook) -> None:
    hoja = destino.create_sheet(title=hoja_original.name[:31])
    for numero_fila in range(hoja_original.nrows):
        hoja.append(
            [
                _valor(
                    original,
                    hoja_original.cell_type(numero_fila, columna),
                    hoja_original.cell_value(numero_fila, columna),
                )
                for columna in range(hoja_original.ncols)
            ]  # fmt: skip
        )


def _valor(original: Book, tipo: int, valor: object) -> object:
    """Celda de xlrd → el valor que openpyxl habría entregado.

    Solo las fechas necesitan traducción real: xlrd las deja como el número
    serial de Excel y marca el tipo aparte, mientras que openpyxl ya devuelve
    ``datetime``. Sin esto, la columna Fecha llegaría como '46190' — el mismo
    síntoma que el lector ya trata como fecha dañada, y todos los pedidos
    quedarían sin día.
    """
    if tipo == xlrd.XL_CELL_DATE:
        try:
            return xldate_as_datetime(float(str(valor)), original.datemode)
        except (XLDateError, ValueError):
            return None
    if tipo in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
        return None
    return valor
