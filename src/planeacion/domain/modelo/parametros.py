"""Los números del negocio que se pueden mover sin tocar código.

Acá vive el **catálogo**: qué parámetros hay, cuánto valen por defecto y qué hace
cada uno. La tabla `parametros` de la base guarda solo los valores cambiados; si
está vacía, le falta una clave o alguien borró una fila, manda el default de este
módulo. Esa asimetría es deliberada: la app tiene que funcionar en una base sin
migrar, y una fila borrada por error no puede convertirse en un cero silencioso
que apague el equilibrio por clientes.

El dominio es la fuente de verdad del catálogo; la migración 005 repite las
descripciones en la tabla solo para que se entienda abriéndola en Supabase.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from planeacion.domain.modelo.balanceo import (
    OBSERVACIONES_PARA_FIJAR,
    REGLAS_POR_DEFECTO,
    UMBRAL_CV_ACEPTABLE,
    UMBRAL_CV_ATENCION,
    ReglasBalanceo,
    UmbralesDesbalance,
)

CLAVE_W_CLIENTES = "w_clientes"
CLAVE_W_PESOS = "w_pesos"
CLAVE_W_KILOS = "w_kilos"
CLAVE_W_FRECUENCIA = "w_frecuencia"
CLAVE_MIN_CLIENTES_CONDUCTOR = "min_clientes_conductor"
CLAVE_MAX_FACTURAS_CONDUCTOR = "max_facturas_conductor"
CLAVE_VEHICULOS_REFERENCIA = "vehiculos_referencia"
CLAVE_KILOS_MAX_POR_UNIDAD = "kilos_max_por_unidad"
CLAVE_UMBRAL_CV_ACEPTABLE = "umbral_cv_aceptable"
CLAVE_UMBRAL_CV_ATENCION = "umbral_cv_atencion"
CLAVE_DESBALANCE_PLANILLAS = "desbalance_planillas"
CLAVE_OBSERVACIONES_PARA_FIJAR = "observaciones_para_fijar"


@dataclass(frozen=True)
class DefinicionParametro:
    """Un parámetro del catálogo: su clave, su default y para qué sirve."""

    clave: str
    valor_por_defecto: Decimal
    descripcion: str


CATALOGO: tuple[DefinicionParametro, ...] = (
    DefinicionParametro(
        CLAVE_W_CLIENTES,
        Decimal(str(REGLAS_POR_DEFECTO.w_clientes)),
        "Cuánto pesa igualar la cantidad de clientes entre carros (0 lo apaga).",
    ),
    DefinicionParametro(
        CLAVE_W_PESOS,
        Decimal(str(REGLAS_POR_DEFECTO.w_pesos)),
        "Cuánto pesa igualar la plata entre carros (0 lo apaga).",
    ),
    DefinicionParametro(
        CLAVE_W_KILOS,
        Decimal(str(REGLAS_POR_DEFECTO.w_kilos)),
        "Cuánto pesa igualar los kilos entre carros, que es lo que hay que cargar y descargar.",
    ),
    DefinicionParametro(
        CLAVE_W_FRECUENCIA,
        Decimal(str(REGLAS_POR_DEFECTO.w_frecuencia)),
        "Cuánto pesa la costumbre: entre carros que pueden atender la zona, prefiere al que la "
        "viene atendiendo ese día. Bajo a propósito: rompe empates, no sobrecarga.",
    ),
    DefinicionParametro(
        CLAVE_MIN_CLIENTES_CONDUCTOR,
        Decimal("50"),
        "Meta de clientes por conductor en Tunja, Barbosa y Chiquinquirá. Solo avisa: el reparto "
        "no se modifica por esta alerta.",
    ),
    DefinicionParametro(
        CLAVE_MAX_FACTURAS_CONDUCTOR,
        Decimal("110"),
        "Facturas por conductor desde las que conviene revisar si hace falta carro externo. Solo avisa.",
    ),
    DefinicionParametro(
        CLAVE_VEHICULOS_REFERENCIA,
        Decimal("12"),
        'Divisor del "Promedio Vh" (facturas del día ÷ vehículos), el mismo en la alerta del '
        "Paso 3 y en la fila 2 del Excel. 0 = automático: camiones activos (claves de conductor "
        "distintas de las rutas activas). 12 es el valor con el que está calibrada la regla de "
        "80–110 pedidos por vehículo de la operación: si cambia, hay que recalibrar "
        "max_facturas_conductor con Julián.",
    ),
    DefinicionParametro(
        CLAVE_UMBRAL_CV_ACEPTABLE,
        Decimal(str(UMBRAL_CV_ACEPTABLE)),
        "Hasta este CV el reparto se ve verde en el semáforo. Los 0,10 de julio de 2026 dejaban "
        "los cuatro municipios en rojo todos los días: el reparto real mide 25 a 46 %.",
    ),
    DefinicionParametro(
        CLAVE_UMBRAL_CV_ATENCION,
        Decimal(str(UMBRAL_CV_ATENCION)),
        "Hasta este CV el semáforo va en ámbar; por encima, rojo. Solo cambia el color: el "
        "reparto propuesto es el mismo.",
    ),
    DefinicionParametro(
        CLAVE_DESBALANCE_PLANILLAS,
        Decimal("0.75"),
        "Diferencia desde la que dos planillas del mismo camión se consideran desparejas, como "
        "fracción de la menor (0,75 = 75 %). Se compara en pesos y kilos, no en clientes. Solo "
        "avisa: el reparto no cambia.",
    ),
    DefinicionParametro(
        CLAVE_OBSERVACIONES_PARA_FIJAR,
        Decimal(str(OBSERVACIONES_PARA_FIJAR)),
        "Cuántas veces hay que haber visto a la única ruta de una zona ese día para que salga "
        "fija (candado) en el Paso 3. Por debajo sale «sugerida» y se puede mover a cualquier ruta "
        "del municipio. Con 1 vuelve al comportamiento anterior. Frecuencia 0 («este carro no») "
        "fija siempre. No cambia el reparto automático.",
    ),
    DefinicionParametro(
        CLAVE_KILOS_MAX_POR_UNIDAD,
        Decimal("25"),
        "Kilos por unidad desde los que una línea de ECOM se considera mal cargada y sus kilos "
        "no entran al reparto. Hay fichas con 715,5 kg la unidad.",
    ),
)

# Inmutable a propósito: es el default de un dataclass y lo lee todo el sistema;
# un mapa mutable compartido sería una fuente de sorpresas.
DEFECTOS: Mapping[str, Decimal] = MappingProxyType(
    {definicion.clave: definicion.valor_por_defecto for definicion in CATALOGO}
)


@dataclass(frozen=True)
class Parametros:
    """Los valores vigentes, con el default del catálogo como red.

    Se construye con lo que haya en la base —puede ser nada— y resuelve cada
    lectura contra el catálogo, así que nunca devuelve un valor sin sentido.
    """

    valores: Mapping[str, Decimal] = DEFECTOS

    def numero(self, clave: str) -> Decimal:
        valor = self.valores.get(clave)
        return valor if valor is not None else DEFECTOS[clave]

    def entero(self, clave: str) -> int:
        return int(self.numero(clave))

    def flotante(self, clave: str) -> float:
        return float(self.numero(clave))

    def umbrales_desbalance(self) -> UmbralesDesbalance:
        """Los dos cortes del semáforo, como estén configurados."""
        return UmbralesDesbalance(
            aceptable=self.flotante(CLAVE_UMBRAL_CV_ACEPTABLE),
            atencion=self.flotante(CLAVE_UMBRAL_CV_ATENCION),
        )

    def reglas_balanceo(self) -> ReglasBalanceo:
        """Los cuatro pesos de la función de costo, tal como están configurados."""
        return ReglasBalanceo(
            w_clientes=self.flotante(CLAVE_W_CLIENTES),
            w_pesos=self.flotante(CLAVE_W_PESOS),
            w_kilos=self.flotante(CLAVE_W_KILOS),
            w_frecuencia=self.flotante(CLAVE_W_FRECUENCIA),
        )
