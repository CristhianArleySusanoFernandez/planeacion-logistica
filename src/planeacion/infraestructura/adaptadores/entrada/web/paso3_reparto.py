"""Paso 3 — Reparto de zonas a carros: revisar, mover zonas y ver el balance en vivo."""

import html
from pathlib import Path

import streamlit as st

from planeacion.application.dto.pivote import PivotePorZonaDTO
from planeacion.application.dto.planeacion import PlaneacionCompleta
from planeacion.config.contenedor import (
    Contenedor,
    crear_ajustar_asignacion,
    crear_generar_planeacion,
)
from planeacion.domain.errores import ErrorDeDominio, MovimientoInvalido
from planeacion.domain.modelo import (
    UMBRAL_CV_ACEPTABLE,
    UMBRAL_CV_ATENCION,
    CargaCarro,
    MetricasDesbalance,
    Parametros,
    clave_orden_carro,
)
from planeacion.domain.modelo.parametros import (
    CLAVE_MAX_FACTURAS_CONDUCTOR,
    CLAVE_MIN_CLIENTES_CONDUCTOR,
    CLAVE_VEHICULOS_REFERENCIA,
)
from planeacion.domain.servicios.agrupacion_por_conductor import agrupar_por_conductor
from planeacion.domain.servicios.alertas_operativas import (
    Alerta,
    alerta_de_promedio_por_vehiculo,
    alertas_de_conductores,
)
from planeacion.infraestructura.adaptadores.entrada.web import datos, estado, estilos


def mostrar(contenedor: Contenedor) -> None:
    estilos.titulo_seccion("Paso 3 — Reparto de carros")
    pivote: PivotePorZonaDTO | None = st.session_state.get(estado.CLAVE_PIVOTE)
    if pivote is None:
        st.info("Primero carga el archivo de pedidos en el paso 1.")
        return

    planeacion = _obtener_planeacion(contenedor, pivote)
    if planeacion is None:
        return
    resultado = planeacion.resultado

    if resultado.desde_historico:
        de_fecha = f" del {planeacion.fecha_previa.isoformat()}" if planeacion.fecha_previa else ""
        st.caption(f"📅 Parte de la planeación{de_fecha} (el mismo día de la semana anterior).")
    else:
        st.caption("No hay planeación previa de este día de semana: la app repartió desde cero.")

    if resultado.zonas_sin_carro:
        nombres = "  ·  ".join(
            f"{z.zona.nombre} ({z.clientes} clientes, ${z.pesos:,.0f})"
            for z in sorted(resultado.zonas_sin_carro, key=lambda z: z.zona.nombre)
        )
        st.warning(
            f"⚠ Estas zonas no tienen ningún carro que las pueda atender y quedaron "
            f"**sin asignar**: {nombres}. Para arreglarlo: agrégalas a un carro en "
            "Configuración → Zonas por carro y regenera el reparto."
        )

    _resumen_balance(resultado.metricas_iniciales, resultado.metricas_finales, resultado.cargas_por_municipio)

    _alertas_operativas(contenedor, resultado.cargas_por_municipio, planeacion.total_facturas)
    _resumen_por_conductor(resultado.cargas_por_municipio)

    municipios = sorted(resultado.cargas_por_municipio)
    for tab, municipio in zip(st.tabs(municipios), municipios, strict=True):
        with tab:
            _mostrar_municipio(municipio, resultado.cargas_por_municipio[municipio], planeacion)

    st.divider()
    col1, col2 = st.columns(2)
    if col1.button("🔄 Regenerar reparto", key="regenerar"):
        st.session_state[estado.CLAVE_CONFIRMA_REGENERAR] = True
    if st.session_state.get(estado.CLAVE_CONFIRMA_REGENERAR):
        st.warning("Esto descarta los ajustes manuales y vuelve a repartir desde cero.")
        col_si, col_no = st.columns(2)
        if col_si.button("Sí, regenerar", key="regenerar_si"):
            st.session_state.pop(estado.CLAVE_PLANEACION, None)
            st.session_state.pop(estado.CLAVE_EXCEL_EXPORTADO, None)
            st.session_state[estado.CLAVE_CONFIRMA_REGENERAR] = False
            st.rerun()
        if col_no.button("Cancelar", key="regenerar_no"):
            st.session_state[estado.CLAVE_CONFIRMA_REGENERAR] = False
            st.rerun()
    col2.button(
        "Continuar a exportación →",
        type="primary",
        key="continuar_paso3",
        on_click=estado.ir_a,
        args=(estado.PASO_EXPORTAR,),
    )


def _obtener_planeacion(contenedor: Contenedor, pivote: PivotePorZonaDTO) -> PlaneacionCompleta | None:
    planeacion: PlaneacionCompleta | None = st.session_state.get(estado.CLAVE_PLANEACION)
    if planeacion is None:
        ruta = Path(st.session_state[estado.CLAVE_RUTA_ECOM])
        with st.spinner("Repartiendo las zonas entre los carros de cada municipio..."):
            try:
                planeacion = crear_generar_planeacion(contenedor).ejecutar(ruta, fecha=pivote.fecha)
            except ErrorDeDominio as error:
                st.error(f"No se pudo generar el reparto: {error}")
                return None
        st.session_state[estado.CLAVE_PLANEACION] = planeacion
    return planeacion


