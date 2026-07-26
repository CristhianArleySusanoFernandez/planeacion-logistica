"""Validación de la Fase 2: el pivote de la app debe reproducir la hoja PLANEACION.

Los valores esperados se leen DEL PROPIO .xlsm (fila "Ventas Totales" y filas de
zona de la hoja PLANEACION), nunca quemados en el test. Nota honesta sobre los
datos: el crudo trae 94 pedidos viejos del 17-jun-2026 con la fecha dañada como
texto serial ('46190'); Rudy solo pivoteó los del 24-jun, por eso el caso de uso
filtra por fecha y este test verifica también lo excluido.

Requiere credenciales de Supabase (BD ya sembrada) y los archivos en datos/.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from pydantic import ValidationError

from planeacion.domain.servicios.parseo_zonas import normalizar_nombre_zona

RUTA_ECOM = Path("datos/pedidos24-26Junio.xlsx")
RUTA_XLSM = Path("datos/DEL_24_PAR_EL_26_JUNIO.xlsm")
HOJA_PLANEACION = "PLANEACION"
_ETIQUETAS_NO_ZONA = {"#N/D", "(en blanco)"}
_GRAMOS_POR_KILO = Decimal("1000")
_TOLERANCIA = Decimal("0.01")  # redondeo de los floats que Excel guarda en el pivote


def _hay_credenciales() -> bool:
    try:
        from planeacion.config.settings import Settings

        Settings()
        return True
    except ValidationError:
        return False


requiere_entorno = pytest.mark.skipif(
    not (_hay_credenciales() and RUTA_ECOM.exists() and RUTA_XLSM.exists()),
    reason="sin credenciales de Supabase o sin los archivos de datos/",
)


@dataclass
class _ZonaEsperada:
    facturas: int = 0
    clientes: int = 0
    pesos: Decimal = Decimal("0")
    kilos: Decimal = Decimal("0")  # ya en kg (la hoja los trae en gramos)


@dataclass
class _Esperado:
    total_facturas: int
    total_clientes: int
    total_pesos: Decimal
    total_kilos: Decimal
    zonas: dict[str, _ZonaEsperada]


def _decimal(valor: object) -> Decimal:
    return Decimal(str(valor))


def _leer_esperado_de_planeacion() -> _Esperado:
    """Lee "Ventas Totales" y las filas de zona. La hoja repite algunas zonas con
    espacios finales distintos (p.ej. "MONIQUIRA 2" y "MONIQUIRA 2 "): al
    normalizar se suman, igual que hace nuestra app."""
    libro = openpyxl.load_workbook(RUTA_XLSM, read_only=True, data_only=True)
    try:
        hoja = libro[HOJA_PLANEACION]
        filas = list(hoja.iter_rows(min_row=1, max_row=200, max_col=6, values_only=True))
    finally:
        libro.close()

    totales = None
    zonas: dict[str, _ZonaEsperada] = {}
    en_zonas = False
    for fila in filas:
        etiqueta = str(fila[1]).strip() if fila[1] is not None else None
        if etiqueta == "Ventas Totales":
            totales = fila
            continue
        if etiqueta == "Etiquetas de fila":
            en_zonas = True
            continue
        if not en_zonas:
            continue
        if etiqueta is None or etiqueta in _ETIQUETAS_NO_ZONA:
            break  # se acabaron las filas de zona reales
        zona = zonas.setdefault(normalizar_nombre_zona(etiqueta), _ZonaEsperada())
        zona.facturas += int(fila[2])  # type: ignore[arg-type]
        zona.clientes += int(fila[5])  # type: ignore[arg-type]
        zona.pesos += _decimal(fila[3])
        zona.kilos += _decimal(fila[4]) / _GRAMOS_POR_KILO

    assert totales is not None, "no se encontró la fila 'Ventas Totales' en PLANEACION"
    assert zonas, "no se encontraron filas de zona en PLANEACION"
    return _Esperado(
        total_facturas=int(totales[2]),  # type: ignore[arg-type]
        total_clientes=int(totales[5]),  # type: ignore[arg-type]
        total_pesos=_decimal(totales[3]),
        total_kilos=_decimal(totales[4]),  # el total ya viene en kg
        zonas=zonas,
    )


@pytest.mark.integration
@requiere_entorno
def test_el_pivote_reproduce_la_hoja_planeacion() -> None:
    from planeacion.config.contenedor import crear_contenedor, crear_generar_pivote
    from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import LectorEcomExcel

    esperado = _leer_esperado_de_planeacion()
    caso_uso = crear_generar_pivote(crear_contenedor())

    # Sin fecha: debe escoger sola la del día planeado (la más frecuente del archivo).
    pivote = caso_uso.ejecutar(RUTA_ECOM)

    # Totales generales contra "Ventas Totales" (facturas y clientes exactos).
    assert pivote.total_facturas == esperado.total_facturas
    assert pivote.total_clientes == esperado.total_clientes
    assert abs(pivote.total_pesos - esperado.total_pesos) <= _TOLERANCIA
    assert abs(pivote.total_kilos - esperado.total_kilos) <= _TOLERANCIA

    # Zona por zona: mismas zonas y mismos números.
    nuestras = {zona.zona: zona for zona in pivote.zonas}
    assert set(nuestras) == set(esperado.zonas)
    diferencias = []
    for nombre, zona_esperada in esperado.zonas.items():
        zona = nuestras[nombre]
        if (
            zona.facturas != zona_esperada.facturas
            or zona.clientes != zona_esperada.clientes
            or abs(zona.pesos - zona_esperada.pesos) > _TOLERANCIA
            or abs(zona.kilos - zona_esperada.kilos) > _TOLERANCIA
        ):
            diferencias.append(
                f"{nombre}: app=({zona.facturas}, {zona.clientes}, {zona.pesos}, {zona.kilos}) "
                f"esperado=({zona_esperada.facturas}, {zona_esperada.clientes}, "
                f"{zona_esperada.pesos}, {zona_esperada.kilos})"
            )
    assert not diferencias, "zonas que no cuadran con PLANEACION:\n" + "\n".join(diferencias)

    # Lo excluido por fecha también debe cuadrar: nada se pierde en silencio.
    pedidos_en_archivo = {linea.pedido for linea in LectorEcomExcel().leer(RUTA_ECOM)}
    assert pivote.pedidos_excluidos_por_fecha == len(pedidos_en_archivo) - pivote.total_facturas
