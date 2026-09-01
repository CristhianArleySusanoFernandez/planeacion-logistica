"""Configuración — administración de carros, zonas, repertorio, clientes, correcciones y overrides.

CRUD con ``st.data_editor`` dinámico: cada tab tiene filtro de texto, se pueden
agregar y borrar filas, y "Guardar cambios" persiste el diff (nuevas → insert,
editadas → update, eliminadas → delete con protección de referencias).
La excepción es "Zonas por carro": una matriz zonas × carros de casillas con
guardado automático por celda (lógica pura en ``repertorio_matriz``).
"""

from decimal import Decimal
from typing import Any

import streamlit as st

from planeacion.config.contenedor import Contenedor
from planeacion.domain.errores import ZonaInvalida
from planeacion.domain.modelo import (
    DIAS_LABORALES,
    Carro,
    Cliente,
    CorreccionUbicacion,
    Municipio,
    OverrideZona,
    ReglaChiquinquira,
    Zona,
)
from planeacion.domain.servicios.parseo_zonas import crear_zona
from planeacion.infraestructura.adaptadores.entrada.web import clientes_maestra, conexion, estilos
from planeacion.infraestructura.adaptadores.entrada.web.repertorio_matriz import (
    TODOS,
    FiltroMatriz,
    FrecuenciasDelDia,
    Repertorio,
    aplicar_cambios,
    cambios_desde_edicion,
    cambios_para_copiar,
    carros_visibles,
    contar_carros_de_zona,
    contar_sin_carro,
    frecuencias_del_dia,
    pares_sospechosos,
    resumen_de_frecuencias,
    zonas_visibles,
)
from planeacion.infraestructura.adaptadores.entrada.web.tablas import (
    Fila,
    calcular_diff,
    filtrar_filas,
    normalizar,
)

_REGLAS = [regla.value for regla in ReglaChiquinquira]
_SIN_CARRO = "⚠ sin carro"


def mostrar(contenedor: Contenedor) -> None:
    estilos.titulo_seccion("Configuración")
    st.caption("Los catálogos que usa la planeación. Los cambios quedan guardados de inmediato.")
    tab_carros, tab_zonas, tab_repertorio, tab_clientes, tab_correcciones, tab_overrides = st.tabs(
        ["Carros", "Zonas", "Zonas por carro", "Clientes", "Correcciones", "Overrides"]
    )
    with tab_carros, st.container(border=True):
        _tab_carros(contenedor)
    with tab_zonas, st.container(border=True):
        _tab_zonas(contenedor)
    with tab_repertorio, st.container(border=True):
        _tab_repertorio(contenedor)
    with tab_clientes, st.container(border=True):
        _tab_clientes(contenedor)
    with tab_correcciones, st.container(border=True):
        _tab_correcciones(contenedor)
    with tab_overrides, st.container(border=True):
        _tab_overrides(contenedor)


def _municipios(contenedor: Contenedor) -> list[str]:
    nombres: list[str] | None = st.session_state.get("municipios_nombres")
    if nombres is None:
        nombres = sorted(m.nombre for m in contenedor.municipios.listar())
        st.session_state["municipios_nombres"] = nombres
    return nombres


def _zonas_nombres(contenedor: Contenedor) -> list[str]:
    nombres: list[str] | None = st.session_state.get("zonas_nombres")
    if nombres is None:
        nombres = [zona.nombre for zona in contenedor.zonas.listar()]
        st.session_state["zonas_nombres"] = nombres
    return nombres


def _editor_con_filtro(clave: str, originales: list[Fila], **kwargs: Any) -> tuple[list[Fila], list[Fila]]:
    """Filtro de texto + editor dinámico. Devuelve (visibles, editadas): el diff
    del guardado se calcula contra las VISIBLES para que una fila oculta por el
    filtro nunca cuente como eliminada."""
    texto = st.text_input(
        "Filtrar...", key=f"filtro_{clave}", placeholder="Filtrar por cualquier columna de texto"
    )
    visibles = filtrar_filas(originales, texto)
    if texto.strip():
        st.caption(f"{len(visibles)} de {len(originales)} filas (el guardado aplica a las visibles).")
    # El key incluye el filtro: el estado del editor guarda ediciones por posición
    # de fila y quedaría corrupto si las filas cambian bajo el mismo key.
    editadas = st.data_editor(
        visibles,
        key=f"editor_{clave}_{texto.strip().lower()}",
        num_rows="dynamic",
        hide_index=True,
        **kwargs,
    )
    return visibles, list(editadas)


