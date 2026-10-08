"""Detecta las líneas de ECOM con kilos imposibles, antes de que decidan el reparto.

ECOM trae productos con el peso mal cargado en la ficha. El caso que lo destapó:
``CMU. 2 TOSH MIEL GTS FUS``, 18 líneas de $17.279 a **715,5 kg la unidad**. Con
eso, los totales de kilos del 5, 6 y 7 de octubre de 2026 dieron 8.863, 20.978 y
17.562 kg contra los 4.000-5.300 de un día normal: un solo producto mal cargado
pesaba más que todo el resto del día junto.

Importa porque los kilos entran a la función de costo del balanceo: sin esta
guarda, una ficha mal cargada decidiría sola el reparto de un municipio entero.

Qué hace y qué NO hace: solo **señala** las líneas y dice por qué. No borra el
pedido —existe, se factura y sus pesos y clientes son reales—, no corrige el peso
(no sabemos cuál es el verdadero) y no decide nada. Quién las usa resuelve qué
hacer: el pivote les pone los kilos en cero y la interfaz las lista para que
alguien avise a quien mantiene las fichas de producto.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from statistics import median

from planeacion.domain.modelo.pedido import LineaPedido

# Una unidad de venta de esta empresa es una caja, una bolsa o un display de
# galletas, café o dulces: 25 kg es generoso como techo y ningún producto sano
# de los archivos de 2026 se acerca. Es el límite absoluto, no una estadística.
KILOS_MAX_POR_UNIDAD = Decimal("25")

# El segundo criterio es relativo y atrapa lo que el techo no ve: una línea 10
# veces más pesada que lo normal PARA ESE MISMO producto. Pide al menos tres
# apariciones para que la mediana signifique algo.
FACTOR_SOBRE_MEDIANA = Decimal("10")
MINIMO_APARICIONES = 3


class MotivoKilosSospechosos(Enum):
    """Por qué se marcó la línea. Va al aviso de la interfaz, así que se lee."""

    SOBRE_EL_MAXIMO = "kilos por unidad sobre el máximo"
    LEJOS_DE_SU_PRODUCTO = "muy por encima de lo normal en ese producto"


@dataclass(frozen=True)
class LineaSospechosa:
    """Una línea marcada, con lo que hace falta para mostrarla y rastrearla."""

    indice: int  # posición en el archivo: con eso se le ponen los kilos en cero
    linea: LineaPedido
    kilos_por_unidad: Decimal
    motivo: MotivoKilosSospechosos
    referencia: Decimal  # el máximo o la mediana del producto, según el motivo

    @property
    def descripcion(self) -> str:
        return (
            f"{self.kilos_por_unidad:,.1f} kg/unidad — {self.motivo.value} "
            f"(referencia {self.referencia:,.1f} kg)"
        )


def kilos_por_unidad(linea: LineaPedido) -> Decimal:
    """Kilos de la línea divididos por su cantidad.

    Sin cantidad (o en cero) se toma la línea como una unidad: así se mide, que
    es lo que el archivo quiere decir cuando deja la columna vacía, y no se
    pierde de vista una línea por un dato faltante.
    """
    if linea.cantidad is None or linea.cantidad <= 0:
        return linea.kilos
    return linea.kilos / linea.cantidad


def _clave_producto(linea: LineaPedido) -> str | None:
    """El código del producto, o su nombre si el archivo no trae el código."""
    return linea.cod_producto or linea.producto


def detectar_kilos_sospechosos(
    lineas: Sequence[LineaPedido],
    maximo_por_unidad: Decimal = KILOS_MAX_POR_UNIDAD,
    factor_sobre_mediana: Decimal = FACTOR_SOBRE_MEDIANA,
) -> list[LineaSospechosa]:
    """Las líneas con kilos imposibles, por las dos reglas, en el orden del archivo.

    La mediana se calcula **dentro del archivo** y por producto: no hace falta un
    catálogo de pesos y el criterio se adapta a lo que ese día trae. Una línea
    que cae por las dos reglas se reporta una vez, con el techo como motivo,
    porque es el más concreto para explicarle el aviso a alguien.
    """
    medianas = _medianas_por_producto(lineas, maximo_por_unidad)

    sospechosas: list[LineaSospechosa] = []
    for indice, linea in enumerate(lineas):
        por_unidad = kilos_por_unidad(linea)
        if por_unidad > maximo_por_unidad:
            sospechosas.append(
                LineaSospechosa(
                    indice=indice,
                    linea=linea,
                    kilos_por_unidad=por_unidad,
                    motivo=MotivoKilosSospechosos.SOBRE_EL_MAXIMO,
                    referencia=maximo_por_unidad,
                )
            )
            continue
        mediana = medianas.get(_clave_producto(linea))
        if mediana is not None and mediana > 0 and por_unidad > mediana * factor_sobre_mediana:
            sospechosas.append(
                LineaSospechosa(
                    indice=indice,
                    linea=linea,
                    kilos_por_unidad=por_unidad,
                    motivo=MotivoKilosSospechosos.LEJOS_DE_SU_PRODUCTO,
                    referencia=mediana,
                )
            )
    return sospechosas


def _medianas_por_producto(
    lineas: Sequence[LineaPedido], maximo_por_unidad: Decimal
) -> dict[str | None, Decimal]:
    """Mediana de kilos por unidad de cada producto con suficientes apariciones.

    Las líneas que ya pasan el techo absoluto no entran al cálculo: si un
    producto está mal cargado en varias líneas —y el caso real son 18—, incluirlas
    correría la mediana hasta volverla inútil justo donde más hace falta.
    """
    valores: dict[str | None, list[Decimal]] = {}
    for linea in lineas:
        por_unidad = kilos_por_unidad(linea)
        if por_unidad > maximo_por_unidad:
            continue
        valores.setdefault(_clave_producto(linea), []).append(por_unidad)
    return {
        clave: median(muestras)
        for clave, muestras in valores.items()
        if clave is not None and len(muestras) >= MINIMO_APARICIONES
    }


def sin_kilos_sospechosos(
    lineas: Sequence[LineaPedido], sospechosas: Sequence[LineaSospechosa]
) -> list[LineaPedido]:
    """Las mismas líneas con los kilos de las sospechosas en cero.

    En cero y no afuera: la factura, el cliente y la plata del pedido son
    reales y tienen que seguir contando en el pivote y en el reparto. Lo único
    que no se puede creer es el peso.
    """
    marcadas = {sospechosa.indice for sospechosa in sospechosas}
    if not marcadas:
        return list(lineas)
    return [
        (replace(linea, kilos=Decimal("0")) if indice in marcadas else linea)
        for indice, linea in enumerate(lineas)
    ]
