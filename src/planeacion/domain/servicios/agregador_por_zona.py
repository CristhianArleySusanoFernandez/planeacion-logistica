"""Agrega las líneas del ECOM por zona: facturas, clientes únicos, pesos y kilos.

Las facturas se cuentan por pedidos DISTINTOS (un pedido de 5 líneas es 1 factura)
y los clientes por códigos distintos. Las líneas cuyo cliente no resuelve zona no
se botan: se acumulan aparte con su motivo, y los totales generales las incluyen
(igual que la fila "Ventas Totales" del Excel viejo).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from planeacion.domain.modelo import Zona
from planeacion.domain.modelo.pedido import LineaPedido
from planeacion.domain.modelo.pivote import ClienteNoResuelto, FacturaAgrupada, ZonaAgregada
from planeacion.domain.servicios.resolutor_zona import ResolutorDeZona


@dataclass(frozen=True)
class ResultadoAgregacion:
    """El pivote ya calculado. Los totales cubren zonas + no resueltos."""

    zonas: tuple[ZonaAgregada, ...]  # ordenadas por municipio y nombre de zona
    no_resueltos: tuple[ClienteNoResuelto, ...]
    facturas: tuple[FacturaAgrupada, ...]  # por zona y cliente; las sin zona al final
    total_facturas: int
    total_clientes: int
    total_pesos: Decimal
    total_kilos: Decimal
    facturas_no_resueltas: int
    pesos_no_resueltos: Decimal
    kilos_no_resueltos: Decimal


class _Acumulador:
    def __init__(self) -> None:
        self.pedidos: set[str] = set()
        self.clientes: set[str] = set()
        self.pesos = Decimal("0")
        self.kilos = Decimal("0")

    def sumar(self, linea: LineaPedido) -> None:
        self.pedidos.add(linea.pedido)
        self.clientes.add(linea.codigo_cliente)
        self.pesos += linea.total_linea
        self.kilos += linea.kilos


class AgregadorPorZona:
    def agregar(self, lineas: Sequence[LineaPedido], resolutor: ResolutorDeZona) -> ResultadoAgregacion:
        por_zona: dict[Zona, _Acumulador] = {}
        sin_zona = _Acumulador()
        linea_por_no_resuelto: dict[str, LineaPedido] = {}
        total = _Acumulador()

        for linea in lineas:
            total.sumar(linea)
            zona = resolutor.resolver(linea.codigo_cliente)
            if zona is None:
                sin_zona.sumar(linea)
                linea_por_no_resuelto.setdefault(linea.codigo_cliente, linea)
                continue
            por_zona.setdefault(zona, _Acumulador()).sumar(linea)

        zonas = tuple(
            ZonaAgregada(
                zona=zona,
                facturas=len(acumulado.pedidos),
                clientes=len(acumulado.clientes),
                pesos=acumulado.pesos,
                kilos=acumulado.kilos,
            )
            for zona, acumulado in sorted(
                por_zona.items(), key=lambda par: (par[0].municipio.nombre, par[0].nombre)
            )
        )
        no_resueltos = tuple(
            ClienteNoResuelto(
                codigo=codigo,
                motivo=resolutor.motivo_no_resuelto(codigo),
                nombre=linea.nombre_cliente,
                documento=linea.documento,
                direccion=linea.direccion,
                ciudad=linea.ciudad,
                barrio=linea.barrio,
            )
            for codigo, linea in sorted(linea_por_no_resuelto.items())
        )
        return ResultadoAgregacion(
            zonas=zonas,
            no_resueltos=no_resueltos,
            facturas=_agrupar_facturas(lineas, resolutor),
            total_facturas=len(total.pedidos),
            total_clientes=len(total.clientes),
            total_pesos=total.pesos,
            total_kilos=total.kilos,
            facturas_no_resueltas=len(sin_zona.pedidos),
            pesos_no_resueltos=sin_zona.pesos,
            kilos_no_resueltos=sin_zona.kilos,
        )


def _agrupar_facturas(
    lineas: Sequence[LineaPedido], resolutor: ResolutorDeZona
) -> tuple[FacturaAgrupada, ...]:
    """Colapsa las líneas por pedido. R. Social y otros campos vienen solo en la
    primera línea del pedido: se toma el primer valor no vacío de cada uno."""
    por_pedido: dict[str, list[LineaPedido]] = {}
    for linea in lineas:
        por_pedido.setdefault(linea.pedido, []).append(linea)

    facturas = []
    for pedido, del_pedido in por_pedido.items():
        primera = del_pedido[0]
        facturas.append(
            FacturaAgrupada(
                pedido=pedido,
                codigo_cliente=primera.codigo_cliente,
                zona=resolutor.resolver(primera.codigo_cliente),
                total=sum((linea.total_linea for linea in del_pedido), Decimal("0")),
                kilos=sum((linea.kilos for linea in del_pedido), Decimal("0")),
                fecha=primera.fecha,
                nombre_cliente=_primer_valor(del_pedido, "nombre_cliente"),
                ciudad=_primer_valor(del_pedido, "ciudad"),
                barrio=_primer_valor(del_pedido, "barrio"),
                direccion=_primer_valor(del_pedido, "direccion"),
                asesor=_primer_valor(del_pedido, "asesor"),
            )
        )
    facturas.sort(
        key=lambda f: (
            f.zona is None,
            f.zona.municipio.nombre if f.zona else "",
            f.zona.nombre if f.zona else "",
            f.codigo_cliente,
            f.pedido,
        )
    )
    return tuple(facturas)


def _primer_valor(lineas: Sequence[LineaPedido], campo: str) -> str | None:
    for linea in lineas:
        valor: str | None = getattr(linea, campo)
        if valor is not None:
            return valor
    return None
