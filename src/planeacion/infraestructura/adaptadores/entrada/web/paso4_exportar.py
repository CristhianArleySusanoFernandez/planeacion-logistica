"""Paso 4 — Exportar el Excel para facturación y guardar la planeación en Supabase."""

import tempfile
from pathlib import Path

import streamlit as st

from planeacion.application.dto.planeacion import PlaneacionCompleta
from planeacion.config.contenedor import (
    Contenedor,
    crear_exportador_planeacion,
    crear_generar_planeacion,
)
from planeacion.infraestructura.adaptadores.entrada.web import estado, estilos

_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def mostrar(contenedor: Contenedor) -> None:
    estilos.titulo_seccion("Paso 4 — Exportar y guardar")
    planeacion: PlaneacionCompleta | None = st.session_state.get(estado.CLAVE_PLANEACION)
    if planeacion is None:
        st.info("Primero genera el reparto en el paso 3.")
        return

    _resumen_final(planeacion)
    col_excel, col_guardar = st.columns(2)
    with col_excel, st.container(border=True):
        _exportar_excel(planeacion)
    with col_guardar, st.container(border=True):
        _guardar(contenedor, planeacion)


def _resumen_final(planeacion: PlaneacionCompleta) -> None:
    carros_usados = sum(
        1 for cargas in planeacion.resultado.cargas_por_municipio.values() for carga in cargas if carga.zonas
    )
    estilos.fila_metricas(
        [
            estilos.tarjeta_metrica("📄", "Facturas", f"{planeacion.total_facturas:,}"),
            estilos.tarjeta_metrica("👥", "Clientes", f"{planeacion.total_clientes:,}"),
            estilos.tarjeta_metrica("🚚", "Carros con carga", str(carros_usados)),
            estilos.tarjeta_metrica("💰", "Pesos", f"${planeacion.total_pesos:,.0f}"),
        ]
    )
    if planeacion.no_resueltos:
        st.warning(
            f"Quedan {len(planeacion.no_resueltos)} clientes sin zona: saldrán como #N/A en la "
            "hoja ECOM. Puedes resolverlos en el paso 2 y regenerar el reparto."
        )


def _exportar_excel(planeacion: PlaneacionCompleta) -> None:
    estilos.titulo_seccion("Excel para facturación")
    st.caption("Genera el archivo con las hojas ECOM, PLANEACION, BASE y PEDIDOS.")
    nombre = f"planeacion_{planeacion.fecha.isoformat()}.xlsx"
    if st.button("📄 Generar el Excel", key="exportar_excel"):
        ruta = Path(tempfile.gettempdir()) / nombre
        with st.spinner("Generando las hojas ECOM, PLANEACION, BASE y PEDIDOS..."):
            crear_exportador_planeacion().exportar(planeacion, ruta)
        st.session_state[estado.CLAVE_EXCEL_EXPORTADO] = ruta.read_bytes()

    contenido: bytes | None = st.session_state.get(estado.CLAVE_EXCEL_EXPORTADO)
    if contenido is not None:
        st.download_button(
            "⬇ Descargar " + nombre,
            data=contenido,
            file_name=nombre,
            mime=_MIME_XLSX,
            key="descargar_excel",
            type="primary",
            width="stretch",
        )


def _guardar(contenedor: Contenedor, planeacion: PlaneacionCompleta) -> None:
    estilos.titulo_seccion("Guardar en la base de datos")
    id_guardada: int | None = st.session_state.get(estado.CLAVE_ID_GUARDADA)
    if id_guardada is not None:
        st.success(
            f"✓ Planeación del {planeacion.fecha.isoformat()} guardada (registro nº {id_guardada}). "
            f"La próxima planeación de un {planeacion.dia_semana} partirá de esta."
        )
        return
    st.caption("Nada se guarda sin este clic: la máquina propone, Rudy decide.")
    if st.button("💾 Guardar planeación", key="guardar_planeacion"):
        with st.spinner("Guardando la planeación..."):
            nuevo_id = crear_generar_planeacion(contenedor).guardar(planeacion)
        st.session_state[estado.CLAVE_ID_GUARDADA] = nuevo_id
        st.rerun()