def _tarjeta_municipio(
    municipio: str,
    inicial: MetricasDesbalance,
    final: MetricasDesbalance,
    cargas: list[CargaCarro],
) -> str:
    """Card de un municipio: punto del semáforo, CV antes → después y mini-barras
    con los pesos de cada carro (para ver de un vistazo qué tan parejo quedó)."""
    peor_cv = final.cv_peor
    barras = estilos.barras_carros([(f"C{c.carro.numero}", float(c.pesos)) for c in cargas if c.zonas])
    return (
        '<div class="tarjeta-kpi">'
        f'<div class="valor" style="font-size:1rem">{estilos.punto_semaforo(peor_cv)}'
        f"{html.escape(municipio)}</div>"
        f'<div class="detalle">Clientes: {inicial.cv_clientes:.0%} → <b>{final.cv_clientes:.0%}</b>'
        f" &nbsp;·&nbsp; Pesos: {inicial.cv_pesos:.0%} → <b>{final.cv_pesos:.0%}</b>"
        f" &nbsp;·&nbsp; Kilos: {inicial.cv_kilos:.0%} → <b>{final.cv_kilos:.0%}</b></div>"
        f"{barras}</div>"
    )


def _resumen_balance(
    iniciales: dict[str, MetricasDesbalance],
    finales: dict[str, MetricasDesbalance],
    cargas_por_municipio: dict[str, list[CargaCarro]],
) -> None:
    estilos.titulo_seccion("Balance por municipio")
    estilos.fila_metricas(
        [
            _tarjeta_municipio(municipio, iniciales[municipio], m, cargas_por_municipio[municipio])
            for municipio, m in sorted(finales.items())
        ]
    )
    # Los cortes se leen del dominio para que la leyenda no pueda mentirle a los colores.
    leyenda = (
        f"{estilos.punto_color(estilos.SEMAFORO_VERDE)}menos de {UMBRAL_CV_ACEPTABLE:.0%} &nbsp; "
        f"{estilos.punto_color(estilos.SEMAFORO_AMBAR)}{UMBRAL_CV_ACEPTABLE:.0%}–"
        f"{UMBRAL_CV_ATENCION:.0%} &nbsp; "
        f"{estilos.punto_color(estilos.SEMAFORO_ROJO)}más de {UMBRAL_CV_ATENCION:.0%}"
    )
    st.markdown(
        '<span class="texto-suave">CV = qué tan parejo quedó el reparto '
        "entre los carros (menor = mejor). El reparto se equilibra por <b>tres</b> variables "
        "—clientes, pesos y kilos— y <b>el color lo pone la peor de las tres</b>, no el promedio: "
        f"{leyenda}.</span>",
        unsafe_allow_html=True,
    )


def _alertas_operativas(
    contenedor: Contenedor, cargas_por_municipio: dict[str, list[CargaCarro]], total_facturas: int
) -> None:
    """Los indicadores que mira la jefatura, debajo del balance.

    Ninguno cambia el reparto: son metas, no reglas. La operación incumple el
    mínimo de clientes 19 veces en los 16 archivos de septiembre y octubre de
    2026, así que imponerlo rechazaría repartos que ellos hacen todas las semanas.
    """
    parametros = Parametros(valores=datos.parametros(contenedor))
    alertas: list[Alerta] = list(
        alertas_de_conductores(
            cargas_por_municipio,
            min_clientes=parametros.entero(CLAVE_MIN_CLIENTES_CONDUCTOR),
            max_facturas=parametros.entero(CLAVE_MAX_FACTURAS_CONDUCTOR),
        )
    )
    del_dia = alerta_de_promedio_por_vehiculo(
        total_facturas,
        vehiculos_referencia=parametros.entero(CLAVE_VEHICULOS_REFERENCIA),
        max_facturas=parametros.entero(CLAVE_MAX_FACTURAS_CONDUCTOR),
    )
    if del_dia is not None:
        alertas.append(del_dia)

    estilos.titulo_seccion("Alertas operativas")
    if not alertas:
        st.markdown(
            '<span class="texto-suave">Sin alertas: ningún conductor queda por debajo del '
            "mínimo de clientes ni por encima del máximo de facturas.</span>",
            unsafe_allow_html=True,
        )
        return
    for alerta in alertas:
        st.markdown(
            f"{estilos.badge('⚠ revisar', 'ambar')} {html.escape(alerta.texto)}",
            unsafe_allow_html=True,
        )
    st.markdown(
        '<span class="texto-suave">Son <b>metas, no reglas</b>: el reparto propuesto no se '
        "modifica por estas alertas. Los umbrales se editan en Configuración → Parámetros.</span>",
        unsafe_allow_html=True,
    )