def _reportar_guardado(guardadas: int, eliminadas: int, errores: list[str]) -> None:
    for error in errores:
        st.error(error)
    st.success(f"{guardadas} fila(s) guardadas, {eliminadas} eliminadas.")


# ---------------------------------------------------------------- tab Carros


def _carro_desde_fila(fila: Fila) -> Carro:
    return Carro(
        numero=str(fila["numero"]).strip(),
        conductor=fila.get("conductor") or None,
        placa=fila.get("placa") or None,
        auxiliar=fila.get("auxiliar") or None,
        municipio=Municipio(fila["municipio"]) if fila.get("municipio") else None,
        es_externo=bool(fila.get("es_externo")),
        costo_diario=Decimal(str(fila.get("costo_diario") or 0)),
        activo=fila.get("activo") is not False,  # una fila nueva sin marcar nace activa
    )


def _tab_carros(contenedor: Contenedor) -> None:
    estilos.titulo_seccion("Flota de carros")
    st.caption(
        "Activa/desactiva carros y cambia su municipio: eso define el pool que usa el "
        "balanceador. El carro externo lleva `es_externo` y su `costo_diario`. Un carro "
        "con planeaciones guardadas no se puede borrar: desactívalo."
    )
    originales: list[Fila] = [
        {
            "numero": c.numero,
            "conductor": c.conductor,
            "placa": c.placa,
            "auxiliar": c.auxiliar,
            "municipio": c.municipio.nombre if c.municipio else None,
            "es_externo": c.es_externo,
            "costo_diario": float(c.costo_diario),
            "activo": c.activo,
        }
        for c in contenedor.carros.listar()
    ]
    visibles, editadas = _editor_con_filtro(
        "carros",
        originales,
        column_config={
            "numero": st.column_config.TextColumn("numero", required=True),
            "municipio": st.column_config.SelectboxColumn(
                "municipio", options=_municipios(contenedor), required=False
            ),
        },
    )
    if not st.button("Guardar cambios", key="guardar_carros"):
        return
    diff = calcular_diff(visibles, editadas, "numero")
    errores = [f"{len(diff.invalidas)} fila(s) sin numero: no se guardaron."] if diff.invalidas else []
    guardadas = 0
    for fila in diff.nuevas + diff.editadas:
        try:
            contenedor.carros.actualizar_carro(_carro_desde_fila(fila))
            guardadas += 1
        except LookupError as error:
            errores.append(str(error))
    eliminadas = 0
    for numero in diff.eliminadas:
        try:
            contenedor.carros.eliminar_carro(numero)
            eliminadas += 1
        except (LookupError, ValueError) as error:
            errores.append(str(error))
    _reportar_guardado(guardadas, eliminadas, errores)


# ----------------------------------------------------------------- tab Zonas


def _carros_que_atienden(contenedor: Contenedor) -> dict[str, str]:
    """Zona → 'números de carro que la tienen en su repertorio' (vista inversa).

    Se juntan los siete días a propósito: acá la pregunta es si la zona la atiende
    ALGUIEN alguna vez, porque una zona sin ningún carro en ningún día es la que
    queda huérfana. El detalle por día se edita en la matriz de "Zonas por carro".
    """
    atienden: dict[str, list[str]] = {}
    por_carro_por_dia = contenedor.carro_zonas.obtener_matriz()
    numeros_por_zona: dict[str, set[str]] = {}
    for por_carro in por_carro_por_dia.values():
        for numero, zonas in por_carro.items():
            for nombre in zonas:
                numeros_por_zona.setdefault(nombre, set()).add(numero)
    for nombre, numeros in numeros_por_zona.items():
        atienden[nombre] = sorted(numeros)
    return {
        nombre: ", ".join(sorted(numeros, key=lambda n: (len(n), n))) for nombre, numeros in atienden.items()
    }


def _zona_desde_fila(fila: Fila, es_nueva: bool) -> Zona:
    # Como la siembra: si la fila no trae municipio, se deriva del prefijo del
    # nombre (y para una fila nueva, también la regla de Chiquinquirá).
    base = crear_zona(str(fila["nombre"]))
    regla_cruda = fila.get("regla_chiquinquira")
    regla_derivada = base.regla_chiquinquira if es_nueva else None
    regla = ReglaChiquinquira(regla_cruda) if regla_cruda else regla_derivada
    return Zona(
        # El nombre siempre normalizado (también al editar una zona vieja): así una
        # variante con espacios de más nunca entra a la base como zona aparte.
        nombre=base.nombre,
        municipio=Municipio(fila["municipio"]) if fila.get("municipio") else base.municipio,
        regla_chiquinquira=regla,
        activa=fila.get("activa") is not False if es_nueva else bool(fila.get("activa")),
    )


