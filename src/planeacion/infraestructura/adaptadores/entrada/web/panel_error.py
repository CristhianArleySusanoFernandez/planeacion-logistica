"""El panel que ve la usuaria cuando algo falla: qué pasó, qué hacer y a dónde ir.

Uno solo para todos los fallos, para que la pantalla de un problema de base se
lea igual que la de un archivo equivocado y no haya que aprenderse dos formatos.

Reintentar **limpia el cache de lecturas** antes de volver a dibujar: sin eso, un
error que se arregló por fuera (el proyecto reactivado, la migración aplicada)
seguiría mostrándose hasta que venciera el TTL de cinco minutos, y el botón
parecería roto.
"""

import streamlit as st

from planeacion.infraestructura.adaptadores.entrada.web import datos, estilos
from planeacion.infraestructura.adaptadores.entrada.web.errores import ErrorUsuario


def mostrar(error: ErrorUsuario, *, clave: str = "") -> None:
    """Dibuja el panel. ``clave`` distingue los botones si hay más de uno en pantalla."""
    with st.container(border=True):
        estilos.titulo_seccion(f"⚠ {error.titulo}")
        st.write(error.que_paso)
        if error.que_hacer:
            st.markdown("**Qué hacer:**")
            for numero, paso in enumerate(error.que_hacer, start=1):
                st.markdown(f"{numero}. {paso}")

        columnas = st.columns(2)
        if error.enlace is not None:
            etiqueta, url = error.enlace
            # link_button abre en una pestaña nueva: la app no se pierde al salir.
            columnas[0].link_button(etiqueta, url)
        reintentar = error.reintentable and columnas[1].button(
            "🔄 Reintentar", key=f"reintentar_{error.codigo}_{clave}"
        )
        if reintentar:
            datos.invalidar_todo()
            st.rerun()
        # El código va chico y al final: no le dice nada a quien usa la app, pero
        # es lo que hace falta nombrar cuando llama a pedir ayuda.
        st.caption(f"Código del error: {error.codigo}")
