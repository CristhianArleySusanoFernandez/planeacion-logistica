"""Paso 2 — Clientes nuevos (#N/D): la máquina sugiere zona, Rudy confirma."""

import html
from datetime import date
from pathlib import Path

import streamlit as st

from planeacion.application.dto.clientes_nuevos import ClientePendiente, SugerenciaDTO
from planeacion.application.dto.pivote import PivotePorZonaDTO
from planeacion.config.contenedor import (
    Contenedor,
    crear_generar_pivote,
    crear_resolver_clientes_nuevos,
)
from planeacion.domain.errores import ErrorDeDominio
from planeacion.domain.modelo import MotivoNoResuelto
from planeacion.infraestructura.adaptadores.entrada.web import datos, estado, estilos

_OPCION_MANUAL = "🔎 Asignar manualmente..."
_OPCION_OMITIR = "⏭ Omitir este cliente"
_MOTIVOS = {
    MotivoNoResuelto.NO_ESTA_EN_MAESTRA.value: "Cliente nuevo",
    MotivoNoResuelto.EN_MAESTRA_SIN_ZONA.value: "En la maestra, sin zona",
}


_CLAVE_MENSAJE = "mensaje_paso2"


def mostrar(contenedor: Contenedor) -> None:
    estilos.titulo_seccion("Paso 2 — Clientes nuevos")
    mensaje = st.session_state.pop(_CLAVE_MENSAJE, None)
    if mensaje:
        st.success(mensaje)
    pivote: PivotePorZonaDTO | None = st.session_state.get(estado.CLAVE_PIVOTE)
    if pivote is None:
        st.info("Primero carga el archivo de pedidos en el paso 1.")
        return

    if not pivote.no_resueltos:
        estilos.estado_vacio("✓", "Todos los clientes del día ya tienen zona asignada.")
        st.button(
            "Continuar →",
            type="primary",
            key="continuar_paso2",
            on_click=estado.ir_a,
            args=(estado.PASO_REPARTO,),
        )
        return

    pendientes = _obtener_pendientes(contenedor, pivote)
    st.caption(
        f"{len(pendientes)} clientes sin zona. La app sugiere una zona mirando a los vecinos "
        "de la misma ciudad y barrio; revisa cada sugerencia y confirma."
    )
    zonas_nombres = _zonas_nombres(contenedor)
    elecciones: dict[str, str | None] = {}
    for pendiente in pendientes:
        with st.container(border=True):
            elecciones[pendiente.codigo] = _fila_pendiente(pendiente, zonas_nombres)

    st.divider()
    col1, col2 = st.columns(2)
    if col1.button("✔ Confirmar todos", type="primary", key="confirmar_todos"):
        _confirmar(contenedor, pendientes, elecciones)
    col2.button(
        "Omitir y continuar →",
        key="omitir_continuar",
        on_click=_omitir_y_continuar,
    )


def _omitir_y_continuar() -> None:
    st.session_state.pop(estado.CLAVE_PENDIENTES, None)
    estado.ir_a(estado.PASO_REPARTO)


def _obtener_pendientes(contenedor: Contenedor, pivote: PivotePorZonaDTO) -> list[ClientePendiente]:
    pendientes: list[ClientePendiente] | None = st.session_state.get(estado.CLAVE_PENDIENTES)
    if pendientes is None:
        with st.spinner("Buscando vecinos en la maestra para sugerir zonas..."):
            pendientes = crear_resolver_clientes_nuevos(contenedor).pendientes(pivote.no_resueltos)
        st.session_state[estado.CLAVE_PENDIENTES] = pendientes
    return pendientes


def _zonas_nombres(contenedor: Contenedor) -> list[str]:
    nombres: list[str] | None = st.session_state.get("zonas_nombres")
    if nombres is None:
        nombres = [zona.nombre for zona in datos.zonas(contenedor)]
        st.session_state["zonas_nombres"] = nombres
    return nombres


def _badges_pendiente(pendiente: ClientePendiente) -> str:
    """El motivo (informativo) y de qué escalón salieron los vecinos."""
    partes = [estilos.badge(_MOTIVOS.get(pendiente.motivo, pendiente.motivo), "info")]
    sugerencia = pendiente.sugerencia
    if sugerencia is None:
        partes.append(estilos.badge("Sin sugerencia — asignar a mano", "neutro"))
    elif sugerencia.confianza == "barrio":
        partes.append(
            estilos.badge(f"Alta confianza — {sugerencia.total_vecinos} vecinos del barrio", "verde")
        )
    else:
        partes.append(estilos.badge(f"Solo por ciudad — {sugerencia.total_vecinos} vecinos", "ambar"))
    return " ".join(partes)