def _tab_zonas(contenedor: Contenedor) -> None:
    estilos.titulo_seccion("Zonas de reparto")
    st.caption(
        "La regla de Chiquinquirá (SUR/NORTE) fija la zona a un carro y el balanceador no "
        "la mueve. La columna «carros» es la vista inversa del repertorio (solo lectura; "
        "se edita en el tab Zonas por carro): filtra por «sin carro» para ver las huérfanas. "
        "Una zona con clientes no se puede borrar: desactívala."
    )
    atienden = _carros_que_atienden(contenedor)
    originales: list[Fila] = [
        {
            "nombre": z.nombre,
            "municipio": z.municipio.nombre,
            "regla_chiquinquira": z.regla_chiquinquira.value if z.regla_chiquinquira else None,
            "activa": z.activa,
            "carros": atienden.get(z.nombre, _SIN_CARRO),
        }
        for z in contenedor.zonas.listar()
    ]
    visibles, editadas = _editor_con_filtro(
        "zonas",
        originales,
        column_config={
            "nombre": st.column_config.TextColumn("nombre", required=True),
            "municipio": st.column_config.SelectboxColumn(
                "municipio", options=_municipios(contenedor), required=False
            ),
            "regla_chiquinquira": st.column_config.SelectboxColumn(
                "regla_chiquinquira", options=_REGLAS, required=False
            ),
            "carros": st.column_config.TextColumn(
                "carros que la atienden", disabled=True, help="Se edita en «Zonas por carro»"
            ),
        },
    )
    if not st.button("Guardar cambios", key="guardar_zonas"):
        return
    diff = calcular_diff(visibles, editadas, "nombre")
    errores = [f"{len(diff.invalidas)} fila(s) sin nombre: no se guardaron."] if diff.invalidas else []
    guardadas = 0
    nuevas = {str(f["nombre"]).strip() for f in diff.nuevas}
    for fila in diff.nuevas + diff.editadas:
        try:
            zona = _zona_desde_fila(fila, es_nueva=str(fila["nombre"]).strip() in nuevas)
            contenedor.zonas.actualizar_zona(zona)
            guardadas += 1
        except (LookupError, ZonaInvalida) as error:
            errores.append(str(error))
    eliminadas = 0
    for nombre in diff.eliminadas:
        try:
            contenedor.zonas.eliminar_zona(nombre)
            eliminadas += 1
        except (LookupError, ValueError) as error:
            errores.append(str(error))
    st.session_state.pop("zonas_nombres", None)  # el catálogo cambió
    _reportar_guardado(guardadas, eliminadas, errores)


# ------------------------------------------------------- tab Zonas por carro


def _guardar_matriz(
    contenedor: Contenedor,
    clave_editor: str,
    orden_zonas: list[str],
    numeros_carros: list[str],
    dia_semana: str,
) -> None:
    """Callback del data_editor: persiste de una vez la(s) casilla(s) que cambiaron.

    Después de aplicar se cambia el nonce, lo que recrea el editor desde la base:
    así los cambios guardados quedan en los datos (no en el overlay de edición),
    una casilla fallida se revierte sola, y el estado posicional nunca se corrompe
    cuando una fila desaparece del filtro (ej. con «solo sin carro» activo).
    """
    estado_editor = st.session_state.get(clave_editor) or {}
    cambios = cambios_desde_edicion(estado_editor.get("edited_rows", {}), orden_zonas, set(numeros_carros))
    st.session_state["matriz_nonce"] = st.session_state.get("matriz_nonce", 0) + 1
    if not cambios:
        return
    # Este es un callback: corre fuera del cuerpo del script, así que el envoltorio
    # de app.py no lo alcanza y necesita el suyo. Sin ``st.stop()``, que acá no aplica.
    with conexion.errores_de_conexion(detener=False):
        errores = aplicar_cambios(contenedor.carro_zonas, cambios, dia_semana)
        if errores:
            st.session_state["matriz_errores"] = errores
        if len(cambios) > len(errores):
            st.toast("Guardado ✓")


