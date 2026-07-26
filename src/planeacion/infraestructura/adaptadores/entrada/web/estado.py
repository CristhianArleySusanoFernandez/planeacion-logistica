"""Claves de ``st.session_state`` y navegación entre pasos, en un solo lugar.

El estado (pivote, planeación viva, pendientes) sobrevive a los reruns de
Streamlit; cambiar de paso no recalcula nada.
"""

import streamlit as st

PASO_CARGAR = "1 · Cargar ECOM"
PASO_CLIENTES = "2 · Clientes nuevos"
PASO_REPARTO = "3 · Reparto de carros"
PASO_EXPORTAR = "4 · Exportar y guardar"
PAGINA_CONFIGURACION = "⚙ Configuración"
PASOS = (PASO_CARGAR, PASO_CLIENTES, PASO_REPARTO, PASO_EXPORTAR, PAGINA_CONFIGURACION)

CLAVE_PASO = "paso_actual"  # paso visible; lo escriben los botones de navegación vía ir_a
CLAVE_RUTA_ECOM = "ruta_ecom"  # ruta temporal del archivo subido
CLAVE_NOMBRE_ARCHIVO = "nombre_archivo"
CLAVE_PIVOTE = "pivote"  # PivotePorZonaDTO
CLAVE_PLANEACION = "planeacion"  # PlaneacionCompleta (dominio vivo: se muta al mover zonas)
CLAVE_PENDIENTES = "pendientes"  # list[ClientePendiente] del paso 2
CLAVE_ID_GUARDADA = "id_guardada"  # id en Supabase si ya se guardó
CLAVE_EXCEL_EXPORTADO = "excel_exportado"  # bytes del .xlsx generado
CLAVE_CONFIRMA_REGENERAR = "confirma_regenerar"


def ir_a(paso: str) -> None:
    """Navegación entre pasos: usar como ``on_click`` de un botón, para que el
    cambio quede escrito antes de que el rerun dibuje la página."""
    st.session_state[CLAVE_PASO] = paso


def limpiar_resultados_posteriores() -> None:
    """Al cargar otro archivo o confirmar clientes, lo derivado queda obsoleto."""
    for clave in (
        CLAVE_PLANEACION,
        CLAVE_PENDIENTES,
        CLAVE_ID_GUARDADA,
        CLAVE_EXCEL_EXPORTADO,
        CLAVE_CONFIRMA_REGENERAR,
    ):
        st.session_state.pop(clave, None)
