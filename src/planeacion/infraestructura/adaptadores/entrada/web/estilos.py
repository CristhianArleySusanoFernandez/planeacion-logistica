"""Identidad visual de la app: paleta de la empresa, CSS global y piezas HTML.

Solo presentación, cero lógica de negocio. Tres grupos de colores separados a
propósito: la MARCA es decorativa, el SEMÁFORO comunica estado (el dorado
jamás indica estado) y las SUPERFICIES cambian con el modo claro/oscuro que el
usuario elige en el menú ⋮ → Settings. Los selectores CSS son ``data-testid``
documentados de Streamlit o clases propias; nunca clases generadas (que
cambian entre versiones).
"""

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template

import streamlit as st

# ------------------------------------------------ paleta de MARCA (decorativa)
AZUL_MARINO = "#1B3C8F"  # principal: encabezados, botones
AZUL_CIELO = "#29A9E1"  # secundario: hover, acentos, barras
DORADO = "#F0A500"  # línea decorativa bajo los títulos, como el logo
TERRACOTA = "#C33C0E"  # detalles pequeños (NO es un color de error)

# --------------------------------------- semáforo (semántico: SOLO estado)
SEMAFORO_VERDE = "#16A34A"
SEMAFORO_AMBAR = "#D97706"
SEMAFORO_ROJO = "#DC2626"

# ----------------------- superficies: lo único que cambia entre claro y oscuro
_SUPERFICIES_CLARO: Mapping[str, str] = {
    "fondo_suave": "#F7F9FC",  # zebra de tablas, zona de arrastre
    "fondo_tarjeta": "#FFFFFF",
    "texto": "#1F2937",
    "texto_suave": "#6B7280",
    "borde": "#E5E7EB",
    "color_marca": AZUL_MARINO,  # títulos y valores KPI
    "hover_primario": AZUL_CIELO,
    "badge_verde_fondo": "#DCFCE7",
    "badge_verde_texto": "#15803D",
    "badge_ambar_fondo": "#FEF3C7",
    "badge_ambar_texto": "#B45309",
    "badge_rojo_fondo": "#FEE2E2",
    "badge_rojo_texto": "#B91C1C",
    "badge_info_fondo": "#E3F3FB",
    "badge_info_texto": AZUL_MARINO,
    "badge_neutro_fondo": "#F3F4F6",
    "badge_neutro_texto": "#4B5563",
}
_SUPERFICIES_OSCURO: Mapping[str, str] = {
    "fondo_suave": "#18202F",
    "fondo_tarjeta": "#1B2436",
    "texto": "#E5E7EB",
    "texto_suave": "#94A3B8",
    "borde": "#334155",
    "color_marca": AZUL_CIELO,  # el azul marino se pierde sobre fondo oscuro
    "hover_primario": "#53BCE7",
    "badge_verde_fondo": "rgba(34, 197, 94, .18)",
    "badge_verde_texto": "#4ADE80",
    "badge_ambar_fondo": "rgba(245, 158, 11, .18)",
    "badge_ambar_texto": "#FBBF24",
    "badge_rojo_fondo": "rgba(239, 68, 68, .18)",
    "badge_rojo_texto": "#F87171",
    "badge_info_fondo": "rgba(41, 169, 225, .18)",
    "badge_info_texto": "#7CCFF0",
    "badge_neutro_fondo": "#374151",
    "badge_neutro_texto": "#D1D5DB",
}

_RUTA_ASSETS = Path(__file__).parent / "assets"

_TONOS_BADGE = {
    "verde": "badge-verde",
    "ambar": "badge-ambar",
    "rojo": "badge-rojo",
    "info": "badge-info",
    "neutro": "badge-neutro",
}


@dataclass(frozen=True)
class Html:
    """Celda de ``tabla_marca`` que ya viene como HTML seguro (badges, puntos)."""

    contenido: str


def ruta_logo() -> Path | None:
    """El logo real de la empresa, si ya lo pusieron en ``web/assets/logo.png``."""
    ruta = _RUTA_ASSETS / "logo.png"
    return ruta if ruta.is_file() else None