def _copiar_de_otro_dia(
    contenedor: Contenedor,
    dia_destino: str,
    matriz: dict[str, dict[str, set[str]]],
) -> None:
    """Toma el repertorio de otro día como base para el que se está editando.

    La mayoría de los días se parecen entre sí, así que copiar y ajustar las pocas
    diferencias ahorra muchísimo trabajo. Reemplaza, no acumula: el día queda igual
    al de origen, altas y bajas incluidas. Por eso pide confirmación y muestra
    cuántas casillas va a mover antes de tocar nada.

    Recibe la matriz completa en vez de consultar el día de origen: Streamlit
    ejecuta el contenido del popover en cada rerun, esté abierto o cerrado, así
    que consultar acá sería una ida a la base por cada tecla en cualquier filtro.
    """
    otros = [d for d in DIAS_LABORALES if d != dia_destino]
    with st.popover(f"Copiar la configuración de otro día a {dia_destino}"):
        origen = st.selectbox("Copiar desde", otros, key="matriz_copiar_origen")
        cambios = cambios_para_copiar(matriz.get(origen, {}), matriz.get(dia_destino, {}))
        altas = sum(1 for c in cambios if c.marcado)
        if not cambios:
            st.caption(f"El {dia_destino} ya está igual que el {origen}: no hay nada que copiar.")
            return
        st.warning(
            f"El {dia_destino} va a quedar **igual** que el {origen}: "
            f"{altas} casilla(s) se marcan y {len(cambios) - altas} se desmarcan."
        )
        if st.button("Copiar", type="primary", key="matriz_copiar_confirmar"):
            errores = aplicar_cambios(contenedor.carro_zonas, cambios, dia_destino)
            st.session_state["matriz_errores"] = errores
            st.session_state["matriz_nonce"] = st.session_state.get("matriz_nonce", 0) + 1
            st.toast(f"{len(cambios) - len(errores)} casilla(s) copiadas de {origen} ✓")
            st.rerun()


def _revisar_sospechosos(filas: list[Zona], repertorio: Repertorio, frecuencias: FrecuenciasDelDia) -> None:
    """El panel de repaso: los pares vistos UNA sola vez en el histórico.

    Son los candidatos a borrar. La app no los quita sola —puede ser una regla
    real que solo se dio una vez en el período medido— pero los junta para que
    revisarlos sea un rato y no una cacería por la matriz.
    """
    sospechosos = pares_sospechosos(filas, repertorio, frecuencias)
    if not sospechosos:
        return
    st.markdown(
        estilos.badge(f"⚠ {len(sospechosos)} par(es) vistos una sola vez", "ambar"),
        unsafe_allow_html=True,
    )
    with st.expander("Revisar los pares vistos una sola vez"):
        st.caption(
            "Un par que aparece una única vez en todo el histórico suele ser un reemplazo "
            "de ese día (el conductor de siempre faltó), no una regla del negocio. "
            "Desmarcá en la matriz los que no correspondan."
        )
        estilos.tabla_marca(
            ["Zona", "Carro"],
            [[zona, numero] for zona, numero in sospechosos],
        )


