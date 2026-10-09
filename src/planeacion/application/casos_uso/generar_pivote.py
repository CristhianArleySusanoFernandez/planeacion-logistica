"""Caso de uso: generar el pivote por zona desde el ECOM crudo del día.

El archivo de ECOM puede traer pedidos viejos colados (p.ej. de la semana
anterior, con la fecha dañada como texto serial). El pivote es de UN día: se
filtra por la fecha pedida (o la más frecuente del archivo) y lo excluido se
reporta en el DTO en vez de perderse en silencio.
"""

import logging
from collections import Counter
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

from planeacion.application.dto.pivote import (
    ClienteNoResueltoDTO,
    FacturaDTO,
    LineaKilosExcluidosDTO,
    PivotePorZonaDTO,
    ZonaAgregadaDTO,
)
from planeacion.application.puertos.salida.lector_pedidos import LectorDePedidos
from planeacion.application.puertos.salida.repositorios import (
    RepositorioClientes,
    RepositorioOverrides,
    RepositorioZonas,
)
from planeacion.domain.errores import SinPedidosParaPivotear
from planeacion.domain.modelo import LineaPedido, Zona
from planeacion.domain.servicios.agregador_por_zona import AgregadorPorZona, ResultadoAgregacion
from planeacion.domain.servicios.guarda_kilos import (
    KILOS_MAX_POR_UNIDAD,
    LineaSospechosa,
    detectar_kilos_sospechosos,
    sin_kilos_sospechosos,
)
from planeacion.domain.servicios.parseo_zonas import normalizar_nombre_zona
from planeacion.domain.servicios.resolutor_zona import ResolutorDeZona
from planeacion.instrumentacion import medir

logger = logging.getLogger(__name__)


class CasoDeUsoGenerarPivote:
    """Implementación del puerto de entrada ``GenerarPivotePorZona``."""

    def __init__(
        self,
        lector: LectorDePedidos,
        clientes: RepositorioClientes,
        overrides: RepositorioOverrides,
        zonas: RepositorioZonas,
    ) -> None:
        self._lector = lector
        self._clientes = clientes
        self._overrides = overrides
        self._zonas = zonas
        self._agregador = AgregadorPorZona()

    def ejecutar(
        self,
        ruta_ecom: Path,
        fecha: date | None = None,
        todas_las_fechas: bool = False,
        kilos_max_por_unidad: Decimal = KILOS_MAX_POR_UNIDAD,
    ) -> PivotePorZonaDTO:
        with medir("lectura del ECOM", logger):
            lineas = self._lector.leer(ruta_ecom)
        if not lineas:
            raise SinPedidosParaPivotear(f"{ruta_ecom.name} no trae líneas de pedido")

        # Guarda de kilos: ECOM trae productos con el peso mal cargado en la ficha
        # (un caso real de 715,5 kg la unidad). Se les ponen los kilos en cero
        # ANTES de agregar, así no contaminan el pivote ni el balanceo; la factura
        # y el cliente siguen contando porque el pedido existe.
        with medir("guarda de kilos", logger):
            sospechosas = detectar_kilos_sospechosos(lineas, maximo_por_unidad=kilos_max_por_unidad)
            kilos_excluidos = sum((s.linea.kilos for s in sospechosas), Decimal("0"))
            lineas = sin_kilos_sospechosos(lineas, sospechosas)

        fecha_pivote = fecha or _fecha_mas_frecuente(lineas)
        if todas_las_fechas:
            # El origen ya viene filtrado y a veces cubre dos días a propósito
            # (jornadas que se planearon juntas): filtrar por uno solo partiría
            # en dos una planeación que se hizo entera. La fecha del DTO sigue
            # siendo la más frecuente, solo como etiqueta del día.
            return _a_dto(
                fecha_pivote,
                self._agregar(lineas),
                lineas,
                [],
                sospechosas,
                kilos_excluidos,
            )

        del_dia = [linea for linea in lineas if linea.fecha == fecha_pivote]
        if not del_dia:
            raise SinPedidosParaPivotear(
                f"{ruta_ecom.name} no trae pedidos con fecha {fecha_pivote.isoformat()}"
            )
        excluidas = [linea for linea in lineas if linea.fecha != fecha_pivote]

        resultado = self._agregar(del_dia)
        # Las sospechosas que quedaron fuera del día tampoco se reportan: el aviso
        # tiene que hablar de lo que se planea hoy.
        del_dia_marcadas = [s for s in sospechosas if s.linea.fecha == fecha_pivote]
        return _a_dto(
            fecha_pivote,
            resultado,
            del_dia,
            excluidas,
            del_dia_marcadas,
            sum((s.linea.kilos for s in del_dia_marcadas), Decimal("0")),
        )

    def _agregar(self, lineas: list[LineaPedido]) -> ResultadoAgregacion:
        """Resuelve la zona de cada línea y agrega por zona, midiendo las dos."""
        resolutor = self._crear_resolutor()
        with medir("resolucion de zonas + pivote", logger):
            return self._agregador.agregar(lineas, resolutor)

    def _crear_resolutor(self) -> ResolutorDeZona:
        with medir("zonas (catalogo)", logger):
            zonas_por_nombre = {normalizar_nombre_zona(z.nombre): z for z in self._zonas.listar()}
        with medir("maestra de clientes", logger):
            zonas_maestra = {cliente.codigo: cliente.zona for cliente in self._clientes.listar()}
        zonas_override: dict[str, Zona] = {}
        for override in self._overrides.listar():
            zona = zonas_por_nombre.get(normalizar_nombre_zona(override.zona_nombre))
            if zona is not None:
                zonas_override[override.cliente_codigo] = zona
        return ResolutorDeZona(zonas_maestra, zonas_override)


