"""Pruebas de la guarda de kilos: qué línea se marca y qué pasa con el pedido.

El caso que la motivó es real: ``CMU. 2 TOSH MIEL GTS FUS``, 18 líneas de $17.279
a 715,5 kg la unidad, que llevaron el total del 6 de octubre de 2026 a 20.978 kg
contra los ~4.600 que tiene ese día sin ellas.
"""

from decimal import Decimal

from planeacion.domain.modelo import LineaPedido
from planeacion.domain.servicios.guarda_kilos import (
    MotivoKilosSospechosos,
    detectar_kilos_sospechosos,
    kilos_por_unidad,
    sin_kilos_sospechosos,
)


def _linea(
    kilos: str,
    cantidad: str | None = "1",
    cod_producto: str = "1027117",
    pedido: str = "6004793",
) -> LineaPedido:
    return LineaPedido(
        pedido=pedido,
        codigo_cliente="200001651668",
        fecha=None,
        total_linea=Decimal("17279"),
        kilos=Decimal(kilos),
        producto="PRODUCTO",
        cod_producto=cod_producto,
        cantidad=Decimal(cantidad) if cantidad is not None else None,
    )


class TestDeteccion:
    def test_una_linea_normal_no_se_marca(self) -> None:
        assert detectar_kilos_sospechosos([_linea("0.6"), _linea("12.5")]) == []

    def test_la_linea_de_715_kilos_por_unidad_cae(self) -> None:
        sospechosas = detectar_kilos_sospechosos([_linea("715.5")])

        assert len(sospechosas) == 1
        assert sospechosas[0].motivo is MotivoKilosSospechosos.SOBRE_EL_MAXIMO
        assert sospechosas[0].kilos_por_unidad == Decimal("715.5")

    def test_la_cantidad_divide_antes_de_comparar(self) -> None:
        """La misma ficha mal cargada con cantidad 2 son 1.431 kg: sigue siendo
        715,5 por unidad, y 30 kg repartidos en 2 unidades no son sospechosos."""
        sospechosas = detectar_kilos_sospechosos([_linea("1431", cantidad="2"), _linea("30", cantidad="2")])

        assert [s.kilos_por_unidad for s in sospechosas] == [Decimal("715.5")]

    def test_sin_cantidad_la_linea_cuenta_como_una_unidad(self) -> None:
        """Columna vacía: no se pierde de vista la línea por un dato faltante."""
        assert kilos_por_unidad(_linea("40", cantidad=None)) == Decimal("40")
        assert len(detectar_kilos_sospechosos([_linea("40", cantidad=None)])) == 1

    def test_una_linea_diez_veces_su_producto_cae_aunque_no_llegue_al_maximo(self) -> None:
        """El criterio relativo: 15 kg no pasan el techo de 25, pero son 15 veces
        lo que pesa ese mismo producto en las otras cuatro líneas del archivo."""
        normales = [_linea("1") for _ in range(4)]

        sospechosas = detectar_kilos_sospechosos([*normales, _linea("15")])

        assert len(sospechosas) == 1
        assert sospechosas[0].motivo is MotivoKilosSospechosos.LEJOS_DE_SU_PRODUCTO
        assert sospechosas[0].referencia == Decimal("1")

    def test_con_pocas_apariciones_no_hay_mediana_que_comparar(self) -> None:
        """Dos líneas del mismo producto no hacen una referencia: sin el techo
        absoluto, marcar ahí seria adivinar."""
        assert detectar_kilos_sospechosos([_linea("1"), _linea("15")]) == []

    def test_las_lineas_mal_cargadas_no_corren_la_mediana_de_su_producto(self) -> None:
        """El caso real son 18 líneas malas del mismo producto: si entraran al
        cálculo, la mediana se volveria inutil justo donde hace falta."""
        malas = [_linea("715.5") for _ in range(18)]
        buenas = [_linea("0.6") for _ in range(3)]

        sospechosas = detectar_kilos_sospechosos([*malas, *buenas])

        assert len(sospechosas) == 18
        assert all(s.motivo is MotivoKilosSospechosos.SOBRE_EL_MAXIMO for s in sospechosas)

    def test_productos_distintos_no_se_mezclan(self) -> None:
        """La mediana es por Cod.Prod: un producto liviano no vuelve sospechoso a
        uno pesado que de por si pesa mas."""
        livianos = [_linea("0.5", cod_producto="A") for _ in range(3)]
        pesados = [_linea("20", cod_producto="B") for _ in range(3)]

        assert detectar_kilos_sospechosos([*livianos, *pesados]) == []

    def test_el_maximo_es_parametrizable(self) -> None:
        lineas = [_linea("12.5")]

        assert detectar_kilos_sospechosos(lineas) == []
        assert len(detectar_kilos_sospechosos(lineas, maximo_por_unidad=Decimal("10"))) == 1


class TestTratamiento:
    def test_el_pedido_sobrevive_sin_sus_kilos(self) -> None:
        """Lo unico que no se puede creer es el peso: la factura, el cliente y la
        plata son reales y tienen que seguir contando."""
        lineas = [_linea("0.6"), _linea("715.5")]

        limpias = sin_kilos_sospechosos(lineas, detectar_kilos_sospechosos(lineas))

        assert [linea.kilos for linea in limpias] == [Decimal("0.6"), Decimal("0")]
        assert [linea.total_linea for linea in limpias] == [Decimal("17279"), Decimal("17279")]
        assert [linea.pedido for linea in limpias] == ["6004793", "6004793"]

    def test_un_archivo_sano_vuelve_intacto(self) -> None:
        lineas = [_linea("0.6"), _linea("1.2")]

        assert sin_kilos_sospechosos(lineas, []) == lineas

    def test_los_kilos_excluidos_son_los_de_las_lineas_marcadas(self) -> None:
        lineas = [_linea("0.6"), _linea("715.5"), _linea("1431", cantidad="2")]

        sospechosas = detectar_kilos_sospechosos(lineas)

        assert sum(s.linea.kilos for s in sospechosas) == Decimal("2146.5")
