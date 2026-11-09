"""Alertas operativas: lo que la jefatura quiere mirar, sin tocar el reparto.

Las tres salen de pedidos del responsable de planeación, y las tres son **metas,
no reglas**. Eso no es un detalle de implementación, es lo que los datos dicen:

- *Mínimo de 50 clientes por conductor* en Tunja, Barbosa y Chiquinquirá. En los
  16 archivos de septiembre y octubre de 2026 la operación lo incumple **19
  veces** (Wilmar, José Jiménez, Jairo Garzón…). Si fuera una restricción dura,
  el balanceador tendría que rechazar repartos que la operación hace todas las
  semanas.
- *Carro externo con más de 110 pedidos*. Fabián y Angélica Arias pasan de 110
  facturas casi todos los días y nunca se llamó un externo.
- *Promedio por vehículo* = facturas del día ÷ 12 (el divisor fijo de la hoja de
  Julián). Osciló entre 91,8 y 112,5 sin que nunca se prendiera un externo.

Por eso acá no hay nada que restrinja: estas funciones **miran** un reparto ya
hecho y devuelven avisos para mostrar. Quien decide sigue siendo la persona.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from planeacion.domain.modelo import CargaCarro
from planeacion.domain.modelo.carro import clave_orden_carro
from planeacion.domain.servicios.agrupacion_por_conductor import (
    CargaConductor,
    agrupar_por_conductor,
    cargas_por_conductor,
)

# Los tres umbrales, configurables en la tabla de parámetros. Los defaults son
# los números que pidió la jefatura, no un cálculo nuestro.
MIN_CLIENTES_CONDUCTOR = 50
MAX_FACTURAS_CONDUCTOR = 110
VEHICULOS_REFERENCIA = 12
# Cuánto puede superar la planilla más cargada a la menos cargada del mismo camión
# antes de avisar, como fracción de la menor: 0,75 = 75 %. Calibrado sobre los 7
# días reales del 20 al 27 de octubre de 2026 (ver dominio.md, «Planillas»).
DESBALANCE_PLANILLAS = Decimal("0.75")

# El mínimo de clientes aplica solo a los municipios con reparto urbano. Las
# rutas viajeras (pool OTROS) hacen pocos clientes y mucho kilómetro por
# naturaleza: medirlas con la misma vara sería ruido permanente.
MUNICIPIOS_CON_MINIMO_DE_CLIENTES = ("TUNJA", "BARBOSA", "CHIQUINQUIRA")


class TipoAlerta(Enum):
    POCOS_CLIENTES = "pocos clientes"
    MUCHAS_FACTURAS = "muchas facturas"
    PROMEDIO_POR_VEHICULO = "promedio por vehículo"
    PLANILLAS_DESPAREJAS = "planillas desparejas"


@dataclass(frozen=True)
class Alerta:
    """Un aviso para mostrar. ``conductor`` es None en las alertas del día entero."""

    tipo: TipoAlerta
    texto: str
    valor: int
    umbral: int
    conductor: str | None = None

    @property
    def texto_corto(self) -> str:
        """Para la columna del Excel, donde no cabe la frase entera."""
        return f"{self.tipo.value}: {self.valor}"


def alertas_de_conductores(
    cargas_por_municipio: Mapping[str, Sequence[CargaCarro]],
    min_clientes: int = MIN_CLIENTES_CONDUCTOR,
    max_facturas: int = MAX_FACTURAS_CONDUCTOR,
) -> list[Alerta]:
    """Avisos por conductor: pocos clientes o demasiadas facturas.

    Se suma por conductor y no por ruta porque es la persona la que hace el día:
    dos rutas de 30 clientes no son dos problemas, son un conductor con 60.
    """
    alertas: list[Alerta] = []
    for grupo in _conductores(cargas_por_municipio):
        if _tiene_minimo_de_clientes(grupo) and grupo.clientes < min_clientes:
            alertas.append(
                Alerta(
                    tipo=TipoAlerta.POCOS_CLIENTES,
                    texto=(
                        f"{grupo.conductor} lleva {grupo.clientes} clientes, por debajo "
                        f"de los {min_clientes} de la meta"
                    ),
                    valor=grupo.clientes,
                    umbral=min_clientes,
                    conductor=grupo.conductor,
                )
            )
        if grupo.facturas > max_facturas:
            alertas.append(
                Alerta(
                    tipo=TipoAlerta.MUCHAS_FACTURAS,
                    texto=(
                        f"{grupo.conductor} lleva {grupo.facturas} facturas, por encima de {max_facturas}"
                    ),
                    valor=grupo.facturas,
                    umbral=max_facturas,
                    conductor=grupo.conductor,
                )
            )
    return alertas


# Las dos variables en que se comparan las planillas: etiqueta, cómo medirla en
# una carga y cómo escribir el valor. Clientes NO entra: en los 7 días medidos la
# operación reparte las mitades por carga, no por paradas, y hay planillas con el
# doble de clientes que su pareja con los pesos parejos.
_VARIABLES_DE_PLANILLA: tuple[tuple[str, Callable[[CargaCarro], Decimal], str], ...] = (
    ("pesos", lambda carga: carga.pesos, "$"),
    ("kilos", lambda carga: carga.kilos, " kg"),
)


def alertas_de_planillas(
    cargas_por_municipio: Mapping[str, Sequence[CargaCarro]],
    desbalance: Decimal = DESBALANCE_PLANILLAS,
) -> list[Alerta]:
    """Avisa cuando las planillas de un mismo camión salen desparejas.

    Cinco conductores llevan dos planillas (Fabián 1 y 2, Angélica Arias 1 y 2,
    Raúl 1 y 2, Carlos 1 y 2, Javier Reyes 14 y 15) y la operación partió zonas en
    dos justamente para que las dos lleguen parejas a bodega. El balanceador
    reparte por ruta y no sabe que dos rutas comparten camión, así que puede
    dejar una planilla con 310 kg y la otra con 160 sin que ninguna métrica se
    entere: por municipio el CV no lo ve, y por conductor la suma lo esconde.

    Se compara la mayor contra la menor en pesos **o** kilos: basta que una se
    pase. Los clientes no se comparan: un cliente es una parada, no una carga. Una
    planilla vacía frente a otra con carga siempre avisa. Las planillas se nombran
    por **número de ruta** y no por el sufijo del conductor, porque Javier Reyes
    lleva la 14 y la 15 sin ningún "1" ni "2" en el nombre.
    Es una meta, no una regla: el reparto no cambia.
    """
    alertas: list[Alerta] = []
    todas = [carga for cargas in cargas_por_municipio.values() for carga in cargas]
    for conductor, planillas in cargas_por_conductor(todas).items():
        if len(planillas) < 2:
            continue
        detalles: list[str] = []
        peor_exceso = Decimal("0")
        for etiqueta, medir, unidad in _VARIABLES_DE_PLANILLA:
            mayor = max(planillas, key=medir)
            menor = min(planillas, key=medir)
            valor_mayor, valor_menor = medir(mayor), medir(menor)
            if valor_mayor <= 0:
                continue  # las dos vacías en esta variable: nada que comparar
            if valor_mayor <= valor_menor * (1 + desbalance):
                continue  # en el umbral exacto todavía no avisa: tiene que superarlo
            exceso = (valor_mayor - valor_menor) / valor_menor if valor_menor > 0 else Decimal("Infinity")
            peor_exceso = max(peor_exceso, exceso)
            detalles.append(
                f"en {etiqueta} la ruta {mayor.carro.numero} lleva {_formatear(valor_mayor, unidad)} "
                f"y la {menor.carro.numero} lleva {_formatear(valor_menor, unidad)}"
            )
        if not detalles:
            continue
        rutas = ", ".join(sorted((c.carro.numero for c in planillas), key=clave_orden_carro))
        alertas.append(
            Alerta(
                tipo=TipoAlerta.PLANILLAS_DESPAREJAS,
                texto=f"Planillas de {conductor} desparejas (rutas {rutas}): " + "; ".join(detalles),
                valor=_porcentaje(peor_exceso),
                umbral=int(desbalance * 100),
                conductor=conductor,
            )
        )
    return alertas


def _formatear(valor: Decimal, unidad: str) -> str:
    """`$1,234,567`, `310 kg` o `60`, según la variable."""
    if unidad == "$":
        return f"${valor:,.0f}"
    return f"{valor:,.0f}{unidad}"


def _porcentaje(exceso: Decimal) -> int:
    """El exceso como entero de porcentaje; una planilla vacía da un tope legible."""
    if not exceso.is_finite():
        return 999
    return int(exceso * 100)


def alerta_de_promedio_por_vehiculo(
    total_facturas: int,
    vehiculos_referencia: int = VEHICULOS_REFERENCIA,
    max_facturas: int = MAX_FACTURAS_CONDUCTOR,
) -> Alerta | None:
    """El "Promedio Vh" de la hoja de Julián: facturas del día ÷ un divisor FIJO.

    El divisor es un parámetro y no la cantidad de carros con carga a propósito:
    así se calcula en la hoja que la operación mira todos los días, y cambiarlo
    por "los carros que hoy tienen zonas" daría otro número y rompería la
    comparación con lo que ellos ya tienen en la cabeza.
    """
    if vehiculos_referencia <= 0:
        return None
    promedio = total_facturas // vehiculos_referencia
    if promedio <= max_facturas:
        return None
    return Alerta(
        tipo=TipoAlerta.PROMEDIO_POR_VEHICULO,
        texto=f"Promedio por vehículo {promedio}: revisar si hace falta carro externo",
        valor=promedio,
        umbral=max_facturas,
    )


def alertas_por_ruta(alertas: Sequence[Alerta], cargas: Sequence[CargaCarro]) -> dict[str, str]:
    """Número de ruta → texto corto de las alertas de SU conductor, para el Excel.

    Las rutas sin alerta no entran al mapa: la columna queda vacía, que es lo que
    tiene que pasar en un día normal.
    """
    por_conductor: dict[str, list[str]] = {}
    for alerta in alertas:
        if alerta.conductor is not None:
            por_conductor.setdefault(alerta.conductor, []).append(alerta.texto_corto)

    por_ruta: dict[str, str] = {}
    for grupo in agrupar_por_conductor(cargas):
        textos = por_conductor.get(grupo.conductor)
        if textos:
            for numero in grupo.rutas:
                por_ruta[numero] = "; ".join(textos)
    return por_ruta


def _conductores(cargas_por_municipio: Mapping[str, Sequence[CargaCarro]]) -> list[CargaConductor]:
    return agrupar_por_conductor([carga for cargas in cargas_por_municipio.values() for carga in cargas])


def _tiene_minimo_de_clientes(grupo: CargaConductor) -> bool:
    """¿Le aplica la meta de clientes? Sí si alguna de sus rutas es de los tres
    municipios urbanos; un conductor que solo hace viajeras queda fuera."""
    return any(municipio in MUNICIPIOS_CON_MINIMO_DE_CLIENTES for municipio in grupo.municipios)


def nota_de_clientes_especiales(carga: CargaCarro) -> str | None:
    """Los clientes especiales que lleva esta ruta, para la columna Alerta.

    No es una alerta de umbral como las demás: es un aviso de composición. La app
    eligió el vehículo por la carga del día, no por costumbre —un cliente especial
    no tiene carro habitual—, así que quien despacha tiene que confirmar que ese
    camión sirve para ese cliente: horario de recepción, tamaño, acceso.
    """
    nombres = sorted(zona.zona.nombre for zona in carga.zonas if zona.zona.especial)
    if not nombres:
        return None
    return f"Cliente especial ({', '.join(nombres)}): verifique el vehículo"
