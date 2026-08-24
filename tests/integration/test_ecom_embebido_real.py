"""El bloque de ECOM embebido cuadra con la hoja PLANEACION del mismo .xlsm.

Es la prueba que hace confiable a ``planeacion-validar``: si el bloque se leyera
mal (por ejemplo tomando los ``Total``/``Kilos`` de la tabla de trabajo que está
a su izquierda), los totales reconstruidos no darían los mismos que Rudy dejó en
la fila "Ventas Totales" y toda la comparación de zonas mediría cualquier cosa.

Los números esperados no están escritos a mano: se leen de la propia hoja
PLANEACION de cada archivo, así que la prueba compara dos lecturas independientes
del mismo día.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom_embebido import LectorEcomEmbebido
from planeacion.infraestructura.adaptadores.salida.excel.lector_referencia import LectorReferenciaExcel

# Un día normal, uno de junio y uno de los dos que cubren DOS jornadas planeadas
# juntas (por eso el validador no filtra por fecha: filtrando, este último
# perdería la mitad de sus facturas y jamás cuadraría).
_ARCHIVOS = [
    "datos/DEL 07 PARA EL 09 JULIO.xlsm",
    "datos/DEL_24_PAR_EL_26_JUNIO.xlsm",
    "datos/DEL 20-21 PARA EL 23 JULIO.xlsm",
]

# Los totales de PLANEACION salen de fórmulas de Excel en coma flotante: no son
# comparables al centavo exacto contra los Decimal que arma el lector.
_TOLERANCIA_PESOS = Decimal("1")
_TOLERANCIA_KILOS = Decimal("0.01")


@pytest.mark.integration
@pytest.mark.parametrize("ruta", _ARCHIVOS)
def test_los_totales_del_bloque_embebido_cuadran_con_la_hoja_planeacion(ruta: str) -> None:
    archivo = Path(ruta)
    if not archivo.exists():
        pytest.skip(f"sin {ruta}")

    lineas = LectorEcomEmbebido().leer(archivo)
    with LectorReferenciaExcel(archivo) as referencia:
        esperados = referencia.leer_totales_planeacion()

    assert len({linea.pedido for linea in lineas}) == esperados.facturas
    assert len({linea.codigo_cliente for linea in lineas}) == esperados.clientes
    assert abs(sum(linea.total_linea for linea in lineas) - esperados.pesos) <= _TOLERANCIA_PESOS
    assert abs(sum(linea.kilos for linea in lineas) - esperados.kilos) <= _TOLERANCIA_KILOS


@pytest.mark.integration
def test_el_archivo_de_dos_jornadas_trae_las_dos_fechas() -> None:
    """Documenta por qué existe la bandera ``todas_las_fechas``: este archivo no
    es un día, son dos, y la planeación manual los repartió como un solo bloque."""
    archivo = Path("datos/DEL 20-21 PARA EL 23 JULIO.xlsm")
    if not archivo.exists():
        pytest.skip("sin el archivo de dos jornadas")

    fechas = {linea.fecha for linea in LectorEcomEmbebido().leer(archivo)}

    assert len(fechas) == 2


@pytest.mark.integration
def test_hay_un_archivo_donde_el_bloque_pegado_es_mas_grande_que_lo_planeado() -> None:
    """El caso que obliga al validador a descartar archivos en vez de promediarlos.

    En "DEL 14 PARA EL 16 JULIO" el bloque de ECOM trae 2.435 facturas pero la
    planeación se hizo sobre 2.097: de los 1.285 pedidos del 14 de julio solo
    entraron 947. El bloque de la izquierda (A-P), que es la lista de facturas
    efectivamente trabajadas, tiene esas 2.097 filas y suma exacto el total de
    PLANEACION. O sea que el ECOM se pegó cuando el día aún no había cerrado y
    después se refrescó. Comparar el reparto de ese archivo mediría la propuesta
    contra una entrada que Rudy nunca tuvo, así que el descuadre se reporta y el
    archivo queda fuera del resumen.
    """
    archivo = Path("datos/DEL 14 PARA EL 16 JULIO.xlsm")
    if not archivo.exists():
        pytest.skip("sin el archivo de la jornada parcial")

    lineas = LectorEcomEmbebido().leer(archivo)
    with LectorReferenciaExcel(archivo) as referencia:
        esperados = referencia.leer_totales_planeacion()

    assert len({linea.pedido for linea in lineas}) > esperados.facturas
