"""Traductor del ECOM que llega como HTML con extensión .xls.

Lo que descarga la empresa del portal de ECOM **no es un .xls**: es una tabla
HTML con el nombre cambiado (el export de "Excel.Sheet" de toda la vida, que
arranca con ``<html xmlns:o="urn:schemas-microsoft-com:office:office">``). Excel
lo abre sin chistar, así que nadie se enteró, pero ni openpyxl ni xlrd lo pueden
leer: xlrd falla con "Expected BOF record; found b'\\t\\t\\t\\t<htm'".

Igual que el traductor de .xls binario, esto NO duplica el mapeo de columnas:
devuelve las filas y el mapeo de siempre hace el resto. Las celdas llegan como
texto, que es lo que el lector ya recibía del bloque pegado en los .xlsm (fechas
en ISO, totales y kilos como string).

**No construye un libro de openpyxl.** Lo hacía, y armar ese libro intermedio
para que después lo recorriéramos de vuelta costaba 1,5 de los 3,7 s que tardaba
leer el ECOM del 7 de octubre: más que el parseo del HTML mismo.

Sin dependencias nuevas: ``html.parser`` es de la biblioteca estándar. Meter
pandas o lxml para esto serían decenas de megas en cada build de Streamlit
Community Cloud a cambio de nada.
"""

from html.parser import HTMLParser
from pathlib import Path

from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import FormatoEcomInvalido

# Alcanza con el arranque del archivo: el export pone el <html> en los primeros
# bytes. Se mira un kilobyte por si viene con sangría o un BOM delante.
_BYTES_A_OLFATEAR = 1024
_MARCAS_DE_HTML = (b"<html", b"<table", b"<!doctype html")

# El archivo DECLARA charset=us-ascii y es mentira: trae 0xD1 (Ñ) y 0xA0. Se
# prueban las dos tablas de un byte habituales antes de rendirse a reemplazar
# caracteres, porque un nombre de cliente mal decodificado es un cliente que no
# casa contra la maestra.
_CODIFICACIONES = ("cp1252", "latin-1")

_CELDAS = ("td", "th")
_MENSAJE_SIN_TABLA = (
    "Este archivo parece una página HTML, no una tabla de pedidos: no encontré "
    "ninguna fila. Verificá que sea el informe de pedidos descargado de ECOM."
)


def parece_html(ruta: Path) -> bool:
    """¿Es HTML disfrazado? Se decide por el contenido, no por la extensión.

    La extensión ya mintió una vez: todos estos archivos se llaman .xls.
    """
    with ruta.open("rb") as archivo:
        arranque = archivo.read(_BYTES_A_OLFATEAR).lower()
    return any(marca in arranque for marca in _MARCAS_DE_HTML)


def _decodificar(crudo: bytes) -> str:
    for codificacion in _CODIFICACIONES:
        try:
            return crudo.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return crudo.decode("utf-8", errors="replace")


class _LectorDeTablas(HTMLParser):
    """Junta las filas de cada ``<table>`` del documento como listas de texto.

    El texto de una celda se acumula entre su apertura y su cierre, así que los
    ``<font>``/``<span>`` que Excel mete adentro no parten el valor en pedazos.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tablas: list[list[list[str | None]]] = []
        self._fila: list[str | None] | None = None
        self._celda: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.tablas.append([])
        elif tag == "tr" and self.tablas:
            self._fila = []
        elif tag in _CELDAS and self._fila is not None:
            self._celda = []
        elif tag == "br" and self._celda is not None:
            self._celda.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _CELDAS and self._celda is not None and self._fila is not None:
            texto = "".join(self._celda).strip()
            self._fila.append(texto or None)
            self._celda = None
        elif tag == "tr" and self._fila is not None:
            if self.tablas:
                self.tablas[-1].append(self._fila)
            self._fila = None
        elif tag == "table":
            # Una celda o fila sin cerrar al terminar la tabla no arrastra basura
            # a la siguiente: el HTML de Excel es prolijo, pero esto no cuesta.
            self._celda = None
            self._fila = None

    def handle_data(self, data: str) -> None:
        if self._celda is not None:
            self._celda.append(data)


def filas_del_html(ruta: Path) -> list[list[str | None]]:
    """HTML (con nombre .xls) → sus filas, la primera el encabezado.

    De haber varias tablas se queda con la que más filas tiene: los exports
    suelen traer tablas de maqueta alrededor de los datos, y la de datos es, por
    lejos, la más larga.
    """
    lector = _LectorDeTablas()
    lector.feed(_decodificar(ruta.read_bytes()))
    lector.close()

    filas = max(lector.tablas, key=len, default=[])
    if not filas:
        raise FormatoEcomInvalido(f"{ruta.name}: {_MENSAJE_SIN_TABLA}")
    return filas
