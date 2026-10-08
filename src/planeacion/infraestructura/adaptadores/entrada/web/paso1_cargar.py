"""Paso 1 — Cargar el ECOM crudo del día y ver el resumen del pivote."""

import tempfile
from pathlib import Path

import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile

from planeacion.application.dto.pivote import PivotePorZonaDTO
from planeacion.config.contenedor import Contenedor, crear_generar_pivote
from planeacion.domain.errores import ErrorDeDominio
from planeacion.infraestructura.adaptadores.entrada.web import estado, estilos
from planeacion.infraestructura.adaptadores.salida.excel.lector_ecom import (
    ColumnasEcomFaltantes,
    FormatoEcomInvalido,
)


def mostrar(contenedor: Contenedor) -> None:
    estilos.titulo_seccion("Paso 1 — Cargar los pedidos del día")
    archivo = st.file_uploader(
        "Archivo de pedidos de ECOM (.xlsx, .xlsm o .xls)",
        type=["xlsx", "xlsm", "xls"],
        label_visibility="collapsed",
    )
    if archivo is not None and st.session_state.get(estado.CLAVE_NOMBRE_ARCHIVO) != archivo.name:
        _procesar(contenedor, archivo)

    pivote: PivotePorZonaDTO | None = st.session_state.get(estado.CLAVE_PIVOTE)
    if pivote is None:
        st.info("Sube el archivo de pedidos para arrancar la planeación del día.")
        return

    estilos.titulo_seccion(f"Resumen del {pivote.fecha.isoformat()}")
    estilos.fila_metricas(
        [
            estilos.tarjeta_metrica("📅", "Fecha detectada", pivote.fecha.isoformat()),
            estilos.tarjeta_metrica("📄", "Facturas", f"{pivote.total_facturas:,}"),
            estilos.tarjeta_metrica("👥", "Clientes", f"{pivote.total_clientes:,}"),
            estilos.tarjeta_metrica("💰", "Pesos", f"${pivote.total_pesos:,.0f}"),
            estilos.tarjeta_metrica("⚖️", "Kilos", f"{pivote.total_kilos:,.0f}"),
        ]
    )

    if pivote.pedidos_excluidos_por_fecha:
        st.warning(
            f"El archivo traía **{pivote.pedidos_excluidos_por_fecha} pedidos de otro día** "
            f"(fecha {', '.join(pivote.fechas_excluidas)}) y se dejaron por fuera. No se "
            f"pierden: simplemente no entran a la planeación del {pivote.fecha.isoformat()}."
        )
    if pivote.lineas_kilos_excluidos:
        st.warning(
            f"⚖️ Se dejaron fuera **{pivote.kilos_excluidos:,.0f} kg** de "
            f"{len(pivote.lineas_kilos_excluidos)} línea(s) con el peso mal cargado en ECOM. "
            "Las facturas, los clientes y la plata de esos pedidos **sí cuentan**: lo único que "
            "no entra al reparto es ese peso, porque un producto con la ficha mal cargada "
            "decidiría solo el equilibrio del día. Conviene avisar para que corrijan la ficha."
        )
        with st.expander(f"Ver las {len(pivote.lineas_kilos_excluidos)} línea(s)"):
            estilos.tabla_marca(
                ["Pedido", "Cliente", "Cód. producto", "Producto", "Cantidad", "Kilos", "Motivo"],
                [
                    [
                        linea.pedido,
                        linea.nombre_cliente or linea.codigo_cliente,
                        linea.cod_producto or "—",
                        linea.producto or "—",
                        f"{linea.cantidad:,.0f}" if linea.cantidad is not None else "—",
                        f"{linea.kilos:,.1f}",
                        linea.motivo,
                    ]
                    for linea in pivote.lineas_kilos_excluidos
                ],
                numericas=("Cantidad", "Kilos"),
            )

    if pivote.no_resueltos:
        st.info(
            f"{len(pivote.no_resueltos)} clientes todavía no tienen zona asignada: "
            "en el paso 2 la app sugiere una para cada uno."
        )

    st.button(
        "Continuar →",
        type="primary",
        key="continuar_paso1",
        on_click=estado.ir_a,
        args=(estado.PASO_CLIENTES,),
    )


def _procesar(contenedor: Contenedor, archivo: UploadedFile) -> None:
    directorio = Path(tempfile.gettempdir()) / "planeacion_ecom"
    directorio.mkdir(exist_ok=True)
    ruta = directorio / archivo.name
    ruta.write_bytes(archivo.getvalue())

    with st.spinner("Leyendo el archivo y agrupando los pedidos por zona..."):
        try:
            pivote = crear_generar_pivote(contenedor).ejecutar(ruta)
        except ColumnasEcomFaltantes as error:
            st.error(str(error))  # el mensaje ya dice qué columnas faltan y qué trae el archivo
            return
        except (ErrorDeDominio, FormatoEcomInvalido) as error:
            st.error(f"No se pudo procesar el archivo: {error}. Revisa que sea el export de ECOM.")
            return

    st.session_state[estado.CLAVE_PIVOTE] = pivote
    st.session_state[estado.CLAVE_RUTA_ECOM] = str(ruta)
    st.session_state[estado.CLAVE_NOMBRE_ARCHIVO] = archivo.name
    estado.limpiar_resultados_posteriores()