def _tab_repertorio(contenedor: Contenedor) -> None:
    estilos.titulo_seccion("Zonas por carro (repertorio)")
    st.caption(
        "Marca en la matriz qué carros pueden atender cada zona: el balanceador solo "
        "asigna una zona a un carro que la tenga permitida. Cada casilla se guarda "
        "sola al marcarla, sin botón de guardar."
    )
    carros = [c for c in contenedor.carros.listar() if c.activo]
    if not carros:
        st.info("No hay carros activos en la base: siembra primero con planeacion-sembrar.")
        return
    zonas = [z for z in contenedor.zonas.listar() if z.activa]

    for error in st.session_state.pop("matriz_errores", []):
        st.error(error)

    col_dia, col_copiar = st.columns([1, 2], vertical_alignment="bottom")
    dia = col_dia.selectbox(
        "Día de la semana",
        DIAS_LABORALES,
        key="matriz_dia",
        help="El repertorio depende del día: la misma zona puede ir en un carro "
        "los martes y en otro los sábados.",
    )
    # Una sola lectura de la matriz completa por render: la usan el día en
    # pantalla y el popover de copiar, que Streamlit ejecuta aunque esté cerrado.
    matriz = contenedor.carro_zonas.obtener_matriz()
    repertorio = matriz.get(dia, {})
    with col_copiar:
        _copiar_de_otro_dia(contenedor, dia, matriz)

    frecuencias = frecuencias_del_dia(contenedor.carro_zonas.frecuencias(), dia)

    col_municipio, col_sin_carro, col_buscar = st.columns([2, 2, 3], vertical_alignment="bottom")
    municipio = col_municipio.selectbox(
        "Municipio", [*_municipios(contenedor), TODOS], key="matriz_municipio"
    )
    solo_sin_carro = col_sin_carro.checkbox(
        "Solo zonas sin carro",
        key="matriz_solo_sin_carro",
        help="La vista de trabajo: solo las zonas que ningún carro atiende. "
        "Van desapareciendo de la lista a medida que las asignas.",
    )
    texto = col_buscar.text_input("Buscar zona", key="matriz_buscar", placeholder="Nombre o parte del nombre")

    sin_carro, total = contar_sin_carro(zonas, repertorio)
    progreso = (
        estilos.badge(f"Zonas sin asignar: {sin_carro} de {total}", "ambar")
        if sin_carro
        else estilos.badge(f"✓ Las {total} zonas tienen carro asignado", "verde")
    )
    st.markdown(progreso, unsafe_allow_html=True)

    filtro = FiltroMatriz(municipio=municipio, solo_sin_carro=solo_sin_carro, texto=texto)
    filas = zonas_visibles(zonas, repertorio, filtro)
    if not filas:
        estilos.estado_vacio(
            "✓",
            "No hay zonas sin asignar en este filtro."
            if solo_sin_carro
            else "Ninguna zona coincide con este filtro.",
        )
        return

    columnas = carros_visibles(carros, filas, repertorio, municipio)
    orden_zonas = [z.nombre for z in filas]
    numeros = [c.numero for c in columnas]
    datos: list[Fila] = [
        {
            "zona": zona.nombre,
            **{numero: zona.nombre in repertorio.get(numero, set()) for numero in numeros},
            "n_carros": contar_carros_de_zona(zona.nombre, repertorio),
            "frecuencias": resumen_de_frecuencias(zona.nombre, repertorio, frecuencias),
        }
        for zona in filas
    ]
    # El nonce recrea el editor tras cada guardado (ver _guardar_matriz).
    nonce = st.session_state.setdefault("matriz_nonce", 0)
    clave_editor = f"matriz_{dia}_{municipio}_{int(solo_sin_carro)}_{normalizar(texto)}_{nonce}"
    st.data_editor(
        datos,
        key=clave_editor,
        hide_index=True,
        column_config={
            "zona": st.column_config.TextColumn("Zona", disabled=True, pinned=True),
            **{
                c.numero: st.column_config.CheckboxColumn(
                    c.numero,
                    help=f"{c.conductor or 'sin conductor'} — "
                    f"{c.municipio.nombre if c.municipio else 'sin municipio'}",
                    default=False,
                )
                for c in columnas
            },
            "n_carros": st.column_config.NumberColumn(
                "Nº de carros",
                disabled=True,
                help="Cuántos carros atienden la zona (0 = huérfana, sin nadie que la reparta).",
            ),
            "frecuencias": st.column_config.TextColumn(
                "Veces visto",
                disabled=True,
                help="Cuántas veces se observó cada par carro-zona ESE día en el histórico. "
                "«3×8» = el carro 3 lo hizo 8 veces. ⚠ marca la fila donde algún carro "
                "aparece una sola vez (probable reemplazo puntual, no una regla). "
                "0 = configurado a mano, nunca observado.",
            ),
        },
        on_change=_guardar_matriz,
        args=(contenedor, clave_editor, orden_zonas, numeros, dia),
    )
    st.caption(f"{len(filas)} zona(s) y {len(columnas)} carro(s) en la vista.")
    _revisar_sospechosos(filas, repertorio, frecuencias)

    with st.expander("Resumen por carro"):
        estilos.tabla_marca(
            ["Carro", "Conductor", "Municipio", "Zonas permitidas", ""],
            [
                [
                    c.numero,
                    c.conductor or "—",
                    c.municipio.nombre if c.municipio else "—",
                    len(repertorio.get(c.numero, set())) or "—",
                    estilos.Html(
                        "" if repertorio.get(c.numero) else estilos.badge("⚠ sin configurar", "ambar")
                    ),
                ]
                for c in sorted(carros, key=lambda c: (len(c.numero), c.numero))
            ],
            numericas=("Zonas permitidas",),
        )