_CSS_CRUDO = """
<style>
/* ---- limpieza: pie y decoración por defecto (el menú ⋮ queda: ahí está el tema) ---- */
footer { visibility: hidden; }
[data-testid="stDecoration"] { display: none; }

/* ---- encabezado de página con la línea dorada de la marca ---- */
.encabezado-marca {
  display: flex; align-items: baseline; gap: .6rem; flex-wrap: wrap;
  padding-bottom: .5rem; border-bottom: 3px solid $dorado; margin-bottom: 1rem;
}
.encabezado-marca .nombre { font-size: 1.55rem; font-weight: 700; color: $color_marca; }
.encabezado-marca .puntito { color: $terracota; font-weight: 700; }
.encabezado-marca .detalle { color: $texto_suave; font-size: .95rem; }

/* ---- títulos de sección con subrayado dorado corto ---- */
.titulo-seccion { font-size: 1.25rem; font-weight: 650; color: $texto; margin: .3rem 0 0 0; }
.titulo-seccion .linea-dorada {
  display: block; width: 52px; height: 3px; background: $dorado;
  border-radius: 2px; margin: .25rem 0 .5rem 0;
}

/* ---- texto secundario propio (leyendas) ---- */
.texto-suave { font-size: .8rem; color: $texto_suave; }

/* ---- marca en la sidebar y separador dorado ---- */
.marca-lateral { font-size: 1.05rem; font-weight: 700; color: $color_marca; }
.separador-dorado {
  border: none; height: 2px; margin: .7rem 0;
  background: linear-gradient(90deg, $dorado, transparent);
}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: .4rem; }

/* ---- tarjetas de métricas (KPI) ---- */
.fila-kpi { display: flex; gap: .7rem; flex-wrap: wrap; margin: .35rem 0 .6rem 0; }
.tarjeta-kpi {
  flex: 1 1 150px; background: $fondo_tarjeta; border: 1px solid $borde;
  border-radius: 10px; padding: .65rem .85rem;
  box-shadow: 0 1px 3px rgba(27, 60, 143, .08);
}
.tarjeta-kpi .etiqueta {
  font-size: .74rem; color: $texto_suave; text-transform: uppercase;
  letter-spacing: .04em; white-space: nowrap;
}
.tarjeta-kpi .valor { font-size: 1.3rem; font-weight: 700; color: $color_marca; }
.tarjeta-kpi .detalle { font-size: .78rem; color: $texto_suave; }
.tarjeta-kpi.mini { flex: 1 1 42%; padding: .4rem .6rem; }
.tarjeta-kpi.mini .valor { font-size: .98rem; }

/* ---- badges (estado con colores del semáforo; info con la marca) ---- */
.badge {
  display: inline-block; padding: .12rem .55rem; border-radius: 999px;
  font-size: .74rem; font-weight: 600; white-space: nowrap; vertical-align: middle;
}
.badge-verde { background: $badge_verde_fondo; color: $badge_verde_texto; }
.badge-ambar { background: $badge_ambar_fondo; color: $badge_ambar_texto; }
.badge-rojo { background: $badge_rojo_fondo; color: $badge_rojo_texto; }
.badge-info { background: $badge_info_fondo; color: $badge_info_texto; }
.badge-neutro { background: $badge_neutro_fondo; color: $badge_neutro_texto; }

/* ---- punto del semáforo ---- */
.punto-semaforo {
  display: inline-block; width: .68rem; height: .68rem; border-radius: 50%;
  margin-right: .38rem;
}

/* ---- tabla con estilo de la marca (solo lectura) ---- */
.contenedor-tabla { overflow-x: auto; margin: .25rem 0 .5rem 0; }
.tabla-marca { width: 100%; border-collapse: collapse; font-size: .85rem; }
.tabla-marca th {
  background: $marino; color: #FFFFFF; text-align: left; padding: .4rem .6rem;
  font-weight: 600; white-space: nowrap;
}
.tabla-marca th:first-child { border-top-left-radius: 8px; }
.tabla-marca th:last-child { border-top-right-radius: 8px; }
.tabla-marca td { padding: .35rem .6rem; border-bottom: 1px solid $borde; }
.tabla-marca tbody tr:nth-child(even) td { background: $fondo_suave; }
.tabla-marca th.num, .tabla-marca td.num {
  text-align: right; font-variant-numeric: tabular-nums;
}

/* ---- mini-barras para comparar carros ---- */
.barras-carros { display: flex; flex-direction: column; gap: .22rem; margin-top: .45rem; }
.barra-carro {
  display: flex; align-items: center; gap: .45rem;
  font-size: .74rem; color: $texto_suave;
}
.barra-carro .etiqueta-barra { min-width: 2.4rem; text-align: right; white-space: nowrap; }
.barra-carro .pista {
  flex: 1; background: $borde; border-radius: 4px; height: 8px; overflow: hidden;
}
.barra-carro .relleno { background: $cielo; height: 100%; border-radius: 4px; }

/* ---- encabezado azul marino de la card de un carro (igual en ambos modos) ---- */
.card-carro-encabezado {
  display: flex; justify-content: space-between; align-items: baseline;
  flex-wrap: wrap; gap: .4rem; background: $marino; color: #FFFFFF;
  border-radius: 8px; padding: .45rem .8rem; margin-bottom: .5rem;
}
.card-carro-encabezado .titulo { font-weight: 700; }
.card-carro-encabezado .metricas { font-size: .84rem; opacity: .92; }

/* ---- estado vacío amable (paso 2 sin pendientes) ---- */
.estado-vacio { text-align: center; padding: 1.6rem 1rem; }
.estado-vacio .icono {
  font-size: 2.4rem; font-weight: 700; color: $semaforo_verde; line-height: 1.1;
}
.estado-vacio .mensaje { font-size: 1.05rem; color: $texto; margin-top: .3rem; }

/* ---- botones: hover azul cielo; navegación de la sidebar ---- */
[data-testid="stBaseButton-primary"]:hover {
  background-color: $hover_primario !important; border-color: $hover_primario !important;
}
[data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"] {
  justify-content: flex-start; color: $texto;
}
[data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"]:hover { color: $cielo; }
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] { justify-content: flex-start; }

/* ---- tabs con el indicador azul cielo ---- */
[data-baseweb="tab-highlight"] { background-color: $cielo; }

/* ---- zona de arrastre del cargador de archivos, en español ---- */
[data-testid="stFileUploaderDropzone"] {
  border: 2px dashed $cielo; background: $fondo_suave; border-radius: 12px;
}
[data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
[data-testid="stFileUploaderDropzone"]::before {
  content: "⬆  Arrastra aquí el archivo de pedidos de ECOM (.xlsx)";
  color: $color_marca; font-weight: 600; margin-right: auto;
}
[data-testid="stFileUploaderDropzone"] button {
  visibility: hidden; position: relative; min-width: 9.5rem;
}
[data-testid="stFileUploaderDropzone"] button::after {
  content: "Buscar archivo"; visibility: visible; position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  border: 1px solid $color_marca; border-radius: 8px; color: $color_marca; font-weight: 600;
}

/* ---- sombra suave para las cards nativas (st.container(border=True)) ---- */
[data-testid="stVerticalBlockBorderWrapper"] {
  box-shadow: 0 1px 3px rgba(27, 60, 143, .06); border-radius: 10px;
}
</style>
"""


