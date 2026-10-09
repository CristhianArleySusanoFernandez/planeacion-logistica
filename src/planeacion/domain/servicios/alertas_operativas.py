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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from planeacion.domain.modelo import CargaCarro
from planeacion.domain.servicios.agrupacion_por_conductor import CargaConductor, agrupar_por_conductor

# Los tres umbrales, configurables en la tabla de parámetros. Los defaults son
# los números que pidió la jefatura, no un cálculo nuestro.
MIN_CLIENTES_CONDUCTOR = 50
MAX_FACTURAS_CONDUCTOR = 110
VEHICULOS_REFERENCIA = 12

# El mínimo de clientes aplica solo a los municipios con reparto urbano. Las
# rutas viajeras (pool OTROS) hacen pocos clientes y mucho kilómetro por
# naturaleza: medirlas con la misma vara sería ruido permanente.
MUNICIPIOS_CON_MINIMO_DE_CLIENTES = ("TUNJA", "BARBOSA", "CHIQUINQUIRA")


class TipoAlerta(Enum):
    POCOS_CLIENTES = "pocos clientes"
    MUCHAS_FACTURAS = "muchas facturas"
    PROMEDIO_POR_VEHICULO = "promedio por vehículo"


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