def _fecha_mas_frecuente(lineas: list[LineaPedido]) -> date:
    conteo = Counter(linea.fecha for linea in lineas if linea.fecha is not None)
    if not conteo:
        raise SinPedidosParaPivotear("ninguna línea trae fecha legible; pasa la fecha a mano")
    return conteo.most_common(1)[0][0]


def _a_dto(
    fecha_pivote: date,
    resultado: ResultadoAgregacion,
    del_dia: list[LineaPedido],
    excluidas: list[LineaPedido],
    kilos_sospechosos: Sequence[LineaSospechosa] = (),
    kilos_excluidos: Decimal = Decimal("0"),
) -> PivotePorZonaDTO:
    pedidos_del_dia = {linea.pedido for linea in del_dia}
    pedidos_excluidos = {linea.pedido for linea in excluidas} - pedidos_del_dia
    fechas_excluidas = sorted({linea.fecha.isoformat() if linea.fecha else "ilegible" for linea in excluidas})
    return PivotePorZonaDTO(
        fecha=fecha_pivote,
        zonas=tuple(
            ZonaAgregadaDTO(
                municipio=agregada.zona.municipio.nombre,
                zona=agregada.zona.nombre,
                facturas=agregada.facturas,
                clientes=agregada.clientes,
                pesos=agregada.pesos,
                kilos=agregada.kilos,
            )
            for agregada in resultado.zonas
        ),
        total_facturas=resultado.total_facturas,
        total_clientes=resultado.total_clientes,
        total_pesos=resultado.total_pesos,
        total_kilos=resultado.total_kilos,
        no_resueltos=tuple(
            ClienteNoResueltoDTO(
                codigo=cliente.codigo,
                motivo=cliente.motivo.value,
                nombre=cliente.nombre,
                documento=cliente.documento,
                direccion=cliente.direccion,
                ciudad=cliente.ciudad,
                barrio=cliente.barrio,
            )
            for cliente in resultado.no_resueltos
        ),
        facturas_no_resueltas=resultado.facturas_no_resueltas,
        pesos_no_resueltos=resultado.pesos_no_resueltos,
        kilos_no_resueltos=resultado.kilos_no_resueltos,
        kilos_excluidos=kilos_excluidos,
        lineas_kilos_excluidos=tuple(
            LineaKilosExcluidosDTO(
                pedido=sospechosa.linea.pedido,
                codigo_cliente=sospechosa.linea.codigo_cliente,
                nombre_cliente=sospechosa.linea.nombre_cliente,
                producto=sospechosa.linea.producto,
                cod_producto=sospechosa.linea.cod_producto,
                cantidad=sospechosa.linea.cantidad,
                kilos=sospechosa.linea.kilos,
                motivo=sospechosa.descripcion,
            )
            for sospechosa in kilos_sospechosos
        ),
        pedidos_excluidos_por_fecha=len(pedidos_excluidos),
        fechas_excluidas=tuple(fechas_excluidas),
        facturas=tuple(
            FacturaDTO(
                pedido=factura.pedido,
                codigo_cliente=factura.codigo_cliente,
                zona=factura.zona.nombre if factura.zona else None,
                total=factura.total,
                kilos=factura.kilos,
                fecha=factura.fecha,
                nombre_cliente=factura.nombre_cliente,
                ciudad=factura.ciudad,
                barrio=factura.barrio,
                direccion=factura.direccion,
                asesor=factura.asesor,
            )
            for factura in resultado.facturas
        ),
    )
