"""Cronómetro de etapas: mide y registra, no decide nada.

Vive en la raíz del paquete y no en un anillo: lo usan el dominio, los casos de
uso y los adaptadores, y solo depende de la biblioteca estándar (``logging`` ya
se usaba en los casos de uso). Medir no es lógica de negocio ni es un adaptador.

El tiempo sale por ``logging`` en nivel INFO, así que en producción no cuesta
nada y no hay que acordarse de apagarlo. Además va en el ``extra`` del registro,
para que quien mida pueda recoger los números sin parsear el mensaje:

    with medir("balanceo", logger):
        ...

El motivo de existir es la regla del Prompt 21: **medir antes de optimizar**. Sin
esto, "la app se siente lenta" no se puede convertir en una tabla.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

# Claves del `extra` del LogRecord. Quien recoge las mediciones lee estos
# atributos del registro en vez de interpretar el texto del mensaje.
CAMPO_ETAPA = "etapa_medida"
CAMPO_SEGUNDOS = "segundos"


@contextmanager
def medir(etapa: str, logger: logging.Logger) -> Iterator[None]:
    """Mide el bloque y lo registra en INFO, incluso si lanza una excepción.

    Se registra igual cuando falla porque una etapa que tarda y después revienta
    es justo la que hay que ver.
    """
    inicio = perf_counter()
    try:
        yield
    finally:
        transcurrido = perf_counter() - inicio
        logger.info(
            "etapa %s: %.3f s",
            etapa,
            transcurrido,
            extra={CAMPO_ETAPA: etapa, CAMPO_SEGUNDOS: transcurrido},
        )


class RecolectorDeEtapas(logging.Handler):
    """Handler que junta las mediciones de un tramo de ejecución.

    Se instala en la raíz, corre el flujo y después se leen las etapas. Ignora
    cualquier registro que no venga de ``medir``, así que conviven con los logs
    normales de la aplicación.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.etapas: list[tuple[str, float]] = []

    def emit(self, record: logging.LogRecord) -> None:
        etapa = getattr(record, CAMPO_ETAPA, None)
        segundos = getattr(record, CAMPO_SEGUNDOS, None)
        if isinstance(etapa, str) and isinstance(segundos, float):
            self.etapas.append((etapa, segundos))

    def limpiar(self) -> None:
        self.etapas.clear()

    def total(self) -> float:
        return sum(segundos for _, segundos in self.etapas)
