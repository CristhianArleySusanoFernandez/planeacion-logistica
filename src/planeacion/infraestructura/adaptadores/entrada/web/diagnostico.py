"""Comprueba al arrancar que las tablas que la app espera estén en la base.

Por qué hace falta un aviso aparte: dos repositorios **toleran** que su tabla no
exista y devuelven vacío a propósito, para que la app funcione sobre una base a
medio migrar (`parametros` desde la migración 005 y `carro_zonas` desde la 002).
Eso es lo correcto —no queremos que la app muera por una migración pendiente—,
pero tiene un costo: sin este aviso, el panel de error **nunca** se mostraría
para esas dos y el síntoma sería silencioso. El de `carro_zonas` es grave: sin
repertorio el balanceador reparte como si cualquier carro pudiera atender
cualquier zona del municipio.

El aviso no bloquea: es un `st.warning` y la app sigue. Las tablas que **no**
toleran faltar siguen cayendo en el panel de error de siempre.
"""

import logging

import streamlit as st
from postgrest.exceptions import APIError

from planeacion.config.contenedor import crear_cliente_supabase
from planeacion.config.settings import Settings
from planeacion.infraestructura.adaptadores.entrada.web.errores import migracion_de

_logger = logging.getLogger(__name__)

# Códigos con que Postgres y PostgREST dicen "esa tabla no existe".
_TABLA_INEXISTENTE = ("42P01", "PGRST205")

# Qué pasa mientras la tabla no esté. Las dos primeras son las tolerantes; el
# resto están para detectar una base a medio sembrar antes de que el usuario se
# choque con el error en medio de una planeación.
CONSECUENCIAS: dict[str, str] = {
    "carro_zonas": (
        "**el reparto va a salir mal**: sin repertorio, el balanceador asume que cualquier carro "
        "puede atender cualquier zona de su municipio"
    ),
    "parametros": "se usan los valores por defecto del programa (el reparto sigue siendo correcto)",
    "municipios": "no hay pools de carros: el reparto no va a poder correr",
    "zonas": "no se puede resolver la zona de ningún cliente",
    "carros": "no hay flota entre la que repartir",
    "clientes": "todos los clientes del día van a quedar como no resueltos",
    "correcciones_ubicacion": "no se corrigen las ciudades que ECOM trae mal",
    "overrides_zona": "no se aplican las zonas forzadas a mano",
    "planeaciones": "no hay histórico: el reparto arranca desde cero todos los días",
}

_TTL_SEGUNDOS = 300


@st.cache_data(ttl=_TTL_SEGUNDOS, show_spinner=False)
def tablas_faltantes() -> list[str]:
    """Las tablas conocidas que la base no tiene, consultando una fila de cada una.

    Cacheado: son nueve consultas y la respuesta no cambia entre clics. Si la
    base no responde, devuelve lista vacía y deja que el fallo lo cuente el panel
    de error, que para eso está: este diagnóstico no es el lugar para avisar que
    no hay conexión.
    """
    try:
        cliente = crear_cliente_supabase(Settings())
    except Exception:  # noqa: BLE001 — sin credenciales no hay diagnóstico que hacer
        return []

    faltantes: list[str] = []
    for tabla in CONSECUENCIAS:
        try:
            cliente.table(tabla).select("*").limit(1).execute()
        except APIError as error:
            if error.code in _TABLA_INEXISTENTE:
                faltantes.append(tabla)
        except Exception:  # noqa: BLE001 — cualquier otro fallo no es asunto de acá
            return []
    return faltantes


def mostrar_aviso() -> None:
    """Un `st.warning` con las tablas que faltan, su migración y qué pasa mientras."""
    faltantes = tablas_faltantes()
    if not faltantes:
        return
    _logger.warning("[BD_MIGRACION_FALTANTE] tablas ausentes: %s", ", ".join(faltantes))

    lineas = [
        "**Falta aplicar actualizaciones en la base de datos.** La aplicación funciona, "
        "pero con limitaciones:",
        "",
    ]
    for tabla in faltantes:
        numero = migracion_de(tabla)
        migracion = f"migración {numero}" if numero else "una migración pendiente"
        lineas.append(f"- `{tabla}` ({migracion}): {CONSECUENCIAS[tabla]}.")
    lineas.append("")
    lineas.append("Avise a quien administra la aplicación para que las aplique.")
    st.warning("\n".join(lineas))