# --------------------------------------------------------------- tab Clientes

_CLAVE_MAESTRA = "clientes_maestra"


def _maestra(contenedor: Contenedor) -> list[Cliente]:
    """La maestra completa, leída una sola vez por sesión.

    Son ~9.000 clientes. Se cachea acá y no se relee en cada rerun porque el
    filtrado es en Python (la búsqueda ignora acentos y PostgREST no sabe) y
    porque es exactamente la misma lectura que la planeación ya hace en cada
    corrida para armar el resolutor de zonas.
    """
    cache: list[Cliente] | None = st.session_state.get(_CLAVE_MAESTRA)
    if cache is None:
        cache = contenedor.clientes.listar()
        st.session_state[_CLAVE_MAESTRA] = cache
    return cache


def _filtro_clientes(contenedor: Contenedor) -> clientes_maestra.FiltroClientes:
    texto = st.text_input(
        "Buscar cliente",
        key="buscar_cliente",
        placeholder="Código, razón social o zona (no importan las tildes)",
    )
    columna_zona, columna_municipio, columna_inactivos = st.columns([2, 1, 1])
    zona = columna_zona.selectbox(
        "Zona",
        [clientes_maestra.TODOS, clientes_maestra.SIN_ZONA, *_zonas_nombres(contenedor)],
        key="filtro_zona_clientes",
    )
    municipio = columna_municipio.selectbox(
        "Municipio", [clientes_maestra.TODOS, *_municipios(contenedor)], key="filtro_municipio_clientes"
    )
    incluir_inactivos = columna_inactivos.checkbox(
        "Incluir inactivos", key="incluir_inactivos", help="Los desactivados no salen en la búsqueda."
    )
    return clientes_maestra.FiltroClientes(
        texto=texto, zona=zona, municipio=municipio, incluir_inactivos=incluir_inactivos
    )


def _tab_clientes(contenedor: Contenedor) -> None:
    estilos.titulo_seccion("Maestra de clientes")
    st.caption(
        "El cruce cliente → zona del que sale toda la planeación. Corregir acá la zona de un "
        "cliente cambia a qué carro va a caer desde el próximo pivote."
    )
    filtro = _filtro_clientes(contenedor)
    if not filtro.hay_criterio:
        st.info(
            f"La maestra tiene {len(_maestra(contenedor)):,} clientes: buscá uno o filtrá por "
            "zona o municipio para verlos."
        )
        return

    encontrados = clientes_maestra.filtrar_clientes(_maestra(contenedor), filtro)
    if not encontrados:
        estilos.estado_vacio("🔍", "Ningún cliente coincide con la búsqueda.")
        return

    total = clientes_maestra.total_paginas(len(encontrados))
    numero = 1
    if total > 1:
        numero = st.number_input("Página", min_value=1, max_value=total, step=1, key="pagina_clientes")
    visibles = clientes_maestra.pagina(encontrados, int(numero))
    st.caption(f"{len(encontrados):,} cliente(s) — página {numero} de {total}.")
    _editor_clientes(contenedor, visibles, filtro, int(numero))


def _editor_clientes(
    contenedor: Contenedor,
    visibles: list[Cliente],
    filtro: clientes_maestra.FiltroClientes,
    numero_pagina: int,
) -> None:
    # El key incluye filtro y página: el editor guarda las ediciones por posición
    # de fila y quedaría corrupto si las filas cambian bajo el mismo key.
    firma = f"{normalizar(filtro.texto)}_{filtro.zona}_{filtro.municipio}_{numero_pagina}"
    editadas = st.data_editor(
        [clientes_maestra.a_fila(cliente) for cliente in visibles],
        key=f"editor_clientes_{firma}",
        num_rows="fixed",  # los clientes nuevos se dan de alta en el paso 2, no acá
        hide_index=True,
        disabled=["codigo"],
        column_config={
            "codigo": st.column_config.TextColumn("Código"),
            "razon_social": st.column_config.TextColumn("Razón social"),
            "documento": st.column_config.TextColumn("Documento"),
            "ciudad": st.column_config.TextColumn("Ciudad"),
            "barrio": st.column_config.TextColumn("Barrio"),
            "direccion": st.column_config.TextColumn("Dirección"),
            "zona": st.column_config.SelectboxColumn(
                "Zona", options=["", *_zonas_nombres(contenedor)], help="En blanco = cliente sin zona."
            ),
            "activo": st.column_config.CheckboxColumn(
                "Activo", help="Desmarcar desactiva al cliente; no lo borra, para no perder historial."
            ),
        },
    )
    if not st.button("Guardar cambios", key="guardar_clientes"):
        return

    zonas = {zona.nombre: zona for zona in contenedor.zonas.listar()}
    try:
        resultado = clientes_maestra.aplicar_cambios(contenedor.clientes, visibles, list(editadas), zonas)
    except ZonaInvalida as zona_invalida:
        st.error(str(zona_invalida))
        return
    if resultado.guardados:
        st.session_state.pop(_CLAVE_MAESTRA, None)  # la caché quedó vieja
    for error in resultado.errores:
        st.error(error)
    # Nunca se borran clientes desde acá (se desactivan), así que no hay eliminadas.
    st.success(
        f"{resultado.guardados} cliente(s) guardados."
        if resultado.guardados
        else "No había cambios que guardar."
    )


