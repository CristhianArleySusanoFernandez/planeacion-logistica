"""UI Streamlit de la planeación diaria — un adaptador de entrada más.

Toda la lógica vive en los casos de uso; estas páginas solo traducen clics a
llamadas y muestran resultados. Se lanza con:

    uv run streamlit run src/planeacion/infraestructura/adaptadores/entrada/web/app.py
"""

import streamlit as st
from pydantic import ValidationError

from planeacion.application.dto.pivote import PivotePorZonaDTO
from planeacion.config.contenedor import Contenedor, crear_contenedor
from planeacion.config.settings import Settings
from planeacion.infraestructura.adaptadores.entrada.web import (
    conexion,
    configuracion,
    diagnostico,
    estado,
    estilos,
    paso1_cargar,
    paso2_clientes_nuevos,
    paso3_reparto,
    paso4_exportar,
)

st.set_page_config(
    page_title="Distribuciones Santiago — Planeación Logística",
    page_icon="🚚",
    layout="wide",
)
estilos.aplicar_estilos()


@st.cache_resource
def _obtener_contenedor() -> Contenedor:
    """Wiring una sola vez por proceso (los casos de uso se crean por página, son baratos)."""
    return crear_contenedor(Settings())


def _paso_completado(paso: str) -> bool:
    """Qué pasos ya quedaron listos, deducido del estado de la sesión."""
    pivote: PivotePorZonaDTO | None = st.session_state.get(estado.CLAVE_PIVOTE)
    if paso == estado.PASO_CARGAR:
        return pivote is not None
    if paso == estado.PASO_CLIENTES:
        con_planeacion = st.session_state.get(estado.CLAVE_PLANEACION) is not None
        return pivote is not None and (not pivote.no_resueltos or con_planeacion)
    if paso == estado.PASO_REPARTO:
        return st.session_state.get(estado.CLAVE_PLANEACION) is not None
    if paso == estado.PASO_EXPORTAR:
        return st.session_state.get(estado.CLAVE_ID_GUARDADA) is not None
    return False


def _navegacion_lateral(actual: str) -> None:
    """La lista de pasos como botones: el actual en azul marino, los completados
    con ✓ azul cielo y los pendientes en gris."""
    for indice, paso in enumerate(estado.PASOS):
        if paso == estado.PAGINA_CONFIGURACION:
            estilos.separador_dorado()
        etiqueta = paso
        if paso != actual and _paso_completado(paso):
            etiqueta = f":blue[✓] {paso}"
        st.button(
            etiqueta,
            key=f"nav_{indice}",
            type="primary" if paso == actual else "tertiary",
            width="stretch",
            on_click=estado.ir_a,
            args=(paso,),
        )


def _resumen_lateral() -> None:
    pivote: PivotePorZonaDTO | None = st.session_state.get(estado.CLAVE_PIVOTE)
    if pivote is None:
        st.caption("Sin archivo cargado todavía.")
        return
    st.caption("Resumen del día")
    estilos.fila_metricas(
        [
            estilos.tarjeta_metrica("📅", "Día", pivote.fecha.isoformat(), mini=True),
            estilos.tarjeta_metrica("📄", "Facturas", f"{pivote.total_facturas:,}", mini=True),
            estilos.tarjeta_metrica("👥", "Clientes", f"{pivote.total_clientes:,}", mini=True),
            estilos.tarjeta_metrica("💰", "Pesos", f"${pivote.total_pesos:,.0f}", mini=True),
        ]
    )


def main() -> None:
    logo = estilos.ruta_logo()
    if logo is not None:
        st.logo(str(logo), size="large")

    try:
        with conexion.errores_de_conexion():
            contenedor = _obtener_contenedor()
    except ValidationError:
        st.error(
            "Faltan las credenciales de la base de datos (SUPABASE_URL / SUPABASE_KEY). "
            "En local: copia `.env.example` a `.env` y pon las del proyecto (clave "
            "service_role). En Streamlit Cloud: configúralas en Settings → Secrets con el "
            "formato de `.streamlit/secrets.toml.example`."
        )
        st.stop()
        return

    st.session_state.setdefault(estado.CLAVE_PASO, estado.PASO_CARGAR)
    paso: str = st.session_state[estado.CLAVE_PASO]

    with st.sidebar:
        estilos.marca_lateral("Distribuciones Santiago")
        st.caption("Planeación logística diaria")
        # El plan gratuito de Render duerme la app tras 15 minutos sin uso y
        # tarda cerca de un minuto en despertar. No se arregla con código: lo
        # único honesto es avisarlo donde se ve antes de que alguien piense que
        # se colgó (ver README, "Limitaciones del plan gratuito").
        st.caption(":grey[La primera carga del día puede tardar un minuto.]")
        _navegacion_lateral(paso)
        estilos.separador_dorado()
        _resumen_lateral()

    pivote: PivotePorZonaDTO | None = st.session_state.get(estado.CLAVE_PIVOTE)
    detalle = f"día cargado: {pivote.fecha.isoformat()}" if pivote else "sin archivo cargado"
    estilos.encabezado_pagina("Planeación Logística", detalle)

    # Aviso no bloqueante: dos repositorios toleran que su tabla no exista y
    # devuelven vacío, así que sin esto una migración pendiente pasaría
    # inadvertida (ver web/diagnostico.py).
    with conexion.errores_de_conexion(detener=False, clave="diagnostico"):
        diagnostico.mostrar_aviso()

    # Un solo envoltorio para las cinco páginas (Configuración incluye sus cuatro
    # pestañas): si la base no responde, ninguna sigue dibujando con datos que no
    # llegaron. Ver web/conexion.py.
    with conexion.errores_de_conexion():
        if paso == estado.PASO_CARGAR:
            paso1_cargar.mostrar(contenedor)
        elif paso == estado.PASO_CLIENTES:
            paso2_clientes_nuevos.mostrar(contenedor)
        elif paso == estado.PASO_REPARTO:
            paso3_reparto.mostrar(contenedor)
        elif paso == estado.PASO_EXPORTAR:
            paso4_exportar.mostrar(contenedor)
        else:
            configuracion.mostrar(contenedor)


main()
