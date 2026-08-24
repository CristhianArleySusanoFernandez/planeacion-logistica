"""Los días de la semana, como los nombra el negocio.

En minúsculas y sin tildes porque así viajan a la base (columna ``dia_semana``
de ``planeaciones`` y de ``carro_zonas``) y así se comparan entre sí.
"""

from datetime import date

# Indexado por date.weekday(): 0 = lunes.
DIAS_SEMANA = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")

# Los días en que se reparte. El domingo existe en DIAS_SEMANA porque una fecha
# puede caer ahí, pero no se configura repertorio para él.
DIAS_LABORALES = DIAS_SEMANA[:6]


def dia_de(fecha: date) -> str:
    """La fecha → el nombre de su día ("lunes"..."domingo")."""
    return DIAS_SEMANA[fecha.weekday()]