# ----------------------------------------------------------- tab Correcciones


def _tab_correcciones(contenedor: Contenedor) -> None:
    estilos.titulo_seccion("Correcciones de ubicación")
    st.caption(
        "Correcciones de ubicación (la vieja hoja CAMBIOS): ciudad/barrio reales de los "
        "clientes que ECOM trae mal. Se aplican al sugerir zonas en el paso 2."
    )
    originales: list[Fila] = [
        {
            "cliente_codigo": c.cliente_codigo,
            "ciudad_real": c.ciudad_real,
            "barrio_real": c.barrio_real,
        }
        for c in contenedor.correcciones.listar()
    ]
    visibles, editadas = _editor_con_filtro("correcciones", originales)
    if not st.button("Guardar cambios", key="guardar_correcciones"):
        return
    diff = calcular_diff(visibles, editadas, "cliente_codigo")
    errores = (
        [f"{len(diff.invalidas)} fila(s) sin código de cliente: no se guardaron."] if diff.invalidas else []
    )
    guardadas = 0
    for fila in diff.nuevas + diff.editadas:
        contenedor.correcciones.guardar_correccion(
            CorreccionUbicacion(
                cliente_codigo=str(fila["cliente_codigo"]).strip(),
                ciudad_real=fila.get("ciudad_real") or None,
                barrio_real=fila.get("barrio_real") or None,
            )
        )
        guardadas += 1
    for codigo in diff.eliminadas:
        contenedor.correcciones.eliminar(codigo)
    _reportar_guardado(guardadas, len(diff.eliminadas), errores)


# -------------------------------------------------------------- tab Overrides


def _tab_overrides(contenedor: Contenedor) -> None:
    estilos.titulo_seccion("Overrides de zona")
    st.caption(
        "Overrides de zona (la vieja hoja `martha ojo`): fuerzan la zona de un cliente "
        "puntual por encima de la maestra."
    )
    originales: list[Fila] = [
        {"cliente_codigo": o.cliente_codigo, "zona_nombre": o.zona_nombre}
        for o in contenedor.overrides.listar()
    ]
    visibles, editadas = _editor_con_filtro(
        "overrides",
        originales,
        column_config={
            "zona_nombre": st.column_config.SelectboxColumn(
                "zona_nombre", options=_zonas_nombres(contenedor), required=True
            ),
        },
    )
    if not st.button("Guardar cambios", key="guardar_overrides"):
        return
    diff = calcular_diff(visibles, editadas, "cliente_codigo")
    errores = (
        [f"{len(diff.invalidas)} fila(s) sin código de cliente: no se guardaron."] if diff.invalidas else []
    )
    guardadas = 0
    for fila in diff.nuevas + diff.editadas:
        if not fila.get("zona_nombre"):
            errores.append(f"el override de {fila['cliente_codigo']} no tiene zona: no se guardó.")
            continue
        try:
            contenedor.overrides.guardar_override(
                OverrideZona(
                    cliente_codigo=str(fila["cliente_codigo"]).strip(),
                    zona_nombre=str(fila["zona_nombre"]),
                )
            )
            guardadas += 1
        except LookupError as error:
            errores.append(str(error))
    for codigo in diff.eliminadas:
        contenedor.overrides.eliminar(codigo)
    _reportar_guardado(guardadas, len(diff.eliminadas), errores)
