"""Un solo lugar para traducir los fallos previsibles a algo que se pueda resolver.

Envuelve el render y, si adentro salta algo que ``errores.clasificar`` reconoce,
muestra el panel con instrucciones en vez del traceback de Streamlit. Nació para
el caso de la base pausada —el proyecto de Supabase en el plan gratuito se pausa
tras varios días sin uso— y hoy cubre además las credenciales rechazadas, las
migraciones sin aplicar y los archivos que no son el informe de ECOM.

El alcance es deliberado y angosto: **lo que no se reconoce se propaga**. No hay
un ``except Exception`` que muestre "ocurrió un error" para todo, porque eso
esconderia los bugs de verdad en lugar de arreglarlos.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import streamlit as st
from pydantic import ValidationError

from planeacion.config.settings import Settings
from planeacion.infraestructura.adaptadores.entrada.web import panel_error
from planeacion.infraestructura.adaptadores.entrada.web.errores import clasificar

_logger = logging.getLogger(__name__)


def _url_de_supabase() -> str | None:
    """La URL configurada, si se puede leer.

    Si faltan las credenciales no hay nada que derivar: el panel va sin enlace, y
    ese caso lo trata ``app.py`` con su propio mensaje antes de llegar acá.
    """
    try:
        return Settings().supabase_url
    except ValidationError:
        return None


@contextmanager
def errores_de_conexion(*, detener: bool = True, clave: str = "") -> Iterator[None]:
    """Muestra el panel si adentro falla algo previsible; si no, deja pasar.

    ``detener=False`` es para los callbacks de Streamlit (``on_click`` /
    ``on_change``), donde ``st.stop()`` no corresponde: ahí basta con avisar y
    dejar que el render siga.
    """
    try:
        yield
    except Exception as excepcion:
        error = clasificar(excepcion, _url_de_supabase())
        if error is None:
            raise
        # El traceback completo queda en los logs del servidor, con el código
        # adelante para poder filtrar por él en el panel de Render.
        _logger.exception("[%s] %s", error.codigo, error.titulo)
        panel_error.mostrar(error, clave=clave)
        if detener:
            st.stop()