def _componer_css(superficies: Mapping[str, str]) -> str:
    return Template(_CSS_CRUDO).substitute(
        marino=AZUL_MARINO,
        cielo=AZUL_CIELO,
        dorado=DORADO,
        terracota=TERRACOTA,
        semaforo_verde=SEMAFORO_VERDE,
        **superficies,
    )


_CSS_CLARO = _componer_css(_SUPERFICIES_CLARO)
_CSS_OSCURO = _componer_css(_SUPERFICIES_OSCURO)


def aplicar_estilos() -> None:
    """Inyecta el CSS global según el modo activo (claro u oscuro). Llamar una
    sola vez al principio de ``app.py``: Streamlit vuelve a correr el script
    cuando el usuario cambia el tema, así que el CSS siempre acompaña al modo."""
    tema = getattr(st.context, "theme", None)
    oscuro = getattr(tema, "type", "light") == "dark"
    st.markdown(_CSS_OSCURO if oscuro else _CSS_CLARO, unsafe_allow_html=True)


# ------------------------------------------------------------ piezas de página


def encabezado_pagina(titulo: str, detalle: str | None = None) -> None:
    """Franja superior con el nombre de la app y la línea dorada de la marca."""
    extra = ""
    if detalle:
        extra = f'<span class="puntito">·</span><span class="detalle">{html.escape(detalle)}</span>'
    st.markdown(
        f'<div class="encabezado-marca"><span class="nombre">{html.escape(titulo)}</span>{extra}</div>',
        unsafe_allow_html=True,
    )


def titulo_seccion(texto: str) -> None:
    """Título de sección con el subrayado dorado corto (decorativo, como el logo)."""
    st.markdown(
        f'<div class="titulo-seccion">{html.escape(texto)}<span class="linea-dorada"></span></div>',
        unsafe_allow_html=True,
    )


