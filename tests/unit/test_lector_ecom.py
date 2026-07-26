"""Pruebas del lector del ECOM crudo: conversiones robustas, extracción del código
y tolerancia a variaciones del export (hoja renombrada, columnas movidas, etc.)."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import (
    ColumnasEcomFaltantes,
    FormatoEcomInvalido,
    LectorEcomExcel,
    convertir_decimal,
    convertir_fecha,
    extraer_codigo_cliente,
)


class TestConvertirDecimal:
    def test_texto_con_decimales(self) -> None:
        assert convertir_decimal("1234.56") == Decimal("1234.56")

    def test_texto_con_separador_de_miles(self) -> None:
        assert convertir_decimal("1,234,567.89") == Decimal("1234567.89")

    def test_numero_ya_numerico(self) -> None:
        assert convertir_decimal(150) == Decimal("150")

    def test_vacio_vale_cero(self) -> None:
        assert convertir_decimal(None) == Decimal("0")
        assert convertir_decimal("   ") == Decimal("0")

    def test_basura_lanza_error_con_contexto(self) -> None:
        with pytest.raises(FormatoEcomInvalido, match=r"fila 7"):
            convertir_decimal("N/A", "(fila 7, col AE)")


class TestExtraerCodigoCliente:
    def test_prefijo_antes_del_primer_guion(self) -> None:
        assert extraer_codigo_cliente("8043-TIENDA DONA MARIA") == "8043"

    def test_nombre_con_mas_guiones_no_confunde(self) -> None:
        assert extraer_codigo_cliente("9-AUTO-SERVICIO EL SOL") == "9"

    def test_sin_guion_devuelve_todo(self) -> None:
        assert extraer_codigo_cliente("SINGUION") == "SINGUION"

    def test_recorta_espacios(self) -> None:
        assert extraer_codigo_cliente("  8043 - TIENDA") == "8043"


class TestConvertirFecha:
    def test_datetime_a_date(self) -> None:
        assert convertir_fecha(datetime(2026, 6, 24, 10, 30)) == date(2026, 6, 24)

    def test_texto_iso(self) -> None:
        assert convertir_fecha("2026-06-24 00:00:00") == date(2026, 6, 24)

    def test_serial_danado_queda_none(self) -> None:
        # El ECOM real trae pedidos viejos con la fecha como texto serial de Excel.
        assert convertir_fecha("46190") is None

    def test_vacia_queda_none(self) -> None:
        assert convertir_fecha(None) is None


# Encabezados reales del export de ECOM (los del archivo de julio 2026; los viejos
# solo difieren en que el segundo "Total" venía renombrado "Total2").
_ENCABEZADOS: list[object] = [
    "Tipo", "Pedido", "Est", "Fecha", "Hora", "Sku", "nit/ced", "R. Social",
    "Cliente", "Ciudad", "Barrio", "Zona", "Direccion", "Telefono", "Total",
    "Asesor", "No Compra", "Bodega", "Bodega Transf", "Observaciones",
    "Cod.Prod", "Producto", "Cantidad", "Unidad", "Inventario", "Rotacion",
    "Precio U.", "Descuento", "Descuento_2", "Iva", "Total", None, "Tip Pro",
    "Comentario", "Kilos", "Fecha Entrega", "Pedidos Pideky", "Sistema Origen",
]  # fmt: skip


def _fila(pedido: str, h: str | None, i: str | None, fecha: object, ae: str, ai: str) -> list[object]:
    """Una línea con la semántica real: H y Total de factura solo en la 1ª línea."""
    celdas: list[object] = [None] * len(_ENCABEZADOS)
    celdas[0] = "PEDIDO"
    celdas[1] = pedido
    celdas[3] = fecha
    celdas[7] = h
    celdas[8] = i
    celdas[9] = "15001 - TUNJA"
    celdas[10] = "CENTRO"
    celdas[14] = "999999.99" if h is not None else None  # Total de FACTURA: no confundir
    celdas[21] = "PRODUCTO X"
    celdas[22] = 2
    celdas[30] = ae
    celdas[34] = ai
    return celdas


def _filas_de_prueba() -> list[list[object]]:
    return [
        _fila("100", "123-TIENDA DONA MARIA", "123-TIENDA", datetime(2026, 6, 24), "1234.56", "1500"),
        # Segunda línea del mismo pedido: H vacía (como en el archivo real), I presente.
        _fila("100", None, "123-TIENDA", datetime(2026, 6, 24), "1,000.44", "500"),
        # Pedido viejo con fecha dañada y sin I: el código sale de H.
        _fila("101", "456-OTRO NEGOCIO", None, "46190", "10", "0"),
    ]


def _guardar(
    ruta: Path,
    encabezados: list[object] | None = None,
    filas: list[list[object]] | None = None,
    titulo: str = "Hoja1",
) -> None:
    libro = openpyxl.Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = titulo
    hoja.append(encabezados if encabezados is not None else _ENCABEZADOS)
    for fila in filas if filas is not None else _filas_de_prueba():
        hoja.append(fila)
    libro.save(ruta)


def _verificar_lectura_normal(ruta: Path) -> None:
    """Las aserciones compartidas: los datos de _filas_de_prueba bien interpretados."""
    lineas = LectorEcomExcel().leer(ruta)

    assert len(lineas) == 3
    primera, segunda, tercera = lineas

    assert primera.pedido == "100"
    assert primera.codigo_cliente == "123"
    assert primera.nombre_cliente == "TIENDA"
    assert primera.fecha == date(2026, 6, 24)
    assert primera.total_linea == Decimal("1234.56")  # el de la LÍNEA, no 999999.99
    assert primera.kilos == Decimal("1.5")  # la columna Kilos viene en gramos
    assert primera.ciudad == "15001 - TUNJA"
    assert primera.barrio == "CENTRO"
    assert primera.cantidad == Decimal("2")

    # La segunda línea del pedido no trae H, pero I basta.
    assert segunda.codigo_cliente == "123"
    assert segunda.total_linea == Decimal("1000.44")
    assert segunda.kilos == Decimal("0.5")

    # Sin I, el código sale de H; la fecha dañada queda None (no se inventa).
    assert tercera.codigo_cliente == "456"
    assert tercera.fecha is None


def test_lee_lineas_con_la_semantica_del_archivo_real(tmp_path: Path) -> None:
    ruta = tmp_path / "ecom.xlsx"
    _guardar(ruta)
    _verificar_lectura_normal(ruta)


def test_la_hoja_puede_llamarse_de_cualquier_forma(tmp_path: Path) -> None:
    # El export de julio 2026 llegó con la hoja "Informe" en vez de "Hoja1".
    ruta = tmp_path / "ecom_informe.xlsx"
    _guardar(ruta, titulo="Informe")
    _verificar_lectura_normal(ruta)


def test_formato_viejo_con_total2_sigue_leyendo(tmp_path: Path) -> None:
    # Los archivos de junio traían el total de línea como "Total2" y una "Columna3".
    encabezados = list(_ENCABEZADOS)
    encabezados[30] = "Total2"
    encabezados[31] = "Columna3"
    ruta = tmp_path / "ecom_viejo.xlsx"
    _guardar(ruta, encabezados=encabezados)
    _verificar_lectura_normal(ruta)


def test_columna_extra_intermedia_no_rompe_el_mapeo(tmp_path: Path) -> None:
    posicion = 5  # una columna nueva de ECOM en plena zona de cabecera
    encabezados = list(_ENCABEZADOS)
    encabezados.insert(posicion, "Novedad")
    filas = []
    for fila in _filas_de_prueba():
        fila.insert(posicion, "X")
        filas.append(fila)
    ruta = tmp_path / "ecom_columna_extra.xlsx"
    _guardar(ruta, encabezados=encabezados, filas=filas)
    _verificar_lectura_normal(ruta)


def test_columnas_reordenadas_no_rompen_el_mapeo(tmp_path: Path) -> None:
    a, b = 3, 34  # Fecha ↔ Kilos: se mueven encabezado Y datos, como haría ECOM
    encabezados = list(_ENCABEZADOS)
    encabezados[a], encabezados[b] = encabezados[b], encabezados[a]
    filas = []
    for fila in _filas_de_prueba():
        fila[a], fila[b] = fila[b], fila[a]
        filas.append(fila)
    ruta = tmp_path / "ecom_reordenado.xlsx"
    _guardar(ruta, encabezados=encabezados, filas=filas)
    _verificar_lectura_normal(ruta)


def test_los_dos_total_sin_columna_iva(tmp_path: Path) -> None:
    # Sin "Iva" como ancla, el primer "Total" es factura y el segundo línea.
    posicion_iva = 29
    encabezados = list(_ENCABEZADOS)
    del encabezados[posicion_iva]
    filas = []
    for fila in _filas_de_prueba():
        del fila[posicion_iva]
        filas.append(fila)
    ruta = tmp_path / "ecom_sin_iva.xlsx"
    _guardar(ruta, encabezados=encabezados, filas=filas)
    _verificar_lectura_normal(ruta)


def test_con_varias_hojas_elige_la_que_tiene_los_encabezados(tmp_path: Path) -> None:
    ruta = tmp_path / "ecom_varias_hojas.xlsx"
    libro = openpyxl.Workbook()
    resumen = libro.active
    assert resumen is not None
    resumen.title = "Resumen"
    resumen.append(["Esto", "no", "es", "el", "export"])
    datos = libro.create_sheet("Datos")
    datos.append(_ENCABEZADOS)
    for fila in _filas_de_prueba():
        datos.append(fila)
    libro.save(ruta)
    _verificar_lectura_normal(ruta)


def test_sin_columna_esencial_el_error_dice_cual_falta(tmp_path: Path) -> None:
    posicion_kilos = 34
    encabezados = list(_ENCABEZADOS)
    del encabezados[posicion_kilos]
    filas = []
    for fila in _filas_de_prueba():
        del fila[posicion_kilos]
        filas.append(fila)
    ruta = tmp_path / "ecom_sin_kilos.xlsx"
    _guardar(ruta, encabezados=encabezados, filas=filas)

    with pytest.raises(ColumnasEcomFaltantes) as excinfo:
        LectorEcomExcel().leer(ruta)
    mensaje = str(excinfo.value)
    assert "[Kilos]" in mensaje
    assert "Encabezados encontrados" in mensaje
    assert "Pedido" in mensaje  # muestra lo que sí trae el archivo


def test_columna_opcional_faltante_no_falla(tmp_path: Path) -> None:
    posicion_direccion = 12
    encabezados = list(_ENCABEZADOS)
    del encabezados[posicion_direccion]
    filas = []
    for fila in _filas_de_prueba():
        del fila[posicion_direccion]
        filas.append(fila)
    ruta = tmp_path / "ecom_sin_direccion.xlsx"
    _guardar(ruta, encabezados=encabezados, filas=filas)

    lineas = LectorEcomExcel().leer(ruta)
    assert len(lineas) == 3
    assert all(linea.direccion is None for linea in lineas)


def test_archivo_sin_encabezados_de_ecom_lanza_error_claro(tmp_path: Path) -> None:
    ruta = tmp_path / "otra_cosa.xlsx"
    libro = openpyxl.Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = "OTRA"
    hoja.append(["Nombre", "Valor"])
    libro.save(ruta)

    with pytest.raises(ColumnasEcomFaltantes, match="faltan las columnas"):
        LectorEcomExcel().leer(ruta)


def test_fila_sin_cliente_lanza_error_con_la_fila(tmp_path: Path) -> None:
    celdas: list[object] = [None] * len(_ENCABEZADOS)
    celdas[1] = "200"  # pedido sin Cliente ni R. Social
    ruta = tmp_path / "ecom_malo.xlsx"
    _guardar(ruta, filas=[celdas])

    with pytest.raises(FormatoEcomInvalido, match=r"fila 2"):
        LectorEcomExcel().leer(ruta)