def _mostrar_opciones(sugerencia: SugerenciaDTO) -> None:
    """Las zonas candidatas con su respaldo, el nivel usado y vecinos de ejemplo.

    Se muestran las tres y no solo la ganadora porque el margen es parte de la
    decisión, y los vecinos con su dirección porque se reconoce la calle aunque
    no se reconozca el nombre de la zona.
    """
    st.caption(f"Vecinos encontrados por: {sugerencia.nivel}.")
    for puesto, opcion in enumerate(sugerencia.opciones, start=1):
        marca = "**" if puesto == 1 else ""
        st.markdown(
            f"{marca}{puesto}. {html.escape(opcion.zona)}{marca} &nbsp; "
            f'<span class="texto-suave">{opcion.vecinos} de {sugerencia.total_vecinos} vecinos '
            f"({opcion.porcentaje:.0%})</span>",
            unsafe_allow_html=True,
        )
        for vecino in opcion.ejemplos:
            st.markdown(
                f'<span class="texto-suave">&nbsp;&nbsp;&nbsp;· {html.escape(vecino.etiqueta)}</span>',
                unsafe_allow_html=True,
            )


def _fila_pendiente(pendiente: ClientePendiente, zonas_nombres: list[str]) -> str | None:
    """La card de un cliente. Devuelve la zona elegida o None si se omite."""
    nombre = pendiente.nombre or "sin nombre"
    st.markdown(
        f"**{html.escape(pendiente.codigo)} — {html.escape(nombre)}** &nbsp; {_badges_pendiente(pendiente)}",
        unsafe_allow_html=True,
    )
    ubicacion = " · ".join(dato for dato in (pendiente.ciudad, pendiente.barrio, pendiente.direccion) if dato)
    if ubicacion:
        st.caption(ubicacion)

    opciones: list[str] = []
    if pendiente.sugerencia is not None:
        _mostrar_opciones(pendiente.sugerencia)
        for opcion in pendiente.sugerencia.opciones:
            if opcion.zona not in opciones:
                opciones.append(opcion.zona)
    opciones.extend([_OPCION_MANUAL, _OPCION_OMITIR])

    eleccion = st.selectbox("Zona para este cliente", opciones, key=f"eleccion_{pendiente.codigo}")
    if eleccion == _OPCION_OMITIR:
        return None
    if eleccion != _OPCION_MANUAL:
        return eleccion

    texto = st.text_input("Buscar zona por texto", key=f"buscar_{pendiente.codigo}")
    clave = " ".join(texto.upper().split())
    coincidencias = [nombre for nombre in zonas_nombres if clave in nombre.upper()]
    if not coincidencias:
        st.caption("Ninguna zona coincide con la búsqueda.")
        return None
    zona: str = st.selectbox("Zona", coincidencias, key=f"manual_{pendiente.codigo}")
    return zona


def _confirmar(
    contenedor: Contenedor,
    pendientes: list[ClientePendiente],
    elecciones: dict[str, str | None],
) -> None:
    caso_uso = crear_resolver_clientes_nuevos(contenedor)
    confirmados, omitidos = 0, 0
    for pendiente in pendientes:
        zona = elecciones.get(pendiente.codigo)
        if zona is None:
            omitidos += 1
            continue
        try:
            caso_uso.confirmar_cliente(pendiente, zona)
            confirmados += 1
        except ErrorDeDominio as error:
            st.error(f"No se pudo confirmar el cliente {pendiente.codigo}: {error}")

    if confirmados:
        # La maestra cambió: se invalida su lectura y se re-pivotea, para que los
        # confirmados entren con su zona (el pivote lee la maestra de nuevo).
        datos.invalidar_clientes()
        ruta = Path(st.session_state[estado.CLAVE_RUTA_ECOM])
        pivote: PivotePorZonaDTO = st.session_state[estado.CLAVE_PIVOTE]
        fecha: date = pivote.fecha
        with st.spinner("Actualizando el resumen con las zonas confirmadas..."):
            st.session_state[estado.CLAVE_PIVOTE] = crear_generar_pivote(contenedor).ejecutar(
                ruta, fecha=fecha
            )
        estado.limpiar_resultados_posteriores()
        st.session_state[_CLAVE_MENSAJE] = (
            f"✓ {confirmados} cliente(s) confirmados y guardados. Omitidos: {omitidos}."
        )
        st.rerun()
    else:
        st.info("No se confirmó ningún cliente.")
