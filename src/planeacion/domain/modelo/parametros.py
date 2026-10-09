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

from planeacion.domain.modelo.balanceo import REGLAS_POR_DEFECTO, ReglasBalanceo

CLAVE_W_CLIENTES = "w_clientes"
CLAVE_W_PESOS = "w_pesos"
CLAVE_W_KILOS = "w_kilos"
CLAVE_W_FRECUENCIA = "w_frecuencia"
CLAVE_MIN_CLIENTES_CONDUCTOR = "min_clientes_conductor"
CLAVE_MAX_FACTURAS_CONDUCTOR = "max_facturas_conductor"
CLAVE_VEHICULOS_REFERENCIA = "vehiculos_referencia"
CLAVE_KILOS_MAX_POR_UNIDAD = "kilos_max_por_unidad"


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
        'Divisor fijo del "Promedio Vh" de la hoja de la empresa. No es la cantidad de carros con '
        "carga: se deja fijo para que el número sea comparable con el que ellos ya miran.",
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

    def reglas_balanceo(self) -> ReglasBalanceo:
        """Los cuatro pesos de la función de costo, tal como están configurados."""
        return ReglasBalanceo(
            w_clientes=self.flotante(CLAVE_W_CLIENTES),
            w_pesos=self.flotante(CLAVE_W_PESOS),
            w_kilos=self.flotante(CLAVE_W_KILOS),
            w_frecuencia=self.flotante(CLAVE_W_FRECUENCIA),
        )
