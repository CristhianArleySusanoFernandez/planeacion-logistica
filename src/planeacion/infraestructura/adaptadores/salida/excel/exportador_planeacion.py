"""Exportador Excel de la planeación: las hojas que consume facturación.

Replica el layout del .xlsm de referencia (inspeccionado en DEL_24_PAR_EL_26_JUNIO.xlsm):

- ECOM: filas 1-2 vacías; fila 3 encabezado `Etiquetas de fila | Mín. de RUTA`;
  una fila por CLIENTE con su carro asignado ('#N/A' si quedó sin zona); cierra
  con la fila `Total general`.
- PLANEACION: fila 2 `Promedio Vh`, fila 3 `Ventas Totales` (E en KILOS), fila 4
  encabezados del pivote, y desde la fila 5 una fila por zona en orden
  alfabético con la columna E en GRAMOS (así viene en el archivo viejo).
- BASE: el bloque de estadísticas por carro (`Ruta | Facturas | ... | CIUDAD`)
  más las zonas asignadas concatenadas en la columna I.
- PEDIDOS: detalle por factura (extra pedido por el usuario; no existe con esta
  forma en la referencia, que lo trae por línea de producto).

Solo traducción de datos: todos los números vienen ya calculados en el DTO.
"""

from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from planeacion.application.dto.planeacion import PlaneacionCompleta
from planeacion.domain.modelo import CargaCarro

_GRAMOS_POR_KILO = Decimal("1000")
_SIN_CARRO = "#N/A"
_SIN_ZONA = "#N/D"
_NEGRITA = Font(bold=True)
_RELLENO_ENCABEZADO = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")

ENCABEZADO_ECOM = ("Etiquetas de fila", "Mín. de RUTA")
ENCABEZADO_PLANEACION = (
    "CARROS",
    "Etiquetas de fila",
    "Cuenta de Total",
    "Suma de Total2",
    "Suma de Kilos",
    "Clientes Unicos",
)
ENCABEZADO_BASE = ("Ruta", "Facturas", "Clientes", "Pesos", "Kilos", "CONDUCTOR", "AUX", "CIUDAD")
ENCABEZADO_PEDIDOS = (
    "Fecha",
    "Pedido",
    "CODIGO",
    "CLIENTES",
    "Ciudad",
    "Barrio",
    "Direccion",
    "Total",
    "Kilos",
    "Asesor",
    "CUADRANTE",
    "CARRO",
)


def _clave_carro(numero: str) -> tuple[int, str]:
    """Orden estable de números de carro ('9' antes que '108')."""
    return (len(numero), numero)


def _escribir_encabezado(hoja: Worksheet, fila: int, valores: tuple[str, ...], columna: int = 1) -> None:
    for desplazamiento, valor in enumerate(valores):
        celda = hoja.cell(row=fila, column=columna + desplazamiento, value=valor)
        celda.font = _NEGRITA
        celda.fill = _RELLENO_ENCABEZADO


def _ajustar_anchos(hoja: Worksheet, anchos: dict[str, int]) -> None:
    for letra, ancho in anchos.items():
        hoja.column_dimensions[letra].width = ancho