def _resumen_por_conductor(cargas_por_municipio: dict[str, list[CargaCarro]]) -> None:
    """Lo mismo que el reparto, visto por quien maneja.

    El balanceador reparte por ruta, que es la unidad real, pero un conductor con
    dos rutas (`FABIAN 1` y `FABIAN 2`) puede tenerlas parejas entre sí y cargar
    el doble que el resto; en la tabla por ruta eso no se ve.
    """
    cargas = [carga for lista in cargas_por_municipio.values() for carga in lista]
    agrupadas = agrupar_por_conductor(cargas)
    if len(agrupadas) == len(cargas):
        return  # un conductor por ruta: la tabla no agregaría nada
    with st.expander(f"Resumen por conductor ({len(agrupadas)} conductores, {len(cargas)} rutas)"):
        estilos.tabla_marca(
            ["Conductor", "Rutas", "Facturas", "Clientes", "Pesos", "Kilos"],
            [
                [
                    grupo.conductor,
                    " + ".join(grupo.rutas),
                    f"{grupo.facturas:,}",
                    f"{grupo.clientes:,}",
                    f"${grupo.pesos:,.0f}",
                    f"{grupo.kilos:,.0f}",
                ]
                for grupo in agrupadas
            ],
            numericas=("Facturas", "Clientes", "Pesos", "Kilos"),
        )


def _mostrar_municipio(municipio: str, cargas: list[CargaCarro], planeacion: PlaneacionCompleta) -> None:
    for carga in cargas:
        _mostrar_carga(municipio, carga, cargas, planeacion)


def _encabezado_carro(carga: CargaCarro) -> str:
    conductor = f" — {carga.carro.conductor}" if carga.carro.conductor else ""
    titulo = f"🚚 Carro {carga.carro.numero}{conductor}"
    metricas = (
        f"👥 {carga.clientes} clientes &nbsp;·&nbsp; 💰 ${carga.pesos:,.0f} "
        f"&nbsp;·&nbsp; ⚖ {carga.kilos:,.0f} kg"
    )
    return (
        f'<div class="card-carro-encabezado"><span class="titulo">{html.escape(titulo)}</span>'
        f'<span class="metricas">{metricas}</span></div>'
    )


def _mostrar_carga(
    municipio: str, carga: CargaCarro, cargas: list[CargaCarro], planeacion: PlaneacionCompleta
) -> None:
    with st.container(border=True):
        st.markdown(_encabezado_carro(carga), unsafe_allow_html=True)
        if not carga.zonas:
            st.caption("Sin zonas asignadas hoy.")
            return
        estilos.tabla_marca(
            ["Zona", "Clientes", "Pesos", "Kilos", ""],
            [
                [
                    zona.zona.nombre,
                    zona.clientes,
                    f"${zona.pesos:,.0f}",
                    f"{zona.kilos:,.1f}",
                    estilos.Html(
                        estilos.badge("🔒 fija", "neutro") if zona.zona.regla_chiquinquira is not None else ""
                    ),
                ]
                for zona in sorted(carga.zonas, key=lambda z: z.zona.nombre)
            ],
            numericas=("Clientes", "Pesos", "Kilos"),
        )
        _controles_mover(municipio, carga, cargas, planeacion)


def _destinos_para(
    nombre_zona: str, origen: CargaCarro, cargas_municipio: list[CargaCarro], planeacion: PlaneacionCompleta
) -> list[str]:
    """Con repertorio configurado, solo los carros (de cualquier pool) que permiten
    la zona; sin repertorio, los del mismo municipio como siempre."""
    resultado = planeacion.resultado
    if resultado.repertorio:
        candidatas = [c for cargas in resultado.cargas_por_municipio.values() for c in cargas]
    else:
        candidatas = cargas_municipio
    numeros = [
        c.carro.numero
        for c in candidatas
        if c is not origen and resultado.carro_permite(c.carro.numero, nombre_zona)
    ]
    return sorted(numeros, key=clave_orden_carro)


def _controles_mover(
    municipio: str, carga: CargaCarro, cargas: list[CargaCarro], planeacion: PlaneacionCompleta
) -> None:
    movibles = sorted(zona.zona.nombre for zona in carga.zonas if zona.zona.regla_chiquinquira is None)
    if not movibles:
        return
    clave = f"{municipio}_{carga.carro.numero}"
    col1, col2, col3 = st.columns([4, 2, 1])
    zona_elegida = col1.selectbox("Mover la zona:", movibles, key=f"mover_zona_{clave}")
    destinos = _destinos_para(zona_elegida, carga, cargas, planeacion)
    if not destinos:
        col2.caption("Ningún otro carro tiene permitida esta zona (Configuración → Zonas por carro).")
        return
    destino = col2.selectbox("al carro:", destinos, key=f"mover_destino_{clave}")
    col3.markdown("&nbsp;")  # alinea el botón con los selectbox
    if col3.button("Mover", key=f"mover_boton_{clave}"):
        try:
            crear_ajustar_asignacion().ejecutar(planeacion.resultado, zona_elegida, destino)
        except MovimientoInvalido as error:
            st.error(str(error))
            return
        st.session_state.pop(estado.CLAVE_EXCEL_EXPORTADO, None)  # el Excel quedó obsoleto
        st.rerun()