def marca_lateral(nombre: str) -> None:
    """El nombre de la empresa arriba de la sidebar (con 🚚 si aún no hay logo)."""
    icono = "" if ruta_logo() else "🚚 "
    st.markdown(f'<div class="marca-lateral">{icono}{html.escape(nombre)}</div>', unsafe_allow_html=True)


def separador_dorado() -> None:
    st.markdown('<hr class="separador-dorado">', unsafe_allow_html=True)


def estado_vacio(icono: str, mensaje: str) -> None:
    """Mensaje grande y amable para pantallas sin nada pendiente."""
    st.markdown(
        f'<div class="estado-vacio"><div class="icono">{html.escape(icono)}</div>'
        f'<div class="mensaje">{html.escape(mensaje)}</div></div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------- piezas reutilizables


def tarjeta_metrica(
    icono: str, etiqueta: str, valor: str, detalle: str | None = None, mini: bool = False
) -> str:
    """Una tarjeta KPI; se agrupan con :func:`fila_metricas`."""
    clase = "tarjeta-kpi mini" if mini else "tarjeta-kpi"
    pie = f'<div class="detalle">{html.escape(detalle)}</div>' if detalle else ""
    return (
        f'<div class="{clase}"><div class="etiqueta">{html.escape(icono)} {html.escape(etiqueta)}</div>'
        f'<div class="valor">{html.escape(valor)}</div>{pie}</div>'
    )


def fila_metricas(tarjetas: Sequence[str]) -> None:
    st.markdown(f'<div class="fila-kpi">{"".join(tarjetas)}</div>', unsafe_allow_html=True)


def badge(texto: str, tono: str) -> str:
    """Etiqueta redondeada. Tonos: verde/ambar/rojo (estado), info (marca), neutro."""
    clase = _TONOS_BADGE[tono]
    return f'<span class="badge {clase}">{html.escape(texto)}</span>'


def color_semaforo(cv: float) -> str:
    """Verde < 10 %, ámbar 10–20 %, rojo > 20 %. Nunca colores de la marca."""
    if cv < 0.10:
        return SEMAFORO_VERDE
    if cv <= 0.20:
        return SEMAFORO_AMBAR
    return SEMAFORO_ROJO


def punto_semaforo(cv: float) -> str:
    return f'<span class="punto-semaforo" style="background:{color_semaforo(cv)}"></span>'


def punto_color(color: str) -> str:
    """Un punto suelto de un color dado (para leyendas)."""
    return f'<span class="punto-semaforo" style="background:{color}"></span>'


def tabla_marca(
    columnas: Sequence[str],
    filas: Sequence[Sequence[object]],
    numericas: Sequence[str] = (),
) -> None:
    """Tabla HTML de solo lectura con el encabezado azul marino de la marca.

    (``st.dataframe`` se dibuja en un canvas que el CSS no puede tocar; por eso
    las tablas de solo lectura son HTML propio.) Las celdas se escapan salvo que
    vengan envueltas en :class:`Html`; ``numericas`` alinea esas columnas a la
    derecha.
    """
    con_clase = [(nombre, ' class="num"' if nombre in numericas else "") for nombre in columnas]
    encabezado = "".join(f"<th{clase}>{html.escape(nombre)}</th>" for nombre, clase in con_clase)
    cuerpo = []
    for fila in filas:
        celdas = []
        for (_, clase), celda in zip(con_clase, fila, strict=True):
            contenido = celda.contenido if isinstance(celda, Html) else html.escape(str(celda))
            celdas.append(f"<td{clase}>{contenido}</td>")
        cuerpo.append(f"<tr>{''.join(celdas)}</tr>")
    st.markdown(
        f'<div class="contenedor-tabla"><table class="tabla-marca">'
        f"<thead><tr>{encabezado}</tr></thead><tbody>{''.join(cuerpo)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def barras_carros(items: Sequence[tuple[str, float]]) -> str:
    """Mini-barras horizontales para comparar la carga de los carros de un pool."""
    maximo = max((valor for _, valor in items), default=0.0)
    filas = []
    for etiqueta, valor in items:
        ancho = 0 if maximo <= 0 else round(valor / maximo * 100)
        filas.append(
            f'<div class="barra-carro"><span class="etiqueta-barra">{html.escape(etiqueta)}</span>'
            f'<div class="pista"><div class="relleno" style="width:{ancho}%"></div></div></div>'
        )
    return f'<div class="barras-carros">{"".join(filas)}</div>'
