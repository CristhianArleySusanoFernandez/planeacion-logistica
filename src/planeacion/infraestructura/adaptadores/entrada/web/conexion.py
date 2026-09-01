"""Un solo lugar para traducir «no llegué a la base de datos» a algo que Rudy pueda leer.

El proyecto de Supabase está en el plan gratuito y se pausa solo tras varios días sin
uso. Cuando eso pasa, cualquier repositorio revienta con un error de red que Streamlit
muestra como un traceback ilegible. Acá lo atrapamos una vez, arriba de todo, y lo
cambiamos por instrucciones concretas.

Ojo con el alcance: solo errores de transporte (no llegué al servidor). Un error de
datos —una regla de negocio violada, un archivo mal formado, una respuesta 4xx de
PostgREST— NO pasa por acá y sigue mostrando su mensaje propio como siempre.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import streamlit as st

_logger = logging.getLogger(__name__)

MENSAJE = """### No se pudo conectar con la base de datos.

Esto suele pasar cuando el proyecto de Supabase estuvo varios días sin uso y se
puso en pausa automáticamente. Para solucionarlo:

1. Entrá a supabase.com con la cuenta de la empresa.
2. Abrí el proyecto de Planeación Logística.
3. Si aparece pausado, hacé clic en "Restore" o "Resume".
4. Esperá 1-2 minutos y volvé a cargar esta página.

Si el proyecto ya está activo y este mensaje sigue apareciendo, contactá al
encargado del sistema."""


@contextmanager
def errores_de_conexion(*, detener: bool = True) -> Iterator[None]:
    """Muestra el mensaje amigable si adentro se cae la conexión.

    Capturamos ``httpx.TransportError`` y no ``ConnectError`` a secas porque es la base
    común de todas las formas en que se manifiesta un servidor inalcanzable
    (``ConnectError``, ``ConnectTimeout``, ``ReadTimeout``, ``RemoteProtocolError``), y
    aun así sigue significando estrictamente «no hubo respuesta».

    ``detener=False`` es para los callbacks de Streamlit (``on_click`` / ``on_change``),
    donde ``st.stop()`` no corresponde: ahí basta con avisar y dejar que el render siga.
    """
    try:
        yield
    except httpx.TransportError:
        # El traceback queda en los logs del servidor para quien tenga que depurar.
        _logger.exception("Sin conexión con Supabase")
        st.error(MENSAJE)
        if detener:
            st.stop()