class ExportadorExcelPlaneacion:
    """Adaptador del puerto ``ExportadorPlaneacion``."""

    def exportar(self, planeacion: PlaneacionCompleta, ruta_salida: Path) -> Path:
        carro_por_zona = {
            zona.zona.nombre: carga.carro.numero
            for cargas in planeacion.resultado.cargas_por_municipio.values()
            for carga in cargas
            for zona in carga.zonas
        }
        libro = Workbook()
        hoja_ecom = libro.active
        assert hoja_ecom is not None  # openpyxl siempre crea la hoja inicial
        hoja_ecom.title = "ECOM"
        self._hoja_ecom(hoja_ecom, planeacion, carro_por_zona)
        self._hoja_planeacion(libro.create_sheet("PLANEACION"), planeacion, carro_por_zona)
        self._hoja_base(libro.create_sheet("BASE"), planeacion)
        self._hoja_pedidos(libro.create_sheet("PEDIDOS"), planeacion, carro_por_zona)
        libro.save(ruta_salida)
        return ruta_salida

    def _hoja_ecom(
        self, hoja: Worksheet, planeacion: PlaneacionCompleta, carro_por_zona: dict[str, str]
    ) -> None:
        _escribir_encabezado(hoja, 3, ENCABEZADO_ECOM)
        carro_por_cliente: dict[str, str | None] = {}
        for factura in planeacion.facturas:
            carro = carro_por_zona.get(factura.zona) if factura.zona else None
            carro_por_cliente.setdefault(factura.codigo_cliente, carro)

        clientes = sorted(
            carro_por_cliente.items(),
            key=lambda par: (par[1] is None, _clave_carro(par[1] or ""), par[0]),
        )
        fila = 4
        for codigo, carro in clientes:
            hoja.cell(row=fila, column=1, value=codigo)
            hoja.cell(row=fila, column=2, value=carro if carro is not None else _SIN_CARRO)
            fila += 1
        hoja.cell(row=fila, column=1, value="Total general").font = _NEGRITA
        hoja.cell(row=fila, column=2, value=len(clientes)).font = _NEGRITA
        _ajustar_anchos(hoja, {"A": 18, "B": 14})
        hoja.freeze_panes = "A4"

    def _hoja_planeacion(
        self, hoja: Worksheet, planeacion: PlaneacionCompleta, carro_por_zona: dict[str, str]
    ) -> None:
        cargas = [
            carga
            for cargas_municipio in planeacion.resultado.cargas_por_municipio.values()
            for carga in cargas_municipio
        ]
        carros_usados = sum(1 for carga in cargas if carga.zonas)

        hoja.cell(row=2, column=2, value="Promedio Vh").font = _NEGRITA
        if carros_usados:
            hoja.cell(row=2, column=3, value=planeacion.total_facturas / carros_usados)
            hoja.cell(row=2, column=4, value=float(planeacion.total_pesos) / carros_usados)
            hoja.cell(row=2, column=5, value=float(planeacion.total_kilos) / carros_usados)
            hoja.cell(row=2, column=6, value=planeacion.total_clientes / carros_usados)

        hoja.cell(row=3, column=2, value="Ventas Totales").font = _NEGRITA
        hoja.cell(row=3, column=3, value=planeacion.total_facturas)
        hoja.cell(row=3, column=4, value=planeacion.total_pesos)
        hoja.cell(row=3, column=5, value=planeacion.total_kilos)  # aquí en KILOS, como la referencia
        hoja.cell(row=3, column=6, value=planeacion.total_clientes)

        _escribir_encabezado(hoja, 4, ENCABEZADO_PLANEACION)
        zonas = sorted(
            ((carga.carro.numero, zona) for carga in cargas for zona in carga.zonas),
            key=lambda par: par[1].zona.nombre,
        )
        fila = 5
        for carro, zona in zonas:
            hoja.cell(row=fila, column=1, value=carro)
            hoja.cell(row=fila, column=2, value=zona.zona.nombre)
            hoja.cell(row=fila, column=3, value=zona.facturas)
            hoja.cell(row=fila, column=4, value=zona.pesos)
            hoja.cell(row=fila, column=5, value=zona.kilos * _GRAMOS_POR_KILO)  # zonas en GRAMOS
            hoja.cell(row=fila, column=6, value=zona.clientes)
            hoja.cell(row=fila, column=7, value=carro)
            fila += 1
        self._fila_no_resueltos(hoja, fila, planeacion)
        _ajustar_anchos(hoja, {"A": 10, "B": 55, "C": 14, "D": 16, "E": 14, "F": 14, "G": 8})
        hoja.freeze_panes = "A5"

    def _fila_no_resueltos(self, hoja: Worksheet, fila: int, planeacion: PlaneacionCompleta) -> None:
        """La fila '#N/D' del pivote viejo: los clientes que quedaron sin zona."""
        sin_zona = [factura for factura in planeacion.facturas if factura.zona is None]
        if not sin_zona:
            return
        hoja.cell(row=fila, column=2, value=_SIN_ZONA)
        hoja.cell(row=fila, column=3, value=len({factura.pedido for factura in sin_zona}))
        hoja.cell(row=fila, column=4, value=sum((f.total for f in sin_zona), Decimal("0")))
        hoja.cell(
            row=fila,
            column=5,
            value=sum((f.kilos for f in sin_zona), Decimal("0")) * _GRAMOS_POR_KILO,
        )
        hoja.cell(row=fila, column=6, value=len({factura.codigo_cliente for factura in sin_zona}))

    def _hoja_base(self, hoja: Worksheet, planeacion: PlaneacionCompleta) -> None:
        _escribir_encabezado(hoja, 1, ENCABEZADO_BASE)
        cargas: list[CargaCarro] = sorted(
            (
                carga
                for cargas_municipio in planeacion.resultado.cargas_por_municipio.values()
                for carga in cargas_municipio
                if carga.zonas
            ),
            key=lambda carga: _clave_carro(carga.carro.numero),
        )
        for fila, carga in enumerate(cargas, start=2):
            hoja.cell(row=fila, column=1, value=carga.carro.numero)
            hoja.cell(row=fila, column=2, value=carga.facturas)
            hoja.cell(row=fila, column=3, value=carga.clientes)
            hoja.cell(row=fila, column=4, value=carga.pesos)
            hoja.cell(row=fila, column=5, value=carga.kilos)
            hoja.cell(row=fila, column=6, value=carga.carro.conductor)
            hoja.cell(row=fila, column=7, value=carga.carro.auxiliar)
            municipio = carga.carro.municipio.nombre if carga.carro.municipio else None
            hoja.cell(row=fila, column=8, value=municipio)
            zonas = ", ".join(sorted(zona.zona.nombre for zona in carga.zonas))
            hoja.cell(row=fila, column=9, value=zonas)
        _ajustar_anchos(
            hoja, {"A": 10, "B": 10, "C": 10, "D": 14, "E": 12, "F": 22, "G": 22, "H": 16, "I": 80}
        )
        hoja.freeze_panes = "A2"

    def _hoja_pedidos(
        self, hoja: Worksheet, planeacion: PlaneacionCompleta, carro_por_zona: dict[str, str]
    ) -> None:
        _escribir_encabezado(hoja, 1, ENCABEZADO_PEDIDOS)
        for fila, factura in enumerate(planeacion.facturas, start=2):
            carro = carro_por_zona.get(factura.zona) if factura.zona else None
            hoja.cell(row=fila, column=1, value=factura.fecha)
            hoja.cell(row=fila, column=2, value=factura.pedido)
            hoja.cell(row=fila, column=3, value=factura.codigo_cliente)
            hoja.cell(row=fila, column=4, value=factura.nombre_cliente)
            hoja.cell(row=fila, column=5, value=factura.ciudad)
            hoja.cell(row=fila, column=6, value=factura.barrio)
            hoja.cell(row=fila, column=7, value=factura.direccion)
            hoja.cell(row=fila, column=8, value=factura.total)
            hoja.cell(row=fila, column=9, value=factura.kilos)
            hoja.cell(row=fila, column=10, value=factura.asesor)
            hoja.cell(row=fila, column=11, value=factura.zona if factura.zona else _SIN_ZONA)
            hoja.cell(row=fila, column=12, value=carro if carro is not None else _SIN_CARRO)
        _ajustar_anchos(
            hoja,
            {
                "A": 12,
                "B": 12,
                "C": 15,
                "D": 32,
                "E": 18,
                "F": 18,
                "G": 24,
                "H": 12,
                "I": 10,
                "J": 16,
                "K": 45,
                "L": 10,
            },
        )
        hoja.freeze_panes = "A2"
